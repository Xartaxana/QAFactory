#!/usr/bin/env python3
"""FR-39: what the references say a party may write, the guard permits — and only that party.

`references/artifact-writers.json` exists to say "one artifact, one writer". `guard_pre_tool`
kept a second, shorter copy of the same list: eight of the sixteen artifacts a role owns, so the
readiness, the machine plan, the diff, the bug drafts, the retro and the two project ledgers
could be repaired by whoever noticed — the defect `owner_check` exists for, on nine artifacts it
never looked at (FR-13 "one fact, one owner"; FR-17 "wired everywhere the problem occurs").

The permission is now derived from the registry, and this walks every row of it against the
guard, the way test_brief_pack walks the read side: for each artifact a role owns, the owning
role's write passes and another role's write is refused with the rework door for the right role.
A row nobody exercised is a permission nobody has checked, which is what FR-39 is about.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import guard_pre_tool as G  # noqa: E402

TICKET = "QA-39"


def blocked(event: dict, cfg: dict) -> str | None:
    """The guard's refusal text for this event, or None."""
    return G._blocked(G.owner_check, event, cfg)


def write_event(path: Path, role: str = "", transcript: str = "") -> dict:
    event = {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": "x"}}
    if role:
        event["agent_type"] = role
    if transcript:
        event["transcript_path"] = transcript
    return event


def story(root: Path, running_role: str = "") -> Path:
    """A story on disk whose controller has one dispatch, `running` for `running_role`."""
    task = root / "qa-factory" / "artifacts" / TICKET
    (task / "state").mkdir(parents=True, exist_ok=True)
    (task / "work").mkdir(parents=True, exist_ok=True)
    dispatches = {}
    if running_role:
        dispatches["D-1"] = {"role": running_role, "status": "running", "stage": "S1"}
    (task / "state" / "controller.json").write_text(
        json.dumps({"dispatches": dispatches, "stages": {}}), encoding="utf-8")
    (task / "pipeline.json").write_text(json.dumps({"ticket": TICKET, "stages": {}}),
                                        encoding="utf-8")
    return task


def registry_rows() -> list:
    """[(artifact key, owning role)] — the registry's own rows, not a copy of them."""
    data = json.loads((harness.PLUGIN_ROOT / "references" / "artifact-writers.json")
                      .read_text(encoding="utf-8"))
    rows = []
    for key, entry in (data.get("artifacts") or {}).items():
        writer = str((entry or {}).get("writer") or "")
        found = [part for part in writer.replace("(", " ").split() if part.startswith("qa-")]
        role = found[0] if found else G.REGISTRY_ROLE_BY_SCRIPT.get(writer.split()[0] if writer else "")
        if role:
            rows.append((key, role))
    return rows


def path_for(task: Path, project: Path, key: str) -> Path:
    """Where an artifact of this key lives, as the registry spells it."""
    key = key.replace("<", "_").replace(">", "_").replace("*", "x")      # `<case>` and `*` are not legal Windows file names (t-2087 F8; a per-dispatch key `...-*.md` is matched by fnmatch, so `x` stands for the `*`)
    if key.startswith("project:"):
        return project / key[len("project:"):].rstrip("/") / "FILE.md" \
            if key.endswith("/") else project / key[len("project:"):]
    if key.endswith("/"):
        return task / key.rstrip("/") / "FILE.md"
    return task / key


def every_declared_owner_is_exercised() -> None:
    root = temp_project("qa-guard-owner-")
    use_project(root)
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    cfg = {}
    try:
        rows = registry_rows()
        check("the registry names an owning role for at least sixteen artifacts",
              len(rows) >= 16, str(len(rows)))
        derived = G.owned_artifacts()
        # A slash-ending or project: key is kept as spelled; a path key is kept whole, and its
        # basename alias only where no other key shares that basename.
        bases = [k.rsplit("/", 1)[-1] for k, _r in rows if not k.endswith("/") and not k.startswith("project:")]
        expected = set()
        for k, _r in rows:
            if k.endswith("/") or k.startswith("project:") or "/" not in k:
                expected.add(k)
            else:
                expected.add(k)
                if bases.count(k.rsplit("/", 1)[-1]) == 1:
                    expected.add(k.rsplit("/", 1)[-1])
        check_eq("and the guard's map is the registry's, row for row", set(derived), expected)
        for key, owner in sorted(rows):
            task = story(root, running_role="")
            target = path_for(task, root, key)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("existing\n", encoding="utf-8")

            # (1) the host says the owning role is writing: allowed.
            check_eq(f"{key}: {owner} may write it",
                     blocked(write_event(target, role=owner), cfg), None)
            # (2) somebody else, with no dispatch of the owner open: refused, by name.
            other = "qa-scout" if owner != "qa-scout" else "qa-runner"
            refusal = blocked(write_event(target, role=other), cfg)
            check(f"{key}: {other} may not", bool(refusal), str(refusal)[:120])
            if refusal:
                check_in(f"{key}: and the refusal names its owner", owner, refusal)
                check_in(f"{key}: with the door that sends it back", "--operation rework", refusal)
            # (3) a dispatch of the owning role is open: allowed, whoever the caller says it is.
            story(root, running_role=owner)
            check_eq(f"{key}: an open dispatch of {owner} is the other way through",
                     blocked(write_event(target, role=other), cfg), None)
    finally:
        cleanup(root)


def the_fallback_map_is_a_subset() -> None:
    """The in-code map is the floor under a broken checkout, so it may not disagree with the
    registry — a second copy that drifts is what the registry replaced."""
    derived = G.owned_artifacts()
    wrong = {name: role for name, role in G.OWNED_ARTIFACTS.items()
             if derived.get(name) not in (None, role)}
    check_eq("the fallback map names no other owner than the registry", wrong, {})
    missing = [name for name in G.OWNED_ARTIFACTS if name not in derived]
    check_eq("and nothing in it is unknown to the registry", missing, [])
    check("the registry covers more than the fallback did",
          len(derived) > len(G.OWNED_ARTIFACTS), f"{len(derived)} vs {len(G.OWNED_ARTIFACTS)}")


def a_file_nobody_owns_is_not_this_guards_business() -> None:
    root = temp_project("qa-guard-free-")
    use_project(root)
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    try:
        task = story(root)
        free = task / "work" / "notes.md"
        free.write_text("notes\n", encoding="utf-8")
        check_eq("a file the registry does not name passes",
                 blocked(write_event(free, role="qa-scout"), {}), None)
        ledger = task / "work" / "ledger.json"
        ledger.write_text("{}", encoding="utf-8")
        check_eq("and so does an artifact whose writer is a script, not a role",
                 blocked(write_event(ledger, role="qa-scout"), {}), None)
    finally:
        cleanup(root)


def onboarding_may_write_a_persons_words_under_the_project_state() -> None:
    """FR-15, FR-39: onboarding has no story folder, so phases/p4-generate.md names
    `qa-factory/state/words/<name>.txt` (beside `qa-factory/state/config-migrations/`, which it
    already writes) as the place for `project_decisions.py resolve --words-file`. The REAL guard,
    run as the hook runs it, permits that Write and still refuses a secret-file name there."""
    import subprocess
    root = temp_project("qa-guard-onb-words-")
    try:
        def verdict(name: str) -> int:
            target = root / "qa-factory" / "state" / "words" / name
            event = {"hook_event_name": "PreToolUse", "session_id": "onb-words", "cwd": str(root),
                     "tool_name": "Write", "tool_input": {"file_path": str(target), "content": "their words"}}
            proc = subprocess.run([sys.executable, "-B", str(harness.SCRIPTS / "guard_pre_tool.py")],
                                  input=json.dumps(event), capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", cwd=str(root), timeout=120,
                                  env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
            return proc.returncode
        check_eq("a Write to qa-factory/state/words/<topic>-<stamp>.txt passes the guard",
                 verdict("topic-20261003-101500.txt"), 0)
        check_eq("a secret-file name under it is still refused", verdict("credentials.txt"), 2)
    finally:
        cleanup(root)


def onboarding_notes_pass_the_real_guard_before_any_config() -> None:
    """B-411 G1 (FR-39): the run's own notes are written by the role with its file tools BEFORE the project has a config
    (a first onboarding). The REAL guard, run as the hook runs it (through telemetry_hook.py), in a project with NO config.json,
    permits a Write of a words file, an Edit of discovery.yaml, a Write of proposal.json and the Bash call of the notes CLI, and
    still refuses secret content; and the hook creates no qa-factory/ of its own (hooklib.require_project, TP1-14336)."""
    import subprocess
    root = harness.temp_dir("qa-guard-onb-notes-")
    try:
        notes = root / "qa-factory" / "state" / "onboarding"
        script = harness.SCRIPTS / "onboarding_notes.py"

        def verdict(tool: str, tool_input: dict) -> subprocess.CompletedProcess:
            event = {"hook_event_name": "PreToolUse", "session_id": "onb-notes", "cwd": str(root), "tool_name": tool, "tool_input": tool_input}
            return subprocess.run([sys.executable, "-B", str(harness.SCRIPTS / "telemetry_hook.py"), "guard_pre_tool.py"], input=json.dumps(event),
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(root), timeout=120,
                                  env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1"))
        before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
        check_eq("G1 setup: the project has no config.json", (root / "qa-factory" / "config.json").exists(), False)
        for label, tool, tool_input in (
                ("a Write of a words file", "Write", {"file_path": str(notes / "words" / "batch-1-x.txt"), "content": "their words"}),
                ("an Edit of discovery.yaml", "Edit", {"file_path": str(notes / "discovery.yaml"), "old_string": 'state: "pending"', "new_string": 'state: "found"'}),
                ("a Write of proposal.json", "Write", {"file_path": str(notes / "proposal.json"), "content": "{}"}),
                ("a Write of sealed.json", "Write", {"file_path": str(notes / "sealed.json"), "content": "{}"}),
                ("a Write of answers.json", "Write", {"file_path": str(notes / "answers.json"), "content": "{}"}),
                ("the Bash call of the notes CLI (answer)", "Bash", {"command": f'python "{script}" --root . answer --batch b1 --words-file qa-factory/state/onboarding/words/batch-b1-1.txt --answered t1'}),
                ("the Bash call of the notes CLI (status)", "Bash", {"command": f'python "{script}" --root . status'})):
            p = verdict(tool, tool_input)
            check_eq(f"G1: {label} passes the real guard with no config", p.returncode, 0)
        p = verdict("Write", {"file_path": str(notes / "words" / "batch-1-x.txt"), "content": "api_key: 'ABCDEFGHIJKLMNOP'"})
        check("G1 control: secret content in the same file is still refused (exit 2, SECRETS)", p.returncode == 2 and "SECRET" in p.stderr.upper(), f"{p.returncode} {p.stderr[-200:]}")
        check_eq("G1: no hook created a qa-factory/ (or anything else) in the project", sorted(p.relative_to(root).as_posix() for p in root.rglob("*")), before)
    finally:
        cleanup(root)


def a_critics_findings_are_the_critics_not_the_designers() -> None:
    """The S4 case critic's findings sit under `work/test-cases/`, the designer's directory key;
    the path key for them wins (FR-39), and only for them."""
    base = "/p/qa-factory/artifacts/QA-39/work"
    cases = {
        "S4 findings under an area dir": (f"{base}/test-cases/webhook/critic-findings.md", "qa-case-critic"),
        "S4 findings at the cases root": (f"{base}/test-cases/critic-findings.md", "qa-case-critic"),
        "S5 findings": (f"{base}/test-code/critic-findings.md", "qa-code-critic"),
        "a case file beside them": (f"{base}/test-cases/webhook/TC-001.md", "qa-case-designer"),
        "any other file of the directory": (f"{base}/test-cases/webhook/notes.md", "qa-case-designer"),
    }
    for label, (path, role) in cases.items():
        check_eq(f"{label}: owned by {role}", G._owner_of_path(path, {}), (role, False))
    # A key with a directory part but a different basename does not match, and a same-named file
    # outside the key's directory is not claimed by the path key.
    check_eq("critic-findings.md in another directory is nobody's",
             G._owner_of_path(f"{base}/other/critic-findings.md", {}), (None, False))
    check_eq("another file under test-code is not the code critic's",
             G._owner_of_path(f"{base}/test-code/notes.md", {})[0] != "qa-code-critic", True)
    # The rest of the map is unmoved: a basename that no other key shares still resolves anywhere.
    check_eq("a path key with a unique basename still resolves as before",
             G._owner_of_path(f"{base}/triage.json", {})[0], "qa-failure-analyst")
    # Through the guard: the critic writes its findings with no designer dispatch open.
    root = temp_project("qa-guard-critic-")
    use_project(root)
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    try:
        task = story(root)
        target = task / "work" / "test-cases" / "webhook" / "critic-findings.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        check_eq("the case critic's Write of its findings passes",
                 blocked(write_event(target, role="qa-case-critic"), {}), None)
        check("and the designer's own Write of that file is refused (one artifact, one writer)",
              bool(blocked(write_event(target, role="qa-case-designer"), {})))
    finally:
        cleanup(root)


# --- t-110 / B-193, R-A5 (K1, K2): a ROLE never writes qa-factory/config.json ----------------------

PROFILE = "qa-factory/config.json"
ROLE = "qa-automator"


def profile_refusal(event: dict) -> str | None:
    """The refusal text of the profile check alone, or None. An exception is a failure, not a pass."""
    return G._blocked(G.config_write_check, event, {})


def shell_event(command: str, role: str = ROLE, tool: str = "Bash", **extra) -> dict:
    event = {"tool_name": tool, "tool_input": {"command": command}}
    if role:
        event["agent_type"] = role
    event.update(extra)
    return event


def file_event(tool: str, path: str, role: str = ROLE, key: str = "file_path") -> dict:
    event = {"tool_name": tool, "tool_input": {key: path, "content": "x"}}
    if role:
        event["agent_type"] = role
    return event


def a_role_never_writes_the_profile_through_a_file_tool() -> None:
    root = temp_project("qa-guard-cfg-file-")
    other = temp_project("qa-guard-cfg-other-")
    use_project(root)
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    try:
        spellings = {
            "relative, forward slashes": "qa-factory/config.json",
            "relative, backslashes": "qa-factory\\config.json",
            "absolute, forward slashes": str(root / "qa-factory" / "config.json").replace("\\", "/"),
            "absolute, native": str(root / "qa-factory" / "config.json"),
        }
        for tool in ("Write", "Edit", "NotebookEdit"):
            for label, path in spellings.items():
                refusal = profile_refusal(file_event(tool, path))
                check(f"row 1: {tool} of the profile ({label}) by a role is refused", bool(refusal),
                      "passed")
        check("row 1: NotebookEdit names its file `notebook_path`, and that is read too",
              bool(profile_refusal(file_event("NotebookEdit", "qa-factory/config.json", key="notebook_path"))))
        check("row 1: the host's namespaced role id is a role too",
              bool(profile_refusal(file_event("Write", PROFILE, role="qa-factory:qa-automator"))))
        check("row 1: any factory role is refused, not the automator alone",
              all(profile_refusal(file_event("Edit", PROFILE, role=r)) for r in
                  ("qa-scout", "qa-code-critic", "qa-runner", "qa-doc-scribe")))
        refusal = profile_refusal(file_event("Write", PROFILE)) or ""
        check_in("row 1: the refusal says what is refused", "does not write qa-factory/config.json", refusal)
        check_in("row 1: and why - the command every window runs changes under running work",
                 "the command every window of this story runs", refusal)
        check_in("row 1: and that it changes under work already running", "under work that is already running", refusal)
        check_in("row 1: the role's door is the digest line", "`launch: <cause>`", refusal)
        check_in("row 1: with the evidence line", "the evidence line", refusal)
        check_in("row 1: the person's word is the orchestrator's, which edits the profile itself",
                 "the orchestrator carries it out: it edits the profile itself", refusal)
        check_in("row 1: and proves it with launch_check", "`launch_check.py --profile <id>`", refusal)
        for banned in ("config_contract", "--apply", "onboarding execution batch"):
            check(f"row 1: the refusal does not name {banned!r} (a door the role cannot use)",
                  banned not in refusal, banned)
        check_in("row 1: the trapped-role tail of every refusal stays", "halt", refusal)

        # (2) the MAIN session is never refused, with a dispatch open or not.
        for label, spelling in spellings.items():
            check_eq(f"row 2: Write of the profile by the main session ({label}), no dispatch open, passes",
                     profile_refusal(file_event("Write", spelling, role="")), None)
        story(root, running_role=ROLE)
        for tool in ("Write", "Edit", "NotebookEdit"):
            check_eq(f"row 2: {tool} of the profile by the main session with a dispatch OPEN passes",
                     profile_refusal(file_event(tool, PROFILE, role="")), None)
        check_eq("row 2: and a shell edit by the main session with a dispatch open passes",
                 profile_refusal(shell_event("sed -i s/a/b/ qa-factory/config.json", role="")), None)
        check("row 2: while the same dispatch open, the role is still refused",
              bool(profile_refusal(file_event("Write", PROFILE))))
        check_eq("row 2 (shape): a caller named by a built-in agent type, not a factory role, passes",
                 profile_refusal(file_event("Write", PROFILE, role="general-purpose")), None)
        check_eq("row 2 (shape): a subagent transcript with no agent name is not told from the main session",
                 profile_refusal(dict(file_event("Write", PROFILE, role=""),
                                      transcript_path="/x/session/subagents/agent-1.jsonl")), None)

        # (3), (4) other files
        check_eq("row 3: Edit of qa-factory/config.json.bak passes",
                 profile_refusal(file_event("Edit", "qa-factory/config.json.bak")), None)
        check_eq("row 3: Write of qa-factory/config.json5 passes",
                 profile_refusal(file_event("Write", "qa-factory/config.json5")), None)
        check_eq("row 3: Write of qa-factory/xconfig.json passes",
                 profile_refusal(file_event("Write", "qa-factory/xconfig.json")), None)
        check_eq("row 4: Edit of other/qa-factory/config.json (relative, under the root) passes",
                 profile_refusal(file_event("Edit", "other/qa-factory/config.json")), None)
        check_eq("row 4: Edit of another project's qa-factory/config.json (absolute, outside the root) passes",
                 profile_refusal(file_event("Edit", str(other / "qa-factory" / "config.json"))), None)
        check_eq("row 4: a path that is not a string of the tool's own shape is nobody's business",
                 profile_refusal({"tool_name": "Edit", "agent_type": ROLE, "tool_input": {"file_path": None}}), None)
    finally:
        cleanup(root)
        cleanup(other)


# (command, refused?) - every row of the shell table. The write shape and the profile's path must sit
# in the SAME segment, the path in the destination position (K2).
SHELL_ROWS = [
    ("row 5: cat", "cat qa-factory/config.json", False),
    ("row 6: python reads it", "python -c \"import json;json.load(open('qa-factory/config.json'))\"", False),
    ("row 6: python opens it for reading (r, rb)",
     "python -c \"open('qa-factory/config.json','r').read();open('qa-factory/config.json','rb')\"", False),
    ("row 7: git diff", "git diff qa-factory/config.json", False),
    ("row 7: git log", "git log -p -- qa-factory/config.json", False),
    ("row 8: sed -n", "sed -n 1,5p qa-factory/config.json", False),
    ("row 9: sed -i", "sed -i s/a/b/ qa-factory/config.json", True),
    ("row 9: sed -i with a backup suffix", "sed -i.bak 's/a/b/' qa-factory/config.json", True),
    ("row 9: sed -ni", "sed -ni s/a/b/p qa-factory/config.json", True),
    ("row 9: sed --in-place", "sed --in-place s/a/b/ qa-factory/config.json", True),
    ("row 9: sed -E reads", "sed -E s/a/b/ qa-factory/config.json", False),
    ("row 10: perl -i -pe", "perl -i -pe s/a/b/ qa-factory/config.json", True),
    ("row 10: perl -pi", "perl -pi -e s/a/b/ qa-factory/config.json", True),
    ("row 10: perl -Mstrict is not -i (a read)", "perl -Mstrict -ne print qa-factory/config.json", False),
    ("row 11: > with a backslash path", "echo x > qa-factory\\config.json", True),
    ("row 11: >> with forward slashes", "echo x >> qa-factory/config.json", True),
    ("row 11: > with no space", "echo x >qa-factory/config.json", True),
    ("row 11: a quoted target", "echo x > \"qa-factory/config.json\"", True),
    ("row 11: a descriptor redirect", "some-tool 2> qa-factory/config.json", True),
    ("row 11: a stderr redirect elsewhere reads", "cat qa-factory/config.json 2>&1", False),
    ("row 11: a > inside a quoted string is not a redirection", "echo \"a > qa-factory/config.json\"", False),
    ("row 11: a heredoc STORED by cat into it", "cat > qa-factory/config.json <<'EOF'\n{}\nEOF", True),
    ("row 12: python heredoc, open w",
     "python - <<'EOF'\nimport json\nwith open('qa-factory/config.json','w') as f:\n    json.dump({}, f)\nEOF", True),
    ("row 12: python heredoc, open a",
     "python - <<'EOF'\nopen('qa-factory/config.json', 'a').write('x')\nEOF", True),
    ("row 12: python heredoc, open r+",
     "python - <<'EOF'\nopen(\"qa-factory/config.json\",\"r+\").write('x')\nEOF", True),
    ("row 12: python heredoc, open with mode=", "python - <<'EOF'\nopen('qa-factory/config.json', mode='w')\nEOF", True),
    ("row 12: python heredoc, write_text",
     "python - <<'EOF'\nfrom pathlib import Path\nPath('qa-factory/config.json').write_text('{}')\nEOF", True),
    ("row 12: python heredoc, a backslash literal",
     "python - <<'EOF'\nopen('qa-factory\\\\config.json','w')\nEOF", True),
    ("row 12: python heredoc, read mode passes", "python - <<'EOF'\nopen('qa-factory/config.json','r').read()\nEOF", False),
    ("row 12: python heredoc, a path in a variable passes (unclear -> pass)",
     "python - <<'EOF'\np = 'qa-factory/config.json'\nopen(p, 'w')\nEOF", False),
    ("row 12: python heredoc, another file passes", "python - <<'EOF'\nopen('qa-factory/other.json','w')\nEOF", False),
    ("row 12: the same text in a heredoc a NON-interpreter stores passes",
     "cat > note.md <<'EOF'\nopen('qa-factory/config.json','w')\nEOF", False),
    ("row 12: the same text quoted by echo passes", "echo \"open('qa-factory/config.json','w')\" > note.md", False),
    ("row 13: python -c open w", "python -c \"open('qa-factory/config.json','w').write('x')\"", True),
    ("row 13: python3 -c write_text",
     "python3 -c \"import pathlib; pathlib.Path('qa-factory/config.json').write_text('x')\"", True),
    ("row 13: python -c with escaped inner quotes",
     "python -c \"open(\\\"qa-factory/config.json\\\",\\\"w\\\").write('x')\"", True),
    ("row 14: git checkout -p", "git checkout -p qa-factory/config.json", True),
    ("row 14: git restore", "git restore qa-factory/config.json", True),
    ("row 14: git checkout REV --", "git checkout HEAD~1 -- qa-factory/config.json", True),
    ("row 14: git -C dir restore", "git -C . restore qa-factory/config.json", True),
    ("row 14: git restore --staged only touches the index (passes)", "git restore --staged qa-factory/config.json", False),
    ("row 14: git checkout of a branch passes", "git checkout main", False),
    ("row 14: git status passes", "git status qa-factory/config.json", False),
    ("row 15: cp onto it", "cp /tmp/c.json qa-factory/config.json", True),
    ("row 15: cp from it", "cp qa-factory/config.json /tmp/c.json", False),
    ("row 15: mv onto it", "mv /tmp/c.json qa-factory/config.json", True),
    ("row 15: mv from it takes the profile away (a write)", "mv qa-factory/config.json /tmp/c.json", True),
    ("row 15: copy onto it", "copy c.json qa-factory\\config.json", True),
    ("row 15: copy /Y onto it", "copy /Y c.json qa-factory\\config.json", True),
    ("row 15: copy from it", "copy qa-factory\\config.json c.json", False),
    ("row 15: move onto it", "move c.json qa-factory\\config.json", True),
    ("row 15: move from it takes the profile away (a write)", "move qa-factory\\config.json c.json", True),
    ("row 15: cp -t names a directory (passes)", "cp -t qa-factory/ qa-factory/config.json", False),
    ("row 15: Copy-Item -Destination onto it", "Copy-Item -Path c.json -Destination qa-factory/config.json", True),
    ("row 15: Copy-Item -Destination from it", "Copy-Item -Path qa-factory/config.json -Destination c.json", False),
    ("row 15: Copy-Item positional onto it", "Copy-Item c.json qa-factory/config.json", True),
    ("row 15: Copy-Item positional from it", "Copy-Item qa-factory/config.json c.json", False),
    ("row 15: Copy-Item -Path named, destination positional", "Copy-Item -Path c.json qa-factory/config.json", True),
    ("row 15: Move-Item -Destination onto it", "Move-Item -Path c.json -Destination qa-factory\\config.json", True),
    ("row 15: Move-Item -Destination from it takes the profile away (a write)",
     "Move-Item -Path qa-factory\\config.json -Destination c.json", True),
    ("row 15: Move-Item positional onto it", "Move-Item c.json qa-factory\\config.json", True),
    ("row 15: Move-Item -Dest abbreviation onto it", "Move-Item c.json -Dest qa-factory\\config.json", True),
    ("row 16: tee", "cat c.json | tee qa-factory/config.json", True),
    ("row 16: tee -a", "echo x | tee -a qa-factory/config.json", True),
    ("row 16: tee elsewhere passes", "cat qa-factory/config.json | tee out.json", False),
    ("row 17: Set-Content", "Get-Content c.json | Set-Content qa-factory/config.json", True),
    ("row 17: Out-File", "Get-Content c.json | Out-File qa-factory/config.json", True),
    ("row 17: Out-File -FilePath", "$x | Out-File -FilePath qa-factory/config.json -Encoding utf8", True),
    ("row 17: Add-Content", "'x' | Add-Content qa-factory/config.json", True),
    ("row 17: Set-Content -Path named", "Set-Content -Path qa-factory/config.json -Value x", True),
    ("row 17: Set-Content -Encoding before the path", "Set-Content -Encoding utf8 qa-factory/config.json x", True),
    ("row 17: Set-Content with a quoted path", "Set-Content 'qa-factory/config.json' 'x'", True),
    ("row 18: Get-Content then Set-Content elsewhere", "Get-Content qa-factory/config.json | Set-Content b.json", False),
    ("row 18: Get-Content, Out-File elsewhere", "Get-Content qa-factory/config.json | Out-File b.json", False),
    ("row 18: Set-Content whose VALUE is the path", "Set-Content -Path b.json -Value qa-factory/config.json", False),
    ("row 19: jq with a redirect elsewhere", "jq . qa-factory/config.json > out.json", False),
    ("row 19: a redirect into it whose command only reads it still refuses", "jq . other.json > qa-factory/config.json", True),
    ("row 20: a write shape in ANOTHER segment (&&)", "sed -i s/a/b/ t.py && cat qa-factory/config.json", False),
    ("row 20: another segment (;)", "sed -i s/a/b/ t.py; cat qa-factory/config.json", False),
    ("row 20: another segment (|)", "cp a.json b.json | cat qa-factory/config.json", False),
    ("row 20: another segment (newline)", "echo x > out.txt\ncat qa-factory/config.json", False),
    ("row 20: the shape and the path in ONE segment after a &&", "cd . && sed -i s/a/b/ qa-factory/config.json", True),
    ("row 20: the redirect belongs to the segment it stands in", "echo x > out.txt && cat qa-factory/config.json", False),
    ("row 21: config_contract --apply",
     "python \"${CLAUDE_PLUGIN_ROOT}/scripts/config_contract.py\" --root . --apply p.json --approval-ref r "
     "--config qa-factory/config.json", False),
    ("row 21: config_contract --apply, the command as the spec writes it (no profile path in it)",
     "python \"${CLAUDE_PLUGIN_ROOT}/scripts/config_contract.py\" --root . --apply p.json --approval-ref r", False),
    ("row 21: config_contract whatever its arguments (a redirect into the profile)",
     "python scripts/config_contract.py --root . --apply p.json > qa-factory/config.json", False),
    ("row 21: project_decisions", "python scripts/project_decisions.py add x > qa-factory/config.json", False),
    ("row 21: runtime_probe --write", "python scripts/runtime_probe.py --write > qa-factory/config.json", False),
    ("row 21: runtime_probe WITHOUT --write is no sanctioned write",
     "python scripts/runtime_probe.py > qa-factory/config.json", True),
    ("row 21: ticket_adapter --migrate-method",
     "python scripts/ticket_adapter.py --migrate-method x > qa-factory/config.json", False),
    ("row 21: ticket_adapter without --migrate-method is no sanctioned write",
     "python scripts/ticket_adapter.py view X > qa-factory/config.json", True),
    ("row 21: the sanction covers its own segment only, not a && neighbour",
     "python scripts/config_contract.py --apply p.json && sed -i s/a/b/ qa-factory/config.json", True),
    ("row 22: a variable-held path passes (unclear -> pass)", "P=qa-factory/config.json; sed -i s/a/b/ $P", False),
    ("row 22: a glob passes (unclear -> pass)", "sed -i s/a/b/ qa-factory/config.j*", False),
    ("row 22: an unrelated command", "ls -la", False),
    ("row 22: a path outside the root", "sed -i s/a/b/ ../elsewhere/qa-factory/config.json", False),
    # edge 1: the sanction belongs to the command that is RUN in the segment, not to a name that appears in it
    ("edge 1: a sanctioned name in a comment does not exempt a redirect",
     "echo {} > qa-factory/config.json # see config_contract.py", True),
    ("edge 1: a sanctioned name as an argument of grep does not exempt a redirect",
     "grep -l x config_contract.py > qa-factory/config.json", True),
    ("edge 1: a sanctioned name as an argument of cat does not exempt a redirect",
     "cat config_contract.py > qa-factory/config.json", True),
    ("edge 1: a sanctioned name as an argument of ANOTHER python script does not exempt it",
     "python scripts/other.py config_contract.py > qa-factory/config.json", True),
    ("edge 1: python -c runs no script file, so a sanctioned name after it does not exempt",
     "python -c \"print(1)\" config_contract.py > qa-factory/config.json", True),
    ("edge 1: the flag must follow the script that needs it, not stand in another command's arguments",
     "python scripts/other.py runtime_probe.py --write > qa-factory/config.json", True),
    ("edge 1: config_contract.py as the command actually run, exactly as the spec writes it",
     "python .../config_contract.py --root . --apply p.json --approval-ref r", False),
    ("edge 1: project_decisions.py run through ${CLAUDE_PLUGIN_ROOT}, with a redirect into the profile",
     "python \"${CLAUDE_PLUGIN_ROOT}/scripts/project_decisions.py\" add x y > qa-factory/config.json", False),
    ("edge 1: the script run directly as the program",
     "./scripts/config_contract.py --apply p.json > qa-factory/config.json", False),
    ("edge 1: python flags before the script (-u, -W with its value)",
     "python -u -W ignore scripts/config_contract.py --apply p.json > qa-factory/config.json", False),
    ("edge 1: a versioned interpreter name",
     "python3.12 scripts/config_contract.py --apply p.json > qa-factory/config.json", False),
    ("edge 1: an environment prefix does not hide the command that is run",
     "FOO=1 python scripts/config_contract.py --apply p.json > qa-factory/config.json", False),
    ("edge 1: the flag a sanctioned script needs, after the script",
     "python scripts/runtime_probe.py x --write > qa-factory/config.json", False),
    # edge 2: shapes on the literal profile path
    ("edge 2: python Path(...).open('w')",
     "python -c \"from pathlib import Path; Path('qa-factory/config.json').open('w').write('x')\"", True),
    ("edge 2: python Path(...).open('a')",
     "python -c \"from pathlib import Path; Path('qa-factory/config.json').open('a')\"", True),
    ("edge 2: python Path(...).open('r+')",
     "python -c \"from pathlib import Path; Path('qa-factory/config.json').open('r+')\"", True),
    ("edge 2: python Path(...).open('x')",
     "python -c \"from pathlib import Path; Path('qa-factory/config.json').open('x')\"", True),
    ("edge 2: python Path(...).open(mode='w')",
     "python -c \"from pathlib import Path; Path('qa-factory/config.json').open(mode='w')\"", True),
    ("edge 2: python Path(...).open('r') reads",
     "python -c \"from pathlib import Path; Path('qa-factory/config.json').open('r').read()\"", False),
    ("edge 2: python Path(...).open() reads (no mode)",
     "python -c \"from pathlib import Path; Path('qa-factory/config.json').open()\"", False),
    ("edge 2: python Path(...).open('w') on another file",
     "python -c \"from pathlib import Path; Path('qa-factory/other.json').open('w')\"", False),
    ("edge 2: python Path(...).open('w') in a heredoc",
     "python - <<'EOF'\nfrom pathlib import Path\nPath('qa-factory/config.json').open('w')\nEOF", True),
    ("edge 2: python shutil.copy onto it",
     "python -c \"import shutil; shutil.copy('c.json', 'qa-factory/config.json')\"", True),
    ("edge 2: python shutil.copy onto it with a call as the source",
     "python -c \"import shutil; shutil.copy(str(p), 'qa-factory/config.json')\"", True),
    ("edge 2: python shutil.copyfile onto it",
     "python -c \"import shutil; shutil.copyfile('c.json', 'qa-factory/config.json')\"", True),
    ("edge 2: python shutil.move onto it",
     "python -c \"import shutil; shutil.move('c.json', 'qa-factory/config.json')\"", True),
    ("edge 2: python os.replace onto it",
     "python -c \"import os; os.replace('c.json', 'qa-factory/config.json')\"", True),
    ("edge 2: python os.rename onto it",
     "python -c \"import os; os.rename('c.json', 'qa-factory/config.json')\"", True),
    ("edge 2: python shutil.copy onto it in a heredoc",
     "python - <<'EOF'\nimport shutil\nshutil.copy('c.json', 'qa-factory/config.json')\nEOF", True),
    ("edge 2: python shutil.copy FROM it reads",
     "python -c \"import shutil; shutil.copy('qa-factory/config.json', 'c.json')\"", False),
    ("edge 2: python shutil.copy onto another file",
     "python -c \"import shutil; shutil.copy('c.json', 'qa-factory/other.json')\"", False),
    ("edge 2: a string replace whose argument is the path is no write",
     "python -c \"print(text.replace('a', 'qa-factory/config.json'))\"", False),
    ("edge 2: rm of it", "rm qa-factory/config.json", True),
    ("edge 2: rm -f of it", "rm -f qa-factory/config.json", True),
    ("edge 2: rm of it, backslashes", "rm qa-factory\\config.json", True),
    ("edge 2: del of it", "del qa-factory\\config.json", True),
    ("edge 2: del /q of it", "del /q qa-factory\\config.json", True),
    ("edge 2: Remove-Item of it", "Remove-Item qa-factory\\config.json", True),
    ("edge 2: Remove-Item -Path -Force of it", "Remove-Item -Path qa-factory/config.json -Force", True),
    ("edge 2: Remove-Item -LiteralPath: of it", "Remove-Item -LiteralPath:qa-factory/config.json", True),
    ("edge 2: rm of another file", "rm qa-factory/config.json.bak", False),
    ("edge 2: rm elsewhere, the profile read in the next segment", "rm b.json && cat qa-factory/config.json", False),
    ("edge 2: mv with it as the source, to a directory", "mv qa-factory/config.json qa-factory/old/", True),
    ("edge 2: mv -t names a directory, and the profile is a source",
     "mv -t /tmp qa-factory/config.json", True),
    ("edge 2: mv of another file into a directory passes", "mv a.json qa-factory/", False),
    ("edge 2: Move-Item with it as the positional source", "Move-Item qa-factory\\config.json c.json", True),
    ("edge 2: Move-Item -LiteralPath source", "Move-Item -LiteralPath qa-factory\\config.json -Destination c.json", True),
    ("edge 2: cp FROM it still reads", "cp qa-factory/config.json /tmp/c.json", False),
    ("edge 2: Copy-Item FROM it still reads", "Copy-Item -LiteralPath qa-factory\\config.json c.json", False),
]


def a_role_shell_is_read_by_shape_and_destination() -> None:
    root = temp_project("qa-guard-cfg-shell-")
    use_project(root)
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    try:
        for label, command, expected in SHELL_ROWS:
            refusal = profile_refusal(shell_event(command))
            check_eq(f"{label} [{command[:60]!r}]: role -> {'refuse' if expected else 'pass'}",
                     refusal is not None, expected)
        for label, command, expected in SHELL_ROWS:
            if not expected:
                continue
            check_eq(f"{label}: the SAME command by the main session passes",
                     profile_refusal(shell_event(command, role="")), None)
        # PowerShell is the same class as Bash
        check("row 17: the PowerShell tool is read the same way",
              bool(profile_refusal(shell_event("Set-Content qa-factory/config.json x", tool="PowerShell"))))
        check_eq("row 5: and its reads pass",
                 profile_refusal(shell_event("Get-Content qa-factory/config.json", tool="PowerShell")), None)
        refusal = profile_refusal(shell_event("sed -i s/a/b/ qa-factory/config.json")) or ""
        check_in("the shell refusal says which shape it read", "`sed -i` on it", refusal)
        check_in("and carries the same doors", "`launch: <cause>`", refusal)
        # cwd: a relative path is the profile of the directory the call stands in
        sub = root / "sub"
        sub.mkdir(exist_ok=True)
        check_eq("a relative path from a subdirectory names another file (unclear -> pass)",
                 profile_refusal(shell_event("sed -i s/a/b/ qa-factory/config.json", cwd=str(sub))), None)
        check("an absolute path is the profile whatever the cwd",
              bool(profile_refusal(shell_event(
                  f"sed -i s/a/b/ {(root / 'qa-factory' / 'config.json').as_posix()}", cwd=str(sub)))))
        check("a relative path from the root, with the cwd given, is the profile",
              bool(profile_refusal(shell_event("sed -i s/a/b/ qa-factory/config.json", cwd=str(root)))))
    finally:
        cleanup(root)


def a_shell_that_cannot_be_read_passes_without_an_exception() -> None:
    root = temp_project("qa-guard-cfg-edge-")
    use_project(root)
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    try:
        big = "cat " + "a " * 100000 + "qa-factory/config.json"
        cases = {
            "row 22: an empty command": ("", None),
            "row 22: a missing command": (None, None),
            "row 22: a 200 KB read": (big, None),
            "row 22: a 200 KB write is still decided": (
                "sed -i s/a/b/ " + "f " * 100000 + "qa-factory/config.json", True),
            "row 22: 200 KB of open( literals": ("python -c \"" + "open('a" * 30000 + "\" config.json", None),
            "row 22: 200 KB of quotes": ("echo " + "'\"" * 100000 + " config.json", None),
            "row 22: non-ASCII bytes in a read": ("cat qa-factory/\u00e9\u4e2d.json config.json", None),
            "row 22: non-ASCII bytes in a write": ("echo \"\u00e9\u4e2d\" > qa-factory/config.json", True),
            "row 22: an unbalanced double quote": ("echo \"unterminated qa-factory/config.json", None),
            "row 22: an unbalanced single quote in a sed": ("sed -i 's/a/b qa-factory/config.json", None),
            "row 22: a lone redirect": ("echo x > config.json >", None),
            "row 22: a NUL in the command": ("cat qa-factory/config.json\x00", None),
            "row 22: only separators": (";;&&|| config.json ()", None),
            "row 22: a here-string with no end": ("python - <<'EOF'\nopen('qa-factory/config.json'", None),
        }
        for label, (command, expected) in cases.items():
            event = {"tool_name": "Bash", "agent_type": ROLE, "tool_input": {"command": command}}
            try:
                got = profile_refusal(event)
                raised = ""
            except BaseException as exc:  # noqa: BLE001 - the point is that nothing escapes
                got, raised = None, f"{type(exc).__name__}: {exc}"
            check_eq(f"{label}: no exception", raised, "")
            check_eq(f"{label}: {'refused' if expected else 'passes'}", got is not None, bool(expected))
        for event, label in (({"tool_name": "Bash", "agent_type": ROLE, "tool_input": None}, "tool_input None"),
                             ({"tool_name": "Bash", "agent_type": ROLE}, "no tool_input"),
                             ({"tool_name": "Write", "agent_type": ROLE, "tool_input": {}}, "a Write with no path"),
                             ({"tool_name": "Read", "agent_type": ROLE, "tool_input": {"file_path": PROFILE}}, "a Read"),
                             ({"tool_name": "Grep", "agent_type": ROLE, "tool_input": {"path": PROFILE}}, "a Grep"),
                             (None, "no event")):
            try:
                got = profile_refusal(event)
                raised = ""
            except BaseException as exc:  # noqa: BLE001
                got, raised = None, f"{type(exc).__name__}: {exc}"
            check_eq(f"row 22: {label}: no exception and a pass", (raised, got), ("", None))
    finally:
        cleanup(root)


def edge_3_a_call_that_does_not_name_the_file_resolves_no_path() -> None:
    """The cheap substring test runs BEFORE the role test and any path resolution. Counted, not timed:
    a role's plain `ls` used to pay for `project_root` and `Path.resolve` on every call (about 13 ms
    measured), which a call that cannot name the profile has no business paying."""
    root = temp_project("qa-guard-cfg-cost-")
    use_project(root)
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    counts = {"resolve": 0, "matcher": 0, "role": 0}
    real_resolve, real_matcher, real_role = Path.resolve, G._profile_matcher, G._is_factory_role

    def counting_resolve(self, *args, **kwargs):
        counts["resolve"] += 1
        return real_resolve(self, *args, **kwargs)

    def counting_matcher(event):
        counts["matcher"] += 1
        return real_matcher(event)

    def counting_role(event):
        counts["role"] += 1
        return real_role(event)

    def run(event: dict) -> tuple:
        for key in counts:
            counts[key] = 0
        got = profile_refusal(event)
        return got, dict(counts)

    Path.resolve, G._profile_matcher, G._is_factory_role = counting_resolve, counting_matcher, counting_role
    try:
        zero = {"resolve": 0, "matcher": 0, "role": 0}
        for label, event in (
                ("a plain ls by a role", shell_event("ls")),
                ("a python one-liner by a role", shell_event("python -c \"print(1)\"")),
                ("a redirect into another file by a role", shell_event("echo x > out.txt")),
                ("a sanctioned script name that is not the profile's, by a role",
                 shell_event("python scripts/config_contract.py --apply p.json")),
                ("a PowerShell call by a role", shell_event("Get-ChildItem", tool="PowerShell")),
                ("a Write of another file by a role", file_event("Write", "notes/x.md")),
                ("an Edit of another file by a role", file_event("Edit", "src/app.py")),
                ("a plain ls by the main session", shell_event("ls", role=""))):
            got, seen = run(event)
            check_eq(f"edge 3: {label} resolves no path and asks no role question", (got, seen), (None, zero))
        got, seen = run(shell_event("CAT NOTES.MD", role=""))
        check_eq("edge 3: a call that does not name the file costs the main session the same (nothing)",
                 seen, zero)
        # positive controls: the same instrument sees the resolution when the file IS named
        got, seen = run(shell_event("sed -i s/a/b/ qa-factory/config.json"))
        check("edge 3 (control): a call that names the profile does resolve paths and is refused",
              bool(got) and seen["resolve"] > 0 and seen["matcher"] == 1, str(seen))
        got, seen = run(file_event("Write", "qa-factory/config.json"))
        check("edge 3 (control): a Write of the profile does resolve paths and is refused",
              bool(got) and seen["resolve"] > 0 and seen["matcher"] == 1, str(seen))
        got, seen = run(shell_event("cat QA-FACTORY/CONFIG.JSON"))
        check("edge 3 (control): the substring test is not case-sensitive",
              seen["matcher"] == 1, str(seen))
        got, seen = run(shell_event("cat qa-factory/config.json", role=""))
        check_eq("edge 3: the main session naming the file is still a pass", got, None)
    finally:
        Path.resolve, G._profile_matcher, G._is_factory_role = real_resolve, real_matcher, real_role
        cleanup(root)


def edge_4_the_refusal_names_the_fallback_a_role_can_always_use() -> None:
    root = temp_project("qa-guard-cfg-text-")
    use_project(root)
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    try:
        refusal = profile_refusal(file_event("Write", PROFILE)) or ""
        check_in("edge 4: the refusal says what to write when the cause is not known",
                 "If you cannot tell the cause, write `launch: unknown`", refusal)
        check_in("edge 4: the earlier door stays", "name `launch: <cause>` and the evidence line", refusal)
        data = json.loads((harness.PLUGIN_ROOT / "references" / "launch-causes.json").read_text(encoding="utf-8"))
        causes = data.get("causes") or {}
        ids = set(causes) if isinstance(causes, dict) else {str(c.get("id")) for c in causes}
        named = set(re.findall(r"`launch: ([a-z_]+)`", refusal))
        check_eq("edge 4: every cause id the text names is a cause of launch-causes.json (the door opens)",
                 (bool(named), named <= ids), (True, True))
        check_in("edge 4: and `unknown` is one of them", "unknown", ids)
        for banned in ("config_contract", "--apply", "onboarding execution batch"):
            check(f"edge 4: still no {banned!r} (a door the role cannot use)", banned not in refusal, banned)
        shell = profile_refusal(shell_event("rm qa-factory/config.json")) or ""
        check_in("edge 4: the shell refusal carries the fallback as well", "`launch: unknown`", shell)
    finally:
        cleanup(root)


def edge_5_a_role_event_with_no_role_name_passes_as_the_main_session_does() -> None:
    """A resumed session whose agent could not be found sends no `agent_type`: it cannot be told from the
    main session, which must never be refused. The dispatch-boundary detector reports the change."""
    root = temp_project("qa-guard-cfg-noname-")
    use_project(root)
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    try:
        transcript = "/x/session/subagents/agent-7.jsonl"
        for label, event in (
                ("Write", file_event("Write", PROFILE, role="")),
                ("Edit", file_event("Edit", PROFILE, role="")),
                ("a shell redirect", shell_event("echo x > qa-factory/config.json", role="")),
                ("rm", shell_event("rm qa-factory/config.json", role="")),
                ("an empty agent_type", dict(shell_event("rm qa-factory/config.json", role=""), agent_type="")),
                ("a blank agent_type", dict(shell_event("rm qa-factory/config.json", role=""), agent_type="  ")),
                ("a null agent_type", dict(shell_event("rm qa-factory/config.json", role=""), agent_type=None))):
            check_eq(f"edge 5: {label} with no role name passes", profile_refusal(event), None)
            check_eq(f"edge 5: {label} with no role name, from a subagent transcript, passes",
                     profile_refusal(dict(event, transcript_path=transcript)), None)
        check("edge 5 (control): the same call with a role name is refused",
              bool(profile_refusal(shell_event("rm qa-factory/config.json"))))
    finally:
        cleanup(root)


def run_hook(root: Path, event: dict) -> tuple:
    """The real hook process on this event: (exit code, stderr)."""
    import subprocess
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-B", str(harness.SCRIPTS / "guard_pre_tool.py")],
                          input=json.dumps(dict(event, cwd=str(root))), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(root), env=env, timeout=120)
    return done.returncode, done.stderr


def the_check_is_registered_after_every_older_refusal() -> None:
    """Position invariant: the profile check sits LAST in every chain of main(), so every older refusal
    is reached exactly as before and this one refuses only a call they all passed."""
    root = temp_project("qa-guard-cfg-wire-")
    use_project(root)
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    try:
        story(root, running_role=ROLE)
        code, err = run_hook(root, file_event("Write", str(root / "qa-factory" / "config.json")))
        check_eq("hook: a role's Write of the profile exits 2", code, 2)
        check_in("hook: and says why", "does not write qa-factory/config.json", err)
        code, err = run_hook(root, file_event("Write", str(root / "qa-factory" / "config.json"), role=""))
        check_eq("hook: the main session's Write of the profile exits 0 (a P-00 warning may print)",
                 (code, "does not write qa-factory/config.json" in err), (0, False))
        code, err = run_hook(root, shell_event("python -c \"open('qa-factory/config.json','w').write('x')\""))
        check_eq("hook: a shell write with NO write marker still reaches the check (exit 2)", code, 2)
        check_in("hook: with the profile refusal", "does not write qa-factory/config.json", err)
        code, err = run_hook(root, shell_event("sed -i s/a/b/ qa-factory/config.json"))
        check_eq("hook: sed -i on the profile exits 2", code, 2)
        code, err = run_hook(root, shell_event("cat qa-factory/config.json"))
        check_eq("hook: a read of the profile exits 0", (code, "does not write" in err), (0, False))
        code, err = run_hook(root, shell_event("sed -i s/a/b/ t.py && cat qa-factory/config.json"))
        check_eq("hook: a write elsewhere and a read of the profile exits 0",
                 (code, "does not write" in err), (0, False))
        # an OLDER refusal wins, with its own words: the new check never replaces it and never hides it
        code, err = run_hook(root, shell_event("poetry run pytest tests/x.py > qa-factory/config.json"))
        check_eq("hook: an older refusal (a direct pytest launch) still fires first", code, 2)
        check_in("hook: with ITS words", "direct pytest launch", err)
        check("hook: and not the profile's", "does not write qa-factory/config.json" not in err, err[:200])
        code, err = run_hook(root, shell_event("git config --global x y > qa-factory/config.json"))
        check_in("hook: git configuration is still refused first", "changing git configuration", err)
        # a call every older check refuses is never turned into a pass, main session included
        code, err = run_hook(root, shell_event("poetry run pytest tests/x.py", role=""))
        check_eq("hook: the main session's direct pytest is refused by the older check as before", code, 2)
    finally:
        cleanup(root)


def b220_the_probe_is_no_new_door_to_the_profile() -> None:
    """B-220 K8 (t-385): the onboarding probe writes the config ONLY through `config_contract.py --record-approval` / `--apply`
    (`apply_plan`), on a person's yes. So the guard's list of sanctioned writers is exactly what it was, a role still cannot write
    the profile with a file tool or a shell, and the new script is sanctioned for nothing: a role that pipes its output into the
    profile is refused like any other write."""
    check_eq("K8: the sanctioned writers of the profile are the four there were (config_contract.py is one, by name)",
             dict(G._SANCTIONED_CONFIG_SCRIPTS),
             {"config_contract.py": (), "project_decisions.py": (), "runtime_probe.py": ("--write",), "ticket_adapter.py": ("--migrate-method",)})
    check("K8: onboarding_probe.py is not among them", "onboarding_probe.py" not in G._SANCTIONED_CONFIG_SCRIPTS)
    root = temp_project("qa-guard-cfg-b220-")
    use_project(root)
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    try:
        check("K8: a role's Write of the profile is still refused", bool(profile_refusal(file_event("Write", PROFILE))))
        check("K8: a role redirecting the probe's output into the profile is refused (the probe is no sanctioned writer)",
              bool(profile_refusal(shell_event("python scripts/onboarding_probe.py --probe-profiles > qa-factory/config.json"))))
        check("K8: a role redirecting a sealed proposal into the profile is refused",
              bool(profile_refusal(shell_event("cp /tmp/cure-web-123.json qa-factory/config.json"))))
        check_eq("K8: the probe itself reads (it names no profile path), so a role may run it",
                 profile_refusal(shell_event("python scripts/onboarding_probe.py --root . --probe-profiles --proposals-dir /tmp/p --json")), None)
    finally:
        cleanup(root)


def main() -> None:
    onboarding_may_write_a_persons_words_under_the_project_state()
    onboarding_notes_pass_the_real_guard_before_any_config()
    a_role_never_writes_the_profile_through_a_file_tool()
    b220_the_probe_is_no_new_door_to_the_profile()
    a_role_shell_is_read_by_shape_and_destination()
    a_shell_that_cannot_be_read_passes_without_an_exception()
    edge_3_a_call_that_does_not_name_the_file_resolves_no_path()
    edge_4_the_refusal_names_the_fallback_a_role_can_always_use()
    edge_5_a_role_event_with_no_role_name_passes_as_the_main_session_does()
    the_check_is_registered_after_every_older_refusal()
    a_critics_findings_are_the_critics_not_the_designers()
    every_declared_owner_is_exercised()
    the_fallback_map_is_a_subset()
    a_file_nobody_owns_is_not_this_guards_business()
    finish("test_guard_write_owners")


if __name__ == "__main__":
    main()
