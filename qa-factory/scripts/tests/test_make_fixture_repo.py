"""make_fixture_repo.py — the real sample fixture becomes a real two-branch git repo, and the
one failure mode that used to be a raw traceback: `git apply` conflicting with the working
tree. `run()` used `check=True` with no handler, so a `git apply` conflict left a
CalledProcessError traceback where the two sibling failures above it (fixture not found,
target not empty) both answer a clean `return 2` — the fix (TP2-2553-era selftest
cleanup) is `main()` catching it and answering the same way, with one stderr line naming the
command and the first line git reported."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import make_fixture_repo as M  # noqa: E402


def call(*args) -> int:
    """M.main()'s own argv parsing, in this process. The git commands inside `run()` are
    still real subprocesses — that is the point: the assertions below are about what those
    real commands leave on disk, not about a mock of them."""
    saved_argv = sys.argv
    sys.argv = ["make_fixture_repo.py", *[str(a) for a in args]]
    try:
        return M.main()
    finally:
        sys.argv = saved_argv


def branches(repo: Path) -> list[str]:
    p = subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=str(repo),
                       capture_output=True, text=True)
    return sorted(line.strip() for line in p.stdout.splitlines() if line.strip())


def current_branch(repo: Path) -> str:
    p = subprocess.run(["git", "branch", "--show-current"], cwd=str(repo),
                       capture_output=True, text=True)
    return p.stdout.strip()


def make_broken_patch(root: Path) -> tuple[Path, str, str]:
    """A fixture directory + a patch that cannot apply to it, entirely outside the package
    (real evals/fixtures is read-only for a test — see harness.py's root note). Returns
    (fixtures_dir, fixture_name, feature_slug)."""
    fixtures_dir = root / "fixtures"
    src = fixtures_dir / "brk-fixture"
    src.mkdir(parents=True)
    (src / "a.txt").write_text("hello\nworld\n", encoding="utf-8")
    patch = fixtures_dir / "brk-fixture.feature-brk.patch"
    # The "-" lines name context that is not in a.txt, so `git apply` refuses the hunk —
    # a real conflict, not a malformed patch (a malformed one is a different failure entirely).
    patch.write_text(
        "diff --git a/a.txt b/a.txt\n"
        "index 0000000..1111111 100644\n"
        "--- a/a.txt\n"
        "+++ b/a.txt\n"
        "@@ -1,2 +1,2 @@\n"
        "-does not match the fixture's first line\n"
        "-does not match the fixture's second line\n"
        "+patched one\n"
        "+patched two\n",
        encoding="utf-8",
    )
    return fixtures_dir, "brk-fixture", "brk"


def main() -> None:
    # 1. Happy path: the real sample fixture — main branch committed, feature branch with the
    #    patch applied and committed, the patch's own commit message on top.
    root = temp_dir("qa-factory-fixture-repo-happy-")
    try:
        out = root / "repo"
        code = call("--out", str(out), "--fixture", "sample-pytest-repo", "--feature", "qa-1")
        check_eq("happy path: exit 0", code, 0)
        check_eq("happy path: main + feature/qa-1 both exist",
                 branches(out), ["feature/qa-1", "main"])
        check_eq("happy path: left on the feature branch (matches the docstring: "
                 "'main + feature/<ticket>' committed, checked back out to main)",
                 current_branch(out), "main")
        log = subprocess.run(["git", "log", "--oneline", "feature/qa-1"], cwd=str(out),
                             capture_output=True, text=True).stdout
        check_in("happy path: the feature branch carries the patch's own commit",
                 "QA-1: items can carry tags", log)
    finally:
        cleanup(root)

    # 2. No patch for the requested feature: main only, exit 0 — not every ticket has one.
    root = temp_dir("qa-factory-fixture-repo-nopatch-")
    try:
        out = root / "repo"
        code = call("--out", str(out), "--fixture", "sample-pytest-repo", "--feature", "no-such-slug")
        check_eq("no patch for this feature: exit 0", code, 0)
        check_eq("no patch for this feature: main only", branches(out), ["main"])
    finally:
        cleanup(root)

    # 3. Fixture not found: exit 2, names the path — same shape as the other two failures.
    root = temp_dir("qa-factory-fixture-repo-missing-")
    try:
        out = root / "repo"
        code, err = None, ""
        saved_argv = sys.argv
        sys.argv = ["make_fixture_repo.py", "--out", str(out), "--fixture", "no-such-fixture"]
        import io
        from contextlib import redirect_stderr
        buf = io.StringIO()
        try:
            with redirect_stderr(buf):
                code = M.main()
        finally:
            sys.argv = saved_argv
        err = buf.getvalue()
        check_eq("fixture not found: exit 2", code, 2)
        check_in("fixture not found: names the missing path", "fixture not found", err)
    finally:
        cleanup(root)

    # 4. Target directory not empty: exit 2.
    root = temp_dir("qa-factory-fixture-repo-nonempty-")
    try:
        out = root / "repo"
        out.mkdir()
        (out / "already-here.txt").write_text("x", encoding="utf-8")
        import io
        from contextlib import redirect_stderr
        buf = io.StringIO()
        saved_argv = sys.argv
        sys.argv = ["make_fixture_repo.py", "--out", str(out), "--fixture", "sample-pytest-repo"]
        try:
            with redirect_stderr(buf):
                code = M.main()
        finally:
            sys.argv = saved_argv
        check_eq("target not empty: exit 2", code, 2)
        check_in("target not empty: names the target", "not empty", buf.getvalue())
    finally:
        cleanup(root)

    # 5. `git apply` conflicts with the working tree: exit 2, one stderr line naming the
    #    command and git's first reported line — never the raw CalledProcessError traceback
    #    this used to be (bare `check=True`, no handler).
    root = temp_dir("qa-factory-fixture-repo-conflict-")
    saved_fixtures = M.FIXTURES
    try:
        fixtures_dir, fixture_name, feature = make_broken_patch(root)
        M.FIXTURES = fixtures_dir
        out = root / "repo"
        import io
        from contextlib import redirect_stderr
        buf = io.StringIO()
        code = None
        try:
            with redirect_stderr(buf):
                code = call("--out", str(out), "--fixture", fixture_name, "--feature", feature)
        finally:
            pass
        err = buf.getvalue()
        check_eq("git apply conflict: exit 2, not an unhandled traceback", code, 2)
        check_in("git apply conflict: names the command", "git apply failed: git apply", err)
        check_eq("git apply conflict: exactly one stderr line", len(err.strip().splitlines()), 1)
        # main branch was still committed before the conflict was hit — the failure is
        # isolated to the feature branch step, not a half-initialized repo.
        check_eq("git apply conflict: main was already committed when the patch step failed",
                 branches(out), ["feature/brk", "main"])
    finally:
        M.FIXTURES = saved_fixtures
        cleanup(root)

    finish("test_make_fixture_repo")


if __name__ == "__main__":
    main()
