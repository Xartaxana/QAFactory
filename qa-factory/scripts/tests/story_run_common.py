"""Shared scaffolding of the story-runner tests: the stub `claude`, the temp-project builders, the helpers
and constants every `test_story_run_*.py` file uses, and `run_scenarios` (the runner every file's `main` calls).

This is not a test itself (selftest runs `test_*.py`); `test_human_questions.py`, the `test_infra_failure_*.py` parts and `infra_failure_common.py`,
`test_package_generation.py` and `test_repair_route.py` import it as `T`. `harness` is imported before
anything from scripts/, so no test ever reaches a real `claude -p` (harness points STORY_RUN_CLAUDE at
no_claude.py unless a test names its own stub). What the stub proves and what each scenario proves is
written where the scenario is, in its own `test_story_run_*.py` file.
"""

import json
import os
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))


# What the plugin's own SessionStart hook leaves behind (B-014): one receipt per session naming the
# plugin root the hooks of that session ran from. `claude -p` is replaced by a stub, so no hook runs;
# the stub writes the receipt with the root it was told to load (`--plugin-dir`, the driver's own),
# which is exactly what a real session does. `control["receipt"]` bends it for a test: "none" writes
# nothing, a dict is the root entry written instead of the driver's own. No test-only bypass lives in
# the driver: it reads this file like any other.
RECEIPT = r'''
def write_receipt(session, control=None):
    import hashlib, json, os, sys
    from pathlib import Path
    argv = sys.argv[1:]
    plugin = argv[argv.index("--plugin-dir") + 1] if "--plugin-dir" in argv else ""
    project = os.environ.get("CLAUDE_PROJECT_DIR") or ""
    mode = (control or {}).get("receipt")
    if not (plugin and project and session) or mode == "none":
        return
    root = str(Path(plugin).resolve())
    try:
        version = json.loads((Path(root) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version", "")
    except Exception:
        version = ""
    roots = mode if isinstance(mode, list) else [dict(plugin_root=root, version=version, first_hook="SessionStart")]
    path = Path(project) / "qa-factory" / "state" / "host-receipts" / (
        "package-" + hashlib.sha256(session.encode("utf-8")).hexdigest()[:16] + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"session_id": session, "roots": roots, "observed_at": "stub"}), encoding="utf-8")
'''

STUB = RECEIPT + r'''
import json, os, re, subprocess, sys
from pathlib import Path
argv = sys.argv[1:]
control = json.loads(Path(os.environ["STUB_CONTROL"]).read_text(encoding="utf-8"))
log = Path(os.environ["STUB_LOG"])
def opt(name):
    return argv[argv.index(name) + 1] if name in argv else ""
resume, agent, sysfile = opt("--resume"), opt("--agent"), opt("--append-system-prompt-file")
# The driver writes the prompt as UTF-8 bytes; `sys.stdin.read()` would decode them with the machine's
# locale (cp1252 on a Windows shell without PYTHONUTF8), so a person's words in another script would
# reach this log as mojibake or fail to decode. Decoded explicitly, the stub sees what was sent.
prompt = sys.stdin.buffer.read().decode("utf-8")
role = agent.split(":")[-1]
kind = "resume" if resume else ("role" if agent else "conductor")
earlier = []
for line in (log.read_text(encoding="utf-8").splitlines() if log.exists() else []):
    try:       # a parallel scenario: another stub may be appending to this log right now; a torn last line is not a row yet
        earlier.append(json.loads(line))
    except ValueError:
        pass
# `index` below is read-then-append: two stubs started together can read the same length, so a LIST-valued `result` / `action` is not
# safe in a parallel scenario (the scenarios of test_story_run_s5_parallel.py use none).
index = len([e for e in earlier if e["kind"] == kind and e["role"] == role])
with log.open("a", encoding="utf-8") as h:
    h.write(json.dumps({"kind": kind, "role": role, "prompt": prompt, "resume": resume, "sysfile": sysfile,
                        "argv": argv, "cwd": os.getcwd()}) + "\n")
def pick(value):
    if isinstance(value, list):
        return value[min(index, len(value) - 1)]
    return value
# TR3-18 (spec t-1937 M5): per-call START and END marks and a BARRIER, never a sleep. A scenario that sets `control["marks"]` gets one
# row per event in `<STUB_LOG>.marks` (a file of its own: the call log above keeps its shape, so no older scenario counts a mark). A
# role spec may carry `barrier: {name, need, cap}` (the call waits until `need` distinct dispatches reached the barrier `name`) and
# `hold_until: {file, cap}` (the call waits until that file exists); `by_scope: {"TC-2": {...}}` overlays a spec on the calls whose
# prompt names that dispatch scope. EVERY wait has a cap (default 20 s) and a failure that NAMES the peer: the call answers
# `is_error`, exits 3 and the marks hold a `barrier_timeout` / `hold_timeout` row - the stub never deadlocks a run.
# `is_error: true` and `exit: <n>` on a role spec make the call fail the way the service does (a limit text, a non-zero exit).
import time
marks_path = Path(os.environ["STUB_LOG"] + ".marks")
dispatch_id = ""
def mark(event, **extra):
    if not control.get("marks"):
        return
    row = dict(event=event, kind=kind, role=role, dispatch=dispatch_id, t=time.time(), pid=os.getpid(), **extra)
    with marks_path.open("a", encoding="utf-8") as h:
        h.write(json.dumps(row) + "\n")
def marks_seen():
    rows = []
    if marks_path.exists():
        for line in marks_path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows
def wait_until(ready, cap):
    stop = time.monotonic() + cap
    while not ready():
        if time.monotonic() >= stop:
            return False
        time.sleep(0.05)
    return True
fail, broken = {}, ""
if kind == "role":
    task_dir = Path(re.search(r"Artifacts dir: (\S+)", prompt).group(1))
    dispatch = re.search(r"Dispatch: (\S+)\.", prompt).group(1)
    spec = control.get("roles", {}).get(role, {})
    scoped = re.search(r"Dispatch scope \(one digest line per item\): (.+)", prompt)
    scope_key = scoped.group(1).strip() if scoped else ""
    spec = dict(spec, **((spec.get("by_scope") or {}).get(scope_key) or {}))
    for needle, overlay in (spec.get("by_prompt") or {}).items():       # `by_prompt`: an overlay on the calls whose prompt holds the text
        if needle in prompt:
            spec = dict(spec, **overlay)
    dispatch_id, fail = dispatch, spec
    mark("start", scope=scope_key)
    barrier = spec.get("barrier")
    if barrier and not control.get("marks"):
        broken = "STUB BARRIER: a barrier needs control[\"marks\"] (the peers are told apart by their start marks)"
    elif barrier:
        name, need, cap = barrier["name"], int(barrier["need"]), float(barrier.get("cap", 20))
        mark("barrier_wait", barrier=name)
        def arrived():
            return sorted({r["dispatch"] for r in marks_seen() if r.get("event") == "barrier_wait" and r.get("barrier") == name})
        if not wait_until(lambda: len(arrived()) >= need, cap):
            broken = f"STUB BARRIER {name}: {dispatch} waited {cap} s for {need} calls, saw {arrived()}, missing {need - len(arrived())}"
            mark("barrier_timeout", barrier=name, seen=arrived())
    hold = spec.get("hold_until")
    if hold and not broken:
        if not wait_until(lambda: Path(hold["file"]).exists(), float(hold.get("cap", 20))):
            broken = f"STUB HOLD: {dispatch} waited {hold.get('cap', 20)} s for {hold['file']}, which never appeared"
            mark("hold_timeout", file=str(hold["file"]))
    for rel, content in (spec.get("files") or {}).items():
        path = task_dir / rel.replace("{dispatch}", dispatch)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    result, session = pick(spec.get("result", "")), "sess-" + dispatch
    if broken:
        result = broken
elif kind == "resume":
    result, session = pick(control.get("resume", {}).get("result", "")), resume
else:
    spec = control.get("conductor", {})
    # The driver writes the person's words to a file and names it in the prompt; a command of the
    # scenario carries `@WORDS_FILE@` where a conductor would pass that path as --words-file.
    named = re.search(r"The person's words are in (.+?); pass them as", prompt)
    words_path = named.group(1) if named else ""
    for cmd in spec.get("run") or []:
        subprocess.run([sys.executable, "-B"] + [str(c).replace("@WORDS_FILE@", words_path) for c in cmd],
                       capture_output=True)
    verdict = {"action": pick(spec.get("action", "continue")), "did": spec.get("did", "stub"),
               "question": spec.get("question", "")}
    if "options" in spec:                 # C1-1: the options a conductor answers `ask_person` / `stop` with (the seam reads them)
        verdict["options"] = spec["options"]
    for field in ("why_person", "checked"):   # RN1-9: the class a conductor question names and what it read (seam_control's default)
        if field in spec:
            verdict[field] = spec[field]
    result, session = (spec.get("text", "I looked.") + "\n" + json.dumps(verdict)), f"sess-conductor-{index + 1}"
write_receipt(session, control)
mark("end")
print(json.dumps({"type": "result", "subtype": "success", "is_error": bool(fail.get("is_error")) or bool(broken),
                  "session_id": session, "num_turns": 3, "total_cost_usd": 0.0123, "duration_ms": 1500, "result": result}))
sys.stdout.flush()
if broken:
    sys.exit(3)
if fail.get("exit"):
    sys.exit(int(fail["exit"]))
'''

GOOD_MANIFEST = {"ticket": "{task}", "acceptance_criteria": [], "implementation": {"source": "diff"}}

SCOUT_DIGEST = "qa-scout S1 {task} · ok\n{task} · found · the task itself\nwork/context-manifest.json"


def seed(task: str, parallel_windows: int | None = 1, dispatch: dict | None = None) -> tuple:
    """A project with S0 done and the controller initialized, the way test_story_step builds one.
    TR3-12: the project pins `dispatch.parallel_windows` to 1 so old scenarios keep their serial meaning; the key merges into
    a `dispatch` block the config already has, a key already set there wins, and `parallel_windows=None` leaves the key out."""
    root = harness.temp_project("qa-story-run-")
    harness.use_project(root)
    # These scenarios are about the driver's LOOP, and the stub role writes a digest without
    # filling a handover form. The form is required by default (a real role is told to fill it
    # in its prompt), so this project switches the requirement off exactly the way a story
    # already in flight under an older build does. `the_form_is_required_of_the_driver_too`
    # below is the scenario that does exercise it.
    config = root / "qa-factory" / "config.json"
    cfg = json.loads(config.read_text(encoding="utf-8"))
    cfg["handoffs"] = {"required": False}
    block = dict(cfg.get("dispatch")) if isinstance(cfg.get("dispatch"), dict) else {}
    block.pop("parallel_windows", None)               # the template's 3 is not a caller's choice
    block.update(dispatch or {})                      # the caller's other keys stay; a caller that sets the key wins
    if parallel_windows is not None:
        block.setdefault("parallel_windows", parallel_windows)
    cfg["dispatch"] = block
    # t-2147 C1 (F6 a): the template's `manual.walkers: 3` is not a caller's choice either; old S6 scenarios keep their serial meaning
    manual = dict(cfg.get("manual")) if isinstance(cfg.get("manual"), dict) else {}
    manual["walkers"] = 1
    cfg["manual"] = manual
    config.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    task_root = root / "qa-factory/artifacts" / task
    (task_root / "work").mkdir(parents=True)
    # A story that has just been checked against its ticket (B-364 R7): these scenarios resume stories that have no
    # snapshot, which the freshness trigger reads as "older" (an unknown age is not a fresh one) and would send to the
    # tracker on every resume. The stamp is what a `none` check leaves, so the driver's own look is simply not due.
    (task_root / "work" / "ticket-freshness.json").write_text(json.dumps(
        {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "result": "none"}), encoding="utf-8")
    (task_root / "pipeline.json").write_text(json.dumps(
        {"ticket": task, "size": "S", "environment": "local",
         "stages": {"S0": {"status": "pending"}}, "gates": {}, "halts": []}), encoding="utf-8")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    harness.run_script("stage_done.py", "--task", task, "--stage", "S0", "--status", "done",
                       "--digest", "preflight green", cwd=root, env=env)
    from controller import Controller
    Controller(task_root).apply("initialize", {"scope": [], "source_revision": "src-1",
                                               "known_paths": {"root": str(task_root), "project_root": str(root)},
                                               "idempotency_key": "init", "coverage_contract_version": 2,
                                               "plan_contract_mode": "new"})
    stub = root / "fake_claude.py"
    stub.write_text(STUB, encoding="utf-8")
    control = root / "stub-control.json"
    control.write_text("{}", encoding="utf-8")
    env.update(STORY_RUN_CLAUDE=str(stub), STUB_CONTROL=str(control), STUB_LOG=str(root / "stub-log.jsonl"))
    return root, task_root, env


_DIFF_WORLD_DIFF = ("diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@ -10,3 +10,3 @@ def a()\n ctx\n-old_a\n+new_a\n tail\n")
_DIFF_WORLD_REGISTER = ("# Register\n\n## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact |\n"
                        "|---|---|---|---|---|---|---|---|\n| R-1 | First thing | ac | - | yes | AC1 | diff:src/a.py:10 | access |\n\n"
                        "## Contradiction matrix\n")


def diff_world(task_root: Path) -> None:
    """Make a story a world whose `implementation_source` is `diff` WITH real bytes (G1-5, spec t-527 section 4 item 8): the word in
    `pipeline.json`, `work/impl-diff.txt`, a one-requirement register, the empty blast index, and the table of diff form that the
    skeleton writes with every row labelled (the fixture shape of test_grounding_table.py). A test that only needs the WORD keeps
    none of this: `seed` records no implementation source (`off_diff:absent`), which is the world an S3 acceptance passes in."""
    import grounding_table as GT
    import planning_contract as PC
    task_root = Path(task_root)
    work = task_root / "work"
    work.mkdir(parents=True, exist_ok=True)
    pipe_path = task_root / "pipeline.json"
    pipe = json.loads(pipe_path.read_text(encoding="utf-8"))
    pipe["implementation_source"] = "diff"
    pipe_path.write_text(json.dumps(pipe), encoding="utf-8")
    (work / "impl-diff.txt").write_bytes(_DIFF_WORLD_DIFF.encode("utf-8"))
    (work / "requirements-register.md").write_bytes(_DIFF_WORLD_REGISTER.encode("utf-8"))
    (work / GT.BLAST_FILE).write_bytes(json.dumps({"index": {"state": "built"}, "areas": []}).encode("utf-8"))
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(task_root.parent.parent.parent), PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-B", str(Path(GT.__file__)), "--skeleton", "--task", task_root.name],
                          capture_output=True, text=True, env=env, cwd=str(task_root.parent.parent.parent))
    assert done.returncode == 0, done.stderr
    doc, problem = PC.read_grounding(task_root)
    assert doc is not None, problem
    for row in doc.data["rows"]:
        row["label"], row["reason"] = "refactoring", "ok"
    for line in doc.data.get("requirements") or []:
        line["state"], line["where"] = "outside_diff", "src/b.py:1"
    GT.write_yaml(GT.table_path(task_root), doc.data)


def seam_option(token: str, move: str, says: str = "") -> dict:
    """One valid option of a conductor's `ask_person` / `stop` answer (the seam's options contract, C1-1)."""
    return {"token": token, "move": move, "says": says or f"the {token} option does its work",
            "factory": "nothing runs now", "person": "work of yours outside the factory: the thing named above",
            "story": {"unverified": "what is in the way stays unproven", "report": "listed as an open item",
                      "delivery": "waits"}}


def seam_control(question: str = "Which of these should happen? `retry` or `stop`?", tokens=(("retry", "person_does"), ("stop", "stop_here")),
                 action: str = "ask_person", **extra) -> dict:
    """A `conductor` control for `set_control` that answers with a question and valid options. RN1-9: it names a class and what it read
    by DEFAULT (`why_person="access"`, `checked="the refusal"`); a case that wants the refusal overrides it (`why_person=None`)."""
    return dict({"action": action, "question": question, "did": "looked", "why_person": "access", "checked": "the refusal",
                 "options": [seam_option(token, move) for token, move in tokens]}, **extra)


def set_control(root: Path, data: dict) -> None:
    (root / "stub-control.json").write_text(json.dumps(data), encoding="utf-8")


def accept_record(root, stage, dispatch=""):
    """X2-7: a stage that has an acceptor (`acceptance_by` in stages.json) closes over the acceptor's `accept` record; the fixtures that close
    S2-S4 in one move, and the S6 rigs that stand for an analyst's verdict, write that record the way `stage_done.py --acceptance` would (the
    real writer is proved in test_controller_stage_acceptance). The ONE writer of the record in the KEPT tests: `dispatch` is the `reviewed_dispatch`."""
    import contract
    entry = contract._stage_entry(stage)
    if not entry.get("acceptance_by"):
        return
    path = root / "pipeline.json"
    pipeline = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    pipeline.setdefault("acceptance", {})[stage] = [{
        "stage": stage, "role": entry["roles"][0], "acceptor": entry["acceptance_by"], "reviewed_dispatch": dispatch, "verdict": "accept",
        "failure_class": None, "quote": "", "witness_paths": [], "at": "t"}]
    path.write_text(json.dumps(pipeline), encoding="utf-8")


def awaits(value):
    """The open-work word of a `complete` that awaits a consumer's acceptance: `value.unresolved` of an `OpenWork`; a plain string, None or
    any object without that attribute comes back as itself. The ONE NORMALISER of the word: a site that must be strict reads the attribute itself, with a type check."""
    return getattr(value, "unresolved", value)


def stub_calls(root: Path) -> list:
    path = root / "stub-log.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def jsonl(path: Path) -> list:
    """The rows of a journal that are CALLS: a `launched` row (t-363 B2) is the START of a call and its end row follows it,
    so the tests that count a driver journal's calls through this helper do not count the launch rows."""
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    return [r for r in rows if not (isinstance(r, dict) and r.get("kind") == "launched")]


def eq(name: str, got, expected, detail: str = "") -> bool:
    return check(name, got == expected, f"expected {expected!r}, got {got!r}\n{detail}")


def run_driver(root: Path, env: dict, *args):
    return harness.run_script("story_run.py", "--project", str(root), *args, cwd=root, env=env)


def driver_for(root: Path, env: dict, task: str, **overrides):
    """An in-process Driver over the same temp project (for the loop tests that fake `where`).

    The Driver chdirs into the project (`story_run.Driver.__init__`, the factory runs from the project), so the
    caller's cwd is recorded first: `harness.cleanup(root)` goes back to it BEFORE it deletes the project, and
    `run_scenarios` checks after every scenario that the cwd still exists (C4-6)."""
    harness.remember_cwd()
    for key in ("STORY_RUN_CLAUDE", "STUB_CONTROL", "STUB_LOG"):
        os.environ[key] = env[key]
    import story_run
    ns = types.SimpleNamespace(task=task, answer=None, until="end", dry_run=False, model="sonnet",
                               plugin_dir=None, project=str(root), mr=None, branch=None, commit=None,
                               ungrounded=False, ticket_file=None, env=None, branch_suffix="", max_boundaries=10)
    for key, value in overrides.items():
        setattr(ns, key, value)
    return story_run.Driver(ns)


# --- S0 by code: one snapshot, and a door on every stop (t-017 D1: B-008, B-004) -------------------
FIXTURE_TICKET = (harness.PLUGIN_ROOT / "evals" / "fixtures" / "tickets" / "QA-1.md").read_text(encoding="utf-8")


# A file the ticket adapter reads without loss but whose `## Acceptance criteria` section holds
# no numbered item: the one problem check_ticket names is "acceptance criteria mentioned, none
# came through". It is what a snapshot that lost its criteria looks like.
INCOMPLETE_TICKET = (
    "---\nkey: QA-1\ntype: Story\nstatus: In Review\nparent: QA-EPIC-1 \"Inventory tagging\"\n---\n\n"
    "# Items can carry tags\n\nAs a warehouse operator I want tags.\n\n## Acceptance criteria\n\n"
    "## Comments\n\n- **po** (2026-09-10): a comment.\n")

# D-0050: a criteria heading with TEXT under it that the item reader takes nothing from (prose, no list): the lost read
# (the 15045 class) - the one shape at which S0 stops. `INCOMPLETE_TICKET` above (heading, empty section) is an empty
# template: S0 goes on with a line.
LOST_READ_TICKET = (
    "---\nkey: QA-1\ntype: Story\nstatus: In Review\nparent: QA-EPIC-1 \"Inventory tagging\"\n---\n\n"
    "# Items can carry tags\n\nAs a warehouse operator I want tags.\n\n## Acceptance criteria\n\n"
    "The operator can tag an item and filter the list by that tag.\n\n"
    "## Comments\n\n- **po** (2026-09-10): a comment.\n")


# The same file with a NEW problem on top of the first: the parent line is gone while the text
# still speaks of an epic.
INCOMPLETE_TICKET_2 = (INCOMPLETE_TICKET.replace("parent: QA-EPIC-1 \"Inventory tagging\"\n", "")
                       .replace("I want tags.", "I want tags; this story belongs to an epic."))

NOT_A_TICKET = "not one of the answers, but words the person typed"


# A person's answer in another script, built from code points so that the package stays English
# (FR-30): "go on without a stand" in Russian.
OTHER_SCRIPT = "".join(chr(c) for c in (0x434, 0x430, 0x43B, 0x435, 0x435, 0x20, 0x431, 0x435, 0x437, 0x20,
                                        0x441, 0x442, 0x435, 0x43D, 0x434, 0x430))

BOM = chr(0xFEFF)

CUT = chr(0x2026)

AGENT_STUB = RECEIPT + r'''
import json, os, sys
from pathlib import Path
Path(os.environ["STUB_LOG"]).open("a", encoding="utf-8").write(json.dumps({"kind": "agent", "argv": sys.argv[1:]}) + "\n")
sys.stdin.buffer.read().decode("utf-8")
write_receipt("sess-ticket")
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "session_id": "sess-ticket",
                  "num_turns": 1, "total_cost_usd": 0.0, "duration_ms": 1, "result": "I could not find that issue."}))
'''


def s0_project(task: str = "QA-1", *, git: bool = True, ticket: str = FIXTURE_TICKET, config: dict | None = None):
    """A FRESH project for S0 by code: a file ticket adapter over `tickets/<task>.md`, a git
    working tree (readiness needs one), and `claude` replaced by the stub - so nothing here can
    reach a model, and a stub log with a line in it is a conductor call that should not have
    been made."""
    root = harness.temp_project("qa-story-run-s0-")
    if git:
        subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    tickets = root / "tickets"
    tickets.mkdir()
    (tickets / f"{task}.md").write_text(ticket, encoding="utf-8")
    cfg_path = root / "qa-factory" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["adapters"] = {"ticket": {"kind": "file", "path": str(tickets)}}
    cfg.update(config or {})
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    stub = root / "fake_claude.py"
    stub.write_text(STUB, encoding="utf-8")
    (root / "stub-control.json").write_text("{}", encoding="utf-8")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), STORY_RUN_CLAUDE=str(stub),
               STUB_CONTROL=str(root / "stub-control.json"), STUB_LOG=str(root / "stub-log.jsonl"))
    return root, root / "qa-factory" / "artifacts" / task, env


def s0_run(root: Path, env: dict, task: str, *args):
    """One driver process, stopped after S0: `--max-boundaries 0` runs no stage after it."""
    return run_driver(root, env, "--task", task, "--max-boundaries", "0", *args)


def s0_answer(root: Path, env: dict, task: str, words: str, *args):
    """The person's answer, as a file - written as bytes so that a BOM or a lone `\\u` stays as given."""
    path = root / "answer.md"
    path.write_bytes(words.encode("utf-8"))
    return s0_run(root, env, task, "--answer", str(path), *args)


def s0_state(task_root: Path) -> dict:
    path = task_root / "state" / "driver-state.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def s0_question(task_root: Path) -> str:
    return (task_root / "state" / "driver-question.md").read_text(encoding="utf-8")


def s0_pipeline(task_root: Path) -> dict:
    return json.loads((task_root / "pipeline.json").read_text(encoding="utf-8"))


def s0_findings(root: Path) -> str:
    path = root / "qa-factory" / "factory-backlog.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def s0_journal(root: Path) -> list:
    return jsonl(root / "qa-factory" / "records" / "journal.jsonl")


def rules_broken(text: str) -> list:
    import human_text
    return [p["rule"] for p in human_text.problems(text)]


def check_not_in_text(name: str, needles, text: str) -> bool:
    return check(name, not any(needle in text for needle in needles), f"one of {needles!r} is in {text!r}")


# --- the stand: S0 records it, S5/S6 ask once (t-017 D2: B-005, owner decision D-0014) ----------------
D2_ENVIRONMENT = {"env_file": "qa.env", "base_url_key": "QA_BASE_URL", "health_path": "/health"}

D2_DEAD = "http://127.0.0.1:9"        # the discard port: nothing listens there, so the probe gets no answer

D2_ASKED_ONCE = "stand not confirmed"


def d2_alive_server():
    """A stand that answers: (server, its url). The caller shuts the server down."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    class Alive(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Alive)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def d2_stand_at(root: Path, url: str) -> None:
    """Where the stand is, as the project's env file says: rewriting it is bringing the stand up or down."""
    (root / "qa.env").write_text(f"QA_BASE_URL={url}\n", encoding="utf-8")


def human_broken(text: str) -> list:
    """The rules a text breaks once it has the answer block `ask()` puts under every question."""
    import human_text
    tail = "\n---\nAnswer: write your words to a file and run\n  python story_run.py --task QA-1 --answer <file>\n"
    return [p["rule"] for p in human_text.problems(text + tail)]


def d2_seed(task: str = "QA-9", *, environment="Local", pending=True, stands=("Local", "Staging"), url=D2_DEAD):
    """A seeded project (S0 done, controller initialised) with stands recorded and the stand fact set
    the way S0 writes it: `environment` and `environment_pending`. `url` is where the stand is."""
    root, task_root, env = seed(task)
    config = root / "qa-factory" / "config.json"
    cfg = json.loads(config.read_text(encoding="utf-8"))
    cfg["environments"] = [{"name": name} for name in stands]
    cfg["environment"] = dict(D2_ENVIRONMENT)
    config.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    d2_stand_at(root, url)
    d2_pipeline(task_root, environment=environment, environment_pending=pending)
    return root, task_root, env


def d2_pipeline(task_root: Path, **facts) -> None:
    path = task_root / "pipeline.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(facts)
    path.write_text(json.dumps(data), encoding="utf-8")


def d2_driver(root: Path, env: dict, task: str, *, s5=("TC-1",), auto=("TC-1",), manual=(), **overrides):
    """An in-process driver whose stage scopes are fixed and whose roles are recorded, not run:
    (driver, started roles, `story_step` calls, `env_probe` calls). What is under test is the
    order - the stand is asked BEFORE a role starts - so a role that starts is a list entry."""
    driver = driver_for(root, env, task, max_boundaries=1, **overrides)   # one boundary, then the loop pauses

    def scope(stage, kind=""):
        if stage == "S5":
            return {"scope": list(s5), "windows": [{"scope": list(s5), "accepted_by": {}}] if s5 else []}
        return {"scope": list(auto if kind == "automation" else manual)}
    driver.stage_scope = scope
    started, steps, probes = [], [], []

    def fake_role(stage, role, **kwargs):
        started.append((stage, role))
        return "", None
    driver.run_role = fake_role
    driver.run_manual_block = lambda cases: started.append(("S6", "manual"))
    real_step, real_py = driver.step, driver.py

    def spy_step(*args):
        steps.append(args)
        return real_step(*args)

    def spy_py(script, *args, **kwargs):
        if script == "env_probe.py":
            probes.append(args)
        return real_py(script, *args, **kwargs)
    driver.step, driver.py = spy_step, spy_py
    return driver, started, steps, probes


def d2_enter(driver, stage: str) -> int:
    """One entry into a stage the way the loop makes it: `where` says prepare_stage, run() acts on it."""
    driver.where = lambda: {"action": "prepare_stage", "stage": stage, "revision": 1}
    return driver.run()


def d2_answer(root: Path, words: str) -> str:
    path = root / "answer.md"
    path.write_bytes(words.encode("utf-8"))
    return str(path)


def d2_conductor_calls(root: Path) -> list:
    return [c for c in stub_calls(root) if c["kind"] == "conductor"]


def d2_waiver(task: str, stage: str, words: str) -> list:
    """The conductor's move as the stub runs it: the person's word recorded with waiver.py."""
    flag = "--" + "stage"          # spelled apart: a guard matches the literal in a shell command
    return [str(harness.SCRIPTS / "waiver.py"), "--task", task, flag, stage, "--block", D2_ASKED_ONCE, "--decision", words]


# --- D3 (t-017): an experiment that leaves no trace (B-003) and the delivery mark (delta 8b) --------
D3_JIRA = {"external_writes": {"bugs": "jira", "cases": "markdown",
                               "channels": {"jira": {"method": "agent", "invoke": "jira-assistant"}}}}

D3_WARNING = "this run is an experiment: nothing leaves the project — no merge request, no tracker write; bugs stay as files"

D3_PHRASE = "verify the branch, commits and merge request that exist and reuse them — create nothing twice."

D3_MR = "https://githost.example.invalid/g/a/-/merge_requests/1"


def d3_receipt(root: Path) -> Path:
    """Where the tracker-write probe leaves its answer: the file S0's readiness call writes and a
    `--no-trace` run must neither write nor touch."""
    import runtime_paths          # the receipt is machine-local (state/): the layout's own `state_file`, as `tracker_write.receipt_path`
    return runtime_paths.state_file(root, "integrations", "tracker-write.json")


def d3_config(root: Path, extra: dict) -> None:
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.update(extra)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def d3_s8_done(task_root: Path) -> None:
    """The story a delivery question comes from: S8 is done (gate B decided) - the record the
    `take_answer` branch for a stop passed before the answer reads."""
    path = task_root / "pipeline.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("stages", {})["S8"] = {"status": "done"}
    path.write_text(json.dumps(data), encoding="utf-8")


def d3_loop(driver) -> None:
    """The loop of a story with gate B decided and S8 done: one `closed` action that runs S9's
    FIRST step - the delivery - and then the end of the test. The rest of S9 (the retro) is not
    what is under test, so the stage is its first step."""
    seen: list = []

    def where():
        seen.append(1)
        if len(seen) == 1:
            return {"action": "closed", "closed_at": "legacy", "revision": 9, "stage": "S9",
                    "reason": "gate B is decided and S8 is done", "retro_pending": True}
        return {"action": "stop", "reason": "end of test"}
    driver.where = where
    driver.stage_S9 = driver.after_gate_B


def d3_delivery_ends(root: Path, env: dict, task: str, control: dict, words: str = ""):
    """One delivery that asks: the first driver is run against `control` (the conductor's verdict);
    when `words` is given, S8 is marked done and a second driver takes them as the answer. Returns
    (the first exit code, the second's or None, the second driver)."""
    set_control(root, {"conductor": control})
    driver = driver_for(root, env, task)
    d3_loop(driver)
    first = driver.run()
    if not words:
        return first, None, driver
    d3_s8_done(root / "qa-factory" / "artifacts" / task)
    driver = driver_for(root, env, task, answer=d2_answer(root, words))
    d3_loop(driver)
    return first, driver.run(), driver


# --- S6 decides freshness in code (t-043 Dispatch D: D1 the branch, D2 the texts) -----------------------
D1_SAME = "instance bytes changed since the last run"


def d1_answer(states: dict, observed: bool = True, **extra) -> dict:
    """What `execution_request.fresh_evidence` answers: `states` is {instance: (state, outcome, why)}."""
    return dict({"instances": {i: {"state": s, "outcome": o, "job_id": ("job-" + i) if s == "result" else "", "why": w}
                               for i, (s, o, w) in states.items()}, "observed": observed}, **extra)


class D1Evidence:
    """`execution_request.fresh_evidence` replaced for a block: `answer` is what it returns (or the
    exception it raises) and `calls` says how often the driver asked, and with what."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    @property
    def asked(self) -> list:
        """The cases of each ask - short enough to read in a failure line (`calls` also carries the config)."""
        return [cases for cases, _kwargs in self.calls]

    def __enter__(self):
        import execution_request
        self.module, self.saved = execution_request, execution_request.fresh_evidence

        def fake(project_root, task, cases, **kwargs):
            self.calls.append((list(cases), kwargs))
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer
        execution_request.fresh_evidence = fake
        return self

    def __exit__(self, *_exc):
        self.module.fresh_evidence = self.saved


def d1_driver(root: Path, env: dict, task: str, *, auto=("TC-1", "TC-2"), manual=(), accepted_auto=False):
    """An in-process driver at S6 whose roles are recorded (with their arguments), whose code-only receipt
    and `stage_done` are recorded as moves, and whose `finalize_task.py` really runs.
    (driver, dispatched roles, moves, started manual blocks)."""
    driver, started, _steps, _probes = d2_driver(root, env, task, auto=auto, manual=manual)
    launched, moves = [], []

    def run_role(stage, role, **kwargs):
        launched.append(dict(kwargs, stage=stage, role=role))
        return "", None
    driver.run_role = run_role
    driver.code_only = lambda stage, reason, evidence: moves.append(("code_only", stage, reason, list(evidence)))
    spied_py = driver.py

    def py(script, *args, **kwargs):
        if script == "stage_done.py":
            moves.append(("stage_done", " ".join(str(a) for a in args)))
            return 0, ""
        if script == "finalize_task.py":
            moves.append(("finalize", str(args[0])))
        return spied_py(script, *args, **kwargs)
    driver.py = py
    if accepted_auto:
        driver.controller_state = lambda: {"dispatches": {"S6-qa-runner-1": {
            "stage": "S6", "status": "accepted", "execution_kind": "automation"}}}
    return driver, launched, moves, started


def d1_write_blocks(task_root: Path) -> None:
    """Two S5 run blocks (test_a green, test_b red) and the manifest that joins them - what an S5 window leaves."""
    work = task_root / "work"
    (work / "run-blocks").mkdir(parents=True, exist_ok=True)
    (work / "automation-manifest.json").write_text(json.dumps({"tests": [
        {"instance_id": "test_a", "case": "TC-1", "covers": ["TC-1"], "test": "test_a", "file": "tests/t.py", "status": "green"},
        {"instance_id": "test_b", "case": "TC-2", "covers": ["TC-2"], "test": "test_b", "file": "tests/t.py", "status": "red"}],
        "unresolved": []}), encoding="utf-8")
    for n, (instance, status) in enumerate([("test_a", "passed"), ("test_b", "failed")], 1):
        (work / "run-blocks" / f"b{n}.json").write_text(json.dumps({
            "block_id": f"b{n}", "attempt_id": f"a{n}", "dispatch_id": "S5-qa-automator-1",
            "attempt_started_at": f"2026-09-30T00:0{n}:00+00:00", "execution_status": status,
            "results": [{"instance_id": instance, "case": f"TC-{n}", "status": status}]}), encoding="utf-8")


def d1_extras(launched: list) -> str:
    return "\n".join(str(line) for entry in launched for line in entry.get("extra") or [])


def run_scenarios(side_by_side: list, in_process: list) -> None:
    """Run one file's scenarios: those that only start driver processes side by side (their waiting is
    the child processes' own, and nothing here measures time); then, once every one of them is
    finished, those that build a Driver in this process, one after another. Never together: a Driver
    changes the working directory, and some of them redirect stdout, which is process-wide - a pool
    thread's FAIL line printed meanwhile would be swallowed (FR-31). Nothing is caught here: a scenario
    that raises fails its file (`future.result()` re-raises what a pool thread raised). An empty
    `side_by_side` starts no pool; an empty `in_process` is legal.

    THE DRIVER GOLDEN (t-301 N0, `driver_golden.py`): when `DRIVER_GOLDEN_SINK` is set, each scenario runs under the
    recorder's per-scenario tag, so that the events of its thread are filed under its name (a pool thread of the
    side-by-side phase included). Without the variable nothing here changes: `tagged` returns the scenario itself.
    The variable set while the recorder is NOT loaded in this process is an error, never a silent untagged run."""
    from concurrent.futures import ThreadPoolExecutor
    recorder = None
    if os.environ.get("DRIVER_GOLDEN_SINK"):
        recorder = sys.modules.get("driver_trace")
        if recorder is None or getattr(recorder, "RT", None) is None:
            raise RuntimeError("DRIVER_GOLDEN_SINK is set but the golden's recorder is not loaded in this process: "
                               "run the file through `driver_golden.py` (it puts golden_sitecustomize on PYTHONPATH)")

    def tagged(scenario):
        if recorder is None:
            return scenario

        def run():
            with recorder.scenario(scenario.__name__):
                return scenario()
        return run

    if side_by_side:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for future in [pool.submit(tagged(scenario)) for scenario in side_by_side]:
                future.result()
        harness.guard_cwd("the side-by-side scenarios")
    for scenario in in_process:
        tagged(scenario)()
        harness.guard_cwd(scenario.__name__)       # C4-6: a scenario that left a deleted cwd is named here, not by its successor
