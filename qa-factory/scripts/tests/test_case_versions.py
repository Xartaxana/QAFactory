#!/usr/bin/env python3
"""Immutable version pinning: a later story must not rewrite an earlier story's facts.

The second half pins `--verify` and `--all` on a story with no case to check (SC5-12, SS1-14 item 4): no input without
cases prints `verified: true`, and the reason is a field of the answer, not words (FR-12)."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import case_versions as V  # noqa: E402
import contract as C  # noqa: E402
import check_delivery as D  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project  # noqa: E402


def write_case(path, title, task="QA-OLD", cid="TC-100"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {cid}\nstatus: Draft\ntask: {task}\n---\nRequirements: R-1\nPlan row: TS-1\n# {title}\n", encoding="utf-8")


def versions() -> None:
    with tempfile.TemporaryDirectory(prefix="qa-case-version-") as td:
        root = Path(td)
        store, source = root / "case-store", root / "authoring" / "TC-100.md"
        old, new = root / "artifacts" / "QA-OLD", root / "artifacts" / "QA-NEW"
        write_case(source, "original behaviour")
        first = V.create_version(store, source)
        V.pin(old, first)
        write_case(source, "changed behaviour")
        second = V.create_version(store, source)
        V.pin(new, second)
        old_case = C.case_index(old)["TC-100"]
        new_case = C.case_index(new)["TC-100"]
        check("different content produces immutable versions", first["version"] != second["version"])
        check("old story still reads original pinned content", "original behaviour" in old_case["path"].read_text(encoding="utf-8"))
        check("new story reads its own pinned version", "changed behaviour" in new_case["path"].read_text(encoding="utf-8"))
        check("case index exposes pinned version", old_case["version"] == first["version"])
        link = C.story_case_links(old)[0]
        check("story link points to a portable task snapshot", not Path(link["path"]).is_absolute()
              and (old / link["path"]).exists())
        pinned = old / link["path"]
        pinned.write_text("tampered", encoding="utf-8")
        check("modified immutable blob is reported as delivery issue", bool(C.case_link_issues(old)))
        check("delivery reader surfaces the dangling/stale version issue", bool(D.case_version_reasons(old)))


def story(project: Path, name: str) -> Path:
    root = project / "qa-factory" / "artifacts" / name
    (root / "work").mkdir(parents=True)
    (root / "pipeline.json").write_text("{}", encoding="utf-8")
    return root


def cli(project: Path, root: Path, *flags):
    return run_script("case_versions.py", "--task-root", root, *flags, cwd=project,
                      env=dict(os.environ, CLAUDE_PROJECT_DIR=str(project)))


def answer(run) -> dict:
    lines = [line for line in run.stdout.splitlines() if line.strip()]
    return json.loads(lines[-1]) if lines else {}


def empty_verify() -> None:
    project = temp_project("qa-case-verify-empty-")
    try:
        # B: nothing at all - the folder does not exist
        root = story(project, "TP3-1")
        run = cli(project, root, "--verify")
        check("verify_empty_story: exit 1", run.returncode == 1, run.stdout + run.stderr)
        check_eq("verify_empty_story: stdout is the declared shape", answer(run),
                 {"verified": False, "cases": 0, "reason": "no_cases"})
        check_in("verify_empty_story: the folders looked in are named", "test-cases", run.stderr)
        check_in("verify_empty_story: the id form is named", "TC-{nnn}", run.stderr)
        check_in("verify_empty_story: the door order is --all, then --verify",
                 "run --all after S4 wrote them, then --verify", run.stderr)
        # B': the folder exists and is empty; only README.md is red too
        folder = root / "work" / "test-cases"
        folder.mkdir(parents=True)
        check_eq("empty folder: exit 1", cli(project, root, "--verify").returncode, 1)
        (folder / "README.md").write_text("notes", encoding="utf-8")
        run = cli(project, root, "--verify")
        check("README.md only: exit 1, never verified", run.returncode == 1 and answer(run).get("verified") is False,
              run.stdout + run.stderr)
        (folder / "conventions.md").write_text("see TC_ naming and TP3-1", encoding="utf-8")
        run = cli(project, root, "--verify")
        check("README.md and conventions.md only: no_cases, not names_outside_form",
              run.returncode == 1 and answer(run).get("reason") == "no_cases", run.stdout + run.stderr)
        (folder / "conventions.md").unlink()
        (folder / "TP3-1-notes.md").write_text("x", encoding="utf-8")
        run = cli(project, root, "--verify")
        check("a name holding the story key but no TC_ counts: names_outside_form",
              answer(run).get("reason") == "names_outside_form", run.stdout + run.stderr)
        (folder / "TP3-1-notes.md").unlink()
        (folder / "README.md").unlink()
        # --cases-dir at a path that does not exist
        run = cli(project, root, "--verify", "--cases-dir", project / "nowhere")
        check("verify --cases-dir at a missing folder: exit 1, no_cases",
              run.returncode == 1 and answer(run).get("reason") == "no_cases", run.stdout + run.stderr)
        # C: a file outside the id form
        (folder / "ADD-TO-CART_TC_001.md").write_text("x", encoding="utf-8")
        run = cli(project, root, "--verify")
        check("verify_names_outside_form: exit 1 and the reason field", run.returncode == 1
              and answer(run) == {"verified": False, "cases": 0, "reason": "names_outside_form"}, run.stdout + run.stderr)
        check_in("verify_names_outside_form: the file name is in the text", "ADD-TO-CART_TC_001.md", run.stderr)
        check_in("verify_names_outside_form: the form is in the text", "TC-{nnn}", run.stderr)
        check_not_in("verify_names_outside_form: no 'more' for one name", " more", run.stderr)
        # the limit of 10 names: at 10 no `more`, at 11 `and 1 more`
        (folder / "ADD-TO-CART_TC_001.md").unlink()
        for number in range(10):
            (folder / f"ADD_TC_{number:02d}.md").write_text("x", encoding="utf-8")
        run = cli(project, root, "--verify")
        check("limit: 10 names are all listed", all(f"ADD_TC_{n:02d}.md" in run.stderr for n in range(10)), run.stderr)
        check_not_in("limit: 10 names carry no 'more'", " more", run.stderr)
        (folder / "ADD_TC_10.md").write_text("x", encoding="utf-8")
        run = cli(project, root, "--verify")
        check_in("limit: 11 names say `and 1 more`", "and 1 more", run.stderr)
        check_not_in("limit: the 11th name is cut", "ADD_TC_10.md", run.stderr)
        # a shared library holds only another story's files: red, and their names do not make the hint
        for path in folder.glob("ADD_TC_*.md"):
            path.unlink()
        library = project / "library"
        write_case(library / "TC-001.md", "alien", task="OTHER-9", cid="TC-001")
        (library / "alien-notes.md").write_text("---\ntask: OTHER-9\n---\n", encoding="utf-8")
        (library / "conventions.md").write_text("TC_ names", encoding="utf-8")
        (library / "README.md").write_text("TP3-1", encoding="utf-8")
        cfg = json.loads((project / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        cfg["cases_root"] = str(library)
        (project / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        C.case_config_reset()
        run = cli(project, root, "--verify")
        check("another story's library: exit 1, no_cases (their files are not ours)",
              run.returncode == 1 and answer(run).get("reason") == "no_cases", run.stdout + run.stderr)
        del cfg["cases_root"]
        (project / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        C.case_config_reset()
    finally:
        cleanup(project)


def pinned_stories() -> None:
    project = temp_project("qa-case-verify-pinned-")
    try:
        root = story(project, "TP3-2")
        case = root / "work" / "test-cases" / "TC-001.md"
        write_case(case, "login", task="TP3-2", cid="TC-001")
        # A: files, no version yet
        run = cli(project, root, "--verify")
        lines = run.stderr.splitlines()
        check("verify_no_versions: exit 1, no stdout", run.returncode == 1 and run.stdout.strip() == "", run.stdout + run.stderr)
        check_eq("verify_no_versions: the REJECT list opens with its own line",
                 lines[1] if len(lines) > 1 else "", "- no case of this story has a version yet; run --all")
        check_in("verify_no_versions: and still lists the case", "TC-001", "\n".join(lines[2:]))
        # E: control - one pinned case
        pin = cli(project, root, "--all")
        check("pin --all of one case: exit 0", pin.returncode == 0, pin.stdout + pin.stderr)
        run = cli(project, root, "--verify")
        check_eq("verify of one pinned case: cases 1", answer(run), {"verified": True, "cases": 1})
        check_eq("verify of one pinned case: exit 0", run.returncode, 0)
        # A2: a changed case is not pinned at its bytes, yet versions exist: no 'no version yet' line
        write_case(case, "login, changed", task="TP3-2", cid="TC-001")
        run = cli(project, root, "--verify")
        check("verify with a stale pin: exit 1 and the old text", run.returncode == 1
              and "not pinned at its current bytes" in run.stderr and "has a version yet" not in run.stderr, run.stderr)
        write_case(case, "login", task="TP3-2", cid="TC-001")
        # D: versions, no files
        case.unlink()
        run = cli(project, root, "--verify")
        check("verify_pins_without_files: exit 1, reason and pins", run.returncode == 1
              and answer(run) == {"verified": False, "cases": 0, "reason": "pins_without_files", "pins": 1},
              run.stdout + run.stderr)
        check_in("verify_pins_without_files: the text says what to do", "1 pinned versions have no case file on disk", run.stderr)
    finally:
        cleanup(project)


def empty_all() -> None:
    project = temp_project("qa-case-all-empty-")
    try:
        root = story(project, "TP3-3")
        links = root / "state" / "story-case-links.json"
        for flags in (("--all",), ("--cases-dir", project / "nowhere")):
            run = cli(project, root, *flags)
            label = "--all" if flags[0] == "--all" else "--cases-dir"
            check(f"{label} on no case: exit 1, the text, no stdout verdict",
                  run.returncode == 1 and "no case file found" in run.stderr and run.stdout.strip() == "",
                  f"rc {run.returncode}: {run.stdout}{run.stderr}")
            check(f"{label} on no case: nothing is written", not links.exists() and not (root / "state").exists())
        bare = cli(project, root)
        check("a bare call keeps the usage error (exit 2)", bare.returncode == 2 and "provide --case-file" in bare.stderr,
              f"rc {bare.returncode}: {bare.stderr[:200]}")
    finally:
        cleanup(project)


def pin_state_counts() -> None:
    """K6 (SC5-15): `pin_state` counts the case files it walked, and `unpinned` is its list."""
    project = temp_project("qa-case-pin-state-")
    try:
        root = story(project, "TP3-4")
        check_eq("no case folder: no cases, nothing unpinned", V.pin_state(root), {"cases": 0, "unpinned": []})
        for n in (1, 2):
            write_case(root / "work" / "test-cases" / f"TC-10{n}.md", f"case {n}", task="TP3-4", cid=f"TC-10{n}")
        state = V.pin_state(root)
        check_eq("two case files on disk: two cases", state["cases"], 2)
        check_eq("none of them pinned: two unpinned", len(state["unpinned"]), 2)
        check_eq("`unpinned` is the list of `pin_state`", V.unpinned(root), state["unpinned"])
    finally:
        cleanup(project)


def test_store_lock_busy_names_the_holder() -> None:
    """TR4-2 part B: the store lock is the package's one file lock. Busy = the old head + the holder clause (no holder is
    recorded in a tracked tree: the lock file stays one byte); broken = RuntimeError with the LockBroken sentence, never
    the busy head."""
    with tempfile.TemporaryDirectory(prefix="qa-case-lock-") as td:
        store = Path(td) / "case-store"
        with V.store_lock(store):
            try:
                with V.store_lock(store):
                    raise AssertionError("a second writer got the store lock")
            except RuntimeError as exc:
                text = str(exc)
        assert text.startswith("case version store has an active writer; "), text
        assert "no holder recorded - released when that process ends: wait and repeat" in text, text
        assert (store / ".case-versions.lock").read_bytes() == b"0", "a tracked-tree lock file carries only byte 0"
        with V.store_lock(store):                           # released: it can be taken again
            pass
        links = Path(td) / "task"
        with V.task_link_lock(links):
            try:
                with V.task_link_lock(links):
                    raise AssertionError("a second writer got the link lock")
            except RuntimeError as exc:
                assert str(exc).startswith("story case links have an active writer; no holder recorded"), str(exc)
        broken = Path(td) / "folder-store"
        (broken / ".case-versions.lock").mkdir(parents=True)  # a folder where the lock file should be
        try:
            with V.store_lock(broken):
                raise AssertionError("a folder at the lock path was taken as a lock")
        except RuntimeError as exc:
            text = str(exc)
        assert "cannot be locked" in text and "active writer" not in text, text


def main() -> int:
    test_store_lock_busy_names_the_holder()
    versions()
    empty_verify()
    pinned_stories()
    empty_all()
    pin_state_counts()
    finish("test_case_versions")


if __name__ == "__main__":
    main()
