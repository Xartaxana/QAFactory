#!/usr/bin/env python3
"""The brief a role must read first names only commands that role may run (CX1-6, TP2-2406 S4-6/S4-7).

On Codex Desktop (14.10) the case designer (`tools: Read, Grep, Glob, Write, Edit`, no Bash) was refused by
the role guard (`host_adapter.role_policy`) when it ran a script a text of the factory named. The launch prompt was
closed first; the brief the prompt says to read first still handed the S4 designer and critic `manifest_view.py`
(`brief_pack.SLICE_INSTEAD`), opened every card with "Every command is `python ...`" and gave the strategist
`planning_contract.py` / `plan_row.py`. The guard was right; the brief named a door the role cannot use (FR-2, FR-56).
The question "may a text send this role to a script" is asked of ONE reader, `host_adapter.role_has_bash`, by the
prompt, the brief, the injection and the driver's note alike. What is proved here, each check naming the ONE mutation
that kills it (builder-rules 7a; the mutation is `shell = True` in `brief_pack.build`), the brief rendered through
`brief_pack.build` for every role on the test_brief_pack fixture task root:

  K1  every executable instruction a brief names (role_replay's extractor: backticked and bare `name.py`
      tokens, `python` lines, rg / Get-Content lines) is allowed by the real guard (`guard_pre_tool.py`, a
      Codex `exec_command` event for that role) for a role without Bash - judge off and on; a Bash role is
      still sent to its scripts (the control that the replay finds commands at all)
  K2  the S4 designer's and critic's briefs and the strategist's S3 brief name no `name.py` token (the ahead
      card, which is data in references/ahead-cards.json, is cut out first - see AHEAD_TOKENS) and name the
      files to read instead of `manifest_view.py`
  K3  the strategist's no-shell card says Edit and the code's own checks, not `planning_contract.py` / `plan_row.py`
  K4  `NO_SHELL`, the dead second list of no-shell roles, is gone
  K5  a role file that is absent gets the no-shell brief (the conservative text is always usable); a role file with
      no `tools:` line, an empty one, or the line only in its body gets it too
  K6  a Bash role's brief is today's text: its `## Commands` section is pinned by hash, its SLICE_INSTEAD
      lines by literal
  K7  (E13) the three no-Bash briefs fit `BRIEF_MAX_BYTES` with the card the node adds, on the plain fixture and on
      the rich one (judge off and on); the numbers are in the output, and the file list is never emptied by the card
  K8  (SC1-10 B-K1) the tester's card opens with the diff pass (every changed line of every hunk) and the scout's names
      `--summary` and the merge-request command; the other seven cards are unchanged (hash pins)
  K9  (SC1-9/10 fix round, F4) every script a Bash role's charter names through `${CLAUDE_PLUGIN_ROOT}` is on its card
"""
import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
import role_replay as RR  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import brief_pack  # noqa: E402
import hooklib  # noqa: E402
import judge  # noqa: E402
from test_brief_pack import seed, seed_story_for_s5  # noqa: E402  (the fixture task root, not copied)

TASK = "QA-9"
AHEAD_HEAD = "## The rules code will apply to your handoff"
# The ahead cards are data (references/ahead-cards.json, FR-13) and are not this task's to edit: two of them
# name a script as the party that CHECKS, in a sentence ("planning_contract.py and observation_contract.py will
# check ..."), not as a command. The brief tests cut that section out and pin what is known to be in it, so a
# card that grows a new script name is noticed. Queued with the integrator: reword the two cards.
AHEAD_TOKENS = {"qa-case-critic": ["critic_rollcall.py"],
                "qa-test-strategist": ["observation_contract.py", "planning_contract.py"]}


def stage_of() -> dict:
    """{role: stage id} from references/stages.json: the stage whose `roles` holds it."""
    stages = hooklib.load_ref_json("stages.json").get("stages") or []
    return {role: st["id"] for st in stages for role in (st.get("roles") or [])}


STAGE = stage_of()


def render(role: str, judge_on: bool = False) -> str:
    """The brief this role is handed at its stage, through brief_pack's own entry."""
    with patch.object(judge, "active", return_value=judge_on):
        return brief_pack.build(TASK, STAGE[role], role, f"{STAGE[role]}-{role}-1", write=False)["markdown"]


def section(text: str, head: str) -> str:
    """The lines under `## <head>` up to the next `## ` heading."""
    out, on = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            on = line == "## " + head
            continue
        if on:
            out.append(line)
    return "\n".join(out)


def without_ahead(text: str) -> str:
    """The brief with the ahead-card section (data, see AHEAD_TOKENS) cut out."""
    out, skip = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            skip = line == AHEAD_HEAD
        if not skip:
            out.append(line)
    return "\n".join(out)


# SC1-10 B-K1: the lines of the two cards, written here as the spec fixed them (not read back from the code under test).
SC1_10_RT_LINE = ("- diff_pass.py --diff <work/impl-diff*.txt> --files-only, then --file <path> --max-lines 100000 for EVERY file it "
                  "lists, in every impl-diff - every changed line of every hunk, numbered in the new file ("
                  "a removed line is numbered at its place in the new file, so a `diff:-<path>:<line>` reference carries that number); "
                  "never Read a diff whole")
# Fix round t-1313 (F2a): `--summary` stands in the COMMAND FORM of each of the four verbs (the form a role copies), not in a
# clause on the `get|children|diff` line: `peek` plain prints no assessment ref, and `assess --assessment-ref` needs one.
SC1_10_SCOUT_LINES = [
    ["ticket_adapter.py peek <KEY> --output <task root>/work/source-inventory.json --summary - a mentioned ticket's first look",
     "--source-id <id> --relevance relevant|not_relevant|unknown --reason <reason> --assessment-ref <path> --summary - the verdict",
     "--relation task|subject|parent|normative|referenced --summary - the full read",
     "--inspection-status read|partial|unavailable --summary - one attachment's receipt"],
    "- vcs_evidence.py --url <MR URL> --output qa-factory/artifacts/QA-9/work/sources/<source id>/mr-<iid>.json - the merge request "
    "whole into the file, a summary on stdout; a file already at that path is the driver's receipt: Grep it, never collect again; "
    "its `status` says whether it was read; `mr-<iid>-git.md` next to it is the driver's partial route; "
    "record a new one with ticket_adapter.py inspect --output <inventory> --source-id <source id> --media-url <MR URL> "
    "--inspection-status read --local-ref sources/<source id>/mr-<iid>.json; never `glab mr view` into your context"]
OLD_SLICE_LINES = [
    '- work/automation-manifest.json: do not read whole - `manifest_view.py --task QA-9 --window "<ids>" | --case <case id> | --summary`',
    '- work/test-plan.json: do not read whole - `manifest_view.py --task QA-9 --context --rows <TS ids> (the plan rows of your cases)`',
    "- work/context-bundle.json: do not read whole - `Grep -n the case's requirement ids, then Read the range`"]


def replay_checks(root: Path) -> None:
    jobs, seen = [], {}
    for role in RR.ROLES:
        for judge_on in (False, True):
            for command in RR.named_commands(without_ahead(render(role, judge_on))):
                jobs.append((role, command))
                seen.setdefault((role, judge_on), []).append(command)
    verdicts = RR.replay_all(jobs, root, 5000)
    refused = [(r, c) for (r, c), (code, _e) in zip(jobs, verdicts) if code != 0 and r in RR.NO_BASH]
    check_eq(f"K1 every command a no-shell role's brief names is allowed by the real guard "
             f"({len(jobs)} replays, judge off and on, {len(RR.ROLES)} roles)", refused, [])
    for role in RR.NO_BASH:
        check_eq(f"K1 {role} (no Bash): the brief instructs no python command",
                 [c for c in seen[(role, False)] if c.startswith("python")], [])
        check(f"K1 control: {role} (no Bash): the replay is not empty - it found the plain read the card names",
              any(c.startswith("Get-Content") for c in seen[(role, False)]), str(seen[(role, False)]))
    for role in RR.WITH_BASH:
        names = seen[(role, False)]
        check(f"K1 control: {role} (Bash) is still sent to scripts by its brief ({len(names)} commands)",
              any(c.startswith("python") for c in names), str(names[:3]))
    old = RR.named_commands(OLD_SLICE_LINES[1])
    code, err = RR.guard_verdict("qa-case-designer", old[0], root, 9001)
    check_eq("K1 negative control: the old `manifest_view.py` line is refused for the case designer", code, 2)
    check_in("K1 negative control: by the role guard, with its own words", "FACTORY ROLE: qa-case-designer", err)
    code, _err = RR.guard_verdict("qa-case-designer", "Get-Content qa-factory/artifacts/QA-9/work/context-manifest.json",
                                  root, 9002)
    check_eq("K1 positive control: a plain read by the same role passes the same replay", code, 0)


def no_shell_checks() -> None:
    check("K2 the roles without Bash include the three the incident named",
          {"qa-case-designer", "qa-case-critic", "qa-test-strategist"} <= set(RR.NO_BASH), str(RR.NO_BASH))
    for role in RR.NO_BASH:
        for judge_on in (False, True):
            text = render(role, judge_on)
            label = f"{role} (judge {'on' if judge_on else 'off'})"
            check_eq(f"K2 {label}: no `name.py` token outside the ahead card",
                     RR.PY_TOKEN.findall(without_ahead(text)), [])
            check_not_in(f"K2 {label}: no `python` command", 'python "', text)
            check_not_in(f"K2 {label}: not told that `--help` is a door", "--help", text)
        ahead = section(render(role), AHEAD_HEAD.removeprefix("## "))
        check_eq(f"K2 {role}: the ahead card names only the known tokens", sorted(set(RR.PY_TOKEN.findall(ahead))),
                 AHEAD_TOKENS.get(role, []))
    for role in ("qa-case-designer", "qa-case-critic"):
        text = render(role)
        check_in(f"K2 {role}: the plan file is named by its path to read",
                 "- qa-factory/artifacts/QA-9/work/test-plan.json: do not read whole - `Grep -n` the TS ids", text)
        check_in(f"K2 {role}: ... and the S1 observables by the file they are in",
                 "qa-factory/artifacts/QA-9/work/context-manifest.json", section(text, "Read these files"))
        check_in(f"K2 {role}: says the conductor can cut the slice", "the conductor can cut", text)
        check_in(f"K2 {role}: says what it can run, once", "Get-Content <path>", section(text, "Commands"))
    commands = section(render("qa-test-strategist"), "Commands")
    check_in("K3 the strategist's card: Edit, one row's own lines", "Edit", commands)
    check_in("K3 ... the plan is written whole once, a Write over it is refused", "a Write over it is refused", commands)
    check_in("K3 ... the code checks the plan when it is saved and at the exit gate", "exit gate", commands)
    check_not_in("K3 ... and no plan_row / planning_contract command", ".py", commands)
    # SLICE_INSTEAD, the file lines the brief builds, for a role with no shell
    task_root = hooklib.artifacts_dir(TASK)
    project = hooklib.project_root()
    names = sorted([*brief_pack.SLICE_INSTEAD, brief_pack.BUNDLE_JSON])    # SC1-10: the bundle is named by file_lines itself
    plain = dict(zip(names, brief_pack.file_lines(names, task_root, project, shell=False)))
    check_eq("K2 file_lines for a role with no shell: one line per SLICE_INSTEAD name", len(plain), len(names))
    check_eq("K2 ... none of them names a script", RR.PY_TOKEN.findall("\n".join(plain.values())), [])
    check_in("K2 ... the manifest by its path", "- qa-factory/artifacts/QA-9/work/automation-manifest.json: do not read whole",
             plain["work/automation-manifest.json"])
    check_eq("K2 ... the context bundle line is the Grep/Read one for both", plain["work/context-bundle.json"],
             brief_pack.file_lines(["work/context-bundle.json"], task_root, project, shell=True)[0])


def doubt_checks() -> None:
    """K5: a role with no agent file, or one whose frontmatter grants no Bash, is a role with no Bash."""
    plugin = harness.temp_dir("cx16-plugin-")
    try:
        (plugin / "agents").mkdir()
        front = {"qa-with-bash": "---\ntools: Read, Edit, Bash\n---\n",
                 "qa-no-line": "---\nmodel: sonnet\n---\nbody\n",
                 "qa-empty-line": "---\ntools:\nmodel: sonnet\n---\nbody\n",
                 "qa-body-line": "---\nmodel: sonnet\n---\ntools: Read, Edit, Bash\n",
                 "qa-bom-bash": chr(0xFEFF) + "---\ntools: Read, Edit, Bash\n---\nbody\n"}
        for name, text in front.items():
            (plugin / "agents" / f"{name}.md").write_text(text, encoding="utf-8")
        with patch.object(hooklib, "PLUGIN_ROOT", plugin):
            built = {name: brief_pack.build(TASK, "S5", name, f"S5-{name}-1", write=False)["markdown"]
                     for name in [*front, "qa-absent"]}
        check_in("K5 control: a Bash role of the temp plugin gets the python card", 'Every command is `python "',
                 built["qa-with-bash"])
        check_in("K5 control: a role whose file starts with a BOM and lists Bash gets the python card (M3)",
                 'Every command is `python "', built["qa-bom-bash"])
        for name in ("qa-absent", "qa-no-line", "qa-empty-line", "qa-body-line"):
            check_not_in(f"K5 {name}: no python card", 'python "', built[name])
            check_eq(f"K5 {name}: ... and no script name outside the ahead card",
                     RR.PY_TOKEN.findall(without_ahead(built[name])), [])
            check_in(f"K5 {name}: ... but is told what it can do", "no shell", section(built[name], "Commands"))
    finally:
        cleanup(plugin)


def bash_pin_checks() -> None:
    """K6: a role WITH Bash is handed today's brief."""
    # K-R3-6 (t-1508 5.3): the analyst's card names the diagnostic run of "One red, one triage"; no other Bash card does.
    check_in("K-R3-6 the failure analyst's card names `red_sandbox.py --diagnostic`", "red_sandbox.py --diagnostic",
             "\n".join(brief_pack.TOOLING["qa-failure-analyst"]))
    check_eq("K-R3-6 ... and no other role's card does",
             [r for r, lines in brief_pack.TOOLING.items() if r != "qa-failure-analyst"
              and "red_sandbox.py --diagnostic" in "\n".join(lines)], [])
    task_root = hooklib.artifacts_dir(TASK)
    project = hooklib.project_root()
    got = brief_pack.file_lines(["work/automation-manifest.json", "work/test-plan.json", "work/context-bundle.json"],
                                task_root, project)
    check_eq("K6 the SLICE_INSTEAD lines of a role with a shell are today's, byte for byte", got, OLD_SLICE_LINES)
    check_eq("K6 ... also when the shell is stated", brief_pack.file_lines(
        ["work/test-plan.json"], task_root, project, shell=True), OLD_SLICE_LINES[1:2])
    critic = render("qa-code-critic")
    check_in("K6 the code critic's S5 brief carries the manifest line as today",
             OLD_SLICE_LINES[0], section(critic, "Read these files"))
    check_in("K6 ... and the card's opening line", 'Every command is `python "', critic)
    check_in("K6 ... and the rule's `--help` door", "and `--help` is the door.", critic)


def card_literal_checks() -> None:
    """B-K1 (SC1-10): the tester's card opens with the diff pass in the form of every changed line of every hunk; the
    scout's names `--summary` for its four commands and the merge-request command into the driver's own path. Killing
    mutations: drop the `diff_pass.py` line of TOOLING["qa-requirements-tester"], `--max-lines 40` in it, or drop the
    `vcs_evidence.py` line - each turns one check red (and the hash pin of its role)."""
    tester = section(render("qa-requirements-tester"), "Commands").replace(brief_pack.SCRIPTS, "<S>").splitlines()
    scout = section(render("qa-scout"), "Commands").replace(brief_pack.SCRIPTS, "<S>")
    check_eq("B-K1 the tester's card: the diff pass is the first command line, word for word",
             next((x for x in tester if x.startswith("- ")), None), SC1_10_RT_LINE)
    check_in("B-K1 ... every line of every hunk: the flag of the number is --max-lines 100000, not the default 40",
             "--max-lines 100000", SC1_10_RT_LINE)
    check_not_in("B-K1 ... and the card does not carry the default", "--max-lines 40", "\n".join(tester))
    for form in SC1_10_SCOUT_LINES[0]:
        check_in("B-K1 (F2a) the scout's card: --summary is in the command form of peek, assess, collect and inspect", form, scout)
    check_not_in("B-K1 (F2a) ... and no clause about it stands on the get|children|diff line", "take --summary", scout)
    # spec t-1765 X1 (B-D, "moved"): the number a removed line carries is said by the card's diff_pass line, not by the charter
    check_in("B-K1 (F10 b) the tester's card says which number a removed line carries",
             "a removed line is numbered at its place in the new file, so a `diff:-<path>:<line>` reference carries that number",
             "\n".join(tester))
    check_not_in("B-K1 (F10 b) control: a wrong number rule is not on the card",
                 "a removed line is numbered at its place in the OLD file", "\n".join(tester))
    check_in("B-K1 the scout's card: the merge request goes to the driver's own file and the receipt is recorded",
             SC1_10_SCOUT_LINES[1], scout)
    for role in RR.WITH_BASH:
        if role not in ("qa-scout", "qa-requirements-tester"):
            check_not_in(f"B-K1 {role}: the other cards carry neither new line", "vcs_evidence.py",
                         section(render(role), "Commands"))
    check_not_in("B-K1 the tester's card does not carry the scout's merge-request line", "vcs_evidence.py", "\n".join(tester))


PLUGIN_ROOT_SCRIPT = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/scripts/([A-Za-z0-9_]+\.py)")
# `` `x.py --flag` (`python`, from `${CLAUDE_PLUGIN_ROOT}/scripts/`) `` - the script is named first, the directory after it
PLUGIN_ROOT_AFTER = re.compile(r"`([A-Za-z0-9_]+\.py)[^`]*`\s*\([^)]*\$\{CLAUDE_PLUGIN_ROOT\}/scripts/")


def charter_scripts(text: str) -> list:
    """The scripts a charter names through the plugin root, in either of the two spellings it uses; sorted, once each."""
    return sorted(set(PLUGIN_ROOT_SCRIPT.findall(text)) | set(PLUGIN_ROOT_AFTER.findall(text)))


def missing_from_card(text: str, card: list) -> list:
    """The scripts `text` names that no line of `card` carries."""
    flat = "\n".join(card)
    return [name for name in charter_scripts(text) if name not in flat]


def charter_card_checks() -> None:
    """K9 (SC1-9/10 fix round, F4; the class of B-014 / FR-15): `${CLAUDE_PLUGIN_ROOT}` is text nobody expands, and the
    rule that told a role what to do with an empty one is gone (the common rules are trimmed per role). So every script a
    role with Bash is told to run through the plugin root must be on its card, with the absolute path the card carries.
    Killing mutation: delete the `bug_snapshot.py` line of TOOLING["qa-failure-analyst"] (or `report_facts.py` of the
    scribe's) - the role's check below names the script."""
    for role in RR.WITH_BASH:
        text = (harness.PLUGIN_ROOT / "agents" / f"{role}.md").read_text(encoding="utf-8")
        # t-1550 F2: the runner's MANUAL block is handed the manual-only list on top (TOOLING_MANUAL); its charter covers both halves
        card = list(brief_pack.TOOLING.get(role, [])) + list(brief_pack.TOOLING_MANUAL.get(role, []))
        check_eq(f"K9 {role}: every script its charter names through the plugin root is on its card", missing_from_card(
            text, card), [])
    check_eq("K9 t-1550 F2: the automated qa-runner card (TOOLING) names no manual command",
             [x for x in brief_pack.TOOLING["qa-runner"] if "manual_capture.py" in x or "manual_evidence.py build" in x], [])
    check_eq("K9 the failure analyst's and the scribe's scripts are found in their charters (the finding of t-1308)", [
        charter_scripts((harness.PLUGIN_ROOT / "agents" / "qa-failure-analyst.md").read_text(encoding="utf-8")),
        "report_facts.py" in charter_scripts((harness.PLUGIN_ROOT / "agents" / "qa-doc-scribe.md").read_text(encoding="utf-8"))],
        [["bug_records.py", "bug_snapshot.py"], True])


def byte_checks(rich: bool) -> None:
    """K7 (E13): the card the node adds does not push a no-Bash brief over the cap, and never empties the file list."""
    fixture = "rich" if rich else "plain"
    for role in RR.NO_BASH:
        for judge_on in (False, True):
            with patch.object(judge, "active", return_value=judge_on):
                out = brief_pack.build(TASK, STAGE[role], role, f"{STAGE[role]}-{role}-1", write=False)
            size, text = out["budget_bytes"], out["markdown"]      # N4: the budget, the digest template is outside it
            print(f"MEASURED {fixture} {role} judge={'on' if judge_on else 'off'} bytes={size} cap={brief_pack.BRIEF_MAX_BYTES}")
            check(f"K7 {fixture} {role} (judge {'on' if judge_on else 'off'}): {size} bytes <= {brief_pack.BRIEF_MAX_BYTES}",
                  size <= brief_pack.BRIEF_MAX_BYTES)
            check(f"K7 {fixture} {role}: the file list is not emptied by the card",
                  bool(section(text, "Read these files").strip()), section(text, "Read these files")[:80])


def s4_stand_checks(root: Path) -> None:
    """GW1-16, K16.11: the S4 brief of the case designer and the case critic lists the names a case may declare (integrations by
    name and who needs them, never a key; the stand's account roles). Killed by: M16.7 (the limit 15 -> 16) and M16.8 (a `keys` in the
    line) in the checks below; the role and stage gates by the control lines."""
    import json
    lines = brief_pack.s4_stand_lines

    def row(name: str, **fields) -> dict:
        return dict({"name": name, "keys": [f"{name.upper().replace('-', '_')}_KEY"], "required_by": ["api"]}, **fields)

    def cfg(rows, roles=None, stands=1) -> dict:
        return {"environment": {"integrations": rows},
                "environments": [{"name": f"S{n}", "credentials_by_role": dict(roles or {})} for n in range(stands)]}
    designer = "qa-case-designer"
    few = lines(cfg([row("jira"), row("aws", required_by=[])]), designer, "S0")
    check_eq("K16.11: the header, one line with who needs it, one with only the name", few[1:],
             ["- jira: api", "- aws"])
    check_in("K16.11: the header says how to declare", '{"integration": "<name>"}', few[0])
    for count, shown, more in ((15, 15, []), (16, 15, ["- and 1 more in qa-factory/config.json, environment.integrations"])):
        got = lines(cfg([row(f"svc-{n}") for n in range(count)]), designer, "S0")
        check_eq(f"K16.11: {count} integrations: {shown} lines" + (" and the count of the rest" if more else ""),
                 (len(got) - 1 - len(more), got[len(got) - len(more):]), (shown, more))
    for size, same in ((80, True), (81, False)):
        got = lines(cfg([row("jira", required_by=["x" * size])]), designer, "S0")[1]
        check_eq(f"K16.11: required_by of {size} characters {'as it is' if same else 'is clipped to at most 80'}",
                 len(got.split(": ", 1)[1]) == 80 if same else len(got.split(": ", 1)[1]) <= 80, True)
        check_eq(f"K16.11: and {'whole' if same else 'with the clip mark'}", "..." in got, not same)
    secret = row("jira", read_at=["tests/x.py:1"], credential_alternatives=[["SENTINEL_ALT"]], owner="SENTINEL_OWNER",
                 keys=["SENTINEL_KEY"])
    text = "\n".join(lines(cfg([secret]), designer, "S0"))
    for word in ("SENTINEL_KEY", "SENTINEL_ALT", "SENTINEL_OWNER", "tests/x.py"):
        check_not_in(f"K16.11: {word} is not in the brief", word, text)
    left_out = [row("off", applicability="not_required"), row("nokeys", keys=[]), row("other", environments=["elsewhere"]),
                row("twin"), row("twin", required_by=["web"])]
    got = lines(cfg(left_out), designer, "S0")
    check_eq("K16.11: not needed here, no keys, another stand: not listed; a twin name once", got[1:], ["- twin: api"])
    check_eq("K16.11: no integrations and no config: no lines", (lines(cfg([]), designer, "S0"), lines({}, designer, "S0")), ([], []))
    check_eq("K16.11: another role: none", lines(cfg([row("jira")]), "qa-automator", "S0"), [])
    roles = {"default_user": "a", "admin": "b"}
    got = lines(cfg([row("jira")], roles), "qa-case-critic", "S0")
    check_eq("K16.11 (G-8): the roles of the selected stand", got[-1], 'Stand accounts (for check {"stand_account": ...}): default_user, admin')
    check_eq("K16.11 (G-8): no stand selected (two stands, none named): no roles line",
             [l for l in lines(cfg([row("jira")], roles, stands=2), designer, "") if l.startswith("Stand accounts")], [])
    check_eq("K16.11 (G-8): no roles: no line", [l for l in lines(cfg([row("jira")]), designer, "S0") if l.startswith("Stand accounts")], [])
    # through the entry: S4 designer and critic get the block, the strategist (S3) does not
    path = Path(root) / "qa-factory" / "config.json"
    held = path.read_bytes() if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg([row("jira-integration")], {"default_user": "a"}, stands=1)), encoding="utf-8")
    try:
        for role in ("qa-case-designer", "qa-case-critic", "qa-test-strategist"):
            text = render(role)
            check_eq(f"K16.11: the {role} brief {'carries' if role != 'qa-test-strategist' else 'does not carry'} the block",
                     "Stand integrations (declare one" in text, role != "qa-test-strategist")
    finally:
        if held is None:
            path.unlink()
        else:
            path.write_bytes(held)


def stage_critic_checks() -> None:
    """X2-1 (t-1765): the brief of the role that ACCEPTS a stage (`acceptance_by`) names the artifact under acceptance, the stage's advice
    file (present or not) and the author's handoff form; the brief of any other role is byte for byte what it was without the call.
    The one mutation that kills it: `stage_critic_names` returning [] for the acceptor (killed by the first three checks)."""
    def brief(stage: str, role: str) -> str:
        with patch.object(judge, "active", return_value=False):
            return brief_pack.build(TASK, stage, role, f"{stage}-{role}-1", write=False)["markdown"]
    s2 = brief("S2", "qa-case-critic")
    check_in("X2-1: the S2 critic's brief names the register under acceptance", "work/requirements-register.md", s2)
    check_in("X2-1: ...and the advice file of the stage, although it does not exist yet", "work/advice-S2.json", s2)
    check_in("TR4-1: the S2 critic's brief says no author dispatch is there to review yet", "Reviewed dispatch: none yet", s2)
    check_in("X2-1: ...and says it is absent, in the words file_lines prints for any absent file", "advice-S2.json", s2.split("advice-S2.json", 1)[1][:200] and s2)
    check_not_in("X2-1: the S4 critic's brief names the S4 advice file, not S2's", "advice-S2.json", brief("S4", "qa-case-critic"))
    stage_def = stage_of_def("S2")
    check_eq("X2-1: a role that is not the acceptor gets no extra names", brief_pack.stage_critic_names(stage_def, "qa-requirements-tester", Path(".")), [])
    check_eq("X2-1: a stage with no acceptance_by gives none either", brief_pack.stage_critic_names(dict(stage_def, acceptance_by=None), "qa-case-critic", Path(".")), [])
    designer = brief("S4", "qa-case-designer")
    with patch.object(brief_pack, "stage_critic_names", return_value=[]):
        check_eq("X2-1: the designer's S4 brief is byte for byte what it is without the call", designer, brief("S4", "qa-case-designer"))
    names = brief_pack.stage_critic_names(stage_def, "qa-case-critic", Path("."))
    check_eq("X2-1: the acceptor's names are the outputs, then the advice file", (names[:3], names[-1]),
             (stage_def["outputs"][:3], "work/advice-S2.json"))


def tried_reader_checks(root: Path) -> None:
    """t-1884 M-2 (AR-22): a `tried` table is read by somebody. S6 and S7 by the stage's acceptor (`stage_critic_names`), the two S8 forms
    by the retro analyst's brief (`TRIED_READERS`), the scribe's also by the gate B packet (test_bug_records). The S9 form is read by the
    next story's retro brief (`prior_retro_lines`, test_retro_prior_tried) and packed by qa-collect (B16); the S5 form by the code critic's brief (test_brief_pack_s5_plan)."""
    def brief(stage: str, role: str) -> str:
        with patch.object(judge, "active", return_value=False):
            return brief_pack.build(TASK, stage, role, f"{stage}-{role}-9", write=False)["markdown"]
    task = root / "qa-factory/artifacts" / TASK
    (task / "state").mkdir(exist_ok=True)
    (task / "state" / "controller.json").write_text(json.dumps({"dispatches": {
        "S6-qa-runner-1": {"id": "S6-qa-runner-1", "stage": "S6", "role": "qa-runner", "status": "accepted"},
        "S7-qa-failure-analyst-1": {"id": "S7-qa-failure-analyst-1", "stage": "S7", "role": "qa-failure-analyst", "status": "accepted"},
        "S8-qa-doc-scribe-1": {"id": "S8-qa-doc-scribe-1", "stage": "S8", "role": "qa-doc-scribe", "status": "accepted"},
        "S8-qa-bug-reporter-1": {"id": "S8-qa-bug-reporter-1", "stage": "S8", "role": "qa-bug-reporter", "status": "accepted"}}}), encoding="utf-8")
    try:
        check_in("M-2: the S6 acceptor's brief names the runner's form", "work/handoffs/S6-qa-runner-1.yaml", brief("S6", "qa-failure-analyst"))
        scribe7 = brief("S7", "qa-doc-scribe")
        check_in("M-2: the S7 acceptor's brief names the analyst's form", "work/handoffs/S7-qa-failure-analyst-1.yaml", scribe7)
        check_in("TR4-1: ...and the line says which row of inputs_read counts", "Reviewed dispatch: the LAST `inputs_read` row", scribe7)
        retro = brief("S9", "qa-retro-analyst")
        check_in("M-2: the retro brief names the scribe's last S8 form", "work/handoffs/S8-qa-doc-scribe-1.yaml", retro)
        check_in("M-2: ... and the bug reporter's", "work/handoffs/S8-qa-bug-reporter-1.yaml", retro)
        check_eq("M-2: the readers are a table, and a role outside it gets none",
                 (brief_pack.TRIED_READERS, brief_pack.tried_reader_names(stage_of_def("S8"), "qa-doc-scribe", task)),
                 ({("S9", "qa-retro-analyst"): (("S8", "qa-doc-scribe"), ("S8", "qa-bug-reporter"))}, []))
        check_eq("M-2: no accepted dispatch, no name", brief_pack.last_accepted_form(task, "S8", "qa-nobody"), "")
        check("M-2: the retro brief stays within the ceiling the K7 test holds (BRIEF_MAX_BYTES)",
              len(retro.encode("utf-8")) <= brief_pack.BRIEF_MAX_BYTES, str(len(retro.encode("utf-8"))))
    finally:
        (task / "state" / "controller.json").unlink()


def stage_of_def(stage: str) -> dict:
    return next(st for st in hooklib.load_ref_json("stages.json")["stages"] if st["id"] == stage)


def main() -> None:
    root = temp_project("cx16-project-")
    try:
        harness.use_project(root)
        seed(root, TASK)
        stage_critic_checks()
        tried_reader_checks(root)
        s4_stand_checks(root)
        no_shell_checks()
        doubt_checks()
        bash_pin_checks()
        card_literal_checks()
        charter_card_checks()
        byte_checks(rich=False)
        replay_checks(root)
    finally:
        cleanup(root)
    rich_root = temp_project("cx16-rich-")
    try:
        harness.use_project(rich_root)
        seed_story_for_s5(seed(rich_root, TASK), rich_root, "go ahead " + "x" * 11000)
        byte_checks(rich=True)
    finally:
        cleanup(rich_root)
    finish("test_brief_pack_roles")


if __name__ == "__main__":
    main()
