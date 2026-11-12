"""Per-story record of the plugin version that last wrote the story's artifacts.

A story resumed on a plugin newer than the one that wrote it carries artifacts spelled the
way that older build wrote them (a case-prefixed instance id like `TC-012::test_x` that
today's reader only ever matches through `contract.instance_id_aliases`, never rewritten to
the current spelling). `pipeline.json` had no field a resume could compare against, so nothing
could tell "resumed on a newer build, migrate once" from "still on the build that started it".

This script owns exactly one field, `plugin_version`, and decides nothing about what a
version difference means — `migrate_artifacts.py --if-older` is the caller that reads this to
decide whether to run, and re-stamps the field once its migrations are applied.

  story_version.py --task-root <T> --check     prints {"recorded", "installed", "older"}
  story_version.py --task-root <T> --record    stamps pipeline.json with the installed version
  story_version.py --task-root <T> --record --version 0.7.9   stamps an explicit version (tests)
"""
import argparse
import json
import re
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def installed_version() -> str:
    """The installed package's own version.

    Same manifests `factory_dashboard._package_version` reads ("a label nobody computes is a
    label nobody updates" applies here too), read again rather than imported: a version check
    on every story resume should not pull in the dashboard's heavier import surface for one
    three-line lookup.
    """
    for manifest in (".claude-plugin", ".codex-plugin", ".plugin"):
        try:
            data = json.loads((PACKAGE_ROOT / manifest / "plugin.json").read_text(encoding="utf-8"))
            version = str(data.get("version") or "").split("+", 1)[0].strip()
            if version:
                return version
        except Exception:
            continue
    return ""


def _read_pipeline(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def recorded_version(task_root) -> str:
    """The version last stamped into this story's `pipeline.json`, or "" for a story written
    before this field existed (0.7.8 and earlier) — `is_older` treats that as older on purpose:
    backward compatibility means an old story still gets migrated once, not silently skipped."""
    pipeline = _read_pipeline(Path(task_root) / "pipeline.json")
    return str(pipeline.get("plugin_version") or "").strip()


def plugin_version_of(pipeline) -> str:
    """The plugin version a story's `pipeline.json` carries, "" when it carries none (FR-41: never a guess).

    The running factory writes it in two places: `run_mode.plugin_version` at the story's start
    (story_step.stamp_run_mode) and the top-level `plugin_version` when `record` stamps it (older
    stories have only the top-level key). `run_mode` wins when both exist and differ: it is what the
    run wrote at start. A `run_mode` that is not a dict counts as absent."""
    if not isinstance(pipeline, dict):
        return ""
    run_mode = pipeline.get("run_mode")
    for value in ((run_mode.get("plugin_version") if isinstance(run_mode, dict) else None), pipeline.get("plugin_version")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


_PART_RE = re.compile(r"\d+")


def _parts(version: str) -> tuple:
    return tuple(int(p) for p in _PART_RE.findall(version or ""))


def is_older(recorded: str, installed: str) -> bool:
    """True when `recorded` names a build before `installed`, or names none at all.

    A missing field IS the older case (no 0.7.8-or-earlier story ever wrote it). An unreadable
    `installed` compares as "not older" — never migrate against a version we could not read,
    that is a reason to leave the story exactly as it stands, not a reason to guess.
    """
    if not installed:
        return False
    if not recorded:
        return True
    return _parts(recorded) < _parts(installed)


def record(task_root, version: str = "") -> dict:
    """Stamp `pipeline.json.plugin_version`. A plain read-modify-write, like every other field
    `stage_done.set_facts` writes outside its own lock — this field races with a concurrent
    stage write no worse than `size` or `warnings[]` already do, and a heavier lock here would
    not be consistent with how the rest of pipeline.json is written."""
    root = Path(task_root)
    path = root / "pipeline.json"
    pipeline = _read_pipeline(path)
    if not pipeline:
        return {"written": False, "reason": f"no pipeline.json at {path}"}
    version = version or installed_version()
    if not version:
        return {"written": False, "reason": "installed version unreadable"}
    if pipeline.get("plugin_version") == version:
        return {"written": False, "reason": "already recorded", "version": version}
    pipeline["plugin_version"] = version
    from event_store import atomic_json
    atomic_json(path, pipeline)
    return {"written": True, "version": version}


def check(task_root) -> dict:
    recorded = recorded_version(task_root)
    installed = installed_version()
    return {"recorded": recorded, "installed": installed, "older": is_older(recorded, installed)}


def main() -> None:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task-root", required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--version", default="", help="version to stamp instead of the installed one (tests)")
    import hooklib      # only the command line needs it; `check`/`record` stay free of it
    args = hooklib.exact_options(parser).parse_args()
    if args.check == args.record:
        print("story_version: exactly one of --check / --record", file=sys.stderr)
        sys.exit(2)
    # The story first (CX1-18): `check` on a phantom answered "older: true" (a missing field IS the older case).
    task_root = hooklib.story_cli("story_version.py", root=args.task_root, key_flag=None)
    if args.check:
        print(json.dumps(check(task_root)))
        return
    result = record(task_root, args.version)
    print(json.dumps(result))
    sys.exit(0 if result.get("written") or result.get("reason") == "already recorded" else 1)


if __name__ == "__main__":
    main()
