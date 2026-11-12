"""The refactoring share (G2-1): `grounding_table.share` (pure) and `grounding_table.py --share --task T` (writes ONE key).

Edges (spec t-527-s2-final section 3): T = changed production lines, W = those carried by hunks every row of which has a label of the
policy's `numerator_labels`; the road is `100*W > percent*T` in integers, strictly (exactly the threshold is not past it); what cannot be
measured is `unknown` with a reason, never `none` and never `stop`; a measure is never written on a table the reader refuses.
"""
import copy
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, run_script, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import grounding_table as GT  # noqa: E402
import planning_contract as PC  # noqa: E402
import test_files as TF  # noqa: E402

POLICY, WHY = PC.grounding_policy()
check("the shipped policy reads", POLICY is not None, WHY)
NOTIFY, STOP, WORDS = POLICY["notify_above_percent"], POLICY["stop_above_percent"], POLICY["numerator_labels"]
NUM = WORDS[0]                                       # a label the policy counts
OTHER = next(w for w in GT.H.vocabulary()["grounding_labels"] if w not in WORDS)    # a label the policy does not count
Finding = GT.Finding


def table(parts, file="src/a.py"):
    """A table of production hunks: `parts` = [(lines, label)]; one hunk and one row per part."""
    hunks = [{"id": f"h{n}", "file": file, "added": lines, "removed": 0, "pseudo": ""} for n, (lines, _) in enumerate(parts)]
    rows = [{"id": f"G-{n}", "hunks": f"h{n}", "label": label} for n, (_, label) in enumerate(parts)]
    return {"hunks": hunks, "rows": rows}


def at(w, t, **kw):
    """The share of T=`t` lines with W=`w` of them labelled with a counted word."""
    parts = [(w, NUM)] + ([(t - w, OTHER)] if t > w else [])
    return GT.share(table(parts), POLICY, [], **kw)


def road(result):
    return (result["road"], result["percent"])


# --- the boundaries, T=100: exactly 30.0 and 50.0 are NOT past, +1 line is -----------------------------------------------------
check_eq("W=30 of 100: exactly the notify threshold is none", road(at(30, 100)), ("none", "30.0"))
check_eq("W=31 of 100: one line past notify", road(at(31, 100)), ("notify", "31.0"))
check_eq("W=50 of 100: exactly the stop threshold is notify", road(at(50, 100)), ("notify", "50.0"))
check_eq("W=51 of 100: one line past stop", road(at(51, 100)), ("stop", "51.0"))
check_eq("W=0 of 100: none, 0.0", road(at(0, 100)), ("none", "0.0"))
check_eq("W=100 of 100: stop", road(at(100, 100)), ("stop", "100.0"))
check_eq("T=200: 60 is exactly 30, 61 is past it", (at(60, 200)["road"], at(61, 200)["road"]), ("none", "notify"))
check_eq("T=200: 100 is exactly 50, 101 is past it", (at(100, 200)["road"], at(101, 200)["road"]), ("notify", "stop"))
big = at(3001, 10000)
check_eq("T=10000, W=3001 (30.01 %): notify although the shown percent is 30.0 (the road never compares the display)", road(big), ("notify", "30.0"))
check_eq("T=10000, W=5001 (50.01 %): stop although the shown percent is 50.0", road(at(5001, 10000)), ("stop", "50.0"))
check_eq("T=10000, W=3000 exactly: none", at(3000, 10000)["road"], "none")
check_eq("the counts are reported", (big["refactoring"], big["total"], big["measure"]), (3001, 10000, "changed_production_lines"))
check_eq("the policy used is reported", big["policy"], {"notify_above_percent": NOTIFY, "stop_above_percent": STOP, "numerator_labels": WORDS})

# --- the thresholds come from the policy, not from the code ----------------------------------------------------------------------
other = dict(copy.deepcopy(POLICY), notify_above_percent=10, stop_above_percent=20)
check_eq("another policy, another road: 10 none, 11 notify, 20 notify, 21 stop",
         [GT.share(table([(w, NUM), (100 - w, OTHER)]), other, [])["road"] for w in (10, 11, 20, 21)], ["none", "notify", "notify", "stop"])
only = dict(copy.deepcopy(POLICY), numerator_labels=[OTHER])
check_eq("another numerator: the word the policy counts is the one that counts (60 of NUM is 40 % here, 60 % by the shipped policy)",
         (GT.share(table([(60, NUM), (40, OTHER)]), only, [])["road"], GT.share(table([(60, NUM), (40, OTHER)]), POLICY, [])["road"]),
         ("notify", "stop"))
check_eq("...and the other word now stops", GT.share(table([(60, OTHER), (40, NUM)]), only, [])["road"], "stop")

# --- what cannot be measured is unknown, with a reason ---------------------------------------------------------------------------
nothing = GT.share({"hunks": [], "rows": []}, POLICY, [])
check_eq("T=0 (no hunk): percent n/a, road none, a reason", (nothing["percent"], nothing["road"], bool(nothing["reason"])), ("n/a", "none", True))
check_eq("T=0 is not 0 %", nothing["percent"] != "0.0", True)
tests_only = GT.share(table([(50, NUM)], file="tests/test_a.py"), POLICY, [])
check_eq("only test lines: T=0, n/a, none", (tests_only["percent"], tests_only["road"], tests_only["total"]), ("n/a", "none", 0))
dead = GT.share(table([(60, NUM), (40, OTHER)]), None, [], policy_why="references/grounding-policy.json is broken")
check_eq("no policy: unknown, never none and never stop", dead["road"], "unknown")
check_in("...and the reason says what is wrong", "grounding-policy.json is broken", dead["reason"])
check_eq("...with the percent n/a", dead["percent"], "n/a")
check_eq("no policy and no why: still unknown with a reason", (GT.share(table([(1, NUM)]), None, [])["road"], bool(GT.share(table([(1, NUM)]), None, [])["reason"])), ("unknown", True))
for rule in ("R0", "R1", "R5"):
    got = GT.share(table([(60, NUM), (40, OTHER)]), POLICY, [Finding(rule, "x", "role")])
    check_eq(f"a finding {rule}: unknown, the rule is named", (got["road"], rule in got["reason"]), ("unknown", True))
check_eq("a finding of another rule (R3) does not stop the measure", GT.share(table([(60, NUM), (40, OTHER)]), POLICY, [Finding("R3", "x", "role")])["road"], "stop")
empty_mark = table([(60, NUM), (40, "")])
got = GT.share(empty_mark, POLICY, [])
check_eq("an empty mark on a production hunk: unknown, not a share of the rest", (got["road"], got["percent"]), ("unknown", "n/a"))
check_in("...the reason names the empty mark", "empty mark", got["reason"])
unrowed = table([(60, NUM), (40, OTHER)])
unrowed["rows"].pop()
check_eq("a production hunk that no row names: unknown", GT.share(unrowed, POLICY, [])["road"], "unknown")
badcount = table([(60, NUM)])
badcount["hunks"][0]["added"] = "60"
check_eq("a line count that is not a whole number: unknown", GT.share(badcount, POLICY, [])["road"], "unknown")
check_eq("a table that is not a mapping: unknown", GT.share([], POLICY, [])["road"], "unknown")
check_eq("an empty mark on a TEST hunk does not matter (it is not in T)", GT.share(
    {"hunks": [{"id": "t", "file": "tests/test_a.py", "added": 9, "removed": 0}, {"id": "p", "file": "src/a.py", "added": 10, "removed": 0}],
     "rows": [{"hunks": "p", "label": NUM}]}, POLICY, [])["road"], "stop")

# --- who is in T and who is in W -------------------------------------------------------------------------------------------------
parts = table([(40, NUM), (60, OTHER)])
parts["hunks"].append({"id": "t0", "file": "tests/test_a.py", "added": 1000, "removed": 0})
parts["rows"].append({"hunks": "t0", "label": NUM})
check_eq("T excludes test lines: 1000 test lines do not move 40 of 100", road(GT.share(parts, POLICY, [])), ("notify", "40.0"))
infra = table([(40, NUM), (60, "infrastructure")])
check_eq("a label of the role that is not counted (infrastructure) on a production file stays in T, not in W", road(GT.share(infra, POLICY, [])), ("notify", "40.0"))
mixed = table([(40, NUM), (60, NUM)])
mixed["rows"].append({"id": "G-9", "hunks": "h0", "label": OTHER})
got = GT.share(mixed, POLICY, [])
check_eq("a hunk with a counted label AND another: not in W (`all`, not `any`); named in mixed_hunks", (got["refactoring"], got["mixed_hunks"]), (60, ["h0"]))
check_eq("...the share is 60 of 100", road(got), ("stop", "60.0"))
both = table([(40, NUM), (60, OTHER)])
both["rows"].append({"id": "G-9", "hunks": "h0", "label": WORDS[-1]})
check_eq("two counted labels on one hunk: still in W, not mixed", (GT.share(both, POLICY, [])["refactoring"], GT.share(both, POLICY, [])["mixed_hunks"]), (40, []))
one_row = {"hunks": [{"id": "h0", "file": "src/a.py", "added": 5, "removed": 5}], "rows": [{"hunks": ["h0"], "label": NUM}]}
check_eq("added + removed both count", GT.share(one_row, POLICY, [])["total"], 10)
whole = {"hunks": [{"id": "h0", "repo": "r", "file": "src/a.py", "added": 5, "removed": 0}, {"id": "h1", "repo": "r", "file": "src/a.py", "added": 5, "removed": 0},
                   {"id": "h2", "repo": "r", "file": "src/b.py", "added": 5, "removed": 0}],
         "rows": [{"hunks": "all:r:src/a.py", "label": NUM}, {"hunks": "h2", "label": OTHER}]}
check_eq("`all:<repo>:<file>` carries every hunk of the file", (GT.share(whole, POLICY, [])["refactoring"], GT.share(whole, POLICY, [])["total"]), (10, 15))
orph = table([(10, NUM), (90, OTHER)])
orph["orphans"] = [{"was": "row", "id": "G-7", "label": NUM, "hunks": ["h1"]}] * 5
check_eq("a record in orphans[] is not counted", GT.share(orph, POLICY, [])["refactoring"], 10)
moved = table([(20, NUM), (80, OTHER)])
moved["hunks"].append({"id": "p0", "file": "src/old.py", "added": 0, "removed": 0, "pseudo": "rename"})
moved["hunks"].append({"id": "p1", "file": "src/new.py", "added": 50, "removed": 50, "pseudo": "mode"})
moved["rows"].append({"hunks": "p0", "label": NUM})
got = GT.share(moved, POLICY, [])
check_eq("a pseudo-hunk (a pure rename) weighs 0 lines even when it carries numbers; its files are named", (got["total"], got["pseudo_files"]), (100, ["src/old.py", "src/new.py"]))
cfg = table([(20, NUM), (80, OTHER)])
for name in ("package.lock", "docs/guide.json", "README.md"):
    cfg["hunks"].append({"id": name, "file": name, "added": 500, "removed": 0})
    cfg["rows"].append({"hunks": name, "label": NUM})
got = GT.share(cfg, POLICY, [])
check_eq("generated, config and docs files are outside T; the report names them", (got["total"], got["outside_files"]), (100, ["package.lock", "docs/guide.json", "README.md"]))
unclass = table([(30, GT.SHARE_REPORT_LABEL), (70, OTHER)])
got = GT.share(unclass, POLICY, [])
check_eq("an unclassified hunk counts in the numerator when the policy says so, and is reported on its own line",
         (got["refactoring"], got["unclassified"]), (30, 30))
check_eq("a share of a result is idempotent: the same table twice, the same result", GT.share(unclass, POLICY, []), GT.share(unclass, POLICY, []))
before = copy.deepcopy(unclass)
GT.share(unclass, POLICY, [])
check_eq("share() does not change its input", unclass, before)

# --- TF.file_kind as the gate of T: the awkward inputs (an error only in production) ----------------------------------------------
for name, kind in (("src/app/test_mode.py", "production"), ("tests_root/helper.py", "production"), ("docs/guide.json", "config"),
                   ("docs/schema.sql", "production"), ("tests/test_a.py", "test")):
    check_eq(f"file_kind({name}) is {kind}", TF.file_kind(name), kind)
    got = GT.share(table([(10, NUM)], file=name), POLICY, [])
    check_eq(f"...so {name} {'is in' if kind == 'production' else 'is not in'} T", got["total"], 10 if kind == "production" else 0)
lying = table([(10, NUM)], file="tests/test_a.py")
lying["hunks"][0]["kind"] = "production"
check_eq("the table's own `kind` is not believed: a test file written down as production is still out of T", GT.share(lying, POLICY, [])["total"], 0)
sneaky = table([(10, NUM)], file="src/a.py")
sneaky["hunks"][0]["kind"] = "test"
check_eq("...and a production file written down as a test is still in T", GT.share(sneaky, POLICY, [])["total"], 10)

# --- the command line -------------------------------------------------------------------------------------------------------------
DIFF = ("diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -10,3 +10,3 @@ def a()\n ctx\n-old_a\n+new_a\n tail\n"
        "@@ -40,1 +40,1 @@\n-x = 1\n+x = 2\n"
        "diff --git a/src/b.py b/src/b.py\n--- a/src/b.py\n+++ b/src/b.py\n@@ -5,0 +5,1 @@\n+added_b\n")
REG = ("# Register\n\n## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact |\n"
       "|---|---|---|---|---|---|---|---|\n| R-1 | First thing | ac | — | yes | AC1 | diff:a.py:1 | access |\n\n## Contradiction matrix\n")


class Story:
    def __init__(self, source="diff", diff=DIFF):
        self.root = temp_project("qa-share-")
        self.task = self.root / "qa-factory" / "artifacts" / "T-1"
        (self.task / "work").mkdir(parents=True)
        pipe = {"ticket": "T-1"}
        if source is not None:
            pipe["implementation_source"] = source
        (self.task / "pipeline.json").write_bytes(json.dumps(pipe).encode("utf-8"))
        if diff is not None:
            (self.task / "work" / "impl-diff.txt").write_bytes(diff.encode("utf-8"))
        (self.task / "work" / "requirements-register.md").write_bytes(REG.encode("utf-8"))
        (self.task / "work" / GT.BLAST_FILE).write_bytes(json.dumps({"index": {"state": "built"}, "areas": []}).encode("utf-8"))

    def run(self, *args, task="T-1"):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.root), PYTHONDONTWRITEBYTECODE="1")
        return run_script("grounding_table.py", *args, "--task", task, cwd=self.root, env=env)

    @property
    def table(self):
        return GT.table_path(self.task)

    def data(self):
        doc, problem = PC.read_grounding(self.task)
        assert doc is not None, problem
        return doc.data

    def labelled(self, *labels):
        assert self.run("--skeleton").returncode == 0
        data = self.data()
        for row, label in zip(data["rows"], labels):
            row["label"], row["reason"] = label, "ok"
        GT.write_yaml(self.table, data)
        return data

    def digest(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(self.root.rglob("*")) if p.is_file()}


s = Story()
s.labelled(NUM, NUM, OTHER)                                 # the three hunks weigh 2, 2 and 1: W = 4 of T = 5
before = s.data()
done = s.run("--share")
check_eq("--share exits 0", done.returncode, 0)
after = s.data()
key = after.get("refactoring_share") or {}
check_eq("--share writes the key: 4 of 5 is stop at 80.0", (key.get("refactoring"), key.get("total"), key.get("percent"), key.get("road")), (4, 5, "80.0", "stop"))
check_eq("...and only those two keys (G2-2: `--share` writes refactoring_share and requirement_coverage): the rest of the table is as it was",
         {k: v for k, v in after.items() if k not in ("refactoring_share", "requirement_coverage")}, before)
check_in("the line printed is a measure, not a REJECT", "road stop", done.stdout)
check("...no REJECT in the output", "REJECT" not in done.stdout + done.stderr, done.stdout)
check("the written key reads back through the reader and its road is in ROADS", key.get("road") in GT.ROADS)
again = s.run("--share")
check_eq("running it twice leaves the same table", (again.returncode, s.data()), (0, after))
check("the check still finds nothing new about the key (R3 reads the road)", not [f for f in GT.check(s.task) if f.rule == "R3"], str(GT.check(s.task)))
s.root and cleanup(s.root)

s = Story()
s.labelled(NUM, "", "")
done = s.run("--share")
key = s.data().get("refactoring_share") or {}
check_eq("an empty mark in a table: the key is written as unknown (exit 0), not as a share", (done.returncode, key.get("road"), key.get("percent")), (0, "unknown", "n/a"))
check_in("...the reason names the rule of the check", "R1", key.get("reason", ""))
cleanup(s.root)

s = Story()
s.labelled(NUM, NUM, OTHER)
real = PC.grounding_policy
PC.grounding_policy = lambda path=None: (None, "references/grounding-policy.json cannot be found, so no threshold can be read")
try:
    lines = GT._cmd_share(s.task)
finally:
    PC.grounding_policy = real
key = s.data().get("refactoring_share") or {}
check_eq("an unreadable policy: road unknown with the reason, written, not stop and not none", (key.get("road"), "cannot be found" in key.get("reason", "")), ("unknown", True))
check_in("...the printed line says unknown", "unknown", lines[0])
cleanup(s.root)

s = Story(source="current-code", diff=None)
snapshot = s.digest()
done = s.run("--share")
check_eq("not a diff: exit 0, nothing written (no table made, no file changed)", (done.returncode, s.digest()), (0, snapshot))
check("...and the output says why", "nothing was written" in done.stdout, done.stdout)
s2 = Story(source=None, diff=None)
snapshot = s2.digest()
check_eq("no source recorded and no diff: exit 0, nothing written", (s2.run("--share").returncode, s2.digest()), (0, snapshot))
cleanup(s.root)
cleanup(s2.root)

s = Story()
snapshot = s.digest()
done = s.run("--share")
check_eq("the world diff but no table yet: exit 0, no table is made", (done.returncode, s.digest()), (0, snapshot))
check_in("...the line says unknown and why", "R0", done.stdout)
check("...and says nothing was written", "Nothing was written" in done.stdout, done.stdout)

s.labelled(NUM, NUM, OTHER)
s.table.write_bytes(s.table.read_bytes() + b"rows:\n  - [a\n")
snapshot = s.digest()
done = s.run("--share")
check_eq("a table the reader refuses (a line it cannot parse): exit 0, the file is byte for byte as it was, no key", (done.returncode, s.digest()), (0, snapshot))
check_in("...the line names R0", "R0", done.stdout)
s.table.write_bytes(b"rows: [\n  - {broken\n")
snapshot = s.digest()
done = s.run("--share")
check_eq("broken YAML: R0, nothing written", (done.returncode, "R0" in done.stdout, s.digest()), (0, True, snapshot))
cleanup(s.root)

s = Story()
s.labelled(NUM, NUM, OTHER)
snapshot = s.digest()
for args in (("--share", "--check"), ("--share", "--skeleton"), ("--share", "--refresh")):
    done = s.run(*args)
    check_eq(f"{' '.join(args)}: argparse refuses (exit 2), nothing written", (done.returncode, s.digest()), (2, snapshot))
for label, task in (("an empty --task", ""), ("a missing story", "NO-SUCH-1"), ("a long --task", "T" * 300), ("a Cyrillic --task", "".join(map(chr, (0x417, 0x410, 0x414, 0x410, 0x427, 0x410))) + "-1")):
    mine, theirs = s.run("--share", task=task), s.run("--check", task=task)
    check_eq(f"{label}: --share ends as --check does", mine.returncode, theirs.returncode)
    check_eq(f"{label}: nothing written", s.digest(), snapshot)
cleanup(s.root)

finish("test_grounding_share")
