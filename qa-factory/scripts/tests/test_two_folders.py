"""The two folders (t-232 section 8, owner's decision F7+F8): `qa-factory/records/` is tracked and holds
the carried records, `qa-factory/state/` is machine-local and ignored whole; one path module
(`runtime_paths.py`) says where each file is, in BOTH worlds until a project is re-onboarded; the
reinstall MOVES the records an older factory kept in `state/`.

What is proved here, from the outside:
  * the layout of a fresh project, and the one place every reader and writer asks (runtime_paths);
  * both worlds: a project that has only the old layout is read and written where its files are; both
    copies present -> the newer by mtime is read; a fresh project gets the new place;
  * the move on an old-layout tree: records/ populated byte for byte, state/ holds no carried file,
    `config-migrations/` moves whole, the old folder is gone, the move happens BEFORE regenerate and
    retire (nothing carried is ever absent from both places), a second plan has nothing to do;
  * two different copies are never merged or overwritten: the plan lists the one not in use, apply
    leaves both; the same bytes in both places finish the move;
  * the `.gitignore` block is derived from the table: one line for the ignored folder, none for records/.

Mutations this file kills (each by this file alone):
  read fallback off (an old-layout project unreadable) | move after retire | a gitignore line for
  records/ emitted | a duplicate silently resolved

Run: python -B scripts/tests/test_two_folders.py
"""
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import check, check_eq, check_in, cleanup, finish, run_script, temp_dir, temp_project, use_project  # noqa: E402

use_project(temp_project("qa-two-folders-audit-"))      # config_contract pulls audit_factory, which reads the hook layer

import config_contract as C  # noqa: E402
import hooklib  # noqa: E402
import install_paths as I  # noqa: E402
import onboard_apply as OA  # noqa: E402
import project_gitignore as G  # noqa: E402
import runtime_paths as RP  # noqa: E402

DATE = "2026-10-01"
CTX = {"package_fingerprint": "fingerprint-of-the-installed-package"}
NAMES = ["journal.jsonl", "estimation-ledger.jsonl", "coverage-map.md", "project-decisions.json", "onboarding-approvals.jsonl"]
MIGRATIONS = {"a.json": '{"a": 1}\n', "b.json": '{"b": 2}\n', "sub/c.json": '{"c": 3}\n'}


def put(root: Path, rel: str, text: str = "x") -> Path:
    path = root.joinpath(*rel.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def sha(root: Path, rel: str) -> str:
    return hashlib.sha256(root.joinpath(*rel.split("/")).read_bytes()).hexdigest()


def tree(root: Path, under: str) -> list:
    base = root.joinpath(*under.split("/"))
    return sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()) if base.is_dir() else []


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def old_layout() -> Path:
    """A project an older factory installed: every carried record in state/, the readiness report
    beside the config, plus the machine-local files that must stay where they are."""
    root = temp_project("qa-two-folders-old-")
    for name in NAMES:
        put(root, f"qa-factory/state/{name}", f"old {name}\nsecond line\n")
    put(root, "qa-factory/state/onboarding-approvals.jsonl",      # an earlier install's word: valid lines, the log is appended to
        json.dumps({"schema_version": 1, "approval_ref": "onboarding:earlier", "status": "approved", "input_hash": "0" * 64,
                    "proposal_hash": "1" * 64, "evidence_ref": "t:earlier"}) + "\n")
    for rel, text in MIGRATIONS.items():
        put(root, f"qa-factory/state/config-migrations/{rel}", text)
    put(root, "qa-factory/state/host-receipts/r1.json", "{}\n")
    put(root, "qa-factory/state/cost/s1.json", "{}\n")
    put(root, "qa-factory/readiness.json", json.dumps({"runtime_paths": {"package_version": "0.7.4"}}))
    return root


def stub(root, script, args=()):
    """Stands in for readiness.py / factory_dashboard.py / check_coverage.py: records what stood where
    when each ran, and writes what the real one writes."""
    STUB_CALLS.append((script, {"records": [p for p in NAMES if (Path(root) / "qa-factory/records" / p).exists()],
                                "old": [p for p in NAMES if (Path(root) / "qa-factory/state" / p).exists()]}))
    if script == "readiness.py":
        put(Path(root), OA.READINESS_REL, json.dumps({"runtime_paths": {"package_version": C.package_version()}}))
    elif script == "factory_dashboard.py":
        put(Path(root), OA.DASHBOARD_REL, "<html></html>")
    return {"step": script, "ok": True, "rc": 0, "note": ""}


STUB_CALLS: list = []


def plan_of(root: Path) -> dict:
    # t-298: `environment.access` is asked until answered; these cases are about the layout, so the person's answer is "not now" (the
    # template default, given explicitly: the config on disk stays as it is, so no config write and no backup disturb the tree). An
    # answer for a config that already records an access is simply listed as not asked.
    answer = {"/environment/access": C.canonical_template()["environment"]["access"]}
    return OA.plan(root, C.migration_plan(C.read_config_file(root), root=root, answers=answer), context=CTX, date=DATE)


def approve(root: Path, made: dict, ref: str = "onboarding:two-folders") -> str:
    C.record_approval(root, made["proposal"], ref, "test:evidence")
    return ref


# --- the layout, and the one module ------------------------------------------------------------------

def layout_of_a_fresh_project() -> None:
    root = temp_project("qa-two-folders-fresh-")
    try:
        check_eq("the two folders are named in one place", (RP.HOME, RP.RECORDS, RP.STATE), ("qa-factory", "records", "state"))
        check_eq("a fresh project: a carried record resolves to records/ (nothing exists yet, so the layout's own place)",
                 [RP.record(root, n) for n in NAMES], [root / "qa-factory" / "records" / n for n in NAMES])
        check_eq("...the readiness report to state/, the machine-local files to state/",
                 (RP.readiness(root), RP.readiness_write(root), RP.state_file(root, "cost", "x.json")),
                 (root / "qa-factory/state/readiness.json", root / "qa-factory/state/readiness.json", root / "qa-factory/state/cost/x.json"))
        check_eq("FR-45: resolving creates nothing", sorted(p.name for p in (root / "qa-factory").iterdir()), ["config.json", "state"])
        check_eq("the names that live in records/ come from the table (no second list in code)", RP.record_names(),
                 tuple(Path(m["to"]).name for m in I.moves()))
        check_eq("rel_text is the spelling for a text a person or a role reads", RP.rel_text("journal.jsonl"), "qa-factory/records/journal.jsonl")
        check_eq("configured(): empty and BOTH spellings of the factory's own default resolve through the layout",
                 {RP.configured(root, v, "journal.jsonl") for v in ("", None, "qa-factory/state/journal.jsonl", "qa-factory\\records\\journal.jsonl")},
                 {root / "qa-factory/records/journal.jsonl"})
        check_eq("configured(): a person's own path is honoured as it is", RP.configured(root, "elsewhere/j.jsonl", "journal.jsonl"), root / "elsewhere/j.jsonl")
        check_eq("project_alias: the data files' spellings follow the layout (idempotent for the new ones)",
                 [RP.project_alias(root, s) for s in ("readiness.json", "state/journal.jsonl", "records/journal.jsonl", "strategy/faq.md", "state/cost/")],
                 ["state/readiness.json", "records/journal.jsonl", "records/journal.jsonl", "strategy/faq.md", "state/cost/"])
    finally:
        cleanup(root)


# --- both worlds ---------------------------------------------------------------------------------------

def both_worlds() -> None:
    root = old_layout()
    try:
        check_eq("an old-layout project: every record resolves to where its file IS (state/), not to a file that is not there",
                 [RP.record(root, n) for n in NAMES], [root / "qa-factory/state" / n for n in NAMES])
        check_eq("...the config-migrations folder too, and the readiness report beside the config",
                 (RP.record(root, "config-migrations"), RP.readiness(root)),
                 (root / "qa-factory/state/config-migrations", root / "qa-factory/readiness.json"))
        check_eq("...so the project_alias of a data file points at the real file",
                 (RP.project_alias(root, "state/journal.jsonl"), RP.project_alias(root, "readiness.json")),
                 ("state/journal.jsonl", "readiness.json"))
        # a real reader of each kind reads the old file
        check_eq("config_contract reads the approvals where the old layout keeps them", C.approvals_path(root), root / "qa-factory/state/onboarding-approvals.jsonl")
        check_eq("hooklib.version_carriers reads the old readiness report", hooklib.version_carriers(root)["readiness"]["version"], "0.7.4")
        import brief_pack
        put(root, "qa-factory/state/journal.jsonl", json.dumps({"event": "human_answer", "task": "T-1", "notes": "never write to Jira"}) + "\n")
        check_eq("brief_pack reads the person's answers from an old-layout journal", brief_pack.answers_of("T-1", root), ["never write to Jira"])
        # a writer writes where the file is: no second journal beside the old one
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
        done = run_script("log_append.py", "--event", "delegated", "--agent", "qa-scout", "--task", "T-1", env=env, cwd=root)
        check_eq("log_append in an old-layout project succeeds", done.returncode, 0)
        lines = (root / "qa-factory/state/journal.jsonl").read_text(encoding="utf-8").splitlines()
        check_eq("...and appends to the OLD journal (two lines now), starting no second file in records/",
                 (len(lines), (root / "qa-factory/records/journal.jsonl").exists()), (2, False))
    finally:
        cleanup(root)
    # a fresh project: the writer starts records/journal.jsonl and nothing in state/
    fresh = temp_project("qa-two-folders-fresh-writer-")
    try:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(fresh))
        done = run_script("log_append.py", "--event", "delegated", "--agent", "qa-scout", "--task", "T-1", env=env, cwd=fresh)
        check_eq("log_append in a fresh project succeeds", done.returncode, 0)
        check_eq("...it writes records/journal.jsonl and no journal in state/",
                 ((fresh / "qa-factory/records/journal.jsonl").is_file(), (fresh / "qa-factory/state/journal.jsonl").exists()), (True, False))
        check_eq("...its lock is machine-local: in state/, never beside the tracked journal",
                 (sorted(p.name for p in (fresh / "qa-factory/records").iterdir()), (fresh / "qa-factory/state/.journal-writer").is_dir()),
                 (["journal.jsonl"], True))
    finally:
        cleanup(fresh)
    # both copies: the newer by mtime is read; a tie goes to the layout's own place
    both = temp_project("qa-two-folders-both-")
    try:
        old, new = put(both, "qa-factory/state/journal.jsonl", "old\n"), put(both, "qa-factory/records/journal.jsonl", "new\n")
        os.utime(old, (2_000_000_000, 2_000_000_000))
        os.utime(new, (1_000_000_000, 1_000_000_000))
        check_eq("both copies: the NEWER by mtime is read (the old one is newer here)", RP.record(both, "journal.jsonl"), old)
        os.utime(new, (3_000_000_000, 3_000_000_000))
        check_eq("...and when the new place is the newer, that one", RP.record(both, "journal.jsonl"), new)
        os.utime(old, (3_000_000_000, 3_000_000_000))
        check_eq("...a tie goes to records/", RP.record(both, "journal.jsonl"), new)
        check_eq("duplicate(): the pair, newer first", RP.duplicate(both, "journal.jsonl"), (new, old))
        check_eq("duplicate(): None when only one copy exists", RP.duplicate(both, "coverage-map.md"), None)
        put(both, "qa-factory/state/readiness.json", "{}")
        put(both, "qa-factory/readiness.json", "{}")
        os.utime(both / "qa-factory/readiness.json", (3_000_000_000, 3_000_000_000))
        os.utime(both / "qa-factory/state/readiness.json", (1_000_000_000, 1_000_000_000))
        check_eq("the readiness report follows the same rule (the newer of its two places)", RP.readiness(both), both / "qa-factory/readiness.json")
    finally:
        cleanup(both)
    # the version line reads the new place of the readiness report too
    new_only = temp_project("qa-two-folders-ready-")
    try:
        put(new_only, "qa-factory/state/readiness.json", json.dumps({"runtime_paths": {"package_version": "0.7.7"}}))
        check_eq("hooklib.version_carriers reads state/readiness.json", hooklib.version_carriers(new_only)["readiness"]["version"], "0.7.7")
    finally:
        cleanup(new_only)


# --- the move -------------------------------------------------------------------------------------------

def the_move_on_an_old_layout_tree() -> None:
    root = old_layout()
    try:
        OA._run_script = stub
        STUB_CALLS.clear()
        before = {n: sha(root, f"qa-factory/state/{n}") for n in NAMES if n != "onboarding-approvals.jsonl"}
        made = plan_of(root)
        snap = snapshot(root)
        check_eq("FR-45: plan() writes nothing (the moves are listed, not made)", snapshot(root), snap)
        listed = [(w["source"], w["rel_path"]) for w in made["write"] if w["action"] == "move"]
        expect = [(f"qa-factory/state/{n}", f"qa-factory/records/{n}") for n in NAMES] + \
                 [(f"qa-factory/state/config-migrations/{r}", f"qa-factory/records/config-migrations/{r}") for r in sorted(MIGRATIONS)]
        check_eq("the plan lists every record as a move, old place -> new place (the folder file by file)", sorted(listed), sorted(expect))
        check_eq("...in the listing the person's one word covers (the proposal's listing holds the moves)",
                 sorted((w["source"], w["rel_path"]) for w in made["proposal"]["listing"]["write"] if w["action"] == "move"), sorted(expect))
        text = OA.render(made)
        check_in("the listing says what moves and why, in the person's words", "Will be moved (your records, bytes unchanged", text)
        check_in("...and names one record's old and new place", "qa-factory/state/journal.jsonl -> qa-factory/records/journal.jsonl", text)
        check_eq("no carried record is offered for retirement", [r["rel_path"] for r in made["retire"] if "journal" in r["rel_path"]], [])
        ref = approve(root, made)
        approvals_before = sha(root, "qa-factory/state/onboarding-approvals.jsonl")      # the word was appended to the OLD file
        before["onboarding-approvals.jsonl"] = approvals_before
        steps = []
        done = OA.apply(root, made, ref, date=DATE, checkpoint=steps.append)
        check_eq("apply: the records move BEFORE regenerate and retire", steps[steps.index("move records"):],
                 ["move records", "regenerate", "retire", "manifest"])
        check_eq("...so every script that ran saw all five in records/ and none in state/ (nothing carried is absent from both)",
                 [(call["records"] == NAMES, call["old"]) for _, call in STUB_CALLS], [(True, [])] * len(STUB_CALLS))
        results = next(s["detail"]["results"] for s in done["steps"] if s["step"] == "move records")
        check_eq("every move says what it did, with the sha256 before and after (bytes preserved)",
                 sorted({r["result"] for r in results}), ["moved"])
        check("...and the two shas are the same on every row", all(r["sha256"] == r["sha256_after"] for r in results), str(results[:2]))
        check_eq("records/: the five records and the folder, every byte as it was",
                 ({n: sha(root, f"qa-factory/records/{n}") for n in NAMES}, tree(root, "qa-factory/records/config-migrations")),
                 (before, sorted(MIGRATIONS)))
        check_eq("...the folder's files are byte-equal too",
                 {r: (root / "qa-factory/records/config-migrations" / r).read_text(encoding="utf-8") for r in MIGRATIONS}, MIGRATIONS)
        check_eq("state/ holds no carried record any more: none of the five, no config-migrations folder",
                 ([os.path.exists(root / f"qa-factory/state/{n}") for n in NAMES], os.path.exists(root / "qa-factory/state/config-migrations")),
                 ([False] * 5, False))
        check_eq("...and what is machine-local stayed where it was (receipts, cost) and the readiness report is rebuilt in state/",
                 (tree(root, "qa-factory/state/host-receipts"), tree(root, "qa-factory/state/cost"), os.path.exists(root / "qa-factory/state/readiness.json"),
                  os.path.exists(root / "qa-factory/readiness.json")), (["r1.json"], ["s1.json"], True, False))
        check_eq("the approvals are read from their new place (fold receipts, memory) and still carry the word just given",
                 (C.approvals_path(root), ref in (root / "qa-factory/records/onboarding-approvals.jsonl").read_text(encoding="utf-8")),
                 (root / "qa-factory/records/onboarding-approvals.jsonl", True))
        gi = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
        check_eq("the .gitignore block is one piece: the header and one line per class folder, none for records/",
                 gi, [G.HEADER, *G.GITIGNORE_BLOCK])
        check_eq("...the ignored folder is ONE line, the tracked folder none",
                 ([l for l in gi if "qa-factory/state" in l], [l for l in gi if "records" in l]), (["qa-factory/state/"], []))
        # K-line: what a person sees on this tree, one line each
        print("K-line records/ :", ", ".join(tree(root, "qa-factory/records")))
        print("K-line state/   :", ", ".join(tree(root, "qa-factory/state")))
        print("K-line .gitignore:", " | ".join(gi))
        again = plan_of(root)
        check_eq("a second plan over the moved tree: no move, nothing to approve",
                 ([w for w in again["write"] if w["action"] == "move"], again["changed_since_install"]), ([], []))
        check_eq("(it is only the manifest that is left to write, or nothing at all)", all(w["rel_path"] == OA.MANIFEST_REL for w in again["write"]), True)
    finally:
        cleanup(root)


def a_crash_after_the_move() -> None:
    root = old_layout()
    try:
        OA._run_script = stub
        made = plan_of(root)
        ref = approve(root, made)

        def boom(step):
            if step == "move records":
                raise RuntimeError("power cut right after the move")
        try:
            OA.apply(root, made, ref, date=DATE, checkpoint=boom)
            raised = ""
        except RuntimeError as exc:
            raised = str(exc)
        check_in("the crash we injected happened after the move", "power cut", raised)
        check_eq("nothing carried is absent from both places: every record is in records/ and none was lost",
                 ([os.path.exists(root / f"qa-factory/records/{n}") for n in NAMES], [os.path.exists(root / f"qa-factory/state/{n}") for n in NAMES]),
                 ([True] * 5, [False] * 5))
        check_eq("the old readiness report is still there (nothing was retired before the crash)", os.path.exists(root / "qa-factory/readiness.json"), True)
        replan = plan_of(root)
        check_eq("the next plan finds no move left, and the rest still goes through",
                 ([w for w in replan["write"] if w["action"] == "move"], replan["blocked"]), ([], None))
    finally:
        cleanup(root)


def two_copies() -> None:
    root = old_layout()
    try:
        OA._run_script = stub
        # a crash between the two halves of a move elsewhere: the SAME bytes already stand in records/
        put(root, "qa-factory/records/coverage-map.md", (root / "qa-factory/state/coverage-map.md").read_text(encoding="utf-8"))
        # two machines: DIFFERENT bytes in both places of one record, the old one newer
        newer = put(root, "qa-factory/state/project-decisions.json", "old side, edited later\n")
        older = put(root, "qa-factory/records/project-decisions.json", "new side, older\n")
        os.utime(older, (1_000_000_000, 1_000_000_000))
        os.utime(newer, (2_000_000_000, 2_000_000_000))
        old_sha, new_sha = sha(root, "qa-factory/state/project-decisions.json"), sha(root, "qa-factory/records/project-decisions.json")
        made = plan_of(root)
        check_eq("a record that stands in BOTH places with different bytes is listed, never silently resolved: "
                 "the copy that is not in use (older by mtime) is in changed_since_install, naming the one that is",
                 [(c["rel_path"], c["duplicate_of"], c["actual_sha256"], c["expected_sha256"]) for c in made["changed_since_install"]],
                 [("qa-factory/records/project-decisions.json", "qa-factory/state/project-decisions.json", new_sha, old_sha)])
        check_eq("...and it is NOT among the moves (nothing is moved over the other)",
                 [w["rel_path"] for w in made["write"] if w["action"] == "move" and "project-decisions" in w["rel_path"]], [])
        check_eq("...while the same-bytes copy IS: it finishes the move (the old one goes)",
                 [w["rel_path"] for w in made["write"] if w["action"] == "move" and "coverage-map" in w["rel_path"]], ["qa-factory/records/coverage-map.md"])
        text = OA.render(made)
        check_in("the listing says it in words: two different copies, the newer one is in use, nothing moved over the other", "two different copies of one record", text)
        check_in("...naming both files", "qa-factory/records/project-decisions.json (the other copy: qa-factory/state/project-decisions.json)", text)
        ref = approve(root, made)
        done = OA.apply(root, made, ref, date=DATE)
        results = {r["to"]: r["result"] for s in done["steps"] if s["step"] == "move records" for r in s["detail"]["results"]}
        check_eq("apply: the different copies are KEPT, both, bytes untouched",
                 (results["qa-factory/records/project-decisions.json"].startswith("kept: two different copies"),
                  sha(root, "qa-factory/state/project-decisions.json"), sha(root, "qa-factory/records/project-decisions.json")), (True, old_sha, new_sha))
        check_eq("apply: the same-bytes copy completes the move: the old one is removed, the new stands",
                 (results["qa-factory/records/coverage-map.md"].startswith("completed"), os.path.exists(root / "qa-factory/state/coverage-map.md"),
                  os.path.exists(root / "qa-factory/records/coverage-map.md")), (True, False, True))
        check_eq("the one in use is the newer by mtime: reads follow it", RP.record(root, "project-decisions.json"), root / "qa-factory/state/project-decisions.json")
        replan = plan_of(root)
        check_eq("the duplicate is reported again by the next plan (it is not forgotten)",
                 [c["rel_path"] for c in replan["changed_since_install"]], ["qa-factory/records/project-decisions.json"])
    finally:
        cleanup(root)


def the_gitignore_block_is_derived() -> None:
    table = I.load_table()
    check_eq("the block is what the table derives: the artifacts' generated files, then one line per untracked folder",
             G.GITIGNORE_BLOCK, I.gitignore_block(table))
    check_eq("...which is one line for state/", [l for l in G.GITIGNORE_BLOCK if "state" in l], ["qa-factory/state/"])
    check("...and none names records/ (the tracked folder must stay visible to git)", not any("records" in l for l in G.GITIGNORE_BLOCK), str(G.GITIGNORE_BLOCK))
    # OH3-33 (8d8c540d): the story's evidence rows are machine-local inside the TRACKED artifacts/ folder; their
    # ignore lines are `gitignore_block.inside_tracked`, so such a row is covered when a path made from its glob
    # is ignored by those lines (the same reader the delivery check uses), not only when it sits under state/.
    def probe(glob: str) -> str:
        return glob.replace("**", "x/x").replace("*", "S")
    check_eq("the ignore line and the classification cannot drift: every machine-local row of the table lies in the ignored folder (or under an inside-tracked ignore line)",
             [r["glob"] for r in table["rules"] if r.get("machine_local") and not r["glob"].startswith("qa-factory/state/")
              and not r["glob"] == "qa-factory/readiness.json" and not I.ignored_inside_tracked(probe(r["glob"]), table)], [])
    check_eq("...and no carried record that is not machine-local lies in it (but the old places the moves leave)",
             [r["glob"] for r in table["rules"] if r["class"] == "carried" and not r.get("machine_local") and r["glob"].startswith("qa-factory/state/")
              and "moved_to" not in r], [])


def the_one_path_normaliser() -> None:
    """t-272 item 5: `configured()` and the install's value migration use ONE normaliser."""
    root = temp_project("qa-two-folders-normaliser-")
    try:
        new = root / "qa-factory/records/journal.jsonl"
        check_eq("normalise_project_path: `./`, backslashes, blanks and a trailing slash fold; the case is kept; an absolute path stays absolute; empty stays empty",
                 [RP.normalise_project_path(v) for v in ("./a/b", ".\\a\\b", "a/b/", "  a/b ", "A/B", "/a/b", ".//a", ".", "", None, "./", "C:/x/y", "//srv/s")],
                 ["a/b", "a/b", "a/b", "a/b", "A/B", "/a/b", "a", "", "", "", "", "C:/x/y", "//srv/s"])
        spellings = ["qa-factory/state/journal.jsonl", "qa-factory\\state\\journal.jsonl", "./qa-factory/state/journal.jsonl",
                     ".\\qa-factory\\state\\journal.jsonl", " qa-factory/state/journal.jsonl ", "qa-factory/state/journal.jsonl/",
                     "./qa-factory/records/journal.jsonl", "qa-factory\\records\\journal.jsonl", "", None]
        check_eq("configured(): every spelling of either default - the critic's backslash and `./` forms included - resolves through the layout "
                 "(a fresh project: records/)", {RP.configured(root, v, "journal.jsonl") for v in spellings}, {new})
        put(root, "qa-factory/state/journal.jsonl", "the only copy, in the old place\n")
        check_eq("configured(): ...and in an old-layout project every one of them reads the file where it is (state/), the `./` form too "
                 "(it used to be joined by hand: the same file by luck, a different file once records/ exists)",
                 {RP.configured(root, v, "journal.jsonl") for v in spellings}, {root / "qa-factory/state/journal.jsonl"})
        for own in ("logs/j.jsonl", "qa-factory/state/Journal.jsonl", "qa-factory/state/journal.jsonl.bak", "state/journal.jsonl"):
            check_eq(f"configured(): a person's own path ({own}) is honoured as it is", RP.configured(root, own, "journal.jsonl"), root / own)
        absolute = root.parent / "elsewhere" / "qa-factory" / "state" / "journal.jsonl"        # absolute on this platform (a drive on Windows)
        check_eq("configured(): an absolute path of the person's is not turned into a relative one (backslashes or not)",
                 [RP.configured(root, str(absolute), "journal.jsonl"), RP.configured(root, absolute.as_posix(), "journal.jsonl")], [absolute, absolute])
    finally:
        cleanup(root)


def the_dashboard_reads_the_journal_the_writers_use() -> None:
    """t-272 class row: factory_dashboard.py asked `RP.record` for the journal and ignored a person's own `journal_path`."""
    import contextlib
    import io
    import factory_dashboard as D
    seen: list = []
    real = D.parse_journal
    D.parse_journal = lambda path: (seen.append(Path(path)), real(path))[1]
    try:
        for label, value, place in (("a person's own journal_path", "logs/my-journal.jsonl", "logs/my-journal.jsonl"),
                                    ("no journal_path (the layout's own place)", "", "qa-factory/records/journal.jsonl"),
                                    ("the old default in the `./` spelling, in an old-layout project", "./qa-factory/state/journal.jsonl", "qa-factory/state/journal.jsonl")):
            root = temp_dir("qa-dashboard-journal-")
            try:
                cfg = json.loads((Path(__file__).resolve().parents[2] / "references/templates/config.json").read_text(encoding="utf-8"))
                cfg["journal_path"] = value
                put(root, "qa-factory/config.json", json.dumps(cfg))
                if place.startswith("qa-factory/state"):
                    put(root, place, json.dumps({"ts": "2026-10-01T10:00:00", "event": "x", "agent": "scout", "category": "recon", "notes": "n"}) + "\n")
                seen.clear()
                out = root.parent / (root.name + "-page.html")
                with contextlib.redirect_stdout(io.StringIO()):
                    D.main(["--root", str(root), "--read-only", "--out", str(out)])
                check_eq(f"the dashboard reads the journal where the writers put it: {label}", seen[:1], [root.resolve() / place])
                with contextlib.suppress(OSError):
                    out.unlink()
            finally:
                cleanup(root)
    finally:
        D.parse_journal = real


def main() -> None:
    saved = OA._run_script
    try:
        layout_of_a_fresh_project()
        both_worlds()
        the_move_on_an_old_layout_tree()
        a_crash_after_the_move()
        two_copies()
        the_gitignore_block_is_derived()
        the_one_path_normaliser()
        the_dashboard_reads_the_journal_the_writers_use()
    finally:
        OA._run_script = saved
    finish("test_two_folders")


if __name__ == "__main__":
    main()
