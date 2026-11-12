#!/usr/bin/env python3
"""GW1-40: `waiver.py --carry-from <old key> [--carry-from-root <folder>] --task <new key>` carries a person's words to a story under
another key.

A story that moves to a new key starts a new history; the person's earlier words stay in the old folder. The command copies the live
S0-S2 words and the words of a class (`stage_overrides[]`, plus the rows of `work/gap-classes.json`) into the new history, marked
`carried_from`, and nothing else. This file holds the table of edges of the spec (`docs/tasks/specs/t-538-s1a-final.md` section 5):

  c1  the refusals, one row each: nothing is written, the text says what was expected and the door
  c2  what is carried, what is not, and the lines that say so
  c3  the edges of a word of the new history: its own live word wins, a revoked one does not come back, the repeat adds nothing
  c4  `at` stays old, `class` is the source's, `carried_from` keeps the origin, the order by `at` holds
  c5  the carried word acts: `split_overridden` lifts the same block under the new key; the journal says `carried from`
  c6  the words of a kind of gap (`gap-classes.json`)
  c7  the guard: a role is refused, the conductor is not, a quotation and another script's flag are not
  c8  both worlds of the S6 key: no function of the key form is called
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import contract as C  # noqa: E402
import guard_pre_tool as G  # noqa: E402
import source_inventory as SI  # noqa: E402
import waiver as W  # noqa: E402

OLD, NEW = "ADD-TO-CART", "TP1-100"
T1, T2, T3, T4 = ("2026-10-01T10:00:00+00:00", "2026-10-02T10:00:00+00:00", "2026-10-03T10:00:00+00:00", "2026-10-04T10:00:00+00:00")
KLASS = "probe_gap_accepted"
ROLE = {"tool_name": "Bash", "agent_type": "qa-factory:qa-scout"}


def word(stage, match, decision, at=T1, **extra):
    return dict({"stage": stage, "match": match, "decision": decision, "at": at, "by": "human"}, **extra)


def old_pipeline() -> dict:
    return {"task": OLD, "stage_overrides": [
        word("S1", "source material unavailable", "go on without the video", T1),
        word("S2", "requirements gap", "that is fine", T2),
        word("S5", "probe gap: TC_OLD", "I check these by hand", T3, **{"class": KLASS}),
        word("S5", "executor unavailable: e2e-ui", "I run those myself", T2),
        word("S4", "*", "all of it", T2),
        word("S1", "*", "everything at S1", T2),
        word("S1", "taken back", "x", T1, revoked_at=T4, revoked_by="human", revoked_decision="no"),
    ]}


def project() -> Path:
    return temp_project("qa-words-carry-")


def folder(root: Path, key: str, base: Path | None = None) -> Path:
    path = (base or root / "qa-factory" / "artifacts") / key
    path.mkdir(parents=True, exist_ok=True)
    return path


def put(path: Path, data) -> Path:
    (path / "pipeline.json").write_text(data if isinstance(data, str) else json.dumps(data, indent=2), encoding="utf-8")
    return path / "pipeline.json"


def read(path: Path) -> dict:
    return json.loads((path / "pipeline.json").read_text(encoding="utf-8"))


def env(root: Path) -> dict:
    import os
    return dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")


def carry(root: Path, *args):
    return run_script("waiver.py", *args, cwd=root, env=env(root))


def story_pair(root: Path, old=None, new=None):
    """(old folder, new folder): the old one with its history, the new one as S0 leaves it."""
    return put(folder(root, OLD), old if old is not None else old_pipeline()).parent, put(folder(root, NEW), new if new is not None else {"task": NEW}).parent


def by_key(task: Path) -> dict:
    return {(o["stage"], o["match"]): o for o in read(task).get("stage_overrides") or []}


def in_process(root: Path, *args):
    """(exit code, stdout, stderr) of `waiver.run_carry` in this process."""
    use_project(root)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = W.run_carry(*args)
    return code, out.getvalue(), err.getvalue()


# --- c1: the refusals -------------------------------------------------------------------------------------------------

def c1_the_refusals() -> None:
    root = project()
    try:
        old, new = story_pair(root)
        before = (new / "pipeline.json").read_bytes()

        def refused(label, done, code, *needles):
            check_eq(f"c1 {label}: exit {code}", done.returncode, code)
            check_eq(f"c1 {label}: nothing written", (new / "pipeline.json").read_bytes(), before)
            for needle in needles:
                check_in(f"c1 {label}: the text names `{needle}`", needle, done.stderr)

        refused("no folder of the old key", carry(root, "--carry-from", "NO-SUCH", "--task", NEW), 2, "--carry-from-root", "NO-SUCH")
        refused("the old key is the new one", carry(root, "--carry-from", NEW, "--task", NEW), 2, "not copied onto themselves")
        refused("the same key in another case", carry(root, "--carry-from", NEW.lower(), "--task", NEW), 2, "not copied onto themselves")
        for label, key in (("a slash", "a/b"), ("a backslash", "a\\b"), ("dot dot", ".."), ("dot dot inside", "a..b"), ("empty", ""),
                           ("blank", "  "), ("a drive", "C:x")):
            refused(f"the old key has {label}", carry(root, "--carry-from", key, "--task", NEW), 2, "not the name of one story folder")
        refused("the root is not a folder", carry(root, "--carry-from", OLD, "--carry-from-root", str(root / "nowhere"), "--task", NEW),
                2, "is not a folder", "leave the option out")
        elsewhere = folder(root, "elsewhere")
        refused("the root holds no such story", carry(root, "--carry-from", OLD, "--carry-from-root", str(elsewhere), "--task", NEW),
                2, "--carry-from-root <folder>")
        for flags in (("--stage", "S1", "--block", "x"), ("--revoke",), ("--remark",), ("--decision", "go on"), ("--gate", "A"),
                      ("--words-file", str(root / "w.txt")), ("--list",)):
            refused(f"mixed with {flags[0]}", carry(root, "--carry-from", OLD, "--task", NEW, *flags), 2, "does not combine")
        refused("the root alone", carry(root, "--carry-from-root", str(root), "--task", NEW), 2, "goes with --carry-from")
        refused("no --task", carry(root, "--carry-from", OLD), 2, "needs --task")
        # the source cannot be read: NOT "nothing to carry" (AR-28)
        for label, content in (("a broken file", "{not json"), ("an array", "[]"), ("an empty file", "")):
            put(old, content)
            refused(f"the old pipeline.json is {label}", carry(root, "--carry-from", OLD, "--task", NEW), 2, "cannot be read", "unknown, not empty")
        (old / "pipeline.json").unlink()
        refused("the old folder has no pipeline.json", carry(root, "--carry-from", OLD, "--task", NEW), 2, "cannot be read")
        # the new history does not exist
        put(old, old_pipeline())
        (new / "pipeline.json").unlink()
        none = carry(root, "--carry-from", OLD, "--task", NEW)
        check_eq("c1 the new story has no pipeline.json: EXIT_NO_PIPELINE", none.returncode, W.EXIT_NO_PIPELINE)
        check_in("c1 ... the text says to run S0 first", "S0", none.stderr)
        check_eq("c1 ... and no file was made", (new / "pipeline.json").exists(), False)
        # the old key is the same folder under another spelling of the root
        put(new, {"task": NEW})
        same = carry(root, "--carry-from", NEW, "--carry-from-root", str(root / "qa-factory" / "artifacts"), "--task", NEW)
        check_eq("c1 the same folder through --carry-from-root is the same story", same.returncode, 2)
        # nothing to carry is NOT an error
        put(old, {"task": OLD})
        quiet = carry(root, "--carry-from", OLD, "--task", NEW)
        check_eq("c1 an old story with no word that stands: exit 0", quiet.returncode, 0)
        check_in("c1 ... and says `nothing to carry`", "nothing to carry", quiet.stdout)
        put(old, {"task": OLD, "stage_overrides": [word("S1", "x", "y", revoked_at=T4)]})
        quiet = carry(root, "--carry-from", OLD, "--task", NEW)
        check_eq("c1 only a revoked word in the old story: nothing to carry", (quiet.returncode, "nothing to carry" in quiet.stdout), (0, True))
        put(old, {"stage_overrides": [None, 3, "x"]})
        check_eq("c1 a stage_overrides list of entries that are no words is read as no word that stands",
                 carry(root, "--carry-from", OLD, "--task", NEW).returncode, 0)
        # F-8 (t-596, AR-28): a PRESENT stage_overrides that is no list is unknown, not empty - in the old story and in the new one
        before = (new / "pipeline.json").read_bytes()
        for shape in ("x", 5, {"a": 1}):
            put(old, {"task": OLD, "stage_overrides": shape})
            refused(f"the old stage_overrides is {shape!r}", carry(root, "--carry-from", OLD, "--task", NEW), 2,
                    "stage_overrides", "is not a list", "unknown")
        put(old, old_pipeline())
        for shape in ("x", 5):
            put(new, {"task": NEW, "stage_overrides": shape})
            before = (new / "pipeline.json").read_bytes()
            refused(f"the new stage_overrides is {shape!r}", carry(root, "--carry-from", OLD, "--task", NEW), 2,
                    "stage_overrides", "is not a list", "nothing can be stored")
    finally:
        cleanup(root)


# --- c2 + c3 + c4: what is carried ---------------------------------------------------------------------------------------

def c2_what_is_carried() -> None:
    root = project()
    try:
        old, new = story_pair(root)
        done = carry(root, "--carry-from", OLD, "--task", NEW)
        check_eq("c2 the carry succeeds", done.returncode, 0)
        out = done.stdout
        for line in ("carried: S1 · source material unavailable", "carried: S2 · requirements gap", "carried: S5 · probe gap: TC_OLD",
                     "not carried: S5 · executor unavailable: e2e-ui", "not carried: S4 · *", "not carried: S1 · *"):
            check_in(f"c2 the line `{line}`", line, out)
        check_not_in("c2 a taken-back word of the old story is not even listed", "taken back", out)
        words = by_key(new)
        check_eq("c2 exactly the three carried words are in the new story", sorted(words), [
            ("S1", "source material unavailable"), ("S2", "requirements gap"), ("S5", "probe gap: TC_OLD")])
        first = words[("S1", "source material unavailable")]
        check_eq("c2 the person's words whole, the author", (first["decision"], first["by"]), ("go on without the video", "human"))
        check_eq("c2 `carried_from` is the key", first["carried_from"], OLD)
        check("c2 `carried_at` is the moment of the carry, not the old one", first["carried_at"] > T4, first["carried_at"])
        # AR-4: a key, no path, anywhere in the stored record
        text = (new / "pipeline.json").read_text(encoding="utf-8")
        check_not_in("c2 AR-4: no folder path is stored", str(root), text)
        check_not_in("c2 AR-4: ... in either spelling", str(root).replace("\\", "/"), text)
        check_eq("c2 AR-4: `carried_from` holds a bare key (one path component)", all(
            o["carried_from"] == OLD for o in words.values()), True)
        # the old story is untouched
        check_eq("c2 the old story is not changed", read(old), old_pipeline())
        # c3 the repeat
        before = (new / "pipeline.json").read_bytes()
        again = carry(root, "--carry-from", OLD, "--task", NEW)
        check_eq("c3 the repeat: exit 0", again.returncode, 0)
        check_eq("c3 ... every carried word says `already carried`", again.stdout.count("already carried:"), 3)
        check_not_in("c3 ... and nothing is `carried:` again", "\ncarried:", "\n" + again.stdout)
        check_eq("c3 ... the file is byte for byte the same (`at` and `carried_at` do not move)", (new / "pipeline.json").read_bytes(), before)
    finally:
        cleanup(root)


def c3_own_words() -> None:
    root = project()
    try:
        own_live = word("S1", "source material unavailable", "my own words here", T4)
        revoked = word("S2", "requirements gap", "i said it", T2, revoked_at=T3, revoked_by="human", revoked_decision="no")
        old, new = story_pair(root, new={"task": NEW, "stage_overrides": [own_live, revoked]})
        before = by_key(new)
        done = carry(root, "--carry-from", OLD, "--task", NEW)
        check_eq("c3 exit 0", done.returncode, 0)
        check_in("c3 own live word on the same block wins: `kept yours`", "kept yours: S1 · source material unavailable", done.stdout)
        check_eq("c3 ... and is not touched", by_key(new)[("S1", "source material unavailable")], before[("S1", "source material unavailable")])
        check_in("c3 a word the person took back here does not come back", "not carried: S2 · requirements gap", done.stdout)
        check_eq("c3 ... it stays revoked, with its words", by_key(new)[("S2", "requirements gap")], before[("S2", "requirements gap")])
        check_in("c3 the other words are carried", "carried: S5 · probe gap: TC_OLD", done.stdout)
        # a word carried from a third key keeps its origin; a word of the same block carried from ANOTHER key is not "already carried"
        third = word("S1", "source material unavailable", "from the first story", T1, carried_from="FIRST-KEY", carried_at=T2)
        put(new, {"task": NEW, "stage_overrides": [third]})
        done = carry(root, "--carry-from", OLD, "--task", NEW)
        check_in("c3 live and carried from another key is the new story's live word: `kept yours`", "kept yours: S1 · source", done.stdout)
        # the old story's word was itself carried: the origin stays
        put(old, {"task": OLD, "stage_overrides": [word("S1", "a block", "w", T1, carried_from="FIRST-KEY", carried_at=T2)]})
        put(new, {"task": NEW})
        carry(root, "--carry-from", OLD, "--task", NEW)
        check_eq("c3 a word carried twice keeps the key it was first said under", by_key(new)[("S1", "a block")]["carried_from"], "FIRST-KEY")
        again = carry(root, "--carry-from", OLD, "--task", NEW)
        check_in("c3 ... and its repeat reads that origin", "already carried: S1 · a block", again.stdout)
        # revoked in the old story: never carried
        put(old, {"task": OLD, "stage_overrides": [word("S1", "was said", "w", T1, revoked_at=T2, revoked_by="human", revoked_decision="no")]})
        put(new, {"task": NEW})
        carry(root, "--carry-from", OLD, "--task", NEW)
        check_eq("c3 a word revoked in the old story is not carried", by_key(new), {})
    finally:
        cleanup(root)


def c4_the_fields() -> None:
    root = project()
    try:
        # `at` stays old; the class is the source's - none for a word with none, even where the data row would give one
        old = {"task": OLD, "stage_overrides": [
            word("S5", "probe gap: TC_NOCLASS", "mine", T1),                          # a record written before the class existed; S5, no class: not carried
            word("S5", "probe gap: TC_CLASSED", "classed", T2, **{"class": KLASS}),
            word("S1", "something odd", "w", T3, **{"class": "another_kind"}),         # the source's class wins, whatever it is
            word("S1", "no class here", "w", T3),
            word("S1", "undated", "w", at="")]}
        old_dir, new = story_pair(root, old=old)
        carry(root, "--carry-from", OLD, "--task", NEW)
        words = by_key(new)
        check_eq("c4 S5 word with no class is not carried (it is not S0-S2 and not a class word)", ("S5", "probe gap: TC_NOCLASS") in words, False)
        check_eq("c4 `at` of the source stays", words[("S5", "probe gap: TC_CLASSED")]["at"], T2)
        check_eq("c4 the class of the source stays", words[("S5", "probe gap: TC_CLASSED")]["class"], KLASS)
        check_eq("c4 the source's class wins over nothing", words[("S1", "something odd")]["class"], "another_kind")
        check_eq("c4 a source with no class: no class", "class" in words[("S1", "no class here")], False)
        check_eq("c4 a source with no `at`: no `at` (the old is not made newer)", "at" in words[("S1", "undated")], False)
        # a data row that WOULD give a class to the new record: the source's absence wins (a word of S5 with the row's block but no class)
        old2 = {"task": OLD, "stage_overrides": [word("S1", "probe gap: TC_ONE", "w", T1)]}
        put(old_dir, old2)
        put(new, {"task": NEW})
        carry(root, "--carry-from", OLD, "--task", NEW)
        check_eq("c4 the data row of a block gives no class to a carried word whose source had none (an old word stays old)",
                 "class" in by_key(new)[("S1", "probe gap: TC_ONE")], False)
        # the order by `at`: the new story's own later word is the class word; the carried one is older by its old `at`
        put(old_dir, {"task": OLD, "stage_overrides": [word("S5", "probe gap: TC_OLD", "old class word", T2, **{"class": KLASS})]})
        put(new, {"task": NEW, "stage_overrides": [word("S5", "probe gap: TC_NEW", "new class word", T3, **{"class": KLASS})]})
        carry(root, "--carry-from", OLD, "--task", NEW)
        check_eq("c4 order: a word of the new story with a later `at` is above the carried one",
                 C.probe_gap_class_word(read(new), ["x"])["words"], "new class word")
        put(new, {"task": NEW, "stage_overrides": [word("S5", "probe gap: TC_NEW", "new class word", T1, **{"class": KLASS})]})
        carry(root, "--carry-from", OLD, "--task", NEW)
        check_eq("c4 order: and below it when the new story's own is older",
                 C.probe_gap_class_word(read(new), ["x"])["words"], "old class word")
        # the carried word acts like the source did: the same block is lifted under the new key
        put(old_dir, old_pipeline())
        put(new, {"task": NEW})
        errors = ["source-inventory.json: source material unavailable: SRC-1", "other line"]
        check_eq("c5 before the carry the new story blocks the line", W.split_overridden(errors, read(new), "S1")[0], errors)
        check_eq("c5 the old story passes it (its `*` at S1 passes both lines)", [p["error"] for p in W.split_overridden(errors, read(old_dir), "S1")[1]], errors)
        carry(root, "--carry-from", OLD, "--task", NEW)
        blocking, passed = W.split_overridden(errors, read(new), "S1")
        check_eq("c5 after the carry `split_overridden` lifts the same block under the new key", (blocking, [p["error"] for p in passed]),
                 (errors[1:], errors[:1]))
        check_eq("c5 ... with the person's words", passed[0]["decision"], "go on without the video")
    finally:
        cleanup(root)


def c5_the_journal() -> None:
    root = project()
    try:
        old, new = story_pair(root)
        import log_append
        collected = []
        real = log_append.write
        log_append.write = lambda records, *a, **k: collected.extend(records)
        try:
            code, out, err = in_process(root, NEW, OLD, None, "human")
        finally:
            log_append.write = real
        check_eq("c5 in-process carry: exit 0", code, 0)
        notes = [r.get("notes", "") for r in collected]
        check_eq("c5 one journal line per carried word", len(notes), 3)
        check_eq("c5 ... each says `carried from <key>`", all(f"(carried from {OLD})" in n for n in notes), True)
        check_in("c5 ... and holds the person's words", "go on without the video", notes)
        # record_stage_overrides without `fields` writes what it always wrote (no `carried from`, no extra field)
        plain = project()
        try:
            task = put(folder(plain, "P-1"), {"task": "P-1"})
            collected.clear()
            log_append.write = lambda records, *a, **k: collected.extend(records)
            try:
                use_project(plain)
                W.record_stage_overrides(task, "P-1", [("S1", "a block", "words")])
            finally:
                log_append.write = real
            check_eq("c5 `fields` absent: the record is the one it always was", json.loads(task.read_text(encoding="utf-8"))["stage_overrides"][0].keys()
                     - {"at"}, {"stage", "match", "decision", "by"})
            check_eq("c5 ... and the journal line has no `carried from`", [("carried from" in r.get("notes", "")) for r in collected], [False])
        finally:
            cleanup(plain)
    finally:
        cleanup(root)


# --- c6: the words of a kind of gap ---------------------------------------------------------------------------------------

def gap_class_in(task: Path, cause: str = "host_unreachable", words: str = "the VPN is down, go on without it") -> None:
    (task / "work").mkdir(exist_ok=True)
    written, _already, problem = SI.record_gap_class(task / "work" / "source-inventory.json", [cause], words, "Shall I go on without it?", task.name)
    assert not problem and written, problem


def c6_the_gap_classes() -> None:
    root = project()
    try:
        old, new = story_pair(root)
        gap_class_in(old)
        gap_class_in(old, "auth_required", "no login, go on")
        # no work/ in the new story: the folder belongs to its owner, nothing is made
        done = carry(root, "--carry-from", OLD, "--task", NEW)
        check_eq("c6 no work/ in the new story: exit 0", done.returncode, 0)
        check_in("c6 ... the line `not carried: no inventory yet`", "not carried: no inventory yet", done.stdout)
        check_eq("c6 ... and no folder was made", (new / "work").exists(), False)
        check_in("c6 ... the stage_overrides went", "carried: S1 · source material unavailable", done.stdout)
        # the new story has its work/
        (new / "work").mkdir()
        done = carry(root, "--carry-from", OLD, "--task", NEW)
        check_eq("c6 the kinds of gap are carried (exit 0)", done.returncode, 0)
        check_in("c6 ... `carried GC-1: host_unreachable`", "carried GC-1: host_unreachable", done.stdout)
        check_in("c6 ... `carried GC-2: auth_required`", "carried GC-2: auth_required", done.stdout)
        rows, problem = SI.live_gap_classes(new)
        check_eq("c6 the new story's record holds both, with the person's words whole and its own key", (problem, [
            (r["cause"], r["words"], r["story"], r["shown"]) for r in rows]), ("", [
                ("host_unreachable", "the VPN is down, go on without it", NEW, "Shall I go on without it?"),
                ("auth_required", "no login, go on", NEW, "Shall I go on without it?")]))
        before = (new / "work" / SI.GAP_CLASSES_FILE).read_bytes()
        again = carry(root, "--carry-from", OLD, "--task", NEW)
        check_in("c6 the repeat says `already recorded`", "already recorded GC-1: host_unreachable", again.stdout)
        check_eq("c6 ... and the record is the same bytes", (new / "work" / SI.GAP_CLASSES_FILE).read_bytes(), before)
        # a taken-back kind of the old story is not carried
        fresh = project()
        try:
            old2, new2 = story_pair(fresh)
            gap_class_in(old2)
            (new2 / "work").mkdir()
            SI.revoke_gap_class(old2 / "work" / "source-inventory.json", "GC-1", "no, ask again", False)
            carry(fresh, "--carry-from", OLD, "--task", NEW)
            check_eq("c6 a revoked kind of the old story is not carried", SI.live_gap_classes(new2), ([], ""))
        finally:
            cleanup(fresh)
        # F-4 (t-596, FR-40): a kind the person took back in the NEW story is not carried back from the old one; a kind they did not
        # take back still is (the control: the same call carries the other kind)
        fresh = project()
        try:
            old4, new4 = story_pair(fresh)
            gap_class_in(old4)
            gap_class_in(old4, "auth_required", "no login, go on")
            (new4 / "work").mkdir()
            gap_class_in(new4)
            SI.revoke_gap_class(new4 / "work" / "source-inventory.json", "GC-1", "no, ask again", False)
            done = carry(fresh, "--carry-from", OLD, "--task", NEW)
            check_eq("c6 F-4 the new story took its word back: exit 0", done.returncode, 0)
            check_in("c6 F-4 ... said as not carried, with the reason",
                     "not carried: gap class host_unreachable (you took your word back in this story)", done.stdout)
            check_eq("c6 F-4 ... no live row of that kind in the new story (CONTROL: the other kind is carried)",
                     [r["cause"] for r in SI.live_gap_classes(new4)[0]], ["auth_required"])
        finally:
            cleanup(fresh)
        # the old record cannot be read: the stage_overrides go, the partial carry is said
        (old / "work" / SI.GAP_CLASSES_FILE).write_text("{broken", encoding="utf-8")
        put(new, {"task": NEW})
        done = carry(root, "--carry-from", OLD, "--task", NEW)
        check_eq("c6 the old gap-classes.json cannot be read: exit 0", done.returncode, 0)
        check_in("c6 ... `not carried: gap classes: <why>`", "not carried: gap classes: ", done.stdout)
        check_in("c6 ... and the stage_overrides still went", "carried: S1 · source material unavailable", done.stdout)
        # the kind of gap is gone from the table of causes
        gap_class_in(folder(root, "OLD2"), "host_unreachable")
        put(root / "qa-factory" / "artifacts" / "OLD2", {"task": "OLD2"})
        path = root / "qa-factory" / "artifacts" / "OLD2" / "work" / SI.GAP_CLASSES_FILE
        path.write_text(path.read_text(encoding="utf-8").replace("host_unreachable", "bogus_cause"), encoding="utf-8")
        done = carry(root, "--carry-from", "OLD2", "--task", NEW)
        check_eq("c6 a cause the table no longer holds: exit 0", done.returncode, 0)
        check_in("c6 ... `not carried: gap class bogus_cause`", "not carried: gap class bogus_cause", done.stdout)
        # the NEW record cannot be read: print, exit 2, nothing written over it, and nothing of the words either
        old3, new3 = story_pair(root)
        (old3 / "work" / SI.GAP_CLASSES_FILE).unlink()
        gap_class_in(old3)
        (new3 / "work").mkdir(exist_ok=True)
        broken = new3 / "work" / SI.GAP_CLASSES_FILE
        broken.write_text("{broken", encoding="utf-8")
        put(new3, {"task": NEW})
        pipeline_before = (new3 / "pipeline.json").read_bytes()
        done = carry(root, "--carry-from", OLD, "--task", NEW)
        check_eq("c6 the new gap-classes.json cannot be read: exit 2", done.returncode, 2)
        check_eq("c6 ... it is not written over", broken.read_text(encoding="utf-8"), "{broken")
        check_eq("c6 ... and nothing was carried (a half carry would be a promise)", (new3 / "pipeline.json").read_bytes(), pipeline_before)
        check_in("c6 ... the text says what was expected", "Expected: a readable", done.stderr)
    finally:
        cleanup(root)


# --- c7: the guard ---------------------------------------------------------------------------------------------------------

def refused_for(command: str, event=None) -> str | None:
    ev = dict(event or ROLE, tool_input={"command": command})
    return G._blocked(G.human_word_check, ev, {})


def c7_the_guard() -> None:
    cmd = f"python scripts/waiver.py --carry-from {OLD} --task {NEW}"
    text = refused_for(cmd)
    check("c7 a role running `waiver.py --carry-from` is refused", text is not None)
    check_in("c7 ... the text says why", "copies what a person said under another key", text or "")
    check_in("c7 ... in the sentence of the spec", "excusing itself with someone else's words", text or "")
    check("c7 the `=` spelling is refused too", refused_for(f"python waiver.py --carry-from={OLD} --task {NEW}") is not None)
    check("c7 with the root option too", refused_for(f"python waiver.py --carry-from {OLD} --carry-from-root x --task {NEW}") is not None)
    check_eq("c7 the conductor (no role signature) is not refused", refused_for(cmd, {"tool_name": "Bash"}), None)
    check_eq("c7 a quotation (`echo`) is not a call", refused_for(f'echo "run waiver.py --carry-from {OLD} --task {NEW}"'), None)
    check_eq("c7 another script's flag of the same name is not closed", refused_for("python scripts/handoff_init.py --carry-from prev.md"), None)
    check_eq("c7 `--carry-fromage` is no such flag", refused_for("python waiver.py --carry-fromage x"), None)
    check("c7 the existing door still closes (`--stage`)", refused_for('python waiver.py --task T --stage S1 --block "x" --words-file f') is not None)
    check_eq("c7 `waiver.py --list` is open to a role (as before)", refused_for("python waiver.py --task T --list"), None)


# --- c8: both worlds of the S6 key -------------------------------------------------------------------------------------------

def c8_both_worlds() -> None:
    root = project()
    try:
        old, new = story_pair(root)
        import adapter_forms
        import local_keys

        def boom(*args, **kwargs):
            raise AssertionError("the carry must not call a function of the key form")
        real = (adapter_forms.is_key, adapter_forms.key_refused, adapter_forms.is_local_form, local_keys.is_local)
        adapter_forms.is_key = adapter_forms.key_refused = adapter_forms.is_local_form = local_keys.is_local = boom
        try:
            for label, old_key, new_key in (("a free old key, a tracker key", OLD, NEW), ("a free old key, a LOCAL-n key", OLD, "LOCAL-7"),
                                            ("a LOCAL-n old key, a tracker key", "LOCAL-3", NEW)):
                put(folder(root, old_key), old_pipeline())
                put(folder(root, new_key), {"task": new_key})
                code, out, err = in_process(root, new_key, old_key, None, "human")
                check_eq(f"c8 {label}: carried and no key function called", (code, "carried: S1 · source material unavailable" in out), (0, True))
        finally:
            adapter_forms.is_key, adapter_forms.key_refused, adapter_forms.is_local_form, local_keys.is_local = real
        # the source keeps no stale mark of a world: nothing in the module names the key forms
        source = (SCRIPTS / "waiver.py").read_text(encoding="utf-8")
        body = source[source.index("def _carry_overrides"):source.index("def run_remark")]
        for name in ("is_key", "is_local", "key_refused", "adapter_forms", "local_keys"):
            check_not_in(f"c8 the carry code does not name `{name}`", name, body)
    finally:
        cleanup(root)


def c9_by_hand_root() -> None:
    """`--carry-from-root`: a folder moved by hand (CART-1 sits in `superseded/`)."""
    root = project()
    try:
        superseded = root / "qa-factory" / "artifacts" / "superseded"
        put(folder(root, OLD, superseded), old_pipeline())
        new = put(folder(root, NEW), {"task": NEW}).parent
        missing = carry(root, "--carry-from", OLD, "--task", NEW)
        check_eq("c9 the moved folder is not found by default (and the door is named)", (missing.returncode, "--carry-from-root" in missing.stderr), (2, True))
        done = carry(root, "--carry-from", OLD, "--carry-from-root", str(superseded), "--task", NEW)
        check_eq("c9 with the root named it is carried", (done.returncode, "carried: S1 · source material unavailable" in done.stdout), (0, True))
        check_eq("c9 ... and the new story holds the words", ("S1", "source material unavailable") in by_key(new), True)
    finally:
        cleanup(root)


def main() -> None:
    c1_the_refusals()
    c2_what_is_carried()
    c3_own_words()
    c4_the_fields()
    c5_the_journal()
    c6_the_gap_classes()
    c7_the_guard()
    c8_both_worlds()
    c9_by_hand_root()
    finish("GW1-40 words carry")


if __name__ == "__main__":
    main()
