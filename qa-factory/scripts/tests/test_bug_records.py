"""bug_records.py — which bug files belong to ONE story (backlog B-206, piece P4).

Every check is named for the edge it guards. The projects are synthetic and built so that the two
stories share case ids (`TC_003`) and bug file names (`BUG-1.md`), the way TP1-13797 and
TP1-15045 do: a reader that matches on either, or that counts every project bug, fails here.
"""
import ast
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project,
)

sys.path.insert(0, str(SCRIPTS))
import bug_records as BR  # noqa: E402
import contract as C  # noqa: E402
import traceability as T  # noqa: E402


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def bug_md(bug_id: str, title: str, gate: str | None = None, confirmation: str | None = None,
           source_draft: str | None = None, found_by: str = "qa-bug-reporter") -> str:
    lines = ["---", f"id: {bug_id}", f"title: {title}", "severity: major", "status: Open",
             "area: webhook", f"found_by: {found_by}", "violates: requirement:R-7", "created: 2026-09-30"]
    if source_draft is not None:
        lines.append(f"source_draft: {source_draft}")
    if gate is not None:
        lines.append(f"gate_b_decision_id: {gate}")
    if confirmation is not None:
        lines.append(f"confirmation: {confirmation}")
    return "\n".join(lines + ["---", "", "## Initial state", "the body", ""])


def story(root: Path, name: str, gate: str | None) -> Path:
    task = root / "qa-factory" / "artifacts" / name
    task.mkdir(parents=True)
    if gate is not None:
        write(task / "pipeline.json", json.dumps({"gates": {"B": {"id": gate, "gate": "B",
                                                               "decision": "approved"}}}))
    return task


def controller(task: Path, decisions: list) -> None:
    """state/controller.json the way the controller writes it: decisions keyed by id, in order."""
    write(task / "state" / "controller.json", json.dumps({"decisions": {
        d[0]: {"id": d[0], "gate": d[1], "status": d[2] if len(d) > 2 else "approved"} for d in decisions}}))


def groups(result: dict) -> dict:
    """The three states, counted over `state` (the reader's own word for the group)."""
    return {s: sorted(r["id"] for r in result["records"] if r["state"] == s)
            for s in ("confirmed", "unconfirmed", "unknown")}


def ids(result: dict) -> list:
    return [r["id"] for r in result["records"]]


def by_id(result: dict, bug_id: str) -> dict:
    # a missing record answers with empty fields, so one absent bug is one FAIL line, not a traceback
    return next((r for r in result["records"] if r["id"] == bug_id),
                {"id": "<absent>", "title": "", "confirmation": "", "state": "", "paths": [], "homes": [],
                 "notes": []})


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "<dir>")
            for p in sorted(root.rglob("*"))}


def source(result: dict, home: str) -> dict:
    return next((s for s in result["sources"] if s["home"] == home), {})


def owned_bug(root: Path, name: str, task: str | None = None, gate: str | None = None) -> Path:
    """A project-home bug file with the front matter keys `owner_of` reads (and nothing else it needs)."""
    lines = ["---", f"id: {name}", "title: t"]
    if task is not None:
        lines.append(f"task: {task}")
    if gate is not None:
        lines.append(f"gate_b_decision_id: {gate}")
    return write(root / "qa-factory" / "bugs" / f"{name}.md", "\n".join(lines + ["---", ""]))


def owner_pins() -> None:
    """`owner_of`: `other` only when something POSITIVELY names another story that exists on disk and nothing names
    this one; everything else is checked by the exit gate (FR-59). Expectations come from the requirement (the story's
    own bug is never skipped), not from the code; the three pins of t-956 F-1 are BUG-7, BUG-8 and BUG-12."""
    root = temp_project("qa-factory-owner-")
    try:
        t = story(root, "T", "gateB-T-2")
        story(root, "S", "gateB-S")
        story(root, "X", None)
        write(root / "qa-factory" / "artifacts" / "X" / "pipeline.json", "{}")
        story(root, "X-1", None)
        write(root / "qa-factory" / "artifacts" / "X-1" / "pipeline.json", "{}")
        bare = root / "qa-factory" / "artifacts" / "T0"      # a folder with no pipeline.json: no story
        bare.mkdir()
        write(t / "state" / "controller.json", "{not json")   # this story's earlier decisions cannot be read

        def own(label, bug, want, task_root=t, facts=None):
            check_eq(f"owner_of {label}", BR.owner_of(bug, task_root, facts), want)

        own("task names another existing story: other (the live 2530 shape)", owned_bug(root, "BUG-1", task="S"), BR.OTHER)
        own("task is this story's, any case: mine", owned_bug(root, "BUG-2", task="t"), BR.MINE)
        own("task names a story that is not on disk (a typo of this one is as likely): unknown",
            owned_bug(root, "BUG-3", task="NOPE"), BR.UNKNOWN)
        own("task that is a path, not a story name: unknown", owned_bug(root, "BUG-4", task="../S"), BR.UNKNOWN)
        own("no task, the id names another existing story: other", owned_bug(root, "BUG-5", gate="gateB-S"), BR.OTHER)
        own("no task, a repeated decision of another story (-3): other", owned_bug(root, "BUG-6", gate="gateB-S-3"), BR.OTHER)
        own("PIN BUG-7: a ticket-less id names no story: unknown, never skipped",
            owned_bug(root, "BUG-7", gate="B"), BR.UNKNOWN)
        own("PIN BUG-8: this story's earlier decision with controller.json unreadable: not other",
            owned_bug(root, "BUG-8", gate="gateB-T"), BR.MINE)
        own("this story's id with a typo in its number: not other", owned_bug(root, "BUG-9", gate="gateB-T-9"), BR.MINE)
        own("PIN BUG-12: task names another story, the id is this one's: unknown (a conflict is a doubt)",
            owned_bug(root, "BUG-12", task="S", gate="gateB-T-2"), BR.UNKNOWN)
        own("task is this story's, the id names another: unknown", owned_bug(root, "BUG-13", task="T", gate="gateB-S"), BR.UNKNOWN)
        own("the id names a story that does not exist: unknown", owned_bug(root, "BUG-14", gate="gateB-GONE"), BR.UNKNOWN)
        own("the id's case is not an existing story's spelling: unknown", owned_bug(root, "BUG-15", gate="gateB-s"), BR.UNKNOWN)
        own("the id can be a ticket or a ticket and a number (X and X-1 both exist): unknown",
            owned_bug(root, "BUG-16", gate="gateB-X-1"), BR.UNKNOWN)
        own("nothing names a story: unknown", owned_bug(root, "BUG-17"), BR.UNKNOWN)
        write(root / "qa-factory" / "bugs" / "BUG-18.md", "no front matter at all\n")
        own("unreadable front matter: unknown", root / "qa-factory" / "bugs" / "BUG-18.md", BR.UNKNOWN)
        own("a story with no pipeline.json holds nothing against any bug: unknown",
            owned_bug(root, "BUG-19", task="S"), BR.UNKNOWN, task_root=bare)
        own("a story that is not on disk: unknown", owned_bug(root, "BUG-20", task="S"), BR.UNKNOWN,
            task_root=root / "qa-factory" / "artifacts" / "GONE")
        own("a bug file that is not there: unknown, no exception", root / "qa-factory" / "bugs" / "NONE-BUG-1.md", BR.UNKNOWN)
        # the join: a file the join counted for this story is mine, though nothing in its front matter says so
        counted = owned_bug(root, "BUG-21", gate="B")
        own("a ticket-less id the join did not count: unknown", counted, BR.UNKNOWN, facts={})
        own("... and counted by the join (read once by the caller): mine", counted, BR.MINE,
            facts={"records": [{"paths": [counted.as_posix()]}]})
        own("... and the same by the join read here (the story's own file of the same name holds the id)",
            counted, BR.UNKNOWN)
    finally:
        cleanup(root)


# ----------------------------------------------------------------- the drafts of a story (G1-9, t-1078)

def draft(root_task: Path, name: str, body=None, home: str = "work/bug-drafts") -> Path:
    return write(root_task / home / name, json.dumps({"title": name} if body is None else body))


def draft_paths_reads_the_writers_files() -> None:
    """`draft_paths`: the `*.json` files the writer produces, `work/bug-drafts/` then the old `bug-drafts/`, one order on
    every OS, never an exception. Edges 1-5 and 8-10 of the spec. The `.md` rows are the legacy world (I1)."""
    root = temp_dir("qa-factory-drafts-")
    try:
        task = root / "T"
        task.mkdir()
        check_eq("edge 3: no folder at all: []", (BR.draft_paths(task), BR.legacy_md_drafts(task)), ([], []))
        (task / "work" / "bug-drafts").mkdir(parents=True)
        check_eq("edge 1: an empty folder: []", BR.draft_paths(task), [])
        check_eq("the folder is where the writer puts it", BR.draft_dir(task), task / "work" / "bug-drafts")
        draft(task, "BD-2.json")
        draft(task, "BD-10.json")
        draft(task, "BD-1.JSON")
        write(task / "work" / "bug-drafts" / "laid-by-hand.md", "# a hand-made draft")
        write(task / "work" / "bug-drafts" / "notes.txt", "x")
        (task / "work" / "bug-drafts" / "x.json").mkdir()
        names = [p.name for p in BR.draft_paths(task)]
        check_eq("edge 10 / small choice 1: the suffix is case folded (`BD-1.JSON` is a draft, on Windows and Linux alike)",
                 "BD-1.JSON" in names, True)
        check_eq("order: `hooklib.sorted_paths` (code point of the path), the same on every OS - BD-10 before BD-2, "
                 "which a natural order would swap", names, ["BD-1.JSON", "BD-10.json", "BD-2.json"])
        check_eq("edge 9: a folder called `x.json` is no draft", "x.json" in names, False)
        check_eq("edge 4 / I1: a hand-laid `*.md` and a `.txt` are not drafts", [n for n in names if not n.lower().endswith(".json")], [])
        check_eq("the `.md` legacy world is NAMED, never silent: `legacy_md_drafts` lists it",
                 [p.name for p in BR.legacy_md_drafts(task)], ["laid-by-hand.md"])
        check_eq("edge 5: `.md` and `.json` together: the count is the number of `.json`", len(names), 3)
        # edge 8 / F-2 (a): the old flat home is read too, AFTER `work/` (I4: gate B numbers drafts in this order)
        draft(task, "a-old.json", home="bug-drafts")
        check_eq("edge 8: the old home follows `work/`, whatever its names sort like (I4)",
                 [p.relative_to(task).as_posix() for p in BR.draft_paths(task)],
                 ["work/bug-drafts/BD-1.JSON", "work/bug-drafts/BD-10.json", "work/bug-drafts/BD-2.json",
                  "bug-drafts/a-old.json"])
        check_eq("`draft_listing` of a readable story: the same paths and nothing unreadable",
                 BR.draft_listing(task), (BR.draft_paths(task), []))
        # F-1 (t-1100): a folder that cannot be listed is NOT 'no drafts'. `draft_paths` never raises (it adds nothing),
        # `draft_listing` says the folder was not read, and an EMPTY listable folder stays unreadable-free.
        import pathlib
        real = pathlib.Path.iterdir

        def refuse(self):
            raise PermissionError("denied")
        pathlib.Path.iterdir = refuse
        try:
            check_eq("an unlistable folder: `draft_paths` is [] and no exception", BR.draft_paths(task), [])
            check_eq("... and `draft_listing` names BOTH homes as not read, with the reason (FR-41: not 'nothing there')",
                     BR.draft_listing(task),
                     ([], ["work/bug-drafts: cannot list: denied", "bug-drafts: cannot list: denied"]))
            check_eq("a `.md` listing of an unlistable folder is [] too (the legacy note is only a note)",
                     BR.legacy_md_drafts(task), [])
        finally:
            pathlib.Path.iterdir = real
        check_eq("and the folder is read again once it can be", len(BR.draft_paths(task)), 4)
        # only the old home fails: the work/ drafts are still listed, and the failure is named with its own label
        old_home = task / "bug-drafts"

        def refuse_old(self):
            if self == old_home:
                raise PermissionError("denied")
            return real(self)
        pathlib.Path.iterdir = refuse_old
        try:
            paths, unreadable = BR.draft_listing(task)
            check_eq("one home unlistable: the other is still listed, the unreadable one is named by its label",
                     ([p.name for p in paths], unreadable),
                     (["BD-1.JSON", "BD-10.json", "BD-2.json"], ["bug-drafts: cannot list: denied"]))
        finally:
            pathlib.Path.iterdir = real
        empty = root / "E"
        (empty / "work" / "bug-drafts").mkdir(parents=True)
        check_eq("an EMPTY listable folder is not unreadable: ([], [])", BR.draft_listing(empty), ([], []))
    finally:
        cleanup(root)


def the_pairing_of_a_draft_with_its_triage_row_is_one_helper() -> None:
    """`pair_drafts`, `draft_triage_key`, `triage_verdicts` (lifted from `GP._draft_triage_verdicts`): both ways of
    the S7 claim and of gate B's rehearsal. The expectation is the requirement (a bug at the gate needs a draft AND an
    APP_BUG row, each the other's), not what the code printed."""
    app = {"instance_id": "t_a", "attempt_id": "a1", "verdict": "APP_BUG"}
    env = {"instance_id": "t_b", "attempt_id": "a1", "verdict": "ENV_ISSUE"}
    ref = lambda i, a="": {"triage_ref": {"instance_id": i, "attempt_id": a}}   # noqa: E731
    check_eq("key: a mapping", BR.draft_triage_key(ref("t_a", "a1")), ("t_a", "a1"))
    check_eq("key: `instance@attempt` as a string", BR.draft_triage_key({"triage_ref": " t_a @a1 "}), ("t_a", "a1"))
    check_eq("key: names nothing (absent, null, a list, a number, not a draft): ('', '') and no exception",
             [BR.draft_triage_key(x) for x in ({}, {"triage_ref": None}, {"triage_ref": ["t_a"]}, {"triage_ref": 7}, [], None)],
             [("", "")] * 6)
    check_eq("verdicts: each row under its attempt AND under the bare instance; a row without an instance answers nobody",
             BR.triage_verdicts([app, {"verdict": "APP_BUG"}, "junk", {"test": "t_c", "verdict": " FLAKY "}]),
             {("t_a", "a1"): ["APP_BUG"], ("t_a", ""): ["APP_BUG"], ("t_c", ""): ["FLAKY", "FLAKY"]})
    check_eq("verdicts: rows that are not a list: {} and no exception",
             [BR.triage_verdicts(x) for x in (None, {}, "x", 3)], [{}] * 4)

    def pair(drafts, rows):
        got = BR.pair_drafts(drafts, rows)
        return got["no_row"], got["not_app_bug"], got["app_bug_without_draft"], got["app_bug_rows"]
    check_eq("a draft on its APP_BUG row: nothing wrong", pair([("d1", ref("t_a", "a1"))], [app]), ([], [], [], 1))
    check_eq("nothing on either side (I3)", pair([], []), ([], [], [], 0))
    check_eq("only rows that are not APP_BUG, no drafts (edge 7): nothing wrong", pair([], [env]), ([], [], [], 0))
    check_eq("a draft with no row at all (judge-off/13797): no_row", pair([("d1", ref("t_a", "a1"))], []),
             (["d1"], [], [], 0))
    check_eq("a draft that names no row: no_row", pair([("d1", {})], [app]), (["d1"], [], ["t_a@a1"], 1))
    check_eq("a draft on a row that is not APP_BUG: named with the verdicts",
             pair([("d1", ref("t_b", "a1"))], [env]), ([], [("d1", ["ENV_ISSUE"])], [], 0))
    check_eq("an APP_BUG row with no draft: its label",
             pair([], [app]), ([], [], ["t_a@a1"], 1))
    check_eq("a draft naming the instance alone covers every attempt of it (a draft before 0.7.16)",
             pair([("d1", ref("t_a"))], [app]), ([], [], [], 1))
    check_eq("a draft naming ANOTHER attempt rests on no row of this one, and the row has no draft",
             pair([("d1", ref("t_a", "a2"))], [app]), (["d1"], [], ["t_a@a1"], 1))
    check_eq("two drafts for one row: both rest on it, nothing is wrong (as the rehearsal has always allowed)",
             pair([("d1", ref("t_a", "a1")), ("d2", ref("t_a", "a1"))], [app]), ([], [], [], 1))
    check_eq("an APP_BUG row with no instance: covered by nobody",
             pair([("d1", ref("t_a", "a1"))], [app, {"verdict": "APP_BUG"}]), ([], [], ["(a row with no instance_id)"], 2))
    check_eq("rows that are not a list (the caller's refusal comes first): no exception", pair([("d1", {})], None),
             (["d1"], [], [], 0))

    # R6 (t-1508): a red that is ANOTHER case's defect is covered by the blocker's draft, which lists the case in `cases`
    tc2 = {"instance_id": "t_2", "attempt_id": "a1", "case": "TC-002", "verdict": "APP_BUG"}
    tc3 = {"instance_id": "t_3", "attempt_id": "a1", "case": "TC-003", "verdict": "APP_BUG", "blocking_check": "TC-002"}
    d2 = lambda cases=("TC-002", "TC-003"): {**ref("t_2", "a1"), "cases": list(cases)}   # noqa: E731

    def pair_all(drafts, rows):
        got = BR.pair_drafts(drafts, rows)
        return got["app_bug_without_draft"], got["duplicate_draft"], got["blocker_draft_misses_case"]
    check_eq("K-R6-7: TC-003 `blocking_check: TC-002`, the only draft TC-002's with `cases` [TC-002, TC-003] -> covered",
             pair_all([("d2", d2())], [tc2, tc3]), ([], [], []))
    check_eq("K-R6-8: the blocker has no draft -> both rows are owed one",
             pair_all([], [tc2, tc3]), (["t_2@a1", "t_3@a1"], [], []))
    for name, rows_ in (("a TEST_BUG blocker", [dict(tc2, verdict="TEST_BUG"), tc3]),
                        ("itself", [tc2, dict(tc3, blocking_check="TC-003")]),
                        ("an unknown blocker", [tc2, dict(tc3, blocking_check="TC-009")]),
                        ("a cycle A<->B", [dict(tc2, blocking_check="TC-003"), tc3])):
        check(f"K-R6-8: {name} -> the row is in app_bug_without_draft", "t_3@a1" in pair_all([("d2", d2())], rows_)[0],
              str(pair_all([("d2", d2())], rows_)))
    check_eq("K-R6-8: a blocker that is a case with no row at all -> owed",
             pair_all([("d2", d2())], [tc3])[0], ["t_3@a1"])
    check_eq("K-R6-9: an area prefix on the blocker and on `cases` is the same case",
             pair_all([("d2", d2(("integrations/TC-002", "integrations/TC-003")))],
                      [tc2, dict(tc3, blocking_check="integrations/TC-002")]), ([], [], []))
    check_eq("K-R6-9: the blocker named by the id of its test",
             pair_all([("d2", d2())], [tc2, dict(tc3, blocking_check="t_2")]), ([], [], []))
    check_eq("K-R6-10a: a draft on the row with `blocking_check` duplicates the blocker's",
             pair_all([("d2", d2()), ("d3", ref("t_3", "a1"))], [tc2, tc3]), ([], ["d3"], []))
    check_eq("K-R6-10b: the blocker's draft does not list the case -> named",
             pair_all([("d2", d2(("TC-002",)))], [tc2, tc3]), ([], [], [("TC-003", "TC-002")]))
    check_eq("K-R6-10: two rows of one blocker are both covered by its one draft",
             pair_all([("d2", d2(("TC-002", "TC-003", "TC-004")))],
                      [tc2, tc3, dict(tc3, instance_id="t_4", case="TC-004")]), ([], [], []))
    check_eq("K-R6: a row with `blocking_check` and no case is owed a draft (covered by nobody)",
             pair_all([("d2", d2())], [tc2, {k: v for k, v in tc3.items() if k != "case"}])[0], ["t_3@a1"])


def story_bugs_reads_through_the_one_reader() -> None:
    """M-2: `story_bugs` takes its draft files from `draft_paths` - both homes, the suffix case folded - so traceability
    (which reads `story_bugs`) and gate B count the same drafts as the S7 claim; the order of the records stays the
    natural one (BD-2 before BD-10); `_listing` stays only for `exists` and `error`."""
    root = temp_project("qa-factory-bugs-g19-")
    try:
        task = story(root, "STORY-G19", "gateB-G19")
        draft(task, "BD-10.json", {"title": "ten"})
        draft(task, "BD-2.json", {"title": "two"})
        draft(task, "UP.JSON", {"title": "upper"})
        draft(task, "old.json", {"title": "old home"}, home="bug-drafts")
        write(task / "work" / "bug-drafts" / "laid-by-hand.md", "# not a draft")
        got = BR.story_bugs(task)
        check_eq("story_bugs: both homes, the suffix case folded, no `.md`; the natural order of the records",
                 [r["id"] for r in got["records"]], ["BD-2", "BD-10", "UP", "old"])
        sources = source(got, "drafts")
        check_eq("the source entry still names the story's own folder and counts every file read",
                 (sources["exists"], sources["files"], sources["path"].endswith("STORY-G19/work/bug-drafts")), (True, 4, True))
        bare = story(root, "STORY-G19-NONE", "gateB-G19N")
        got = BR.story_bugs(bare)
        check_eq("no draft folder: exists is False and there is no error", (source(got, "drafts")["exists"],
                                                                         "error" in source(got, "drafts")), (False, False))
        # F-5 (t-1100): `exists` and `files` speak of the same homes - "exists: False, files: 1" cannot be written
        old_only = story(root, "STORY-G19-OLD", "gateB-G19O")
        draft(old_only, "old.json", {"title": "old home"}, home="bug-drafts")
        entry = source(BR.story_bugs(old_only), "drafts")
        check_eq("F-5: a draft only in the old home: exists is True and files is 1 (both homes, one answer)",
                 (entry["exists"], entry["files"], "error" in entry), (True, 1, False))
        # F-1: a home that cannot be listed is an `error` of the entry, named by its label - not a quiet 0 files
        import pathlib
        real = pathlib.Path.iterdir
        old_home = (old_only / "bug-drafts").resolve()   # story_bugs resolves the task path (a short Windows temp name)

        def refuse(self):
            if self.resolve() == old_home:
                raise PermissionError("denied")
            return real(self)
        pathlib.Path.iterdir = refuse
        try:
            entry = source(BR.story_bugs(old_only), "drafts")
        finally:
            pathlib.Path.iterdir = real
        check_eq("F-1: an unlistable old home: the entry carries the error with the home's label, the folder is there; "
                 "the count is what could be read",
                 (entry.get("error"), entry["exists"], entry["files"]), ("bug-drafts: cannot list: denied", True, 0))
    finally:
        cleanup(root)


# ---- the census of the readers of the draft folder, by `ast` (M-3) ----------------------------------------------
SCOPES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
# Calls that walk a directory. A reader of the draft folder that does any of them on its own is the defect this node
# removed (`glob("*.md")` where the writer produces `*.json`); the one walk is `BR.draft_paths`.
WALKS = {"glob", "rglob", "iterdir", "scandir", "listdir", "walk"}
# The calls of the one reader: a file that makes either is a reader (READERS). `draft_listing` is the verdict form (F-1).
READER_CALLS = {"draft_paths", "draft_listing"}
# Names that stand for the draft folder in code that holds no literal: the helper and its constant.
FOLDER_NAMES = {"draft_dir", "DRAFT_DIR"}
# The files that read the drafts THROUGH `draft_paths` today. An allow-list on purpose: a new reader is added here
# in the same diff (one line), and a reader missing from it is red, so the census cannot go stale quietly.
READERS = {"bug_records.py", "delivery_summary.py", "factory_dashboard.py", "gate_brief.py", "gate_preflight.py",
           "handoff_check.py", "judge_results.py", "place_answers.py", "bug_neighbours.py"}   # place_answers: the S7 places' `bug` answer names a draft file (t-1995)
# The places that name the folder without reading it, one permanent reason each: (file, scope) -> why. Docstrings
# count (they are string constants): a new line, or a line that no longer exists, is red.
KEPT = {
    ("brief_pack.py", "<module>"): "the folders a role is briefed on (a path in a brief, not a read)",
    ("factory_dashboard.py", "story_bug_rows"): "a `where` label of a row, not a read",
    ("handoff_check.py", "_claim_bug_has_a_draft"): "the refusal text names the folder (FR-1) and the docstring says where the reader is",
    ("judge_results.py", "<module>"): "the module docstring names the folder in prose",
    ("place_answers.py", "_bug_list"): "the refusal text names the folder (FR-1); the listing is `BR.draft_listing`",
    ("validate_artifacts.py", "check_bug_form"): "the refusal text names the folder (FR-1); the draft itself is resolved by the caller through `BR._draft_of` (t-2187 N4)",
    ("driver_dispatch.py", "DriverDispatch.s7_place_lines"): "prose to the role (a message naming the folder), not a read",
    ("driver_stage_plan.py", "DriverStagePlan.role_lines"): "prose to the role (a message), not a read",
    ("driver_s0.py", "DriverS0.s0"): "the writer's side: the folder is created here",
    ("story_step.py", "_post_work"): "mtime of the folder against the judge's file (a staleness probe, not a listing)",
}
# Scopes that pair a draft with its triage row read the draft's `triage_ref` AND a row's `instance_id`/`attempt_id`:
# outside BR there must be none (the pairing is `BR.pair_drafts`; the claim and the rehearsal both call it).
PAIRING_KEPT = {
    ("contract.py", "<module>"): "module-level tuples: BUG_DRAFT_REQUIRED names the field `triage_ref`, other tuples name "
                                 "id fields; none of them pairs anything",
}


def _own_walk(scope):
    """The nodes of a scope, without those of the scopes nested in it (a nested scope node itself is yielded)."""
    todo = list(ast.iter_child_nodes(scope))
    while todo:
        node = todo.pop()
        yield node
        if not isinstance(node, SCOPES):
            todo.extend(ast.iter_child_nodes(node))


def _mentions(node, tainted=frozenset()) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and BR.DRAFT_DIR in n.value:
            return True
        if (isinstance(n, ast.Name) and (n.id in FOLDER_NAMES or n.id in tainted)) \
                or (isinstance(n, ast.Attribute) and n.attr in FOLDER_NAMES):
            return True
    return False


def _is_path_module(node) -> bool:
    """`os.path`, `posixpath`, `ntpath`, `path`: the receivers of a `join` that builds a path (not `", ".join(...)`)."""
    return (isinstance(node, ast.Attribute) and node.attr == "path") \
        or (isinstance(node, ast.Name) and node.id in {"path", "posixpath", "ntpath"})


def _targets(node) -> set:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def census(source: str) -> dict:
    """What one module does with the draft folder: `reads` (scope, line) of every directory walk on a path built from
    the folder's name or from `draft_dir`, through a local name too; `literals` {(scope)} holding the folder's name in
    a string; `calls_draft_paths`; `pairing` {(scope)} holding the draft's `triage_ref` and a row's id string."""
    tree = ast.parse(source)
    out = {"reads": [], "literals": set(), "calls_draft_paths": False, "pairing": set()}

    def go(scope, qual):
        own = list(_own_walk(scope))
        tainted: set = set()
        for _ in range(3):                                   # a name bound from a name bound from the folder
            for n in own:
                if isinstance(n, ast.Assign) and _mentions(n.value, tainted):
                    tainted |= set().union(*(_targets(t) for t in n.targets))
                elif isinstance(n, (ast.For, ast.comprehension)) and _mentions(n.iter, tainted):
                    tainted |= _targets(n.target)
        strings = set()
        for n in own:
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                strings.add(n.value)
                if BR.DRAFT_DIR in n.value:
                    out["literals"].add(qual)
            if isinstance(n, ast.Call):
                fn = n.func
                name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
                if name in READER_CALLS:
                    out["calls_draft_paths"] = True
                receiver = fn.value if isinstance(fn, ast.Attribute) else None
                is_join = name == "join" and _is_path_module(receiver)
                if name in WALKS or is_join:
                    # F-2 (t-1100): the folder may sit in the RECEIVER (`(task / "bug-drafts").glob("*")`) or in an ARGUMENT
                    # (`art.root.glob("work/bug-drafts/*.md")`, `glob.glob(os.path.join(task, "bug-drafts", "*"))`,
                    # `os.listdir(...)`); `os.path.join` names the folder it builds a path to, so it counts as well.
                    parts = ([receiver] if receiver is not None and not is_join else []) + list(n.args) \
                        + [kw.value for kw in n.keywords]
                    if any(_mentions(part, tainted) for part in parts):
                        out["reads"].append((qual, n.lineno))
        if "triage_ref" in strings and ({"attempt_id", "instance_id"} & strings):
            out["pairing"].add(qual)
        for n in own:
            if isinstance(n, SCOPES):
                go(n, n.name if qual == "<module>" else f"{qual}.{n.name}")
    go(tree, "<module>")
    return out


def census_of_package(scripts: Path = SCRIPTS) -> dict:
    return {p.name: census(p.read_text(encoding="utf-8")) for p in sorted(scripts.glob("*.py"))}


CLEAN = {"raw_walks": {}, "readers": [], "named": [], "pairing": []}


def package_violations(found: dict) -> dict:
    """The judge of the census: what in `found` (the census of every module of the package) breaks the class rule.
    ONE function for the real package and for the failing controls, so a control is red through the same code the real
    run is green through. Empty (`CLEAN`) means: no walk of the folder, and no `os.path.join` to it, outside
    `bug_records.py`; the files that read through the one reader are exactly READERS; the places that name the folder
    without reading it are exactly KEPT (a new one is red, a stale one is red); no second pairing outside
    `bug_records.py` (`triage_ref` + a row's id in one scope)."""
    outside = {name: c for name, c in found.items() if name != "bug_records.py"}
    return {
        "raw_walks": {name: c["reads"] for name, c in outside.items() if c["reads"]},
        "readers": sorted({name for name, c in found.items() if c["calls_draft_paths"]} ^ READERS),
        "named": sorted({(name, scope) for name, c in outside.items() for scope in c["literals"]} ^ set(KEPT)),
        "pairing": sorted({(name, scope) for name, c in outside.items() for scope in c["pairing"]} ^ set(PAIRING_KEPT)),
    }


def every_reader_of_the_drafts_folder_reads_through_one_reader() -> None:
    """The class this node fixes: a reader of `work/bug-drafts` with its own glob (`*.md` in the claim, where the writer
    produces `*.json`). The detector is by `ast`, not by the hyphen alone: `BR.draft_dir(t).glob("*.md")` carries no
    literal and was invisible to the first plan (M-3). Positive control FIRST: the shapes of the six readers on `main`
    are flagged, the clean ones are not."""
    shapes = {
        "handoff_check": 'def f(art):\n    return list((art.root / "work" / "bug-drafts").glob("*.md"))\n',
        "gate_brief/gate_preflight": ('def f(task_root):\n    for directory in (task_root / "work" / "bug-drafts", '
                                      'task_root / "bug-drafts"):\n        for p in sorted_paths(directory.glob("*.json")):\n'
                                      '            pass\n'),
        "delivery_summary": "def f(task):\n    for p in sorted_paths((task / 'work/bug-drafts').glob('*.json')):\n        pass\n",
        "judge_results": ('def f(task_root):\n    drafts_dir = task_root / "work/bug-drafts"\n'
                          '    return sorted_paths(drafts_dir.glob("*.json")) if drafts_dir.is_dir() else []\n'),
        "factory_dashboard": ('def f(t):\n    draft_dir = Path(t) / "work" / "bug-drafts"\n'
                              '    return [load(p) for p in sorted_paths(draft_dir.glob("*.json"))]\n'),
        "M-3: draft_dir(...).glob, no literal": 'def f(task):\n    return BR.draft_dir(task).glob("*.md")\n',
        "os.listdir": 'def f(task):\n    return os.listdir(BR.draft_dir(task))\n',
        "iterdir through a local": 'def f(task):\n    home = BR.draft_dir(task)\n    return list(home.iterdir())\n',
    }
    for label, text in shapes.items():
        check(f"census positive control: {label} is a read of the folder", len(census(text)["reads"]) == 1, str(census(text)["reads"]))
    clean = {"the one reader": "def f(task):\n    return [p for p in BR.draft_paths(task)]\n",
             "a glob of another folder": 'def f(task):\n    return (task / "bugs").glob("*.md")\n',
             "the folder named, not walked": 'def f(task):\n    return task / "work" / "bug-drafts"\n'}
    for label, text in clean.items():
        check(f"census negative control: {label} is no read", census(text)["reads"] == [], str(census(text)["reads"]))
    check_eq("census: the scope name is the function (and class) that holds the line",
             census('class K:\n    def m(self, task):\n        return BR.draft_dir(task).glob("*")\n')["reads"], [("K.m", 3)])

    # F-2 (t-1100): the folder in an ARGUMENT of a walk or of a path join, also inside a scope the allow-list already keeps
    arg_forms = {
        "art.root.glob('work/bug-drafts/*.md') in the kept `_claim_bug_has_a_draft`":
            'def _claim_bug_has_a_draft(art):\n    return list(art.root.glob("work/bug-drafts/*.md"))\n',
        "glob.glob(os.path.join(task, 'work', 'bug-drafts', '*.md'))":
            'def f(task):\n    return glob.glob(os.path.join(task, "work", "bug-drafts", "*.md"))\n',
        "os.path.join(task, 'bug-drafts') alone": 'def f(task):\n    return os.path.join(task, "bug-drafts")\n',
        "a pattern holding the folder: task.glob('bug-drafts/*')": 'def f(task):\n    return task.glob("bug-drafts/*")\n',
        "through a local: pattern = 'work/bug-drafts/*.md'":
            'def f(task):\n    pattern = "work/bug-drafts/*.md"\n    return task.glob(pattern)\n',
    }
    for label, text in arg_forms.items():
        check(f"census positive control (F-2): {label} is a read of the folder", len(census(text)["reads"]) >= 1,
              str(census(text)["reads"]))
    for label, text in {"a join of other names": 'def f(task):\n    return os.path.join(task, "bugs", "x.md")\n',
                        "a string join": 'def f(rows):\n    return "; ".join(["bug-drafts", "x"])\n',
                        "a glob with other args": 'def f(task):\n    return task.glob("*.md")\n'}.items():
        check(f"census negative control (F-2): {label} is no read", census(text)["reads"] == [], str(census(text)["reads"]))

    found = census_of_package()
    check("census finds the package at all (control: scripts/*.py are read)", "bug_records.py" in found and len(found) > 100,
          str(len(found)))
    check_eq("the real package is green on every census equality (the positive control of the judge, bug_records.py included)",
             package_violations(found), CLEAN)
    check("every KEPT row carries its reason", all(KEPT.values()))
    second = 'def f(draft, rows):\n    ref = draft.get("triage_ref") or {}\n    return [r for r in rows if r["attempt_id"] == ref["attempt_id"]]\n'
    check_eq("pairing positive control: the shape of a second helper is seen", census(second)["pairing"], {"f"})


def inject(found: dict, **modules: str) -> dict:
    """`found` plus the census of scratch modules BUILT IN A TEMP DIR and read by `census_of_package` - the way the real
    package is read; a module with the name of a real file replaces it. The failing controls of the census (F-3)."""
    scratch = temp_dir("qa-factory-census-")
    try:
        for name, text in modules.items():
            write(scratch / name, text)
        return {**found, **census_of_package(scratch)}
    finally:
        cleanup(scratch)


def the_census_fails_on_an_offender_it_is_not_evergreen() -> None:
    """F-3 (t-1100): the negative control of every equality of the census, committed. A census that is green on the
    package cannot be told from one that checks nothing until it is shown RED on a module that offends: a new reader
    outside READERS, a new name outside KEPT, a stale KEPT row, a walk in a kept scope (F-2), a second pairing."""
    found = census_of_package()
    reader = "import bug_records as BR\n\ndef f(task):\n    return BR.draft_paths(task)\n"
    check_eq("control: a NEW reader outside READERS is red, named by file",
             package_violations(inject(found, **{"zz_new_reader.py": reader}))["readers"], ["zz_new_reader.py"])
    check_eq("control: a new reader through `draft_listing` is red too (the verdict form is a reader as well)",
             package_violations(inject(found, **{"zz_new_listing.py": reader.replace("draft_paths", "draft_listing")}))["readers"],
             ["zz_new_listing.py"])
    check_eq("control: a NEW name of the folder outside KEPT is red, named by file and scope",
             package_violations(inject(found, **{"zz_new_name.py": 'def g():\n    return "work/bug-drafts"\n'}))["named"],
             [("zz_new_name.py", "g")])
    kept_file = sorted({name for name, _scope in KEPT})[0]
    without = {name: c for name, c in found.items() if name != kept_file}
    check_eq(f"control: a STALE KEPT row (its file `{kept_file}` is gone) is red",
             sorted({name for name, _scope in package_violations(without)["named"]}), [kept_file])
    check_eq("control: a READER that stopped reading (its file is gone) is red",
             package_violations({n: c for n, c in found.items() if n != "judge_results.py"})["readers"], ["judge_results.py"])
    scoped = package_violations(inject(found, **{"handoff_check.py":
        'def _claim_bug_has_a_draft(art):\n    return list(art.root.glob("work/bug-drafts/*.md"))\n'}))
    check_eq("control (F-2): a glob with the folder in its ARGUMENT, inside a scope already in KEPT, is a raw walk - red",
             [(name, scope) for name, hits in scoped["raw_walks"].items() for scope, _line in hits],
             [("handoff_check.py", "_claim_bug_has_a_draft")])
    glob_join = package_violations(inject(found, **{"zz_glob.py":
        'import glob\nimport os\n\ndef g(task):\n    return glob.glob(os.path.join(task, "work", "bug-drafts", "*.md"))\n'}))
    check_eq("control (F-2): glob.glob(os.path.join(..., 'bug-drafts', ...)) in a new file is a raw walk - red",
             sorted(glob_join["raw_walks"]), ["zz_glob.py"])
    pairing = package_violations(inject(found, **{"zz_pair.py":
        'def pair(draft, rows):\n    ref = draft.get("triage_ref") or {}\n    return [r for r in rows if r["attempt_id"] == ref["attempt_id"]]\n'}))
    check_eq("control: a second pairing outside bug_records.py is red", pairing["pairing"], [("zz_pair.py", "pair")])
    check_eq("control: a scratch module that does none of it adds nothing (the controls are red for their own reason)",
             package_violations(inject(found, **{"zz_clean.py": "def h():\n    return 1\n"})), CLEAN)
    check_eq("control: `bug_records.py` replaced by a copy that walks the folder itself stays green (the one allowed walk)",
             package_violations(inject(found, **{"bug_records.py":
                 'def draft_paths(task):\n    return list((task / "work" / "bug-drafts").glob("*.json"))\n'
                 'def draft_listing(task):\n    return draft_paths(task), []\n'}))["raw_walks"], {})


# --- t-1676 (RN1-12): the code-reading draft. Mutations (named, not run): skip the `_confirmed` check in `_oracle_problems` -> C2 P20 ---
CR_FACT = "XPANBFLFA-167 price sync / subtotal"
CR_PATH = "MyBooks/src/lib/services/cartService.ts"
CR_READING = "the price shown when added is kept (6 stays 6)"


def cr_task(root, status="answered", says="contradicts: " + CR_FACT, bundle="default"):
    """A LOCAL-1-shaped story (English, re-typed): Q7 answered `a`, a register row R-24, a bundle with the real fact spelling."""
    import question_register as QR
    task = root / "qa-factory" / "artifacts" / "CR-1"
    for stale in ("question-answers.jsonl", "context-bundle.json"):     # one folder serves every variant: nothing of the last one stays
        (task / "work" / stale).unlink(missing_ok=True)
    row = {"id": "Q7", "question": "What should the cart keep?", "severity": "blocker", "source_says": [{"quote": "q", "where": "R-24"}],
           "readings": [{"reading": CR_READING, "from": "person", "if_chosen": "x"}, {"reading": "the price is refreshed", "from": "person", "if_chosen": "y"}]}
    write(task / "work" / "requirements-readiness.json", json.dumps({"open_questions": [row]}))
    record = {"id": "Q7", "status": status, "words": "a", "where": "gate_a", "at": "2026-11-01T12:00:00", "row_hash": QR._hash(row)}
    if status == "answered":
        record["reading"] = "a"
    if status == "changed":
        record.update(status="answered", reading="a", row_hash="0" * 64)
    if status != "none":
        write(task / "work" / "question-answers.jsonl", json.dumps(record) + "\n")
    write(task / "work" / "requirements-register.md",
          "## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact | delta | code_says |\n|---|---|---|---|---|---|---|---|---|---|\n"
          f"| R-24 | The cart keeps the price shown when the book was added | story | — | yes | — | expected-contract | money | new | {says} |\n")
    if bundle == "default":
        bundle = json.dumps({"facts": [
            {"id": CR_FACT, "path": CR_PATH, "line": 103, "note": "calculateCartTotal from DB price"},
            {"id": "XPANBFLFA-44 AC2 out-of-stock product", "path": "MyBooks/src/pages/BookDetailPage.tsx", "line": 170},
            {"id": "XPANBFLFA-44 AC2 out-of-stock product", "path": "MyBooks/src/lib/services/cartService.ts", "line": 35}]})
    if bundle is not None:
        write(task / "work" / "context-bundle.json", bundle)
    return task


def cr_draft(**over) -> dict:
    return {"title": "The cart total uses the current price", "impact": "money", "violates": "requirement:R-24", "evidence": "code-reading",
            "oracle": {"question": "Q7", "quote": "the price shown when added is kept"},
            "fact": {"id": CR_FACT, "path": CR_PATH, "line": 103, "note": "calculateCartTotal from DB price"},
            "check_state": "not_executed", "manual_steps": ["add a book at 6, change its price to 8, open the cart"], "confirmation": "unconfirmed",
            "red_test_none": "no run spoke: the defect is read from the code", **over}


def the_red_test_travels_with_the_bug() -> None:
    """X7-5 (P28): a draft carries `red_test {path, command}` or `red_test_none: <why>`, never neither."""
    both = "`red_test` or `red_test_none`"
    base = {"title": "t", "impact": "money", "violates": "requirement:R-1"}
    problems = C.red_test_problems(base)
    check("X7-5 (4) a draft with neither is refused, naming both fields", len(problems) == 1 and both in problems[0], str(problems))
    check_eq("X7-5 (4) `red_test_none: manual check only` passes", C.red_test_problems({**base, "red_test_none": "manual check only"}), [])
    check_eq("X7-5 (4) a `red_test` with path and command passes",
             C.red_test_problems({**base, "red_test": {"path": "tests/a.py::t", "command": "pytest tests/a.py::t"}}), [])
    check("X7-5 (4) a `red_test` with no command is refused, naming the field",
          any("`command`" in p for p in C.red_test_problems({**base, "red_test": {"path": "tests/a.py::t"}})), "")
    check("X7-5 (4) both set is a conflict, refused",
          len(C.red_test_problems({**base, "red_test_none": "x y", "red_test": {"path": "p", "command": "c"}})) == 1, "")
    check("X7-5 (4) a dash and a blank reason are no reason",
          all(C.red_test_problems({**base, "red_test_none": v}) for v in ("", "-", "  ", None)), "")
    check("m-5 a draft's `red_test` as plain text or a list is refused (a draft holds a mapping)",
          all(C.red_test_problems({**base, "red_test": v}) for v in ("yes", ["x"])), "")
    check_eq("X7-5 the empty draft and a non-dict are refused, never a crash", [bool(C.red_test_problems(x)) for x in ({}, None, "x")],
             [True, True, True])
    root = temp_project("qa-factory-redtest-")
    try:
        task = cr_task(root)
        bare = {k: v for k, v in cr_draft().items() if k != "red_test_none"}
        check_in("X7-5 a code-reading draft without either field is refused (R_RED_TEST)", BR.R_RED_TEST,
                 [code for code, _d in BR.code_reading_problems(task, bare, [("d.json", bare)])])
        # t-1884 M-3: the same cutoff as the bug file and the gate B rehearsal (`contract.red_test_owed`): 11-03 is not asked, 11-04 is
        for day, asked in (("2026-11-03", False), ("2026-11-04", True)):
            dated = {**bare, "created": day}
            check_eq(f"M-3 a code-reading draft created {day} is {'refused' if asked else 'not refused'} for its red test",
                     BR.R_RED_TEST in [code for code, _d in BR.code_reading_problems(task, dated, [("d.json", dated)])], asked)
    finally:
        cleanup(root)


def cr_codes(task, draft, others=()) -> list:
    return [code for code, _detail in BR.code_reading_problems(task, draft, [("d.json", draft), *others])]


REGISTER_WITH_SOURCES = (
    "## Register\n\n| R | Requirement | Source | derived_from | Delta | ac_ref | Observable |\n|---|---|---|---|---|---|---|\n"
    "| R-8 | a quantity of 0 is rejected | TP3-501 description | | | AC-1 | the cart |\n"
    "| R-9 | a negative quantity is rejected | TP3-5011 comment | | | AC-2 | the cart |\n")


def source_ticket(task: Path, folder: str, **fields) -> None:
    write(task / "work" / "sources" / folder / "rev1" / "ticket.json", json.dumps(fields))


def the_open_source_bugs() -> None:
    """RN1-18 C4 (K-C4): the open bug tickets of the story's sources, from the closed word list of bug-status-words.json."""
    task = temp_dir("qa-factory-osb-")
    try:
        write(task / "work" / "requirements-register.md", REGISTER_WITH_SOURCES)
        source_ticket(task, "a", key="TP3-501", type="Bug", status="Open", title="Quantity 0 is added",
                      description="see BookDetailPage.tsx:164 and also src\\cart\\add.ts:12 again BookDetailPage.tsx:164")
        source_ticket(task, "b", key="TP3-502", type="Bug", status="Done", title="Closed one", description="BookDetailPage.tsx:164")
        source_ticket(task, "c", key="TP3-503", type="Story", status="Open", title="Not a bug", description="x.ts:1")
        source_ticket(task, "d", key="TP3-504", type="defect", status="in progress", title="Lower-case type, free status")
        write(task / "work" / "sources" / "e" / "rev1" / "ticket.json", "{not json")
        scan = BR.source_bug_scan(task)
        bugs = {b["key"]: b for b in scan["bugs"]}
        check_eq("K-C4 an open Bug is listed; Done (closed list) and a non-bug type are not",
                 sorted(bugs), ["TP3-501", "TP3-504"])
        check_eq("K-C4 locations: the file:line places, backslashes folded, each once",
                 bugs["TP3-501"]["locations"], ["BookDetailPage.tsx:164", "src/cart/add.ts:12"])
        check_eq("K-C4 requirements: the register Source cell names the key as a WHOLE word (TP3-5011 is another)",
                 bugs["TP3-501"]["requirements"], ["R-8"])
        check_eq("K-C4 a ticket without a place has locations [] (never invented)", bugs["TP3-504"]["locations"], [])
        check_eq("E-C4 an unreadable ticket is skipped and counted in a note", len(scan["notes"]), 1)
        check("E-C4 the note says how many", "1 source ticket" in scan["notes"][0])
        check_eq("K-C4 open_source_bugs is the same list", [b["key"] for b in BR.open_source_bugs(task)], ["TP3-501", "TP3-504"])

        hit = BR.matching_open_bug("BookDetailPage.tsx:164", [], scan["bugs"])
        check_eq("K-C5 a draft at the bug's location extends it", (hit or {}).get("key"), "TP3-501")
        check_eq("K-C5 a draft whose requirements meet the bug's extends it",
                 (BR.matching_open_bug("", ["R-8"], scan["bugs"]) or {}).get("key"), "TP3-501")
        check_eq("K-C5 the same ticket Done: nothing to extend",
                 BR.matching_open_bug("BookDetailPage.tsx:164", ["R-8"], [b for b in scan["bugs"] if b["key"] == "TP3-502"]), None)
        check_eq("E-C5 a bug with no place and no requirements is never matched, an empty place equals nothing",
                 BR.matching_open_bug("", [], scan["bugs"]), None)
        check_eq("K-C5 another place and other requirements: no match", BR.matching_open_bug("Other.tsx:1", ["R-9"], scan["bugs"]), None)

        saved = BR.BUG_STATUS_WORDS_FILE
        BR.BUG_STATUS_WORDS_FILE = "no-such-bug-status-words.json"
        try:
            gone = BR.source_bug_scan(task)
        finally:
            BR.BUG_STATUS_WORDS_FILE = saved
        check_eq("E-C3 the word list missing: no bug listed (an unknown list never marks a duplicate)", gone["bugs"], [])
        check("E-C3 ... and a note says why", len(gone["notes"]) == 1 and "bug-status-words" in gone["notes"][0], str(gone["notes"]))
    finally:
        cleanup(task)
    bare = temp_dir("qa-factory-osb0-")
    try:
        check_eq("K-C4 a story with no sources folder: no bugs, no note", BR.source_bug_scan(bare), {"bugs": [], "notes": []})
    finally:
        cleanup(bare)


def packet_story(root: Path, draft_extra: dict) -> Path:
    """A story with ONE bug draft for the gate B packet and the open bug tickets of its sources (D1-C2 K-C5d)."""
    write(root / "qa-factory" / "config.json", "{}")
    task = root / "qa-factory" / "artifacts" / "QA-1"
    write(task / "pipeline.json", json.dumps({"ticket": "QA-1"}))
    write(task / "work" / "requirements-register.md", REGISTER_WITH_SOURCES)
    source_ticket(task, "a", key="TP3-501", type="Bug", status="Open", title="Quantity 0 is added", description="BookDetailPage.tsx:164")
    source_ticket(task, "b", key="TP3-502", type="Bug", status="Done", title="Closed one", description="BookDetailPage.tsx:164")
    draft = {"title": "Quantity 0 goes into the cart", "impact": "degraded", "violates": "requirement:R-8", "case": "TC-002",
             "triage_ref": {"instance_id": "t1", "attempt_id": "a1"}, "manual_steps": ["add 0 books"], "confirmation": "unconfirmed"}
    write(task / "work" / "bug-drafts" / "q0.json", json.dumps(dict(draft, **draft_extra)))
    write(task / "work" / "triage.json", json.dumps({"triage": [{"test": "t::a", "instance_id": "t1", "attempt_id": "a1", "case": "TC-002",
                                                              "verdict": "APP_BUG", "evidence": "evidence/run.json"}]}))
    return task


def the_draft_place_and_mark() -> None:
    """D1-C2 (t-1727 Q4): `defect_location`, `requirements`, the CLI, the same-place rule and the verified `extends_open_bug` mark.

    Mutations (named, NOT run; one killing file, this one):
      m1 gate_brief `bug_rows`: take the mark without the `in open_keys` check          -> K-C5d (every unverified input renders "Extends")
      m2 bug_records `pair_drafts`: drop the `if place and` guard (empty places count)   -> K-C6b"""
    import contextlib
    import io
    import gate_brief as GB
    check_eq("K-C5a: a place is read in one spelling", BR.draft_location({"defect_location": " src\\BookDetailPage.tsx : 164 "}),
             "src/BookDetailPage.tsx:164")
    check_eq("K-C5a: a code-reading draft has no place (its own rule)", BR.draft_location({"evidence": "code-reading", "defect_location": "a.ts:1"}), "")
    check_eq("K-C5a: no place, a place that is no `file:line`, a non-dict", (BR.draft_location({}), BR.draft_location({"defect_location": "a.ts"}),
                                                                           BR.draft_location(None)), ("", "", ""))
    check_eq("K-C5b: `requirements` wins, sorted and unique", BR.draft_requirements({"requirements": ["R-9", "R-4", "R-4"], "violates": "requirement:R-1"}),
             ["R-4", "R-9"])
    check_eq("K-C5b: the fallback reads `violates`", BR.draft_requirements({"violates": "requirement:R-4"}), ["R-4"])
    check_eq("K-C5b: ... and `oracle.requirement`", BR.draft_requirements({"oracle": {"requirement": "R-24"}}), ["R-24"])
    check_eq("K-C5b: an invalid entry gives nothing, then the fallback", BR.draft_requirements({"requirements": ["x", 3], "violates": "R-2"}), ["R-2"])
    check_eq("K-C5b: nothing gives []", (BR.draft_requirements({}), BR.draft_requirements(None), BR.draft_requirements({"requirements": "R-1"})), ([], [], []))

    root = temp_dir("qa-factory-pm-")
    try:
        task = packet_story(root, {"defect_location": "BookDetailPage.tsx:164", "requirements": ["R-8"]})
        draft_file = task / "work" / "bug-drafts" / "q0.json"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = BR.main(["open-bugs", "--task-root", str(task), "--draft", str(draft_file)])
        said = json.loads(out.getvalue())
        check_eq("K-C5c: the CLI exits 0 and prints ONE json line", (code, out.getvalue().count("\n")), (0, 1))
        check_eq("K-C5c: the open bugs are listed (Done is not)", [b["key"] for b in said["bugs"]], ["TP3-501"])
        check_eq("K-C5c: `match` is the ticket on the draft's place", (said["match"] or {}).get("key"), "TP3-501")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            BR.main(["open-bugs", "--task-root", str(task)])
        check_eq("K-C5c: with no draft there is no match", json.loads(out.getvalue())["match"], None)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            BR.main(["open-bugs", "--task-root", str(task), "--draft", str(root / "gone.json")])
        check("K-C5c: an unreadable draft is a note and no match, exit 0", json.loads(out.getvalue())["match"] is None and "could not be read" in out.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            check_eq("K-C5c: bad arguments exit 2", (BR.main([]), BR.main(["open-bugs"])), (2, 2))

        # K-C5d: a verified mark renders "Extends"; every unverified input renders the old question line
        def packet(extra: dict) -> tuple:
            story_root = temp_dir("qa-factory-pm2-")
            try:
                t = packet_story(story_root, extra)
                rows = GB.bug_rows(t, {})
                return rows[0], GB.render_gate_b("QA-1", root=t)
            finally:
                cleanup(story_root)
        row, text = packet({"extends_open_bug": {"key": "TP3-501", "summary": "THE DRAFT'S OWN WORDS"}})
        check_eq("K-C5d: a verified mark, the summary is the scan's", row["extends"], {"key": "TP3-501", "summary": "Quantity 0 is added"})
        check_in("K-C5d: the packet says it extends the open bug", "Extends the open bug TP3-501 (Quantity 0 is added)", text)
        check_not_in("K-C5d: ... and does not ask", "your call", text)
        check_not_in("K-C5d: ... and never prints the draft's own summary", "THE DRAFT'S OWN WORDS", text)
        for why, mark in (("a ticket that is now Done", {"key": "TP3-502"}), ("a key that is not under work/sources", {"key": "TP3-999"}),
                          ("`tp3-501` against `TP3-501`", {"key": "tp3-501"}), ("a string mark with an unknown key", "TP3-777"),
                          ("a mark with an empty key", {"key": ""})):
            row, text = packet({"extends_open_bug": mark})
            if why == "a mark with an empty key":
                check_not_in(f"K-C5d: {why} renders no Extends and no invented question", "Extends the open bug", text)
                continue
            check_in(f"K-C5d: {why} renders the `your call` line", "your call", text)
            check_not_in(f"K-C5d: {why} never renders `Extends`", "Extends the open bug", text)
        # t-1884 M-2: the person at gate B is the reader of the scribe's form (its `tried` table): the packet links the last accepted one
        form_root = temp_dir("qa-factory-pm3-")
        try:
            t = packet_story(form_root, {})
            check_not_in("M-2: with no accepted scribe dispatch the packet links no form", "the scribe's form", GB.render_gate_b("QA-1", root=t))
            (t / "state").mkdir(exist_ok=True)
            (t / "state" / "controller.json").write_text(json.dumps({"dispatches": {
                "S8-qa-doc-scribe-1": {"id": "S8-qa-doc-scribe-1", "stage": "S8", "role": "qa-doc-scribe", "status": "rejected"},
                "S8-qa-doc-scribe-2": {"id": "S8-qa-doc-scribe-2", "stage": "S8", "role": "qa-doc-scribe", "status": "accepted"}}}), encoding="utf-8")
            text = GB.render_gate_b("QA-1", root=t)
            check_in("M-2: the packet links the scribe's accepted form", "work/handoffs/S8-qa-doc-scribe-2.yaml", text)
            check_not_in("M-2: ... and not the rejected one", "S8-qa-doc-scribe-1.yaml", text)
        finally:
            cleanup(form_root)
        saved = BR.BUG_STATUS_WORDS_FILE
        BR.BUG_STATUS_WORDS_FILE = "no-such-bug-status-words.json"
        try:
            row, text = packet({"extends_open_bug": {"key": "TP3-501"}})
        finally:
            BR.BUG_STATUS_WORDS_FILE = saved
        check_in("K-C5d / E-C16: a missing word list verifies no mark: the `your call` line", "your call", text)
        check_not_in("K-C5d / E-C16: ... and never `Extends`", "Extends the open bug", text)
        check_in("K-C5d / E-C3 (F6b t-1752): ... and the packet SAYS the list could not be read", "bug-status-words", text)
        check_in("K-C5d / E-C3 (F6b): ... in the Note line", "Note: references/no-such-bug-status-words.json could not be read", text)
        row, text = packet({"extends_open_bug": {"key": "TP3-501"}})
        check_not_in("K-C5d (F6b): with a readable list there is no Note line", "Note:", text)
        # F6a (t-1752): a mark with no key is no mark - the word "None" is never printed and nothing is extended
        for why, mark in (("a dict with no key", {"summary": "x"}), ("a null key", {"key": None}), ("a null mark", None)):
            row, text = packet({"extends_open_bug": mark})
            check_not_in(f"K-C5d (F6a): {why} prints no `duplicate of None`", "duplicate of None", text)
            check_not_in(f"K-C5d (F6a): {why} prints no `duplicate` and no `Extends`", "uplicate", text)
            check_not_in(f"K-C5d (F6a): {why} no Extends", "Extends the open bug", text)
        row, text = packet({"possible_duplicate": "TP3-300"})
        check_in("K-C5d: the role's own `possible_duplicate` keeps its line byte for byte", "Possibly a duplicate of TP3-300 — your call", text)
        row, text = packet({})
        check_not_in("K-C7: no `which of` line in gate B (the C7 pin)", "which of", text)
        check_eq("K-C5d: no mark, no extends", row["extends"], None)
    finally:
        cleanup(root)

    # K-C6: the same-place rule
    def d(place: str = "", **extra) -> dict:
        return dict({"triage_ref": {"instance_id": "t", "attempt_id": "a"}, "defect_location": place}, **extra)
    drafts = [("a.json", d("src/x.ts:1")), ("b.json", d("src/x.ts:1")), ("c.json", d("src/x.ts:1")), ("e.json", d("src/y.ts:2"))]
    paired = BR.pair_drafts(drafts, [])
    check_eq("K-C6a: three drafts on one place are one group", paired["same_location"], [("src/x.ts:1", ["a.json", "b.json", "c.json"])])
    check_eq("K-C6b: two drafts with empty places are no group",
             BR.pair_drafts([("a.json", d()), ("b.json", d())], [])["same_location"], [])
    check_eq("K-C6b: a draft with `distinct_defect` leaves the group",
             BR.pair_drafts([("a.json", d("x.ts:1")), ("b.json", d("x.ts:1", distinct_defect="another defect"))], [])["same_location"], [])
    check_eq("K-C6b: a blank `distinct_defect` does not",
             len(BR.pair_drafts([("a.json", d("x.ts:1")), ("b.json", d("x.ts:1", distinct_defect="  "))], [])["same_location"]), 1)
    check_eq("E-C17: code-reading drafts are never grouped (their own one-per-requirement rule)",
             BR.pair_drafts([("a.json", {"evidence": "code-reading", "defect_location": "x.ts:1"}),
                             ("b.json", {"evidence": "code-reading", "defect_location": "x.ts:1"})], [])["same_location"], [])
    check_eq("E-C18: a draft already filed is left out", BR.pair_drafts(drafts[:2], [], filed={"b.json"})["same_location"], [])
    check_eq("K-C6: the default `filed` leaves the old call shape working", BR.pair_drafts(drafts[:2], [])["same_location"],
             [("src/x.ts:1", ["a.json", "b.json"])])
    lines = BR.same_location_problems(paired)
    check_eq("K-C6c: one line per group", len(lines), 1)
    check("K-C6c: it names every draft, the place and both doors",
          all(w in lines[0] for w in ("a.json", "b.json", "c.json", "src/x.ts:1", "merge them into one draft", "distinct_defect")), lines[0])
    check_eq("K-C6c: no group, no line (and a non-dict is no line)", (BR.same_location_problems({"same_location": []}), BR.same_location_problems(None)), ([], []))
    # the filed names come from the one reader of the bug files
    filed_root = temp_dir("qa-factory-pm3-")
    try:
        task = packet_story(filed_root, {})
        write(task / "bugs" / "BUG-1.md", bug_md("BUG-1", "t", source_draft="work/bug-drafts/q0.json"))
        check_eq("E-C18: `filed_draft_names` reads the draft a filed bug names", BR.filed_draft_names(task), {"q0.json"})
    finally:
        cleanup(filed_root)
    check_eq("E-C18: an unreadable story gives the empty set", BR.filed_draft_names(Path("no-such-folder-d1c2")), set())

    # K-C6d: the requirement reaches the role BEFORE the work (AR-10)
    package = Path(SCRIPTS).parent
    contract_text = (package / "references" / "artifact-contract-run.md").read_text(encoding="utf-8")
    charter = (package / "agents" / "qa-failure-analyst.md").read_text(encoding="utf-8")
    for field in ("defect_location", "requirements", "extends_open_bug", "distinct_defect"):
        check_in(f"K-C6d: the contract section names `{field}`", f"`{field}`", contract_text)
    check_in("K-C6d: the charter names the instrument", "bug_records.py open-bugs", charter)
    # t-2187 I5: the charter no longer names `distinct_defect` (cut by decision); the role is handed the key page slice before the work (FR-38)
    slice_text = (package / "references" / "slices" / "qa-failure-analyst" / "artifact-contract-run.md").read_text(encoding="utf-8")
    check_in("K-C6d: the key page slice the analyst is handed names the way out of the same-place rule", "distinct_defect", slice_text)
    check_in("K-C6d: the claim adds the same-place problems", "BR.same_location_problems(paired)",
             (SCRIPTS / "handoff_check.py").read_text(encoding="utf-8"))


def the_code_reading_draft() -> None:
    root = temp_project("qa-factory-cr-")
    try:
        task = cr_task(root)
        good = cr_draft()
        check_eq("C2 valid question-oracle draft", BR.code_reading_problems(task, good, [("d.json", good)]), [])
        req = cr_draft(oracle={"requirement": "R-24", "quote": "keeps the price shown"})
        check_eq("C2 valid requirement-oracle draft (code_says contradicts, no question settled)", cr_codes(cr_task(root, status="none"), req), [])
        check_eq("C2 requirement oracle with code_says unknown -> R_CR_NO_ORACLE", cr_codes(cr_task(root, status="none", says="unknown"), req), [BR.R_CR_NO_ORACLE])
        check_eq("C2 (C-m2) the code_says cell is read by the S2 parser: extra spaces after the colon are the same cell",
                 cr_codes(cr_task(root, status="none", says="contradicts:  " + CR_FACT), req), [])
        check_eq("C2 (C-m2) ... and another fact id in the cell is still no oracle",
                 cr_codes(cr_task(root, status="none", says="contradicts: other"), req), [BR.R_CR_NO_ORACLE])
        check_eq("C2 requirement oracle naming another R -> R_CR_NO_ORACLE", cr_codes(cr_task(root, status="none"), cr_draft(oracle={"requirement": "R-9", "quote": "x"})), [BR.R_CR_NO_ORACLE])
        for status, why in (("none", "no record: open (P20: the fact alone gives nothing)"), ("open", "reopened"), ("deferred_to_report", "deferred"),
                            ("not_needed", "not_needed is no expectation (C-4)"), ("changed", "changed since the answer"), ("with_designer", "with the designer")):
            check_eq(f"C2 Q7 {why} -> R_CR_NO_ORACLE", cr_codes(cr_task(root, status=status), good), [BR.R_CR_NO_ORACLE])
        task = cr_task(root)
        check_eq("C2 quote not in its source -> R_CR_QUOTE", cr_codes(task, cr_draft(oracle={"question": "Q7", "quote": "the price is whatever"})), [BR.R_CR_QUOTE])
        check_eq("C2 the chosen reading's text is a source of the quote", cr_codes(task, cr_draft(oracle={"question": "Q7", "quote": CR_READING})), [])
        for label, fact in (("unknown id", {"id": "nope", "path": CR_PATH, "line": 103}), ("line differs", {"id": CR_FACT, "path": CR_PATH, "line": 104}),
                            ("path differs", {"id": CR_FACT, "path": "MyBooks/other.ts", "line": 103})):
            check_eq(f"C2 fact {label} -> R_CR_NO_FACT", cr_codes(task, cr_draft(fact=fact)), [BR.R_CR_NO_FACT])
        check_eq("C2 (C-3) two facts with one id: either place matches", [cr_codes(task, cr_draft(fact={"id": "XPANBFLFA-44 AC2 out-of-stock product", "path": p, "line": n}))
                                                                          for p, n in (("MyBooks/src/pages/BookDetailPage.tsx", 170), (CR_PATH, 35))], [[], []])
        check_eq("C2 bundle missing -> R_CR_NO_FACT", cr_codes(cr_task(root, bundle=None), good), [BR.R_CR_NO_FACT])
        check_eq("C2 bundle not JSON -> R_CR_NO_FACT", cr_codes(cr_task(root, bundle="{not json"), good), [BR.R_CR_NO_FACT])
        check_eq("C2 bundle with no list facts -> R_CR_NO_FACT", cr_codes(cr_task(root, bundle=json.dumps({"facts": "x"})), good), [BR.R_CR_NO_FACT])
        task = cr_task(root)
        check_eq('C2 check_state "passed" -> R_CR_CHECK_STATE', cr_codes(task, cr_draft(check_state="passed")), [BR.R_CR_CHECK_STATE])
        check_eq("C2 check_state unverifiable is accepted (AT the list)", cr_codes(task, cr_draft(check_state="unverifiable")), [])
        check_eq("C2 a missing field -> R_CR_FIELDS", cr_codes(task, {k: v for k, v in good.items() if k != "manual_steps"}), [BR.R_CR_FIELDS])
        write(task / "work" / "triage.json", json.dumps({"triage": [{"instance_id": "t1", "attempt_id": "a1", "verdict": "APP_BUG"}]}))
        red = {"title": "red", "violates": "requirement:R-24", "case": "TC-1", "triage_ref": {"instance_id": "t1", "attempt_id": "a1"}}
        check_eq("C2 plus an APP_BUG draft on R-24 -> R_CR_SUPERSEDED", cr_codes(task, good, [("r.json", red)]), [BR.R_CR_SUPERSEDED])
        twin = cr_draft(title="the same bug again")
        check_eq("C2 two code-reading drafts on R-24 -> R_CR_TWICE", cr_codes(task, good, [("e.json", twin)]), [BR.R_CR_TWICE])
        # C-2: a code place S1 did not record, verified by the one resolver
        (root / "src").mkdir(exist_ok=True)
        (root / "src" / "BookDetailPage.tsx").write_text("a\n" * 60 + "  if (!navigator.onLine)   return;\n", encoding="utf-8")
        place = lambda **kw: cr_draft(fact={"path": "src/BookDetailPage.tsx", "line": 61, "quote": "if (!navigator.onLine) return;", **kw})   # noqa: E731
        check_eq("C2 (C-2) a code place whose quote is the line (whitespace-normalized) is accepted", cr_codes(task, place()), [])
        check_eq("C2 (C-2) a code place with another quote -> R_CR_NO_FACT", cr_codes(task, place(quote="return null;")), [BR.R_CR_NO_FACT])
        check_eq("C2 (C-2) a code place with no such file -> R_CR_NO_FACT", cr_codes(task, place(path="src/Nope.tsx")), [BR.R_CR_NO_FACT])
        check_eq("C2 pair_drafts lists it under code_reading and asks no triage row of it",
                 (BR.pair_drafts([("d.json", good)], [])["code_reading"], BR.pair_drafts([("d.json", good)], [])["no_row"]), (["d.json"], []))
        check_eq("C2 `Code-Reading` is no code-reading draft (the triage road refuses it)", (BR.is_code_reading(cr_draft(evidence="Code-Reading")), BR.pair_drafts([("d.json", cr_draft(evidence="Code-Reading"))], [])["no_row"]), (False, ["d.json"]))
        check_eq("C2 reproduction entries leave it unconfirmed (E-19)", BR.confirmation_of(task, cr_draft(reproduction=[{"kind": "own_script", "evidence": "evidence/x", "observed": "y"}]))[0], "unconfirmed")
    finally:
        cleanup(root)
    contract_text = (SCRIPTS.parent / "references" / "artifact-contract-run.md").read_text(encoding="utf-8")
    import contract as C
    check("C1 the contract text names every field of BUG_DRAFT_CODE_READING_REQUIRED", all(f"\"{f}\"" in contract_text for f in C.BUG_DRAFT_CODE_READING_REQUIRED))
    analyst = (SCRIPTS.parent / "agents" / "qa-failure-analyst.md").read_text(encoding="utf-8")
    names = lambda text: all(w in text for w in ("code-reading", "SETTLED", "code_says", "No oracle, no draft"))   # noqa: E731
    check("C6 the analyst charter names evidence code-reading, settled, code_says and `no oracle`", names(analyst))
    check("C6 (C-R1) the analyst charter names the code-place form `{path, line, quote}` beside `facts[]`", "code place you read (`{path, line, quote}`)" in analyst)
    check("C6 (C-R1) negative control: the same key on a copy without it fails", "code place you read (`{path, line, quote}`)" not in analyst.replace("code place you read", ""))
    check("C6 negative control: the same assertion on a copy without `No oracle, no draft` fails", not names(analyst.replace("No oracle, no draft", "")))


def one_bug_many_manifestations_n2() -> None:
    """t-2187 N2: the pairing through manifestations (5.1), the same-place door (5.16), the bug text (5.17), the merge that cannot be
    re-read (`merged_unconfirmed`, F-2 (a)), A2 (the statement) and the first-manifestation row by instance. Mutations (named, not run):
    `keys` without the manifestations -> M1; `_blocker_cover` reads `draft.get("cases")` -> M3; a manifestation covers a blocked row -> M2;
    `bug_text` always adds the sections -> M6 (golden); `merged_unconfirmed` counts one manifestation -> M5."""
    rows = [{"instance_id": f"t_{n}", "attempt_id": "a1", "case": f"TC-{n}", "verdict": "APP_BUG"} for n in (1, 2, 3)]
    rows.append({"instance_id": "t_9", "attempt_id": "a1", "case": "TC-9", "verdict": "NO_DEFECT"})
    row = lambda n, att="a1": {"instance_id": f"t_{n}", "attempt_id": att}   # noqa: E731

    def man(n, **over):
        return {**{"action": f"type {n}", "start_state": "erased", "seen": "11", "requirement": "R-1", "case": f"TC-{n}",
                   "triage_row": row(n), "evidence": f"work/evidence/manual/TC-{n}/a1/1.txt", "red_test_none": "manual"}, **over}

    def dr(*mans, **over):
        return {**{"title": "t", "triage_ref": row(1), "case": "TC-1", "manifestations": list(mans)}, **over}
    # M1: three APP_BUG rows, one draft naming all three as manifestations
    got = BR.pair_drafts([("m.json", dr(man(1), man(2), man(3)))], rows)
    check_eq("N2 5.1: three rows, one merged draft: no row is owed a draft", (got["app_bug_without_draft"], got["manifestation_no_row"], got["manifestation_not_app_bug"]), ([], [], []))
    check_eq("N2 5.1: without the manifestations two rows are owed (control)", BR.pair_drafts([("m.json", {"triage_ref": row(1)})], rows)["app_bug_without_draft"], ["t_2@a1", "t_3@a1"])
    got = BR.pair_drafts([("m.json", dr(man(1), man(9), man(2, triage_row={"instance_id": "zzz", "attempt_id": "a1"})))], rows)
    check_eq("N2 5.1: a NO_DEFECT row -> manifestation_not_app_bug; an unknown row -> manifestation_no_row; neither covers",
             (got["manifestation_not_app_bug"], got["manifestation_no_row"], got["app_bug_without_draft"]),
             ([("m.json", "t_9@a1", ["NO_DEFECT"])], [("m.json", "zzz@a1")], ["t_2@a1", "t_3@a1"]))
    got = BR.pair_drafts([("m.json", dr(man(1), man(2, triage_row="t_2"), man(2, triage_row="t_2@a1"), man(3, triage_row=None, probe={"case": "x"})))], rows)
    check_eq("N2 5.1: a bare instance covers every attempt; one row listed twice is one coverage and no error; a probe covers nothing",
             (got["app_bug_without_draft"], got["manifestation_no_row"]), (["t_3@a1"], []))
    got = BR.pair_drafts([("m.json", dr(man(1), "x", 4, {"triage_row": None}))], rows)
    check_eq("N2 5.1: an entry that is not an object, or names no row, covers nothing and breaks nothing",
             (got["app_bug_without_draft"], got["manifestation_no_row"]), (["t_2@a1", "t_3@a1"], []))
    check_eq("N2 5.1: `manifestations` that is not a list is read as none",
             BR.pair_drafts([("m.json", dr(man(1), manifestations="x"))], rows)["app_bug_without_draft"], ["t_2@a1", "t_3@a1"])
    got = BR.pair_drafts([("a.json", dr(man(2))), ("b.json", dr(man(2), triage_ref=row(3), case="TC-3"))], rows)
    check_eq("N2 5.1 (F-3): one row in two drafts' manifestations is no error", (got["app_bug_without_draft"], got["manifestation_no_row"]), ([], []))
    check_eq("N2 5.1: a code-reading draft's manifestations cover nothing (it rests on no row)",
             BR.pair_drafts([("c.json", {"evidence": "code-reading", "manifestations": [man(2)]})], rows)["app_bug_without_draft"], ["t_1@a1", "t_2@a1", "t_3@a1"])
    # M2: a manifestation never covers a row with `blocking_check`
    blocked = [rows[0], dict(rows[2], blocking_check="TC-1")]
    got = BR.pair_drafts([("m.json", dr(man(1), man(3, case="TC-77")))], blocked)
    check_eq("N2 5.1: a manifestation naming a blocked row (its case not listed) is NOT coverage: the blocker rule speaks (the draft misses the case)",
             got["blocker_draft_misses_case"], [("TC-3", "TC-1")])
    got_no_blocker_draft = BR.pair_drafts([("m.json", {"title": "t", "triage_ref": row(2), "manifestations": [man(3, case="TC-77")]})], blocked)
    check_eq("N2 5.1: ... and where the blocker has no draft the manifestation does not cover the blocked row either",
             got_no_blocker_draft["app_bug_without_draft"], ["t_1@a1", "t_3@a1"])
    got = BR.pair_drafts([("m.json", dr(man(1), cases=["TC-1", "TC-3"]))], blocked)
    check_eq("N2 5.1: ... the blocker's `cases` covers it", (got["app_bug_without_draft"], got["blocker_draft_misses_case"]), ([], []))
    # M3: _blocker_cover reads the union (a case only in `manifestations[].case`)
    got = BR.pair_drafts([("m.json", dr(man(1), man(3, triage_row=None, probe={"case": "p"})))], blocked)
    check_eq("N2 5.1: the blocked row's case sits only in `manifestations[].case` of the blocker's draft -> covered",
             (got["app_bug_without_draft"], got["blocker_draft_misses_case"]), ([], []))
    got = BR.pair_drafts([("m.json", dr(man(1)))], blocked)
    check_eq("N2 5.1: ... and without it the draft misses the case", got["blocker_draft_misses_case"], [("TC-3", "TC-1")])
    # purity: pair_drafts reads no file
    import builtins
    plain = BR.pair_drafts([("m.json", dr(man(1), man(2)))], rows)
    real_open, real_read = builtins.open, Path.read_text

    def no_read(*a, **k):
        raise AssertionError("pair_drafts read a file")
    builtins.open, Path.read_text = no_read, no_read
    try:
        pure = BR.pair_drafts([("m.json", dr(man(1), man(2)))], rows)
    finally:
        builtins.open, Path.read_text = real_open, real_read
    check_eq("N2 5.1: pair_drafts is pure: the same dict with open and Path.read_text patched to raise", pure, plain)
    # 5.16: the same-place door
    place = lambda n, **o: {"triage_ref": row(n), "defect_location": "src/x.ts:1", "case": f"TC-{n}", **o}   # noqa: E731
    line = BR.same_location_problems(BR.pair_drafts([("a.json", place(1)), ("b.json", place(2))], rows))[0]
    check("N2 5.16: the refusal names the manifestations door and the distinct_defect door", "`manifestations` hold every row" in line and "distinct_defect: <why>" in line, line)
    got = BR.pair_drafts([("a.json", place(1, manifestations=[man(1), man(2), man(3)]))], rows)
    check_eq("N2 5.16: merged into one draft with every row as a manifestation: no same_location, no row owed", (got["same_location"], got["app_bug_without_draft"]), ([], []))
    said = 'the person said these are different bugs at gate B: "split them"'
    got = BR.pair_drafts([("a.json", place(1, distinct_defect=said)), ("b.json", place(2, distinct_defect=said)), ("c.json", place(3, distinct_defect=said))], rows)
    check_eq("N2 5.16: the split with the person's words: no same_location, one draft per row", (got["same_location"], got["app_bug_without_draft"]), ([], []))
    # 5.17: the bug text
    single = {"title": "Qty", "impact": "degraded", "manual_steps": ["open", "type -1"], "expected": "rejected", "actual": "11"}
    sure = BR.reproduction_words({"confirmation": "unconfirmed", "reproduced_how": [], "reproduction_problems": []})
    golden = ("# Qty\n\nImpact: degraded - priority P2\n\n## Steps to see it\n1. open\n2. type -1\n\n## Expected\nrejected\n\n"
              "## What was seen\n11\n\n## How sure the factory is\n" + sure + "\n")
    check_eq("N2 5.17: a draft with no manifestations: today's bytes", BR.bug_text(single, "P2", "unconfirmed", [], []), golden)
    check_eq("N2 5.17: ... with ONE manifestation (and a mechanism): today's bytes",
             BR.bug_text({**single, "manifestations": [man(1)], "mechanism": {"status": "confirmed", "statement": "s"}}, "P2", "unconfirmed", [], []), golden)
    cause = {"statement": "the field turns an invalid value into 1", "status": "confirmed", "why": "",
             "basis": [{"id": "b1", "kind": "code_line", "path": "p", "line": 1, "quote": "q"},
                       {"id": "b2", "kind": "run", "start_state": "erased"}, {"id": "b3", "kind": "run", "start_state": "selected"}],
             "claims": [{"says": "paste behaves the same", "confirmed_by": []}, {"says": "typing is the cause", "confirmed_by": ["b1"]}]}
    seven = [man(1, action=f"way {n}", requirement="R-8" if n else None, red_test={"path": "t.py", "command": f"pytest t.py::t{n}"} if n % 2 else None,
                 red_test_none=None if n % 2 else "manual check only") for n in range(7)]
    text = BR.bug_text({**single, "mechanism": cause, "manifestations": seven}, "P2", "unconfirmed", [], [])
    check_eq("N2 5.17: the merged text starts with today's bytes", text.startswith(golden.rstrip("\n")), True)
    section = text.split("## Manifestations\n", 1)[1].splitlines()
    check_eq("N2 5.17: seven manifestations -> seven lines, all of them (no cap), then the closing sentence",
             [ln.split(".", 1)[0] for ln in section[:-1] if ln], [str(n) for n in range(1, 8)])
    check_eq("N8 I4 (spec 8.4): the section closes with the re-check sentence, once",
             (section[-1], text.count("After the fix, re-check every manifestation; one that still fails is a separate bug.")),
             ("After the fix, re-check every manifestation; one that still fails is a separate bug.", 1))
    check_not_in("N8 I4: a single-manifestation text has no re-check sentence (the golden above is byte-equal)", "re-check every manifestation", golden)
    check("N2 5.17: a line holds action, start state, seen, requirement and the red test or the reason there is none",
          all(w in section[0] for w in ("way 0", "start: erased", "seen: 11", "no requirement named", "no test: manual check only"))
          and all(w in section[1] for w in ("way 1", "as requirement R-8 says", "red test: pytest t.py::t1")), section[:2])
    check("N2 5.17: ## Cause: the statement, how confirmed in words (code line and two starting states), the unverified claim only",
          all(w in text for w in ("## Cause\nthe field turns an invalid value into 1\nConfirmed by the line of the application code that does it and by trying it from two starting states.",
                                  "Not verified: paste behaves the same")) and "Not verified: typing is the cause" not in text, text)
    check_not_in("N2 5.17: no field name or JSON in the text", "manifestations", text)
    unknown = BR.bug_text({**single, "mechanism": {"status": "unknown", "why": "only one start state was run"}, "manifestations": seven[:2]}, "", "", [], [])
    check_in("N2 5.17: an unknown cause is never printed as one", "Cause not established: only one start state was run.", unknown)
    check_in("N2 5.17: an unverified one says what is missing", "What is missing: no code", BR.bug_text(
        {**single, "mechanism": {"status": "unverified", "statement": "maybe", "why": "no code"}, "manifestations": seven[:2]}, "", "", [], []))
    check_in("N2 5.17: no mechanism at all with two manifestations says so", "Cause not established:", BR.bug_text({**single, "manifestations": seven[:2]}, "", "", [], []))
    # merged_unconfirmed (F-2 (a)) and A2 / the first-manifestation row
    root = temp_project("qa-factory-n2-")
    try:
        (root / "src").mkdir(exist_ok=True)
        (root / "src" / "P.tsx").write_text("a\nconst q = f(1);\n", encoding="utf-8")
        task = root / "qa-factory" / "artifacts" / "T-1"
        task.mkdir(parents=True)
        good = {"statement": "s", "status": "confirmed", "basis": [{"id": "b1", "kind": "code_line", "path": "src/P.tsx", "line": 2, "quote": "const q = f(1);"}]}
        bad = {**good, "basis": [{"id": "b1", "kind": "code_line", "path": "src/P.tsx", "line": 2, "quote": "nope"}]}
        two = lambda mech=None, **o: dr(man(1), man(2), **({"mechanism": mech} if mech is not None else {}), **o)   # noqa: E731
        check_eq("N2 F-2: a merge whose basis stands, and a draft with one manifestation, are not listed",
                 BR.merged_unconfirmed(task, [("ok.json", two(good)), ("one.json", dr(man(1), mechanism=bad)), ("old.json", {"title": "t"}), ("junk", None)]), [])
        got = BR.merged_unconfirmed(task, [("bad.json", two(bad)), ("none.json", two()), ("unk.json", two({"status": "unknown", "why": "w"})),
                                           ("typo.json", two({**good, "status": "Confirmed"})), ("shape.json", two("x")),
                                           ("person.json", two({**good, "basis": [{"id": "p1", "kind": "person", "quote": "one bug"}]}))])
        check_eq("N2 F-2: a broken basis, no mechanism, status unknown, a typo, a shape, a person word nobody recorded: each listed once",
                 [name for name, _why in got], ["bad.json", "none.json", "unk.json", "typo.json", "shape.json", "person.json"])
        check("N2 F-2: the first problem is named", BR.R_MECH_CODE_LINE in got[0][1] and "no `mechanism`" in got[1][1] and "not confirmed" in got[2][1], got)
        check_eq("N2 F-2: `manifestations` of 2+ junk items counts (an unreadable merge is not a pass)", [n for n, _ in BR.merged_unconfirmed(task, [("j.json", {"manifestations": ["x", 3]})])], ["j.json"])
        check_eq("N2 A2: confirmed with no statement, and unverified with a blank one, are refused; unknown needs none",
                 [[c for c, _d in BR.mechanism_problems(task, dr(man(1), mechanism=m))] for m in
                  ({**good, "statement": ""}, {k: v for k, v in good.items() if k != "statement"}, {"status": "unverified", "statement": "  ", "why": "w"},
                   {"status": "unknown", "why": "w"}, {**good, "statement": 5})],
                 [[BR.R_MECH_STATEMENT], [BR.R_MECH_STATEMENT], [BR.R_MECH_STATEMENT], [], [BR.R_MECH_SHAPE]])
        first = lambda ref, row_: [c for c, _d in BR.manifestation_problems(task, dr(man(1, triage_row=row_), triage_ref=ref), rows)]   # noqa: E731
        check_eq("N2 first row: a bare instance on either side and the full key of it are ONE row; another instance or attempt is not",
                 [first("t_1", row(1)), first(row(1), "t_1"), first("t_1", "t_1"), first(row(1), row(1)), first(row(2), "t_1"), first("t_1@a2", row(1))],
                 [[], [], [], [], [BR.R_MAN_PRIMARY], [BR.R_MAN_PRIMARY]])
        check_eq("N2 first row: a first entry that is a probe is still not the draft's own row",
                 [c for c, _d in BR.manifestation_problems(task, dr(man(1, triage_row=None, probe={"case": "c"}), triage_ref=row(1)), rows)][-1], BR.R_MAN_PRIMARY)
    finally:
        cleanup(root)


def main() -> None:
    root = temp_project("qa-factory-bugs-")
    extra = []
    try:
        proj_bugs = root / "qa-factory" / "bugs"
        a = story(root, "STORY-A", "gateB-A")
        b = story(root, "STORY-B", "gateB-B")
        # STORY-A: its own BUG-1 (also filed in the project home), BUG-2 only in the project home.
        write(a / "bugs" / "BUG-1.md", bug_md("BUG-1", "A: filter not visible", "gateB-A", "confirmed_by_person"))
        write(proj_bugs / "BUG-1.md", bug_md("BUG-1", "A: filter not visible", "gateB-A", "confirmed_by_person"))
        write(proj_bugs / "BUG-2.md", bug_md("BUG-2", "A: second bug", "gateB-A", "unconfirmed",
                                             found_by="STORY-A_TC_003"))
        # STORY-B: a different bug with the same file name, one more only in the project home.
        write(b / "bugs" / "BUG-1.md", bug_md("BUG-1", "B: payload limit", "gateB-B"))
        write(proj_bugs / "BUG-3.md", bug_md("BUG-3", "B: third", "gateB-B", found_by="STORY-B_TC_003"))
        # Nobody's: no decision id (mentions TC_003 of story A) and another story's id.
        write(proj_bugs / "BUG-4.md", bug_md("BUG-4", "orphan", None, found_by="STORY-A_TC_003"))
        write(proj_bugs / "BUG-5.md", bug_md("BUG-5", "elsewhere", "gateB-C", found_by="STORY-A_TC_003"))
        before = snapshot(root)
        ra = BR.story_bugs(a)
        rb = BR.story_bugs(b)
        check_eq("edge 10: the reader writes nothing (tree snapshot before == after)", snapshot(root), before)
        check_eq("edge 10: same input, same answer", BR.story_bugs(a), ra)

        # --- shape ---------------------------------------------------------------------------
        check_eq("shape: the named keys", sorted(ra),
                 ["gate_b_decision_id", "gate_b_decision_ids", "outside_home", "records", "sources",
                  "unattributed"])
        check_eq("owner decision: a record in both homes and a project-only record are not outside_home",
                 ra["outside_home"], [])
        check_eq("shape: the gate B id the project files were joined on", ra["gate_b_decision_id"], "gateB-A")
        check_eq("shape: the set of gate B ids (a sorted list), from pipeline.json alone here",
                 ra["gate_b_decision_ids"], ["gateB-A"])
        check_eq("sources: no controller file, so the ids are said to come from pipeline.json alone",
                 (source(ra, "project")["gate_b_ids_from"], "gate_b_ids_note" in source(ra, "project")),
                 ("pipeline.json gates.B.id only", True))
        for name, record in (("BUG-1", by_id(ra, "BUG-1")), ("BUG-2", by_id(ra, "BUG-2"))):
            check(f"edge 8: record {name} carries id, title, state, paths, homes",
                  all(k in record for k in ("id", "title", "confirmation", "state", "paths", "homes")),
                  str(record))

        # --- edge 1: the two homes and their sources -----------------------------------------
        check_eq("edge 1: sources name the three places looked at",
                 [s["home"] for s in ra["sources"]], ["task", "project", "drafts"])
        check("edge 1: task and project homes are marked as existing",
              source(ra, "task")["exists"] and source(ra, "project")["exists"], str(ra["sources"]))
        check("edge 1: an absent drafts directory is named, not skipped",
              source(ra, "drafts")["exists"] is False, str(ra["sources"]))
        check_eq("edge 1: the project home's counts are reported (5 files, 2 counted, 1 unattributed, 2 other id)",
                 (source(ra, "project")["files"], source(ra, "project")["counted"],
                  source(ra, "project")["unattributed"], source(ra, "project")["other_id"]), (5, 2, 1, 2))

        # --- edge 2: the task folder is the story's ------------------------------------------
        check("edge 2: the file in the task folder is a record", "BUG-1" in ids(ra), str(ids(ra)))
        check("edge 2: STORY-B's own BUG-1 is a record of B", by_id(rb, "BUG-1").get("title") == "B: payload limit",
              str(rb["records"]))

        # --- edge 3: the project home joins on the gate B id ---------------------------------
        check_eq("edge 3: story A counts its own two bugs and no others", ids(ra), ["BUG-1", "BUG-2"])
        check_eq("edge 3: BUG-2 is a project-home record, joined on the decision id",
                 by_id(ra, "BUG-2").get("homes"), ["project"])
        check("edge 3: another story's project bug (BUG-3, gateB-B) is not counted for A",
              "BUG-3" not in ids(ra), str(ids(ra)))
        check("edge 3: a bug that carries a third story's id (BUG-5) is not counted",
              "BUG-5" not in ids(ra), str(ids(ra)))
        check("edge 3: and it is not listed as unattributed either (it has an id)",
              all(u["id"] != "BUG-5" for u in ra["unattributed"]), str(ra["unattributed"]))
        check_eq("edge 3: a project file with no decision id is unattributed", [u["id"] for u in ra["unattributed"]],
                 ["BUG-4"])
        check("edge 3: and it is not counted for the story (mentions story A's TC_003)",
              "BUG-4" not in ids(ra), str(ids(ra)))
        check_eq("edge 3: story B counts BUG-1 (task folder) and BUG-3 (its decision id)", ids(rb), ["BUG-1", "BUG-3"])
        check("edge 3: story A's project BUG-1 (gateB-A) is not counted for B",
              len(by_id(rb, "BUG-1")["paths"]) == 1 and "STORY-B" in by_id(rb, "BUG-1")["paths"][0],
              str(rb["records"]))

        # --- edge 5: the same bug in both homes is one record --------------------------------
        one = by_id(ra, "BUG-1")
        check_eq("edge 5: a copy in both homes is ONE record", ids(ra).count("BUG-1"), 1)
        check_eq("edge 5: its homes name both", one["homes"], ["task", "project"])
        check("owner decision: the project copy (the canonical home) is named first in paths",
              len(one["paths"]) == 2 and one["paths"][0].endswith("qa-factory/bugs/BUG-1.md")
              and "artifacts/STORY-A/bugs/BUG-1.md" in one["paths"][1], str(one["paths"]))
        check_eq("edge 5: same file name, different decision ids: two bugs, one per story "
                 "(A's and B's BUG-1 titles differ)",
                 (by_id(ra, "BUG-1")["title"], by_id(rb, "BUG-1")["title"]),
                 ("A: filter not visible", "B: payload limit"))

        # --- edge 8: the confirmed / unconfirmed rule is the contract's ----------------------
        check_eq("edge 8: no `confirmation` reads confirmed (contract default)", by_id(rb, "BUG-3")["state"], "confirmed")
        check_eq("edge 8: `unconfirmed` reads unconfirmed", (by_id(ra, "BUG-2")["state"],
                                                              by_id(ra, "BUG-2")["confirmation"]),
                 ("unconfirmed", "unconfirmed"))
        check_eq("edge 8: `confirmed_by_person` reads confirmed", by_id(ra, "BUG-1")["state"], "confirmed")
        check_eq("edge 8: the headline traceability prints over these records",
                 T.bug_headline(ra["records"]), "Product bugs — 1 confirmed · 1 unconfirmed.")
        via_traceability = {r["id"]: r["confirmation"] for r in T.bug_records(a, a)}
        check_eq("edge 8: one rule - the task folder read by traceability.bug_records gives the same value",
                 via_traceability, {"BUG-1": by_id(ra, "BUG-1")["confirmation"]})

        # --- edge 9: no matching on a case id or a bare BUG number ---------------------------
        check("edge 9: BUG-4 names STORY-A_TC_003 in found_by and is still not a record of A",
              "BUG-4" not in ids(ra))
        check("edge 9: the same BUG-1 in two stories are two bugs (each story sees only its own file)",
              by_id(ra, "BUG-1")["paths"][:1] != by_id(rb, "BUG-1")["paths"][:1])

        # --- edge 1 again: nothing at all, no project, no story ------------------------------
        empty = story(root, "STORY-EMPTY", "gateB-E")
        nothing = BR.story_bugs(empty)
        check_eq("edge 1: no bug directory of the story and a project home with other stories' bugs: zero records",
                 nothing["records"], [])
        bare = temp_dir("qa-factory-bugs-bare-")      # NOT a project on purpose: the bug records' "no project" refusals (t-617 section 8.2)
        extra.append(bare)
        try:
            gone = BR.story_bugs(bare / "no-such-task")
            check_eq("edge 1: a task root that does not exist: zero records, no exception", gone["records"], [])
            check("edge 1: and the sources say nothing exists",
                  not any(s["exists"] for s in gone["sources"]), str(gone["sources"]))
            check("edge 1: no project root above the task folder is named in the sources",
                  source(gone, "project")["path"] is None and "note" in source(gone, "project"), str(gone["sources"]))
        except Exception as exc:  # noqa: BLE001
            check("edge 1: a task root that does not exist: no exception", False, repr(exc))
        lone = bare / "task-without-project"
        write(lone / "bugs" / "BUG-1.md", bug_md("BUG-1", "lonely"))
        check_eq("edge 1: no project root at all: the task folder's bug is still a record",
                 ids(BR.story_bugs(lone)), ["BUG-1"])
        check_eq("edge 1 (t-622): the home of a story under a project is found by the one walk, runtime_paths.nearest_project",
                 BR._project_home(story(root, "STORY-HOME", None), None), Path(root).resolve() / "qa-factory" / "bugs")
        check_eq("edge 1 (t-622): ...and a story under no project has no home - None, never its own folder",
                 BR._project_home(lone, None), None)

        # --- edge 4: the story has no gate B record yet --------------------------------------
        for n, (label, content) in enumerate((
                ("no pipeline.json", None), ("invalid JSON", "{not json"),
                ("gates.B without an id (old record)", json.dumps({"gates": {"B": {"decision": "approve"}}})),
                ("gates.B id empty", json.dumps({"gates": {"B": {"id": "  "}}})),
                ("gates is not an object", json.dumps({"gates": []})),
                ("pipeline is not an object", json.dumps([1, 2])))):
            t = story(root, f"NOGATE-{n}", None)
            if content is not None:
                write(t / "pipeline.json", content)
            write(t / "bugs" / "BUG-9.md", bug_md("BUG-9", "task-folder bug", None))
            r = BR.story_bugs(t)
            check_eq(f"edge 4 ({label}): the task folder's file is still a record; no project file is counted",
                     ids(r), ["BUG-9"])
            check_eq(f"edge 4 ({label}): only the file without an id is unattributed",
                     [u["id"] for u in r["unattributed"]], ["BUG-4"])
            check_eq(f"edge 4 ({label}): the gate id reads empty", r["gate_b_decision_id"], "")

        # --- edge 6: unreadable front matter, not UTF-8, empty ------------------------------
        weird = story(root, "STORY-WEIRD", "gateB-W")
        write(weird / "bugs" / "BUG-1.md", "no front matter at all\njust a body\n")
        (weird / "bugs").joinpath("BUG-2.md").write_bytes(b"\xff\xfe\x00 not utf-8 \x80\x81")
        (weird / "bugs").joinpath("BUG-3.md").write_bytes(b"")
        write(weird / "bugs" / "BUG-4.md", "---\nid: BUG-4\nseverity: major\n---\nbody without a title\n")
        write(weird / "bugs" / "BUG-5.md", "---\ntitle: unterminated front matter\nid: BUG-5\n")
        rw = BR.story_bugs(weird)
        check_eq("edge 6: every unreadable task-folder file is a record (never dropped)",
                 ids(rw), ["BUG-1", "BUG-2", "BUG-3", "BUG-4", "BUG-5"])
        check_eq("edge 6: it is labelled 'title unreadable' (no front matter, not UTF-8, empty, no title, unterminated)",
                 [r["title"] for r in rw["records"]], ["title unreadable"] * 5)
        check_eq("edge 6: and it still carries its path and home",
                 [(len(r["paths"]), r["homes"]) for r in rw["records"]], [(1, ["task"])] * 5)
        check_eq("edge 3 (unreadable): an unreadable task-folder file has state unknown and is in NEITHER "
                 "group; a readable file that only lacks `confirmation` (BUG-4) takes the contract default",
                 groups(rw), {"confirmed": ["BUG-4"], "unconfirmed": [], "unknown": ["BUG-1", "BUG-2", "BUG-3", "BUG-5"]})
        check_eq("edge 3 (unreadable): its confirmation is not defaulted to confirmed_by_person",
                 [by_id(rw, n)["confirmation"] for n in ("BUG-1", "BUG-2", "BUG-3", "BUG-5")], ["unknown"] * 4)
        write(proj_bugs / "BUG-6.md", "not a bug file, no front matter")
        (proj_bugs / "BUG-7.md").write_bytes(b"\xff\xfe\x00\x80")
        (proj_bugs / "BUG-8.md").write_bytes(b"")
        rw = BR.story_bugs(weird)
        check_eq("edge 6: unreadable files in the project home are unattributed, never counted",
                 (sorted(u["id"] for u in rw["unattributed"] if u["id"] in ("BUG-6", "BUG-7", "BUG-8")),
                  [i for i in ids(rw) if i in ("BUG-6", "BUG-7", "BUG-8")]),
                 (["BUG-6", "BUG-7", "BUG-8"], []))
        check_eq("edge 6: their reason says the front matter is unreadable",
                 {u["reason"] for u in rw["unattributed"] if u["id"] in ("BUG-6", "BUG-7", "BUG-8")},
                 {"front matter unreadable"})
        for name in ("BUG-6.md", "BUG-7.md", "BUG-8.md"):
            (proj_bugs / name).unlink()

        # --- edge 5 (edge of the edge): the task copy is unreadable, the project copy joins ---
        merge = story(root, "STORY-MERGE", "gateB-M")
        (merge / "bugs").mkdir()
        (merge / "bugs" / "BUG-11.md").write_bytes(b"\xff\xfe")
        write(proj_bugs / "BUG-11.md", bug_md("BUG-11", "read from the project copy", "gateB-M", "unconfirmed"))
        rm = BR.story_bugs(merge)
        check_eq("edge 4: an unreadable task copy and a readable project copy are NOT merged (ids cannot "
                 "be equal): two records, the task one unknown, the project one read as it is",
                 sorted((r["title"], r["state"], tuple(r["homes"])) for r in rm["records"]),
                 [("read from the project copy", "unconfirmed", ("project",)),
                  ("title unreadable", "unknown", ("task",))])
        check_eq("edge 4: each of the two carries a note that names the other",
                 [len(r["notes"]) for r in rm["records"]], [1, 1])
        write(merge / "bugs" / "BUG-12.md", bug_md("BUG-12", "task copy", "gateB-OLD"))
        write(proj_bugs / "BUG-12.md", bug_md("BUG-12", "project copy", "gateB-M"))
        rm = BR.story_bugs(merge)
        twelve = [r for r in rm["records"] if r["id"] == "BUG-12"]
        check_eq("edge 4 (same name, different ids): two records, not one",
                 sorted(r["title"] for r in twelve), ["project copy", "task copy"])
        check("edge 4: each note names the other file's path and id",
              all(len(r["notes"]) == 1 for r in twelve)
              and any("qa-factory/bugs/BUG-12.md" in n and "gateB-M" in n
                      for r in twelve if r["title"] == "task copy" for n in r["notes"])
              and any("artifacts/STORY-MERGE/bugs/BUG-12.md" in n and "gateB-OLD" in n
                      for r in twelve if r["title"] == "project copy" for n in r["notes"]),
              str([r["notes"] for r in twelve]))
        (proj_bugs / "BUG-11.md").unlink()
        (proj_bugs / "BUG-12.md").unlink()

        # --- the owner's home: the project's qa-factory/bugs; a task-folder-only record is outside ---
        check_eq("owner decision: outside_home lists the records that exist ONLY in the story's folder "
                 "(B: BUG-1), each with its path and a plain sentence",
                 [(o["id"], len(o["paths"]), "STORY-B" in o["paths"][0], "story's own folder" in o["reason"])
                  for o in rb["outside_home"]], [("BUG-1", 1, True, True)])
        check("owner decision: a task-folder-only record is still counted (never hidden by its folder)",
              "BUG-1" in ids(rb) and by_id(rb, "BUG-1")["homes"] == ["task"], str(rb["records"]))
        check_eq("owner decision: a record only in the project home is normal (not outside_home)",
                 [o["id"] for o in ra["outside_home"]], [])
        check_eq("owner decision: a story with no project home at all lists its task-folder bug as outside",
                 [o["id"] for o in BR.story_bugs(lone)["outside_home"]], ["BUG-1"])

        # --- gate B decided twice: every decision of the story joins -----------------------------
        two = story(root, "T", "gateB-T-1-2")
        controller(two, [("gateA-T", "A"), ("gateB-T-1", "B"), ("gateB-T-1-2", "B", "approved")])
        write(proj_bugs / "BUG-40.md", bug_md("BUG-40", "filed under the first decision", "gateB-T-1"))
        write(proj_bugs / "BUG-41.md", bug_md("BUG-41", "filed under the second decision", "gateB-T-1-2"))
        write(proj_bugs / "BUG-42.md", bug_md("BUG-42", "another story", "gateB-U-1"))
        write(proj_bugs / "BUG-43.md", bug_md("BUG-43", "gate A id", "gateA-T"))
        rt = BR.story_bugs(two)
        check_eq("gate B decided twice: a bug of the FIRST decision is counted, and the second's; not another "
                 "story's, not a gate A id", ids(rt), ["BUG-40", "BUG-41"])
        check_eq("gate B decided twice: the ids are a sorted list, the latest one is kept for a single value",
                 (rt["gate_b_decision_ids"], rt["gate_b_decision_id"]), (["gateB-T-1", "gateB-T-1-2"], "gateB-T-1-2"))
        check_eq("gate B decided twice: the sources say the ids came from the controller's decisions",
                 (source(rt, "project")["gate_b_ids_from"], "gate_b_ids_note" in source(rt, "project"),
                  source(rt, "project")["counted"], source(rt, "project")["other_id"]), ("controller decisions", False, 2, 6))   # other_id: BUG-1,2,3,5 (A/B/C ids) + 42, 43
        write(two / "state" / "controller.json", "{not json")
        rt = BR.story_bugs(two)
        check_eq("gate B decided twice, controller unreadable: falls back to gates.B.id alone and says so",
                 (ids(rt), rt["gate_b_decision_ids"], source(rt, "project")["gate_b_ids_from"],
                  "gate_b_ids_note" in source(rt, "project")),
                 (["BUG-41"], ["gateB-T-1-2"], "pipeline.json gates.B.id only", True))
        write(two / "state" / "controller.json", json.dumps({"decisions": []}))
        check_eq("gate B decided twice, `decisions` not an object: the same fallback",
                 BR.story_bugs(two)["gate_b_decision_ids"], ["gateB-T-1-2"])
        # the controller alone (pipeline.json has no gate B yet): the latest is the longest id
        solo = story(root, "T2", None)
        controller(solo, [("gateB-T2", "B"), ("gateB-T2-2", "B"), ("gateB-T2-10", "B"), ("gateB-T2-3", "B")])
        rs = BR.story_bugs(solo)
        check_eq("gate B ids from the controller alone: every one, the latest by growth (-10 after -3)",
                 (rs["gate_b_decision_ids"], rs["gate_b_decision_id"]),
                 (["gateB-T2", "gateB-T2-10", "gateB-T2-2", "gateB-T2-3"], "gateB-T2-10"))
        for n in ("BUG-40", "BUG-41", "BUG-42", "BUG-43"):
            (proj_bugs / f"{n}.md").unlink()

        # --- file patterns: both homes read *BUG-*.md; a README is not a bug ----------------------
        rd_me = story(root, "STORY-README", "gateB-R")
        write(rd_me / "bugs" / "BUG-1.md", bug_md("BUG-1", "real bug", "gateB-R"))
        write(rd_me / "bugs" / "README.md", "# bugs of this story\nnot a bug\n")
        write(rd_me / "bugs" / "notes.md", "---\ntitle: notes\n---\n")
        write(proj_bugs / "README.md", "# the project's bugs\n")
        rr = BR.story_bugs(rd_me)
        check_eq("file patterns: a README and another .md in the task bug folder are not records",
                 ids(rr), ["BUG-1"])
        check_eq("file patterns: they are listed in sources as not a bug file, task and project home",
                 (source(rr, "task")["not_a_bug_file"], source(rr, "project")["not_a_bug_file"],
                  source(rr, "task")["files"], source(rr, "project")["files"]),
                 (["README.md", "notes.md"], ["README.md"], 1, 5))
        check("file patterns: a README in the project home is not unattributed either",
              all(u["id"] != "README" for u in rr["unattributed"]), str(rr["unattributed"]))
        (proj_bugs / "README.md").unlink()

        # --- ticket-less ids ----------------------------------------------------------------------
        hand = story(root, "STORY-HAND", "B")
        write(hand / "bugs" / "BUG-31.md", bug_md("BUG-31", "held by the story's own file", "B"))
        write(proj_bugs / "BUG-31.md", bug_md("BUG-31", "held by the story's own file", "B"))
        write(proj_bugs / "BUG-30.md", bug_md("BUG-30", "a hand-made id, no ticket", "B"))
        write(proj_bugs / "BUG-32.md", bug_md("BUG-32", "same name, other id in the task folder", "B"))
        write(hand / "bugs" / "BUG-32.md", bug_md("BUG-32", "task", "gateB-OLD"))
        rh = BR.story_bugs(hand)
        check_eq("ticket-less id: a project-home file does not join on it (BUG-30, BUG-32 unattributed)",
                 sorted(u["id"] for u in rh["unattributed"] if u["id"] in ("BUG-30", "BUG-32")), ["BUG-30", "BUG-32"])
        check("ticket-less id: and the reason says so in plain words",
              all("no ticket" in u["reason"] for u in rh["unattributed"] if u["id"] in ("BUG-30", "BUG-32")),
              str(rh["unattributed"]))
        check_eq("ticket-less id: it joins a file that ALSO lies in the story's folder with the same id: one record, "
                 "project copy first", (ids(rh).count("BUG-31"), by_id(rh, "BUG-31")["homes"],
                                        by_id(rh, "BUG-31")["paths"][0].endswith("qa-factory/bugs/BUG-31.md")),
                 (1, ["task", "project"], True))
        check("ticket-less id: BUG-30 is not a record of the story", "BUG-30" not in ids(rh), str(ids(rh)))
        for n in ("BUG-30", "BUG-31", "BUG-32"):
            (proj_bugs / f"{n}.md").unlink()

        # --- edge 7: unfiled drafts ----------------------------------------------------------
        dr = story(root, "STORY-DRAFTS", "gateB-D")
        drafts = dr / "work" / "bug-drafts"
        write(drafts / "tc-009.json", json.dumps({"id": "DRAFT-9", "title": "Login fails on\nsecond try",
                                                 "case": "TC_003", "confirmation": "unconfirmed"}))
        write(drafts / "paired.json", json.dumps({"title": "the draft of BUG-20", "case": "TC_004"}))
        write(drafts / "paired-slash.json", json.dumps({"title": "the draft of BUG-21"}))
        write(drafts / "paired-project.json", json.dumps({"title": "the draft of BUG-22"}))
        write(drafts / "same-case.json", json.dumps({"title": "another draft, case TC_004", "case": "TC_004"}))
        write(drafts / "broken.json", "{not json")
        write(drafts / "empty.json", "{}")
        write(dr / "bugs" / "BUG-20.md", bug_md("BUG-20", "filed", "gateB-D", source_draft="work/bug-drafts/paired.json"))
        write(dr / "bugs" / "BUG-21.md", bug_md("BUG-21", "filed 2", "gateB-D",
                                                source_draft="./work\\bug-drafts\\paired-slash.json"))
        write(proj_bugs / "BUG-22.md", bug_md("BUG-22", "filed in project", "gateB-D",
                                              source_draft="work/bug-drafts/paired-project.json"))
        # source_draft is free text in real files: without the work/ prefix it still resolves; a
        # value that names no draft ("pipeline.json", as on cmp1) does not, and a shared title is
        # only a hint - both stay, each with a note.
        write(drafts / "no-prefix.json", json.dumps({"title": "the draft of BUG-23"}))
        write(drafts / "maybe.json", json.dumps({"title": "Retry storm on webhook"}))
        write(drafts / "other.json", json.dumps({"title": "Nothing like it"}))
        write(dr / "bugs" / "BUG-23.md", bug_md("BUG-23", "filed 3", "gateB-D", source_draft="bug-drafts/no-prefix.json"))
        write(dr / "bugs" / "BUG-24.md", bug_md("BUG-24", "retry storm on   webhook", "gateB-D",
                                                source_draft="pipeline.json"))
        rd = BR.story_bugs(dr)
        check_eq("edge 7: a draft and the filed bug that names it are ONE record each; the others stay drafts",
                 sorted(ids(rd)), sorted(["BUG-20", "BUG-21", "BUG-22", "BUG-23", "BUG-24", "DRAFT-9", "same-case",
                                          "maybe", "other"]))
        check_eq("drafts: source_draft without the work/ prefix resolves to the draft: one record",
                 (by_id(rd, "BUG-23")["homes"], "no-prefix" in ids(rd)), (["task", "drafts"], False))
        check_eq("drafts: a filed bug whose source_draft names nothing real (\"pipeline.json\") and a draft with "
                 "the same title are NOT merged: two records",
                 (ids(rd).count("BUG-24"), "maybe" in ids(rd)), (1, True))
        check("drafts: each of the two carries the note that they may be the same bug",
              "may be the same bug: the filed file does not name its draft" in " ".join(by_id(rd, "BUG-24")["notes"])
              and "may be the same bug: the filed file does not name its draft" in " ".join(by_id(rd, "maybe")["notes"]),
              str((by_id(rd, "BUG-24")["notes"], by_id(rd, "maybe")["notes"])))
        check_eq("drafts: no other record gets that note, and sources count the pairs (1)",
                 (sorted(r["id"] for r in rd["records"] if r["notes"]), source(rd, "drafts")["maybe_same_by_title"]),
                 (["BUG-24", "maybe"], 1))
        check_eq("edge 7: the filed record names the pair and lists the draft path last",
                 (by_id(rd, "BUG-20")["title"], by_id(rd, "BUG-20")["homes"],
                  (by_id(rd, "BUG-20")["paths"] or [""])[-1].endswith("work/bug-drafts/paired.json")),
                 ("filed", ["task", "drafts"], True))
        check_eq("edge 7: backslashes and a leading ./ in source_draft still pair",
                 by_id(rd, "BUG-21")["homes"], ["task", "drafts"])
        check_eq("edge 7: a project-home filed bug joined to this story pairs its draft too",
                 by_id(rd, "BUG-22")["homes"], ["project", "drafts"])
        d9 = by_id(rd, "DRAFT-9")
        check_eq("edge 7: an unfiled draft is a record (not filed, unconfirmed, one-line title, home drafts)",
                 (d9["filed"], d9["state"], d9["title"], d9["homes"]),
                 (False, "unconfirmed", "Login fails on second try", ["drafts"]))
        check("edge 7 / 9: a draft with the same case id as a filed bug is NOT paired by case",
              "same-case" in ids(rd) and by_id(rd, "BUG-20")["homes"] == ["task", "drafts"], str(ids(rd)))
        check_eq("edge 7: an unreadable or empty draft is skipped by name, not silently",
                 sorted(source(rd, "drafts")["skipped_unreadable"]), ["broken.json", "empty.json"])
        check_eq("edge 7: four drafts paired with their filed bugs", source(rd, "drafts")["paired_with_filed"], 4)
        (proj_bugs / "BUG-22.md").unlink()
        rd2 = BR.story_bugs(dr)
        check_eq("edge 7: without the project copy the draft it named is a record again (a draft is never lost)",
                 "paired-project" in ids(rd2) and "BUG-22" not in ids(rd2), True)

        # --- the invariant, stated as one check each -----------------------------------------
        check("invariant: a bug file in the story's task folder is never reported as none",
              all(ids(r) for r in (ra, rb, rw)) and ids(BR.story_bugs(lone)) == ["BUG-1"])
        check("invariant: no record of A carries a path of another story's task folder",
              all("STORY-B" not in p for r in ra["records"] for p in r["paths"]))
    finally:
        cleanup(root)
        for d in extra:
            cleanup(d)
    owner_pins()
    draft_paths_reads_the_writers_files()
    the_pairing_of_a_draft_with_its_triage_row_is_one_helper()
    story_bugs_reads_through_the_one_reader()
    every_reader_of_the_drafts_folder_reads_through_one_reader()
    the_census_fails_on_an_offender_it_is_not_evergreen()
    the_code_reading_draft()
    the_red_test_travels_with_the_bug()
    the_open_source_bugs()
    the_draft_place_and_mark()
    one_bug_many_manifestations_n2()
    finish("bug_records")


if __name__ == "__main__":
    main()
