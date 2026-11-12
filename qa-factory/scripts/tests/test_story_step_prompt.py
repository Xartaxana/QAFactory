#!/usr/bin/env python3
"""The launch prompt names only commands the receiving role may run (CX1-6, TP2-2406 S4-6/S4-7).

On Codex Desktop (14.10) `story_step._prompt` told EVERY role with a handover form to run
`handoff_check.py` and `handoff_help.py`. The case designer carries `tools: Read, Grep, Glob, Write,
Edit` - no Bash - so the role guard (`host_adapter.role_policy`) refused the call twice in each of two
children, and both halted with the form untouched. The guard was right; the prompt named a door the
role could not use (FR-2, FR-56). What is proved here, each check naming the ONE mutation that kills
it (builder-rules 7a; the mutation is the branch condition of `_prompt` set to True):

  K1  for EVERY role in agents/*.md: every command the rendered prompt names (parsed from the prompt's
      own lines) is allowed by the real guard (`guard_pre_tool.py`, a Codex PreToolUse `exec_command`
      event for that role) - a Bash role must still be sent to its checker (the control that the
      replay finds commands at all), a role without Bash is sent to none
  K2  the three roles without Bash get no mention of handoff_check.py / handoff_help.py, and do get the
      Edit / `blocked` / `finish validates` text
  K3  a role with Bash gets today's prompt byte for byte (pinned from the pre-change text of `main`)
  K4  a role file that is absent, unreadable, without a `tools:` line, with an EMPTY one (the next line's text is
      never read as its tools), with the line only in its body, or with Bash behind a BOM is judged by
      `host_adapter.role_has_bash`: no Bash, except the BOM file that lists it (M3)
  K5  `story_step` still imports without importing the guard (the import is lazy, inside `_prompt`)
  K6  the door the no-Bash prompt names is open and the one it warns about is shut: Edit is in
      the role's tools line, an `apply_patch` on the role's own existing form passes the real guard as a
      Codex event, a Write over it is refused (the prompt's parenthetical is true)
  K7  a no-Bash prompt names NO script at all - no `name.py` token in any spelling, judge off
      and on - and the extractor itself reads a backticked `name.py args` and a bare `name.py args`
"""
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
import role_replay as RR  # noqa: E402  (the extractor and the guard replay, shared with the brief and guidance tests)
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project  # noqa: E402
from role_replay import NO_BASH, PY_TOKEN, ROLES, WITH_BASH, agent_tools, file_event  # noqa: E402
from role_replay import guard_verdict, named_commands  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import host_adapter  # noqa: E402
import hooklib  # noqa: E402
import story_step  # noqa: E402

TASK = "TP2-2406"
BOM = chr(0xFEFF)   # a byte-order mark in front of the frontmatter (M3); built, never typed into the source (FR-29)


def form_of(role: str) -> str:
    return f"qa-factory/artifacts/{TASK}/work/handoffs/S4-{role}-1.yaml"


def render(role: str, judge_on: bool = False) -> str:
    with patch.object(story_step.judge, "active", return_value=judge_on):
        return story_step._prompt(TASK, {"inputs": []}, role, f"S4-{role}-1", [], "", form_of(role))


def replay_checks(root: Path) -> None:
    jobs = []
    for role in ROLES:
        for judge_on in (False, True):
            for command in named_commands(render(role, judge_on)):
                jobs.append((role, judge_on, command))
    verdicts = RR.replay_all([(r, c) for r, _j, c in jobs], root)
    refused = [(r, c) for (r, _j, c), (code, _e) in zip(jobs, verdicts) if code != 0]
    check_eq("K1 every command the prompt names is allowed by the real guard for that role "
             f"({len(jobs)} replays over {len(ROLES)} roles)", refused, [])
    for role in ROLES:
        names = [c for r, j, c in jobs if r == role and not j]
        if role in WITH_BASH:
            check(f"K1 control: {role} (Bash) is still sent to its checker and to the help script",
                  any("handoff_check.py" in c for c in names) and any("handoff_help.py" in c for c in names),
                  str(names))
        else:
            check_eq(f"K1 {role} (no Bash) is sent to no command at all", names, [])
    # Negative control: the replay can refuse. The old text for the designer is exactly what S4-7 ran.
    old = f'python "{harness.SCRIPTS.as_posix()}/handoff_check.py" --file {form_of("qa-case-designer")} --task {TASK} --fix'
    code, err = guard_verdict("qa-case-designer", old, root, 9001)
    check_eq("K1 negative control: the pre-change command is refused for the case designer", code, 2)
    check_in("K1 negative control: by the role guard, with its own words", "FACTORY ROLE: qa-case-designer", err)
    code, _err = guard_verdict("qa-case-designer", f"Get-Content {form_of('qa-case-designer')}", root, 9002)
    check_eq("K1 positive control: a plain read by the same role passes the same replay", code, 0)


def door_checks(root: Path) -> None:
    """K6: the door the no-Bash prompt names (Edit) is open, the one it warns about (Write) is shut."""
    for n, role in enumerate(NO_BASH):
        form = root / form_of(role)
        form.parent.mkdir(parents=True, exist_ok=True)
        form.write_text("task: x\nstatus: draft\n", encoding="utf-8")
        check(f"K6 {role}: Edit is in its tools line (the claim the prompt rests on)", "Edit" in agent_tools(role),
              str(agent_tools(role)))
        body = f"*** Begin Patch\n*** Update File: {form}\n@@\n-status: draft\n+status: filled\n*** End Patch"
        code, err = guard_verdict(role, "", root, 9100 + n,
                                  file_event(role, "apply_patch", {"command": body}, root, 9100 + n))
        check_eq(f"K6 {role}: an apply_patch on its own existing form is allowed ({err[-200:]!r})", code, 0)
        code, err = guard_verdict(role, "", root, 9200 + n, file_event(
            role, "Write", {"file_path": str(form), "content": "task: x\n"}, root, 9200 + n))
        check_eq(f"K6 {role}: a Write over its own existing form is refused", code, 2)
        check_in(f"K6 {role}: ... by the rewrite guard, with its own words", "not rewritten", err)
        add = f"*** Begin Patch\n*** Add File: {form}\n+task: x\n*** End Patch"
        code, err = guard_verdict(role, "", root, 9300 + n,
                                  file_event(role, "apply_patch", {"command": add}, root, 9300 + n))
        check_eq(f"K6 {role}: a Codex Add File over its own existing form (a Write on Codex) is refused", code, 2)


def script_name_checks() -> None:
    """K7: a no-Bash prompt names no script in any spelling; the extractor finds every spelling."""
    for role in NO_BASH:
        for judge_on in (False, True):
            check_eq(f"K7 {role} (judge {'on' if judge_on else 'off'}): no `name.py` token in the prompt",
                     PY_TOKEN.findall(render(role, judge_on)), [])
    root = harness.PLUGIN_ROOT.as_posix()
    check_eq("K7 extractor: a backticked `name.py args` span is a command",
             named_commands('say `judge_code.py --cause --finding "<t>"` now'),
             [f'python "{root}/scripts/judge_code.py" --cause --finding "x"'])
    check_eq("K7 extractor: a bare `name.py args` is a command",
             named_commands("then judge_code.py --cause now"), [f'python "{root}/scripts/judge_code.py" --cause now'])
    check_eq("K7 extractor: a line with no script is none", named_commands("Return your digest line only."), [])
    commands = named_commands(render("qa-code-critic", True))
    check("K7 control: the Bash role qa-code-critic (judge on) has a live bare script name the extractor replays",
          any("judge_code.py" in c and "--cause" in c for c in commands), str(commands))


def no_bash_checks() -> None:
    check("K2 the roles without Bash include the three the incident named",
          {"qa-case-designer", "qa-case-critic", "qa-test-strategist"} <= set(NO_BASH), str(NO_BASH))
    for role in NO_BASH:
        prompt = render(role)
        check_not_in(f"K2 {role}: no handoff_check.py", "handoff_check.py", prompt)
        check_not_in(f"K2 {role}: no handoff_help.py", "handoff_help.py", prompt)
        check_not_in(f"K2 {role}: no python command", "python", prompt)
        for needle in ("fill it with Edit", "`blocked`", "story_step finish` validates the form",
                       "you never ask the person"):
            check_in(f"K2 {role}: says {needle!r}", needle, prompt)
        check_in(f"K2 {role}: still names its form", form_of(role), prompt)
        check_not_in(f"K2 {role}: says nothing of a host (the prompt is built before the host is known)", "Codex", prompt)


def bash_pin_checks() -> None:
    """The text of `main` before this node, written out here and not computed from the code under test."""
    for role in WITH_BASH:
        form = form_of(role)
        expected = "\n".join([
            f"You are {role}. Ticket: {TASK}. Dispatch: S4-{role}-1.",
            f"Artifacts dir: qa-factory/artifacts/{TASK}/", "Inputs:",
            f"Your handover is the form {form}. Fill it as you work; what code could already answer is filled in.",
            f"  when it is filled: python \"{story_step.HERE.as_posix()}/handoff_check.py\" --file {form} --task {TASK} --fix",
            "  it refuses with the field, the problem and the values YOUR role may write; "
            "nothing it says is about the quality of your work",
            f"  what you cannot fill: put it under `blocked` and run handoff_help.py --file {form} "
            "- the conductor answers, you never ask the person",
            "Return your digest line only."])
        check_eq(f"K3 {role}: the prompt is today's text byte for byte", render(role), expected)


def doubt_checks() -> None:
    """A role file that is absent, unreadable, has no tools line (or an empty one, or the line only in its body) is
    a role with no Bash; the text and the guard read it through ONE helper."""
    plugin = temp_dir("cx16-plugin-")
    try:
        agents = plugin / "agents"
        agents.mkdir()
        files = {
            "qa-with-bash": "---\nname: x\ntools: Read, Edit, Bash\n---\n",
            "qa-no-bash": "---\nname: x\ntools: Read, Edit\n---\n",
            "qa-no-line": "---\nname: x\nmodel: sonnet\n---\nbody mentions Bash\n",
            # the main bug: an empty `tools:` line was read through the blank to the NEXT line (`model: sonnet`)
            "qa-empty-line": "---\ntools:\nmodel: sonnet\n---\n",
            "qa-empty-then-bash": "---\ntools:\nname: Bash\n---\n",
            # the second main bug: `tools:` read from the BODY of the file
            "qa-body-line": "---\nname: x\nmodel: sonnet\n---\ntools: Read, Edit, Bash\n",
            "qa-no-front": "tools: Read, Edit, Bash\nno frontmatter at all\n",
            "qa-two-lines": "---\ntools: Read, Edit, Bash\ntools: Read, Edit\n---\n",
            "qa-two-lines-rev": "---\ntools: Read, Edit\ntools: Read, Edit, Bash\n---\n",
            "qa-lower": "---\ntools: Read, bash\n---\n",
            "qa-call-form": "---\ntools: Read, Bash(git:*)\n---\n",
            "qa-bracket": "---\ntools: [Read, Bash]\n---\n",
            "qa-nospace": "---\ntools: Read,Bash\n---\n",
            "qa-padded": "---\ntools:  Read ,  Bash \n---\n",
            "qa-bashoutput": "---\ntools: Read, BashOutput\n---\n",
            "qa-crlf": "---\r\ntools: Read, Bash\r\n---\r\n",
            # M3: a BOM before the frontmatter made `parse_frontmatter` answer None, so a role WITH Bash was refused
            "qa-bom-bash": BOM + "---\nname: x\ntools: Read, Edit, Bash\n---\n",
            "qa-bom-no-line": BOM + "---\nname: x\nmodel: sonnet\n---\n",
        }
        for name, text in files.items():
            (agents / f"{name}.md").write_bytes(text.encode("utf-8"))
        (agents / "qa-a-directory.md").mkdir()
        cases = [("qa-with-bash", True, "control: a Bash role in this temp plugin is found"),
                 ("qa-factory:qa-with-bash", True, "control: the plugin namespace is stripped"),
                 ("qa-no-bash", False, "a tools line without Bash"),
                 ("qa-no-line", False, "a role file without a tools line"),
                 ("qa-empty-line", False, "a tools line with nothing on it, `model:` on the next line"),
                 ("qa-empty-then-bash", False, "a tools line with nothing on it, `name: Bash` on the next line"),
                 ("qa-body-line", False, "`tools: ... Bash` only in the BODY of the file (frontmatter only)"),
                 ("qa-no-front", False, "no frontmatter at all, `tools:` in the first line"),
                 ("qa-two-lines", False, "two tools lines: the LAST one wins (parse_frontmatter's rule), Bash first"),
                 ("qa-two-lines-rev", True, "two tools lines: the LAST one wins, Bash last"),
                 ("qa-lower", False, "`bash` is not `Bash` (the host's tool names are case-sensitive)"),
                 ("qa-call-form", False, "`Bash(git:*)` is not `Bash`"),
                 ("qa-bracket", False, "an inline list `[Read, Bash]` is not parsed: the doubt is no Bash"),
                 ("qa-nospace", True, "`Read,Bash` without a space"),
                 ("qa-padded", True, "` Bash ` padded"),
                 ("qa-bashoutput", False, "`BashOutput` is not `Bash`"),
                 ("qa-crlf", True, "CRLF line ends"),
                 ("qa-bom-bash", True, "M3: a BOM before the frontmatter, Bash listed: the role HAS Bash"),
                 ("qa-bom-no-line", False, "M3: a BOM before the frontmatter, no tools line: no Bash"),
                 ("qa-a-directory", False, "a role file that cannot be read"),
                 ("qa-absent", False, "a role with no file"),
                 ("", False, "no role at all")]
        with patch.object(hooklib, "PLUGIN_ROOT", plugin):
            for role, expected, label in cases:
                check_eq(f"K4 {label}", host_adapter.role_has_bash(role), expected)
            check_eq("K4 an empty tools line grants NOTHING (not the next line's text)",
                     host_adapter.role_tools("qa-empty-line"), frozenset())
            check_eq("K4 a role file with no tools line grants nothing", host_adapter.role_tools("qa-no-line"), frozenset())
            check_eq("K4 a role with no file has no tools at all (None, not an empty set)",
                     host_adapter.role_tools("qa-absent"), None)
            prompt = render("qa-no-line")
            bom_prompt = render("qa-bom-bash")
            empty_prompt = render("qa-empty-line")
        check_in("K4 a role without a tools line gets the no-Bash text", "fill it with Edit", prompt)
        check_not_in("K4 ... and is sent to no checker", "handoff_check.py", prompt)
        check_in("K4 an empty tools line gets the no-Bash text", "fill it with Edit", empty_prompt)
        check_in("K4 a BOM role that lists Bash is sent to its checker (M3)", "handoff_check.py", bom_prompt)
    finally:
        cleanup(plugin)


def import_checks() -> None:
    probe = ("import sys; sys.path.insert(0, sys.argv[1]); import story_step; "
             "print('guard_pre_tool' in sys.modules)")
    done = subprocess.run([sys.executable, "-B", "-c", probe, str(harness.SCRIPTS)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120)
    check_eq("K5 importing story_step does not import the guard (the import is lazy, in _prompt)",
             done.stdout.strip(), "False")
    check("K5 control: the reader answers",
          host_adapter.role_has_bash("qa-scout") is True and host_adapter.role_has_bash("qa-case-designer") is False)


def main() -> None:
    no_bash_checks()
    bash_pin_checks()
    doubt_checks()
    import_checks()
    script_name_checks()
    root = temp_project("cx16-prompt-")
    try:
        door_checks(root)
        replay_checks(root)
    finally:
        cleanup(root)
    finish("test_story_step_prompt")


if __name__ == "__main__":
    main()
