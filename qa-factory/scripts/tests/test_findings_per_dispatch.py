#!/usr/bin/env python3
"""t-1937 TR3-5 (AR-8, AR-13, AR-14): the S5 critic's findings go one file per DISPATCH.

Before this node every critic wrote `work/test-code/critic-findings.md` and every reader took "the newest on disk" or a glob. With
two windows side by side the author of window 1 read the findings of window 2. The file is now `critic-findings-<dispatch>.md`
(a registry row with a `*`, matched by the guard with fnmatch); its readers - the form's `findings_file` deriver, the brief of the
author's rework round, the driver's author round - each take the file of THEIR critic, and fall back to the one old name only
(a story from before has it; the new world never writes it). The S4 file is not touched.
"""
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import brief_pack  # noqa: E402
import guard_pre_tool as G  # noqa: E402
import handoff_check as HC  # noqa: E402

TASK = "QA-9"
C1, C2 = "S5-qa-code-critic-1", "S5-qa-code-critic-2"
OLD = "work/test-code/critic-findings.md"


def new_file(c: str) -> str:
    return f"work/test-code/critic-findings-{c}.md"


class Doc:
    """The part of a handoff document the deriver reads: `get(path)`."""

    def __init__(self, **values):
        self.values = values

    def get(self, path, default=None):
        return self.values.get(path, default)


def story(root: Path, files: tuple = (), dispatches: dict | None = None) -> Path:
    task = root / "qa-factory" / "artifacts" / TASK
    shutil.rmtree(task, ignore_errors=True)          # each call is a fresh story: files of the one before are not this one's
    (task / "state").mkdir(parents=True, exist_ok=True)
    (task / "work" / "test-code").mkdir(parents=True, exist_ok=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": TASK, "size": "S", "environment": "local",
                                                   "implementation_source": "diff", "stages": {}, "gates": {}, "halts": []}),
                                        encoding="utf-8")
    (task / "state" / "controller.json").write_text(json.dumps({"dispatches": dispatches or {}, "stages": {}}), encoding="utf-8")
    for rel in files:
        (task / rel).parent.mkdir(parents=True, exist_ok=True)
        (task / rel).write_text(f"findings in {rel}\n", encoding="utf-8")
    return task


def dispatches(w1_critic_first: bool = True) -> dict:
    """Window 1 (TC-1) and window 2 (TC-2) side by side: each has its author, its critic, and window 1 an author's rework round."""
    def rec(did, role, scope, status="accepted", **more):
        return {did: dict({"id": did, "stage": "S5", "role": role, "scope": scope, "status": status}, **more)}
    out = {}
    out.update(rec("S5-qa-automator-1", "qa-automator", ["TC-1"]))
    out.update(rec("S5-qa-automator-2", "qa-automator", ["TC-2"]))
    out.update(rec(C1, "qa-code-critic", ["TC-1"]))
    out.update(rec(C2, "qa-code-critic", ["TC-2"]))
    out.update(rec("S5-qa-automator-3", "qa-automator", ["TC-1"], status="running", rework_of="S5-qa-automator-1"))
    return out


def one_window_dispatches() -> dict:
    """A story from before windows run side by side: both critics review the same scope (one window, sequential rounds)."""
    out = dispatches()
    out[C2] = dict(out[C2], scope=["TC-1"])
    return out


def findings_of_w2_not_read_by_w1() -> None:
    """A window's handoff and an author's round never read another window's findings."""
    root = temp_project("qa-findings-w2-")
    use_project(root)
    try:
        task = story(root, files=(new_file(C1), new_file(C2)), dispatches=dispatches())
        got1 = HC._findings_file(HC.Artifacts(task, dispatch=C1), Doc())
        got2 = HC._findings_file(HC.Artifacts(task, dispatch=C2), Doc())
        check_eq("the form of critic 1 points at its own file", got1 and got1[0], new_file(C1))
        check_eq("the form of critic 2 points at its own file", got2 and got2[0], new_file(C2))
        # the deriver takes the dispatch from the form's header when the checker was not told one
        via_doc = HC._findings_file(HC.Artifacts(task), Doc(**{"header.dispatch": C2}))
        check_eq("a form that names its dispatch in the header is read the same way", via_doc and via_doc[0], new_file(C2))
        check_eq("the brief of the author's rework of window 1 names critic 1's file",
                 brief_pack.own_findings(task, json.loads((task / "state" / "controller.json").read_text("utf-8")),
                                         {"id": "S5-qa-automator-3", "scope": ["TC-1"]}), new_file(C1))
        # the driver's author round
        for critic, other in ((C1, C2), (C2, C1)):
            seen = _author_round(task, critic)
            check_in(f"the round after {critic} reads its findings", f"findings in {new_file(critic)}", seen["reason"])
            check_not_in(f"the round after {critic} does not read {other}'s", new_file(other), seen["reason"] + "".join(seen["extra"]))
        # ERROR DIRECTION: only window 2's file exists -> window 1 gets NOTHING, never the other window's
        only_w2 = story(root, files=(new_file(C2),), dispatches=dispatches())
        for name in (new_file(C1), OLD):
            (only_w2 / name).unlink(missing_ok=True)
        check_eq("critic 1 without a file of its own is not pointed at window 2's", HC._findings_file(HC.Artifacts(only_w2, dispatch=C1), Doc()), None)
        check_eq("the author of window 1 without its critic's file is named no findings",
                 brief_pack.own_findings(only_w2, json.loads((only_w2 / "state" / "controller.json").read_text("utf-8")),
                                         {"id": "S5-qa-automator-3", "scope": ["TC-1"]}), "")
        check_eq("an author with no scope is named no findings (a missing scope is not 'every window')",
                 brief_pack.own_findings(task, json.loads((task / "state" / "controller.json").read_text("utf-8")),
                                         {"id": "S5-qa-automator-3", "scope": []}), "")
    finally:
        cleanup(root)


def findings_old_story_falls_back() -> None:
    """A story from before has `critic-findings.md`: the readers fall back to that one name, nothing else."""
    root = temp_project("qa-findings-old-")
    use_project(root)
    try:
        task = story(root, files=(OLD,), dispatches=one_window_dispatches())
        got = HC._findings_file(HC.Artifacts(task, dispatch=C1), Doc())
        check_eq("the form of an old story points at the old file", got and got[0], OLD)
        check_eq("the brief of the author's rework names the old file when the critic has none of its own",
                 brief_pack.own_findings(task, json.loads((task / "state" / "controller.json").read_text("utf-8")),
                                         {"id": "S5-qa-automator-3", "scope": ["TC-1"]}), OLD)
        seen = _author_round(task, C1)
        check_in("the author's round of an old story reads the old file", "findings in " + OLD, seen["reason"])
        # the new world never writes the old name: a per-dispatch file beats it
        both = story(root, files=(OLD, new_file(C1)), dispatches=dispatches())
        check_eq("the file of the dispatch wins over the old name", HC._findings_file(HC.Artifacts(both, dispatch=C1), Doc())[0], new_file(C1))
        # NEVER "the newest on disk": the newest file belongs to another window and an old story has none for this one
        stray = story(root, files=(new_file(C2),), dispatches=dispatches())
        (stray / OLD).unlink(missing_ok=True)
        check_eq("with no file of its own and no old file the deriver names none (never the newest on disk)",
                 HC._findings_file(HC.Artifacts(stray, dispatch=C1), Doc()), None)
        seen = _author_round(stray, C1)
        check_in("the round with no findings file of its critic is given the critic's digest", "THE-DIGEST", seen["reason"])
        check_not_in("and not the other window's file", "findings in", seen["reason"])
    finally:
        cleanup(root)


def _author_round(task: Path, critic: str) -> dict:
    """Run the real `Driver.s5_author_round` on a stand-in that records what `rework` is given."""
    import story_run
    box = {}

    def rework(stage, role, cases, reason, **kw):
        box.update(stage=stage, role=role, cases=cases, reason=reason, extra=list(kw.get("extra") or []))
        return "", ""
    stub = SimpleNamespace(task_root=task, rework=rework,
                           newest=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("an author round never takes the newest file on disk")))
    counted = story_run.Driver.s5_author_round(stub, ["TC-1"], {"counted": 0, "cap": 3}, "THE-DIGEST", f"work/handoffs/{critic}.yaml", [], critic)
    box["counted"] = counted
    return box


def author_round_reads_its_critic() -> None:
    root = temp_project("qa-findings-round-")
    use_project(root)
    try:
        task = story(root, files=(new_file(C1), new_file(C2), OLD))
        seen = _author_round(task, C2)
        check_eq("the round is the author's test_defect round of the window", (seen["stage"], seen["role"]), ("S5", "qa-automator"))
        check_in("the reason carries the text of its critic's file", f"findings in {new_file(C2)}", seen["reason"])
        check_in("the prompt names its critic's file", new_file(C2), "".join(seen["extra"]))
        check_not_in("and not the other critic's", new_file(C1), "".join(seen["extra"]))
        check_eq("it returns the count it was dispatched at", seen["counted"], 0)
    finally:
        cleanup(root)


def owner_of_per_dispatch_findings_is_critic() -> None:
    base = "/p/qa-factory/artifacts/QA-9/work/test-code"
    check_eq("a per-dispatch findings file is the code critic's", G._owner_of_path(f"{base}/critic-findings-{C2}.md", {}), ("qa-code-critic", False))
    check_eq("the old exact name is still the code critic's (the exact row, first match as today)",
             G._owner_of_path(f"{base}/critic-findings.md", {}), ("qa-code-critic", False))
    check_eq("a backslash path of a Windows host is read the same way",
             G._owner_of_path(base.replace("/", "\\") + f"\\critic-findings-{C1}.md", {}), ("qa-code-critic", False))
    check("a file that only shares the start of the name is not claimed by the `*` row",
          G._owner_of_path(f"{base}/critic-findings-{C1}.txt", {})[0] != "qa-code-critic")
    check("the `*` row is for the code critic's directory only",
          G._owner_of_path(f"/p/qa-factory/artifacts/QA-9/work/other/critic-findings-{C1}.md", {})[0] != "qa-code-critic")
    check("an `*` key is not claimed by exact match: a file literally named by the pattern is no special case",
          "work/test-code/critic-findings-*.md" in G.owned_artifacts() and "work/test-code/critic-findings.md" in G.owned_artifacts())


def s4_owner_unchanged() -> None:
    base = "/p/qa-factory/artifacts/QA-9/work/test-cases"
    check_eq("S4 findings at the cases root are the case critic's", G._owner_of_path(f"{base}/critic-findings.md", {}), ("qa-case-critic", False))
    check_eq("S4 findings under an area are the case critic's", G._owner_of_path(f"{base}/webhook/critic-findings.md", {}), ("qa-case-critic", False))
    check("a per-dispatch name under the cases directory is not the code critic's",
          G._owner_of_path(f"{base}/webhook/critic-findings-{C1}.md", {})[0] != "qa-code-critic")
    # the S4 form still resolves its own file, and an S5 file of the story does not take its place
    root = temp_project("qa-findings-s4-")
    use_project(root)
    try:
        task = story(root, files=("work/test-cases/critic-findings.md",))
        got = HC._findings_file(HC.Artifacts(task, dispatch="S4-qa-case-critic-1"), Doc())
        check_eq("the S4 form's findings file is the S4 file", got and got[0], "work/test-cases/critic-findings.md")
    finally:
        cleanup(root)


def brief_of_rework_names_its_findings() -> None:
    names_with = brief_pack._input_names({}, "qa-automator", "window", new_file(C1))
    check_in("the author's inputs name its critic's findings file", new_file(C1), names_with)
    check_not_in("and no glob over the folder", "critic-findings*", names_with)
    check_not_in("and not the sentinel word", brief_pack.OWN_FINDINGS, names_with)
    names_without = brief_pack._input_names({}, "qa-automator", "window", "")
    check("with no critic yet the findings line is dropped, not left as a glob or a placeholder",
          not any("critic-findings" in n for n in names_without), str(names_without))
    check_in("the critic keeps the folder", "work/test-code/", brief_pack._input_names({}, "qa-code-critic", "window"))
    # the real brief: the rework of window 1 is told critic 1's file, the critic is told the path of its own
    root = temp_project("qa-findings-brief-")
    use_project(root)
    try:
        story(root, files=(new_file(C1), new_file(C2)), dispatches=dispatches())
        built = brief_pack.build(TASK, "S5", "qa-automator", "S5-qa-automator-3", write=False)["markdown"]
        check_in("the rework's brief lists its critic's file", new_file(C1), built)
        check_not_in("and not the other window's", new_file(C2), built)
        critic = brief_pack.build(TASK, "S5", "qa-code-critic", C2, write=False)["markdown"]
        check_in("the critic's brief gives the path of its own findings file", f"qa-factory/artifacts/{TASK}/{new_file(C2)}", critic)
        check_not_in("and not the path of another window's", new_file(C1), critic)
        first = brief_pack.build(TASK, "S5", "qa-automator", "S5-qa-automator-1", write=False)["markdown"]
        check_not_in("an author with no critic yet is named no findings file", "critic-findings", first)
        check_in("and is told there are none", "critic findings: none yet", first)
    finally:
        cleanup(root)


S4_FILE = "work/test-cases/critic-findings.md"


def receipts_are_each_critics_own() -> None:
    """t-2098 B3: `story_step._role_receipts` (a review's finish evidence, the receipt door's precondition) names the finishing
    critic's OWN findings file; a critic with none is receipted on nothing - not on another window's file, not on the S4 file."""
    import findings_path
    import story_step
    root = temp_project("qa-findings-receipts-")
    use_project(root)
    try:
        both = story(root, files=(new_file(C1), new_file(C2), S4_FILE), dispatches=dispatches())
        check_eq("critic 1 is receipted on its own file", story_step._role_receipts(both, "qa-code-critic", C1), [new_file(C1)])
        check_eq("critic 2 is receipted on its own file", story_step._role_receipts(both, "qa-code-critic", C2), [new_file(C2)])
        case = story_step._role_receipts(both, "qa-case-critic", "S4-qa-case-critic-1")
        check_eq("the case critic is receipted on the S4 file only, never an S5 one", case, [S4_FILE])
        check_eq("a role that is no review has no receipts", story_step._role_receipts(both, "qa-automator", C1), [])
        check_eq("resolver: own file first", findings_path.resolve(both, C1), new_file(C1))
        only_w2 = story(root, files=(new_file(C2), S4_FILE), dispatches=dispatches())
        check_eq("critic 1 without a file is not receipted on window 2's or on the S4 file",
                 story_step._role_receipts(only_w2, "qa-code-critic", C1), [])
        check_eq("no dispatch named: nothing but the old file could answer, and there is none",
                 story_step._role_receipts(only_w2, "qa-code-critic"), [])
        check_eq("resolver: none for a critic without a file", findings_path.resolve(only_w2, C1), "")
        old = story(root, files=(OLD, new_file(C2)), dispatches=one_window_dispatches())
        check_eq("a story from before: the old single file", story_step._role_receipts(old, "qa-code-critic", C1), [OLD])
        check_eq("resolver: blank dispatch answers only the old file", findings_path.resolve(old, ""), OLD)
        check_eq("resolver: all_files lists the old and per-dispatch files only",
                 [p.name for p in findings_path.all_files(old)], ["critic-findings-S5-qa-code-critic-2.md", "critic-findings.md"])
    finally:
        cleanup(root)


def s5_form_never_falls_to_the_s4_file() -> None:
    """t-2098 F2: an S5 critic form whose own file is missing names nothing (never the S4 case critic's file); an S4 form
    still resolves the S4 file; the ledger's remarks pointer takes the file that names the case, one file per window."""
    import ledger
    root = temp_project("qa-findings-f2-")
    use_project(root)
    try:
        task = story(root, files=(S4_FILE,), dispatches=dispatches())
        check_eq("an S5 form (stage from its record) with only the S4 file on disk names no findings file",
                 HC._findings_file(HC.Artifacts(task, dispatch=C1), Doc()), None)
        bare = story(root, files=(S4_FILE,))
        check_eq("an S5 form (stage from its id, no record) names none either",
                 HC._findings_file(HC.Artifacts(bare, dispatch=C1), Doc()), None)
        check_eq("an S4 form with the old S5 file on disk still takes the S4 file, never the S5 one",
                 (HC._findings_file(HC.Artifacts(story(root, files=(S4_FILE, OLD)), dispatch="S4-qa-case-critic-1"), Doc()) or ("",))[0],
                 S4_FILE)
        two = story(root, files=(new_file(C1), new_file(C2)), dispatches=dispatches())
        (two / new_file(C1)).write_text("TC-1 is weak\n", encoding="utf-8")
        (two / new_file(C2)).write_text("TC-2 is weak\n", encoding="utf-8")
        check_eq("remarks pointer of TC-1 is window 1's file", ledger.remarks_carrier(two, "TC-1"), new_file(C1))
        check_eq("remarks pointer of TC-2 is window 2's file", ledger.remarks_carrier(two, "TC-2"), new_file(C2))
    finally:
        cleanup(root)


def old_file_never_crosses_windows() -> None:
    """t-2106 X1/X4/X3: with two windows the old single file answers nothing (a new-world critic that wrote it must not hand
    it to a window with none); an unknown-stage form takes only its own file; the S4 helper never lists an S5 file; the status
    line counts the returning critic's own file."""
    import findings_path
    import stage_status
    import story_step
    root = temp_project("qa-findings-x-")
    use_project(root)
    try:
        task = story(root, files=(OLD, new_file(C2)), dispatches=dispatches())
        check_eq("two windows: critic 1 gets nothing from the old file", findings_path.resolve(task, C1), "")
        check_eq("two windows: critic 2 still gets its own", findings_path.resolve(task, C2), new_file(C2))
        check_eq("two windows: the receipt of critic 1 is empty", story_step._role_receipts(task, "qa-code-critic", C1), [])
        check_eq("two windows: the deriver of critic 1 names none", HC._findings_file(HC.Artifacts(task, dispatch=C1), Doc()), None)
        check_eq("two windows: the author round of critic 1 reads the digest, not the old file",
                 "findings in" in _author_round(task, C1)["reason"], False)
        bad = story(root, files=(OLD,))
        (bad / "state" / "controller.json").write_text("{not json", encoding="utf-8")
        check_eq("an unreadable record file is unknown: the old file answers nothing", findings_path.resolve(bad, C1), "")
        # X4b: no record, a stem that names no stage
        odd = story(root, files=(OLD,))
        check_eq("an unknown-stage form never takes the old S5 file", HC._findings_file(HC.Artifacts(odd, dispatch="weird"), Doc()), None)
        own = story(root, files=(OLD, "work/test-code/critic-findings-weird.md"))
        check_eq("an unknown-stage form takes the file named after itself",
                 (HC._findings_file(HC.Artifacts(own, dispatch="weird"), Doc()) or ("",))[0], "work/test-code/critic-findings-weird.md")
        # X4a: one S4 helper
        mixed = story(root, files=(S4_FILE, "work/test-cases/area/critic-findings.md", new_file(C1)))
        check_eq("s4_files lists the S4 files only, area folders included",
                 [p.relative_to(mixed).as_posix() for p in findings_path.s4_files(mixed)],
                 ["work/test-cases/area/critic-findings.md", S4_FILE])
        check_eq("s4_files(nested=False) lists the top of test-cases only",
                 [p.name for p in findings_path.s4_files(mixed, nested=False)], ["critic-findings.md"])
        # X3: the status line's count
        counted = story(root, files=(), dispatches=one_window_dispatches())
        (counted / S4_FILE).parent.mkdir(parents=True, exist_ok=True)
        (counted / S4_FILE).write_text("1. a\n2. b\n3. c\n", encoding="utf-8")
        (counted / new_file(C1)).write_text("1. only one\n", encoding="utf-8")
        check_eq("an S5 count is the critic's own file, not the S4 file", stage_status.findings_count(counted, "S5", C1), 1)
        check_eq("an S4 count is the case critic's file", stage_status.findings_count(counted, "S4"), 3)
        check_eq("an S5 count with no file of its own is none, never the S4 file",
                 stage_status.findings_count(counted, "S5", "S5-qa-code-critic-9"), None)
        check_in("the sentence uses the dispatch it is given", "1 findings",
                 stage_status.line(counted, "critic_returned", stage="S5", dispatch=C1))
    finally:
        cleanup(root)


def main() -> None:
    old_file_never_crosses_windows()
    receipts_are_each_critics_own()
    s5_form_never_falls_to_the_s4_file()
    findings_of_w2_not_read_by_w1()
    findings_old_story_falls_back()
    author_round_reads_its_critic()
    owner_of_per_dispatch_findings_is_critic()
    s4_owner_unchanged()
    brief_of_rework_names_its_findings()
    finish("test_findings_per_dispatch")


if __name__ == "__main__":
    main()
