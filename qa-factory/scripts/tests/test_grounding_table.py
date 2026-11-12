"""The grounding table by code (G1-4): skeleton, refresh, check (R0..R5, R8), hunk ids, orphans, the one YAML writer.

Edges (spec t-1014 sections 4, 5, L-2, L-3): a hunk id is a hash of the index `body` (markers included), a label moves only with the
same `(sha256, occurrence)`, an orphan is kept and its id never reused, `--check` writes nothing and prints detector form 1, the
join diff <-> manifest goes through `HC.implementation_entries`, and a table the reader cannot read is R0, never a pass.
"""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, run_script, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import detector_verdict as DV  # noqa: E402
import diff_pass as DP  # noqa: E402
import grounding_table as GT  # noqa: E402
import planning_contract as PC  # noqa: E402



def _write_text_lf(self, data, encoding="utf-8", errors=None, newline=None):
    """`Path.write_text` that never turns LF into CRLF: on Windows it would, and the table (rightly) refuses a CR."""
    self.write_bytes(data.encode(encoding))
    return len(data)


Path.write_text = _write_text_lf
REAL = Path(__file__).resolve().parents[4] / "experiments" / "TP1-13877"
REG = ("# Register\n\n## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact |\n"
       "|---|---|---|---|---|---|---|---|\n| R-1 | First thing | ac | — | yes | AC1 | diff:a.py:1 | access |\n"
       "| R-2 | Second thing | ac | — | yes | AC2 | diff:a.py:2 | access |\n| R-3 | Third thing | ac | — | yes | AC3 | none | access |\n\n"
       "## Contradiction matrix\n")
LABELS = list(GT.H.vocabulary()["grounding_labels"])
EMPTY_BLAST = {"index": {"state": "built"}, "areas": []}


def hunk(start, lines, fn=""):
    old = sum(1 for x in lines if x[0] in " -")
    new = sum(1 for x in lines if x[0] in " +")
    return [f"@@ -{start},{old} +{start},{new} @@" + (f" {fn}" if fn else "")] + lines


def section(path, *hunks):
    return [f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}"] + [x for h in hunks for x in h]


def diff_text(*sections, eol="\n"):
    return eol.join(x for s in sections for x in s) + eol


A1 = section("src/a.py", hunk(10, [" ctx", "-old_a", "+new_a", " tail"], "def a()"), hunk(40, ["-x = 1", "+x = 2"]))
B1 = section("src/b.py", hunk(5, ["+added_b"]))
BASE = diff_text(A1, B1)


class Story:
    """A temporary project with one story: pipeline, work/impl-diff.txt, the register, an optional manifest."""

    def __init__(self, diff=BASE, source="diff", register=REG, manifest=None, blast=EMPTY_BLAST):
        self.root = temp_project("qa-grounding-")
        self.task = self.root / "qa-factory" / "artifacts" / "T-1"
        (self.task / "work").mkdir(parents=True)
        pipe = {"ticket": "T-1", "stages": {}}
        if source is not None:
            pipe["implementation_source"] = source
        (self.task / "pipeline.json").write_text(json.dumps(pipe), encoding="utf-8")
        if diff is not None:
            self.diff(diff)
        if register is not None:
            (self.task / "work" / "requirements-register.md").write_text(register, encoding="utf-8")
        if manifest is not None:
            (self.task / "work" / "context-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        if blast is not None:                                   # the index file the driver would have built (R8 reads THIS, not the table)
            self.blast(blast)

    def blast(self, content):
        """Write `work/blast-radius.json`: a mapping is dumped as JSON, a string is written as it is (a broken file)."""
        (self.task / "work" / GT.BLAST_FILE).write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")

    def diff(self, text, name="impl-diff.txt"):
        (self.task / "work" / name).write_bytes(text.encode("utf-8"))

    @property
    def table(self):
        return GT.table_path(self.task)

    def run(self, *args, task="T-1"):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.root), PYTHONDONTWRITEBYTECODE="1")
        return run_script("grounding_table.py", *args, "--task", task, cwd=self.root, env=env)

    def skeleton(self):
        done = self.run("--skeleton")
        assert done.returncode == 0, done.stderr
        return self.data()

    def data(self):
        doc, problem = PC.read_grounding(self.task)
        assert doc is not None, problem
        return doc.data

    def edit(self, fn):
        data = self.data()
        fn(data)
        GT.write_yaml(self.table, data)
        return data

    def text_edit(self, old, new, count=1):
        text = self.table.read_text(encoding="utf-8")
        assert old in text, old
        self.table.write_text(text.replace(old, new, count), encoding="utf-8")

    def tree_hash(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(self.root.rglob("*")) if p.is_file()}

    def rules(self):
        return [f.rule for f in GT.check(self.task)]

    def done(self):
        cleanup(self.root)


def label_all(data, label="refactoring"):
    """Label every row (the story's `work/blast-radius.json` is the empty built index, `Story` writes it)."""
    for row in data["rows"]:
        row["label"], row["reason"] = label, "ok"


def find(story, rule):
    return [f.text for f in GT.check(story.task) if f.rule == rule]


# --- T1: the skeleton on the real 13877 copy -------------------------------------------------------------------------------
if REAL.is_dir():
    s = Story(diff=None, register=None)
    shutil.rmtree(s.task)
    shutil.copytree(REAL, s.task, ignore=shutil.ignore_patterns("state"))
    pipe = json.loads((s.task / "pipeline.json").read_text(encoding="utf-8"))
    pipe["implementation_source"] = "diff"
    (s.task / "pipeline.json").write_text(json.dumps(pipe), encoding="utf-8")
    index = DP.index(s.task / "work")
    real_hunks = [h for f in index["files"] for h in f["hunks"] if not h.get("pseudo")]
    check_eq("13877: the index holds 35 real hunks", len(real_hunks), 35)
    data = s.skeleton()
    check_eq("13877: one hunk record per index hunk (35 + the pseudo-hunk)", len(data["hunks"]), len(real_hunks) + 1)
    check_eq("13877: one empty row per hunk", [len(r["hunks"]) for r in data["rows"]], [1] * len(data["hunks"]))
    ids = GT.C.register_ids(s.task / "work" / "requirements-register.md")
    check_eq("13877: a line per requirement of the register", [x["r"] for x in data["requirements"]],
             [r for r in ids if r not in GT.C.implementation_only((s.task / "work" / "requirements-register.md").read_text(encoding="utf-8"))])
    check_eq("13877: three manifest entries, the diff joins backend by its basename; the commit is copied",
             (data["diff"][0]["implementation_commit"][:8], data["diff"][0]["repo_id"]), ("66014ac2", "testproject1-backend"))
    doc, problem = PC.read_grounding(s.task)
    check("13877: the skeleton reads back through read_grounding as (Doc, '')", doc is not None and problem == "", str(problem))
    built = GT.skeleton(GT.gather(s.task))                  # the in-memory table, never read back: the other side of the round trip
    check_eq("13877: the round trip keeps every hunk record (in-memory skeleton == what read_grounding returns)", doc.data["hunks"], built["hunks"])
    check_eq("13877: ...and the whole table", doc.data, built)
    s.done()
else:
    print("SKIP the 13877 pins: experiments/TP1-13877 is not in this tree (the synthetic pins below still run)")

# --- T2: ids and the round trip of the writer ------------------------------------------------------------------------------
def ids_of(text):
    s = Story(diff=text)
    try:
        return [h["id"] for h in s.skeleton()["hunks"]]
    finally:
        s.done()


base_ids = ids_of(BASE)
same_body = diff_text(section("one.py", hunk(1, ["-q", "+w"])), section("two.py", hunk(1, ["-q", "+w"])))
check("a body in two files: two ids", len(set(ids_of(same_body))) == 2)
twice = diff_text(section("one.py", hunk(1, ["-q", "+w"]), hunk(20, ["-q", "+w"])))
check_eq("a body twice in one file: occurrence -1, -2 after the same prefix", [i.split("-")[1] for i in ids_of(twice)], ["1", "2"])
check_eq("the same prefix for the two equal bodies", len({i.rsplit("-", 1)[0] for i in ids_of(twice)}), 1)
shifted = diff_text(section("src/a.py", hunk(10, [" ctx", "-old_a", "+new_a", " tail"], "def a()"), hunk(40, ["-x = 1", "+x = 2"])),
                    section("src/c.py", hunk(1, ["+zzz"])), B1)
check("an inserted file does not move the ids of the others", set(base_ids) <= set(ids_of(shifted)))
check_eq("a CRLF copy gives the same ids", ids_of(BASE.replace("\n", "\r\n")), base_ids)
check("a bare CR inside a line gives another id", ids_of(BASE.replace("+added_b", "+added\rb")) != base_ids)
check("an indent change gives another id", ids_of(BASE.replace("+added_b", "+ added_b")) != base_ids)
check_eq("only the text after the second @@ changes: the same ids", ids_of(BASE.replace("def a()", "def renamed()")), base_ids)
check("a context-only edit gives another id (the hash is over the body, not the +/- lines)", ids_of(BASE.replace(" ctx", " ctx2")) != base_ids)
eof = diff_text(section("e.py", hunk(1, ["-x", "+y"])))
eof_nl = diff_text(section("e.py", hunk(1, ["-x", "\\ No newline at end of file", "+y"])))
check("the no-newline marker is part of the body: an EOF-only edit gives another id", ids_of(eof) != ids_of(eof_nl))
above = diff_text(section("src/a.py", hunk(2, ["+inserted_top"]), hunk(11, [" ctx", "-old_a", "+new_a", " tail"], "def a()"), hunk(41, ["-x = 1", "+x = 2"])), B1)
check("a hunk inserted ABOVE in the same file shifts the line numbers of the lower ones: their ids do not move (no position in the hash)",
      set(base_ids) <= set(ids_of(above)) and len(ids_of(above)) == len(base_ids) + 1)
s = Story()
tricky = ["007", "a #b", "{x}", "x, y", "q\"uote\\", "line" + chr(0x2028) + "sep", "nel" + chr(0x85) + "x", "bom" + chr(0xFEFF) + "x", "tab\there",
          "yes", "null", "30.1", "- dash", "[a]", "", "lone" + chr(0xD800), "p" + chr(0x2029) + "q", "vt" + chr(0x0B) + "ff" + chr(0x0C)]
GT.write_yaml(s.table, {"schema_version": 1, "implementation_source": "diff", "rows": [{"id": "G-1", "reason": t, "hunks": [t or "e"]} for t in tricky]})
doc, problem = PC.read_grounding(s.task)
check("the writer's output is read by read_grounding", doc is not None, str(problem))
check_eq("every tricky string reads back as written", [r["reason"] for r in doc.data["rows"]], tricky)
check_eq("a number-like string stays a string", type(doc.data["rows"][0]["reason"]).__name__, "str")
s.done()
check_eq("dump_yaml is deterministic", GT.dump_yaml({"a": [{"b": 1, "c": []}]}), GT.dump_yaml({"a": [{"b": 1, "c": []}]}))
check_eq("a flow map or list with content is never written", [ln for ln in GT.dump_yaml({"a": [{"b": {"c": 1}}], "d": ["x"]}).splitlines() if "{c" in ln or "[x" in ln], [])

# --- T3: a prefix collision lengthens both ids, and the labels still move ------------------------------------------------------
real_digest = GT._digest
try:
    def build(story):
        GT.write_yaml(story.table, GT.skeleton(GT.gather(story.task)))
        return story.data()

    GT._digest = lambda text: "0123456789ab" + real_digest(text)[12:]
    s = Story()
    wide = [h["id"] for h in build(s)["hunks"]]
    check("a shared 12-hex prefix: every colliding id has 16 hex", all(len(i.split("-")[0]) == 16 for i in wide), str(wide))
    GT._digest = lambda text: "0123456789abcdef" + real_digest(text)[16:]
    wider = [h["id"] for h in build(s)["hunks"]]
    check("a shared 16-hex prefix: 20 hex", all(len(i.split("-")[0]) == 20 for i in wider), str(wider))
    s.edit(lambda d: label_all(d))
    s.diff(diff_text(section("src/a.py", hunk(10, [" ctx", "-old_a", "+new_a", " tail"], "def a()"))))
    new, report = GT.refresh_table(s.data(), GT.gather(s.task))
    check_eq("a partner leaves, the id shortens, the label still moves (the key is (sha256, occurrence), not the id)",
             ([r["label"] for r in new["rows"]], len(new["hunks"][0]["id"].split("-")[0]), len(new["orphans"])), (["refactoring"], 12, 2))
    s.done()
finally:
    GT._digest = real_digest

# --- T4: refresh and orphans -----------------------------------------------------------------------------------------------
s = Story()
data = s.skeleton()
s.edit(lambda d: [d["rows"][i].update(label="implements", requirements=["R-1"], reason=f"r{i}") for i in range(3)])
first = s.table.read_bytes()
done = s.run("--refresh")
check_eq("a refresh on the same bytes: exit 0 and the same bytes (idempotent)", (done.returncode, s.table.read_bytes() == first), (0, True))
s.diff(diff_text(section("src/a.py", hunk(2, ["+inserted_top"]), hunk(10, [" ctx", "-old_a", "+new_a", " tail"], "def a()"), hunk(40, ["-x = 1", "+x = 2"])), B1))
done = s.run("--refresh")
after = s.data()
check_eq("an inserted hunk: exit 0, three old labels in place, one new empty row", (done.returncode, [r["label"] for r in after["rows"]]), (0, ["implements"] * 3 + [""]))
check_eq("...the new row is G-4 (max + 1)", after["rows"][-1]["id"], "G-4")
s.diff(diff_text(section("src/a.py", hunk(10, [" ctx", "-old_a", "+new_a2", " tail"], "def a()"), hunk(40, ["-x = 1", "+x = 2"])), B1))
done = s.run("--refresh")
after = s.data()
check_eq("a changed hunk: its row goes to orphans (hunk_gone), the others stay", ([o["why_orphan"] for o in after["orphans"]], len(after["rows"])), (["hunk_gone"], 3))
check_eq("...the orphan keeps the label, the requirement, the reason, the old hunk id and the diff sha",
         (after["orphans"][0]["was"], after["orphans"][0]["label"], after["orphans"][0]["requirements"], after["orphans"][0]["reason"],
          after["orphans"][0]["hunks"] == [data["hunks"][0]["id"]], len(after["orphans"][0]["diff_sha"])), ("row", "implements", ["R-1"], "r0", True, 64))
check("...and the new hunk's row never reuses an orphaned id, nor the id (G-4) of the empty row dropped in this very refresh (F-7): G-5",
      after["rows"][-1]["id"] not in {o["id"] for o in after["orphans"]} and after["rows"][-1]["id"] == "G-5", str(after["rows"][-1]["id"]))
s.diff(diff_text(section("src/a.py", hunk(10, [" ctx", "-old_a", "+new_a2", " tail"], "def a()"), hunk(40, ["-x = 1", "+x = 2"]))))
s.run("--refresh")
after = s.data()
check_eq("a removed file: its row is an orphan too, earlier orphans survive", sorted(o["why_orphan"] for o in after["orphans"]), ["hunk_gone", "hunk_gone"])
last_orphan = max(int(o["id"][2:]) for o in after["orphans"])
s.diff(diff_text(A1, B1, section("src/new.py", hunk(1, ["+n"]))))
s.run("--refresh")
after = s.data()
check("the id of an orphan taken from the LAST row is not given to a new row", all(int(r["id"][2:]) > last_orphan or r["id"] in {"G-1", "G-2"} for r in after["rows"] if r["label"] == ""), str([r["id"] for r in after["rows"]]))
s.done()
# F-7: an id given out is never given out again - the P7 scenario of the critic (a hunk changes, its bytes come back)
s = Story()
s.skeleton()
s.edit(lambda d: label_all(d))
changed = diff_text(A1, section("src/b.py", hunk(5, ["+added_b_changed"])))
s.diff(changed)
s.run("--refresh")
first_new = s.data()["rows"][-1]["id"]
s.diff(BASE)
s.run("--refresh")
back = s.data()
issued = [r["id"] for r in back["rows"]] + [o["id"] for o in back["orphans"]]
check_eq("F-7: the empty row of the changed hunk (G-4) is dropped when the hunk leaves; the returning hunk does NOT get G-4 again",
         (first_new, len(issued) == len(set(issued)), back["rows"][-1]["id"]), ("G-4", True, "G-5"))
# F-7: a table that holds only orphans still advances the counter (the source goes away and comes back)
s = Story()
s.skeleton()
s.edit(lambda d: label_all(d))
(s.task / "pipeline.json").write_text(json.dumps({"ticket": "T-1", "implementation_source": "current-code"}), encoding="utf-8")
(s.task / "work" / "impl-diff.txt").unlink()
s.run("--refresh")
(s.task / "pipeline.json").write_text(json.dumps({"ticket": "T-1", "implementation_source": "diff"}), encoding="utf-8")
s.diff(BASE)
s.run("--refresh")
back = s.data()
check_eq("F-7: ONLY orphans left (G-1..G-3 kept as source_changed): the new rows start at G-4", [r["id"] for r in back["rows"]], ["G-4", "G-5", "G-6"])
s.done()
s = Story(diff=diff_text(section("f.py", hunk(1, ["-a", "+b"]), hunk(30, ["-c", "+d"]))))
s.skeleton()
s.edit(lambda d: d["rows"].__setitem__(slice(None), [{"id": "G-1", "hunks": "all::f.py", "label": "infrastructure", "requirements": [], "risks": [], "question": "", "reason": "whole"}]))
s.diff(diff_text(section("f.py", hunk(1, ["-a", "+b"]), hunk(30, ["-c", "+d"]), hunk(60, ["+e"]))))
s.run("--refresh")
rows = s.data()["rows"]
check_eq("an all: row does not inherit a new hunk of its file: explicit old ids, one new empty row", ([len(r["hunks"]) for r in rows], [r["label"] for r in rows]), ([2, 1], ["infrastructure", ""]))
s.diff(diff_text(section("f.py", hunk(1, ["-a", "+b"]), hunk(30, ["-c", "+d"]))))
s.run("--refresh")
check_eq("...an empty row whose hunk left is dropped silently; the labelled row stays", ([r["label"] for r in s.data()["rows"]], s.data().get("orphans")),(["infrastructure"], None))
s.done()
s = Story()
s.skeleton()
s.edit(lambda d: d["requirements"][0].update(state="implemented", hunks=[d["hunks"][0]["id"]], where=""))
s.edit(lambda d: d["requirements"][1].update(state="unknown", question="what is meant?"))
(s.task / "work" / "requirements-register.md").write_text(REG.replace("| R-3 | Third thing", "| R-9 | Third thing").replace("First thing", "First thing, reworded"), encoding="utf-8")
s.run("--refresh")
after = s.data()
check_eq("a reworded requirement goes to orphans (requirement_changed), its line is empty again",
         ([o["why_orphan"] for o in after["orphans"] if o["was"] == "requirement"], after["requirements"][0]["state"]), (["requirement_changed", "requirement_gone"], ""))
check_eq("a requirement that left the register is kept whole (requirement_gone); a new one gets an empty line; an unchanged one is carried",
         ([x["r"] for x in after["requirements"]], after["requirements"][1]["question"]), (["R-1", "R-2", "R-9"], "what is meant?"))
check("...the orphan carries state and question verbatim", {o["id"]: o["state"] for o in after["orphans"]}.get("R-1") == "implemented")
s.done()
s = Story()
(s.task / "work" / "impl-diff.txt").write_bytes(BASE.encode("utf-8").replace(b"added_b", b"added_\xff"))
s.skeleton()
s.edit(lambda d: label_all(d))
s.run("--refresh")
check_eq("a body with a replacement character (U+FFFD) never moves its label, even on the same bytes: its row goes to orphans",
         ([r["label"] for r in s.data()["rows"]].count("refactoring"), [o["why_orphan"] for o in s.data()["orphans"]]), (2, ["hunk_gone"]))
s.done()
s = Story()
s.skeleton()
s.edit(lambda d: label_all(d))
s.table.write_text("schema_version: 1\nimplementation_source: diff\nrows:\n  - id: G-1\n    label: [oops\n", encoding="utf-8")
done = s.run("--refresh")
check_eq("--refresh on a table that cannot be read: exit 2, nothing written, --force named", (done.returncode, "--force" in done.stderr), (2, True))
unreadable_bytes = s.table.read_bytes()
refusals = [done.stderr, s.run("--skeleton").stderr, s.run("--skeleton", "--force").stderr]
done = s.run("--refresh", "--force")
kept = sorted((s.task / "work").glob("grounding.unreadable-*.yaml"))
check_eq("--refresh --force writes a new table, keeps the old bytes beside it and names them in one orphan (table_unreadable)",
         (done.returncode, {o["why_orphan"] for o in s.data()["orphans"]}, [p.read_bytes() for p in kept] == [unreadable_bytes]), (0, {"table_unreadable"}, True))
check_eq("--skeleton on an existing table: exit 2 and the door --refresh", (s.run("--skeleton").returncode, "--refresh" in s.run("--skeleton").stderr), (2, True))
check_eq("--skeleton --force is refused too (no mark is discarded)", s.run("--skeleton", "--force").returncode, 2)
check("F-4: every text about --force states both facts (old bytes kept beside the table, ONE orphan points at them)",
      all("grounding.unreadable-<sha8>.yaml" in t and "ONE orphan" in t for t in refusals), str(refusals)[:400])
check("F-4: ...none says the old content is read 'as orphans'", not any("read as orphans" in t for t in refusals))
check("F-4: each refusal ends with a period and says nothing was written", all(t.strip().endswith("nothing was written.") for t in refusals), str(refusals)[:300])
s.done()
# F-1: the door R0 names is the door that works - empty, `{}`, comment only, a list at the top
for label, content in (("empty", ""), ("{}", "{}\n"), ("comment only", "# nothing\n"), ("a list at the top", "- a\n- b\n")):
    s = Story()
    s.skeleton()
    s.table.write_bytes(content.encode("utf-8"))
    found = GT.check(s.task)
    check_eq(f"F-1 ({label}): R0 for the conductor, naming exactly `--refresh --force`", ([(f.rule, f.who) for f in found], "`--refresh --force`" in found[0].text), ([("R0", "conductor")], True))
    plain = s.run("--refresh")
    check_eq(f"F-1 ({label}): --refresh without --force: exit 2, the door named, nothing written", (plain.returncode, "--refresh --force" in plain.stderr, s.table.read_bytes() == content.encode("utf-8")), (2, True, True))
    forced = s.run("--refresh", "--force")
    kept = sorted((s.task / "work").glob("grounding.unreadable-*.yaml"))
    after = s.data()
    check_eq(f"F-1 ({label}): --refresh --force: exit 0, old bytes beside, one table_unreadable orphan, a table the check no longer calls R0",
             (forced.returncode, [p.read_bytes() for p in kept], [o["why_orphan"] for o in after["orphans"]], "R0" in s.rules()),
             (0, [content.encode("utf-8")], ["table_unreadable"], False))
    s.done()

# --- T5: the rules, at and beyond their limits -------------------------------------------------------------------------------
many = diff_text(*[section(f"f{i}.py", hunk(1, [f"-a{i}", f"+b{i}"])) for i in range(8)])
s = Story(diff=many)
s.skeleton()
for k in (0, 1, 6, 7):
    s.edit(lambda d: [r.update(label="refactoring", reason="ok") for r in d["rows"]])
    s.edit(lambda d: [d["rows"][i].update(label="") for i in range(k)])
    text = " ".join(find(s, "R1"))
    check(f"R1 with {k} unlabelled hunks", (not text) if k == 0 else (f"{k} of 8 hunks" in text and ("more (" in text) == (k > 6)), text[:200])
check_in("R1 AT 6: no tail; BEYOND (7): 'and 1 more (rows with label \"\" in work/grounding.yaml)'", 'and 1 more (rows with label "" in work/grounding.yaml)', " ".join(find(s, "R1")))
s.edit(lambda d: label_all(d))
s.edit(lambda d: d["rows"].pop(0))
check("R1 counts by the recomputed index: a deleted row hides nothing", any("1 of 8 hunks" in t for t in find(s, "R1")), str(s.rules()))
s.done()
s = Story()
s.skeleton()
s.edit(lambda d: label_all(d))
s.edit(lambda d: [x.update(state="outside_diff", where="elsewhere") for x in d["requirements"]])
check_eq("clean table: no findings", GT.check(s.task), [])
s.edit(lambda d: d["requirements"].pop())
check("R2: a requirement with no line", any("R-3" in t for t in find(s, "R2")))
s.edit(lambda d: d["requirements"].append({"r": "R-3", "state": "", "hunks": [], "where": "", "question": ""}))
check("R2: state \"\"", any("R-3" in t for t in find(s, "R2")))
s.edit(lambda d: d["requirements"][-1].update(state="implemented"))
check("R2: implemented with no hunks", any("implemented with no hunks" in t for t in find(s, "R2")))
s.edit(lambda d: d["requirements"][-1].update(state="unknown"))
check("R2: unknown with no question", any("no `question`" in t for t in find(s, "R2")))
s.edit(lambda d: d["requirements"][-1].update(state="unknown", question="what?"))
check_eq("R2: unknown with a question passes", find(s, "R2"), [])
reg = REG.replace("| R-3 |", "| R-3a |")
(s.task / "work" / "requirements-register.md").write_text(reg, encoding="utf-8")
s.edit(lambda d: d.update(register_sha256=hashlib.sha256(reg.encode("utf-8")).hexdigest()))
check("R2: a register row the id reader drops (R-3a) is named", any("R-3a" in t for t in find(s, "R2")))
(s.task / "work" / "requirements-register.md").write_text(REG, encoding="utf-8")
s.edit(lambda d: d.update(register_sha256=hashlib.sha256(REG.encode("utf-8")).hexdigest()))
s.done()
s = Story()
s.skeleton()
s.edit(lambda d: [x.update(state="outside_diff", where="w") for x in d["requirements"]])
s.edit(lambda d: label_all(d))
for reason, expect in (("x" * 160, False), ("x" * 161, True)):
    s.edit(lambda d: d["rows"][0].update(reason=reason))
    check(f"R3: reason of {len(reason)} characters", bool(find(s, "R3")) == expect)
for qlen, expect in ((300, False), (301, True)):
    s.edit(lambda d: d["rows"][0].update(reason="ok", question="q" * qlen))
    check(f"R3: question of {qlen} characters", bool(find(s, "R3")) == expect)
s.edit(lambda d: d["rows"][0].update(question=""))
s.edit(lambda d: d["rows"][0].update(label="refactor"))
check("R3: a label outside the list", any("refactor" in t for t in find(s, "R3")))
s.edit(lambda d: d["rows"][0].update(label="refactoring"))
for raw, name in (("reason: fix #12", "a comment"), ("reason: {code}", "a map"), ("reason: 007", "digits"), ("reason: first\n      second", "a line break")):
    s.edit(lambda d: d["rows"][0].update(reason="ok"))
    s.text_edit('reason: "ok"', raw)
    check(f"R3: a value the reader takes differently ({name})", any("reader" in t or "differently" in t for t in find(s, "R3")), str(find(s, "R3")))
# F-6: every scalar the role writes is read as written - a person's words are never cut silently (risk hypothesis, requirement list, claim)
s.edit(lambda d: d["rows"][0].update(reason="ok", requirements=["R-1"], risks=[{"id": "K-7", "hypothesis": "login fails"}]))
s.edit(lambda d: d.update(claims=[{"row": "G-1", "text": "claim words"}]))
check_eq("F-6: clean before the comment", [t for t in find(s, "R3")], [])
for old, new, words, what in (('hypothesis: "login fails"', "hypothesis: login fails # keep these words", ["K-7", "hypothesis", "comment"], "risks[].hypothesis"),
                              ('- "R-1"', "- R-1 # which one", ["requirements", "comment"], "rows[].requirements[] item"),
                              ('text: "claim words"', "text: claim words # more", ["claim G-1", "text", "comment"], "claims[].text")):
    s.text_edit(old, new, count=1)
    r3 = " ".join(find(s, "R3"))
    check(f"F-6: ` #` in {what} is an R3 finding that names it (the text is not cut silently)", all(w in r3 for w in words), r3[:300])
    s.text_edit(new, old, count=1)
s.done()
s = Story()
s.skeleton()
s.edit(lambda d: [x.update(state="outside_diff", where="w") for x in d["requirements"]])
s.edit(lambda d: label_all(d))
imp = lambda d: d["rows"][0].update(label="implements", requirements=["R-30"])        # noqa: E731
s.edit(imp)
check("R4: implements names an R the register does not hold", any("R-30" in t for t in find(s, "R4")))
s.edit(lambda d: d["rows"][0].update(requirements=[]))
check("R4: implements names no requirement", any("names no requirement" in t for t in find(s, "R4")))
s.edit(lambda d: d["rows"][0].update(label="refactoring", hunks=["deadbeef0000-1"]))
check("R4: a hunk id that is not in the diff", any("deadbeef0000-1" in t for t in find(s, "R4")))
s.edit(lambda d: d["rows"][0].update(hunks=["all:x:nowhere.py"]))
check("R4: an all: of a file that is not in the diff", any("nowhere.py" in t for t in find(s, "R4")))
s.edit(lambda d: d["rows"][0].update(hunks=[d["hunks"][0]["id"]], label="behaviour_change"))
check("R4: behaviour_change with no claims[] entry", any("behaviour_change" in t for t in find(s, "R4")))
s.edit(lambda d: d.update(claims=[{"r": "R-1", "row": d["rows"][0]["id"]}]))
check_eq("R4: ...and with one it passes", [t for t in find(s, "R4") if "behaviour_change" in t], [])
s.edit(lambda d: d["rows"][0].update(label="unclassified", reason="", question=""))
check("R4: unclassified with no question and no reason", sum("unclassified" in t for t in find(s, "R4")) == 1 and "`question`" in " ".join(find(s, "R4")))
s.edit(lambda d: d["rows"][0].update(label="refactoring", reason="ok"))
s.edit(lambda d: d["rows"][1].update(id=d["rows"][0]["id"]))
check("R4: a duplicate G id is named in both places", any("rows[0] and rows[1]" in t for t in find(s, "R4")))
s.edit(lambda d: d["rows"][1].update(id="G-2"))
s.edit(lambda d: [d["rows"][0].update(risks=[{"id": "K-1", "hypothesis": "h"}]), d["rows"][1].update(risks=[{"id": "K-1", "hypothesis": "h"}])])
check("R4: a duplicate K id", any("K-1" in t for t in find(s, "R4")))
s.edit(lambda d: [d["rows"][0].update(risks=[]), d["rows"][1].update(risks=[])])
s.edit(lambda d: [d["rows"][0].update(label="implements", requirements=["R-1"]), d["requirements"][0].update(state="implemented", hunks=[d["hunks"][1]["id"]])])
check("R4 (F-11): implemented on a hunk no implements row ties to this R", any("no implements row" in t for t in find(s, "R4")))
s.edit(lambda d: d["requirements"][0].update(hunks=[d["hunks"][0]["id"]]))
check_eq("R4 (F-11): tied hunk passes", [t for t in find(s, "R4") if "no implements row" in t], [])
s.done()
# R5
for name, act, words in (("the diff moved", lambda s: s.diff(BASE + "\n" + diff_text(section("n.py", hunk(1, ["+n"])))), "moved"),
                         ("the register changed", lambda s: (s.task / "work" / "requirements-register.md").write_text(REG + "\nmore\n", encoding="utf-8"), "register changed"),
                         ("the source changed", lambda s: s.edit(lambda d: d.update(implementation_source="current-code")), "implementation_source"),
                         ("a hunk record was removed", lambda s: s.edit(lambda d: d["hunks"].pop()), "was edited"),
                         ("a hunk record was edited", lambda s: s.edit(lambda d: d["hunks"][0].update(file="other.py")), "was edited")):
    s = Story()
    s.skeleton()
    s.edit(lambda d: label_all(d))
    act(s)
    found = GT.check(s.task)
    check(f"R5 stops everything else ({name}) and says why", {f.rule for f in found} == {"R5"} and any(words in f.text for f in found), str([f.text[:80] for f in found]))
    s.done()
man = {"implementations": [{"repo": "be", "diff_path": "x/work/impl-diff.txt", "source_sha": "a" * 40}]}
s = Story(manifest=man)
s.skeleton()
s.edit(lambda d: label_all(d))
man["implementations"][0]["source_sha"] = "b" * 40
(s.task / "work" / "context-manifest.json").write_text(json.dumps(man), encoding="utf-8")
check_eq("R5: the recorded commit moved (both hex)", s.rules(), ["R5"])
man["implementations"][0]["source_sha"] = "HEAD"
(s.task / "work" / "context-manifest.json").write_text(json.dumps(man), encoding="utf-8")
check_eq("R5: was hex, now unmeasured", s.rules(), ["R5"])
s.done()
# R8
s = Story()
s.skeleton()
s.edit(lambda d: [label_all(d), [x.update(state="outside_diff", where="w") for x in d["requirements"]]])
def areas(*items):
    """The index FILE gets the code part of each area (id, key, path_kind, tests ...); the table gets its projection and the role's
    judgement (matters, regression ...) - the split R8 reads."""
    def apply(d):
        code = [dict({"id": f"B-{i + 1}", "key": f":f{i}.py", "path_kind": "additive"}, **{k: v for k, v in a.items() if k not in GT.ROLE_AREA_FIELDS})
                for i, a in enumerate(items)]
        s.blast({"index": {"state": "built"}, "areas": code})
        d["blast_radius"] = GT.project_blast(GT.gather(s.task))
        for area, a in zip(d["blast_radius"]["areas"], items):
            area.update(dict({"matters": "no"}, **{k: v for k, v in a.items() if k in GT.ROLE_AREA_FIELDS}))
    return apply
s.edit(areas({}))
check_eq("R8: an additive area judged no passes", find(s, "R8"), [])
for kind in ("shared_path", "", "unmeasured", "xyz"):
    s.edit(areas({"path_kind": kind}))
    check(f"R8: matters no on path_kind {kind!r} with no regression", bool(find(s, "R8")))
s.edit(areas({"path_kind": "shared_path", "regression": "gap:no suite"}))
check_eq("R8: a gap: reason passes", find(s, "R8"), [])
s.edit(areas({"path_kind": "not_applicable"}))
check_eq("R8: not_applicable passes", find(s, "R8"), [])
s.edit(areas({"matters": "yes"}))
check("R8: matters yes with no regression", bool(find(s, "R8")))
s.edit(areas({"matters": ""}))
check("R8: matters \"\" (the silence is not 'not important')", bool(find(s, "R8")))
s.edit(areas({"matters": "yes", "regression": "pytest t", "tests": "none"}))
check("R8: yes with tests none and no add_tests", any("add_tests" in t for t in find(s, "R8")))
s.edit(areas({"matters": "yes", "regression": "pytest t", "tests": "none", "add_tests": "TS-4"}))
check_eq("R8: ...add_tests fills it", find(s, "R8"), [])
(s.task / "work" / GT.BLAST_FILE).unlink()
s.edit(lambda d: d.update(blast_radius={"index": {"state": "built"}, "areas": []}))
check("R8 (F-2): no index FILE at diff: R8 even though the table's own copy says `state: built`", "no blast radius index" in " ".join(find(s, "R8")))
s.edit(lambda d: d.pop("blast_radius"))
check("R8 (F-2): ...and when the table holds no blast_radius key at all", "no blast radius index" in " ".join(find(s, "R8")))
for label, text in (("bad JSON", "{not json"), ("a list", "[1, 2]"), ("no areas list", '{"index": {"state": "built"}}')):
    s.blast(text)
    found = [f for f in GT.check(s.task) if f.rule == "R8"]
    check_eq(f"R8 (F-2): the index file is unreadable ({label}): an R8 finding naming the file, never a pass", (len(found), "blast-radius.json cannot be read" in found[0].text, found[0].who), (1, True, "driver"))
done = s.run("--check")
check_eq("R8 (F-2): ...the CLI exits 1 (findings), never 2 and never 0", done.returncode, 1)
s.edit(areas({"matters": ""}))
s.edit(lambda d: d["blast_radius"].update(areas=[]))
texts = " ".join(find(s, "R8"))
check("R8 (F-2): the role deletes an unjudged area from the table: it is still named unjudged, and the edit is a finding", "are not judged" in texts and "do not match" in texts and "missing from the table" in texts, texts[:300])
s.edit(areas({"path_kind": "shared_path"}))
s.edit(lambda d: d["blast_radius"]["areas"][0].update(path_kind="additive"))
texts = " ".join(find(s, "R8"))
check("R8 (F-2): the role relabels a shared path as additive: the code part comes from the file, so the regression is still owed", "shared path" in texts and "differs from the index" in texts, texts[:300])
s.edit(areas({"matters": "no"}))
s.edit(lambda d: d["blast_radius"]["index"].update(state="stale"))
check_eq("R8 (F-2): a `stale` the role writes into the table does nothing either", find(s, "R8"), [])
s.done()
# --- the projection of the blast file ------------------------------------------------------------------------------------------
s = Story()
(s.task / "work" / GT.BLAST_FILE).write_text(json.dumps({"index": {"state": "built"}, "areas": [{"id": "B-7", "key": ":src/a.py", "touched": {"file": "src/a.py", "hunks": [
    {"diff": "impl-diff.txt", "old_start": 10, "new_start": 10}]}, "path_kind": "shared_path"}]}), encoding="utf-8")
blast = s.skeleton()["blast_radius"]
hid = s.data()["hunks"][0]["id"]
check_eq("blast: B-n is copied, positions become hunk ids, role fields start empty", (blast["areas"][0]["id"], blast["areas"][0]["touched"]["hunks"], blast["areas"][0]["matters"]), ("B-7", [hid], ""))
s.edit(lambda d: d["blast_radius"]["areas"][0].update(matters="yes", regression="pytest a"))
s.run("--refresh")
check_eq("blast: a refresh over the same hunks carries the area's role fields by key", s.data()["blast_radius"]["areas"][0]["regression"], "pytest a")
s.diff(BASE.replace("-old_a", "-old_a_changed"))
(s.task / "work" / GT.BLAST_FILE).write_text(json.dumps({"index": {"state": "built"}, "areas": [{"id": "B-7", "key": ":src/a.py", "touched": {"file": "src/a.py", "hunks": [
    {"diff": "impl-diff.txt", "old_start": 10, "new_start": 10}]}}]}), encoding="utf-8")
s.run("--refresh")
after = s.data()
check_eq("blast: the area's hunks changed: role fields reset, the judgement is an orphan (area_changed) with its own `why`",
         (after["blast_radius"]["areas"][0]["matters"], [(o["was"], o["why_orphan"], o["regression"]) for o in after["orphans"] if o["was"] == "area"]), ("", [("area", "area_changed", "pytest a")]))
(s.task / "work" / GT.BLAST_FILE).write_text(json.dumps({"index": {"state": "built"}, "areas": [{"id": "B-7", "key": ":src/a.py", "touched": {"file": "src/a.py", "hunks": [
    {"diff": "impl-diff.txt", "old_start": 999, "new_start": 999}]}}]}), encoding="utf-8")
s.run("--refresh")
check_eq("blast: a position that maps to no hunk marks the index stale (never dropped silently)", s.data()["blast_radius"]["index"]["state"], "stale")
(s.task / "work" / GT.BLAST_FILE).unlink()
done = s.run("--refresh")
check_eq("blast: no index file at --refresh: no `blast_radius` key (seam 3), exit 0, and `unreadable` carries no `areas`",
         (done.returncode, "blast_radius" in s.data()), (0, False))
s.blast("{broken")
s.run("--refresh")
check_eq("blast: an unreadable index file is written as `{index: {state: unreadable}}` - no `areas: []`", s.data()["blast_radius"], {"index": {"state": "unreadable"}})
s.done()
# Q-a (t-1224): the position is keyed WITH its file - two files whose hunks start at the same numbers are two hunk ids (13877: ten new
# files shared (impl-diff.txt, 0, 1) and ten areas resolved to ONE id)
s = Story(diff=diff_text(A1, B1, section("src/c.py", hunk(5, ["+added_c"]))))


def blast_area(number, file, *positions):
    return {"id": f"B-{number}", "key": f":{file}", "touched": {"file": file, "hunks": [{"diff": "impl-diff.txt", "old_start": o, "new_start": n} for o, n in positions]}}


s.blast({"index": {"state": "built"}, "areas": [blast_area(1, "src/b.py", (5, 5)), blast_area(2, "src/c.py", (5, 5)), blast_area(3, "src/a.py", (10, 10), (10, 10))]})
table = s.skeleton()
file_of = {h["id"]: h["file"] for h in table["hunks"]}
by_area = {a["id"]: a["touched"]["hunks"] for a in table["blast_radius"]["areas"]}
check_eq("Q-a: equal positions in DIFFERENT files: each area resolves to its OWN file's hunk (two distinct ids, index not stale)",
         ([file_of[i] for i in by_area["B-1"]], [file_of[i] for i in by_area["B-2"]], by_area["B-1"] != by_area["B-2"], table["blast_radius"]["index"]["state"]),
         (["src/b.py"], ["src/c.py"], True, "built"))
check_eq("Q-a: the SAME file twice at one position keeps ONE id", (len(by_area["B-3"]), len(set(by_area["B-3"])), file_of[by_area["B-3"][0]]), (2, 1, "src/a.py"))
s.blast({"index": {"state": "built"}, "areas": [blast_area(1, "src/a.py", (5, 5))]})
check_eq("Q-a: a position that exists only in ANOTHER file (src/b.py has (5, 5), src/a.py has not) is no match: the index is stale, never silently borrowed",
         GT.project_blast(GT.gather(s.task))["index"]["state"], "stale")
s.done()

# --- T6: --check writes nothing ------------------------------------------------------------------------------------------------
s = Story()
s.skeleton()
before = s.tree_hash()
done = s.run("--check")
check_eq("--check writes nothing (findings, exit 1)", (done.returncode, s.tree_hash() == before), (1, True))

# --- T7: detector form 1 ---------------------------------------------------------------------------------------------------------
verdict = DV.parse(done.returncode, done.stdout, done.stderr)
heads = [ln for ln in done.stdout.splitlines() if ln.startswith("REJECT")]
declared = int(re.match(r"REJECT — (\d+)", heads[0]).group(1))
check_eq("form 1: parse reads as many findings as the header declares, no defect, nothing unmigrated", (len(verdict["findings"]), verdict["defects"], verdict["unmigrated"]), (declared, [], ""))
check("form 1: every finding has the label [grounding R<n>], a fix, and ends with the FR-4 tail",
      all(re.match(r"^\[grounding R\d\] ", f) and " — fix: " in f and f.endswith(GT.TAIL) for f in verdict["findings"]), str(verdict["findings"])[:300])
check_eq("form 1: the label carries the check and the rule id", {DV.LABEL_RE.match(f).group(1) for f in verdict["findings"]}, {"grounding"})
for label, setup in (("R5 (the diff moved)", lambda: s.diff(BASE + "\n" + diff_text(section("n.py", hunk(1, ["+n"]))))),
                     ("R0 (schema_version 2)", lambda: s.table.write_text("schema_version: 2\n", encoding="utf-8")),
                     ("no table", lambda: s.table.unlink())):
    setup()
    before = s.tree_hash()
    done = s.run("--check")
    check_eq(f"--check writes nothing: {label}", (done.returncode, s.tree_hash() == before), (1, True))
check_eq("--check on a story that does not exist: exit 2, nothing written", (s.run("--check", task="NOPE").returncode, s.tree_hash() == before), (2, True))
s.done()

# --- T8: empty and absent ----------------------------------------------------------------------------------------------------------
s = Story()
check_eq("diff world, no table: R0, who = driver", [(f.rule, f.who) for f in GT.check(s.task)], [("R0", "driver")])
s.table.parent.mkdir(parents=True, exist_ok=True)
for content, who in (("", "conductor"), ("{}\n", "conductor"), ("- a\n", "conductor"), ("schema_version: 2\nimplementation_source: diff\n", "conductor"), ("schema_version: 1\nrows:\n  - id: G-1\n    label: [oops\n", "role")):
    s.table.write_text(content, encoding="utf-8")
    check_eq(f"diff world, table {content[:22]!r}: R0 and the door is {who}", [(f.rule, f.who) for f in GT.check(s.task)], [("R0", who)])
s.table.write_text("schema_version: 1\nrows: []\n", encoding="utf-8")
check_eq("no implementation_source: R0", [f.rule for f in GT.check(s.task)], ["R0"])
s.done()
s = Story(diff=None, source="current-code")
check_eq("off the diff, no table: no findings and a context line", (GT.check(s.task), "nothing to label" in " ".join(GT.check_report(s.task)[1])), ([], True))
done = s.run("--skeleton")
data = s.data()
policy, _ = PC.grounding_policy()
check_eq("off the diff: --skeleton writes the null form with the policy's words", (done.returncode, data["null_outcome"], sorted(data)),
         (0, {"source": "current-code", "words": policy["null_outcome_words"]["current-code"]}, ["implementation_source", "null_outcome", "schema_version"]))
check_eq("...and --check passes it", GT.check(s.task), [])
s.done()
s = Story(diff=None, source=None)
done = s.run("--skeleton")
check_eq("no source and no diff: the null outcome `absent` (exit 0, never 2)", (done.returncode, s.data()["null_outcome"]["source"], s.data()["implementation_source"]), (0, "absent", ""))
s.done()
s = Story(source="current-code")
check_eq("a diff on disk while the source is not diff: R0 for the conductor; --skeleton exit 2", ([(f.rule, f.who) for f in GT.check(s.task)], s.run("--skeleton").returncode), ([("R0", "conductor")], 2))
check_eq("source_state names the world", GT.source_state(s.task)[0], "mismatch")
s.done()
s = Story(diff="")
s.skeleton()
check_eq("E1: an empty diff gives no hunk, no row; --check says the diff has no hunk (R1)", ([GT.check(s.task)[0].rule], "no hunk" in GT.check(s.task)[0].text), (["R1"], True))
s.done()
s = Story()
s.skeleton()
s.edit(lambda d: label_all(d))
s.edit(lambda d: [x.update(state="outside_diff", where="w") for x in d["requirements"]])
(s.task / "pipeline.json").write_text(json.dumps({"ticket": "T-1", "implementation_source": "current-code"}), encoding="utf-8")
(s.task / "work" / "impl-diff.txt").unlink()
done = s.run("--refresh")
data = s.data()
check_eq("a source change at --refresh: the null form, every row/line is kept in orphans (source_changed)", (done.returncode, "rows" in data, {o["why_orphan"] for o in data["orphans"]}), (0, False, {"source_changed"}))
(s.task / "pipeline.json").write_text(json.dumps({"ticket": "T-1", "implementation_source": "diff"}), encoding="utf-8")
s.diff(BASE)
done = s.run("--refresh")
check_eq("the source is `diff` again: a new skeleton, the orphans stay", (done.returncode, len(s.data()["hunks"]), {o["why_orphan"] for o in s.data()["orphans"]}),
         (0, 3, {"source_changed"}))
s.done()
s = Story()
s.skeleton()
real_index = GT.DP.index
try:
    GT.DP.index = lambda work: {"files": [{"path": "p.py", "repo": "", "diff": "impl-diff.txt", "hunks": [{"new_start": 1, "lines": [], "header": ""}]}], "refusals": []}
    try:
        GT.skeleton(GT.gather(s.task))
        refused = ""
    except GT.Refusal as exc:
        refused = exc.text
    found = GT.check_report(s.task)[0]
finally:
    GT.DP.index = real_index
check("an index with no body: --skeleton refuses (FR-59), no hash by lines", "no hunk bodies" in refused, refused)
check_eq("...and --check says R1 on the index, for the conductor", [(f.rule, f.who) for f in found], [("R1", "conductor")])
s.done()

# --- the join diff <-> manifest ------------------------------------------------------------------------------------------------------
single = {"implementation": {"repo": "solo", "diff_path": "x/impl-diff.txt", "source_sha": "c" * 40}}
s = Story(manifest=single)
check_eq("a manifest with only the singular entry still joins (through HC.implementation_entries)", s.skeleton()["diff"][0]["implementation_commit"], "c" * 40)
s.done()
both = {"implementation": {"repo": "a", "diff_path": "impl-diff.txt", "source_sha": "d" * 40}, "implementations": [{"repo": "a", "diff_path": "impl-diff.txt", "source_sha": "d" * 40}]}
s = Story(manifest=both)
check_eq("both keys naming one diff: the list wins, ONE entry (not '2 manifest entries name')", s.skeleton()["diff"][0]["implementation_commit"], "d" * 40)
s.done()
for entries, expect in (([], "unmeasured: no manifest entry for impl-diff.txt"),
                        ([{"repo": "a", "diff_path": "impl-diff.txt", "source_sha": "e" * 40}, {"repo": "b", "diff_path": "z/impl-diff.txt", "source_sha": "f" * 40}], "unmeasured: 2 manifest entries name impl-diff.txt"),
                        ([{"repo": "a", "diff_path": "impl-diff.txt", "source_sha": "ABC"}], "unmeasured: source_sha 'ABC' is not a commit id"),
                        ([{"repo": "a", "diff_path": "impl-diff.txt"}], "unmeasured: no source_sha for repo a"),
                        ([{"repo": "a", "diff_path": "impl-diff.txt", "source_sha": "e" * 39}], "unmeasured: source_sha '" + "e" * 39 + "' is not a commit id"),
                        ([{"repo": "a", "diff_path": "impl-diff.txt", "source_sha": "e" * 64}], "e" * 64)):
    s = Story(manifest={"implementations": entries})
    check_eq(f"the commit: {expect[:60]}", s.skeleton()["diff"][0]["implementation_commit"], expect)
    s.done()
s = Story(diff=None, manifest={"implementations": [{"repo": "be", "source_sha": "a" * 40}]})
s.diff(BASE, "impl-diff-be.txt")
s.diff(BASE.replace("added_b", "added_c"), "impl-diff-ui.txt")
d = s.skeleton()["diff"]
check_eq("two diffs: the suffix joins by repo_id or repo; no match is unmeasured; repo_id is the entry's", [(x["repo"], x["repo_id"], x["implementation_commit"][:12]) for x in d],
         [("be", "be", "a" * 12), ("ui", "", "unmeasured: ")])
check_eq("...every hunk carries its repo (E8: a second repository is in the table)", sorted({h["repo"] for h in s.data()["hunks"]}), ["be", "ui"])
s.done()

# --- T9: magnitude ---------------------------------------------------------------------------------------------------------------
files = [section(f"d{i % 300}/f{i // 3}.py", *[hunk(1 + 40 * j, [f"-a{i}_{j}", f"+b{i}_{j}"]) for j in range(3)]) for i in range(3334)][:3334]
big = diff_text(*files)
check("magnitude: the synthetic diff is over 360 KB", len(big.encode("utf-8")) > 360_000, str(len(big)))
s = Story(diff=big)
s.skeleton()
n = len(s.data()["hunks"])
check_eq("10000 hunks: the table holds as many as the index", n, sum(len(f["hunks"]) for f in DP.index(s.task / "work")["files"]))
done = s.run("--check")
check("10000 unlabelled hunks: the output stays within 6000 bytes", len(done.stdout.encode("utf-8")) <= DV.FINDINGS_MAX_BYTES, str(len(done.stdout)))
check_in(f"...and names the rest: 'and {n - 6} more (rows with label \"\" in work/grounding.yaml)'", f'and {n - 6} more (rows with label "" in work/grounding.yaml)', done.stdout)
s.done()

# --- T10: E5, E14, P2 --------------------------------------------------------------------------------------------------------------
s = Story()
s.skeleton()
s.edit(lambda d: [x.update(state="outside_diff", where="w") for x in d["requirements"]])
s.edit(lambda d: label_all(d))
s.edit(lambda d: d["rows"][0].update(label="unclassified", reason="cannot tell", question="what is this?"))
check_eq("E5: unclassified with reason and question passes", GT.check(s.task), [])
s.edit(lambda d: d["rows"][1].update(hunks=[d["hunks"][0]["id"], d["hunks"][1]["id"]], label="refactoring"))
check_eq("E14: one hunk in two rows is legal", GT.check(s.task), [])
s.edit(lambda d: d["rows"].__setitem__(slice(None), [{"id": "G-1", "hunks": "all::src/a.py", "label": "infrastructure", "requirements": [], "risks": [], "question": "", "reason": "build"},
                                                       {"id": "G-2", "hunks": "all::src/b.py", "label": "refactoring", "requirements": [], "risks": [], "question": "", "reason": "x"}]))
report = GT.check_report(s.task)
check_eq("P2: a whole file labelled infrastructure passes and is named", (report[0], "labelled whole: src/a.py" in " ".join(report[1])), ([], True))
s.done()

# --- F-5: the escape set is the READER's ----------------------------------------------------------------------------------------------
check_eq("F-5: every character the reader refuses raw is written escaped and reads back",
         [GT._quote(chr(c)) for c in (0x85, 0x2028, 0x2029, 0xD800)], ['"\\u0085"', '"\\u2028"', '"\\u2029"', '"\\ud800"'])

# --- F-3: GT.write_key and parse_list (the seam 9.4 API of G1-8) ---------------------------------------------------------------------
s = Story()
s.skeleton()
writes = []
real_write_yaml = GT.write_yaml
GT.write_yaml = lambda path, data: (writes.append(sorted(data)), real_write_yaml(path, data))[1]
try:
    GT.write_key(s.task, "base_slice", [{"repo": "r", "note": "a #b"}])
    by_root = s.data()
    GT.write_key(s.table, "refactoring_share", {"road": "none"})
finally:
    GT.write_yaml = real_write_yaml
after = s.data()
check_eq("F-3: write_key writes ONE key (by the story root or by the table's path) through the one writer GT.write_yaml",
         (len(writes), by_root["base_slice"], after["refactoring_share"], [k for k in after if k not in by_root]), (2, [{"repo": "r", "note": "a #b"}], {"road": "none"}, ["refactoring_share"]))
check_eq("F-3: ...every other key is as it was", {k: v for k, v in after.items() if k != "refactoring_share"}, by_root)
kept_bytes = s.table.read_bytes()
for label, call in (("an unknown key", lambda: GT.write_key(s.task, "nope", 1)), ("a path that is no table", lambda: GT.write_key(s.root / "x" / "y.yaml", "rows", []))):
    try:
        call()
        text = ""
    except GT.Refusal as exc:
        text = exc.text
    check(f"F-3: write_key refuses {label} (FR-1, ends with a period) and writes nothing", text.endswith("nothing was written.") and s.table.read_bytes() == kept_bytes, text)
s.table.write_text("schema_version: 2\n", encoding="utf-8")
try:
    GT.write_key(s.task, "base_slice", [])
    text = ""
except GT.Refusal as exc:
    text = exc.text
check("F-3: write_key on a table the reader refuses: a Refusal that names the problem; the table is untouched", "schema_version" in text and s.table.read_text(encoding="utf-8") == "schema_version: 2\n", text)
s.done()
check_eq("F-3: parse_list tolerates spaces around commas", GT.parse_list(" 10 , 3 ", "old"), ["10", "3"])
check_eq("F-3: parse_list: an empty string (or None) is [], never ['']", (GT.parse_list("", "old"), GT.parse_list("   "), GT.parse_list(None)), ([], [], []))
for bad in (",", "a,,b", "a,"):
    try:
        GT.parse_list(bad, "the old range")
        text = ""
    except GT.Refusal as exc:
        text = exc.text
    check(f"F-3: parse_list({bad!r}) is a refusal that names the argument and ends with a period", "`the old range`" in text and text.endswith("nothing was read."), text)

# --- F-4: a node the table form cannot hold is a refusal that names the node, never a traceback -------------------------------------
try:
    GT.dump_yaml({"rows": [{"id": "G-1", "hunks": [["x"]]}]})
    text = ""
except TypeError as exc:
    text = str(exc)
check("F-4: dump_yaml names the node path of a list inside a list", "`rows[0].hunks[0]`" in text, text)
s = Story()
real_skeleton = GT.skeleton
GT.skeleton = lambda inp: {"rows": [{"id": "G-1", "hunks": [["x"]]}]}
real_story_root = GT.hooklib.story_root
GT.hooklib.story_root = lambda key, program, *rest, **more: s.task
errors = io.StringIO()
try:
    with contextlib.redirect_stderr(errors):
        code = GT.main(["--skeleton", "--task", "T-1"])
finally:
    GT.skeleton = real_skeleton
    GT.hooklib.story_root = real_story_root
check_eq("F-4: main turns the TypeError into exit 2 and an FR-1 sentence (names the node, ends with a period), writes nothing",
         (code, "`rows[0].hunks[0]`" in errors.getvalue(), errors.getvalue().strip().endswith("nothing was written."), s.table.exists()), (2, True, True, False))
s.done()

# --- Q-5: the closed list of orphan reasons is read by the one function that makes an orphan ------------------------------------------
try:
    GT.make_orphan("row", {"id": "G-1"}, "made_up_word", [], "")
    text = ""
except ValueError as exc:
    text = str(exc)
check("Q-5: make_orphan refuses a reason outside ORPHAN_WHY", "made_up_word" in text, text)

# --- mutation 1 (spec section 5): R1 counts by the RECOMPUTED index, called past R5 so the deleted hunk record cannot stop it ----------
s = Story(diff=many)
data = s.skeleton()
label_all(data)
data["hunks"].pop(0)
data["rows"].pop(0)
found = []
GT._scan_rows(data, GT.gather(s.task), found, [])
check("R1 (I1): the hunk record AND its row deleted from the table: the recomputed index still names the hunk (R1, 1 of 8)",
      any(f.rule == "R1" and "1 of 8 hunks" in f.text for f in found), str([f.text[:80] for f in found]))
s.done()

# --- G1-5: the S3 exit findings (exit_findings), R7, R7-regression, regression_from_blast, the claims' view -------------------------
def grounded(*items, risks=("K-1",), plan_md="## Recommended regression\n- blast:B-1 pytest a\n"):
    """A diff story with a complete table (every row labelled, every requirement outside the diff), the areas `items`, the risks, a plan md."""
    st = Story()
    st.skeleton()
    # G2-2: this fixture's table asks nothing of the story (every requirement outside the diff) and is all refactoring, so both stops would
    # stand (R6); the tests below are about R7, so a person's `*` word passes them (R6 itself is pinned in test_grounding_coverage.py)
    (st.task / "pipeline.json").write_text(json.dumps({"ticket": "T-1", "implementation_source": "diff", "stages": {},
                                                       "stage_overrides": [{"stage": "S3", "match": "*", "decision": "go on"}]}), encoding="utf-8")
    st.edit(lambda d: [label_all(d), [x.update(state="outside_diff", where="w") for x in d["requirements"]],
                       d["rows"][0].update(risks=[{"id": k, "hypothesis": "h " + k} for k in risks])])
    code = [dict({"id": f"B-{i + 1}", "key": f":f{i}.py", "path_kind": "additive"}, **{k: v for k, v in a.items() if k not in GT.ROLE_AREA_FIELDS})
            for i, a in enumerate(items)]
    st.blast({"index": {"state": "built"}, "areas": code})

    def judge(d):
        d["blast_radius"] = GT.project_blast(GT.gather(st.task))
        for area, a in zip(d["blast_radius"]["areas"], items):
            area.update(dict({"matters": "no"}, **{k: v for k, v in a.items() if k in GT.ROLE_AREA_FIELDS}))
    st.edit(judge)
    if plan_md is not None:
        GT.C.artifact_write_path(st.task, "test-plan.md").write_text(plan_md, encoding="utf-8")
    return st


AREA = {"matters": "yes", "regression": "pytest a", "tests": "x"}


def ex(st, rows, np=()):
    return GT.exit_findings(st.task, rows, list(np))


def texts(found, rule):
    return " | ".join(f.text for f in found if f.rule == rule)


s = grounded(AREA)
reach = [{"id": "TS-1", "risk_source_refs": ["grounding:K-1", "blast:B-1"]}]
check_eq("G1-5 R7: K-1 and B-1 named by a plan row, the regression named by the token: no finding", ex(s, reach), [])
before = s.tree_hash()
check_eq("G1-5 R7: exit_findings writes nothing (FR-45)", (ex(s, reach), s.tree_hash() == before), ([], True))
for refs, what in ((["grounding:K-0", "blast:B-0"], "ids that are no id"), (["grounding:k-1", "blast:B-1x"], "lower case and a glued suffix"),
                   (["grounding:K-1 blast:B-1"], "two refs in one string"), ([], "no refs")):
    got = ex(s, [{"id": "TS-1", "risk_source_refs": refs}])
    check(f"G1-5 R7 (ZA): {what} -> K-1 and B-1 reach nothing", "K-1" in texts(got, "R7") and "B-1" in texts(got, "R7"), str(got)[:200])
check_eq("G1-5 R7 (AT): backticks around the ref are taken off by PC.grounding_refs",
         ex(s, [{"id": "TS-1", "risk_source_refs": ["`grounding:K-1`", " `blast:B-1` "]}]), [])
check_eq("G1-5 R7: a not_planned entry with `ref` K-1 / B-1 is enough (a K-n in not_planned passes R7)",
         ex(s, [{"id": "TS-1", "risk_source_refs": []}], [{"ref": "K-1", "state": "deferred", "reason": "r"}, {"ref": "`B-1`", "state": "deferred", "reason": "r"}]), [])
check("G1-5 R7: a not_planned entry with only `requirement` (the old key) does not reach K-1",
      "K-1" in texts(ex(s, [{"id": "TS-1"}], [{"requirement": "K-1"}]), "R7"))
check("G1-5 R7: a plan reference the table does not hold is R7",
      "K-9" in texts(ex(s, reach + [{"id": "TS-2", "risk_source_refs": ["grounding:K-9"]}]), "R7"))
s2 = grounded(dict(AREA, add_tests="TS-9"))
check("G1-5 R7: add_tests TS-9 with no plan row of that id is R7", "TS-9" in texts(ex(s2, reach), "R7"))
check_eq("G1-5 R7: ...and with the row it is not", ex(s2, reach + [{"id": "TS-9"}]), [])
s2.done()
many = grounded(AREA, risks=[f"K-{n}" for n in range(1, 41)])
text = texts(ex(many, reach), "R7")
check("G1-5 R7: 40 risks, one finding that names each one or counts the rest (no name lost without a counter)",
      all(f"K-{n} " in text or f"K-{n}(" in text or f"K-{n}" in text for n in range(2, 8)) and ("more" in text), text[:300])
many.done()
check_eq("G1-5 R7: no plan (None) runs no R7 and no R7-regression", [f.rule for f in ex(s, None)], [])
for label, md in (("no md file", None), ("no section", "# plan\n"), ("only `No regression:`", "## Recommended regression\nNo regression: none\n"),
                  ("blast:B-1x", "## Recommended regression\n- blast:B-1x pytest a\n")):
    st = grounded(AREA, plan_md=md)
    got = ex(st, reach)
    check(f"G1-5 R7-regression: {label} -> B-1 owed, the text names the expected command",
          "B-1" in texts(got, GT.R7_REGRESSION) and "pytest a" in texts(got, GT.R7_REGRESSION), str(got)[:200])
    st.done()
st = grounded(dict(AREA, regression="gap:no suite"), plan_md=None)
check_eq("G1-5 R7-regression: a `gap:` regression owes no token", ex(st, reach), [])
st.done()
check_eq("G1-5 R7-regression: a token in ANY line of the section is enough (until the section has a form)",
         ex(grounded(AREA, plan_md="## Recommended regression\nsome words\n- `blast:B-1` and more\n"), reach), [])
# regression_from_blast: numeric order, equal commands merged, gap, empty, the mapping or the Doc
blast = {"blast_radius": {"areas": [{"id": "B-10", "regression": "pytest a", "why": "w10"}, {"id": "B-2", "regression": "pytest a", "why": "w2"},
                                    {"id": "B-3", "regression": "gap: no suite", "why": ""}, {"id": "B-4", "regression": ""}, {"id": "B-1", "regression": "pytest z"}]}}
check_eq("G1-5 regression_from_blast: B-10 after B-2 (by number), equal commands merge, gap -> gap, empty -> no entry",
         PC.regression_from_blast(blast),
         [{"area": "B-1", "command": "pytest z", "why": "shared path, no reason written"}, {"area": "B-2, B-10", "command": "pytest a", "why": "w2; w10"},
          {"area": "B-3", "gap": "no suite", "why": "shared path, no reason written"}])
check_eq("G1-5 regression_from_blast: nothing / junk gives []", [PC.regression_from_blast(x) for x in ({}, None, {"blast_radius": {"areas": "x"}})], [[], [], []])
# the table-level findings reach exit_findings; the role's lines alone reach the detector
st = Story()
check_eq("G1-5 R0: a diff and no table -> one conductor finding with the person's door, nothing else",
         [(f.rule, f.who, "missing" in f.text, "waiver.py --task T-1" in f.text) for f in ex(st, None)], [("R0", "conductor", True, True)])
st.skeleton()
st.table.unlink()
check_eq("G1-5 R0: the same after the table is deleted", [f.rule for f in ex(st, [])], ["R0"])
st.table.write_text("{}", encoding="utf-8")
check_eq("G1-5 R0: an unreadable table is ONE R0 (the claims add no second one)", [f.rule for f in ex(st, [])], ["R0"])
st.done()
off = next(w for w in GT.H.allowed("implementation_sources") if w != "diff")
st = Story(diff=None, source=off, register=None, blast=None)
check_eq("G1-5: off a diff with no table -> [] (0 of 0 is green only there)", ex(st, []), [])
GT.write_yaml(st.table, {"schema_version": 1, "implementation_source": "diff", "rows": []})
check_eq("G1-5 G-0b: off a diff a table with rows is the conductor's", [(f.rule, f.who) for f in ex(st, [])], [("G-0b", "conductor")])
st.done()
roles = grounded(AREA)
check_eq("G1-5 role_exit_lines: only the role's findings, rendered with the person's tail",
         [("[grounding R7]" in line, "A person's word passes" in line) for line in GT.role_exit_lines(roles.task, [{"id": "TS-1"}])], [(True, True)])
check_eq("G1-5 claim_view: R7 is False with no refs, True with them; R1 is False when a row loses its label; regression False with none",
         (GT.claim_view(roles.task, ("R7",), plan_rows=[{"id": "TS-1"}], not_planned=[])[0], GT.claim_view(roles.task, ("R7",), plan_rows=reach, not_planned=[])[0]),
         (False, True))
roles.edit(lambda d: d["rows"][0].update(label=""))
check_eq("G1-5 claim_view: R1 False when a hunk has no labelled row", GT.claim_view(roles.task, ("R1",))[0], False)
roles.edit(lambda d: d["blast_radius"]["areas"][0].update(regression=""))
check_eq("G1-5 claim_view: the regression claim is False with matters yes and no regression", GT.claim_view(roles.task, regression=True)[0], False)
roles.done()
off_claim = Story(diff=None, source=off, register=None, blast=None)
check_eq("G1-5 claim_view: off a diff there is no verdict (None)", GT.claim_view(off_claim.task, ("R1",))[0], None)
off_claim.done()
finish("test_grounding_table")
