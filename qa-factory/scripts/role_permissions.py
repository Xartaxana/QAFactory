"""role_permissions.py — A23 role/Bash parity.

Incident (TP1-15045, session b156530d-72fb-4ea4-b462-42cb9cc24a2f): the
`qa-requirements-tester` subagent called the `Bash` tool by name to run `artifact_producer.py`
and got back `Error: No such tool available: Bash.` — not a permission prompt, not a guard
block. Its `agents/qa-requirements-tester.md` frontmatter simply never listed Bash among its
`tools:`, while its own Procedure section tells it to run that script. The same transcript's
`qa-case-designer` subagent hit the identical error on `case_versions.py`, and the sibling
`qa-scout` subagent — whose `tools:` DOES include Bash — ran 65 Bash calls in the same run with
zero errors. That rules out a session-wide or host-level block: it is a per-role charter/tools
mismatch, caught here so it fails an audit instead of a live story.

This mirrors `audit_factory.a2_role_tools_parity` (write verbs require Write/Edit) but for the
run-a-script verb requiring Bash. Kept as a standalone script rather than a new function in
audit_factory.py: that file is owned by the plugin's shared audit surface, not by this package
; qa-doctor step 3 runs both.

Heuristic: a backtick or fenced `python ...`/`<name>.py <args>` command inside a role's body is
a RUN signal. It is excluded when the surrounding text attributes the run to someone else (the
orchestrator, a hook, a human-run recommendation, or "checked by" a script that runs elsewhere) —
see EXCLUDE_RE. This is prose matching, not parsing; a role whose real behaviour disagrees with
its own wording will not be caught here, the same limitation A2 already has for write verbs.

Run standalone: `python -B role_permissions.py` (prints `A23 role/Bash parity: ...`, exit 1 on
a finding). `findings(plugin_root)` is importable (e.g. by a test, or a future doctor script).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hooklib import PLUGIN_ROOT, parse_frontmatter  # noqa: E402
from hooklib import sorted_paths  # noqa: E402
from host_adapter import tools_line  # noqa: E402  (the ONE splitter of a role file's `tools:` line)

# A command inside backticks: `<name>.py <at least one more token>` — a script name alone
# (`external_writes.py` with nothing after it) is a reference, not an instruction to run it.
INLINE_RUN_RE = re.compile(r"`([\w\-]+\.py)\s+[^`\n]+`")
# A fenced block whose first content line starts with "python " — a literal shell command.
FENCE_RE = re.compile(r"```[^\n]*\n(\s*python\s[^\n]*)\n(?:[^\n]*\n)*?```")
# The run is attributed elsewhere: the orchestrator does it, a hook fires automatically, the
# text is a recommendation for a human to run by hand, or another script "checks" the result
# without the role itself invoking anything.
EXCLUDE_RE = re.compile(
    r"(?i)(orchestrator|checked by|hook runs on|performs the write later|"
    r"recommendation for the human to run|you execute here)"
)
WINDOW_BEFORE, WINDOW_AFTER = 200, 250


def _script_name(match: "re.Match") -> str:
    if match.re is INLINE_RUN_RE:
        return match.group(1)
    m = re.search(r"([\w\-]+\.py)", match.group(1))
    return m.group(1) if m else match.group(1).strip()


def findings(plugin_root: Path) -> list:
    errors = []
    agents_dir = plugin_root / "agents"
    for role_file in sorted_paths(agents_dir.glob("*.md")) if agents_dir.exists() else []:
        text = role_file.read_text(encoding="utf-8-sig", errors="replace")
        tools = (parse_frontmatter(text) or {}).get("tools", "")   # the line's own text, for the message
        if "Bash" in tools_line(text):                              # membership of the set, not a substring
            continue
        body = text.split("---", 2)[-1]
        seen = set()
        for pattern in (INLINE_RUN_RE, FENCE_RE):
            for m in pattern.finditer(body):
                name = _script_name(m)
                if name in seen:
                    continue
                window = body[max(0, m.start() - WINDOW_BEFORE): m.end() + WINDOW_AFTER]
                if EXCLUDE_RE.search(window):
                    continue
                seen.add(name)
                line = body.count("\n", 0, m.start()) + 1
                errors.append(
                    f"{role_file.name}:{line}: the charter tells the role to run `{name}`, "
                    f"tools ({tools or '(none)'}) lack Bash"
                )
    return errors


# The literal dispatch template a phase file hands to a role, e.g. `prompt: "You are
# qa-scout. ...`. This is the exact text a role receives — unlike surrounding prose, which is
# read and acted on by the orchestrator itself, even where it names a role in passing (TP1-15045:
# `phases/s4.md` says "the designer hands over case files and has no Bash" while the
# orchestrator runs `case_versions.py`, which is not a violation).
PROMPT_ROLE_RE = re.compile(r'prompt:\s*"You are ([\w-]+)\.')


def _prompt_blocks(text: str) -> list:
    """[(role, block_text, block_start_offset), ...] for every dispatch prompt template."""
    blocks = []
    for m in PROMPT_ROLE_RE.finditer(text):
        end = text.find('"\n)', m.end())
        if end == -1:
            end = min(len(text), m.end() + 2000)
        blocks.append((m.group(1), text[m.start():end], m.start()))
    return blocks


def phase_findings(plugin_root: Path) -> list:
    """'run <script>' demands inside a phase file's dispatch-prompt templates, addressed to a
    role whose `tools:` lack Bash (role_permissions.py
    only READS `skills/qa-story/phases/*.md`, it does not own them — a finding here is for the
    integrator's report, not a fix made in this file).
    """
    phases_dir = plugin_root / "skills" / "qa-story" / "phases"
    agents_dir = plugin_root / "agents"
    role_tools = {}      # role -> (the line's own text for the message, the set it grants)
    for role_file in sorted_paths(agents_dir.glob("*.md")) if agents_dir.exists() else []:
        text = role_file.read_text(encoding="utf-8-sig", errors="replace")
        role_tools[role_file.stem] = ((parse_frontmatter(text) or {}).get("tools", ""), tools_line(text))
    findings = []
    for phase_file in sorted_paths(phases_dir.glob("*.md")) if phases_dir.exists() else []:
        text = phase_file.read_text(encoding="utf-8", errors="replace")
        for role, block, start in _prompt_blocks(text):
            if role not in role_tools:        # not a factory role: nothing to compare with
                continue
            tools, granted = role_tools[role]
            if "Bash" in granted:
                continue
            for pattern in (INLINE_RUN_RE, FENCE_RE):
                for m in pattern.finditer(block):
                    name = _script_name(m)
                    line = text.count("\n", 0, start + m.start()) + 1
                    findings.append(
                        f"{phase_file.name}:{line}: the dispatch prompt for {role} tells it "
                        f"to run `{name}`, its tools ({tools or '(none)'}) lack Bash"
                    )
    return findings


def report(check: str, errors: list) -> None:
    if errors:
        print(f"{check}: VIOLATIONS ({len(errors)})  owner: factory — nothing wanted from you")
        for e in errors:
            print(f"  - {e}")
    else:
        print(f"{check}: no violations")


def main() -> None:
    errs = findings(PLUGIN_ROOT)
    report("A23 role/Bash parity", errs)
    # phases/*.md is only read here, never edited: report what is
    # found there, but a finding in a file this script does not own never fails this check.
    phase_errs = phase_findings(PLUGIN_ROOT)
    if phase_errs:
        print(f"A23 phase dispatch-prompt scan: {len(phase_errs)} finding(s) for the "
              "integrator (phases/*.md is not owned here)")
        for e in phase_errs:
            print(f"  - {e}")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
