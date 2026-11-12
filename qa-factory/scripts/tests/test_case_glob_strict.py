"""A case id in a file name is matched STRICTLY, on every platform (t-911 / C4-13, after t-896 F-3).

`Path.rglob("TC-001.md")` matches `tc-001.md` on Windows (case-insensitive filesystem semantics) and does not on
Linux, so the same story found its case file on a developer's machine and lost it in CI. The decided class rule
(the Lead's, FR-16): where a case id is part of a file name the lookup is exact on every platform. Three sites look a
case file up by id - `s5_precheck.find_case_file`, `handoff_check._case_front_matter`, `judge_results._find_case_file` -
and all three go through `s5_precheck.case_files_named`.

The tree: `a/TC-001.md` (the exact file), `b/tc-001.md` (a lower-case twin in ANOTHER folder - two files differing only
by case cannot share a folder on Windows), `only-lower/tc-002.md` (the lower-case-only file), `x/TC-003.MD` (a wrong
suffix). The expected results are the same on Windows and on Linux; run it in docker (python:3.12) as well as on
Windows - on Windows alone the premise (the platform default finds the twin) is what the test fails on when a site goes
back to `rglob(f"{case}.md")`.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import s5_precheck as S5
import handoff_check as HC
import judge_results as JR
import dashboard_refresh as DR
from harness import temp_dir, temp_project, cleanup, check, check_eq, finish


def _tree(task: Path) -> None:
    base = task / "work" / "test-cases"
    for rel, body in (("a/TC-001.md", "---\ncovers: R-1\n---\n"), ("b/tc-001.md", "---\ncovers: R-9\n---\n"),
                      ("only-lower/tc-002.md", "---\ncovers: R-2\n---\n"), ("x/TC-003.MD", "---\ncovers: R-3\n---\n"),
                      ("a/TC-0010.md", "---\ncovers: R-10\n---\n")):
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    (task / "other").mkdir()
    (task / "other" / "TC-005.md").write_text("x", encoding="utf-8")


def _rel(task: Path, path) -> str:
    return "None" if path is None else path.relative_to(task).as_posix()


def _dashboard_inputs(project: Path) -> list:
    """The files `dashboard_refresh` hashes: `content_hash` is swapped for the identity so the receipt carries them."""
    stub = SimpleNamespace(main=lambda argv=None: 0)
    sys.modules["factory_dashboard"] = stub
    real = DR.content_hash
    DR.content_hash = lambda value: value
    try:
        receipt = DR.refresh_project(project)
    finally:
        DR.content_hash = real
        del sys.modules["factory_dashboard"]
    return [name for name, _ in receipt["input_hash"][0]]


def _under(root: Path, path) -> str:
    """`_rel` for a path that may spell the root differently (Windows 8.3 `DEV2~1` against the long name)."""
    return "None" if path is None else Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def _store(root: Path, files: dict) -> Path:
    """A project whose config keeps its cases in `<root>/cases` (`cases_root`): {relative path: case id}. Every file
    is the story QA-9's own (`task:`), and its NAME carries a slug after the id, so no exact `<id>.md` exists."""
    config = root / "qa-factory" / "config.json"
    data = json.loads(config.read_text(encoding="utf-8"))
    data["cases_root"] = "cases"
    config.write_text(json.dumps(data), encoding="utf-8")
    task = root / "qa-factory" / "artifacts" / "QA-9"
    (task / "work").mkdir(parents=True, exist_ok=True)
    for rel, cid in files.items():
        target = root / "cases" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"---\nid: {cid}\ntask: QA-9\n---\n# {cid}\n## Then\n1. a\n2. b\n", encoding="utf-8")
    return task


def index_fallback_and_roots() -> None:
    """EP1-38 item 1-2: `find_case_file` asks the strict name search FIRST and, only when it finds nothing, the story's
    case index (the project's own case store); `case_search_roots` is what a refusal says it looked under."""
    root = temp_project("ep138-store-")
    try:
        task = _store(root, {"cart/TC-001-add-to-cart.md": "TC-001"})
        check_eq("EP1-38: a case file named `<id>-<slug>.md` in the project's store is found through the index",
                 _under(root,S5.find_case_file(task, "TC-001")), "cases/cart/TC-001-add-to-cart.md")
        check_eq("EP1-38: the id is exact - `tc-001` is not `TC-001` on any platform", S5.find_case_file(task, "tc-001"), None)
        check_eq("EP1-38: an id the store does not hold is None", S5.find_case_file(task, "TC-002"), None)
        roots = [_under(root,r) for r in S5.case_search_roots(task)]
        check_eq("EP1-38: the roots are the story's work/test-cases, the story, the project's store - in that order",
                 roots, ["qa-factory/artifacts/QA-9/work/test-cases", "qa-factory/artifacts/QA-9", "cases"])
        strict = task / "work" / "test-cases" / "TC-001.md"
        strict.parent.mkdir(parents=True, exist_ok=True)
        strict.write_text("---\nid: TC-001\ntask: QA-9\n---\n# strict\n", encoding="utf-8")
        check_eq("EP1-38: the strict name search comes FIRST: the file that was found is still the one found",
                 _under(root,S5.find_case_file(task, "TC-001")), "qa-factory/artifacts/QA-9/work/test-cases/TC-001.md")
        strict.unlink()
        twin = root / "cases" / "other" / "TC-001-twin.md"
        twin.parent.mkdir(parents=True)
        twin.write_text("---\nid: TC-001\ntask: QA-9\n---\n# twin\n", encoding="utf-8")
        check_eq("EP1-38: two areas hold the bare id -> no single file (a Then of the other area must not answer)",
                 S5.find_case_file(task, "TC-001"), None)
        twin.unlink()
        check_eq("EP1-38: ... and with the twin gone the one file is found again",
                 _under(root,S5.find_case_file(task, "TC-001")), "cases/cart/TC-001-add-to-cart.md")
        (root / "cases" / "cart" / "TC-001-copy.md").write_text(
            "---\nid: TC-001\ntask: QA-9\n---\n# the same area and identity, another text\n", encoding="utf-8")
        check_eq("EP1-38: an index that raises (an identity collision) is None, not an exception",
                 S5.find_case_file(task, "TC-001"), None)
    finally:
        cleanup(root)
    bare = temp_dir()
    try:
        check_eq("EP1-38: no config, an empty story: the two roots every search always had, no repeats",
                 [_under(bare, r) for r in S5.case_search_roots(bare)][:2], ["work/test-cases", "."])
        check_eq("EP1-38: an empty story finds nothing and does not raise", S5.find_case_file(bare, "TC-001"), None)
    finally:
        cleanup(bare)


def main() -> None:
    index_fallback_and_roots()
    task = temp_dir()
    try:
        _tree(task)
        base = task / "work" / "test-cases"

        # --- the shared lookup ---
        check_eq("the exact name is found; the lower-case twin in another folder is not",
                 [_rel(task, p) for p in S5.case_files_named(base, "TC-001")], ["work/test-cases/a/TC-001.md"])
        check_eq("a lower-case-only file is NOT found for the upper-case id (the platform default found it on Windows)",
                 S5.case_files_named(base, "TC-002"), [])
        check_eq("the lower-case id finds the lower-case file", [p.name for p in S5.case_files_named(base, "tc-002")],
                 ["tc-002.md"])
        check_eq("the suffix is exact too: TC-003.MD is no case file", S5.case_files_named(base, "TC-003"), [])
        check_eq("an id that is only a prefix of another name is not an exact match",
                 [p.name for p in S5.case_files_named(base, "TC-001")], ["TC-001.md"])
        check_eq("prefix=True: TC-001 takes TC-001.md and TC-0010.md (as the old `TC-001*.md`), not tc-001.md",
                 [p.name for p in S5.case_files_named(base, "TC-001", prefix=True)], ["TC-001.md", "TC-0010.md"])
        check_eq("prefix=True: an id with nothing after it needs the full `.md` (no `TC-001.m`)",
                 S5.case_files_named(base, "TC-001.m", prefix=True), [])
        check_eq("an id with glob metacharacters is a literal name, not a pattern",
                 S5.case_files_named(base, "TC-0*"), [])
        check_eq("an absent root's walk is empty, not an error", S5.case_files_named(base / "nowhere", "TC-001"), [])

        # --- the three sites ---
        check_eq("s5_precheck.find_case_file: the exact file", _rel(task, S5.find_case_file(task, "TC-001")),
                 "work/test-cases/a/TC-001.md")
        check_eq("s5_precheck.find_case_file: a lower-case-only file is not found (zero -> None, as before)",
                 S5.find_case_file(task, "TC-002"), None)
        check_eq("s5_precheck.find_case_file: the task-root fallback finds the exact name",
                 _rel(task, S5.find_case_file(task, "TC-005")), "other/TC-005.md")
        check_eq("s5_precheck.find_case_file: the task-root fallback is strict too (tc-005 is not TC-005.md)",
                 S5.find_case_file(task, "tc-005"), None)

        art = SimpleNamespace(root=task)
        check_eq("handoff_check._case_front_matter: the exact file's own front matter, not the twin's",
                 HC._case_front_matter(art, "TC-001"), {"covers": "R-1"})
        check_eq("handoff_check._case_front_matter: a lower-case-only file gives {} (zero -> {}, as before)",
                 HC._case_front_matter(art, "TC-002"), {})

        check_eq("judge_results._find_case_file: the exact file (its stem is the id), not the twin or TC-0010",
                 _rel(task, JR._find_case_file(task, "TC-001")), "work/test-cases/a/TC-001.md")
        check_eq("judge_results._find_case_file: a lower-case-only file is not found (zero -> None, as before)",
                 JR._find_case_file(task, "TC-002"), None)
        check_eq("judge_results._find_case_file: an empty id is None", JR._find_case_file(task, ""), None)
    finally:
        cleanup(task)

    # --- dashboard_refresh: `seen` is "the same file through two roots", not an id lookup ---
    project = temp_dir()
    try:
        factory = project / "qa-factory"
        (factory / "cases").mkdir(parents=True)
        (factory / "config.json").write_text('{"cases_root": "qa-factory/cases"}', encoding="utf-8")
        (factory / "cases" / "TC-001.md").write_text("x", encoding="utf-8")
        (factory / "notes.md").write_text("y", encoding="utf-8")
        inputs = _dashboard_inputs(project)
        check_eq("dashboard_refresh: a file under two overlapping roots (qa-factory and cases_root) is hashed once",
                 sorted(Path(n).name for n in inputs), ["TC-001.md", "config.json", "notes.md"])
        check("dashboard_refresh: no input appears twice", len(inputs) == len(set(inputs)), str(inputs))
    finally:
        cleanup(project)
    finish("test_case_glob_strict")


if __name__ == "__main__":
    main()
