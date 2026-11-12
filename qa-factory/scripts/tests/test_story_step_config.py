#!/usr/bin/env python3
"""story_step.py `start` / `finish`: the config.json boundary detector (B-193 R-A6) and its unit checks.

`start` keeps the sha256 of qa-factory/config.json in the dispatch record, `finish` reports a difference as one note and nothing
else; a record with no start hash, or a file that cannot be read at either end, is "not measured" in words (FR-41).
Split off test_story_step.py (TQ1-10); the helpers are in story_step_common.py.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import story_step  # noqa: E402
from story_step_common import (  # noqa: E402
    CONFIG_FIELD,
    change_config,
    dispatch_record,
    finish_s1,
    open_story,
    sha256_of,
)


def config_boundary_checks(root: Path, env: dict) -> None:
    """B-193 R-A6: `start` keeps the hash of config.json, `finish` compares - and only reports."""
    from controller import Controller
    config = root / "qa-factory/config.json"
    saved_bytes = config.read_bytes()
    try:
        # edges 1 and 7 (record level): each dispatch keeps the hash of the file as IT started.
        first = open_story(root, env, "QA-B")
        before = sha256_of(config)
        harness.run_script("story_step.py", "start", "--task", "QA-B", "--stage", "S1", "--role",
                           "qa-scout", cwd=root, env=env)
        check_eq("edge 1: start stores the sha256 of config.json in the dispatch record",
                 dispatch_record(first, "S1-qa-scout-1").get(CONFIG_FIELD), before)
        change_config(root, 1)
        after = sha256_of(config)
        check("the probe edit really changed the bytes", before != after)
        second = open_story(root, env, "QA-C")
        harness.run_script("story_step.py", "start", "--task", "QA-C", "--stage", "S1", "--role",
                           "qa-scout", cwd=root, env=env)
        check_eq("edge 7: a dispatch opened later stores its own hash",
                 dispatch_record(second, "S1-qa-scout-1").get(CONFIG_FIELD), after)
        check_eq("edge 7: and the earlier one still holds the hash it started with",
                 dispatch_record(first, "S1-qa-scout-1").get(CONFIG_FIELD), before)

        # edge 2, unequal: one finding, plain words, exit code and file untouched.
        changed = finish_s1(root, env, "QA-B")
        check_in("edge 2: a changed file is one reported finding, in plain words",
                 "note: config.json changed during S1-qa-scout-1", changed.stdout)
        check_eq("edge 2: the finding is not a refusal - exit code 0", changed.returncode, 0)
        check_in("edge 2: the dispatch is accepted all the same", "accepted S1-qa-scout-1", changed.stdout)
        check_eq("edge 2: exactly one line speaks of config.json",
                 [ln for ln in changed.stdout.splitlines() if "config.json" in ln],
                 ["note: config.json changed during S1-qa-scout-1"])
        check_not_in("edge 2: it does not name who changed the file", "by ", "\n".join(
            ln for ln in changed.stdout.splitlines() if "config.json" in ln))
        check_eq("edge 2: it never reverts the file", sha256_of(config), after)
        # edge 2, equal: nothing at all, and the rest of the output is the very same lines.
        same = finish_s1(root, env, "QA-C")
        check_eq("edge 2: equal hashes - exit code 0", same.returncode, 0)
        check_not_in("edge 2: equal hashes print nothing about config.json", "config.json", same.stdout)
        check_not_in("edge 2: and record no 'not measured' either", "not measured", same.stdout)
        import re

        def masked(text: str, keep_config: bool) -> list:
            # the only thing two runs of the same finish differ in is the clock stamp stage_done writes
            return [re.sub(r"\d{4}-\d\d-\d\dT[\d:+]+", "<ts>", ln) for ln in text.splitlines()
                    if keep_config or "config.json" not in ln]
        check_eq("position invariant: the changed finish prints the unchanged finish's lines plus one",
                 masked(changed.stdout, keep_config=False), masked(same.stdout, keep_config=True))

        # edge 3, real dispatch: created the way a rework / relaunch packet is - no start hash.
        third_task = open_story(root, env, "QA-D")
        controller = Controller(third_task)
        packet = controller.prepare({"stage": "S1", "role": "qa-scout", "id": "S1-qa-scout-1"})
        controller.apply("dispatch", packet["dispatch_request"])
        check("edge 3: a packet built without the start hash carries none",
              CONFIG_FIELD not in dispatch_record(third_task, "S1-qa-scout-1"))
        unmeasured = finish_s1(root, env, "QA-D")
        check_in("edge 3: no start hash - 'not measured' in words",
                 "config.json: not measured for S1-qa-scout-1", unmeasured.stdout)
        check_not_in("edge 3: never reported as a change", "changed during", unmeasured.stdout)
        check_not_in("edge 3: never reported as unchanged", "unchanged", unmeasured.stdout)
        check_eq("edge 3: and never a refusal", unmeasured.returncode, 0)
    finally:
        config.write_bytes(saved_bytes)


def config_unit_checks() -> None:
    """Edges 3-6 at the function level: the file states a real finish cannot reach."""
    import hashlib
    import hooklib
    directory = harness.temp_dir("qa-story-step-cfg-")
    target = directory / "config.json"
    saved = hooklib.config_path
    hooklib.config_path = lambda event=None: target
    read_bytes = Path.read_bytes
    try:
        # edge 4: absent at both ends is equal; absent at one end is a change.
        check_eq("edge 4: an absent file is stored as `absent`", story_step.config_fingerprint(), "absent")
        check_eq("edge 4: absent at start and absent at finish - nothing reported",
                 story_step.config_finding("D-1", {CONFIG_FIELD: "absent"}), [])
        check_eq("edge 4: absent at start, present at finish - a change",
                 (target.write_text("{}", encoding="utf-8"),
                  story_step.config_finding("D-1", {CONFIG_FIELD: "absent"}))[1],
                 ["config.json changed during D-1"])
        digest = hashlib.sha256(b"{}").hexdigest()
        check_eq("edge 1: a present file is stored as the sha256 of its bytes",
                 story_step.config_fingerprint(), digest)
        check_eq("edge 2: equal digests - nothing reported",
                 story_step.config_finding("D-1", {CONFIG_FIELD: digest}), [])
        target.unlink()
        check_eq("edge 4: present at start, absent at finish - a change",
                 story_step.config_finding("D-1", {CONFIG_FIELD: digest}),
                 ["config.json changed during D-1"])

        # edge 3: no start value, or one that is not a value at all - unknown, never a verdict.
        for label, record in (("no field", {}), ("a null", {CONFIG_FIELD: None}),
                              ("no record", None)):
            got = story_step.config_finding("D-2", record)
            check_eq(f"edge 3: {label} - one 'not measured' line", len(got), 1)
            check_in(f"edge 3: {label} - says not measured", "not measured", got)
            check_not_in(f"edge 3: {label} - is not called a change", "changed during", got)
        junk = story_step.config_finding("D-2", {CONFIG_FIELD: "not-a-hash"})
        check_in("edge 3: a start value that is no hash is not measured either", "not measured", junk)
        check_not_in("edge 3: and is not called a change", "changed during", junk)

        # edge 5: unreadable at either end - the reason is stated, nothing is raised.
        target.mkdir()  # the file was removed just above: a directory now stands in its place
        fingerprint = story_step.config_fingerprint()
        check("edge 5: a directory in the file's place is stored as `unreadable: <reason>`",
              fingerprint.startswith("unreadable: ") and len(fingerprint) > len("unreadable: "), fingerprint)
        at_finish = story_step.config_finding("D-3", {CONFIG_FIELD: digest})
        check_in("edge 5: unreadable at finish - not measured, with the reason",
                 "not measured for D-3 - unreadable at finish (", at_finish)
        check_not_in("edge 5: unreadable at finish - not a change", "changed during", at_finish)
        at_start = story_step.config_finding("D-3", {CONFIG_FIELD: fingerprint})
        check_in("edge 5: unreadable at start - not measured, with the reason",
                 "unreadable at start (", at_start)
        target.rmdir()
        target.write_text("{}", encoding="utf-8")
        at_start_only = story_step.config_finding("D-3", {CONFIG_FIELD: fingerprint})
        check_in("edge 5: unreadable at start, readable now - still not measured",
                 "unreadable at start (", at_start_only)
        check_not_in("edge 5: and still not a change", "changed during", at_start_only)

        def refuse(self, *a, **kw):
            raise PermissionError(13, "Permission denied")
        Path.read_bytes = refuse
        try:
            denied = story_step.config_fingerprint()
            check("edge 5: a permission error is `unreadable`, not an exception",
                  denied.startswith("unreadable: PermissionError"), denied)
            check_in("edge 5: unreadable at finish by permission - not measured",
                     "unreadable at finish (PermissionError", story_step.config_finding("D-4", {CONFIG_FIELD: digest}))
        finally:
            Path.read_bytes = read_bytes

        # edge 6: the comparison writes nothing - not the file, not its neighbours.
        def snapshot():
            return sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns, sha256_of(p))
                          for p in directory.iterdir() if p.is_file())
        before = snapshot()
        story_step.config_finding("D-5", {CONFIG_FIELD: "0" * 64})
        story_step.config_finding("D-5", {})
        check_eq("edge 6: comparing changes no file in the project", snapshot(), before)
    finally:
        hooklib.config_path = saved
        Path.read_bytes = read_bytes
        harness.cleanup(directory)


def main() -> None:
    root = harness.temp_project("qa-story-step-")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    try:
        harness.use_project(root)
        config_boundary_checks(root, env)
        config_unit_checks()
    finally:
        harness.cleanup(root)
    harness.finish("test_story_step_config")


if __name__ == "__main__":
    main()
