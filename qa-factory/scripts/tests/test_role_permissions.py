"""role_permissions.py — A23 role/Bash parity: synthetic fixtures plus a live-repo regression.

TP1-15045 / session b156530d-72fb-4ea4-b462-42cb9cc24a2f: a role's charter told it
to run a script, its `tools:` frontmatter did not list Bash, and the subagent's own attempt at
the `Bash` tool came back `Error: No such tool available: Bash.` — a charter/tools mismatch,
not a host permission prompt (the sibling `qa-scout` subagent, whose `tools:` DOES include
Bash, ran 65 Bash calls in the same run with zero errors). These tests fix the good/bad shape
of that heuristic and then run it over the real shipped `agents/*.md`.

Runnable on its own: `python -B scripts/tests/test_role_permissions.py`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import role_permissions as R  # noqa: E402


def make_role(root: Path, name: str, tools: str, body: str) -> None:
    (root / "agents").mkdir(parents=True, exist_ok=True)
    (root / "agents" / name).write_text(
        f"---\nname: {name}\ntools: {tools}\ndisallowedTools: Agent, Task\n---\n\n{body}\n",
        encoding="utf-8",
    )


def test_inline_command_without_bash_is_a_violation() -> None:
    root = temp_dir("qa-factory-rolepe-")
    try:
        make_role(root, "qa-fake-a.md", "Read, Grep, Glob, Write, Edit",
                  "Create `out.json` from `artifact_producer.py prepare --kind readiness`.")
        found = R.findings(root)
        check("GOOD A23: inline run command with no Bash is caught",
              any("artifact_producer.py" in e for e in found), str(found))
    finally:
        cleanup(root)


def test_fenced_command_without_bash_is_a_violation() -> None:
    root = temp_dir("qa-factory-rolepe-")
    try:
        make_role(root, "qa-fake-b.md", "Read, Grep, Glob, Write, Edit",
                  "Run this local command for each file:\n\n"
                  "```\npython scripts/case_versions.py --store <s> --task-root <t> --case-file <f>\n```")
        found = R.findings(root)
        check("GOOD A23: fenced python command with no Bash is caught",
              any("case_versions.py" in e for e in found), str(found))
    finally:
        cleanup(root)


def test_bash_declared_is_never_flagged() -> None:
    root = temp_dir("qa-factory-rolepe-")
    try:
        make_role(root, "qa-fake-c.md", "Read, Grep, Glob, Write, Edit, Bash",
                  "Run `context_bundle.py` to create `work/context-bundle.json`.")
        check("GOOD A23: a role that already holds Bash is never flagged", R.findings(root) == [])
    finally:
        cleanup(root)


def test_orchestrator_attributed_run_is_not_a_violation() -> None:
    root = temp_dir("qa-factory-rolepe-")
    try:
        make_role(root, "qa-fake-d.md", "Read, Grep, Glob, Write",
                  "Every automate row cites its reason — checked by `validate_artifacts.py`. "
                  "The orchestrator validates this JSON with `planning_contract.py --kind plan` "
                  "before accepting S3.")
        check("GOOD A23: a run attributed to the orchestrator/a checker is not the role's own",
              R.findings(root) == [])
    finally:
        cleanup(root)


def test_human_run_recommendation_is_not_a_violation() -> None:
    root = temp_dir("qa-factory-rolepe-")
    try:
        make_role(root, "qa-fake-e.md", "Read, Grep, Glob, Write",
                  'Name a run command per `python "${CLAUDE_PLUGIN_ROOT}/scripts/run_suite.py" '
                  "--label <area> -- <target>`. This section is a recommendation for the human "
                  "to run, never something you execute here.")
        check("GOOD A23: a documented recommendation for a human is not the role's own run",
              R.findings(root) == [])
    finally:
        cleanup(root)


def test_bare_script_mention_without_args_is_not_a_violation() -> None:
    root = temp_dir("qa-factory-rolepe-")
    try:
        make_role(root, "qa-fake-f.md", "Read, Grep, Glob, Write, Edit",
                  "you never call the tracker yourself — `external_writes.py` performs the "
                  "write later, idempotently, after gate B has already been recorded.")
        check("GOOD A23: a bare script name with no run verb is not flagged",
              R.findings(root) == [])
    finally:
        cleanup(root)


def test_live_plugin_has_no_role_bash_mismatch() -> None:
    found = R.findings(PLUGIN_ROOT)
    check("GOOD A23: the shipped plugin has no role/Bash mismatch", not found, str(found))


def make_phase(root: Path, name: str, body: str) -> None:
    phases = root / "skills" / "qa-story" / "phases"
    phases.mkdir(parents=True, exist_ok=True)
    (phases / name).write_text(body, encoding="utf-8")


def test_phase_prompt_telling_a_bashless_role_to_run_is_caught() -> None:
    root = temp_dir("qa-factory-rolepe-phase-")
    try:
        make_role(root, "qa-fake-g.md", "Read, Grep, Glob, Write", "Reviews cases.")
        make_phase(root, "s4.md",
                   'Dispatch `qa-fake-g`:\n\n```\nAgent(\n  subagent_type: "qa-fake-g",\n'
                   '  prompt: "You are qa-fake-g. Ticket: <TICKET>.\n'
                   '    Run `critic_rollcall.py --task-root <T> --apply-fixes` yourself.\n'
                   '    Return your digest line only."\n)\n```\n')
        found = R.phase_findings(root)
        check("BAD A23 phase scan: a dispatch prompt telling a Bash-less role to run a "
              "script is caught", any("critic_rollcall.py" in e and "qa-fake-g" in e for e in found),
              str(found))
    finally:
        cleanup(root)


def test_phase_prose_mentioning_a_role_by_name_is_not_a_violation() -> None:
    """Orchestrator prose that merely names a role ("the designer has no Bash") is not a
    dispatch prompt — only `prompt: "You are <role>. ..."` blocks are addressed TO the role."""
    root = temp_dir("qa-factory-rolepe-phase-")
    try:
        make_role(root, "qa-fake-h.md", "Read, Grep, Glob, Write, Edit", "Designs cases.")
        make_phase(root, "s4.md",
                   "The designer hands over case files and has no Bash; "
                   "`case_versions.py --store <s> --task-root <t> --all` is the orchestrator's "
                   "own step, run after the designer returns.\n")
        check("GOOD A23 phase scan: prose naming a role outside its own prompt block is not "
              "flagged", R.phase_findings(root) == [], str(R.phase_findings(root)))
    finally:
        cleanup(root)


def test_phase_prompt_for_a_bash_role_is_not_a_violation() -> None:
    root = temp_dir("qa-factory-rolepe-phase-")
    try:
        make_role(root, "qa-fake-i.md", "Read, Grep, Glob, Write, Bash", "Runs suites.")
        make_phase(root, "s6.md",
                   'prompt: "You are qa-fake-i. Ticket: <TICKET>.\n'
                   '    Run `run_suite.py --task <T>` and return your digest line only."\n')
        check("GOOD A23 phase scan: a role whose own tools already include Bash is never "
              "flagged", R.phase_findings(root) == [], str(R.phase_findings(root)))
    finally:
        cleanup(root)


def test_live_plugin_phases_have_no_role_bash_mismatch() -> None:
    found = R.phase_findings(PLUGIN_ROOT)
    check("GOOD A23 phase scan: the shipped phases/*.md dispatch no Bash-less role to run a "
          "script", not found, str(found))


if __name__ == "__main__":
    test_inline_command_without_bash_is_a_violation()
    test_fenced_command_without_bash_is_a_violation()
    test_bash_declared_is_never_flagged()
    test_orchestrator_attributed_run_is_not_a_violation()
    test_human_run_recommendation_is_not_a_violation()
    test_bare_script_mention_without_args_is_not_a_violation()
    test_live_plugin_has_no_role_bash_mismatch()
    test_phase_prompt_telling_a_bashless_role_to_run_is_caught()
    test_phase_prose_mentioning_a_role_by_name_is_not_a_violation()
    test_phase_prompt_for_a_bash_role_is_not_a_violation()
    test_live_plugin_phases_have_no_role_bash_mismatch()
    finish("role_permissions")
