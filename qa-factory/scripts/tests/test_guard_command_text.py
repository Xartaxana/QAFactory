#!/usr/bin/env python3
"""The pre-tool guard matches the call a command MAKES, not the text it carries.

2026-09-23, this factory's own session: a subagent wrote a scratch file through a Bash
heredoc; the file held a Jira comment that quoted `waiver.py --stage S9 --block "still
running"` as an example of the call a person makes. `human_word_check` matched that literal
anywhere in the command string, heredoc body included, and refused the write. The agent then
routed around the guard with a placeholder and a `perl` substitution - exactly the move this
factory forbids roles to make - and the host raised a security warning.

The half of this file that matters most is the second one: every spelling in which a role
could actually RUN one of the guarded commands - plainly, through `bash -c`, through
`pwsh -Command`, through `python -c`, in a subshell, behind a `cd`, inside a heredoc fed to
an interpreter, or hidden in a command substitution inside an `echo` - is still refused.
Loosening the matcher is only safe while those stay red.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import guard_pre_tool as G  # noqa: E402

ROLE = {"tool_name": "Bash", "agent_type": "qa-factory:qa-scout"}
# The comment the subagent was writing when the guard refused it, shortened but whole in shape.
INCIDENT = ("cat > /tmp/qa-comment.md <<'EOF'\n"
            "Gate S9 is open. To pass it, run\n"
            '  python scripts/waiver.py --stage S9 --block "still running" --decision ok\n'
            "and paste the receipt here.\n"
            "EOF")


def parts(command):
    return G.command_text_parts(command)


def refused(command, event=None):
    """True when the human-word check refuses this command from a role."""
    ev = dict(ROLE, **(event or {}))
    ev["tool_input"] = {"command": command}
    return G._blocked(G.human_word_check, ev, {}) is not None


def refusal(command):
    ev = dict(ROLE, tool_input={"command": command})
    return G._blocked(G.human_word_check, ev, {}) or ""


def blocked_by(fn, command, cfg=None):
    return G._blocked(fn, {"tool_name": "Bash", "tool_input": {"command": command}},
                      cfg or {}) is not None


# --- the helper itself --------------------------------------------------------------------

def the_helper_separates_what_runs_from_what_is_carried() -> None:
    p = parts(INCIDENT)
    check_not_in("the heredoc body is not part of what runs", "waiver.py", p["exec"])
    check_in("the heredoc body is kept as text", "waiver.py --stage S9", p["text"])
    check_in("and the region is named", "a heredoc body", "".join(p["where"]))
    check_in("the command that receives it stays executable", "cat", p["exec"])

    p = parts("python - <<EOF\nrun('python waiver.py --stage S9 --block x')\nEOF")
    check_in("a body handed to an interpreter IS what runs", "waiver.py", p["exec"])
    check_eq("so nothing is set aside as text", p["where"], [])

    p = parts("cd /proj && cat >> notes.md <<-NOTE\n\twaiver.py --stage S9\n\tNOTE\ncat notes.md")
    check_not_in("`<<-` is a heredoc too", "waiver.py", p["exec"])
    check_in("and the command after the terminator is still seen", "cat notes.md", p["exec"])

    p = parts("cat > x.md <<'EOF'\nwaiver.py --stage S9\n")
    check_not_in("an unterminated heredoc runs out at the end of the string", "waiver.py",
                 p["exec"])

    p = parts("$body = @'\npython waiver.py --stage S9 --block x\n'@\nSet-Content x.md $body")
    check_not_in("a PowerShell here-string is text", "waiver.py", p["exec"])
    check_in("and is named as one", "a PowerShell here-string", "".join(p["where"]))

    p = parts('echo "waiver.py --stage S9" > note.txt')
    check_not_in("a quoted argument of echo is text", "waiver.py", p["exec"])
    check_in("named with the command that prints it", "`echo`", "".join(p["where"]))

    p = parts("Set-Content -Path note.txt -Value 'python waiver.py --stage S9'")
    check_not_in("so is the -Value of Set-Content", "waiver.py", p["exec"])

    p = parts('cat report.md <<< "waiver.py --stage S9"')
    check_not_in("so is a here-string", "waiver.py", p["exec"])

    p = parts('bash -c "python waiver.py --stage S9 --block x"')
    check_in("a `-c` body is a call, not a string", "waiver.py", p["exec"])
    check_eq("and nothing about it is text", p["where"], [])

    p = parts('echo "$(python waiver.py --stage S9 --block x)"')
    check_in("a command substitution inside a quoted argument still runs", "waiver.py",
             p["exec"])

    p = parts("cat > x.md <<EOF\n$(python waiver.py --stage S9)\nEOF")
    check_in("an unquoted heredoc delimiter expands its body, so the body runs", "waiver.py",
             p["exec"])

    check_eq("an empty command has nothing in it", parts(None)["exec"], "")
    check_eq("an ordinary command is untouched", parts("git status --porcelain")["exec"],
             "git status --porcelain")


def the_refusal_says_where_it_matched() -> None:
    plain = refusal("python scripts/waiver.py --stage S9 --block x --decision ok")
    check_in("a plain call names the arguments", "Found in the command's arguments.", plain)
    mixed = refusal("cat > note.md <<'EOF'\nwaiver.py --stage S9\nEOF\n"
                    "python scripts/waiver.py --stage S9 --block x")
    check_in("a mixed command says which half was not checked", "a heredoc body", mixed)
    check_in("and says so as plainly as that", "was not checked", mixed)


# --- what a role can still not do ----------------------------------------------------------

def every_spelling_of_the_real_call_is_still_refused() -> None:
    for command, why in [
        ("python scripts/waiver.py --stage S9 --block x --decision ok", "the plain call"),
        ("python waiver.py --task T-1 --stage S1 --block '*' --decision ok", "with quoted flags"),
        ('bash -c "python waiver.py --stage S9 --block x"', "through bash -c"),
        ("sh -c 'python waiver.py --stage S9 --block x'", "through sh -c"),
        ('pwsh -Command "python waiver.py --stage S9 --block x"', "through pwsh -Command"),
        ('powershell -Command "python waiver.py --stage S9"', "through powershell -Command"),
        ('python -c "import subprocess; subprocess.run([\'waiver.py\', \'--stage\', \'S9\'])"',
         "through python -c"),
        ("(cd /proj && python waiver.py --stage S9 --block x)", "in a subshell"),
        ("cd /proj; python waiver.py --stage S9 --block x", "after a cd"),
        ("ls | xargs -I{} python waiver.py --stage S9 --block x", "at the end of a pipeline"),
        ("python - <<EOF\nimport os\nos.system('waiver.py --stage S9')\nEOF",
         "inside a heredoc an interpreter runs"),
        ('echo "$(python waiver.py --stage S9 --block x)"',
         "hidden in a command substitution"),
        ("python scripts/ticket_adapter.py accept-gap --output x --all-unavailable --words ok",
         "accept-gap"),
        ('bash -c "python ticket_adapter.py accept-gap --output x"', "accept-gap through bash -c"),
        ("python ticket_adapter.py review --output x --record --words ok", "review --record"),
        ('pwsh -Command "python ticket_adapter.py review --record --words ok"',
         "review --record through pwsh"),
    ]:
        check(f"a role is still refused: {why}", refused(command))


def role_refused_load_revoke() -> None:
    """B-231 P7: the person's list of sources to leave out, and taking one back, are the person's
    word: a role choosing its own sources would be the factory excusing itself."""
    for command, why in [
        ("python scripts/source_exclusions.py --task T-1 --load list.txt", "--load"),
        ("python source_exclusions.py --task T-1 --revoke X1 --words 'read it'", "--revoke"),
        ("python source_exclusions.py --revoke=X1 --task T-1 --words w", "--revoke=<id>"),
        ("python source_exclusions.py --task T-1 --load=C:/list.txt", "--load=<file>"),
        ("python SOURCE_EXCLUSIONS.PY --task T-1 --REVOKE X1 --words w", "capitals"),
        ('bash -c "python source_exclusions.py --task T-1 --revoke X1 --words w"', "through bash -c"),
        ('pwsh -Command "python source_exclusions.py --task T-1 --load list.txt"', "through pwsh -Command"),
        ("cd /proj && python source_exclusions.py --task T-1 --load list.txt", "after a cd"),
    ]:
        check(f"a role is refused: source_exclusions {why}", refused(command))
    message = refusal("python source_exclusions.py --task T-1 --revoke X1 --words w")
    check_in("the refusal names the commands it closed", "`source_exclusions.py --load` and `--revoke`", message)
    check_in("and tells the role its own door (--show) and where the open point goes (the digest)", "--show", message)
    check_in("...and the digest", "digest", message)
    check("the orchestrator is never refused",
          G._blocked(G.human_word_check, {"tool_name": "Bash", "tool_input": {
              "command": "python source_exclusions.py --task T-1 --load list.txt"}}, {}) is None)


def role_refused_decide() -> None:
    """t-721 D4: `story_step.py decide` records the person's decision about a dispatch (S5 cases they run themselves,
    work left open, a stage closed as it is). A role running it would hand its own cases to the person or close its
    own stage: closed to every role, open to the orchestrator. `finish`, `start` and `where` stay open."""
    for command, why in [
        ("python scripts/story_step.py decide --task T-1 --dispatch-id D --hand TC-9 --words-file w.txt", "--hand"),
        ("python story_step.py decide --task T-1 --dispatch-id D --open --words-file w.txt", "--open"),
        ("python story_step.py decide --task T-1 --dispatch-id D --close --words-file w.txt", "--close"),
        ("python STORY_STEP.PY DECIDE --task T-1 --dispatch-id D --close --words-file w.txt", "capitals"),
        ('bash -c "python story_step.py decide --task T-1 --dispatch-id D --close --words-file w"', "through bash -c"),
        ("cd /proj && python story_step.py decide --task T-1 --dispatch-id D --hand TC-1 --words-file w", "after a cd"),
    ]:
        check(f"a role is refused: story_step decide {why}", refused(command))
    for command, why in [
        ("python story_step.py finish --task T-1 --dispatch-id D --digest x", "finish"),
        ("python story_step.py where --task T-1", "where"),
        ("cat > note.md <<'EOF'\nstory_step.py decide --hand TC-1 is not mine to run.\nEOF", "a heredoc quoting decide"),
        ("python other_tool.py decide --task T-1", "another script's decide"),
    ]:
        check(f"a role is not refused: story_step {why}", not refused(command))
    check("the orchestrator is never refused",
          G._blocked(G.human_word_check, {"tool_name": "Bash", "tool_input": {
              "command": "python story_step.py decide --task T-1 --dispatch-id D --hand TC-1 --words-file w"}}, {}) is None)


def role_allowed_show() -> None:
    """`--show` stays open (FR-39: what a role is told to honour, it may read), and so does any
    mention of the commands that only carries the words."""
    for command, why in [
        ("python scripts/source_exclusions.py --task T-1 --show", "--show"),
        ("python source_exclusions.py --show --task T-1", "--show first"),
        ("cat > note.md <<'EOF'\nsource_exclusions.py --task T-1 --load list.txt is not mine to run.\nEOF",
         "a heredoc quoting --load"),
        ("echo \"source_exclusions.py --revoke X1 is the orchestrator's\" >> digest.md", "a digest line quoting --revoke"),
        ("python other_tool.py --load list.txt", "another script's --load"),
    ]:
        check(f"a role is not refused: {why}", not refused(command))


def the_words_a_command_only_carries_are_not_a_call() -> None:
    for command, why in [
        (INCIDENT, "the heredoc of the 2026-09-23 incident"),
        ('echo "run waiver.py --stage S9 --block x yourself" >> digest.md',
         "quoting the call in a digest line"),
        ("$note = @'\nAsk the person to run waiver.py --stage S9.\n'@",
         "a PowerShell here-string"),
        ("Set-Content -Path digest.md -Value 'waiver.py --stage S9 is the orchestrator''s'",
         "Set-Content storing the sentence"),
        ("cat > gap.md <<'EOF'\nticket_adapter.py accept-gap is not mine to run.\nEOF",
         "a heredoc quoting accept-gap"),
        ("printf '%s\\n' 'ticket_adapter.py review --record'", "printf of the same words"),
    ]:
        check(f"a role is not refused for: {why}", not refused(command))


def the_orchestrator_is_never_refused() -> None:
    plain = {"tool_name": "Bash", "tool_input": {
        "command": "python scripts/waiver.py --stage S9 --block x --decision ok"}}
    check_eq("no role signature, no refusal", G._blocked(G.human_word_check, plain, {}), None)
    check("a role signature from the transcript path is enough",
          refused("python waiver.py --stage S9 --block x",
                  {"agent_type": "", "transcript_path": "C:/x/subagents/agent-1.jsonl"}))


def the_neighbouring_checks_read_the_same_way() -> None:
    declared = {"external_writes": {"commands": {"bugs": "dmtools jira create {file}"}}}
    for command, why in [
        ("glab issue create --title x", "the plain tracker write"),
        ('bash -c "glab issue create --title x"', "the same write through bash -c"),
        ("dmtools jira create bug.json", "a project-declared write command"),
        ("echo external_writes.py; jira issue create QA-1", "chained after a mention"),
    ]:
        check(f"writes: still blocked, {why}", blocked_by(G.writes_check, command, declared))
    for command, why in [
        ("cat > proposal.md <<'EOF'\nglab issue create --title x\nEOF",
         "a proposal file quoting the command"),
        ('echo "glab issue create --title x" > proposals/bug.md', "echoed into a proposal"),
    ]:
        check(f"writes: not blocked, {why}", not blocked_by(G.writes_check, command, declared))

    check("git config: the call is blocked",
          blocked_by(G.git_config_check, "git config --global safe.directory C:/repo"))
    check("git config: the call inside bash -c is blocked",
          blocked_by(G.git_config_check, 'bash -c "git config --global core.longpaths true"'))
    check("git config: a heredoc quoting it is not",
          not blocked_by(G.git_config_check,
                         "cat > note.md <<'EOF'\nnever run git config --global\nEOF"))
    check("git config: reading is still allowed",
          not blocked_by(G.git_config_check, "git config --get remote.origin.url"))


PERSON_WORD_CALLS = [
    ("python scripts/stand_identity.py confirm --task T-1 --environment localhost --profile api --revision x --words ok", "confirm"),
    ("python stand_identity.py record --environment localhost --profile api --method person_confirms --words ok", "record"),
    ("python stand_identity.py forget --environment localhost --profile api --words ok", "forget"),
    ("python stand_identity.py unconfirm --task T-1 --environment localhost --profile api --words ok", "unconfirm"),
    ('python "C:/plugin/scripts/stand_identity.py" confirm --task T-1', "a quoted path"),
    ("python STAND_IDENTITY.PY CONFIRM --task T-1", "capitals"),
    ('bash -c "python stand_identity.py confirm --task T-1 --words ok"', "through bash -c"),
    ('pwsh -Command "python stand_identity.py record --method person_confirms"', "through pwsh -Command"),
    ("cd /proj && python stand_identity.py confirm --task T-1 --words ok", "after a cd"),
    ("(cd /proj; python stand_identity.py forget --words ok)", "in a subshell"),
    ('python -c "import subprocess; subprocess.run([\'stand_identity.py\', \'confirm\', \'--task\', \'T-1\'])"', "through python -c"),
    ("python - <<EOF\nimport os\nos.system('python stand_identity.py confirm --task T-1')\nEOF", "inside a heredoc an interpreter runs"),
]


def role_refused_stand_identity() -> None:
    """K34 (t-300 Q12): `stand_identity.py record|confirm|forget|unconfirm` are a person's word about which build a stand
    runs. A role that could run them would confirm its OWN build and unblock its own run (G11)."""
    for command, why in PERSON_WORD_CALLS:
        check(f"K34: a role is refused: stand_identity.py {why}", refused(command))
    message = refusal("python stand_identity.py confirm --task T-1 --words ok")
    check_in("K34: the refusal names the commands it closed", "`stand_identity.py record`, `confirm`, `forget` and `unconfirm`", message)
    check_in("K34: and the two a role MAY run (its door, FR-2)", "`show` and `validate` are open to you", message)
    check_in("K34: and where the open point goes (the digest)", "digest", message)
    check("K34 CONTROL: `waiver.py --stage` is still refused (the older commands did not move)",
          refused("python scripts/waiver.py --stage S9 --block x --decision ok"))
    check("K34 CONTROL: so is `source_exclusions.py --load`", refused("python source_exclusions.py --task T-1 --load list.txt"))
    # the SAME commands from the driver, the conductor and the orchestrator (no role signature) are allowed: they record the word
    for command, why in PERSON_WORD_CALLS[:5]:
        plain = {"tool_name": "Bash", "tool_input": {"command": command}}
        check_eq(f"K34: with no role signature nothing is refused ({why})", G._blocked(G.human_word_check, plain, {}), None)
    check("K34: a role signature from the subagent transcript path is enough",
          refused("python stand_identity.py confirm --task T-1", {"agent_type": "", "transcript_path": "C:/x/subagents/agent-1.jsonl"}))
    for command, why in [
        ("python scripts/stand_identity.py show --environment localhost", "show"),
        ("python stand_identity.py show --json", "show --json"),
        ("python stand_identity.py validate", "validate"),
        ("python stand_identity.py validate --file confirm.json", "validate --file confirm.json (the word confirm in a file name)"),
        ("python stand_identity.py show --profile record", "show with a profile named like a subcommand"),
        ("cat > note.md <<'EOF'\nstand_identity.py confirm is the orchestrator's to run.\nEOF", "a heredoc quoting confirm"),
        ("echo \"stand_identity.py record --method person_confirms is not mine\" >> digest.md", "a digest line quoting record"),
        ("python other_tool.py confirm --task T-1", "another script's confirm"),
        ("python stand_identity_notes.py confirm", "a script that only starts like it"),
    ]:
        check(f"K34: a role is not refused: {why}", not refused(command))


def the_host_binding_gives_a_driver_launched_role_its_signature() -> None:
    """MEASURED (t-300 N1a, pt.6(a)): a driver-launched role is its OWN session, not a subagent of anybody, and the
    hook payload of its tool calls is not stored anywhere. What `read_event` hands the guard is `enrich(normalize(event))`:
    `host_dispatch.enrich` looks up `qa-factory/state/host-dispatches/<sha256(session_id)>.json` - the binding `story_step`
    wrote at the role's start (man1 copy, the code critic of 02.10: `agent_id` = the session id, `agent_type: qa-code-critic`,
    `bound_by: story_step`) - and copies `agent_type` into the event. So the guard keys on `agent_type`, and the fixture
    here builds it THE WAY IT ARRIVES: through the binding, not by hand."""
    import hashlib
    import json
    import os
    import host_dispatch
    from harness import cleanup, temp_project, use_project
    root = temp_project()
    saved = os.environ.get("CLAUDE_PROJECT_DIR")
    try:
        use_project(root)
        session = "4e123d7b-0b86-4ded-8d6a-96859828fc08"
        binding = root / "qa-factory" / "state" / "host-dispatches" / (hashlib.sha256(session.encode()).hexdigest() + ".json")
        binding.parent.mkdir(parents=True)
        command = "python stand_identity.py confirm --task T-1 --environment localhost --profile api --words ok"
        event = {"session_id": session, "tool_name": "Bash", "tool_input": {"command": command}}
        check_eq("binding: with NO binding the event has no agent_type (the main session, or a driver run not yet bound)",
                 "agent_type" in host_dispatch.enrich(dict(event, tool_input=event["tool_input"])), False)
        check_eq("binding: ...and the check lets it pass", G._blocked(G.human_word_check, host_dispatch.enrich(dict(event)), {}), None)
        binding.write_text(json.dumps({"agent_id": session, "agent_type": "qa-code-critic", "task_id": "T-1",
                                       "dispatch_id": "S5-qa-code-critic-6", "status": "running", "bound_by": "story_step"}),
                           encoding="utf-8")
        enriched = host_dispatch.enrich(dict(event))
        check_eq("binding: with the story_step binding the event carries the role's agent_type", enriched.get("agent_type"), "qa-code-critic")
        check_in("binding: and the person-word check refuses the command from that session",
                 "a person's word is recorded by the orchestrator", G._blocked(G.human_word_check, enriched, {}) or "")
        check_eq("binding: while `show` from the same session stays open",
                 G._blocked(G.human_word_check, host_dispatch.enrich(dict(event, tool_input={"command": "python stand_identity.py show"})), {}), None)
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved
        import hooklib
        hooklib._PROJECT_ROOT_CACHE = None
        cleanup(root)


def role_may_not_write_the_stand_records() -> None:
    """K34 (path half, §0b): the registry and a story's confirmations ARE the person's word, so the road that does not go
    through the CLI - a Write, an Edit, a redirection, a copy - is closed to a role too (`config_write_check`'s shape)."""
    import os
    from harness import cleanup, temp_project, use_project
    root = temp_project()
    saved = os.environ.get("CLAUDE_PROJECT_DIR")
    try:
        use_project(root)
        registry = (root / "qa-factory" / "records" / "stand-identity.json").as_posix()
        confirmations = (root / "qa-factory" / "artifacts" / "QA-1" / "state" / "stand-confirmations.jsonl").as_posix()
        role = {"agent_type": "qa-factory:qa-automator", "cwd": str(root)}

        def blocked(tool, path=None, command=None, **who):
            ti = {"file_path": path} if path is not None else {"command": command}
            return G._blocked(G.stand_record_write_check, dict(who or role, tool_name=tool, tool_input=ti), {}) is not None
        for tool in ("Write", "Edit", "NotebookEdit"):
            check(f"K34 path: a role's {tool} on the registry is refused", blocked(tool, registry))
            check(f"K34 path: a role's {tool} on a story's confirmations is refused", blocked(tool, confirmations))
        # B-414 R10: the environment record is a person's word about the environment too
        environment = (root / "qa-factory" / "records" / "environment-properties.json").as_posix()
        for tool in ("Write", "Edit", "NotebookEdit"):
            check(f"B-414 R10: a role's {tool} on the environment record is refused", blocked(tool, environment))
        for command, why in [(f"echo '{{}}' > {environment}", "a redirection into the environment record"),
                             ("echo x >> qa-factory/records/environment-properties.json", "an append, relative path"),
                             (f"rm {environment}", "rm of the environment record (the person's words would be gone)")]:
            check(f"B-414 R10: a role is refused: {why}", blocked("Bash", command=command))
        check("B-414 R10: reading the environment record is open", not blocked("Bash", command=f"cat {environment}"))
        check("B-414 R10: another file of the same name elsewhere is not refused", not blocked("Bash", command="echo x > /tmp/other/environment-properties.json"))
        check_in("B-414 R10: the refusal names the file", "environment-properties.json",
                 G._blocked(G.stand_record_write_check, dict(role, tool_name="Write", tool_input={"file_path": environment}), {}) or "")
        check("B-414: the main session (the driver, the conductor) records it: never refused",
              G._blocked(G.stand_record_write_check, {"cwd": str(root), "tool_name": "Write", "tool_input": {"file_path": environment}}, {}) is None)
        for command in ("python environment_record.py record --task T --option accept", "python environment_record.py revoke --id EP-1"):
            check(f"B-414: a role may not run `{command.split()[2]}` (a person's word)",
                  G._blocked(G.human_word_check, dict(role, tool_name="Bash", tool_input={"command": command}), {}) is not None)
        check("B-414: but `show` is open to a role",
              G._blocked(G.human_word_check, dict(role, tool_name="Bash", tool_input={"command": "python environment_record.py show"}), {}) is None)
        message = G._blocked(G.stand_record_write_check, dict(role, tool_name="Write", tool_input={"file_path": registry}), {})
        check_in("K34 path: the refusal says what it protects and the role's door (the digest)", "digest", message or "")
        check_in("K34 path: and names the files", "stand-identity.json", message or "")
        check_in("K34 path: and says reading is open", "Reading the files", message or "")
        for command, why in [
            (f"echo '{{}}' > {registry}", "a redirection into the registry"),
            ("echo x >> qa-factory/records/stand-identity.json", "an append, relative path"),
            (f"tee {confirmations} < x.jsonl", "tee into a confirmation file"),
            (f"cp /tmp/x.json {registry}", "cp onto the registry"),
            (f"mv /tmp/x.jsonl {confirmations}", "mv onto a confirmation file"),
            ("sed -i s/a/b/ qa-factory/records/stand-identity.json", "sed -i on the registry"),
            (f"rm {registry}", "rm of the registry (the person's words would be gone)"),
            (f"python -c \"open('{registry}', 'w').write('{{}}')\"", "python open(..., 'w') with the literal path"),
        ]:
            check(f"K34 path: a role is refused: {why}", blocked("Bash", command=command))
        for command, why in [
            (f"cat {registry}", "reading the registry"),
            ("python stand_identity.py show", "the show command"),
            (f"grep method {registry}", "grep of the registry"),
            (f"cp {registry} /tmp/copy.json", "copying it AWAY (a read)"),
            ("cat > note.md <<'EOF'\necho x > qa-factory/records/stand-identity.json is not mine\nEOF", "a heredoc quoting the redirection"),
            ("echo x > /tmp/other/stand-identity.json", "another folder's file of the same name"),
            ("echo x > qa-factory/artifacts/QA-1/work/stand-confirmations.jsonl", "a file of that name outside `state/`"),
            ("echo x > qa-factory/records/stand-identity.json.bak", "a sibling name"),
        ]:
            check(f"K34 path: a role is not refused: {why}", not blocked("Bash", command=command))
        check("K34 path: a role's Read of the registry is not this check's business", not blocked("Read", registry))
        check("K34 path: another file under records/ is not refused", not blocked("Write", (root / "qa-factory" / "records" / "journal.jsonl").as_posix()))
        main_session = {"cwd": str(root)}
        check("K34 path: the MAIN session (the conductor, the orchestrator) is never refused: it records the word",
              G._blocked(G.stand_record_write_check, dict(main_session, tool_name="Write", tool_input={"file_path": registry}), {}) is None)
        # said out loud: a write HIDDEN in a `bash -c` / `pwsh -Command` body is not unwrapped here, exactly as
        # config_write_check does not unwrap it (error direction: toward PASS on anything unclear; the `recorded_by` of
        # every line and `stand_identity.py validate` are the detectors)
        check("K34 path (known residual, same as config_write_check): a redirection inside `bash -c \"...\"` is not decided",
              not blocked("Bash", command=f"bash -c \"echo x > {registry}\""))
        check("K34 path: nor from the main session by a shell redirection",
              G._blocked(G.stand_record_write_check, dict(main_session, tool_name="Bash", tool_input={"command": f"echo x > {registry}"}), {}) is None)
        check("K34 path: a subagent transcript marks a role too",
              G._blocked(G.stand_record_write_check, dict(main_session, transcript_path="C:/x/subagents/a.jsonl", tool_name="Write",
                                                          tool_input={"file_path": registry}), {}) is not None)
        check("K34 path: a call that names neither file costs nothing and passes",
              G._blocked(G.stand_record_write_check, dict(role, tool_name="Write", tool_input={"file_path": "tests/test_x.py"}), {}) is None)
        check("K34 path: and a malformed event is `cannot tell`, which passes",
              G._blocked(G.stand_record_write_check, {"tool_name": "Write", "tool_input": None, "agent_type": "qa-x"}, {}) is None)
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved
        import hooklib
        hooklib._PROJECT_ROOT_CACHE = None
        cleanup(root)


def the_stand_door_is_a_digest_the_form_accepts() -> None:
    """t-345 F1 (FR-2, FR-57): the door a refusal names must be one the refused party can use. The stand-record guard tells a
    role to hand off a stand problem in its digest; the digest's exit gate (`role_digest.parse`) refused the first spelling of
    that door (a free `stand: ...` line), so the role was told to do what the next gate then refused. The shape the message
    prescribes is PASTED here as a digest and the form must accept it; the old free line must be refused (the negative control)."""
    import re
    import role_digest as RD
    import refusal_registry as RR
    message = G.STAND_RECORD_MSG
    shape = re.search(r"`(stand · blocked · <[^`>]+>)`", message)
    check("F1: the message prescribes a row `stand · blocked · <what is wrong, at most 80 characters>`", shape is not None, message[:300])
    row_shape = shape.group(1) if shape else "stand · blocked · <x>"

    def digest(row: str, path: str = "artifacts/QA-1/work/handoffs/S5-qa-automator-1.yaml") -> str:
        return f"qa-automator S5 e2e-ui · halt\n{row}\n{path}"
    reason = "the image of the container carries no revision label"
    pasted = re.sub(r"<[^>]+>", reason, row_shape)
    parsed = RD.parse(digest(pasted))
    check_eq("F1: the pasted door parses with NO error, as a halt with ONE row `stand` / `blocked`",
             (parsed["errors"], parsed["header"].get("verdict"), [(r["id"], r["state"], r["reason"]) for r in parsed["rows"]]),
             ([], "halt", [("stand", "blocked", reason)]))
    check_eq("F1: and `check` (the exit gate's judge) finds nothing to refuse", RD.check(digest(pasted)), [])
    check_eq("F1 limit AT 80: a reason of exactly 80 characters is in the form", RD.check(digest(f"stand · blocked · {'x' * 80}")), [])
    check_eq("F1 limit BEYOND: 81 characters is refused (the message says `at most 80`)",
             bool(RD.check(digest(f"stand · blocked · {'x' * 81}"))), True)
    check_in("F1: the message says the header ends with `halt`", "halt", message)
    check_in("F1: the message names the form's `blocked` section and handoff_help.py (common-rules.md: a field you cannot fill)",
             "handoff_help.py", message)
    check_in("F1: the message says who reads it next: the conductor", "conductor", message)
    # the negative control: the OLD door, a free line, is refused by the same parser (so the test can fail)
    old = RD.parse(digest("stand: the image of the container carries no revision label"))
    check_in("F1 NEGATIVE CONTROL: the old free `stand: ...` line is refused by role_digest.parse",
             "this line is not in the form", " ".join(old["errors"]))
    after_path = RD.parse(f"qa-automator S5 e2e-ui · halt\nartifacts/QA-1/work/handoffs/S5-qa-automator-1.yaml\nstand: {reason}")
    check_eq("F1 NEGATIVE CONTROL: after the path the old line lands in `notes`, which nothing reads, and no row carries it",
             ([r for r in after_path["rows"] if r["id"].startswith("stand")], bool(after_path["notes"])), ([], True))
    check_not_in("F1: the message no longer prescribes the free line", "name `stand:", message)
    entry = next((e for e in RR.REGISTRY if e["id"] == "PT-stand-record-write"), {})
    check_in("F1: the registry row's `override` carries the SAME row shape, word for word", row_shape, entry.get("override", ""))
    check_not_in("F1: and no longer the free line", "`stand: <what is wrong>`", entry.get("override", ""))


def a_here_string_never_ends_a_segment() -> None:
    """B-404 E17: a bash here-string is written inline, so cutting its body out must not create a
    command position - the pin for every check that reads `exec` and treats a newline as a boundary."""
    for command in ('cat <<< "a" pytest', "cat <<< a pytest", 'grep x <<< "a" pytest -q'):
        exec_text = parts(command)["exec"]
        check_not_in(f"a here-string leaves one segment: {command!r}", "\n", exec_text)
        check_in(f"and the body is still text: {command!r}", "here-string", " ".join(parts(command)["where"]))
    # the heredoc join mirrors a real newline and stays one
    check_in("a heredoc body still leaves a newline between the lines around it", "\n",
             parts("cat > n.md <<'EOF'\nbody\nEOF\nls")["exec"])
    check_in("a real separator after a here-string is still a boundary", "\n", parts('cat <<< "a"; pytest')["exec"])
    # the PowerShell here-string (`@'` ... `'@`) is inline too: what follows the closer on its line is an argument
    for command in ("Write-Output @'\nhello\n'@ pytest", "Write-Output @'\nhello\n'@ dotnet test"):
        check_not_in(f"a PowerShell here-string leaves one segment: {command!r}", "\n", parts(command)["exec"])
        check_in(f"and the body is still text: {command!r}", "PowerShell here-string", " ".join(parts(command)["where"]))
    check_in("a command on the NEXT line after a PowerShell here-string is still its own segment", "\n",
             parts("Write-Output @'\nhello\n'@\npytest -q")["exec"])
    # a real write that the newline join used to hide: the value is the here-string, the path is an argument
    root = temp_project("qa-guard-ps-herestring-")
    harness.use_project(root)
    try:
        command = "Set-Content -Value @'\n{}\n'@ -Path qa-factory/config.json"
        role = {"tool_name": "PowerShell", "agent_type": "qa-factory:qa-automator", "tool_input": {"command": command}}
        check("Set-Content -Value @'..'@ -Path qa-factory/config.json is a profile write, refused to a role",
              G._blocked(G.config_write_check, role, {}) is not None)
        check_eq("and the main session still passes it",
                 G._blocked(G.config_write_check, dict(role, agent_type=""), {}), None)
    finally:
        cleanup(root)


if __name__ == "__main__":
    the_helper_separates_what_runs_from_what_is_carried()
    the_refusal_says_where_it_matched()
    every_spelling_of_the_real_call_is_still_refused()
    role_refused_load_revoke()
    role_refused_decide()
    role_allowed_show()
    the_words_a_command_only_carries_are_not_a_call()
    the_orchestrator_is_never_refused()
    the_neighbouring_checks_read_the_same_way()
    the_stand_door_is_a_digest_the_form_accepts()
    role_refused_stand_identity()
    the_host_binding_gives_a_driver_launched_role_its_signature()
    role_may_not_write_the_stand_records()
    a_here_string_never_ends_a_segment()
    finish("test_guard_command_text")
