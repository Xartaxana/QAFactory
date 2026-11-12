#!/usr/bin/env python3
"""A role without Bash on Codex Desktop is told the tools it really has (CX1-6, TP2-2406 S3-4/S3-5).

S3-4, 16.10: the Desktop child's `exec` cell holds `tools.exec_command`, `tools.apply_patch` and
`tools.mcp__codex_app__*`; no tool named Read, Grep, Glob, Write or Edit exists there, and every text of the factory
named only those. The strategist sent an empty `apply_patch`, then asked `mcp__codex_app__open_in_codex` to read its
brief and was refused with a door (`host_tools.read_only`) a role cannot use. `host_adapter.CODEX_DESKTOP_TOOLS` is
the ONE text of how such a role reads and edits; this file proves where it is used (each check names its mutation):

  K1 the constant: size (AT and beyond the cap), ASCII, the sentences in their order, `_READ_DOOR` inside it whole,
     every example in it one plain read for the guard
  K2 the injection (`inject_context.codex_role_instructions`, and `main` for a Codex event): a role without Bash gets
     the block right under the "Factory role instructions" heading; a role with Bash, a Claude Code event and an
     unreadable role file get none (that one with an informed stderr line, FR-4); the guard (`role_policy`) and the
     injection read `tools:` through ONE helper (`host_adapter.role_tools`/`role_has_bash`) and agree on a role file
     with no tools line, an empty one, the line only in the body, a BOM, with Bash, without Bash, with no file.
     Mutations: `guide = ""` in inject_context.py -> the presence checks go red; `role_has_bash` always True -> the
     no-Bash rows of the agreement check go red
  K3 the brief: the strategist's no-shell card carries the constant verbatim
  K4 the refusals, through the real guard_pre_tool.py as the Codex events the host sends: the row-22 connector call
     by the strategist stays blocked and carries the constant; the same call by a role WITH Bash (qa-runner) and by a
     caller that is no role keeps the text of `main` byte for byte (M1: the constant says "any other shell command is
     refused", false for them); the read refusal carries the constant and says the prohibition once
  K4b the plan's markdown copy (`plan_write_check`): a role without Bash is told Edit, never `plan_row.py`; a role
     with Bash keeps the bytes of `main`; `role_ways` doubt (M2): no role / no file -> both doors; a file with no
     `tools:` line -> Codex {Edit}, Claude both (an estimate, not measured here)
  K5 the changelog fragment
  K6 `references/role-commands.json`: the `plan_row.py` entry names Edit for a role without Bash and copies no tools line
  K7 ONE reader of the line: the consumers (the driver's note, A23, A2) answer as `tools_line` does on the edge rows
     (empty line, body line, case, brackets, BashOutput, NotebookEdit), and no regex reader of `^tools:` is left in
     the package scripts

Negative control: `T028_NEGATIVE_CONTROL=1` adds ONE check for a key that is not in the text; the run must then end red.
"""
import contextlib
import io
import json
import os
import re
import sys
import types
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
import role_replay as RR  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import audit_factory as AF  # noqa: E402
import brief_pack  # noqa: E402
import guard_pre_tool  # noqa: E402
import host_adapter  # noqa: E402
import hooklib  # noqa: E402
import inject_context as IC  # noqa: E402
import role_permissions  # noqa: E402
import story_run  # noqa: E402
from test_brief_pack import seed  # noqa: E402  (the fixture task root, not copied)

CONST = host_adapter.CODEX_DESKTOP_TOOLS
CAP = 900
BOM = chr(0xFEFF)   # a byte-order mark in front of the frontmatter (M3); built, never typed into the source (FR-29)
STRATEGIST = "qa-test-strategist"
BASH_ROLE = "qa-automator"
RUNNER = "qa-runner"
TICKET = "TP2-2406"
TASK = "QA-9"
PLAN = f"qa-factory/artifacts/{TICKET}/work/test-plan.json"
PLAN_MD = f"qa-factory/artifacts/{TICKET}/work/test-plan.md"
BRIEF = f"qa-factory/artifacts/{TICKET}/work/briefs/S3-qa-test-strategist-4.md"
FRAGMENT = harness.PLUGIN_ROOT / "changelog.d" / "codex-1-cx1-06-no-shell-roles.md"
NOTE_MARKER = "A role without Bash is never sent to a command its guard refuses"  # the first words of this note in CHANGELOG.md
HEADING = "\n\n# Factory role instructions: "
GUIDE_HEAD = "# Your tools on Codex Desktop\n"
# The connector refusal of `main` for a caller the constant does not speak to (written out here, not computed).
MAIN_LEAD = ("FACTORY HOST POLICY: unclassified or mutating connector tool mcp__codex_app__open_in_codex; "
             "external writes require a proposal and the gated executor.")
MAIN_DOOR = (" The orchestrator registers verified read-only tools in host_tools.read_only, or the exact call forms of "
             "a code-taking tool in host_tools.read_only_calls.")
MAIN_MACHINE = " The machine copy is test-plan.json, and it is changed with plan_row.py, never by hand."


def within_cap(text: str) -> bool:
    """The ONE size check of the constant (E14): AT the cap passes, beyond it does not."""
    return len(text) <= CAP


# --- K1: the constant ---------------------------------------------------------------------------------------------

def the_constant() -> None:
    check(f"K1 at most {CAP} characters ({len(CONST)})", within_cap(CONST))
    check("K1 the size check passes AT the cap (a string of exactly 900)", within_cap("x" * CAP))
    check("K1 ... and fails BEYOND it (the constant padded to 901)", not within_cap(CONST + "x" * (CAP + 1 - len(CONST))))
    check("K1 plain ASCII: no Cyrillic, no typographic quote, nothing above U+007E", all(ord(c) < 127 for c in CONST))
    check("K1 no end-anchor example (a dollar sign right before a quote)", not re.search(r"\$['\"]", CONST))
    check("K1 the one wording of the read limits is inside it whole (I5: no second wording)",
          host_adapter._READ_DOOR in CONST)
    order = ["no Read, Grep, Glob, Write or Edit tool", "tools.exec_command", "rg -n '<pattern>' <path>",
             "Get-Content <path>", "even quoted", "never rg --pre", "Any other shell command is refused",
             "tools.apply_patch", "empty hunk", "Create a NEW file with tools.apply_patch and an *** Add File: <path> hunk",
             "reads it as Write", "tools.mcp__codex_app__*", "open_in_codex"]
    places = [CONST.find(part) for part in order]
    check(f"K1 every sentence is there ({places})", all(p >= 0 for p in places))
    check("K1 ... in the order the spec gives", places == sorted(places), str(places))
    check("K1 the constant prohibits shell on its own, in one sentence, and says it once",
          CONST.count("Any other shell command is refused") == 1 and "rbitrary shell" not in CONST)
    for command in re.findall(r"`([^`]+)`", CONST):
        check(f"K1 the example is one plain read for the guard: {command!r}",
              host_adapter._is_one_plain_read(re.sub(r"<[^>]+>", "x", command)))
    check("K1 a pattern may hold | ; & ( ) inside ASCII quotes, and the read rule agrees",
          host_adapter._is_one_plain_read("rg -n 'a|b;c&d(e)' x") and not host_adapter._is_one_plain_read("rg -n 'a$' x"))
    check("K1 the card replay finds no script in it", RR.named_commands(CONST) == ["rg -n 'x' x", "Get-Content x"],
          str(RR.named_commands(CONST)))


# --- K2: the injection ---------------------------------------------------------------------------------------------

def agent_file(plugin: Path, name: str, front: str) -> None:
    (plugin / "agents" / f"{name}.md").write_text(f"---\nname: {name}\n{front}---\nBODY of {name}\n", encoding="utf-8")


def injected(role: str, plugin: Path) -> str:
    blocks = ["\n\n# earlier block\n"]
    with patch.object(IC, "PLUGIN_ROOT", plugin):
        IC.codex_role_instructions(blocks, role)
    check(f"K2 {role}: the role instructions go FIRST among the blocks", blocks[-1] == "\n\n# earlier block\n", str(blocks)[:80])
    return blocks[0]


def the_injection_unit() -> None:
    plugin = temp_dir("cx16-inject-")
    try:
        (plugin / "agents").mkdir()
        agent_file(plugin, "qa-nobash", "tools: Read, Grep, Glob, Write, Edit\n")
        agent_file(plugin, "qa-notools", "model: sonnet\n")
        agent_file(plugin, "qa-emptyline", "tools:\nmodel: sonnet\n")
        agent_file(plugin, "qa-bash", "tools: Read, Edit, Bash\n")
        agent_file(plugin, "qa-bashfirst", "tools: Bash,Read\n")
        (plugin / "agents" / "qa-nofront.md").write_text("BODY with no frontmatter\n", encoding="utf-8")
        (plugin / "agents" / "qa-bodyline.md").write_text("---\nname: x\n---\ntools: Read, Edit, Bash\nBODY\n", encoding="utf-8")
        (plugin / "agents" / "qa-bom-bash.md").write_bytes((BOM + "---\nname: x\ntools: Read, Edit, Bash\n---\nBODY\n").encode("utf-8"))
        (plugin / "agents" / "qa-bom-none.md").write_bytes((BOM + "---\nname: x\nmodel: sonnet\n---\nBODY\n").encode("utf-8"))
        for role in ("qa-nobash", "qa-notools", "qa-emptyline"):
            text = injected(role, plugin)
            check_in(f"K2 {role}: the block sits right under the heading and before the body",
                     HEADING + role + "\n" + GUIDE_HEAD + CONST + "\n", text)
            check(f"K2 {role}: ... and the body follows it", 0 <= text.find(CONST) < text.find("BODY of " + role), text[:120])
            check_not_in(f"K2 {role}: the frontmatter itself is still split off", "tools:", text)
        check_in("K2 qa-nofront (no frontmatter at all, so no tools line): the block is there", GUIDE_HEAD + CONST, injected("qa-nofront", plugin))
        check_in("K2 qa-bodyline (`tools: ... Bash` only in the body): the block is there (frontmatter only)",
                 GUIDE_HEAD + CONST, injected("qa-bodyline", plugin))
        check_in("K2 a BOM file with no tools line: the block is there", GUIDE_HEAD + CONST, injected("qa-bom-none", plugin))
        for role in ("qa-bash", "qa-bashfirst"):
            text = injected(role, plugin)
            check_eq(f"K2 {role} (Bash in tools): no block, today's text", text, HEADING + role + f"\n\nBODY of {role}\n")
        text = injected("qa-bom-bash", plugin)
        check_eq("K2 a BOM file that lists Bash: no block, and the BOM does not hide the frontmatter split", text,
                 HEADING + "qa-bom-bash" + "\n\nBODY\n")
        blocks = ["\n\n# earlier block\n"]
        err = io.StringIO()
        with patch.object(IC, "PLUGIN_ROOT", plugin), contextlib.redirect_stderr(err):
            try:
                IC.codex_role_instructions(blocks, "qa-missing")
                raised = ""
            except Exception as exc:  # noqa: BLE001 - the edge is "no exception, whatever it would be"
                raised = type(exc).__name__
        check_eq("K2 a missing role file: no exception", raised, "")
        # RH1-5 B9 (t-1456, docs/tasks/handoffs/t-1456-rh1-5-b9.md l.10): an unreadable role file adds an
        # "unavailable" block to the prompt and a signal to the person - it was a stderr print.
        check_eq("K2 ... the earlier block is untouched, ONE 'unavailable' block is put first",
                 (len(blocks), blocks[-1]), (2, "\n\n# earlier block\n"))
        check("K2 ... and that block says which role file could not be read, in the prompt",
              "Factory context unavailable" in blocks[0] and "agents/qa-missing.md could not be read" in blocks[0], blocks[0])
        lines = err.getvalue().splitlines()
        check("K2 ... and ONE informed signal line, not a silent pass (FR-4)",
              len(lines) == 1 and "role qa-missing" in lines[0] and "could not be read" in lines[0], err.getvalue())
        err = io.StringIO()
        with patch.object(IC, "PLUGIN_ROOT", plugin), contextlib.redirect_stderr(err):
            IC.codex_role_instructions([], "qa-bash")
            IC.codex_role_instructions([], "qa-nobash")
        check_eq("K2 a readable role file (Bash or not) writes nothing to stderr", err.getvalue(), "")
        the_two_readers_agree(plugin)
    finally:
        cleanup(plugin)


def guard_blocks_python(role: str, plugin: Path) -> bool:
    """Whether role_policy (the guard) refuses a `python x.py` Bash call of `role` - the guard's own reading of `tools:`."""
    event = {"turn_id": "turn-1", "agent_type": role, "tool_name": "Bash", "tool_input": {"command": "python x.py"}}
    with patch.object(hooklib, "PLUGIN_ROOT", plugin), contextlib.redirect_stderr(io.StringIO()):
        try:
            host_adapter.role_policy(event, {"host_tools": {}})
        except SystemExit as stop:
            return stop.code == 2
    return False


def the_two_readers_agree(plugin: Path) -> None:
    """F-2: role_policy and codex_role_instructions read `tools:` through ONE helper (host_adapter.role_tools), so
    'the guard refuses its shell' and 'the role is told it has no shell' cannot part. Mutation: `role_has_bash` always
    True -> every no-Bash row below goes red (role_has_bash row and both the guard and the guide rows)."""
    (plugin / "agents" / "qa-dir.md").mkdir()           # not a file: not a factory role (role_policy's own test)
    none, bash3 = frozenset(), frozenset({"Read", "Edit", "Bash"})
    rows = [("qa-notools", "no tools line", none, False), ("qa-emptyline", "an EMPTY tools line", none, False),
            ("qa-bodyline", "`tools:` only in the body", none, False), ("qa-nofront", "no frontmatter", none, False),
            ("qa-bash", "Bash", bash3, True), ("qa-bashfirst", "Bash,Read", frozenset({"Bash", "Read"}), True),
            ("qa-nobash", "no Bash", frozenset({"Read", "Grep", "Glob", "Write", "Edit"}), False),
            ("qa-bom-bash", "BOM, Bash (M3)", bash3, True), ("qa-bom-none", "BOM, no line (M3)", none, False),
            ("qa-missing", "no file", None, False), ("qa-dir", "a directory", None, False)]
    for role, label, tools, bash in rows:
        check_eq(f"K2 role_tools, {label}", host_adapter.role_tools(role, plugin), tools)
        check_eq(f"K2 role_has_bash, {label}", host_adapter.role_has_bash(role, plugin), bash)
        told = bool(GUIDE_HEAD in injected_quiet(role, plugin))
        blocked = guard_blocks_python(role, plugin)
        has_file = (plugin / "agents" / (role + ".md")).is_file()
        want = has_file and not bash
        check_eq(f"K2 {label}: the guard refuses python = {want}", blocked, want)
        check_eq(f"K2 {label}: the role is told it has no shell = {want}", told, want)
        check_eq(f"K2 {label}: the two call sites agree", blocked, told)
    # E9: a file that is there but cannot be read is a role without Bash (refusal), not an exception in the hook
    (plugin / "agents" / "qa-unreadable.md").write_text("---\ntools: Read, Edit, Bash\n---\n", encoding="utf-8")
    real = Path.read_text

    def deny(self, *args, **kwargs):
        if self.name == "qa-unreadable.md":
            raise PermissionError("denied")
        return real(self, *args, **kwargs)

    with patch.object(Path, "read_text", deny):
        check_eq("K2 E9 an unreadable role file has no tools (None)", host_adapter.role_tools("qa-unreadable", plugin), None)
        check_eq("K2 E9 ... the guard refuses its python (the doubt falls toward refusal, no exception)",
                 guard_blocks_python("qa-unreadable", plugin), True)
    with patch.object(hooklib, "PLUGIN_ROOT", plugin):
        check_eq("K2 role_tools with no plugin_root argument reads hooklib.PLUGIN_ROOT",
                 host_adapter.role_tools("qa-bash"), bash3)
        check_eq("K2 ... and strips the plugin namespace", host_adapter.role_tools("qa-factory:qa-bash"), bash3)


def injected_quiet(role: str, plugin: Path) -> str:
    blocks = []
    with patch.object(IC, "PLUGIN_ROOT", plugin), contextlib.redirect_stderr(io.StringIO()):
        IC.codex_role_instructions(blocks, role)
    return "".join(blocks)


def run_main(project: Path, role: str, codex: bool) -> tuple:
    """inject_context.main() in this process for an Agent dispatch of `role`; returns (stdout, the context Codex staged)."""
    os.environ["CLAUDE_PROJECT_DIR"] = str(project)
    hooklib._PROJECT_ROOT_CACHE = None
    event = {"hook_event_name": "PreToolUse", "tool_name": "Agent",
             "tool_input": {"subagent_type": role, "prompt": f"Dispatch id: S3-{role}-1\nTask {TICKET}"}}
    if codex:
        event.update(turn_id="turn-1", session_id="s-1", tool_use_id="u-1")
    staged = []
    real = (IC.read_event, IC.run_stage_guard, sys.argv)
    IC.read_event, IC.run_stage_guard, sys.argv = (lambda: event), (lambda _event: None), ["inject_context.py"]
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with patch("native_context.stage", lambda root, ev, r, context, ticket: staged.append(context)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                IC.main()
            except SystemExit as stop:
                code = stop.code or 0
    finally:
        IC.read_event, IC.run_stage_guard, sys.argv = real
    check_eq(f"K2 main exits clean for {role} (codex {codex}; {err.getvalue()[-160:]!r})", code, 0)
    return out.getvalue(), "".join(staged)


def the_injection_through_main(root: Path) -> None:
    out, context = run_main(root, STRATEGIST, codex=True)
    heading = HEADING + STRATEGIST + "\n" + GUIDE_HEAD + CONST + "\n"
    check_in("K2 main, Codex, strategist (no Bash): the staged context carries the heading and the block", heading, context)
    body = (harness.PLUGIN_ROOT / "agents" / f"{STRATEGIST}.md").read_text(encoding="utf-8").split("---", 2)[-1]
    check_in("K2 ... and the role file body right after it", heading + body[:60], context)
    check_eq("K2 main, Codex: nothing is printed (the context is staged, not rewritten into the prompt)", out.strip(), "")
    _out, context = run_main(root, BASH_ROLE, codex=True)
    check_in("K2 main, Codex, qa-automator (Bash): the heading and the body are there", HEADING + BASH_ROLE + "\n", context)
    check_not_in("K2 ... without the block", GUIDE_HEAD, context)
    check_not_in("K2 ... and without the constant", CONST, context)
    # a Claude Code event: the same dispatch, no turn_id, so is_codex is false; its prompt carries neither
    first, _ = run_main(root, STRATEGIST, codex=False)
    second, _ = run_main(root, STRATEGIST, codex=False)
    prompt = json.loads(first)["hookSpecificOutput"]["updatedInput"]["prompt"] if first.strip() else ""
    check("K2 Claude event: the hook rewrites the prompt as before", prompt.startswith(f"Dispatch id: S3-{STRATEGIST}-1"), prompt[:80])
    check_not_in("K2 ... with no role-instructions heading", "Factory role instructions", prompt)
    check_not_in("K2 ... and no Codex guidance", GUIDE_HEAD, prompt)
    check_not_in("K2 ... and not the constant", CONST[:60], prompt)
    check_eq("K2 ... and the same event twice gives the same bytes", first, second)


# --- K3: the brief -------------------------------------------------------------------------------------------------

def the_brief(root: Path) -> None:
    harness.use_project(root)
    seed(root, TASK)
    text = brief_pack.build(TASK, "S3", STRATEGIST, "S3-qa-test-strategist-1", write=False)["markdown"]
    check_in("K3 the strategist's brief carries the constant verbatim", CONST, text)
    check_not_in("K3 ... and no longer opens 'You have no shell'", "You have no shell", text)
    check_in("K3 ... it names the Claude tools for Claude Code", "reads on Claude Code with Read, Grep and Glob and writes with Write and Edit", text)
    check_in("K3 ... it keeps the sentence about the plugin's scripts",
             "The scripts of the plugin are run for you by the orchestrator and the exit gate; the plugin's scripts are not read.", text)
    check("K3 NO_SHELL_HEAD holds the constant (substring identity) and the card holds NO_SHELL_HEAD",
          CONST in brief_pack.NO_SHELL_HEAD and brief_pack.NO_SHELL_HEAD in text)
    bash = brief_pack.build(TASK, "S5", BASH_ROLE, "S5-qa-automator-1", write=False)["markdown"]
    check_not_in("K3 ... the Bash role's brief holds no constant", CONST[:60], bash)


# --- K4: the guard -------------------------------------------------------------------------------------------------

def event_for(role: str, tool: str, tool_input, root: Path, n: int) -> dict:
    """The shape the host sends (repro of S3-4): the nested call is the event, with turn_id and the task-named agent_type."""
    event = dict(RR.codex_event(role, "", root, n), tool_name=tool, tool_input=tool_input)
    if not role:
        event.pop("agent_type")
    return event


def verdict(role: str, tool: str, tool_input, root: Path, n: int) -> tuple:
    return RR.guard_verdict(role or STRATEGIST, "", root, n, event_for(role, tool, tool_input, root, n))


def the_guard(root: Path) -> None:
    plan = root / PLAN
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text('[\n  {"id": "TS-1",\n    "verification_depth": "low"}\n]\n', encoding="utf-8")
    row22 = {"target": {"type": "file", "path": str(root / BRIEF)}, "placement": "right"}
    code, err = verdict(STRATEGIST, "mcp__codex_app__open_in_codex", row22, root, 400)
    check_eq(f"K4 row 22 (open_in_codex by the strategist) stays BLOCKED ({err[-100:]!r})", code, 2)
    check_in("K4 ... by the host policy, naming the tool", "FACTORY HOST POLICY: unclassified or mutating connector tool "
             "mcp__codex_app__open_in_codex", err)
    check_in("K4 ... the role's text is the lead, then the constant (FR-2)", MAIN_LEAD + " " + CONST, err)
    check_not_in("K4 ... and it does NOT send the role to the orchestrator's door (host_tools.read_only)", "host_tools.read_only", err)
    check_in("K4 ... and names tools.exec_command", "tools.exec_command", err)
    code, err = verdict(RUNNER, "mcp__codex_app__open_in_codex", row22, root, 408)
    check_eq(f"K4 M1 the same tool from a role WITH Bash (qa-runner) stays BLOCKED ({err[-100:]!r})", code, 2)
    check_in("K4 ... with the text of `main`, byte for byte", MAIN_LEAD + MAIN_DOOR, err)
    check_not_in("K4 ... and it never hears 'Any other shell command is refused' (it has a shell)",
                 "Any other shell command is refused", err)
    check_not_in("K4 ... nor the Desktop tool block", "tools.exec_command", err)
    code, err = verdict("", "mcp__codex_app__open_in_codex", row22, root, 401)
    check_eq(f"K4 the same tool from a caller that is no role stays BLOCKED ({err[-100:]!r})", code, 2)
    check_in("K4 ... with the old text, byte for byte (the orchestrator keeps its door)", MAIN_LEAD + MAIN_DOOR, err)
    check_not_in("K4 ... and none of the role guidance", "tools.exec_command", err)
    code, err = verdict(STRATEGIST, "exec_command", {"cmd": f"Get-Content {BRIEF}", "workdir": str(root)}, root, 402)
    check_eq(f"K4 exec_command Get-Content <brief> PASSES ({err[-100:]!r})", code, 0)
    code, err = verdict(STRATEGIST, "exec_command", {"cmd": f"rg -n 'TS-(1|2)' {PLAN}", "workdir": str(root)}, root, 403)
    check_eq(f"K4 exec_command rg -n with a quoted alternation PASSES ({err[-100:]!r})", code, 0)
    patch_text = (f"*** Begin Patch\n*** Update File: {plan}\n@@\n"
                  '-    "verification_depth": "low"}\n+    "verification_depth": "high"}\n*** End Patch')
    code, err = verdict(STRATEGIST, "apply_patch", patch_text, root, 404)
    check_eq(f"K4 apply_patch Update of the plan PASSES ({err[-100:]!r})", code, 0)
    new_file = root / "qa-factory" / "artifacts" / TICKET / "work" / "test-plan.md"
    add_text = f"*** Begin Patch\n*** Add File: {new_file}\n+# Test plan\n+words for the human\n*** End Patch"
    code, err = verdict(STRATEGIST, "apply_patch", add_text, root, 407)
    check_eq(f"K4 apply_patch *** Add File of a new work file (read as Write) PASSES ({err[-100:]!r})", code, 0)
    check_eq("K4 ... the guard reads that hunk as a Write",
             [(e["tool_name"], e["tool_input"]["patch_operation"]) for e in host_adapter.mutation_events(
                 {"tool_name": "apply_patch", "cwd": str(root), "tool_input": {"command": add_text}})], [("Write", "add")])
    code, err = verdict(STRATEGIST, "exec_command", {"cmd": "python plan_row.py --row TS-1", "workdir": str(root)}, root, 405)
    check_eq(f"K4 exec_command python is BLOCKED ({err[-100:]!r})", code, 2)
    why = host_adapter._read_refusal("python plan_row.py --row TS-1")
    check_in("K4 ... by the role policy: its lead, THEN the reason, then the constant (FR-1: what is wrong first)",
             "FACTORY ROLE: " + STRATEGIST + " may read using rg/Get-Content without shell chaining; arbitrary shell "
             "execution is not permitted: " + why + ". " + CONST, err)
    check_eq("K4 ... and the prohibition is said ONCE in the combined refusal", err.lower().count("arbitrary shell"), 1)
    check_eq("K4 ... 'Any other shell command' (the constant's) is there once too", err.count("Any other shell command"), 1)
    code, err = verdict(BASH_ROLE, "exec_command", {"cmd": "ls qa-factory | sort", "workdir": str(root)}, root, 406)
    check_eq("K4 a Bash role's pipe is untouched (PASSES)", code, 0)
    plan_md_checks(root)


def plan_md_checks(root: Path) -> None:
    """K4b: the markdown copy's refusal names the door THIS role has (E19, M2)."""
    md = root / PLAN_MD
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text("# plan\n", encoding="utf-8")
    write = {"file_path": str(md), "content": "# plan again\n"}
    code, err = verdict(STRATEGIST, "Write", write, root, 410)
    check_eq(f"K4b the strategist's Write over test-plan.md is BLOCKED ({err[-100:]!r})", code, 2)
    check_in("K4b ... the markdown copy is changed with Edit, one row's own lines at a time",
             " The machine copy is test-plan.json, and it is changed with Edit, one row's own lines at a time, never by "
             "a whole Write; code checks the plan when it is saved.", err)
    check_not_in("K4b ... and it never sends a role without Bash to plan_row.py", "plan_row.py", err)
    check_not_in("K4b ... nor to artifact_supersede.py", "artifact_supersede.py", err)
    code, err = verdict(BASH_ROLE, "Write", write, root, 411)
    check_eq(f"K4b a role WITH Bash is blocked the same way ({err[-100:]!r})", code, 2)
    check_in("K4b ... and keeps the text of `main`: plan_row.py", MAIN_MACHINE, err)
    code, err = verdict("", "Write", write, root, 412)
    check_eq(f"K4b the orchestrator (no role) is blocked too ({err[-100:]!r})", code, 2)
    check_in("K4b M2 ... and keeps both doors (plan_row.py): no role binds no tools", MAIN_MACHINE, err)


def ways_checks() -> None:
    """K4b / M2: the doubt of `role_ways` is decided by role_policy's own test (a role is a role when its file exists)."""
    plugin = temp_dir("cx16-ways-")
    try:
        (plugin / "agents").mkdir()
        (plugin / "agents" / "qa-noline.md").write_text("---\nname: x\nmodel: sonnet\n---\n", encoding="utf-8")
        (plugin / "agents" / "qa-emptyline.md").write_text("---\ntools:\nmodel: sonnet\n---\n", encoding="utf-8")
        (plugin / "agents" / "qa-bodyline.md").write_text("---\nname: x\n---\ntools: Read, Bash\n", encoding="utf-8")
        (plugin / "agents" / "qa-bom.md").write_bytes((BOM + "---\ntools: Read, Edit\n---\n").encode("utf-8"))
        (plugin / "agents" / "qa-listed.md").write_text("---\ntools: Read, Write\n---\n", encoding="utf-8")
        (plugin / "agents" / "qa-dir.md").mkdir()
        both, edit = {"Edit", "Bash"}, {"Edit"}
        rows = [("", "no role at all", both, both), ("qa-absent", "a role with no file", both, both),
                ("qa-dir", "a directory, not a file", both, both),
                ("qa-noline", "a file with no tools line (the estimate on Claude)", edit, both),
                ("qa-emptyline", "a file with an EMPTY tools line", edit, both),
                ("qa-bodyline", "a file whose only tools line is in the body", edit, both),
                ("qa-bom", "a BOM file listing Read, Edit", {"Read", "Edit"}, {"Read", "Edit"}),
                ("qa-listed", "a file listing Read, Write (no Edit)", {"Read", "Write"}, {"Read", "Write"})]
        with patch.object(guard_pre_tool, "PLUGIN_ROOT", plugin):
            for role, label, codex_ways, claude_ways in rows:
                check_eq(f"K4b M2 Codex, {label}", guard_pre_tool.role_ways({"agent_type": role, "turn_id": "t-1"}), codex_ways)
                check_eq(f"K4b M2 Claude Code, {label}", guard_pre_tool.role_ways({"agent_type": role}), claude_ways)
    finally:
        cleanup(plugin)


# --- K5: the changelog fragment -----------------------------------------------------------------------------------

def the_changelog_fragment() -> None:
    # a release folds the fragment into CHANGELOG.md (changelog_assemble.py): after it the text lives there, under the version
    try:
        text, why = harness.release_note(FRAGMENT, NOTE_MARKER), ""
    except ValueError as err:
        text, why = "", str(err)
    check("K5 the release note exists (the fragment, or its CHANGELOG.md block)", bool(text.strip()),
          why or f"neither {FRAGMENT.name} nor a CHANGELOG.md block carrying {NOTE_MARKER!r}")
    for needle in ("CODEX_DESKTOP_TOOLS", "TP2-2406", "tools.exec_command", "tools.apply_patch", "NO_SHELL_HEAD",
                   "inject_context.py", "open_in_codex"):
        check_in(f"K5 the fragment names {needle}", needle, text)
    check("K5 it holds no heading line", not re.search(r"(?m)^#{1,6}(\s|$)", text))
    check("K5 it is free of Cyrillic", not re.search("[" + chr(0x0400) + "-" + chr(0x04FF) + "]", text))


# --- K6: the registry ---------------------------------------------------------------------------------------------

def the_registry() -> None:
    data = json.loads((harness.PLUGIN_ROOT / "references" / "role-commands.json").read_text(encoding="utf-8"))
    entry = next(v["plan_row.py"] for v in _walk(data) if "plan_row.py" in v)
    text = entry["input"] + " " + entry["verify"]
    check_in("K6 the plan_row.py entry tells a role without Bash to use Edit, one row's own lines at a time",
             "a role without Bash with Edit, one row's own lines at a time", text)
    check_in("K6 ... and that code checks the plan when it is saved", "code checks the plan when it is saved", text)
    check_not_in("K6 ... and it copies no `tools:` line of a role file (that is data of agents/*.md)", "tools:", text)
    check_not_in("K6 ... and no longer says every change comes through the command", "after that comes through this command", text)
    check("K6 the text is ASCII (FR-30)", all(ord(c) < 127 for c in text))


def _walk(node):
    """Every dict in the registry that could hold the plan_row.py entry."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


# --- K7: one reader of the line -----------------------------------------------------------------------------------

def the_census() -> None:
    """The consumers answer as `tools_line` does on the edge rows. Mutations: Driver.role_has_bash answering True on
    None / A23 back to a substring / A2 back to a substring each turn one row red."""
    plugin = temp_dir("cx16-census-")
    try:
        (plugin / "agents").mkdir()
        rows = [  # (file, frontmatter-or-text, Bash granted, Write/Edit granted)
            ("qa-plain", "---\nname: x\ntools: Read, Bash, Write\n---\n", True, True),
            ("qa-empty", "---\ntools:\nmodel: sonnet\n---\n", False, False),
            ("qa-body", "---\nname: x\n---\ntools: Read, Bash, Write\n", False, False),
            ("qa-case", "---\ntools: Read, bash, write\n---\n", False, False),
            ("qa-call", "---\ntools: Read, Bash(git:*)\n---\n", False, False),
            ("qa-brackets", "---\ntools: [Read, Bash]\n---\n", False, False),
            ("qa-bashoutput", "---\ntools: Read, BashOutput\n---\n", False, False),
            ("qa-notebook", "---\ntools: Read, NotebookEdit\n---\n", False, False),
            ("qa-twice", "---\ntools: Read, Bash, Write\ntools: Read\n---\n", False, False),
            ("qa-bom", BOM + "---\ntools: Read, Bash, Write\n---\n", True, True)]
        for name, text, _bash, _write in rows:
            (plugin / "agents" / f"{name}.md").write_bytes((text + "\n## Outputs\n\n- `work/out.md`\n\nRun `thing.py --a b` now.\n").encode("utf-8"))
        driver = types.SimpleNamespace(plugin=plugin)
        a23 = role_permissions.findings(plugin)
        for name, _text, bash, _write in rows:
            check_eq(f"K7 Driver.role_has_bash, {name}", story_run.Driver.role_has_bash(driver, name), bash)
            check_eq(f"K7 A23 reports {name} = {not bash} (the charter runs thing.py, so a role without Bash is reported)",
                     any(line.startswith(f"{name}.md:") for line in a23), not bash)
        check_eq("K7 Driver.role_has_bash: a role with no file has no Bash (the one default)",
                 story_run.Driver.role_has_bash(driver, "qa-absent"), False)
        out = io.StringIO()
        with patch.object(AF, "PLUGIN_ROOT", plugin), patch.object(AF, "FINDINGS", []), contextlib.redirect_stdout(out):
            AF.a2_role_tools_parity()
        reported = out.getvalue()
        for name, _text, _bash, write in rows:
            check_eq(f"K7 A2 reports {name} = {not write} (its Outputs name a file; Write/Edit is a MEMBER of the set)",
                     f"{name}.md:" in reported, not write)
        check_in("K7 A2 keeps the line's own text in its message", "tools (Read, NotebookEdit)", reported)
    finally:
        cleanup(plugin)


def no_second_reader() -> None:
    """I3: no regex reader of the `tools:` line is left in the package scripts (the parse is hooklib.parse_frontmatter).
    Positive control: the same pattern finds a sample that is there."""
    pattern = re.compile(r"\(\?m\)\^tools|\^tools:")
    sample = '    line = re.search(r"(?m)^tools:\\s*(.+)$", text)'
    check("K7 control: the scan pattern finds the old reader's shape", bool(pattern.search(sample)))
    hits = []
    for path in sorted(harness.SCRIPTS.glob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.name}:{number}")
    check_eq("K7 no `^tools:` regex reader in scripts/*.py", hits, [])


def main() -> None:
    the_constant()
    the_injection_unit()
    ways_checks()
    root = temp_project("cx16-guidance-")
    try:
        (root / "qa-factory" / "artifacts" / TICKET / "work").mkdir(parents=True, exist_ok=True)
        the_injection_through_main(root)
        the_guard(root)
    finally:
        cleanup(root)
    brief_root = temp_project("cx16-guidance-brief-")
    try:
        the_brief(brief_root)
    finally:
        cleanup(brief_root)
    the_changelog_fragment()
    the_registry()
    the_census()
    no_second_reader()
    if os.environ.get("T028_NEGATIVE_CONTROL"):
        check_in("NEGATIVE CONTROL (must be red): a key that is not in the text", "tools.read_file", CONST)
    finish("test_codex_tool_guidance")


if __name__ == "__main__":
    main()
