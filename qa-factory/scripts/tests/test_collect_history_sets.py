"""CL3-3 (t-682; spec t-624 with the plan critic's corrections t-656): the collector's set table covers the story-history folder.

Every expected entry comes from the spec (section 2.2 / 2.3 as amended), written into fixtures/collect-history-tree.json and below -
never from running the matcher (FR-58). The table is read through `collect_pack.load_sets()` and matched only through
`collect_pack.compile_entries` + `collect_pack.match_entry` (AR-13): this file builds no matcher of its own. Keys: K1 registry tie,
K1c its negative control, K2 the recorded tree, K3 end to end, K4 negative controls, K5 empty history, K6 two matches, K7 entry with
no file, K8 ceiling AT and BEYOND, K9 project scope, K10 not onboarded. Fictional identities (FR-30).
"""
import copy
import json
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURES, PLUGIN_ROOT, SCRIPTS, check, check_eq, finish, mark_project, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import artifact_registry  # noqa: E402
import collect_pack as C  # noqa: E402
import hooklib  # noqa: E402
import machine_facts as M  # noqa: E402

BASE = temp_dir("collect-history-")
IDS = {"users": ["Zoya_Kantorova"], "display_names": ["Zoya Kantorova"], "emails": [], "machine": ["WKS-HX4LN77"], "domain": ["SAMPLECORP"]}
RED = M.compile_redactor(M.load_rules(), project_root=str(BASE), plugin_root=str(PLUGIN_ROOT), pythons=(sys.executable,), home="C:\\Users\\Zoya_Kantorova",
                         tmp=tempfile.gettempdir(), identities=IDS, hosts=("stand.sample-hx.example",), secret_values={}, short=lambda p: None)
NOW = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
STORY = "TP1-13877"
MARKER = "PRODUCT-CODE-MARKER-CL33"
COUNT = [0]
SETS = C.load_sets()
COMPILED = C.compile_entries(SETS)
TREE = json.loads((FIXTURES / "collect-history-tree.json").read_text(encoding="utf-8"))["rows"]


def hit(scope, rel, compiled=COMPILED):
    e = C.match_entry(compiled, scope, rel)
    return e["id"] if e else None


def project():
    COUNT[0] += 1
    return mark_project(BASE / f"p{COUNT[0]}")


def put(root, rel, text, story=STORY):
    path = Path(root) / "qa-factory" / "artifacts" / story / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))


def pack(root, **kw):
    kw.setdefault("redactor", RED)
    kw.setdefault("git", lambda p, *a: (124, ""))
    kw.setdefault("temp_root", BASE / "out")
    kw.setdefault("rules_sha", M.rules_sha256())
    kw.setdefault("now", NOW)
    return C.pack(root, **kw)


def read_parts(res):
    out = {}
    for part in res["parts"]:
        with zipfile.ZipFile(part) as zf:
            out.update({i.filename: zf.read(i.filename) for i in zf.infolist()})
    return out


def manifest(res):
    return json.loads(read_parts(res)["manifest.json"].decode("utf-8"))


def registry_samples():
    """The story-scope paths the package's two registries name, as sample files. A key ending in '/' or with no '.' in its last segment is a
    folder ('<key>/sample.md'); '*' becomes 'z'. Read through the registries' own readers (artifact_registry.entries, hooklib.load_ref_json)."""
    keys = [k for k in hooklib.load_ref_json("artifact-writers.json")["artifacts"] if not k.startswith(("project:", "qa-factory/"))]
    keys += [v["path"] for v in artifact_registry.entries().values()]
    out = {}
    for k in keys:
        folder = k.endswith("/") or "." not in k.rstrip("/").rsplit("/", 1)[-1]
        out[k] = (k.rstrip("/") + "/sample.md" if folder else k).replace("*", "z")
    return out


def tie_misses(compiled):
    return sorted(k for k, sample in registry_samples().items() if C.match_entry(compiled, "h", sample) is None)


def k1_registry_tie():
    samples = registry_samples()
    check("K1 setup: the walk reads both registries (50 distinct story paths today; never a handful)", len(samples) >= 45, str(len(samples)))
    check_eq("K1: every story-scope key of artifact-writers.json and every path of artifact-registry.json resolves to an entry (misses by key)",
             tie_misses(COMPILED), [])
    no_b16 = copy.deepcopy(SETS)
    no_b16["entries"] = [e for e in no_b16["entries"] if e["id"] != "B16"]
    got = tie_misses(C.compile_entries(no_b16))
    check("K1c: the tie can fail - with B16 removed, work/handoffs/ and work/digests/ are misses", "work/handoffs/" in got and "work/digests/" in got, str(got))


def k2_recorded_tree():
    wrong = [(r["rel"], r["entry"], hit("h", r["rel"])) for r in TREE if hit("h", r["rel"]) != r["entry"]]
    check_eq("K2: every fixture row matches the entry the spec assigns (None for a negative row)", wrong, [])
    check_eq("K2: the briefs and handoffs of the history are all B16",
             {r["entry"] for r in TREE if r["rel"].startswith(("work/briefs/S", "work/handoffs/"))}, {"B16"})


def x9_retro_form_is_packed():
    """X9 (F-8 a): the S9 retro form, whose `tried` table the NEXT story's retro brief reads (brief_pack.prior_retro_lines), is packed by
    B16 - a pin, nothing to wire. Negative control: the table without B16 packs nothing of it."""
    path = "work/handoffs/S9-qa-retro-analyst-1.yaml"
    check_eq("X9: the S9 retro form is packed (B16)", hit("h", path), "B16")
    no_b16 = copy.deepcopy(SETS)
    no_b16["entries"] = [e for e in no_b16["entries"] if e["id"] != "B16"]
    check_eq("X9 negative control: with B16 removed the same path matches nothing", hit("h", path, C.compile_entries(no_b16)), None)


def materialise(root, rows):
    n_b15 = 0
    for r in rows:
        if r["entry"] is None:
            continue
        if r["entry"] == "B15":
            n_b15 += 1
            put(root, r["rel"], MARKER + "\n")
        else:
            put(root, r["rel"], "{}" if r["rel"].endswith(".json") else "text of " + r["rel"] + "\n")
    return n_b15


def k3_end_to_end():
    root = project()
    n_b15 = materialise(root, TREE)
    res = pack(root)
    m = manifest(res)
    unknown = [s["src_rel"] for s in m["skipped"] if s["reason"] == "unknown file" and s["src_rel"].startswith("artifacts/")]
    check_eq("K3: no file of the history is skipped as unknown", unknown, [])
    b15 = [s for s in m["skipped"] if s["set"] == "B" and s["reason"].startswith("product code")]
    check("K3 (B-1): the product-code files make ONE grouped skipped row of set B whose files equals the number materialised",
          len(b15) == 1 and b15[0].get("files") == n_b15, str(b15))
    check("K3 (B-1): the grouped row names the pattern, not a story path", len(b15) == 1 and not b15[0]["src_rel"].startswith("artifacts/"), str(b15))
    check("K3: the product-code marker is in no archive member", all(MARKER.encode() not in data for data in read_parts(res).values()))
    got = {r["src_rel"] for r in m["files"]}
    check("K3: a handoff, a brief and the register are packed", all(f"artifacts/{STORY}/{p}" in got for p in
          ("work/handoffs/S1-qa-scout-1.yaml", "work/briefs/S1-qa-scout-1.md", "work/requirements-register.md")), str(sorted(got)[:5]))


def k4_negative_controls():
    nulls = [r["rel"] for r in TREE if r["entry"] is None]
    check_eq("K4 a: the four negative rows match nothing", (len(nulls), [hit("h", p) for p in nulls]), (4, [None] * 4))
    root = project()
    put(root, "src/main.ts", MARKER + "\n")
    put(root, "pipeline.json", "{}")
    res = pack(root)
    m = manifest(res)
    check("K4 b: a source file at the story root lands skipped, unknown file", any(s["src_rel"] == f"artifacts/{STORY}/src/main.ts" and s["reason"] == "unknown file" for s in m["skipped"]))
    check("K4 b: its text is in no archive member", all(MARKER.encode() not in d for d in read_parts(res).values()))
    check_eq("K4 c: no h entry is a catch-all", (hit("h", "work/odd.dat"), hit("h", "zz-unknown/x.bin")), (None, None))
    check_eq("K4 d: scope is honoured - state/cost/s1.json is no h path and is C2 in scope p", (hit("h", "state/cost/s1.json"), hit("p", "state/cost/s1.json")), (None, "C2"))
    check_eq("K4 e: a backslash path and a case variant are unknown, the safe side", (hit("h", "work\\handoffs\\S1.yaml"), hit("h", "Work/Handoffs/S1.yaml")), (None, None))
    check_eq("K4 e: the same path in posix and exact case is B16 (control)", hit("h", "work/handoffs/S1.yaml"), "B16")


def k5_empty_history():
    root = project()
    (root / "qa-factory" / "artifacts" / "EMPTY-1").mkdir(parents=True)
    bare = project()
    res = pack(root)
    m = manifest(res)
    base = manifest(pack(bare))
    check("K5: the empty story is a stories[] row", "EMPTY-1" in json.dumps(m["stories"]), json.dumps(m["stories"]))
    check_eq("K5: no files[] / skipped[] row under artifacts/EMPTY-1/",
             [r for r in m["files"] + m["skipped"] if "artifacts/EMPTY-1/" in r["src_rel"]], [])
    check_eq("K5: sets B..E keep the status of the same project with no history folder",
             {s: m["sets"][s]["status"] for s in "BCDE"}, {s: base["sets"][s]["status"] for s in "BCDE"})


def k6_two_matches():
    check_eq("K6: mr-12.json matches B15 and E8 - the first (B15) wins", hit("h", "work/sources/SRC-1/mr-12.json"), "B15")
    check_eq("K6: repo-map-app.md matches A12 and B16 - the first (A12) wins", hit("h", "work/briefs/repo-map-app.md"), "A12")
    check_eq("K6: a lock under work/test-cases matches B13 and E7 - the first (B13) wins", hit("h", "work/test-cases/.case-versions.lock"), "B13")
    check_eq("K6 (B-2): an MR receipt is skipped at ANY depth under work/sources (the locator source_exclusions._receipt_files takes): B15, never E8",
             [hit("h", p) for p in ("work/sources/SRC-1/mrs/mr-12.json", "work/sources/mr-12.json", "work/sources/SRC-1/a/b/mr-3-git.md")], ["B15"] * 3)
    check_eq("K6 (B-2): a non-receipt beside them is still a record (E8), so the skip is no catch-all", hit("h", "work/sources/SRC-1/mrs/notes.md"), "E8")
    ids = [e["id"] for e in SETS["entries"]]
    check("K6: B15 stands before B16 and E8 in the data, and every new entry stands before H1",
          ids.index("B15") < ids.index("B16") < ids.index("E8") and ids.index("H1") == len(ids) - 1, str(ids))


def k7_entry_with_no_file():
    few = project()
    put(few, "pipeline.json", "{}")
    put(few, "state/events.jsonl", "")
    one = project()
    put(one, "pipeline.json", "{}")
    put(one, "state/events.jsonl", "")
    put(one, "work/handoffs/S1-qa-scout-1.yaml", "a: 1\n")
    m_few, m_one = manifest(pack(few)), manifest(pack(one))
    rows = [r["src_rel"] for r in m_one["files"] + m_one["skipped"]]
    check("K7: the handoff gives a row", any("work/handoffs/S1-qa-scout-1.yaml" in r for r in rows), str(rows))
    names = [e for e in ("E8", "E9", "E10", "E11", "E12") if e in json.dumps([m_one["files"], m_one["skipped"], m_one["gaps"]])]
    check_eq("K7: no row, skip or gap names E8..E12 (entries with no file)", names, [])
    check_eq("K7: the gaps are those of the same project without the handoff", m_one["gaps"], m_few["gaps"])


def k8_ceiling():
    n = 40000      # above the project's own config.json (about 34 KB), so only the handoff meets the ceiling
    rel = "work/handoffs/S1-qa-scout-1.yaml"
    src = f"artifacts/{STORY}/{rel}"
    at = project()
    put(at, rel, "x" * n)
    m_at = manifest(pack(at, file_max_bytes=n))
    check("K8 AT the ceiling: a files[] row, no too_large", any(r["src_rel"] == src for r in m_at["files"]) and not any(s["reason"] == "too_large" for s in m_at["skipped"]), str([s["src_rel"] for s in m_at["skipped"]]))
    over = project()
    put(over, rel, "x" * (n + 1))
    res = pack(over, file_max_bytes=n)
    m_over = manifest(res)
    sk = [s for s in m_over["skipped"] if s["src_rel"] == src]
    check("K8 BEYOND the ceiling: a skipped too_large row with sha256 and excerpt", len(sk) == 1 and sk[0]["reason"] == "too_large" and sk[0].get("sha256") and "excerpt" in sk[0], str(sk))
    check("K8 BEYOND: no files[] row for it", not any(r["src_rel"] == src for r in m_over["files"]))


def k9_project_scope():
    want = {"state/turns/dispatches/a.json": "C3", "state/stand-health.json": "A14", "state/integrations/tracker-write.json": "A14",
            "state/integrations/jira-direct-probe.json": "A14", "state/config-reverts/x.json": "A15",
            "state/decision-transactions/DD-1.json": "D4", "state/words/a.txt": "A13", "records/coverage-map.md": "E13"}
    check_eq("K9: project-scope paths resolve to the entries the spec assigns", {p: hit("p", p) for p in want}, want)
    check_eq("K9 (B-2): a file the install table does not name is no A14 path", hit("p", "state/integrations/other.json"), None)
    a15 = next(e for e in SETS["entries"] if e["id"] == "A15")
    check("K9: A15 is a skip and an orphan on purpose (no install-paths row)", a15["mode"] == "skip" and a15.get("orphan") is True)


def k10_not_onboarded():
    off = C.compile_entries(SETS, onboarded=False)
    on = C.compile_entries(SETS)
    check("K10: not onboarded - only set-A entries, and no virtual entry", off and all(e["set"] == "A" and not e.get("virtual") for e, _p in off))
    check("K10: onboarded - no virtual entry, and entries of other sets are there (control)", all(not e.get("virtual") for e, _p in on) and any(e["set"] == "B" for e, _p in on))
    check_eq("K10: B16 is compiled when onboarded and absent when not", ([e["id"] for e, _p in on].count("B16"), [e["id"] for e, _p in off].count("B16")), (1, 0))


def k11_empty_table():
    check_eq("K11 (empty history): an empty table compiles to nothing and matches nothing", (C.compile_entries({"entries": []}), C.match_entry([], "h", "pipeline.json")), ([], None))


k1_registry_tie()
k2_recorded_tree()
x9_retro_form_is_packed()
k3_end_to_end()
k4_negative_controls()
k5_empty_history()
k6_two_matches()
k7_entry_with_no_file()
k8_ceiling()
k9_project_scope()
k10_not_onboarded()
k11_empty_table()
finish("test_collect_history_sets")
