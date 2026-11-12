"""references/stages.json — the single table B2 makes inject_context.py, stage_guard.py and
exit_gate.py read instead of hardcoding role names. This file checks:

1. every stage's role(s) exist as agents/<role>.md;
2. every input/output name (after stripping a `project:` prefix) is a name
   references/artifact-contract.md actually documents — not an invented filename nobody
   reads or writes;
3. gate A sits after S3 and gate B sits after S8;
4. exit_gate.py's SubagentStop check denies a handoff missing a stage's `required_outputs`
   and allows it once they exist (tmp project, tmp artifacts dir, run as a subprocess so the
   real hook entry point is exercised, not just the helper functions);
5. stage_guard.py rule 1 denies dispatching S3's role (qa-test-strategist) while S2 is not
   done in pipeline.json — reusing harness.py's temp_project/run_script plumbing.
"""
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    PLUGIN_ROOT, SCRIPTS, check, check_eq, cleanup, finish, temp_project, use_project,
)

sys.path.insert(0, str(SCRIPTS))
import stage_guard as SG  # noqa: E402

REFS = PLUGIN_ROOT / "references"
AGENTS_DIR = PLUGIN_ROOT / "agents"


def load_stages() -> dict:
    return json.loads((REFS / "stages.json").read_text(encoding="utf-8"))


# --- part 1/2/3: stages.json against agents/ and artifact-contract.md ----------------------

def known_artifact_tokens() -> set:
    """The exact file/dir tokens listed in artifact-contract.md's "Where artifacts live"
    tree — the one place every artifact name is enumerated. Placeholders (<project>,
    <TICKET>) are dropped; everything else (config.json, test-cases/<area>/TC-NNN.md,
    strategy/*.md, evidence/, ...) is kept verbatim."""
    text = (REFS / "artifact-contract.md").read_text(encoding="utf-8")
    m = re.search(r"## Where artifacts live\s*\n\s*```\n(.*?)\n```", text, re.DOTALL)
    if not m:
        return set()
    placeholder = re.compile(r"^<[^>]+>/?$")  # a bare <project>/<TICKET> segment, not a real path
    tokens = set()
    for line in m.group(1).splitlines():
        for tok in line.split():
            if placeholder.match(tok):
                continue
            tokens.add(tok)
    return tokens


def in_contract(entry: str, known: set) -> bool:
    """entry is a stages.json inputs/outputs item, e.g. 'context-manifest.json',
    'test-cases/', or 'project:strategy/test-strategy.md'."""
    name = entry[len("project:"):] if entry.startswith("project:") else entry
    # `work/` is a location inside the story folder, not part of an artifact's name — the
    # contract tree shows the nesting by indentation, so match on the name itself.
    if name.startswith("work/"):
        name = name[len("work/"):]
    if name in known:
        return True
    if name.endswith("/"):
        return any(k == name or k.startswith(name) for k in known)
    for k in known:
        if "*" in k and fnmatch.fnmatch(name, k):
            return True
        if "/" in k and "/" in name and k.split("/", 1)[0] == name.split("/", 1)[0]:
            return True
    return False


def part_role_and_contract() -> None:
    model = load_stages()
    known = known_artifact_tokens()
    check("artifact-contract.md's tree yields a non-empty token set", len(known) > 0, str(known))

    for stage in model["stages"]:
        sid = stage["id"]
        roles = stage.get("roles") or ([stage["role"]] if stage.get("role") else [])
        for role in roles:
            check(f"{sid}: role file agents/{role}.md exists", (AGENTS_DIR / f"{role}.md").exists())

        for direction, names in (("inputs", stage.get("inputs") or []),
                                  ("outputs", stage.get("outputs") or [])):
            for name in names:
                check(f"{sid} {direction}: '{name}' is a name artifact-contract.md documents",
                      in_contract(name, known), f"known tokens sample: {sorted(known)[:8]}...")

        required = stage.get("required_outputs") or []
        outputs = stage.get("outputs") or []
        check(f"{sid}: required_outputs is a subset of outputs",
              all(r in outputs for r in required), f"required={required} outputs={outputs}")

    witness = model.get("witness") or {}
    stage_roles = {r for st in model["stages"] for r in
                   (st.get("roles") or ([st["role"]] if st.get("role") else []))}
    check_eq("witness map covers exactly the roles named in stages.json",
             set(witness), stage_roles)
    for role, name in witness.items():
        check(f"witness[{role}] = '{name}' is a name artifact-contract.md documents",
              in_contract(name, known))


def part_gates() -> None:
    model = load_stages()
    check_eq("gate A sits after S4", model["gates"]["A"]["after"], "S4")
    check_eq("gate B sits after S8", model["gates"]["B"]["after"], "S8")


# --- part 4: exit_gate.py denies/allows on required_outputs --------------------------------

def env_for(root: Path) -> dict:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    return env


def write_pipeline(art: Path, running_stage: str) -> None:
    data = {"ticket": "QA-1", "stages": {running_stage: {"status": "running"}}, "gates": {}}
    (art / "pipeline.json").write_text(json.dumps(data), encoding="utf-8")


def run_subagent_stop(role: str, root: Path) -> subprocess.CompletedProcess:
    event = {"hook_event_name": "SubagentStop", "session_id": "s-test-stages", "agent_type": role}
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "exit_gate.py")],
        input=json.dumps(event), capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=str(root), env=env_for(root),
    )


def part_exit_gate_required_outputs() -> None:
    root = temp_project("qa-factory-stages-exitgate-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        art.mkdir(parents=True)
        write_pipeline(art, "S1")  # qa-scout's stage, required_outputs = [context-manifest.json]

        p = run_subagent_stop("qa-scout", root)
        check("exit_gate denies SubagentStop when a required output is missing",
              p.returncode == 2, f"exit {p.returncode} | {(p.stdout + p.stderr)[-400:]}")

        # A minimal but SCHEMA-VALID manifest: collect_errors() re-validates every JSON
        # artifact on disk (not just the one required for this handoff), so a bare "{}"
        # would fail on context-manifest.json's own required keys before the
        # required-outputs check is even reached.
        (art / "work").mkdir(parents=True, exist_ok=True)
        (art / "work" / "context-manifest.json").write_text(
            json.dumps({"ticket": "QA-1", "acceptance_criteria": [], "implementation": {}}),
            encoding="utf-8")
        (art / "work" / "context-bundle.json").write_text(
            json.dumps({"schema_version": 1, "task_id": "QA-1", "grounding_complete": True}),
            encoding="utf-8")
        p = run_subagent_stop("qa-scout", root)
        check("exit_gate allows SubagentStop once the required output exists",
              p.returncode == 0, f"exit {p.returncode} | {(p.stdout + p.stderr)[-400:]}")

        # A foreign / non-factory agent is never blocked by this mechanism.
        p = run_subagent_stop("general-purpose", root)
        check("exit_gate does not block an agent stages.json does not know",
              p.returncode == 0, f"exit {p.returncode} | {(p.stdout + p.stderr)[-400:]}")
    finally:
        cleanup(root)


# --- part 5: stage_guard rule 1 ---------------------------------------------------------------

def part_stage_guard_rule1() -> None:
    root = temp_project("qa-factory-stages-guard-")
    try:
        art = root / "qa-factory" / "artifacts" / "QA-1"
        art.mkdir(parents=True)
        model = load_stages()
        stages = {s["id"]: {"status": "done" if s["id"] in ("S0", "S1") else "pending"}
                  for s in model["stages"]}
        pipeline = {"ticket": "QA-1", "stages": stages, "gates": {}}
        (art / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")

        use_project(root)  # points hooklib.project_root() at this temp project, in-process

        event = {"tool_name": "Task", "tool_input": {"subagent_type": "qa-test-strategist", "prompt": "QA-1"}}
        rc = SG.check(event)
        check_eq("stage_guard rule 1 denies S3's role (qa-test-strategist) while S2 is not done",
                 rc, SG.DENY)

        stages["S2"]["status"] = "done"
        (art / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        rc = SG.check(event)
        check_eq("stage_guard rule 1 allows it once S2 is done", rc, SG.ALLOW)
    finally:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        import hooklib
        hooklib._PROJECT_ROOT_CACHE = None
        cleanup(root)


def part_rework_mode() -> None:
    """`rework_mode` (SC1-1): every stage carries it, `contract.rework_mode` is its one reader. KILLS: a stage without the key
    or with another word; S3 not `fresh`; S5 not `resume`; a missing key read as `resume`; an unknown word read as a mode;
    a list root / `stages` not a list / a row not an object raising or read as a mode; `rework_mode` back to its own JSON reader."""
    import tempfile
    import contract
    model = load_stages()
    for stage in model["stages"]:
        check(f"{stage['id']}: rework_mode is one of {contract.REWORK_MODES}", stage.get("rework_mode") in contract.REWORK_MODES,
              str(stage.get("rework_mode")))
    check_eq("S3 reworks fresh (a new agent with the findings)", contract.rework_mode("S3"), "fresh")
    check_eq("S5 reworks by resume (SendMessage with the delta)", contract.rework_mode("S5"), "resume")
    check_eq("a stage the table does not name reads the default, fresh", contract.rework_mode("S99"), "fresh")
    with tempfile.TemporaryDirectory(prefix="qa-rework-mode-") as folder:
        table = Path(folder) / "stages.json"
        table.write_text(json.dumps({"stages": [{"id": "S3"}, {"id": "S4", "rework_mode": "resume"},
                                                {"id": "S5", "rework_mode": "resum"}]}), encoding="utf-8")
        check_eq("a stage with no rework_mode key reads fresh", contract.rework_mode("S3", table), "fresh")
        check_eq("a stage that says resume reads resume", contract.rework_mode("S4", table), "resume")
        try:
            contract.rework_mode("S5", table)
            refused = ""
        except ValueError as exc:
            refused = str(exc)
        check("an unknown word refuses at read, saying which words are expected (FR-1)",
              "rework_mode 'resum'" in refused and "fresh, resume" in refused, refused)
        check_eq("a table that cannot be read reads the default", contract.rework_mode("S3", Path(folder) / "none.json"), "fresh")
        # a malformed table is `fresh` and never raises (P1); `stage_roles` reads the same table through the same reader
        bad = Path(folder) / "bad.json"
        shapes = {"a list root": [{"id": "S4", "rework_mode": "resume"}], "stages is a number": {"stages": 5},
                  "stages is an object": {"stages": {"id": "S4", "rework_mode": "resume"}},
                  "a row is a string": {"stages": ["S4"]}, "a row is a list": {"stages": [["S4", "resume"]]},
                  "a string root": "S4", "a null root": None}
        for name, shape in shapes.items():
            bad.write_text(json.dumps(shape), encoding="utf-8")
            try:
                got = contract.rework_mode("S4", bad)
            except Exception as exc:  # noqa: BLE001 - the check is that nothing is raised
                got = f"{type(exc).__name__}: {exc}"
            check_eq(f"{name}: reads the default, fresh, and raises nothing", got, "fresh")
        bad.write_text("{not json", encoding="utf-8")
        check_eq("a file that is not JSON reads the default", contract.rework_mode("S4", bad), "fresh")
        check_eq("the one reader returns the stage's row", contract._stage_entry("S3", table), {"id": "S3"})
        check_eq("a malformed table has no stage entry (the one reader of stages.json)", contract._stage_entry("S4", bad), {})


def main() -> None:
    part_role_and_contract()
    part_rework_mode()
    part_gates()
    part_exit_gate_required_outputs()
    part_stage_guard_rule1()
    finish("test_stages")


if __name__ == "__main__":
    main()
