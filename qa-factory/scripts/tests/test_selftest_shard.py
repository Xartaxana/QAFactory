"""`selftest.py --shard I/N` splits a full run's test files so the release run fits the CI hour (F6-50, t-1702 D2).

Pins (keys S1-S8): `1/1` is the full list and, for N in 1..5, the shards are disjoint with the full list as their union
and do not depend on which shard is asked; every invalid value is exit 2 with the expected form; N larger than the number
of files leaves empty shards that print an explicit note and pass; the refused flag combinations; in a flagless run
shard 1 runs every non-test check and a shard I > 1 only its tests and the hygiene; the header line; the join of the
saved shard outputs read by `--slow-tests --from` (complete, missing, repeated, mixed N, no header); the
longest-processing-time order and the tie by name.

The command-line cases run a COPY of selftest.py in a temp package, so the data file and the tests folder they see are
temp ones. Nothing here waits on the clock (FR-31): the partition is a pure function."""
import contextlib
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import selftest as S  # noqa: E402

NAMES = [f"test_{c}.py" for c in "abcdefg"]
WEIGHTS = {"test_a.py": 40.0, "test_b.py": 30.0, "test_c.py": 20.0, "test_d.py": 10.0, "test_e.py": None}


def paths(names):
    return [Path("t") / n for n in names]


def names_of(parts):
    return [[f.name for f in part] for part in parts]


def partition_cases() -> None:
    files = paths(NAMES)
    check_eq("S1: 1/1 is the full list", names_of(S.shard_files(files, WEIGHTS, 1)), [NAMES])
    for n in range(1, 6):
        parts = S.shard_files(files, WEIGHTS, n)
        flat = [f.name for part in parts for f in part]
        check(f"S1: N={n}: {n} shards, pairwise disjoint, the union is the full list",
              len(parts) == n and len(flat) == len(set(flat)) and sorted(flat) == sorted(NAMES), repr(names_of(parts)))
        check_eq(f"S1: N={n}: the split does not depend on the order the files are handed in",
                 names_of(S.shard_files(list(reversed(files)), WEIGHTS, n)), names_of(parts))
    check_eq("E-D2-3: a listed-but-absent file is not partitioned, an unlisted one takes the default weight",
             sorted(f.name for part in S.shard_files(paths(["test_a.py", "test_new.py"]), {"test_gone.py": 99}, 2)
                    for f in part), ["test_a.py", "test_new.py"])

    # S8: LPT. Each file, in descending weight, goes to the least-loaded shard.
    four = paths(["test_a.py", "test_b.py", "test_c.py", "test_d.py"])
    check_eq("S8: longest-processing-time greedy: 40|30, then 20 to the 30-shard, 10 to the 40-shard",
             names_of(S.shard_files(four, WEIGHTS, 2)), [["test_a.py", "test_d.py"], ["test_b.py", "test_c.py"]])
    check_eq("S8: modulo-by-index would differ: the shape above is not [a,c] / [b,d]",
             names_of(S.shard_files(four, WEIGHTS, 2)) != [["test_a.py", "test_c.py"], ["test_b.py", "test_d.py"]], True)
    equal = paths(["test_z.py", "test_m.py", "test_a.py"])
    check_eq("S8: equal weights: sorted by name, the tie goes to the lowest shard index",
             names_of(S.shard_files(equal, {}, 2, default=1.0)), [["test_a.py", "test_z.py"], ["test_m.py"]])
    check_eq("S8: a listed null weight counts as the default", names_of(S.shard_files(
        paths(["test_e.py", "test_f.py"]), {"test_e.py": None, "test_f.py": 3.0}, 2, default=3.0)),
        [["test_e.py"], ["test_f.py"]])
    check_eq("N past the file count: the extra shards are empty lists, not missing",
             names_of(S.shard_files(paths(["test_a.py"]), {}, 3)), [["test_a.py"], [], []])


def parse_cases() -> None:
    for good, want in (("1/1", (1, 1)), ("2/2", (2, 2)), ("1/9", (1, 9)), ("3/5", (3, 5))):
        check_eq(f"S2: {good!r} parses", S.parse_shard(good), want)
    for bad in ("0/2", "3/2", "1/0", "2", "a/b", "1/2/3", "-1/2", "", "1/", "/2", " 1/2", "1/2 ", "1/-2", "١/٢",
                "1/" + "9" * 5000):
        check_eq(f"S2: {bad[:12]!r} is refused", S.parse_shard(bad), None)


def tests_dir_with(root: Path, names) -> None:
    tests = root / "scripts" / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    for name in names:
        (tests / name).write_text("import sys\nsys.exit(0)\n", encoding="utf-8")


def cli(args, root: Path, name: str, tests=NAMES[:4], weights=None, artifact: str | None = None, layers=None,
        bodies=None):
    pkg = root / name
    scripts = pkg / "scripts"
    tests_dir_with(pkg, tests)
    for fname, source in (bodies or {}).items():
        (scripts / "tests" / fname).write_text(source, encoding="utf-8")
    if layers is not None:
        (scripts / "tests" / "test-layers.json").write_text(layers if isinstance(layers, str) else json.dumps(layers),
                                                            encoding="utf-8")
    for module in ("selftest.py", "content_size.py", "console_io.py"):
        shutil.copy2(PLUGIN_ROOT / "scripts" / module, scripts / module)
    body = {"measured_on": "2026-01-01", "source": "hand", "thresholds": {"slow_over_s": 10, "fast_under_s": 5},
            "max_drift": 5, "files": weights or {}}
    (scripts / "slow_tests.json").write_text(json.dumps(body), encoding="utf-8")
    if artifact is not None:
        (pkg / "selftest.txt").write_text(artifact, encoding="utf-8")
    argv = [a.replace("@ART", str(pkg / "selftest.txt")).replace("@OUT", str(pkg / "out" / "sub" / "w.json")) for a in args]
    return subprocess.run([sys.executable, "-B", str(scripts / "selftest.py"), *argv], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(pkg), timeout=120)


def cli_cases(root: Path) -> None:
    for i, bad in enumerate(("0/2", "3/2", "1/0", "2", "a/b", "1/2/3", "-1/2")):
        p = cli(["--tests", f"--shard={bad}"], root, f"bad{i}")      # `=` form: "-1/2" would read as an option
        check(f"S2/E-D2-1: --shard {bad} = exit 2, the form 'I/N with 1 <= I <= N' on stderr, nothing run",
              p.returncode == 2 and "1 <= I <= N" in p.stderr and "e.g. 1/2" in p.stderr and "PASS" not in p.stdout,
              f"{p.returncode} {p.stderr[-200:]!r}")

    p = cli(["--tests", "--jobs", "1", "--shard", "1/2"], root, "run12", weights={"test_a.py": 20.0})
    lines = p.stdout.splitlines()
    check("S6: the header is the first line: `selftest shard 1/2: K of M test files`",
          p.returncode == 0 and lines[0] == "selftest shard 1/2: 1 of 4 test files", f"{p.returncode} {lines[:2]!r}")
    check_in("the summary names the shard", "=== qa-factory selftest (shard 1/2): 1/1 ok ===", p.stdout)
    p2 = cli(["--tests", "--jobs", "1", "--shard", "2/2"], root, "run22", weights={"test_a.py": 20.0})
    ran = [ln.split()[2].replace("\\", "/") for ln in p.stdout.splitlines() + p2.stdout.splitlines()
           if ln.startswith("PASS tests: scripts")]
    check_eq("two shards of one pipeline run every file exactly once", sorted(ran),
             sorted(f"scripts/tests/{n}" for n in NAMES[:4]))

    p = cli(["--tests", "--jobs", "1", "--shard", "5/5"], root, "empty", tests=NAMES[:2])
    check("S3/E-D2-2: N > files: the header says 0 of 2, the explicit note is printed, a PASS, exit 0",
          p.returncode == 0 and p.stdout.splitlines()[0] == "selftest shard 5/5: 0 of 2 test files"
          and "tests: shard 5/5: 0 test files (explicit note)" in p.stdout and "PASS tests: shard 5/5" in p.stdout,
          f"{p.returncode} {p.stdout!r}")
    p = cli(["--tests", "--shard", "1/1000000000"], root, "huge", tests=NAMES[:2])
    check_eq("an absurd N is cheap and passes with shard 1 of two files", p.returncode, 0)

    for k, (label, args) in enumerate((("--fast", ["--fast"]), ("--slow-tests", ["--slow-tests", "--from", "@ART"]),
                                       ("--lang without --tests", ["--lang"]), ("--hygiene alone", ["--hygiene"]),
                                       ("--ping", ["--ping"]))):
        p = cli([*args, "--shard", "1/2"], root, f"refuse{k}", artifact="x\n")
        check(f"S4/E-D2-4: --shard with {label} is refused at argparse (exit 2, nothing run)",
              p.returncode == 2 and "--shard" in p.stderr and "PASS" not in p.stdout, f"{p.returncode} {p.stderr[-200:]!r}")


def spy_run(argv) -> tuple[list, int]:
    """main() in-process with every check replaced by a recorder; returns (the checks that ran, the exit code)."""
    ran: list = []

    def recorder(name):
        def fn(*args, **kwargs):
            ran.append((name, kwargs.get("shard")))
            return True
        return fn

    names = ("cmd_selftest_scripts", "cmd_roots", "cmd_lang", "cmd_limits", "cmd_wiring", "cmd_slices", "cmd_homes",
             "cmd_hygiene", "cmd_tests")
    stack = contextlib.ExitStack()
    with stack:
        for name in names:
            stack.enter_context(patch.object(S, name, recorder(name)))
        stack.enter_context(patch.object(sys, "argv", ["selftest.py", *argv]))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        with patch.dict("sys.modules", {"console_io": type("M", (), {"utf8_stdio": staticmethod(lambda: None)})}):
            try:
                S.main()
                code = 0
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
    return ran, code


def flagless_cases() -> None:
    ran, code = spy_run(["--shard", "1/2"])
    check_eq("S5: flagless shard 1/2 runs every check of the flagless run, its tests sharded",
             ([n for n, _ in ran], dict(ran)["cmd_tests"], code),
             (["cmd_selftest_scripts", "cmd_roots", "cmd_lang", "cmd_limits", "cmd_wiring", "cmd_slices", "cmd_tests",
               "cmd_homes", "cmd_hygiene"], (1, 2), 0))
    ran, code = spy_run(["--shard", "2/2"])
    check_eq("S5: flagless shard 2/2 runs only its tests and the hygiene",
             ([n for n, _ in ran], dict(ran)["cmd_tests"], code), (["cmd_tests", "cmd_hygiene"], (2, 2), 0))
    ran, code = spy_run([])
    check_eq("S5: with no --shard the flagless run is what it was: the same nine checks, no shard",
             ([n for n, _ in ran], dict(ran)["cmd_tests"]),
             (["cmd_selftest_scripts", "cmd_roots", "cmd_lang", "cmd_limits", "cmd_wiring", "cmd_slices", "cmd_tests",
               "cmd_homes", "cmd_hygiene"], None))
    ran, code = spy_run(["--tests", "--shard", "2/3"])
    check_eq("S5: --tests --shard runs only the tests", [n for n, _ in ran], ["cmd_tests"])


def execution_path_cases() -> None:
    """t-1755 F7: `cmd_tests` selects its files through the tested `shard_files`, not through its own copy."""
    seen: list = []
    calls: list = []
    real = S.shard_files

    def spy(files, weights, n, default=0.0):
        calls.append(n)
        return real(files, weights, n, default)

    with patch.object(S, "shard_files", spy), patch.object(S, "_run_test_file", lambda f: seen.append(f.name) or True), \
            contextlib.redirect_stdout(io.StringIO()):
        ok = S.cmd_tests(workers=1, shard=(2, 3))
        # the same selection cmd_tests makes: the quarantine rows of test-layers.json are in no shard
        canon = S._quarantine_branch(S.test_layers()["quarantine"], False)[0]
        expected = [[p.name for p in part] for part in real(canon, S.slow_tests()["files"], 3,
                                                           S.slow_tests()["thresholds"]["fast_under_s"] / 2)]
    check("F7: cmd_tests calls shard_files (the spy saw it, asked for 3 shards)", calls == [3] and ok, str(calls))
    check_eq("F7: the files it ran are shard 2 of shard_files' own split", seen, expected[1])
    calls.clear()
    seen.clear()
    with patch.object(S, "shard_files", spy), patch.object(S, "_run_test_file", lambda f: seen.append(f.name) or True), \
            contextlib.redirect_stdout(io.StringIO()):
        S.cmd_tests(workers=1, shard=(1, 10 ** 9))
    check("F7: an absurd N asks shard_files for no more shards than there are files", calls and calls[0] <= 10 ** 4, str(calls))


def header(i, n, k=3, m=6) -> str:
    return f"selftest shard {i}/{n}: {k} of {m} test files\nPASS tests: scripts/tests/test_x{i}.py  1.0s\n"


def join_cases(root: Path) -> None:
    ok = header(1, 2) + header(2, 2)
    check_eq("S7: shards 1..N each once: no problem", S.shard_join_problem(ok), None)
    check_eq("S7: no header at all (a whole run): today's behaviour, no problem",
             S.shard_join_problem("PASS tests: scripts/tests/test_a.py  1.0s\n"), None)
    check_eq("S7: a shard order of 2 then 1 is still complete", S.shard_join_problem(header(2, 2) + header(1, 2)), None)
    missing = S.shard_join_problem(header(1, 2))
    check("S7: a missing shard is named", missing is not None and "missing [2]" in missing and "of 2" in missing, missing)
    repeated = S.shard_join_problem(header(1, 2) + header(2, 2) + header(2, 2))
    check("S7: a repeated shard is named", repeated is not None and "repeated [2]" in repeated, repeated)
    mixed = S.shard_join_problem(header(1, 2) + header(2, 3))
    check("S7: mixed totals are named", mixed is not None and "mixed totals yes" in mixed and "of 2, 3" in mixed, mixed)
    check("S7: the message tells how to fix it", "concatenate every shard's output once" in (missing or ""))
    lone = S.shard_join_problem(header(1, 1))
    check_eq("S7: 1/1 alone is complete", lone, None)
    check("S7: a header past N (3/2) is a problem", S.shard_join_problem(header(1, 2) + header(2, 2) + header(3, 2)) is not None)
    check("S7: a header glued behind other text is no header (it must start a line)",
          S.shard_join_problem("x selftest shard 1/2: 1 of 2 test files\n") is None)

    measured = "PASS tests: scripts/tests/test_a.py  12.0s\n"
    weights = {"test_a.py": 12.0}
    for label, text, code in (("complete", header(1, 2) + header(2, 2) + measured, 0),
                              ("missing one", header(1, 2) + measured, 2),
                              ("repeated", header(1, 2) + header(2, 2) + header(2, 2) + measured, 2),
                              ("mixed N", header(1, 2) + header(2, 3) + measured, 2),
                              ("no header", measured, 0)):
        p = cli(["--slow-tests", "--from", "@ART"], root, "join-" + label.replace(" ", ""), tests=["test_a.py"],
                weights=weights, artifact=text)
        check(f"S7/E-D2-6 CLI: {label}: exit {code}" + (" and one stderr line naming it" if code == 2 else ""),
              p.returncode == code and (code == 0 or (len(p.stderr.strip().splitlines()) == 1
                                                      and "concatenate every shard's output once" in p.stderr
                                                      and "slow tests:" in p.stderr)),
              f"{p.returncode} {p.stderr!r} {p.stdout!r}")
        if code == 2:
            check(f"S7 CLI: {label}: nothing is measured (no diff on stdout)", "unchanged" not in p.stdout, p.stdout)
    p = cli(["--slow-tests", "--from", "@ART", "--update"], root, "join-update", tests=["test_a.py"], weights=weights,
            artifact=header(1, 2) + measured)
    check_eq("S7: an incomplete join is never written by --update (exit 2)", p.returncode, 2)


QROW = {"cohort": "c1", "entered": "2026-11-20", "release_at_entry": "0.10.9"}


def layers_doc(keep, quarantine, enforce=True) -> dict:
    return {"enforce_listing": enforce, "cohorts": {"c1": {}}, "pin_holds": {}, "quarantine": {n: dict(QROW) for n in quarantine},
            "keep": {n: ({"layer": "detector", "why": "w", "named_by": ["x"], "replaced_by": None} if n == "test_det.py"
                         else {"layer": "table", "why": "w"}) for n in keep}}


def ran_names(*outs) -> list:
    return sorted(ln.split()[2].replace("\\", "/").split("/")[-1] for out in outs for ln in out.splitlines()
                  if ln.startswith(("PASS tests: scripts", "FAIL tests: scripts")))


def layers_cli_cases(root: Path) -> None:
    """TD-15.1 items 3 and 5: quarantine filtered before the shards and --fast; --quarantined; the watch record."""
    four = ["test_keep.py", "test_det.py", "test_quar.py", "test_unl.py"]
    doc = layers_doc(["test_keep.py", "test_det.py"], ["test_quar.py"])
    one = cli(["--tests", "--jobs", "1", "--shard", "1/2"], root, "lay1", tests=four, layers=doc)
    two = cli(["--tests", "--jobs", "1", "--shard", "2/2"], root, "lay1", tests=four, layers=doc)
    check_eq("layers: the shards of 4 files (keep, detector, quarantine, unlisted) hold keep + detector + unlisted, not the quarantine",
             ran_names(one.stdout, two.stdout), ["test_det.py", "test_keep.py", "test_unl.py"])
    check("layers: `unlisted:` names the file once, with the door; the quarantine count is printed; exit 1",
          (one.stdout + two.stdout).count("FAIL tests: unlisted: test_unl.py -- add a keep row") == 1
          and "tests: quarantine: 1 file(s) not run (scripts/tests/test-layers.json)" in one.stdout
          and one.stdout.splitlines()[0].startswith("selftest shard 1/2: ") and 1 in (one.returncode, two.returncode),
          f"{one.stdout!r} {two.stdout!r}")
    p = cli(["--tests", "--jobs", "1", "--quarantined"], root, "lay1", tests=four, layers=doc)
    check("layers: --quarantined runs only the quarantine row, exit 0, the count line",
          ran_names(p.stdout) == ["test_quar.py"] and p.returncode == 0 and "tests: quarantine: 1 files" in p.stdout, p.stdout)
    for label, doc2, want in (("empty keep", layers_doc([], ["test_quar.py"]), "tests: keep list empty"),
                              ("a keep row without a file", layers_doc(four[:2] + ["test_ghost.py"], []),
                               "tests: keep row names no file: test_ghost.py")):
        p = cli(["--tests", "--jobs", "1"], root, "lay2", tests=four[:2], layers=doc2)
        check(f"layers: enforce_listing, {label}: one FAIL line, the files still run, exit 1",
              p.stdout.count("FAIL " + want) == 1 and "unlisted:" not in p.stdout and p.returncode == 1
              and len(ran_names(p.stdout)) == 2, p.stdout)
    pinned = layers_doc(["test_keep.py"], [])
    pinned["pin_holds"] = {"test_pin.py": "role pin"}
    p = cli(["--tests", "--jobs", "1"], root, "lay5", tests=["test_keep.py", "test_pin.py"], layers=pinned)
    check("layers: a pin-held file with enforce_listing runs and prints no `unlisted:` line, exit 0",
          ran_names(p.stdout) == ["test_keep.py", "test_pin.py"] and "unlisted:" not in p.stdout and p.returncode == 0, p.stdout)
    pinned["pin_holds"] = {}
    p = cli(["--tests", "--jobs", "1"], root, "lay6", tests=["test_keep.py", "test_pin.py"], layers=pinned)
    check("layers: the same file with the pin row removed is `unlisted:`, still runs, exit 1",
          ran_names(p.stdout) == ["test_keep.py", "test_pin.py"] and p.stdout.count("FAIL tests: unlisted: test_pin.py -- add a keep row") == 1
          and p.returncode == 1, p.stdout)
    cli(["--ping"], root, "lay3", tests=four, layers=doc)
    pkg3 = root / "lay3"
    with patch.object(S, "PLUGIN_ROOT", pkg3), patch.object(S, "TESTS_DIR", pkg3 / "scripts" / "tests"), \
            patch.object(S, "SLOW_TESTS_FILE", pkg3 / "scripts" / "slow_tests.json"), patch.object(S, "RESULTS", []), \
            contextlib.redirect_stdout(io.StringIO()) as out:
        S.cmd_tests(1, True)
    check("layers: --fast does not run the quarantine", "test_quar.py" not in out.getvalue()
          and "test_keep.py" in out.getvalue(), out.getvalue())

    reds = {"test_red.py": "print('FAIL first check')\nprint('FAIL second check')\nraise SystemExit(1)\n",
            "test_crash.py": "raise RuntimeError('boom')\n", "test_ok.py": "pass\n"}
    p = cli(["--quarantined", "--jobs", "1", "--watch-out", "@OUT"], root, "lay4", tests=["test_ok.py"], bodies=reds,
            layers=layers_doc([], ["test_red.py", "test_crash.py", "test_ok.py", "test_gone.py"]))
    record = json.loads((root / "lay4" / "out" / "sub" / "w.json").read_text(encoding="utf-8"))
    files = record["files"]
    check("watch: the folder is created, exit 0 with red files, expected = the shard's names, a record per name",
          p.returncode == 0 and record["expected"] == ["test_crash.py", "test_gone.py", "test_ok.py", "test_red.py"]
          and record["shard"] == "1/1" and {"sha", "package_version"} <= set(record), f"{p.returncode} {record!r}")
    check("watch: red carries both FAIL names, the crash carries the exception line, the absent file is `missing`",
          files["test_red.py"]["status"] == "red" and [f[:12] for f in files["test_red.py"]["fails"]] == ["first check", "second check"]
          and files["test_crash.py"]["crash"] == "RuntimeError: boom" and files["test_gone.py"]["status"] == "missing"
          and files["test_ok.py"]["status"] == "green", repr(files))

    p = cli(["--quarantined", "--watch-out", "@OUT"], root, "lay5", layers=layers_doc(four, []))
    record = json.loads((root / "lay5" / "out" / "sub" / "w.json").read_text(encoding="utf-8"))
    check("zero quarantine rows: the line `tests: quarantine: 0 files`, an empty record, exit 0",
          p.returncode == 0 and "tests: quarantine: 0 files" in p.stdout and record["expected"] == [] and record["files"] == {},
          f"{p.stdout!r} {record!r}")
    # TD-15.2: exit 0 covers the quarantine run only; another check flag in the same call keeps its own verdict
    clean = cli(["--quarantined", "--lang"], root, "lay8", tests=["test_ok.py"], bodies=reds, layers=layers_doc([], ["test_red.py"]))
    (root / "lay8" / "notes.md").write_text(chr(0x416) + "\n", encoding="utf-8")
    dirty = cli(["--quarantined", "--lang"], root, "lay8", tests=["test_ok.py"], bodies=reds, layers=layers_doc([], ["test_red.py"]))
    check("layers: --quarantined --lang: a red quarantine file alone = exit 0 (control), a failing --lang beside it = exit 1",
          clean.returncode == 0 and dirty.returncode == 1 and "FAIL lang:" in dirty.stdout,
          f"{clean.returncode} {dirty.returncode} {dirty.stdout[-300:]!r}")
    for label, args, words in (("--quarantined with --fast", ["--quarantined", "--fast"], ("--quarantined", "--fast")),
                               ("--quarantined with --slow-tests", ["--quarantined", "--slow-tests"], ("--quarantined", "--slow-tests")),
                               ("--watch-out alone", ["--tests", "--watch-out", "@OUT"], ("--watch-out", "--quarantined"))):
        p = cli(args, root, "lay6", layers=doc)
        check(f"layers: {label} is refused naming the pair (exit 2, nothing run)",
              p.returncode == 2 and all(w in p.stderr for w in words) and "PASS" not in p.stdout, p.stderr[-200:])
    p = cli(["--tests"], root, "lay7", layers="{ broken")
    check("layers: a broken file = exit 2, one stderr sentence naming test-layers.json, nothing run",
          p.returncode == 2 and "test-layers.json" in p.stderr and len(p.stderr.strip().splitlines()) == 1
          and "PASS" not in p.stdout, p.stderr)


def main() -> None:
    root = temp_dir("shard-")
    try:
        layers_cli_cases(root)
        partition_cases()
        parse_cases()
        cli_cases(root)
        flagless_cases()
        execution_path_cases()
        join_cases(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    finish("test_selftest_shard")


if __name__ == "__main__":
    main()
