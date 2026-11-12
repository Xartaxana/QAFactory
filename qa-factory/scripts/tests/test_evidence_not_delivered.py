"""OH3-33: the evidence of a story is generated, git ignores it, and it is never in the delivery commit.

Owner, 29.10.2026: the screenshots are for the tester, they do not go into the repository. One declaration
(`install-paths.json`: `gitignore_block.inside_tracked` and two `carried`/`machine_local` rows), one derived
block, one manifest that lists none of it, one door for an old manifest, one `git rm --cached` line for what an
older install already committed. The git answers here come from the REAL `git check-ignore` and a real `git add`,
not from a matcher of our own (a second matcher would only prove itself).

Run: python -B scripts/tests/test_evidence_not_delivered.py
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

import artifact_registry  # noqa: E402
import check_delivery as D  # noqa: E402
import delivery_manifest as M  # noqa: E402
import install_paths as I  # noqa: E402
import manual_evidence  # noqa: E402
import onboard_apply as OA  # noqa: E402
import project_gitignore as G  # noqa: E402

TASK = "qa-factory/artifacts/T-1"

IGNORED = ("evidence/runs/x/r.json", "evidence/abc123.png", "evidence/index.json", "evidence/runtime-provenance-1.json",
           "work/evidence/manual/TC-1/a1/x", "work/t-fragment-1.json", "work/impl-diff-1.txt")
NOT_IGNORED = ("test-report.md", "work/ledger.json", "work/test-cases/evidence/x.md")


def git(root: Path, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def ignored_by_git(root: Path, rel: str) -> bool:
    # --no-index: a path git already TRACKS is otherwise never reported, which is exactly the E7 case
    return git(root, "check-ignore", "-q", "--no-index", "--", rel).returncode == 0


def put(root: Path, rel: str, text: str = "x\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def repo(prefix: str) -> Path:
    root = temp_dir(prefix)
    git(root, "init", "-q")
    return root


def commit_all(root: Path, msg: str = "c") -> None:
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


def story_dir() -> Path:
    """A minimal story folder: documents, compact ledgers, events, and the evidence a manual run leaves."""
    task = temp_dir("qa-evid-story-") / "T-1"
    put(task, "test-report.md", "report\n")
    put(task, "work/ledger.json", '{"delivery_ready": false}\n')
    put(task, "work/automation-manifest.json", '{"tests": []}\n')
    put(task, "state/events.jsonl", '{"type": "seed"}\n')
    return task


def e1_real_git() -> None:
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        check("E1: git is available (the answers below come from the real git; without it this is a FAILED control, not a pass)", False)
        return
    root = repo("qa-evid-e1-")
    try:
        G.write_block(root)
        for rel in IGNORED:
            check(f"E1: git ignores {rel}", ignored_by_git(root, f"{TASK}/{rel}"))
            check_eq(f"E1: the table's answer matches git for {rel}", I.ignored_inside_tracked(f"{TASK}/{rel}"), True)
        for rel in NOT_IGNORED:
            check(f"E1: git does NOT ignore {rel}", not ignored_by_git(root, f"{TASK}/{rel}"))
            check_eq(f"E1: the table's answer matches git for {rel}", I.ignored_inside_tracked(f"{TASK}/{rel}"), False)
        for rel in ("qa-factory/artifacts/evidence/test-report.md", "qa-factory/records/journal.jsonl"):
            check(f"E1: git does NOT ignore {rel} (a story named `evidence`; a tracked record)", not ignored_by_git(root, rel))
            check_eq(f"E1: the table's answer matches git for {rel}", I.ignored_inside_tracked(rel), False)
        check_eq("E1: a FILE called evidence is not the folder the line names", I.ignored_inside_tracked(f"{TASK}/evidence"), False)
        check_eq("E1: a path that does not normalise is False, never an error", I.ignored_inside_tracked("../x/evidence/a"), False)
        block = [ln for ln in (root / ".gitignore").read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")]
        check("E1/AR-4: every line of the written block is relative (no drive, no leading slash, no backslash)",
              not any(ln.startswith("/") or ":" in ln or "\\" in ln for ln in block), str(block))
    finally:
        cleanup(root)
    # the project lives in a SUBFOLDER of the repository (a monorepo): the same answers
    outer = repo("qa-evid-e1-mono-")
    try:
        proj = outer / "proj"
        proj.mkdir()
        G.write_block(proj)
        check("E1 monorepo: git ignores the exported evidence of a project in a subfolder",
              ignored_by_git(proj, f"{TASK}/evidence/abc123.png") and not ignored_by_git(proj, f"{TASK}/test-report.md"))
    finally:
        cleanup(outer)


def e2_manifest_lists_no_evidence() -> None:
    task = story_dir()
    try:
        put(task, "evidence/abc123.png", "png")
        put(task, "evidence/runtime-provenance-1.json", "{}")
        put(task, "work/evidence/manual/TC-1/a1/x.json", "{}")
        files = [r["path"] for r in M.build(task)["files"]]
        check("E2: no index on disk: the manifest builds and names no evidence path",
              files and not any(p.startswith(("evidence/", "work/evidence/")) for p in files), str(files))
        check("E2: ...and the compact records are still listed", {"test-report.md", "work/ledger.json"} <= set(files), str(files))
        check_in("E2: the manifest says what it leaves out", "evidence/**", M.build(task)["excluded"])
        # whatever the registry says (I4: no table may put evidence in files[]): the filter is its own guard
        held = M.approved_paths
        M.approved_paths = lambda: {*held(), "evidence/abc123.png", "evidence/runtime-provenance-1.json",
                                    "work/evidence/manual/TC-1/a1/x.json", "evidence/index.json"}
        try:
            files = [r["path"] for r in M.build(task)["files"]]
        finally:
            M.approved_paths = held
        check("E2: even a registry that approves evidence paths cannot put them in files[]",
              not any(p.startswith(("evidence/", "work/evidence/")) for p in files), str(files))
        # the real index: the loop checks the copies and lists none of them
        digest = __import__("hashlib").sha256(b"png").hexdigest()
        index = {"rows": [{"case": "TC-1", "evidence_refs": [{"path": "evidence/abc123.png", "sha256": digest}]}], "errors": []}
        put(task, "evidence/index.json", json.dumps(index))
        held_export = manual_evidence.export_records
        manual_evidence.export_records = lambda *_a, **_k: json.loads(json.dumps(index))
        try:
            files = [r["path"] for r in M.build(task)["files"]]
            check("E2: a real index with a real copy: the copy is checked and NOT in files[]",
                  not any(p.startswith(("evidence/", "work/evidence/")) for p in files), str(files))
            check_eq("E2: the manifest of such a story has nothing to say to check_delivery", (D.delivery_manifest_reasons(task)), [])
            # E6: a stale index and a changed file are still refused, with a door
            (task / "evidence" / "abc123.png").write_text("changed", encoding="utf-8")
            try:
                M.build(task)
                refused = ""
            except ValueError as exc:
                refused = str(exc)
            check_in("E6: a changed copy is still refused (a corrupt manual record does not turn green)", "missing or changed", refused)
            check_in("E6: ...and the refusal names the command that rebuilds the index", "ledger.py ", refused)
            check("E6: ...and no longer says the evidence is 'delivered'", "delivered" not in refused, refused)
            (task / "evidence" / "abc123.png").write_text("png", encoding="utf-8")
            manual_evidence.export_records = lambda *_a, **_k: {"rows": [], "errors": []}
            try:
                M.build(task)
                refused = ""
            except ValueError as exc:
                refused = str(exc)
            check_in("E6: a stale index is still refused", "not the current approved projection", refused)
            check_in("E6: ...with the same door", "ledger.py ", refused)
            manual_evidence.export_records = lambda *_a, **_k: {**index, "errors": [{"case": "TC-1", "errors": ["x"]}]}
            (task / "evidence" / "index.json").write_text(json.dumps({**index, "errors": [{"case": "TC-1", "errors": ["x"]}]}), encoding="utf-8")
            try:
                M.build(task)
                refused = ""
            except ValueError as exc:
                refused = str(exc)
            check_in("E6: an export with unresolved errors is still refused, with the door", "ledger.py ", refused)
        finally:
            manual_evidence.export_records = held_export
        # the registry no longer claims the index for delivery
        row = artifact_registry.entries()["manual-evidence-index.json"]
        check_eq("E2: the registry says the index is not for delivery and lives with the task", (row["delivery"], row["retention"]), (False, "task"))
        check("E2: ...and delivery is not among its consumers", "delivery" not in row["consumers"], str(row))
    finally:
        cleanup(task.parent)
    # no evidence at all: nothing to say, the manifest builds
    bare = story_dir()
    try:
        check("E2: a story with no evidence folder builds a manifest", bool(M.build(bare)["files"]))
    finally:
        cleanup(bare.parent)


def e6_real_door() -> None:
    """E6 (r0107 F-1): the door of a refusal is RUN, on the real export (no stand-in for `export_records`): a changed copy of
    a screenshot is refused; the steps the refusal names (delete the changed copy, run ledger.py) make `build` pass."""
    import tempfile
    import test_manual_evidence as fixtures
    import finalize_task as F
    import ledger as L
    from event_store import EventStore, content_hash, atomic_json
    from test_coverage_contract import obligation
    with tempfile.TemporaryDirectory() as td:
        task = Path(td)
        fixtures.ROOT = task
        before, after = task / "work/evidence/before.png", task / "work/evidence/after.png"
        before.parent.mkdir(parents=True)
        before.write_bytes(b"before")
        after.write_bytes(b"after")
        obs = [obligation("O-1", "manual-agent")]
        obs[0]["evidence_policy"] = "ui"
        atomic_json(task / "work/test-plan.json", [{"id": "TS-1", "schema_version": 2, "coverage_obligations": obs}])
        atomic_json(task / "state/story-case-links.json", {"links": [{"case_id": "TC-1", "version": "cv_1"}]})
        store = EventStore(task)
        store.commit("initialize", {"source_revision": fixtures.SNAPSHOT_SHA, "scope": ["TC-1"]}, "init")
        fixtures.seed_provenance(task)
        store.commit("dispatch", {"id": "d1", "stage": "S6", "role": "qa-runner", "scope": ["TC-1"]}, "d1")
        rec = fixtures.record(before, after)
        rec["completion_condition"] = "done"
        rec["obligation_ids"] = ["O-1"]
        rec["obligation_hashes"] = {"O-1": content_hash(obs[0])}
        rec["approved_policy_hash"] = content_hash({"evidence_policy": "ui", "completion_condition": obs[0]["completion_condition"],
                                                    "obligation_hashes": rec["obligation_hashes"]})
        rec["gate_a_decision_ref"] = "decision:gate-a"
        manual_evidence.write_block(task, [rec])
        F.refresh(task)
        L.write(task, L.build(task))
        M.build(task)                                    # the healthy world builds
        copies = sorted(p for p in (task / "evidence").glob("*.png"))
        check("E6 real: the export made copies of the screenshots", len(copies) == 2, str(copies))
        # t-423 F2: the compact record that IS delivered (and pasted into the gate B packet) carries no link or path of a screenshot,
        # while the machine record beside it keeps the exported paths
        ledger_md = (task / "work" / "ledger.md").read_text(encoding="utf-8")
        manual_lines = [ln for ln in ledger_md.splitlines() if ln.startswith("- TC-1")]
        check("E6 real: the delivered ledger.md has a manual-evidence line for the case", len(manual_lines) == 1, ledger_md)
        check("E6 real: ... and it holds no link, no path and no file name of a copy",
              not any(key in ledger_md for key in ("evidence/", ".png", "](")), ledger_md)
        check_in("E6 real: ... only the words: provided", "screenshots: provided", "\n".join(manual_lines))
        kept = json.loads((task / "work" / "ledger.json").read_text(encoding="utf-8"))["manual_evidence"]["rows"][0]["evidence_refs"]
        check("E6 real: the machine record keeps the exported paths", all(ref["path"].startswith("evidence/") for ref in kept), str(kept))
        copies[0].write_bytes(b"a tester marked the picture")          # the copy changed, the source is intact
        try:
            M.build(task)
            refused = ""
        except ValueError as exc:
            refused = str(exc)
        check_in("E6 real: a changed copy is refused", "unresolved errors", refused)
        check_in("E6 real: ...naming the cause, not only the symptom", "public export hash conflict", refused)
        check_in("E6 real: ...and the door says to delete the changed copy before ledger.py", "delete that changed copy", refused)
        for _ in range(2):                              # the OLD door: ledger.py alone never cleared it
            L.write(task, L.build(task))
        try:
            M.build(task)
            still = ""
        except ValueError as exc:
            still = str(exc)
        check("E6 real: ledger.py alone does NOT clear it (so the door must say more than ledger.py)", bool(still), still)
        copies[0].unlink()                              # the door: delete the changed copy ...
        L.write(task, L.build(task))                    # ... then ledger.py
        try:
            M.build(task)
            after_door = ""
        except ValueError as exc:
            after_door = str(exc)
        check_eq("E6 real: after the steps the refusal names, build passes", after_door, "")


def e3_classes() -> None:
    table = I.load_table()
    rules = [r.get("glob") for r in table["rules"]]
    wide = rules.index("qa-factory/artifacts/**")
    for rel in ("evidence/runs/x/r.json", "evidence/abc123.png", "work/evidence/manual/TC-1/a1/x"):
        got = I.classify(f"{TASK}/{rel}")
        check_eq(f"E3: {rel} is carried, machine-local, kept by a reinstall",
                 (got["class"], got["machine_local"], got["retire_safe"], got["retire_mode"], got["reader"]),
                 ("carried", True, True, None, "manual_evidence.py"))
        check("E3: ...and the row that wins is the new one, not artifacts/**", got["rule"] != "qa-factory/artifacts/**", got["rule"])
    check("E3: the two rows stand ABOVE qa-factory/artifacts/** (the first row of a class wins; below it they are dead)",
          rules.index("qa-factory/artifacts/*/evidence/**") < wide and rules.index("qa-factory/artifacts/*/work/evidence/**") < wide)
    check("E3: no new row of the class `regenerated` carries an evidence glob (a reinstall would delete screenshots nobody rebuilds)",
          not any(r.get("class") == "regenerated" and "evidence" in str(r.get("glob")) for r in table["rules"]))
    for rel in ("qa-factory/artifacts/evidence/test-report.md", f"{TASK}/work/test-cases/evidence/x.md", f"{TASK}/test-report.md"):
        got = I.classify(rel)
        check_eq(f"E3: {rel} is NOT evidence: the old row, not machine-local", (got["rule"], got["machine_local"]),
                 ("qa-factory/artifacts/**", False))
    verdict = I.validate_table()
    check_eq("E3: validate_table has no error with the new rows", (verdict["ok"], verdict["errors"]), (True, []))
    # a reinstall keeps the files: none of them is in a retire list
    root = temp_dir("qa-evid-e3-")
    try:
        for rel in ("evidence/runs/x/r.json", "evidence/abc123.png", "work/evidence/manual/TC-1/a1/x.png"):
            put(root, f"{TASK}/{rel}", "bytes")
        scan = I.scan_tree(root)
        retired = [i["rel_path"] for i in scan["retire"]]
        check("E3/I6: a reinstall lists none of the evidence files for retirement", not any("/evidence/" in p for p in retired), str(retired))
    finally:
        cleanup(root)


def e4_git_add_by_manifest() -> None:
    root = repo("qa-evid-e4-")
    try:
        task = root / TASK
        for rel in ("test-report.md", "work/ledger.json", "state/events.jsonl"):
            put(task, rel)
        for rel in ("evidence/abc123.png", "evidence/runtime-provenance-1.json", "work/evidence/manual/TC-1/a1/x.png"):
            put(task, rel)
        files = [f"{TASK}/{r['path']}" for r in M.build(task)["files"]]
        # the NEW world: the new block, the new manifest: every path adds
        G.write_block(root)
        added = git(root, "add", "--", *files)
        check_eq("E4: the new block and the new manifest: `git add` of every path in files[] passes", added.returncode, 0)
        staged = git(root, "diff", "--cached", "--name-only").stdout.splitlines()
        check("E4: ...and no evidence is staged", not any("/evidence/" in p for p in staged), str(staged))
        # the OLD manifest (an earlier run listed the copy) against the new block: git refuses - they cannot change apart
        refused = git(root, "add", "--", f"{TASK}/evidence/abc123.png")
        check("E4: an old manifest row for an ignored copy is refused by git (block and manifest change in one commit)",
              refused.returncode != 0, refused.stdout + refused.stderr)
    finally:
        cleanup(root)
    # the OLD world: a project with the older block (no `evidence/` line): the new manifest still lists no evidence
    older = repo("qa-evid-e4-old-")
    try:
        put(older, ".gitignore", "qa-factory/artifacts/*/work/evidence/\nqa-factory/state/\n")
        task = older / TASK
        put(task, "test-report.md")
        put(task, "evidence/abc123.png")
        files = [f"{TASK}/{r['path']}" for r in M.build(task)["files"]]
        check("E4: the older block: the new manifest names no evidence copy either", not any("/evidence/" in p for p in files), str(files))
        check_eq("E4: ...and its `git add` passes", git(older, "add", "--", *files).returncode, 0)
    finally:
        cleanup(older)


def e5_old_manifest_door() -> None:
    task = story_dir()
    try:
        doc = M.build(task)
        put(task, "evidence/x.png", "png")
        doc["files"].append({"path": "evidence/x.png", "sha256": "0" * 64, "bytes": 3})
        put(task, "state/delivery-manifest.json", json.dumps(doc))
        reasons = D.delivery_manifest_reasons(task)
        row = next((r for r in reasons if "evidence/x.png" in r), "")
        check("E5: an old manifest listing a copy gets a reason", bool(row), str(reasons))
        check_in("E5: ...with the door: the command that rebuilds the manifest", "delivery_manifest.py --task-root", row)
        check_in("E5: ...naming where the rebuilt file goes", "state/delivery-manifest.json", row)
        M.refresh(task)
        check_eq("E5: finalize_task's refresh rebuilds it and the reason is gone", D.delivery_manifest_reasons(task), [])
    finally:
        cleanup(task.parent)


def e7_tracking() -> None:
    root = repo("qa-evid-e7-")
    try:
        task = root / TASK
        tracked_ignored = ["evidence/a.png", "work/evidence/manual/TC-1/a1/f.png", "work/x-fragment-1.json", "work/impl-diff-1.txt"]
        for rel in (*tracked_ignored, "work/ledger.json", "test-report.md"):
            put(task, rel)
        put(root, "qa-factory/state/s.json", "{}")
        commit_all(root, "an old install committed everything")
        G.write_block(root)
        t = OA.tracking(root, [])
        want = sorted(f"{TASK}/{rel}" for rel in tracked_ignored)
        check_eq("E7: tracked_ignored names every tracked path the block now covers", t["tracked_ignored"], want)
        check_eq("E7: ...and the state file stays in its own group", t["tracked_in_state"], ["qa-factory/state/s.json"])
        check_eq("E7: git_rm holds one exact line per path of both groups, sorted",
                 t["git_rm"], sorted(f"git rm --cached {p}" for p in [*want, "qa-factory/state/s.json"]))
        check("E7: an untouched tracked record (work/ledger.json) gets no line", not any("ledger.json" in ln for ln in t["git_rm"]), str(t["git_rm"]))
        check_eq("E7: every path named is one the real git ignores now", [p for p in want if not ignored_by_git(root, p)], [])
        text = OA.render({"blocked": None, "nothing_to_do": False, "manifest": {"status": "ok", "reason": "", "newer": False},
                          "retire": [], "write": [], "regenerate": [], "changed_since_install": [], "not_ours_kept": [], "locks": [],
                          "live_locks": [], "unknown": [], "refused": [], "tracking": t, "set_aside": None, "proposal": {},
                          "install_exists": True, "date": "2026-10-30"})
        check_in("E7: the text a person reads has the group, with the exact line beside each path", "Generated files your repository still tracks", text)
        check_in("E7: ...", f"git rm --cached {want[0]}", text)
        check("E7: ...and names no field of the plan", "tracked_ignored" not in text and "git_rm" not in text)
        index_before = (root / ".git" / "index").read_bytes()
        OA.tracking(root, [])
        check_eq("E7: tracking only READS git: the index is byte-for-byte unchanged", (root / ".git" / "index").read_bytes() == index_before, True)
        # nothing deleted by code
        check("E7: no evidence file was touched on disk", all((task / rel).is_file() for rel in tracked_ignored))
    finally:
        cleanup(root)
    # a project in a subfolder of a monorepo
    outer = repo("qa-evid-e7-mono-")
    try:
        proj = outer / "proj"
        put(proj, f"{TASK}/evidence/a.png")
        commit_all(outer)
        G.write_block(proj)
        check_eq("E7 monorepo: the project's tracked evidence is found relative to the project",
                 OA.tracking(proj, [])["tracked_ignored"], [f"{TASK}/evidence/a.png"])
    finally:
        cleanup(outer)
    # not a repository: the same keys, nothing listed
    plain = temp_dir("qa-evid-e7-plain-")
    try:
        saved = __import__("os").environ.get("GIT_CEILING_DIRECTORIES")
        __import__("os").environ["GIT_CEILING_DIRECTORIES"] = str(plain.parent)
        try:
            t = OA.tracking(plain, [])
        finally:
            if saved is None:
                __import__("os").environ.pop("GIT_CEILING_DIRECTORIES", None)
            else:
                __import__("os").environ["GIT_CEILING_DIRECTORIES"] = saved
        check_eq("E7: not a repository: checked false with a line, tracked_ignored empty (FR-41)",
                 (t["checked"], bool(t["line"]), t["tracked_ignored"], t["git_rm"]), (False, True, [], []))
    finally:
        cleanup(plain)
    # 93 tracked files: 93 lines, no cap
    many = repo("qa-evid-e7-many-")
    try:
        for i in range(93):
            put(many, f"{TASK}/evidence/p{i:03d}.png")
        commit_all(many)
        G.write_block(many)
        t = OA.tracking(many, [])
        check_eq("E7: 93 tracked files: 93 lines, nothing cut", (len(t["tracked_ignored"]), len(t["git_rm"])), (93, 93))
    finally:
        cleanup(many)


def main() -> None:
    e1_real_git()
    e2_manifest_lists_no_evidence()
    e6_real_door()
    e3_classes()
    e4_git_add_by_manifest()
    e5_old_manifest_door()
    e7_tracking()
    finish("test_evidence_not_delivered")


if __name__ == "__main__":
    main()
