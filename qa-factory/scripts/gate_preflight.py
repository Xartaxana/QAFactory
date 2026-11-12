"""The gate rehearsal: everything that could stop the story AFTER an approval, checked BEFORE it.

The owner's rule of 21.09.2026: the factory must not show a person gate A if, once they have
approved, it cannot go on because it lacks something. Every check belongs before the person is
addressed.

TP1-15045 is the story that earned it. After the person typed "approve, keep all automate,
accept gaps" the factory stopped four more times, each time for a reason it already had on
disk: the decision would not record (design reviews were bound through the wrong field), the
stage guard would not let S5 start (two spellings of one gate field), the working tree was
dirty and nobody had chosen a branch, and four exact replacements the critic had written were
never applied. Five facts, all computable at the S4 exit; all found one by one, after the
approval, across three restarts.

  gate_preflight.py --task TP1-15045 --gate A
  gate_preflight.py --task TP1-15045 --gate A --text
  controller.py --task-root <TASK_ROOT> --operation gate-preflight --gate A

Read-only as to the STORY. It records the gate decision nowhere, dispatches nobody and records
nothing about the story: a rehearsal that moved the story would be a second way to run it. It does
write two machine-local state files of its own (B-416 corrects the old "changes no state file"): the
proofs of a test command's report (`qa-factory/state/reporter-rehearsals.json`) and the report a probe
run wrote that the code could not read (`qa-factory/state/reporter-unread/<profile>/`, kept for the
conductor's helper, `report_adapt.py`).

Every finding carries a class, and the class says whose problem it is:

  factory_fixable  the factory repairs it by its own code or one role rework, BEFORE the gate.
                   The person never sees it; the gate waits (`stage_done.py` for S4 and S8
                   refuses to close the stage while one is open).
  person_decides   a choice only a person makes — a dirty tree, a branch, a gap in the stand,
                   cases the critic never read. It goes INTO the gate packet as a question, so
                   there is one stop and one answer.
  factory_defect   a refusal the factory cannot repair itself. The gate packet says so plainly
                   ("after your approval X will stop me; the owner of X is the factory"), and
                   `fix` names the door in words - the person writes `<check id>: accept` and
                   their reason (t-357: never the `waiver.py` command, a person is not shown a
                   script) - because a person's word passes any block in this factory; the
                   block that word passes travels in the finding's `waives` field.

Gate A also rehearses the ENVIRONMENT the next stage runs in : the existing
tests of the project are collected through the project's own command, and the keys and
accounts the cases need are checked against the environment file the runner really reads —
with the path where they go. Both facts were on disk on TP1-15045 and both stopped the
story after the approval instead: fifteen minutes of writing code that could not be collected
(`ModuleNotFoundError: pydantic`), then credentials put into the `.env` of another directory.
And it checks what each CASE needs from the stand — the `preconditions` of its front matter
(a feature flag, data, an account, a variable, a service) — on the stand itself, so "the flag
is off here" is one grouped question inside the gate and not four partitions blocked in S5.

Four more facts of the stand were found by cmp2 (TP1-15045, 01.10.2026) and are asked here
and nowhere else: a precondition the case creates itself (`case_seeds`) or the stand's own
account holds (`stand_account`, met only on positive evidence) is not a question, and the prose
`none` of a story is ONE card; an integration's keys are asked only when the story needs the
integration; a profile without a registered runtime probe has one derived and checked once
(`check_s5_runtime_probe`, which writes nothing); and e2e rows whose page objects wait less than
the stand takes to load a page are one card (`check_s5_stand_limits`).

Gate B rehearses the BUG LIST the person is about to answer: every draft must rest on an
`APP_BUG` triage verdict, on a case the critic actually read, and on steps a person can follow
in the product. TP1-15045 showed two of its four bugs to the owner out of red tests nobody
had triaged, on cases the critic had listed as unreviewed, with the test's own assertion line
for steps — a red result without a verdict is a block of this factory, not a product bug.

A check whose implementation is not installed yet is itself a `factory_defect` finding
("rehearsal step unavailable: ..."), never a silent pass: a rehearsal that quietly skips the
step that would have failed is worth less than no rehearsal at all.
"""
import functools
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contract import HANDED_MATCH_PREFIX, STAND_GAP_MATCH_PREFIX, remedy_errors  # noqa: E402
# The onboarded project a story lives in, or None: found by its marker (`qa-factory/config.json`, the one
# `hooklib.project_root` uses), never guessed - the ONE walk, shared with `case_stamp` and `sizing`.
from critic_rollcall import project_root_of as _project_root  # noqa: E402
import hooklib  # noqa: E402  (`read_json`, the one JSON reader)
from stand_gaps import GATE_STAGE, ROLE_NAMED, ROLE_SCOPES  # noqa: E402 (gate -> the stage it stands in front of: the ONE table)
from hooklib import sorted_paths  # noqa: E402

FACTORY_FIXABLE = "factory_fixable"
PERSON_DECIDES = "person_decides"
# The door of a `not_proved` sign-in, in WORDS: a person reads `fix`, and the owner's rule (t-357) bars a script name or a flag there.
# The command itself (`onboard_apply.py --set-login-ui`) is in phase p1-discovery, which the onboarding role reads.
SIGN_IN_RECIPE_DOOR = ("the onboarding records how this project's login page is used (the fields of its sign-in form, read from "
                       "the project's own page object or test), then the gate is rehearsed again; nothing of yours to do. Known "
                       "limit: the accounts of the environment check are not probed here")
SIGN_IN_FACTORY_DOOR = ("the check is the factory's own and nothing of yours to repair: the gate is shown without it, and a manual "
                        "check that needs this account stops in S6 until the sign-in is proved")
FACTORY_DEFECT = "factory_defect"
CLASSES = (FACTORY_FIXABLE, PERSON_DECIDES, FACTORY_DEFECT)
# Where a door's words name the finding the person answers (`<check id>: accept`): written into the text by
# `Rehearsal.waiver_command`, replaced by `Rehearsal.add` with the finding's own id (the id is born there).
DOOR_ID = "<check-id>"
# Where a finding's text names a stand gap by the name its card gives it: written by the check, replaced by `Rehearsal.add`.
GAP_SLOT = "<gap-name>"
# HF1-9 (GW1-13): a stand integration the project's config records (`environment.integrations[]`) whose keys are not where
# the runner reads them. The check id is its OWN, so the waivers recorded against `s5_environment` keep their meaning.
INTEGRATION_CHECK = "s5_integrations"
# The id of the stand gap one integration makes on one case: `INT-<slug of its name>` (`integration_gap_ids`).
INTEGRATION_GAP_PREFIX = "INT-"
# What a person's word is matched against when no case can be named (the story-level question of `_integration_question`).
INTEGRATION_BLOCK = "integration missing:"
INTEGRATION_CARD_STAGE = "the automated run (S5)"   # the step a tied card says stops; one name, so the texts cannot drift


def integration_gap_ids(names: list) -> list:
    """The `INT-<slug>` gap id of each integration name, in the order given (E18). The slug replaces every character outside
    `[A-Za-z0-9_-]` by `-` (a `:` ends the form id the person writes, an `@` and a `/` are the form reader's own separators), and
    two names that slug alike get `-2`, `-3` in config order, so one answer never passes another integration's gap (B-414 R15)."""
    out = []
    for name in names:
        slug = INTEGRATION_GAP_PREFIX + (re.sub(r"[^A-Za-z0-9_-]", "-", str(name or "").strip()) or "integration")
        candidate, number = slug, 1
        while candidate in out:      # a later twin takes the next free suffix, whatever the earlier ones were called
            number += 1
            candidate = f"{slug}-{number}"
        out.append(candidate)
    return out


def matched_text(message: str, doors: list) -> str:
    """What `waiver.split_overridden` is shown for a finding: its message and the blocks its door names (`waives`).
    A message that says its gap in words does not carry the block key, and the person's recorded word must still pass it."""
    return " ".join([str(message)] + [str(d.get("block") or "") for d in doors or [] if isinstance(d, dict)])

# The stage each gate stands in front of is `stand_gaps.GATE_STAGE` (imported above, B-309 e: one table). The rehearsal is always
# about the NEXT stage: "can it start" is the only question an approval is allowed to leave open.
# The roles that run on the other side of gate A. Their charters are checked against their
# tools here, because a role told to run a script it has no Bash for fails mid-stage.
NEXT_ROLES = {"A": ("qa-automator", "qa-code-critic", "qa-runner"),
              "B": ("qa-retro-analyst",)}
# The three ways out of "the approved write cannot be delivered" . One
# question, three options, the person's to pick — the factory never picks for them and never
# turns this into a waiver, because none of the three is "ignore the block".
DELIVERY_OPTIONS = ("answer with your approval, one of three: (a) set the delivery up now and "
                    "I rehearse again; (b) I hand you each write and you give me the id it gets "
                    "back; (c) keep it "
                    "local — the files stay in the repository and every unsent write becomes a "
                    "row in obligations.md")
# `pytest`, however it is launched. Only a pytest-shaped command can be rehearsed by
# `--collect-only`; a project on another runner simply has no cheap collect to rehearse.
PYTEST_TOKENS = ("pytest", "py.test")
# The plan level whose rows drive a browser (`contract.PLAN_LEVELS`): the only rows a page-load
# limit is about.
E2E_LEVEL = "e2e-ui"


def limit_seconds(value):
    """A recorded limit as a positive number of seconds, or None. A bool is not a number here,
    a string is not one either, and zero, a negative and NaN are not limits."""
    import math
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value > 0 else None


PROBE_TIMEOUT_S = 120   # what `runtime_probe.suggest` writes as the probe's own `timeout_s`


def run_probe(argv, cwd, timeout) -> dict:
    """Run a runtime probe once: `{"record": {...}}`, `{"timed_out": True}` or `{"unreadable":
    why}`. The probe prints ONE JSON line (FR-14); anything else is its failure, said as it came.
    Tests replace this one function; nothing else here starts the probe."""
    import os
    import node_ids
    try:
        out = node_ids.run_captured([str(a) for a in argv], str(cwd),
                                    dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout)
    except subprocess.TimeoutExpired:
        return {"timed_out": True}
    except OSError as exc:
        return {"unreadable": f"{type(exc).__name__}: {exc}"}
    text = (out.stdout or "").strip()
    try:
        record = json.loads(text)
        if isinstance(record, dict):
            return {"record": record}
    except ValueError:
        pass
    tail = [ln.strip() for ln in (out.stderr or text).splitlines() if ln.strip()]
    return {"unreadable": f"the probe answered no provenance JSON (exit {out.returncode}"
                          + (f": {tail[-1][:120]}" if tail else "") + ")"}


def measurement_is_stale(at, verified) -> str:
    """Why a measurement cannot stand for the stand as it is now, or ''. A stand verified AFTER
    the measurement may be a different build; both are read as the date they START with and a
    value that carries no date says nothing (it is never read as stale)."""
    pattern = re.compile(r"\s*(\d{4}-\d{2}-\d{2})")
    measured, checked = pattern.match(str(at or "")), pattern.match(str(verified or ""))
    if measured and checked and measured.group(1) < checked.group(1):
        return (f"the measurement of {measured.group(1)} is older than the stand's last "
                f"verification ({checked.group(1)}), so it may describe another build")
    return ""


# The package's one JSON reader. This module's direction: whatever goes wrong while reading is `default`, None unless passed.
_read_json = functools.partial(hooklib.read_json, errors=Exception)


def _git(root, *args, timeout=10):
    """One read-only git question, or None when git cannot answer it. Never prompts: a probe
    that opens a credential dialog in front of a gate is worse than an unanswered probe."""
    try:
        import os
        out = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=timeout,
                             env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never"))
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _factory_home_in_repo(project_root, repo_dir) -> str:
    """The factory's own folder (`runtime_paths.home_dir`) as a path relative to the top of the git working tree that
    `repo_dir` is in, with a trailing `/`; "" when it cannot be told (no git answer, or the folder lies outside that tree)."""
    try:
        import runtime_paths
        top = _git(repo_dir, "rev-parse", "--show-toplevel")
        if not top:
            return ""
        rel = runtime_paths.home_dir(project_root).resolve().relative_to(Path(top).resolve())
        return rel.as_posix().rstrip("/") + "/"
    except Exception:
        return ""


def porcelain_path(line: str) -> str:
    """The path part of one `git status --porcelain` line. `_git` strips its whole output, so the FIRST line of ` M src/a.ts`
    arrives as `M src/a.ts`: a fixed `line[3:]` cut a character off it. Split after the status word instead."""
    parts = str(line).strip().split(None, 1)
    return parts[1] if len(parts) > 1 else str(line).strip()


def outside_factory_home(lines: list, home_rel: str) -> list:
    """The `git status --porcelain` lines that are NOT the factory's own writes (t-1685 N3-5, R7). A line is left out
    only when EVERY path it names lies under `home_rel` (`qa-factory/`, an untracked folder shown as the folder itself
    included); a rename from or to a path outside it, a quoted path that cannot be read, and any line when `home_rel` is
    empty stay in: a change the person made is never hidden, so the error direction is "counted"."""
    if not home_rel:
        return list(lines)
    kept = []
    for line in lines:
        body = porcelain_path(line) if len(line.strip().split(None, 1)) > 1 else ""
        paths = [part.strip().strip('"') for part in body.split(" -> ")]
        if paths and all(path == home_rel.rstrip("/") or path.startswith(home_rel) for path in paths):
            continue
        kept.append(line)
    return kept


def collect_base(config: dict) -> list:
    """The project's own run command with its placeholders dropped, and nothing added: `[]` when it is not pytest-shaped.

    What the rehearsal hands to `node_ids.collect_output`, the runner S5 reads its node ids through (SC1-12, EP1-11,
    AR-15): that function adds `--collect-only -q` and the retries itself, so the gate sees the ids S5 sees on a
    project whose own `addopts` carry a `-q` or a `-v`.

    Built from `test_command_templates` so the rehearsal proves the toolchain the project
    actually uses — plugins, markers and all — instead of a bare `pytest` that would pass on a
    machine where the real command fails. Every `<placeholder>` is dropped with the flag that
    was waiting for it: a collect must select nothing in particular."""
    import shlex
    templates = config.get("test_command_templates") or {}
    for key in ("quiet", "suite", "one_test"):
        raw = str(templates.get(key) or "").strip()
        if not raw:
            continue
        try:
            tokens = shlex.split(raw)
        except ValueError:
            continue
        if not tokens or not any(any(t in part for t in PYTEST_TOKENS) for part in tokens[:3]):
            continue
        out = []
        for token in tokens:
            if "<" in token and ">" in token:
                # ... and the flag that was about to receive it (`-m "<test-id>"`).
                if out and out[-1].startswith("-") and "=" not in out[-1]:
                    out.pop()
                continue
            out.append(token)
        return out
    return []


def collect_command(config: dict) -> list:
    """The project's own run command, reduced to a collect: `[]` when it cannot be (`collect_base` + `-q` + `--collect-only`).

    The command line itself, for a reader who wants to see what a collect of this project is; the rehearsal does not run it
    (it runs `collect_base` through `node_ids.collect_output`)."""
    out = collect_base(config)
    if not out:
        return []
    if not any(flag in out for flag in ("-q", "--quiet")):
        out.append("-q")
    return out + ["--collect-only"]


def collect_failure(stdout: str, stderr: str) -> str:
    """The one line of a failed collect that says what is actually missing.

    `ModuleNotFoundError: No module named 'pydantic'` is the whole diagnosis; the 200 lines of
    traceback around it are not, and a gate packet is not the place for them."""
    text = (stdout or "") + "\n" + (stderr or "")
    for line in text.splitlines():
        line = line.strip()
        if any(marker in line for marker in ("ModuleNotFoundError", "ImportError",
                                             "No module named", "command not found",
                                             "is not recognized")):
            return " ".join(line.split())[:180]
    tail = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(tail[-1].split())[:180] if tail else "the collect failed without a message"


# --- the executor of a profile: can I launch it at all? ---------------------------------------
#
# TP2-2536 is the story that earned this. Its S5 scope was eight Maestro/iOS cases, and
# the session the factory ran in had no Xcode, no Simulator and no `maestro` binary — not a
# stand that was down, not a missing account: a runner that does not exist here and will not
# start existing. The rehearsal said nothing, S5 wrote the tests, no window could be completed
# without a run, and the person ended up executing everything by hand twice while the factory
# waited. So the question is asked BEFORE the gate, as a question with three answers, and only
# the third one hands anything over.
#
# "Not resolvable" is not "missing". A wrapper this code cannot see through is reported as
# unchecked, never as a refusal: a rehearsal that guesses wrong here costs the person a
# handover they did not need.
EXECUTOR_OPTION_IDS = ("install_here", "other_environment", "handed_to_person")
# The launchers whose real tool is the NEXT token, not the first one.
EXECUTOR_WRAPPERS = {"poetry": 2, "npx": 1, "pipenv": 2, "uv": 2, "npm": 0, "yarn": 0, "pnpm": 0}
# How a shell script says out loud which tool it needs. `run-local.sh` of 2536 does exactly
# this — `command -v maestro` — three lines before it would have run anything.
_SCRIPT_TOOL_RE = re.compile(r"(?:command\s+-v|\bwhich|\btype\s+-p)\s+([A-Za-z][\w.-]{1,40})")


def executor_options(count: int) -> list:
    """The three answers, machine-readable, in the order the question asks them."""
    cases = f"these {count} case(s)" if count else "these cases"
    return [
        {"id": "a", "action": EXECUTOR_OPTION_IDS[0],
         "text": "install it here yourself and tell me - I check again"},
        {"id": "b", "action": EXECUTOR_OPTION_IDS[1],
         "text": "name an environment where I can run them (another machine, a CI runner) — "
                 "I record it in the profile"},
        {"id": "c", "action": EXECUTOR_OPTION_IDS[2],
         "text": f"you run {cases} yourself — I write and review the code, report them as "
                 "handed to you, and never wait for your results"},
    ]


def executor_question(tool: str, profile_id: str, cases: list, stage: str = "S5") -> tuple:
    """(the statement, the three options as one sentence) — the only wording of this question.

    `run_suite.py` asks it again when the tool disappears mid-S5, and it must be the same
    question: a person who answered (b) before the gate and is asked something differently
    worded an hour later has been asked twice."""
    shown = ", ".join(str(c) for c in cases[:6]) + ("…" if len(cases) > 6 else "")
    statement = (f"`{tool}` is not available to me in this session, and the {stage} tests of "
                 f"profile `{profile_id}` ({len(cases)} case{'' if len(cases) == 1 else 's'}: "
                 f"{shown or 'none named yet'}) run through it")
    options = "Your options: " + "; ".join(
        f"({row['id']}) {row['text']}" for row in executor_options(len(cases)))
    return statement, options


# --- and the case before that one: nothing here can run a test at all -------------------------
#
# TP2-2553 ran with `profiles` absent from `qa-factory/config.json`. `s5_profiles`
# answers {} then, so the question above asked nothing, readiness stayed green, and the first
# thing the automator met INSIDE S5 was `run_suite.py --mine` refusing every run
# (`mine_refused`) — after which every typed request of that story was assembled by hand.
# The command that runs one test is what the onboarding is for, so the gap is the onboarding's
# and never the person's homework, and it is said at gate A in the same three-answer shape.
NO_PROFILE_ID = "no-profile"
PROFILE_OPTION_IDS = ("onboard_execution", "name_command", "handed_to_person")


def no_profile_options(count: int) -> list:
    """The three answers to "nothing configured can run these tests", machine-readable."""
    return [
        # t-373 (class completeness of t-363 B3): the plugin's command is something to TYPE, so it is not in the text a
        # person reads (human-questions.md rule 5: it belongs in the answer block); the text says "the onboarding step's
        # execution batch" and the command travels in its own field for whatever renders the how-to-answer block.
        {"id": "a", "action": PROFILE_OPTION_IDS[0],
         "text": "onboard it now, with the onboarding step's execution batch — I record "
                 "your word and run it",
         "command": "/qa-factory:qa-onboarding"},
        {"id": "b", "action": PROFILE_OPTION_IDS[1],
         "text": "name the command that runs ONE test (argv, cwd, reporter) — I write the "
                 "profile into config.json"},
        # (c) is the executor question's third answer, in its own words and not a paraphrase:
        # a person meeting "you run these cases yourself" twice must be meeting one option.
        executor_options(count)[2],
    ]


def no_profile_question(cases: list, stage: str = "S5") -> tuple:
    """(the statement, the three options as one sentence) — the only wording of this one."""
    shown = ", ".join(str(c) for c in cases[:6]) + ("…" if len(cases) > 6 else "")
    statement = (f"no execution profile in `qa-factory/config.json` runs the {stage} tests of "
                 f"this story ({len(cases)} case{'' if len(cases) == 1 else 's'}: "
                 f"{shown or 'none named yet'}) — the factory would reach {stage} and refuse "
                 "every run (`mine_refused`)")
    options = "Your options: " + "; ".join(
        f"({row['id']}) {row['text']}" for row in no_profile_options(len(cases)))
    return statement, options


SCRIPT_SUFFIXES = ("", ".sh", ".bash", ".zsh", ".bat", ".cmd", ".ps1")


def _script_tools(path: Path) -> list:
    """The tools a shell script names as required, when it is readable. Nothing is inferred
    from a name we cannot see: an unreadable script contributes nothing, not a failure, and a
    compiled binary is not opened at all."""
    if path.suffix.lower() not in SCRIPT_SUFFIXES:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:20000]
    except OSError:
        return []
    return list(dict.fromkeys(m.group(1) for m in _SCRIPT_TOOL_RE.finditer(text)))


def executor_probe(argv, cwd: Path, profile: dict | None = None) -> dict:
    """Can this command be launched here? `{"status", "tool", "detail"}`.

    status is `ok` (the launcher resolves), `missing` (it provably does not), or
    `not_checked` (this code cannot tell, which is never a finding). `cwd` is the directory
    the command would run in; `profile` may declare its own `execution_prerequisites`."""
    import shutil
    tokens = [str(t) for t in (argv or []) if str(t).strip()]
    if not tokens:
        return {"status": "not_checked", "tool": "", "detail": "the profile declares no command"}
    cwd = Path(cwd) if cwd else Path(".")
    head = tokens[0]
    # A script path: it exists or it does not, and what it needs may be written inside it.
    if "/" in head or "\\" in head or head.lower().endswith((".sh", ".bat", ".cmd", ".ps1")):
        script = (cwd / head).resolve() if not Path(head).is_absolute() else Path(head)
        if not script.is_file():
            return {"status": "missing", "tool": head,
                    "detail": f"{head} is not on disk at {script}"}
        wanted = _script_tools(script)
    else:
        index = EXECUTOR_WRAPPERS.get(head.lower())
        if shutil.which(head) is None:
            return {"status": "missing", "tool": head, "detail": f"`{head}` is not on PATH"}
        wanted = [tokens[index]] if index and len(tokens) > index else []
    declared = [str(t) for t in ((profile or {}).get("execution_prerequisites") or {}).get(
        "hook_executables") or [] if str(t).strip()]
    for tool in dict.fromkeys(wanted + declared):
        if tool.startswith("-") or "/" in tool or "\\" in tool:
            continue
        if shutil.which(tool) is None:
            return {"status": "missing", "tool": tool, "detail": f"`{tool}` is not on PATH"}
    return {"status": "ok", "tool": head, "detail": "the launcher resolves in this session"}


def s5_automate_rows(task_root: Path) -> list:
    """[(case id, its plan row)] for every case the next stage will have to RUN.

    Kept apart from `s5_profiles` because the question TP2-2553 was never asked is
    exactly "this list is not empty and that one is": there is automation to run and nothing
    configured that can run it."""
    return plan_rows_of(task_root, ("automate",))


def plan_rows_of(task_root: Path, dispositions) -> list:
    """[(case id, its plan row)] for every case whose plan row carries one of these dispositions."""
    rows = _read_json(Path(task_root) / "work" / "test-plan.json", []) or []
    if isinstance(rows, dict):
        rows = rows.get("rows") or []
    by_row = {str(r.get("id") or r.get("ts")): r for r in rows if isinstance(r, dict)}
    try:
        import contract
        cases = contract.case_index(Path(task_root))
    except Exception:
        cases = {}
    out = []
    for case, meta in sorted(cases.items()):
        row = by_row.get(str((meta or {}).get("plan_row") or ""))
        if isinstance(row, dict) and str(row.get("disposition") or "") in dispositions:
            out.append((case, row))
    return out


def default_login_needed(task_root, cfg) -> bool:
    """Does this story need the stand's DEFAULT account (the project's login keys)? The ONE rule of gate A (`check_s5_credentials`)
    and S6 (`Driver.stand_login_problem`) - AR-19: both ask the same question of the same data. PURE: reads the plan, the cases, the
    registry and the config; writes nothing. ERROR DIRECTION: toward True - a question too many, never one too few; any exception is True.

    True when ANY of: (a) a case declares `{"stand_account": "default"}`; (b) the plan has an `automate` row; (c) an executed case (`automate`,
    `manual-agent`) has no `kind: account` precondition with a `stand_account` role (an `env` account counts as none, toward asking); (d) the plan, a case's preconditions, a case's plan row cannot be read, or a row's disposition is
    outside `contract.DISPOSITIONS`; (e) an executed case (`automate`, `manual-agent`) declares `case_seeds` - seeding runs as default;
    (f) an executed `manual-agent` case declares a role whose account is not `known` on the chosen stand, or no stand is chosen, or the
    registry cannot be read - the runner creates such an account as default. EXCEPT (N3) a role whose roster state is a live `not_needed`
    with no load problem (its cases are carried as not run, the runner never walks them) and a guest (`sign_in: none`). Only `manual-human`
    / `skip` / `unverifiable` rows, or no case at all, need no login. The facts are read as data (AR-29): no word of a case is judged."""
    try:
        import contract
        import project_knowledge as PK
        import stand_gaps
        root = Path(task_root)
        plan = root / "work" / "test-plan.json"
        if not plan.is_file():
            return True
        rows = json.loads(plan.read_text(encoding="utf-8-sig"))
        if isinstance(rows, dict):
            rows = rows.get("rows")
        if not isinstance(rows, list):
            return True
        by_row = {str(r.get("id") or r.get("ts")): r for r in rows if isinstance(r, dict)}
        if any(not isinstance(r, dict) or str(r.get("disposition") or "") not in contract.DISPOSITIONS
               or r.get("disposition") == "automate" for r in rows):
            return True
        roles = []
        for case, meta in sorted(contract.case_index(root).items()):
            row = by_row.get(str((meta or {}).get("plan_row") or ""))
            if not isinstance(row, dict):
                return True
            raw = case_preconditions_raw(Path(meta["path"]).read_text(encoding="utf-8", errors="replace"))
            items, errors = parse_preconditions(raw)
            if errors:
                return True
            checks = [next(iter(i["check"].items())) for i in items]
            if any(name == "stand_account" and str(spec).strip() == "default" for name, spec in checks):
                return True
            if row["disposition"] not in ("automate", "manual-agent"):
                continue
            if any(name == "case_seeds" for name, _ in checks):
                return True
            named = [str(spec).strip() for i, (name, spec) in zip(items, checks)
                     if i.get("kind") == "account" and name == "stand_account" and str(spec).strip()]
            if not named:
                return True
            roles.extend(named)
        if not roles:
            return False
        stand = stand_gaps.stand_name(root)
        project = stand_gaps.project_of(root)
        if project is None or not isinstance(cfg, dict) \
                or not any(isinstance(e, dict) and str(e.get("name") or "") == stand for e in cfg.get("environments") or []):
            return True
        guests = None
        for role in dict.fromkeys(roles):
            account = PK.state(project, PK.ACCOUNTS_KEY, stand, role, cfg)
            if account["problem"]:
                return True
            if account["state"] == PK.KNOWN:
                continue
            word = PK.state(project, PK.ROLES_KEY, "", role, cfg)
            if word["state"] == PK.NOT_NEEDED and not word["problem"]:
                continue
            if guests is None:
                roster = PK.roster(project, cfg, stand)
                guests = set() if roster["problem"] else {_role_form(e["role"]) for e in roster["elements"]
                                                          if e.get("sign_in") == "none" and e.get("state") == PK.KNOWN}
            if _role_form(role) not in guests:
                return True
        return False
    except Exception:
        return True


# Dispositions whose cases never reach a stand the factory identifies: a person checks those by hand with no probe.
# Never part of `stand_profiles`, whatever the caller asks for (Q14-A).
NO_STAND_DISPOSITIONS = ("manual-human",)


def stand_profiles(config: dict, task_root: Path, dispositions) -> dict:
    """{profile_id: {"cases", "keyed_on"}} - the profiles a stand-identity question is about: `s5_profiles` over
    the cases of THESE plan dispositions (S5: `("automate",)`; S6: `("automate", "manual-agent")`). A `manual-human`
    row is never included - nobody probes a stand for a case a person checks alone - so a question about the build
    never blocks a window it does not concern. Nothing is read from a stand here."""
    wanted = tuple(d for d in dispositions if d not in NO_STAND_DISPOSITIONS)
    return s5_profiles(config, task_root, plan_rows_of(task_root, wanted))


def _surface_level_fits(config: dict, profiles: list, level: str) -> list:
    """EP1-41f: the ids of the profiles that hold the capability of a surface row whose `fits_levels` names this plan level
    (references/surfaces.json, read through `surfaces`, the one reader). [] - no fit, no answer - when the level is empty, when the
    project declares nothing beyond web/API words (the table is NOT read: that road does not change), or when the table cannot be
    read: a case left unkeyed is asked about, never keyed to a guessed profile."""
    if not level:
        return []
    try:
        import surfaces
        if not surfaces.declared_surfaces(config):
            return []
        table = surfaces.rows()["surfaces"]
    except ValueError:
        return []
    words = {row["capability"] for row in table.values()
             if isinstance(row.get("fits_levels"), list) and level in row["fits_levels"]}
    return [str(p["profile_id"]) for p in profiles
            if isinstance(p.get("capabilities"), list) and any(w in words for w in p["capabilities"] if isinstance(w, str))]


def s5_profiles(config: dict, task_root: Path, rows=None) -> dict:
    """{profile_id: {"cases", "keyed_on"}} — the profiles the S5 scope will need.

    Keyed on, in this order: the case's own `execution_profile_id` when a plan row carries
    one; else the plan row's `level` against the profile's `capabilities` (`e2e-ui`, `api`,
    … — `contract.PLAN_LEVELS` is the one field in the plan that names the execution
    surface); else the plan row's `level` EQUAL to exactly one profile id (t-218, F3a: cmp2's
    `e2e-ui` profile declares the capability `web`, so no capability fit exists, and with two
    profiles the single-profile fallback never applies — its e2e rows were keyed to nothing and
    no e2e check could fire); else, when the project declares exactly one profile, that
    profile. The id step stands AFTER the capability fit, so a capability fit still wins, and
    BEFORE the fallback; after it, EP1-41f, the level against the `fits_levels` of a test surface (`_surface_level_fits`): the one
    profile that holds that surface's capability. Two such profiles key nothing. A case whose profile cannot be told this way is left out — a question
    asked about the wrong profile is worse than no question.

    Users: `controller.Controller._handed_cases`, `check_s5_executor`, `check_s5_toolchain`
    (its missing-launcher branch), `check_s5_reporter`, and since t-218 `check_s5_stand_limits`
    and `check_s5_runtime_probe`."""
    profiles = [p for p in (config.get("profiles") or [])
                if isinstance(p, dict) and p.get("profile_id")]
    if not profiles:
        return {}
    out: dict = {}
    for case, row in (s5_automate_rows(task_root) if rows is None else rows):
        named = str(row.get("execution_profile_id") or "")
        keyed, chosen = "", ""
        if named and any(str(p["profile_id"]) == named for p in profiles):
            keyed, chosen = "plan row execution_profile_id", named
        else:
            level = str(row.get("level") or "")
            fits = [str(p["profile_id"]) for p in profiles
                    if level and level in (p.get("capabilities") or [])]
            same = [str(p["profile_id"]) for p in profiles if level and str(p["profile_id"]) == level]
            if len(fits) == 1:
                keyed, chosen = f"plan row level `{level}` against profile capabilities", fits[0]
            elif len(same) == 1:
                keyed, chosen = f"plan row level `{level}` equals the profile id", same[0]
            elif len(surface_fits := _surface_level_fits(config, profiles, level)) == 1:
                keyed, chosen = f"plan row level `{level}` fits a test surface of the profile", surface_fits[0]
            elif len(profiles) == 1:
                keyed, chosen = "the project declares one execution profile", str(profiles[0]["profile_id"])
        if not chosen:
            continue
        entry = out.setdefault(chosen, {"cases": [], "keyed_on": keyed})
        entry["cases"].append(case)
    return out


# --- and the fact the run itself rests on: does the report exist at all? ----------------------
#
# TP2-2553: Karma was configured with `progress`, `kjhtml` and `coverage`, and
# `karma-junit-reporter` was in no dependency of the project. The profile said the run writes a
# report; the runner can name the cure and did — in the middle of S5, on the first real run,
# after the approval. One test of the project's own suite, run at the gate, proves the same
# thing for the price of one test.
#
# B-407 B-deps: what spells a test is `test_files.is_test_for("name", ...)`, the usual names of
# references/test-path-markers.json (FooTest.java, foo_test.go, FooTests.cs). These globs are only the
# FLOOR - today's rule - for the moment those names cannot be read (the verdict is None).
REPORTER_TEST_GLOBS = ("test_*.py", "*_test.py", "*.spec.ts", "*.spec.tsx", "*.spec.js",
                       "*.test.ts", "*.test.tsx", "*.test.js", "*Tests.cs", "*Test.cs")
# Trees a test file is never picked from: a vendored copy of somebody else's suite proves
# nothing about this project's reporter, and walking them is the slow part of the search.
REPORTER_SKIP_DIRS = {"node_modules", "venv", "dist", "build", "out", "bin", "obj",
                      "__pycache__", "target", "vendor", "coverage"}


# One probe per command per process. The packet, the stage closure and the orchestrator's own
# `--text` call each rehearse the same gate, and a person's test must not be run three times to
# answer one question. This map is only the per-process half: every process starts empty, and a
# gate that is called again in the next one would run the person's test again, at every gate A
# of every story on the same stand. The durable half is `qa-factory/state/reporter-rehearsals.json`
# (owner decision D-0019 item 2: once per project; B-220 F11 narrowed the key to the COMMAND - not the stand, not the
# deployed version - so the onboarding probe's proof is the one gate A reuses). It is written only
# after a rehearsal PROVED a report (a negative outcome is what the person's fix is about to
# change, so the next call must look again) and it is a record of its own, which FR-45 allows;
# the rehearsal still writes nothing of the caller's, and the report itself stays in the OS temp.
_REPORTER_PROBES: dict = {}
REPORTER_REHEARSALS_FILE = "reporter-rehearsals.json"
COLLECT_SHOWN = 5   # broken test files named in the gate's note; `broken_files` of the note holds all of them


class ReporterCtx(NamedTuple):
    """What one profile's reporter rehearsal knows before it picks a test (t-683 D11): the check that speaks, the profile, the project
    root, the directory the command really runs in, its argv (a TUPLE - nothing in a context is mutable, E11), the report format this
    step reads, the kind the profile declares and the run's time limit. Built by `Rehearsal._rehearse_reporter` once the profile has an
    argv; the test chosen, the launch and the report path are not in it - they exist only later."""
    check: str
    profile_id: str
    root: Path
    cwd: Path
    argv: tuple
    fmt: str
    declared_kind: str
    timeout: int
    # EP1-22 (B-2): WHICH command this is - `profile_contract.command_identity`, the single input of every digest and key of the
    # command. `argv` stays the words that are launched and shown; on a command with no `env` the two are the same words.
    identity: tuple = ()


def _spelled_as_a_test(name: str) -> bool:
    """A CODE file whose name is a usual test name: `test_files.is_test_for("name", name)` and `is_code_file(name)` (the
    file is RUN as the one test, so `test_data.json` is no candidate). `is_code_file` None (the extensions are unknown)
    is the leaf's own floor, `CODE_EXTENSION_FLOOR`, never a refusal: a refusal here would make gate A ask a person
    about a reason that is the factory's (FR-3). `REPORTER_TEST_GLOBS` (today's rule, case-sensitive on every
    platform: FR-31) decides when the usual test names themselves cannot be read or asked."""
    import fnmatch
    try:
        from test_files import CODE_EXTENSION_FLOOR, is_code_file, is_test_for
        verdict = is_test_for("name", name)
        code = is_code_file(name) if verdict else None
    except Exception:
        verdict, code = None, None
    if verdict is None:
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in REPORTER_TEST_GLOBS)
    if not verdict:
        return False
    return code if code is not None else Path(name).suffix.lower() in CODE_EXTENSION_FLOOR


def first_test_file(root) -> str:
    """The first file under `root` whose NAME is a usual test name (`test_files`, the one leaf), or ''.

    Sorted at every level, so the same machine picks the same test twice and a card written
    about it means the same thing tomorrow. The trees in `REPORTER_SKIP_DIRS` are not entered."""
    import os
    root = Path(root)
    if not root.is_dir():
        return ""
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in REPORTER_SKIP_DIRS and not d.startswith("."))
        for name in sorted(files):
            if _spelled_as_a_test(name):
                return str(Path(base) / name)
    return ""


def first_collected_node(stdout: str, under: str = "") -> str:
    """The first node id of a `pytest --collect-only -q` output, or ''. The collect has already
    been paid for by `check_s5_toolchain`; running it twice at one gate would be the cost this
    whole rehearsal exists to avoid.

    `under` is a directory (posix, relative to where the collect ran): only a node below it
    counts. The collect is the PROJECT's, and its first node belongs to whichever profile sorts
    first - on cmp2 an api test was offered to prove the e2e profile's report (t-218, C5)."""
    # ONE reader of a collect's output for the gate and for S5 (`node_ids.parse_collected`, AR-13): until EP1-9 this
    # function kept its own rules and the two could disagree on the same bytes (a `=` banner before the ids, a
    # warnings section after them).
    nodes = collected_nodes(stdout, under)
    return nodes[0] if nodes else ""


def collected_nodes(stdout: str, under: str = "") -> list:
    """Every node id of a collect's output, or only those below `under` (same reading as `first_collected_node`, which
    is its first element): `first_collected_node` and the card's counts (HF8-14) cannot disagree on one collect."""
    import node_ids
    prefix = str(under or "").strip().strip("/")
    if prefix in (".", ""):
        prefix = ""
    return [line for line in node_ids.parse_collected(stdout or "")
            if not prefix or line.replace("\\", "/").startswith(prefix + "/")]


# --- case preconditions: the shape ------------------------------------------------------------
#
# What a case needs from the STAND before its first step, written by the designer in a form
# code can check. On TP1-15045 all of it was prose inside a Given — "needs guardrail
# integration data", "a non-owner account (not available on localhost)" — and the stand's
# answer arrived in S5, one dispatch at a time: `features:subWorkflow` was off, there was no
# guardrail data, no second account, and the account variables sat in an env file the conftest
# never loads. A first dispatch was wasted and four partitions of TC-012 ended "blocked by the
# stand", all of it knowable at gate A.
#
# The field is ONE line of JSON in the case front matter. Not a nested YAML block: the
# factory's front-matter parser is flat, and `external_writes.upsert_frontmatter` rewrites the
# header from that flat dict — a block would be dropped the first time a case id is recorded.
PRECONDITION_KINDS = ("feature_flag", "data", "account", "env", "service")
# `case_seeds` and `stand_account` are the two structured answers to "who provides this" that
# `none` used to carry as prose (t-218, TP1-15045: 14 of the 16 cards at gate A said, in the
# designer's own words, "seeded by the case itself" or "the localhost superadmin holds it", and a
# detector may not read those words, FR-12). The designer names the field before the work (FR-38).
#
# `stand_frontend` (GW1-27) is the third: the case needs the stand's UI (an address a browser opens). The gate reads the
# project's own record of it (`env_probe.frontend_of`, the one reader) and asks only when none is recorded; the case's
# text never names the address (a `none` about "the base URL of the UI" stays a card: no detector reads prose, FR-12).
#
# `integration` (GW1-16) is the fourth: the case goes through a service the project records in `environment.integrations`.
# The role writes the integration's NAME as its brief lists it, never a variable name: the gate reads the keys (and the
# alternative sets) from the record, so a service reached by one of several key sets is met when any set is held.
PRECONDITION_CHECKS = ("env", "http", "none", "case_seeds", "stand_account", "stand_frontend", "integration")
PRECONDITION_HTTP_KEYS = ("path", "status", "json_path", "equals")
PRECONDITION_FORM = ('preconditions: [{"id": "PC-1", "kind": "feature_flag", "what": "sub-workflow '
                     'states are enabled", "partitions": ["P-selfref"], "check": {"http": {"path": '
                     '"/v1/config", "status": 200, "json_path": "features.subWorkflow", "equals": '
                     'true}}}] — one line of JSON; kind is one of ' + " | ".join(PRECONDITION_KINDS)
                     + '; check is {"env": "VAR_NAME"}, {"http": {...}}, {"case_seeds": "<what the '
                     'case itself creates>"} (never asked), {"stand_account": "<credentials_by_role '
                     'key>"} (an account the stand already holds), {"stand_frontend": "<why the case '
                     'needs the stand\'s UI>"} (the address of the UI, looked up in the project\'s record), '
                     '{"integration": "<name of one integration from your brief>"} (a service the case goes '
                     'through; the name, never a variable name) '
                     'or {"none": "<why no machine can '
                     'check it>"} (the person is asked); `partitions` is optional; `remedy` is optional '
                     'and is {"kind": "flag|credential|data|service", "where": "<file:lines or '
                     'a variable NAME>", "change": "<what to set>", "restart": "<what to '
                     'restart>"} — names only, never the value of a credential')
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PRECONDITIONS_LINE_RE = re.compile(r"^preconditions:[ \t]*(.*)$", re.MULTILINE)
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_PARTITION_RE = re.compile(r"\bP-[a-z][A-Za-z0-9-]*\b")  # the spelling s5_precheck counts


_KEY_SHAPE = r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+"   # a variable name has an underscore: `NOT` is a word
_ACCOUNT_PREFIX_RE = re.compile(r"^(\S+?):\s+")
_ACCOUNT_KEY_RE = re.compile(r"\s*(?:[/,+&]\s*)?(" + _KEY_SHAPE + r")(?![A-Za-z0-9_])")


def account_keys(note) -> list:
    """The variable NAMES an account note of `credentials_by_role` lists up front, or [].

    `.env: AUTH_USERNAME / AUTH_PASSWORD - the superadmin ...` lists two; `NOT provisioned
    locally`, `missing locally` and an empty note list none. Only the leading run of names
    counts: the prose after it names other variables (the stand's own `SUPERADMIN_EMAIL`)
    that the test runner never reads. Presence of name-shaped tokens, not the meaning of the
    sentence (FR-12); the debt is on `_stand_account`."""
    rest = " ".join(str(note or "").split())
    for _ in range(2):  # an optional `<file>:` before the names - but never a name itself
        prefix = _ACCOUNT_PREFIX_RE.match(rest)
        if not prefix or re.fullmatch(_KEY_SHAPE, prefix.group(1)):
            break
        rest = rest[prefix.end():]
    keys, pos = [], 0
    while True:
        found = _ACCOUNT_KEY_RE.match(rest, pos)
        if not found:
            return keys
        keys.append(found.group(1))
        pos = found.end()


def configured_env_files(env_cfg, root) -> tuple:
    """(the env files the CONFIG names, how we know): `environment.env_files` when it lists any, else the older single
    `environment.env_file`, else `([], "")`. The ONE reading of that part of the config (AR-13): the gate's `_loaded_env_files`
    starts from it, and `project_decisions stand-frontend` checks the variable it records in the same files, so a file the
    gate reads is a file the writer reads. A project that names no file is the gate's to resolve (conftest, `.env`)."""
    env_cfg = env_cfg if isinstance(env_cfg, dict) else {}
    root = Path(root)
    listed = [str(p).strip() for p in (env_cfg.get("env_files") or []) if str(p or "").strip()] \
        if isinstance(env_cfg.get("env_files"), list) else []
    if listed:
        return ([root / p for p in listed], "config `environment.env_files`")
    if str(env_cfg.get("env_file") or "").strip():
        return ([root / str(env_cfg["env_file"]).strip()], "config `environment.env_file`")
    return ([], "")


def env_values(files) -> dict:
    """{name: value} of what is set for the runner: the process environment with `files` laid over it, empty values left out.
    The one reading of it, for the gate's `_env_names` and for `project_decisions stand-frontend` (AR-13). Values are for the
    caller to test; the only thing ever printed about a variable is its name."""
    import os
    import env_probe
    values = {k: v for k, v in os.environ.items() if str(v or "").strip()}
    for path in files:
        if Path(path).is_file():
            values.update({k: v for k, v in env_probe.parse_env_file(Path(path)).items() if str(v or "").strip()})
    return values


_ROLE_SEPARATORS_RE = re.compile(r"[\s_-]+")


def _role_form(text) -> str:
    """A role's normal form: lower case, and a run of spaces, `_` and `-` one space (`default_user` = `Default-User` =
    `default user`)."""
    return _ROLE_SEPARATORS_RE.sub(" ", str(text).strip().lower()).strip()


def role_candidates(roles, asked) -> list:
    """The keys of `roles` (a stand's `credentials_by_role`) that `asked` names: the key equal to it after its edges are
    trimmed, else every key of the same normal form. A reserved form (`default`, `env:...`, `created:...`: `reserved_role`)
    is never a candidate and is never matched: the capture reads those before any role, so such a key is unreachable and
    must not become the account of a looser spelling. Empty for an `asked` that is not text, or empty, or a `roles` that
    is not an object."""
    if not isinstance(roles, dict) or not isinstance(asked, str) or not asked.strip():
        return []
    from config_contract import reserved_role
    text = asked.strip()
    if reserved_role(text):
        return []
    if text in roles:
        return [text]
    form = _role_form(text)
    if not form:        # only separators (`_`, `--`): no letter to compare, so no match (an empty form equals another empty one)
        return []
    return [key for key in roles if isinstance(key, str) and not reserved_role(key) and _role_form(key) == form]


def account_role(roles, asked):
    """The ONE reader of a role name (AR-13, GW1-27): the real key of `roles` that `asked` names, or None. The key equal to
    `asked` (edges trimmed) wins, even beside a twin; else the only key of the same normal form. Two such keys (`Admin`,
    `admin` asked as `ADMIN`) or none is None: a doubt is never another account (ERROR DIRECTION: toward `unmet`/a refusal).
    The gate (`_stand_account`), `manual_capture.resolve_actor` / `auto_actor` and `Driver.stand_login_problem` resolve
    through it, so what the gate calls met is what the sign-in reads."""
    found = role_candidates(roles, asked)
    return found[0] if len(found) == 1 else None


def role_names(roles) -> str:
    """The roles of a stand named for a person: `a`, `b` ... at most LIST_LIMIT, then how many were left; `none` when it lists none."""
    names = [str(r) for r in roles if isinstance(r, str)] if isinstance(roles, dict) else []
    if not names:
        return "none"
    return ", ".join(f"`{n}`" for n in names[:LIST_LIMIT]) + (f" and {len(names) - LIST_LIMIT} more" if len(names) > LIST_LIMIT else "")


LIST_LIMIT = 6   # case ids named in one line; the rest are counted ("and N more")


def named_ids(ids: list, limit: int = LIST_LIMIT) -> str:
    """`TC_001, TC_002 and 5 more`: the first `limit` ids, then how many were left out."""
    ids = list(dict.fromkeys(str(i) for i in ids))
    shown = ", ".join(ids[:limit])
    return shown + (f" and {len(ids) - limit} more" if len(ids) > limit else "")


def required_by_entries(spec: dict) -> list:
    """The stripped, non-empty entries of an integration row's `required_by` (a field that is not a list says nothing)."""
    raw = spec.get("required_by")
    return [str(a).strip() for a in raw if str(a or "").strip()] if isinstance(raw, list) else []


def access_fix(keys: list, where: str, waiver: str) -> str:
    """The moves of the question about an integration's access (HF8-11, F-1), fitted to what `brief_lines` shows of a `fix`
    (2 x BRIEF_CUT): the NAMES give way, never the moves after them. As many names as fit, at most LIST_LIMIT, then how many
    were left and who has the list; at least one. When one name and a long `where` still do not fit, the front of `where` is
    clipped (`...` + its tail, the file name survives); the fix is then as long as the moves need and the brief marks the cut."""
    lead, mid = "give access yourself: set ", ", never in the chat - nothing is recorded; "
    tail = ", and what needs it is reported as not run; if you know which cases use it, tell the conductor"
    # `add` replaces the door placeholder of the waiver with the finding's id (`s5_integrations-14`): count it as grown
    grown = len(waiver) + waiver.count(DOOR_ID) * (len(INTEGRATION_CHECK) + len("-99") - len(DOOR_ID))
    budget = 2 * BRIEF_CUT - len(lead) - len(" in ") - len(mid) - grown - len(tail)
    count = len(dict.fromkeys(str(k) for k in keys))

    def names_of(limit: int) -> str:
        return named_ids(keys, limit) + ("; the conductor has the full list" if limit < count else "")
    names = names_of(1)
    for limit in range(min(count, LIST_LIMIT), 0, -1):
        if len(names_of(limit)) + len(where) <= budget:
            names = names_of(limit)
            break
    else:
        room = budget - len(names)
        if 12 <= room < len(where):
            where = "…" + where[len(where) - room + 1:]
    return f"{lead}{names} in {where}{mid}{waiver}{tail}"


def integration_row_keys(spec) -> list:
    """The key NAMES of one `environment.integrations[]` row: its `keys`, and when that list is empty the union of its
    `credential_alternatives` (HF8-11). A row that names its sets is an integration however `keys` was written - the
    contract wants `keys` to be that union, but a hand-written config must not make the row vanish from the gate."""
    def names(raw) -> list:
        return [str(k).strip() for k in raw if isinstance(k, str) and str(k).strip()] if isinstance(raw, list) else []
    if not isinstance(spec, dict):
        return []
    keys = names(spec.get("keys"))
    if keys:
        return keys
    options = spec.get("credential_alternatives")
    return list(dict.fromkeys(k for option in (options if isinstance(options, list) else []) for k in names(option)))


def integration_row_name(spec) -> str:
    """The name of one `environment.integrations[]` row, as every reader of it spells it (AR-13): stripped, `an integration` for a
    row with none. `integration_gap_ids` and a case's `check.integration` equality both depend on this one normalisation."""
    return str(spec.get("name") or "an integration").strip() or "an integration" if isinstance(spec, dict) else "an integration"


def integration_login_keys(env_cfg) -> list:
    """The key NAMES of the login (`user_key`, `secret_keys`, `extra_keys`), stripped, none empty: the keys the login question asks
    and an integration's question leaves alone. ONE reader (AR-13): `check_s5_credentials` and `_unmatched_integrations` call it."""
    return [str(k).strip() for k in [env_cfg.get("user_key")] + list(env_cfg.get("secret_keys") or [])
            + list(env_cfg.get("extra_keys") or []) if str(k or "").strip()]


def not_asked_line(seeded: list, held: list) -> str:
    """The one INFO line for the preconditions nobody is asked about: `[(case id, item)]` of
    what the cases create themselves and of what the stand's own account holds."""
    parts = []
    if seeded:
        cases = list(dict.fromkeys(c for c, _ in seeded))
        parts.append(f"{len(seeded)} "
                     + ("the cases create themselves" if len(cases) != 1 else "the case creates itself")
                     + f" ({named_ids(cases)})")
    if held:
        cases = list(dict.fromkeys(c for c, _ in held))
        parts.append(f"{len(held)} {'are' if len(held) != 1 else 'is'} held by the stand's own "
                     f"account ({named_ids(cases)})")
    total = len(seeded) + len(held)
    return (f"{total} precondition{'s are' if total != 1 else ' is'} not asked: "
            + ", ".join(parts) + ".")


NONE_CARD_BLOCK = "preconditions no machine can check"   # what a person's word is matched against
BRIEF_CUT = 200   # characters of one finding the gate packet shows (`brief_lines`); the rest is `--text`


def none_card_lead(preconditions: int, cases: int) -> str:
    """The first sentence of the card of every prose `none` precondition: the block text, the
    count and the question, and never a reason (those follow it). Built so that it fits `BRIEF_CUT`
    for any count - only the two numbers vary - because the gate packet shows the first 200
    characters and the question must be among them (t-224, C1). A count of one still reads as a
    count."""
    return (f"{NONE_CARD_BLOCK}: {preconditions} precondition{'s' if preconditions != 1 else ''} "
            f"of {cases} case{'s' if cases != 1 else ''} cannot be checked on the stand - which "
            "of these are real needs of this stand?")


def case_preconditions_raw(text: str):
    """The raw `preconditions:` value of a case, or None when the case declares none.

    None is the answer for every case written before 0.7.8, and it is never a finding: a
    story in flight is not refused over a field its designer was never asked for."""
    front = _FRONT_MATTER_RE.match(text or "")
    if not front:
        return None
    line = _PRECONDITIONS_LINE_RE.search(front.group(1))
    return line.group(1).strip() if line else None


def parse_preconditions(raw) -> tuple:
    """(preconditions, shape errors). Shape only — nothing here touches the stand.

    The one owner of the shape: `validate_artifacts.py` calls this on write, the rehearsal
    calls it before it checks anything, so the two can never disagree about what is legal."""
    if raw is None:
        return [], []
    value = raw
    if isinstance(raw, str):
        if not raw.strip():
            return [], ["`preconditions:` is empty or written as a nested block — the form is "
                        + PRECONDITION_FORM]
        try:
            value = json.loads(raw)
        except ValueError as exc:
            return [], [f"`preconditions` is not JSON ({exc}) — the form is " + PRECONDITION_FORM]
    if not isinstance(value, list):
        return [], ["`preconditions` must be a list — the form is " + PRECONDITION_FORM]
    errors, seen = [], set()
    for index, item in enumerate(value):
        where = f"preconditions[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{where} must be an object")
            continue
        pid = str(item.get("id") or "").strip()
        if not pid:
            errors.append(f"{where}: `id` is missing (PC-1, PC-2 …)")
        elif pid in seen:
            errors.append(f"{where}: id `{pid}` is used twice")
        seen.add(pid)
        where = pid or where
        if item.get("kind") not in PRECONDITION_KINDS:
            errors.append(f"{where}: kind `{item.get('kind')}` outside {list(PRECONDITION_KINDS)}")
        if not isinstance(item.get("what"), str) or not item["what"].strip():
            errors.append(f"{where}: `what` is missing — the plain words the person reads at the gate")
        partitions = item.get("partitions", [])
        if not isinstance(partitions, list) or any(
                not isinstance(p, str) or not _PARTITION_RE.fullmatch(p) for p in partitions):
            errors.append(f"{where}: `partitions` must be a list of `P-<name>` ids of this case")
        if "remedy" in item:
            # A precondition that carries its own fix becomes a card at the gate instead of a
            # sentence the person has to decode (TP1-15045). The shape is the contract's,
            # so the card, the manifest row and the validator cannot drift apart.
            errors.extend(f"{where}: {problem}" for problem in remedy_errors(item.get("remedy")))
        check = item.get("check")
        if not isinstance(check, dict) or len(check) != 1 or next(iter(check)) not in PRECONDITION_CHECKS:
            errors.append(f"{where}: `check` must hold exactly one of {list(PRECONDITION_CHECKS)}")
            continue
        name, spec = next(iter(check.items()))
        if name == "env" and not (isinstance(spec, str) and _ENV_NAME_RE.match(spec)):
            errors.append(f"{where}: check.env must be the NAME of one variable, never a value")
        elif name == "none" and not (isinstance(spec, str) and spec.strip()):
            errors.append(f"{where}: check.none must say why no machine can check it")
        elif name == "case_seeds" and not (isinstance(spec, str) and spec.strip()):
            errors.append(f"{where}: check.case_seeds must say what the case itself creates")
        elif name == "stand_account" and not (isinstance(spec, str) and spec.strip()):
            errors.append(f"{where}: check.stand_account must be the `credentials_by_role` key of "
                          "the account (`default_user`), never a value")
        elif name == "stand_frontend" and not (isinstance(spec, str) and spec.strip()):
            errors.append(f"{where}: check.stand_frontend must say why the case needs the stand's UI "
                          "(plain words), never an address")
        elif name == "integration" and not (isinstance(spec, str) and spec.strip() and "\n" not in spec
                                            and "\r" not in spec):
            errors.append(f"{where}: check.integration must be the name of one integration from your brief, "
                          "never a key")
        elif name == "http":
            if not isinstance(spec, dict):
                errors.append(f"{where}: check.http must be an object with a `path`")
                continue
            extra = sorted(set(spec) - set(PRECONDITION_HTTP_KEYS))
            if extra:
                errors.append(f"{where}: check.http has unknown keys {extra}; allowed: "
                              f"{list(PRECONDITION_HTTP_KEYS)}")
            path = spec.get("path")
            # A path, never a URL: the rehearsal only ever talks to the stand the project's
            # own config names. A case file is role-written text; it does not get to choose
            # which host a gate sends a request to.
            if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
                errors.append(f"{where}: check.http.path must start with `/` — it is glued to "
                              "the environment's API base URL from config, never a full URL")
            status = spec.get("status", 200)
            if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
                errors.append(f"{where}: check.http.status must be an HTTP status code")
            if "json_path" in spec and not (isinstance(spec["json_path"], str) and spec["json_path"].strip()):
                errors.append(f"{where}: check.http.json_path must be a dotted path (`features.subWorkflow`)")
            if "equals" in spec and "json_path" not in spec:
                errors.append(f"{where}: check.http.equals needs a json_path to compare")
            if isinstance(spec.get("equals"), (dict, list)):
                errors.append(f"{where}: check.http.equals must be a scalar")
    return ([item for item in value if isinstance(item, dict)], errors)


_PRECONDITION_ID_RE = re.compile(r'"id"\s*:\s*"([^"]+)"')


def shared_precondition_ids(task_root) -> set:
    """The precondition ids that MORE THAN ONE case file of the story declares (`PC-1` in two cases) - B-414 R14, M9.

    Counted over the RAW ids of every case file, parse errors included (a file whose line does not parse still names its ids,
    read out of the text): a case file that is broken for the moment must not un-qualify an id for another case, or a person's
    old, ambiguous `stand gap: PC-1` would settle a gap it was never about. Reads files only."""
    from collections import Counter
    from contract import case_files, case_glob
    try:
        files = case_files(Path(task_root))
    except Exception:
        files = case_glob(Path(task_root) / "work" / "test-cases", Path(task_root))
    counts: Counter = Counter()
    for path in files:
        try:
            raw = case_preconditions_raw(Path(path).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if raw is None:
            continue
        items, errors = parse_preconditions(raw)
        ids = {str(item.get("id") or "").strip() for item in items}
        if errors and not items:
            ids = {m.strip() for m in _PRECONDITION_ID_RE.findall(raw)}
        counts.update(ids - {""})
    return {pid for pid, n in counts.items() if n > 1}


def precondition_gap_id(case_id, pc_id, shared) -> str:
    """The id of the stand gap a precondition makes: its own (`PC-1`), or `PC-1@TC-007` when another case declares the same one
    (F18). `@` is the separator the form reader reads whole (`/` is the area separator of a case key, `:` ends the form id).
    ONE function for the rehearsal's gap rows, their doors and `stand_gaps.declared_preconditions`."""
    pc_id = str(pc_id or "")
    return f"{pc_id}@{case_id}" if pc_id in shared else pc_id


def _json_path(body, dotted: str) -> tuple:
    """(found, value) for `a.b.0.c`. A list is indexed by a number; anything else is a miss."""
    node = body
    for part in [p for p in str(dotted).split(".") if p != ""]:
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return (False, None)
    return (True, node)


def http_get(url: str, timeout_s: float) -> tuple:
    """(status, body text) of one anonymous GET. Raises on no answer.

    Standard library, no credentials, no redirects followed: a stand behind a login answers
    302 to its identity provider, and following it would "succeed" on a login page — the
    probe artifact that once recorded a healthy preview stand as MISSING. Tests replace this
    one function; nothing else in the rehearsal opens a socket.

    B-408: through the factory's one HTTP helper (its User-Agent), and the body of an ERROR answer is kept (it used to
    be dropped), so a 403 that is a protection page can be told from the stand's own."""
    import http_client
    answer = http_client.fetch(url, headers={"Accept": "application/json"}, timeout=timeout_s, max_body=1048576)
    if answer.unreadable and 200 <= answer.status < 300:
        # a stalled body of a 2xx was always a timeout here ("the stand did not answer"); the helper now keeps the
        # status and says `unreadable`, so this caller keeps its old word by raising the same exception (B-408 F1)
        raise TimeoutError("the body of the answer did not arrive")
    return (answer.status, answer.body.decode("utf-8", errors="replace"))


# The ONE form of a finding id (AR-18, F5 t-1752): `<check>-<ordinal or subject token>`, a lower-case check name, a `-`, then the token.
# `Rehearsal.add` WRITES ids of this form (`_id_token`), `story_run.Driver._FINDING_LINE_RE` READS them through this pattern; the `-` is
# required so a plain `word: text` line of the person's words is no finding line.
FINDING_ID_PATTERN = r"[a-z][a-z0-9_]*-[A-Za-z0-9_-]*[A-Za-z0-9_]"
FINDING_ID_RE = re.compile(FINDING_ID_PATTERN)


def _id_token(subject) -> str:
    """The part of a finding id a SUBJECT makes (R7): `[A-Za-z0-9_-]` kept, every other run of characters (a `.` too) folded to one `-`,
    and no `-` at either edge, so the id ends on a character `FINDING_ID_PATTERN` accepts. Two subjects that fold to one token are told
    apart by `Rehearsal.add` (`-2`, `-3`), never by this function; an empty subject, or one with no letter or digit in it, gives `""`."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(subject or "").strip()).strip("-")


ROLE_GAP_PREFIX, PRODUCT_ROLE_PREFIX = "RA-", "PR-"
ROLE_NAME_CLIP = 40                          # characters of a stand or role name in the lead of the card's finding
# (`ROLE_SCOPES` and `ROLE_NAMED`, the cases a role card names, are `stand_gaps`'s: one home for what the card and its lines agree on)
ACCOUNT_MARK = "[knowledge:credentials_by_role]"   # a DATA token in the MACHINE field `mark` of the "acting on your earlier answers" note, for counting later; never in the text a person reads


def _lossless_token(text) -> str:
    """The readable id token of a name when the fold keeps every character (`_id_token` changes nothing but the separators), else ""."""
    tok = _id_token(text)
    return tok if tok and tok.replace("-", " ") == str(text).strip() else ""


def role_gap_tokens(stand, role, packet_forms=()) -> tuple:
    """`(stand token, role token)` of a role card's ids (t-2142 §3 (2), N1). Built separately, each lossless-or-hash (a stand name holding a `-`
    or whitespace is hashed whole, so `RA-<stand>-<role>` reads back to one pair; F4): a role whose fold
    keeps every character of its normal form takes the readable token (it maps back to exactly ONE form, since a form holds no `-`);
    any other (a name in Cyrillic letters, `admin-` followed by one) takes the first 8 hex of the sha1 of the form, so no lossy form ever takes a token another
    role could also take, whatever the stand's spelling. A stand name is compared exactly (§2): the token is its own when lossless, else
    the sha1 prefix of the exact name. Defensive: when two distinct forms of this packet still give one role token (a prefix
    collision), both widen to 16 hex. Pure."""
    form = _role_form(role)
    tok = _lossless_token(form)
    digest = hashlib.sha1(form.encode("utf-8")).hexdigest()
    tok = tok or digest[:8]
    if any(other != form and (_lossless_token(other) or hashlib.sha1(other.encode("utf-8")).hexdigest()[:8]) == tok
           for other in packet_forms or ()):
        tok = digest[:16]
    name = str(stand or "")
    # a stand token is readable only when it holds no `-` and no whitespace: with one, `RA-dev-a-b` could be stand `dev-a` + role `b` or stand
    # `dev` + role `a b` (F4, the Lead's decision) - such a stand takes the hash of its exact name, so the first `-` ends the stand token
    stok = _id_token(name) if _id_token(name) == name.strip() and not re.search(r"[-\s]", name) else ""
    return (stok or hashlib.sha1(name.encode("utf-8")).hexdigest()[:8], tok)


def role_gap_id(stand, role, packet_forms=()) -> str:
    """The id of a role card: `RA-<stand token>-<role token>` (`role_gap_tokens`). One `RA-...: <word>` answer, and one `stand gap: RA-...`
    override, can never pass two cards; the same role on the same stand gets the same id in every rehearsal."""
    stok, tok = role_gap_tokens(stand, role, packet_forms)
    return f"{ROLE_GAP_PREFIX}{stok}-{tok}"


class Rehearsal:
    """One run's inputs, read once. Each check appends findings; nothing of the story's is written.

    Two things are written, and both are the rehearsal's own: the reporter step's test report goes
    to a temp directory that is removed afterwards, and a PROVEN reporter rehearsal is kept once
    per project + command in `qa-factory/state/reporter-rehearsals.json`
    (`_record_rehearsal`, through `atomic_json`; D-0019 item 2, B-220 F11, FR-45)."""

    _declarations_read = False      # set by `_integration_keys`: were the cases' declarations looked at (F-3b); unknown says no

    def __init__(self, task_root: Path, gate: str):
        self.task_root = Path(task_root)
        self.gate = gate
        self.next_stage = GATE_STAGE[gate]
        self.pipeline = _read_json(self.task_root / "pipeline.json", {}) or {}
        self.ticket = str(self.pipeline.get("ticket") or self.task_root.name)
        self.project_root = _project_root(self.task_root)
        self.config = _read_json((self.project_root or self.task_root) / "qa-factory" / "config.json", {}) or {}
        self.findings = []
        self._doors = []     # the blocks `waiver_command` named since the last `add`; `add` takes them (see `door`)
        self._named = []     # (finding, message template, gap id): the findings whose text names a stand gap (`gap_name`)
        # What `stand_gaps.py` turns into a card: one row per precondition this stand does not
        # meet. Collected here because this is the only place that has both the case's own
        # words and the stand's answer; rendered there, because the same card is shown at gate B
        # from rows nothing in this file reads.
        self.stand_gaps = []
        # B-414 (D-0029): the gaps the ENVIRONMENT RECORD covers - a gap row with the live record row under `property`. They get
        # no card and no finding; the packet shows them as decided once, and the driver carries them into the story.
        self.covered_gaps = []
        # What a step PROVED, as opposed to what it asks. Nothing waits on these and they are
        # not findings; they are printed because a step that runs a real command and stays
        # silent when it works reads exactly like a step that never ran.
        self.info = []
        # `check_s5_toolchain` collects the project's existing tests; `check_s5_reporter` reads
        # one node id out of that same output instead of collecting a second time.
        self.collect_stdout = ""
        # The plan and the cases are read once per rehearsal: six steps ask which profile each
        # automate row belongs to, and the answer cannot change while one rehearsal runs.
        self._keyed = None
        self._automate = None
        # t-2142 PK0-4: what `check_role_accounts` carded, read by `check_case_preconditions` and `_probe_actor` (one card per fact).
        # `_role_carded`: {(stand name, role form)} the role card holds; `_account_carded`: {role form: "role" | "case" | "not_needed"} - "role" the
        # role card asks for the account, "case" the per-case card asks for its keys, "not_needed" no card exists (the person's word). Both are filled before the steps that read them.
        self._role_carded = set()
        self._account_carded = {}

    def keyed_profiles(self) -> dict:
        """`s5_profiles` for this story, computed once per rehearsal."""
        if self._keyed is None:
            self._keyed = s5_profiles(self.config, self.task_root, self.automate_rows())
        return self._keyed

    def automate_rows(self) -> list:
        """`s5_automate_rows` for this story, computed once per rehearsal."""
        if self._automate is None:
            self._automate = s5_automate_rows(self.task_root)
        return self._automate

    # --- recording -------------------------------------------------------------------------

    def door(self, block: str, stage: str = "", option: str = "accept", row: str = "") -> None:
        """Register the block a person's word passes, for the finding the next `add` writes.

        The finding carries it as `waives` - `[{block, stage, option}]` - machine data that nothing prints: whoever
        records the person's line reads the field, never a sentence (FR-12). `block` is what `waiver.split_overridden`
        matches against the message (the first 60 characters, a `"` written as `'`). `row` (D1-C2): the plan row a `product_gap` door
        is about, carried as `"row"` - machine data the recorder reads; a door with no `row` is byte-for-byte what it was."""
        self._doors.append({"block": " ".join(str(block).split())[:60].replace('"', "'"),
                            "stage": stage or self.next_stage, "option": option, **({"row": row} if row else {})})

    @staticmethod
    def word_of(option: str) -> str:
        """The word of one answer to a stand gap, from the data file (`stand_gap_words`; FR-13): `accept` ->
        `accept`, `handed` -> `run`. '' when the list cannot be read - the caller then says it in plain words."""
        try:
            import gate_brief
            return gate_brief.stand_gap_word_of().get(option, "")
        except Exception:
            return ""

    def waiver_command(self, block: str, stage: str = "", option: str = "accept") -> str:
        """The WORDS that tell a person how their word passes this block - never the command that records it.

        t-357, the owner's rule of 02.10: a person is never shown a script name, a flag or a block id; the door of a
        refusal is a line they write (`<check id>: accept`, the id the finding is listed under) and the factory
        records it. `{DOOR_ID}` is replaced with that id by `add`, which is the only place that knows it. The
        TP1-15045 lesson stands - a refusal with no door invites a person to patch the plugin - so the door is
        always in the text, in words. `option` is the answer of `stand_gap_words` the line means; the block it
        passes travels in the finding's `waives`."""
        self.door(block, stage, option)
        word = self.word_of(option)
        if option == "handed":
            return (f"to run it yourself, write `{DOOR_ID}: {word}`" if word else
                    f"to run it yourself, say so in your own words, naming `{DOOR_ID}`")
        return (f"to pass this check anyway, write `{DOOR_ID}: {word}` with your reason" if word else
                f"to pass this check anyway, say so in your own words, naming `{DOOR_ID}`, with your reason")

    def card_door(self, gap_id: str, stage: str = "") -> str:
        """The `fix` of a finding that points at a stand-gap card: the card is the door, and it carries its own words
        and its one form (`gate_brief.stand_gap_card_lines`, the same card at both gates, FR-10), so nothing is
        repeated here - and nothing of how the factory records the line (t-357). The block the line passes travels
        in the finding's `waives`, option `any`: the word the person writes picks the option."""
        self.door(f"{STAND_GAP_MATCH_PREFIX} {gap_id}", stage, "any")
        return "answer the card: write the line it shows, with one of the words it lists"

    def _exact_gap_view(self, doors: list) -> dict:
        """The pipeline `waiver.split_overridden` is shown for a finding: a `stand gap:` override is kept only when its gap id is
        EXACTLY one the finding's own doors name (B-414 R15). `split_overridden` matched by substring (before GW1-1; now by whole words, `contract.names_whole`), so `stand gap: PC-1` also
        passed the finding of `PC-10` and `stand gap: RP-web` that of `RP-webapp`: a person's word about one gap passed another.
        Every other override (a block of another kind, `*`) is unchanged; `waiver.py` itself is not touched."""
        import contract
        named = {contract.stand_gap_id(d.get("block")) for d in doors or [] if isinstance(d, dict)} - {""}
        overrides = self.pipeline.get("stage_overrides") if isinstance(self.pipeline, dict) else None
        if not isinstance(overrides, list):
            return self.pipeline
        kept = [o for o in overrides
                if not (isinstance(o, dict) and contract.stand_gap_id(o.get("match")) and contract.stand_gap_id(o.get("match")) not in named)]
        return dict(self.pipeline, stage_overrides=kept)

    def gap_name(self, gap_id: str, case: str = "") -> str:
        """The name the stand-gap CARD gives this gap, in the words a person reads (t-357 F5: one gap, one name):
        the case id when the case has this one gap (`gate_brief.stand_gap_form_ids` heads the card by it), else the
        case and the gap's own id, `TC-008, gap PC-2` (the card heads such a gap by `PC-2`). Counted over the gaps the
        rehearsal holds NOW; `add` renames the findings that carry a name again when a later gap changes the count."""
        rows = [r for r in self.stand_gaps if isinstance(r, dict)]
        if any(str(r.get("id")) == str(gap_id) and r.get("scope") in ROLE_SCOPES for r in rows):
            return str(gap_id)          # a role card is named by its own id (`RA-dev-auditor`): it holds several cases, never one
        level = next((r for r in rows if str(r.get("id")) == str(gap_id) and r.get("scope") == "level"), None)
        if level is not None:
            return f"the {level.get('contour')} tests"          # a level gap speaks of its tests, never of its id (R1)
        if not case:
            case = next((str(r.get("case") or "") for r in rows if str(r.get("id")) == str(gap_id)), "")
        if case and sum(1 for r in rows if str(r.get("case") or "") == case) == 1:
            return case
        return f"{case}, gap {gap_id}" if case else str(gap_id)

    def add(self, check: str, klass: str, message: str, fix: str = "", gap: str = "", gap_case: str = "", subject: str = "",
            **extra) -> None:
        """Write one finding. `gap` (a stand-gap id): the message holds `GAP_SLOT`, which names that gap the way its
        card does (`gap_name`) - the block key of the gap's door is never in the text a person reads; it is matched
        here from the finding's own `waives` (FR-4), so a recorded word still drops the finding.

        `subject` (R7, D1-B B6): what the finding is ABOUT (a plan row id, `test-repo`). The id is then `<check>-<token>`
        (`_id_token`), so the person's word `case_environment-TS-10: accept` keeps meeting TS-10 when another row leaves the
        list between two rehearsals; a taken id gets `-2`, `-3`, ... in `add` order. No subject: the ordinal, as before."""
        message = " ".join(str(message).split())
        doors, self._doors = self._doors, []
        # A block the person already passed by name is not raised again. Asking twice for the
        # same decision is how this factory turned one approval into four stops. The blocks the finding's own
        # door names are part of what the word is matched against (the message no longer spells them).
        try:
            from waiver import split_overridden
            blocking, _ = split_overridden([matched_text(message, doors)], self._exact_gap_view(doors), self.next_stage)
            if not blocking:
                return
        except Exception:
            pass
        found = f"{check}-{1 + sum(1 for f in self.findings if f['check'] == check)}"
        subject = _id_token(subject)         # "" (no subject, or nothing to fold into an id) keeps the ordinal
        if subject:
            taken = {f["id"] for f in self.findings}
            found = base = f"{check}-{subject}"
            for n in range(2, len(taken) + 3):
                if found not in taken:
                    break
                found = f"{base}-{n}"
        template = message.replace(DOOR_ID, found)
        self.findings.append({"id": found, "check": check, "class": klass,
                              "message": template.replace(GAP_SLOT, self.gap_name(gap, gap_case) if gap else GAP_SLOT),
                              "fix": str(fix).replace(DOOR_ID, found),
                              **({"waives": doors} if doors else {}), **extra})
        if gap:
            self._named.append((self.findings[-1], template, gap, gap_case))
        for finding, text, gap_id, case_id in self._named:
            finding["message"] = text.replace(GAP_SLOT, self.gap_name(gap_id, case_id))

    def note(self, check: str, message: str, **extra) -> None:
        """One line of what this step proved. Never a finding: `can_proceed` ignores it.
        `extra` is machine data that travels with the line (an argv the driver will run) and is
        never printed: a reader that acts on it reads the field, never the sentence (FR-12)."""
        self.info.append({"check": check, "message": " ".join(str(message).split()), **extra})

    def unavailable(self, check: str, what: str) -> None:
        self.add(check, FACTORY_DEFECT, f"rehearsal step unavailable: {what}",
                 "this step of the rehearsal is not installed in this build; the gate is shown "
                 "without it and what it would have caught may still stop the story")

    # --- gate A: 1. the decision records ----------------------------------------------------

    def check_gate_decision(self) -> None:
        """The decision the person's approval will produce, built and validated without writing.

        On TP1-15045 this is the refusal that came back three minutes after "approve":
        `critical plan row needs independent accepted design review`. The data it refused on
        was unchanged since the S4 exit."""
        check = "gate_decision"
        if not (self.task_root / "state" / "events.jsonl").is_file():
            return  # not a controller-managed story: its decision is not built by the controller
        try:
            from controller import Controller
            controller = Controller(self.task_root)
        except Exception as exc:
            self.unavailable(check, f"controller.Controller ({type(exc).__name__}: {exc})")
            return
        build = getattr(controller, "build_gate_decision", None)
        verify = getattr(controller, "check_decision", None)
        if not callable(build) or not callable(verify):
            self.unavailable(check, "Controller.build_gate_decision / Controller.check_decision")
            return
        try:
            payload = build(self.gate, "<the words the person is about to say>")
        except Exception as exc:
            # Every message that offers a person's word opens with the block text the word is
            # matched against (FR-4; `waiver.split_overridden` finds it in the message). The
            # two older wordings here did not contain theirs, so the word named in `fix` passed
            # nothing (t-238 W2); test_gate_preflight walks every such call.
            block = f"gate {self.gate} decision cannot be assembled"
            self.add(check, FACTORY_DEFECT, f"{block} — {type(exc).__name__}: {exc}",
                     self.waiver_command(block))
            return
        try:
            problems = verify(payload) or []
        except Exception as exc:
            block = f"gate {self.gate} decision validation raised"
            self.add(check, FACTORY_DEFECT, f"{block} — {type(exc).__name__}: {exc}",
                     self.waiver_command(block))
            return
        for problem in problems:
            # The factory built this request itself, so a rejected request is the factory's own
            # to repair (rebind the reviews, re-run the role) before the person is addressed.
            self.add(check, FACTORY_FIXABLE,
                     f"the gate {self.gate} decision will NOT record: {problem}",
                     "repair it before the gate: the role that owns the missing evidence is sent "
                     "back to repair it, then the rehearsal runs again")

    # --- gate A: 2. the next stage starts ----------------------------------------------------

    def check_stage_guard(self) -> None:
        check = "stage_guard"
        try:
            import stage_guard
        except Exception as exc:
            self.unavailable(check, f"stage_guard ({type(exc).__name__}: {exc})")
            return
        errors = getattr(stage_guard, "dispatch_errors", None)
        if not callable(errors):
            self.unavailable(check, "stage_guard.dispatch_errors")
            return
        try:
            problems = errors(self.pipeline, self.next_stage, assume_gate_approved=self.gate) or []
        except Exception as exc:
            self.add(check, FACTORY_DEFECT,
                     f"the stage guard could not be rehearsed for {self.next_stage}: "
                     f"{type(exc).__name__}: {exc}",
                     self.waiver_command("stage guard could not be rehearsed"))
            return
        for problem in problems:
            # The guard's own message ends with ITS command (`stage_guard.waiver_hint`: a script name, flags and
            # a block); that tail is the guard's to a role, not words for a person (t-357), so it is cut off
            # and the door is the one every other card has. A hinted message names its block itself
            # (`stage_guard.block_match`): the door carries that, so the word passes what the guard refuses.
            # `waiver_command` writes a `"` of the block as `'` (the command quoted with `"`), and
            # a message that kept the `"` no longer contained its block: the guard's own wording
            # is quoted the same way in both (t-238 W2).
            try:
                import stage_guard as _sg
                clean = _sg.without_hint(str(problem))
                hinted = clean != str(problem).strip()
                guard_block = _sg.block_match(str(problem)) if hinted else "*"
            except Exception:
                clean, guard_block = str(problem), "*"
            clean = clean.replace('"', "'")
            self.add(check, FACTORY_DEFECT,
                     f"after your approval the stage guard will refuse {self.next_stage}: {clean}",
                     self.waiver_command(guard_block if guard_block != "*" else clean))

    def check_prepare(self) -> None:
        """`prepare` is what the orchestrator calls first on the other side of the gate; if it
        raises there, the approval is already spent."""
        check = "prepare"
        try:
            from controller import Controller
            packet = Controller(self.task_root).prepare({"stage": self.next_stage})
        except Exception as exc:
            self.add(check, FACTORY_FIXABLE,
                     f"`prepare` for {self.next_stage} raises {type(exc).__name__}: {exc}",
                     "the dispatch packet is built by the factory; repair the state it reads "
                     "before the gate")
            return
        for missing in packet.get("missing_facts") or []:
            self.add(check, FACTORY_FIXABLE,
                     f"{self.next_stage} would be dispatched without {missing}",
                     f"produce {missing} before the gate")
        # Only a controller-managed story has a projection to derive a scope from. A story
        # onboarded on an older build has none, and is not refused for lacking one.
        if self.next_stage in ("S5", "S6") and (self.task_root / "state" / "events.jsonl").is_file():
            scope = (packet.get("stage_scope") or {}).get("scope") or []
            if not scope:
                self.add(check, FACTORY_FIXABLE,
                         f"the derived scope of {self.next_stage} is empty — an empty scope "
                         "passes every later check and closes the stage having tested nothing: "
                         + str((packet.get("stage_scope") or {}).get("reason") or "no reason given"),
                         "the factory's stage-scope read-out shows what the plan dispositions "
                         "derive; repair the plan rows before the gate")

    def check_role_permissions(self) -> None:
        """A role told to run a script it has no Bash for fails in the middle of its stage, with
        `No such tool available: Bash` — twice on TP1-15045."""
        check = "role_permissions"
        try:
            import role_permissions
            from hooklib import PLUGIN_ROOT
            problems = role_permissions.findings(PLUGIN_ROOT)
        except Exception as exc:
            self.unavailable(check, f"role_permissions.findings ({type(exc).__name__}: {exc})")
            return
        wanted = NEXT_ROLES.get(self.gate) or ()
        for problem in problems:
            if any(role in str(problem) for role in wanted):
                self.add(check, FACTORY_DEFECT,
                         f"a role of {self.next_stage} is told to do what its charter does not "
                         f"allow: {problem}",
                         "the charter is the factory's own file; record it as a finding about the "
                         "factory and tell the person plainly")

    def _planned_rows_count(self) -> int:
        """Plan rows that plan something: a dict row whose `disposition` is not `skip` (a row with no `disposition`
        key counts as planned). No plan file = 0; a plan that cannot be read = 0 with an `unavailable` line."""
        path = self.task_root / "work" / "test-plan.json"
        if not path.exists():
            return 0
        unread = object()
        plan = _read_json(path, unread)
        rows = plan.get("rows") if isinstance(plan, dict) else plan
        if plan is unread or not isinstance(rows, list):
            self.unavailable("case_versions", "the test plan could not be read")
            return 0
        return sum(1 for row in rows if isinstance(row, dict) and str(row.get("disposition") or "") != "skip")

    def check_cases(self) -> None:
        """Pins, the critic's roll-call and the exact replacements it wrote."""
        try:
            import case_versions
            state = case_versions.pin_state(self.task_root)
            unpinned, cases = state["unpinned"], state["cases"]
        except Exception as exc:
            self.unavailable("case_versions", f"case_versions.pin_state ({type(exc).__name__}: {exc})")
            unpinned, cases = [], None
        if cases == 0:
            # SC5-15: no case file on disk is "nothing to pin" only when the plan plans nothing. An absent plan file is
            # an empty plan (silent); an unreadable one is `unavailable`, never a pass (AR-28).
            planned = self._planned_rows_count()
            if planned:
                self.add("case_versions", FACTORY_FIXABLE,
                         f"the plan has {planned} rows but no case file is on disk; "
                         "the factory writes the cases before the gate",
                         "the factory writes the cases of the plan and pins them; "
                         "the gate must approve cases that exist")
        for item in unpinned[:8]:
            self.add("case_versions", FACTORY_FIXABLE,
                     f"a case the gate approves is not pinned at its current bytes: {item}",
                     "the factory re-pins the whole batch at the bytes on disk; "
                     "the gate must approve what is on disk")
        try:
            import critic_rollcall
        except Exception as exc:
            self.unavailable("critic_rollcall", f"critic_rollcall ({type(exc).__name__}: {exc})")
            return
        for path in critic_rollcall.findings_files(self.task_root) or []:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
            fixes = critic_rollcall.parse_fixes(text)
            errors, unapplied = ([], [])
            if fixes:
                try:
                    errors, unapplied = critic_rollcall.fix_errors(fixes, self.task_root)
                except Exception as exc:
                    self.unavailable("critic_rollcall",
                                     f"critic_rollcall.fix_errors ({type(exc).__name__}: {exc})")
            for problem in errors:
                self.add("critic_rollcall", FACTORY_FIXABLE, problem,
                         "the factory applies the critic's exact replacements by code and re-pins the case")
            for item in unapplied:
                where = str((item.get("fix") or {}).get("locator") or "").strip()
                # A replacement that matches zero or several places cannot be applied by code,
                # and the critic carries it to the gate as a debt with an owner (s4.md,
                # critic_rollcall.findings_errors). Calling that `factory_fixable` deadlocked
                # S4 on TP1-15045: `stage_done` refuses to close the stage while a
                # factory_fixable is open, and there was no repair to run — the only way out
                # was a waiver s4.md forbids asking for. A carried debt is the person's to
                # weigh; a fix `--apply-fixes` can still land stays the factory's own.
                appliable = critic_rollcall.fix_match_count(item.get("fix") or {}, self.task_root) == 1
                owed = "" if appliable else critic_rollcall.debt_owner(
                    text, str(item.get("case_id") or ""))
                self.add("critic_rollcall",
                         PERSON_DECIDES if owed else FACTORY_FIXABLE,
                         f"the critic's exact replacement for {item.get('case_id')}"
                         + (f" ({where})" if where else "")
                         + f" is not applied: {item.get('reason')}"
                         + (f"; carried as a Gate A debt — {owed}" if owed else ""),
                         "approve with the debt as it stands, or send the case back for a "
                         "repair round — your call" if owed else
                         "the factory applies it by code and re-pins the case; no designer "
                         "dispatch is needed")
            rows = critic_rollcall.parse_rollcall(text)
            derived = critic_rollcall.derive(rows) if rows else {}
            unreviewed = derived.get("unreviewed") or []
            if unreviewed:
                # Not the factory's to repair: whether a plan approved on 8 of 15 read cases is
                # good enough is the person's call, and it belongs in the packet, not after it.
                self.add("critic_rollcall", PERSON_DECIDES,
                         f"the critic reviewed {derived.get('digest')}; not reviewed: "
                         + ", ".join(str(u) for u in unreviewed[:10]),
                         "answer with your approval: accept them unread, or send the critic back")

    def check_planning_contract(self) -> None:
        check = "planning_contract"
        try:
            import planning_contract
            rows = _read_json(self.task_root / "work" / "test-plan.json", []) or []
            if isinstance(rows, dict):
                rows = rows.get("rows") or []
            mode, coverage_version = planning_contract.story_contract_mode(self.task_root)
        except Exception as exc:
            self.unavailable(check, f"planning_contract ({type(exc).__name__}: {exc})")
            return
        if not rows:
            self.add(check, FACTORY_FIXABLE, "work/test-plan.json has no rows to approve",
                     "S3 writes the plan; the gate has nothing to show without it")
            return
        try:
            problems = planning_contract.gate_plan_errors(rows, mode, coverage_version) or []
        except Exception as exc:
            self.unavailable(check, f"planning_contract.gate_plan_errors ({type(exc).__name__}: {exc})")
            return
        # Every violation is its own finding (K1): the screen the person reads is capped by
        # `brief_lines` with a count and a pointer to the whole list below, so the length of the
        # package is bounded there, and a cut here would drop violations without a word.
        for problem in problems:
            self.add(check, FACTORY_FIXABLE, f"the plan does not satisfy its own contract: {problem}",
                     "repair the plan rows (a strategist rework) before the gate")

    def check_open_questions(self) -> None:
        """Every question this gate is about to ask can actually be answered as it stands.

        On TP1-15045 gate A carried `Where must a removed node appear when the YAML has no
        layout meta?` — no quote of the source, no readings, no consequence. It was never
        answered, and the factory then tested the letter of the AC with a 1 px coordinate
        check while the implementing developer's comment on the parent ticket said the diff
        re-lays the nodes out. Put as "the source says X; reading a; reading b; what each
        costs", the same question was answered in one minute. So a bare question is the
        FACTORY's to rewrite before the person is addressed — never something the person is
        asked to repair, and never a reason to hold a story whose readiness was written by an
        older build: their own recorded word passes it, and once a waiver names the question
        id it is not raised again."""
        check = "open_questions"
        try:
            import contract
            path = contract.artifact(self.task_root, "requirements-readiness.json")
        except Exception:
            path = self.task_root / "work" / "requirements-readiness.json"
        questions = [q for q in ((_read_json(Path(path), {}) or {}).get("open_questions") or [])
                     if isinstance(q, dict)]
        if not questions:
            return
        try:
            from contract import CLAIM_KEYS, claim_mark_problem, parse_json_list, question_errors
        except Exception as exc:
            self.unavailable(check, f"contract.question_errors ({type(exc).__name__}: {exc})")
            return
        # D1-B B8: the norms-list rule (`question_errors(q, norm_ids)`) runs here too, with the register's norm rows read ONCE. A register
        # that cannot be read is a note and the rule is not applied (None: inert) - never a finding about a register nobody can read.
        norm_ids = None
        try:
            import planning_contract
            register = planning_contract.story_register_text(self.task_root)
            if not register.strip():
                raise ValueError("no register")
            norm_ids = contract.norm_row_ids(register)
        except Exception:
            self.note(check, "the register could not be read, so the norms-question rule was not checked")
        # TR2-9 (B-12): the status of a question is read from the question register, the one reader (AR-13) - an answer recorded
        # there is an answer, as much as a word kept in the question's own dict. FR-59: a register that cannot be read, or a
        # record it set aside, is a note, and the question is then checked as it stands (the safe direction: toward asking).
        import question_register
        settled_rows = [False] * len(questions)
        try:
            view = question_register.load(self.task_root)
            # B-12 F1: only the FIRST row of an id is the row the register's answer belongs to (`question_register.matches`,
            # the one rule, shared with gate_brief.still_open); a later row of the same id has no answer of its own.
            settled_rows = [question_register.settled(m) for m in question_register.matches(questions, view)]
            set_aside = sum(int(n or 0) for n in (view.get("skipped") or {}).values())
            if view.get("problems") or set_aside:
                shown = [str(p) for p in view.get("problems") or []]
                more = f" and {len(shown) - 2} more" if len(shown) > 2 else ""   # F-5: the cut at two is said out loud
                self.note(check, "the question register was read with problems (" + "; ".join(
                    shown[:2] + ([f"{set_aside} record(s) set aside"] if set_aside else [])) + more + "), so a question it does not "
                    "show as settled is checked as it stands")
        except Exception as exc:
            settled_rows = [False] * len(questions)   # F-4: the note below must be true - nothing computed above stands (FR-59: toward asking)
            self.note(check, f"the status of the questions could not be read from the question register ({type(exc).__name__}), "
                             "so every question is checked as it stands")
        keyed = None   # the question ids some case keys by meaning (`now` / `before`), read once and only when needed
        for index, question in enumerate(questions, start=1):
            if question_register.row_answered(question):
                continue  # already answered: nothing left to ask, nothing to rewrite
            if settled_rows[index - 1]:
                continue  # answered in the register (B-12): the same question is not shown again as one nobody can answer
            problems = question_errors(question, norm_ids)
            qid = str(question.get("id") or question.get("ref") or f"Q-{index}").strip()
            # HF4-7 (B7-3): a before/now question that does not say which reading is the behaviour now is the tester's to
            # fix ONLY when a case already keys its texts by meaning (`now` / `before`) on it - the condition is the data,
            # not a date: such a case cannot be tied to a reading
            unmarked = claim_mark_problem(question)
            if unmarked:
                if keyed is None:
                    keyed = set()
                    for case in self._branch_cases():
                        entries, _why = parse_json_list(case.get("question_thens"))
                        keyed.update(str(e.get("question") or "").strip() for e in entries or []
                                     if isinstance(e.get("readings"), dict)
                                     and any(k in e["readings"] for k in CLAIM_KEYS))
                if qid in keyed:
                    problems = [*problems, unmarked]
            if not problems:
                continue
            role = str(question.get("owner_role") or "the owner")
            # EVERY defect of the question in the one finding (K1): the rewrite is one dispatch,
            # and a question named by its first defect came back for the second.
            defects = problems[0] if len(problems) == 1 else f"{len(problems)} defect(s): " + "; ".join(problems)
            self.add(check, FACTORY_FIXABLE,
                     f"{qid} cannot be answered as it stands ({defects}) — "
                     "`qa-requirements-tester` rewrites it as what the source says plus the "
                     f"readings and where each comes from, before {role} is asked",
                     "the question packet goes back to qa-requirements-tester at S2, for the "
                     "question packet only; " + self.waiver_command(qid))

    def _branch_cases(self) -> list:
        """One dict per case of the story for `planning_contract.variant_errors`: its id, its
        `question_thens` line, the numbers of the items under `## Then` (the reader S5 binds
        with), and `readable: False` for a pinned case whose file is not on disk or not readable."""
        from contract import CASE_PLAN_ROW_RE, case_files, story_case_links
        out = []
        for path in case_files(self.task_root):
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                out.append({"case": Path(path).stem, "readable": False})
                continue
            front = _FRONT_MATTER_RE.match(text)
            line = re.search(r"^question_thens:[ \t]*(.*)$", front.group(1), re.MULTILINE) if front else None
            case_id = (re.search(r"^id:\s*(\S+)", text, re.MULTILINE) or [None, Path(path).stem])[1]
            numbers = []
            if line:  # only a case that branches needs S5's reader; a legacy story never imports it
                from s5_precheck import then_clauses
                numbers = [number for number, _ in then_clauses(text)]
            plan_row = CASE_PLAN_ROW_RE.search(text)    # GW1-41 (`row_owes_case`): the row this case answers
            out.append({"case": str(case_id), "readable": True,
                        "question_thens": line.group(1).strip() if line else None,
                        "thens": numbers, "plan_row": plan_row.group(1) if plan_row else "",
                        "text": text})       # GW1-41 (obligations): the case quotes the obligation ids of its row
        for link in story_case_links(self.task_root):
            raw = str(link.get("path") or "")
            if raw and not (self.task_root / raw).is_file():
                out.append({"case": str(link.get("case_id") or raw), "readable": False})
        return out

    def check_unraised_questions(self) -> None:
        """A Then still `unknown` with the ref `raise` at gate A (O4, t-227, P20).

        The case designer has no Bash, so it writes the question as a `raise_questions` line and the Then
        as `unknown` with the ref `raise`; the S4 exit (`critic_rollcall.py --apply-fixes`) raises the
        question, writes its id into the case and re-pins it. A `raise` that is still there means that step
        did not run (or could not raise it), and the person would be shown a Then that waits for an answer
        nobody asked them for: the invariant is that no `unknown` reaches gate A without its question.
        Every finding is `factory_fixable` (the factory's own step, never the person's question); a
        person's word recorded at S4 passes it. Writes nothing."""
        check = "unraised_questions"
        try:
            import contract
            files = list(contract.case_files(self.task_root))
        except Exception as exc:
            self.unavailable(check, f"the cases could not be listed ({type(exc).__name__}: {exc})")
            return
        block = "question left unraised"
        for path in files:
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            entries, _why = contract.then_oracles_from_text(text)
            left = sorted(e["then"] for e in entries or [] if str(e.get("ref") or "").strip() == contract.RAISE_REF
                          and isinstance(e.get("then"), int) and not isinstance(e.get("then"), bool))
            if not left:
                continue
            case_id = (contract.front_line(text, "id") or Path(path).stem).strip().strip("\"'")
            self.add(check, FACTORY_FIXABLE,
                     f"{block} - {case_id}: Then {', '.join(str(n) for n in left)} says `unknown` with the ref "
                     f"`{contract.RAISE_REF}`, so the question that would ask the person was never raised and the "
                     "Then reaches the gate with no door for an answer",
                     "the factory's own to repair, not a question for you: the factory raises the question "
                     "and re-pins the case itself (no designer dispatch); " + self.waiver_command(block),
                     where=case_id)

    def check_question_branches(self) -> None:
        """What each answer to an open register question DOES, written before the person sees it.

        TP1-13797 (cmp1, B-216): the person answered four of five questions by letter at gate
        A; TS-6's disposition and TC_006's Then stayed as authored and the row's reason went on
        naming a settled question. A row that rests on a question now carries `question_refs` and
        `if_answered`, a case carries `question_thens` (`artifact-contract-plan.md`,
        `artifact-contract.md`); the pure checks are `planning_contract.variant_errors`.

        Every finding is `factory_fixable`: the authors wrote the branch, so an author's rework
        repairs it and the person is never asked. A story with no branch field anywhere is never
        a finding, and a register that cannot be read leaves one INFO line and no finding. The
        person's word recorded at S4 (`--block "question branches"`) passes it. Writes nothing."""
        check = "question_branches"
        try:
            import planning_contract
            path = planning_contract.story_plan_path(self.task_root)
            rows = (_read_json(path, []) or []) if path else []
            if isinstance(rows, dict):
                rows = rows.get("rows") or []
            mode, coverage_version = planning_contract.story_contract_mode(self.task_root)
            cases = self._branch_cases()
        except Exception as exc:
            self.unavailable(check, f"the plan and the cases could not be read ({type(exc).__name__}: {exc})")
            return
        # t-261 (O12): a plan created on/after the oracle cutoff is under the branch contract with no field
        created = planning_contract.plan_created(self.task_root)
        if not planning_contract.has_branch_fields(rows, cases, created):
            return  # written before branches existed: nothing to check and nothing to say
        why = ""
        try:
            import question_register
            view = question_register.load(self.task_root)
            questions = list(view.get("questions") or [])
            if not questions:
                why = ((view.get("problems") or [""])[0]
                       or ("the story has no work/requirements-readiness.json"
                           if not view.get("register_present") else "the register lists no question"))
        except Exception as exc:
            questions, why = [], f"{type(exc).__name__}: {exc}"
        if not questions:
            self.note(check, "question branches were not checked: the register's questions could "
                             f"not be read ({why})")
            return
        try:
            found = planning_contract.variant_errors(
                rows, questions, cases, plan_contract_mode=mode, coverage_contract_version=coverage_version,
                plan_created=created, at_cases_stage=True)
        except Exception as exc:
            self.unavailable(check, f"planning_contract.variant_errors ({type(exc).__name__}: {exc})")
            return
        for item in found:
            message = "question branches - " + item["message"]
            try:
                from waiver import split_overridden
                # ONE word passes the finding wherever it was recorded (t-721 3.6): at S4 (the block quoting the
                # S4 message), or at S3 in either form S3 printed it - the message or the `where: it rests on`
                # line. One call per form and per line: a record that lifts one form must not leave the other
                # blocking. Substring comparison is the writer's (`waiver.py`), unchanged.
                if any(not split_overridden([line], self.pipeline, stage)[0]
                       for line, stage in ((message, "S4"), (item["message"], "S3"),
                                           (planning_contract.missing_branch_line(item), "S3"))):
                    continue  # the person already passed this block, where it stops the stage
            except Exception:
                pass
            if item["owner"] == "strategist":
                door = (f"rows {item['where']} go back to qa-test-strategist at S3, with this "
                        "finding as the reason")
            else:
                door = (f"cases {item['where']} go back to qa-case-designer at S4, with this "
                        "finding as the reason")
            self.add(check, FACTORY_FIXABLE, message,
                     f"the factory's own to repair, not a question for you: {door}; "
                     + self.waiver_command("question branches", "S4"),
                     kind=item["kind"], where=item["where"], question=item["question"])

    # --- gate A: 3. the environment of the next stage -----------------------------------------

    def check_vcs(self) -> None:
        """The dirty tree and the branch: one question, asked once, inside the packet.

        On TP1-15045 this arrived as a separate stop AFTER the gate, although `--probe-vcs`
        knew it at S0."""
        check = "vcs"
        root = self.project_root
        if root is None:
            return
        tests_root = (root / str(self.config.get("tests_root") or ".")).resolve()
        if not tests_root.is_dir():
            return
        branch = _git(tests_root, "rev-parse", "--abbrev-ref", "HEAD")
        if branch is None:
            return  # not a working tree, or no git here: nothing to decide
        status = _git(tests_root, "status", "--porcelain")
        head = _git(tests_root, "rev-parse", "HEAD") or ""
        dirty = outside_factory_home([line for line in (status or "").splitlines() if line.strip()],
                                     _factory_home_in_repo(root, tests_root))
        # GW1-43: the door of both branches is the block `test repository state: <HEAD>` - the HEAD, not the number of changes,
        # so a word stands while S5 writes its own tests into this tree, and a moved HEAD (other code) asks again. No HEAD,
        # no door (as before).
        block = f"test repository state: {head[:12]}" if head else ""
        if dirty:
            self.add(check, PERSON_DECIDES,
                     f"the test repository has {len(dirty)} uncommitted change(s) on branch "
                     f"`{branch}` (HEAD {head[:12]}), and {self.next_stage} writes test code into "
                     f"it: {', '.join(porcelain_path(line) for line in dirty[:5])}"
                     + (f" and {len(dirty) - 5} more" if len(dirty) > 5 else ""),
                     "answer with your approval: commit, stash, or go on on this branch"
                     + (f" - {self.waiver_command(block)}" if block else ""), subject="test-repo")
        else:
            self.add(check, PERSON_DECIDES,
                     f"{self.next_stage} will write test code on branch `{branch}` "
                     f"(HEAD {head[:12]}), the branch this checkout is on",
                     "answer with your approval: this branch, or name another"
                     + (f" - {self.waiver_command(block)}" if block else ""), subject="test-repo")

    def check_stand(self) -> None:
        """Only what an existing probe already answered. A gate is not the place to start a
        network probe, and a stale `unknown` is not a refusal."""
        check = "environment"
        root = self.project_root
        if root is None:
            return
        # t-261: through the layout (`runtime_paths.readiness`), not by hand (FR-37): a project onboarded
        # after the two-folder layout keeps it in `state/`, an older one beside the config - both are read.
        import runtime_paths
        readiness = _read_json(runtime_paths.readiness(root))
        if not isinstance(readiness, dict):
            self.add(check, FACTORY_FIXABLE,
                     "no readiness.json — the stand of the next stage was never probed",
                     "the factory writes its readiness record, probing the version control, before the gate")
            return
        caps = readiness.get("capabilities") or {}
        for name in ("environment", "test_repo"):
            entry = caps.get(name) if isinstance(caps.get(name), dict) else {}
            if str(entry.get("status") or "") == "missing":
                self.add(check, PERSON_DECIDES,
                         f"the last probe of `{name}` says it cannot be used: "
                         + " ".join(str(entry.get("note") or "").split())[:160],
                         "answer with your approval: fix the stand first, or let the stage run "
                         "and report what it could not execute")

    def check_case_environment_gaps(self) -> None:
        """Gaps the plan itself declares in structured fields — never parsed out of prose.

        `coverage_obligations[].parts[].status == unresolved` and an observation surface with
        `status: gap` are the plan's own machine-readable way of saying "this cannot be
        observed here". On TP1-15045 exactly one of them was the missing non-owner account,
        and it reached the gate as a sentence nobody had checked."""
        check = "case_environment"
        try:   # D1-C2: the product gaps the person already recorded (the delivery side's one reader); an unreadable carrier suppresses nothing
            import check_delivery
            decided = {g["requirement"] for g in check_delivery._read_product_gaps(self.task_root)[0]}
        except Exception:
            decided = set()
        try:     # the closed word of the product-gap door, read once per call; "" (the block unreadable) offers no door
            import gate_brief
            word = gate_brief.finding_door_word_of().get("product_gap", "")
        except Exception:
            word = ""
        rows = _read_json(self.task_root / "work" / "test-plan.json", []) or []
        if isinstance(rows, dict):
            rows = rows.get("rows") or []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            held = []        # the obligations of this row that carry a gap: (obligation, parts, surfaces)
            for obligation in row.get("coverage_obligations") or []:
                if not isinstance(obligation, dict):
                    continue
                parts = [str(p.get("part_id") or "?") for p in (obligation.get("parts") or [])
                         if isinstance(p, dict) and str(p.get("status") or "") == "unresolved"]
                surfaces = [str(s.get("id") or "?") for s in
                            ((obligation.get("observation_contract") or {}).get("surfaces") or [])
                            if isinstance(s, dict) and str(s.get("status") or "") == "gap"]
                if parts or surfaces:
                    held.append((obligation, parts, surfaces))
            row_id = str(row.get("id") or "").strip()
            # D1-C2 (Q1-a): the product-gap door only for a row that names a requirement it blocks, and only when the closed word
            # list can say the word (FR-9: no word is offered that code cannot read). Silent only when EVERY requirement of the
            # row is already a recorded product gap (FR-7), and then said ONCE for the row; any other row still asks. The row's
            # requirements are read once per row, the word once per call (F7 t-1752)
            reqs = []
            if held:
                try:
                    import product_gaps
                    reqs = product_gaps.row_ids(row)
                except Exception:
                    pass
            if reqs and set(reqs) <= decided:
                self.note(check, f"{row_id}: the product gap you recorded for {', '.join(reqs)} stands; not asked again")
                continue
            for obligation, parts, surfaces in held:
                gap = " ".join(str(obligation.get("remaining_gap") or "").split())[:180]
                # R7: the id is the ROW's (`case_environment-TS-10`); a row with several gapped obligations adds the obligation's own
                # id when it has one, so each of them is its own item and an answer never lands on a neighbour (E-B5)
                subject = row_id
                if row_id and len(held) > 1 and str(obligation.get("obligation_id") or "").strip():
                    subject = f"{row_id}-{str(obligation.get('obligation_id')).strip()}"
                fix = "answer with your approval: accept the gap, or hold the row back"
                if reqs and word:
                    self.door(f"product gap {subject or row_id}", option="product_gap", row=row_id)
                    fix = (f"answer with your approval: accept the gap (the stand cannot), `{DOOR_ID}: {word}` (the product has no "
                           "such function), or hold the row back")
                self.add(check, PERSON_DECIDES,
                         f"{row.get('id') or '?'} carries a declared gap the next stage cannot "
                         f"close ({', '.join(parts + surfaces)}): " + (gap or "no reason recorded"), fix, subject=subject)

    # --- gate A: 3b. each account a manual check signs in as (RN1-10 b) --------------------------

    def _actors_of_manual_cases(self) -> dict:
        """{actor: [case ids]} of the `manual-agent` cases of the plan: the `stand_account` role of each precondition of
        `kind: "account"` (the text a `--session` call is given as the actor). Read through `parse_preconditions`, the one
        reader of the line; a line that cannot be read is left to `check_case_preconditions`, which says so once."""
        import contract
        wanted = [case for case, _ in plan_rows_of(self.task_root, ("manual-agent",))]
        if not wanted:
            return {}
        index = contract.case_index(self.task_root)
        out: dict = {}
        for case in wanted:
            path = (index.get(case) or {}).get("path")
            try:
                raw = case_preconditions_raw(Path(path).read_text(encoding="utf-8", errors="replace")) if path else None
                items, errors = parse_preconditions(raw) if raw is not None else ([], [])
            except (OSError, ValueError):
                continue
            if errors:
                continue
            for item in items:
                name, spec = next(iter(item["check"].items()))
                if item.get("kind") == "account" and name == "stand_account" and str(spec).strip():
                    out.setdefault(str(spec).strip(), []).append(case)
        # TR3-10 D8 (F14): the project's EXTRA accounts of a role a manual case names are probed too, so `walk_pool.pool_of` can keep
        # only the handles with an `ok` row. `self._extra_accounts` = {handle: (role, position)} tells `_probe_actor` which rows are
        # extras (a failed extra is a note and "dropped", never a question). The supply is read ONLY through its reader (AR-13); its
        # notes are not a refusal here (a bad block reads as no extras). Obtain users are not probed (they open as guest).
        self._extra_accounts = {}
        if not out:
            return out
        import config_contract
        accounts = config_contract.walk_supply(self.config)[0].get("accounts")
        more = accounts.get("more_accounts") if isinstance(accounts, dict) else None
        if not isinstance(more, dict) or not more:
            return out
        import manual_capture as MC
        import walk_pool
        stand = self._selected_environment()
        roles = stand.get("credentials_by_role") if isinstance(stand, dict) and isinstance(stand.get("credentials_by_role"), dict) else {}

        def pair_of(handle):
            try:
                return tuple(MC.resolve_actor(self.config, stand, handle, self.task_root)[:2])
            except ValueError:
                return None
        taken = {pair for pair in (pair_of(actor) for actor in out) if pair}
        for actor, cases in list(out.items()):
            real = "default" if actor == "default" else (account_role(roles, actor) or actor)
            for position, handle in enumerate(walk_pool._by_role(more, real) or [], 1):
                if handle in self._extra_accounts:          # listed under two roles: probed once, for the cases of both
                    out[handle] = out[handle] + [c for c in cases if c not in out[handle]]
                    continue
                pair = pair_of(handle)
                if handle in out or (pair and pair in taken):        # the base handle itself, or the same key pair: one account
                    continue
                if pair:
                    taken.add(pair)
                out[handle] = list(cases)
                self._extra_accounts[handle] = (actor, position)
        return out

    @staticmethod
    def _cases_phrase(cases: list) -> tuple:
        """`(the cases as the card's lines name them, the verb that follows)`: up to `ROLE_NAMED` ids (explained on the card's
        `the test:` line, which comes first), else their number. Never names an id the `the test:` line does not."""
        ids = [str(c) for c in cases]
        if len(ids) > ROLE_NAMED:
            return f"the {len(ids)} cases", "are"
        named = ids[0] if len(ids) == 1 else ", ".join(ids[:-1]) + " and " + ids[-1]
        return named, "is" if len(ids) == 1 else "are"

    @classmethod
    def _role_options(cls, variant: str, role: str, stand: str, cases: list) -> list:
        """The answers of a role card, each with its three price lines (human-questions.md item 6; t-2142 §3 (2), fork FK-9 (a)).
        An option of an offered word (`theirs`, `accept`) carries `says` - the card writes the word from the data file; any other carries
        `head`, the person's own words on a line of their own. Pure text: nothing here reads or records anything."""
        named, are = cls._cases_phrase(cases)
        it_they = "it checks" if len(cases) == 1 else "they check"
        accept = {"option": "accept", "says": "only this story",
                  "factory": f"nothing runs for {named}.",
                  "you": f"this answer; the next story that needs \"{role}\" on \"{stand}\" asks again.",
                  "story": f"{named} {are} reported as not run on this stand; what {it_they} stays unverified and is an open item of the "
                           "report; delivery: not known."}
        if variant == "twins":
            return [{"option": "theirs",
                     "says": "you remove the wrong one from the stand's entry in qa-factory/config.json by hand (the factory never edits it)",
                     "factory": "the gate is rehearsed again after your change; no agent works.",
                     "you": "this answer, and that edit of your project's settings file.",
                     "story": f"{named} {are} checked as the account that stays; delivery unchanged."}, accept]
        return [{"option": "keys",
                 "head": "the names of the two variables in the project's env file that hold its login and password (never the values), "
                         f"in your own words on a line of their own: kept for \"{stand}\" from now on, the next stories do not ask",
                 "factory": "a record only, then the gate is rehearsed again; no agent works.",
                 "you": "this answer, and putting the login and password into the env file yourself if they are not there yet.",
                 "story": f"{named} {are} checked as \"{role}\"; delivery unchanged."},
                accept,
                {"option": "not_a_role", "head": "\"not a role of this product\", in your own words on a line of their own",
                 "factory": "a record for the whole project; no agent works.",
                 "you": "this answer; to undo it, say so in a later story.",
                 "story": f"{named} {are} reported as not run with your words as the reason, and later stories report the cases that need "
                          f"\"{role}\" the same way without asking; delivery: not known."}]

    @staticmethod
    def _confirm_options(role: str) -> list:
        """The answers of the confirm card (§3 (6)): in the person's own words, naming the role; none is a word code reads."""
        return [{"option": "yes", "head": "yes, it is a role of the product",
                 "factory": "a record for the whole project; no agent works.", "you": "this answer.",
                 "story": f"unchanged; later stories show \"{role}\" as a confirmed role; delivery unchanged."},
                {"option": "no", "head": "no, it is not (say what it is instead, if it has another name)",
                 "factory": "a record for the whole project; no agent works.", "you": "this answer, and the other name if it has one.",
                 "story": f"this story's plan stays as it is; later stories do not show \"{role}\" as a role; delivery unchanged."},
                {"option": "leave", "head": "leave it", "factory": "nothing runs.",
                 "you": f"nothing more now; you are asked again in the next story whose plan names \"{role}\".",
                 "story": "unchanged; delivery unchanged."}]

    def _answered_cases(self, rows: list, cases: list) -> set:
        """The cases of one role the person already answered in this story, by the two existing readers (t-2142 §3 (2), N5): an `accept as
        blocked` APPLIED through the per-case question (`stand_gaps.level_applied`), or a LIVE `accept` on the case's own card for this
        account item (`stand_gaps.decisions`, keyed by `precondition_gap_id`) or on its carry key. A revoked record accepts nothing (the
        reader drops it); a read that fails drops nothing - toward asking. Pure."""
        import stand_gaps
        done = set()
        try:
            applied = stand_gaps.level_applied(self.task_root, {"cases": list(cases)})
            done.update(applied or [])
        except Exception:
            pass
        try:
            taken = {key: v for key, v in stand_gaps.decisions(self.task_root).items() if v.get("option") == "accept"}
            for row in rows:
                if str(row["id"]) in taken or any(stand_gaps.names_case({"case_id": key}, row["case"]) for key in taken):
                    done.add(row["case"])
        except Exception:
            pass
        return done

    def check_role_accounts(self) -> None:
        """ONE card per (stand, role) a case of the story needs an account for and the project holds none (t-2142 PK0-4; the owner's
        word: a question once answered is not asked in every story and not once per case). Joins three DATA readers and judges nothing:
        the cases' own declarations (`stand_gaps.declared_preconditions`: `{"stand_account": R}`), the registry and the config
        (`project_knowledge.state`: config first) and the answers already given in this story (`level_applied`, `decisions`).

        A role whose account the project holds asks nothing here (an earlier answer the person gave is said once, in one note). A
        role the person said is `not_needed` (a live registry row) asks nothing either: its cases go to `covered_gaps` (`_cover_not_needed`,
        the "decided once" road; the registry unreadable, a revoked row or a later `known` row ask as any other role). The role card is
        a ROW of `self.stand_gaps` (the road the per-case cards use) with ONE finding whose lead is the question and whose door is the
        card; the role's account items leave the per-case cards (`_role_carded`), and an `unmet` actor of the sign-in probe is a note,
        not a second card (`_account_carded`). A noticed role this story's plan names gets the confirm card: a row, no finding - silence
        keeps it unconfirmed (FK-10). The registry is only read. Everything is worked out first (`_plan_role_accounts`: the rows, the
        leads) and written last (`_write_role_accounts`), and a raise while writing takes back everything written, so a card is never
        left without its finding and the per-case cards stay as they were."""
        if self.project_root is None:
            return
        import project_knowledge as PK
        plan = self._plan_role_accounts(PK)
        mark = {"stand_gaps": len(self.stand_gaps), "findings": len(self.findings), "covered_gaps": len(self.covered_gaps),
                "info": len(self.info), "named": len(self._named), "doors": list(self._doors),
                "role_carded": set(self._role_carded), "account_carded": dict(self._account_carded)}
        try:
            self._write_role_accounts("role_accounts", plan)
        except Exception:
            del self.stand_gaps[mark["stand_gaps"]:], self.findings[mark["findings"]:], self.covered_gaps[mark["covered_gaps"]:]
            del self.info[mark["info"]:], self._named[mark["named"]:]
            self._doors, self._role_carded, self._account_carded = mark["doors"], mark["role_carded"], mark["account_carded"]
            raise

    def _declared_role_forms(self) -> dict:
        """`{role form: {"role": the role as a case wrote it first, "rows": its declared `stand_account` rows}}`: the cases' own
        declarations, read by `stand_gaps.declared_preconditions`; `default`, `env:...` and `created:...` are no product role."""
        import stand_gaps
        from config_contract import reserved_role
        declared = [r for r in stand_gaps.declared_preconditions(self.task_root)
                    if isinstance(r.get("check"), dict) and isinstance(r["check"].get("stand_account"), str)]
        by_form: dict = {}
        for row in declared:
            spec = row["check"]["stand_account"].strip()
            if spec and not reserved_role(spec):
                by_form.setdefault(_role_form(spec), {"role": spec, "rows": []})["rows"].append(row)
        return by_form

    def _plan_role_accounts(self, PK) -> dict:
        """Read and join, write nothing: `{"stand", "planned" (each with its finished row, id and lead), "acting", "carded_case",
        "problem", "decided_not", "confirm"}` for `_write_role_accounts` (F6: a failure here leaves the rehearsal as it was)."""
        root = self.project_root
        stand = self._selected_environment()
        stand_name = str(stand.get("name") or "").strip() if stand else ""
        rehearsal_cfg = self.config.get("gate_rehearsal") if isinstance(self.config.get("gate_rehearsal"), dict) else {}
        will_ask_keys = not rehearsal_cfg.get("skip_preconditions")        # the per-case step (project_root is set here)
        by_form = self._declared_role_forms()
        planned, acting, carded_case, problem = [], [], [], ""
        decided_not = []        # PK0-9: [(form, role, cases, the registry row)] - a live `not_needed` row decides, no card
        ctx = None
        if stand_name and by_form:
            held = PK.roster(root, self.config, stand_name)
            in_roster = {_role_form(e["role"]) for e in held.get("elements") or []}
            for form, entry in by_form.items():
                role = entry["role"]
                said = PK.state(root, PK.ROLES_KEY, "", role)
                if said["state"] == PK.NOT_NEEDED and isinstance(said.get("row"), dict):
                    # (2b): the person's latest word on the role is "not a role of this product" - it wins over a config account (the
                    # roster reads the same); an unreadable registry, a revoked row or a later `known` row never get here (they ask)
                    cases = list(dict.fromkeys(str(r["case"]) for r in entry["rows"]))
                    answered = self._answered_cases(entry["rows"], cases)
                    decided_not.append((form, role, [c for c in cases if c not in answered], said["row"]))
                    continue
                st = PK.state(root, PK.ACCOUNTS_KEY, stand_name, role, cfg=self.config)
                problem = problem or str(st.get("problem") or "") or str(said.get("problem") or "")
                if st["state"] == PK.KNOWN:
                    if st.get("row") is not None:
                        acting.append(st["row"])
                    if will_ask_keys:
                        ctx = ctx or self._precondition_ctx(rehearsal_cfg)
                        if self._stand_account(role, ctx)[0] == "unmet":
                            carded_case.append(form)
                    continue
                cases = list(dict.fromkeys(str(r["case"]) for r in entry["rows"]))
                answered = self._answered_cases(entry["rows"], cases)
                cases = [c for c in cases if c not in answered]
                if cases:
                    planned.append({"form": form, "role": role, "cases": cases, "in_roster": form in in_roster,
                                    "variant": "twins" if st.get("twins") else "malformed" if st.get("malformed") else "missing",
                                    "twins": list(st.get("twins") or [])})
        # the packet's forms: the carded roles and the covered ones, so both kinds of id are made against the same set (D1)
        forms = [p["form"] for p in planned] + [form for form, *_rest in decided_not]
        where = ""
        if planned or any(cases for _f, _r, cases, _row in decided_not):
            ctx = ctx or self._precondition_ctx(rehearsal_cfg)
            # F5: `where` is the PATH the apply guard and `remedy_path` read - the file the runner reads; words only when the project names none
            where = self._place_of(ctx["files"], ctx["how"])
            for plan in planned:
                plan.update(self._role_card_plan(PK, stand_name, plan, forms, where))
        return {"stand": stand_name, "planned": planned, "acting": acting, "carded_case": carded_case, "problem": problem,
                "decided_not": decided_not, "forms": forms, "where": where, "confirm": self._confirm_rows(PK, root)}

    def _role_row(self, stand_name: str, role: str, cases: list, forms: list, where: str, fact: dict, variant: str, in_roster: bool) -> dict:
        """The row of a role gap, the ONE builder of the role card (`_role_card_plan`) and of the covered role (`_cover_not_needed`): the id by
        `role_gap_id`, the remedy `where` the env-file path (words only when the project names none), the offers by the variant. Pure."""
        gap_id = role_gap_id(stand_name, role, forms)
        return {"id": gap_id, "scope": "role", "role": role, "stand": stand_name, "case": "", "cases": cases, "kind": "account",
                "check": {"stand_account": role}, "fact": fact,
                "remedy": {"kind": "credential", "where": where or "the project's env file", "where_words": "the project's env file",
                           "change": f"two variables for the role {role}",
                           "offers": ["theirs", "accept"] if variant == "twins" else ["accept"]},
                "options": self._role_options(variant, role, stand_name, cases), "variant": variant,
                "in_roster": in_roster, "state": "unmet", "detail": ""}

    def _role_card_plan(self, PK, stand_name: str, plan: dict, forms: list, where: str) -> dict:
        """The finished card of one planned role: `{"gap_id", "row", "lead", "fact"}`. Pure (the row by `_role_row`, the lead by `_role_lead`)."""
        role, cases = plan["role"], plan["cases"]
        fact = {"key": PK.ACCOUNTS_KEY, "environment": stand_name, "element": role}
        if plan["twins"]:
            fact["twins"] = plan["twins"]
        row = self._role_row(stand_name, role, cases, forms, where, fact, plan["variant"], plan["in_roster"])
        return {"gap_id": row["id"], "row": row, "fact": fact,
                "lead": self._role_lead(plan["variant"], stand_name, role, len(cases), row["id"])}

    def _write_role_accounts(self, check: str, plan: dict) -> None:
        """Write what `_plan_role_accounts` worked out: the covered roles, then each role card with its finding, the confirm cards and the
        notes. `check_role_accounts` takes the whole write back if anything here raises."""
        stand_name = plan["stand"]
        for form, role, cases, row in plan["decided_not"]:
            self._role_carded.add((stand_name, form))          # its account items leave the per-case cards too: nothing here is asked
            self._account_carded[form] = "not_needed"          # and the sign-in probe says so, not "waits for the card" (no card exists)
            if cases:
                self._cover_not_needed(check, stand_name, role, cases, row, plan["forms"], plan["where"])
        for card in plan["planned"]:
            self.stand_gaps.append(card["row"])
            self._role_carded.add((stand_name, card["form"]))
            self._account_carded[card["form"]] = "role"
            self.add(check, PERSON_DECIDES, card["lead"], self.card_door(card["gap_id"]), gap=card["gap_id"],
                     subject=card["gap_id"][len(ROLE_GAP_PREFIX):], cases=card["cases"], fact=card["fact"])
        for form in plan["carded_case"]:
            self._account_carded.setdefault(form, "case")
        self.stand_gaps.extend(plan["confirm"])
        if plan["problem"]:
            self.note(check, "What you told the factory in earlier stories could not be read this time, so only the project's own settings "
                             "were used to find the accounts of this story's roles; a role with no account there is asked.", problem=plan["problem"])
        import project_knowledge as PK
        line = PK.acting_line(plan["acting"])
        if line:
            self.note(check, line, mark=ACCOUNT_MARK)          # the marker is the machine field `mark`, never the text a person reads

    def _cover_not_needed(self, check, stand_name: str, role: str, cases: list, row: dict, forms: list, where: str = "") -> None:
        """PK0-9 (§3 (2b)): a role the person said is not a product role raises no card and no finding. The role card's row goes to
        `covered_gaps` - the "decided once" road (B-414) - with the registry row under `property` (`record: project_knowledge`), so the
        driver's existing carry reports the role's cases as not run, the packet says so in one line, and `ask again` takes it back."""
        import stand_gaps
        gap = self._role_row(stand_name, role, cases, forms, where, {"key": "product.roles", "environment": "", "element": role},
                             "missing", False)
        gap_id = gap["id"]
        gap["property"] = stand_gaps.pk_property(row, gap_id)
        gap["case_titles"] = stand_gaps.case_titles_of(self.task_root, cases)         # AR-21: the titles travel with the gap (B2)
        self.covered_gaps.append(gap)
        self.note(check, f"`{gap_id}`: not asked - {stand_gaps.covered_says(gap)} ({row.get('id')})")

    def _role_lead(self, variant: str, stand: str, role: str, count: int, gap_id: str) -> str:
        """The lead of a role card's finding: the fact and the question, at most `BRIEF_CUT` characters once `GAP_SLOT` is the gap's name
        (the packet cuts a finding there, so the question must be inside it). The stand and the role are clipped to `ROLE_NAME_CLIP`, and
        further when the line would still be longer; the case count says how many cases wait. The lead names no case id, so no per-case
        block can match it - its door is the gap id (`card_door`)."""
        twins = variant == "twins"
        plural, verb = ("" if count == 1 else "s"), ("s" if count == 1 else "")
        forms = [
            f"{GAP_SLOT} — a card at this gate: the stand \"{{s}}\" "
            + ("records two accounts the role \"{r}\" could mean; which one is it?" if twins else
               f"has no account for the role \"{{r}}\", which {count} case{plural} need{verb}; which account should the factory use?"),
            f"{GAP_SLOT}: the stand \"{{s}}\" "
            + ("records two accounts the role \"{r}\" could mean; which one is it?" if twins else
               f"has no account for the role \"{{r}}\", which {count} case{plural} need{verb}; which account should the factory use?"),
            f"{GAP_SLOT}: " + ("two accounts for \"{r}\" on \"{s}\"; which one is it?" if twins else
                               "no account for \"{r}\" on \"{s}\"; which account should the factory use?"),
            # the last form names no gap: an id of any length (it is the lossless token of the names) can leave no room for the question
            # inside `BRIEF_CUT`, and the card's own heading names the id (F8)
            ("two accounts for \"{r}\" on \"{s}\"; which one is it?" if twins else
             "no account for \"{r}\" on \"{s}\"; which account should the factory use?")]

        def clip(text: str, n: int) -> str:
            return text if len(text) <= n else text[:max(n - 1, 1)].rstrip() + "…"
        s, r = clip(stand, ROLE_NAME_CLIP), clip(role, ROLE_NAME_CLIP)
        for position, form in enumerate(forms):
            room = BRIEF_CUT - len(form.format(s="", r="").replace(GAP_SLOT, gap_id))
            if room >= len(s) + len(r) or room >= 16 or position == len(forms) - 1:
                if room < len(s) + len(r):
                    half = max(room // 2, 4)
                    s, r = clip(s, max(min(len(s), half), 4)), clip(r, max(room - min(len(s), half), 4))
                return form.format(s=s, r=r)
        return forms[-1].format(s=clip(stand, 4), r=clip(role, 4))

    def _confirm_rows(self, PK, root) -> list:
        """The confirm card rows (§3 (6)): ONE per noticed role (`noticed_unconfirmed`) that the strategist's `product_roles` names in THIS
        story - a noticed role this story does not name is not shown. No finding: the card does not hold the gate. [] when nothing is
        noticed, the form names no role, or the registry cannot be read (an unknown is not shown as a fact)."""
        out = []
        roles, _reason = PK.story_roles(self.task_root)
        seen = set()
        for item in roles:
            st = PK.state(root, PK.ROLES_KEY, "", item["role"])
            role = item["role"]
            if st["state"] != PK.NOTICED or _role_form(role) in seen:
                continue
            seen.add(_role_form(role))
            _stok, tok = role_gap_tokens("", role)
            where = " ".join(str(item.get("where") or "").split())[:160]
            sentence = (f"the plan checks \"{role}\" as a separate role" + (" (no sign-in)" if item.get("sign_in") == "none" else "")
                        + (f", from {where}" if where else ""))
            out.append({"id": f"{PRODUCT_ROLE_PREFIX}{tok}", "scope": "product_role", "role": role, "stand": "", "case": "", "cases": [],
                        "kind": "role", "what": sentence, "check": {}, "remedy": {"offers": []},
                        "fact": {"key": PK.ROLES_KEY, "environment": "", "element": role}, "options": self._confirm_options(role),
                        "variant": "noticed", "in_roster": False, "state": PK.NOTICED, "detail": ""})
        return out

    def check_actor_sign_in(self) -> None:
        """Prove, for EVERY account a manual case signs in as, that the stand lets it in (RN1-10 b, FK-2 a, FK-6 a): one real
        browser sign-in per account by `manual_capture.sign_in` - the ONE sign-in of a manual capture (AR-13, AR-15) - in a
        throwaway browser context, and the answer written to `state/sign-in-probe.json`, keyed by the account text as a
        `--session` call is given it (`manual_capture.sign_in_row` reads it back; S6 refuses a session without an `ok` row).

        Outcomes of a row: `ok` only after the sign-in LANDED; `failed` - submitted and the stand did not let the account in
        (the person's: three answers); `not_proved` - the keys are not where the runner reads them (the person's), or the
        project's recipe does not fit the page / no recipe / no browser (the factory's). Neither `failed` nor `not_proved` is
        ever a pass (AR-28). One account whose keys are missing never stops the probe of another (E8). Nothing is written, and no
        browser is opened, when no manual case names an account. The file is rewritten whole each run: an `ok` of an earlier
        run never outlives the run that no longer proves it."""
        if self.project_root is None:
            return
        actors = self._actors_of_manual_cases()
        if not actors:
            return
        import manual_capture as MC
        rehearsal_cfg = self.config.get("gate_rehearsal") if isinstance(self.config.get("gate_rehearsal"), dict) else {}
        ctx = self._precondition_ctx(rehearsal_cfg)
        stand = self._selected_environment()
        rows = {actor: self._probe_actor(MC, actor, cases, ctx, stand) for actor, cases in actors.items()}
        from event_store import atomic_json
        path = self.task_root.joinpath(*MC.SIGN_IN_PROBE)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(path, rows)

    def _probe_actor(self, MC, actor: str, cases, ctx, stand) -> dict:
        """The row of `state/sign-in-probe.json` for ONE account (F10: the per-actor body of `check_actor_sign_in`). What was found
        is told through `self.add` / `self.note`; the row says `ok` only after the sign-in LANDED, and one account's trouble never
        stops the probe of another (E8)."""
        check = "actor_sign_in"
        row = {"outcome": "not_proved", "method": "ui_recipe", "recipe_sha": MC.recipe_sha({}), "at": MC._now()}
        shown = named_ids(cases)
        block = f"sign-in of the account {actor}"
        three = (f"one of three: give access - fix the account or the stand, or put the right login and password where the "
                 f"runner reads them (never in the chat) and tell me, and I rehearse again; or check {shown} yourself by hand "
                 f"and say so; or say that this check is not needed. ")
        extra = getattr(self, "_extra_accounts", {}).get(actor)
        carded = self._account_carded.get(_role_form(actor))
        if carded == "not_needed" and not extra:
            # PK0-9 (§3 (2b), FR-7): the person said this is no role of the product, so whatever its account state (a config account
            # included: not_needed wins over it) it is never signed in and raises no card and no finding; checked BEFORE the state
            self.note(check, f"the sign-in of {actor} was not tried: you said it is not a role of this product")
            return row
        if extra:
            # TR3-10 D8 (F14): an EXTRA account of the project. INVARIANT: its failure is a note and "dropped from the pool", never a
            # question and never a stop of gate A (the base account's question stays as it is); the handle is never printed (the role
            # and the position are), and `pool_of` keeps only handles with an `ok` row.
            block = f"sign-in of extra account {extra[1]} of the role {extra[0]}"

            def drop(why: str) -> dict:
                self.note(check, f"{block} {why}; it is dropped from the pool of that role and no question is asked about it")
                return row
            try:
                user, secret = MC.resolve_actor(self.config, stand, actor, self.task_root)[:2]
            except ValueError:
                return drop("is not an account the runner can sign in as")
            values = ctx.get("values") or {}
            if ctx.get("env_error") or any(key not in values for key in (user, secret)):
                return drop("was not tried: its keys are not set where the runner reads them")
            state, detail = "met", ""
        else:
            state, detail = self._stand_account(actor, ctx)
        if state == "unmet" and not extra and carded:
            # PK0-4: a card already asks about this account (the role card, or the per-case card for its keys): ONE card per fact
            self.note(check, f"the sign-in of {actor} waits for the card about its account")
            return row
        if state == "unmet":
            self.add(check, PERSON_DECIDES, f"{block} was not tried: {detail} ({shown})",
                     three + self.waiver_command(block, "", "accept"), cases=list(cases))
            return row
        if state != "met":
            self.add(check, FACTORY_DEFECT, f"{block} could not be tried: {detail}", SIGN_IN_FACTORY_DOOR, cases=list(cases))
            return row
        try:
            recipe = MC.login_recipe(self.config, MC.spec(), "ui")
            row["recipe_sha"] = MC.recipe_sha(recipe)
            result = self._probe_sign_in(MC, recipe, actor, stand)
        except MC.BrowserUnavailable as exc:
            if extra:
                return drop("could not be tried: no browser could be opened here")
            self.add(check, FACTORY_DEFECT, f"{block} could not be tried: no browser could be opened here ({str(exc)[:120]})",
                     SIGN_IN_FACTORY_DOOR, cases=list(cases))
            return row
        except Exception as exc:  # a recipe or an account the reader refuses: the project's record, the factory's to fix
            if extra:
                return drop(f"could not be proved ({type(exc).__name__})")
            self.add(check, FACTORY_FIXABLE, f"{block} could not be proved: {' '.join(str(exc).split())[:240]}",
                     SIGN_IN_RECIPE_DOOR, cases=list(cases))
            return row
        if result.get("signed_in") is True:
            weak = bool(result.get("weak"))
            row.update(outcome="ok", proof="weak" if weak else str(result.get("proof") or ""))
            if weak:
                self.note(check, f"{block} landed, but the project's sign-in recipe has no landing rule, so it is proved only by "
                                 "the sign-in field being gone (a weak proof)")
        elif result.get("kind") == "not_landed":
            row["outcome"] = "failed"
            if extra:
                return drop("was not let in by the stand")
            self.add(check, PERSON_DECIDES,
                     f"{block}: the stand did not let it in - the login was submitted and the page did not land. "
                     f"{shown} need it.", three + self.waiver_command(block, "", "accept"), cases=list(cases),
                     detail=str(result.get("detail") or "")[:300])
        else:
            if extra:
                return drop("could not be proved: the sign-in recipe does not fit the login page, or none is recorded")
            self.add(check, FACTORY_FIXABLE,
                     f"{block} could not be proved: the project's sign-in recipe does not fit its login page, or none is "
                     f"recorded ({str(result.get('kind') or 'no result')}).",
                     SIGN_IN_RECIPE_DOOR, cases=list(cases), detail=str(result.get("detail") or "")[:300])
        return row

    def _probe_sign_in(self, MC, recipe: dict, actor: str, stand: dict) -> dict:
        """One `manual_capture.sign_in` in a context of its own that is closed after (nothing of it is kept: no profile, no cookie)."""
        backend = MC.BACKEND_FACTORY() if MC.BACKEND_FACTORY is not None else MC.PlaywrightBackend()
        try:
            hosts = set(MC.stand_hosts(self.config, root=self.project_root))
            backend.open(MC.timeout_for(stand), hosts, recipe.get("local_storage"), MC.element_wait_for(self.config))
            return MC.sign_in(backend, self.config, self.project_root, actor, stand, task_root=self.task_root, hosts=hosts)
        finally:
            backend.close()

    # --- gate A: 4. the environment S5 itself will run in --------------------------------------

    def check_s5_executor(self) -> None:
        """Every execution profile the next stage will need, launched as far as resolving it.

        Nothing is asked when the launcher resolves. When it does not, the person gets ONE
        question per profile with three answers — install it here, name an environment I can
        run it in, or run these cases yourself — and only the third one hands anything over.
        `gate_rehearsal.skip_executor: true` turns the step off.

        When NO profile can be keyed to the automation at all — none configured, or none that
        fits — there is no launcher to probe and one question stands in for all of them
        (TP2-2553). A story whose plan has no `automate` row asks nothing either way.

        A profile the person has already taken over (`contract.handed_profiles`) is not asked
        about again: they answered, and asking twice is how one approval became four stops."""
        check = "s5_executor"
        root = self.project_root
        if root is None or (self.config.get("gate_rehearsal") or {}).get("skip_executor"):
            return
        try:
            import contract
            handed = contract.handed_profiles(self.pipeline)
        except Exception:
            handed = {}
        profiles = {str(p.get("profile_id")): p for p in (self.config.get("profiles") or [])
                    if isinstance(p, dict) and p.get("profile_id")}
        keyed = self.keyed_profiles()
        if not keyed:
            automate = [case for case, _row in self.automate_rows()]
            # `handed` can only be this story's own execution, there being no profile to tell
            # apart: a person who already said "I run them" is not asked a second time.
            if automate and not handed:
                statement, options = no_profile_question(automate, self.next_stage)
                self.add(check, PERSON_DECIDES, statement, options,
                         profile=NO_PROFILE_ID, tool="", cases=list(automate),
                         keyed_on="no profile in qa-factory/config.json keys these cases",
                         options=no_profile_options(len(automate)))
            return
        for profile_id, entry in sorted(keyed.items()):
            if profile_id in handed:
                continue
            profile = profiles.get(profile_id) or {}
            # `one_test`, else `run` (a profile that names only a run command), through the ONE reader of the shape (OH3-27,
            # AR-13): a shape it cannot read is a note and no probe - a launcher nobody could name is not a launcher missing
            import profile_contract
            spec, problem = profile_contract.profile_command(profile, "one_test")
            if not problem and not spec:
                spec, problem = profile_contract.profile_command(profile, "run")
            argv, argv_problem = ([], "") if problem else profile_contract.command_argv(spec, drop_placeholders=True)
            problem = problem or argv_problem
            if problem:
                self.note(check, f"`{profile_id}`: {problem}, so no launcher was looked for")
                continue
            cwd = (root / str(spec.get("cwd") or ".")).resolve()
            probe = executor_probe(argv, cwd, profile)
            if probe["status"] != "missing":
                continue
            statement, options = executor_question(probe["tool"], profile_id, entry["cases"],
                                                   self.next_stage)
            self.add(check, PERSON_DECIDES, statement, options,
                     profile=profile_id, tool=probe["tool"], cases=list(entry["cases"]),
                     keyed_on=entry["keyed_on"], options=executor_options(len(entry["cases"])))

    def check_s5_dependencies(self) -> None:
        """What is installed in the PROJECT's environment against the project's lock (RH1-4, F-8 (c)).

        A difference or a missing package is one `note` with the pair of versions and the project's install command (the
        profile's `commands.install`, else the package manager's table row): not a finding, the gate waits on nothing, and
        the factory does not run the command (C3-18 part 2 owns that). The state is kept for `check_s5_toolchain`, which
        adds the same pair to a collect that then fails on an import. An environment the check cannot read says nothing
        here: `unknown` is not a claim either way. Every profile this story's S5 will run is checked (`s5_profiles`; the
        selected profiles when none is keyed), one check per distinct environment, each result naming the profiles it
        covers. `gate_rehearsal.skip_dependencies: true` turns the step off."""
        check = "s5_dependencies"
        root = self.project_root
        self._drift = []
        if root is None or self._gate_switch("skip_dependencies"):
            return
        import dependency_drift
        import profile_contract
        selected = profile_contract.selected_profiles(self.config)
        keyed = set(self.keyed_profiles())
        entries = dependency_drift.check_profiles(root, [p for p in selected if str(p["profile_id"]) in keyed] or selected)
        self._drift = [e for e in entries if e["result"]["state"] in ("differs", "missing_only")]
        self._drift_all = entries
        for entry in self._drift:
            result = entry["result"]
            self.note(check, dependency_drift.drift_text([entry], of=entries), lock=result["lock"],
                      differs=list(result["differs"]), absent=list(result["absent"]), command=dict(result["command"]),
                      profiles=list(entry["profiles"]))

    def _drift_phrase(self, code=None, text="", argv=None, failed=False) -> str:
        """The one phrase the collect card adds when the dependency check found a difference: the pair of versions and the
        project's install command. `failed=True` (the collect FAILED outright - decided by the collect verdict, never by
        the text, which may be empty): only when the launch check reads the output as a missing library
        (`dependency_missing`); for a partial or an all-broken collect always."""
        drift = getattr(self, "_drift", None)
        if not drift:
            return ""
        if failed:
            import launch_check
            if launch_check.classify(code, str(text or "").splitlines(), None, argv=argv).get("cause") != "dependency_missing":
                return ""
        import dependency_drift
        return dependency_drift.drift_text(drift, of=getattr(self, "_drift_all", None))

    def check_s5_toolchain(self) -> None:
        """Collect the tests that ALREADY exist, the way the project's own command would.

        S0 wrote "preflight green, env=pending" and the automator then spent fifteen minutes
        writing code that could not even be collected: `ModuleNotFoundError: pydantic`. The
        story's own tests do not exist yet at gate A — but the project's do, and collecting
        them proves the one thing that mattered: the runner and its imports are alive on this
        machine. Nothing is executed; `--collect-only` imports and reports.

        The one thing this step does not own: a project's own `conftest.py` runs at
        `pytest_configure`, before collection, and whatever it does there it does here too —
        the same thing S5 would trigger an hour later, now instead of after the approval.
        `gate_rehearsal.skip_collect: true` turns the step off for a project that says no."""
        check = "s5_toolchain"
        root = self.project_root
        if root is None or (self.config.get("gate_rehearsal") or {}).get("skip_collect"):
            return
        tests_root = (root / str(self.config.get("tests_root") or ".")).resolve()
        if not tests_root.is_dir():
            return
        command = collect_base(self.config)
        if not command:
            # Only a pytest-shaped command can be rehearsed this cheaply. A project on another
            # runner is not told a step is broken — there is simply no step here to run.
            return
        try:
            timeout = int((self.config.get("gate_rehearsal") or {}).get("collect_timeout_s") or 120)
        except Exception:
            timeout = 120
        # The collect is S5's own (SC1-12, EP1-11, AR-15): `node_ids.collect_output` adds `--collect-only -q` and
        # retries a `-qq` (`file.py: 3`) or a `<Module>` tree, so a project whose addopts carry a `-q` or a `-v`
        # gets here the ids S5 will read. Its `CollectError.kind` picks the question, as the exception class did.
        # The template's OWN `-q`/`--quiet` is dropped first (t-1329 F2): `collect_output` adds the `-q` itself, and two of
        # them are `-qq`, which prints `file.py: 3` and costs a second collect (up to 2x the timeout) on every project whose
        # `quiet` template says what its name says. A `-q` in the project's addopts still earns the retry, as in S5.
        import launch_check
        import node_ids
        bare = [token for token in command if token not in ("-q", "--quiet")]
        # RH1-3: the runner's row (data) lets the ONE collect go on past a file that fails to import; the outcome is read
        # by `node_ids.collect_verdict` with the REAL exit code (the same reading S5 and the onboarding probe use).
        form, why = launch_check.runner_row(bare)
        if why:     # a table that cannot be read: the collect stays all-or-nothing, and the gate says so (E3-12)
            self.note(check, launch_check.table_note(why))
        try:
            code, text = node_ids.collect_output(bare, tests_root, timeout, form=form)
        except node_ids.CollectError as exc:
            if exc.kind == "not_started":
                # No runner: FileNotFoundError / PermissionError only (t-1329 F1); any other launch failure is
                # `launch_failed` and takes the unavailable branch below. The same fact `check_s5_executor` asks about, reached from the other side — so
                # it is asked in the same words, with the same three answers. Two differently
                # worded questions about one missing binary is two stops (TP2-2536).
                profiles = self.keyed_profiles()
                profile_id = next(iter(sorted(profiles)), "the project command")
                cases = list((profiles.get(profile_id) or {}).get("cases") or [])
                statement, options = executor_question(command[0], profile_id, cases, self.next_stage)
                self.add(check, PERSON_DECIDES, statement, options,
                         profile=profile_id, tool=command[0], cases=cases,
                         options=executor_options(len(cases)))
            elif exc.kind == "timeout":
                self.add(check, PERSON_DECIDES,
                         f"collecting the existing tests in `{self.config.get('tests_root') or '.'}` "
                         f"did not finish within {timeout}s — {self.next_stage} would start against "
                         "a toolchain nobody has seen answer",
                         "answer with your approval: look at it first, or go on and let the stage "
                         "report what it could not run")
            else:   # an unknown kind is an unavailable step, never a green one (E25)
                self.unavailable(check, f"collect-only ({type(exc).__name__}: {exc})")
            return
        except Exception as exc:
            self.unavailable(check, f"collect-only ({type(exc).__name__}: {exc})")
            return
        self._collect_outcome(check, code, text, form, bare)

    def _collect_outcome(self, check: str, code: int, text: str, form, bare: list) -> None:
        """What the ONE collect of `check_s5_toolchain` proved, by `node_ids.collect_verdict`: a note (`partial`,
        `none_selected`), a record for the report, or the question to the person (`all_broken`, `stopped`, `failed`);
        an output that does not add up is an unavailable step - never a pass (AR-28). `bare` is the collect's argv: the
        dependency phrase of a failed collect reads the output with it (`launch_check.classify`)."""
        import node_ids
        verdict = node_ids.collect_verdict(code, text, form)
        kind = verdict["kind"]
        if kind == "unread":
            # The same count verdict S5 uses (EP1-9 / AR-15): pytest counted N tests and the one parser read none, or a
            # partial exit whose count does not add up - say so, never let the rehearsal go on as if the project had no tests.
            head = " | ".join(node_ids.output_head(text).splitlines())[:300]
            seen = f"{verdict['selected'] or 0} collected, 0 read" if code == 0 else "the runner ended with errors and its count does not add up"
            self.unavailable(check, f"collect output unreadable: {seen}: {head}")
        elif kind == "complete":
            # Kept for `check_s5_reporter`, which needs ONE existing node id and must not pay
            # for a second collect of the same suite at the same gate. 5 is pytest's "nothing matched": a fact about the filter.
            self.collect_stdout = text
            self._keep_collect_gaps([])               # a collect that finished with nothing broken erases an earlier row
        elif kind in ("partial", "none_selected"):
            self.collect_stdout = text
            self._collect_note(check, verdict)
        elif kind == "all_broken":
            first = verdict["broken"][0]
            self._keep_collect_gaps(verdict["broken"])   # "let the stage run" must not leave the report silent about them (m6)
            self._collect_card(check, f"every one of the {len(verdict['broken'])} test files failed to import; the first is "
                               f"{first['path']}" + (f" ({first['head']})" if first["head"] else ""), promise=False,
                               phrase=self._drift_phrase())
        else:
            # The runner joins the two streams into one (`run_bounded`), so the failure line is read from that one text.
            detail = collect_failure(text, "")
            if kind == "stopped":
                detail += "; the project's addopts stop the collect at the first error"
            elif form is not None and not form.get("continue_tokens"):
                detail += ("; the runner cannot continue past a file that fails to import, so one broken file hides the rest")
            self._collect_card(check, detail, phrase=self._drift_phrase(code, text, bare, failed=True))

    def _keep_collect_gaps(self, broken: list) -> None:
        """The broken files of this gate's collect go to the story's history (`collect_gaps.record`, the one writer; `[]`
        erases the row), so the report can name them. A record that cannot be kept is a note, never a finding."""
        try:
            import collect_gaps
            # the gate collects the whole `tests_root` with the one template, not per profile: its row is the project's,
            # and so is every file in it - the story's own tests do not exist yet at gate A (F4)
            problem = collect_gaps.record(self.task_root, "gate_a", "project", [dict(b, owner="project") for b in broken])
        except Exception as exc:  # the record is the factory's own; its defect must not stop the gate
            problem = f"{type(exc).__name__}: {exc}"
        if problem:
            self.note("s5_toolchain", f"the broken test files could not be kept for the report: {problem}"[:300])

    def _collect_note(self, check: str, verdict: dict) -> None:
        """`partial` / `none_selected`: not a finding and no stop - one line of what the collect proved, the broken files
        named (at most `COLLECT_SHOWN`, the rest counted; the note's field holds all of them)."""
        import node_ids
        broken = verdict["broken"]
        left = node_ids.broken_names(broken, COLLECT_SHOWN)
        if verdict["kind"] == "none_selected":
            message = f"no test was selected by the filter; {len(broken)} file(s) could not be collected: {left}"
        else:
            message = (f"{len(broken)} of the project's test files could not be collected and are left out: {left}; "
                       "the other tests were collected")
            phrase = self._drift_phrase()
            message += f"; {phrase}" if phrase else ""
        self.note(check, message, broken_files=[dict(b) for b in broken])
        self._keep_collect_gaps(broken)

    def _collect_card(self, check: str, detail: str, promise: bool = True, phrase: str = "") -> None:
        """The question a collect that gave nothing usable asks the person (`PERSON_DECIDES`). `promise=False`: the
        "say the word and I do it" offer is not made (the install is C3-18's, not built here). `phrase`: the one sentence
        of the dependency check (the pair of versions and the project's install command), when it has one."""
        detail = f"{detail}; {phrase}" if phrase else detail
        tests_root = str(self.config.get("tests_root") or ".")
        offer = ("install what is missing (say the word and I do it, with your decision recorded), or let the stage run and "
                 "report the tests as not executed" if promise else
                 "let the stage run and report the tests as not executed, or have the project's environment or the broken "
                 "files fixed first and the check repeated")
        self.add(check, PERSON_DECIDES,
                 f"the existing tests in `{tests_root}` cannot even be collected, so {self.next_stage} would write code "
                 f"nothing can run: {detail}",
                 f"answer with your approval: {offer}. Collecting the project's tests with its own runner, in {tests_root}, "
                 "reproduces it")

    # --- gate A: 4b. a stand too slow for the page objects --------------------------------------

    def _gate_switch(self, name: str) -> bool:
        """`gate_rehearsal.<name>: true` turns a step off, like every other switch here."""
        cfg = self.config.get("gate_rehearsal") if isinstance(self.config.get("gate_rehearsal"), dict) else {}
        return bool(cfg.get(name))

    def _handed(self) -> dict:
        try:
            import contract
            return contract.handed_profiles(self.pipeline)
        except Exception:
            return {}

    def _e2e_limit(self, profile_id: str, profile: dict, entry: dict) -> dict:
        """What the recorded limits say about one profile's e2e rows: `{"state": ...}`.

        `n/a` (no automate row of the profile is an e2e one, or the step is switched off),
        `unmeasured` (a limit is not recorded, or is older than the stand - `why` says which, in
        words a person reads, and `fields` names where it is recorded),
        `unreadable` (recorded and not a positive number - `what` says which limit in words and
        `fields` names the field), `incomplete` (a page load is recorded without how or when it
        was measured: `missing` names the parts, t-224 Q2), `within`, or `over` (a full page
        load takes longer than the page objects wait: `load`, `wait`, `route`, `stand`,
        `cases`). The field paths stay in `fields`/`missing`: they are for the fix text and the
        extra fields, never for a sentence a person reads (FR-6). Pure: the step that raises the
        card and the reporter step that must not run a test on a stand this slow both ask it,
        and neither writes.

        cmp2 (TP1-15045, 01.10.2026): a full load of the workflow editor took 70-110 s under
        Vite dev, the page objects wait 5-30 s, and about $2.3 of automator dispatches went
        before S5 found out. The number is carried with how it was measured (command hygiene
        6b); onboarding records it by hand (a headless-browser probe is a later B-line)."""
        if self._gate_switch("skip_stand_limits"):
            return {"state": "n/a"}
        rows = dict(self.automate_rows())
        cases = [c for c in entry.get("cases") or []
                 if str((rows.get(c) or {}).get("level") or "") == E2E_LEVEL]
        if not cases:
            return {"state": "n/a"}
        stand = self._selected_environment()
        stand_name = str(stand.get("name") or "") or "this stand"
        measured = stand.get("measured") if isinstance(stand.get("measured"), dict) else {}
        record = measured.get("e2e_page_load_s")
        wait_raw = profile.get("page_object_max_wait_s")
        load_field = "environments[].measured.e2e_page_load_s"
        wait_field = "profiles[].page_object_max_wait_s"
        base = {"stand": stand_name, "cases": cases}
        if record is None and wait_raw is None:
            return dict(base, state="unmeasured", fields=[load_field, wait_field],
                        why="neither the stand's page load nor the page objects' wait is recorded")
        words, fields = [], []
        load = None
        if record is not None:
            load = limit_seconds(record.get("value") if isinstance(record, dict) else None)
            if load is None:
                words.append(f"the page load recorded for {stand_name}")
                fields.append(load_field + ".value")
        wait = None
        if wait_raw is not None:
            wait = limit_seconds(wait_raw)
            if wait is None:
                words.append("the wait of the page objects")
                fields.append(wait_field)
        if words:
            return dict(base, state="unreadable", what=words, fields=fields)
        # A number nobody can trace is not a measurement (command hygiene 6b): the record says
        # how it was measured and when, or it is the onboarding's defect. The route is NOT
        # required - there is no reference route in the config to compare it with (t-224, Q2).
        if isinstance(record, dict):
            missing = [part for part in ("command", "at")
                       if not (isinstance(record.get(part), str) and record[part].strip())]
            if missing:
                return dict(base, state="incomplete", missing=missing,
                            fields=[f"{load_field}.{part}" for part in missing])
        if load is None:
            return dict(base, state="unmeasured", wait=wait, fields=[load_field],
                        why=f"the page objects wait at most {wait:g} s, and the stand's page load "
                            "is not recorded")
        if wait is None:
            return dict(base, state="unmeasured", load=load, fields=[wait_field],
                        why=f"a full page load measured {load:g} s, and the page objects' wait is "
                            "not recorded")
        stale = measurement_is_stale(record.get("at"), stand.get("verified"))
        if stale:
            return dict(base, state="unmeasured", why=stale)
        route = " ".join(str(record.get("route") or "").split())[:80]
        if load > wait:
            return dict(base, state="over", load=load, wait=wait, route=route)
        return dict(base, state="within", load=load, wait=wait)

    def check_s5_stand_limits(self) -> None:
        """e2e rows whose page objects would time out on this stand become ONE card per profile.

        The options are the answers this factory already has executors for (FR-9): (a) the
        handed door `executor unavailable: <profile>` - S5 writes the tests and the person runs
        them where the page loads in time; (b) `<case id>: manual` - the gate-A answer form that
        moves the row to a check by an agent. A third door, "accept them as blocked" through
        `waiver.py --stage S5 --block "e2e stand limit: <profile>"`, was dropped from the card
        (t-224, C2): nothing outside this file reads that block yet (a reader that turns it into
        `blocked_by_env` rows is queued behind t-226), so offering it was a door with no
        executor (FR-9). A waiver file that already holds the block still passes the card, which
        is `add()`'s own rule (FR-4). Nothing recorded is "not measured", an INFO line, never a
        card (FR-41). Strict `>`: a load equal to the wait fits. `gate_rehearsal.
        skip_stand_limits: true` turns it off."""
        check = "e2e_stand_limit"
        if self.project_root is None or self._gate_switch("skip_stand_limits"):
            return
        keyed = self.keyed_profiles()
        handed = self._handed()
        profiles = {str(p.get("profile_id")): p for p in (self.config.get("profiles") or [])
                    if isinstance(p, dict) and p.get("profile_id")}
        for profile_id, entry in sorted(keyed.items()):
            if profile_id in handed:
                continue
            limit = self._e2e_limit(profile_id, profiles.get(profile_id) or {}, entry)
            state = limit["state"]
            if state == "unmeasured":
                self.note(check, f"`{profile_id}`: e2e page load on {limit['stand']} is not "
                                 f"measured - {limit['why']}, so whether its page objects' waits "
                                 "fit this stand is unknown", fields=limit.get("fields") or [])
            elif state == "unreadable":
                self.add(check, FACTORY_DEFECT,
                         f"the recorded limit cannot be read: {' and '.join(limit['what'])} "
                         f"{'is' if len(limit['what']) == 1 else 'are'} not a number above zero, "
                         f"so the e2e rows of `{profile_id}` were not compared with the stand's "
                         "page load",
                         "the limit is onboarding's own record: record a positive number of "
                         "seconds in " + ", ".join(f"`{f}`" for f in limit["fields"])
                         + "; "
                         + self.waiver_command("the recorded limit cannot be read"),
                         profile=profile_id, fields=limit["fields"])
            elif state == "incomplete":
                self.add(check, FACTORY_DEFECT,
                         f"the recorded limit is incomplete: the page load recorded for "
                         f"{limit['stand']} does not say how or when it was measured, so the e2e "
                         f"rows of `{profile_id}` were not compared with the page objects' wait",
                         "the record is onboarding's own: add what is missing ("
                         + " and ".join(f"`{part}`" for part in limit["missing"])
                         + ") next to the number in `environments[].measured.e2e_page_load_s`; "
                         + self.waiver_command("the recorded limit is incomplete"),
                         profile=profile_id, missing=limit["missing"], fields=limit["fields"])
            elif state == "over":
                self._stand_limit_card(check, profile_id, limit)

    def _stand_limit_card(self, check: str, profile_id: str, limit: dict) -> None:
        cases = limit["cases"]
        stand, wait = limit["stand"], limit["wait"]
        elsewhere = "another stand where the page loads in time"
        for other in self.config.get("environments") or []:
            if not isinstance(other, dict) or str(other.get("name") or "") in ("", limit["stand"]):
                continue
            record = (other.get("measured") or {}).get("e2e_page_load_s") \
                if isinstance(other.get("measured"), dict) else None
            value = limit_seconds(record.get("value") if isinstance(record, dict) else None)
            if value is not None and value <= wait:
                elsewhere = str(other["name"])
                break
        # The message still opens with this block text although the card no longer offers a
        # waiver on it (C2): a waiver file written while it did must keep passing the card, and
        # `add()` matches the block against the message (FR-4).
        block = f"e2e stand limit: {profile_id}"
        route = limit["route"] or "the page"
        shown = named_ids(cases)
        self.add(check, PERSON_DECIDES,
                 f"{block} — e2e on {stand}: a full load of {route} measured {limit['load']:g} s and "
                 f"the page objects of `{profile_id}` wait at most {wait:g} s, so {shown} cannot "
                 "run here",
                 "answer with your approval, one of two: "
                 f"(a) the tests are written now and you run them on {elsewhere} — "
                 + self.waiver_command(f"{HANDED_MATCH_PREFIX} {profile_id}", "S5", "handed") + "; "
                 "(b) an agent checks these cases by hand here and shows you before and after — "
                 f"answer `<case id>: manual` for each of {shown}",
                 profile=profile_id, cases=list(cases), load_s=limit["load"], wait_s=wait,
                 options=[{"id": "a", "action": EXECUTOR_OPTION_IDS[2]},
                          {"id": "b", "action": "manual_by_agent"}])

    def check_s5_reporter(self) -> None:
        """ONE existing test, run through the profile's own one-test command, to prove that a
        report the factory can read really comes out of it.

        TP2-2553: the profile said the run writes a report; Karma was configured with
        `progress`, `kjhtml` and `coverage`, and `karma-junit-reporter` was in no dependency of
        the project. `run_suite.py` knows that cure and printed it — in the middle of S5, on the
        first real run, after the approval — and the story's only true execution gap cost a
        window. The gate already collects the suite and resolves the launcher; the last link
        costs one test.

        Nothing of the story runs here: an existing test of the project, with the report
        written into the OS temp directory and never into this task's evidence.
        `gate_rehearsal.skip_reporter: true` turns the step off, and the card a missing report
        raises is passed by a person's word like every other block in this factory.

        Once per project + command (D-0019 item 2, F11 of B-220: no longer per stand or deployed version - the proof
        is a property of the command on this machine): a proven report is kept in
        `qa-factory/state/reporter-rehearsals.json`, with the argv it proved, and the next gate, in any process - and
        the onboarding probe's own proof - says it did not rehearse again. A card says whether the command changed
        since it was proved or stopped working (`onboarding_probe.earlier_proof`)."""
        check = "s5_reporter"
        root = self.project_root
        cfg = self.config.get("gate_rehearsal") if isinstance(self.config.get("gate_rehearsal"), dict) else {}
        if root is None or cfg.get("skip_reporter"):
            return
        keyed = self.keyed_profiles()
        if not keyed:
            return  # nothing keys these cases to a profile: `check_s5_executor` asks that one
        try:
            import contract
            handed = contract.handed_profiles(self.pipeline)
        except Exception:
            handed = {}
        profiles = {str(p.get("profile_id")): p for p in (self.config.get("profiles") or [])
                    if isinstance(p, dict) and p.get("profile_id")}
        try:
            timeout = int(cfg.get("reporter_timeout_s") or 180)
        except Exception:
            timeout = 180
        self._rehearsals = self._load_rehearsals(check)
        import shutil
        import tempfile
        temp = Path(tempfile.mkdtemp(prefix="qa-gate-reporter-"))
        try:
            for profile_id, entry in sorted(keyed.items()):
                if profile_id in handed:
                    continue
                if self._e2e_limit(profile_id, profiles.get(profile_id) or {}, entry)["state"] == "over":
                    # A test through a stand whose page takes longer to load than the page
                    # objects wait would time out and prove nothing about the report; the card
                    # of `check_s5_stand_limits` already says why (t-218, C5).
                    self.note(check, f"`{profile_id}`: one test was not run to prove its report - "
                                     "a full page load on this stand takes longer than its page "
                                     "objects wait (see the e2e stand limit above)")
                    continue
                self._rehearse_reporter(check, profile_id, entry, profiles.get(profile_id) or {},
                                        root, temp, timeout, cfg.get("reporter_probe_test"))
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def _probe_test_of(self, profile_id: str, declared) -> str:
        """The test `gate_rehearsal.reporter_probe_test` names for this profile, or ''.
        One string means "this one for every profile"; a map is keyed by profile id."""
        if isinstance(declared, dict):
            return str(declared.get(profile_id) or "").strip()
        return str(declared or "").strip()

    def _profile_tests_dir(self, profile: dict, root):
        """The directory of the profile's own tests (`roots.test`), or None when the profile does
        not name one or it is not on disk - then nothing narrows the search."""
        roots = profile.get("roots") if isinstance(profile.get("roots"), dict) else {}
        rel = str(roots.get("test") or "").strip()
        if not rel:
            return None
        path = (Path(root) / rel).resolve()
        return path if path.is_dir() else None

    # The gate proves ONE profile's report, so a test another profile may own proves nothing (EP1-10). The onboarding
    # probe (`onboarding_probe.ProbeRehearsal`) learns what a COMMAND writes, and any test under the root serves that.
    SHARED_ROOT_PICKS_NOTHING = True

    def _profiles_sharing_root(self, profile: dict, tests_dir, root) -> list:
        """The ids of the OTHER profiles that own this profile's test directory together with it, sorted: those
        `execution_request.profiles_owning` names for the directory (the predicate `_profile_for` and the probe
        use, so `tests` and `./tests` are one root here too). [] when this profile has no test directory of its
        own (none named, or not on disk: nothing narrows the search, and nothing new is said), or when it owns
        the directory alone (EP1-10)."""
        if tests_dir is None:
            return []
        import execution_request
        mine = str(profile.get("profile_id") or "")
        owners = execution_request.profiles_owning(self.config, self._root_rel(tests_dir, root))
        return sorted(o for o in owners if o != mine)

    @staticmethod
    def _rel_inside(path, base):
        """`path` relative to `base` as a posix string ('.' for `base` itself), or None when `path` is not inside
        `base`. The one "is it inside" reading of the gate's two callers (EP1-12, AR-13); never raises."""
        try:
            return Path(path).relative_to(Path(base)).as_posix() or "."
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _root_rel(path, root) -> str:
        """`path` relative to the project root, as a posix string; '.' for none. Not inside the root: the path as
        given (a printing spelling and a key `profiles_owning` finds no owner for - an absolute path never gives
        an owner)."""
        if path is None:
            return "."
        inside = Rehearsal._rel_inside(path, Path(root).resolve())
        return str(path) if inside is None else inside

    def _node_prefix(self, tests_dir, root):
        """`tests_dir` as the directory a collect node id starts with (the collect runs in `tests_root`); '' when
        no directory narrows the search (`tests_dir` is None: the whole collect); None when the directory is NOT
        below `tests_root` - no node of that collect can be under it, and '' (the whole collect) there would offer a
        test outside the profile's own directory (EP1-12)."""
        if tests_dir is None:
            return ""
        tests_root = (Path(root) / str(self.config.get("tests_root") or ".")).resolve()
        return self._rel_inside(tests_dir, tests_root)

    def _rehearsals_path(self) -> Path:
        return Path(self.project_root) / "qa-factory" / "state" / REPORTER_REHEARSALS_FILE

    def _load_rehearsals(self, check: str) -> dict:
        """The rehearsals that already proved a report, keyed as `_rehearsal_key` keys them.

        Absent is the normal state before the first positive rehearsal. A file that does not
        parse is not a stop: it is said once, treated as empty, and the next proven rehearsal
        writes it whole again (P1: code tells, it does not halt the gate)."""
        path = self._rehearsals_path()
        if not path.is_file():
            return {}
        try:
            rows = json.loads(path.read_text(encoding="utf-8")).get("rehearsals")
            if not isinstance(rows, dict):
                raise ValueError("no `rehearsals` map")
            return {str(k): v for k, v in rows.items() if isinstance(v, dict)}
        except Exception:
            self.note(check, f"{REPORTER_REHEARSALS_FILE} unreadable, rehearsing: every profile "
                             "is run once more, and the next proven rehearsal writes it again")
            return {}

    def _observed_identity(self, profile_id: str, root) -> str:
        """What the stand runs right now, through the probe the project registered for this
        profile (or for `*`) and the REHEARSAL reader (`execution_request.rehearsal_probe`, t-300 B1);
        '' when the project registered none or the probe could not answer. Read-only, like every probe:
        the probe runs with `--no-evidence` and this story's `--task-root` (it used to write an evidence
        file on every rehearsal, and to read the newest pipeline of the project). It is NOT
        `run_suite.probe_runtime`, which stays strict. A `matched` build is an identity, and so is a build
        the person confirmed for this story (`person_confirmed`); anything else is ''."""
        execution = self.config.get("execution") if isinstance(self.config.get("execution"), dict) else {}
        probes = execution.get("runtime_probes") if isinstance(execution.get("runtime_probes"), dict) else {}
        spec = probes.get(profile_id) or probes.get("*")
        if not (isinstance(spec, dict) and spec.get("argv")):
            return ""
        try:
            import execution_request
            import runtime_probe
            cwd = Path(str(spec.get("cwd") or "."))
            observed = execution_request.rehearsal_probe({
                # the stored argv is portable (t-238 W5): this machine's python and plugin path
                # are filled in here, the way the S5 run path fills them
                "argv": [str(a) for a in runtime_probe.resolve_argv(spec["argv"])],
                "cwd": str(cwd if cwd.is_absolute() else Path(root) / cwd),
                "timeout_s": spec.get("timeout_s") or 30,
                "task_root": str(Path(self.task_root).resolve())}, accepts=("matched", "person_confirmed"))
            return str((observed or {}).get("observed_runtime_identity") or "").strip()
        except Exception:
            return ""

    def _rehearsal_key(self, profile_id, cwd, argv, chosen, fmt, identity, root) -> str:
        """The sha256 that says "this is the same rehearsal": same profile, command, test,
        format and dependency bytes (the reporter plugin lives in them). '' when it cannot be
        built, which means "not durable", never "matches".

        B-220 part 2 (F11): NOT the stand and NOT the deployed version. Whether a command
        leaves a report the factory can read is a property of the command on this machine,
        not of a stand: a key that held either would never match the proof the onboarding
        made (it has no pipeline, so no stand and no build identity), and the second stand of
        a project would pay for the same proof again. `identity` stays in the signature (the
        onboarding probe's subclass calls it) and is recorded in the row as information, but
        it no longer keys anything. TEMPORAL: a row written by the code before this change
        was keyed with both, so no key built now ever equals it - it is inert, and
        `_record_rehearsal` drops it the next time the file is written.

        B-407 B-deps: the files it watches are `execution_request.dependency_files(cwd, self.config)` (the
        table's names and top-level patterns, and the project's own `run.dependency_files`) and the table's
        `report_config`, one list in `references/dependency-files.json` shared with the run fingerprint. On a
        project that has none of the newly listed files the key is byte-identical to the one built before. TEMPORAL:
        a row written for a project that now has one of them (a Java or JS project) no longer matches, so it is
        rehearsed once more and `_record_rehearsal` replaces the row - a proof is never reused across a changed
        report config. The onboarding may run before `qa-factory/config.json` exists: its `self.config` then has no
        `run.dependency_files`, so for a project that lists extra files its proof never matches gate A (one
        extra rehearsal, never a wrong reuse)."""
        try:
            import hashlib
            import os
            from execution_request import dependency_files, dependency_table
            try:
                where = Path(cwd).resolve().relative_to(Path(root).resolve()).as_posix()
            except ValueError:
                where = str(cwd)
            watched, problem = dependency_files(cwd, getattr(self, "config", None) or {})
            if problem:
                self._note_once("s5_reporter", problem)
            # The dependency files, and the files a runner reads its own report configuration from: the
            # report options (`--junitxml`, a plugin's `-p`) live in them just as often. The dict is keyed by
            # the path relative to the cwd: a plain name for a name of the table.
            names = set()
            for path in watched:
                try:
                    names.add(os.path.relpath(path, cwd).replace("\\", "/"))
                except ValueError:
                    # another drive than the cwd's: no relative path exists, the file's own resolved path keys it
                    names.add(Path(path).resolve().as_posix())
            names |= {name for name in dependency_table()["report_config"] if (Path(cwd) / name).is_file()}
            dependencies = {name: hashlib.sha256((Path(cwd) / name).read_bytes()).hexdigest()
                            for name in sorted(names)}
            payload = {"profile_id": profile_id, "cwd": where, "argv": list(argv),
                       "chosen": chosen, "fmt": fmt, "dependencies": dependencies}
            return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False)
                                  .encode("utf-8")).hexdigest()
        except (OSError, ValueError):
            return ""       # a file that cannot be read, a path that cannot be keyed: "not durable"
        except Exception as exc:
            # A programming error is not "not durable" by nature: say it once, or the proof is lost at every gate
            # with no trace. The key stays '' (never a wrong "matches").
            self._note_once("s5_reporter", f"the proof of this report could not be keyed ({type(exc).__name__}), so it "
                                           "is not kept and the command is rehearsed again at every gate")
            return ""

    def _note_once(self, check: str, message: str) -> None:
        """`note`, unless this gate already said the same line."""
        said = " ".join(str(message).split())
        if not any(i.get("message") == said for i in getattr(self, "info", [])):
            self.note(check, message)

    def _record_rehearsal(self, check, durable, profile_id, chosen, fmt, identity, tests) -> None:
        """Keep one PROVEN rehearsal. Read-modify-write through `atomic_json`: two gates at
        once each write a whole positive file and the last one wins. A project that cannot be
        written to loses only the saving: the failure is said in one note, never a stop, and
        the rehearsal's own result is untouched (P1).

        The row carries the `argv` it proved and its `argv_digest` (`onboarding_probe.argv_digest`, the one
        definition the onboarding wrote its rows with; both of the command's IDENTITY words, `profile_contract.command_identity`,
        EP1-22 B-2: the argv words, and after them the `env` when the command sets one): `onboarding_probe.earlier_proof` tells "the command
        changed" from "it stopped working" by it (F11). One row per (profile, argv): a newer proof of the
        SAME command replaces the older one (other bytes, same words), and the rows of OTHER commands of the
        profile stay - the old command's proof is still true of the old command. A row with no `argv_digest`
        is the old form: it can never match a key built now, is never a proof, and is not carried forward."""
        from datetime import datetime, timezone
        rows = getattr(self, "_rehearsals", None)
        if rows is None:
            rows = self._rehearsals = {}
        argv = [str(a) for a in (getattr(self, "_rehearsing_argv", None) or [])]
        row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "profile_id": profile_id,
               "environment": str(self._selected_environment().get("name") or ""),
               "runtime_identity": identity or None, "chosen": chosen, "fmt": fmt,
               "tests": int(tests)}
        try:
            from onboarding_probe import argv_digest
            if argv:
                row.update(argv=argv, argv_digest=argv_digest(argv))
        except Exception as exc:
            self.note(check, f"`{profile_id}`: the command this rehearsal proved could not be recorded with it "
                             f"({str(exc)[:80] or 'no reason given'}), so a later gate cannot tell a changed command "
                             "from one that stopped working")
        digest = row.get("argv_digest")
        for old in [k for k, v in rows.items()
                    if not isinstance(v.get("argv_digest"), str)
                    or (digest and v.get("profile_id") == profile_id and v.get("argv_digest") == digest)]:
            del rows[old]
        rows[durable] = row
        try:
            from event_store import atomic_json
            atomic_json(self._rehearsals_path(), {"schema_version": 1, "rehearsals": rows})
        except Exception as exc:
            self.note(check, f"`{profile_id}`: this rehearsal could not be saved to "
                             f"{REPORTER_REHEARSALS_FILE} ({str(exc)[:80] or 'no reason given'}), "
                             "so the next gate rehearses again; this rehearsal's own result "
                             "stands")

    @staticmethod
    def _reporter_command(profile) -> tuple:
        """`(spec, argv, env, identity, problem)` of one profile's one-test command, through the ONE reader of the shape
        (`profile_contract`, OH3-27 / EP1-22, AR-13): `spec` the command object, `argv` the words launched and shown, `env` the
        variables it sets (`{report_path}` as written), `identity` the words that say WHICH command this is
        (`command_identity`: the single input of every key and digest of the command). A shape that cannot be read - the
        commands, the command, its `argv` or its `env` - is `problem` (a sentence), never an empty command."""
        import profile_contract
        spec, problem = profile_contract.profile_command(profile, "one_test")
        argv, argv_problem = ([], "") if problem else profile_contract.command_argv(spec)
        env, env_problem = ({}, "") if problem or argv_problem else profile_contract.command_env(spec)
        problem = problem or argv_problem or (f"commands.one_test.{env_problem}" if env_problem else "")
        if problem:
            return spec, [], {}, [], problem
        return spec, argv, env, profile_contract.command_identity(spec), ""

    def _rehearse_reporter(self, check, profile_id, entry, profile, root, temp, timeout,
                           declared) -> None:
        """One profile's turn of `check_s5_reporter`: pick the test, run it, read the report."""
        cases = list(entry.get("cases") or [])
        spec, argv, env, identity, problem = self._reporter_command(profile)
        if problem:
            # a shape that cannot be read is said as that, never as "no command" (which would be untrue)
            self.note(check, f"`{profile_id}`: {problem}, so no run could prove its report")
            return
        if not argv:
            # The onboarding gap `run_suite.py --mine` refuses on inside S5 — already a
            # question of `check_s5_executor`'s shape; saying it twice would be two stops.
            self.note(check, f"`{profile_id}`: no `commands.one_test.argv` in the profile, so "
                             "no run could prove its report")
            return
        pytest_shaped, declared_kind, fmt = self._report_format(profile, argv, spec)
        disagreement = self._older_setting_note(profile_id, profile, fmt)
        if disagreement:
            self.note(check, disagreement)
        # The directory the command really runs in: the profile's when it exists, the
        # project root otherwise, so the test is both searched for and named relative to it.
        cwd = (root / str(spec.get("cwd") or ".")).resolve()
        if not cwd.is_dir():
            cwd = Path(root)
        ctx = ReporterCtx(check, profile_id, root, cwd, tuple(argv), fmt, declared_kind, timeout,
                          tuple(identity))
        chosen, how, why_empty, counts = self._choose_test(ctx, declared, profile, spec, pytest_shaped)
        if not chosen:
            message, fix = self._no_test_card(profile_id, profile, root, spec, why_empty, counts, pytest_shaped)
            self.add(check, PERSON_DECIDES, message, fix, profile=profile_id, cases=cases, why_empty=why_empty)
            return
        # One directory per profile, so a report found there was written by THIS run and not by
        # the profile rehearsed before it.
        slot = temp / re.sub(r"[^A-Za-z0-9_.-]", "_", profile_id)
        slot.mkdir(parents=True, exist_ok=True)
        report = slot / f"report.{'trx' if fmt == 'trx' else 'xml'}"
        launch, placed = self._launch_argv(argv, chosen, report, pytest_shaped)
        launch_env = self._launch_env(env, report)
        if not placed and not pytest_shaped:
            # No `<...>` token to put a test into: the command runs as the profile declares it,
            # which still proves the one thing this step is about.
            chosen, how = "the command as declared", "the profile names no selector placeholder"
        # What the durable record says about THIS command of this profile (F11, B-220 part 2): read on every call, never cached
        # in the per-process map (a proof written a moment ago by another process must be seen), and used for what is SAID.
        earlier = self._earlier_proof(profile_id, identity)
        outcome = self._reporter_outcome(ctx, chosen, launch, report, earlier, launch_env)
        if outcome.get("reused"):
            self.note(check, outcome["reused"] + self._accepted_before(profile_id))
            return
        cannot_read = self._record_unreadable(earlier)
        if outcome.get("launcher_missing"):
            # `check_s5_executor` already asked about this binary, with three answers. A second
            # question about one missing launcher is a second stop (TP2-2536).
            import project_env
            self.note(check, f"`{profile_id}`: {project_env.head_not_found(launch[0])} - so its report is unproven; the "
                             "launcher question already covers it" + cannot_read)
            return
        if outcome.get("timed_out"):
            self.add(check, PERSON_DECIDES,
                     f"one test of `{profile_id}` ({chosen}) did not finish within {timeout}s, "
                     f"so whether it writes a report {self.next_stage} can read is unknown" + cannot_read,
                     "answer with your approval: raise `gate_rehearsal.reporter_timeout_s`, or "
                     "go on and let the stage report what it could not read",
                     profile=profile_id, cases=cases)
            return
        if outcome.get("tests"):
            self.note(check, f"`{profile_id}` writes a {fmt if fmt != 'pytest' else 'junit-xml'} "
                             f"report {self.next_stage} can read: {outcome['tests']} test(s) "
                             f"counted from {chosen} ({how})" + self._accepted_before(profile_id) + self._adapted_since(profile_id, identity))
            return
        # B-416 N3 (D-0031): code -> conductor -> person. Neither the gap row nor the cover of B-414 is built before the helper had its one
        # turn per command: with no countable row of the helper's the conductor is called (a finding), and only after it (a row) the person.
        countable = self._adaptation_state(profile_id, identity)
        if countable["state"] == "none":
            self._adapt_finding(check, profile_id, cases, fmt, outcome, declared_kind, identity)
            return
        if countable["note"]:
            self.note(check, f"`{profile_id}`: {countable['note']}, so the helper is taken to have been called: the card is shown")
        understood = next((str(r.get("understood") or "") for r in reversed(countable["rows"]) if r.get("understood")), "")
        self._reporter_card(check, profile_id, cases, fmt, chosen, outcome, launch, argv=argv, earlier=earlier, understood=understood)

    @staticmethod
    def _report_format(profile, argv, spec=None) -> tuple:
        """`(pytest_shaped, declared_kind, fmt)` of one profile's one-test command: whether it is a pytest command, the report kind
        the profile declares, and the format this step reads - the declared kind when it is one the factory reads, `pytest` for a
        pytest command, `none` otherwise.

        FB-22: when the COMMAND names its own format (`spec` = `commands.one_test`, `reporter.format` one of
        `profile_contract.REPORT_FORMATS`), that is the format `--request` executes by, so it is the one proved - the
        explicit `none` included, never guessed from the command's shape - and it is the declared kind too (so no
        legacy-kind heal is offered for a key this step does not read). A command that names none, or a value outside
        the list (`null`, `"TRX"`, `"mocha"`), leaves the rule above exactly as it was: the legacy `reporter.kind` first
        (its `none` included: only a format the COMMAND declares is an explicit `none`)."""
        try:
            from execution_request import is_pytest_command
            pytest_shaped = is_pytest_command(argv)
        except Exception:
            pytest_shaped = any(any(t in part for t in PYTEST_TOKENS) for part in argv[:3])
        command_reporter = spec.get("reporter") if isinstance(spec, dict) else None
        named = command_reporter.get("format") if isinstance(command_reporter, dict) else None
        try:
            from profile_contract import REPORT_FORMATS
        except Exception:
            REPORT_FORMATS = ()
        if isinstance(named, str) and named in REPORT_FORMATS:
            return pytest_shaped, named, named
        declared_kind = str((profile.get("reporter") or {}).get("kind") or "")
        fmt = declared_kind if declared_kind in ("junit-xml", "trx", "pytest") else \
            ("pytest" if pytest_shaped else "none")
        return pytest_shaped, declared_kind, fmt

    @staticmethod
    def _older_setting_note(profile_id, profile, fmt) -> str:
        """FB-22, the sentence for a proof that may not match the run: the stage that runs the tests (`run_suite.py --mine`)
        reads the profile's older `reporter.kind`, this step proves the command's own format (or `pytest` for a pytest
        command whose older kind says `none`). Said only when that older kind is a format the factory reads and differs
        from the one proved; '' otherwise (an unknown older kind is the old rule's business, not a disagreement)."""
        try:
            from profile_contract import REPORT_FORMATS
        except Exception:
            return ""
        older = str((profile.get("reporter") or {}).get("kind") or "")
        if older not in REPORT_FORMATS or older == fmt:
            return ""
        return (f"`{profile_id}`: the report was rehearsed as {fmt}, but the profile's older report setting (`reporter.kind`) "
                f"says {older} and the stage that runs the tests reads that one - the two disagree, so this proof may not "
                "match the run")

    def _choose_test(self, ctx: ReporterCtx, declared, profile, spec, pytest_shaped) -> tuple:
        """`(chosen, how, why_empty, counts)`: the test one rehearsal runs, where the choice came from, and - when `chosen` is
        '' - the closed code of why (`shared_root` | `nothing_under_profile` | `no_test_files`; '' otherwise) with the collect's
        numbers (`_collect_counts`). In this order: the test the project named
        (`gate_rehearsal.reporter_probe_test`), the first node of the gate's collect below the profile's own tests (a pytest command
        only), the first test file under the profile's tests or the command's directory. `chosen` is '' when none is found."""
        import os
        root, cwd = ctx.root, ctx.cwd
        chosen = self._probe_test_of(ctx.profile_id, declared)
        how = "named by `gate_rehearsal.reporter_probe_test`"
        # The profile's own tests (`roots.test`), never the whole project's first one: with two
        # profiles in one harness the first node of the collect is an api test, offered to
        # prove the e2e profile's report (t-218, C5).
        tests_dir = self._profile_tests_dir(profile, root)
        others = self._profiles_sharing_root(profile, tests_dir, root) if self.SHARED_ROOT_PICKS_NOTHING else []
        if not chosen and others:
            # The root does not tell this profile's tests from the others' (an api and a ui profile over one
            # `tests/`): the first test under it is as likely theirs, and a report it proved said nothing about
            # this profile - the ui rehearsal "passed" on an api test and S5 met the gap (EP1-10). No pick by
            # path; the project names one, and the card below says so.
            self.note(ctx.check, f"`{ctx.profile_id}`: shares its test root `{self._root_rel(tests_dir, root)}` with "
                                 f"{', '.join('`' + o + '`' for o in others)}, so the first test under it cannot be "
                                 "told to be this profile's and none was picked; name one in "
                                 "`gate_rehearsal.reporter_probe_test`")
            return ("", "no test of this profile's own could be told apart (shared test root)", "shared_root",
                    self._collect_counts(tests_dir, root, pytest_shaped))
        prefix = self._node_prefix(tests_dir, root)
        if not chosen and pytest_shaped and prefix is not None:
            chosen = first_collected_node(self.collect_stdout, prefix)
            how ="the first test of the profile's own tests the gate's collect found"
        if not chosen:
            found = first_test_file(tests_dir if tests_dir is not None else cwd)
            if found:
                try:
                    chosen = os.path.relpath(found, cwd).replace("\\", "/")
                except ValueError:
                    chosen = found
                how = "the first test file under " + str(spec.get("cwd") or ".")
        counts = self._collect_counts(tests_dir, root, pytest_shaped)
        if chosen:
            return chosen, how, "", counts
        # Why nothing was found, as a closed code (FR-12: the card's words are built from it and the counts, never the reverse).
        # A collect that listed nothing is UNKNOWN, not "no tests" (FR-41): only a read collect says "none of them".
        return "", how, ("nothing_under_profile" if counts["collected"] and not counts["under_prefix"] else "no_test_files"), counts

    def _collect_counts(self, tests_dir, root, pytest_shaped) -> dict:
        """`{collected, under_prefix, prefix}` of the gate's collect for one profile: the nodes it listed, those below the
        profile's tests, and the folder the filter used (as the collect spells it; the project-relative folder when it lies
        outside `tests_root`, where no node can be below it). A command that is not pytest-shaped uses no collect: 0 and 0."""
        prefix = self._node_prefix(tests_dir, root)
        shown = prefix if prefix is not None else self._root_rel(tests_dir, root)
        if not pytest_shaped:
            return {"collected": 0, "under_prefix": 0, "prefix": shown}
        return {"collected": len(collected_nodes(self.collect_stdout)),
                "under_prefix": 0 if prefix is None else len(collected_nodes(self.collect_stdout, prefix)),
                "prefix": shown}

    def _no_test_card(self, profile_id, profile, root, spec, why_empty, counts, pytest_shaped=True) -> tuple:
        """`(message, fix)` of the card for an empty choice, by the closed code `_choose_test` returned (HF8-14). Only numbers
        and folders from `counts` are printed, nothing is cut; one door (`gate_rehearsal.reporter_probe_test`), no new command."""
        # the way out AND what going on costs, for every code: the consequence is the same whatever left the choice empty
        door = ("answer with your approval: name one existing test in `gate_rehearsal.reporter_probe_test` (a node id or a file, "
                "per profile or one for all) and I rehearse again, or go on and let S5 find out. If you go on, "
                f"{self.next_stage} runs the tests of `{profile_id}` anyway; if their report cannot be read, every run of "
                f"`{profile_id}` is recorded as not executed, and you learn that only there")
        tests_dir = self._profile_tests_dir(profile, root)
        if why_empty == "shared_root":
            others = self._profiles_sharing_root(profile, tests_dir, root)
            names = ", ".join(f"`{o}`" for o in others)
            return (f"The `{profile_id}` tests and the {names} tests are kept in one folder (`{self._root_rel(tests_dir, root)}`), "
                    f"so I cannot tell which existing test belongs to `{profile_id}`, and none was run to prove its report.",
                    door)
        if why_empty == "nothing_under_profile":
            return (f"The list of tests the gate read holds {counts['collected']}, none of them under `{counts['prefix']}`, the folder of "
                    f"the `{profile_id}` tests; no test file was found there either.", door)
        where = self._root_rel(tests_dir, root) if tests_dir is not None else str(spec.get("cwd") or ".")
        # the wording follows what the gate HAD (FR-41): no listing because the command is not pytest, no listing because none ran, or a
        # listing that ran and found nothing; the person's words, not the gate's insides (human-questions.md); each under BRIEF_CUT
        if not pytest_shaped:
            head = "I could not list this project's tests (only pytest can be asked, this is not pytest)"
        elif not self.collect_stdout.strip():
            head = "I have no list of this project's tests (the listing did not run)"
        else:
            head = "The listing of this project's tests found none"
        return (f"{head}, and no file under `{where}` has a usual test name, so nothing proves `{profile_id}` writes a report the "
                "tests stage reads.", door)

    @staticmethod
    def _launch_argv(argv, chosen, report, pytest_shaped) -> tuple:
        """`(launch, placed)`: the profile's argv with `{report_path}` replaced by the report's path, a `<...>` token replaced by
        the chosen test (`placed`), and for a pytest command the test appended when there is no such token and `--junitxml` added
        when the command has none. Pure: it reads and writes nothing."""
        launch, placed = [], False
        for token in argv:
            if "{report_path}" in token:
                launch.append(token.replace("{report_path}", str(report)))
                continue
            if token.startswith("<") and token.endswith(">"):
                launch.append(chosen)
                placed = True
                continue
            launch.append(token)
        if not placed and pytest_shaped:
            launch.append(chosen)
        if pytest_shaped and not any(str(t).startswith("--junitxml") for t in launch):
            # The rule the runner itself applies: pytest is the one framework the factory
            # equips on its own, so a pytest profile is proven the way it will really run.
            launch.append(f"--junitxml={report}")
        return launch, placed

    @staticmethod
    def _launch_env(env, report) -> dict:
        """The variables the command is launched with: `{report_path}` in a value replaced by the report's path, exactly as
        `run_suite` does for the run (FR-17: S5 and the probe agree on what a proven command is). Pure."""
        return {str(name): str(value).replace("{report_path}", str(report)) for name, value in (env or {}).items()}

    def _reporter_outcome(self, ctx: ReporterCtx, chosen, launch, report, earlier, launch_env=None) -> dict:
        """What came of this command with this test: the per-process map's outcome for the key (cwd, argv, test, format), else
        the durable proof when exactly this command was already proved (`{"reused": <the sentence>}`), else the run itself
        (`_probe_reporter`; what it left unread is kept for the helper, a proven report is recorded). Writes `_REPORTER_PROBES` and
        `self._rehearsing_argv`; `earlier` is what the durable record says about this command (`_earlier_proof`)."""
        check, profile_id, root, cwd, fmt, declared_kind = ctx.check, ctx.profile_id, ctx.root, ctx.cwd, ctx.fmt, ctx.declared_kind
        # WHICH command: the identity (EP1-22 B-2) keys the per-process map, the durable record and the helper's rows alike; on a
        # command with no `env` it is the argv words, so every key and digest is byte for byte what it was
        command_id = list(ctx.identity or ctx.argv)      # NOT `identity` below: that is the stand's runtime identity, a record field
        key = (str(cwd), tuple(command_id), chosen, fmt)
        outcome = _REPORTER_PROBES.get(key)
        if outcome is None:
            # The durable half (D-0019 item 2, F11): a rehearsal that already proved a report for exactly this
            # command of this project - by the onboarding or by an earlier gate, on any stand - is not paid for
            # again. `same_command` AND the key must both agree: the key also holds what the proof was ABOUT
            # (the test it ran, the report format, the dependency files), so a proof is never reused for a
            # different argv (the invariant) and never for the same words over other dependencies (FR-59).
            durable = self._rehearsal_key(profile_id, cwd, command_id, chosen, fmt, "", root)
            hit = (getattr(self, "_rehearsals", None) or {}).get(durable) if durable else None
            if isinstance(hit, dict) and isinstance(hit.get("at"), str) and earlier["state"] == "same_command":
                # The hit fills the per-process map too, so the next gate call of this process does not launch again.
                who = ("the onboarding proved it on" if hit.get("source") == "onboarding" else "rehearsed on")
                outcome = _REPORTER_PROBES[key] = {"reused": (
                    f"`{profile_id}` writes a report {self.next_stage} can read"
                    f" — {who} {hit['at'][:10]} for this project and exactly this command "
                    "(the same words, test, report format and dependency files); "
                    "not rehearsed again (to rehearse again, remove this command's entry from "
                    f"qa-factory/state/{REPORTER_REHEARSALS_FILE}, or the file)")}
            else:
                # Observed only now, for the record: it no longer keys a proof, so a reuse never asks the stand.
                identity = self._observed_identity(profile_id, root)
                self._rehearsing_argv = list(command_id)
                # the variables go only when the command sets some: a probe that is given none is called exactly as before
                outcome = (self._probe_reporter(launch, cwd, ctx.timeout, report, fmt, env=launch_env) if launch_env
                           else self._probe_reporter(launch, cwd, ctx.timeout, report, fmt))
                _REPORTER_PROBES[key] = outcome
                if not (outcome.get("tests") or outcome.get("launcher_missing") or outcome.get("timed_out")):
                    outcome["kept"] = self._keep_unread(check, profile_id, list(ctx.argv), fmt, declared_kind, report.parent, outcome,
                                                        command_id=command_id)
                if outcome.get("tests") and durable:
                    # Only a proven report is kept. A missing report, a timeout or a missing
                    # launcher is what the person's fix is about to change: the next call must
                    # look again.
                    self._record_rehearsal(check, durable, profile_id, chosen, fmt, identity,
                                           outcome["tests"])
        return outcome

    def _has_story(self) -> bool:
        """Does this rehearsal belong to a story? The onboarding probe has none (its folder holds no `pipeline.json`): the record of
        the helper's turns and the environment record are about a STORY's gate and are never asked for it."""
        return (self.task_root / "pipeline.json").is_file()

    def _adaptation_state(self, profile_id, command_id) -> dict:
        """B-416 N3: `{state, rows, note}` of the helper's rows for THIS command (`report_adapt.countable`; `command_id` is the
        command's identity words, `profile_contract.command_identity`, EP1-22 B-2): `none` (the conductor is called),
        `rows` (a row counts: the card), `unknown` (a record that cannot be read: read as a row, FR-59). A rehearsal with no story is `rows`
        with nothing to say: the card, as before (onboarding's text is unchanged)."""
        if not self._has_story() or self.project_root is None:
            return {"state": "rows", "rows": [], "note": ""}
        try:
            import report_adapt
            from onboarding_probe import argv_digest
            return report_adapt.countable(self.project_root, profile_id, argv_digest(command_id))
        except Exception as exc:
            return {"state": "unknown", "rows": [], "note": f"the helper's record could not be consulted ({type(exc).__name__})"}

    def _adapted_since(self, profile_id, command_id) -> str:
        """` - read since the adaptation of <date>` when the helper set the report kind of this command (its identity words,
        EP1-22 B-2) and the report reads now."""
        if not self._has_story() or self.project_root is None:
            return ""
        try:
            import report_adapt
            from onboarding_probe import argv_digest
            row = report_adapt.last_adaptation(self.project_root, profile_id, argv_digest(command_id))
        except Exception:
            return ""
        return f" - read since the adaptation of {str(row.get('at') or '')[:10]}" if row else ""

    def _keep_unread(self, check, profile_id, argv, fmt, declared_kind, slot, outcome, command_id=None) -> str:
        """B-416 N2: keep what the probe run wrote and the code could not read, for the helper (`report_adapt.keep_unread`): the folder of the
        profile is REPLACED, at most `KEEP_FILES` files of at most `KEEP_LIMIT` bytes, and a manifest of the command, the digest, what was
        tried, the sha256 of every file and the tails of the run's output (names only). `no_file` is kept too (the helper reads the
        toolchain fault from the tails). A candidate of the onboarding (`durable` False) keeps nothing, and neither does a rehearsal with no story (the onboarding's own
        probe: no conductor turn is owed there, and the probe leaves the project as it was but for the proven-rehearsal record). A copy
        that failed is one note. Returns the kept folder as the person's project reads it, or ""."""
        if not getattr(self, "durable", True) or self.project_root is None or not self._has_story():
            return ""
        try:
            import report_adapt
            import reporters
            from onboarding_probe import argv_digest
            from stand_gaps import names_only
            limit = report_adapt.TAIL_LIMIT
            tail = lambda text: names_only(" ".join(str(text or "").split())[-limit:])[-limit:]  # noqa: E731
            # `argv` is the words shown to the helper; the digest is of the command's IDENTITY (`command_id`, EP1-22 B-2: the same
            # digest `report_adapt.prove_kept` and the gate's manifest read), which is the argv words when the command has no `env`
            meta = {"argv": list(argv), "argv_digest": argv_digest(command_id if command_id is not None else argv), "fmt": fmt, "declared_kind": declared_kind,
                    "reason_class": str(outcome.get("reason_class") or ""), "stdout_tail": tail(outcome.get("stdout")),
                    "stderr_tail": tail(outcome.get("stderr")), "tried": outcome.get("tried") or [], "fit": str(outcome.get("fit") or "")}
            manifest, problem = report_adapt.keep_unread(self.project_root, profile_id, slot, meta, reporters.KEEP_FILES, reporters.KEEP_LIMIT)
        except Exception as exc:
            manifest, problem = None, f"the report could not be kept ({type(exc).__name__})"
        if manifest is None:
            self.note(check, f"`{profile_id}`: {problem}")
            return ""
        return f"{report_adapt.UNREAD_REL}/{report_adapt.safe_name(profile_id)}/"

    def _adapt_finding(self, check, profile_id, cases, fmt, outcome, declared_kind, command_id) -> None:
        """B-416 N3: a report the code could not read goes to the CONDUCTOR first - one `factory_fixable` finding, and no card, no cover.

        The message says the level, the reason, what was tried and where the report is kept; the `fix` is the action in WORDS (the command
        is a row of `conductor-actions.json`). Typed fields (FR-12): `profile`, `argv_digest`, `kept`, `fit`, `declared_kind`; and, when
        exactly one reader fits and the declared kind is EMPTY, `argv` - the exact `report_adapt.py kind` command the driver runs by its
        own code (`GATE_REPAIRS`, N6): FR-48, a fixed command is not the conductor's."""
        from onboarding_probe import argv_digest
        kept, fit = str(outcome.get("kept") or ""), str(outcome.get("fit") or "")
        tried = sorted({str(r.get("reader")) for r in outcome.get("tried") or []})
        said = (f"; it was tried as {' and '.join(tried)} and none of them reads a test" if tried and not fit else
                f"; only {fit} reads a test in it" if fit else "")
        extra = {"profile": profile_id, "argv_digest": argv_digest(command_id), "kept": kept, "fit": fit, "declared_kind": declared_kind,
                 "cases": list(cases)}
        if fit and not declared_kind:
            extra["argv"] = ["{python}", "{plugin_root}/scripts/report_adapt.py", "kind", "--profile", profile_id, "--reader", fit,
                             "--by", "driver", "--task", self.ticket]
        self.add(check, FACTORY_FIXABLE,
                 f"the {profile_id} tests: one existing test ran and left no report {self.next_stage} can read ({outcome.get('why')}){said}"
                 + (f"; the report is kept in {kept}" if kept else ""),
                 "the factory's helper reads the kept report and records what it changed or understood", **extra)

    def _earlier_proof(self, profile_id, command_id) -> dict:
        """`onboarding_probe.earlier_proof` for this command (`command_id`: its identity words, EP1-22 B-2 - the same command with
        another `env` is another command): {state: same_command | command_changed | none | unreadable, at}.
        The reader is imported at the moment of use (the probe imports this module), and a reader that cannot be
        imported is `unreadable`: an unknown is never a proof (FR-59), the gate rehearses."""
        try:
            import onboarding_probe
            return dict(onboarding_probe.earlier_proof(self.project_root, profile_id, command_id))
        except Exception as exc:
            return {"state": "unreadable", "at": "", "why": f"{type(exc).__name__}: {str(exc)[:80]}"}

    @staticmethod
    def _record_unreadable(earlier: dict) -> str:
        """The tail of a sentence that says a rehearsal could not establish the report AND the record of earlier proofs
        could not be read (so there was nothing to fall back on): '' for every other state of the record."""
        if earlier.get("state") != "unreadable":
            return ""
        return "; the factory's record of earlier proofs could not be read either, so nothing earlier can be relied on"

    def _accepted_before(self, profile_id: str) -> str:
        """B-220 part 2, conflict (ii): the person had said to go on WITHOUT this profile's report (`accept` on its card), and a
        rehearsal now reads the report. The PROOF wins what the gate states and records - a waiver is a word about a block,
        and the block is gone, so it must not hide a fact - and the person's word is not erased (it stays on the record, FR-4); what S5
        does with a case accepted as blocked is not decided here. '' when there is no such word."""
        try:
            import contract
            said = contract.stand_gap_decisions(self.pipeline).get(f"RP-{profile_id}") or {}
        except Exception:
            return ""
        if said.get("option") != "accept":
            return ""
        return (" - you had said to go on without this report; that word stays on the record, and the report is readable now, "
                "so the proof is stated here and not hidden by it")

    def _probe_reporter(self, launch, cwd, timeout, report: Path, fmt: str, env=None) -> dict:
        """Run the command once and say what came of it. Nothing of the caller's is written:
        the report goes to the OS temp directory the step made for it. `env` (EP1-22): the variables the command sets, already
        holding the report's path (`_launch_env`); they win over the process environment, as in `run_suite`."""
        import os
        import node_ids
        import project_env
        try:
            out = node_ids.run_captured([str(t) for t in launch], str(cwd),
                                        {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **{str(k): str(v) for k, v in (env or {}).items()}},
                                        timeout)
        except project_env.CmdUnsafe as exc:
            # A `.cmd` wrapper would corrupt an argument: nothing ran. The existing "no report" move (AR-25), with the
            # refusal's own sentence as the reason; a new outcome key would be a state with no reader.
            return {"tests": 0, "why": str(exc), "reason_class": "no_file", "tried": [], "fit": None,
                    "returncode": None, "stdout": "", "stderr": ""}
        except FileNotFoundError:
            return {"launcher_missing": True}
        except subprocess.TimeoutExpired:
            return {"timed_out": True}
        tests, why, reason_class, tried, fit = self._read_probe_report(report, fmt)
        return {"tests": tests, "why": why, "reason_class": reason_class, "tried": tried, "fit": fit, "returncode": out.returncode,
                "stdout": out.stdout or "", "stderr": out.stderr or ""}

    def _read_probe_report(self, report: Path, fmt: str) -> tuple:
        """(tests counted, why not, reason class, tried, fit) of the report one probe run was supposed to write.

        The class (`environment_record.REASON_CLASSES`, B-414 R1) is the TYPED form of the reason, so that nothing reads it back
        out of a sentence: `no_file` (no report file was written), `unparsable` (the report it wrote cannot be parsed),
        `zero_tests` (it counts no test); "" when the report was read.

        B-416 N1: a report that declares XML entities is refused BEFORE the declared parse (a hostile report never reaches the parser),
        and on every failure the other readers the factory has are tried on what the run wrote (`_readers_tried`): `tried` is what each
        counted, `fit` the reader that fits when EXACTLY one does, else "". A success has neither.

        THE FILE, AND ONLY THE FILE (EP1-22, I-1, FR-17): S5 reads the one path it gave the command (`run_suite`: the unique
        report of the run) and nothing beside it, so the proof is that file and never a neighbour of it. A framework that
        names its file itself (`TESTS-chrome.xml` beside the path it was given) is NOT proven by it: the run left no
        report where S5 looks, and S5 would record every run as not executed. The direction of every doubt here is toward
        `no_file` / `unparsable`, never toward a count: a folder where the file should be, a missing file, an empty file. A
        missing file keeps `tried == []` and `fit == ""` (a neighbour is no proof: the helper must not be handed a reader that
        "fits" a file S5 never reads, and `_adapt_finding` must not write a config by it); the neighbours are named in
        `why` and kept as they are by `_keep_unread`, which the helper reads itself."""
        import reporters
        siblings = ([p for p in sorted_paths(report.parent.rglob("*")) if p.is_file() and p != report]
                    if report.parent.is_dir() else [])
        if report.is_dir():
            return (0, "the path it was given is a folder, not a file", "no_file", [], "")
        if not report.is_file():
            beside = ""
            if siblings:
                names = ", ".join(p.relative_to(report.parent).as_posix() for p in siblings)
                beside = (f"; the run left {len(siblings)} other file(s) beside it ({names}), which S5 would not read")
            return (0, "no report file was written" + beside, "no_file", [], "")
        if report.stat().st_size == 0:
            return (0, "the report file it wrote is empty", "no_file", [], "")
        files = [report]
        if reporters.entity_declared(report):
            return (0, "the report declares XML entities, which the factory does not expand", "unparsable") + self._readers_tried(files)
        try:
            import run_suite
            totals = (run_suite.parse_trx(report) if fmt == "trx"
                      else run_suite.parse_junitxml(report)).get("totals") or {}
        except Exception as exc:
            return (0, f"the report it wrote is not one the factory can parse "
                       f"({type(exc).__name__}: {exc})", "unparsable") + self._readers_tried(files)
        if int(totals.get("tests") or 0) >= 1:
            return (int(totals["tests"]), "", "", [], "")
        return (0, "the report it wrote counts no test at all", "zero_tests") + self._readers_tried(files)

    @staticmethod
    def _readers_tried(files: list) -> tuple:
        """`(tried, fit)`: every reader of `reporters.fits` run over at most `KEEP_FILES` files of the run. `tried` rows are names and
        counts only (`file`, `reader`, `tests`, `error`); `fit` is the one reader that counts a test in some file, "" when none does or two
        do (the conductor decides, FR-48: code never picks between readers)."""
        import reporters
        tried, fitting = [], set()
        for path in files[:reporters.KEEP_FILES]:
            for row in reporters.fits(path):
                tried.append({"file": path.name, "reader": row["reader"], "tests": row["tests"], "error": row["error"]})
                if row["tests"] >= 1:
                    fitting.add(row["reader"])
        return tried, (next(iter(fitting)) if len(fitting) == 1 else "")

    # What a reporter card says first, per what the durable record knows of THIS command (F11, FR-41: "no longer" only on a
    # record). `none` says nothing extra: the card's own sentence already says no run of it left a report.
    _EARLIER_SAYS = {
        "same_command": ("the command stopped working: a run of exactly this command left a report the factory could read "
                         "on {at}, and now it does not"),
        "command_changed": ("the command changed since it was last proved: a run of the earlier command left a report the "
                            "factory could read on {at}, and the command recorded now is another one"),
        "unreadable": ("the factory's record of earlier proofs could not be read, so whether this command ever left a "
                       "report is not known"),
    }

    def _reporter_offers(self, launch) -> tuple:
        """(the options this reporter card offers, whether a cure that is ONE change of the command exists).

        ONE switch, data: `question-vocabulary.json` `probe_answers.live` (flipped together with the driver's handlers). While
        it is false (this release) the card offers exactly `theirs`, `handed`, `accept` - `myself`, `run`, `accept` in the person's
        words - whatever the cure table holds, even when the cure is already in the command: `command` and `change` are read by
        nothing yet, and a word that nothing executes must not be offered (FR-9; t-409 H1 - `change` was recorded as a waiver that
        closed the card and changed nothing). While it is true: `command` (the person gives their own line) and `apply`
        (`change`), the last only when `report-cures.json` holds a cure that is one change of THIS command (a row with
        `add_argv`: the others need a package or a config edit, which the factory does not make - Y7, F12; a row's `add_env`
        (EP1-22: the variables the same cure puts in the command's `env`) is part of that one change of the command, not a
        thing the factory does not make). TEMPORAL, for whoever flips `live`: the `apply` handler must then write the cure's
        `env` as well as its `argv` (`onboarding_probe.classify_cure` `candidate_env`, `config_contract.command_proposal(env=)`),
        or a `change` offered here would apply half a cure. A table or a vocabulary that cannot be read offers less, never more."""
        cure = False
        try:
            import report_cures
            row = report_cures.row_for(launch)
            cure = bool(row and row.get("add_argv"))
        except Exception:
            cure = False
        live = False
        try:
            import gate_brief
            live = bool(gate_brief.probe_answers().get("live"))
        except Exception:
            live = False
        return (["command"] if live else []) + (["apply"] if live and cure else []) + ["theirs", "handed", "accept"], cure

    @staticmethod
    def _with_command(change: str, argv) -> str:
        """`change` with the command the profile records NOW, in backquotes - the one thing the action line (`the fix:`) may
        carry (`human-text.json` `action_lines`, F6). Said only when the whole line then passes the shape rules: a recorded
        command with a shape the rules refuse (`x=true`) is left out, so a card is never dirtied by the project's own words."""
        if not argv:
            return change
        try:
            import human_text
            from config_contract import display_command
            where = "qa-factory/config.json, the command that runs one test"
            fuller = f"{change} (the command recorded now: `{display_command(argv)}`)"
            return fuller if not human_text.shape_problems(f"the fix: {where} -> {fuller}") else change
        except Exception:
            return change

    def _reporter_card(self, check, profile_id, cases, fmt, chosen, outcome, launch, argv=None, earlier=None, understood="") -> None:
        """The stand-gap card of a profile whose run leaves nothing the factory can read - or no card at all, when the
        environment record covers it (B-414 R7: after the probe, on the card branch only).

        A failing test is fine here — the reporter is what is proven, not the product. `argv` is the command the profile
        records (it goes on the fix line, `_with_command`); `earlier` is what the durable record says of it
        (`_EARLIER_SAYS`). The card's `remedy` also carries two UNPRINTED fields the answer reader uses: `profile` (whose
        command a `command` line is about) and `offers` (the options this card takes, `_reporter_offers`).

        The gap is a LEVEL gap (B-414 R1): it speaks of every test of the execution contour, so its row carries `scope`,
        `contour` and every case (`cases`), and no `case` of its own."""
        row = self._reporter_gap_row(profile_id, cases, fmt, chosen, outcome, launch, argv, earlier)
        if understood.strip():     # what the factory's helper read of the report (N7): shown on the card, names only, at most UNDERSTOOD_SHOWN characters
            from stand_gaps import names_only
            try:
                import report_adapt
                shown = report_adapt.UNDERSTOOD_SHOWN      # the stored cut is the shown cut (t-683 D10)
            except Exception:
                shown = None    # the rule that says how much to show cannot be loaded: the row carries none, never a guess (FR-59)
            if shown is not None:
                row["understood"] = names_only(understood)[:shown]      # outside the try: a scrubber failure propagates as before D10
        if self._environment_cover(check, row):
            return
        self.stand_gaps.append(row)
        self.add(check, PERSON_DECIDES,
                 f"{GAP_SLOT} — one existing test ran and "
                 f"left no report {self.next_stage} can read, so every run of the {profile_id} tests would be "
                 "recorded as not executed; the exact change is known, so this is a card at "
                 "this gate and not a surprise inside the stage",
                 self.card_door(row["id"]), gap=row["id"], gap_case="", profile=profile_id, cases=list(cases))

    def _reporter_gap_row(self, profile_id, cases, fmt, chosen, outcome, launch, argv, earlier) -> dict:
        """The LEVEL gap row of a reporter card (`scope`, `contour`, `cases`, the typed `reason_class` and `exit_code`, the key
        `accept always` would be recorded under or why there is none). Nothing is appended or asked here."""
        gap_id = f"RP-{profile_id}"
        why, stdout = str(outcome.get("why") or ""), str(outcome.get("stdout") or "")
        stderr = str(outcome.get("stderr") or "")
        try:
            from run_suite import report_cure
            cure = report_cure(launch)
        except Exception:
            cure = ""
        if not cure:
            # pytest is equipped by the runner itself, so "no report" is never the flag here:
            # the card says what actually went wrong instead of naming a cure that is not one.
            cure = ("the runner already asks pytest for a JUnit report itself, so the report is missing "
                    "for another reason: " + collect_failure(stdout, stderr)) if fmt == "pytest" else \
                ("name the flag that makes this command write a JUnit XML report and add a "
                 "`{report_path}` token to the argv, so the factory reads a run-unique file")
        tail = " ".join((stderr or stdout).split())[-400:]
        offers, _cure_is_one_change = self._reporter_offers(launch)
        earlier = earlier or {"state": "none", "at": ""}
        first = self._EARLIER_SAYS.get(earlier.get("state"), "").format(at=str(earlier.get("at") or "an earlier day"))
        row = {
            "id": gap_id, "case": "", "scope": "level", "contour": profile_id, "cases": list(cases), "kind": "reporter",
            "reason_class": str(outcome.get("reason_class") or ""), "exit_code": outcome.get("returncode"),
            "what": (first + " - " if first else "") + f"{profile_id} writes no "
                    f"{fmt if fmt not in ('none', 'pytest') else 'machine-readable'} report the "
                    f"factory can read ({why}; one existing test ran on {chosen}"
                    + ("" if outcome.get("returncode") is None else
                       ", and the run ended with an error" if outcome.get("returncode") else
                       ", and the run ended normally") + ")",
            "partitions": [], "state": "unmet",
            "remedy": {"kind": "reporter",
                       "where": f"qa-factory/config.json:profiles[{profile_id}].commands.one_test",
                       "where_words": f"qa-factory/config.json, the command that runs one {profile_id} test",
                       "change": self._with_command(cure, argv), "restart": "",
                       "profile": profile_id, "offers": offers},
            "detail": tail}
        self._lasting_of(row)
        return row

    def _lasting_of(self, row: dict) -> None:
        """Say on a gap row whether `accept always` is offered for it (B-414 R4, M8, M13): `property_key` - the key an answer
        would be recorded under, or None - and `lasting`, why there is none (`fault`: the cause is a file or the machine, never
        a property of the environment; `no_key`: nothing to key it by). The ONE derivation (`environment_record.lasting`) the
        command line `record` uses too, with the stand `stand_gaps.stand_name` gives."""
        try:
            import environment_record
            import stand_gaps
            stand = stand_gaps.stand_name(self.task_root)
            got = environment_record.lasting(row, self.config, stand)
            row.update(property_key=got["key"], lasting=got["why"], stand=stand)
        except Exception:
            row.update(property_key=None, lasting="no_key")

    def _environment_cover(self, check, row) -> bool:
        """B-414 R7: is this gap covered by what a person accepted once for this environment? True: no card, no finding -
        `covered_gaps` holds the row with the record's row under `property`, and one note says so in words.

        Reached only AFTER the probe, and (when B-416 lands) after the adaptation lookup - on the card branch alone - so the
        record never hides a report the probe reads, and never skips a probe (E7, E15). An unreadable record is said once and
        covers nothing (FR-59). A rehearsal that belongs to no story (the onboarding probe: its folder holds no `pipeline.json`)
        never asks the record (E16). A record held for the SAME command or stand but another one NOW is said on the card."""
        key = row.get("property_key")
        if not key or self.project_root is None or not self._has_story():
            return False
        import environment_record as ER
        rows, problem = ER.load(self.project_root)
        name = row.get("contour") or row.get("id")
        if problem:
            self.note(check, f"`{name}`: the environment record could not be read ({problem}), so it covers nothing and the "
                             "card is shown")
            return False
        held = ER.covering(rows, key)
        if held is None:
            profiles = {str(p.get("profile_id")) for p in self.config.get("profiles") or [] if isinstance(p, dict)}
            lost = sorted({str(r["subject"].get("contour")) for r in rows if ER.live_level(r)} - profiles - {""})
            if lost:      # E3: a contour that was renamed or removed: its answer covers nothing, and the note names it
                self.note(check, "the environment record holds an answer for " + ", ".join(f"`{c}`" for c in lost)
                                 + ", which is no longer a test command of this project: it covers nothing")
            earlier, why = ER.near_miss(rows, key)
            if earlier is not None:
                row["changed_since"] = {
                    "command": f"the command changed since {str(earlier.get('at'))[:10]}, when you recorded an answer for the earlier one",
                    "reason": f"this command now fails for another reason than the one you recorded on {str(earlier.get('at'))[:10]}",
                    "address": f"the stand's address changed since {str(earlier.get('at'))[:10]}, when you recorded this answer",
                }[why]
            return False
        self.covered_gaps.append(dict(row, property=held))
        self.note(check, f"`{name}`: not asked - {ER.says(held)}, as you recorded on {str(held.get('at'))[:10]} ({held.get('id')})")
        return True

    # --- gate A: 4d. does the stand run THIS story's code? ----------------------------------

    def check_s5_runtime_probe(self) -> None:
        """A profile with no `execution.runtime_probes` entry is derived and checked here, once.

        `execution_request.py` refuses the story's first typed run of a profile that has no probe
        (`probes["*"]` counts as one), and on cmp2 that refusal cost two automator dispatches in
        S5 for a fact the config and the running stand already held. A registered probe is left
        to the reporter step, which observes it; this one never re-runs it.

        For an unregistered profile the spec is derived in memory (the selected stand; the
        checkout of the repository whose `execution_profile_id` is the profile; the container by
        CONTENT - a candidate holds every file the story changed) and the probe is run once with
        `--task-root` and `--no-evidence`, so a rehearsal still writes nothing (FR-45). Nothing is
        ever written to config.json or the story: writing the entry is `runtime_probe.py
        --suggest --write`, a repair the driver owns (t-225), whose exact argv this step carries
        (`argv` on the INFO line, FR-12: the driver reads the field, never the sentence).

          matched      `factory_fixable` (`_probe_derived`): the exact write argv travels as a list in
                       the finding's `argv` field, never in its sentence; `stage_done` refuses to
                       close S4 over it until the driver's repair row has run it (t-261, t-279)
          mismatched   person_decides: the stand runs other code than this story's
          unknown      `factory_fixable` quoting the probe's own error + the same argv field
          not_applicable  INFO quoting the probe's own reason (nothing of the story is in this
                       checkout); no argv rides on it, nothing is registered
          no candidate INFO: a stand that serves a BUILT bundle holds no sources to compare
                       (F3d); a fact about the stand, never a card
          nothing to compare  INFO: the story's diff does not touch the profile's checkout (C4), or
                       NO diff is recorded for it - two facts, two sentences (W1, FR-41); no docker
                       call, no probe, no card
          the argv in the INFO lines is the PORTABLE form (`{python}`, `{plugin_root}`, W5)
          no checkout recorded for the profile  INFO, one per profile (Q1, FR-41)
          2+ candidates, a docker that does not answer, an ambiguous checkout or stand:
                       ONE person_decides card per profile
          timeout, or an answer that is not a provenance record (no JSON, no `result`):
                       factory_defect - the probe gave no verdict (D4)
          person_confirmed  INFO: the person's word for this story, said as such (t-300); no argv, nothing registered
          a `result` outside the five words above (`MATCHED`, a number): factory_defect naming it
                       (W3) - an INFO line would read as a stand that was checked

        `gate_rehearsal.skip_runtime_probe: true` turns the step off."""
        check = "s5_runtime_probe"
        root = self.project_root
        if root is None or self._gate_switch("skip_runtime_probe"):
            return
        keyed = self.keyed_profiles()
        if not keyed:
            return
        import runtime_probe as rp
        handed = self._handed()
        execution = self.config.get("execution") if isinstance(self.config.get("execution"), dict) else {}
        probes = execution.get("runtime_probes") if isinstance(execution.get("runtime_probes"), dict) else {}
        for profile_id in sorted(keyed):
            spec = probes.get(profile_id) or probes.get("*")
            if profile_id in handed or (isinstance(spec, dict) and spec.get("argv")):
                continue
            if not rp.has_checkout(self.config, profile_id):
                # Silence here read exactly like a step that never ran (FR-41). Nothing is asked
                # and nothing is run: there is no code to compare the stand with.
                self.note(check, f"`{profile_id}`: no checkout is recorded for it, so what its "
                                 "stand runs is not checked here; S5's first run on the profile "
                                 "will be written from the request template", profile=profile_id)
                continue
            self._derive_probe(check, profile_id)

    def _probe_derived(self, check: str, profile_id: str, message: str, argv: list) -> None:
        """A probe the project has not registered and the stand proved: the factory's own repair
        (`factory_fixable`), not a note - the driver's `GATE_REPAIRS` row `s5_runtime_probe`
        resolves the tokens of `argv` (`runtime_probe.resolve_argv`) and runs it, and `stage_done`
        refuses to close S4 over it until it has run (t-261, t-279). The argv travels as a LIST in
        the finding's `argv` field, which the driver reads; the sentence never carries it as the
        driver's input (FR-12), and the plugin's own command line is not a sentence for a person
        (FR-6) - and, since t-357, not `fix` either: `fix` is read by a person in the rehearsal text, so it says in words
        that the factory writes the entry itself."""
        self.add(check, FACTORY_FIXABLE, message,
                 "the factory registers this probe for the profile itself, from what the running stand proved; "
                 "nothing is asked of you", profile=profile_id, argv=list(argv))

    def _probe_card(self, check: str, profile_id: str, message: str, offer: str,
                    container_exit: bool = True, **extra) -> None:
        """One card per profile. A person's word passes it (FR-4); where the question was "which
        container", saying the stand is not a container one is the second way out."""
        block = f"runtime probe: {profile_id}"
        self.add(check, PERSON_DECIDES, f"{block} — {message}",
                 f"answer with your approval: {offer}"
                 + (", or say this stand is not a container one" if container_exit else "")
                 + f" — {self.waiver_command(block)}", profile=profile_id,
                 **extra)

    def _probe_defect(self, check: str, profile_id: str, what: str, label: str, **extra) -> None:
        """The probe gave no verdict - it did not answer, or what it printed is not a provenance
        record. One branch for both (D4): the probe is the factory's own, so this is the factory's
        defect, and S5's first typed run will meet the same question. The message opens with the
        block text a person's word is matched against (FR-4)."""
        block = f"runtime probe: {profile_id}"
        self.add(check, FACTORY_DEFECT,
                 f"{block} — the probe {what}, so whether {label} runs this story's code is "
                 "unknown before S5",
                 "the probe is the factory's own: S5's first typed run will meet the same "
                 f"question; {self.waiver_command(block)}",
                 profile=profile_id, **extra)

    def _probe_picks(self, rp, profile_id: str) -> tuple:
        """`(environment, checkout, refusal)`: the stand this rehearsal is about and the checkout its profile runs from, or the
        runtime probe's own refusal (an object whose `plain` half a person reads) when either cannot be told. Reads, says nothing."""
        stand = str(self._selected_environment().get("name") or "")
        try:
            import surfaces
            stand = surfaces.stand_of_profile(self.config, profile_id, stand)      # the PROFILE's stand, not the story's (F-6, AR-19)
        except ValueError as exc:       # the factory's table is broken: said as it is, never a guess at a stand
            return "", "", " ".join(str(exc).split())
        # t-2181 PC-9b (critic t-2513 F10): the same rule as the probe's own pick - only the IMPLICIT pick (no stand named) skips the stands
        # that run an OLD version of a side, so a reference stand never turns "the only stand" into "two stands that cannot be told apart"
        import stand_identity as SI
        project, task_root = getattr(self, "project_root", None), getattr(self, "task_root", None)
        references = () if stand or project is None or task_root is None else SI.reference_stands(project, Path(task_root).name)
        environment, refusal = rp.pick_environment(self.config, stand, profile_id, references)
        checkout = ""
        if not refusal:
            checkout, refusal = rp.pick_checkout(self.config, profile_id, "")
        return environment, checkout, refusal

    def _probe_refused(self, check: str, profile_id: str, refusal) -> None:
        # The refusal is written for a command line; a person reads its plain half, and the
        # whole of it travels in `refusal` for whoever acts on it (FR-6).
        self._probe_card(check, profile_id,
                         f"I could not check before S5 that the {profile_id} stand runs this "
                         f"story's code: {getattr(refusal, 'plain', refusal)}",
                         "name the container that serves it, in your own words, and I check it once now", refusal=str(refusal))

    def _probe_no_container(self, check: str, profile_id: str, rp, environment: str, checkout: str) -> None:
        """Docker names no running container: the card says what `runtime_probe.suggest` refuses with, or that docker names none."""
        scripts = Path(rp.__file__).resolve().parent
        _spec, refusal = rp.suggest(self.config, Path(self.project_root), profile_id, environment, "", checkout,
                                    rp.APP_ROOT, scripts)
        self._probe_card(check, profile_id,
                         f"I could not check before S5 that the {profile_id} stand runs this "
                         f"story's code: "
                         f"{getattr(refusal, 'plain', refusal) or 'docker names no running container'}",
                         "bring the stand up and say so, or name the container that serves it, or say the application does not run in one, in your own words, "
                         "and I check it once now",
                         refusal=str(refusal or ""))

    def _probe_no_candidates(self, check: str, profile_id: str, label: str, app_root: str) -> None:
        self.note(check, f"`{profile_id}`: no running container holds the files this story "
                         f"changed under `{app_root}`, so what {label} runs cannot be checked "
                         "by content here (a stand that serves a built bundle looks like "
                         "this) - nothing is asked")

    CONTAINER_ANSWER_LIMIT = 5
    CONTAINER_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}")

    def _container_answers(self, rp, profile_id: str, environment: str, checkout: str, unique: list) -> tuple:
        """`(names, probe_argvs, write_argvs)`: the containers of the card (`unique`: each name once) that a person can answer BY NAME -
        at most CONTAINER_ANSWER_LIMIT, each a plain docker name (never empty, never a leading `-`, never longer than 200 characters,
        no space or `;`) that is not also a word of the stand-gap answers (the word would be read as that answer) - with, for each,
        the read-only check and the write command in the portable form (`{python}`, `{plugin_root}`), one argv element per name.
        The stand and the checkout are the caller's picks (`_derive_probe` has them and has already refused on a missing one)."""
        import gate_brief
        words = gate_brief.stand_gap_word_index()
        names = [n for n in unique
                 if self.CONTAINER_NAME_RE.fullmatch(n) and gate_brief._word_key(n) not in words][:self.CONTAINER_ANSWER_LIMIT]
        pairs = {n: self._probe_argvs(rp, profile_id, environment, n, checkout) for n in names}
        return (names, {n: [*rp.PORTABLE_HEAD, *p[2:]] for n, (p, _w) in pairs.items()}, {n: w for n, (_p, w) in pairs.items()})

    def _probe_which_container(self, check: str, profile_id: str, label: str, candidates: list, environment: str = "",
                               checkout: str = "") -> None:
        """The card lists the containers; each one it can take BY NAME is a closed answer (`<check id>: <name>`, read by
        `story_run.read_finding_doors` against the finding's own `container_answers`; the driver runs the read-only check
        `answer_probes` first and the write `answer_argvs` only when the check said `matched`; FR-9, AR-28). A container that
        cannot be offered, or past the limit, is the conductor's, and the card NAMES them."""
        import runtime_probe as rp
        unique = list(dict.fromkeys(str(c) for c in candidates))
        names, probes, writes = self._container_answers(rp, profile_id, environment, checkout, unique)
        left = [n for n in unique if n not in names]
        offer = ("write `" + DOOR_ID + ": <name>` with one of those names and I check that container once now"
                 + (f" (I cannot take these by name: {named_ids(left, 3)}; say which one in your own words)" if left else "")
                 if names else "name the container in your own words and I check it once now")
        self._probe_card(check, profile_id,
                         f"I cannot tell which running container serves the {profile_id} tests "
                         f"on {label}, so I cannot check that it runs this story's code before "
                         f"S5: {named_ids(unique)}", offer,
                         **({"container_answers": names, "answer_probes": probes, "answer_argvs": writes} if names else {}))

    def _probe_argvs(self, rp, profile_id: str, environment: str, container: str, checkout: str) -> tuple:
        """`(probe_argv, write_argv)`: the command the rehearsal runs itself and the portable form of the one the factory registers."""
        scripts = Path(rp.__file__).resolve().parent
        app_root = rp.APP_ROOT
        probe_argv = [sys.executable, str(scripts / "runtime_probe.py"), "--profile", profile_id,
                      "--environment", environment or "local", "--container", container,
                      "--checkout", checkout, "--app-root", app_root,
                      "--task-root", str(self.task_root.resolve()), "--no-evidence"]
        # What the INFO line carries is the portable form (`{python}`, `{plugin_root}`; W5): no
        # line of a rehearsal names this machine's interpreter. Whoever runs it resolves it with
        # `runtime_probe.resolve_argv`. The probe the rehearsal runs ITSELF just above is not shown.
        write_argv = [*rp.PORTABLE_HEAD, "--suggest", "--write",
                      "--profile", profile_id, *(["--environment", environment] if environment else []),
                      "--container", container, "--checkout", checkout, "--app-root", app_root,
                      "--task-root", str(self.task_root.resolve())]
        return probe_argv, write_argv

    @staticmethod
    def _probe_verdict(root: Path, probe_argv: list) -> tuple:
        """`(outcome, record, result)`: the probe run and its record, and the verdict as the probe wrote it, not as the gate would like
        it spelled: the four words are exact (only the whitespace around them was ever forgiven), so `MATCHED` and a number are in
        no branch of `_derive_probe` and reach the defect that names them (W3). Nothing at all - no key, an empty or blank string -
        is "no verdict" (`result` is ''), the probe's timeout's case."""
        outcome = run_probe(probe_argv, root, PROBE_TIMEOUT_S)
        record = outcome.get("record") or {}
        if not isinstance(record, dict):
            outcome, record = dict(outcome, unreadable=f"the probe printed {type(record).__name__}, not a record"), {}
        verdict = record.get("result")
        result = "" if verdict is None else (verdict.strip() if isinstance(verdict, str) else repr(verdict))
        return outcome, record, result

    CHECK_WORDS = {"mismatched": "it runs other code than this story's",
                   "unknown": "what it runs could not be verified by content",
                   "not_applicable": "the check does not apply to this profile",
                   "person_confirmed": "the check was waived by a person's word, not made"}

    @classmethod
    def named_container_said(cls, root: Path, name: str, probe_argv: list) -> str:
        """The read-only check of a container a person named on a which-container card (`answer_probes`, the portable form), run
        once by the driver: '' when the probe's own verdict is exactly `matched`, else the verdict in words (a timeout, an answer the
        factory cannot read, another word). Parsed by `_probe_verdict`, the one reader of the probe's answer, never from a sentence
        (FR-12); writes nothing (`--no-evidence`). Whoever registers the container acts on '' alone (AR-28)."""
        import runtime_probe
        outcome, _record, result = cls._probe_verdict(Path(root), [str(a) for a in runtime_probe.resolve_argv(probe_argv)])
        if outcome.get("timed_out"):
            return f"the check of `{name}` did not answer within {PROBE_TIMEOUT_S}s, so nothing was registered"
        if outcome.get("unreadable") or not result:
            return f"the check of `{name}` answered in a form the factory cannot read, so nothing was registered"
        if result == "matched":
            return ""
        return (f"the check of `{name}` said `{result}` ({cls.CHECK_WORDS.get(result, 'a word the factory does not know')}), "
                "so nothing was registered; another container can still be named")

    def _probe_unreadable(self, check: str, profile_id: str, label: str, outcome: dict, record: dict) -> None:
        # Not JSON, or JSON with no verdict: the probe gave none, which is its timeout's
        # case and not an `unknown` (D4). What it printed is machine text for the factory's
        # own people, so it travels in `detail` and the sentence stays in the story's words.
        self._probe_defect(check, profile_id, "answered in a form the factory cannot read",
                           label, detail=" ".join(str(outcome.get("unreadable")
                                                      or json.dumps(record)).split())[:200])

    def _probe_matched(self, check: str, profile_id: str, container: str, record: dict, write_argv: list) -> None:
        compared = [c for c in record.get("comparisons") or [] if c.get("container_sha256")]
        listed = record.get("not_shipped_files")
        skipped = [str(n) for n in listed] if isinstance(listed, list) else []
        # FB-8: a build input the container does not hold was not compared - never shown as a plain verified build
        left = (f"; not compared, because they are not in the container: {named_ids(skipped, 3)}" if skipped else "")
        self._probe_derived(check, profile_id,
                            f"`{profile_id}`: `{container}` runs this story's code "
                            f"({len(compared)} file(s) compared by content{left}) and no probe is "
                            "registered for it yet.", write_argv)

    def _probe_mismatched(self, check: str, profile_id: str, container: str, checkout: str, label: str, record: dict) -> None:
        # the probe's own list of differing files: it counts a file ABSENT from the container too (a stale build)
        named = record.get("differing_files")
        bad = ([str(n) for n in named] if isinstance(named, list) and named else
               [str(c.get("file")) for c in record.get("comparisons") or []
                if c.get("container_sha256") and c.get("container_sha256") != c.get("local_sha256")])
        self._probe_card(check, profile_id,
                         f"the stand runs other code than this story's: in `{container}` "
                         f"{len(bad)} of the files the story changed differ from the checkout "
                         f"`{checkout}` ({named_ids(bad, 3)}), so the {profile_id} tests of S5 "
                         "would run against the wrong build",
                         f"bring {label} to this story's code and I check again, or go on and "
                         "let S5 report what it saw", container_exit=False)

    def _probe_unknown(self, check: str, profile_id: str, container: str, record: dict, write_argv: list) -> None:
        said = " ".join(str(record.get("error") or "the probe gave no verdict").split())[:200]
        self._probe_derived(check, profile_id,
                            f"`{profile_id}`: what `{container}` runs could not be verified by "
                            f"content ({said}).", write_argv)

    def _probe_not_applicable(self, check: str, profile_id: str, record: dict) -> None:
        # The probe itself found nothing of this story in the checkout (a race with the
        # gate's own file check): a fact about the story, said, and no probe is registered.
        said = " ".join(str(record.get("reason") or "no reason given").split())[:200]
        self.note(check, f"`{profile_id}`: the probe does not apply to this profile ({said}), "
                         "so what its stand runs is not checked here", profile=profile_id)

    def _probe_person_confirmed(self, check: str, profile_id: str) -> None:
        # A word the person gave for THIS story (t-300): not a defect (the probe's own fifth word) and not a
        # stand the factory checked - the line says whose word it is, and nothing is registered or asked (the
        # question belongs to the stage entry, N1b).
        self.note(check, f"`{profile_id}`: the build on this stand is confirmed by the person for this story, "
                         "so what it runs was not checked by the factory", profile=profile_id)

    def _derive_probe(self, check: str, profile_id: str) -> None:
        import runtime_probe as rp
        root = Path(self.project_root)
        environment, checkout, refusal = self._probe_picks(rp, profile_id)
        if refusal:
            self._probe_refused(check, profile_id, refusal)
            return
        if environment and rp.is_device_stand(self.config, environment):
            # a device stand runs no container: docker is not walked (F-6); the build is read from the device at S6
            self.note(check, f"`{profile_id}`: the stand `{environment}` runs the application on a device, not in a container, so "
                             "its build is read from the device when the manual capture starts - nothing is asked here")
            return
        checkout_dir = (root / checkout).resolve()
        files = rp.diff_files(self.task_root)
        why = rp.why_nothing_to_compare(self.task_root, files, checkout_dir, checkout)
        if why:
            # Before any docker call: with nothing to compare every container looked like a
            # candidate, and the card that followed asked about files the story never touched
            # (C4). Saying it is the whole answer - and which of the two facts it is: no diff on
            # record (nothing is known of the story's changes) or a diff that lies elsewhere
            # (W1, FR-41).
            self.note(check, f"`{profile_id}`: {why}", profile=profile_id)
            return
        running = rp.containers()
        if not running:
            self._probe_no_container(check, profile_id, rp, environment, checkout)
            return
        candidates = rp.content_candidates(files, checkout_dir, rp.APP_ROOT, running, cfg=self.config)
        label = environment or "this stand"
        if not candidates:
            self._probe_no_candidates(check, profile_id, label, rp.APP_ROOT)
            return
        if len(candidates) > 1:
            self._probe_which_container(check, profile_id, label, candidates, environment, checkout)
            return
        container = candidates[0]
        probe_argv, write_argv = self._probe_argvs(rp, profile_id, environment, container, checkout)
        outcome, record, result = self._probe_verdict(root, probe_argv)
        if outcome.get("timed_out"):
            self._probe_defect(check, profile_id, f"did not answer within {PROBE_TIMEOUT_S}s", label)
            return
        if outcome.get("unreadable") or not result:
            self._probe_unreadable(check, profile_id, label, outcome, record)
            return
        # The five words the probe is documented to give; each branch's body is a helper that compares no word (D12)
        if result == "matched":
            self._probe_matched(check, profile_id, container, record, write_argv)
        elif result == "mismatched":
            self._probe_mismatched(check, profile_id, container, checkout, label, record)
        elif result == "unknown":
            self._probe_unknown(check, profile_id, container, record, write_argv)
        elif result == "not_applicable":
            self._probe_not_applicable(check, profile_id, record)
        elif result == "person_confirmed":
            self._probe_person_confirmed(check, profile_id)
        else:
            # The probe is the factory's own: a verdict outside the five it is documented to give
            # is the factory's defect, and an INFO line would read as a stand that was checked (W3).
            self._probe_defect(check, profile_id,
                               f"answered with a verdict the factory does not know ({result})", label)

    def check_s5_credentials(self) -> None:
        """What the cases need from the environment, against the file the runner really reads.

        On TP1-15045 the credentials the person supplied were put into the `.env` of the
        wrong directory — a second stop and a 24-minute window for a fact the config already
        held: `environment.env_file` names the one file the harness loads."""
        check = "s5_environment"
        root = self.project_root
        if root is None:
            return
        env_cfg = self.config.get("environment") or {}
        if not isinstance(env_cfg, dict):
            return
        # HF1-9 (F-4, AR-13): the keys are read where the RUNNER reads them - `_loaded_env_files` + `_env_names`, the same two
        # functions `check_case_preconditions` uses - not from `environment.env_file` alone. A project that names only
        # `env_file` reads exactly the file it read before; one that lists `env_files` or loads its files in a conftest no
        # longer gets "missing" for a key that sits in a file the runner loads.
        try:
            files, how = self._loaded_env_files()
            values = self._env_names(files)
        except Exception as exc:
            self.unavailable(check, f"env_probe.parse_env_file ({type(exc).__name__}: {exc})")
            return
        rel = self._place_of(files, how)
        # PK0-5: the default login is asked on need - ONE rule with S6 (`default_login_needed`, AR-19). The integrations' keys and the
        # keys a case names are asked as before; the absent-file card follows the same need when none of them is asked either.
        login = integration_login_keys(env_cfg)
        asked, not_asked = self._integration_keys(env_cfg, values, login)
        needed = default_login_needed(self.task_root, self.config)
        try:
            case_keys, keys_read = self._case_env_names()
        except Exception:
            case_keys, keys_read = set(), False
        if how.startswith("config") and files and not any(Path(p).is_file() for p in files) \
                and (needed or asked or case_keys or not keys_read):
            self.add(check, PERSON_DECIDES,
                     f"`{rel}` — the environment file this project's runner reads — is not on "
                     f"disk, and every credential {self.next_stage} needs is read from it",
                     f"answer with your approval: create `{rel}` with the keys below, or say "
                     "which environment the stage should use instead")
        # What the LOGIN needs is asked as it always was. An integration's keys are asked only
        # when this story needs the integration (t-218, F2a): on cmp2 three AWS keys and three
        # accounts were put to the person for a story whose cases touch neither, the very block
        # `env_probe` stopped raising on 23.09 - this sibling detector was left out.
        for entry in not_asked:
            name, why = entry[0], entry[1]
            if len(entry) > 2 and entry[2]:
                # HF8-11 (the new row form): the project recorded WHERE its code reads the keys and not who needs them,
                # and they are not set - a line of what was not established, never a question
                self._untied_note(name, entry[2], rel, "the project records where its code reads them, not which "
                                  "tests need them")
            else:
                # a row a case declares is said under the integrations' check, where `_integration_cards` reads what was said
                # beside "none of the N recorded has keys missing" (F-3a)
                self.note(INTEGRATION_CHECK if len(entry) > 3 else check, f"keys of {name} not asked: {why}",
                          **({"declared": True} if len(entry) > 3 else {}))
        missing = [key for key in dict.fromkeys(login) if key not in values] if needed else []
        if not needed:
            self.note(check, "the stand's default account is not asked: no case of this story signs in with it, seeds data or creates an "
                      "account (each names its own recorded account or none).")
        if missing:
            # The accounts `credentials_by_role` records as "not provisioned" left this check
            # (t-218, F2b): a case that needs an account says so in its `preconditions`
            # (`stand_account`), and `case_preconditions` is the one place that asks - one statement
            # of each fact (FR-10). The phrase read that stood here is retired with them (FR-12). The keys of an
            # integration are `_integration_cards`' / `_integration_question`'s to ask (HF1-9), once, with the
            # integration's name: a key that is ALSO a login key stays here.
            where = (f"put them in `{rel}` — that is the file the runner loads, not the one in the "
                     "repository root" if rel else
                     "this project reads credentials from the process environment, not from a file")
            message = (f"{self.next_stage} needs credentials it does not have — keys not set "
                       "anywhere this session: " + ", ".join(missing[:8])
                       + (f" and {len(missing) - 8} more" if len(missing) > 8 else ""))      # a cut list says it is cut (L1)
            self.add(check, PERSON_DECIDES, message + " (names only; nothing here reads a value)",
                     f"answer with your approval: {where}, or accept the gap and let the stage "
                     "report those cases as not executed")
        recorded = env_cfg.get("integrations") if isinstance(env_cfg.get("integrations"), list) else []
        usable = sum(1 for spec in recorded if integration_row_keys(spec))      # a row with no key (and no named set) is no integration
        self._integration_cards(asked, rel, usable)

    def _story_ids(self) -> dict:
        """{"profiles", "rows", "obligations"}: the names `integrations[].required_by` can use
        for THIS story - the profiles its automate rows run on, its plan rows, the obligations
        of those rows (`coverage_obligations[].obligation_id`)."""
        rows = _read_json(self.task_root / "work" / "test-plan.json", []) or []
        if isinstance(rows, dict):
            rows = rows.get("rows") or []
        rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        obligations = [str(o.get("obligation_id")) for r in rows
                       for o in (r.get("coverage_obligations") or [])
                       if isinstance(o, dict) and o.get("obligation_id")]
        # HF1-9: the same two reads also say WHICH rows carry an obligation and which cases run on a profile, so the tie of an
        # integration to cases (`_integration_cases`) reads this one function and the rehearsal's cache is asked in one place
        by_obligation: dict = {}
        for r in rows:
            for o in r.get("coverage_obligations") or []:
                if isinstance(o, dict) and str(o.get("obligation_id") or "").strip():
                    by_obligation.setdefault(str(o["obligation_id"]).strip(), []).append(str(r.get("id") or ""))
        keyed = self.keyed_profiles()
        return {"profiles": sorted(keyed),
                "rows": [str(r.get("id")) for r in rows if r.get("id")],
                "obligations": obligations, "obligation_rows": by_obligation,
                "profile_cases": {profile: list(entry.get("cases") or []) for profile, entry in keyed.items()}}

    def _case_checks(self) -> tuple:
        """([(case id, precondition item)] of every case of the story, whether every case could be read) - the ONE reading of
        the cases' `preconditions` that `_case_env_names` and `_case_integration_needs` share (GW1-16). A case whose line does
        not parse makes the second false (its items, as far as they parsed, are still listed): its needs are unknown, and
        unknown is never read as "needs nothing". The case id is the `id:` line of the file, as `_declared_cases` reads it."""
        found, readable = [], True
        try:
            from contract import case_files
            files = case_files(self.task_root)
        except Exception:
            return found, False
        for path in files:
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                readable = False
                continue
            items, errors = parse_preconditions(case_preconditions_raw(text))
            if errors:
                readable = False
            case_id = str((re.search(r"^id:\s*(\S+)", text, re.MULTILINE) or [None, Path(path).stem])[1])
            found.extend((case_id, item) for item in items)
        return found, readable

    def _case_env_names(self) -> tuple:
        """(the variable NAMES the story's cases ask for through `check.env`, whether every case
        could be read). A case whose `preconditions` line does not parse makes the second false:
        its needs are unknown, and unknown is never read as "needs nothing"."""
        found, readable = self._case_checks()
        names = set()
        for _case, item in found:
            check = item.get("check") if isinstance(item.get("check"), dict) else {}
            if isinstance(check.get("env"), str) and check["env"].strip():
                names.add(check["env"].strip())
        return names, readable

    def _case_integration_needs(self) -> tuple:
        """({integration name: [case id]} the cases declare through `check.integration`, whether every case could be read)
        (GW1-16). The name is the declaration stripped, nothing more: a match with `environment.integrations[].name` is EQUALITY
        and is the precondition check's to make (`_integration_state`), never a reading of the words (FR-12, AR-2). It is the
        ground to take a question away, so an unreadable case makes `readable` false and the caller keeps every question (AR-28)."""
        found, readable = self._case_checks()
        needs: dict = {}
        for case_id, item in found:
            check = item.get("check") if isinstance(item.get("check"), dict) else {}
            name = check.get("integration")
            if isinstance(name, str) and name.strip():
                cases = needs.setdefault(name.strip(), [])
                if case_id not in cases:
                    cases.append(case_id)
        return needs, readable

    def _integration_keys(self, env_cfg: dict, values: dict | None = None, login=()) -> tuple:
        """([a dict per integration the story asks about], [a tuple per one it does not]): `(integration, why)`, and for a row
        that only says where its code reads the keys (`read_at`) `(integration, why, keys not set)` - a line of what was not
        established, never a question; `(integration, why, [], cases)` for a row a case declares (GW1-16: that case's card
        asks, so no line). An asked entry: `name`, `spec`, `uses`, `keys` (the route wanted), `missing` (not set
        where the runner reads them; a login key never - the login question's), `all_set`, `declared_by` (the cases that
        declare it through `check.integration`; `[]` whenever any case could not be read or the card step does not run). HF1-9: with
        `credential_alternatives` the route nearest to satisfied is named and a satisfied one asks nothing (FR-50).

        `env_probe` answers "who needs this key" and its helpers are used here (`integration_readiness` for the scope, in
        its own order; `needed_by`). The direction of the error differs: there it advises, here it would silence a question,
        so it errs toward a card: an integration that names who needs it (`required_by`, whatever the names) or is `required`
        is asked; only one that says nothing is left out (FR-41). A case that cannot be read leaves every key wanted; a key a
        case names through `check.env` is `case_preconditions`' to ask, once (FR-10)."""
        import env_probe
        integrations = [i for i in (env_cfg.get("integrations") or []) if isinstance(i, dict)]
        if not integrations:
            return [], []
        case_names, readable = self._case_env_names()
        # GW1-16: a case that declares the integration (`check.integration`) makes its own card (`PC-n`, `case_preconditions`).
        # `declared_by` is what lets `_integration_cards` leave the integration's collective line or story question to that card,
        # and only when nothing can make the card disappear unseen: every case was read (both readings), and the step that
        # makes the card runs (`skip_preconditions` and a rehearsal with no project root skip it: nothing would replace the
        # line, AR-28)
        needs, needs_readable = self._case_integration_needs()
        rehearsal_cfg = self.config.get("gate_rehearsal") if isinstance(self.config.get("gate_rehearsal"), dict) else {}
        can_declare = readable and needs_readable and self.project_root is not None \
            and not rehearsal_cfg.get("skip_preconditions")
        self._declarations_read = bool(can_declare)       # what `_untied_note` says of the cases' declarations (F-3b)
        ids = self._story_ids()
        story_names = set(ids["profiles"]) | set(ids["rows"]) | set(ids["obligations"])
        # HF8-11: an entry equal to a profile id of the PROJECT is not prose either (t-051 E6: half known is asked)
        project_names = story_names | {str(p.get("profile_id")) for p in (self.config.get("profiles") or [])
                                       if isinstance(p, dict) and p.get("profile_id")}
        stand = str(self._selected_environment().get("name") or "")
        values = values or {}
        asked, not_asked = [], []
        # the gap ids are born over EVERY recorded integration in config order, so an answer recorded for `INT-x-2` keeps
        # meaning the same integration whichever of its twins the story asks about today (E18)
        gap_ids = integration_gap_ids([integration_row_name(spec) for spec in integrations])
        for position, spec in enumerate(integrations):
            name = integration_row_name(spec)
            keys = integration_row_keys(spec)
            if not keys:
                continue
            required_by = required_by_entries(spec)
            declared_by = list(needs.get(name, [])) if can_declare else []
            # Scope FIRST, as `integration_readiness` orders it (C5): an integration that is
            # `not_required` or belongs to another stand is out whatever the cases say, and only
            # then does "a case could not be read, so the story's needs are unknown" keep the
            # rest. The other order asked for the keys of an integration nobody needs.
            scope = env_probe.integration_readiness(spec, {}, stand)
            if scope.get("status") == "not_required":
                not_asked.append((name, str(scope.get("reason") or "outside selected scope")))
                continue
            if not readable:
                uses = sorted(set(required_by) & story_names)
            elif spec.get("applicability") != "required" and not required_by:
                if declared_by:
                    # a case names it: its card asks, so this row says no collective line (the 4th element marks it)
                    # F-3a: the card is raised only for keys that are not set; with them set the line says that instead
                    said = " declares it as a precondition and asks for it itself" \
                        if self._integration_route(spec, keys, values, stand)[1] else \
                        " declares it as a precondition, and its keys are set where the runner reads them"
                    not_asked.append((name, f"{named_ids(declared_by)}{said}", [], declared_by))
                else:
                    not_asked.append(self._unnamed_entry(spec, name, keys, values, stand, set(login) | case_names))
                continue
            else:
                keys = [k for k in keys if k not in case_names]
                uses = sorted(set(required_by) & story_names) or required_by
            if not keys:
                continue
            route, absent = self._integration_route(spec, keys, values, stand)
            # `missing` leaves a key a case names (`case_preconditions`' to ask), also inside an alternative
            asked.append({"name": name, "spec": spec, "uses": uses, "keys": route, "gap": gap_ids[position],
                          "readable": readable, "named_here": bool(set(required_by) & project_names),
                          "declared_by": declared_by,
                          "missing": [k for k in absent if k not in login and not (readable and k in case_names)],
                          "all_set": not absent})
        return asked, not_asked

    def _unnamed_entry(self, spec: dict, name: str, keys: list, values: dict, stand: str, not_ours: set) -> tuple:
        """The `not_asked` entry of an integration that is not `required` and names nobody who needs it: (name, why) as
        before, and for the new row form (`read_at`, OH3-8: onboarding knows the place the code reads the keys, not who needs
        them) a third element - the keys not set, which the gate says in ONE line for all such rows. The alternatives count
        (the route). `not_ours` are the keys that are the login's or a case's to ask."""
        import env_probe
        from config_contract import reads_recorded
        why = env_probe.needed_by(keys[0], {k: [] for k in keys}, {}, [])
        if not reads_recorded(spec):
            return (name, why)
        absent = self._integration_route(spec, keys, values, stand)[1]
        return (name, why, [k for k in absent if k not in not_ours])

    @staticmethod
    def _integration_route(spec: dict, keys: list, values: dict, stand: str) -> tuple:
        """(the keys of the route to ask about, the ones of it not set). `credential_alternatives` is the data form of "another
        way to the same credential" (OR of AND-lists): one that is satisfied by what the runner loads asks nothing, else the
        alternative with the FEWEST names missing is the one named (first on a tie). A list that holds no usable alternative
        (`[]`, `[[]]`, junk) is no alternative - every key is wanted, the direction that asks (AR-28). Values are never read
        into a text: only whether a name is set. `integration_readiness` stays the one reader of "an alternative is satisfied"."""
        import env_probe
        options = spec.get("credential_alternatives") if isinstance(spec.get("credential_alternatives"), list) else []
        alternatives =[[str(k).strip() for k in option if isinstance(k, str) and str(k).strip()]
                        for option in options if isinstance(option, list)]
        alternatives = [option for option in alternatives if option]
        if not alternatives:
            return list(keys), [k for k in keys if k not in values]
        if env_probe.integration_readiness(spec, values, stand).get("status") != "missing" \
                and any(all(k in values for k in option) for option in alternatives):
            return [], []     # both readers agree an alternative is satisfied; either one saying no keeps the question
        nearest = min(alternatives, key=lambda option: sum(1 for k in option if k not in values))
        return nearest, [k for k in nearest if k not in values]

    def _integration_cases(self, spec: dict) -> tuple:
        """(cases, tied, why): which cases of THIS story an integration is tied to. HF1-9, F-1 (b).

        `required_by` is free text by design (onboarding asks "which area or profile needs them"), so a tie is made by EQUALITY
        only, never by reading the words (FR-12, AR-2): an entry equal to a plan row id of the story, an obligation id of its
        rows, a profile id the story's automate cases run on, or the area of a case. `cases` are the automate cases the entries
        resolve to (case ids, in the index's order), `tied` is True then. Three more answers:
        - `([], True, why)`: COMPLETE positive evidence that no case runs on it - every entry is a profile of the project, no
          case of this story runs on any of them, the plan and the cases were read and every automate case has a profile
          (E6). Nothing is asked; `why` is the INFO line.
        - `([], False, why)`: it cannot be tied - prose, nothing recorded, or a plan / cases that could not be read. The
          error direction is the question (AR-28), and the caller says what the person is told: since HF8-11 prose alone is
          one line of the brief (`_unmatched_by_wording`), every other untied answer a story-level question, and since GW1-16
          a case that declares the integration takes it off this list (`_integration_ties`) - an answer is never silence
          that nothing replaced."""
        entries = required_by_entries(spec)
        if not entries:
            return [], False, "the project does not say which tests use it"
        try:
            import contract
            index = contract.case_index(self.task_root)
        except Exception:
            return [], False, "the cases could not be read"
        plan = _read_json(self.task_root / "work" / "test-plan.json", None)
        rows = plan.get("rows") if isinstance(plan, dict) else plan
        if not isinstance(rows, list):
            return [], False, "the plan could not be read"
        automate = self.automate_rows()
        ids = self._story_ids()
        by_row: dict = {}
        for key, row in automate:
            by_row.setdefault(str(row.get("id") or row.get("ts") or ""), []).append(key)
        found: list = []
        for entry in entries:
            found += by_row.get(entry, [])
            found += [key for row_id in ids["obligation_rows"].get(entry, []) for key in by_row.get(row_id, [])]
            found += ids["profile_cases"].get(entry, [])
            found += [key for key, _row in automate if str((index.get(key) or {}).get("area") or "") == entry]
        found = list(dict.fromkeys(found))
        if found:
            return list(dict.fromkeys(str((index.get(key) or {}).get("case_id") or key) for key in found)), True, ""
        profile_ids = {str(p.get("profile_id")) for p in (self.config.get("profiles") or [])
                       if isinstance(p, dict) and p.get("profile_id")}
        unkeyed = [key for key, _row in automate if not any(key in cases for cases in ids["profile_cases"].values())]
        if profile_ids and all(entry in profile_ids for entry in entries) and not unkeyed:
            return [], True, f"needed by {', '.join(entries)}, which no case of this story runs on"
        return [], False, "the project names who needs it in its own words: \"" + "; ".join(entries) + "\""

    def _integration_ties(self, spec: dict, declared_by: list) -> tuple:
        """`_integration_cases(spec)` with the cases that DECLARE the integration taken out (GW1-16): they have a card of their own
        (`PC-n`), so the `INT-*` card is for the cases the equality ties and nobody declared. THE reader of this relation (AR-13):
        the gate's cards and the carry of a word to gate B (`integration_ids_of_case`) both call it.

        The error direction is the card: a case number two areas both hold (`case_index` keys it `<area>/TC-NNN`, and the case id
        `_integration_cases` gives is the bare number) is never taken out - the declaration of one of them says nothing of the
        other (C4) - and an index that cannot be read takes nothing out."""
        cases, tied, why = self._integration_cases(spec)
        if not declared_by or not cases:
            return cases, tied, why
        try:
            import contract
            from collections import Counter
            index = contract.case_index(self.task_root)
            seen = Counter(str(entry.get("case_id") or key) for key, entry in index.items())
        except Exception:
            return cases, tied, why
        held = {case for case in declared_by if seen.get(str(case), 0) <= 1}
        return [case for case in cases if case not in held], tied, why

    def _integration_decision(self, item: dict) -> tuple:
        """`(what, cases, why)` of ONE asked integration with keys missing: what the person is told (GW1-16, extracted from
        `_integration_cards`). `what` is `declared` (the cases that declare it hold its cards, nothing is left to say), `none` (it
        is tied to no case of this story: `why` is the INFO line), `tied` (`cases` get an `INT-*` card each) or `untied` (a line or
        a story-level question, `why` says why). A case that could not be read is `untied` whatever else is known: the story's
        needs are unknown, and unknown is asked at story level, never tied to a case or dropped (E7, AR-28)."""
        if not item["readable"]:
            return "untied", [], "a case of this story could not be read"
        declared = item.get("declared_by") or []
        cases, tied, why = self._integration_ties(item["spec"], declared)
        # "no cases left" is a fact only when the cases were READ: an unread reason is "not known", asked (F-2, AR-28, FR-59)
        if declared and not cases and not why.startswith(INTEGRATION_UNREAD_WHY):
            return "declared", [], ""
        if tied and not cases:
            return "none", [], why
        return ("tied", cases, why) if tied else ("untied", [], why)

    def _integration_cards(self, asked: list, place: str, recorded: int) -> None:
        """What the person is told about every integration the story asks about (HF1-9; GW1-13). Runs inside
        `check_s5_credentials`, so `run` is unchanged: the step still comes after every `factory_fixable` check and its
        questions are `person_decides`, which `gate_ready` never counts - it hides no repair and blocks no gate.

        Missing keys and the cases tied to the integration: one stand-gap card per (case, integration) - the card, its words
        and the recorder are the ones every stand gap already has (F-2 a). Missing keys that cannot be tied to a case: ONE
        question per integration for the whole story (F-1 c), or - when the project's words name nothing this story has
        (HF8-11) - a line of what was not established, never a question. Keys all set: an INFO line that says access is not proved,
        and that the brief repeats (F-3 b). Nothing missing at all: one INFO line, never silence (AR-23)."""
        check = INTEGRATION_CHECK
        open_items, tied_items, untied = [], [], []
        for item in asked:
            if item["missing"]:
                open_items.append(item)
                what, cases, why = self._integration_decision(item)
                if what == "declared":
                    # GW1-16: every case the project's words tie to it, if any, is covered by the card of a case that
                    # declares it: neither a line nor a question - the cards (`PC-n`) ask, and this says who declared it
                    self.note(check, f"{item['name']}: declared by {named_ids(item['declared_by'])}, whose own cards ask "
                                     "for the access", declared=True)
                elif what == "none":
                    self.note(check, f"{item['name']}: {why}")
                elif what == "tied":
                    tied_items.append((item, cases))
                else:
                    untied.append((item, why))
            elif item["all_set"]:
                # presence is never "verified": a placeholder or a wrong token lands later as a blocked test, not a failure
                self.note(check, f"{item['name']}: its keys are set where the runner reads them, and whether they reach "
                                 f"{item['name']} is not proved before {INTEGRATION_CARD_STAGE}", brief=True)
        shared = shared_precondition_ids(self.task_root) | {item["gap"] for item, cases in tied_items if len(cases) > 1}
        for item, cases in tied_items:
            for case in cases:
                gap_id = precondition_gap_id(case, item["gap"], shared)
                row = self._integration_gap_row(item, case, gap_id, place)
                if self._environment_cover(check, row):
                    continue
                self.stand_gaps.append(row)
                needed = "; ".join(required_by_entries(item["spec"]))
                # OH3-8: the person is told about ACCESS to a service; the variable names and the file are on the card's
                # fix line (`remedy`), where the first move needs them
                self.add(check, PERSON_DECIDES,
                         f"{GAP_SLOT} — the stand has no access set for {item['name']}, and the project "
                         f"says \"{needed}\" needs it: the card below asks what to do",
                         self.card_door(gap_id), gap=gap_id, gap_case=case,
                         integration=item["name"], integration_case=str(case))
        for item, why in untied:
            if self._unmatched_by_wording(item, why):
                # HF8-11: the project's own words name nothing this story has (prose, or an id of another story): the
                # factory cannot tie the integration to a case, and says so in ONE line of the brief instead of asking
                # one question per integration. Every other untied answer stays a question (AR-28, FR-59).
                needed = "; ".join(required_by_entries(item["spec"]))
                self._untied_note(item["name"], item["missing"], place, f"the project says \"{needed}\" needs it")
            else:
                self._integration_question(item, place, why)
        # an integration with unset keys that was left to a line (`untied`, from here or from `check_s5_credentials`' not-asked
        # loop) is a key missing for this story that was not established: "none has keys missing" would be false (F-2, AR-23)
        said_untied = any((i.get("untied") or i.get("declared")) and i.get("check") == check for i in self.info)
        if recorded and not open_items and not said_untied and not any(item["all_set"] for item in asked):
            self.note(check, f"integrations: none of the {recorded} recorded has keys missing for this story")

    @staticmethod
    def _unmatched_by_wording(item: dict, why: str) -> bool:
        """May this untied integration become a line instead of a question? Only when ALL of: the entries are the project's
        own words (`_integration_cases` answered with its prose branch), none equals an id this story or the project has
        (`named_here`), and the project does not call it `required`. The error direction is the question: unreadable cases or
        plan, nothing recorded, a `required` row, an id of a profile or of this story's rows - all keep the question."""
        return why.startswith("the project names") and not item["named_here"] \
            and item["spec"].get("applicability") != "required"

    def _untied_note(self, name: str, missing: list, place: str, reason: str) -> None:
        """The whole fact for `--text` of an integration the factory could not match to the story's cases. `untied` and
        `integration` travel as data: `brief_lines` reads them, never the sentence (FR-12). It is not proved anything -
        the line says what was NOT established."""
        self.note(INTEGRATION_CHECK, f"{name}: {named_ids(missing)} not set where the test runner reads them"
                  + (f" ({place})" if place else "") + f"; not established which tests of this story need it - {reason}",
                  untied=True, integration=name, declarations_read=self._declarations_read)

    def _unmatched_integrations(self) -> dict:
        """`{"names": [...], "readable": bool}`: the integrations the gate's collective line (`brief_lines`, `_untied_note`) says
        the factory could not match to this story's cases (GW1-31), computed WITHOUT writing a finding or a note: read-only
        and never a socket (the env file and the config are the only inputs). The condition is the ones the gate uses - the
        `read_at` row of `_integration_keys` and `_integration_decision` + `_unmatched_by_wording` - so the line and this answer
        cannot drift (AR-13). `readable` is False when the answer is not known: no story, no project, a plan, a case or the case
        index that cannot be read, or any exception - never an empty list standing for "none" (FR-41, AR-28)."""
        try:
            env_cfg = self.config.get("environment")
            if not self._has_story() or self.project_root is None:
                return {"names": [], "readable": False}
            if env_cfg is None and isinstance(self.config, dict) and self.config:
                # a project whose readable config (a missing or broken file reads as {}) has no `environment` block records no
                # integration: "none", as `integration_ids_of_case` reads it (F-6, FR-41); a block that is there and not an
                # object, and a config nobody could read, are still unknown
                return {"names": [], "readable": True}
            if not isinstance(env_cfg, dict):
                return {"names": [], "readable": False}
            recorded = [s for s in (env_cfg.get("integrations") or []) if isinstance(s, dict) and integration_row_keys(s)]
            if not recorded:
                return {"names": [], "readable": True}
            import contract
            contract.case_index(self.task_root)
            plan = _read_json(self.task_root / "work" / "test-plan.json", None)
            readable = self._case_checks()[1] and isinstance(plan.get("rows") if isinstance(plan, dict) else plan, list)
            files, _how = self._loaded_env_files()
            values = self._env_names(files)
            login = integration_login_keys(env_cfg)
            asked, not_asked = self._integration_keys(env_cfg, values, login)
            names = [entry[0] for entry in not_asked if len(entry) > 2 and entry[2]]
            for item in asked:
                if item["missing"]:
                    what, _cases, why = self._integration_decision(item)
                    if what == "untied" and self._unmatched_by_wording(item, why):
                        names.append(item["name"])
            return {"names": list(dict.fromkeys(names)), "readable": bool(readable)}
        except Exception:
            return {"names": [], "readable": False}

    @staticmethod
    def _integration_remedy(absent: list, place: str) -> dict:
        """The fix line of a card about an integration's access, in ONE shape for the `INT-*` card and the card of a case's
        `integration` precondition (GW1-16, FR-10): the file (`place`, `_place_of`; '' = the process environment) and the NAMES of
        the keys to set - never a value. `offers` has no `apply`: the factory never writes a secret."""
        return {"kind": "credential", "where": place or "the process environment",
                "change": f"set {', '.join(absent)} (names only; the value is yours to put there - never in the chat)",
                "restart": "", "offers": ["theirs", "handed", "accept"]}

    def _integration_gap_row(self, item: dict, case: str, gap_id: str, place: str) -> dict:
        """The stand-gap row of ONE case and ONE integration, shaped as a carded precondition (`_card_items`): the card, the
        words, the driver's recorder and gate B's carry read it as any other. `check.env` is the first missing key, so
        `accept always` has a key (`environment_record`) and asking again when the keys change is the error direction.
        `offers` has no `apply`: the factory never writes a secret. Names only - no value is read into the row."""
        spec, keys = item["spec"], item["missing"]
        owner = str(spec.get("owner") or "").strip()
        needed = ", ".join(required_by_entries(spec))
        row = {"id": gap_id, "pc_id": item["gap"], "case": str(case), "scope": "case", "kind": "env",
               "check": {"env": keys[0]}, "what": f"{item['name']} ({needed})", "partitions": [], "state": "unmet",
               # OH3-8: access in words; the names and the file are the fix line's (`remedy` below)
               "detail": f"access to {item['name']} is not set on this stand; "
                         f"{INTEGRATION_CARD_STAGE} of this case stops without it",
               "remedy": self._integration_remedy(keys, place),
               "owner": owner if owner and owner != "not named by the team" else "not recorded by the project"}
        self._lasting_of(row)
        return row

    def _integration_question(self, item: dict, place: str, why: str) -> None:
        """ONE question for an integration whose missing keys no case can be tied to (F-1 c; 12586: `required_by` was the
        prose "api: Jira datasources and tools"). Since HF8-11 only what the factory cannot call prose reaches here: a
        `required` row, a profile id, an unreadable plan or case. The first 200 characters - what the gate packet shows -
        carry the name and the project's own words for who needs it; the prose is clipped INSIDE its quotes when it is long,
        the name never (L2). OH3-8: no key or file in the text - the first move of the fix names them (at most LIST_LIMIT,
        then how many were left). Ways out, in words: give access yourself (nothing is recorded), accept the gap (a waiver
        the stage reads), or tell the conductor which cases use it. The factory never asks for a value."""
        keys = item["missing"]
        spec = item["spec"]
        # the path is the person's own file: written plainly, because `human_text` reads a quoted `a_b/.env` as a field name
        where = place or "the environment the test runner starts from"
        entries = required_by_entries(spec)
        # OH3-8: said as access to a service; the variable names and the file are the FIRST move's (the fix line), the one
        # place the person needs them. The first BRIEF_CUT characters carry the name and the project's own words.
        head = f"{item['name']}: no access set on this stand; "
        if entries:
            room = max(BRIEF_CUT - len(head) - len("the project says \"\" needs it"), 12)
            words = "; ".join(entries)
            words = words if len(words) <= room else words[:room - 1].rstrip() + "…"
            head += f"the project says \"{words}\" needs it"
        else:
            head += "the project does not say which tests use it"
        cause = "the factory does not read the project's wording" if why.startswith("the project names") else \
            "the project does not say" if why.startswith("the project does not say") else why
        owner = str(spec.get("owner") or "").strip()
        has_owner = bool(owner) and owner != "not named by the team"
        message = (head + f" - which of this story's cases use it is not known ({cause}), so the tests that do will stop in "
                   f"{INTEGRATION_CARD_STAGE} if access stays unset."
                   + (f" Who gives the access: {owner}." if has_owner else ""))
        self.add(INTEGRATION_CHECK, PERSON_DECIDES, message,
                 access_fix(keys, where, self.waiver_command(f"{INTEGRATION_BLOCK} {item['name']}", "", "accept")),
                 story_level=True)

    def _selected_environment(self) -> dict:
        """The stand this story runs against: the one the pipeline recorded, else the only one."""
        environments = [e for e in (self.config.get("environments") or []) if isinstance(e, dict)]
        chosen = str(self.pipeline.get("environment") or "").strip()
        for entry in environments:
            if chosen and str(entry.get("name") or "") == chosen:
                return entry
        return environments[0] if len(environments) == 1 else {}

    # --- gate A: 5. what the cases themselves need from the stand -------------------------------

    def _rel(self, path: Path) -> str:
        try:
            return Path(path).resolve().relative_to(Path(self.project_root).resolve()).as_posix()
        except Exception:
            return Path(path).name

    def _loaded_env_files(self) -> tuple:
        """(the env files the test runner REALLY loads, how we know).

        `environment.env_files` when the project says so, else the older single
        `environment.env_file`, else what the project's own conftest / pytest-dotenv setup
        names, else `.env` at the test root. A variable sitting in any OTHER file is exactly
        the TP1-15045 failure: the accounts were on disk, in a file nothing loads."""
        root = Path(self.project_root)
        env_cfg = self.config.get("environment") if isinstance(self.config.get("environment"), dict) else {}
        named = configured_env_files(env_cfg, root)
        if named[0]:
            return named
        tests_root = (root / str(self.config.get("tests_root") or ".")).resolve()
        found = []
        conftests = [p for pattern in ("conftest.py", "*/conftest.py", "*/*/conftest.py")
                     for p in sorted_paths(tests_root.glob(pattern))
                     if not any(part.startswith(".") or part in ("node_modules", "venv", "site-packages")
                                for part in p.relative_to(tests_root).parts[:-1])][:20]
        for conftest in conftests:
            try:
                source = conftest.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for call in re.findall(r"(?:load_dotenv|dotenv_values)\s*\(([^)]*)\)", source):
                literals = re.findall(r"""["']([^"'\n]*\.env[^"'\n]*)["']""", call)
                if literals:
                    found.extend(conftest.parent / lit for lit in literals)
                    continue
                # A bare `load_dotenv()` walks up from the file that called it.
                for base in (conftest.parent, *conftest.parent.parents):
                    if (base / ".env").is_file() or base == root:
                        found.append(base / ".env")
                        break
        for name in ("pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg"):  # pytest-dotenv
            try:
                source = (tests_root / name).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for block in re.findall(r"^env_files\s*=\s*(.*(?:\n[ \t]+\S.*)*)", source, re.MULTILINE):
                found.extend(tests_root / item for item in re.findall(r"[^\s\[\],\"']+", block))
        if found:
            return (list(dict.fromkeys(found)), "the project's own conftest / pytest-dotenv setup")
        return ([tests_root / ".env"], "the default: `.env` at the test root")

    def _env_names(self, files: list) -> dict:
        """{name: value} of what is set for the runner. Values stay inside this object: the
        only thing ever printed about a variable is its name."""
        return env_values(files)

    def _stray_env_file(self, name: str, loaded: list) -> str:
        """The env file that HOLDS `name` but is not loaded, or ''. Names only."""
        import env_probe
        root = Path(self.project_root)
        tests_root = (root / str(self.config.get("tests_root") or ".")).resolve()
        loaded_set = {Path(p).resolve() for p in loaded}
        for folder in dict.fromkeys([root, tests_root] + [Path(p).resolve().parent for p in loaded]):
            for pattern in (".env*", "*.env"):
                for candidate in sorted_paths(folder.glob(pattern)):
                    if candidate.is_file() and candidate.resolve() not in loaded_set:
                        try:
                            if str(env_probe.parse_env_file(candidate).get(name) or "").strip():
                                return self._rel(candidate)
                        except Exception:
                            continue
        return ""

    def _api_base_url(self, values: dict) -> str:
        """The API base URL of the stand this story runs against — from config, never from a
        case. Never printed: a base URL may carry credentials."""
        selected = self._selected_environment()
        for key in ("api_base_url", "api_url", "base_url"):
            if str(selected.get(key) or "").strip():
                return str(selected[key]).strip()
        env_cfg = self.config.get("environment") if isinstance(self.config.get("environment"), dict) else {}
        key = str(env_cfg.get("base_url_key") or "").strip()
        return str(values.get(key) or "").strip() if key else ""

    def _place_of(self, files: list, how: str) -> str:
        """The file the runner reads, as a person sees it, or '' when the project does not say which one (GW1-16, FR-10): the ONE
        calculation behind every address a gate A text gives - the s5 credential check, the integration cards (`INT-*` and a case's
        `integration` precondition) and the doors of `case_preconditions` - so two texts of one packet never name two places."""
        named = how.startswith("config") or how.startswith("the project's own")
        return self._rel(next((p for p in files if Path(p).is_file()), files[0])) if named and files else ""

    def _target_of(self, ctx: dict) -> str:
        """The file the runner reads (`_loaded_env_files`), as a person sees it: what the doors of a question name (FR-37)."""
        return self._place_of(ctx["files"], ctx["how"]) or "the process environment"

    def _looked_in(self, ctx: dict) -> str:
        """Every place `_stand_account` looked for a key, as a person reads it (OH3-40): each file of the list in order, in
        backticks, and `(not found)` after one that is not there; a `how` that names no file is `the process environment`.
        `_place_of` names the first file that exists, which hides a file the config lists and the disk lacks."""
        how = str(ctx.get("how") or "")
        files = list(ctx.get("files") or [])
        if not (how.startswith("config") or how.startswith("the project's own")) or not files:
            return "`the process environment`"
        return ", ".join(f"`{self._rel(p)}`" + ("" if Path(p).is_file() else " (not found)") for p in files)

    def _stand_rows(self) -> list:
        """The `environments[]` rows of the config that are objects."""
        return [row for row in (self.config.get("environments") or []) if isinstance(row, dict)] \
            if isinstance(self.config.get("environments"), list) else []

    def _stand_account(self, role: str, ctx: dict) -> tuple:
        """(state, detail) of `{"stand_account": <role>}`: `met` only on POSITIVE evidence.

        The evidence is the keys the stand's own note for that role names, all of them set
        (non-empty) in the env files the runner loads (`_env_names`). An absent role, an empty
        note and a note naming no key ("missing locally", "NOT provisioned") are `unmet`, and so
        is a note whose keys are not all set: an account nobody can prove is not an account the
        stand holds, so the error direction is a card, never silence (C2).

        FR-12 debt, stated here and in `design/factory-rules-debt.md`: `credentials_by_role`
        notes are prose, and the names are read from the LEADING list of the note - the part
        after an optional `<file>:` and before the first word that is not a name - as presence
        of tokens, never by what the sentence means. It stays so until the config carries a
        structured `provisioned: bool` (integrator)."""
        role = str(role).strip()
        if role == "default":
            # GW1-27: the stand's default account is the two keys of `environment` (`manual_capture._default_keys`, the one
            # reader), not a row of `credentials_by_role`. POSITION: before the stand is looked up - `default` needs no row
            # of a stand and is never the account of a role.
            if ctx.get("env_error"):
                return ("error", ctx["env_error"])
            import manual_capture
            environment = self.config.get("environment") if isinstance(self.config.get("environment"), dict) else {}
            absent = [key for key in manual_capture._default_keys(environment) if key not in ctx["values"]]
            if absent:
                return ("unmet", f"the default account needs {', '.join(absent)}, not set where the runner reads it "
                                 f"({self._looked_in(ctx)})")
            return ("met", "")
        stand = self._selected_environment()
        if not stand:
            return ("error", "no stand is selectable for this story (it names none and the "
                             "project does not record exactly one), so an account of it cannot "
                             "be looked up")
        if ctx.get("env_error"):
            return ("error", ctx["env_error"])
        roles = stand.get("credentials_by_role") if isinstance(stand.get("credentials_by_role"), dict) else {}
        real = account_role(roles, role)
        if real is None:
            if len(role_candidates(roles, role)) > 1:
                return ("unmet", f"the stand lists more than one account that `{role}` could mean "
                                 f"({role_names({k: 1 for k in role_candidates(roles, role)})}); name one of them exactly")
            return ("unmet", f"the stand records no such account (`{role}` is not one of the "
                             f"accounts it lists: {role_names(roles)})")
        role = real
        keys = account_keys(roles[role])
        if not keys:
            return ("unmet", f"the stand records no key for `{role}` that is set here: its note "
                             "names none")
        absent = [key for key in keys if key not in ctx["values"]]
        if absent:
            return ("unmet", f"`{role}` needs {', '.join(absent)}, not set where the runner reads "
                             f"it ({self._looked_in(ctx)})")
        return ("met", "")

    def _stand_frontend(self, ctx: dict) -> tuple:
        """(state, detail) of `{"stand_frontend": ...}` (GW1-27): `met` when the project records an address of the UI for the
        stand this story runs against, read by `env_probe.frontend_of` - the ONE reader, never `frontend_url` or the block
        directly (AR-13). `error` (the factory's) when the env file cannot be read, or when several stands are recorded and
        none is selected; `unmet` when no address is recorded. The detail never holds the key of the config (a person reads
        it; the key goes to the finding's `remedy`) and never a value; the reader's own notes (names, never values) follow it.

        The entry is passed as the config's own row, not a copy: the reader finds its index by identity, and `entry={}`
        instead of None would silently drop the block."""
        import env_probe
        if ctx.get("env_error"):
            return ("error", ctx["env_error"])
        rows = self._stand_rows()
        if rows:
            selected = self._selected_environment()
            if not selected:
                return ("error", "no stand is selectable for this story (it names none and the project does not record "
                                 "exactly one), so the address of its UI cannot be looked up")
            found = env_probe.frontend_of(self.config, "", ctx["values"], entry=selected, root=self.project_root)
        else:
            found = env_probe.frontend_of(self.config, "", ctx["values"], root=self.project_root)
        if found.get("url"):
            return ("met", "")
        notes = "; ".join(" ".join(str(n).split()) for n in found.get("notes") or [] if str(n).strip())
        return ("unmet", "no address of this stand's UI is recorded" + (f" ({notes})" if notes else ""))

    def _integration_state(self, name: str, ctx: dict) -> tuple:
        """`(state, detail, absent)` of `{"integration": <name>}` (GW1-16): the ONE place the state of a declared integration is
        decided; `_check_one_precondition` gives its first two and `_sort_items` the third (the keys for the card's fix line).

        The row is found by EQUALITY of the stripped name with `environment.integrations[].name` (FR-12, AR-2). Every row of that
        name counts when it has keys (`integration_row_keys`) and is in scope on this stand (`env_probe.integration_readiness`
        is not `not_required`); `met` only when every such row is, else `unmet` by the first row not met in config order (E25).
        "Met" is `_integration_route`'s (AR-13), the reader that knows `credential_alternatives`: a set held is a service
        reached. `uncheckable` - the project records no such name (`absent` is None: the case designer's to rewrite), no keys for
        it, or marks it not needed here (a person's question: the data conflict, E9) - is never `met`. The detail names no key.
        `absent` is the keys of the nearest route not set, for an `unmet`."""
        import env_probe
        if ctx.get("env_error"):
            return ("error", ctx["env_error"], [])
        name = str(name).strip()
        env_cfg = self.config.get("environment") if isinstance(self.config.get("environment"), dict) else {}
        recorded = [spec for spec in (env_cfg.get("integrations") if isinstance(env_cfg.get("integrations"), list) else [])
                    if isinstance(spec, dict)]
        rows = [spec for spec in recorded if integration_row_name(spec) == name]
        if not rows:
            return ("uncheckable", f"the project records no integration named {name}", None)
        keyed = [spec for spec in rows if integration_row_keys(spec)]
        if not keyed:
            return ("uncheckable", f"the project records no access keys for {name}", [])
        stand = str(self._selected_environment().get("name") or "")
        scopes = [(spec, env_probe.integration_readiness(spec, {}, stand)) for spec in keyed]
        live = [spec for spec, scope in scopes if scope.get("status") != "not_required"]
        if not live:
            reason = " ".join(str(scopes[0][1].get("reason") or "outside selected scope").split())
            return ("uncheckable", f"the project marks {name} as not needed on this stand: {reason}", [])
        for spec in live:
            absent = self._integration_route(spec, integration_row_keys(spec), ctx["values"], stand)[1]
            if absent:
                return ("unmet", f"access to {name} is not set on this stand", absent)
        return ("met", "", [])

    def _check_one_precondition(self, item: dict, ctx: dict) -> tuple:
        """(state, detail): seeded | met | unmet | uncheckable | error.

        `seeded` is `{"case_seeds": ...}`: the case creates it, so nothing about the stand can
        be missing and nobody is asked. It never makes another item of its case met - each
        item is classified on its own, here, before the carded / open split."""
        name, spec = next(iter(item["check"].items()))
        if name == "case_seeds":
            return ("seeded", " ".join(str(spec).split())[:120])
        if name == "stand_account":
            return self._stand_account(str(spec), ctx)
        if name == "stand_frontend":
            return self._stand_frontend(ctx)
        if name == "none":
            return ("uncheckable", "no machine check exists: " + " ".join(str(spec).split())[:120])
        if name == "integration":
            # POSITION (GW1-16): before `spec["path"]` below, which reads a field only the `http` form has and would raise on
            # this one's string; the order among the forms above is free, this boundary is not
            return self._integration_state(str(spec), ctx)[:2]
        if name == "env":
            if ctx.get("env_error"):
                return ("error", ctx["env_error"])
            if spec in ctx["values"]:
                return ("met", "")
            stray = self._stray_env_file(spec, ctx["files"])
            return ("unmet", f"`{spec}` is not set where the runner reads it (`{self._target_of(ctx)}`, per {ctx['how']})"
                    + (f" — it IS set in `{stray}`, which the runner does not load" if stray else ""))
        path, expected = spec["path"], spec.get("status", 200)
        base = ctx["base"]
        if not base:
            return ("error", "config names no API base URL for this stand (`environments[].base_url` "
                             "or `environment.base_url_key`)")
        if ctx.get("dead"):
            return ("error", ctx["dead"])
        url = base.rstrip("/") + path
        if url not in ctx["responses"]:
            try:
                ctx["responses"][url] = http_get(url, ctx["timeout"])
            except Exception as exc:
                # One timeout per rehearsal, not one per case: a stand that does not answer the
                # first GET will not answer the ninth either.
                reason = " ".join(str(getattr(exc, "reason", "") or exc).replace(base, "<stand>").split())[:100]
                ctx["dead"] = f"the stand did not answer GET {path} ({type(exc).__name__}: {reason})"
                return ("error", ctx["dead"])
        status, body = ctx["responses"][url]
        if status != expected:
            if status in (301, 302, 303, 307, 308, 401, 403):
                import http_client
                said = http_client.unattributed(status, body, None, expect="json") if status in (401, 403) else ""
                if said:
                    # B-408: what answered is not shown to be the stand's own (a page, an unreadable text): the state
                    # stays `uncheckable` - the check could not be made - but the sentence no longer claims a login.
                    return ("uncheckable", f"GET {path} answers HTTP {status}: what answered is not shown to be the "
                                           f"stand's own ({said}), so whether the stand wants a login is unknown, and "
                                           "this check carries no credentials")
                return ("uncheckable", f"GET {path} answers HTTP {status}: it wants a login, and "
                                       "this check carries no credentials")
            return ("unmet", f"GET {path} answered HTTP {status}, expected {expected}")
        flag = item.get("kind") == "feature_flag"
        if "json_path" not in spec:
            if flag:
                # GW1-27 (F-5): a bare 200 is what a single-page app or a sign-in page answers whether the flag is on or not,
                # so it proves nothing about a flag; a pass on what is not known is forbidden (AR-28). A `service` keeps it.
                return ("uncheckable", f"GET {path} answers HTTP {status}, but a bare answer does not say whether a flag is on")
            return ("met", "")
        try:
            document = json.loads(body)
        except ValueError:
            import http_client
            said = http_client.unattributed(status, body, None, expect="json")
            return ("error", f"GET {path} did not return JSON" + (f" ({said})" if said else ""))
        found, value = _json_path(document, spec["json_path"])
        if not found:
            if flag:
                # GW1-27 (F-5): this check carries no login, and a flag the anonymous answer does not show is not a flag that
                # is off: "not verifiable", never "not enabled".
                return ("uncheckable", f"the answer of GET {path} without a login does not carry `{spec['json_path']}`")
            return ("unmet", f"GET {path} has no `{spec['json_path']}`")
        if "equals" not in spec or json.dumps(value) == json.dumps(spec["equals"]):
            return ("met", "")
        secretive = re.search(r"pass|secret|token|key|credential|auth", spec["json_path"], re.IGNORECASE)
        seen = "another value" if secretive or isinstance(value, (dict, list)) \
            else json.dumps(value)[:40]
        return ("unmet", f"GET {path} `{spec['json_path']}` is {seen}, expected {json.dumps(spec['equals'])}"
                + (" (read without a login)" if flag else ""))

    def check_case_preconditions(self) -> None:
        """What each case needs from the stand, checked on the stand, one sentence per case.

        TP1-15045: TC-012 and TC-014 said in prose that they needed guardrail data and a
        non-owner account. Nobody checked; S5 found out that `features:subWorkflow` was off,
        the data and the account did not exist, and the account variables were in an env file
        the conftest does not load — a wasted first dispatch, a repair round, four partitions
        "blocked by the stand". With `preconditions` in the front matter the same facts reach
        the person INSIDE gate A, as one grouped question per case.

        A case without the field is never a finding (stories in flight). A check that cannot
        be RUN is the factory's, never the person's; only what the stand really lacks, or what
        no machine can see, becomes a question. `gate_rehearsal.skip_preconditions: true`
        turns the step off."""
        check = "case_preconditions"
        rehearsal_cfg = self.config.get("gate_rehearsal") if isinstance(self.config.get("gate_rehearsal"), dict) else {}
        if self.project_root is None or rehearsal_cfg.get("skip_preconditions"):
            return
        declared = self._declared_cases(check)
        if not declared:
            return
        shared = shared_precondition_ids(self.task_root)
        ctx = self._precondition_ctx(rehearsal_cfg)
        # the file the runner reads (`_loaded_env_files`): the one the doors of the questions name (GW1-27, FR-37)
        target = self._target_of(ctx)
        # What is NOT asked, and the cases whose `none` items wait for ONE story-wide card
        # (t-218, F1): the stand is not consulted about what a case creates or what the stand's
        # own account holds, and the prose `none` is shown once, not once per case.
        seeded, held, none_rows = [], [], []
        for case_id, text, items in declared:
            open_items, broken, case_seeded, case_held = self._sort_items(items, ctx, case_id)
            seeded.extend(case_seeded)
            held.extend(case_held)
            if broken:
                # Whose problem: the factory's. The person is told, and told it is not theirs.
                self.add(check, FACTORY_DEFECT,
                         f"{case_id}: {len(broken)} precondition(s) could not be checked on the "
                         "stand — " + "; ".join(broken)[:400],
                         "the check is the factory's own and nothing of yours to repair: the gate "
                         "is shown without it, and S5 reports the case as blocked if the stand "
                         "really lacks it")
            # PK0-4: an account item the role card of this (stand, role) holds is asked THERE, once - never again on the case's own card
            stand_name = str(self._selected_environment().get("name") or "")
            open_items = [row for row in open_items if not (
                next(iter(row[0]["check"])) == "stand_account" and (stand_name, _role_form(row[0]["check"]["stand_account"])) in self._role_carded)]
            carded = self._card_items(check, case_id, open_items, shared)
            open_items = [row for row in open_items if row not in carded]
            # `none` is the designer's prose reason, kept for what only a person can know. All
            # of a story's go to ONE card below (cmp2: 15 cases, 16 cards, one stop each).
            for row in [r for r in open_items if next(iter(r[0]["check"])) == "none"]:
                none_rows.append((case_id, row[0]))
            open_items = [row for row in open_items if next(iter(row[0]["check"])) != "none"]
            if not open_items:
                continue
            self._case_question(check, case_id, text, open_items, target)
        if seeded or held:
            self.note(check, not_asked_line(seeded, held))
        if none_rows:
            self._none_card(check, none_rows, target)

    def _declared_cases(self, check: str) -> list:
        """`[(case id, case text, preconditions)]` of every case that declares some. A field that cannot
        be read is the factory's to repair: it is said here, in file order, and the case is left out."""
        try:
            from contract import case_files, case_glob
            files = case_files(self.task_root)
        except Exception:
            files = case_glob(self.task_root / "work" / "test-cases", self.task_root)
        declared = []
        for path in files:
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            raw = case_preconditions_raw(text)
            if raw is None:
                continue
            case_id = (re.search(r"^id:\s*(\S+)", text, re.MULTILINE) or [None, Path(path).stem])[1]
            items, errors = parse_preconditions(raw)
            if errors:
                # The designer wrote it and a designer rework repairs it; the validator refuses
                # the same shape on write, so this is reached only by a file code never saw.
                self.add(check, FACTORY_FIXABLE,
                         f"{case_id}: `preconditions` cannot be read, so nothing it names was "
                         f"checked on the stand: " + "; ".join(errors[:2])[:300],
                         "the case designer rewrites the line in the form the artifact check "
                         "expects; " + self.waiver_command(
                             f"{case_id}: `preconditions` cannot be read"))
                continue
            if items:
                declared.append((str(case_id), text, items))
        return declared

    def _precondition_ctx(self, rehearsal_cfg: dict) -> dict:
        """What every check of this step shares: the timeout, and the runner's env names and the API base
        URL read once. A runner whose env files cannot be read leaves `env_error` for the checks to say."""
        try:
            timeout = float(rehearsal_cfg.get("precondition_timeout_s") or 5)
        except Exception:
            timeout = 5.0
        ctx = {"responses": {}, "timeout": timeout, "values": {}, "files": [], "how": "", "base": ""}
        try:
            ctx["files"], ctx["how"] = self._loaded_env_files()
            ctx["values"] = self._env_names(ctx["files"])
        except Exception as exc:
            ctx["env_error"] = f"the runner's env files could not be read ({type(exc).__name__}: {exc})"
        ctx["base"] = self._api_base_url(ctx["values"])
        return ctx

    def _sort_items(self, items: list, ctx: dict, case_id: str) -> tuple:
        """One case's preconditions, each checked on the stand: `(open_items, broken, seeded, held)`.
        `open_items` are `(item, state, detail)` still to ask, `broken` the sentences of the checks that
        could not run, `seeded` and `held` the `(case id, item)` pairs nobody is asked about. Returned,
        never added to the caller's lists."""
        open_items, broken, seeded, held = [], [], [], []
        for item in items:
            try:
                state, detail = self._check_one_precondition(item, ctx)
            except Exception as exc:
                state, detail = "error", f"{type(exc).__name__}: {exc}"
            if state == "error":
                broken.append(f"{item.get('id')} ({' '.join(str(item.get('what')).split())[:60]}): {detail}")
            elif state == "seeded":
                seeded.append((case_id, item))
            elif state == "met":
                if next(iter(item["check"])) == "stand_account":
                    held.append((case_id, item))
            elif next(iter(item["check"])) == "integration":
                item = self._integration_item(item, state, case_id, ctx)
                if item is not None:
                    open_items.append((item, state, detail))
            else:
                open_items.append((item, state, detail))
        return open_items, broken, seeded, held

    def _integration_item(self, item: dict, state: str, case_id: str, ctx: dict):
        """The item of a declared integration that is not `met`, as the card or the question reads it (GW1-16), or None when
        a finding took its place. A COPY, never the parsed item itself (`parse_preconditions`' result is shared). The role does
        not write the fix of this check - the config knows the names, the role does not (FR-11) - so an `unmet` item carries the
        code's own `remedy` (`_integration_remedy`: the nearest set's keys and the file), and any other state carries none: a
        `remedy` the role wrote, valid as it may be, would make a card of an item that is not about missing keys.

        The name the project does not record is the ROLE's mistake and the person has no door to it: a finding of the
        factory, the designer rewrites the line (the same form as an unreadable `preconditions`), never a question."""
        name = str(item["check"]["integration"]).strip()
        _state, _detail, absent = self._integration_state(name, ctx)
        if absent is None:
            env_cfg = self.config.get("environment") if isinstance(self.config.get("environment"), dict) else {}
            rows = env_cfg.get("integrations") if isinstance(env_cfg.get("integrations"), list) else []
            recorded = [str(s.get("name") or "").strip() for s in rows
                        if isinstance(s, dict) and integration_row_keys(s) and str(s.get("name") or "").strip()]
            self.add("case_preconditions", FACTORY_FIXABLE,
                     f"{case_id}: `preconditions` names an integration the project does not record - {item.get('id')} says the "
                     f"case goes through `{name}` ("
                     + (f"the project records {named_ids(recorded)}" if recorded else "the project records none")
                     + "), so nothing about it was checked on the stand",
                     "the case designer rewrites the precondition with the name exactly as the brief lists it; "
                     + self.waiver_command(f"{case_id}: `preconditions` names an integration the project does not record"))
            return None
        copy = {k: v for k, v in item.items() if k != "remedy"}
        if state == "unmet":
            copy["remedy"] = self._integration_remedy(absent, self._place_of(ctx["files"], ctx["how"]))
        return copy

    def _card_items(self, check: str, case_id: str, open_items: list, shared: set) -> list:
        """The open preconditions of a case that carry their own fix, as cards; returns them all, the
        ones an environment record already covers included (those raise no card).

        An open precondition that carries its own fix is a CARD, not a sentence the person has to
        decode: the gap travels whole (what the test does, what is missing, the exact change, four
        answers) and the finding left here is one line pointing at it, so `can_proceed` still says a
        question is open and one recorded word closes both — `add()` drops a finding whose text a
        `stand gap: <id>` override matches."""
        carded = [row for row in open_items if isinstance(row[0].get("remedy"), dict)
                  and not remedy_errors(row[0]["remedy"])]
        for item, state, detail in carded:
            # F18: the gap's id is the precondition's own, `PC-1@TC-007` where another case declares the same one
            gap_id = precondition_gap_id(case_id, item.get("id"), shared)
            row = {"id": gap_id, "pc_id": str(item.get("id") or ""), "case": str(case_id), "scope": "case",
                   "kind": str(item.get("kind") or ""), "check": item["check"],
                   "what": str(item.get("what") or ""),
                   "partitions": list(item.get("partitions") or []),
                   "remedy": item["remedy"], "state": state,
                   "detail": " ".join(str(detail).split())}
            self._lasting_of(row)
            if self._environment_cover(check, row):    # R7: after the check on the stand, before the card
                continue
            self.stand_gaps.append(row)
            self.add(check, PERSON_DECIDES,
                     f"{GAP_SLOT} — a stand gap "
                     f"({' '.join(str(item.get('what')).split())[:70]}): the exact change is "
                     "known, so this is a card at this gate, not a gap you have to work out",
                     self.card_door(gap_id), gap=gap_id, gap_case=str(case_id), **self._integration_data(item, case_id))
        return carded

    @staticmethod
    def _integration_data(item: dict, case_id: str) -> dict:
        """GW1-31: the integration a card's finding is about, as DATA (`integration`, `integration_case`) so `brief_lines` groups
        by the field and never reads the sentence (FR-12). Only a precondition whose check is `check.integration` has one."""
        check = item.get("check") if isinstance(item.get("check"), dict) else {}
        name = check.get("integration")
        return {"integration": name.strip(), "integration_case": str(case_id)} if isinstance(name, str) and name.strip() else {}

    @staticmethod
    def _precondition_door(item: dict, case_id: str, target: str, stands: int):
        """The way out of ONE open precondition, in words (GW1-27, FR-50, FR-2), or None for the general one. Chosen by the
        item's CHECK, not by its kind: what closes the question depends on the check (a `none` the code never reads, an `env`
        looked up by its exact name, a `stand_account` resolved by role), and a door that promised "I record it and rehearse
        again" for a check that no record can satisfy would ask the same question twice. `target` is the file the runner reads
        (the gate's own reading, `_loaded_env_files`), `<role>` the role as the case wrote it. `stands` is the number of
        `environments[]` rows: the UI's address is recorded as the NAME of a variable at most one stand (the block key) and as
        the address itself at several (the stand's own entry), and `project_decisions.py stand-frontend` refuses the other
        arm at each count, so the door offers only the arm the tool accepts (FR-2). Never a value, never a script."""
        name, spec = next(iter(item["check"].items()))
        way_out = f"or say it is not needed (S5 then reports it as not executed); or write `{case_id}: accept as blocked`."
        if name == "stand_account" and str(spec).strip() != "default":
            role = str(spec).strip()
            return (f"this account (role {role}): put its login and password in {target} as two variables of your choice, "
                    f"never in the chat, and tell me the two names — I record them under the role {role} and rehearse again; "
                    + way_out)
        if name == "env" and item.get("kind") == "account":
            return (f"this account: set {spec} and its password in {target}, never in the chat, and I rehearse again; "
                    + way_out)
        if name == "stand_frontend":
            if stands <= 1:
                return (f"the address of this stand's UI: tell me which variable of {target} holds it (put the address there "
                        "first if it is not in the file) — I record it in the project and rehearse again; " + way_out)
            return ("the address of this stand's UI: tell me the address itself — I record it for this stand in the project "
                    "and rehearse again; " + way_out)
        return None

    def _case_question(self, check: str, case_id: str, text: str, open_items: list, target: str) -> None:
        """The ONE question of a case: what it still needs from the stand, which partitions wait for it,
        the ways out (one per kind of need: `_precondition_door`). `open_items` is not empty."""
        named = [p for item, _, _ in open_items for p in (item.get("partitions") or [])]
        whole = any(not item.get("partitions") for item, _, _ in open_items)
        total = len(set(_PARTITION_RE.findall(text.split("\n---", 1)[-1])))
        hit = list(dict.fromkeys(named))
        scope = "the case needs" if whole or not hit else \
            f"{len(hit)} of {max(total, len(hit))} partitions ({', '.join(hit[:6])}) need"
        unmet = sum(1 for _, state, _ in open_items if state == "unmet")
        general = ("answer with your approval: prepare the stand (I rehearse again and S5 runs "
                   f"them), or write `{case_id}: accept as blocked` on a line of its own — S5 then "
                   "reports exactly these as not executed instead of spending a dispatch to find it out")
        doors: dict = {}
        stands = len(self._stand_rows())
        for item, _, _ in open_items[:5]:
            doors.setdefault(self._precondition_door(item, case_id, target, stands), []).append(str(item.get("id")))
        if set(doors) == {None}:
            fix = general
        else:
            fix = " ".join((door or general) if len(doors) == 1 else f"{', '.join(ids)}: {door or general}"
                           for door, ids in doors.items())
        extra = {}
        if any(next(iter(item["check"])) == "stand_frontend" for item, _, _ in open_items):
            # the key of the config is for the conductor, who records the answer; the person's text above has none (FR-6)
            import env_probe
            extra["remedy"] = env_probe.frontend_door(self.config)["none"]
        self.add(check, PERSON_DECIDES,
                 f"{case_id}: {scope} "
                 + "; ".join(" ".join(str(item.get("what")).split())[:70] for item, _, _ in open_items[:5])
                 + f" — on this stand {unmet} not met, {len(open_items) - unmet} not verifiable: "
                 + "; ".join(f"{item.get('id')} {detail}" for item, _, detail in open_items[:5])[:500],
                 fix, **extra)

    def _none_card(self, check: str, rows: list, target: str) -> None:
        """ONE card for every prose `none` precondition of the story, each reason quoted as the
        designer wrote it and grouped by identical text, with the cases that gave it.

        F1b (owner's fork, accepted risk): a real need - TC_017 of cmp2, "needs the preview
        stand" - shares the card with the cases that only say "the superadmin holds it", and the
        card names it by its case, so it is not lost. A designer who knows which of the two
        a precondition is writes `case_seeds` or `stand_account`, which are never asked."""
        by_reason: dict = {}
        for case_id, item in rows:
            reason = " ".join(str(item["check"]["none"]).split())
            by_reason.setdefault(reason, [])
            if case_id not in by_reason[reason]:
                by_reason[reason].append(case_id)
        cases = list(dict.fromkeys(case_id for case_id, _ in rows))
        quoted = "; ".join(f"\"{reason}\" ({', '.join(ids)})" for reason, ids in by_reason.items())
        # The lead carries the count and the question and nothing else: the gate packet cuts a
        # finding at 200 characters (`brief_lines`), and on the real cmp2 cases the question sat
        # behind 700 characters of the designers' reasons (t-224, C1). The reasons follow it.
        self.add(check, PERSON_DECIDES,
                 f"{none_card_lead(len(rows), len(cases))} Each case says why in its own words: "
                 f"{quoted}",
                 "answer with your approval: prepare the stand for any of them that is a real need "
                 "(I rehearse again and S5 runs them), or accept the ones that cannot be run as blocked, "
                 "one line per case: "
                 + ", ".join(f"`{c}: accept as blocked`" for c in cases[:LIST_LIMIT])
                 + (f" and {len(cases) - LIST_LIMIT} more of the same form" if len(cases) > LIST_LIMIT else "")
                 + " — S5 then reports exactly these as not executed instead of spending a dispatch to "
                 "find it out; " + self.waiver_command(NONE_CARD_BLOCK)
                 # GW1-27: ONE paragraph for the card (not one per row) when a row names an account. `none` is never read by
                 # code, so the rehearsal alone would show the same card again: only a rewrite of the line to a `stand_account`
                 # closes it, and the paragraph says that.
                 + (f"; an account named here: put its login and password in {target}, never in the chat, and tell me the role "
                    "and the two names — I record them and the case designer rewrites this precondition to that role, then I "
                    "rehearse again." if any(item.get("kind") == "account" for _, item in rows) else ""),
                 cases=cases)

    # --- gate B -------------------------------------------------------------------------------

    def check_external_writes(self) -> None:
        """What `external_writes.py` will be asked to do the moment gate B is answered."""
        check = "external_writes"
        try:
            import external_writes as _ew
            if _ew.closed_by_run(self.task_root):
                return  # an experiment sends nothing after gate B: nothing to rehearse (t-017 D3)
        except Exception:
            pass  # the check below reports an executor that cannot load, in its own words
        proposals = []
        for directory in (self.task_root / "proposals", self.task_root / "work" / "proposals"):
            if directory.is_dir():
                proposals.extend(sorted_paths(directory.glob("*.json")))
        for path in proposals:
            if _read_json(path) is None:
                self.add(check, FACTORY_FIXABLE,
                         f"a proposal gate B would publish is not readable JSON: {path.name}",
                         "the role that wrote it rewrites it; a proposal the publisher cannot "
                         "read stops the delivery after your approval")
        writes = self.config.get("external_writes") or {}
        try:
            import external_writes
        except Exception as exc:
            self.unavailable(check, f"external_writes ({type(exc).__name__}: {exc})")
            return
        for kind, channel in writes.items():
            # `channels` is the per-channel delivery map, not a channel of its own; markdown is
            # written by the factory and needs nobody. `probe` / `bugs_project` are settings.
            if kind in ("channels", "commands", "write_scopes", "probe", "bugs_project") \
                    or not isinstance(channel, str) \
                    or channel.strip() in ("", "markdown", "none", "file"):
                continue
            name = str(channel).strip()
            delivery = external_writes.channel_delivery(writes, name)
            if str(delivery.get("method") or "none") == "none":
                # NOT a defect of the factory, and never a waiver. The owner's decision of
                # 21.09: a tracker that cannot be written to is an unfinished setup, and how to
                # close it is a choice among three — which makes it the person's, with options.
                self.add(check, PERSON_DECIDES,
                         f"what you approve here for `{kind}` goes to `{name}`, and nothing is "
                         "configured to perform that write (no command, no agent) — nothing "
                         "would leave the repository after your approval",
                         DELIVERY_OPTIONS)

    def check_tracker_write(self) -> None:
        """Not "is a channel configured" but "may it CREATE an issue" — the question
        TP2-2534 answered after the person had already chosen which bugs to file.

        The gate B rehearsal is the last place to ask it: a token that was good at S0 can have
        expired inside a long story, so the probe is repeated here on its own short clock."""
        check = "tracker_write"
        if self.project_root is None:
            return
        # Before the probe, not after: an experiment never asks the tracker anything (FR-36).
        try:
            import external_writes as _ew
            if _ew.closed_by_run(self.task_root):
                return
        except Exception:
            pass  # unreadable closes nothing; check_external_writes reports the load failure
        try:
            import tracker_write
        except Exception as exc:
            self.unavailable(check, f"tracker_write ({type(exc).__name__}: {exc})")
            return
        try:
            # save=False: the rehearsal is read-only, and a receipt written by it would be a
            # second way for a "read-only" call to change the project.
            result = tracker_write.probe(self.config, self.project_root, where="gate_b",
                                         save=False)
        except Exception as exc:
            self.unavailable(check, f"tracker_write.probe ({type(exc).__name__}: {exc})")
            return
        if result.get("applicable") is False:
            return  # bugs stay in the repository: nothing to write, so nothing to probe
        status = str(result.get("status") or "")
        reason = " ".join(str(result.get("reason") or "").split())[:200]
        if status == tracker_write.CONFIRMED:
            return
        if status == tracker_write.NO:
            if "nothing is configured to perform that write" in reason:
                return  # already one question, in check_external_writes' own words
            self.add(check, PERSON_DECIDES,
                     f"the bugs you approve here cannot be filed: {reason}", DELIVERY_OPTIONS)
            return
        ask = str(result.get("ask") or "")
        if not ask:
            return  # a command channel: only a real write proves it, and that write is read back
        # Asking the assistant is a step the ORCHESTRATOR can take before the person is
        # addressed, so it is the factory's own to close — never a question at the gate.
        self.add(check, FACTORY_FIXABLE,
                 f"nobody has established whether `{result.get('invoke') or 'the tracker agent'}` "
                 "may create issues; on TP2-2534 that was learned after the person had "
                 "chosen which bugs to file, and none of them reached the tracker",
                 "ask it once, before the gate — " + ask + " — then record what it answered, "
                 "in its own words")

    # --- gate B: a red test is a draft until someone reproduced it ----------------------------

    def _draft_triage_verdicts(self) -> dict:
        """{(instance_id, attempt_id): [verdict]} of `triage.json`, plus the same rows under the
        bare instance id — a draft written before 0.7.16 names the instance and no attempt."""
        try:
            import contract
            triage = _read_json(contract.artifact(self.task_root, "triage.json"), {}) or {}
        except Exception:
            triage = _read_json(self.task_root / "work" / "triage.json", {}) or {}
        import bug_records as BR   # the pairing of a draft with its triage row lives there (G1-9): the S7 claim reads it too
        return BR.triage_verdicts((triage.get("triage") or []) if isinstance(triage, dict) else [])

    def check_bug_drafts(self) -> None:
        """A bug draft rests on a triage verdict and on a case someone reviewed.

        TP1-15045 filed four bugs. Two of them — BUG-1 and BUG-2 — came from red tests with
        no row in `triage.json` at all, on cases the critic listed as "Unreviewed for Gate A",
        and nobody ever reproduced either by hand: the "steps" were the test's own assertion
        line. A red result without a verdict is a factory block, not a product bug, and it is
        the factory's own to close before the person is shown a list to answer."""
        check = "bug_drafts"
        try:
            from contract import BUG_DRAFT_REQUIRED
        except Exception as exc:
            self.unavailable(check, f"contract.BUG_DRAFT_REQUIRED ({type(exc).__name__}: {exc})")
            return
        import bug_records as BR
        drafts = [(path, _read_json(path, {}) or {}) for path in BR.draft_paths(self.task_root)]
        if not drafts:
            return
        verdicts = self._draft_triage_verdicts()
        step_rows_report = BR.step_facts(self.task_root)   # the triage rows and the run report, read once for all the drafts
        unreviewed, unstated = set(), set()
        try:
            import critic_rollcall
            for path in critic_rollcall.findings_files(self.task_root) or []:
                rows = critic_rollcall.parse_rollcall(
                    Path(path).read_text(encoding="utf-8", errors="replace"))
                derived = critic_rollcall.derive(rows) if rows else {}
                unreviewed |= {str(u) for u in (derived.get("unreviewed") or [])}
                # A roll-call with no `reviewed` column says nothing about its rows, and the gate
                # brief prints that word. This check read the same table and treated silence as a
                # review, so one fact reached the person two ways (FR-10, FR-41).
                unstated |= {str(u) for u in (derived.get("unstated") or [])}
        except Exception as exc:
            self.unavailable(check, f"critic_rollcall ({type(exc).__name__}: {exc})")
        # t-2187 N2 (F-2 (a)): the drafts that merge 2+ manifestations under a cause the factory cannot re-read, read once for all of them
        import contract as _contract
        merged_bad = dict(BR.merged_unconfirmed(self.task_root, [(p.name, d) for p, d in drafts if isinstance(d, dict)]))
        triage_rows = step_rows_report[0]
        for path, draft in drafts:
            name = str(draft.get("id") or path.stem)
            case = (BR.draft_cases(draft) or [name])[0]      # the label of the card: the draft's primary case, read through the one reader (AR-13)
            if BR.is_code_reading(draft):
                # POSITION: before `draft_verdicts`. A code-reading draft (t-1676) rests on an oracle and an S1 fact, never on a triage
                # row, so it must never meet "without a triage verdict"; it is reached ONLY by `evidence == "code-reading"` exactly - a
                # triage draft that lacks `triage_ref` keeps its refusal. Its one checker is the S7 claim's (`code_reading_problems`).
                block = f"{case} code-reading bug draft is not ready"
                for _code, detail in BR.code_reading_problems(self.task_root, draft, [(p.name, d) for p, d in drafts]):
                    self.add(check, FACTORY_FIXABLE, f"{block} — {case}'s bug draft ({path.name}): {detail}",
                             "S7 completes the draft or withdraws it; " + self.waiver_command(block))
                continue
            found = BR.draft_verdicts(draft, verdicts)
            # Each message below opens with the block text its `fix` names as the door (`waives`): the
            # word is matched against the MESSAGE (`waiver.split_overridden`), and six of these
            # carried a different wording from their block, so the word the card offered passed
            # nothing (FR-4, t-238 W2). The sentence after the block is the one it always was.
            if not found:
                block = f"{case} bug draft without a triage verdict"
                self.add(check, FACTORY_FIXABLE,
                         f"{block} — {case} is red with no triage verdict behind its bug draft "
                         f"({path.name}) — S7 triages it first; a red result without a verdict "
                         "is a block of this factory, never a product bug shown to you",
                         "S7 re-triages it (the case goes back to the analyst), or "
                         + self.waiver_command(block))
            elif "APP_BUG" not in found:
                block = f"{case} bug draft without an APP_BUG verdict"
                self.add(check, FACTORY_FIXABLE,
                         f"{block} — {case}'s bug draft ({path.name}) rests on a triage row whose "
                         f"verdict is {', '.join(sorted(set(v for v in found if v))) or 'empty'}, "
                         "not APP_BUG — only APP_BUG becomes a bug",
                         "S7 owns the verdict; the draft is withdrawn or the verdict corrected; "
                         + self.waiver_command(block))
            # the cases of the draft are the union `BR.draft_cases` reads (`case`, `cases`, `manifestations[].case`): a merged draft whose
            # second case the critic never read is a bug from an unreviewed case (t-2187 N2, 5.3); the label above stays the primary case
            label_tokens = set(str(case).replace(",", " ").split())
            named = label_tokens | {token for cell in BR.draft_cases(draft) for token in cell.replace(",", " ").split()}
            which = case if (named & unreviewed) <= label_tokens else ", ".join(sorted(named & unreviewed))
            if unreviewed and named & unreviewed:
                block = f"{case} bug draft from an unreviewed case"
                self.add(check, FACTORY_FIXABLE,
                         f"{block} — {which} never reached the case critic (it is in the "
                         f"roll-call's unreviewed list) and a bug draft was written from it "
                         f"({path.name}) — a case nobody reviewed cannot produce a bug",
                         "send the critic back over that case, or "
                         + self.waiver_command(block))
            elif unstated and named & unstated:
                block = f"{case} bug draft from a case whose review is not stated"
                self.add(check, FACTORY_FIXABLE,
                         f"{block} — {case}'s bug draft ({path.name}) rests on a case whose review "
                         "is not stated: the roll-call has no `reviewed` column, so nothing says "
                         "the critic read it — and a case nobody reviewed cannot produce a bug",
                         "the critic adds the column and says yes or no per row, or "
                         + self.waiver_command(block))
            # `triage_ref` has its own finding above, in the words of the rule it breaks.
            missing = [field for field in BUG_DRAFT_REQUIRED
                       if field != "triage_ref" and not draft.get(field)]
            if "manual_steps" in missing:
                block = f"{case} bug draft without manual steps"
                self.add(check, FACTORY_FIXABLE,
                         f"{block} — {case}'s bug draft ({path.name}) carries no `manual_steps` — "
                         "steps a person follows in the product to see the defect. On "
                         "TP1-15045 the steps were the test's own assertion line, which "
                         "nobody can follow",
                         "S7 writes them; a defect the analyst cannot state as steps is an "
                         "observation for this gate, not a bug; "
                         + self.waiver_command(block))
            other = [field for field in missing if field != "manual_steps"]
            if other:
                block = f"{case} bug draft is incomplete"
                self.add(check, FACTORY_FIXABLE,
                         f"{block} — {case}'s bug draft ({path.name}) is missing {', '.join(other)}",
                         "S7 completes the draft before the gate reads it; "
                         + self.waiver_command(block))
            # P28 (X7-5): the red test travels with the bug - `red_test` or `red_test_none`; the one reader is contract.red_test_problems
            # (FR-17). A draft dated before the cutoff (its `created`, else the file's own day) is not asked.
            import datetime
            from contract import red_test_owed, red_test_problems
            made = datetime.date.fromtimestamp(path.stat().st_mtime).isoformat()
            red_problems = red_test_problems(draft) if red_test_owed(draft, made) else []
            if red_problems:
                block = f"{case} bug draft without its red test"
                self.add(check, FACTORY_FIXABLE,
                         f"{block} — {case}'s bug draft ({path.name}): {'; '.join(red_problems)}",
                         "S7 adds `red_test` (or `red_test_none` with the reason) to the draft; "
                         + self.waiver_command(block))
            # HF8-16: a `reproduction` receipt the code cannot check is the analyst's to fix BEFORE the person is shown the
            # draft as "unconfirmed"; the READER is bug_records (AR-13), this only names what it found. A draft with no field
            # is no finding. The missing-APP_BUG case has its own finding above and is not said twice.
            _valid, problems = BR.reproduction_problems(self.task_root, draft, *step_rows_report)
            if problems and {code for code, _detail in problems} != {BR.R_NO_TRIAGE}:
                block = f"{case} bug draft reproduction not checkable"
                details = "; ".join(detail for _code, detail in problems)
                self.add(check, FACTORY_FIXABLE,
                         f"{block} — {case}'s bug draft ({path.name}) records a `reproduction` the code could not check "
                         f"({details[:600]}), so the gate shows the bug as unconfirmed",
                         "S7 fixes the entry or removes it (evidence is a non-empty file under evidence/; a fresh_data_rerun "
                         "names the attempt of a later run that failed again); " + self.waiver_command(block))
            # One bug, many manifestations (t-2187 N2). The READERS are bug_records' (AR-13); this only names what they found. A merge
            # whose cause cannot be re-read comes first and carries the mechanism's first problem, so the same defect is not two cards.
            if path.name in merged_bad:
                block = f"{case} bug draft merges manifestations without a confirmed cause"
                self.add(check, FACTORY_FIXABLE,
                         f"{block} — {case}'s bug draft ({path.name}) puts several manifestations under one cause the factory cannot "
                         f"confirm: {merged_bad[path.name]}",
                         "S7 fixes the basis (a shared `defect_location` line can be cited as a `code_line`), or splits the draft and "
                         "links the parts with `possibly_same_cause`; " + self.waiver_command(block))
            else:
                mechanism_found = BR.mechanism_problems(self.task_root, draft)
                if mechanism_found:
                    block = f"{case} bug draft cause does not stand"
                    self.add(check, FACTORY_FIXABLE,
                             f"{block} — {case}'s bug draft ({path.name}) has a `mechanism` the factory cannot accept: "
                             + "; ".join(f"{reason} ({detail})" for reason, detail in mechanism_found)[:600],
                             "S7 fixes the `mechanism` (or writes status unknown with the reason); " + self.waiver_command(block))
            manifestation_found = BR.manifestation_problems(self.task_root, draft, triage_rows)
            if manifestation_found:
                block = f"{case} bug draft manifestations do not stand"
                self.add(check, FACTORY_FIXABLE,
                         f"{block} — {case}'s bug draft ({path.name}) lists manifestations the factory cannot accept: "
                         + "; ".join(f"{reason} ({detail})" for reason, detail in manifestation_found)[:600],
                         "S7 fixes the manifestations or removes the one that does not stand; " + self.waiver_command(block))
            # F-5 (a): every triage draft made on or after the day `contract.BUG_MECHANISM_CUTOFF` names carries `mechanism` (the empty
            # outcome is status unknown with the reason). `None` = nobody is asked yet (FR-38: no charter has asked for the field).
            # The day rule is `contract.mechanism_owed`, the one reader of the cutoff (AR-13).
            if "mechanism" not in draft and _contract.mechanism_owed(draft, made):
                block = f"{case} bug draft without its cause"
                self.add(check, FACTORY_FIXABLE,
                         f"{block} — {case}'s bug draft ({path.name}) says nothing about the cause of the defect",
                         "S7 adds `mechanism`: what the cause is and how far the analyst got (confirmed, unverified or unknown, "
                         "with the reason it is not known); " + self.waiver_command(block))

    def check_delivery_inputs(self) -> None:
        check = "delivery"
        # `artifact-registry.json` puts the ledger at `work/ledger.json`; reading the flat path
        # made every gate-B rehearsal announce "delivery_ready is not yes" about a ledger that
        # said yes. `contract.artifact` reads the canonical path and the legacy alias both.
        try:
            import contract
            ledger_path = contract.artifact(self.task_root, "ledger.json")
        except Exception:
            ledger_path = self.task_root / "work" / "ledger.json"
        ledger = _read_json(ledger_path, {}) or {}
        # t-305 N8: `after_checks` is a delivery the person can approve (its checks are theirs to finish), like `yes`
        import delivery_verdict as DV
        if DV.word_of(ledger) not in ("yes", "after_checks"):
            reasons = "; ".join(str(r) for r in (ledger.get("reasons") or [])[:3])
            self.add(check, PERSON_DECIDES,
                     "the delivery is not ready: " + (reasons or "the delivery check has not run"),
                     "answer with your approval: close the gaps, or say `deliver with known gaps`")
        for name in ("test-report.md", "work/delivery-summary.json"):
            if not (self.task_root / name).is_file():
                self.add(check, FACTORY_FIXABLE, f"{name} is not on disk, and gate B reads it",
                         "S8 produces it before the gate is shown")


def run(task_root, gate: str = "A") -> dict:
    """The rehearsal. Read-only except for ONE file: gate A's `check_actor_sign_in` writes `state/sign-in-probe.json` (the
    sign-in proof of each manual account, rewritten whole each run); no other state file is written by this call or anything it calls."""
    gate = str(gate or "A").upper()
    if gate not in GATE_STAGE:
        raise ValueError(f"gate must be one of: {', '.join(sorted(GATE_STAGE))}")
    r = Rehearsal(Path(task_root), gate)
    if gate == "A":
        steps = (r.check_gate_decision, r.check_stage_guard, r.check_prepare,
                 r.check_role_permissions, r.check_cases, r.check_planning_contract,
                 r.check_vcs, r.check_stand, r.check_case_environment_gaps, r.check_role_accounts, r.check_actor_sign_in,
                 r.check_s5_executor, r.check_s5_dependencies, r.check_s5_toolchain, r.check_s5_stand_limits,
                 r.check_s5_reporter, r.check_s5_runtime_probe,
                 r.check_s5_credentials,
                 r.check_case_preconditions, r.check_open_questions, r.check_unraised_questions,
                 r.check_question_branches)
    else:
        steps = (r.check_gate_decision, r.check_stage_guard, r.check_role_permissions,
                 r.check_bug_drafts, r.check_external_writes, r.check_tracker_write,
                 r.check_delivery_inputs)
    for step in steps:
        try:
            step()
        except Exception as exc:  # one broken check never costs the gate the other eight
            r.unavailable(getattr(step, "__name__", "step").replace("check_", ""),
                          f"{type(exc).__name__}: {exc}")
    by_class = {name: sum(1 for f in r.findings if f["class"] == name) for name in CLASSES}
    return {"gate": gate, "next_stage": r.next_stage, "task": r.ticket,
            "can_proceed": not r.findings, "gate_ready": by_class[FACTORY_FIXABLE] == 0,
            "by_class": by_class, "findings": r.findings, "stand_gaps": r.stand_gaps,
            "covered_gaps": r.covered_gaps, "info": r.info}


def render(result: dict) -> str:
    """The short human form: what the person would be told, in the order they need it."""
    # Three answers, not two: "no" over a list of questions read as a factory failure, when
    # all that stands between the approval and the stage is the person's own answer.
    by_class = result.get("by_class") or {}
    if result.get("can_proceed"):
        verdict = "yes"
    elif by_class.get(FACTORY_FIXABLE) or by_class.get(FACTORY_DEFECT):
        verdict = "no"
    else:
        verdict = f"yes, once the gate answers {by_class.get(PERSON_DECIDES, 0)} question(s)"
    lines = [f"Gate {result.get('gate')} rehearsal — {result.get('task', '?')}: "
             f"{result.get('next_stage')} can start: {verdict}"]
    # t-357: the heading says whose it is in words (the class names are the code's, not a person's); `[id]` stays - it is
    # the key a person's line names (`<id>: accept`, see `Rehearsal.waiver_command`) - and `fix:` is words, never a script
    for klass, title in ((FACTORY_FIXABLE, "The factory repairs these before the gate"),
                         # t-357 F6: no promise of a word door in a heading - some defects have no door; the door is stated
                         # per finding that has one (its `fix`)
                         (FACTORY_DEFECT, "The factory cannot repair these"),
                         (PERSON_DECIDES, "Questions for you at this gate")):
        rows = [f for f in result.get("findings") or [] if f.get("class") == klass]
        if not rows:
            continue
        lines.append(f"\n{title} ({len(rows)}):")
        for row in rows:
            lines.append(f"  - [{row['id']}] {row['message']}")
            if row.get("fix"):
                lines.append(f"      fix: {row['fix']}")
    proved = result.get("info") or []
    if proved:
        lines.append(f"\nINFO ({len(proved)}) — proved here, nothing waits on these:")
        for row in proved:
            lines.append(f"  - [{row.get('check')}] {row.get('message')}")
    return "\n".join(lines) + "\n"


def unmatched_integrations(task_root) -> dict:
    """`{"names": [...], "readable": bool}` of the integrations whose access is not set and which the factory could not match to
    this story's cases (the collective line of gate A), for a reader of a LATER stage (the report, HF8-17, queue GW1-31 ->
    HF8-17). Pure: nothing is written and no socket opens. `readable` False = not known (no `pipeline.json`, an unreadable plan or
    case, any exception): the reader says "not known", never "none" (E18, AR-28)."""
    try:
        return Rehearsal(Path(task_root), "A")._unmatched_integrations()
    except Exception:
        return {"names": [], "readable": False}


# The reasons `Rehearsal._integration_cases` gives when what it ties by could not be read (an unknown, never "no case"): the
# one place a reader of `integration_ids_of_case` tells them from "prose, tied to nothing" (equality of the start, as
# `_unmatched_by_wording` reads its prose reason; a test pins that the method still says them).
INTEGRATION_UNREAD_WHY = ("the cases could not be read", "the plan could not be read")


def integration_ids_of_case(task_root, case, cfg=None):
    """The `INT-*` gap ids the gate A cards give `case` at this moment, met or unmet (GW1-15): `declared_ids` joins them to the
    precondition ids, so a later word about an integration card reopens a carried answer (C3) and a new integration of the case
    is a new stand gap (C5). THE reader of the relation is `Rehearsal._integration_ties` (AR-13) and of the id
    `integration_gap_ids` + `precondition_gap_id`: the card and this function make one id (`shared` is the same formula).

    Keys are not looked at: "declared" is met or unmet, as for a precondition. A row with no keys is no integration (skipped,
    as `_integration_keys` skips it), a row `not_required` on the selected stand asks nothing; the gap ids are counted over EVERY
    recorded row, so `INT-x-2` stays the second `x`. Returns `[]` for no integrations and for a project with no config file,
    and None when it cannot be known - a config that is there and cannot be read, the plan, a case, an exception: the caller
    asks again (AR-28), never `[]` standing for "none"."""
    try:
        import contract
        import env_probe
        task_root = Path(task_root)
        root = _project_root(task_root)
        path = (root or task_root) / "qa-factory" / "config.json"
        if not path.is_file():
            return []
        config = hooklib.read_json(path, None, errors=Exception)      # a file that is there and says nothing is not "no integrations"
        if not isinstance(config, dict):
            return None
        env_cfg = config.get("environment")
        rows = [i for i in (env_cfg.get("integrations") or []) if isinstance(i, dict)] if isinstance(env_cfg, dict) else []
        if not rows:
            return []
        rehearsal = Rehearsal(task_root, "A")
        needs, readable = rehearsal._case_integration_needs()
        if not readable:
            return None
        rehearsal_cfg = rehearsal.config.get("gate_rehearsal") if isinstance(rehearsal.config.get("gate_rehearsal"), dict) else {}
        can_declare = rehearsal.project_root is not None and not rehearsal_cfg.get("skip_preconditions")
        stand = str(rehearsal._selected_environment().get("name") or "")
        names = [integration_row_name(spec) for spec in rows]
        gap_ids = integration_gap_ids(names)
        shared_pc = shared_precondition_ids(task_root)
        found = []
        for position, spec in enumerate(rows):
            if not integration_row_keys(spec):
                continue
            if env_probe.integration_readiness(spec, {}, stand).get("status") == "not_required":
                continue
            declared_by = list(needs.get(names[position], [])) if can_declare else []
            cases, tied, why = rehearsal._integration_ties(spec, declared_by)
            if not tied and why.startswith(INTEGRATION_UNREAD_WHY):
                return None
            shared = shared_pc | ({gap_ids[position]} if len(cases) > 1 else set())
            found += [precondition_gap_id(c, gap_ids[position], shared) for c in cases
                      if str(c) == case or contract.case_matches(str(c), case, cfg=cfg)]
        return sorted(set(found))
    except Exception:
        return None


def _group_by_integration(rows: list) -> list:
    """GW1-31: the findings that carry `integration` (and the case they are about, `integration_case`) become ONE row per
    integration, in the place of the first, naming the cases (`named_ids`: six, then how many were left). Only the line is
    grouped: the findings, their ids, doors and waivers stay one per gap, so one word still answers one gap. A finding with no
    `integration` (an older result, a story-level question) or no case is left as it is (E17)."""
    out, groups = [], {}
    for found in rows:
        name = str(found.get("integration") or "").strip()
        case = str(found.get("integration_case") or "").strip()
        if not name or not case:
            out.append(found)
            continue
        if name not in groups:
            groups[name] = {"class": PERSON_DECIDES, "check": found.get("check"), "integration": name, "cases": [],
                            "fix": ""}
            out.append(groups[name])
        groups[name]["cases"].append(case)
    for name, group in groups.items():
        group["message"] = (f"{name}: the stand has no access set; {named_ids(group.pop('cases'))} need it: "
                            "the cards below ask what to do")
    return out


def brief_lines(result: dict, limit: int = 5, skip_checks: tuple = ()) -> list:
    """The "After your approval" block of `gate_brief.py` — short by contract: the gate packet
    has a line cap, and a rehearsal that pushes the plan off the screen has missed the point.

    `skip_checks` drops the findings the packet already states in its own words (the brief
    names the critic's unreviewed rows a few lines higher); one stop, one answer, but also one
    statement of each fact."""
    stage = result.get("next_stage", "the next stage")
    # What the keys of an integration already set leave unknown (F-3 b): a report, never a question, so it follows the rows
    # and the limit does not count it. At most LIST_LIMIT lines, then how many were left out.
    reported = [" ".join(str(i.get("message")).split()) for i in result.get("info") or []
                if isinstance(i, dict) and i.get("brief") and i.get("check") == INTEGRATION_CHECK]
    tail = [f"- {line}" for line in reported[:LIST_LIMIT]] \
        + ([f"- and {len(reported) - LIST_LIMIT} more integrations whose keys are set and access is not proved"]
           if len(reported) > LIST_LIMIT else [])
    # HF8-11: the integrations the factory could not match to the story's cases are ONE line (the whole fact is in `--text`
    # and in `info`); the names come from the data the notes carry, at most LIST_LIMIT and then how many were left out
    unmatched = list(dict.fromkeys(str(i.get("integration")) for i in result.get("info") or []
                                   if isinstance(i, dict) and i.get("untied") and i.get("integration")
                                   and i.get("check") == INTEGRATION_CHECK))
    if unmatched:
        # F-3 (by recommendation, for Lead: a departure from the C1 text): true for BOTH row forms - the project's own words
        # (`required_by` prose) and a row that only says where its code reads the keys (`read_at`, no `required_by`)
        # GW1-31: said after GW1-16 - a case that needs one declares it, so these are the ones none declares
        # F-3b: "none declares" is said only when the declarations were looked at (`skip_preconditions` and a rehearsal with no
        # project do not look); an older note that carries no field keeps the clause
        looked = all(i.get("declarations_read") is not False for i in result.get("info") or []
                     if isinstance(i, dict) and i.get("untied") and i.get("check") == INTEGRATION_CHECK)
        tail.append(f"- Stand access not set for {named_ids(unmatched)}. "
                    + ("None of this story's cases declares a need for these, " if looked else
                       "The factory did not look at which cases declare a need for these (not checked in this run), ")
                    + "and the project does not say who needs them in a form the factory can match, so the factory could not match them. A test "
                    f"that does need one stops in {INTEGRATION_CARD_STAGE} and is reported as not run. To give access before that, "
                    "ask the conductor which settings to add and where.")
    clear = f"- {stage} can start: yes, with the gap below." if unmatched else f"- {stage} can start: yes."
    if result.get("can_proceed"):
        return [clear if unmatched else f"- {stage} can start: yes — nothing else stands between your approval and it."] + tail
    rows = [f for f in result.get("findings") or []
            if f.get("class") in (FACTORY_DEFECT, PERSON_DECIDES)
            and f.get("check") not in skip_checks]
    # GW1-31: the cards of ONE integration are one line, by the `integration` field the finding carries; `limit` below counts lines
    rows = _group_by_integration(rows)
    # F-5 (a): a missing integration is listed FIRST among the shown rows, so it never sits behind "+N more" (the stable sort
    # keeps every other row in the order the checks produced them); a row of a case's declared integration is one too (GW1-31)
    rows = sorted(rows, key=lambda f: not (f.get("integration") or f.get("check") == INTEGRATION_CHECK))
    fixable = result.get("by_class", {}).get(FACTORY_FIXABLE, 0)
    out = []
    if fixable:
        out.append(f"- {stage} cannot start yet: {fixable} thing(s) the factory still has to "
                   "repair itself — this gate should not have been shown yet.")
    elif not rows:
        return [clear] + tail
    cut = False

    def clipped(text: str, size: int) -> str:
        nonlocal cut
        if len(text) > size:
            # A line that is cut says so: a person must not read the first 200 characters of a
            # long card as the whole of it (t-224, C1). Exactly 200 is not a cut.
            cut = True
            return text[:size] + "…"
        return text

    for row in rows[:limit]:
        tag = "factory owns this" if row["class"] == FACTORY_DEFECT else "your call"
        out.append(f"- [{tag}] {clipped(row['message'], BRIEF_CUT)}")
        if row.get("story_level") and row.get("fix"):
            # the question of an integration no case could be tied to has no card below it: its answers are THIS line
            out.append(f"  - how to answer: {clipped(' '.join(str(row['fix']).split()), 2 * BRIEF_CUT)}")
    if len(rows) > limit or cut:
        more = f"+{len(rows) - limit} more" if len(rows) > limit else ""
        marked = "… marks a line cut here" if cut else ""
        out.append(f"- ({' and '.join(part for part in (more, marked) if part)} — "
                   "the whole list is under \"Rehearsal of gate " + str(result.get("gate") or "") + "\" below)")
    return (out + tail) if out else [clear] + tail


def selftest() -> int:
    failures = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    result = {"gate": "A", "next_stage": "S5", "can_proceed": True, "findings": [],
              "by_class": {c: 0 for c in CLASSES}}
    case("a clean rehearsal says the next stage can start",
         "S5 can start: yes" in brief_lines(result)[0], True)
    result = {"gate": "A", "next_stage": "S5", "can_proceed": False,
              "by_class": {FACTORY_FIXABLE: 1, PERSON_DECIDES: 1, FACTORY_DEFECT: 1},
              "findings": [{"id": "a-1", "check": "a", "class": FACTORY_FIXABLE, "message": "m1", "fix": ""},
                           {"id": "b-1", "check": "b", "class": PERSON_DECIDES, "message": "m2", "fix": ""},
                           {"id": "c-1", "check": "c", "class": FACTORY_DEFECT, "message": "m3", "fix": "w"}]}
    lines = brief_lines(result)
    case("the repairs the factory owes are counted first",
         "1 thing(s) the factory still has to repair" in lines[0], True)
    case("a defect of the factory is named as the factory's", "factory owns this" in lines[2], True)
    case("and a person's question as theirs", "your call" in lines[1], True)
    case("the classes are the three the owner's rule names", len(CLASSES), 3)
    case("a case that declares no preconditions is never a finding",
         parse_preconditions(case_preconditions_raw("---\nid: TC-1\n---\n")), ([], []))
    case("a precondition never names a host of its own",
         any("never a full URL" in e for e in parse_preconditions(
             '[{"id": "PC-1", "kind": "service", "what": "x", "check": {"http": {"path": '
             '"http://elsewhere.invalid/"}}}]')[1]), True)
    case("the executor question offers three answers and no more",
         [row["id"] for row in executor_options(8)], ["a", "b", "c"])
    case("the third answer is the only one that hands anything over",
         executor_options(8)[2]["action"], "handed_to_person")
    case("and it says the factory waits for nothing",
         "never wait for your results" in executor_options(8)[2]["text"], True)
    case("a command with no launcher at all is unchecked, never missing",
         executor_probe([], Path("."))["status"], "not_checked")
    case("a binary that is not on PATH is named exactly",
         executor_probe(["maestro-that-does-not-exist"], Path("."))["tool"],
         "maestro-that-does-not-exist")
    case("a script the profile names and disk does not have is missing",
         executor_probe(["./scripts/run-local.sh"], Path("."))["status"], "missing")
    case("the no-profile question offers the same three answers",
         [row["id"] for row in no_profile_options(3)], ["a", "b", "c"])
    case("its first answer is the onboarding step: the command travels in its own field, never in the text a person reads",
         ("/qa-factory:" in no_profile_options(3)[0]["text"], no_profile_options(3)[0].get("command")),
         (False, "/qa-factory:qa-onboarding"))
    case("and its third is the executor question's third, word for word",
         no_profile_options(3)[2], executor_options(3)[2])
    case("the statement says what would happen inside S5",
         "mine_refused" in no_profile_question(["TC-001"])[0], True)
    case("what a step proved is printed, and is not a question",
         "INFO (1)" in render({"gate": "A", "next_stage": "S5", "can_proceed": True,
                               "findings": [], "by_class": {c: 0 for c in CLASSES},
                               "info": [{"check": "s5_reporter", "message": "one test counted"}]}),
         True)
    case("a pytest collect hands the reporter probe one node id",
         first_collected_node("=== test session ===\ntests/test_a.py::test_x\n3 tests collected\n"),
         "tests/test_a.py::test_x")
    case("... and only one under the profile's own directory when it has one",
         first_collected_node("a/test_1.py::t\nui/test_2.py::t\n", "ui"), "ui/test_2.py::t")
    case("an account note lists the names it starts with and nothing after the prose",
         account_keys(".env: AUTH_USERNAME / AUTH_PASSWORD - made by SUPERADMIN_EMAIL"),
         ["AUTH_USERNAME", "AUTH_PASSWORD"])
    case("`NOT provisioned locally` names no key", account_keys("NOT provisioned locally"), [])
    case("a limit is a positive number, never a bool or a string",
         [limit_seconds(v) for v in (30, 0.5, 0, -1, True, "30", None)], [30.0, 0.5, None, None, None, None, None])
    case("the line of what is not asked names six cases and counts the rest",
         not_asked_line([(f"TC_{n}", {}) for n in range(7)], []).count(" and 1 more"), 1)
    case("a measurement older than the stand's last verification is stale",
         bool(measurement_is_stale("2026-09-17", "2026-09-18: rebuilt")), True)
    case("the lead of the prose-`none` card fits the packet's cut for any count",
         all(len(none_card_lead(n, n)) <= BRIEF_CUT for n in (1, 15, 10 ** 9)), True)
    cut = brief_lines({"gate": "A", "next_stage": "S5", "can_proceed": False, "by_class": {},
                       "findings": [{"id": "a-1", "check": "a", "class": PERSON_DECIDES,
                                     "message": "m" * (BRIEF_CUT + 1), "fix": ""}]})
    case("a finding cut at the packet's limit says so, and where the whole of it is - in words, no command",
         (cut[0].endswith("…"), "under \"Rehearsal of gate A\" below" in cut[-1], "--text" in cut[-1]),
         (True, True, False))
    if failures:
        print("GATE_PREFLIGHT SELFTEST: VIOLATIONS")
        for f in failures:
            print("  - " + f)
        return 1
    print("GATE_PREFLIGHT SELFTEST: no violations (classes, brief block, ownership wording)")
    return 0


def main() -> int:
    # the command line and the story's folder are `stand_gaps`'s (B-309 t-422): the two gate CLIs had one copy each
    from stand_gaps import parse_task_args, resolve_task_root
    args = parse_task_args(__doc__.strip().splitlines()[0], "--text", "the short human form instead of JSON",
                           sorted(GATE_STAGE))
    if args.selftest:
        return selftest()
    task_root = resolve_task_root(args, "gate_preflight")
    if task_root is None:
        return 2
    result = run(task_root, args.gate)
    print(render(result) if args.text else json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
