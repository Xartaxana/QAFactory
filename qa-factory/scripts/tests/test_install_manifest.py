"""install_paths.py, the manifest half: what the last install wrote, and what a reinstall may do
with it (spec t-232, keys K9, K10, K12 and the edges of section 1).

Run: python -B scripts/tests/test_install_manifest.py
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_paths as I  # noqa: E402

MANIFEST = "qa-factory/install-manifest.json"
TABLE = I.load_table()     # the package table; the plugin_root of a version test is a bare directory
FOLD = False    # explicit: these tests must not depend on the platform's case rule unless they say so


def put(root: Path, rel: str, text: str = "x") -> Path:
    path = root.joinpath(*rel.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw_manifest(root: Path) -> dict:
    return json.loads(root.joinpath(*MANIFEST.split("/")).read_text(encoding="utf-8"))


def write_raw(root: Path, body) -> None:
    path = root.joinpath(*MANIFEST.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))


def plugin_with_version(version) -> Path:
    plugin = temp_dir("qa-plugin-")
    if version is not None:
        (plugin / ".claude-plugin").mkdir()
        (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    return plugin


def entry(rel: str, path: Path | None = None, cls: str = "regenerated", version: str = "0.7.19") -> dict:
    return {"rel_path": rel, "class": cls, "sha256": sha(path) if path else "0" * 64, "package_version": version,
            "input_hash": ""}


def manifest_body(entries: list, version: str = "0.7.19") -> dict:
    return {"schema_version": 1, "package_version": version, "entries": entries}


def symlink_or_none(link: Path, target: Path, directory: bool = False) -> bool:
    try:
        os.symlink(target, link, target_is_directory=directory)
        return True
    except (OSError, NotImplementedError):
        pass
    if directory and sys.platform == "win32":      # a junction needs no privilege
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        return done.returncode == 0
    return False


def section_write_and_verify() -> None:
    root = temp_dir("qa-manifest-")
    try:
        check("ABSENT: read_manifest returns None, not an empty manifest", I.read_manifest(root) is None)
        config = put(root, "qa-factory/config.json", '{"a": 1}\n')
        strategy = put(root, "qa-factory/strategy/test-strategy.md", "# s\n")
        journal = put(root, "qa-factory/state/journal.jsonl", "{}\n")
        res = I.write_manifest(root, ["qa-factory/config.json", "qa-factory/strategy/test-strategy.md",
                                      "qa-factory/state/journal.jsonl", "qa-factory/state/host-probe.json"],
                               input_hash="h1")
        check_eq("write: nothing refused", res["refused"], [])
        check_eq("write: the four paths are listed, sorted",
                 res["written"], sorted(["qa-factory/config.json", "qa-factory/strategy/test-strategy.md",
                                         "qa-factory/state/journal.jsonl", "qa-factory/state/host-probe.json"]))
        raw = raw_manifest(root)
        plugin_json = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        check_eq("K9: package_version == plugin.json", raw["package_version"], plugin_json["version"])
        by = {e["rel_path"]: e for e in raw["entries"]}
        check_eq("K9: every non-machine-local sha256 equals the bytes on disk",
                 {r: by[r]["sha256"] for r in by if "sha256" in by[r]},
                 {"qa-factory/config.json": sha(config), "qa-factory/strategy/test-strategy.md": sha(strategy),
                  "qa-factory/state/journal.jsonl": sha(journal)})
        check("K9: every record carries package_version and input_hash",
              all(e["package_version"] == plugin_json["version"] and e["input_hash"] == "h1" for e in raw["entries"]))
        local = by["qa-factory/state/host-probe.json"]
        check("E3: a machine-local entry carries class and machine_local true",
              local["class"] == "regenerated" and local["machine_local"] is True)
        check("E3: a machine-local entry carries NO sha256 key at all", "sha256" not in local)
        check("no timestamp or absolute path anywhere in the manifest bytes (the equality check compares trees)",
              not any(k in json.dumps(raw) for k in ("written_at", str(root), "T00:", "\\\\")))
        check_eq("verify_manifest: ok on a tree that matches", I.verify_manifest(root)["ok"], True)
        before = (root / "qa-factory" / "install-manifest.json").read_bytes()
        I.write_manifest(root, ["qa-factory/state/host-probe.json", "qa-factory/state/journal.jsonl",
                                "qa-factory/strategy/test-strategy.md", "qa-factory/config.json"], input_hash="h1")
        check("same tree, any entry order -> the same manifest bytes",
              (root / "qa-factory" / "install-manifest.json").read_bytes() == before)
        check("manifest file is LF-only (the file is committed; CRLF would differ by checkout)", b"\r" not in before)
        read = I.read_manifest(root)
        check_eq("read: status ok, not newer", (read["status"], read["newer"], read["reason"]), ("ok", False, None))
        local_read = [e for e in read["entries"] if e["machine_local"]]
        check("read: the machine-local entry is returned without sha256",
              len(local_read) == 1 and "sha256" not in local_read[0])

        config.write_text('{"a": 2}\n', encoding="utf-8")
        ver = I.verify_manifest(root)
        check("K9 negative control: an edited file makes verify_manifest fail and name it",
              not ver["ok"] and [m["rel_path"] for m in ver["mismatches"]] == ["qa-factory/config.json"])
    finally:
        cleanup(root)


def section_write_edges() -> None:
    root = temp_dir("qa-manifest-edges-")
    try:
        put(root, "qa-factory/config.json")
        (root / "qa-factory" / "bugs").mkdir(parents=True)
        put(root, "qa-factory/my-notes.md")
        res = I.write_manifest(root, [
            "qa-factory\\config.json",                       # backslash -> stored with forward slashes
            "qa-factory/config.json",                        # the same path again
            "qa-factory/obligations.md",                     # recognised path, not on disk
            "qa-factory/bugs",                               # a directory is not a file entry
            "qa-factory/my-notes.md",                        # on disk but the table does not know it
            {"rel_path": "qa-factory/my-notes.md", "class": "carried"},    # the caller names the class
        ], casefold=FOLD)
        reasons = {r["rel_path"]: r["reason"] for r in res["refused"]}
        check_eq("backslash path is stored with forward slashes only", res["written"][0], "qa-factory/config.json")
        check("the manifest holds no backslash anywhere", "\\" not in
              root.joinpath(*MANIFEST.split("/")).read_text(encoding="utf-8"))
        check_in("a path listed twice is refused once", "listed twice", reasons.get("qa-factory/config.json", ""))
        check_in("a recognised path that is not on disk is refused (the manifest never lists what was not written)",
                 "not a file on disk", reasons.get("qa-factory/obligations.md", ""))
        check_in("a directory (non machine-local) is refused", "not a file on disk", reasons.get("qa-factory/bugs", ""))
        check_in("an unrecognised path with no class is refused, the table named as the place to add it",
                 "install-paths.json", reasons.get("qa-factory/my-notes.md", ""))
        check_eq("with an explicit class the unrecognised path is written",
                 [e["class"] for e in raw_manifest(root)["entries"] if e["rel_path"] == "qa-factory/my-notes.md"],
                 ["carried"])
        dup = I.write_manifest(root, ["QA-Factory/Config.json", "qa-factory/config.json"], casefold=True)
        # The disk decides which of two spellings is a file: where the file system folds case (Windows,
        # default macOS) the first spelling IS config.json and the second is its duplicate; where it does
        # not (Linux, the CI runner, B-301 g) the first spelling is no file at all, so it is refused as
        # such, is never "seen", and the second spelling is the one and only entry.
        if (root / "QA-Factory" / "Config.json").is_file():
            check_in("case-folded duplicates are one path where the platform folds case", "listed twice",
                     json.dumps(dup["refused"]))
        else:
            check_eq("case-sensitive disk: the other spelling is a different path, no file, refused as that; the real one is written",
                     ([(r["rel_path"], "not a file on disk" in r["reason"]) for r in dup["refused"]], dup["written"]),
                     ([("QA-Factory/Config.json", True)], ["qa-factory/config.json"]))
        check_eq("empty list of entries: a valid empty manifest, nothing refused",
                 (I.write_manifest(root, [])["refused"], raw_manifest(root)["entries"]), ([], []))
    finally:
        cleanup(root)


def section_atomic() -> None:
    root = temp_dir("qa-manifest-atomic-")
    real_replace = os.replace
    try:
        put(root, "qa-factory/config.json")
        I.write_manifest(root, ["qa-factory/config.json"])
        path = root.joinpath(*MANIFEST.split("/"))
        before = path.read_bytes()
        put(root, "qa-factory/factory-backlog.md")

        def boom(src, dst):
            raise OSError("simulated crash before the replace")
        os.replace = boom
        try:
            raised = False
            try:
                I.write_manifest(root, ["qa-factory/config.json", "qa-factory/factory-backlog.md"])
            except OSError:
                raised = True
        finally:
            os.replace = real_replace
        check("atomic: a failing write raises (the caller sees it)", raised)
        check("atomic: the OLD manifest bytes stand after the failed write", path.read_bytes() == before)
        check_eq("atomic: no temp file is left behind", sorted(p.name for p in path.parent.iterdir()
                                                                 if "tmp" in p.name), [])
        fresh = temp_dir("qa-manifest-atomic2-")
        try:
            put(fresh, "qa-factory/config.json")
            os.replace = boom
            try:
                try:
                    I.write_manifest(fresh, ["qa-factory/config.json"])
                except OSError:
                    pass
            finally:
                os.replace = real_replace
            check("atomic: with no prior manifest, a failed write leaves none (never a partial one)",
                  I.read_manifest(fresh) is None)
        finally:
            cleanup(fresh)
    finally:
        os.replace = real_replace
        cleanup(root)


def section_unreadable() -> None:
    root = temp_dir("qa-manifest-bad-")
    try:
        old = put(root, "qa-factory/old-leftover.md", "old\n")
        shapes = {
            "not JSON": b"{ this is not json",
            "a list": b"[]",
            "no entries": json.dumps({"schema_version": 1, "package_version": "0.7.19"}).encode(),
            "entries not a list": json.dumps(manifest_body({})).encode(),
            "newer schema": json.dumps({"schema_version": 2, "package_version": "0.7.19", "entries": []}).encode(),
            "no package_version": json.dumps({"schema_version": 1, "entries": []}).encode(),
            "package_version not a version": json.dumps(manifest_body([], "latest")).encode(),
            "empty file": b"",
        }
        for name, body in shapes.items():
            write_raw(root, body)
            m = I.read_manifest(root)
            check(f"K10: unreadable manifest ({name}) is returned as unknown with a reason, not None",
                  m is not None and m["status"] == "unreadable" and m["reason"] and m["entries"] == [])
        write_raw(root, shapes["not JSON"])
        scan = I.scan_tree(root, casefold=FOLD)
        check_eq("K10: an unreadable manifest retires nothing", scan["retire"], [])
        check_eq("K10: the scan says the manifest is unreadable", scan["manifest"]["status"], "unreadable")
        check_in("FR-1: the reason names what was expected and what to do", "write_manifest", scan["manifest"]["reason"])
        check("the leftover file stays 'not ours, kept' (nothing known about it)",
              "qa-factory/old-leftover.md" in [i["rel_path"] for i in scan["not_ours_kept"]])
        check("and the file is untouched", old.read_text(encoding="utf-8") == "old\n")
        check_eq("a manifest DIRECTORY is unreadable too, never a crash", (
            os.remove(root.joinpath(*MANIFEST.split("/"))), root.joinpath(*MANIFEST.split("/")).mkdir(),
            I.read_manifest(root)["status"])[2], "unreadable")
    finally:
        cleanup(root)


def section_manifest_candidates() -> None:
    root = temp_dir("qa-manifest-cand-")
    try:
        gone = put(root, "qa-factory/old-shape.md", "factory wrote this in 0.7.10\n")
        edited = put(root, "qa-factory/old-edited.md", "factory wrote this\n")
        removed = put(root, "qa-factory/old-removed.md", "will vanish\n")
        carried = put(root, "qa-factory/old-carried.md", "a person's data\n")
        rebuilt = put(root, "qa-factory/state/host-probe.json", "{}\n")
        now = put(root, "qa-factory/old-now-written.md", "rewritten by this run\n")
        entries = [entry("qa-factory/old-shape.md", gone), entry("qa-factory/old-edited.md", edited),
                   entry("qa-factory/old-removed.md", removed), entry("qa-factory/old-carried.md", carried, "carried"),
                   entry("qa-factory/state/host-probe.json", rebuilt), entry("qa-factory/old-now-written.md", now)]
        write_raw(root, manifest_body(entries))
        edited.write_text("a person edited this\n", encoding="utf-8")
        removed.unlink()
        scan = I.scan_tree(root, ["qa-factory/old-now-written.md"], casefold=FOLD)
        retire = {i["rel_path"]: i for i in scan["retire"]}
        check_eq("manifest present: an entry not written this run, bytes intact, is a retire CANDIDATE (returned)",
                 sorted(retire), ["qa-factory/old-shape.md"])
        check_eq("the candidate says the manifest named it", retire["qa-factory/old-shape.md"]["source"], "manifest")
        check_eq("K10: an edited path is listed as changed_since_install",
                 [(c["rel_path"], c["written"]) for c in scan["changed_since_install"]],
                 [("qa-factory/old-edited.md", False)])
        changed = scan["changed_since_install"]
        check("K10: ...with both shas, and it is NOT in retire",
              bool(changed) and changed[0]["expected_sha256"] != changed[0]["actual_sha256"]
              and "qa-factory/old-edited.md" not in retire)
        check("K10: ...and not double-listed as 'not ours'",
              "qa-factory/old-edited.md" not in [i["rel_path"] for i in scan["not_ours_kept"]])
        check_eq("a manifest entry whose file is gone is reported missing, nothing to retire",
                 scan["missing"], ["qa-factory/old-removed.md"])
        check("a carried entry is never retired, whatever the manifest says", "qa-factory/old-carried.md" not in retire)
        check("a path the table says is regenerated (a reader rebuilds it) is not retired on the manifest's word",
              "qa-factory/state/host-probe.json" not in retire)
        check("a path this run writes is never retired", "qa-factory/old-now-written.md" not in retire)
        check("scan_tree deleted nothing", all(p.exists() for p in (gone, edited, carried, rebuilt, now)))
        # a table row and the manifest naming the same file: the changed bytes win (no sha in the table)
        passport = put(root, "qa-factory/strategy/product-passport.md", "passport v1\n")
        write_raw(root, manifest_body(entries + [entry("qa-factory/strategy/product-passport.md", passport)]))
        scan = I.scan_tree(root, casefold=FOLD)
        check("table says discarded, manifest says untouched -> one retire item from both",
              [i["source"] for i in scan["retire"] if i["rel_path"].endswith("product-passport.md")] == ["table+manifest"])
        passport.write_text("passport v1 + a person's paragraph\n", encoding="utf-8")
        scan = I.scan_tree(root, casefold=FOLD)
        check("table says discarded but the manifest sha differs -> kept, listed as changed (bytes the factory did not write)",
              "qa-factory/strategy/product-passport.md" not in [i["rel_path"] for i in scan["retire"]]
              and "qa-factory/strategy/product-passport.md" in [c["rel_path"] for c in scan["changed_since_install"]])
    finally:
        cleanup(root)


def section_newer() -> None:
    root = temp_dir("qa-manifest-newer-")
    older = plugin_with_version("0.7.5")
    same = plugin_with_version("0.7.19")
    bare = plugin_with_version(None)
    try:
        leftover = put(root, "qa-factory/old-shape.md", "x\n")
        put(root, "qa-factory/state/jira-probe-1.json", "{}\n")
        write_raw(root, manifest_body([entry("qa-factory/old-shape.md", leftover)], "0.7.19"))
        m = I.read_manifest(root, plugin_root=older)
        check_eq("E2: a manifest of a NEWER package than plugin.json is flagged newer", m["newer"], True)
        check_eq("E2: and says which versions", (m["package_version"], m["plugin_version"]), ("0.7.19", "0.7.5"))
        scan = I.scan_tree(root, plugin_root=older, table=TABLE, casefold=FOLD)
        check_eq("E2: newer -> retire is empty, even for a table-discarded file", scan["retire"], [])
        check_eq("E2: the block is named", scan["retire_blocked"], "newer_manifest")
        check("E2: the withheld candidates stay visible (unknown), with the reason in plain words",
              {u["rel_path"] for u in scan["unknown"]} >= {"qa-factory/old-shape.md", "qa-factory/state/jira-probe-1.json"}
              and "update the plugin" in scan["unknown"][0]["reason"])
        m = I.read_manifest(root, plugin_root=same)
        check_eq("same version: not newer", m["newer"], False)
        check_eq("same version: retirement allowed", len(I.scan_tree(root, plugin_root=same, table=TABLE, casefold=FOLD)["retire"]), 2)
        write_raw(root, manifest_body([entry("qa-factory/old-shape.md", leftover, version="0.8.0")], "0.7.19"))
        check_eq("one entry from a newer package is enough", I.read_manifest(root, plugin_root=same)["newer"], True)
        write_raw(root, manifest_body([entry("qa-factory/old-shape.md", leftover)], "0.7.100"))
        check_eq("versions compare as numbers, not text (0.7.100 > 0.7.19)",
                 I.read_manifest(root, plugin_root=same)["newer"], True)
        write_raw(root, manifest_body([entry("qa-factory/old-shape.md", leftover)], "0.7.2"))
        check_eq("...and 0.7.2 < 0.7.19", I.read_manifest(root, plugin_root=same)["newer"], False)
        m = I.read_manifest(root, plugin_root=bare)
        check_eq("FR-41: plugin.json unreadable -> newer is None (unknown), never False", m["newer"], None)
        check_eq("FR-41: unknown newer-ness retires nothing",
                 (I.scan_tree(root, plugin_root=bare, table=TABLE, casefold=FOLD)["retire"],
                  I.scan_tree(root, plugin_root=bare, table=TABLE, casefold=FOLD)["retire_blocked"]), ([], "plugin_version_unknown"))
    finally:
        for p in (root, older, same, bare):
            cleanup(p)


def section_adversarial() -> None:
    base = temp_dir("qa-manifest-adv-")
    root = base / "project"
    root.mkdir()
    try:
        sentinel = base / "sentinel.txt"
        sentinel.write_text("outside the project\n", encoding="utf-8")
        before = (sha(sentinel), sentinel.stat().st_mtime_ns)
        inside = put(root, "qa-factory/old-shape.md", "inside\n")
        link_made = symlink_or_none(root / "qa-factory" / "link.txt", sentinel)
        dir_link_made = symlink_or_none(root / "qa-factory" / "linkdir", base, directory=True)
        bad = ["../sentinel.txt", "qa-factory/../../sentinel.txt", str(sentinel), str(sentinel).replace("\\", "/"),
               "C:\\x", "C:/x", "C:x", "/etc/x", "\\\\srv\\share\\x", "..\\sentinel.txt", ".. /sentinel.txt",
               "qa-factory/a:stream", "", "   ", "qa-factory/x\x00y", "./../sentinel.txt"]
        if link_made:
            bad.append("qa-factory/link.txt")
        if dir_link_made:
            bad.append("qa-factory/linkdir/sentinel.txt")
        # a manifest naming every one of them with the sentinel's REAL sha: a reader that followed
        # the path would find a match and offer the file for retirement
        raw_entries = [entry(p, sentinel) for p in bad] + [entry("qa-factory/old-shape.md", inside)]
        write_raw(root, manifest_body(raw_entries))
        m = I.read_manifest(root)
        check_eq("K12: every adversarial entry is refused on read", len(m["refused"]), len(bad))
        check_eq("K12: only the honest entry is returned", [e["rel_path"] for e in m["entries"]], ["qa-factory/old-shape.md"])
        check("K12: every refusal carries a reason", all(r["reason"] for r in m["refused"]))
        scan = I.scan_tree(root, casefold=FOLD)
        check_eq("K12: scan retires only the honest entry", [i["rel_path"] for i in scan["retire"]], ["qa-factory/old-shape.md"])
        check("K12: scan lists the refusals", len(scan["refused"]) >= len(bad))
        check_eq("K12: sentinel sha and mtime unchanged after read and scan", (sha(sentinel), sentinel.stat().st_mtime_ns), before)
        check("K12: nothing in the scan's retire/changed lists names a path outside the root",
              all(".." not in i["rel_path"] and not i["rel_path"].startswith("/") for i in scan["retire"] + scan["changed_since_install"]))
        wrote = I.write_manifest(root, bad + [{"rel_path": "qa-factory/old-shape.md", "class": "regenerated"}], casefold=FOLD)
        check_eq("K12: write_manifest refuses them all too, lists them, writes the honest one",
                 (len(wrote["refused"]), wrote["written"]), (len(bad), ["qa-factory/old-shape.md"]))
        check("K12: ...and the written manifest holds no sha of the sentinel", sha(sentinel) not in
              root.joinpath(*MANIFEST.split("/")).read_text(encoding="utf-8"))
        local = I.write_manifest(root, [{"rel_path": "qa-factory/state/host-probe.json", "machine_local": True},
                                        {"rel_path": "qa-factory/linkdir/x.json", "class": "regenerated", "machine_local": True},
                                        {"rel_path": "../x.json", "class": "regenerated", "machine_local": True}], casefold=FOLD)
        check("K12: machine-local entries are checked for escape as well (no sha does not mean no check)",
              "../x.json" in [r["rel_path"] for r in local["refused"]]
              and (not dir_link_made or "qa-factory/linkdir/x.json" in [r["rel_path"] for r in local["refused"]]))
        check_eq("K12: sentinel still unchanged at the end", (sha(sentinel), sentinel.stat().st_mtime_ns), before)
        if not (link_made and dir_link_made):
            print("SKIP symlink/junction cases: this machine cannot create "
                  f"{'a file symlink' if not link_made else ''} {'a directory link' if not dir_link_made else ''}")
        # the walk meets a link out of the root with no manifest at all
        write_raw(root, b"")
        os.remove(root.joinpath(*MANIFEST.split("/")))
        walk = I.scan_tree(root, casefold=FOLD)
        if dir_link_made:
            check("K12: the walk does not descend a link that leaves the root, and lists it as refused",
                  "qa-factory/linkdir" in [r["rel_path"] for r in walk["refused"]]
                  and not any(i["rel_path"].startswith("qa-factory/linkdir/") for i in walk["not_ours_kept"]))
    finally:
        cleanup(base)


def section_normalisation() -> None:
    cases = {
        "qa-factory/state/x.json": "qa-factory/state/x.json",
        "qa-factory\\state\\x.json": "qa-factory/state/x.json",
        ".\\qa-factory//state/./x.json": "qa-factory/state/x.json",
        "qa-factory/state/": "qa-factory/state",
        "Qa-Factory\\State\\X.JSON": "Qa-Factory/State/X.JSON",     # case is kept; matching folds it where the platform does
    }
    for given, want in cases.items():
        check_eq(f"normalize_rel({given!r})", I.normalize_rel(given), (want, None))
    for bad in ("../x", "a/../../x", "/etc/x", "\\x", "C:\\x", "D:x", "\\\\srv\\s", "", "  ", ".", "a/.. /b", "a/...", "x\x01y", 5, None):
        rel, why = I.normalize_rel(bad)
        check(f"normalize_rel refuses {bad!r}", rel is None and bool(why))
    root = temp_dir("qa-manifest-norm-")
    try:
        put(root, "qa-factory/state/journal.jsonl")
        scan_fold = I.scan_tree(root, ["QA-Factory\\State\\Journal.jsonl"], casefold=True)
        check("Windows rule: a mixed-case, backslash `written` path matches the file it names (nothing refused)",
              scan_fold["refused"] == [])
    finally:
        cleanup(root)


def section_empty() -> None:
    root = temp_dir("qa-manifest-empty-")
    try:
        want = {"retire": [], "changed_since_install": [], "not_ours_kept": [], "locks": [], "unknown": [], "missing": [], "refused": []}
        scan = I.scan_tree(root, casefold=FOLD)
        check_eq("empty project root: every list empty", {k: scan[k] for k in want}, want)
        check_eq("empty project root: manifest absent, retire not blocked", (scan["manifest"]["status"], scan["retire_blocked"]), ("absent", None))
        scan = I.scan_tree(root / "no-such-dir", casefold=FOLD)
        check_eq("a root that does not exist: every list empty, no error", {k: scan[k] for k in want}, want)
        check_eq("verify_manifest on a project with no manifest: absent, not ok", (I.verify_manifest(root)["status"], I.verify_manifest(root)["ok"]),
                 ("absent", False))
        check_eq("an empty manifest (zero entries) reads as ok with no entries",
                 (I.write_manifest(root, [])["written"], I.read_manifest(root)["entries"]), ([], []))
    finally:
        cleanup(root)


def main() -> None:
    section_write_and_verify()
    section_write_edges()
    section_atomic()
    section_unreadable()
    section_manifest_candidates()
    section_newer()
    section_adversarial()
    section_normalisation()
    section_empty()
    finish("install manifest")


if __name__ == "__main__":
    main()
