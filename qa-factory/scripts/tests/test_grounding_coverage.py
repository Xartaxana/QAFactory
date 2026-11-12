#!/usr/bin/env python3
"""G2-2: requirement coverage and the stop before window 2 of S3.

  C1 the count (N=1..4, the edge of the threshold)   C2 what leaves N and what never does   C3 the digests and the word
  C4 R6 and the saved-road R3                         C5 the driver: questions, keys, order, the word, unknown, restart
  C6 the row question into the register

The measure is `grounding_table.coverage` (pure) and `coverage_of` (over a story); the word is `grounding_table.stop_word`; the driver
side runs `Driver.grounding_stop` in process over a seeded story with `coverage_of` and `share_of` replaced by recorders.
"""
import contextlib
import io
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import contract as C  # noqa: E402
import grounding_table as GT  # noqa: E402
import planning_contract as PC  # noqa: E402

POLICY, _WHY = PC.grounding_policy()
KEY = "QA-1"


def reg(ids, exempt=()):
    return types.SimpleNamespace(ok=True, why="", ids=list(ids), exempt=list(exempt), statements={}, texts={}, path=None)


def lines(*pairs):
    """`requirements[]` of a table from `(r, state[, where])`."""
    return {"requirements": [{"r": p[0], "state": p[1], **({"where": p[2]} if len(p) > 2 else {})} for p in pairs]}


def cov(states, evidenced=frozenset(), exempt=(), ids=None):
    ids = ids or [f"R-{i + 1}" for i in range(len(states))]
    data = lines(*[(r, s) if isinstance(s, str) else (r,) + tuple(s) for r, s in zip(ids, states)])
    return GT.coverage(data, reg(ids, exempt), POLICY, evidenced)


# --- C1 ---------------------------------------------------------------------------------------------------------------------
def c1_the_count() -> None:
    check_eq("C1: policy threshold is the one the data file holds (a pin: the cases below are built on 50)", POLICY["coverage_stop_below_percent"], 50)
    for states, road in ((["not_implemented"], "stop"), (["implemented"], "none"),
                         (["implemented", "not_implemented"], "highlight"),            # 1/2 is exactly 50 %: not a stop
                         (["implemented", "not_implemented", "not_implemented"], "stop"),
                         (["implemented", "partial", "not_implemented"], "highlight"),
                         (["implemented", "implemented", "implemented", "not_implemented"], "highlight"),
                         (["implemented", "partial", "implemented", "implemented"], "none")):
        out = cov(states)
        check_eq(f"C1: {states} -> N={len(states)} road {road}", (out["n"], out["road"]), (len(states), road))
    out = cov(["partial", "not_implemented"])
    check_eq("C1: partial counts in the numerator", (out["partial"], out["implemented"], out["road"]), (1, 0, "highlight"))
    out = cov(["unknown"] * 4)
    check_eq("C1: four unknown -> N=4, a stop, nothing in the numerator", (out["n"], out["unknown"], out["road"]), (4, 4, "stop"))
    check("C1: all outside the numerator are unknown (the driver picks `.not_known` by this)",
          all(o["state"] == "unknown" for o in out["outside"]), str(out["outside"]))
    out = cov([])
    check_eq("C1: N=0 is a stop that asks nothing of the story", (out["n"], out["road"], out["reading"]), (0, "stop", "nothing_asked"))
    check("C1: N=0 is not 0 of 0 = 100 %", out["percent"] != "100.0", out["percent"])


# --- C2 ---------------------------------------------------------------------------------------------------------------------
def c2_what_leaves_n() -> None:
    out = cov(["not_implemented", "not_implemented"], ) if False else GT.coverage(
        lines(("R-1", "outside_diff", "none"), ("R-2", "outside_diff", "none")), reg(["R-1", "R-2"]), POLICY)
    check_eq("C2: 0/2 outside_diff with `where: none` -> N=2, a stop", (out["n"], out["road"]), (2, "stop"))
    out = GT.coverage(lines(("R-1", "implemented"), ("R-2", "outside_diff", "service b"), ("R-3", "outside_diff", "service b"),
                            ("R-4", "outside_diff", "service b")), reg(["R-1", "R-2", "R-3", "R-4"]), POLICY)
    check_eq("C2: R-1 implemented, R-2..4 outside_diff with a place -> N=1, nothing to ask", (out["n"], out["road"]), (1, "none"))
    out = GT.coverage(lines(("R-1", "outside_diff", "")), reg(["R-1"]), POLICY)
    check_eq("C2: outside_diff with an empty `where` stays in N", (out["n"], out["road"]), (1, "stop"))
    out = GT.coverage(lines(("R-1", "implemented")), reg(["R-1", "R-2"]), POLICY)
    check_eq("C2: a register row with no table line is in N and out of the numerator", (out["n"], out["road"]), (2, "highlight"))
    out = GT.coverage(lines(("R-1", "implemented"), ("R-2", "implemented")), reg(["R-1", "R-2", "R-3"], exempt=["R-3"]), POLICY)
    check_eq("C2: an implementation-only row is not asked of the story", (out["n"], out["road"]), (2, "none"))
    out = cov(["implemented", "not_implemented", "not_implemented"], evidenced={"R-2", "R-3"})
    check_eq("C2: evidenced untouched rows leave N", (out["n"], out["road"]), (1, "none"))
    out = cov(["implemented", "not_implemented", "not_implemented"], evidenced={"R-9"})
    check_eq("C2: an evidenced id that is not in the register changes nothing", (out["n"], out["road"]), (3, "stop"))
    for name, data in (("a state of a word the table does not have", lines(("R-1", "done"))), ("no state", {"requirements": [{"r": "R-1"}]})):
        out = GT.coverage(data, reg(["R-1"]), POLICY)
        check_eq(f"C2: {name} stays in N", (out["n"], out["road"]), (1, "stop"))
    for name, args in (("no policy", (lines(("R-1", "implemented")), reg(["R-1"]), None)),
                       ("a policy with a float", (lines(("R-1", "implemented")), reg(["R-1"]), {"coverage_stop_below_percent": 50.0})),
                       ("a table that is no mapping", ("text", reg(["R-1"]), POLICY)),
                       ("a register that cannot be read", (lines(("R-1", "implemented")), types.SimpleNamespace(ok=False, why="gone"), POLICY))):
        check_eq(f"C2: {name} -> road unknown, never none and never stop", GT.coverage(*args)["road"], "unknown")


def project(register_rows, states, *, diff="diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"):
    """(root, task): a story with a register of `register_rows` ((R, text)), a diff, and a table whose requirement lines carry `states`."""
    root = harness.temp_project("qa-gcov-")
    task = root / "qa-factory" / "artifacts" / KEY
    (task / "work").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": KEY, "implementation_source": "diff", "stages": {}}), encoding="utf-8")
    (task / "work" / "impl-diff.txt").write_bytes(diff.encode("utf-8"))
    rows = "".join(f"| {r} | {text} | ac | — | yes | AC{i} | diff:a.py:1 | access |\n" for i, (r, text) in enumerate(register_rows, 1))
    (task / "work" / "requirements-register.md").write_bytes(
        ("# Register\n\n## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact |\n"
         "|---|---|---|---|---|---|---|---|\n" + rows + "\n## Contradiction matrix\n").encode("utf-8"))
    GT.write_yaml(GT.table_path(task), {"schema_version": 1, **lines(*[(r, s) for (r, _t), s in zip(register_rows, states)])})
    return root, task


# --- C3 ---------------------------------------------------------------------------------------------------------------------
def c3_digest_and_word() -> None:
    rows = [("R-1", "First"), ("R-2", "Second"), ("R-3", "Third")]
    root, task = project(rows, ["implemented", "not_implemented", "not_implemented"])
    try:
        base = GT.coverage_of(task)
        check_eq("C3: coverage_of reads the table and the register now", (base["n"], base["road"]), (3, "stop"))
        d0 = GT.coverage_digest(task, base)
        check("C3: the digest is 12 hex", len(d0) == 12 and all(c in "0123456789abcdef" for c in d0), d0)
        check_eq("C3: the same bytes give the same digest (a restart)", GT.coverage_digest(task, GT.coverage_of(task)), d0)
        # the register moves by something that is not a statement of an uncovered requirement: the claims' projection does that
        reg_path = task / "work" / "requirements-register.md"
        reg_path.write_bytes(reg_path.read_bytes() + b"\n<!-- a projected line -->\n")
        check_eq("C3: the register's own sha256 is not in the digest", GT.coverage_digest(task, GT.coverage_of(task)), d0)
        GT.write_yaml(GT.table_path(task), {"schema_version": 1, **lines(("R-1", "implemented"), ("R-2", "implemented"), ("R-3", "not_implemented"))})
        moved = GT.coverage_of(task)
        check("C3: a state that moved gives another digest (R-3 only, R-2 left the set)", GT.coverage_digest(task, moved) != d0)
        (task / "work" / "impl-diff.txt").write_bytes(b"diff --git a/src/b.py b/src/b.py\n--- a/src/b.py\n+++ b/src/b.py\n@@ -1,1 +1,1 @@\n-x\n+y\n")
        GT.write_yaml(GT.table_path(task), {"schema_version": 1, **lines(("R-1", "implemented"), ("R-2", "not_implemented"), ("R-3", "not_implemented"))})
        check("C3: other diff bytes give another digest", GT.coverage_digest(task, GT.coverage_of(task)) != d0)
        reg_path.write_bytes(reg_path.read_bytes().replace(b"Second", b"Second, changed"))
        (task / "work" / "impl-diff.txt").write_bytes(b"diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -1,1 +1,1 @@\n-a\n+b\n")
        check("C3: another statement of an uncovered requirement gives another digest", GT.coverage_digest(task, GT.coverage_of(task)) != d0)
        # the refactoring digest: the diff bytes and W, T
        share = {"refactoring": 10, "total": 20}
        r0 = GT.refactoring_digest(task, share)
        check("C3: the refactoring digest moves with W", GT.refactoring_digest(task, {"refactoring": 11, "total": 20}) != r0)
        check("C3: the refactoring digest moves with T", GT.refactoring_digest(task, {"refactoring": 10, "total": 21}) != r0)
        check("C3: the two digests are kinds of their own", r0 != d0)
    finally:
        harness.cleanup(root)


def word(match, decision="go on", stage="S3", **extra):
    return {"stage": stage, "match": match, "decision": decision, **extra}


def c3_stop_word() -> None:
    d, other = "abcdef012345", "0123456789ab"
    P = GT.COVERAGE_STOP_BLOCK
    live = {"stage_overrides": [word(f"{P} {d}")]}
    check("C3: the word for this digest is found", GT.stop_word(live, P, d) is not None)
    for name, pipeline in (("another digest", {"stage_overrides": [word(f"{P} {other}")]}),
                           ("a digest by substring (a longer value)", {"stage_overrides": [word(f"{P} {d}ff")]}),
                           ("revoked", {"stage_overrides": [word(f"{P} {d}", revoked_at="2026-10-01")]}),
                           ("an empty decision", {"stage_overrides": [word(f"{P} {d}", decision="  ")]}),
                           ("another stage", {"stage_overrides": [word(f"{P} {d}", stage="S5")]}),
                           ("the other stop's prefix", {"stage_overrides": [word(f"{GT.REFACTORING_STOP_BLOCK} {d}")]}),
                           ("the bare prefix", {"stage_overrides": [word(P)]}),
                           ("`grounding` alone", {"stage_overrides": [word("grounding")]}),
                           ("`stop` alone", {"stage_overrides": [word("stop")]}),
                           ("a pipeline that is a list", []), ("a pipeline with no overrides", {}), ("overrides that are no list", {"stage_overrides": "x"}),
                           ("a record that is no object", {"stage_overrides": ["x", None]})):
        check(f"C3: {name} is no word (the block stands)", GT.stop_word(pipeline, P, d) is None)
    check("C3: a revoked `*` is no word", GT.stop_word({"stage_overrides": [word("*", revoked_at="x")]}, P, d) is None)
    star = GT.stop_word({"stage_overrides": [word("*", decision="all of it")]}, P, d)
    check("C3: the `*` of a person passes (reported as the person's word, FR-4)", star is not None and star["decision"] == "all of it")
    check("C3: the empty digest never matches by prefix", GT.stop_word({"stage_overrides": [word(P)]}, P, "") is None)


# --- C4 ---------------------------------------------------------------------------------------------------------------------
def c4_r6() -> None:
    rows = [("R-1", "First"), ("R-2", "Second"), ("R-3", "Third")]
    root, task = project(rows, ["implemented", "not_implemented", "not_implemented"])
    try:
        data = GT.hooklib.read_json(GT.table_path(task), None) if False else PC.read_grounding(task)[0].data
        found = GT.r6_findings(task, data, [])
        r6 = [f for f in found if f.rule == "R6"]
        check_eq("C4: 1/3 with no word -> one R6 of the driver", [(f.rule, f.who) for f in found], [("R6", "driver")])
        digest = GT.coverage_digest(task, GT.coverage_of(task))
        check_in("C4: R6 names the block with the present digest", f"{GT.COVERAGE_STOP_BLOCK} {digest}", r6[0].text)
        (task / "pipeline.json").write_text(json.dumps({"ticket": KEY, "implementation_source": "diff", "stages": {},
                                                        "stage_overrides": [word(f"{GT.COVERAGE_STOP_BLOCK} {digest}")]}), encoding="utf-8")
        check_eq("C4: the word for the present digest -> no R6", [f.rule for f in GT.r6_findings(task, data, [])], [])
        # the state moves after `go on` (R-3 -> implemented): another digest, another question, and R6 says what changed
        GT.write_yaml(GT.table_path(task), {"schema_version": 1, **lines(("R-1", "not_implemented"), ("R-2", "not_implemented"), ("R-3", "implemented"))})
        data = PC.read_grounding(task)[0].data
        moved = [f for f in GT.r6_findings(task, data, []) if f.rule == "R6"]
        check_eq("C4: the state moved after the word -> R6 again, of the driver (not the role)", [f.who for f in moved], ["driver"])
        check_in("C4: ...and its block has the NEW digest", GT.coverage_digest(task, GT.coverage_of(task)), moved[0].text)
        # F-9: the exit refusal of R6 / R3 reaches the CONDUCTOR (window 2 is over, no driver move exists), never the resumed role
        import re
        import story_run
        refusal = "story_step: refused - S3 grounding: " + GT.exit_line(moved[0])
        check("C4 F-9: a refusal headed `S3 grounding:` does not match STRUCTURED_RE (the role is not resumed)",
              re.search(story_run.STRUCTURED_RE, refusal, re.IGNORECASE | re.DOTALL) is None, refusal[:120])
        check_in("C4 F-9: R6 names the conductor's door", "the conductor puts the question to the person", moved[0].text)
        check_not_in("C4 F-9: ... and not a driver move that no longer exists at the exit", "the driver asks", moved[0].text)
        stale = [f for f in GT.r6_findings(task, dict(PC.read_grounding(task)[0].data, requirement_coverage={"road": "none"}), []) if f.rule == "R3"]
        check("C4 F-9: R3 names the conductor, not the driver, as the one who measures again", stale and "the conductor measures again" in stale[0].text, str(stale))
        # saved keys are shown, never believed
        data = dict(data, requirement_coverage={"road": "none", "implemented": 3, "partial": 0, "n": 3})
        found = GT.r6_findings(task, data, [])
        check_eq("C4: a road `none` written by hand over a stop: R3 (driver) AND the R6 from the fresh count",
                 sorted((f.rule, f.who) for f in found), [("R3", "driver"), ("R6", "driver")])
        fresh = GT.coverage_of(task)
        data = dict(data, requirement_coverage={"road": fresh["road"]})
        check_eq("C4: the saved road equal to the fresh one -> no R3", [f.rule for f in GT.r6_findings(task, data, []) if f.rule == "R3"], [])
        check_eq("C4: no saved key -> no R3 (the fresh measure decides)", [f.rule for f in GT.r6_findings(task, {k: v for k, v in data.items()
                                                                                                             if k != "requirement_coverage"}, []) if f.rule == "R3"], [])
        # a road the code cannot measure goes to the conductor
        (task / "work" / "requirements-register.md").unlink()
        unknown = [f for f in GT.r6_findings(task, data, []) if f.rule == "R6"]
        check("C4: an unreadable register -> R6 of the conductor, no card", unknown and unknown[0].who == "conductor", str(unknown))
    finally:
        harness.cleanup(root)


def c4_unchanged_evidence() -> None:
    root, task = project([("R-1", "First"), ("R-2", "Second")], ["implemented", "not_implemented"])
    try:
        path = task / "work" / "requirements-register.md"
        path.write_bytes(path.read_bytes().replace(b"| impact |\n|---|---|---|---|---|---|---|---|", b"| impact | delta |\n|---|---|---|---|---|---|---|---|---|")
                         .replace(b"| access |\n| R-2", b"| access | new |\n| R-2").replace(b"| access |\n\n", b"| access | unchanged |\n\n"))
        import base_slice as BS
        seen = {}
        real_collect, real_evidence = BS.collect, BS.unchanged_evidence
        try:
            BS.collect = lambda root: (_ for _ in ()).throw(RuntimeError("no slice"))
            check_eq("C2: `BS.collect` raised -> nobody is evidenced, R-2 stays in N", GT.coverage_of(task)["n"], 2)
            BS.collect = lambda root: {}
            BS.unchanged_evidence = lambda row, root, collected=None: ("unevidenced", "no")
            check_eq("C2: `unevidenced` -> R-2 stays in N", GT.coverage_of(task)["n"], 2)
            BS.unchanged_evidence = lambda row, root, collected=None: (seen.setdefault("asked", []).append(row["r"]) or "evidenced", "ok")
            out = GT.coverage_of(task)
            check_eq("C2: `evidenced` is the ONLY word that leaves N (R-2 is asked, it leaves)", (out["n"], seen["asked"]), (1, ["R-2"]))
        finally:
            BS.collect, BS.unchanged_evidence = real_collect, real_evidence
    finally:
        harness.cleanup(root)


# --- C5 ---------------------------------------------------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))
from story_run_common import driver_for, seed  # noqa: E402


def quiet():
    return contextlib.redirect_stdout(io.StringIO())


def driver_story(stop_words=()):
    root, task_root, env = seed(KEY)
    pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
    pipeline["implementation_source"] = "diff"
    if stop_words:
        pipeline["stage_overrides"] = list(stop_words)
    (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    return root, task_root, driver_for(root, env, KEY)


def cov_stub(road, outside=(), n=3, reading="", **extra):
    out = {"implemented": 0, "partial": 0, "n": n, "unknown": 0, "percent": "0.0", "road": road, "reading": reading,
           "outside": [{"r": r, "state": s} for r, s in outside], "reason": ""}
    out.update(extra)
    return out


def share_stub(road, **extra):
    out = {"road": road, "percent": "60.0", "refactoring": 60, "total": 100, "reason": ""}
    out.update(extra)
    return out


def asked(driver):
    """`(key, kind, block)` of the question `grounding_stop` raises, or the Refusal's text."""
    import story_run
    try:
        driver.grounding_stop()
    except story_run.Person as exc:
        return exc
    except story_run.Refusal as exc:
        return exc
    return None


def c5_the_driver() -> None:
    import story_run
    root, _task_root, driver = driver_story()
    keys = []
    real = driver.closed_question
    driver.closed_question = lambda key, lead, options: keys.append(key) or real(key, lead, options)
    try:
        for name, cov_in, share_in, key in (
                ("the coverage stop", cov_stub("stop", [("R-2", "not_implemented"), ("R-3", "unknown")]), share_stub("none"), "s3.grounding_coverage"),
                ("only unknown outside the count", cov_stub("stop", [("R-1", "unknown"), ("R-2", "unknown")], n=2), share_stub("none"),
                 "s3.grounding_coverage.not_known"),
                ("nothing asked", cov_stub("stop", [], n=0, reading="nothing_asked"), share_stub("none"), "s3.grounding_coverage.nothing_asked"),
                ("the refactoring stop", cov_stub("none", n=2), share_stub("stop"), "s3.grounding_refactoring")):
            keys.clear()
            driver.state.pop("asked", None)
            import grounding_table as G
            real_cov, real_share = G.coverage_of, G.share_of
            G.coverage_of, G.share_of = (lambda root, c=cov_in: c), (lambda root, s=share_in: s)
            try:
                got = asked(driver)
            finally:
                G.coverage_of, G.share_of = real_cov, real_share
            check(f"C5: {name} -> a Person", isinstance(got, story_run.Person), repr(got))
            check_eq(f"C5: {name} -> the key", keys, [key])
            tokens = sorted(getattr(got, "offered", ()))
            check_eq(f"C5: {name} -> only `go on` and `stop` are offered", tokens, ["go on", "stop"])
            check(f"C5: {name} -> the block carries the digest", got.block.split()[-1].isalnum() and len(got.block.split()[-1]) == 12, got.block)
            check_not_in(f"C5: {name} -> no field name or K-n in the text", "K-", str(getattr(got, "text", "")))
            if key.endswith("not_known"):
                said = str(getattr(got, "text", "")).lower()
                check_not_in("C5: the `.not_known` text never says not implemented", "not implement", said)
                check_not_in("C5: ... nor that the change implements 0 of N (F-5: nothing is known to be missing)", "implements 0", said)
                check_in("C5: ... it says it could not establish whether, for these 2", "could not establish whether the change implements these 2 requirements", said)
    finally:
        harness.cleanup(root)


def c5_order_and_words() -> None:
    import grounding_table as G
    import story_run
    root, task_root, driver = driver_story()
    real_cov, real_share = G.coverage_of, G.share_of
    try:
        seen = []
        G.coverage_of = lambda r: cov_stub("stop", [("R-2", "not_implemented")], n=2)
        G.share_of = lambda r: (seen.append("share") or share_stub("stop"))
        first = asked(driver)
        check("C5: two stops: coverage first", isinstance(first, story_run.Person) and "coverage" in first.block, getattr(first, "block", repr(first)))
        check_eq("C5: ...and the refactoring share is not even measured while the coverage question stands", seen, [])
        digest = first.block.split()[-1]
        pipeline = json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [word(f"{G.COVERAGE_STOP_BLOCK} {digest}")]
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        second = asked(driver)
        check("C5: a word for the exact digest (a restart) -> the coverage is not asked again, the refactoring is",
              isinstance(second, story_run.Person) and "refactoring" in second.block, getattr(second, "block", repr(second)))
        pipeline["stage_overrides"] = [word(f"{G.COVERAGE_STOP_BLOCK} {'0' * 12}")]
        (task_root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        again = asked(driver)
        check("C5: a word for another digest does not count: asked again", isinstance(again, story_run.Person) and "coverage" in again.block, repr(again))
        G.coverage_of = lambda r: cov_stub("none", n=2)
        G.share_of = lambda r: share_stub("none")
        check_eq("C5: nothing stops -> nothing is asked", asked(driver), None)
        for name, c, s in (("coverage unknown", cov_stub("unknown", reason="no register"), share_stub("none")),
                           ("share unknown", cov_stub("none"), share_stub("unknown", reason="no policy"))):
            G.coverage_of, G.share_of = (lambda r, c=c: c), (lambda r, s=s: s)
            got = asked(driver)
            check(f"C5: {name} -> a Refusal to the conductor, no card", isinstance(got, story_run.Refusal), repr(got))
    finally:
        G.coverage_of, G.share_of = real_cov, real_share
        harness.cleanup(root)


def c5_between_windows() -> None:
    """The slot: `--share` (non-zero is a Refusal), the row questions (problems are a Refusal), then the stop - in this order."""
    import claim_projector as CP
    import story_run
    root, _task_root, driver = driver_story()
    order = []
    try:
        driver.py = lambda script, *a, **k: (order.append((script,) + tuple(a)) or (0, ""))
        driver.grounding_stop = lambda: order.append("stop")
        real = CP.project_row_questions
        CP.project_row_questions = lambda r: (order.append("questions") or types.SimpleNamespace(projected=[], problems=[], wrote=False, notes=[]))
        try:
            driver.s3_between_windows()
            check_eq("C5: --share, then the row questions, then the stop", order, [("grounding_table.py", "--share", "--task", KEY), "questions", "stop"])
            order.clear()
            driver.py = lambda script, *a, **k: (3, "table gone")
            try:
                driver.s3_between_windows()
                check("C5: a --share that exits non-zero is a Refusal", False)
            except story_run.Refusal as exc:
                check_in("C5: ...naming the exit and the output", "table gone", str(exc))
            CP.project_row_questions = lambda r: types.SimpleNamespace(projected=[], problems=["Q problem"], wrote=False, notes=[])
            driver.py = lambda script, *a, **k: (0, "")
            try:
                driver.s3_between_windows()
                check("C5: row-question problems are a Refusal", False)
            except story_run.Refusal as exc:
                check_in("C5: ...naming the problem", "Q problem", str(exc))
        finally:
            CP.project_row_questions = real
    finally:
        harness.cleanup(root)


# --- C6 ---------------------------------------------------------------------------------------------------------------------
def c6_row_questions() -> None:
    import claim_projector as CP
    q = C.grounding_row_question("Is this part of the story?", "the change adds a retry", "work/grounding.yaml (G-1)")
    check_eq("C6: the row question passes question_errors", C.question_errors(dict(q, id="Q1")), [])
    check_eq("C6: it carries no before/now", [k for k in ("before", "now") if k in q], [])
    check("C6: a blank quote comes back blank and question_errors names it", C.question_errors(dict(C.grounding_row_question("x?", "", "w"), id="Q1")))
    root = harness.temp_project("qa-gq-")
    task = root / "qa-factory" / "artifacts" / KEY
    try:
        (task / "work").mkdir(parents=True)
        (task / "pipeline.json").write_text(json.dumps({"ticket": KEY, "implementation_source": "diff", "stages": {}}), encoding="utf-8")
        (task / "work" / "requirements-register.md").write_bytes(
            b"---\nids: [R-1]\n---\n# Register\n\n## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact |\n"
            b"|---|---|---|---|---|---|---|---|\n| R-1 | First | ac | - | yes | AC1 | diff:a.py:1 | access |\n\n## Contradiction matrix\n")
        GT.write_yaml(GT.table_path(task), {"schema_version": 1, "requirements": [{"r": "R-1", "state": "unknown", "question": "Is the retry meant?"}]})
        none = CP.project_row_questions(task)
        check("C6: no readiness file but a question owed -> a problem, never silence", none.problems and not none.wrote, str(none.problems))
        ready = task / "work" / "requirements-readiness.json"
        ready.write_text(json.dumps({"open_questions": [], "verdict": "ready"}), encoding="utf-8")
        done = CP.project_row_questions(task)
        check_eq("C6: a question on a requirement line -> one Q-n", (done.problems, done.projected, done.wrote), ([], ["R-1"], True))
        rows = json.loads(ready.read_text(encoding="utf-8"))["open_questions"]
        check_eq("C6: the row is keyed by the requirement and the origin", [r.get("raised_for", {}).get("requirement") for r in rows], ["R-1"])
        before = ready.read_bytes()
        again = CP.project_row_questions(task)
        check_eq("C6: a repeat writes nothing", (again.projected, again.wrote, ready.read_bytes() == before), ([], False, True))
        GT.write_yaml(GT.table_path(task), {"schema_version": 1, "requirements": [{"r": "R-1", "state": "unknown", "question": "Is the retry really meant?"}]})
        changed = CP.project_row_questions(task)
        rows = json.loads(ready.read_text(encoding="utf-8"))["open_questions"]
        check_eq("C6: the prose changed on the same key -> still ONE Q-n, a note", (len(rows), bool(changed.notes), changed.wrote), (1, True, False))
    finally:
        harness.cleanup(root)


for fn in (c1_the_count, c2_what_leaves_n, c3_digest_and_word, c3_stop_word, c4_r6, c4_unchanged_evidence, c5_the_driver, c5_order_and_words,
           c5_between_windows, c6_row_questions):
    fn()
harness.finish("test_grounding_coverage")
