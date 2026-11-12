"""Which directory the factory calls "the project" — and what it refuses to do without one.

The field bug this pins (TP1-14336): `CLAUDE_PROJECT_DIR` is set by the harness for hook
calls only, so every script a role runs through `Bash` fell through to
`git rev-parse --show-toplevel`. With the project nested inside a monorepo
(`testproject1-sdk/test-harness/qa-factory/`) that is a different repository's root: the journal,
the evidence files and the state tree were created there, silently, and gate B carried a
false `delivery_ready: no` because `check_witness.py` looked for a real file in the wrong
place. The marker — `qa-factory/config.json` — now decides, and a writer that cannot find
one refuses instead of creating it.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, cleanup, finish,  # noqa: E402
                     temp_project)

sys.path.insert(0, str(SCRIPTS))
import hooklib  # noqa: E402


def resolve(cwd: Path, env_dir: Path | None = None, event: dict | None = None) -> Path:
    """hooklib.project_root() as a fresh process would see it from `cwd`."""
    old_env = os.environ.get("CLAUDE_PROJECT_DIR")
    old_cwd = Path.cwd()
    try:
        if env_dir is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = str(env_dir)
        os.chdir(str(cwd))
        hooklib._PROJECT_ROOT_CACHE = None
        return hooklib.project_root(event)
    finally:
        os.chdir(str(old_cwd))
        hooklib._PROJECT_ROOT_CACHE = None
        if old_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = old_env


def git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(path), capture_output=True, timeout=60)


def main() -> None:
    # A monorepo whose root is NOT the project: the project is two levels down, and the
    # monorepo root is exactly where the old fallback used to write.
    mono = temp_project("qa-factory-mono-")
    try:
        # temp_project seeded mono/ itself; move that marker down to the nested project.
        nested = mono / "sdk" / "test-harness"
        nested.mkdir(parents=True)
        (mono / "qa-factory").rename(nested / "qa-factory")
        git_init(mono)

        check_eq("nested project: resolved from its own directory",
                 resolve(nested).resolve(), nested.resolve())
        deep = nested / "tests" / "projects"
        deep.mkdir(parents=True)
        check_eq("nested project: resolved from a directory inside it",
                 resolve(deep).resolve(), nested.resolve())
        check("nested project: the monorepo root is NOT the answer",
              resolve(deep).resolve() != mono.resolve())
        check_eq("the tool-call cwd in the event is honoured the same way",
                 resolve(mono, event={"cwd": str(deep)}).resolve(), nested.resolve())

        # CLAUDE_PROJECT_DIR carrying the marker wins outright (the hook path, unchanged).
        check_eq("CLAUDE_PROJECT_DIR with the marker wins",
                 resolve(mono, env_dir=nested).resolve(), nested.resolve())

        # ...and it wins even when the cwd sits inside a DIFFERENT project that carries the
        # marker too. Until 0.7.12 the code went to the cwd walk first and this branch was
        # never reached, so a caller that pinned the root by setting the variable pinned
        # nothing: on the macOS 0.7.11 install whose plugin clone lived inside an onboarded
        # project, four `--selftest` runs resolved to the user's real stories instead of
        # their own temp project (`FileNotFoundError calls.log`, 14 guard mismatches).
        other = mono / "other-project"
        (other / "qa-factory").mkdir(parents=True)
        (other / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        check_eq("CLAUDE_PROJECT_DIR with the marker beats a cwd inside another project",
                 resolve(deep, env_dir=other).resolve(), other.resolve())
        check_eq("and the same when the event carries that other cwd",
                 resolve(mono, env_dir=other, event={"cwd": str(deep)}).resolve(),
                 other.resolve())

        # A stale/wrong CLAUDE_PROJECT_DIR does not beat a marker found from the cwd: this
        # is the case where a role exported the variable once and then moved, and it is the
        # 14336 shape — the harness sets the variable to the monorepo root, which carries no
        # marker, so the walk from the cwd still decides.
        check_eq("a CLAUDE_PROJECT_DIR without the marker loses to the marker under cwd",
                 resolve(deep, env_dir=mono).resolve(), nested.resolve())
        check_eq("a marker-less CLAUDE_PROJECT_DIR loses to the event's cwd as well",
                 resolve(mono, env_dir=mono, event={"cwd": str(deep)}).resolve(),
                 nested.resolve())

        # No marker anywhere: the old behaviour, so a project mid-onboarding still works.
        plain = mono / "not-a-project"
        plain.mkdir()
        check_eq("no marker anywhere: CLAUDE_PROJECT_DIR is still trusted",
                 resolve(plain, env_dir=plain).resolve(), plain.resolve())

        # The writers refuse rather than create a second state tree.
        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        out = subprocess.run(
            [sys.executable, str(SCRIPTS / "log_append.py"), "--event", "delegated",
             "--agent", "qa-scout", "--task", "QA-1"],
            cwd=str(plain), capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=120)
        check_eq("log_append refuses a project it cannot find", out.returncode,
                 hooklib.EXIT_NO_PROJECT)
        check_in("its message names the marker it looked for",
                 "qa-factory/config.json", out.stderr)
        check("and it created no state tree", not (plain / "qa-factory").exists())

        # Same command from inside the real project writes where it should.
        out = subprocess.run(
            [sys.executable, str(SCRIPTS / "log_append.py"), "--event", "delegated",
             "--agent", "qa-scout", "--task", "QA-1"],
            cwd=str(deep), capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=120)
        check_eq("log_append from inside the project succeeds", out.returncode, 0)
        journal = nested / "qa-factory" / "records" / "journal.jsonl"
        check("it wrote the project's own journal", journal.is_file())
        check("and nothing was written at the monorepo root",
              not (mono / "qa-factory").exists())
    finally:
        cleanup(mono)

    finish("test_project_root")


if __name__ == "__main__":
    main()
