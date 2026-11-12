"""test_bug_neighbours.py - the neighbourhood table of S7 (spec t-2187, node N6): groups by an equal value, never a verdict.

Run: python -B -m pytest -p no:cacheprovider scripts/tests/test_bug_neighbours.py -q      or      python -B scripts/tests/test_bug_neighbours.py

Each test builds its own temp story (run-report.json, automation-manifest.json, triage.json, case files, drafts). The Driver is stubbed the way
test_place_driver.py does it (`Driver.__new__`, the attributes the method reads). Fast: no role runs. Mutation -> killing test (one line each):
  the `seen` key stops squashing whitespace            -> test_seen_equal_after_squash_and_casefold
  `code_line` uses its own normaliser                  -> test_two_drafts_one_defect_location
  a failure, its row and its draft count as 3 units    -> test_a_failure_its_row_and_its_draft_are_one_unit
  `lines` forgets the count left out                   -> test_cut_at_the_limit_and_one_beyond
"""
import atexit
import contextlib
import io
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harness  # noqa: E402

import brief_pack  # noqa: E402
import bug_neighbours as BN  # noqa: E402
import bug_records as BR  # noqa: E402
import place_answers as PA  # noqa: E402
import story_run  # noqa: E402

ROOTS: list = []


def _cleanup_all() -> None:
    while ROOTS:
        harness.cleanup(ROOTS.pop())


atexit.register(_cleanup_all)


def story(report=None, manifest=None, triage=None, cases=None, drafts=None, raw=None) -> Path:
    """A temp story. `cases` {id: requirement line}; `drafts` {file name: draft object}; `raw` {work-relative name: text} for a broken file."""
    root = harness.temp_project()
    ROOTS.append(root)
    task = root / "qa-factory" / "artifacts" / "T-1"
    (task / "work").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": "T-1", "stages": {}}), encoding="utf-8")
    for name, data in (("run-report.json", report), ("automation-manifest.json", manifest), ("triage.json", triage)):
        if data is not None:
            (task / "work" / name).write_text(json.dumps(data), encoding="utf-8")
    for case, line in (cases or {}).items():
        folder = task / "work" / "test-cases"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{case}.md").write_text(f"---\nid: {case}\ntask: T-1\n---\nPlan row: TS-1\nRequirements: {line}\n", encoding="utf-8")
    for name, draft in (drafts or {}).items():
        (task / "work" / "bug-drafts").mkdir(parents=True, exist_ok=True)
        (task / "work" / "bug-drafts" / name).write_text(json.dumps(draft), encoding="utf-8")
    for name, text in (raw or {}).items():
        (task / "work" / name).write_text(text, encoding="utf-8")
    return task


def red(test: str, case: str = "", **more) -> dict:
    return dict({"instance_id": test, "test": test, "status": "failed", **({"case": case} if case else {})}, **more)


def manual(case: str, *seen, result="pass") -> dict:
    return {"case": case, "result": result, "attempt_id": "a1",
            "observations": [{"step": i + 1, "expected": "x", "seen": text, "evidence": "e", "quote": "q"} for i, text in enumerate(seen)]}


def groups(found: dict, key: str) -> list:
    return [g for g in found["groups"] if g["key"] == key]


def ids(group: dict) -> list:
    return [m["id"] for m in group["members"]]


def said(call):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = call()
    return result, [line for line in out.getvalue().splitlines() if line]


def tree(task: Path) -> list:
    return sorted((p.relative_to(task).as_posix(), p.stat().st_size) for p in task.rglob("*") if p.is_file())


# --- the keys -----------------------------------------------------------------------------------------------------------------------

def test_two_failures_of_one_case_are_one_case_group():
    task = story(report={"current_results": [red("t::a", "TC-001"), red("t::b", "TC-001"), red("t::c", "TC-002")]})
    found = BN.neighbours(task)
    got = groups(found, "case")
    assert len(got) == 1 and got[0]["value"] == "TC-001" and ids(got[0]) == ["t::a", "t::b"], found
    assert [g["key"] for g in found["groups"]] == ["case"], found


def test_case_and_test_file_through_the_manifest():
    task = story(report={"current_results": [red("t::a"), red("t::b"), red("u::c")]},
                 manifest={"tests": [{"instance_id": "t::a", "covers": ["TC-001"], "file": "tests\\t.py"},
                                     {"instance_id": "t::b", "covers": ["TC-002"], "file": "tests/t.py"},
                                     {"instance_id": "u::c", "covers": ["TC-003"], "file": "tests/u.py"}]})
    found = BN.neighbours(task)
    files = groups(found, "test_file")
    assert len(files) == 1 and files[0]["value"] == "tests/t.py" and ids(files[0]) == ["t::a", "t::b"], found
    assert groups(found, "case") == [], "three different cases"


def test_requirement_through_the_case_files():
    task = story(report={"current_results": [red("t::a", "TC-001"), red("t::b", "TC-002")]},
                 cases={"TC-001": "R-4", "TC-002": "R-4, R-5"})
    found = BN.neighbours(task)
    got = groups(found, "requirement")
    assert len(got) == 1 and got[0]["value"] == "R-4" and ids(got[0]) == ["t::a", "t::b"], found


def test_seen_equal_after_squash_and_casefold():
    task = story(report={"current_manual_checks": [manual("TC-001", "  The Cart   shows ONE "), manual("TC-002", "the cart shows one")]})
    found = BN.neighbours(task)
    got = groups(found, "seen")
    assert len(got) == 1 and got[0]["value"] == "the cart shows one", found
    assert [m["kind"] for m in got[0]["members"]] == ["observation", "observation"], found
    assert ids(got[0]) == ["TC-001#obs1", "TC-002#obs1"], found


def test_different_seen_is_no_group():
    task = story(report={"current_manual_checks": [manual("TC-001", "the cart shows one"), manual("TC-002", "the cart shows two")]})
    found = BN.neighbours(task)
    assert found["groups"] == [], found
    assert BN.lines(found) == [BN.NO_GROUP], BN.lines(found)


def test_two_drafts_one_defect_location():
    place = "src/pages/Book.tsx:164"
    task = story(drafts={"a.json": {"title": "a", "case": "TC-001", "defect_location": "src\\pages\\Book.tsx : 164"},
                         "b.json": {"title": "b", "case": "TC-002", "defect_location": place},
                         "c.json": {"title": "c", "case": "TC-003", "defect_location": "src/other.ts:9"}})
    found = BN.neighbours(task)
    got = groups(found, "code_line")
    assert len(got) == 1 and got[0]["value"] == BR.normalize_location("src\\pages\\Book.tsx : 164") == place, found
    assert ids(got[0]) == ["a.json", "b.json"] and {m["kind"] for m in got[0]["members"]} == {"draft"}, found


def test_a_basis_code_line_joins_the_same_group():
    mechanism = {"statement": "s", "status": "confirmed", "basis": [{"id": "b1", "kind": "code_line", "path": "src/pages/Book.tsx", "line": 164,
                                                                      "quote": "q"}]}
    task = story(drafts={"a.json": {"title": "a", "case": "TC-001", "defect_location": "src/pages/Book.tsx:164"},
                         "b.json": {"title": "b", "case": "TC-002", "mechanism": mechanism}})
    got = groups(BN.neighbours(task), "code_line")
    assert len(got) == 1 and got[0]["value"] == "src/pages/Book.tsx:164" and ids(got[0]) == ["a.json", "b.json"], got


def test_a_group_of_one_is_not_printed():
    task = story(report={"current_results": [red("t::a", "TC-001")]}, cases={"TC-001": "R-4"},
                 drafts={"a.json": {"title": "a", "case": "TC-009", "defect_location": "src/x.ts:1"}})
    found = BN.neighbours(task)
    assert found["groups"] == [] and BN.lines(found) == [BN.NO_GROUP], found


def test_a_failure_its_row_and_its_draft_are_one_unit():
    """A failure, the triage row that answers it and the draft that names it share a case and still are no neighbours of each other."""
    task = story(report={"current_results": [red("t::a", "TC-001")]},
                 triage={"triage": [{"instance_id": "t::a", "verdict": "APP_BUG", "evidence": "e"}]},
                 drafts={"a.json": {"title": "a", "case": "TC-001", "triage_ref": {"instance_id": "t::a", "attempt_id": ""}}})
    assert BN.neighbours(task)["groups"] == []
    task = story(report={"current_results": [red("t::a", "TC-001"), red("t::b", "TC-001")]},
                 triage={"triage": [{"instance_id": "t::a", "verdict": "APP_BUG", "evidence": "e"}]},
                 drafts={"a.json": {"title": "a", "case": "TC-001", "triage_ref": {"instance_id": "t::a", "attempt_id": ""}}})
    got = groups(BN.neighbours(task), "case")
    assert len(got) == 1 and [m["kind"] for m in got[0]["members"]] == ["failure", "failure", "row", "draft"], got


# --- empty, absent, unreadable ------------------------------------------------------------------------------------------------------

def test_nothing_to_compare_is_one_line_and_exit_zero():
    task = story()
    assert BN.lines(BN.neighbours(task)) == [BN.NOTHING]
    done = harness.run_script("bug_neighbours.py", "--task-root", task)
    assert done.returncode == 0 and done.stdout.splitlines() == [BN.NOTHING] and done.stderr == "", (done.stdout, done.stderr)


def test_unreadable_triage_is_named_not_an_empty_table():
    task = story(report={"current_results": [red("t::a", "TC-001"), red("t::b", "TC-002")]}, raw={"triage.json": "{not json"})
    found = BN.neighbours(task)
    assert [item[0] for item in found["unreadable"]] == ["work/triage.json"], found
    text = BN.lines(found)
    assert any(line.startswith("unreadable: work/triage.json") for line in text), text
    assert BN.NO_GROUP not in text and BN.NOTHING not in text, text


def test_unreadable_draft_is_named_and_groups_still_print():
    task = story(report={"current_results": [red("t::a", "TC-001"), red("t::b", "TC-001")]})
    (task / "work" / "bug-drafts").mkdir()
    (task / "work" / "bug-drafts" / "broken.json").write_text("[1, 2", encoding="utf-8")
    text = BN.lines(BN.neighbours(task))
    assert text[1].startswith("group case = TC-001: ") and any("unreadable: work/bug-drafts/broken.json" in line for line in text), text


def test_no_file_is_written():
    task = story(report={"current_results": [red("t::a", "TC-001"), red("t::b", "TC-001")]}, drafts={"a.json": {"title": "a", "case": "TC-001"}})
    before = tree(task)
    BN.neighbours(task)
    done = harness.run_script("bug_neighbours.py", "--task-root", task)
    harness.run_script("bug_neighbours.py", "--task-root", task, "--json")
    assert done.returncode == 0 and tree(task) == before, set(tree(task)) ^ set(before)


# --- the shape of the output and the limit --------------------------------------------------------------------------------------------

def fake(count: int) -> dict:
    return {"groups": [{"key": "case", "value": f"TC-{i:03d}", "members": [{"kind": "failure", "id": f"t::{i}a", "case": f"TC-{i:03d}"},
                                                                          {"kind": "failure", "id": f"t::{i}b", "case": f"TC-{i:03d}"}]}
                       for i in range(count)], "notes": [], "unreadable": []}


def test_cut_at_the_limit_and_one_beyond():
    at = BN.lines(fake(10), 10)
    assert len([x for x in at if x.startswith("group ")]) == 10 and not any(x.startswith("[and") for x in at), at
    beyond = BN.lines(fake(11), 10)
    assert len([x for x in beyond if x.startswith("group ")]) == 10 and beyond[-1] == "[and 1 more: bug_neighbours.py --task-root <task root>]", beyond
    assert "TC-010" not in " ".join(beyond), "the eleventh group is left out"
    assert BN.lines(fake(25), 10)[-1].startswith("[and 15 more:")


def test_the_text_has_a_stable_shape():
    task = story(report={"current_results": [red("t::a", "TC-001"), red("t::b", "TC-001")]})
    done = harness.run_script("bug_neighbours.py", "--task-root", task)
    assert done.stdout.splitlines() == [
        "Neighbours: 1 group of failures, observations, rows or drafts share one value (a hint, never a verdict: whether they are one cause is your judgment)",
        "group case = TC-001: failure t::a; failure t::b"], done.stdout
    one = harness.run_script("bug_neighbours.py", "--task-root", task, "--json")
    assert len(one.stdout.splitlines()) == 1 and json.loads(one.stdout)["groups"][0]["value"] == "TC-001", one.stdout


def test_the_words_never_judge():
    task = story(report={"current_results": [red("t::a", "TC-001"), red("t::b", "TC-001")]},
                 drafts={"a.json": {"title": "a", "case": "TC-001"}})
    text = " ".join(BN.lines(BN.neighbours(task))).casefold()
    for word in ("merge", "same bug", "root cause", "duplicate"):
        assert word not in text, word


def test_missing_story_is_refused_not_read_as_nothing():
    empty = harness.temp_dir()
    ROOTS.append(empty)
    done = harness.run_script("bug_neighbours.py", "--task-root", empty / "no-such-story")
    assert done.returncode == 2 and done.stdout == "", (done.returncode, done.stdout, done.stderr)


def test_help_exits_zero():
    done = harness.run_script("bug_neighbours.py", "--help")
    assert done.returncode == 0 and "--task-root" in done.stdout


# --- the hand-over: the driver's brief lines and the cards ---------------------------------------------------------------------------

def driver(task: Path):
    d = story_run.Driver.__new__(story_run.Driver)
    d.task_root, d.task, d.plugin = task, task.name, harness.PLUGIN_ROOT
    d.state = {}
    return d


def test_the_cap_is_a_data_row():
    data = json.loads(PA.DATA_PATH.read_text(encoding="utf-8"))
    assert isinstance(data["brief_neighbours_max"], int) and data["brief_neighbours_max"] >= 1, data.get("brief_neighbours_max")


def test_driver_lines_cut_at_the_data_row_and_name_the_command():
    task = story()
    cap = int(PA._data()["brief_neighbours_max"])
    original = BN.neighbours
    try:
        for count, left in ((cap, 0), (cap + 1, 1), (cap + 5, 5)):
            BN.neighbours = lambda root, n=count: fake(n)
            lines, printed = said(lambda: driver(task).s7_neighbour_lines(None))
            assert len([x for x in lines if x.startswith("group ")]) == cap, (count, lines)
            assert (f"[and {left} more: bug_neighbours.py --task-root <task root>]" in lines) == bool(left), (count, lines)
            assert "bug_neighbours.py" in lines[-1] and "--task-root qa-factory/artifacts/T-1/" in lines[-1] and printed == [], (lines[-1], printed)
    finally:
        BN.neighbours = original


def test_driver_says_when_the_table_is_not_whole():
    task = story(raw={"triage.json": "{not json"})
    lines, printed = said(lambda: driver(task).s7_neighbour_lines(None))
    assert any(x.startswith("unreadable: work/triage.json") for x in lines), lines
    assert len(printed) == 1 and "work/triage.json" in printed[0], printed
    original = BN.neighbours
    BN.neighbours = lambda root: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        lines, printed = said(lambda: driver(task).s7_neighbour_lines(None))
    finally:
        BN.neighbours = original
    assert "could not be computed whole (RuntimeError: boom)" in lines[0] and len(printed) == 1, (lines, printed)


def test_driver_lines_for_an_empty_story_say_nothing_was_found():
    lines, printed = said(lambda: driver(story()).s7_neighbour_lines(None))
    assert lines[0] == BN.NOTHING and printed == [], (lines, printed)


def test_the_two_cards_carry_the_command_the_charter_names():
    charter = (harness.PLUGIN_ROOT / "agents" / "qa-failure-analyst.md").read_text(encoding="utf-8")
    form = "bug_neighbours.py --task-root <task root>"
    assert form in charter, "the analyst's Tools line names the command"
    for role in ("qa-failure-analyst", "qa-doc-scribe"):
        mine = [line for line in brief_pack.TOOLING[role] if line.startswith(form)]
        assert len(mine) == 1 and mine[0].endswith("a hint, never a verdict"), (role, mine)
    assert not [line for role, card in brief_pack.TOOLING.items() if role not in ("qa-failure-analyst", "qa-doc-scribe")
                for line in card if "bug_neighbours" in line], "no other card carries it"


def main() -> int:
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn) and fn.__module__ == __name__]
    failed = 0
    try:
        for name, fn in tests:
            try:
                fn()
                print(f"PASS {name}")
            except Exception:                                                 # noqa: BLE001
                failed += 1
                print(f"FAIL {name}\n{traceback.format_exc()}")
    finally:
        _cleanup_all()
    print(f"test_bug_neighbours: {len(tests) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
