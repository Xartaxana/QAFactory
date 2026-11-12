"""hooklib.rotate_telemetry: keep_days for hook files, keep_commands for command pairs,
throttled to at most once per interval, never touching the file currently being written."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, cleanup, finish, temp_dir, use_project  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hooklib  # noqa: E402


def touch(path: Path, age_days: float = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"event_id":"x:start"}\n', encoding="utf-8")
    if age_days:
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
    return path


def part_hook_files_by_age() -> None:
    d = temp_dir("qa-telemetry-hookage-")
    try:
        old = touch(d / "hook-1.jsonl", age_days=10)
        touch(d / "hook-1.aggregate.json", age_days=10)
        fresh = touch(d / "hook-2.jsonl", age_days=1)
        result = hooklib.rotate_telemetry(d, {}, now=time.time())
        check("rotation ran on first call (no marker yet)", result["ran"])
        check("an 8-day-old hook file (default keep_days=7) is removed", not old.exists())
        check("its .aggregate.json companion is removed with it",
              not (d / "hook-1.aggregate.json").exists())
        check("a 1-day-old hook file is kept", fresh.exists())
    finally:
        cleanup(d)


def part_command_files_by_count() -> None:
    d = temp_dir("qa-telemetry-cmdcount-")
    try:
        paths = []
        for i in range(5):
            p = touch(d / f"command-{i}.jsonl", age_days=0)
            os.utime(p, (time.time() - (5 - i), time.time() - (5 - i)))  # i=0 oldest, i=4 newest
            paths.append(p)
        hooklib.rotate_telemetry(d, {"telemetry": {"keep_commands": 2}}, now=time.time())
        check("the two newest command files survive", paths[3].exists() and paths[4].exists())
        check("the three oldest command files are pruned", not any(p.exists() for p in paths[:3]))
    finally:
        cleanup(d)


def part_config_keys_and_defaults() -> None:
    d = temp_dir("qa-telemetry-defaults-")
    try:
        for i in range(3):
            touch(d / f"command-{i}.jsonl", age_days=0)
        # No telemetry key at all -> default keep_commands=200, nothing pruned.
        hooklib.rotate_telemetry(d, {}, now=time.time())
        check_eq("no telemetry config -> default keep_commands leaves everything",
                  sum(1 for _ in d.glob("command-*.jsonl")), 3)
        # Bad values degrade to the same defaults rather than raising.
        r = hooklib.rotate_telemetry(d, {"telemetry": {"keep_days": "not-a-number",
                                                        "keep_commands": None}},
                                      now=time.time() + 120)
        check("malformed telemetry config does not raise", r["ran"] is True)
    finally:
        cleanup(d)


def part_never_deletes_keep_paths() -> None:
    d = temp_dir("qa-telemetry-keeppaths-")
    try:
        victim = touch(d / "hook-9.jsonl", age_days=30)
        hooklib.rotate_telemetry(d, {}, keep_paths=(victim,), now=time.time())
        check("a file passed as keep_paths survives even though it is otherwise a victim",
              victim.exists())
    finally:
        cleanup(d)


def part_throttled_to_once_per_interval() -> None:
    d = temp_dir("qa-telemetry-throttle-")
    try:
        now = time.time()
        first = hooklib.rotate_telemetry(d, {}, now=now, interval_s=60)
        check("first call in an empty directory runs", first["ran"])
        stale = touch(d / "hook-old.jsonl", age_days=30)
        again_same_second = hooklib.rotate_telemetry(d, {}, now=now + 1, interval_s=60)
        check("a call one second later is throttled", not again_same_second["ran"])
        check("throttled call touches nothing", stale.exists())
        later = hooklib.rotate_telemetry(d, {}, now=now + 61, interval_s=60)
        check("a call past the interval runs again", later["ran"])
        check("and the overdue file is now pruned", not stale.exists())
    finally:
        cleanup(d)


def part_never_raises_on_a_broken_directory() -> None:
    # A path that cannot be created (a file sitting where the directory should be) must not
    # escape as an exception: the hook that calls this must never fail because of housekeeping.
    d = temp_dir("qa-telemetry-broken-")
    try:
        blocker = d / "telemetry"
        blocker.write_text("not a directory", encoding="utf-8")
        result = hooklib.rotate_telemetry(blocker, {}, now=time.time())
        check_eq("a directory that cannot be created is reported as not-run, not an exception",
                  result, {"ran": False, "removed": 0})
    finally:
        cleanup(d)


def part_wired_into_the_hook_wrapper() -> None:
    """The real integration point: telemetry_hook.py calls rotate_telemetry before it opens
    its own span, using its own hook-<pid>.jsonl path as a keep_paths entry."""
    project = temp_dir("qa-telemetry-wired-")
    try:
        (project / "qa-factory" / "state").mkdir(parents=True)
        (project / "tests").mkdir()
        (project / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        telemetry_dir = project / "qa-factory" / "state" / "telemetry"
        stale = touch(telemetry_dir / "hook-stale.jsonl", age_days=30)

        target = project / "noop_hook.py"
        target.write_text("if __name__ == '__main__':\n    pass\n", encoding="utf-8")

        use_project(project)
        import telemetry_hook

        old_argv, old_stdin = sys.argv, sys.stdin
        import io
        try:
            sys.argv = ["telemetry_hook.py", str(target)]
            payload = json.dumps({"hook_event_name": "SessionStart", "session_id": "s1",
                                   "source": "startup"}).encode("utf-8")
            sys.stdin = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
            code = telemetry_hook.main()
        finally:
            sys.argv, sys.stdin = old_argv, old_stdin

        check_eq("the wrapped no-op hook still exits 0", code, 0)
        check("a 30-day-old telemetry file is pruned by the wrapper's own rotation call",
              not stale.exists())
        check("the hook's own new span file exists and was not pruned",
              any(telemetry_dir.glob("hook-*.jsonl")))
    finally:
        import hooklib
        hooklib._PROJECT_ROOT_CACHE = None
        cleanup(project)


def main() -> None:
    part_hook_files_by_age()
    part_command_files_by_count()
    part_config_keys_and_defaults()
    part_never_deletes_keep_paths()
    part_throttled_to_once_per_interval()
    part_never_raises_on_a_broken_directory()
    part_wired_into_the_hook_wrapper()
    finish("test_telemetry_rotation")


if __name__ == "__main__":
    main()
