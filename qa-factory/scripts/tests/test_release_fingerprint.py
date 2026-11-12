#!/usr/bin/env python3
"""CL1-8 (collect/1, t-994 with section L-2): ONE recipe of the package fingerprint, a release file, `package_modified`.

What this file proves (expectations come from the spec's own sections 1, 4, 5 and L-2, not from the code under test; the HEAD
recipe frozen below is the I3 requirement itself - a stored fingerprint must keep its meaning):
  K1   the aggregate equals HEAD's recipe on a fixture with a CRLF `run-py.cmd`, a `tests` part, `design/`, `handoffs/`;
  K2   on the real package the four readers agree (install_smoke, resolve_runtime, the recipe, the frozen HEAD recipe);
  K3   a reader that keeps a copy of the recipe is caught: both readers follow the module attribute;
  K4   the release file is excluded from the walk and the aggregate; K13 and from the map, whatever it lists about itself;
  K5   --write then compare = no / match, twice = the same bytes; K6/K7 every doubt row; K8 a proven difference is named;
  K9   what never accuses (tests, design, handoffs, other suffixes, bytecode, litter); K10 mtime is never read;
  K11  CRLF alone is invisible, a lone CR is not; K12 a doubt beats a proven difference; K14 the CLI exit codes and refusals;
  K15  the shape of compare(); K16 the harness reports a planted failure (child process, exactly one FAIL line);
  K17  --write and --check refuse an untracked, ignored, intent-to-add or unstaged-edited recipe file in a git clone (I1: the
       working tree is not the commit), and a failed git listing (F3); a map never holds a litter-named path (F2); the
       version refusal says N.N.N (F4);
  K18  `install` says cache or frozen; K19 the before-world and the edges (empty folder, unreadable walk);
  K20  the survivor's other readers (collect/2, CL2-1): the host probe's fingerprint is the survivor's aggregate plus the project's
       config (unreadable -> `unknown:<why>:<nonce>`, never a hash), and factory_manifest's map is `file_digests` (a stamp of
       another recipe or over an unreadable tree is one line / a refusal, never a pass).
"""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import factory_manifest as FM  # noqa: E402
import host_probe  # noqa: E402
import install_smoke  # noqa: E402
import release_fingerprint as RF  # noqa: E402
import runtime_paths  # noqa: E402

CLEAN: list = []
harness_read = RF._read_bytes   # the survivor's own read, put back after a test replaced the seam
_HEX = re.compile(r"[0-9a-f]{64}")
REL = "references/release-fingerprint.json"
KEYS = {"package_modified", "why", "recipe", "release_version", "running_version", "changed", "added", "removed",
        "unreadable", "litter", "install"}
FILES = {
    ".claude-plugin/plugin.json": b'{"version":"9.9.9"}',
    "scripts/a.py": b"x = 1\nprint(x)\n",
    "scripts/tests/t.py": b"# a test\n",
    "references/x.json": b'{"k": 1}\n',
    "references/slices/r/s.md": b"# slice\n",
    "skills/k/SKILL.md": b"# skill\n",
    "hooks/run-py.cmd": b"@echo off\r\npython %*\r\n",
    "design/d.md": b"# design\n",
    "handoffs/h.yaml": b"a: 1\n",
    "agents/q.md": b"",
}


def scratch() -> Path:
    base = temp_dir("qa-rf-").resolve()
    CLEAN.append(base)
    return base


def make_tree(base: Path) -> Path:
    """The fixture T: bytes written raw, so the CRLF of run-py.cmd stays a CRLF."""
    for rel, data in FILES.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return base


def head_fingerprint(root: Path, skip_release: bool = False) -> str:
    """HEAD's recipe, copied verbatim from install_smoke.package_fingerprint before the fold (the oracle of K1/K2)."""
    manifest = root / ".claude-plugin" / "plugin.json"
    digest = hashlib.sha256(manifest.read_bytes() if manifest.is_file() else b"")
    files = [path for folder in ("scripts", "references", "agents", "skills", "hooks")
             for path in (root / folder).rglob("*")
             if path.is_file() and path.suffix in {".py", ".json", ".md", ".cmd", ".sh"}
             and "tests" not in path.relative_to(root).parts
             and not (skip_release and path.relative_to(root).as_posix() == REL)]
    for path in sorted(files, key=lambda item: item.as_posix()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def quiet(function, *args, **kwargs):
    """(result, stdout, stderr) of a call; the CLI and the writer print."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        result = function(*args, **kwargs)
    return result, out.getvalue(), err.getvalue()


def released() -> Path:
    """A fresh tree with a release file written from it (not a git clone: one warning line on stderr)."""
    base = make_tree(scratch())
    quiet(RF.write_release, base)
    return base


def verdict(base: Path):
    result = RF.compare(base)
    return result["package_modified"], result["why"]


def edit_release(base: Path, mutate) -> None:
    path = base / REL
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def git(base: Path, *args) -> None:
    subprocess.run(["git", "-C", str(base), *args], capture_output=True, check=True, timeout=60)


def temp_project_task():
    project = harness.temp_project()
    CLEAN.append(project)
    task = project / "qa-factory" / "state" / "task-1"
    task.mkdir(parents=True)
    return project, task


# --- K1, K2, K3, K4 -------------------------------------------------------------------------------------------------

def k1_aggregate_is_heads() -> None:
    base = make_tree(scratch())
    check_eq("K1 the aggregate of the fixture (CRLF run-py.cmd, tests part, design/, handoffs/) equals HEAD's recipe",
             RF.package_fingerprint(base), head_fingerprint(base))
    check_eq("K1 the recipe walk skips the `tests` part",
             [p.relative_to(base).as_posix() for p in RF.recipe_files(base)],
             ["agents/q.md", "hooks/run-py.cmd", "references/slices/r/s.md", "references/x.json", "scripts/a.py", "skills/k/SKILL.md"])
    check_eq("K1 the aggregate without a plugin.json is HEAD's value too (b'' for the manifest)",
             RF.package_fingerprint(scratch()), hashlib.sha256(b"").hexdigest())
    # SC1-12 (t-1332): `files=` hands the walk the caller already made; None is the old walk, byte for byte
    listed = RF.recipe_files(base)
    check_eq("K1 files=None is the old walk (the value is HEAD's)", RF.package_fingerprint(base, None), head_fingerprint(base))
    check_eq("K1 files=<the walk's own list> gives the same value", RF.package_fingerprint(base, files=listed), head_fingerprint(base))
    walks = []
    original_walk = RF.recipe_files
    RF.recipe_files = lambda root=None: walks.append(root) or original_walk(root)
    try:
        RF.package_fingerprint(base, files=listed)
        walked_with_list = len(walks)
        RF.package_fingerprint(base)
    finally:
        RF.recipe_files = original_walk
    check_eq("K1 a given list is not walked again", walked_with_list, 0)
    check_eq("K1 without a list the tree is walked exactly once", len(walks), 1)


def k2_k3_readers() -> None:
    project, task = temp_project_task()
    real = harness.PLUGIN_ROOT
    runtime = runtime_paths.resolve_runtime(task, project)["package_fingerprint"]
    values = {"install_smoke": install_smoke.package_fingerprint(), "resolve_runtime": runtime,
              "recipe": RF.package_fingerprint(real), "HEAD recipe": head_fingerprint(real, skip_release=True)}
    check("K2 on the real package the four values are one", len(set(values.values())) == 1, str(values))
    original = RF.package_fingerprint
    RF.package_fingerprint = lambda root=None, files=None: "SENTINEL"
    try:
        smoke = install_smoke.package_fingerprint()
        bound = runtime_paths.resolve_runtime(task, project)["package_fingerprint"]
    finally:
        RF.package_fingerprint = original
    check_eq("K3 install_smoke follows the module attribute", smoke, "SENTINEL")
    check_eq("K3 resolve_runtime follows the module attribute", bound, "SENTINEL")
    check("K3 after the patch both readers are back on the real value",
          install_smoke.package_fingerprint() == values["recipe"])


def k4_release_file_is_outside() -> None:
    base = make_tree(scratch())
    before = RF.package_fingerprint(base)
    (base / REL).write_text(json.dumps({"anything": 1}), encoding="utf-8")
    check_eq("K4 a release file does not move the aggregate", RF.package_fingerprint(base), before)
    check_eq("K4 the aggregate with a release file is HEAD's recipe minus that file", before, head_fingerprint(base, skip_release=True))
    check("K4 the walk lists no release-fingerprint.json",
          not [p for p in RF.recipe_files(base) if p.name == "release-fingerprint.json"])
    check("K4 the map has no entry for it", REL not in RF.file_digests(base))


# --- K5, K6, K7 ---------------------------------------------------------------------------------------------------

def k5_write_then_compare() -> None:
    base = make_tree(scratch())
    data, _, err = quiet(RF.write_release, base)
    check_eq("K5 the written file: schema, recipe, version, note and NO aggregate",
             {key: data[key] for key in ("schema", "recipe", "package_version")}, {"schema": 1, "recipe": RF.RECIPE_ID, "package_version": "9.9.9"})
    check("K5 the file carries no package_fingerprint field (the verdict is the map's)", "package_fingerprint" not in data)
    check_eq("K5 the map holds the manifest and every recipe file, tests/design/handoffs out",
             sorted(data["files"]), [".claude-plugin/plugin.json", "agents/q.md", "hooks/run-py.cmd", "references/slices/r/s.md",
                                     "references/x.json", "scripts/a.py", "skills/k/SKILL.md"])
    check_eq("K5 the written file is read back as what write_release returned", json.loads((base / REL).read_text(encoding="utf-8")), data)
    check("K5 not a git clone: exactly one warning line, no refusal", err.count("\n") == 1 and "warning" in err, err)
    check_eq("K5 compare after --write", verdict(base), ("no", "match"))
    first = (base / REL).read_bytes()
    quiet(RF.write_release, base)
    check_eq("K5 --write twice gives identical bytes", (base / REL).read_bytes(), first)
    check_eq("K5 the digest is of the LF-normalised bytes (the CRLF cmd file)",
             data["files"]["hooks/run-py.cmd"], hashlib.sha256(b"@echo off\npython %*\n").hexdigest())


def k6_release_file_rows() -> None:
    base = make_tree(scratch())
    check_eq("K6 row 2: no release file", verdict(base), ("unknown", "no_release_file"))
    def bad_key(key):
        return lambda b: edit_release(b, lambda d: d["files"].update({key: "0" * 64}))

    cases = [
        ("row 3: not UTF-8", lambda b: (b / REL).write_bytes(b"\xff"), "release_file_unreadable"),
        ("row 3: a JSON list", lambda b: (b / REL).write_text("[]", encoding="utf-8"), "release_file_unreadable"),
        ("row 3: not JSON", lambda b: (b / REL).write_text("{", encoding="utf-8"), "release_file_unreadable"),
        ("row 3: a folder where the file should be", lambda b: ((b / REL).unlink(), (b / REL).mkdir()), "release_file_unreadable"),
        ("row 4: schema 2", lambda b: edit_release(b, lambda d: d.update(schema=2)), "release_file_invalid"),
        ("row 4: schema true (a bool is not 1)", lambda b: edit_release(b, lambda d: d.update(schema=True)), "release_file_invalid"),
        ("row 4: files {}", lambda b: edit_release(b, lambda d: d.update(files={})), "release_file_invalid"),
        ("row 4: files only lists the release file itself", lambda b: edit_release(b, lambda d: d.update(files={REL: "0" * 64})), "release_file_invalid"),
        ("row 4: files is a list", lambda b: edit_release(b, lambda d: d.update(files=[])), "release_file_invalid"),
        ("row 4: a 63-hex digest", lambda b: edit_release(b, lambda d: d["files"].update({"scripts/a.py": "a" * 63})), "release_file_invalid"),
        ("row 4: a 65-hex digest", lambda b: edit_release(b, lambda d: d["files"].update({"scripts/a.py": "a" * 65})), "release_file_invalid"),
        ("row 4: an upper-case digest", lambda b: edit_release(b, lambda d: d["files"].update({"scripts/a.py": "A" * 64})), "release_file_invalid"),
        ("row 4: a digest that is not a string", lambda b: edit_release(b, lambda d: d["files"].update({"scripts/a.py": 7})), "release_file_invalid"),
        ("row 4: package_version empty", lambda b: edit_release(b, lambda d: d.update(package_version="")), "release_file_invalid"),
        ("row 4: package_version missing", lambda b: edit_release(b, lambda d: d.pop("package_version")), "release_file_invalid"),
        ("row 4: recipe missing", lambda b: edit_release(b, lambda d: d.pop("recipe")), "release_file_invalid"),
        ("row 4: a key outside the folders", bad_key("design/d.md"), "release_file_invalid"),
        ("row 4: a key with a tests part", bad_key("scripts/tests/t.py"), "release_file_invalid"),
        ("row 4: a key with ..", bad_key("scripts/../x.md"), "release_file_invalid"),
        ("row 4: an absolute key", bad_key("/etc/passwd.md"), "release_file_invalid"),
        ("row 4: a backslash key", bad_key("scripts\\a.py"), "release_file_invalid"),
        ("row 4: a suffix the recipe lacks", bad_key("scripts/a.txt"), "release_file_invalid"),
        ("row 4: a drive-letter key", bad_key("C:/x/a.py"), "release_file_invalid"),
        ("row 5: another recipe", lambda b: edit_release(b, lambda d: d.update(recipe="x/2")), "recipe_mismatch"),
    ]
    for label, mutate, why in cases:
        tree = released()
        mutate(tree)
        check_eq("K6 " + label, verdict(tree), ("unknown", why))
    tree = released()
    (tree / "scripts" / "a.py").write_bytes(b"changed\n")
    (tree / REL).write_bytes(b"\xff")
    check_eq("K6 a damaged release file never turns a changed tree into `yes`", verdict(tree), ("unknown", "release_file_unreadable"))


def k7_version_rows() -> None:
    tree = released()
    (tree / ".claude-plugin" / "plugin.json").unlink()
    check_eq("K7 row 6: no plugin.json", verdict(tree), ("unknown", "version_unknown"))
    tree = released()
    (tree / ".claude-plugin" / "plugin.json").write_bytes(b'{"version":""}')
    check_eq("K7 row 6: version empty", verdict(tree), ("unknown", "version_unknown"))
    tree = released()
    edit_release(tree, lambda d: d.update(package_version="9.9.8"))
    check_eq("K7 row 7: the file belongs to 9.9.8", verdict(tree), ("unknown", "version_mismatch"))
    result = RF.compare(tree)
    check_eq("K7 both versions are reported", (result["release_version"], result["running_version"]), ("9.9.8", "9.9.9"))


# --- K8 .. K13 ----------------------------------------------------------------------------------------------------

def k8_proven_difference() -> None:
    tree = released()
    (tree / "scripts" / "a.py").write_bytes(b"x = 2\nprint(x)\n")
    (tree / "agents" / "q.md").unlink()
    (tree / "skills" / "k" / "new.md").write_bytes(b"# new\n")
    result = RF.compare(tree)
    check_eq("K8 yes / differs", (result["package_modified"], result["why"]), ("yes", "differs"))
    check_eq("K8 the lists name each file",
             (result["changed"], result["removed"], result["added"]), (["scripts/a.py"], ["agents/q.md"], ["skills/k/new.md"]))
    tree = released()
    (tree / "agents" / "q.md").write_bytes(b"x")
    check_eq("K8 a 0-byte file that gained a byte", verdict(tree), ("yes", "differs"))
    tree = released()
    (tree / "scripts" / "a.py").write_bytes(b"")
    check_eq("K8 a file truncated to 0 bytes", verdict(tree), ("yes", "differs"))
    tree = released()
    (tree / ".claude-plugin" / "plugin.json").write_bytes(b'{"version":"9.9.9","x":1}')
    check_eq("K8 the manifest is in the map", RF.compare(tree)["changed"], [".claude-plugin/plugin.json"])
    tree = released()
    (tree / "skills" / "k" / "SKILL.md").rename(tree / "skills" / "k" / "skill.md")
    result = RF.compare(tree)
    check_eq("K8 case rename = removed + added (the directory listing carries the new spelling on every volume)",
             (result["removed"], result["added"]), (["skills/k/SKILL.md"], ["skills/k/skill.md"]))


def k9_never_accuses() -> None:
    tree = released()
    (tree / "scripts" / "tests" / "t.py").write_bytes(b"# changed\n")
    (tree / "design" / "d.md").write_bytes(b"# changed\n")
    (tree / "handoffs" / "h.yaml").write_bytes(b"a: 2\n")
    (tree / "scripts" / "a.py.bak").write_bytes(b"old")
    (tree / "scripts" / "notes.txt").write_bytes(b"old")
    (tree / "scripts" / "__pycache__").mkdir()
    (tree / "scripts" / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"\x00\x01")
    result = RF.compare(tree)
    check_eq("K9 tests, design, handoffs, other suffixes and bytecode are invisible", (result["package_modified"], result["why"]), ("no", "match"))
    check_eq("K9 ...and not even litter", result["litter"], [])
    tree = released()
    for rel in ("scripts/.pytest_cache/README.md", "skills/k/._x.md", "skills/k/~$y.md"):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_bytes(b"litter")
    result = RF.compare(tree)
    check_eq("K9 recipe-suffixed litter goes to litter[], never to `yes`", (result["package_modified"], result["added"]), ("no", []))
    check_eq("K9 litter is listed", result["litter"], ["scripts/.pytest_cache/README.md", "skills/k/._x.md", "skills/k/~$y.md"])
    (tree / "scripts" / "a.py").write_bytes(b"real change\n")
    result = RF.compare(tree)
    check_eq("K9 a real change next to litter is still `yes`, litter apart", (result["package_modified"], result["changed"], len(result["litter"])),
             ("yes", ["scripts/a.py"], 3))


def k10_mtime_is_never_read() -> None:
    tree = released()
    for path in tree.rglob("*"):
        if path.is_file():
            os.utime(path, (1_000_000_000, 1_000_000_000))
    check_eq("K10 every file touched, same bytes", verdict(tree), ("no", "match"))
    before = RF.package_fingerprint(tree)
    for path in tree.rglob("*"):
        if path.is_file():
            os.utime(path, (1_500_000_000, 1_500_000_000))
    check_eq("K10 the aggregate does not move with mtime either", RF.package_fingerprint(tree), before)


def k11_line_endings() -> None:
    tree = released()
    (tree / "scripts" / "a.py").write_bytes(b"x = 1\r\nprint(x)\r\n")
    check_eq("K11 LF -> CRLF alone is `no`", verdict(tree), ("no", "match"))
    (tree / "scripts" / "a.py").write_bytes(b"x = 1\rprint(x)\n")
    check_eq("K11 a lone CR is a byte difference: `yes`", verdict(tree), ("yes", "differs"))
    (tree / "scripts" / "a.py").write_bytes(b"x = 1\r\r\nprint(x)\n")
    check_eq("K11 CR CR LF is not a plain CRLF: `yes`", verdict(tree), ("yes", "differs"))


def k12_doubt_before_difference() -> None:
    tree = released()
    (tree / "scripts" / "a.py").write_bytes(b"changed\n")
    edit_release(tree, lambda d: d.update(package_version="9.9.8"))
    check_eq("K12 a changed byte AND a version mismatch", verdict(tree), ("unknown", "version_mismatch"))
    tree = released()
    (tree / "scripts" / "a.py").write_bytes(b"changed\n")
    original = RF._read_bytes

    def failing(path):
        if Path(path).name == "x.json":
            raise PermissionError("seam: unreadable")
        return original(path)

    RF._read_bytes = failing
    try:
        result = RF.compare(tree)
    finally:
        RF._read_bytes = original
    check_eq("K12 a changed byte AND a read error", (result["package_modified"], result["why"]), ("unknown", "package_unreadable"))
    check_eq("K12 the unreadable file is named, the verdict lists stay empty",
             (result["unreadable"], result["changed"]), (["references/x.json"], []))


def k13_self_listing_file() -> None:
    tree = released()
    edit_release(tree, lambda d: d["files"].update({REL: "0" * 64}))
    check_eq("K13 the file lists its own path with a wrong digest", verdict(tree), ("no", "match"))
    edit_release(tree, lambda d: d["files"].update({REL: "not a digest"}))
    check_eq("K13 ...or with a value that is no digest at all", verdict(tree), ("no", "match"))


# --- K14, K15, K16 ------------------------------------------------------------------------------------------------

def k14_cli() -> None:
    tree = released()
    code, out, _ = quiet(RF.main, ["--check"], root=tree)
    check_eq("K14 --check on a matching tree: exit 0", code, 0)
    check_in("K14 ...and it says ok", "ok", out)
    (tree / "scripts" / "a.py").write_bytes(b"changed\n")
    code, out, _ = quiet(RF.main, ["--check"], root=tree)
    check_eq("K14 --check on a changed tree: exit 1", code, 1)
    check_in("K14 ...naming the file and the door", "changed: scripts/a.py", out)
    check_in("K14 ...the door is --write", "--write", out)
    tree = make_tree(scratch())
    code, out, _ = quiet(RF.main, ["--check"], root=tree)
    check_eq("K14 --check with no release file: exit 2", code, 2)
    check_in("K14 ...naming the why", "no_release_file", out)
    code, out, _ = quiet(RF.main, ["--json"], root=tree)
    check_eq("K14 --json prints compare() and exits 0", (code, json.loads(out)["why"]), (0, "no_release_file"))
    code, out, _ = quiet(RF.main, [], root=tree)
    check_eq("K14 json is the default", (code, json.loads(out)["package_modified"]), (0, "unknown"))
    code, out, err = quiet(RF.main, ["--write"], root=tree)
    check_eq("K14 --write on a tree: exit 0", code, 0)
    check_eq("K14 ...then --check agrees", quiet(RF.main, ["--check"], root=tree)[0], 0)
    bare = scratch()
    (bare / "scripts").mkdir()
    code, out, err = quiet(RF.main, ["--write"], root=bare)
    check_eq("K14 --write without a version: exit 2", code, 2)
    check("K14 ...stderr names what is wrong, what is expected and the door",
          "no version of the form N.N.N in .claude-plugin/plugin.json" in err and "expected" in err and "package root" in err, err)
    check("K14 ...and writes nothing", not (bare / REL).exists())
    process = harness.run_script("release_fingerprint.py", "--json")
    keys = set(json.loads(process.stdout)) if process.returncode == 0 else None
    check_eq("K14 the real CLI prints the compare() keys on stdout and nothing else", keys, KEYS)


def k15_compare_shape() -> None:
    trees = {"no file": make_tree(scratch()), "match": released(), "differs": released(), "unknown version": released()}
    (trees["differs"] / "scripts" / "a.py").write_bytes(b"changed\n")
    edit_release(trees["unknown version"], lambda d: d.update(package_version="1.0.0"))
    for label, tree in trees.items():
        result = RF.compare(tree)
        check_eq(f"K15 compare() keys ({label})", set(result), KEYS)
        check(f"K15 compare() is JSON-serialisable and every `unknown` carries a why ({label})",
              bool(json.dumps(result)) and (result["package_modified"] != "unknown" or bool(result["why"])))
        check(f"K15 the verdict is one of three words ({label})", result["package_modified"] in ("yes", "no", "unknown"))
    check_eq("K15 compare() writes nothing (FR-45)", sorted(p.name for p in (trees["no file"] / "references").iterdir()), ["slices", "x.json"])


def k16_planted_failure_is_reported() -> None:
    scratch_dir = scratch()
    child = scratch_dir / "planted.py"
    child.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
        "import harness\n"
        "import test_release_fingerprint as T\n"
        "base = T.make_tree(T.scratch())\n"
        "T.quiet(T.RF.write_release, base)\n"
        "(base / 'scripts' / 'a.py').write_bytes(b'changed')\n"
        "harness.check('planted: the changed tree asserted `no`', T.RF.compare(base)['package_modified'] == 'no')\n"
        "harness.check('control: the same harness passes a true statement', True)\n"
        "for tmp in T.CLEAN:\n"
        "    harness.cleanup(tmp)\n"
        "harness.finish('planted')\n", encoding="utf-8")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    process = subprocess.run([sys.executable, "-B", str(child)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                             env=env, timeout=120)
    fails = [line for line in process.stdout.splitlines() if line.startswith("FAIL ")]
    check_eq("K16 the planted check is reported: exactly one FAIL line", len(fails), 1)
    check_eq("K16 ...and the child run exits 1", process.returncode, 1)
    check_in("K16 ...naming the planted check", "planted: the changed tree asserted", fails)


# --- K17 the git gate of --write -------------------------------------------------------------------------------------

def k17_write_refuses_unshipped_files() -> None:
    if not shutil.which("git"):
        check("K17 git is available for the M-2 pins", False, "git not found on PATH")
        return
    tree = make_tree(scratch())
    git(tree, "init", "-q")
    git(tree, "add", "-A")
    litter = tree / "scripts" / ".pytest_cache" / "README.md"
    litter.parent.mkdir(parents=True)
    litter.write_bytes(b"cache")
    code, out, err = quiet(RF.main, ["--write"], root=tree)
    check_eq("K17 an untracked recipe file in a git clone: --write exits 2", code, 2)
    check_in("K17 ...naming the file", "scripts/.pytest_cache/README.md", err)
    check("K17 ...with the expected state and the door", "expected" in err and "git add" in err, err)
    check("K17 ...and writing nothing", not (tree / REL).exists())
    git(tree, "add", "-f", "scripts/.pytest_cache/README.md")
    code, out, err = quiet(RF.main, ["--write"], root=tree)
    check_eq("K17 F2: a TRACKED litter-named recipe file is refused too (a map never holds one): exit 2", code, 2)
    check("K17 F2: ...naming the file, what was expected and the door", "scripts/.pytest_cache/README.md" in err and "expected" in err
          and "rename it or move it" in err, err)
    check("K17 F2: ...and writing nothing", not (tree / REL).exists())
    git(tree, "rm", "-q", "-f", "scripts/.pytest_cache/README.md")
    (tree / "scripts" / "new.py").write_bytes(b"y = 2\n")
    code, out, err = quiet(RF.main, ["--write"], root=tree)
    check_eq("K17 a plain untracked recipe file is refused as before", (code, "scripts/new.py" in err), (2, True))
    git(tree, "add", "scripts/new.py")
    code, out, err = quiet(RF.main, ["--write"], root=tree)
    check_eq("K17 once the file is tracked, --write goes through", code, 0)
    check("K17 ...with no warning (it IS a clone)", "warning" not in err, err)
    code, out, err = quiet(RF.main, ["--write"], root=tree)
    check_eq("K17 the untracked release file itself never blocks a second --write", code, 0)
    check_eq("K17 ...and --check agrees", quiet(RF.main, ["--check"], root=tree)[0], 0)
    ignored = make_tree(scratch())
    git(ignored, "init", "-q")
    (ignored / ".gitignore").write_text("references/ignored.json\n", encoding="utf-8")
    git(ignored, "add", "-A")
    (ignored / "references" / "ignored.json").write_bytes(b"{}")
    code, out, err = quiet(RF.main, ["--write"], root=ignored)
    check_eq("K17 an IGNORED recipe file in a git clone: exit 2", code, 2)
    check_in("K17 ...naming it", "references/ignored.json", err)
    plain = make_tree(scratch())
    code, out, err = quiet(RF.main, ["--write"], root=plain)
    check_eq("K17 not a clone: git is not asked, one warning line, no refusal", (code, err.count("\n")), (0, 1))
    (plain / "scripts" / ".pytest_cache").mkdir()
    (plain / "scripts" / ".pytest_cache" / "README.md").write_bytes(b"cache")
    code, out, err = quiet(RF.main, ["--write"], root=plain)
    check_eq("K17 F2: not a clone, a litter-named recipe file is refused by name all the same", (code, "scripts/.pytest_cache/README.md" in err), (2, True))


def clone(base: Path) -> Path:
    """A git clone of a fixture tree with everything added to the index (line endings left alone: a CRLF edit stays an edit)."""
    git(base, "init", "-q")
    git(base, "config", "core.autocrlf", "false")
    git(base, "add", "-A")
    return base


def k17_f1_index_pins() -> None:
    """F1 (critic t-1055): a file added by intent only (`git add -N`) and an unstaged edit are not in the commit, yet the map holds
    their bytes - every install from git would read `yes`. The gate lists them in --write and in --check."""
    if not shutil.which("git"):
        check("K17 F1 git is available", False, "git not found on PATH")
        return
    tree = clone(make_tree(scratch()))
    (tree / "scripts" / "new.py").write_bytes(b"y = 1\n")
    git(tree, "add", "-N", "scripts/new.py")
    code, out, err = quiet(RF.main, ["--write"], root=tree)
    check_eq("K17 F1 an intent-to-add file: --write exits 2", code, 2)
    check("K17 F1 ...naming it and the door (`git add -A .`)", "scripts/new.py" in err and "git add -A ." in err, err)
    check("K17 F1 ...and writing nothing", not (tree / REL).exists())
    git(tree, "add", "-A")
    (tree / "scripts" / "a.py").write_bytes(b"x = 99\n")
    code, out, err = quiet(RF.main, ["--write"], root=tree)
    check_eq("K17 F1 an unstaged edit of a tracked file: --write exits 2", (code, "scripts/a.py" in err), (2, True))
    git(tree, "add", "-A")
    code, out, err = quiet(RF.main, ["--write"], root=tree)
    check_eq("K17 F1 once everything is in the index, --write goes through", (code, "warning" in err), (0, False))
    check_eq("K17 F1 ...and --check agrees", quiet(RF.main, ["--check"], root=tree)[0], 0)
    (tree / "scripts" / "a.py").write_bytes(b"x = 99\r\n")
    check_eq("K17 F1 control: CRLF alone does not move the verdict of compare", verdict(tree), ("no", "match"))
    code, out, err = quiet(RF.main, ["--check"], root=tree)
    check_eq("K17 F1 --check: an unstaged edit the map cannot see (CRLF) is exit 2", code, 2)
    check("K17 F1 --check: ...naming the file and the door", "scripts/a.py" in out and "git add -A ." in out, out)
    git(tree, "add", "-A")
    check_eq("K17 F1 --check: staged again, exit 0", quiet(RF.main, ["--check"], root=tree)[0], 0)
    git(tree, "rm", "-q", "--cached", "scripts/a.py")
    git(tree, "add", "-N", "scripts/a.py")
    code, out, err = quiet(RF.main, ["--check"], root=tree)
    check_eq("K17 F1 --check: an intent-to-add file is exit 2, named", (code, "scripts/a.py" in out), (2, True))
    top = scratch()
    package = clone_in(top, "pkg")
    (top / "outside.py").write_bytes(b"z = 1\n")
    git(top, "add", "-A")
    (top / "outside.py").write_bytes(b"z = 2\n")
    code, out, err = quiet(RF.main, ["--write"], root=package)
    check_eq("K17 F1 a changed file OUTSIDE the package folder does not block (paths are relative to the package)", code, 0)
    (package / "scripts" / "a.py").write_bytes(b"x = 7\n")
    code, out, err = quiet(RF.main, ["--write"], root=package)
    check_eq("K17 F1 ...an unstaged edit inside it does, named relative to the package", (code, "scripts/a.py" in err), (2, True))


def clone_in(top: Path, name: str) -> Path:
    """The package fixture as a SUBFOLDER of a git top (the release copy keeps the package under ai-packages/qa-factory)."""
    git(top, "init", "-q")
    git(top, "config", "core.autocrlf", "false")
    package = make_tree(top / name)
    git(top, "add", "-A")
    return package


def k17_f3_failed_listing_refuses() -> None:
    """F3 (critic t-1055, FR-59): inside a clone a git listing that fails (the wrapper's 10 s timeout answers 124) is a refusal."""
    import project_inventory
    original = project_inventory._git

    def fake(failing):
        def _git(path, *args):
            if args[:1] == ("rev-parse",):
                return 0, "true"
            return (124, "") if args[0] == failing else (0, "")
        return _git

    try:
        for failing in ("ls-files", "diff"):
            tree = make_tree(scratch())
            project_inventory._git = fake(failing)
            code, out, err = quiet(RF.main, ["--write"], root=tree)
            check_eq(f"K17 F3 `git {failing}` fails inside a clone: --write exits 2", code, 2)
            check("K17 F3 ...naming what git could not do, the expectation and the door",
                  "could not list" in err and f"git {failing}" in err and "expected the listing" in err and "fix git" in err, err)
            check("K17 F3 ...no warning-and-write, no file", "warning" not in err and not (tree / REL).exists(), err)
            project_inventory._git = original
            quiet(RF.write_release, tree)
            project_inventory._git = fake(failing)
            code, out, err = quiet(RF.main, ["--check"], root=tree)
            check_eq(f"K17 F3 `git {failing}` fails inside a clone: --check exits 2, not 0", code, 2)
            check_in("K17 F3 ...naming the why", "git_listing_failed", out)
    finally:
        project_inventory._git = original


def k17_f2_litter_is_added_only() -> None:
    """F2 (critic t-1055, FR-41): a mapped path was shipped, so its change or removal is a difference whatever its name."""
    out = {}
    mapped = {"skills/k/.defaults.json": "a" * 64, "skills/k/~$z.md": "b" * 64, "scripts/a.py": "c" * 64}
    disk = {"skills/k/.defaults.json": "d" * 64, "scripts/a.py": "c" * 64, "skills/k/.added.md": "e" * 64}
    RF._verdict(out, mapped, disk)
    check_eq("K17 F2 a changed and a removed litter-named MAPPED file read `yes`, named",
             (out["package_modified"], out["changed"], out["removed"]), ("yes", ["skills/k/.defaults.json"], ["skills/k/~$z.md"]))
    check_eq("K17 F2 ...only an ADDED litter-named file goes to litter[]", (out["litter"], out["added"]), (["skills/k/.added.md"], []))
    tree = released()
    edit_release(tree, lambda d: d["files"].update({"skills/k/.defaults.json": "0" * 64}))
    check_eq("K17 F2 a release file whose map holds a litter-named path is invalid", verdict(tree), ("unknown", "release_file_invalid"))
    check_eq("K17 F2 the manifest key is not litter although `.claude-plugin` starts with a dot",
             (RF._is_litter(RF.MANIFEST_REL), RF._admissible_key(RF.MANIFEST_REL)), (False, True))
    walked = [path.relative_to(harness.PLUGIN_ROOT).as_posix() for path in RF.recipe_files(harness.PLUGIN_ROOT)]
    check("K17 F2 the real package has no litter-named recipe file (the day one appears this goes red)",
          bool(walked) and not [rel for rel in walked if RF._is_litter(rel)], str([rel for rel in walked if RF._is_litter(rel)]))


def k17_f4_version_text() -> None:
    """F4 (critic t-1055, FR-1): a pre-release version is a version that is not of the form N.N.N; the refusal must not say 'no version'."""
    tree = make_tree(scratch())
    (tree / ".claude-plugin" / "plugin.json").write_bytes(b'{"version":"0.10.0-rc1"}')
    code, out, err = quiet(RF.main, ["--write"], root=tree)
    check_eq("K17 F4 a version outside N.N.N: --write exits 2", code, 2)
    check_in("K17 F4 ...the text says what is wrong and what was found", "no version of the form N.N.N in .claude-plugin/plugin.json", err)
    check_in("K17 F4 ...with the found value", "(found: '0.10.0-rc1')", err)
    check("K17 F4 ...and writes nothing", not (tree / REL).exists())
    released_tree = released()
    (released_tree / ".claude-plugin" / "plugin.json").write_bytes(b'{"version":"0.10.0-rc1"}')
    check_eq("K17 F4 compare reads it as version_unknown (the error direction was right)", verdict(released_tree), ("unknown", "version_unknown"))
    check_in("K17 F4 the version_unknown text says the form too", "N.N.N", RF.WHY_TEXT["version_unknown"][0])
    absent = scratch()
    (absent / "scripts").mkdir()
    code, out, err = quiet(RF.main, ["--write"], root=absent)
    check_in("K17 F4 no manifest: the found value says so", "(found: plugin.json absent)", err)


# --- K18, K19 ------------------------------------------------------------------------------------------------------

def k18_install_kind() -> None:
    tree = released()
    check_eq("K18 a tree outside the plugin cache is `frozen`", RF.compare(tree)["install"], "frozen")
    home = scratch()
    cached = make_tree(home / "plugins" / "cache" / "qafactory" / "qa-factory" / "9.9.9")
    quiet(RF.write_release, cached)
    saved = os.environ.get("CLAUDE_CONFIG_DIR")
    os.environ["CLAUDE_CONFIG_DIR"] = str(home)
    try:
        result = RF.compare(cached)
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = saved
    check_eq("K18 a tree under <claude home>/plugins/cache is `cache`", (result["install"], result["package_modified"]), ("cache", "no"))


def k19_before_world_and_edges() -> None:
    tree = make_tree(scratch())
    (tree / "scripts" / "a.py").write_bytes(b"changed\n")
    check_eq("K19 before the first release that writes the file: unknown, even for a modified tree", verdict(tree), ("unknown", "no_release_file"))
    empty = scratch()
    check_eq("K19 an empty package folder: the aggregate is sha256 of nothing", RF.package_fingerprint(empty), hashlib.sha256(b"").hexdigest())
    check_eq("K19 ...and compare is unknown, never yes", verdict(empty)[0], "unknown")
    tree = released()
    original = RF.recipe_files

    def looping(root=None):
        raise OSError("seam: a loop in the walk")

    RF.recipe_files = looping
    try:
        result = RF.compare(tree)
    finally:
        RF.recipe_files = original
    check_eq("K19 a walk that raises is `unknown / package_unreadable`, compare never raises", (result["package_modified"], result["why"]),
             ("unknown", "package_unreadable"))
    check_eq("K19 ...and the versions already read stay in the answer", (result["release_version"], result["running_version"]), ("9.9.9", "9.9.9"))
    if hasattr(os, "symlink"):
        tree = make_tree(scratch())
        try:
            os.symlink(tree / "scripts" / "a.py", tree / "scripts" / "link.md")
        except (OSError, NotImplementedError):
            check("K19 symlinks cannot be created here: the symlink edge is skipped", True)
        else:
            quiet(RF.write_release, tree)
            check("K19 a symlink to a file is followed (its target's bytes are in the map)", "scripts/link.md" in json.loads((tree / REL).read_text(encoding="utf-8"))["files"])
            (tree / "scripts" / "a.py").unlink()
            result = RF.compare(tree)
            check("K19 a dangling link is invisible: the mapped path reads `removed`", "scripts/link.md" in result["removed"], str(result))


# --- K20 the survivor's other readers (collect/2, CL2-1; AR-15) -----------------------------------------------------------

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def copy_of_host_probe(tree: Path):
    """host_probe.py loaded FROM `tree/scripts/`: its `__file__` is there, so the package it hashes is that tree."""
    import importlib.util
    target = tree / "scripts" / "host_probe.py"
    target.write_bytes((harness.SCRIPTS / "host_probe.py").read_bytes())
    spec = importlib.util.spec_from_file_location("host_probe_copy", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def raising_read(*names):
    """A `_read_bytes` that fails for the named files (all of them when none is named): the survivor's seam, never chmod."""
    real = RF._read_bytes

    def read(path):
        if not names or Path(path).name in names:
            raise PermissionError("seam: unreadable " + Path(path).name)
        return real(path)
    return read


def k20_probe_reads_the_survivor() -> None:
    project = harness.temp_project()
    CLEAN.append(project)
    config = project / "qa-factory" / "config.json"
    body = config.read_bytes()
    original = RF.package_fingerprint
    RF.package_fingerprint = lambda root=None: "SENTINEL"
    try:
        check_eq("K20 the probe is sha256(<survivor's aggregate> + LF + the project's config bytes)",
                 host_probe.fingerprint(project), sha(b"SENTINEL\n" + body))
        config.write_bytes(body + b" ")
        check_eq("K20 one config byte changes it", host_probe.fingerprint(project), sha(b"SENTINEL\n" + body + b" "))
        config.write_bytes(b"")
        empty = host_probe.fingerprint(project)
        config.unlink()
        check_eq("K20 an absent config equals an empty one (existing projects keep the meaning)", host_probe.fingerprint(project), empty)
        check_eq("K20 ...and both are the aggregate over b''", empty, sha(b"SENTINEL\n"))
        config.write_bytes(body)
        real_read = Path.read_bytes

        def read(self):
            if self.name == "config.json":
                raise PermissionError("seam: unreadable config.json")
            return real_read(self)
        Path.read_bytes = read
        try:
            first, second = host_probe.fingerprint(project), host_probe.fingerprint(project)
        finally:
            Path.read_bytes = real_read
        check("K20 an unreadable config is `unknown:config_unreadable:<nonce>`, never a hash",
              first.startswith("unknown:config_unreadable:") and not _HEX.fullmatch(first), first)
        check("K20 ...and two calls differ (the nonce)", first != second, first)
    finally:
        RF.package_fingerprint = original
    check_eq("K20 with the survivor back, the probe is the real aggregate", host_probe.fingerprint(project),
             sha(RF.package_fingerprint(harness.PLUGIN_ROOT).encode("ascii") + b"\n" + body))

    # the package part follows the bytes RUNNING (host_probe's own __file__), and the release file is outside it (I5)
    tree = make_tree(scratch())
    copy = copy_of_host_probe(tree)
    before = copy.fingerprint(project)
    check_eq("K20 the probe hashes the package its own file lives in",
             before, sha(RF.package_fingerprint(tree).encode("ascii") + b"\n" + body))
    quiet(RF.write_release, tree)
    check("K20 a release file written into the package does not change it (I5)", copy.fingerprint(project) == before)
    (tree / "agents" / "q.md").write_bytes(b"changed\n")
    check("K20 a changed agent file does change it (the old walk did not see agents/)", copy.fingerprint(project) != before)

    # the survivor's seam: an unreadable package file is unknown, never raised, never equal to a stored value
    RF._read_bytes = raising_read()
    try:
        first, second = host_probe.fingerprint(project), host_probe.fingerprint(project)
    finally:
        RF._read_bytes = harness_read
    check("K20 an unreadable package is `unknown:package_unreadable:<nonce>`",
          first.startswith("unknown:package_unreadable:") and not _HEX.fullmatch(first), first)
    check("K20 ...two calls differ, so neither equals a stored value", first != second and first.split(":")[2] != second.split(":")[2])
    check("K20 ...and with the seam restored the probe is a hash again", bool(_HEX.fullmatch(host_probe.fingerprint(project))))


def run_manifest(*args) -> tuple:
    """(exit code or None, stdout) of factory_manifest.main() with these arguments."""
    saved, code = sys.argv, None
    sys.argv = ["factory_manifest.py", *args]
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink):
            try:
                FM.main()
            except SystemExit as exc:
                code = exc.code
    finally:
        sys.argv = saved
    return code, sink.getvalue()


def k20_manifest_follows_the_survivor() -> None:
    sentinel = {"scripts/x.py": "0" * 64}
    original = RF.file_digests
    RF.file_digests = lambda root=None: sentinel
    try:
        check_eq("K20 collect_definition() is the survivor's map (no glob walk of its own)", FM.collect_definition(), sentinel)
    finally:
        RF.file_digests = original
    check("K20 DEFINITION_GLOBS is gone", not hasattr(FM, "DEFINITION_GLOBS"))

    scratch_dir = scratch()
    saved_path = FM.MANIFEST_PATH
    FM.MANIFEST_PATH = scratch_dir / "factory-manifest.json"
    try:
        code, out = run_manifest("--stamp", "test witness")
        stamp = json.loads(FM.MANIFEST_PATH.read_text(encoding="utf-8"))
        check_eq("K20 --stamp writes the recipe id and the survivor's map", (code, stamp["recipe"], stamp["files"]),
                 (None, RF.RECIPE_ID, RF.file_digests(harness.PLUGIN_ROOT)))
        check_eq("K20 a stamp of the same tree verifies clean", FM.verify(), [])
        stamp["files"]["scripts/hooklib.py"] = "0" * 64
        FM.MANIFEST_PATH.write_text(json.dumps(stamp), encoding="utf-8")
        check_eq("K20 a changed file is named, once", FM.verify(), ["scripts/hooklib.py: content diverged from the stamp"])
        code, out = run_manifest("--check")
        check_eq("K20 a real drift keeps the header `DRIFT (1)` and exit 1", (code, out.splitlines()[0]), (1, "factory_manifest: DRIFT (1)"))

        # a stamp of another recipe (every stamp before CL2-1 has none) is never judged file by file (E7)
        old = dict(stamp)
        old.pop("recipe")
        FM.MANIFEST_PATH.write_text(json.dumps(old), encoding="utf-8")
        lines = FM.verify()
        check_eq("K20 a stamp without `recipe`: exactly one line", len(lines), 1)
        check_in("K20 ...saying another recipe, and the door", "another recipe (none)", lines)
        check_in("K20 ...with the way out", "--stamp", lines)
        code, out = run_manifest("--check")
        check_eq("K20 ...and --check says NOT JUDGED, never DRIFT (an unknown does not accuse), exit 1 kept",
                 (code, out.splitlines()[0], "DRIFT" in out), (1, "factory_manifest: NOT JUDGED (1)", False))
        FM.MANIFEST_PATH.write_text(json.dumps(dict(stamp, recipe="release-fingerprint/0")), encoding="utf-8")
        check_in("K20 a stamp of a named other recipe says which", "another recipe (release-fingerprint/0)", FM.verify())

        # a tree that cannot be read: --check one UNKNOWN line, never a pass (E3)
        FM.MANIFEST_PATH.write_text(json.dumps(dict(stamp, files=RF.file_digests(harness.PLUGIN_ROOT))), encoding="utf-8")
        RF._read_bytes = raising_read("hooklib.py")
        try:
            lines = FM.verify()
            code, out = run_manifest("--check")
        finally:
            RF._read_bytes = harness_read
        check_eq("K20 --check on an unreadable tree: one line, UNKNOWN, naming the file", (len(lines), lines[0].startswith("UNKNOWN"), "scripts/hooklib.py" in lines[0]),
                 (1, True, True))
        check_eq("K20 ...and exit 1", code, 1)
        check_eq("K20 ...under the header NOT JUDGED, never DRIFT", (out.splitlines()[0], "DRIFT" in out), ("factory_manifest: NOT JUDGED (1)", False))

        # --stamp over an unreadable tree: refused, exit 2, nothing written (E3), the cap says what it hid
        FM.MANIFEST_PATH.write_bytes(b"keep")
        RF._read_bytes = raising_read("hooklib.py")
        try:
            code, out = run_manifest("--stamp", "w")
        finally:
            RF._read_bytes = harness_read
        check_eq("K20 --stamp on an unreadable tree: exit 2", code, 2)
        check_eq("K20 ...and nothing is written (byte compare)", FM.MANIFEST_PATH.read_bytes(), b"keep")
        check("K20 ...the refusal names the file, what was expected and the door",
              "scripts/hooklib.py" in out and "expected" in out and "fix the files" in out, out)
        RF._read_bytes = raising_read()
        try:
            code, out = run_manifest("--stamp", "w")
        finally:
            RF._read_bytes = harness_read
        check("K20 ...a long list is cut at 10 names and says how much it hid", "(+" in out and "more)" in out, out)
        check_eq("K20 ...still nothing written", (code, FM.MANIFEST_PATH.read_bytes()), (2, b"keep"))
    finally:
        FM.MANIFEST_PATH = saved_path


def main() -> None:
    try:
        k1_aggregate_is_heads()
        k2_k3_readers()
        k4_release_file_is_outside()
        k5_write_then_compare()
        k6_release_file_rows()
        k7_version_rows()
        k8_proven_difference()
        k9_never_accuses()
        k10_mtime_is_never_read()
        k11_line_endings()
        k12_doubt_before_difference()
        k13_self_listing_file()
        k14_cli()
        k15_compare_shape()
        k16_planted_failure_is_reported()
        k17_write_refuses_unshipped_files()
        k17_f1_index_pins()
        k17_f3_failed_listing_refuses()
        k17_f2_litter_is_added_only()
        k17_f4_version_text()
        k18_install_kind()
        k19_before_world_and_edges()
        k20_probe_reads_the_survivor()
        k20_manifest_follows_the_survivor()
    finally:
        for base in CLEAN:
            cleanup(base)
    finish("test_release_fingerprint")


if __name__ == "__main__":
    main()
