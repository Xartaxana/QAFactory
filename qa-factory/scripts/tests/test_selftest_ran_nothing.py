"""TR2-12: a test file that executed nothing is red in the package selftest.

selftest judges a test file by its exit code. A pytest-style file (functions `test_*`, no entry) run as a
script defines functions, prints nothing and exits 0 - fourteen such files were invisible this way, and a stale
craft pin stayed unseen. `selftest.ran_nothing` flags exit 0 + no output + `test_*` definitions; a script-style
file with its own tally prints, so it cannot turn red by this. Checked on synthetic files through the real
`_test_outcome`, with negative controls, and on the real tests directory (no file defines `test_*` without an entry).
"""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import SCRIPTS, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import selftest as ST  # noqa: E402

TESTS_DIR = Path(__file__).resolve().parent
ENTRY = 'if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))\n'

root = temp_dir("ran-nothing-")


def write(name: str, text: str) -> Path:
    p = root / name
    p.write_text(text, encoding="utf-8", newline="\n")
    return p


def run(p: Path):
    return ST._test_outcome(p)


# 1. a pytest-style file with no entry: exit 0, nothing printed, red with the refusal text
silent = write("test_silent.py", "def test_a():\n    assert 1 == 2\n")
_, ok, detail, _ = run(silent)
check("a file with test_ functions and no entry is red", not ok, detail)
check("the refusal says what to do", "ran nothing: add a script entry" in detail and "pytest-run" not in detail, detail)

# 2. the same file with the entry: the checks run and are counted (the failing assert makes it red for its own reason)
failing = write("test_entry_fail.py", "import pytest\n\n\ndef test_a():\n    assert 1 == 2\n\n\n" + ENTRY)
_, ok, detail, _ = run(failing)
check("a file with the entry runs its checks: a failing assert is red", not ok and "ran nothing" not in detail, detail)
passing = write("test_entry_pass.py", "import pytest\n\n\ndef test_a():\n    assert 1 == 1\n\n\n" + ENTRY)
_, ok, detail, _ = run(passing)
check("a file with the entry and a passing check is green", ok, detail)

# 3. the entry with nothing collected is pytest exit 5: red, as the spec says
none = write("test_none_collected.py", "import pytest\n\n\ndef helper():\n    pass\n\n\n" + ENTRY)
_, ok, detail, _ = run(none)
check("pytest exit 5 (no tests collected) is red", not ok and detail.startswith("exit 5"), detail)

# 4. NEGATIVE CONTROLS: a working script-style file must not turn red
script = write("test_script.py", "def test_a():\n    pass\n\n\nprint('=== x: 1/1 ok ===')\n")
_, ok, detail, _ = run(script)
check("control: a script-style file that prints its tally stays green", ok, detail)
quiet = write("test_quiet_tool.py", "x = 1\n")
_, ok, detail, _ = run(quiet)
check("control: a silent file with no test_ functions is not judged by this rule", ok, detail)
inner = write("test_string_only.py", "TEXT = 'def test_x(): pass'\n")
check_eq("control: a def inside a string literal that does not start a line is not a test", ST.ran_nothing(inner, "", ""), False)
# a working silent script whose fixture string holds a line-start `def test_x():` stays green (an ast walk, not text)
fixture = write("test_fixture_string.py", 'FIXTURE = """\ndef test_x():\n    pass\n"""\nx = 1\n')
_, ok, detail, _ = run(fixture)
check("control: a def at a line start inside a triple-quoted string is not a test (stays green)", ok, detail)
check_eq("a tally with a non-zero total is evidence of execution", ST.ran_nothing(silent, "=== x: 3/3 ok ===", ""), False)
check_eq("a pytest summary with a passed test is evidence of execution", ST.ran_nothing(silent, "2 passed in 0.1s", ""), False)

# 4b. FAIL OPEN: output that is not evidence of a check is still 'ran nothing'
zero = write("test_zero_tally.py", "import sys\nfrom pathlib import Path\nsys.path.insert(0, %r)\nfrom harness import finish\n\n\n"
             "def test_a():\n    pass\n\n\nfinish('x')\n" % str(TESTS_DIR))
_, ok, detail, _ = run(zero)
check("a real 0/0 tally from finish() is red", not ok and "ran nothing" in detail, detail)
skipped = write("test_all_skipped.py", "import pytest\n\n\n@pytest.mark.skip(reason='r')\ndef test_a():\n    pass\n\n\n" + ENTRY)
_, ok, detail, _ = run(skipped)
check("an entry whose every test is skipped is red", not ok and "ran nothing" in detail, detail)
printed = write("test_print_at_import.py", "print('hello')\n\n\ndef test_a():\n    assert 1 == 2\n")
_, ok, detail, _ = run(printed)
check("output at import is not 'ran'", not ok and "ran nothing" in detail, detail)
spaced = write("test_space_paren.py", "def test_a ():\n    pass\n")
_, ok, detail, _ = run(spaced)
check("a def with a space before the paren is still a test", not ok and "ran nothing" in detail, detail)
nested = write("test_nested.py", "class T:\n    def test_a(self):\n        pass\n")
_, ok, detail, _ = run(nested)
check("a method in a class is a test definition too", not ok and "ran nothing" in detail, detail)
check_eq("a file that errored (stderr, no evidence) with test_ defs reads as ran nothing only at exit 0",
         ST.ran_nothing(silent, "", "Traceback"), True)

# 5. a file that errors stays red as today
broken = write("test_broken.py", "raise SystemExit(3)\n")
_, ok, detail, _ = run(broken)
check("a file that exits non-zero stays red", not ok, detail)

# 7. the real directory, read by the parser: a file that defines test_ functions has an entry or a runner call;
# and every pytest.main call carries -p no:cacheprovider (else .pytest_cache lands in the package and --hygiene is red)
def _has_runner(tree: ast.AST) -> bool:
    for n in ast.walk(tree):
        if isinstance(n, ast.If) and any(isinstance(x, ast.Name) and x.id == "__name__" for x in ast.walk(n.test)):
            return True
        if isinstance(n, ast.Raise) and "SystemExit" in ast.dump(n):
            return True
        if isinstance(n, ast.Call):
            fn = n.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
            if name in ("finish", "exit", "main"):
                return True
    return False


def _no_cache_flag(tree: ast.AST) -> list:
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "main" \
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "pytest":
            if "no:cacheprovider" not in ast.dump(n):
                bad.append(n.lineno)
    return bad


bare, no_flag = [], []
for f in sorted(TESTS_DIR.glob("test_*.py")):
    tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
    if ST.defines_tests(f.read_text(encoding="utf-8", errors="replace")) and not _has_runner(tree):
        bare.append(f.name)
    if _no_cache_flag(tree):
        no_flag.append(f.name)
check_eq("no test file defines test_ functions without an entry or a runner call", bare, [])
check_eq("every pytest.main entry carries -p no:cacheprovider", no_flag, [])
# the pins can fail: a synthetic bare file and a synthetic flag-less entry are caught by the same functions
check_eq("control: a bare file is caught by the runner pin", _has_runner(ast.parse("def test_a():\n    pass\n")), False)
check_eq("control: a flag-less pytest.main is caught by the flag pin",
         _no_cache_flag(ast.parse("import pytest\npytest.main([__file__, '-q'])\n")), [2])
check_eq("control: a flag-ed pytest.main passes the flag pin",
         _no_cache_flag(ast.parse("import pytest\npytest.main([__file__, '-q', '-p', 'no:cacheprovider'])\n")), [])

cleanup(root)
finish("selftest ran-nothing")
