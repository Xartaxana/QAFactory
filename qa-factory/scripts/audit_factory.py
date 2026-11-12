"""Factory audit — the executable half of calibration. Run: python audit_factory.py (via run-py.cmd).

Checks (format: mechanism -> what counts as a violation -> how it is checked):
  A1 hook liveness       — every scripts/*.py is LIVE: named by hooks/hooks.json, imported
                           (transitively) by a script that is, or a declared CLI tool
                           (CLI_SCRIPTS). Anything else is dead code shipped as if it ran;
                           a dead HOOK_SCRIPTS entry is named as a dead hook. Library modules
                           of a hook (guard_app_under_test, guard_secrets inside
                           guard_pre_tool) are live by import — one process per event is the
                           design, not three hooks.json entries
  A2 role/tools parity   — write verbs in a role prompt require Write/Edit in tools (class F-1);
                           extension — reverse capability-separation checks (the qafactory
                           dev-factory principle: "holding no tool is the version of the rule
                           nobody can drift from"): Write/Edit with not one single write signal
                           in the contract — excess right (class F-2); missing disallowedTools
                           with Agent/Task — role-controller, the isolation boundary is not
                           closed by frontmatter (roles do not spawn subagents — the qa-story law)
  A3 case/bug schemas    — validate_artifacts rules run over ALL existing cases and bugs
  A4 state machine       — Automated without red_probe/automated_by; red_lock without a bug file
  A5 seal                — task artifact files younger than the last accepted/subagent_stop for the task
                           or the task's last gate event with a decision (gate-approved edits are
                           legitimate — the decision seals them)
  A6 journal             — every journal.jsonl line has a valid format; rejected carries failure_class
  A7 journal completeness — a task with artifacts but no journal events = journal silence
  A9 injection map       — every references/inject-map.json file exists; every qa role is in the map
  A11 artifact schema sync — every key validate_artifacts.PHASE_JSON_KEYS requires is
                           documented in references/artifact-contract*.md for that artifact
                           (the CONTRACT is the source of truth, not a role's prose); the
                           artifact's writer in PHASE_JSON_WRITERS must exist in agents/
  A12 skill size          — SKILL.md <= 19k chars (post-compaction re-inject cuts ~20k) +
                           every phases/*.md a skill references exists
  A13 deferred decisions — every `[DEFERRED:` marker in qa-factory/strategy/*.md and
                          qa-factory/config.json must have a pair — an open DD-N row
                          in the "## Deferred decisions" section of
                          qa-factory/factory-backlog.md (the registry of findings about
                          the factory itself, not of task obligations — the same principle
                          "knowledge does not live in the chat", but at the factory-setup
                          level, surfacing at calibration); a marker pairs by CELL: the first 40
                          characters of its essence (lower-cased, whitespace runs collapsed) must
                          occur in the `essence + where the marker is` cell of an OPEN row, read
                          through project_decisions.parse_rows — prose elsewhere in the backlog
                          and closed rows pair nothing, and a bare `[DEFERRED:]` is reported as a
                          marker with no essence. A13 also fails a DD row
                          whose `asked` column is empty: a deferral records "we asked and
                          the answer did not come", so a row with no question on record is
                          a SKIPPED question filed as a deferral — the onboarding defect
                          this column exists to expose. The mirror case too: a required
                          interview topic (repos, environment, ticket adapter) left empty
                          in config.json with NO deferral row is a topic nobody was ever
                          asked — the failure that leaves no trace at all
  A14 definition drift  — the plugin's own shipped files, judged by the ONE recipe:
                          release_fingerprint.compare() answers package_modified (yes / no /
                          unknown) from the release file written at release. `no` is the only
                          "no violations"; `yes` and `unknown` are INFO lines (the files named,
                          at most 10 each; the why of an unknown) — never a violation: in the
                          plugin model the installed plugin version IS the pinned definition,
                          a fresh install and a person's own edit must stay green, and an
                          unknown is never a pass. A14 reads no stamp and writes nothing
  A15 estimation loop   — each completed S9 has exactly one active append-only estimate row
                          bound to current retro bytes and task source revision
  A16 registry hygiene   — duplicate ids in obligations.md/factory-backlog.md are always a
                          violation; an oversized essence is a violation for rows created
                          after a date-cutoff
  A17 detector re-run    — FB-27: a quoted detector output is not an acceptance; the audit
                          re-runs check_coverage.py itself and judges by the real exit code
  A18 result projection — completed S6/S8 has current reducer sources or a typed S6 no-execution receipt; completed S8 has test-report.md
  A20 portable paths     — nothing the factory WRITES may carry a machine-local path. Every
                          declared path field in config.json (app_root, tests_root,
                          journal_path, code_repos[].path, protected_app_paths[], env_file)
                          must be relative to the project root; a home-rooted path
                          (/Users/<name>/..., a drive-rooted Windows path) in a command template or
                          in a generated strategy document is a violation too. These files
                          are committed and read on someone else's machine: an absolute path
                          resolves nowhere for the next clone, and it publishes a username
                          besides
  A22 role start load    — ONE number per role: everything it reads before its first useful
                          action (charter, the project's CLAUDE.md, the injection, the packet,
                          the launch card, the brief with its side files, the handoff form),
                          added up by scripts/role_load.py and judged in TOKENS against
                          references/role-load.json. The threshold is the owner's number and
                          prints info while provisional; a per-role shrink-only ratchet is red
                          from the first day. The bytes every role gets alike
                          (contract_slices.common_layer) keep their own two ratchets, and an
                          unmeasured layer is an error, not a zero. Per-file caps are the wrong
                          place to measure (they put the pressure on the lightest layer while
                          the heaviest grew unmetered), so the remedy it names is never "write
                          less" but "move the fact to the layer that owns it"
  A21 one owner per fact — strategy/test-strategy.md and strategy/framework-rules.md go to
                          disjoint roles and must not restate each other: a section heading
                          present in both (normalized — case, punctuation and a trailing
                          parenthetical ignored) is a fact with two owners and therefore two
                          answers as soon as one copy is edited
  A19 agents contract    — every agents/*.md (B1/B2): frontmatter `name` equals the file
                          name; `description` ends with "Dispatched by qa-story at S<n>." for
                          the S<n> references/stages.json assigns that role (never a Python
                          list of role names — the stage table is read at check time); `tools`
                          present; `disallowedTools` contains both Agent and Task; no `model`
                          key; the six sections Role/Inputs/Procedure/Outputs/Witness/Refusals
                          all present. The 9,000-byte per-file size is a NOTE since P7.1, not a
                          violation: the charter is the lightest layer of a dispatch and A22 is
                          the check that counts all of them. Run alone: `--agents`.
An empty check result is printed EXPLICITLY ("no violations") — silence is indistinguishable from not running.

Root split note: this audit runs against ONE project's state (project_root()/state_dir()) for
the project-scoped checks (A3-A7, A9, A11 role lookups still resolve against PLUGIN_ROOT,
A12, A13, A15, A16, A17, A18), and against the plugin's own shipped files (PLUGIN_ROOT) for
A1 and A14 — a project no longer carries its own copy of hooks/roles/skills, so there is
no "session-root vs factory-root" duplication to check (the donor's A8/A10 dropped: A8 was
model-routing drift, out of scope per the no-model-routing rule; A10 was about a per-session
settings.json copy, which the plugin architecture no longer has — hooks are registered once,
globally, by the plugin manifest).
"""
import argparse
import ast
import hashlib
import io
import json
import re
import sys
import tokenize
import warnings
from datetime import datetime
from pathlib import Path
from typing import NamedTuple
from content_size import content_bytes

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hooklib import artifact_root, PLUGIN_ROOT, project_root, state_dir, ref, parse_frontmatter, load_config
import runtime_paths as RP  # noqa: E402
import charter  # noqa: E402  A19: the one reader of a charter's form
import validate_artifacts as va
from hooklib import sorted_paths
from host_adapter import tools_line  # the ONE splitter of a role file's `tools:` line

# The plugin's event handlers. Some are ENTRY POINTS (hooks.json names them on the command
# line), some are LIBRARY MODULES an entry point imports — one process per event is the design,
# so guard_pre_tool.py imports guard_app_under_test.py and guard_secrets.py rather than the
# harness spawning three processes. A1 therefore counts a script live when it is referenced by
# hooks.json OR imported (transitively) by something that is.
HOOK_SCRIPTS = [
    "guard_pre_tool.py", "guard_app_under_test.py", "guard_secrets.py", "validate_artifacts.py",
    "subagent_journal.py", "exit_gate.py", "inject_context.py",
    "cost_capture.py", "precompact_guard.py", "postcompact_reload.py",
]
# CLI tools: run by a human, a skill, the orchestrator or another script — never by the hook
# runner. Their absence from hooks.json is their normal state, not a dead hook. A script that
# is in neither this set, nor hooks.json, nor the import closure of a hook, is genuinely dead.
CLI_SCRIPTS = {
    # The System One judge and the one-command stage boundary (references/judge.md).
    "judge", "judge_sources", "judge_requirements", "judge_plan", "judge_cases", "story_step",
    # The driver experiment's brief for every dispatch and the repository map it links.
    "brief_pack", "repo_map",
    # The stand's identity by code: named by phases/s5.md and called through
    #  in the project's config, not by a hook.
    "runtime_probe",
    "environment_record",   # what a person accepted once as a property of the environment (B-414): run by the driver and the conductor
    "report_adapt",   # the helper's record of a test report the code could not read (B-416, D-0031): run by the driver and the conductor
    "stand_identity",   # the registry of ways to read a stand's build and the person's word for a story (t-300): run by the driver and the conductor
    "onboarding_probe",   # the report probe of each profile's test command (B-220): run by onboard_apply after the profiles are written, and by the onboarding skill (p4) to ask again
    "onboarding_notes",   # the onboarding run's own notes (B-411): run by the onboarding skill's phases; precompact_guard / postcompact_reload import its locator
    "plan_row",   # one field of one plan row, named in the strategist's card (brief_pack.TOOLING)
    "config_view",   # one key of qa-factory/config.json, not the whole file (SC1-8): named by the stage cards and the conductor's skill; story_step imports card_values, no hook runs it
    "grounding_section",   # one part of the S3 grounding table by its id, with its line numbers (SC1-3): run by the driver, the conductor and a role with a shell; reads only, no hook does
    "grounding_table",   # the S3 grounding table by code (G1-4): --skeleton / --refresh / --check; run by the driver's window preparation, imported by the S3 gate
    "blast_radius",      # the blast-radius index of the implementation diff (G1-2): built by code before the S3 window; the driver's preparation and the S3 brief call it, no hook does
    "base_slice",        # the base-code slice «before» (G1-8): prepared by code between the S3 windows from the recorded implementation base; the driver calls it, no hook does
    "claim_projector",   # the S3 planner's claim copied into the register by code (G1-13): the driver calls it after each S3 window; the S3 gate imports s3_claim_errors; no hook does
    "user_path_failures",  # places of the code that swallow a failure (G2-14): the S2 brief calls it, a role with a shell may run it; no hook does
    "artifact_supersede",  # the door of the rewrite guard (FR-57): set aside an unusable artifact of your own
    "reference_snapshot",   # the old version's snapshot of an S-c story (t-2181 PC-9a): `put` is named in the runner's commands by PC-9b, `show` is run by a person and the conductor; no hook does
    "story_run",  # the driver (design/driver.md): the loop that replaces the orchestrator model
    "interim_packet",  # the interim report of a story held for code (t-2181 PC-7): written by the driver on entering the wait; data only, no hook runs it
    "judge_form", "judge_run", "judge_code", "judge_results", "judge_reply", "judge_discovery", "judge_diff",
    # What every judged question actually did, over one project or several (references/judge.md).
    "judge_calibration",
    # The handoff contracts (handoffs/README.md): the library, the form, the check that repairs
    # by code what code can derive, and the way out when a role cannot fill a field.
    "handoff", "handoff_init", "handoff_check", "handoff_help",
    "arch_check", "audit_factory", "check_coverage", "check_delivery", "check_traceability",
    "check_witness", "contract", "diff_pass", "diff_scope", "env_probe", "external_writes", "factory_dashboard",
    "stage_done", "manifest_view", "manifest_put", "manifest_from_tests", "waiver",
    "factory_manifest", "form_selftest", "grammar", "hooklib", "install_smoke", "ledger",
    "log_append", "make_fixture_repo", "readiness", "run_suite", "selftest", "stage_guard",
    "ticket_adapter",
    "http_client",   # the one outbound HTTP helper (B-408): a library, imported by the readers of the tracker and the stand
    "machine_facts",  # the collect archive's redactor and the census's spelling generator: a library with a small main() (CL1-1)
    "collect_pack",  # the qa-collect skill's packer: `collect_pack.py --root . --problems-file <f> ...` (CL1-4); collect_stall.py is live through its import
    "changelog_assemble",  # the release helper that folds changelog.d/ fragments into a version section (F0-5)
    "acceptance", "benchmark_compare", "case_versions", "onboard_apply", "context_bundle",
    "controller", "delivery_manifest", "execution_request", "finalize_task",
    "managed_dependency", "migrate_artifacts", "migrate_coverage", "planning_contract", "profile_contract",
    "reconcile_mutations", "red_sandbox", "render_case_appendix", "runtime_policy",
    "source_preflight", "tms_publication", "artifact_packet", "environment_selection", "telemetry_hook",
    "artifact_producer", "runtime_paths", "delivery_summary",
    "gate_brief", "retro_numbers", "story_budget", "window_budget", "role_permissions",
    "stand_lease", "stand_health", "node_ids",
    "device_stand",   # the stand of a device surface (EP1-41b): a ready device, an answering driver server, with --deep one session; `device_stand.py --project-root . --json [--deep]`, run by a person, the onboarding and the conductor; no hook runs it
    "project_env",   # which environment the project's tests run in (C3-18): `project_env.py <root> [--profile <config.json>] [--json]`, run by a person and the conductor; the launch sites import it
    "case_stamp", "project_gitignore", "install_paths", "story_version",
    "critic_rollcall", "gate_preflight", "refusal_registry", "s5_precheck", "s5_plan", "sizing",
    "stage_status", "tracker_write", "dispatch_liveness",
    "story_progress",   # where a story stands in one line (t-310): `python story_progress.py --task-root <T>`
    "execution_fingerprint", "window_record",
    "estimate_record", "recover_codex_usage", "codex_roles",
    "reachability",
    "probe_by_code",
    "test_locations",  # the project's test locations (D-0030): the one reader and its --suggest / --check CLI, run by onboarding, the conductor and the waiver's door
    "reporters",  # library, no CLI: the one report-row reader run_suite, red_sandbox and probe_by_code share
    "run_py_entry",  # the launcher's entry: hooks/run-py.cmd starts it, no hook names it (M7)
    "gate_registry",  # A26 (FR-59): the gates that judge validity, and the verdict comparisons held to them; run by selftest, never by the doctor
    "proof_level",  # the one reader of references/verification-levels.json (D-0010, D-0012)
    "role_load",  # the one measure of a role's start load (RC1-14): `role_load.py --role <r> | --all [--story <t>]`; audit A22 and retro_numbers import it
    # The factory-fixes wave after cmp1 (30.09-01.10): the launch check, the open-questions register
    # and its threshold stop, the one bug reader, the S0 base of the test repository, the true price,
    # the novelty measurer, the probe debt, the person's list of sources not to read, the report's facts.
    "launch_check", "question_register", "question_stop", "bug_records", "test_repo_base", "task_price",
    "test_novelty", "probe_debt", "source_exclusions", "report_facts",
    # The manual-agent evidence (t-250): the capture the agent runs, and the check of what it left.
    "manual_capture", "manual_evidence",
    "first_look",   # the first-look record, its attempt and the share/due questions (t-2277 FL-2): `first_look.py begin|end|put|show`, run by the driver and the walking role
    "walk_session",   # the kept-session server of a manual walk (t-1957): `walk_session.py open|item|step|look|final|verdict|done|close|status`, run by the driver and the walking role
    "walk_timing",   # what a manual walk cost per item (t-1957 N2): `walk_timing.py --task <KEY> [--summary] [--json]`, run by a person and the conductor; reads only
    "driver_timing",   # where the time between two role calls goes (t-1937 P2): `driver_timing.py --task <KEY> [--json] [--check-hop-s N]`, run by a person and the conductor; reads only
    "app_card",   # the app card of a manual walk (t-1957 N3): built by the driver from the project facts, read by the walking role
    "explore_step",  # the exploration's one CLI (qa-explore): run by the conductor, the skill and a person; exploration.py is live through its import
    "branch_accounting",   # the S2 exit detector of branch accounting and its `--units` / `--unhomed` doors (G2-11): run by the gate, the tester and the conductor
    "place_answers",   # the places of S7 and the analyst's answer per place (t-1991): `place_answers.py list|write|close-unsettled`, run by the analyst, the driver and the conductor; investigation imports it; no hook does
    "bug_neighbours",   # the table of what the S7 failures, observations and drafts share (t-2187 N6): `bug_neighbours.py --task-root <T> [--json]`, run by the analyst, the driver and the conductor; reads only; no hook does
}
# `import x, y` / `from x import y` / `from x.y import z` — only the top-level module matters.
IMPORT_RE = re.compile('^[ \\t]*(?:from[ \\t]+([A-Za-z_]\\w*)[\\w.]*[ \\t]+import\\b|import[ \\t]+([^\\n#]+))', re.M)
SKILL_SIZE_LIMIT = 19_000  # the host truncates a skill body re-injected after compaction at ~20k chars
AGENT_MD_MAX_BYTES = 9_000  # B1 role size cap, mirrored from scripts/selftest.py's --limits
AGENT_REQUIRED_SECTIONS = ["## Role", "## Inputs", "## Procedure", "## Outputs", "## Witness", "## Refusals"]
# Does this role write files? The answer is a field, in two places that already state it: the
# artifact registry (`artifact-writers.json`, "one artifact, one writer") and the role's own
# `## Outputs` section, which `AGENT_REQUIRED_SECTIONS` makes mandatory. Until 0.7.19 A2 and A2b
# read the contract's PROSE for a verb list (`write the file|append to|save to file|…`), so a
# contract phrased around another verb lost the check that it was granted `Write` — the class
# FR-12 is about, in the audit that exists to catch classes like it.
OUTPUT_HEADING = "## Outputs"
# A path in that section: something with a directory in it, or a file with an artifact
# extension. The path is a value, not a wording. A bare script name is neither: `manifest_put.py`
# in an Outputs section is the door the role writes THROUGH, and a role that only has a door
# needs Bash, not Write — which is the distinction A2 is about.
OUTPUT_PATH_RE = re.compile(r"`[^`\n]*(?:/[^`\n]*|\.(?:md|json|jsonl|txt|yaml))[^`\n]*`")
from project_decisions import DEFERRED_MARKER, deferred_table  # noqa: E402  A13: the ONE marker pattern (any case, OH3-23 Q3) and the ONE audit reader of the table (Q2)
FINDINGS: list[str] = []


# Whose problem a violation is. A1/A2/A9/A11/A12/A14/A19/A21/A22 check the PLUGIN's own
# shipped files: nobody working on a project can act on them, and printing them to a person as
# if they could is how an audit section turns into noise they learn to scroll past. The rest
# are about the project's own artifacts and configuration, which a person can genuinely fix.
FACTORY_OWNED = {"A1", "A2", "A9", "A11", "A12", "A14", "A19", "A21", "A22", "A24", "A27"}


def check_owner(check: str) -> str:
    return "factory" if str(check).split()[0] in FACTORY_OWNED else "user"


def report(check: str, errors: list) -> None:
    if errors:
        FINDINGS.extend(f"[{check}] {e}" for e in errors)
        owner = check_owner(check)
        suffix = "  owner: factory — nothing is wanted from you" if owner == "factory" else "  owner: user"
        print(f"{check}: VIOLATIONS ({len(errors)}){suffix}")
        for e in errors:
            print(f"  - {e}")
    else:
        print(f"{check}: no violations")


def report_info(check: str, notes: list) -> None:
    """An observation, not a violation: printed so it is visible, never added to FINDINGS, so
    the exit code (and install_smoke.py) stays green. Silence and INFO must not look the same."""
    for n in notes:
        print(f"{check}: INFO — {n}")


def _local_imports(path: Path, module_names: set) -> set:
    """Top-level modules this script imports that are themselves scripts/ modules."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    found = set()
    for m in IMPORT_RE.finditer(text):
        if m.group(1):
            found.add(m.group(1))
        else:
            for part in m.group(2).split(","):
                found.add(part.strip().split(" ")[0].split(".")[0])
    return found & module_names


def _import_closure(scripts_dir: Path, seeds: set, module_names: set) -> set:
    """Every scripts/ module reachable from `seeds` through imports, seeds included."""
    seen, stack = set(seeds), list(seeds)
    while stack:
        cur = stack.pop()
        for dep in _local_imports(scripts_dir / f"{cur}.py", module_names):
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return seen


def a1_findings(plugin_root: Path) -> list:
    """A1 liveness. A scripts/*.py is LIVE when hooks/hooks.json names it, when a referenced
    hook imports it (directly or transitively — one process per event is the design), or when
    it is a declared CLI tool. Anything else is dead code shipped as if it ran; a hook-shaped
    script (HOOK_SCRIPTS) that goes dead is called out as a dead hook by name."""
    errors: list = []
    scripts_dir = plugin_root / "scripts"
    hooks_json = plugin_root / "hooks" / "hooks.json"
    if not hooks_json.exists():
        return ["hooks/hooks.json is missing — no hooks are registered"]
    try:
        wiring = json.loads(hooks_json.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"hooks/hooks.json is broken ({e})"]

    referenced: set = set()
    for entries in (wiring.get("hooks") or {}).values():
        for entry in entries:
            for h in entry.get("hooks", []):
                m = re.search(r"([\w.-]+\.py)\s*$", str(h.get("command", "")))
                if m:
                    referenced.add(m.group(1))
    for script in sorted(referenced):
        if not (scripts_dir / script).exists():
            errors.append(f"hooks.json references {script}, scripts/{script} does not exist")
    for script in HOOK_SCRIPTS:
        if not (scripts_dir / script).exists():
            errors.append(f"scripts/{script} is missing on disk")

    module_names = {p.stem for p in scripts_dir.glob("*.py")}
    live = _import_closure(scripts_dir, ({Path(r).stem for r in referenced} | CLI_SCRIPTS) & module_names,
                           module_names)
    hook_shaped = {Path(s).stem for s in HOOK_SCRIPTS}
    for stem in sorted(module_names - live):
        if stem in hook_shaped:
            errors.append(
                f"{stem}.py is not referenced by any entry in hooks/hooks.json, is not imported "
                "by a script that is, and is not a declared CLI tool — a dead hook"
            )
        else:
            errors.append(
                f"{stem}.py is reachable from nothing — not in hooks.json, not imported by a "
                "referenced hook, not in CLI_SCRIPTS: dead code shipped as if it ran"
            )
    return errors


def a1_hooks_liveness() -> None:
    report("A1 hook liveness", a1_findings(PLUGIN_ROOT))


def _section_body(text: str, heading: str) -> str:
    """The body under `heading`, up to the next `## `. Empty when the section is absent."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == heading:
            body = []
            for following in lines[i + 1:]:
                if following.strip().startswith("## "):
                    break
                body.append(following)
            return "\n".join(body)
    return ""


def _artifact_writer_roles() -> dict:
    """{role: [artifacts it is named the writer of]} from references/artifact-writers.json."""
    try:
        data = json.loads((PLUGIN_ROOT / "references" / "artifact-writers.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):                        # pragma: no cover - broken checkout
        return {}
    out: dict = {}
    for artifact, record in (data.get("artifacts") or {}).items():
        for role in re.findall(r"qa-[a-z-]+", str((record or {}).get("writer") or "")):
            out.setdefault(role, []).append(artifact)
    return out


def role_writes(role_file: Path, text: str) -> str:
    """Why this role writes files, or "" — from a field, never from the contract's wording."""
    named = _artifact_writer_roles().get(role_file.stem) or []
    if named:
        return f"artifact-writers.json names it the writer of {', '.join(sorted(named)[:3])}"
    found = OUTPUT_PATH_RE.findall(_section_body(text, OUTPUT_HEADING))
    return f"its `{OUTPUT_HEADING}` section names {found[0]}" if found else ""


def a2_role_tools_parity() -> None:
    errors = []
    agents_dir = PLUGIN_ROOT / "agents"
    for role_file in sorted_paths(agents_dir.glob("qa-*.md")) if agents_dir.exists() else []:
        text = role_file.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text) or {}
        tools = fm.get("tools", "")                      # the line's own text, for the message
        why = role_writes(role_file, text)
        if why and not tools_line(text) & {"Write", "Edit"}:     # membership of the set, not a substring
            errors.append(f"{role_file.name}: {why}, and its tools ({tools}) lack Write/Edit")
    report("A2 role/tools parity", errors)


def a2b_excess_write_right() -> None:
    """A2 reverse check (class F-2, "excess right"): a role holds Write and/or Edit while no
    artifact names it as a writer and its own `## Outputs` section names no file. Holding a tool
    the contract never asks for is exactly the kind of right nobody can "drift" off (see the
    file docstring, the qafactory principle)."""
    errors = []
    agents_dir = PLUGIN_ROOT / "agents"
    for role_file in sorted_paths(agents_dir.glob("*.md")) if agents_dir.exists() else []:
        text = role_file.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text) or {}
        tools = fm.get("tools", "")                      # the line's own text, for the message
        if not tools_line(text) & {"Write", "Edit"}:     # membership of the set, not a substring
            continue
        if not role_writes(role_file, text):
            errors.append(
                f"{role_file.name}: tools ({tools}) include Write/Edit, but no artifact names it "
                f"as a writer and its `{OUTPUT_HEADING}` section names no file — excess right "
                "(class F-2)"
            )
    report("A2b excess right (F-2)", errors)


def a2c_role_not_controller() -> None:
    """A2 reverse check — "role-controller": a role has no disallowedTools with the word Agent
    (Task dispatches through the same tool family) -> the isolation boundary is not closed by
    frontmatter, the role can physically spawn a subagent around the orchestrator."""
    errors = []
    agents_dir = PLUGIN_ROOT / "agents"
    for role_file in sorted_paths(agents_dir.glob("*.md")) if agents_dir.exists() else []:
        text = role_file.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text) or {}
        disallowed = fm.get("disallowedTools", "")
        if "Agent" not in disallowed:
            errors.append(
                f"{role_file.name}: no disallowedTools with Agent — the role can spawn subagents, "
                "the isolation boundary is not closed by frontmatter"
            )
    report("A2c role-controller", errors)


def a3_a4_artifacts() -> None:
    schema_errors: list = []
    sm_errors: list = []
    art_root = artifact_root()
    bugs_root = state_dir() / "bugs"
    import contract as C
    for case in C.case_glob(art_root, art_root) if art_root.exists() else []:
        errs: list = []
        va.check_case(case, errs)
        for e in errs:
            (sm_errors if "STATE MACHINE" in e else schema_errors).append(e)
        fm = parse_frontmatter(case.read_text(encoding="utf-8", errors="replace")) or {}
        rl = fm.get("red_lock", "")
        if rl and not (bugs_root / f"{rl}.md").exists():
            sm_errors.append(f"{case.name}: red_lock {rl} — file bugs/{rl}.md does not exist")
    for bug in sorted_paths(bugs_root.glob("*BUG-*.md")) if bugs_root.exists() else []:
        va.check_bug(bug, schema_errors)
    report("A3 case/bug schemas", schema_errors)
    report("A4 state machine", sm_errors)


def backlog_label(backlog: Path) -> str:
    """The backlog's path as a person can open it.

    The canonical file is `qa-factory/factory-backlog.md` — S9 writes it, the template
    describes it and project_decisions.py reads it; `qa-factory/state/factory-backlog.md`
    is only the legacy fallback still accepted for migration. Every message below used to
    name the legacy path unconditionally, so a run that had correctly read the canonical
    file still sent the reader to a stale one that said "No findings yet.". A message names
    the file the audit actually read."""
    try:
        return "qa-factory/" + backlog.resolve().relative_to(state_dir().resolve()).as_posix()
    except (OSError, ValueError):
        return "qa-factory/factory-backlog.md"


# The orchestrator's own control plane. These files are WRITTEN BY THE FACTORY after an
# acceptance by design — a dispatch is recorded, a checkpoint is saved, the projection is
# refreshed — so sealing them reported five violations per story that no person could act on
# and that drowned the findings a person can. The seal covers the story's evidence, which is
# what "do not touch an accepted artifact" was ever about.
CONTROL_PLANE = {"pipeline.json", "checkpoint.json", "controller.json", "events.jsonl",
                 "projection-stale.json", "environment-projection-stale.json", "manifest-projection-stale.json",
                 "journal.jsonl"}


def a5_seal() -> None:
    errors = []
    journal = RP.configured(project_root(), load_config().get("journal_path"), "journal.jsonl")
    if not journal.exists():
        print("A5 seal: journal is empty — nothing to check (explicit note)")
        return
    last_accept: dict[str, datetime] = {}
    last_gate: dict[str, datetime] = {}
    for line in journal.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("event") in ("accepted", "subagent_stop") and rec.get("task"):
            try:
                last_accept[rec["task"]] = datetime.fromisoformat(rec["ts"])
            except Exception:
                pass
        if rec.get("event") == "gate" and rec.get("task") and rec.get("decision"):
            try:
                ts = datetime.fromisoformat(rec["ts"])
            except Exception:
                continue
            prev = last_gate.get(rec["task"])
            if prev is None or ts > prev:
                last_gate[rec["task"]] = ts
    seal: dict[str, datetime] = dict(last_accept)
    for task, gate_at in last_gate.items():
        if task not in seal or gate_at > seal[task]:
            seal[task] = gate_at
    for task, accepted_at in seal.items():
        art_dir = artifact_root() / task
        if not art_dir.exists():
            continue
        for f in sorted_paths(art_dir.rglob("*")):
            if f.is_file() and f.name not in CONTROL_PLANE:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=accepted_at.tzinfo)
                if mtime > accepted_at:
                    errors.append(f"{task}/{f.name}: modified ({mtime:%H:%M:%S}) AFTER the last acceptance ({accepted_at:%H:%M:%S})")
    report("A5 seal", errors)


def a6_journal_format() -> None:
    errors = []
    journal = RP.configured(project_root(), load_config().get("journal_path"), "journal.jsonl")
    if not journal.exists():
        print("A6 journal: no file — the factory has not written events yet (explicit note)")
        return
    from log_append import EVENTS, FAILURE_CLASSES
    # The reject reason family was introduced 2026-09-10: rows older than that date are not
    # required to carry it - the journal is never rewritten after the fact (retro-fabrication is
    # forbidden, cf. journal_legacy_tasks).
    REASON_FAMILY_SINCE = "2026-09-10"
    for n, line in enumerate(journal.read_text(encoding="utf-8").splitlines(), 1):
        try:
            rec = json.loads(line)
        except Exception:
            errors.append(f"line {n}: not JSON")
            continue
        ev = rec.get("event")
        if ev not in EVENTS:
            errors.append(f"line {n}: unknown event '{ev}'")
            continue
        required = list(EVENTS[ev])
        if ev == "rejected" and str(rec.get("ts", "")) < REASON_FAMILY_SINCE:
            required = [f for f in required if f != "reason_family"]
        for f in required:
            if not rec.get(f):
                errors.append(f"line {n} ({ev}): missing field '{f}'")
        if ev == "rejected" and rec.get("failure_class") not in FAILURE_CLASSES:
            errors.append(f"line {n}: failure_class outside the allowed set")
    report("A6 journal", errors)


def a7_journal_completeness() -> None:
    """A task with artifacts but no journal events = journal silence (finding C-1)."""
    errors = []
    cfg = load_config()
    legacy = set(cfg.get("journal_legacy_tasks", []))
    journal = RP.configured(project_root(), cfg.get("journal_path"), "journal.jsonl")
    journaled_tasks: set = set()
    if journal.exists():
        for line in journal.read_text(encoding="utf-8").splitlines():
            try:
                t = json.loads(line).get("task", "")
                if t:
                    journaled_tasks.add(t)
            except Exception:
                pass
    art_root = artifact_root()
    # Container directories are not tasks: requirements/<epic> and releases/<release> are
    # checked at the nested-folder level, archive holds closed work.
    containers = {"requirements", "releases", "archive"}
    if art_root.exists():
        for task_dir in sorted_paths(art_root.iterdir()):
            if not task_dir.is_dir():
                continue
            if task_dir.name in containers:
                for sub in sorted_paths(task_dir.iterdir()):
                    if sub.is_dir() and sub.name not in journaled_tasks and sub.name not in legacy and task_dir.name != "archive":
                        errors.append(f"{task_dir.name}/{sub.name}: artifacts exist, no journal events — the pipeline ran past the journal")
                continue
            if task_dir.name not in journaled_tasks and task_dir.name not in legacy:
                errors.append(f"{task_dir.name}: artifacts exist, no journal events — the pipeline ran past the journal")
    report("A7 journal completeness", errors)


def a9_inject_map() -> None:
    errors = []
    map_path = ref("inject-map.json")
    if not map_path.exists():
        report("A9 injection map", ["references/inject-map.json is missing — injection is dead"])
        return
    try:
        imap = json.loads(map_path.read_text(encoding="utf-8"))
    except Exception as e:
        report("A9 injection map", [f"inject-map.json is broken ({e})"])
        return
    from inject_context import resolve_entry
    # Before onboarding, strategy/state files do not exist yet — expected, not a violation.
    onboarded = (state_dir() / "strategy" / "test-strategy.md").exists()
    missing_pre: set[str] = set()
    for rel in set(list(imap.get("common", [])) + [f for files in imap.get("roles", {}).values() for f in files]):
        if resolve_entry(rel).exists():
            continue
        project_generated = rel.startswith(("project:qa-factory/strategy/", "project:qa-factory/state/",
                                            "project:qa-factory/records/"))
        if project_generated and not onboarded:
            missing_pre.add(rel)
        else:
            errors.append(f"{rel}: listed in the map, file does not exist")
    if missing_pre:
        print(f"A9 (info): {len(missing_pre)} mapped files will appear at onboarding — their absence before it is not a violation")
    roles = set(imap.get("roles", {}))
    agents_dir = PLUGIN_ROOT / "agents"
    for role_file in sorted_paths(agents_dir.glob("*.md")) if agents_dir.exists() else []:
        if role_file.stem not in roles:
            errors.append(f"{role_file.name}: role is not in inject-map.json — it does not even receive the shared rules (Layer 1)")
    # A role slice is a GENERATED file that ships in the package: a stale one delivers a rule
    # the source no longer states, and nothing at runtime would notice (the hook renders
    # nothing — it has no time to). Freshness is therefore an audit fact, not a build habit.
    import contract_slices
    errors.extend(contract_slices.findings(PLUGIN_ROOT))
    report("A9 injection map", errors)


def _contract_sections(plugin_root: Path) -> dict:
    """Artifact filename -> (contract document, the text of its section).

    The contract documents are written as ``## `<filename>` `` sections; a heading may name
    more than one file. This is the parse A11 judges by — the contract document is the source
    of truth for what a role is allowed to be asked for, not the role's own prose."""
    sections: dict = {}
    for path in sorted_paths((plugin_root / "references").glob("artifact-contract*.md")):
        doc = path.name
        text = path.read_text(encoding="utf-8", errors="replace")
        parts = re.split(r"^## ", text, flags=re.M)[1:]
        for part in parts:
            heading, _, body = part.partition('\n')
            for fname in re.findall(r"`([\w.-]+\.(?:json|jsonl|md|txt))`", heading):
                sections[fname] = (doc, body)
    return sections


def a11_findings(plugin_root: Path, schemas: dict | None = None,
                 writers: dict | None = None) -> list:
    """A11 artifact schema sync. Every key the validator REQUIRES must be documented in
    references/artifact-contract*.md for that artifact; a required key the contract does not
    document is the violation (the exit gate would block an agent over an artifact written
    exactly as the contract describes it). The check used to read the writer ROLE's prose,
    which made every rephrasing in a role a false violation and let a donor-era schema for an
    artifact v0 does not have (classification / baseline-report / actual-complexity) survive as
    noise. The role is still checked for one thing only: that it exists and owns the schema."""
    schemas = va.PHASE_JSON_KEYS if schemas is None else schemas
    writers = va.PHASE_JSON_WRITERS if writers is None else writers
    errors: list = []
    agents_dir = plugin_root / "agents"
    sections = _contract_sections(plugin_root)
    if not sections:
        return ["references/artifact-contract*.md document no "
                "artifact at all — the validator's required keys have no source of truth"]
    for fname, keys in schemas.items():
        entry = sections.get(fname)
        if entry is None:
            errors.append(
                f"{fname}: the validator requires keys {list(keys)}, but no artifact-contract*.md "
                "section documents this file — either it is not part of the contract (drop the "
                "validator rule) or the contract is missing a section"
            )
        else:
            doc, body = entry
            missing = [k for k in keys if not re.search(r"\b" + re.escape(k) + r"\b", body)]
            if missing:
                errors.append(
                    f"{fname}: the validator requires keys {missing} that references/{doc} does "
                    "not document — the contract is the source of truth: document the key or "
                    "stop requiring it"
                )
        writer = writers.get(fname)
        if not writer:
            errors.append(f"{fname}: no writer named in PHASE_JSON_WRITERS — a schema without an owner")
        elif not (agents_dir / writer).exists():
            errors.append(f"{fname}: writer role {writer} not found in agents/")
    return errors


def a11_artifact_contract_sync() -> None:
    report("A11 artifact schema sync", a11_findings(PLUGIN_ROOT))


def a12_skill_size() -> None:
    """A skill body is re-injected after every compaction TRUNCATED (~20k characters) — everything
    past the threshold silently drops out of the orchestrator mid-task. The audit threshold of
    19k leaves a margin. Additionally: every phase file referenced by a SKILL.md exists."""
    errors = []
    skills_dir = PLUGIN_ROOT / "skills"
    for skill_md in sorted_paths(skills_dir.glob("*/SKILL.md")) if skills_dir.exists() else []:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        if content_bytes(skill_md) > SKILL_SIZE_LIMIT:
            errors.append(
                f"{skill_md.parent.name}/SKILL.md: {content_bytes(skill_md)} LF-normalized UTF-8 bytes > {SKILL_SIZE_LIMIT} — "
                "the tail will be cut by the post-compaction re-inject; move phase details into phases/*.md"
            )
        for ref_name in set(re.findall(r"phases/([\w.-]+\.md)", text)):
            if not (skill_md.parent / "phases" / ref_name).exists():
                errors.append(f"{skill_md.parent.name}/SKILL.md references phases/{ref_name} — file missing")
    report("A12 skill size", errors)


PLACEHOLDER_CELLS = {"", "n/a", "na", "none", "tbd", "?", "-", "--", "—", "–"}


def deferred_rows_without_a_question(backlog: Path) -> list:
    """The '## Deferred decisions' table's rows whose `asked` cell carries no question.

    A deferral means the team was asked and the answer did not come. A row with an empty
    `asked` cell is therefore not a deferral at all — it is a question the interview never
    put, filed where it looks accounted for. The whole table missing the column is the same
    defect one level up: the project's backlog predates the rule and cannot tell the two
    apart."""
    if not backlog.exists():
        return []
    table = deferred_table(backlog.read_text(encoding="utf-8", errors="replace"))  # the one audit reader (OH3-23 Q2); an escaped `\|` stays in its cell
    header, rows = table["columns"], table["rows"]
    if not rows:
        return []
    if "asked" not in header:
        return [f"{backlog_label(backlog)}: the 'Deferred decisions' table has no `asked` column — "
                "rebuild it from references/templates/factory-backlog.md; without the question on "
                "record a deferral cannot be told from a question nobody asked"]
    idx = header.index("asked")
    out = []
    for cells in rows:
        value = (cells[idx] if idx < len(cells) else "").strip()
        if value.lower() in PLACEHOLDER_CELLS:
            out.append(f"{backlog_label(backlog)}: {cells[0]} has nothing in its `asked` column — a "
                       "deferral for a question nobody put is a skipped question; ask it at "
                       "onboarding/the gate, or drop the row")
    return out


def _blank(value) -> bool:
    return not str(value or "").strip()


# The interview's required topics (p2-interview.md), each paired with the config.json evidence
# that it was actually answered and the words a deferral about it would contain. Topic 8
# (external writes) is absent on purpose: `markdown` is a first-class default, so that field
# is never a hole and its emptiness proves nothing.
REQUIRED_FACTS = [
    ("application repositories (interview topic 1)",
     lambda c: not (c.get("code_repos") or []) and not (c.get("protected_app_paths") or []),
     ("app_repo", "code_repos", "application repo", "application code", "app repo")),
    ("environment access (interview topic 2)",
     lambda c: (not (c.get("environments") or [])
                and _blank((c.get("environment") or {}).get("base_url_key"))
                and _blank((c.get("environment") or {}).get("env_file"))
                and _blank((c.get("environment") or {}).get("health_url"))),
     ("environment", "stand", "base_url", "endpoint", "url")),
    ("test-data lifecycle (interview topic 3)",
     lambda c: not any(str(v).strip() for v in (c.get("test_data") or {}).values() if v),
     ("test data", "test_data", "seeds", "pii", "cleanup", "accounts", "shared record")),
    ("ticket adapter (interview topic 7)",
     lambda c: _blank(((c.get("adapters") or {}).get("ticket") or {}).get("name")
                      or ((c.get("adapters") or {}).get("ticket") or {}).get("kind")),
     ("ticket", "adapter", "tms", "test management")),
]


def required_facts_without_a_deferral(cfg: dict, backlog: Path, profile: Path) -> list:
    """The mirror of the `asked` column. That one catches a deferral with no question behind
    it; this one catches the opposite and more silent failure — a required topic that left no
    trace at all, because the interview never asked and therefore never deferred it.

    The evidence is the config the onboarding wrote: a required fact is either filled in, or
    a DD row explains why it is not. Empty with no row means nobody was ever asked.

    `profile` (strategy/project-profile.md) is the proof that onboarding actually ran. A
    config seeded from the shipped example — install_smoke.py's sandbox, a hand-copied
    starter — has answered nothing because it was never asked anything, and judging it by
    this rule would paint every fresh install red."""
    if not profile.exists():
        return []

    rows_text = ""
    if backlog.exists():
        rows = deferred_table(backlog.read_text(encoding="utf-8", errors="replace"))["rows"]  # the one audit reader (OH3-23 Q2)
        rows_text = "\n".join(" | ".join(cells).lower() for cells in rows)

    out = []
    for label, is_empty, keywords in REQUIRED_FACTS:
        if not is_empty(cfg):
            continue
        if any(k in rows_text for k in keywords):
            continue  # asked, unanswered, and on record — a legitimate deferral
        out.append(
            f"config.json leaves {label} empty and {backlog_label(backlog)} has no deferral for "
            "it — a required onboarding topic that was neither answered nor asked. Re-run "
            "qa-onboarding and answer it, or record the deferral with the question that was put"
        )
    return out


def a13_marker_list(sources: list) -> list:
    """Every `[DEFERRED: ...]` marker of `sources` as (file, essence); the essence is stripped and
    EMPTY for a bare or blank marker, which is still a marker (AR-28)."""
    markers = []
    for f in sources:
        text = f.read_text(encoding="utf-8", errors="replace")
        markers.extend((f, m.group(1).strip()) for m in DEFERRED_MARKER.finditer(text))
    return markers


def a13_backlog_text(backlog: Path) -> tuple:
    """(text, unreadable): the backlog's text; ("", "") when no file stands there; ("", <exception
    name>) when it exists and cannot be read."""
    if not backlog.exists():
        return "", ""
    try:
        return backlog.read_text(encoding="utf-8", errors="replace"), ""
    except OSError as exc:
        return "", type(exc).__name__


def a13_squash(value) -> str:
    return " ".join(str(value).split()).lower()


def a13_markers_without_a_backlog(markers: list, backlog: Path, root: Path, unreadable: str) -> list:
    """One line per marker when the backlog is absent or unreadable: a hole with no row to pair is
    invisible, so each marker is named, with the door when the file exists but cannot be read."""
    gone = f"cannot be read ({unreadable})" if unreadable else "does not"
    door = "; make the file readable and re-run the audit" if unreadable else ""
    return [
        f"{f.relative_to(root)}: the marker [DEFERRED: {text[:40]}...] exists, "
        f"{backlog_label(backlog)} {gone} — a hole with no row is invisible{door}"
        for f, text in markers
    ]


def a13_unpaired_reason(rows: list, headings: list, holders: list) -> str:
    """Why no OPEN row of the table holds the marker: the specific cause and the door."""
    from project_decisions import HEADING as DD_HEADING  # the table's own heading, not a copy
    if headings and not rows and DD_HEADING not in headings:
        return (f"the section's heading is not `{DD_HEADING}` (the template's) — rename it, "
                "the table is read only under that heading")
    if rows and "status" not in rows[0]:
        return ("the table has no `status` column, so no row can be told open — rebuild it from "
                "references/templates/factory-backlog.md")
    if holders:
        return (f"the matching {', '.join(r['id'] for r in holders)} is closed (status "
                f"`{holders[0].get('status', '').strip()}`) — remove the marker or reopen the row")
    return ("no DD row's essence cell holds it (the first 40 characters of the essence are matched "
            "against the `essence + where the marker is` cell of open rows) — add the row "
            "(project_decisions.py add) or remove the marker")


def a13_unpaired_markers(markers: list, backlog: Path, backlog_text: str, root: Path) -> list:
    """The markers no OPEN row pairs, one line each. The table is read through
    `project_decisions.parse_rows`, the one reader of it (AR-13), never by a second walk."""
    from project_decisions import parse_rows
    cell = "essence + where the marker is"
    rows = parse_rows(backlog_text)
    headings = deferred_table(backlog_text)["headings"]
    errors = []
    for f, text in markers:
        needle = a13_squash(text)[:40].strip()
        where = f"{f.relative_to(root)}: the marker [DEFERRED: {text[:40]}] has no open DD-N row in {backlog_label(backlog)}"
        if not needle:
            errors.append(f"{where} — a marker with no essence cannot be paired; write the essence "
                          "between the brackets and add its row")
            continue
        holders = [r for r in rows if needle in a13_squash(r.get(cell, ""))]
        if any(a13_squash(r.get("status", "")) == "open" for r in holders):
            continue
        errors.append(f"{where} — {a13_unpaired_reason(rows, headings, holders)}")
    return errors


def a13_deferred_decisions() -> None:
    """A live [DEFERRED: ...] marker in strategy/*.md or config.json must have a pair — an
    OPEN row of the '## Deferred decisions (onboarding/gates)' table in factory-backlog.md (the
    registry of findings ABOUT THE FACTORY ITSELF, separate from task obligations in
    obligations.md). The pairing is by CELL (OH2-1): the first 40 characters of the marker's
    essence (lower-cased, runs of whitespace collapsed) must occur in the `essence + where the
    marker is` cell of an open row, read through `project_decisions.parse_rows` — the one reader
    of that table (AR-13). Prose elsewhere in the backlog (the template's own sentences) pairs
    nothing, a closed row pairs nothing, and a table with no `status` column cannot say which
    row is open (AR-28: an unknown never passes)."""
    errors = []
    sources = []
    strategy_dir = state_dir() / "strategy"
    if strategy_dir.exists():
        sources.extend(sorted_paths(strategy_dir.glob("*.md")))
    config_path = state_dir() / "config.json"
    if config_path.exists():
        sources.append(config_path)

    markers = a13_marker_list(sources)
    root = project_root()
    backlog = state_dir() / "factory-backlog.md"
    if not backlog.exists():
        backlog = state_dir() / "state" / "factory-backlog.md"
    backlog_text, unreadable = a13_backlog_text(backlog)
    if unreadable:
        if not markers:
            errors.append(f"{backlog_label(backlog)} cannot be read ({unreadable}) — A13 could not judge its DD rows; "
                          "make the file readable and re-run the audit")
    else:
        errors.extend(deferred_rows_without_a_question(backlog))
        if config_path.exists():
            errors.extend(required_facts_without_a_deferral(
                load_config(), backlog, strategy_dir / "project-profile.md"))

    if markers and (unreadable or not backlog.exists()):
        errors.extend(a13_markers_without_a_backlog(markers, backlog, root, unreadable))
    elif markers:
        errors.extend(a13_unpaired_markers(markers, backlog, backlog_text, root))
    report("A13 deferred decisions", errors)


# --- A20 ------------------------------------------------------------------------------------

# A path in config.json or in a strategy document is a promise about a location, and the file
# carrying it gets committed and cloned. An absolute path is a promise only its author's
# machine can keep: `/Users/Test_User_3/Projects/...` resolves nowhere for the next person,
# and it puts an employee's username into a shared repository on the way.
DRIVE_ROOTED = re.compile(r"^[A-Za-z]:[\\/]")
# The conservative half of the rule, for free text and shell commands: not "absolute" (a
# command may legitimately name /usr/bin or /var/run) but "somebody's home directory".
PERSONAL_PATH = re.compile(r"(?i)(?:/Users/|/home/|\\Users\\|:[\\/]Users[\\/]|(?:^|[\s\"'=])~[/\\])")
RELATIVE_HINT = ("replace it with a path relative to the project root (`.`, `..`, "
                 "`../testproject1`) — see references/common-rules.md, \"What a path is relative to\"")


def _machine_local(value) -> bool:
    """Does this value name a place only the machine that wrote it can resolve? Also the gate
    config_contract.migration_plan uses to drop a launch command (t-232), so it may err only
    toward True (dropped, then derived again on this machine), never toward False. A list is
    machine-local when any element is (an argv); `--opt=<path>` is judged by its path; a value
    that starts with an environment reference ($HOME/x, %TEMP%\\x) resolves differently on
    every machine, and a drive-relative `C:foo` depends on the current directory of that drive."""
    if isinstance(value, (list, tuple)):
        return any(_machine_local(item) for item in value)
    if isinstance(value, dict):
        return any(_machine_local(item) for item in value.values())
    v = str(value or "").strip().strip('"').strip("'")
    if not v:
        return False
    if v.startswith("-") and "=" in v:
        return _machine_local(v.split("=", 1)[1])
    return (v.startswith("/") or v.startswith("~") or v.startswith("\\") or v.startswith("$")
            or bool(re.match(r"^%[^%\s]+%", v)) or bool(re.match(r"^[A-Za-z]:", v)))


def _declared_paths(cfg: dict) -> list:
    """(label, value) for every config field whose value IS a path. Anything not on this list
    is judged by the softer PERSONAL_PATH rule instead — the point is to be strict where the
    field has one meaning and careful where it does not."""
    out = [(k, cfg.get(k)) for k in ("app_root", "tests_root", "cases_root", "journal_path")]
    for i, entry in enumerate(cfg.get("code_repos") or []):
        out.append((f"code_repos[{i}].path",
                    entry.get("path") if isinstance(entry, dict) else entry))
    out.extend((f"protected_app_paths[{i}]", p)
               for i, p in enumerate(cfg.get("protected_app_paths") or []))
    # the project's own test locations (D-0030) are paths relative to app_root; an absolute one opens nothing
    # and carries a colleague's username into the repository. A value that is not a list is judged by the
    # guard's own warning, not enumerated here (a text would be read character by character).
    listed = cfg.get("test_locations")
    out.extend((f"test_locations[{i}]", p) for i, p in enumerate(listed if isinstance(listed, list) else []))
    out.append(("environment.env_file", (cfg.get("environment") or {}).get("env_file")))
    for i, env in enumerate(cfg.get("environments") or []):
        if isinstance(env, dict):
            out.append((f"environments[{i}].env_file", env.get("env_file")))
    return [(k, str(v).strip()) for k, v in out if str(v or "").strip()]


def _free_text(cfg: dict) -> list:
    out = [(f"test_command_templates.{k}", v)
           for k, v in (cfg.get("test_command_templates") or {}).items()]
    out.extend((f"pre_commit_commands[{i}]", c)
               for i, c in enumerate(cfg.get("pre_commit_commands") or []))
    return [(k, str(v).strip()) for k, v in out if str(v or "").strip()]


# The value after one of these flags of runtime_probe.py is a path INSIDE the stand's container
# (`/app`): every machine resolves it the same way, so it is not a machine-local path even though
# it starts with a slash. Without this every entry the writer produces would be flagged by the rule
# its own argv was made portable for (t-238 W5).
CONTAINER_PATH_FLAGS = ("--app-root",)


def _probe_machine_local(spec) -> list:
    """[(where, value)] for every element of one `execution.runtime_probes` entry that only the
    machine that wrote it can resolve: each `argv` element on its own (an argv is a list, and one
    element is enough), and `cwd`. A container path (`CONTAINER_PATH_FLAGS`) is not one."""
    if not isinstance(spec, dict):
        return []
    argv = spec.get("argv")
    items = argv if isinstance(argv, list) else ([] if argv is None else [argv])
    found = []
    for i, item in enumerate(items):
        before = items[i - 1] if i else ""
        if before in CONTAINER_PATH_FLAGS or str(item).startswith(tuple(f + "=" for f in CONTAINER_PATH_FLAGS)):
            continue
        if _machine_local(item):
            found.append((f"argv[{i}]", item))
    if _machine_local(spec.get("cwd")):
        found.append(("cwd", spec.get("cwd")))
    return found


def non_portable_probe_entries(cfg: dict) -> list:
    """One error per `execution.runtime_probes` entry holding a machine-local element, naming the
    element(s). The old writer put `sys.executable` and the absolute plugin path into every entry;
    such an entry still RUNS (the reader leaves absolute paths as written) but travels to no other
    machine, so the fix is the factory's own writer: `--suggest --write --force` stores the
    portable form. An element that is NOT the factory's (a project script) is the project's to make
    relative."""
    probes = (cfg.get("execution") or {}).get("runtime_probes") if isinstance(cfg.get("execution"), dict) else None
    if not isinstance(probes, dict):
        return []
    errors = []
    for profile, spec in sorted(probes.items(), key=lambda kv: str(kv[0])):
        found = _probe_machine_local(spec)
        if not found:
            continue
        argv = spec.get("argv")
        script = str(argv[1]).replace("\\", "/").rsplit("/", 1)[-1] if isinstance(argv, list) and len(argv) > 1 else ""
        fix = (f"run `runtime_probe.py --suggest --write --force --profile {profile}`: it writes the "
               "portable form ({python}, {plugin_root}) that every machine resolves for itself"
               if script == "runtime_probe.py" else RELATIVE_HINT)
        named = ", ".join(f"{where} = \"{value}\"" for where, value in found)
        errors.append(f"config.json: execution.runtime_probes.{profile}: {named} — a machine-local "
                      f"path: it resolves only on the machine that wrote it, and this file is "
                      f"committed. {fix}")
    return errors


def non_portable_config_paths(cfg: dict) -> list:
    errors = [
        f"config.json: {label} = \"{value}\" is a machine-local path — it resolves only on the "
        f"machine that wrote it, and this file is committed. {RELATIVE_HINT}"
        for label, value in _declared_paths(cfg) if _machine_local(value)
    ]
    errors.extend(
        f"config.json: {label} = \"{value}\" contains someone's home directory — a command "
        f"that only runs on one laptop. {RELATIVE_HINT}"
        for label, value in _free_text(cfg) if PERSONAL_PATH.search(value)
    )
    errors.extend(non_portable_probe_entries(cfg))
    return errors


def personal_paths_in_docs(paths) -> list:
    """The same defect one file over: onboarding writes the profile for humans to read, and a
    pasted absolute path is as unportable there as in the config."""
    errors = []
    for path in paths:
        if not path.exists():
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if PERSONAL_PATH.search(line):
                errors.append(
                    f"{path.name}:{n}: a home-directory path in a generated document — "
                    f"`{line.strip()[:80]}`. {RELATIVE_HINT}"
                )
    return errors


def a20_portable_paths() -> None:
    config_path = state_dir() / "config.json"
    if not config_path.exists():
        report("A20 portable paths", [])
        return
    errors = non_portable_config_paths(load_config())
    strategy = state_dir() / "strategy"
    docs = sorted_paths(strategy.glob("*.md")) if strategy.exists() else []
    errors.extend(personal_paths_in_docs(docs))
    report("A20 portable paths", errors)


# --- A21 ------------------------------------------------------------------------------------

# The planning document and the code document reach disjoint audiences (inject-map.json), so
# a copied section costs no role any context — it costs correctness. Nothing keeps two copies
# equal, and the pilot's pair proved it: four shared sections, and the two `Team conventions`
# tables already listed different rules on the day onboarding wrote them.
SECTION_OWNERS = ("test-strategy.md", "framework-rules.md")
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*$")


def _normalized_headings(path: Path) -> dict:
    """{normalized heading: as written} for the `##` headings of one document."""
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("## "):
            continue
        raw = line[3:].strip()
        key = _PARENTHETICAL.sub("", raw).strip().lower()
        key = re.sub(r"[^a-z0-9]+", " ", key).strip()
        if key:
            out.setdefault(key, raw)
    return out


def duplicated_sections(first: Path, second: Path) -> list:
    a, b = _normalized_headings(first), _normalized_headings(second)
    if not a or not b:  # one of them missing is A3's business, not this rule's
        return []
    return [
        f"strategy/{first.name} and strategy/{second.name} both carry a section "
        f"\"{a[key]}\" / \"{b[key]}\" — one fact, two owners. The two files go to disjoint "
        "roles (inject-map.json), so a copy buys nothing and drifts the moment either is "
        "edited. Decide which document acts on it — a plan is decided with test-strategy, "
        "code is written against framework-rules — and leave a one-line pointer in the other "
        "(skills/qa-onboarding/phases/p4-generate.md, steps 2 and 4)"
        for key in sorted(set(a) & set(b))
    ]


def a21_one_owner_per_fact() -> None:
    strategy = state_dir() / "strategy"
    report("A21 one owner per fact",
           duplicated_sections(strategy / SECTION_OWNERS[0], strategy / SECTION_OWNERS[1]))


# --- A24 ------------------------------------------------------------------------------------

def a24_refusal_registry() -> None:
    """A24 refusal registry. Every place a hook refuses on the dispatch path is registered
    with the way a person's recorded word passes it and the test that proves it. The rule
    "a check stops a silent pass, never an informed one" was carried by memory until
    TP1-15045: the stage guard never read `stage_overrides[]`, `waiver.py` printed OK
    over a standing block, and the person was offered a line to edit inside the plugin."""
    import refusal_registry
    report("A24 refusal registry", refusal_registry.findings(PLUGIN_ROOT))


# --- A22 ------------------------------------------------------------------------------------

# What a role pays before its first useful action: its charter, the project's CLAUDE.md, the
# injection, the packet, the launch card, its brief with side files and its form - ONE number per
# role, added up by `role_load.py` (the only place that adds them, AR-13) and judged here in
# TOKENS. Every byte is read on the first turn and re-billed on every turn after it, so a document
# added "while we are here" to the common list is paid for by twelve roles across every dispatch of
# every story. Measured on TP1-14336: 26 dispatches, each opening with 28-47 KB of rules (9-14K
# tokens) before the first useful action. The check is not a style rule - it is the one place where
# growth is visible at all, because no single edit ever looks expensive. It replaces two byte caps
# that each saw a slice of the load (A22 injection 42,000 B per role; A25 dispatch 58,000 B per role).
#
# Three bounds, by who may move them:
#  - `threshold_tokens` (references/role-load.json): the OWNER's number. Provisional until
#    `threshold_confirmed_by` carries "owner, <date>"; a role over a provisional threshold prints an
#    info line and never turns the audit red (the number is set after the compression, not before).
#  - `ratchet_tokens` (same file): per role, at the maximum `role_load.py --all` measured when the
#    byte caps were retired. SHRINK-ONLY and red from the first day, so the window before the owner
#    confirms the threshold is not the "grew unmetered" history the old A25 comment records; a row
#    only goes down, and a raise is named in the verdict (AR-20).
#  - the two byte ratchets below over the layer every role is handed.
#
# Two ratchets over the layer every role is handed (SC1-9). `common` is now the manifesto alone;
# `common-rules.md` reaches each role as its own slice. The caps are the MEASURED values of
# `contract_slices.common_layer` rounded up to 250 and may only go down: growth shows as a red A22,
# and a raise is named in the verdict (AR-20), never made quietly.
INJECT_COMMON_CAP_BYTES = 5925        # the `common` list (list 5,262 B when measured)
COMMON_LAYER_CAP_BYTES = 10750        # the bytes every role's slice has in common (shared 10,734 B when measured)
# When a role is over, the remedy is never "write less" but "put the fact in the layer that owns it".
START_LOAD_REMEDY = ("move the fact to the layer that owns it (a rule code checks: the form's # Fill: comment and "
                     "the refusal; a section only some roles act on: <!-- roles: --> and contract_slices.py --write)")


def _a22_ratchets(plugin_root: Path, list_cap: int, shared_cap: int) -> tuple:
    """(errors, info lines) of the two byte ratchets over the layer every role is handed."""
    import contract_slices
    import role_load
    errors = []
    layer = contract_slices.common_layer(plugin_root)
    # A layer that could not be measured is an error, never a zero (AR-28).
    errors += [f"the common layer is not measured: {why}" for why in layer.get("errors") or []]
    common = role_load.common_list_bytes(plugin_root)
    if common is None:
        errors.append("the common injection is not measured: a file of the map's `common` list cannot be read")
    elif common > list_cap:
        errors.append(f"the common injection is {common:,} bytes (cap {list_cap:,}) "
                      "— every role pays this on every dispatch; mark what only some roles act on "
                      "for those roles (`<!-- roles: ... -->` in the source, e.g. references/common-rules.md, "
                      "delivered as the role's slice) and re-run `contract_slices.py --write`")
    shared = layer.get("shared")
    if not layer.get("errors") and isinstance(shared, int) and shared > shared_cap:
        errors.append(f"the layer every role is handed alike is {shared:,} bytes (cap {shared_cap:,}) "
                      "— mark what only some roles act on for those roles "
                      "(`<!-- roles: ... -->` in references/common-rules.md) and re-run "
                      "`contract_slices.py --write`; a raise of the cap is named in the verdict")
    info = []
    if isinstance(shared, int):
        origin = sorted((layer.get("per_role") or {}).values())
        info.append(f"A22 (info): shared layer {shared:,} B (cap {shared_cap:,})"
                    + (f", common-origin per role {origin[0]:,}..{origin[-1]:,} B" if origin else ""))
    return errors, info


def _a22_over_texts(load: dict, limit: int, ratchet) -> tuple:
    """(ratchet error or None, threshold text or None) for one role's static load."""
    import role_load
    heaviest = role_load.heaviest_layer(load)
    where = f"{heaviest['name']} {heaviest['bytes']:,} B is the heaviest"
    who = f"{load['role']} ({load['kind']}) starts with ~{load['tokens']:,} tokens"
    bound = None
    if ratchet is None:
        bound = (f"{load['role']} has no row in `ratchet_tokens` of references/role-load.json - add its measured "
                 f"~{load['tokens']:,} tokens (a role without a bound is a role nothing holds)")
    elif load["tokens"] > ratchet:
        bound = (f"{who}, over its shrink-only ratchet {ratchet:,} (`ratchet_tokens` in references/role-load.json): "
                 f"{where} - {START_LOAD_REMEDY}; a raise of the ratchet is named in the verdict")
    text = None
    if load["tokens"] > limit:
        text = (f"{who} (threshold {limit:,}): {where} - {START_LOAD_REMEDY}; a raise of the threshold is "
                "the owner's word in references/role-load.json")
    return bound, text


def _a22_start_load(plugin_root: Path, threshold: int | None = None, require_settings: bool = False) -> tuple:
    """(errors, info lines) of the per-role start load. The settings file absent from a tree that is not required to have it
    (a synthetic audit tree) prints one info line and judges nothing; absent from the tree that must have it (`require_settings`),
    or unreadable anywhere, is an error: an unreadable threshold is never "no threshold" (E6)."""
    import role_load
    if not role_load.settings_present(plugin_root) and not require_settings:
        return [], ["A22 (info): role-load.json absent: static layers only - the role start load was not judged"]
    try:
        cfg = role_load.settings(plugin_root)
    except role_load.RoleLoadError as exc:
        return [f"role-load.json could not be read - the start-load check did not run ({exc})"], []
    limit = cfg["threshold_tokens"] if threshold is None else threshold
    kinds_map = role_load.load_imap(plugin_root).get("kinds")
    kinds = [k for k in role_load.KINDS if k == "first" or (isinstance(kinds_map, dict) and k in kinds_map)]
    errors, provisional, firsts = [], [], []
    for role in role_load.role_names(plugin_root):
        for kind in kinds:
            try:
                load = role_load.static_load(role, kind, plugin_root)
            except Exception as exc:
                errors.append(f"the start load of {role} ({kind}) could not be measured: {type(exc).__name__}: {exc}")
                continue
            if kind == "first":
                firsts.append(load)
            ratchet = cfg["ratchet_tokens"].get(role)
            bound, text = _a22_over_texts(load, limit, ratchet)
            if bound and (kind == "first" or ratchet is not None):      # a role with no row is told once, not once per kind
                errors.append(bound)
            if text:
                (errors if cfg["threshold_confirmed"] else provisional).append(text)
    info = [f"A22 (info, threshold provisional): {t}" for t in provisional]
    # The process ratchet (spec t-1765 2.3, node A4): dense, slack 0. An old file without the key is NAMED: an error in the tree
    # that must have it (the shipped one), one info line elsewhere (a synthetic tree), never a crash.
    rows = cfg.get("process_ratchet_tokens")
    if rows is None and not require_settings:
        info.append("A22 (info): role-load.json has no process ratchet (`process_ratchet_tokens`): the process load was not judged")
    else:
        errors += [f"A22 process ratchet: {p}" for p in
                   role_load.process_ratchet_problems({ld["role"]: ld["process_tokens"] for ld in firsts}, rows,
                                                      role_load.agent_roles(plugin_root))]
    info += [f"A22 (info): craft marker {n}" for ld in firsts for n in ld["craft_notes"]]
    if cfg.get("target_tokens") is not None:
        info.append(f"A22 (info): target {cfg['target_tokens']:,} tokens of factory text per role "
                    + ("(confirmed)" if cfg["target_confirmed"] else "(informational, owner's word pending)"))
    # Headroom is the number that decides whether the next edit is affordable, and it is
    # invisible until something is already over: print the three heaviest roles every run.
    tight = sorted(firsts, key=lambda ld: -ld["tokens"])[:3]
    if tight:
        estimated = [n for n in role_load.LAYER_NAMES if any(n in ld["unmeasured"] for ld in firsts)]
        status = "confirmed" if cfg["threshold_confirmed"] else "provisional, owner's word pending"
        info.append("A22 (info): heaviest roles - "
                    + ", ".join(f"{ld['role']} ~{ld['tokens']:,} tokens ({limit - ld['tokens']:,} free)" for ld in tight)
                    + f"; threshold {limit:,} tokens ({status}); estimated: " + (", ".join(estimated) or "nothing"))
    return errors, info


def _a22_findings(plugin_root: Path, list_cap: int | None = None, shared_cap: int | None = None,
                  threshold: int | None = None, require_settings: bool = False) -> tuple:
    """(errors, info lines) of A22 on one plugin root - the caps are parameters so that AT and BEYOND a cap
    can be proved on a synthetic tree (FR-28). ([], []) when the map names no role."""
    import role_load
    if not role_load.role_names(plugin_root):
        return [], []
    errors, info = _a22_ratchets(plugin_root,
                                 INJECT_COMMON_CAP_BYTES if list_cap is None else list_cap,
                                 COMMON_LAYER_CAP_BYTES if shared_cap is None else shared_cap)
    load_errors, load_info = _a22_start_load(plugin_root, threshold, require_settings)
    return errors + load_errors, load_info + info


def a22_role_start_load() -> None:
    errors, info = _a22_findings(PLUGIN_ROOT, require_settings=True)
    for line in info:
        print(line)
    if info or errors:
        report("A22 role start load", errors)


def a14_definition_drift() -> None:
    """The plugin's own shipped files, judged by the ONE recipe: `release_fingerprint.compare()` answers
    `package_modified` (yes / no / unknown) from the release file `references/release-fingerprint.json`
    (written at release; collect/2 CL2-1, AR-15). A14 reads only that verdict and the survivor's WHY_TEXT, never
    the release file itself, and writes nothing (AR-13, AR-14).

    In the plugin model the DEFINITION IS the installed plugin version: the marketplace pins it. So `no` is the
    only "no violations"; `yes` is an INFO that names the files (a person's own edit of a cached install is
    not a factory fault, and the violation channel would call it one); `unknown` is an INFO that says so and why
    — never a pass, never an accusation (FR-41, AR-28)."""
    import release_fingerprint

    def _names_capped(names: list, cap: int = 10) -> str:    # a cut list says how much it hid
        return ", ".join(names[:cap]) + (f" (+{len(names) - cap} more)" if len(names) > cap else "")

    result = release_fingerprint.compare(PLUGIN_ROOT)
    verdict, why, install = result["package_modified"], result["why"], result["install"]
    if verdict == "no":
        report("A14 definition drift", [])
        return
    if verdict == "yes":
        notes = [f"package_modified: yes (release {result['release_version']}, install {install})"]
        notes += [f"{name}: {_names_capped(result[name])}" for name in ("changed", "added", "removed") if result[name]]
    else:
        reason = release_fingerprint.WHY_TEXT.get(why, (why, ""))[0]
        notes = [f"package_modified: unknown ({why}, install {install}) — {reason}"]
        if result["unreadable"]:
            notes.append(f"unreadable: {_names_capped(result['unreadable'])}")
    report_info("A14 definition drift", notes)


def a17_detector_rerun() -> None:
    """FB-27: a quoted detector output is not an acceptance. The audit re-runs the detectors
    itself and judges by the real exit code; a forgery lives at most until the next gate/calibration."""
    import subprocess
    errors = []
    refused_as_expected = None  # the root, when it is no project and the detector refused it as it must
    script = PLUGIN_ROOT / "scripts" / "check_coverage.py"
    try:
        root = project_root()
        has_project = (Path(root) / "qa-factory" / "config.json").is_file()
        r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120, cwd=str(root))
        text = (r.stdout or r.stderr or "").strip()
        # every finding of the verdict, not the last three lines of it (the one reader: detector_verdict)
        import detector_verdict
        verdict = " | ".join(detector_verdict.flatten(detector_verdict.parse(r.returncode, r.stdout, r.stderr)))
        if has_project:
            if r.returncode != 0:
                errors.append(f"check_coverage.py: real exit {r.returncode} - " + verdict)
        elif r.returncode == 0:
            # No project, nothing to reconcile: a pass here is a pass on an unknown (FR-59).
            errors.append("check_coverage.py: passed with no project (exit 0) - a detector must not "
                          "pass an unknown (FR-59)")
        elif r.returncode == 2 and "config.json" in text:
            refused_as_expected = root
        else:
            errors.append(f"check_coverage.py: real exit {r.returncode} - " + verdict)
    except Exception as e:
        errors.append(f"check_coverage.py: re-run failed ({type(e).__name__})")
    if refused_as_expected is not None and not errors:
        report_info("A17 detector re-run", [
            f"no project under {refused_as_expected}: check_coverage refused as it must (exit 2) - "
            "re-run the audit inside an onboarded project to reconcile a coverage map"])
        return
    report("A17 detector re-run", errors)


def a16_registry_hygiene() -> None:
    """Registries are shared with many writers (FB-26): duplicate ids are always a violation;
    a wall-of-text essence (>350 chars) is a violation only for rows created after 2026-09-02
    (date-cutoff per the FB-12 edit law)."""
    errors = []
    cutoff = "2026-09-02"
    root = state_dir()
    for rel, id_pat in (("obligations.md", r"OB-\d+"),
                        ("factory-backlog.md", r"(?:FB|DD)-\d+")):
        path = root / rel
        if not path.exists():
            path = root / "state" / rel  # the pre-0.3.0 spelling, still checked
        if not path.exists():
            continue
        seen = {}
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip().startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 3 or not re.fullmatch(id_pat, cells[0]):
                continue
            rid = cells[0]
            if rid in seen:
                errors.append(f"qa-factory/{rel}: duplicate id {rid} - the id must be the next free one across the whole file")
            seen[rid] = True
            essence = cells[1]
            created = next((c for c in cells if re.fullmatch(r"\d{4}-\d{2}-\d{2}", c)), "")
            if len(essence) > 350 and created > cutoff:
                errors.append(f"qa-factory/{rel}: {rid} - essence is {len(essence)} chars (cap 350): a wall of text; "
                              "one-two plain sentences, details go to the details column / witness")
    report("A16 registry hygiene", errors)


def _stage_done(task, stage):
    try:
        pipeline = json.loads((task / "pipeline.json").read_text(encoding="utf-8"))
        stages = pipeline.get("stages", {})
        row = stages.get(stage, {}) if isinstance(stages, dict) else next((r for r in stages if r.get("id") == stage), {})
        return row.get("status") == "done"
    except (OSError, ValueError):
        return False


def a15_findings(artifacts: Path, project_state: Path) -> tuple[list[str], int]:
    """Validate one active estimate bound to each completed S9 retro. `project_state` is
    <project>/qa-factory/state; the ledger is a carried record, so it is looked up through the layout
    (records/, or state/ in a project not yet re-onboarded) from the project that folder belongs to."""
    from estimate_record import active_records
    errors = []
    ledger = RP.record(Path(project_state).parent.parent, "estimation-ledger.jsonl")
    rows = []
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            try: rows.append(json.loads(line))
            except ValueError: errors.append("estimation-ledger.jsonl contains invalid JSON")
    tasks = [p for p in sorted_paths(artifacts.glob("*")) if p.is_dir() and _stage_done(p, "S9")]
    for task in tasks:
        retro = task / "retro.md"
        if not retro.is_file():
            errors.append(f"{task.name}: accepted S9 has no retro.md"); continue
        try:
            controller = json.loads((task / "state/controller.json").read_text(encoding="utf-8"))
            revision = controller.get("source_revision")
        except (OSError, ValueError):
            revision = None
        active = active_records(rows, task.name)
        if len(active) != 1:
            errors.append(f"{task.name}: completed S9 requires exactly one active estimation record (found {len(active)})")
            continue
        retro_hash = hashlib.sha256(retro.read_bytes()).hexdigest()
        row = active[0]
        if row.get("retro_sha256") != retro_hash or not revision or row.get("task_revision") != revision:
            errors.append(f"{task.name}: active estimation record is not bound to current retro.md and task revision")
    return errors, len(tasks)


def a15_estimation_loop() -> None:
    """Completed S9 must leave its current retro-bound estimation precedent."""
    errors, task_count = a15_findings(artifact_root(), state_dir() / "state")
    if not task_count and not errors:
        print("A15 estimation loop: not applicable (no completed S9)")
        return
    report("A15 estimation loop", errors)


def a18_board_runs_row() -> None:
    """Validate current reducer coverage, never an orphaned metrics-board writer."""
    import contract as C
    errors = []
    applicable = 0
    for task in sorted_paths(artifact_root().glob("*")):
        if not task.is_dir() or not (_stage_done(task, "S6") or _stage_done(task, "S8")): continue
        applicable += 1
        blocks = sorted_paths((task / "work/run-blocks").glob("*.json")) + sorted_paths((task / "work/manual-blocks").glob("*.json"))
        report_path = C.artifact(task, "run-report.json")
        if (task / "state/projection-stale.json").exists():
            errors.append(f"{task.name}: projection stale; recover the committed state, do not repeat tests")
        if (task / "state/environment-projection-stale.json").exists():
            # the third marker the dashboard flags (`factory_dashboard.py`): written by the environment jobs' refresh,
            # removed by its next successful one
            errors.append(f"{task.name}: the environment jobs projection is stale; the next successful environment "
                          "refresh clears it, do not repeat tests")
        if (task / "state/manifest-projection-stale.json").exists():
            # its own marker (the controller's recover does not rebuild the manifest): the door is the manifest's
            errors.append(f"{task.name}: the manifest projection is stale; replay the committed fragments with "
                          f"`manifest_put.py --task {task.name} --recover`, do not send them again")
        if blocks:
            try:
                result = json.loads(report_path.read_text(encoding="utf-8"))
                sources = {str(r.get("source")) for r in result.get("reducer", {}).get("sources", [])}
                missing = [p.name for p in blocks if p.relative_to(task / "work").as_posix() not in sources]
                if missing: errors.append(f"{task.name}: reducer is missing committed blocks: {missing}")
            except (OSError, ValueError): errors.append(f"{task.name}: missing or invalid current run-report.json")
        elif not report_path.exists():
            events = task / "state/events.jsonl"
            typed_skip = False
            if events.exists():
                try:
                    records = [json.loads(l) for l in events.read_text(encoding="utf-8").splitlines() if l.strip()]
                    typed_skip = any(e.get("type") == "code_only" and e.get("payload", {}).get("stage") == "S6"
                                     and e.get("payload", {}).get("reason") and e.get("payload", {}).get("evidence_refs") for e in records)
                except ValueError: pass
            if not typed_skip: errors.append(f"{task.name}: completed execution has neither results nor a typed no-execution receipt")
        if _stage_done(task,"S8") and not (task / "test-report.md").exists():
            errors.append(f"{task.name}: completed S8 has no test-report.md")
    if not applicable:
        print("A18 result projection: not applicable (no completed S6/S8)")
        return
    report("A18 result projection", errors)


def a19_agents_contract() -> None:
    """B1/B2: agents/*.md against the twelve-role contract and against
    references/stages.json — the stage table is read here, not duplicated as a Python
    list of role names, so a role added or renamed in stages.json is picked up without a
    matching edit to this file."""
    errors, notes = [], []
    agents_dir = PLUGIN_ROOT / "agents"
    if not agents_dir.exists():
        report("A19 agents contract", ["agents/ does not exist"])
        return
    try:
        stages = json.loads(ref("stages.json").read_text(encoding="utf-8"))
    except Exception as e:
        report("A19 agents contract", [f"references/stages.json is unreadable ({e}) — cannot check the dispatch suffix"])
        return
    role_stage: dict = {}
    for st in stages.get("stages") or []:
        for r in st.get("roles") or ([st["role"]] if st.get("role") else []):
            role_stage[r] = st.get("id")

    for role_file in sorted_paths(agents_dir.glob("*.md")):
        text = role_file.read_text(encoding="utf-8", errors="replace")
        stem = role_file.stem
        fm = parse_frontmatter(text) or {}

        name = fm.get("name")
        if name != stem:
            errors.append(f"{role_file.name}: frontmatter name {name!r} does not equal the file name {stem!r}")

        desc = fm.get("description") or ""
        if not desc:
            errors.append(f"{role_file.name}: no description in frontmatter")
        else:
            expected_stage = role_stage.get(stem)
            if not expected_stage:
                errors.append(f"{role_file.name}: role {stem!r} is not in references/stages.json — the dispatch suffix cannot be checked")
            else:
                suffix = f"Dispatched by qa-story at {expected_stage}."
                if not desc.rstrip().endswith(suffix):
                    errors.append(f"{role_file.name}: description must end with {suffix!r} (stages.json puts {stem!r} at {expected_stage})")

        if not tools_line(text):
            errors.append(f"{role_file.name}: no tools in frontmatter")

        disallowed = fm.get("disallowedTools") or ""
        if "Agent" not in disallowed or "Task" not in disallowed:
            errors.append(f"{role_file.name}: disallowedTools ({disallowed!r}) must contain both Agent and Task")

        if "model" in fm:
            errors.append(f"{role_file.name}: frontmatter carries a 'model' key — no role may pin a model")

        size = content_bytes(role_file)
        if size > AGENT_MD_MAX_BYTES:
            # INFORMATIONAL since P7.1, and the reason is measured: this is the lightest of the
            # three layers a dispatch pays for (a charter is 9 KB of the 56 KB a role is handed)
            # and it was the only one with a cap, so every rule that belongs to all twelve roles
            # hit it while the 23 KB of slices grew unmetered. The check that binds is A22, which
            # counts this file inside the whole start load. A charter over 9,000 bytes is still
            # worth knowing about - it usually means a fact is being restated that another layer
            # owns - so it is printed, with the headroom that decides whether it matters.
            notes.append(f"{role_file.name}: {size} bytes, over the {AGENT_MD_MAX_BYTES} of the "
                         "old per-file cap — A22 is what binds (check the role start load above); "
                         "if this grew by restating a rule, move it to the layer that owns it")

        if charter.is_charter(text):
            # a charter (spec t-1765 3.3) is judged by its own form, the six sections; the old section list does not apply
            errors += [f"{role_file.name}: {problem}" for problem in charter.charter_errors(text)]
            notes_stray = [f"{role_file.name}: kind marker not above a heading, {m}" for m in charter.stray_markers(text)]
            if notes_stray:
                report_info("A19 charter markers", notes_stray)
        else:
            missing_sections = [s for s in AGENT_REQUIRED_SECTIONS if s not in text]
            if missing_sections:
                errors.append(f"{role_file.name}: missing section(s) {missing_sections}")

    stems = {f.stem for f in agents_dir.glob("*.md")}
    for role in role_stage:
        if role not in stems:
            errors.append(f"{role}: named in references/stages.json, agents/{role}.md does not exist")

    if notes:
        report_info("A19 charter size", notes)
    report("A19 agents contract", errors)


# --- A27 ------------------------------------------------------------------------------------
#
# A27 "a state without a move outside the seam" (conductor/1 C1-8; the owner's principle P22; FR-42).
# The driver (story_run.py plus driver_*.py) meets states it has no move for; ONE function answers
# them, `Driver.no_move`. A27 finds, outside that seam, (P) a `Person` built or a builder of one
# called, (S) the same for `Stop`/`InfraStop`, and (U) a factory script run (`self.py` /
# `self.py_stdout`) whose result is dropped or only printed. Error direction: a false red is allowed
# (a door or a baseline row exists for it); a new site reported clean is not. It is NOT wired into
# main()'s full list: like A26 it is a check of the package's own source (scripts/tests/ runs it,
# CI package-fast runs that); `--no-move` prints the census. This section writes nothing (FR-45).
# It parses the DRIVER SET only (story_run.py and the glob driver_*.py), never the other scripts: a module outside
# that set is neither scanned nor reported as unparsable (t-836 F3; a driver is bound by being in the set).

# The seam: its members (`Driver.<m>`) are exempt, and the internal ones may be referenced only from
# inside it. A closed set of the package's own structure (FR-13), checked against the live Driver by
# test_no_move_seam_c26_g27_f2.py n24.
NO_MOVE_SEAM = frozenset({
    "Driver.no_move", "Driver._no_move", "Driver.no_move_legacy", "Driver._person_of",
    "Driver.site_person", "Driver.fallback_person", "Driver.last_resort", "Driver.options_person",
    "Driver._ask_conductor", "Driver.unread", "Driver.funnel"})
NO_MOVE_ENTRIES = frozenset({"no_move", "unread", "funnel"})
# I-one: where `run_claude("conductor", ...)` and the one `self.conductor(...)` call may stand.
CONDUCTOR_SITES = {"conductor": ("Driver.conductor", "Driver.delivery"), "call": ("Driver._ask_conductor",)}
# The shrink-only exact-count baseline of today's sites: {(file, qualname, class, discriminator): count},
# one row per line and sorted, so that two nodes' edits merge line by line. The cap must equal the sum.
NO_MOVE_BASELINE: dict = {
    ('driver_conductor.py', 'Driver.pass_to_person', 'P', 'Person:?'): 1,
    ('driver_core.py', 'Driver.__init__', 'S', 'Stop:?'): 1,
    ('driver_dialog.py', 'Driver.pass_block', 'P', 'builder:held_question'): 1,
    ('driver_dispatch.py', 'Driver._answer_exit_limit', 'P', 'builder:held_question'): 1,
    ('driver_dispatch.py', 'Driver._answer_repair_limit', 'P', 'builder:held_question'): 4,
    ('driver_dispatch.py', 'Driver._exit_fresh', 'P', 'builder:held_question'): 1,
    ('driver_dispatch.py', 'Driver._exit_go_on', 'P', 'builder:held_question'): 2,
    ('driver_dispatch.py', 'Driver.question_threshold', 'P', 'Person:questions'): 1,
    ('driver_dispatch.py', 'Driver.resume_role', 'P', 'Person:halt'): 1,
    ('driver_dispatch.py', 'Driver.run_role', 'P', 'Person:halt'): 1,
    ('driver_dispatch.py', 'Driver.run_role', 'P', 'Person:s1_review'): 1,
    ('driver_dispatch.py', 'Driver.s1_person', 'P', 'Person:s1_gap'): 1,
    ('driver_dispatch.py', 'Driver.s1_person', 'P', 'Person:s1_review'): 1,
    ('driver_dispatch.py', 'Driver.take_question_answer', 'P', 'builder:held_question'): 2,
    ('driver_gates.py', 'Driver.gate', 'P', 'Person:?'): 1,
    ('driver_machine.py', 'Driver._act_await_implementation', 'S', 'Stop:EXIT_DONE'): 1,
    ('driver_machine.py', 'Driver._act_awaiting_stopped', 'S', 'Stop:EXIT_DONE'): 1,
    ('driver_machine.py', 'Driver._act_closed', 'S', 'Stop:EXIT_DONE'): 1,
    ('driver_machine.py', 'Driver._act_wait_existing_job', 'P', 'Person:?'): 1,
    ('driver_machine.py', 'Driver._act_wait_existing_job', 'P', 'Person:questions'): 1,
    ('driver_machine.py', 'Driver._finish_saved_result', 'P', 'Person:halt'): 1,
    ('driver_machine.py', 'Driver._revoke_changed_carries', 'U', 'waiver.py'): 1,
    ('driver_machine.py', 'Driver.approve_by_option', 'P', 'builder:held_question'): 1,
    ('driver_machine.py', 'Driver.arrival_record', 'P', 'Person:arrival_not_waiting'): 1,
    ('driver_machine.py', 'Driver.arrival_record', 'S', 'Stop:EXIT_DONE'): 1,
    ('driver_machine.py', 'Driver.check_run_mode', 'P', 'Person:package'): 1,
    ('driver_machine.py', 'Driver.handle_refusal', 'P', 'Person:?'): 1,
    ('driver_machine.py', 'Driver.handle_refusal', 'S', 'Stop:EXIT_ERROR'): 1,
    ('driver_machine.py', 'Driver.take_answer', 'P', 'builder:held_question'): 1,
    ('driver_machine.py', 'Driver.take_answer', 'S', 'Stop:EXIT_ERROR'): 2,
    ('driver_machine.py', 'Driver.take_package_answer', 'P', 'Person:package'): 1,
    ('driver_machine.py', 'Driver.take_seam_answer', 'P', 'builder:held_question'): 1,
    ('driver_runner.py', 'Driver.package_check', 'P', 'Person:package'): 1,
    ('driver_runner.py', 'Driver.run_claude', 'S', 'InfraStop:?'): 1,
    ('driver_runner.py', 'Driver.run_claude', 'S', 'Stop:EXIT_ERROR'): 1,
    ('driver_runner.py', 'Driver.words_file', 'S', 'Stop:EXIT_ERROR'): 1,
    ('driver_s0.py', 'Driver.s0_read_word', 'P', 'builder:s0_again'): 1,
    ('driver_s0.py', 'Driver.s0_stop', 'P', 'Person:?'): 1,
    ('driver_s0.py', 'Driver.take_ticket_auth_answer', 'P', 'builder:held_question'): 1,
    ('driver_s0.py', 'Driver.ticket_ask_again', 'P', 'builder:ticket_changed_from_files'): 1,
    ('driver_s0.py', 'Driver.ticket_freshness', 'P', 'builder:ticket_changed_person'): 1,
    ('driver_s0.py', 'Driver.ticket_freshness_entry', 'P', 'builder:ticket_changed_from_files'): 1,
    ('driver_s0.py', 'Driver.ticket_look_failed', 'P', 'builder:ticket_auth_person'): 1,
    ('driver_stage_build.py', 'Driver.build_outcome', 'P', 'builder:build_person'): 2,
    ('driver_stage_build.py', 'Driver.take_build_answer', 'P', 'Person:stand_identity'): 2,
    ('driver_stage_s7.py', 'Driver._answer_open_work', 'P', 'builder:held_question'): 1,
    ('driver_stage_s8s9.py', 'Driver.stage_S9', 'P', 'Person:retro'): 1,
}
NO_MOVE_BASELINE_MAX = 55   # PC-7 (t-2181) raise 51 -> 55, reviewed: the four sites of the awaiting-code wait are each an ended run with exit 0 at the person's word (`arrival_record` stop, `_act_await_implementation`, `_act_awaiting_stopped`) or the closed question `arrival.not_waiting` with its three answers. C1-7c (t-1239) on C1-7b: 57 -> 51, the 6 `U` sites of the other owners' functions (O1/O3 `halted` record `py_trace`, O2/O4 `running` record `check=True`, O5 the ledger `check=True` + the traceability door, O6 `delivery_summary` `check=True`). C1-7b (t-1214) on C1-6c: 68 -> 57, the 11 `U` sites of the stage functions (G1-G5 `check=True`, T1/T4/T5/T6 `py_trace`, W15 `owe_row`, L1/R1 doors); the B3 rule (F9) found no new site. C1-6c (t-1213) on C1-6b: 71 -> 68, the three `Person("conductor")` raises of `Driver.delivery` are the closed question `s8.delivery`. C1-6b fix round (t-1234): 72 -> 71, the stand answer's journal row is `answer_row` (owed on a failed write). C1-6b (t-1212) on C1-7a (t-1162): 78 -> 72, the two stand questions are seam questions with a door (-2 Person rows), their site-own executors are gone (-4 log_append rows). Before: C1-7a 102 -> 78, the 24 `U` sites that `owe_row` / `answer_row` / `py_trace` now read (CX1-15, t-1117: 101 -> 102, the ONE `Stop` of `Driver.__init__`)

DRIVER_ENTRY = "story_run.py"      # the driver's main file; the rest of the driver set is scripts/driver_*.py
A27_CHECK = "A27 no move outside the seam"
A27_CLASSES = {"Person": "P", "Stop": "S", "InfraStop": "S"}
A27_DRIVER_CLASS = re.compile(r"^Driver[A-Za-z0-9]*$")
A27_DOOR = re.compile(r"^#\s*remains:(.*)$")
A27_SEAM_KEYS = ("again", "site_fallback")
A27_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
A27_BEFORE_DOORS = ("door", "baseline", "NEW")
A27_BLIND = (
    "B1: getattr(self, \"py\")(...), getattr(self, \"<builder>\")(...) and every dynamic call or call on a receiver other than self",
    "B2: a [delegated] result handed to a callee, which A27 cannot follow (printed by instance)",
    "B4: the skill's prose twins (references/halts.md, phase files) are not read (C1-7 owns them)",
    "B5: an `except Refusal` that swallows is not seen (conductor/3)",
    "B6: a state carried out through a container (`return \"\", self.build_person(...)`) is counted where it was built or called",
    "B7: a swap inside one baseline key (same file, function, class and discriminator, including the shared `?`) stays green",
)
A27_TOTALS = ("P-built", "S-built", "seam", "builder-built", "builder-calls", "U", "delegated", "py-wrappers",
              "doors", "counted", "baseline", "new", "stale")


class A27Site(NamedTuple):
    file: str
    line: int
    stmt_line: int
    qual: str
    cls: str
    disc: str
    verdict: str          # seam | door | builder | delegated | counted (then baseline | NEW after the judge)
    reason: str = ""


class A27Scan(NamedTuple):
    sites: list
    problems: list        # structural findings: cannot scan, integrity, I-one, doors, stale rows, the cap
    news: list            # one finding per [NEW] site
    files: list
    totals: dict
    bare_py: int


class _A27Mod(NamedTuple):
    name: str
    text: str
    tree: ast.Module
    nodes: list           # every node of the tree in ast.walk order, listed once for the whole scan
    parent: dict
    names: dict           # local name -> Person | Stop | InfraStop bound from the driver
    aliases: set          # local names of driver modules (`import story_run as X`)
    driver: bool


class _A27Fn(NamedTuple):
    key: tuple            # ("m", name) for a Driver member, ("f", name) for a module-level function
    qual: str
    node: ast.AST
    mod: _A27Mod
    ann: frozenset        # classes ("P", "S") the return annotation mentions
    rets: list
    binds: dict


def _a27_parse(path: Path) -> tuple:
    """(text, tree, error). The same read -> decode -> parse step as gate_registry.scan_file (an unscannable
    file is never a clean file); a non-UTF-8 file is NOT read with errors="replace"."""
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as exc:
        return "", None, f"cannot be read: {exc}"
    except UnicodeDecodeError as exc:
        return "", None, f"does not parse: {type(exc).__name__}: {exc}"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return text, ast.parse(text, filename=str(path)), ""
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        return "", None, f"does not parse: {type(exc).__name__}: {exc}"


def _a27_index(tree: ast.AST) -> tuple:
    """(nodes, parent): the nodes in ast.walk order and each node's parent, from ONE walk (a scan walks a driver many times)."""
    nodes = [tree]
    parent: dict = {}
    for node in nodes:
        for child in ast.iter_child_nodes(node):
            parent[child] = node
            nodes.append(child)
    return nodes, parent


def _a27_up(node: ast.AST, parent: dict):
    while node in parent:
        node = parent[node]
        yield node


def _a27_bound(tree: ast.Module, nodes: list, text: str, is_driver: bool, stems: set) -> tuple:
    """(names, aliases): what a module binds from the driver. (i) a driver module defines the classes;
    (ii)/(iii) any module binds them by `from <d> import ...` (aliases, `*`) or `import <d> [as X]`."""
    names = {}
    if is_driver:
        names.update({n.name: n.name for n in tree.body if isinstance(n, ast.ClassDef) and n.name in A27_CLASSES})
    aliases: set = set()
    if any(stem in text for stem in stems):
        for node in nodes:
            if isinstance(node, ast.ImportFrom):
                base = (node.module or "").split(".")[-1]
                for alias in node.names:
                    local = alias.asname or alias.name
                    if alias.name in stems:
                        aliases.add(local)
                    elif base in stems and alias.name == "*":
                        names.update({c: c for c in A27_CLASSES})
                    elif base in stems and alias.name in A27_CLASSES:
                        names[local] = alias.name
            elif isinstance(node, ast.Import):
                aliases.update(a.asname or a.name for a in node.names if a.name in stems)
    return names, aliases


def _a27_load(scripts: Path, driver: set, problems: list, failed: set) -> list:
    """The driver set (scripts/story_run.py and scripts/driver_*.py) and nothing else, parsed once. The package's other
    scripts are not parsed: a scan of all of them cost 9 of its 14 seconds (t-836 F3, the Lead's decision, spec L-3)."""
    stems = {Path(n).stem for n in driver}
    mods = []
    for name in sorted(driver):
        text, tree, error = _a27_parse(scripts / name)
        if error:
            problems.append(f"A27 cannot scan {name}: {error}")
            failed.add(name)
            continue
        nodes, parent = _a27_index(tree)
        names, aliases = _a27_bound(tree, nodes, text, True, stems)
        mods.append(_A27Mod(name, text, tree, nodes, parent, names, aliases, True))
    return mods


def _a27_ctx(node: ast.AST, parent: dict) -> tuple:
    """(qualname, innermost statement) of a node. A nested def/lambda keys to its OUTERMOST function; a
    Driver* class keys as `Driver`; module level is `<module>`, a class body `<Class>.<class body>`."""
    chain = list(_a27_up(node, parent))
    stmt = next((a for a in chain if isinstance(a, ast.stmt)), None)
    defs = [i for i, a in enumerate(chain) if isinstance(a, A27_DEFS)]
    above = chain[defs[-1] + 1:] if defs else chain
    cls = next((a for a in above if isinstance(a, ast.ClassDef)), None)
    cname = "" if cls is None else ("Driver" if A27_DRIVER_CLASS.match(cls.name) else cls.name)
    if defs:
        fname = chain[defs[-1]].name
        return (f"{cname}.{fname}" if cname else fname), stmt
    return (f"{cname}.<class body>" if cname else "<module>"), stmt


def _a27_is_seam_call(call: ast.AST) -> bool:
    f = getattr(call, "func", None)
    return (isinstance(call, ast.Call) and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
            and f.value.id == "self" and f.attr in ("unread", "no_move"))


def _a27_seam_lambda(lam: ast.Lambda, parent: dict) -> bool:
    """A lambda that is the value of the keyword `again=` / `site_fallback=` (EXACTLY these two names) of a call to
    self.unread / self.no_move, or the value of the dict key "site_fallback" in the STATE argument of self.no_move
    (its first positional argument or `state=`): a dict anywhere else, and any dict handed to self.unread, is no door."""
    up = parent.get(lam)
    if isinstance(up, ast.keyword):
        return up.arg in A27_SEAM_KEYS and _a27_is_seam_call(parent.get(up))
    if not isinstance(up, ast.Dict) or not any(
            isinstance(k, ast.Constant) and k.value == "site_fallback" and v is lam for k, v in zip(up.keys, up.values)):
        return False
    slot = parent.get(up)
    call = parent.get(slot) if isinstance(slot, ast.keyword) else slot
    if not (_a27_is_seam_call(call) and call.func.attr == "no_move"):
        return False
    return slot.arg == "state" if isinstance(slot, ast.keyword) else bool(call.args) and call.args[0] is up


def _a27_exempt(node: ast.AST, parent: dict) -> bool:
    """The site lies inside a lambda that the seam raises (`again=` / `site_fallback=`)."""
    return any(isinstance(a, ast.Lambda) and _a27_seam_lambda(a, parent) for a in _a27_up(node, parent))


def _a27_construct(call: ast.Call, names: dict, aliases: set):
    """The canonical class name when `call` builds a driver Person/Stop/InfraStop, else None."""
    f = call.func
    if isinstance(f, ast.Name):
        return names.get(f.id)
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in aliases and f.attr in A27_CLASSES:
        return f.attr
    return None


def _a27_disc(call: ast.Call, canon: str) -> str:
    """The discriminator of a construction: Person:<kind>, Stop:<code>, InfraStop:<kind>, else ?."""
    wanted = "code" if canon == "Stop" else "kind"
    first = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == wanted), None)
    if isinstance(first, ast.Starred):
        first = None
    if canon == "Stop":
        ok = isinstance(first, (ast.Name, ast.Attribute)) or (isinstance(first, ast.Constant) and type(first.value) is int)
        return "Stop:" + (ast.unparse(first) if ok else "?")
    ok = isinstance(first, ast.Constant) and isinstance(first.value, str)
    return f"{canon}:" + (first.value if ok else "?")


def _a27_own(fn: ast.AST):
    """The nodes of a function's OWN body: nested defs, lambdas and classes are yielded, not entered."""
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, A27_DEFS + (ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(node))


def _a27_returns_binds(fn: ast.AST) -> tuple:
    rets, binds = [], {}
    for node in _a27_own(fn):
        if isinstance(node, ast.Return) and node.value is not None:
            rets.append(node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    binds.setdefault(target.id, []).append(node.value)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None and isinstance(node.target, ast.Name):
            binds.setdefault(node.target.id, []).append(node.value)
    return rets, binds


def _a27_annotation(fn: ast.AST, names: dict) -> frozenset:
    """Classes a return annotation mentions: a Name, an Attribute, or a string holding the name as a word."""
    found = set()
    for node in ast.walk(fn.returns) if fn.returns is not None else ():
        if isinstance(node, ast.Name) and node.id in names:
            found.add(A27_CLASSES[names[node.id]])
        elif isinstance(node, ast.Attribute) and node.attr in A27_CLASSES:
            found.add(A27_CLASSES[node.attr])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.update(A27_CLASSES[canon] for local, canon in names.items()
                         if re.search(r"\b" + re.escape(local) + r"\b", node.value))
    return frozenset(found)


def _a27_functions(mods: list) -> list:
    """The functions that can be builders: module-level functions and members of Driver* classes."""
    out = []
    for mod in mods:
        if not mod.driver:
            continue
        for node in mod.nodes:
            if not isinstance(node, A27_DEFS):
                continue
            up = mod.parent[node]
            if isinstance(up, ast.Module):
                key, qual = ("f", node.name), node.name
            elif isinstance(up, ast.ClassDef) and A27_DRIVER_CLASS.match(up.name):
                key, qual = ("m", node.name), f"Driver.{node.name}"
            else:
                continue
            rets, binds = _a27_returns_binds(node)
            out.append(_A27Fn(key, qual, node, mod, _a27_annotation(node, mod.names), rets, binds))
    return out


def _a27_callee(call: ast.Call):
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "self":
        return ("m", f.attr)
    return ("f", f.id) if isinstance(f, ast.Name) else None


def _a27_classify(call: ast.Call, mod: _A27Mod, found: dict):
    """"P" / "S" when `call` is a construction or a call of a builder, else None."""
    canon = _a27_construct(call, mod.names, mod.aliases)
    if canon:
        return A27_CLASSES[canon]
    classes = found.get(_a27_callee(call))
    return ("P" if "P" in classes else "S") if classes else None


def _a27_shaped(expr: ast.AST, binds: dict, classify) -> list:
    """The builder-shaped values an expression can be: a construction, a call of a builder, a Name the
    function binds to one, or a branch of an IfExp / BoolOp of them. [(call node, class)]."""
    out, stack, seen = [], [expr], set()
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Call):
            cls = classify(node)
            if cls:
                out.append((node, cls))
        elif isinstance(node, ast.Name):
            if node.id not in seen:
                seen.add(node.id)
                stack.extend(binds.get(node.id, ()))
        elif isinstance(node, ast.IfExp):
            stack.extend([node.body, node.orelse])
        elif isinstance(node, ast.BoolOp):
            stack.extend(node.values)
    return out


def _a27_fn_shaped(fn: _A27Fn, found: dict) -> list:
    out = []
    for ret in fn.rets:
        out.extend(_a27_shaped(ret.value, fn.binds, lambda call: _a27_classify(call, fn.mod, found)))
    return out


def _a27_builders(funcs: list) -> dict:
    """{key: classes}: a function is a builder when its return annotation mentions a bound class or one of its
    own returns is builder-shaped. The closure is TRANSITIVE (a fixpoint over every function): a wrapper of a
    builder that carries no annotation is a builder too, or `raise self.wrapper()` would be a way around the count."""
    found = {fn.key: set(fn.ann) for fn in funcs if fn.ann}
    changed = True
    while changed:
        changed = False
        for fn in funcs:
            for _, cls in _a27_fn_shaped(fn, found):
                if cls not in found.get(fn.key, ()):
                    found.setdefault(fn.key, set()).add(cls)
                    changed = True
    return found


def _a27_builder_nodes(funcs: list, found: dict) -> set:
    """The calls that are the returned value of a NON-SEAM builder: counted at the builder's callers."""
    nodes: set = set()
    for fn in funcs:
        if fn.key in found and fn.qual not in NO_MOVE_SEAM:
            nodes.update(call for call, _ in _a27_fn_shaped(fn, found))
    return nodes


def _a27_ps_sites(mod: _A27Mod, found: dict, bnodes: set) -> list:
    """P / S: every construction, and every call of a non-seam builder, outside the seam."""
    out = []
    for call in (n for n in mod.nodes if isinstance(n, ast.Call)):
        canon = _a27_construct(call, mod.names, mod.aliases)
        key = None if canon or not mod.driver else _a27_callee(call)
        if not canon and key not in found:
            continue
        qual, stmt = _a27_ctx(call, mod.parent)
        seam = qual in NO_MOVE_SEAM or _a27_exempt(call, mod.parent)
        if canon:
            verdict = "seam" if seam else ("builder" if call in bnodes else "counted")
            out.append(A27Site(mod.name, call.lineno, stmt.lineno, qual, A27_CLASSES[canon], _a27_disc(call, canon), verdict))
        elif not seam and not (key[0] == "m" and f"Driver.{key[1]}" in NO_MOVE_SEAM):
            cls = "P" if "P" in found[key] else "S"
            out.append(A27Site(mod.name, call.lineno, stmt.lineno, qual, cls, f"builder:{key[1]}",
                               "builder" if call in bnodes else "counted"))
    return out


def _a27_returns_only(value, names: set) -> bool:
    """The return hands over the WHOLE result unchanged (`return r`, `return code, out`): every bound name, nothing else.
    A function that returns only `out` after deciding on `code` is a reader, not a wrapper."""
    if isinstance(value, ast.Name):
        return {value.id} == names
    return (isinstance(value, (ast.Tuple, ast.List)) and bool(value.elts)
            and all(isinstance(e, ast.Name) for e in value.elts) and {e.id for e in value.elts} == names)


def _a27_assigned_names(stmt) -> set | None:
    """The Names an Assign / AnnAssign binds; None when a target is anything else (an attribute, a subscript, a star)."""
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
    names: set = set()
    for target in targets:
        parts = target.elts if isinstance(target, (ast.Tuple, ast.List)) else [target]
        if not parts or not all(isinstance(p, ast.Name) for p in parts):
            return None
        names.update(p.id for p in parts)
    return names


def _a27_wrapper_of(stmt, parent: dict, names: set | None) -> str:
    """The name of the Driver member that returns this script run unchanged, else "" (a py-wrapper). A `return` hands the
    run over only INSIDE the assignment's window - after it and not past the first re-binding of a bound name (a re-binding
    in a branch closes the window too) - so a result overwritten before the return is not delegated (edge 2)."""
    fn = next((a for a in _a27_up(stmt, parent) if isinstance(a, A27_DEFS)), None)
    owner = parent.get(fn)
    if fn is None or not (isinstance(owner, ast.ClassDef) and A27_DRIVER_CLASS.match(owner.name)):
        return ""
    if names is None:
        return fn.name
    start, closed, _ = _a27_window(stmt, parent, names - {"_"})
    end = min(closed.values(), default=(1 << 60, 0))
    if any(isinstance(n, ast.Return) and start < (n.lineno, n.col_offset) <= end and _a27_returns_only(n.value, names)
           for n in _a27_own(fn)):
        return fn.name
    return ""


def _a27_bind_pos(name: ast.Name, parent: dict) -> tuple:
    """Where a re-binding takes effect: the END of its assignment (the value is read first), else its own position."""
    holder = parent.get(name)
    while isinstance(holder, (ast.Tuple, ast.List, ast.Starred)):
        holder = parent.get(holder)
    if isinstance(holder, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return holder.end_lineno, holder.end_col_offset
    return name.lineno, name.col_offset


def _a27_in_print(node: ast.AST, parent: dict) -> bool:
    return any(isinstance(a, ast.Call) and isinstance(a.func, ast.Name) and a.func.id == "print"
               for a in _a27_up(node, parent))


def _a27_window(stmt, parent: dict, live: set) -> tuple:
    """(start, closed, reads) of an assignment's window over the names `live`: where the statement ends, the first
    re-binding position of each name after it, and every later Load of one of them (line order)."""
    chain = list(_a27_up(stmt, parent))
    scope = next((a for a in chain if isinstance(a, A27_DEFS)), chain[-1] if chain else stmt)
    start = (stmt.end_lineno, stmt.end_col_offset)
    closed: dict = {}
    reads = []
    for node in ast.walk(scope):
        if isinstance(node, ast.Name) and node.id in live and (node.lineno, node.col_offset) > start:
            if isinstance(node.ctx, ast.Load):
                reads.append(node)
            else:
                pos = _a27_bind_pos(node, parent)
                closed[node.id] = min(closed.get(node.id, pos), pos)
    return start, closed, reads


def _a27_print_stmt(stmt: ast.AST) -> bool:
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name)
            and stmt.value.func.id == "print")


def _a27_print_branch(read: ast.AST, parent: dict) -> bool:
    """B3 (C1-7b, F9): the read stands in the TEST of an `if` whose every branch statement only prints (`if code: print(...)`,
    with or without an `else: print(...)`): the exit was looked at and nothing was done with it. A branch that also returns,
    raises, continues, assigns or calls anything else acts on the read, and so does an `elif` (its orelse is an `if`)."""
    child = read
    for up in _a27_up(read, parent):
        if isinstance(up, ast.stmt):
            return isinstance(up, ast.If) and child is up.test and all(_a27_print_stmt(s) for s in up.body + up.orelse)
        child = up
    return False


def _a27_window_read(stmt, parent: dict, names: set) -> bool:
    """Is some bound name (other than `_`) READ in the window: after the assignment, in line order, up to its first
    re-binding, outside every argument of print(...) and outside the test of a print-only `if` (B3)? A re-binding inside a
    branch closes the window too (errs toward flagging)."""
    _, closed, reads = _a27_window(stmt, parent, names - {"_"})
    return any((r.lineno, r.col_offset) <= closed.get(r.id, (1 << 60, 0)) and not _a27_in_print(r, parent)
               and not _a27_print_branch(r, parent) for r in reads)


def _a27_u_class(call: ast.Call, parent: dict) -> tuple:
    """How a script run stands: ("ok" | "delegated" | "wrapper" | "bad", wrapper name). The first rule that matches wins;
    every position not listed as controlled is uncontrolled (fail-closed)."""
    if any(k.arg == "check" and isinstance(k.value, ast.Constant) and k.value.value is True for k in call.keywords):
        return "ok", ""
    up = parent[call]
    if isinstance(up, ast.Lambda) and up.body is call:
        return "delegated", ""
    if isinstance(up, ast.Return) and up.value is call:
        name = _a27_wrapper_of(up, parent, None)
        return ("wrapper", name) if name else ("bad", "")
    if isinstance(up, (ast.Assign, ast.AnnAssign)) and up.value is call:
        names = _a27_assigned_names(up)
        if names is None:
            return "bad", ""
        name = _a27_wrapper_of(up, parent, names)
        if name:
            return "wrapper", name
        return ("ok" if _a27_window_read(up, parent, names) else "bad"), ""
    return "bad", ""


def _a27_u_disc(call: ast.Call) -> str:
    first = call.args[0] if call.args else None
    script = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value else "?"
    return f"py_stdout:{script}" if call.func.attr == "py_stdout" else script if call.func.attr == "py" else "?"


def _a27_u_sites(mods: list) -> tuple:
    """U: every `self.py` / `self.py_stdout` run, and every call of a py-wrapper (transitive), judged by `_a27_u_class`."""
    cands = []
    for mod in mods:
        if mod.driver:
            cands.extend((mod, n) for n in mod.nodes if isinstance(n, ast.Call) and _a27_callee(n)
                         and _a27_callee(n)[0] == "m" and isinstance(n.func, ast.Attribute))
    wrappers: set = set()
    verdicts: dict = {}
    while True:
        grown = set()
        for mod, call in cands:
            if call.func.attr in ("py", "py_stdout") or call.func.attr in wrappers:
                if call not in verdicts:
                    verdicts[call] = _a27_u_class(call, mod.parent)
                if verdicts[call][0] == "wrapper":
                    grown.add(verdicts[call][1])
        if grown <= wrappers:
            break
        wrappers |= grown
    out = []
    for mod, call in cands:
        if call not in verdicts or (call.func.attr not in ("py", "py_stdout") and call.func.attr not in wrappers):
            continue
        how = verdicts[call][0]
        if how == "ok":
            continue
        qual, stmt = _a27_ctx(call, mod.parent)
        out.append(A27Site(mod.name, call.lineno, stmt.lineno, qual, "U", _a27_u_disc(call),
                           "counted" if how == "bad" else "delegated"))
    return out, len(wrappers)


def _a27_references(mods: list, problems: list) -> int:
    """Seam integrity (I-seam) and I-one over the driver set. Returns the number of bare `self.py` hand-overs (B8)."""
    internal = {m.split(".", 1)[1] for m in NO_MOVE_SEAM} - NO_MOVE_ENTRIES
    bare = 0
    for mod in (m for m in mods if m.driver):
        for node in mod.nodes:
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
                if node.attr == "py" and not (isinstance(mod.parent.get(node), ast.Call) and mod.parent[node].func is node):
                    bare += 1
                if node.attr in internal or (node.attr == "conductor" and isinstance(node.ctx, ast.Load)):
                    _a27_reference(mod, node, problems, internal)
            elif isinstance(node, ast.Call) and _a27_callee(node) == ("m", "run_claude"):
                _a27_run_claude(mod, node, problems)
    return bare


def _a27_reference(mod: _A27Mod, node: ast.Attribute, problems: list, internal: set) -> None:
    qual = _a27_ctx(node, mod.parent)[0]
    where = f"{mod.name}:{node.lineno} {qual}"
    if node.attr in internal and qual not in NO_MOVE_SEAM:
        problems.append(f"A27 seam {where}: `Driver.{node.attr}` is the seam's own, not a door for another site: call "
                        "`no_move` (or `unread` / `funnel`) instead")
    elif node.attr == "conductor" and qual not in CONDUCTOR_SITES["call"]:
        problems.append(f"A27 I-one {where}: `self.conductor` is referenced outside {CONDUCTOR_SITES['call'][0]}, the one "
                        "call of the conductor: ask through `no_move`")


def _a27_run_claude(mod: _A27Mod, call: ast.Call, problems: list) -> None:
    kind = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == "kind"), None)
    qual = _a27_ctx(call, mod.parent)[0]
    where = f"{mod.name}:{call.lineno} {qual}"
    if not (isinstance(kind, ast.Constant) and isinstance(kind.value, str)):
        problems.append(f"A27 I-one {where}: A27 cannot tell whether this is a conductor call: pass the kind to "
                        "`run_claude` as a str literal")
    elif kind.value == "conductor" and qual not in CONDUCTOR_SITES["conductor"]:
        problems.append(f"A27 I-one {where}: `run_claude(\"conductor\")` outside {' and '.join(CONDUCTOR_SITES['conductor'])}: "
                        "the conductor is called through `no_move`; a new legitimate site is an edit of CONDUCTOR_SITES")


def _a27_door_table(text: str) -> tuple:
    """({comment line: reason}, comment-only lines) from the COMMENT tokens of the text the AST was parsed from: a
    door is `# remains: <reason>` at the very start of a comment (a string that spells it is a STRING token)."""
    doors, comments, code = {}, set(), set()
    skip = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            comments.add(tok.start[0])
            match = A27_DOOR.match(tok.string)
            if match:
                doors[tok.start[0]] = match.group(1).strip()
        elif tok.type not in skip:
            code.update(range(tok.start[0], tok.end[0] + 1))
    return doors, comments - code


def _a27_apply_doors(name: str, sites: list, doors: dict, comment_only: set, problems: list) -> list:
    """A site's door lines are exactly two: its statement's FIRST line, and the line above it when that line is
    comment-only. A door with no letter in its reason is a finding; a door covering no counted site is an
    orphan; one door over two or more counted sites covers none; of two doors the upper one wins."""
    valid = {line: reason for line, reason in doors.items() if any(c.isalpha() for c in reason)}
    for line in sorted(set(doors) - set(valid)):
        problems.append(f"A27 {name}:{line}: a door with no reason: `# remains:` needs a reason with at least one letter, "
                        "else the site counts")
    claims: dict = {}
    for i, site in enumerate(sites):
        if site.verdict == "counted":
            for line in (site.stmt_line - 1 if site.stmt_line - 1 in comment_only else 0, site.stmt_line):
                if line in valid:
                    claims.setdefault(line, []).append(i)
                    break
    out = list(sites)
    for line, hits in sorted(claims.items()):
        if len(hits) > 1:
            problems.append(f"A27 {name}:{line}: one door, {len(hits)} sites: split the statement so each site has its own")
        else:
            out[hits[0]] = out[hits[0]]._replace(verdict="door", reason=valid[line])
    for line in sorted(set(valid) - set(claims)):
        problems.append(f"A27 {name}:{line}: a `# remains:` door at {line} touches no counted site: a door stands on the first "
                        "line of the statement it covers or on the comment-only line directly above it")
    return out


def _a27_doors(mods: list, sites: list, problems: list) -> list:
    """Apply the doors file by file (the driver set, and any other file that holds a site)."""
    by_file: dict = {}
    for site in sites:
        by_file.setdefault(site.file, []).append(site)
    out = []
    for mod in mods:
        mine = by_file.pop(mod.name, [])
        if not (mod.driver or mine):
            continue
        try:
            doors, comment_only = _a27_door_table(mod.text)
        except (tokenize.TokenError, SyntaxError, ValueError) as exc:
            problems.append(f"A27 cannot scan {mod.name}: does not tokenize: {type(exc).__name__}: {exc}")
            doors, comment_only = {}, set()
        out.extend(_a27_apply_doors(mod.name, mine, doors, comment_only, problems))
    return out


def _a27_judge(sites: list, failed: set, problems: list) -> tuple:
    """The baseline against the census, key by key: a census above its row is [NEW], a row above its census is stale."""
    rows = dict(NO_MOVE_BASELINE)
    groups: dict = {}
    for at, site in enumerate(sites):
        if site.verdict == "counted":
            groups.setdefault((site.file, site.qual, site.cls, site.disc), []).append(at)
    news, judged = [], list(sites)
    for key, items in groups.items():
        for i, at in enumerate(sorted(items, key=lambda n: sites[n].line)):
            site = sites[at]
            if i < rows.get(key, 0):
                judged[at] = site._replace(verdict="baseline")
                continue
            judged[at] = site._replace(verdict="NEW")
            news.append(f"A27 [NEW] {site.file}:{site.line} {site.qual} {site.cls} {site.disc}: a state without a move outside "
                        "the seam; a state the driver has no move for goes through `Driver.no_move`. Three doors: route it "
                        "through `no_move`; for a script run pass `check=True` or read its exit code; or, if it must stay, "
                        "write `# remains: <reason>` on the statement's first line or on the comment-only line above it")
    stale = 0
    for key, count in sorted(rows.items()):
        if key[0] not in failed and len(groups.get(key, ())) < count:
            stale += 1
            problems.append(f"A27 stale row {key}: the baseline says {count}, the census finds {len(groups.get(key, ()))}: "
                            "shrink the row in this commit (renamed or moved? move the row to the new key)")
    total = sum(rows.values())
    if total != NO_MOVE_BASELINE_MAX:
        word = "stale cap: lower it" if NO_MOVE_BASELINE_MAX > total else "raise it only with a reviewed reason"
        problems.append(f"A27 NO_MOVE_BASELINE_MAX is {NO_MOVE_BASELINE_MAX} but the rows sum to {total} ({word}): "
                        "the cap must equal the sum")
    return judged, news, stale


def _a27_totals(sites: list, wrappers: int, baseline: int, stale: int) -> dict:
    make = [s for s in sites if s.cls in ("P", "S") and not s.disc.startswith("builder:")]
    calls = [s for s in sites if s.cls in ("P", "S") and s.disc.startswith("builder:")]
    uses = [s for s in sites if s.cls == "U"]
    count = lambda items, *verdicts: sum(1 for s in items if s.verdict in verdicts)  # noqa: E731
    return {
        "P-built": sum(1 for s in make if s.cls == "P" and s.verdict != "seam"),
        "S-built": sum(1 for s in make if s.cls == "S" and s.verdict != "seam"),
        "seam": count(make, "seam"), "builder-built": count(make, "builder"),
        "builder-calls": count(calls, *A27_BEFORE_DOORS, "counted"), "U": count(uses, *A27_BEFORE_DOORS, "counted"),
        "delegated": count(uses, "delegated"), "py-wrappers": wrappers, "doors": count(sites, "door"),
        "counted": count(sites, "baseline", "NEW", "counted"), "baseline": baseline,
        "new": count(sites, "NEW"), "stale": stale}


def a27_scan(plugin_root) -> A27Scan:
    """ONE scan: the site records (file, line, stmt_line, qualname, class, discriminator, verdict, door reason), the
    structural findings and one finding per [NEW] site. a27_findings and a27_census only format it (no second walk)."""
    scripts = Path(plugin_root) / "scripts"
    problems: list = []
    driver = {p.name for p in [scripts / DRIVER_ENTRY, *scripts.glob("driver_*.py")] if p.is_file()}
    empty = lambda: A27Scan([], problems, [], sorted(driver), _a27_totals([], 0, 0, 0), 0)  # noqa: E731
    if DRIVER_ENTRY not in driver:
        problems.append(f"A27: the driver is missing — scripts/{DRIVER_ENTRY} does not exist")
        return empty()
    failed: set = set()
    mods = _a27_load(scripts, driver, problems, failed)
    if DRIVER_ENTRY in failed:
        return empty()
    if not any(isinstance(n, ast.ClassDef) and A27_DRIVER_CLASS.match(n.name) for m in mods if m.driver for n in m.nodes):
        problems.append("A27: the driver defines no `Driver` class")
        return empty()
    funcs = _a27_functions(mods)
    found = _a27_builders(funcs)
    bnodes = _a27_builder_nodes(funcs, found)
    sites = [s for m in mods for s in _a27_ps_sites(m, found, bnodes)]
    u_sites, wrappers = _a27_u_sites(mods)
    bare = _a27_references(mods, problems)
    sites = _a27_doors(mods, sorted(sites + u_sites, key=lambda s: (s.file, s.line)), problems)
    sites, news, stale = _a27_judge(sites, failed, problems)
    totals = _a27_totals(sites, wrappers, sum(NO_MOVE_BASELINE.values()), stale)
    return A27Scan(sites, problems, news, sorted(driver), totals, bare)


def a27_findings(plugin_root, scan: A27Scan | None = None) -> list:
    scan = scan or a27_scan(plugin_root)
    return [*scan.problems, *scan.news]


def a27_census(plugin_root, scan: A27Scan | None = None) -> str:
    """The census as text: the header, the blind spots, one line per site, the structural findings, the totals line."""
    scan = scan or a27_scan(plugin_root)
    lines = [f"A27 no move outside the seam — census of {len(scan.files)} file(s): {', '.join(scan.files)}"]
    lines.extend(f"BLIND SPOT: {text}" for text in A27_BLIND)
    lines.append(f"BLIND SPOT: B8: the bare `self.py` hand-over to `stand_gaps` ({scan.bare_py} today) is not a call A27 sees")
    for s in sorted(scan.sites, key=lambda s: (s.file, s.line)):
        label = f"door: {s.reason}" if s.verdict == "door" else s.verdict
        lines.append(f"{s.file}:{s.line} {s.qual} {s.cls} {s.disc} [{label}]")
    lines.extend(f"FINDING: {p}" for p in scan.problems)
    lines.append("A27 totals: " + " ".join(f"{name} {scan.totals[name]}" for name in A27_TOTALS))
    return "\n".join(lines)


def a27_no_move() -> None:
    scan = a27_scan(PLUGIN_ROOT)
    print(a27_census(PLUGIN_ROOT, scan))
    report(A27_CHECK, a27_findings(PLUGIN_ROOT, scan))


def main() -> None:
    ap = argparse.ArgumentParser(description="Factory audit")
    only = ap.add_mutually_exclusive_group()
    only.add_argument("--agents", action="store_true",
                      help="run only the agents/*.md contract check (A19) against references/stages.json")
    only.add_argument("--no-move", action="store_true",
                      help="run only A27 (a state without a move outside the seam) and print its census")
    args = ap.parse_args()

    print(f"=== Factory audit {datetime.now():%Y-%m-%d %H:%M} ===")
    if args.no_move:
        a27_no_move()
    elif args.agents:
        a19_agents_contract()
    else:
        a1_hooks_liveness()
        a2_role_tools_parity()
        a2b_excess_write_right()
        a2c_role_not_controller()
        a3_a4_artifacts()
        a5_seal()
        a6_journal_format()
        a7_journal_completeness()
        a9_inject_map()
        a11_artifact_contract_sync()
        a12_skill_size()
        a13_deferred_decisions()
        a14_definition_drift()
        a15_estimation_loop()
        a16_registry_hygiene()
        a17_detector_rerun()
        a18_board_runs_row()
        a19_agents_contract()
        a20_portable_paths()
        a21_one_owner_per_fact()
        a22_role_start_load()
        a24_refusal_registry()
    print(f"=== Result: {'VIOLATIONS ' + str(len(FINDINGS)) if FINDINGS else 'clean'} ===")
    sys.exit(1 if FINDINGS else 0)


if __name__ == "__main__":
    main()
