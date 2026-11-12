"""CL1-2 (t-1024; t-962 sections 2, 3, 8 with L-2): the collector `collect_pack.py`. Every expected value comes from the requirement named
beside the pin (t-962 sections 2, 3, 8; the review t-972 edge battery; L-2 m4..m13 and F-6), never from running the code (FR-58). The
fixture identities are fictional (FR-30). The mutations of the hand-off each die in one group here: the redactor pass (G3), the prefix
check (G4b), the manifest first (G2), the 16 MiB ceiling (G5), the never-list (G9), the residue post-check (G8).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, SCRIPTS, check, check_eq, cleanup, finish, mark_project, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import collect_pack as C  # noqa: E402
import install_paths  # noqa: E402
import machine_facts as M  # noqa: E402

BASE = temp_dir("collect-pack-")
HOME_ = "C:\\Users\\Alexandra_Testova"
IDS = {"users": ["Alexandra_Testova"], "display_names": ["Alexandra Testova"], "emails": [], "machine": ["WKS-ZT9QA01"], "domain": ["EXAMPLECORP"]}
RED = M.compile_redactor(M.load_rules(), project_root=str(BASE), plugin_root=str(PLUGIN_ROOT), pythons=(sys.executable,), home=HOME_,
                         tmp=tempfile.gettempdir(), identities=IDS, hosts=("stand.corp-zq.example",), secret_values={"STAND_PASSWORD": "Zq7-pass-Word"},
                         short=lambda p: None)
NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
NOGIT = lambda p, *a: (124, "")      # noqa: E731
COUNT = [0]
MARK = "MARKER-EVIDENCE-ONLY-IN-EVIDENCE"
SECRET_NAME = "Alexandra_Testova"


def P():
    COUNT[0] += 1
    return mark_project(BASE / f"p{COUNT[0]}")


def W(root, rel, text, base="qa-factory"):
    path = Path(root) / base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return path


def run(root, minutes=0, **kw):
    kw.setdefault("redactor", RED)
    kw.setdefault("git", NOGIT)
    kw.setdefault("temp_root", BASE / "out")
    kw.setdefault("rules_sha", M.rules_sha256())
    kw.setdefault("now", NOW + timedelta(minutes=minutes))
    return C.pack(root, **kw)


def members(res):
    out = {}
    for part in res["parts"]:
        with zipfile.ZipFile(part) as zf:
            out.update({i.filename: zf.read(i.filename) for i in zf.infolist()})
    return out


def man(res):
    return json.loads(members(res)["manifest.json"].decode("utf-8"))


def row(manifest, src_rel):
    return next((r for r in manifest["files"] if r["src_rel"] == src_rel), None)


def refused(fn):
    try:
        fn()
    except C.Refused as exc:
        return str(exc)
    return None


EV = [{"sequence": i, "event_hash": f"h{i}", "type": "x", "created_at": f"2026-10-19T10:0{i}:00Z"} for i in (1, 2, 3)]      # 2 h before NOW: a story that is going on
LINES = "".join(json.dumps(e) + "\n" for e in EV)


def full(root):
    W(root, "state/readiness.json", json.dumps({"runtime_paths": {"package_version": "0.9.0", "package_fingerprint": "ab" * 32}, "host_integration": {"host": "claude-code"}}))
    W(root, "records/journal.jsonl", '{"n":1}\n{"n":2}\n{"n":3}\n')
    W(root, "state/cost/s1.json", json.dumps({"session_id": "s1", "transcript": HOME_ + "\\.claude\\projects\\x\\s1.jsonl", "note": "run by " + SECRET_NAME + " in " + HOME_ + "\\work", "total_cost_usd": 1.5}))
    W(root, "state/telemetry/hook-1.jsonl", '{"timestamp":"2026-10-19T10:00:00","span_kind":"hook","outcome":"ok","reason_code":"none"}\n')
    W(root, "strategy/project-profile.md", "# profile\nowner " + SECRET_NAME + "\n")
    T = "artifacts/TP1-1/"
    W(root, T + "pipeline.json", json.dumps({"run_mode": {"mode": "plugin", "plugin_version": "0.9.0"}, "stages": {}}))      # the real shape: story_step.stamp_run_mode
    W(root, T + "state/events.jsonl", LINES)
    W(root, T + "state/controller.json", json.dumps({"dispatches": {}, "p": "C:\\Users\\Alexandra_Testova\\x"}))
    W(root, T + "evidence/runs/r1/log.txt", MARK)
    W(root, T + "work/evidence/shot.txt", MARK)
    W(root, T + "work/odd.dat", "?")
    W(root, T + "retro.md", "# retro\n")
    return root


def reconciliation():
    sets = C.load_sets()
    table = install_paths.load_table()
    bad = []
    for e in sets["entries"]:
        for path in e.get("paths", []) + e.get("old_paths", []):
            sample = path.replace("**", "x/y").replace("*", "z")
            probe = ("qa-factory/" + sample) if e["scope"] == "p" else "qa-factory/artifacts/SAMPLE/" + sample
            got = install_paths.classify(probe, table=table, casefold=False)
            known = got["class"] not in ("unrecognised", "refused")
            if known == bool(e.get("orphan")):
                bad.append((e["id"], path, got["class"]))
    check_eq("G13 m4: every set path is an install-paths row (project) or sits under artifacts/** (history); orphan entries are rows no table knows", bad, [])
    check_eq("G13: the negative control - a path no row names is unrecognised, so the reconciliation can fail",
             install_paths.classify("qa-factory/state/not-a-row.json", table=table, casefold=False)["class"], "unrecognised")
    mark = install_paths.classify("qa-factory/state/collect/mark.json", table=table, casefold=False)
    check("G13 m12: state/collect/** is carried and machine_local (a reinstall keeps the mark)", mark["class"] == "carried" and mark["machine_local"] and mark["retire_safe"], str(mark))
    check_eq("G13: the whole table still validates (reader collect_pack.py holds the key)", install_paths.validate_table()["errors"], [])
    check("G13: references/collect-sets.json carries the ceilings as data (16 MiB file, 25 MB part)", sets["limits"]["file_max_bytes"] == 16 * 1024 * 1024 and sets["limits"]["part_max_bytes"] == 25_000_000)


def refusals_and_empty():
    root = BASE / "nofolder"
    root.mkdir()
    msg = refused(lambda: run(root))
    check("G1 edge 1: no qa-factory folder -> a refusal that names what, expected and the door (--root)", bool(msg) and "no qa-factory folder" in msg and "--root" in msg and "config.json" in msg, str(msg))
    nb = BASE / "notonboarded"
    (nb / "qa-factory").mkdir(parents=True)
    r = run(nb)
    m = man(r)
    check("G1 edge 1: not onboarded -> an archive; the passport says so; B-H are gaps with the reason (I1)",
          json.loads(members(r)["summaries/A/A1.json"])["onboarded"] is False and all(m["sets"][s]["status"] == "gap" for s in "BCDEFGH")
          and sum(1 for g in m["gaps"] if "not onboarded" in g["why"]) == 7, str(m["sets"]))
    root = P()
    r = run(root)
    m = man(r)
    mem = members(r)
    check_eq("G2 empty project (a config, no state): the archive is the manifest, the passport and the config copy of set A - nothing else", sorted(mem),
             ["A/config.json", "manifest.json", "summaries/A/A1.json"])
    with zipfile.ZipFile(r["archive"]) as zf:
        check_eq("G2 section 3 p.8: manifest.json is the FIRST member", zf.infolist()[0].filename, "manifest.json")
    check_eq("G2 edge 2: empty is not gap (B-H empty: no runs, no stalled story), A holds the passport and the config",
             {s: m["sets"][s]["status"] for s in "ABCDEFGH"}, {"A": "collected","B": "empty", "C": "empty", "D": "empty", "E": "empty", "F": "empty", "G": "empty", "H": "empty"})
    check("G2: no story, so no stall verdict and no wired-by-CL1-4 gap any more", m["stories"] == [] and not any("wired by CL1-4" in g["why"] for g in m["gaps"]))
    check("G2 section 3 p.8: the manifest fields", {"schema", "project_id", "install_id", "collected_at", "collector", "window", "host", "os", "python", "sets", "files",
          "skipped", "gaps", "stories", "answers", "parts", "redaction_rules_sha256", "package_modified"} <= set(m) and m["schema"] == "qa-collect/1"
          and m["redaction_rules_sha256"] == M.rules_sha256() and m["answers"] == {"problems": {"state": "blank", "arc": None}, "suggestions": {"state": "blank", "arc": None}})


def first_run():
    root = full(P())
    # CL1-8 landed (release_fingerprint.py exists), so the guarded import in collect_pack.package_modified succeeds. The
    # absence the G3 check below is about is SIMULATED, never assumed: `sys.modules[name] = None` makes an `import` raise
    # ImportError (the seam check below stubs the module in the other direction). Restored in `finally`: a stub left
    # behind would break every later test of this process.
    had = "release_fingerprint" in sys.modules
    saved = sys.modules.get("release_fingerprint")
    sys.modules["release_fingerprint"] = None
    try:
        r = run(root)
    finally:
        if had:
            sys.modules["release_fingerprint"] = saved
        else:
            del sys.modules["release_fingerprint"]
    mem, m = members(r), man(r)
    blob = b"".join(mem.values())
    check("G3 I2: the name, the home and the host are in no member (the redactor pass, every set)", SECRET_NAME.encode() not in blob and b"Alexandra" not in blob and b"alexandra" not in blob.lower())
    cost = json.loads(mem[row(m, "state/cost/s1.json")["arc"]])
    check("G3 section 2 C: transcript -> <transcript:sid>; the home in a note -> <home>; the name -> <user>",
          cost["transcript"] == "<transcript:s1>" and cost["note"] == "run by <user> in <home>\\work", str(cost))
    check("G3 section 2 A: the profile is copied through the redactor", b"owner <user>" in mem[row(m, "strategy/project-profile.md")["arc"]])
    check("G3 JSON stays JSON and a JSON-escaped path is replaced", json.loads(mem[row(m, "artifacts/TP1-1/state/controller.json")["arc"]])["p"] == "<home>\\x")
    check("G9 m6: evidence content is in no member, work/evidence/ either; the index has the path, bytes and sha256 of the file",
          MARK.encode() not in blob and any(json.loads(v).get("index") for k, v in mem.items() if k.startswith("summaries/B/TP1-1/B11")))
    idx = json.loads(next(v for k, v in mem.items() if k.startswith("summaries/B/TP1-1/B11")))["index"]
    import hashlib
    check("G9: ... the sha256 is the file's", any(i["sha256"] == hashlib.sha256(MARK.encode()).hexdigest() and i["bytes"] == len(MARK) for i in idx))
    check("G3 edge 3: a file no entry names is a skipped row, unknown file; broken JSON is skipped, not a crash",
          any(s["src_rel"] == "artifacts/TP1-1/work/odd.dat" and s["reason"] == "unknown file" for s in m["skipped"]))
    st = m["stories"][0]
    check_eq("G3 stories[]: task, plugin_version, touched, closed_at None, a story going on (events 2 h old, no episode) is NOT stalled: no signals, no transcripts",
             (st["task"], st["plugin_version"], st["touched"], st["closed_at"], st["stalled"], st["stall_signals"], st["transcripts"]), ("TP1-1", "0.9.0", True, None, False, [], []))
    check("G3 F-6: project_id is 12 hex, install_id a uuid4 kept in the mark; the name carries install_id[:8]",
          len(m["project_id"]) == 12 and len(m["install_id"]) == 32 and Path(r["archive"]).name.startswith("qa-collect-" + m["install_id"][:8] + "-20261019T120000Z"))
    check("G3: package_modified is unknown with the reason, while CL1-8 is absent (guarded import)", (m["package_modified"], m["package_modified_why"]) == ("unknown", "fingerprint_unavailable"))
    # with the real module present (CL1-8) the shape is fixed, the value is the release copy's to decide
    m_real = man(run(P(), minutes=2))
    check("G3 CL1-8 present (the absence stub was restored): package_modified is yes|no|unknown with a non-empty package_modified_why that is not the absent-module reason",
          m_real["package_modified"] in ("yes", "no", "unknown") and isinstance(m_real["package_modified_why"], str) and bool(m_real["package_modified_why"])
          and m_real["package_modified_why"] != "fingerprint_unavailable",
          str((m_real["package_modified"], m_real.get("package_modified_why"))))
    sys.modules["release_fingerprint"] = type(sys)("release_fingerprint")
    sys.modules["release_fingerprint"].compare = lambda root: {"package_modified": "yes", "why": "differs", "changed": ["scripts/x.py"]}
    sys.modules["release_fingerprint"].package_fingerprint = lambda root: "f" * 64
    try:
        m2 = man(run(P(), minutes=1))
    finally:
        if had:
            sys.modules["release_fingerprint"] = saved
        else:
            del sys.modules["release_fingerprint"]
    check("G3 CL1-8 seam: compare() answers land in the manifest", (m2["package_modified"], m2["package_modified_detail"]) == ("yes", {"changed": ["scripts/x.py"]}) and m2["collector"]["package_fingerprint"] == "f" * 64)
    check("G3 section 3 p.5: the mark was written after the re-read: archive, sha256 of part 1, install_id, project_id",
          (lambda mk: mk["runs"][-1]["archive"] == Path(r["archive"]).name and mk["install_id"] == m["install_id"] and mk["project_id"] == m["project_id"]
           and mk["runs"][-1]["sha256"] == hashlib.sha256(Path(r["archive"]).read_bytes()).hexdigest())(json.loads((root / "qa-factory/state/collect/mark.json").read_text(encoding="utf-8"))))
    return root, r


def tails(root, first_id):
    j = root / "qa-factory/records/journal.jsonl"
    W(root, "records/journal.jsonl", j.read_text() + '{"n":4}\n{"n":5}\n')
    r2 = run(root, 10)
    m, mem = man(r2), members(r2)
    tail = row(m, "records/journal.jsonl")
    check_eq("G4a section 3 p.2: the tail is only what was appended after the mark, up to the last newline (the redactor re-dumps each JSONL line)",
             [json.loads(x) for x in mem[tail["arc"]].split(b"\n") if x], [{"n": 4}, {"n": 5}])
    check_eq("G4a: the prefix is named (from the marked bytes to the new boundary: 3 lines of 8 bytes, then 5)", tail["prefix"], {"from": 24, "to": 40})
    check("G4a: the second window starts at the first archive, install_id is kept", m["window"]["since_archive"].startswith("qa-collect-") and m["install_id"] == first_id)
    check("G4a edge 7: an unchanged story and unchanged copies are rows without bytes; the second archive is the manifest, the passport and the new tail",
          row(m, "state/cost/s1.json")["flags"] == ["unchanged"] and row(m, "state/cost/s1.json")["arc"] is None, str(sorted(mem)))
    # b. the journal is rewritten: same start length, other bytes
    W(root, "records/journal.jsonl", '{"n":9}\n{"n":2}\n{"n":3}\n{"n":4}\n{"n":5}\n{"n":6}\n')
    r3 = run(root, 20)
    t3 = row(man(r3), "records/journal.jsonl")
    check("G4b I3 'a rewritten journal': a prefix that no longer matches -> the whole file, flagged prefix_changed",
          "prefix_changed" in t3["flags"] and members(r3)[t3["arc"]].count(b"\n") == 6 and t3["prefix"]["from"] == 0, str(t3))
    # c. a line being written is not taken
    j = root / "qa-factory/records/journal.jsonl"
    W(root, "records/journal.jsonl", j.read_text() + '{"n":7')
    t4 = row(man(run(root, 30)), "records/journal.jsonl")
    check("G4c 'a write in progress': no trailing newline -> the half line is not taken, the boundary stays", t4["flags"] == ["unchanged"] or (t4["bytes"] == 0), str(t4))
    W(root, "records/journal.jsonl", j.read_text() + '}\n')
    r5 = run(root, 40)
    t5 = row(man(r5), "records/journal.jsonl")
    check_eq("G4c: the finished line arrives whole in the next window", [json.loads(x) for x in members(r5)[t5["arc"]].split(b"\n") if x], [{"n": 7}])
    # d. events: the hash at the marked sequence differs
    mk = root / "qa-factory/state/collect/mark.json"
    doc = json.loads(mk.read_text(encoding="utf-8"))
    doc["runs"][-1]["events"]["TP1-1"]["event_hash"] = "other"
    mk.write_text(json.dumps(doc), encoding="utf-8")
    W(root, "artifacts/TP1-1/state/events.jsonl", LINES + json.dumps({"sequence": 4, "event_hash": "h4"}) + "\n")
    r6 = run(root, 50)
    t6 = row(man(r6), "artifacts/TP1-1/state/events.jsonl")
    check("G4d edge: event_hash at the marked sequence differs -> the whole file and chain_reset", "chain_reset" in t6["flags"] and t6["prefix"]["from"] == 0 and members(r6)[t6["arc"]].count(b"\n") == 4, str(t6))
    r7 = run(root, 60)
    check_eq("G4e edge 7: a second run with nothing new -> the manifest and the passport only", sorted(members(r7)), ["manifest.json", "summaries/A/A1.json"])
    # f. a mark in the future, a lost mark, a foreign mark
    doc = json.loads(mk.read_text(encoding="utf-8"))
    doc["runs"][-1]["collected_at"] = "2030-01-01T00:00:00Z"
    mk.write_text(json.dumps(doc), encoding="utf-8")
    r8 = run(root, 70)
    m8 = man(r8)
    check("G4f edge: a mark dated in the future -> the first-run window (everything again) and a gap line", m8["window"]["since_archive"] == "install"
          and any("future" in g["what"] for g in m8["gaps"]) and row(m8, "records/journal.jsonl")["prefix"]["from"] == 0)
    iid = m8["install_id"]
    r9 = run(root, 80, since="install")
    check("G4f m10: --since install packs everything again and keeps the install_id", man(r9)["window"]["since_archive"] == "install" and man(r9)["install_id"] == iid and row(man(r9), "state/cost/s1.json")["arc"])
    shutil.rmtree(root / "qa-factory/state/collect")
    m10 = man(run(root, 90))
    check("G4g edge 8/15: a lost mark -> as a first run, the same project_id, a NEW install_id", m10["window"]["since_archive"] == "install" and m10["project_id"] == m8["project_id"] and m10["install_id"] != iid)
    clone = BASE / "clone"
    shutil.copytree(root, clone)
    m11 = man(run(clone, 100))
    check("G4g F-6: a copy of the project carries a foreign mark -> its own project_id and install_id, a gap line, the first-run window",
          m11["project_id"] != m10["project_id"] and m11["install_id"] != m10["install_id"] and any("not this project" in g["what"] for g in m11["gaps"]) and m11["window"]["since_archive"] == "install")
    (root / "qa-factory/state/collect/mark.json").write_text("{not json", encoding="utf-8")
    m12 = man(run(root, 110))
    check("G4g: an unreadable mark is a gap and the first-run window, not a crash", any("cannot be read" in g["what"] for g in m12["gaps"]) and m12["window"]["since_archive"] == "install")


def ids_and_git():
    import hashlib
    top = str(BASE.resolve())

    def fake(code_ignore):
        def git(path, *a):
            if a[:2] == ("rev-parse", "--show-toplevel"):
                return 0, top
            if a[:2] == ("config", "--get"):
                return 0, "https://user:tok@git.example.test/org/repo.git"
            if a[0] == "check-ignore":
                return code_ignore, ""
            return 1, ""
        return git
    root = P()
    m = man(run(root, git=fake(0)))
    want = hashlib.sha256(("https://git.example.test/org/repo.git\n" + root.name).encode()).hexdigest()[:12]
    check_eq("G7 F-6 / F3: project_id = sha256(remote without userinfo + newline + the folder path from the git top)[:12]", m["project_id"], want)
    check("G7 section 3 p.6: git ignores the folder -> the archive is written to qa-factory/state/collect, not to temp",
          m["delivery"]["location"] == "project_state" and Path(run(P(), git=fake(0))["archive"]).parent.name == "collect")
    for code, word in ((1, "does not ignore"), (128, "not a git repository"), (124, "could not be run")):
        r = run(P(), git=fake(code) if code != 124 else NOGIT)
        check(f"G7 edge 4 / I6: check-ignore answer {code} -> the temp folder with the named reason", r["location"] == "temp" and word in r["reason"]
              and Path(r["archive"]).parent == BASE / "out" / "qa-collect", str(r["reason"]))
    a, b = P(), P()
    check("G7 F-6: two project folders of one remote have different project_ids", man(run(a, git=fake(0)))["project_id"] != man(run(b, git=fake(0)))["project_id"])
    if shutil.which("git"):
        g = P()
        subprocess.run(["git", "init", "-q", str(g)], check=True)
        r0 = run(g, git=None)
        W(g, ".gitignore", "qa-factory/state/*\n", base="")
        r1 = run(g, 5, git=None)
        check("G7 the real git: no .gitignore line -> temp; the line qa-factory/state/* -> the project's state/collect", (r0["location"], r1["location"]) == ("temp", "project_state"), f"{r0['reason']} / {r1['reason']}")


def fake_git(remote, top_of, ignored=0):
    """A git runner: the top is top_of(project folder), the remote is `remote` (None = a repository with no origin), check-ignore answers `ignored`."""
    def git(path, *a):
        if a[:2] == ("rev-parse", "--show-toplevel"):
            return 0, str(top_of(Path(path)))
        if a[:2] == ("config", "--get"):
            return (0, remote) if remote else (1, "")
        if a[0] == "check-ignore":
            return ignored, ""
        return 1, ""
    return git


def sha12(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def project_id_formula():
    """t-1043 F3 (Lead: sha256(remote_without_userinfo + newline + rel)[:12]; no remote -> the absolute project path, never sha256(''))."""
    inner = BASE / "f3a" / "x"
    inner.mkdir(parents=True)
    mark_project(inner)
    top = BASE / "f3b"
    top.mkdir()
    mark_project(top)
    a = man(run(inner, git=fake_git("https://github.com/o/app", lambda p: p.parent)))["project_id"]
    b = man(run(top, git=fake_git("https://github.com/o/appx", lambda p: p)))["project_id"]
    check_eq("G7 F3: remote .../app + folder x -> sha256('.../app' newline 'x')", a, sha12("https://github.com/o/app\nx"))
    check_eq("G7 F3: remote .../appx + the git top itself -> sha256('.../appx' newline '')", b, sha12("https://github.com/o/appx\n"))
    check("G7 F3: ... and the two differ (without the separator both were sha256('https://github.com/o/appx'))", a != b)
    one, two = P(), P()
    i1 = man(run(one, git=fake_git(None, lambda p: p)))["project_id"]
    i2 = man(run(two, git=fake_git(None, lambda p: p)))["project_id"]
    check_eq("G7 F3: no origin, the folder is the git top -> the absolute project path stands for the remote", i1, sha12(one.resolve().as_posix() + "\n"))
    check("G7 F3: two repositories with no origin, each at its top, get different ids, and neither is the sha256 of the empty string",
          i1 != i2 and "e3b0c44298fc" not in (i1, i2))


def install_identity():
    """t-1043 F2 (Lead: the mark records the git top and the project_id it was born with; another top/id -> a NEW install_id, the old mark kept under previous)."""
    remote = "https://git.example.test/org/repo.git"
    up = lambda p: p.parent      # noqa: E731
    A = BASE / "cloneA" / "proj"
    A.mkdir(parents=True)
    mark_project(A)
    W(A, "records/journal.jsonl", '{"n":1}\n')
    ga = fake_git(remote, up)
    m1, m2 = man(run(A, 0, git=ga)), man(run(A, 5, git=ga))
    check("G4g F2: the same folder, the next run -> the same install_id and a window since the last archive", m2["install_id"] == m1["install_id"] and m2["window"]["since_archive"] != "install")
    B = BASE / "cloneB" / "proj"
    shutil.copytree(A, B)
    m3 = man(run(B, 10, git=fake_git(remote, up)))
    check("G4g F2: the precondition - the same remote and the same folder name give the copy the SAME project_id (the id alone cannot tell them apart)", m3["project_id"] == m1["project_id"])
    check("G4g F2: a project folder copied with its state/ (another git top) -> a NEW install_id, a gap line, the first-run window",
          m3["install_id"] != m1["install_id"] and any("not this project" in g["what"] for g in m3["gaps"]) and m3["window"]["since_archive"] == "install")
    mk = json.loads((B / "qa-factory/state/collect/mark.json").read_text(encoding="utf-8"))
    check("G4g F2: the copy's mark keeps the old mark under previous (its install_id) and records its own git top",
          [p["install_id"] for p in mk.get("previous") or []] == [m1["install_id"]] and mk["install_id"] == m3["install_id"] and mk.get("git_top") == str(B.parent.resolve()))
    check("G4g F2: the original folder is not disturbed (the same install_id again)", man(run(A, 15, git=ga))["install_id"] == m1["install_id"])
    # temporal edge: a mark of the first generation (no git top, the old id formula) is the same install ONCE and is rewritten with the top
    mkp = A / "qa-factory/state/collect/mark.json"
    doc = json.loads(mkp.read_text(encoding="utf-8"))
    del doc["git_top"]
    doc["project_id"] = sha12(remote + "proj")
    mkp.write_text(json.dumps(doc), encoding="utf-8")
    m5 = man(run(A, 20, git=ga))
    check("G4g F2 temporal: an OLD mark (no git top, the old project_id) is read as the same install, with its window", m5["install_id"] == m1["install_id"] and m5["window"]["since_archive"] != "install")
    check_eq("G4g F2 temporal: ... and the mark is rewritten with the git top", json.loads(mkp.read_text(encoding="utf-8")).get("git_top"), str(A.parent.resolve()))
    doc = json.loads(mkp.read_text(encoding="utf-8"))
    del doc["git_top"]
    doc["project_id"] = "0" * 12
    mkp.write_text(json.dumps(doc), encoding="utf-8")
    check("G4g F2 temporal: an old mark of ANOTHER project is still foreign", man(run(A, 25, git=ga))["install_id"] != m1["install_id"])


def archive_names_and_atomic_write():
    """t-1043 F1 (name to the second; -2, -3 on a collision; an earlier archive is never overwritten or deleted) and F5 (.part, then os.replace)."""
    root = full(P())
    r1 = run(root, 0)
    a1 = Path(r1["archive"])
    b1 = a1.read_bytes()
    r2 = run(root, 0, since="install")
    r3 = run(root, now=NOW + timedelta(milliseconds=999), since="install")
    r4 = run(root, now=NOW + timedelta(seconds=1), since="install")
    names = [Path(r["archive"]).name for r in (r1, r2, r3, r4)]
    check_eq("G3 F1: the name carries the time to the second; two runs in one second -> -2, then -3; the next second -> a name of its own",
             [n.split("-", 3)[3] for n in names], ["20261019T120000Z.zip", "20261019T120000Z-2.zip", "20261019T120000Z-3.zip", "20261019T120001Z.zip"])
    check("G3 F1: all four archives are on disk and the first is byte for byte what the first run wrote", all(Path(r["archive"]).is_file() for r in (r1, r2, r3, r4)) and a1.read_bytes() == b1)
    check_eq("G3 F1: the mark names the archive of the last run", json.loads((root / "qa-factory/state/collect/mark.json").read_text(encoding="utf-8"))["runs"][-1]["archive"], names[3])
    big = P()
    for i in range(3):
        W(big, f"strategy/{['project-profile', 'aspect-profile', 'test-strategy'][i]}.md", "".join(os.urandom(15).hex() + "\n" for _ in range(2000)))
    p1 = run(big, part_max_bytes=40_000)
    sums = {p: hashlib_sha(p) for p in p1["parts"]}
    p2 = run(big, part_max_bytes=40_000, since="install")
    check("G6 F1: a second multi-part run in the same second gets its own part names (-2) and leaves the first run's parts untouched",
          len(p1["parts"]) >= 2 and not set(p1["parts"]) & set(p2["parts"]) and all("-2" in Path(p).name for p in p2["parts"]) and all(hashlib_sha(p) == s for p, s in sums.items()))
    # a refused second run (the post-check) in the same second leaves the first archive and the mark alone
    keep = full(P())
    q1 = run(keep)
    first = Path(q1["archive"])
    before, mark_before = first.read_bytes(), (keep / "qa-factory/state/collect/mark.json").read_bytes()
    W(keep, "state/cost/s2.json", json.dumps({"session_id": "s2", "note": "planted " + SECRET_NAME}))
    msg = refused(lambda: run(keep, redactor=Leaky()))
    left = sorted(p.name for p in first.parent.glob("qa-collect-" + q1["install_id"][:8] + "-*"))
    check("G8 F1: a refused run in the same second leaves the first archive on disk, byte for byte, and no file of its own", bool(msg) and left == [first.name] and first.read_bytes() == before, str(left))
    check("G8 F1: ... and the mark is unchanged", (keep / "qa-factory/state/collect/mark.json").read_bytes() == mark_before)
    # F5: a write that fails half way leaves no archive and no .part, and the mark does not move
    root5 = full(P())
    r5 = run(root5)
    out = Path(r5["archive"]).parent
    listing, mk = sorted(os.listdir(out)), (root5 / "qa-factory/state/collect/mark.json").read_bytes()
    W(root5, "state/cost/s2.json", json.dumps({"session_id": "s2", "total_cost_usd": 2}))
    real, calls, got = zipfile.ZipFile.writestr, [0], None

    def boom(self, *a, **k):
        calls[0] += 1
        if calls[0] == 2:                       # the manifest is in, the next member fails: a truncated archive if the name were final
            raise OSError(28, "No space left on device")
        return real(self, *a, **k)
    zipfile.ZipFile.writestr = boom
    try:
        run(root5, 5)
    except OSError as exc:
        got = exc
    finally:
        zipfile.ZipFile.writestr = real
    check("G3 F5: a write error is not swallowed (it reaches the caller)", got is not None and calls[0] == 2)
    check_eq("G3 F5: ... no .zip and no .part of the failed run is left in the folder", sorted(os.listdir(out)), listing)
    check("G3 F5: ... and the mark did not move", (root5 / "qa-factory/state/collect/mark.json").read_bytes() == mk)


def ceilings_and_parts():
    root = P()
    mb = 1024 * 1024
    big = b"".join(b"a" * (mb - 1) + b"\n" for _ in range(16))
    W(root, "strategy/test-strategy.md", big)
    # the real redactor needs ~5 s for ONE unbroken 16 KB line and ~76 s for 64 KB (quadratic, CL1-1: reported in the hand-off), so the
    # 16 MiB pins isolate the packer's ceiling with a redactor that copies: the ceiling is the packer's, the speed is not under test
    r = run(root, redactor=Fast())
    m = man(r)
    check("G5 edge 10: a file of exactly 16 MiB (after the redactor) is copied", len(big) == 16 * mb and row(m, "strategy/test-strategy.md")["bytes"] == 16 * mb and not any(s["reason"] == "too_large" for s in m["skipped"]))
    W(root, "strategy/test-strategy.md", big + b"x")
    m = man(run(root, 5, redactor=Fast()))
    big_row = next(s for s in m["skipped"] if s["src_rel"] == "strategy/test-strategy.md")
    check("G5 edge 10: 16 MiB + 1 -> too_large with the bytes, sha256, lines and the head/tail excerpt", big_row["reason"] == "too_large" and big_row["bytes"] == 16 * mb + 1
          and len(big_row["sha256"]) == 64 and big_row["lines"] == 17 and big_row["excerpt"].count("\n") <= 41 and "[... omitted ...]" in big_row["excerpt"])
    root = P()
    body = ("a" * 99 + "\n") * 9 + "a" * 99 + "\n"
    W(root, "strategy/test-strategy.md", body)
    W(root, "strategy/faq.md", body + "b\n")
    W(root, "obligations.md", ("by " + SECRET_NAME + "\n") * 60 + ("z" * 30 + "\n") * 5)
    m = man(run(root, file_max_bytes=1000))
    check("G5 seam: AT the data ceiling (1000 bytes) copied, one byte BEYOND too_large", row(m, "strategy/test-strategy.md")["bytes"] == 1000
          and any(s["src_rel"] == "strategy/faq.md" and s["reason"] == "too_large" for s in m["skipped"]))
    exc = next(s["excerpt"] for s in m["skipped"] if s["src_rel"] == "obligations.md")
    check("G5: the excerpt passes the redactor (the name is <user>) and keeps at most 20 + 20 lines", SECRET_NAME not in exc and "<user>" in exc and exc.count("\n") <= 41)
    # parts: the planner against the real size of a real zip (independent oracle: the file system)
    rnd = [("a/%d" % i, os.urandom(2000)) for i in range(3)]
    mf = lambda parts: b'{"parts": %d}' % len(parts)      # noqa: E731
    whole = BASE / "oracle.zip"
    C._write_zip(whole, [("manifest.json", mf([]))] + rnd, NOW)
    s_true = whole.stat().st_size
    check_eq("G6 edge 10 / F-4: an archive at exactly the part limit is one part", len(C.plan_parts(rnd, mf, s_true)), 1)
    check("G6: one byte over the limit -> two parts", len(C.plan_parts(rnd, mf, s_true - 1)) == 2)
    root = P()
    for i in range(3):
        W(root, f"strategy/{['project-profile', 'aspect-profile', 'test-strategy'][i]}.md", "".join(os.urandom(15).hex() + "\n" for _ in range(2000)))
    r = run(root, part_max_bytes=40_000)
    m = man(r)
    sizes = [Path(p).stat().st_size for p in r["parts"]]
    listed = {p["name"]: p for p in m["parts"]}
    mem = members(r)
    check("G6 F-4 / m8: several parts, each within the limit; part 1 lists parts 2..n with the sha256 and bytes of the files, its own sha excluded",
          len(r["parts"]) >= 2 and max(sizes) <= 40_000 and [Path(p).name for p in r["parts"][1:]] == list(listed)
          and all(hashlib_sha(Path(r["parts"][i + 1])) == listed[Path(r["parts"][i + 1]).name]["sha256"] for i in range(len(r["parts"]) - 1)) and m["part_count"] == len(r["parts"]), str(sizes))
    check("G6: every member of the manifest is in exactly one part with the listed sha256", all(r_["arc"] in mem and hashlib_bytes(mem[r_["arc"]]) == r_["sha256"] for r_ in m["files"] if r_["arc"]))


def hashlib_sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hashlib_bytes(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


class Leaky:
    """A redactor that lets everything through but judges with the real post-check: the planted leak of the I2 detector."""
    gaps = []

    def file(self, name, data):
        return M.Result("copied", "json" if name.endswith(".json") else "text", data, "", {k: 0 for k in M.CATEGORIES})

    def __getattr__(self, name):
        return getattr(RED, name)


class Fast(Leaky):
    def residue(self, *a, **k):
        return []

    def residue_document(self, *a, **k):         # `_verify` reads a member through it (t-1206 C2-1): the copy-only redactor judges nothing
        return []


class MemberLeaky(Leaky):
    """`Leaky` for every member but the project marker: the marker (the shipped template) goes through the real redactor, because its own
    description leaves carry paths and a pattern that `Leaky` would pass raw - and the post-check would refuse THEM, not the member under test."""

    def file(self, name, data):
        return RED.file(name, data) if Path(name).name == "config.json" else super().file(name, data)


def post_check():
    root = P()
    W(root, "state/cost/s1.json", json.dumps({"session_id": "s1", "note": "planted login " + SECRET_NAME}))
    out = BASE / "leakout"
    msg = refused(lambda: run(root, redactor=Leaky(), temp_root=out))
    check("G8 I2: a planted login in a member is found by residue() on the written archive -> a refusal (FR-1), the finder and the member named, no value",
          bool(msg) and "still carries" in msg and "update the plugin" in msg and SECRET_NAME not in msg, str(msg))
    check("G8: ... the archive is NOT left behind and the mark is not written", not list((out / "qa-collect").glob("*.zip")) and not (root / "qa-factory/state/collect/mark.json").exists())
    root2 = full(P())
    run(root2)
    before = (root2 / "qa-factory/state/collect/mark.json").read_bytes()
    W(root2, "state/cost/s2.json", json.dumps({"session_id": "s2", "note": "planted " + SECRET_NAME}))
    check("G8 edge: a refusal after a good run leaves the previous mark byte for byte", refused(lambda: run(root2, 5, redactor=Leaky(), temp_root=out)) is not None
          and (root2 / "qa-factory/state/collect/mark.json").read_bytes() == before)
    root3 = P()
    W(root3, "state/cost/s1.json", json.dumps({"session_id": "s1", "note": "planted login " + SECRET_NAME}))
    ok = run(root3)
    check("G8 positive control (same fixture, the real redactor): the archive is written and holds no login", SECRET_NAME.encode() not in b"".join(members(ok).values()))


def post_check_members():
    """t-1206 C2-1: `_verify` reads a member through `run.red.residue_document(text, kind, _first=True)`, kind from the member suffix."""
    check_eq("C2-1: the kind of a member comes from its suffix (.json, .jsonl/.ndjson, anything else - or none - is text)",
             [C._kind(n) for n in ("a.json", "A.JSON", "a.jsonl", "a.NDJSON", "a.md", "noext", "a.json.txt")], ["json", "json", "jsonl", "jsonl", "text", "text", "text"])
    tok = "ghp_" + "Q" * 36
    out = BASE / "keyout"
    root = P()
    W(root, "state/cost/s1.json", json.dumps({"session_id": "s1", tok: 1}))
    msg = refused(lambda: run(root, redactor=MemberLeaky(), temp_root=out))
    check("C2-1: a member whose JSON KEY is token-shaped is refused by _verify (the key is read with the detectors on, as the writer reads it), no value in the message",
          bool(msg) and "still carries" in msg and "detector:github_token" in msg and tok not in msg, str(msg))
    root_ok = P()
    W(root_ok, "state/cost/s1.json", json.dumps({"session_id": "s1", tok: 1}))
    ok = run(root_ok)
    check("C2-1 positive control (same fixture, the real redactor): the archive is written and holds no token", tok.encode() not in b"".join(members(ok).values()))
    root = P()
    W(root, "records/journal.jsonl", json.dumps({"session_id": "s1", tok: 1}) + "\n")
    msg = refused(lambda: run(root, redactor=MemberLeaky(), temp_root=out))
    check("C2-1: a JSONL member is read by line and its key is read the same way: refused", bool(msg) and "detector:github_token" in msg, str(msg))
    patterns = json.dumps({"exempt_path_patterns": ["\\.env$", "\\.env\\."]}, indent=2)
    root = P()
    W(root, "state/cost/s1.json", patterns)
    check("C2-1: a .json member holding the escaped `\\\\.env\\\\.` pattern list is NOT refused (read by its leaves, kind json)",
          refused(lambda: run(root, redactor=MemberLeaky(), temp_root=out)) is None)
    root = P()
    W(root, "strategy/project-profile.md", patterns)
    msg = refused(lambda: run(root, redactor=MemberLeaky(), temp_root=out))
    check("C2-1 negative control: the same bytes in a text member (kind text, one line at a time) ARE refused as a residual path", bool(msg) and "residual-path" in msg, str(msg))
    root = P()
    W(root, "state/cost/s1.json", '{"session_id": "s1", "note": "run by ' + SECRET_NAME + '"')
    msg = refused(lambda: run(root, redactor=MemberLeaky(), temp_root=out))
    check("C2-1 edge: a .json member whose bytes are not JSON is read by line (never a silent pass): the login on its line is found", bool(msg) and "still carries" in msg and SECRET_NAME not in msg, str(msg))
    root = P()
    W(root, "state/cost/s1.json", "")
    check("C2-1 edge: an EMPTY member is not a refusal", refused(lambda: run(root, redactor=MemberLeaky(), temp_root=out)) is None)


def never_and_extras():
    root = full(P())
    ev = root / "qa-factory/artifacts/TP1-1/evidence"
    r = run(root, extras=[("B", ev)])
    m, blob = man(r), b"".join(members(r).values())
    check("G9 section 2 'never': an --extra that points into evidence/ is skipped as never; the content is in no member",
          MARK.encode() not in blob and any(s["reason"] == "never" and "log.txt" in s["src_rel"] for s in m["skipped"]), str([s["reason"] for s in m["skipped"]]))
    secret = root / "qa-factory" / "creds"
    secret.mkdir()
    (secret / "x.env").write_text("K=v")
    check("G9 edge: an --extra on a secret-file pattern is refused with the pattern named", "secret-file pattern" in (refused(lambda: run(root, 5, extras=[("B", secret / "x.env")])) or ""))
    outside = BASE / "outside.txt"
    outside.write_text("x")
    msg = refused(lambda: run(root, 5, extras=[("B", outside)]))
    check("G9 section 6: an --extra outside the project folder is refused, naming --extra and the door", bool(msg) and "--extra" in msg and "outside the project" in msg, str(msg))
    check("G9: an --extra with a missing path / a wrong set is refused", "no such file" in (refused(lambda: run(root, 5, extras=[("B", root / "nope")])) or "") and "not a set" in (refused(lambda: run(root, 5, extras=[("Z", ev)])) or ""))
    inside = root / "elsewhere" / "journal.jsonl"
    inside.parent.mkdir()
    inside.write_text('{"k":1}\n')
    cfg = json.loads((root / "qa-factory/config.json").read_text(encoding="utf-8"))
    cfg["journal_path"] = "elsewhere/journal.jsonl"
    (root / "qa-factory/config.json").write_text(json.dumps(cfg), encoding="utf-8")
    m2 = man(run(root, 6, extras=[("B", inside)]))
    check("G9 edge 14: a journal the config names outside qa-factory/ -> 'not found at the standard place' + the door; --extra then copies it",
          any(g["what"] == "B: records/journal.jsonl not found at the standard place" and "--extra B=" in g["why"] for g in m2["gaps"]) and row(m2, "extra/B/journal.jsonl") is not None)
    # artifact_root outside the project (m7)
    far = P()
    store = BASE / "store"
    (store / "TASK-9").mkdir(parents=True)
    (store / "TASK-9" / "pipeline.json").write_text(json.dumps({"plugin_version": "0.8.0"}))
    cfg = json.loads((far / "qa-factory/config.json").read_text(encoding="utf-8"))
    cfg["artifact_root"] = str(store)
    (far / "qa-factory/config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (store / "TASK-10").mkdir()
    (store / "TASK-10" / "pipeline.json").write_text("{}")
    (store / "TASK-11").mkdir()
    (store / "TASK-11" / "pipeline.json").write_text(json.dumps({"run_mode": {"plugin_version": "0.10.0"}, "plugin_version": "0.9.0"}))
    msg = refused(lambda: run(far))
    check("G9 m7 / edge: artifact_root outside the project and no --extra -> a refusal that names --extra B=<the folder>", bool(msg) and "--extra B=" in msg and "artifact_root" in msg, str(msg))
    got = man(run(far, 5, extras=[("B", store)]))
    check("G9 m7 / edge 3: with --extra the stories there are packed; a story of an older layout without plugin_version has it null, not a crash; run_mode.plugin_version wins over the old top-level key (CL3-5)",
          [(s["task"], s["plugin_version"]) for s in got["stories"]] == [("TASK-10", None), ("TASK-11", "0.10.0"), ("TASK-9", "0.8.0")] and row(got, "artifacts/TASK-9/pipeline.json") is not None, str(got["stories"]))
    W(root, "artifacts/TP1-1/evidence/big.bin", b"x" * 1500)
    idx = [json.loads(v) for k, v in members(run(root, 9, file_max_bytes=1000, since="install")).items() if k.startswith("summaries/B/TP1-1/B11")]
    check("G9 edge 6: evidence over the file ceiling is indexed with sha256 null and not_hashed (the index does not grow the archive)",
          any(i["sha256"] is None and i["flags"] == ["not_hashed"] and i["bytes"] == 1500 for ix in idx for i in ix["index"]), str(idx)[:300])
    bad = P()
    (bad / "qa-factory/config.json").write_text("{broken", encoding="utf-8")
    mb_ = man(run(bad))
    check("G9 m7: a broken config.json is a gap, not a crash; the config itself is skipped, never sent", any("artifact_root" in g["what"] for g in mb_["gaps"])
          and any(s["src_rel"] == "config.json" and s["reason"] == "json_unparsable" for s in mb_["skipped"]))
    sym = P()
    try:
        os.symlink(str(outside), str(sym / "qa-factory/strategy-link.md"))
        check("G9 a symlink is never followed", any(s["reason"].startswith("symlink") for s in man(run(sym))["skipped"]))
    except (OSError, NotImplementedError):
        pass


def answers_and_rules():
    root = P()
    good = BASE / "problems.txt"
    good.write_bytes(("It broke at " + HOME_ + "\\x for " + SECRET_NAME + "\n").encode("utf-8"))
    empty = BASE / "empty.txt"
    empty.write_bytes(b"  \n")
    r = run(root, problems_file=good, suggestions_file=empty)
    m = man(r)
    check("G10 m5: a file with words -> answered, the member passes the redactor; an empty file -> blank",
          m["answers"]["problems"]["state"] == "answered" and members(r)[m["answers"]["problems"]["arc"]] == b"It broke at <home>\\x for <user>\n"
          and m["answers"]["suggestions"] == {"state": "blank", "arc": None})
    check_eq("G10 m5: a flag not passed -> blank; the explicit not_asked -> not_asked; words win over not_asked",
             (man(run(P()))["answers"]["problems"]["state"], man(run(P(), not_asked=True))["answers"]["problems"]["state"], man(run(P(), not_asked=True, problems_file=good))["answers"]["problems"]["state"]),
             ("blank", "not_asked", "answered"))
    msg = refused(lambda: run(P(), problems_file=BASE / "nope.txt")) or ""
    check("G10 edge / F4: a named answers file that is missing is a refusal that says it is missing and names the file, not 'cannot be read as UTF-8'",
          "no such file" in msg and "nope.txt" in msg and "UTF-8" not in msg, msg)
    # F4: the words come through person_words.read; a file it refuses is a refusal here, never an 'answered' with no member
    bad = P()
    bad_cases = {"UTF-16 with a BOM": "words\n".encode("utf-16"), "UTF-16 without a BOM": "words\n".encode("utf-16-le"), "invalid UTF-8": b"\xc3\x28 words"}
    for label, raw in bad_cases.items():
        f = BASE / "bad-answers.txt"
        f.write_bytes(raw)
        msg = refused(lambda: run(bad, problems_file=f)) or ""
        check(f"G10 F4: an answers file in {label} is a refusal that names the file and says it is not UTF-8 text (the words are not dropped)", "bad-answers.txt" in msg and "not UTF-8" in msg, msg)
    check("G10 F4: ... and nothing was written for it", not (bad / "qa-factory/state/collect/mark.json").exists())
    zero, bom = BASE / "zero.txt", BASE / "bom.txt"
    zero.write_bytes(b"")
    bom.write_bytes(b"\xef\xbb\xbf \r\n")
    check_eq("G10 F4/m5: an empty file and a BOM-only file are blank (as the whitespace file), not a refusal",
             [man(run(P(), problems_file=f))["answers"]["problems"] for f in (zero, bom)], [{"state": "blank", "arc": None}] * 2)
    import copy
    small = copy.deepcopy(M.load_rules())
    small["limits"]["text_max_bytes"] = 100
    tiny = M.compile_redactor(small, project_root=str(BASE), plugin_root=str(PLUGIN_ROOT), pythons=(sys.executable,), home=HOME_, tmp=tempfile.gettempdir(),
                              identities=IDS, hosts=("stand.corp-zq.example",), secret_values={"STAND_PASSWORD": "Zq7-pass-Word"}, short=lambda p: None)
    at, beyond = BASE / "at100.txt", BASE / "beyond101.txt"
    at.write_bytes(b"a" * 100)
    beyond.write_bytes(b"a" * 101)
    check_eq("G10 F4 AT: an answers file of exactly the redactor's text limit is answered", man(run(P(), problems_file=at, redactor=tiny))["answers"]["problems"]["state"], "answered")
    msg = refused(lambda: run(P(), problems_file=beyond, redactor=tiny)) or ""
    check("G10 F4 BEYOND: one byte more -> a refusal naming the file (not 'answered' with no member)", "beyond101.txt" in msg and "not packed" in msg and "over 100 bytes" in msg, msg)
    check("G10: --since takes only install", "install" in (refused(lambda: run(P(), since="yesterday")) or ""))
    broken = json.loads(C.SETS_FILE.read_text(encoding="utf-8"))
    broken["schema"] = 7
    msg = refused(lambda: C.load_sets(_write(broken)))
    check("G1 section 6: unreadable packing data -> a refusal in the spec's form (what file, why, reinstall; no packing without the rules)", bool(msg) and "cannot be read" in msg and "reinstall the plugin" in msg and "unredacted" in msg, str(msg))
    real = M.load_rules

    def boom(*a, **k):
        raise M.RulesUnreadable("rules.json", "the file is absent")
    M.load_rules = boom
    try:
        msg = refused(lambda: C.pack(P(), git=NOGIT, now=NOW, temp_root=BASE / "out"))
    finally:
        M.load_rules = real
    check("G1 section 6: the redaction rules unreadable -> the same refusal, nothing written", bool(msg) and "reinstall the plugin" in msg and "unredacted" in msg, str(msg))
    check("G11 summary: at most 12 lines, the real path of the archive, the reason for temp", (lambda ls: len(ls) <= 12 and r["archive"] in ls[0] and any("temp" in x for x in ls))(C.summary_lines(r)))


def _write(doc):
    p = BASE / "badsets.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


FOREIGN_MARK = "FOREIGN-STORY-ROLE-TEXT"
OWN_MARK = "OWN-SESSION-TEXT"


def stalled_project(sessions=(("sess-own", "S5-x-1"),), foreign=True, extra_state=None):
    """A project with the story QA-S whose driver was cut off (K1, an hour before NOW); the host's transcripts sit OUTSIDE the project, under
    `cc<n>/`: each cost file's `transcript` and the `subagents/agent-*.jsonl` beside it - one more session that belongs to another story."""
    root = P()
    T = "artifacts/QA-S/"
    W(root, T + "pipeline.json", json.dumps({"plugin_version": "0.9.0", "stages": {}}))
    W(root, T + "state/events.jsonl", LINES)
    W(root, T + "state/driver-state.json", json.dumps({"sessions": {d: s for s, d in sessions}, "interrupted": {"S5-x-1": {"at": "2026-10-19T11:00:00Z"}}, "in_flight": {}}))
    for rel, text in (extra_state or {}).items():
        W(root, T + rel, text)
    cc = BASE / f"cc{COUNT[0]}"
    for sid, task_key, mark in [(s, "(no task)", OWN_MARK) for s, _d in sessions if not s.endswith("-gone")] + ([("sess-foreign", "QA-OTHER", FOREIGN_MARK)] if foreign else []):
        (cc / sid / "subagents").mkdir(parents=True, exist_ok=True)
        (cc / f"{sid}.jsonl").write_text(json.dumps({"type": "user", "text": f"{mark} {sid} by {SECRET_NAME} in {HOME_}"}) + "\n", encoding="utf-8")
        (cc / sid / "subagents" / f"agent-{sid}.jsonl").write_text(json.dumps({"type": "assistant", "text": f"{mark} role of {sid}"}) + "\n", encoding="utf-8")
        W(root, f"state/cost/{sid}.json", json.dumps({"session_id": sid, "transcript": str(cc / f"{sid}.jsonl"), "by_task": {task_key: {}}}))
    return root


def transcripts_of(res):
    out = {}
    for name in res.get("transcript_parts", []):
        with zipfile.ZipFile(Path(res["archive"]).parent / name) as zf:
            out.update({i.filename: zf.read(i.filename) for i in zf.infolist()})
    return out


def stall_and_transcripts():
    root = stalled_project(sessions=(("sess-own", "S5-x-1"), ("sess-gone", "S5-x-2")))
    r = run(root)
    m, mem, tr = man(r), members(r), transcripts_of(r)
    st = m["stories"][0]
    check("H1 K1: an interrupted call after the mark -> stalled, the signal carries its id, where and a UTC time",
          st["stalled"] is True and [s["id"] for s in st["stall_signals"]] == ["K1"] and st["stall_signals"][0]["at"] == "2026-10-19T11:00:00Z", str(st))
    check_eq("H2 section 2 H: the story's own main transcript and its own subagent are packed - nothing of the other story's session (a foreign story's subagent)",
             sorted(k.rsplit("/", 1)[-1] for k in tr), ["agent-sess-own.jsonl", "sess-own.jsonl"])
    check("H2: ... not in the main archive, and the foreign marker is in no member of any file",
          not any(k.startswith("H/") for k in mem if k not in tr) and FOREIGN_MARK.encode() not in b"".join(mem.values()) + b"".join(tr.values()) and OWN_MARK.encode() in b"".join(tr.values()))
    check("H3 I2: the transcripts pass the redactor (no name, no home) and the host path of the transcript file is not a name in the manifest",
          SECRET_NAME.encode() not in b"".join(tr.values()) and b"<user>" in b"".join(tr.values()) and "cc" + str(COUNT[0]) not in json.dumps(m["files"]))
    check_eq("H4 F-5 (i): the transcripts are their OWN file, listed in the manifest with kind transcripts, its sha256 and size as written",
             [(p["name"], p["kind"], p["sha256"], p["bytes"]) for p in m["parts"]],
             [(Path(r["archive"]).name[:-4] + "-transcripts.zip", "transcripts", hashlib.sha256((Path(r["archive"]).parent / (Path(r["archive"]).name[:-4] + "-transcripts.zip")).read_bytes()).hexdigest(),
               (Path(r["archive"]).parent / (Path(r["archive"]).name[:-4] + "-transcripts.zip")).stat().st_size)])
    check_eq("H5: stories[].transcripts names each packed file (sid, kind, arc) and the set H is collected, with the gap of the missing one",
             ([(t["sid"], t["kind"]) for t in st["transcripts"]], m["sets"]["H"]["status"]), ([("sess-own", "main"), ("sess-own", "subagent")], "collected"))
    check("H5 edge 11: a session the journal names that has no cost file is a gap of H that names its sid (H does not search the disk)",
          any(g["set"] == "H" and "sess-gone" in g["what"] for g in m["gaps"]), str(m["gaps"]))
    check("H6 summary: the transcripts file is named with 'delete that file' and the note that the main transcript carries other work; still at most 12 lines",
          (lambda ls: len(ls) <= 12 and any("-transcripts.zip" in x and "delete that file" in x and "other work" in x for x in ls)
           and not any(x.startswith("Send all parts") and "transcripts" in x for x in ls))(C.summary_lines(r)))
    # a second run: the K1 episode is older than the mark now (only what is NEW since the last packing is an episode)
    s2 = man(run(root, 5))["stories"][0]
    check("H7a window: the same interrupted call, now BEFORE the mark -> not an episode any more: not stalled, no transcripts again", s2["stalled"] is False and s2["transcripts"] == [], str(s2))
    # a story stalled by idleness (`current`) is stalled at every run: its unchanged transcripts are 'unchanged since the last packing', no new bytes
    idle = {"state/events.jsonl": json.dumps({"sequence": 1, "type": "x", "created_at": "2026-10-16T10:00:00Z", "event_hash": "h1"}) + "\n",
            "state/driver-state.json": json.dumps({"sessions": {"S5-x-1": "sess-own"}, "in_flight": {}, "interrupted": {}})}
    ri = stalled_project(foreign=False, extra_state=idle)
    run(ri)
    r2 = run(ri, 5)
    t2 = man(r2)["stories"][0]["transcripts"]
    check("H7 mark: nothing changed in the transcripts -> every one is 'unchanged since the last packing', no transcripts file is written",
          len(t2) == 2 and [t["flags"] for t in t2] == [["unchanged"]] * 2 and r2["transcript_parts"] == [] and transcripts_of(r2) == {}, str(t2))
    # a story that is not stalled yields nothing; a shared session is packed once
    quiet = P()
    W(quiet, "artifacts/QA-Q/pipeline.json", json.dumps({"plugin_version": "0.9.0"}))
    W(quiet, "artifacts/QA-Q/state/events.jsonl", LINES)
    rq = run(quiet)
    check("H8 a story that is going on is not stalled: no signals, no transcripts file", man(rq)["stories"][0]["stalled"] is False and rq["transcript_parts"] == [])
    two = stalled_project(foreign=False)
    for k in ("QA-S2",):
        for rel in ("pipeline.json", "state/events.jsonl", "state/driver-state.json"):
            W(two, f"artifacts/{k}/{rel}", (two / "qa-factory/artifacts/QA-S" / rel).read_text(encoding="utf-8"))
    rt = run(two)
    check_eq("H9 a session two stalled stories share is packed ONCE (the second story's entry points to the first)",
             ([len(v["transcripts"]) for v in man(rt)["stories"]], sum(1 for k in transcripts_of(rt) if k.endswith("/sess-own.jsonl")), [t.get("shared_with") for t in man(rt)["stories"][1]["transcripts"]]),
             ([2, 2], 1, ["QA-S", "QA-S"]))
    small = stalled_project(foreign=False)
    rs = run(small, file_max_bytes=40)
    check("H10 ceiling: a transcript over the file ceiling is a skipped row too_large (no silent slice), the entry says so",
          any(s["reason"] == "too_large" and s["src_rel"].startswith("transcripts/QA-S/") for s in man(rs)["skipped"]) and any(t.get("skipped") == "too_large" for t in man(rs)["stories"][0]["transcripts"]))


def loops_and_transcripts():
    """CL3-9: the transcripts of a story that LOOPED (not stalled), the unknown loop state, the broken table. Expectations: spec t-625."""
    def state(**more):
        return {"state/driver-state.json": json.dumps({"sessions": {"S5-x-1": "sess-own"}, "in_flight": {}, "interrupted": {}, **more})}
    cap = {"window_rounds": {"S5|c1": [{"at": "2026-10-19T11:00:00Z", "dispatch": "S5-x-1", "set": ["x"], "outcome": "cap"}]}}
    # H-L1 (I-0): a story with nothing looping and not stalled stays without transcripts
    quiet = P()
    W(quiet, "artifacts/QA-Q/pipeline.json", json.dumps({"plugin_version": "0.9.0"}))
    W(quiet, "artifacts/QA-Q/state/events.jsonl", LINES)
    rq = run(quiet)
    sq = man(rq)["stories"][0]
    check("H-L1 a clean story: looped False, no loop signals, no transcripts file", sq["looped"] is False and sq["loop_signals"] == [] and rq["transcript_parts"] == [], str(sq))
    # H-L2: not stalled, looped -> its transcripts are packed
    root = stalled_project(foreign=False, extra_state=state(**cap))
    r = run(root)
    st = man(r)["stories"][0]
    check("H-L2 a window `cap` row after the mark: stalled False, looped True, L2 with a UTC time",
          st["stalled"] is False and st["looped"] is True and [s["id"] for s in st["loop_signals"]] == ["L2"] and st["loop_signals"][0]["at"] == "2026-10-19T11:00:00Z", str(st))
    check_eq("H-L2 ... and its transcripts are packed in the transcripts file", sorted(k.rsplit("/", 1)[-1] for k in transcripts_of(r)), ["agent-sess-own.jsonl", "sess-own.jsonl"])
    check("H-L2 the manifest names the loop signals under their own key and the stall's list stays empty", st["stall_signals"] == [])
    # H-L3: a looped story whose transcript is not on disk: reported, not silent
    gone = stalled_project(sessions=(("sess-own", "S5-x-1"), ("sess-gone", "S5-x-2")), foreign=False,
                           extra_state={"state/driver-state.json": json.dumps({"sessions": {"S5-x-1": "sess-own", "S5-x-2": "sess-gone"}, "in_flight": {}, "interrupted": {}, **cap})})
    mg = man(run(gone))
    check("H-L3 a looped story with a session whose transcript is not on disk: a gap of H names the session id",
          mg["stories"][0]["looped"] is True and any(g["set"] == "H" and "sess-gone" in g["what"] for g in mg["gaps"]), str(mg["gaps"]))
    # H-L4: a wrong shape is an unknown loop state: packed, and ONE gap line says so
    odd = stalled_project(foreign=False, extra_state=state(window_rounds="x"))
    ro = run(odd)
    so = man(ro)
    check("H-L4 `window_rounds: \"x\"`: stalled False, looped None, transcripts packed, one gap `loops of QA-S unknown`",
          so["stories"][0]["stalled"] is False and so["stories"][0]["looped"] is None and so["stories"][0]["transcripts"]
          and sum(1 for g in so["gaps"] if g["what"] == "loops of QA-S unknown") == 1, str(so["gaps"]))
    # H-L5: not onboarded: nothing is judged
    off = stalled_project(foreign=False, extra_state=state(**cap))
    (off / "qa-factory/config.json").unlink()
    sf = man(run(off))["stories"][0]
    check_eq("H-L5 not onboarded: looped None, no loop signals", (sf["looped"], sf["loop_signals"]), (None, []))
    # H-L6: the loop row before the mark on the second run is not a loop
    s2 = man(run(root, 5))["stories"][0]
    check("H-L6 the same row, now BEFORE the mark: not looped, no transcripts", s2["looped"] is False and s2["transcripts"] == [], str(s2))
    # H-L7: a broken table refuses the whole collect, before anything is written (B-4: not swallowed by the stall's guard)
    real = C.collect_stall.LOOPS_FILE
    bad = BASE / "badloops.json"
    bad.write_text("{not json", encoding="utf-8")
    C.collect_stall.LOOPS_FILE = bad
    try:
        out_before = sorted((BASE / "out").rglob("*")) if (BASE / "out").exists() else []
        msg = refused(lambda: run(stalled_project(foreign=False)))
        out_after = sorted((BASE / "out").rglob("*")) if (BASE / "out").exists() else []
    finally:
        C.collect_stall.LOOPS_FILE = real
    check("H-L7 a broken collect-loops.json: Refused, naming the file and `reinstall the plugin`", bool(msg) and "badloops.json" in msg and "reinstall the plugin" in msg, str(msg))
    check("H-L7 ... and nothing was written", out_before == out_after)
    # H-L8: the summary line
    check("H-L8 the summary line speaks of stalled or looped stories",
          any("Transcripts of the stories that stalled or looped" in x for x in C.summary_lines(r)), str(C.summary_lines(r)))


def stall_waiting_unreadable_and_config():
    idle = {"state/events.jsonl": json.dumps({"sequence": 1, "type": "x", "created_at": "2026-10-16T10:00:00Z", "event_hash": "h1"}) + "\n"}
    base = lambda **kw: {"pipeline.json": json.dumps({"plugin_version": "0.9.0"}), **idle, **kw}    # noqa: E731

    def story(files, config=None):
        root = P()
        for rel, text in files.items():
            W(root, "artifacts/QA-I/" + rel, text)
        if config is not None:
            W(root, "config.json", json.dumps(config))
        return root
    s = man(run(story(base())))["stories"][0]
    check("H11 `current`: not closed, nothing live, idle for 3 days (beyond 24 h) -> stalled with no episode signal", s["stalled"] is True and s["stall_signals"] == [], str(s))
    w = man(run(story(base(**{"state/driver-question.md": "# q\n"}))))["stories"][0]
    check_eq("H12 a story whose last open item is a person's wait: 'waiting for a person', not stalled, no transcripts", (w["stalled"], w["record"], w["transcripts"]), (False, "waiting for a person", []))
    check_eq("H13 section 5 temporal edge: a config written before collect.stall_quiet_hours existed -> the default 24 h (idle 3 days: stalled; idle 2 h: not)",
             (man(run(story(base(), config={"cost": {}})))["stories"][0]["stalled"], man(run(story(base(), config={})))["stories"][0]["stall_signals"]), (True, []))
    fresh = {"state/events.jsonl": json.dumps({"sequence": 1, "type": "x", "created_at": "2026-10-19T02:00:00Z", "event_hash": "h1"}) + "\n"}    # 10 h before NOW
    check_eq("H14 stall_quiet_hours is DATA: 10 h idle is going on at 24 (the template and an absent key), stalled at 5",
             [man(run(story(base(**fresh), config=c)))["stories"][0]["stalled"] for c in ({"collect": {"stall_quiet_hours": 24}}, {}, {"collect": {"stall_quiet_hours": 5}}, {"collect": {"stall_quiet_hours": None}})],
             [False, False, True, False])
    # CL1-4 F3 (t-1067, FR-59): the key has a declared default (24, absent_means: default), so a value the rule cannot use must not turn EVERY story
    # into 'unknown' with all its transcripts packed: the default is used and ONE gap line of H says so. The rule itself stays strict (test_collect_stall).
    GAP_Q = "config: stall_quiet_hours unreadable, default 24 used"
    for bad_value in ("soon", -3, True, [5], {"h": 5}, float("nan"), float("inf")):
        r15 = man(run(story(base(**fresh), config={"collect": {"stall_quiet_hours": bad_value}})))
        r15b = man(run(story(base(), config={"collect": {"stall_quiet_hours": bad_value}})))
        check_eq(f"H15 F3 a bad stall_quiet_hours {bad_value!r}: verdicts as at the default 24 h (10 h idle: going on; 3 days idle: stalled, no unreadable signal), ONE gap line of H",
                 ([r15["stories"][0][k] for k in ("stalled", "stall_signals", "transcripts")], r15b["stories"][0]["stalled"], r15b["stories"][0]["stall_signals"],
                  [g["what"] for g in r15["gaps"] if g["set"] == "H"].count(GAP_Q), [g["what"] for g in r15b["gaps"]].count(GAP_Q)),
                 ([False, [], []], True, [], 1, 1))
    gq = next(g for g in r15["gaps"] if g["what"] == GAP_Q)
    check("H15 F3 the gap line says which value and what was used (one line, never a refusal)", "inf" in gq["why"] and "24 hours" in gq["why"], str(gq))
    broken = story(base(**fresh), config={})
    W(broken, "config.json", "{broken")
    rb = man(run(broken))
    check("H15 F3 a config that cannot be read at all: the default, the same gap line (and the existing config gap stays), no 'unknown' story",
          rb["stories"][0]["stalled"] is False and [g["what"] for g in rb["gaps"]].count(GAP_Q) == 1 and any("config.json" in g["why"] and "not valid JSON" in g["why"] for g in rb["gaps"] if g["what"] == GAP_Q), str(rb["gaps"]))
    quiet_ok = [[g["what"] for g in man(run(story(base(**fresh), config=c)))["gaps"]].count(GAP_Q) for c in
                ({}, {"collect": {}}, {"collect": {"stall_quiet_hours": None}}, {"collect": {"stall_quiet_hours": 24}}, {"collect": {"stall_quiet_hours": 0}}, {"collect": {"stall_quiet_hours": 5.5}})]
    check_eq("H15 F3 control: an absent key, a null, 24, 0 and 5.5 are values (or the declared default): no gap line", quiet_ok, [0] * 6)
    off = stalled_project(foreign=False)
    (off / "qa-factory/config.json").unlink()
    ro = run(off)
    so = man(ro)["stories"][0]
    check_eq("H15 F7 not onboarded (no config.json) but a story folder exists: H packs nothing - no verdict (unknown), no transcripts file - and its status says gap, as B-G do",
             (so["stalled"], so["transcripts"], ro["transcript_parts"], man(ro)["sets"]["H"]["status"]), (None, [], [], "gap"))
    void = P()
    (void / "qa-factory/artifacts/QA-E").mkdir(parents=True)
    ev = man(run(void))
    e = ev["stories"][0]
    check("H16 FR-41: an empty story folder -> stalled null (unknown), the unreadable signal, and a gap that says why there are no transcripts",
          e["stalled"] is None and [x["id"] for x in e["stall_signals"]] == ["unreadable"] and any(g["set"] == "H" and "QA-E" in g["what"] for g in ev["gaps"]), str(e))
    check("H17 the template carries the key the rule reads (collect.stall_quiet_hours) as the rule's default", json.loads((PLUGIN_ROOT / "references/templates/config.json").read_text(encoding="utf-8"))["collect"]["stall_quiet_hours"] == 24 == C.collect_stall.DEFAULT_QUIET_HOURS)


def cli():
    import contextlib
    import io

    def go(argv, **kw):
        out, err = io.StringIO(), io.StringIO()
        seams = dict(redactor=RED, git=NOGIT, temp_root=BASE / "out", rules_sha=M.rules_sha256(), now=NOW + timedelta(minutes=kw.pop("minutes", 0)))
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = C.main(argv, **seams)
        return code, out.getvalue(), err.getvalue()
    root = full(P())
    code, out, err = go(["--root", str(root), "--json"])
    doc = json.loads(out) if out.startswith("{") else {}
    check("K1 CLI: --json prints the result with the summary lines inside, exit 0; the archive exists", code == 0 and err == "" and Path(doc.get("archive", "")).is_file() and doc["summary"][0].startswith("Packed the factory's records into "), out[:200])
    code, out, err = go(["--root", str(P())])
    check("K1 CLI: without --json the stdout IS the summary (<= 12 lines, the real path)", code == 0 and 1 < len(out.splitlines()) <= 12 and "Send the file to the QA factory developers" in out)
    empty = BASE / "cli-nofolder"
    empty.mkdir(exist_ok=True)
    code, out, err = go(["--root", str(empty)])
    check("K2 CLI: no qa-factory folder -> exit 1, the refusal on stderr names the folder and the door (--root), nothing on stdout", code == 1 and out == "" and "no qa-factory folder" in err and "--root" in err, err)
    real = subprocess.run([sys.executable, "-B", str(SCRIPTS / "collect_pack.py"), "--root", str(empty)], capture_output=True, text=True, encoding="utf-8")
    check("K2 CLI: the script itself, started as a command, refuses the same way (exit 1, no traceback)", real.returncode == 1 and "no qa-factory folder" in real.stderr and "Traceback" not in real.stderr, real.stderr[-300:])
    p, s = BASE / "cli-p.txt", BASE / "cli-s.txt"
    p.write_bytes(("It broke for " + SECRET_NAME + "\n").encode("utf-8"))
    code, out, err = go(["--root", str(P()), "--problems-file", str(p), "--json"])
    a = json.loads(out)
    check_eq("K3 answers: a file with words -> answered; the option left out -> blank (a person who said 'nothing to add' writes no file)", [code, man(a)["answers"]["problems"]["state"], man(a)["answers"]["suggestions"]["state"]], [0, "answered", "blank"])
    code, out, err = go(["--root", str(P()), "--not-asked", "--json"])
    check_eq("K3 answers: --not-asked (nobody to ask) -> not_asked for both; the archive is written all the same", [code, man(json.loads(out))["answers"]["problems"]["state"], man(json.loads(out))["answers"]["suggestions"]["state"]], [0, "not_asked", "not_asked"])
    s.write_bytes(b"  \r\n")
    code, out, err = go(["--root", str(P()), "--suggestions-file", str(s), "--not-asked", "--json"])
    check("K3 answers: a named file with no words is blank even when --not-asked is there", man(json.loads(out))["answers"]["suggestions"]["state"] == "blank")
    for label, raw, want in (("missing", None, "no such file"), ("UTF-16", "words\n".encode("utf-16"), "not UTF-8")):
        f = BASE / ("cli-missing.txt" if raw is None else "cli-utf16.txt")
        if raw is not None:
            f.write_bytes(raw)
        code, out, err = go(["--root", str(P()), "--suggestions-file", str(f)])
        check(f"K4 answers: a {label} answers file -> exit 1, nothing on stdout, the refusal names the file and the option the person's command carries (--suggestions-file), never --words-file, and no story folder",
              code == 1 and out == "" and f.name in err and "--suggestions-file" in err and want in err and "--words-file" not in err and "story folder" not in err, err)
    big = BASE / "cli-big.txt"
    big.write_bytes(b"w" * 101)
    err2 = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err2):
        code = C.main(["--root", str(P()), "--problems-file", str(big)], redactor=text_limited(100), git=NOGIT, temp_root=BASE / "out", rules_sha=M.rules_sha256(), now=NOW)
    check("K4 answers: an answers file over the redactor's text limit -> exit 1 naming the file (the words are never dropped silently)",
          code == 1 and "cli-big.txt" in err2.getvalue() and "not packed" in err2.getvalue(), err2.getvalue())
    inside = P()
    W(inside, "strategy/extra-place/notes.md", "# notes\n")
    code, out, err = go(["--root", str(inside), "--extra", "E=qa-factory/strategy/extra-place", "--json"])
    check("K5 --extra: a place inside the project is packed (set E)", code == 0 and any(r["src_rel"].endswith("notes.md") for r in man(json.loads(out))["files"]), err)
    outside = BASE / "outside-place"
    outside.mkdir(exist_ok=True)
    (outside / "x.md").write_text("x", encoding="utf-8")
    for argv, want in ((["--extra", f"B={outside}"], "outside the project folder"), (["--extra", "B"], "expected SET=path"), (["--extra", "Z=qa-factory"], "is not a set"), (["--extra", "B=nowhere/at-all"], "no such file")):
        code, out, err = go(["--root", str(P()), *argv])
        check(f"K5 --extra {argv[1][:22]!r}: exit 1, an FR-1 refusal that says what is wrong and what to pass", code == 1 and out == "" and want in err, err)
    code, out, err = go(["--root", str(P()), "--since", "install", "--json"])
    check("K6 --since install: everything since the install, window says so", code == 0 and man(json.loads(out))["window"]["since_archive"] == "install")
    code, out, err = go(["--root", str(P()), "--since", "yesterday"])
    check("K6 --since anything else: exit 1, 'install' named", code == 1 and "install" in err)
    # CL1-4 F1 (t-1067): the --extra door is in the OUTPUT the skill's agent reads (the manifest alone is never read by it)
    door = full(P())
    far = door / "elsewhere" / "journal.jsonl"
    far.parent.mkdir()
    far.write_text('{"k":1}\n', encoding="utf-8")
    cfg = json.loads((door / "qa-factory/config.json").read_text(encoding="utf-8"))
    cfg["journal_path"] = "elsewhere/journal.jsonl"
    (door / "qa-factory/config.json").write_text(json.dumps(cfg), encoding="utf-8")
    code, out, err = go(["--root", str(door)])
    lines = out.splitlines()
    check("K7 F1: a journal the config keeps outside qa-factory/ -> the summary prints '<set>: not found at the standard place' with the door --extra B=<path>, within 12 lines, the closing line kept",
          code == 0 and any(x.startswith("B: not found at the standard place (records/journal.jsonl)") and "--extra B=<path inside the project>" in x for x in lines)
          and len(lines) <= 12 and lines[-1].startswith("Send the file"), out)
    mark = door / "qa-factory/state/collect/mark.json"
    first_mark = mark.read_bytes()
    code, out, err = go(["--root", str(door), "--extra", "B=nowhere/at-all"], minutes=5)
    check("K7 F1: a refused re-run does not move the mark (the mark advances only on a successful run)", code == 1 and mark.read_bytes() == first_mark, err)
    code, out, err = go(["--root", str(door), "--extra", "B=elsewhere/journal.jsonl", "--json"], minutes=6)
    again = json.loads(out)
    erow = row(man(again), "extra/B/journal.jsonl")
    check("K7 F1: the re-run with --extra packs the extra place WHOLE (its bytes are in the archive), the door is not printed again for a set given by hand, and the mark moves",
          code == 0 and erow is not None and erow["arc"] and b'"k"' in members(again)[erow["arc"]] and erow["bytes"] > 0 and "unchanged" not in erow["flags"]
          and not any("not found at the standard place (" in x for x in again["summary"]) and mark.read_bytes() != first_mark, str(erow))
    code, out, err = go(["--root", str(door), "--extra", "B=elsewhere/journal.jsonl", "--json"], minutes=7)
    erow = row(man(json.loads(out)), "extra/B/journal.jsonl")
    check("K7 F1: ... and a third run packs it whole again - an extra set is not windowed by the mark ('unchanged' would be a hole in THIS archive)", code == 0 and erow["arc"] and "unchanged" not in erow["flags"], str(erow))
    many = {"bytes": 3_000_000, "archive": "/x/a.zip", "parts": ["/x/a.zip", "/x/a-part2.zip", "/x/a-transcripts.zip"], "transcript_parts": ["a-transcripts.zip"], "files": 9, "unchanged": 1,
            "location": "temp", "reason": "git does not ignore it", "window": {"since_archive": "install"}, "gaps": 4, "skipped": 0, "package_modified": "no",
            "stories": [{"transcripts": [1]}], "extra_doors": [["B", "records/journal.jsonl"], ["C", "c.jsonl"], ["D", "d.jsonl"], ["E", "e.jsonl"]]}
    ls = C.summary_lines(many)
    check("K7 F1 cap: more doors than the 12 lines have room for -> one line still names every set, the closing line stays",
          len(ls) == 12 and ls[-1].startswith("Send the file") and sum("not found at the standard place" in x for x in ls) == 3 and any("C, D, E" in x or "D, E" in x for x in ls), str(ls))
    # CL1-4 F9 / F10: what only the skill's agent sees is a gap line of the manifest
    p2 = BASE / "cli-whole.txt"
    p2.write_bytes("One text for both questions.\n".encode("utf-8"))
    code, out, err = go(["--root", str(P()), "--problems-file", str(p2), "--answers-not-split", "--activity-not-recorded", "--json"])
    flagged = json.loads(out)
    names = [g["what"] for g in man(flagged)["gaps"]]
    check_eq("K8 F10 / F9: an answer that does not split goes whole to the problems answer AND the manifest says 'answers not split; kept whole as problems'; an unrecorded activity is a gap line too",
             (code, "answers not split; kept whole as problems" in names, "the skill's activity was not recorded" in names, man(flagged)["answers"]["problems"]["state"], man(flagged)["answers"]["suggestions"]["state"]),
             (0, True, True, "answered", "blank"))
    code, out, err = go(["--root", str(P()), "--problems-file", str(p2), "--json"])
    names = [g["what"] for g in man(json.loads(out))["gaps"]]
    check("K8 F10 / F9 control: without the options neither line is there", "answers not split; kept whole as problems" not in names and "the skill's activity was not recorded" not in names)


def text_limited(limit):
    import copy
    small = copy.deepcopy(M.load_rules())
    small["limits"]["text_max_bytes"] = limit
    return M.compile_redactor(small, project_root=str(BASE), plugin_root=str(PLUGIN_ROOT), pythons=(sys.executable,), home=HOME_, tmp=tempfile.gettempdir(),
                              identities=IDS, hosts=("stand.corp-zq.example",), secret_values={"STAND_PASSWORD": "Zq7-pass-Word"}, short=lambda p: None)


try:
    reconciliation()
    refusals_and_empty()
    project, _r = first_run()
    tails(project, man(_r)["install_id"])
    ids_and_git()
    project_id_formula()
    install_identity()
    archive_names_and_atomic_write()
    ceilings_and_parts()
    post_check()
    post_check_members()
    never_and_extras()
    answers_and_rules()
    stall_and_transcripts()
    loops_and_transcripts()
    stall_waiting_unreadable_and_config()
    cli()
finally:
    cleanup(BASE)
finish("test_collect_pack")
