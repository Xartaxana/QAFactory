"""FB-27: dependency provisioning never installs outside the throwaway clone or after a mutation - and
`_run_mine` reads a typed refusal from stderr, and only that.

A clone of a Node/Playwright project has no node_modules (git-ignored, never copied), so a TS/JS red probe died
on MODULE_NOT_FOUND before any assertion ran. `prepare` now plans the request's `sandbox_setup` rows (form and
budget) BEFORE the clone exists, copies, installs in the still-unmutated clone, then mutates. What a kind runs,
which files pin it and which folder must be created are rows of references/sandbox-setup.json. Expectations come
from the requirement (FB-27, t-958 section 5 edges 9-20 and L/L-2), not from the code's output (FR-58). No npm is
run here: the shipped row is checked with `node_ids.run_bounded` patched, and every real-subprocess case uses a
fake kind from a temp table whose command is this interpreter.
"""
import contextlib
import errno
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import node_ids  # noqa: E402
import red_sandbox as R  # noqa: E402
from event_store import content_hash  # noqa: E402

INSTANCE = "TC-1::test_one"
HEX = "a" * 64


def refused(call, kind=ValueError) -> str:
    """The text of the refusal of the given class, or "" when the call went through."""
    try:
        call()
    except kind as error:
        return str(error)
    return ""


def table(root: Path, command: str = "pass", timeout: int = 60, name: str = "fake_touch") -> Path:
    """A temp references table with ONE kind whose command is this interpreter."""
    row = {"argv": [sys.executable, "-c", command], "env": {"QA_SETUP_MARK": "marked"},
           "pins": {"manifest.txt": "manifest_sha256"}, "must_not_preexist": ["deps"], "timeout_s": timeout,
           "receipt": {"network": False}}
    path = root / "sandbox-setup.json"
    path.write_text(json.dumps({"kinds": {name: row}}), encoding="utf-8")
    return path


TOUCH = ("import os, pathlib, sys; assert sys.stdin.read() == ''; pathlib.Path('deps').mkdir(); "
         "pathlib.Path('deps/env.txt').write_text(os.environ.get('QA_SETUP_MARK', ''))")


def make_clone(root: Path) -> tuple:
    """(clone, spec): a clone as `prepare` leaves it while preparing - the marker written, the copy made."""
    author, clone = root / "author", root / "clone"
    author.mkdir(parents=True)
    (clone / "app").mkdir(parents=True)
    (clone / "app" / "manifest.txt").write_text("pinned", encoding="utf-8")
    (clone / "behavior.py").write_text("before", encoding="utf-8")
    marker = {"status": "preparing", "repo": str(author), "sandbox": str(clone),
              "targets": [{"path": "behavior.py", "before_sha256": R.digest(clone / "behavior.py")}]}
    (clone / ".qa-probe.json").write_text(json.dumps(marker), encoding="utf-8")
    return clone, {"kind": "fake_touch", "cwd": "app", "manifest_sha256": R.digest(clone / "app/manifest.txt")}


def provision(clone: Path, spec: dict, **kw):
    return R.provision_dependencies(clone, {"sandbox_setup": [spec]}, **kw)


def run_mine_checks() -> None:
    def completed(stdout: str, stderr: str):
        return subprocess.CompletedProcess(["run_suite.py"], 2, stdout=stdout, stderr=stderr)

    def mine():
        return R._run_mine(Path("run_suite.py"), Path("."), ["TC-1"], dispatch="", sandbox_root=Path("."),
                           reason="r", again=False, timeout=5)[1]

    refusal = '{"status": "invalid_request", "error": "RequestError: store.begin refused the key"}'
    run_claim = '{"status": "completed", "execution_status": "passed", "error": "none"}'
    cases = (("a typed refusal on stderr is the summary when stdout holds none", "", "tail\n" + refusal + "\n", json.loads(refusal)),
             ("a stdout summary wins over stderr", '{"status": "completed"}\n', refusal, {"status": "completed"}),
             ("no JSON on either stream is the empty summary", "no json", "no json either", {}),
             ("a stderr line claiming `execution_status` never makes a run `have been`", "", run_claim, {}),
             ("a stderr JSON without `error` is not a refusal", "", '{"status": "invalid_request"}', {}),
             ("a stderr line that is not JSON is nothing", "", '{"status": "inv', {}))
    for label, out, err, expected in cases:
        with patch.object(R.subprocess, "run", return_value=completed(out, err)):
            check_eq(f"_run_mine: {label}", mine(), expected)


def table_checks(root: Path) -> None:
    kinds, problems = R.setup_kinds()
    check_eq("the shipped table has no problem and holds npm_ci", (problems, sorted(kinds)), ({}, ["npm_ci"]))
    row = kinds["npm_ci"]
    check_eq("the shipped program names are the reviewed set (a new program is a reviewed diff)",
             sorted({row["argv"][0], *(v[0] for v in row.get("platform_argv", {}).values())}), ["npm", "npm.cmd"])
    check_eq("the shipped row installs from the lock without scripts, audit or funding noise",
             row["argv"][1:], ["ci", "--ignore-scripts", "--no-audit", "--no-fund"])
    check("two shipped installs fit one probe call's budget (a mutated and a baseline clone)",
          2 * row["timeout_s"] <= R.INSTALL_BUDGET_S, str(row["timeout_s"]))
    check_eq("the shipped receipt names the user download cache (F-7)", row["receipt"].get("download_cache"), "user")

    def shaped(**change):
        good = {"argv": ["x"], "pins": {"a.lock": "lock_sha256"}, "must_not_preexist": ["deps"], "timeout_s": 5}
        path = root / "shaped.json"
        path.write_text(json.dumps({"kinds": {"k": dict(good, **change), "ok": good}}), encoding="utf-8")
        with patch.object(R, "SETUP_KINDS_FILE", path):
            return R.setup_kinds()

    for label, change in (("an empty argv", {"argv": []}), ("a non-string argv entry", {"argv": ["x", 1]}),
                          ("a bool timeout", {"timeout_s": True}), ("a zero timeout", {"timeout_s": 0}),
                          ("a timeout beyond 3600", {"timeout_s": 3601}), ("no pins", {"pins": {}}),
                          ("a pin that is a path", {"pins": {"../a.lock": "f"}}),
                          ("a pin that is a nested path", {"pins": {"sub/a.lock": "f"}}),
                          ("an empty must_not_preexist", {"must_not_preexist": []}),
                          ("an env that is not str:str", {"env": {"A": 1}}),
                          ("a receipt with a list", {"receipt": {"a": [1]}})):
        kinds, problems = shaped(**change)
        check_eq(f"schema: {label} makes ONLY that row absent, and names the field", (sorted(kinds), list(problems)),
                 (["ok"], ["k"]))
    check_eq("schema: the edge values 1 and 3600 are accepted", shaped(timeout_s=1)[1] == {} and shaped(timeout_s=3600)[1] == {}, True)
    for label, content in (("missing", None), ("not JSON", "{"), ("an array", "[]"), ("without kinds", "{}"),
                           ("with kinds that is a list", '{"kinds": []}')):
        path = root / "broken.json"
        if content is None:
            path = root / "no-such-table.json"
        else:
            path.write_text(content, encoding="utf-8")
        with patch.object(R, "SETUP_KINDS_FILE", path):
            kinds, problems = R.setup_kinds()
            words = refused(lambda: R.plan_setup({"sandbox_setup": [{"kind": "npm_ci", "cwd": "."}]}), R.SetupRefused)
        check_eq(f"a table that is {label} knows no kind", kinds, {})
        check_in(f"...and every kind is refused saying so (never a silent `no kinds`): {label}", "unreadable", words)


def plan_checks(root: Path) -> None:
    gone = root / "no-such-table.json"
    with patch.object(R, "SETUP_KINDS_FILE", gone):
        for label, value in (("absent", None), ("[]", [])):
            check_eq(f"sandbox_setup {label}: no plan, and the table is not even read",
                     R.plan_setup({} if value is None else {"sandbox_setup": value}), [])
        check_eq("sandbox_setup null: no plan", R.plan_setup({"sandbox_setup": None}), [])
    check_in("sandbox_setup that is not a list is refused", "must be a list",
             refused(lambda: R.plan_setup({"sandbox_setup": {"kind": "npm_ci"}}), R.SetupRefused))
    base = {"kind": "npm_ci", "cwd": "e2e", "package_sha256": HEX, "lock_sha256": HEX}
    check_eq("a good npm_ci row plans one install", [(p["kind"], p["cwd"]) for p in R.plan_setup({"sandbox_setup": [base]})],
             [("npm_ci", "e2e")])
    words = refused(lambda: R.plan_setup({"sandbox_setup": [dict(base, kind="yarn_install")]}), R.SetupRefused)
    check_in("a kind outside the table: the kinds are named", "the kinds are npm_ci", words)
    check_in("...with the door: probe without sandbox_setup and file the gap (FR-57)", "probe without sandbox_setup", words)
    for label, bad in (("a row that is not an object", "npm_ci"), ("a row without a kind", {"cwd": "."}),
                       ("a kind that is not a string", dict(base, kind=["npm_ci"]))):
        check(f"a bad row is refused: {label}", bool(refused(lambda: R.plan_setup({"sandbox_setup": [bad]}), R.SetupRefused)))
    check_in("an unknown request key (argv, env ...) is refused: the command comes from the table",
             "never from the request", refused(lambda: R.plan_setup({"sandbox_setup": [dict(base, argv=["rm"])]}), R.SetupRefused))
    for label, cwd in (("an absolute path", str(root)), ("a rooted path", "/e2e"), ("a backslash-rooted path", "\\e2e"),
                       ("an escaping path", "../escape"), ("an escape in the middle", "a/../../b"), ("empty", ""),
                       ("not a string", ["e2e"]), ("None", None)):
        check(f"cwd {label} is refused", bool(refused(lambda: R.plan_setup({"sandbox_setup": [dict(base, cwd=cwd)]}), R.SetupRefused)))
    for label, change in (("empty", {"lock_sha256": ""}), ("missing", {"lock_sha256": None}), ("63 hex", {"lock_sha256": "a" * 63}),
                          ("65 hex", {"lock_sha256": "a" * 65}), ("upper case", {"lock_sha256": "A" * 64}),
                          ("not hex", {"lock_sha256": "g" * 64}), ("a number", {"package_sha256": 7})):
        check_in(f"a pin that is {label} is refused naming its field", "sha256",
                 refused(lambda: R.plan_setup({"sandbox_setup": [dict(base, **change)]}), R.SetupRefused))
    check_in("the same kind and folder twice is refused before anything runs", "twice",
             refused(lambda: R.plan_setup({"sandbox_setup": [base, dict(base, cwd="e2e/")]}), R.SetupRefused))
    check_eq("two folders of one kind are two installs", len(R.plan_setup({"sandbox_setup": [base, dict(base, cwd="ui")]}, 480)), 2)
    # t-1057 F4 (a): the duplicate key is a NORMALISED path, not characters stripped from its ends
    dotted = []
    check_eq("`.tools` and `tools` are two folders: not refused as twice (no character stripping)",
             refused(lambda: dotted.extend(R.plan_setup(
                 {"sandbox_setup": [dict(base, cwd=".tools"), dict(base, cwd="tools")]}, 480)), R.SetupRefused), "")
    check_eq("...hence two installs", [p["cwd"] for p in dotted], [".tools", "tools"])
    for same in ("./e2e", "e2e/", "e2e//", "e2e/./"):
        check_in(f"`e2e` and `{same}` are one folder: refused as twice", "twice",
                 refused(lambda: R.plan_setup({"sandbox_setup": [base, dict(base, cwd=same)]}), R.SetupRefused))
    check_in("`.` and `./` are one folder: refused as twice", "twice", refused(lambda: R.plan_setup(
        {"sandbox_setup": [dict(base, cwd="."), dict(base, cwd="./")]}), R.SetupRefused))
    check_eq("`a/b` and `a` are different folders", len(R.plan_setup(
        {"sandbox_setup": [dict(base, cwd="a/b"), dict(base, cwd="a")]}, 480)), 2)

    broken = root / "one-broken.json"
    good = {"argv": ["x"], "pins": {"a.lock": "lock_sha256"}, "must_not_preexist": ["deps"], "timeout_s": 5}
    broken.write_text(json.dumps({"kinds": {"bad_kind": dict(good, timeout_s=0), "ok": good}}), encoding="utf-8")
    with patch.object(R, "SETUP_KINDS_FILE", broken):
        words = refused(lambda: R.plan_setup({"sandbox_setup": [{"kind": "bad_kind", "cwd": "."}]}), R.SetupRefused)
        check_in("a broken row is named as such, with its field (not `unsupported kind`)",
                 "row bad_kind of references/sandbox-setup.json is malformed: timeout_s", words)
        check_in("...and called a factory defect", "a factory defect", words)
        check_eq("...while the healthy row of the same table still plans",
                 len(R.plan_setup({"sandbox_setup": [{"kind": "ok", "cwd": ".", "lock_sha256": HEX}]})), 1)


def budget_checks(root: Path) -> None:
    """M-8: the installs of ONE probe call add up to at most the budget - AT passes, BEYOND refuses, with the door."""
    spec = {"kind": "fake_touch", "cwd": ".", "manifest_sha256": HEX}
    with patch.object(R, "SETUP_KINDS_FILE", table(root, timeout=R.INSTALL_BUDGET_S)):
        check_eq("budget: a single install of exactly 540 s passes", len(R.plan_setup({"sandbox_setup": [spec]})), 1)
    with patch.object(R, "SETUP_KINDS_FILE", table(root, timeout=R.INSTALL_BUDGET_S + 1)):
        words = refused(lambda: R.plan_setup({"sandbox_setup": [spec]}), R.SetupRefused)
        check_in("budget: 541 s refuses (FR-1: what, the limit)", "541 s", words)
        check_in("budget: ...and names the key that is the door", "sandbox.install_timeout_s", words)
        check_in("budget: ...and the other door, a second probe call", "two calls", words)
        check_eq("budget: the same plan passes with the budget raised", len(R.plan_setup({"sandbox_setup": [spec]}, 541)), 1)
    with patch.object(R, "SETUP_KINDS_FILE", table(root, timeout=270)):
        two = [spec, dict(spec, cwd="b")]
        check_eq("budget: two rows of 270 s add up to exactly 540 and pass", len(R.plan_setup({"sandbox_setup": two})), 2)
        check("budget: ...a third does not", bool(refused(lambda: R.plan_setup({"sandbox_setup": two + [dict(spec, cwd="c")]}), R.SetupRefused)))
        check_in("budget: what a first clone spent is gone from the second clone's budget", "up to 270 s",
                 refused(lambda: R.plan_setup({"sandbox_setup": [spec]}, 269), R.SetupRefused))
        check("budget: a budget used up (0 or less) refuses a plan, never divides by it",
              bool(refused(lambda: R.plan_setup({"sandbox_setup": [spec]}, -5), R.SetupRefused)))

    repo = root / "budget-repo"
    for label, config, expected in (("no config.json at all", None, 540), ("a config without the key", {}, 540),
                                    ("a config with sandbox but not the key", {"sandbox": {}}, 540),
                                    ("the key set", {"sandbox": {"install_timeout_s": 900}}, 900)):
        (repo / "qa-factory").mkdir(parents=True, exist_ok=True)
        cfg = repo / "qa-factory" / "config.json"
        if config is None:
            cfg.unlink(missing_ok=True)
        else:
            cfg.write_text(json.dumps(config), encoding="utf-8")
        check_eq(f"install_budget_s: {label}", R.install_budget_s(repo), expected)
    for bad in (0, -1, "540", True, 1.5, []):
        cfg.write_text(json.dumps({"sandbox": {"install_timeout_s": bad}}), encoding="utf-8")
        check_in(f"install_budget_s: {bad!r} is refused by name, not replaced by the default", "sandbox.install_timeout_s",
                 refused(lambda: R.install_budget_s(repo), R.SetupRefused))
    cfg.write_text("{broken", encoding="utf-8")
    check_eq("install_budget_s: an unreadable config.json is the default (the config reader owns that fault)",
             R.install_budget_s(repo), 540)


def shipped_npm_checks(root: Path) -> None:
    (root / "e2e").mkdir()
    for name in ("package.json", "package-lock.json"):
        (root / "e2e" / name).write_text("{}", encoding="utf-8")
    (root / ".qa-probe.json").write_text(json.dumps({"status": "preparing", "repo": str(root.parent / "no-author"),
                                                     "sandbox": str(root), "targets": []}), encoding="utf-8")
    spec = {"kind": "npm_ci", "cwd": "e2e", "package_sha256": R.digest(root / "e2e/package.json"),
            "lock_sha256": R.digest(root / "e2e/package-lock.json")}

    def fake_run(argv, cwd, env, timeout_s, **kw):
        (Path(cwd) / "node_modules").mkdir()
        return 0, b""

    with patch.object(node_ids, "run_bounded", side_effect=fake_run) as run:
        result = R.provision_dependencies(root, {"sandbox_setup": [spec]})
        argv, cwd, env, limit = run.call_args.args
        check_eq("npm_ci: the shipped row runs `npm ci` without scripts, audit or funding noise",
                 argv[1:], ["ci", "--ignore-scripts", "--no-audit", "--no-fund"])
        check("npm_ci: the executable is npm (npm.cmd on Windows)", Path(argv[0]).name == ("npm.cmd" if os.name == "nt" else "npm"), argv[0])
        check_eq("npm_ci: runs inside the clone's own subdirectory", Path(cwd), (root / "e2e").resolve())
        check_eq("npm_ci: browser downloads are off for the install", env.get("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"), "1")
        check_eq("npm_ci: the row's own limit is passed", limit, R.setup_kinds()[0]["npm_ci"]["timeout_s"])
        check_eq("npm_ci: the receipt row is ready and carries both pins, the no-scripts facts and the cache fact",
                 (result[0]["status"], result[0]["kind"], result[0]["lock_sha256"], result[0]["package_sha256"],
                  result[0]["browser_downloads"], result[0]["lifecycle_scripts"], result[0]["download_cache"]),
                 ("ready", "npm_ci", spec["lock_sha256"], spec["package_sha256"], False, False, "user"))
    (root / "e2e" / "node_modules").rmdir()
    with patch.object(node_ids, "run_bounded", return_value=(0, b"")):
        check_in("npm_ci: exit 0 without node_modules is NOT ready (FR-18)", "exit 0 alone cannot establish readiness",
                 refused(lambda: R.provision_dependencies(root, {"sandbox_setup": [spec]}), R.SetupFailed))
    with patch.object(node_ids, "run_bounded", return_value=(1, b"npm ERR! boom")):
        words = refused(lambda: R.provision_dependencies(root, {"sandbox_setup": [spec]}), R.SetupFailed)
        check_in("npm_ci: a non-zero npm exit blocks the probe with the code and the output tail", "exit 1", words)
        check_in("npm_ci: ...the tail is in the words", "npm ERR! boom", words)


def fake_kind_checks(root: Path) -> None:
    clone, spec = make_clone(root)
    with patch.object(R, "SETUP_KINDS_FILE", table(root, TOUCH)):
        result = provision(clone, spec)
        check_eq("a data-file kind runs its argv in the clone's cwd, stdin closed, the row's env laid over",
                 (clone / "app/deps/env.txt").read_text(encoding="utf-8"), "marked")
        check_eq("its receipt row names kind, cwd, the pin under the row's field name and the row's receipt facts",
                 {k: v for k, v in result[0].items() if k != "argv"},
                 {"kind": "fake_touch", "cwd": "app", "status": "ready", "manifest_sha256": spec["manifest_sha256"],
                  "network": False})
        check_in("the row's must_not_preexist folder, once there, refuses a second provisioning",
                 "freshly provisioned", refused(lambda: provision(clone, spec), R.SetupRefused))
        check_eq("a call with no rows runs nothing and returns no receipt", R.provision_dependencies(clone, {}), [])


def guard_checks(root: Path) -> None:
    """F-3 (a): the install is guarded in the function, for ANY caller."""
    command = "import pathlib; pathlib.Path('deps').mkdir()"

    def refuse_with(label, mutate, needle):
        clone, spec = make_clone(root / label.replace(" ", "-"))
        mutate(clone)
        with patch.object(R, "SETUP_KINDS_FILE", table(root, command)):
            words = refused(lambda: provision(clone, spec), R.SetupRefused)
        check_in(f"guard: {label} is refused", needle, words)
        check(f"guard: ...and nothing was installed ({label})", not (clone / "app" / "deps").exists())

    def marker(clone, **change):
        path = clone / ".qa-probe.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(change)
        path.write_text(json.dumps(data), encoding="utf-8")

    refuse_with("no marker", lambda c: (c / ".qa-probe.json").unlink(), "not a clone this probe is preparing")
    refuse_with("a finished sandbox", lambda c: marker(c, status="prepared"), "not a clone this probe is preparing")
    refuse_with("a marker naming another folder", lambda c: marker(c, sandbox=str(c.parent / "other")), "not a clone this probe")
    refuse_with("a clone inside the author tree", lambda c: marker(c, repo=str(c.parent)), "not disjoint")
    refuse_with("an author tree inside the clone", lambda c: marker(c, repo=str(c / "app")), "not disjoint")
    refuse_with("a mutated target", lambda c: (c / "behavior.py").write_text("after", encoding="utf-8"), "already mutated")
    refuse_with("a missing target", lambda c: (c / "behavior.py").unlink(), "already mutated")

    clone, spec = make_clone(root / "files")
    cases = (("lock file not in the clone (says why, not `pin mismatch`)", lambda: (clone / "app/manifest.txt").unlink(),
              "needs it as a pinned file"),
             ("a pin that no longer matches", lambda: (clone / "app/manifest.txt").write_text("other", encoding="utf-8"), "pin mismatch"))
    with patch.object(R, "SETUP_KINDS_FILE", table(root, command)):
        for label, damage, needle in cases:
            damage()
            said = refused(lambda: provision(clone, spec), R.SetupRefused)
            check_in(f"a clone check: {label}", needle, said)
            check(f"...nothing ran ({label})", not (clone / "app/deps").exists())
            if "pinned file" in needle:
                # t-1057 F4 (b): the install command in the words is the TABLE's own argv, not a verb in code
                check_in("...the words carry the table's own command", f"`{sys.executable} -c ", said)
                check_not_in("...and no npm verb is written in code", "installs only from", said)
        (clone / "app/manifest.txt").write_text("pinned", encoding="utf-8")
        (clone / "app/deps").mkdir()
        check_in("a folder the install must create, already there, is not a fresh provisioning",
                 "freshly provisioned", refused(lambda: provision(clone, spec), R.SetupRefused))
        (clone / "app/deps").rmdir()
        # one row's problem stops ALL rows before the first run (the order of checks is kept)
        second = dict(spec, cwd="b")
        (clone / "b").mkdir()
        check("all rows are checked before the first runs: a bad second row leaves the first uninstalled", bool(refused(
            lambda: R.provision_dependencies(clone, {"sandbox_setup": [spec, second]}), R.SetupRefused))
              and not (clone / "app/deps").exists())
        # Edge 12 / lexists: a dangling link (POSIX) or junction (Windows) is "already there".
        target = clone / "gone-target"
        link = clone / "app" / "deps"
        target.mkdir()
        try:
            if os.name == "nt":
                made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
                if made.returncode:
                    raise OSError("mklink /J refused")
            else:
                os.symlink(target, link, target_is_directory=True)
        except OSError as error:
            print(f"skipped: dangling link / junction case ({error})")
        else:
            target.rmdir()
            check_in("a DANGLING link or junction where the install is to create its folder is refused (lexists, not exists)",
                     "freshly provisioned", refused(lambda: provision(clone, spec), R.SetupRefused))
            try:
                os.rmdir(link)
            except OSError:
                os.unlink(link)


def failure_checks(root: Path) -> None:
    clone, spec = make_clone(root)
    exact, over = "x" * 500, "y" + "x" * 500
    fail = "import sys; sys.stdout.write({!r}); sys.exit(3)"
    with patch.object(R, "SETUP_KINDS_FILE", table(root, fail.format(exact))):
        try:
            provision(clone, spec)
        except R.SetupFailed as error:
            check_eq("a non-zero exit carries its code and a tail of exactly 500 characters whole",
                     (error.exit_code, error.output_tail), (3, exact))
            check_in("...in the words, with the code", "exit 3", str(error))
        else:
            check("a non-zero exit raised SetupFailed", False)
    with patch.object(R, "SETUP_KINDS_FILE", table(root, fail.format(over))):
        tail = ""
        try:
            provision(clone, spec)
        except R.SetupFailed as error:
            tail = error.output_tail
        check_eq("501 characters of output: the last 500, marked as cut", tail, "..." + exact)
    with patch.object(R, "SETUP_KINDS_FILE", table(root, "pass")):
        check_in("exit 0 but the folder was not created: not ready (I4)", "exit 0 alone cannot establish readiness",
                 refused(lambda: provision(clone, spec), R.SetupFailed))
    with patch.object(R, "SETUP_KINDS_FILE", table(root, "import pathlib; pathlib.Path('deps').mkdir(); "
                                                       "pathlib.Path('manifest.txt').write_text('changed')")):
        check_in("a command that rewrites a pinned file is refused after the fact", "changed pinned input",
                 refused(lambda: provision(clone, spec), R.SetupFailed))
    (clone / "app/manifest.txt").write_text("pinned", encoding="utf-8")
    shutil.rmtree(clone / "app/deps", ignore_errors=True)
    broken = table(root, "pass")
    row = json.loads(broken.read_text(encoding="utf-8"))
    row["kinds"]["fake_touch"]["argv"] = [str(root / "no-such-program-qa"), "ci"]
    broken.write_text(json.dumps(row), encoding="utf-8")
    with patch.object(R, "SETUP_KINDS_FILE", broken):
        words = refused(lambda: provision(clone, spec), R.SetupFailed)
        check_in("a program that cannot start: SetupFailed 'could not be started'", "could not be started", words)
        check_in("...a defect of the machine, not of the stand (D-0032)", "not a property of the stand", words)
        check_in("t-1057 F4 (c): ENOENT is reported with its errno and as 'not on PATH'", "ENOENT", words)
        check_in("...and only ENOENT says 'not on PATH'", "is not on PATH of this machine", words)
    for label, err, code_name in (("a refusal to execute", PermissionError(errno.EACCES, "Permission denied"), "EACCES"),
                                  ("a file that is no program", OSError(errno.ENOEXEC, "Exec format error"), "ENOEXEC")):
        with patch.object(R, "SETUP_KINDS_FILE", table(root, "pass")), \
                patch.object(node_ids.subprocess, "Popen", side_effect=err):
            words = refused(lambda: provision(clone, spec), R.SetupFailed)
        check_in(f"F4 (c): {label}: SetupFailed 'could not be started' with the errno name", f"could not be started: {code_name}", words)
        check_in(f"...and the strerror ({label})", err.strerror, words)
        check_not_in(f"...but never 'not on PATH' for a cause that is not ENOENT ({label})", "not on PATH", words)
        check_in(f"...still a defect of the machine ({label})", "not a property of the stand", words)
    big = "import pathlib, sys; sys.stdout.write('x' * 2097152); sys.stderr.write('y' * 2097152); pathlib.Path('deps').mkdir()"
    with patch.object(R, "SETUP_KINDS_FILE", table(root, big)):
        started = time.monotonic()
        result = provision(clone, spec)
        check_eq("output of 4 MiB (far beyond a pipe buffer) is read to the end and the install is ready",
                 result[0]["status"], "ready")
        check("...without waiting for a limit", time.monotonic() - started < 30)


def timeout_checks(root: Path) -> None:
    """Edge 14: after the limit the whole tree is killed; a grandchild holding the pipe does not extend the wait."""
    clone, spec = make_clone(root)
    child = ("import subprocess, sys, time, pathlib; "
             "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
             "pathlib.Path('gc.pid').write_text(str(p.pid)); time.sleep(120)")
    with patch.object(R, "SETUP_KINDS_FILE", table(root, child, timeout=1)):
        started = time.monotonic()
        words = refused(lambda: provision(clone, spec), R.SetupFailed)
        took = time.monotonic() - started
    check_in("a command past its limit is SetupFailed 'timed out after 1 s'", "timed out after 1 s", words)
    check("the answer comes at the limit plus the kill, not after the grandchild's 120 s nor the 10 s pipe grace "
          f"(took {took:.1f} s)", took < 9)
    pid_file = clone / "app" / "gc.pid"
    if pid_file.exists():   # a regression leaves the grandchild alive: do not leave it running
        pid = pid_file.read_text(encoding="utf-8").strip()
        subprocess.run(["taskkill", "/PID", pid, "/F"] if os.name == "nt" else ["kill", "-9", pid], capture_output=True)


def prepare_checks(parent: Path) -> None:
    """Each clone (mutated and baseline) is provisioned BEFORE its mutation and its collect."""
    source = parent / "author"
    source.mkdir()
    (source / "behavior.py").write_text("before", encoding="utf-8")
    request = {"mutations": [{"path": "behavior.py", "before_sha256": R.digest(source / "behavior.py"),
                              "replacement_utf8": "after", "instance_id": "test",
                              "expected_location": "test.py:1", "expected_reason": "wrong result"}]}
    order, built = [], []

    def setup(root, req, planned=None):
        order.append(("setup", (root / "behavior.py").read_text(encoding="utf-8"), root != source,
                      json.loads((root / ".qa-probe.json").read_text(encoding="utf-8"))["status"]))
        built.append(root)
        return [{"kind": "fake", "status": "ready"}]

    def collect(root, req, mutations, task):
        order.append(("collect", root in built, (root / "behavior.py").read_text(encoding="utf-8")))
        return {"status": "no_pinned_ids"}

    asking = dict(request, sandbox_setup=[{"kind": "fake_touch", "cwd": ".", "manifest_sha256": HEX}])
    with patch.object(R, "SETUP_KINDS_FILE", table(parent)), patch.object(R, "repo_files", return_value={"behavior.py"}), \
            patch.object(R, "provision_dependencies", side_effect=setup), patch.object(R, "check_node_ids", side_effect=collect):
        first = R.prepare(source, parent / "mutated", asking)
        second = R.prepare(source, parent / "baseline", R._unmutated_variant(source, asking))
        plain = R.prepare(source, parent / "plain", request)
    check_eq("prepare: both clones were provisioned, each while still unmutated, still `preparing`, never the author tree",
             [row for row in order if row[0] == "setup"], [("setup", "before", True, "preparing")] * 2)
    check_eq("prepare: the collect ran after the provisioning of the same clone, on the mutated bytes where mutated",
             [row for row in order if row[0] == "collect"][:2], [("collect", True, "after"), ("collect", True, "before")])
    check_eq("prepare: the dependency_setup receipt is the same on the mutated and the baseline clone",
             (first["dependency_setup"], second["dependency_setup"]),
             ([{"kind": "fake", "status": "ready"}], [{"kind": "fake", "status": "ready"}]))
    check("prepare: a request without sandbox_setup installs nothing and writes no receipt field",
          "dependency_setup" not in plain and len([r for r in order if r[0] == "setup"]) == 2)
    check_eq("prepare: the author tree is untouched", (source / "behavior.py").read_text(encoding="utf-8"), "before")
    check_eq("prepare: the mutated clone holds the mutation, the baseline the author bytes",
             ((parent / "mutated/behavior.py").read_text(encoding="utf-8"),
              (parent / "baseline/behavior.py").read_text(encoding="utf-8")), ("after", "before"))

    def failing(root, req, planned=None):
        raise R.SetupFailed("sandbox npm_ci failed (exit 1); no tests launched", exit_code=1)

    with patch.object(R, "SETUP_KINDS_FILE", table(parent)), patch.object(R, "repo_files", return_value={"behavior.py"}), \
            patch.object(R, "provision_dependencies", side_effect=failing), patch.object(R, "check_node_ids") as collect_call:
        check_in("prepare: a failed install is the preparation's refusal", "no tests launched",
                 refused(lambda: R.prepare(source, parent / "refused", asking), R.SetupFailed))
        check_eq("prepare: ...nothing was collected", collect_call.call_count, 0)
        check("prepare: ...and the half-made clone is removed, so a corrected request is not told 'must be new'",
              not (parent / "refused").exists())
    with patch.object(R, "repo_files", return_value={"behavior.py"}), patch.object(R.shutil, "copy2", side_effect=ValueError("copy broke")):
        refused(lambda: R.prepare(source, parent / "copyfail", request))
        check("prepare: a failed COPY removes the clone as well (the copy is inside the same cleanup)", not (parent / "copyfail").exists())

    # A wrong request costs no clone: the form is judged before the destination exists (P11).
    with patch.object(R, "SETUP_KINDS_FILE", table(parent)), patch.object(R, "repo_files") as listed, \
            patch.object(R.Path, "mkdir") as made:
        for label, bad in (("an unknown kind", [{"kind": "shell", "cwd": "."}]), ("an escaping cwd", [{"kind": "fake_touch", "cwd": "../x", "manifest_sha256": HEX}])):
            check_in(f"prepare: {label} is refused as a SetupRefused", "sandbox_setup",
                     refused(lambda: R.prepare(source, parent / "never", dict(request, sandbox_setup=bad)), R.SetupRefused))
        check_eq("prepare: ...before the file list is read and before any folder is made", (listed.call_count, made.call_count), (0, 0))
    check("prepare: ...so no destination exists", not (parent / "never").exists())

    # Edge 13 / real flow: a mutation of the PINNED file is written after the install, which ran on the author's bytes.
    real = parent / "real"
    real.mkdir()
    (real / "manifest.txt").write_text("pinned", encoding="utf-8")
    pin = {"path": "manifest.txt", "before_sha256": R.digest(real / "manifest.txt"), "replacement_utf8": "changed",
           "instance_id": "i", "expected_location": "t.py:1", "expected_reason": "r"}
    asking = {"mutations": [pin], "sandbox_setup": [{"kind": "fake_touch", "cwd": ".", "manifest_sha256": R.digest(real / "manifest.txt")}]}
    with patch.object(R, "SETUP_KINDS_FILE", table(parent, TOUCH)), patch.object(R, "repo_files", return_value={"manifest.txt"}):
        got = R.prepare(real, parent / "real-clone", asking)
        check_eq("a mutation of the pinned file: installed on the author's bytes, mutated after, the receipt names the author's pin",
                 ((parent / "real-clone/deps/env.txt").read_text(encoding="utf-8"), (parent / "real-clone/manifest.txt").read_text(encoding="utf-8"),
                  got["dependency_setup"][0]["manifest_sha256"] == pin["before_sha256"]), ("marked", "changed", True))
        check_eq("...and the receipt file on disk carries it", json.loads((parent / "real-clone/.qa-probe.json").read_text(
            encoding="utf-8"))["dependency_setup"][0]["status"], "ready")
        # the installs of the second clone get what the first left: a budget used up refuses with the key named
        words = refused(lambda: R.prepare(real, parent / "late-clone", asking, budget_s=59), R.SetupRefused)
        check_in("a second clone with less budget left than its install may take is refused naming the key", "sandbox.install_timeout_s", words)
        check_eq("...a budget that exactly fits (the row's 60 s) passes",
                 R.prepare(real, parent / "fit-clone", asking, budget_s=60)["status"], "prepared")


def receipt_checks(parent: Path) -> None:
    """The dependency_setup rows reach the sensitivity proof, under its hash."""
    repo, task = parent / "repo", parent / "task"
    repo.mkdir()
    task.mkdir()
    setup = [{"kind": "npm_ci", "cwd": "e2e", "status": "ready", "lock_sha256": "l" * 64}]
    probe_receipt = {"repo": str(repo), "original_hashes": {}, "dependency_setup": setup,
                     "targets": [{"instance_id": INSTANCE, "expected_location": "test.py:1",
                                  "expected_reason": "boom", "replacement_utf8": "x"}]}
    results = [{"instance_id": INSTANCE, "status": "failed", "failure_kind": "assertion", "location": "test.py:1",
                "reason": "boom", "semantic_verdict": "intended_failure"}]
    bindings = {INSTANCE: {"case_version": "1", "test_content_hash": "h", "source_revision": "r",
                           "build_id": "b", "restoration_evidence": "e"}}
    base = [{"instance_id": INSTANCE, "status": "passed"}]

    def proof_of():
        refs = R.write_sensitivity_receipts(task, probe_receipt, results, bindings, baseline=base)
        return json.loads((task / refs[INSTANCE]["receipt_ref"]["path"]).read_text(encoding="utf-8"))

    proof = proof_of()
    check_eq("the sensitivity proof carries the dependency_setup it was measured on", proof.get("dependency_setup"), setup)
    check_eq("...inside the receipt hash, not beside it", proof["receipt_hash"],
             content_hash({k: v for k, v in proof.items() if k != "receipt_hash"}))
    with_setup = proof["receipt_hash"]
    del probe_receipt["dependency_setup"]
    proof = proof_of()
    check("a probe without provisioning writes no dependency_setup field", "dependency_setup" not in proof)
    check("...and its hash differs from the provisioned one (the field is part of what was measured)", proof["receipt_hash"] != with_setup)


def cli_checks(parent: Path) -> None:
    """The simple CLI answers a refusal and a failed install with one JSON line and an exit code, never a traceback."""
    repo = parent / "cli-author"
    repo.mkdir()
    (repo / "manifest.txt").write_text("pinned", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)
    pin = {"path": "manifest.txt", "before_sha256": R.digest(repo / "manifest.txt"), "replacement_utf8": "changed",
           "instance_id": "i", "expected_location": "t.py:1", "expected_reason": "r"}
    sha = R.digest(repo / "manifest.txt")

    def cli(setup, name, **cfg):
        request = parent / f"{name}.json"
        request.write_text(json.dumps({"mutations": [pin], "sandbox_setup": setup}), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        argv = ["red_sandbox.py", "--repo", str(repo), "--destination", str(parent / f"{name}-clone"), "--request", str(request)]
        code = None
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                R.main()
            except SystemExit as stop:
                code = stop.code
        return code, out.getvalue(), err.getvalue()

    with patch.object(R, "SETUP_KINDS_FILE", table(parent, "import sys; sys.stdout.write('boom'); sys.exit(4)")):
        code, out, err = cli([{"kind": "nothing", "cwd": "."}], "refused")
        said = json.loads(out)
        check_eq("CLI: a refused sandbox_setup is exit 2 and a JSON refusal", (code, said["status"]), (2, "refused"))
        check_in("CLI: ...saying which kind and the door", "probe without sandbox_setup", said["message"])
        check_not_in("CLI: ...with no traceback", "Traceback", err)
        code, out, err = cli([{"kind": "fake_touch", "cwd": ".", "manifest_sha256": sha}], "failed")
        said = json.loads(out)
        check_eq("CLI: a failed install is exit 1 and a JSON line", (code, said["status"]), (1, "setup_failed"))
        check_eq("CLI: ...with the exit code and the output tail of the command", (said["exit_code"], said["output_tail"]), (4, "boom"))
        check_not_in("CLI: ...and no traceback", "Traceback", err)
        check("CLI: ...and the clone was removed", not (parent / "failed-clone").exists())


def main() -> None:
    run_mine_checks()
    for check_set in (table_checks, plan_checks, budget_checks, shipped_npm_checks, fake_kind_checks, guard_checks,
                      failure_checks, timeout_checks, prepare_checks, receipt_checks, cli_checks):
        with tempfile.TemporaryDirectory() as tmp:
            check_set(Path(tmp).resolve())
    finish("test_red_sandbox_setup")


if __name__ == "__main__":
    main()
