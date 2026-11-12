"""Detector for the "never touch application code" mechanism (PreToolUse: Write|Edit|NotebookEdit|Bash|PowerShell).

Blocks writes into app-under-test paths from any factory phase. Paths live in
config.json (protected_app_paths, filled in by onboarding). Reads are not restricted.

Invoked through guard_pre_tool.py (one process for all PreToolUse checks); the
standalone entry point is kept for manual runs and backwards compatibility.
"""
import os
import re
import shlex
import stat
import sys
from pathlib import Path

from hooklib import (
    artifact_root, artifacts_dir, read_event, load_config, block, norm, project_root, resolve_app_root,
    has_write_marker, read_json, role_name, state_dir, subagent_type, person_signal,
)
from config_contract import editable_strategy_paths

AUTOMATOR = "qa-automator"
# What an automator blocked inside the application tree is told (M15). The orchestrator records
# the person's words; the role names the path in its handover and halts, it never writes around.
TEST_PATH_HOW = ("If this file is a test that has to live inside the application tree, do not write it "
                 "another way: name the path in your handover and halt. The person can open test files "
                 "there for the automator; only when they agreed to that, the orchestrator records their words "
                 "as they were given: waiver.py --task <TICKET> --stage S5 --block \"protected test path: "
                 "<folder/ or pattern>\" --words-file <file> (when they did not agree, nothing is recorded "
                 "under this block).")
# The permanent door (D-0030): the person's word that a place holds the project's tests for EVERY story is
# recorded once, in the config, by the orchestrator with the person's words kept; no story asks again.
TEST_PATH_PERMANENT = (" If this is where the project keeps its tests for every story, say so in your handover "
                       "too: the orchestrator shows the person what that place holds and, on their word, "
                       "records it in test_locations, and no story asks again.")
TEST_PATH_UNTIED = ("A recorded permission is read per story, and this write could not be tied to one story"
                    "{running}.")
TEST_PATH_DELETE = ("Deleting or moving a file inside the application tree is never opened by a permission; "
                    "only writing test files is.")
TEST_PATH_SHELL = ("The recorded permission for '{pattern}' covers Write and Edit only: write the test with "
                   "one of them.")
TEST_PATH_HARDLINK = ("This file has more than one name on disk (a hard link), so writing it could change "
                      "application code: write the test as a new file.")
TEST_PATH_STAT_ERROR = ("The guard could not read this file's entry on disk, so it cannot tell whether "
                        "writing it would change application code: write the test as a new file.")
TEST_PATH_PASSED = ("APP-UNDER-TEST BOUNDARY: passed by the person's recorded permission for test files under "
                    "'{pattern}' ({task}, {date}): \"{words}\" - the automator writes '{raw}'. Application "
                    "code outside that pattern stays closed, and deleting or moving files stays closed.")
# A place the PROJECT named as its tests (`test_locations`, D-0030) is not application code: any role writes
# there, the pass is silent. What stays closed is what the guard cannot see through: a shell command on a whole
# folder or on a name the shell expands (PowerShell 5 `Remove-Item -Recurse` follows junctions), and a
# protected root an entry covers whole (protection wins per target).
TEST_LOCATION_SHELL = ("A shell command on a whole folder, or on a name the shell expands (a wildcard, a "
                       "variable, braces), inside the application tree stays closed even when it is one of the "
                       "project's test locations: write or remove the files by name.")
TEST_LOCATION_WHOLE_ROOT = ("test_locations names all of '{root}', which is also application code in "
                            "protected_app_paths; the orchestrator asks the person which part of '{root}' "
                            "holds the application code.")
# What a shell hands on to something else before the command runs: the guard judges only the paths it can see.
SHELL_EXPANSION = "*?[{$`%~"


def _story_pipeline(event: dict, ticket: str) -> dict:
    try:
        return read_json(artifacts_dir(ticket, event) / "pipeline.json", {}, kind=dict, errors=Exception)
    except Exception:
        return {}  # the PATH is built in here (a ticket that is no path component, a config that cannot be read)


def _empties_existing_file(tool: str, ti: dict, real: Path) -> bool:
    """A Write of nothing over a file that exists, or an Edit whose result is nothing, is a delete
    wearing a write's clothes (7a item 7): the permission opens writing test files, not emptying them.
    A file that does not exist yet has nothing to lose. An Edit whose old text is not in the file
    changes nothing (the tool itself refuses it)."""
    if not real.is_file():
        return False
    if tool == "Write":
        return not str(ti.get("content") or "").strip()
    if tool == "Edit" and "old_string" in ti and "new_string" in ti and ti.get("old_string"):
        text = real.read_text(encoding="utf-8", errors="replace")
        old, new = str(ti["old_string"]), str(ti.get("new_string") or "")
        if old not in text:
            return False
        return not (text.replace(old, new) if ti.get("replace_all") else text.replace(old, new, 1)).strip()
    return False


def _has_other_names(real: Path) -> bool:
    """Does an EXISTING target have more than one name on disk (`st_nlink > 1`)? A hard link under a
    test-folder name IS the application file: the resolved path cannot tell it from a test (a symlink
    resolves, a hard link does not), so a permission for a test folder would let a write change
    application code. A target that does not exist has no second name. Any other stat error is raised:
    the caller's `except` turns it into a refusal (fail closed); `permission_pass` asks
    `_entry_unreadable` first, so the refusal also says so."""
    try:
        found = os.stat(real)
    except (FileNotFoundError, NotADirectoryError):
        return False
    # a directory's link count is not a count of names for it (on POSIX it is 2 or more by itself)
    return stat.S_ISREG(found.st_mode) and found.st_nlink > 1


def _entry_unreadable(real: Path) -> bool:
    """Does the stat of the target fail for a reason other than "it is not there"? A missing target
    has no entry to read (it is a new file); anything else (a permission, an I/O error) is the guard
    not being able to see the file."""
    try:
        os.stat(real)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return True
    return False


def _automator_story(event: dict) -> tuple:
    """(ticket, facts) of the story an AUTOMATOR's call belongs to; ("", {}) for anyone else. The
    permission is the automator's of one story: the critic, the orchestrator, every other role and a
    Codex child with no binding (no role at all) are never asked."""
    if role_name(subagent_type(event)) != AUTOMATOR:
        return "", {}
    import stage_guard
    return stage_guard.resolve_ticket(event)


def test_location_pass(target: str, tool: str, ti: dict, event: dict, cfg: dict, real: Path, raw=None) -> tuple:
    """(passed, what the block adds) for a write into `protected_app_paths` that lies in one of the PROJECT'S
    OWN test locations (`test_locations` in the config, D-0030): a test location is not application code, so
    any role may write there with any of the three tools, delete and move included, silently.

    The one reader is `test_locations.is_test_path`, and only `source == "test_locations"` opens anything: the
    other carriers of where tests live (`run.levels`, `profiles[].roots.test`, `tests_root`) are recognised but
    were never permissions, so an existing config never widens what is writable. Reached ONLY on the blocking
    path, BEFORE `stand_gap_pass` (a test-location write never uses up a person's one-time apply grant) and
    before `permission_pass`. INVARIANT of this position: a file with another name on disk (a hard link) and
    an entry the guard cannot read are refused HERE, before any pass, so no location can open them.

    `raw` is the target as the shell command spelled it; given, the call is a shell write, which passes only
    for a file NAMED in the command: not a name the shell expands (`SHELL_EXPANSION`) and not an existing
    folder (a recursive command could follow a junction into application code). Any error is a refusal."""
    try:
        import test_locations
        verdict = test_locations.is_test_path(str(real), cfg, root=project_root(event))
        if verdict.get("source") != "test_locations":
            return False, ""
        added = []
        unreadable = _entry_unreadable(real)
        if not unreadable and _has_other_names(real):
            added.append(TEST_PATH_HARDLINK)
        if unreadable:
            added.append(TEST_PATH_STAT_ERROR)
        if raw is not None and (any(ch in str(raw) for ch in SHELL_EXPANSION) or real.is_dir()):
            added.append(TEST_LOCATION_SHELL)
        return (False, " ".join(added)) if added else (True, "")
    except Exception:
        return False, ""  # a guard that cannot read the project's word keeps the boundary


def _whole_root_text(target: str, cfg: dict, event: dict) -> str:
    """The sentence for a target a `test_locations` entry matches but only by covering a whole protected root
    (protection wins per target); "" when there is no such entry. It replaces the permanent door, which would
    send the person to a place that is already taken (FR-2)."""
    try:
        import test_locations
        found = test_locations.whole_root_conflict(target, cfg, project_root(event))
        return TEST_LOCATION_WHOLE_ROOT.format(root=found[1]) if found else ""
    except Exception:
        return ""


def _said(*parts: str) -> str:
    """The sentences joined once each, in order: a sentence that an earlier part already carries is dropped."""
    out = ""
    for part in parts:
        if part and part not in out:
            out = f"{out} {part}" if out else part
    return out


def permission_pass(target: str, raw: str, tool: str, event: dict, cfg: dict, real: Path,
                    conflict: bool = False) -> tuple:
    """(passed, what the block adds) for a write into `protected_app_paths` by a dispatched role.

    The person's recorded `protected test path: <pattern>` opens WRITING test files to the automator
    of THAT story, and nothing else: not a delete, not a move, not a write that empties a file, never
    a shell (that branch only ever adds a sentence), never the critic or the orchestrator, never
    another story. Everything that fails to qualify stays blocked exactly as before, and a caller
    that is not the automator gets no added text at all. Reached ONLY on the blocking path, after
    `stand_gap_pass`, so an ordinary call pays nothing. Any error is a refusal (fail closed)."""
    if role_name(subagent_type(event)) != AUTOMATOR:
        return False, ""
    # `conflict`: an entry of `test_locations` covers a whole protected root that holds this target, so the
    # permanent door is already taken and would only send the automator round again (FR-2): it is left out.
    added = TEST_PATH_HOW + ("" if conflict else TEST_PATH_PERMANENT)
    try:
        ti = event.get("tool_input") or {}
        # A target whose entry the OS will not let the guard read may be a file with another name or a
        # file this call empties; the guard cannot tell, so it refuses AND says so (R9, t-076): the
        # automator otherwise sees a bare boundary text for a reason it cannot see.
        unreadable = _entry_unreadable(real)
        destructive = (ti.get("patch_operation") == "delete" or bool(ti.get("patch_move"))
                       or (not unreadable and _empties_existing_file(tool, ti, real)))
        ticket, facts = _automator_story(event)
        if not ticket:
            ids = list(facts.get("running") or facts.get("pipelines") or [])
            added += " " + TEST_PATH_UNTIED.format(
                running=f" ({len(ids)} stories are running: {', '.join(ids)})" if ids else "")
        if destructive:
            added += " " + TEST_PATH_DELETE
        # INVARIANT of this position: a person-granted pass is never reached for a file with another
        # name on disk. It comes before the grant lookup, so no pattern can open such a file.
        linked = not unreadable and _has_other_names(real)
        if linked:
            added += " " + TEST_PATH_HARDLINK
        if unreadable:
            added += " " + TEST_PATH_STAT_ERROR
        if not ticket or destructive or linked or unreadable:
            return False, added
        import test_path_grants
        grant = test_path_grants.grant_for(_story_pipeline(event, ticket), target, cfg,
                                           resolve_app_root(cfg, event))
        if not grant:
            return False, added
        # A pass is recorded for the person (FR-4), not printed: stderr at exit 0 reached nobody (RH1-5, H8).
        person_signal(event, "pass_recorded", TEST_PATH_PASSED.format(
            pattern=grant["pattern"], task=ticket, date=test_path_grants.date_of(grant["at"]),
            words=" ".join(grant["words"].split())[:120], raw=raw), task=ticket)
        return True, ""
    except Exception:
        return False, added  # a guard that cannot read the permission keeps the boundary


def shell_permission_note(target: str, event: dict, cfg: dict) -> str:
    """The sentence a BLOCKED shell write adds when the automator's story holds a permission that
    covers this target: the permission is real, it just does not cover a shell. "" otherwise."""
    try:
        ticket, _ = _automator_story(event)
        if not ticket:
            return ""
        import test_path_grants
        grant = test_path_grants.grant_for(_story_pipeline(event, ticket), target, cfg,
                                           resolve_app_root(cfg, event))
        return TEST_PATH_SHELL.format(pattern=grant["pattern"]) if grant else ""
    except Exception:
        return ""


def stand_gap_pass(target: str, raw: str, tool: str, event: dict, cfg: dict) -> bool:
    """The one write P-00 lets through: the file a person's recorded `apply` decision names.

    P-00 stays absolute. What opens is exactly the file of that gap's own `remedy.where`, once
    per decision, and only for the orchestrator — a role never changes the application, and a
    role's dispatch carries an agent type. Everything else under `protected_app_paths` is
    blocked as before, including a second file named by the same decision. Reached ONLY on the
    blocking path, so an ordinary call pays nothing for it.

    TP1-15045: the factory knew the file, the lines and the value, and the person's only
    options were to make the change themselves or accept a blocked partition."""
    if subagent_type(event):
        return False
    try:
        import stand_gaps
        grant = stand_gaps.apply_grant(target, project_root(event), resolve_app_root(cfg, event),
                                       artifact_root(event), norm=norm)
    except Exception:
        return False  # a guard that cannot read the decision keeps the boundary, never opens it
    if not grant:
        return False
    used = stand_gaps.grant_used(grant, state_dir(event))
    if used:
        # The re-record is a first-word record: only a decision whose FIRST word is `apply` opens a file
        # (`contract.stand_gap_decisions`), and the words travel by file (W3-W1).
        import person_words
        again = person_words.door(f"waiver.py --task {grant['task']} --stage {grant.get('stage') or 'S5'} "
                                  f"--block \"stand gap: {grant['gap']}\"")
        block(f"APP-UNDER-TEST BOUNDARY: your decision on {grant['gap']} ({grant['task']}) "
              f"already applied one change to '{grant['file']}' at {used.get('at')}, and it "
              "opens exactly one write. If the change is not right yet, say so again - "
              f"`{again}`, the file holding `apply - the person wrote: <what to change>`, "
              "records a new word and opens it again. Everything else in the "
              "application stays closed.")
    stand_gaps.record_grant(grant, state_dir(event), target, tool)
    person_signal(event, "pass_recorded",       # H9: the record of a pass goes to the person's journal (RH1-5)
                  f"APP-UNDER-TEST BOUNDARY: passed by your decision on stand gap {grant['gap']} "
                  f"({grant['task']}): \"{stand_gaps.names_only(grant.get('words'))[:120]}\" - writing "
                  f"'{raw}', the file that gap's remedy names. This is the only application file this "
                  "decision opens, and it opens once.", task=str(grant["task"]))
    return True


def check(event: dict, cfg: dict) -> None:
    """Blocks the call (exit 2) or returns control. P-00 applies only when the project
    has declared protected_app_paths (config exists and is filled in) — without it there
    is nothing to protect, and this check is a silent no-op."""
    tool = event.get("tool_name", "")
    ti = event.get("tool_input", {}) or {}
    app_root = resolve_app_root(cfg, event)
    protected = [norm(str(app_root / p)) for p in cfg.get("protected_app_paths", [])]
    strategy_allowlist = {norm(str(p)) for p in editable_strategy_paths(cfg, project_root(event))}
    # Resolution self-check (field lesson): a protected path that does not exist on disk
    # almost certainly means a wrong app_root - the guard must say so out loud instead of
    # silently "protecting" non-existent directories. Printed ONCE per session: the
    # measurement showed 330 repeats of one and the same warning over a story run.
    missing = [p for p in protected if not Path(p).exists()]
    if missing and cfg.get("protected_app_paths"):
        person_signal(
            event, "config",
            "APP-UNDER-TEST BOUNDARY, WARNING: protected paths not found on disk: "
            + ", ".join(missing)
            + ". Check app_root/protected_app_paths in qa-factory/config.json - "
            "P-00 may currently be unprotected by code. (Recorded once per session.)",
            once_key="app-boundary-missing:" + ",".join(sorted(missing)),
        )
    # The project's own test locations (D-0030): an entry that opens nothing is said once, never silently
    # dropped. Asked with the project root of THIS event, not the process's (a hook runs with its own cwd).
    try:
        import test_locations
        problems = test_locations.location_problems(cfg, project_root(event))
    except Exception as exc:
        # H5: a check that could not run is said, never read as "no problems" (FR-59)
        problems = []
        person_signal(event, "config", f"APP-UNDER-TEST BOUNDARY, WARNING: test_locations could not be checked "
                                       f"({type(exc).__name__}); its entries are used as written. (Recorded once per session.)",
                      once_key="test-locations-unchecked")
    if problems:
        person_signal(
            event, "config",
            "APP-UNDER-TEST BOUNDARY, WARNING: test_locations in qa-factory/config.json - "
            + "; ".join(problems)
            + ". Those entries open nothing; the other entries are used. (Recorded once per session.)",
            once_key="test-locations:" + "; ".join(sorted(problems)),
        )
    if not protected:
        # An empty list is the state the pilot was actually in, and the one the guard used to
        # pass over in silence: P-00 unenforced AND unmentioned reads exactly like P-00 kept.
        # The rule itself does not weaken - it binds every role through tester-manifesto.md
        # whether or not a hook can back it - so the honest report is "still binding, not
        # enforced here". Only for a project that HAS a config: the plugin is installed
        # user-wide and must stay silent in repositories that were never onboarded.
        if cfg:
            person_signal(
                event, "config",
                "APP-UNDER-TEST BOUNDARY, WARNING: protected_app_paths is empty in "
                "qa-factory/config.json - P-00 still binds every role (tester-manifesto.md: the "
                "factory never modifies application code, absolutely and without an opt-in), but "
                "no hook is enforcing it in this project. Run qa-onboarding to record where the "
                "application lives. (Recorded once per session.)",
                once_key="app-boundary-unset",
            )
        return

    if tool in ("Write", "Edit", "NotebookEdit"):
        raw_target = ti.get("file_path", "") or ti.get("notebook_path", "")
        target_path = Path(raw_target)
        if not target_path.is_absolute():
            target_path = project_root(event) / target_path
        target = norm(str(target_path))
        if target in strategy_allowlist:
            return
        for p in protected:
            if target.startswith(p + "/") or target == p:
                # The project's test locations come first (D-0030): before the one-time apply grant, which a
                # test-location write must never use up, and before the per-story permission.
                located, located_added = test_location_pass(target, tool, ti, event, cfg, target_path)
                if located:
                    return
                if stand_gap_pass(target, raw_target, tool, event, cfg):
                    return
                conflict = _whole_root_text(target, cfg, event)
                passed, added = permission_pass(target, raw_target, tool, event, cfg, target_path,
                                                conflict=bool(conflict))
                if passed:
                    return
                said = _said(added, located_added, conflict)
                block(
                    f"APP-UNDER-TEST BOUNDARY: writing to '{ti.get('file_path')}' is forbidden. "
                    "Test phases never modify application code (protected_app_paths in qa-factory/config.json). "
                    "A defect in the application is an APP_BUG for the dev team, not a factory patch."
                    + (" " + said if said else "")
                )
    elif tool in ("Bash", "PowerShell"):
        cmd = ti.get("command", "")
        if not has_write_marker(cmd):
            return
        targets = []
        for match in re.finditer(r"(?:>>?\s*|\b(?:Set-Content|Add-Content|Out-File)\b(?:\s+-\w+)*\s+)([^\s;&|]+)",
                                 cmd, re.IGNORECASE):
            targets.append(match.group(1).strip("'\""))
        try:
            words = shlex.split(cmd, posix=False)
        except ValueError:
            block("APP-UNDER-TEST BOUNDARY: ambiguous write command could not be parsed; use a structured Write/Edit call or explicit canonical paths.")
        for i, word in enumerate(words):
            verb = word.lower().rsplit("/", 1)[-1]
            if verb in {"cp", "mv", "copy-item", "move-item", "remove-item", "rm", "del"}:
                operands = [w.strip("'\"") for w in words[i + 1:] if not w.startswith("-")]
                targets.extend(operands if verb in {"mv", "move-item", "remove-item", "rm", "del"} else operands[-1:])
        for raw in targets:
            candidate = Path(raw)
            candidate = candidate if candidate.is_absolute() else project_root(event) / candidate
            target = norm(str(candidate))
            if target in strategy_allowlist:
                continue
            if any(target == p or target.startswith(p + "/") for p in protected):
                located, located_added = test_location_pass(target, tool, ti, event, cfg, candidate, raw=raw)
                if located:
                    continue
                if stand_gap_pass(target, raw, tool, event, cfg):
                    continue
                note = shell_permission_note(target, event, cfg)
                said = _said(note, located_added, _whole_root_text(target, cfg, event))
                block(
                    f"APP-UNDER-TEST BOUNDARY: shell write target '{raw}' resolves inside protected application code. "
                    "Use structured test/artifact writes; application defects belong to the development team."
                    + (" " + said if said else "")
                )


def main() -> None:
    event = read_event()
    if event is None:
        block("APP-UNDER-TEST BOUNDARY: hook event could not be parsed (broken stdin) - fail-closed, write blocked. For a manual run, feed a valid event JSON.")
    check(event, load_config(event))
    sys.exit(0)


if __name__ == "__main__":
    main()
