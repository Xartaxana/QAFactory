"""Stage dispatch guard (PreToolUse Agent/Task, and the delivery-shaped Bash commands).

Seven rules, read from references/stages.json and the story's pipeline.json. The guard does
not forbid outright — it requires an explicit human word, already recorded in the journal,
before the factory proceeds past a risk:

1. ORDER — a role of stage N is dispatched only when every stage listed in that stage's
   `requires` is `done` in pipeline.json. (This is also what catches a skipped retro, A18:
   S9's role cannot run while S8 is not done, and the orchestrator cannot call the story
   finished with S9 pending.)
2. GATE A — no dispatch into a stage after `gates.A.after` (S3) while `contract.gate_approved`
   says gate A is not approved in pipeline.json. That reader knows every spelling the factory
   has written into that field; this rule used to compare against the single string
   "approve", so a decision the controller had just recorded as "approved" refused S5
   (TP1-15045).
3. MANIFEST COMPLETE — no S6/S7/S8 role, and no `git commit` touching test files, while
   automation-manifest.json carries an `unresolved[]` entry without a reason from the closed
   vocabulary (`impossible`, `blocked_by_env`, `pending_implementation`,
   `deferred_by_decision:<gate>`). A named reason travels into the checks ledger as its own
   row; an unnamed hole does not travel at all.
4. GATE ORDERED / DELIVERY GATED — (a) a role that executes an order of a gate (`gate_orders` of the stage in
   stages.json, read by `hooklib.gate_orders`; S8: `qa-bug-reporter` for gate B) is dispatched only when that gate's
   decision is RECORDED and approved (`contract.gate_approved`); the delivery verdict is not asked, so a story whose
   checks say `no` still files its bugs (t-1547, GB-2). (b) Every delivery command of references/adapter-forms.json
   (`glab mr create`, `gh pr create`, ...) and of the project's `adapters.vcs.delivery_commands` runs only
   when ledger.json's verdict word is `yes` or `after_checks` (`delivery_verdict.word_of`), or the
   journal carries a `deliver_with_risks` event for this ticket (written by `controller.py --operation gate-decision
   --gate B` when the person's decision names it, or by `log_append.py --reason-file`; the guard reads the JOURNAL, never the
   gate B record, to open - the record only picks the refusal's sentence, HF8-23). A command is read by its WORDS
   (`adapter_forms.segment_matches`): whitespace runs and options between them do not hide it, and a
   mention inside one quoted argument (`echo "glab mr create"`) is no delivery. A TMS publish is not
   gated (S4, after gate A).
5. COMMIT BY PATHSPEC — a `git commit` the guard recognizes as the factory's (test files or
   qa-factory/ paths) names its own files: a bare `git commit -m` takes whatever the index
   already held, and `-a`/`--all` takes the whole tree.
6. RESUME BY RECORDED ID — `SendMessage` reopens a dispatch, so it is matched here too: the
   id must be one pipeline.json recorded for this story. Otherwise it is a new dispatch
   wearing a different tool name, and it belongs in `Agent` where rules 1-4 apply.
7. STASH BY PATHSPEC — `git stash push -u` at S5 takes untracked files, and the story's own
   artifacts (pipeline.json, the plan, the cases) are untracked. On TP2-2104 they
   went into the stash and the next role's inputs vanished; it was caught and restored by
   hand. A stash that names its paths, or excludes qa-factory/, cannot do it again.
8. HELD FOR CODE — a story held for code (`pipeline.awaiting`, read through `contract.awaiting`) is not let into a
   stage from its `held_from`; a stage below it stays open to the person's rework (`rule_awaiting_code`).

A PERSON'S WORD PASSES ANY OF THEM: rules 1 and 2 run through `dispatch_errors()`, which
filters them through `waiver.split_overridden(...)` — the `stage_overrides[]` the orchestrator
writes with `waiver.py --stage ... --block ...` — and journals what was passed as
`gate_override`. Every refusal below ends with the ready command, because on TP1-15045 the
person said "Go on", `waiver.py` printed OK, and this guard refused again: it had never read
`stage_overrides[]` at all.

FAIL-OPEN BY DESIGN: the plugin is installed at user level and its hooks fire in EVERY
repository. No pipeline.json for the ticket (or no ticket at all) means "this is not a
factory story" — allow, with one note on stderr. The guard blocks only what it can prove
is out of order.

API: check(event) -> 0 allow, 2 deny (the message is already on stderr). inject_context.py
calls it first thing on a dispatch and exits with whatever it returns; guard_pre_tool.py
calls it for the Bash shapes rules 3-5 and 7 name.

CLI: stage_guard.py --ticket <T> --stage S<n>   (explain the state of one stage)
     stage_guard.py --stories                   (one line per open story — qa-doctor step 4)
     stage_guard.py --selftest                  (synthetic project, every rule)
"""
import argparse
import bisect
import functools
import json
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hooklib import artifact_root, artifacts_dir, load_ref_json, load_config, role_name  # noqa: E402
import adapter_forms as AF  # noqa: E402
import detector_verdict as DV  # noqa: E402
import hooklib  # noqa: E402
import runtime_paths as RP  # noqa: E402
import person_words  # noqa: E402
from hooklib import sorted_paths  # noqa: E402

ALLOW = 0
DENY = 2

# Bash shapes the guard cares about. Kept as cheap substrings so guard_pre_tool.py can
# decide in microseconds whether to load the stage model at all.
COMMIT_HINTS = ("git commit",)
STASH_HINTS = ("git stash",)
# t-305 N8 (F8, the owner's correction 03.10): TMS publication is NOT verdict-gated - it happens at S4, after gate A
# (`publish_cases`) - so a "tms publish" command and `--publish-cases` are no delivery shape. The delivery commands are
# DATA now (B-406: references/adapter-forms.json plus the project's `adapters.vcs.delivery_commands`, read by
# `adapter_forms`); a substring test of two literal spellings let `glab  mr create` and `glab --repo x/y mr create` pass.
RUNNER_HINTS = ("run_suite.py", "run_suite ")
# The test-file half of the commit shape is `test_files.is_test_for("commit", ...)` (B-407 A): names and folders are data
# (references/test-path-markers.json) plus the project's own word, not a regex of this file.
FACTORY_PATH_RE = re.compile(r"qa-factory[/\\]")

# `git commit` options that swallow the next token, so it is a value and not a path.
COMMIT_VALUE_OPTS = ("-m", "--message", "-F", "--file", "-C", "--reuse-message",
                     "-c", "--reedit-message", "--author", "--date", "--cleanup",
                     "-t", "--template", "-S", "--gpg-sign", "--fixup", "--squash",
                     "--trailer")
COMMIT_ALL_OPTS = ("-a", "--all", "--include", "-i")

DEFERRED_PREFIX = "deferred_by_decision"


def closed_unresolved_reasons() -> tuple:
    """The closed list of an `unresolved[]` reason: ONE source, `manifest_from_tests.UNRESOLVED_REASON_WORDS`
    (the contract's own list plus what a `qa_unresolved` marker accepts). It used to be a literal copy here,
    kept so a PreToolUse hook would not import the contract on every tool call; a copy is what drifted. It is
    imported where it is ASKED (the manifest rule, S6-S8 dispatches and test-code commits), never at the
    hook's start - `test_stage_guard.py` pins that the two never diverge. If that module cannot be imported
    (its marker file is gone), the contract's own list answers: the guard never crashes a dispatch for it (P1)."""
    try:
        import manifest_from_tests
        return tuple(manifest_from_tests.UNRESOLVED_REASON_WORDS)
    except Exception:
        import contract
        return tuple(contract.UNRESOLVED_REASONS)


def __getattr__(name):
    """`stage_guard.UNRESOLVED_REASONS` still answers (as a set), from the one source, on first use."""
    if name == "UNRESOLVED_REASONS":
        return set(closed_unresolved_reasons())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# --- the stage model -------------------------------------------------------------------

def stage_model() -> dict:
    return load_ref_json("stages.json")


def stage_index(model: dict, stage_id: str) -> int:
    for i, st in enumerate(model.get("stages") or []):
        if st.get("id") == stage_id:
            return i
    return -1


def stages_of_role(model: dict, role: str) -> list:
    """Every stage that lists `role` (in `roles`, or in `role`), in the order of stages.json; [] for a foreign role."""
    if not role:
        return []
    found = []
    for st in model.get("stages") or []:
        roles = st.get("roles") or ([st["role"]] if st.get("role") else [])
        if role in roles:
            found.append(st)
    return found


def stage_of_role(model: dict, role: str) -> dict | None:
    """The HOME stage of a role: the LAST stage that lists it (a role listed on one stage has that one; S4, S5 and S8
    each carry two roles). A role on several stages (the case critic, on the stages it accepts) is placed by
    `stage_of_dispatch`, not here: a caller that needs the stage of a live dispatch asks that; this answer is the static
    one (the audit, the role map), and for every role it is the stage it had before a role could stand on several."""
    found = stages_of_role(model, role)
    return found[-1] if found else None


def stage_of_dispatch(model: dict, role: str, *, held: str = "", dispatches=None) -> dict | None:
    """The stage a role is working on NOW, or None (not established). PURE: reads no file; the stage is an argument.
    (1) `held` names a stage that lists the role -> it; (2) the role stands on one stage -> that one; (3) among
    `dispatches` (the records of controller.json, a mapping or a list) exactly ONE is `running`, of this role, on a stage
    of the role -> that stage; (4) else None. The error direction is toward None only: never the home stage by default
    for a role of several stages (AR-28)."""
    stages = stages_of_role(model, role)
    if not stages:
        return None
    if isinstance(held, str) and held.strip():
        for st in stages:
            if st.get("id") == held.strip():
                return st
    if len(stages) == 1:
        return stages[0]
    if isinstance(dispatches, dict):
        rows = list(dispatches.values())
    elif isinstance(dispatches, list):
        rows = dispatches
    else:
        rows = []
    by_id = {st.get("id"): st for st in stages}
    live = [d for d in rows if isinstance(d, dict) and d.get("status") == "running"
            and str(d.get("role") or "") == role and isinstance(d.get("stage"), str) and d.get("stage") in by_id]
    return by_id[live[0]["stage"]] if len(live) == 1 else None


# --- the optional dispatches of a stage (t-2277 FL-5; PC-9b adds its S1 row in the same shape) -------------------------------------
#
# `stages.json` stage `optional_dispatches: [{"role": R, "purpose": P}]` names a dispatch that may run IN the stage without being one of its
# `roles` and without ever closing it (the first look: a `qa-runner` of purpose `first_look` before S3's window 1). These readers are the ONE
# reader of those rows (AR-13): `story_step start` admits by them, `check_dispatch` and `exit_gate` place the dispatch by them. A row that is
# not a mapping with a non-empty role and purpose is no row. The record of an optional dispatch is judged by its own output, not by the
# stage's: the row's own `output` field says which (one path per row, AR-1: data, not a table in code; a row with none is judged by nothing
# but its form).


def optional_outputs(row) -> tuple:
    """The paths an optional dispatch owes, from its row's `output` (a non-empty string or a list of them); `()` for a row with none, a
    blank value or a non-mapping."""
    value = row.get("output") if isinstance(row, dict) else None
    items = [value] if isinstance(value, str) else (value if isinstance(value, list) else [])
    return tuple(str(item).strip() for item in items if isinstance(item, str) and item.strip())


def optional_purposes(model: dict, role: str) -> set:
    """Every purpose any stage's optional row names for `role` (the words a dispatch of that role may carry without being one of the
    stage's own roles). `set()` for a role no row names. Pure."""
    return {row["purpose"] for st in (model or {}).get("stages") or [] for row in optional_rows(st) if row["role"] == role}


def optional_rows(stage) -> list:
    """The usable `optional_dispatches` rows of one stage entry of the model (mappings with a non-empty `role` and `purpose`); `[]` for
    a stage with none, a malformed list, or a non-mapping."""
    rows = stage.get("optional_dispatches") if isinstance(stage, dict) else None
    return [row for row in rows if isinstance(row, dict) and str(row.get("role") or "").strip() and str(row.get("purpose") or "").strip()] \
        if isinstance(rows, list) else []


def optional_row(model: dict, stage_id: str, role: str, purpose) -> dict | None:
    """The row of stage `stage_id` that admits `role` with `purpose`, or None. A blank purpose never matches (an optional dispatch is
    named by its purpose; the stage's own roles are admitted without one)."""
    if not str(purpose or "").strip():
        return None
    for st in (model or {}).get("stages") or []:
        if st.get("id") == stage_id:
            return next((row for row in optional_rows(st) if row["role"] == role and row["purpose"] == str(purpose)), None)
    return None


def optional_roles(model: dict) -> set:
    """Every role any stage names in an optional row (the cheap test before any state is read)."""
    return {row["role"] for st in (model or {}).get("stages") or [] for row in optional_rows(st)}


def _record_purpose(record) -> str:
    if not isinstance(record, dict):
        return ""
    binding = record.get("request_binding")
    return str((binding if isinstance(binding, dict) else {}).get("purpose") or record.get("purpose") or "")


def optional_stage_of_dispatch(model: dict, role: str, dispatches, *, name: str = "") -> tuple | None:
    """`(stage entry, row, record)` when the dispatch that is running NOW for `role` is an optional dispatch of some stage, else None. PURE.
    The dispatch is the one named (`name`: a held or declared id) or the ONLY running dispatch of the role; two running, none, an unknown
    shape or a purpose no row names is None. Error direction: toward None - the role is then placed as before (its own stage), never
    placed on a stage by a guess (AR-28)."""
    if role not in optional_roles(model):
        return None
    rows = list(dispatches.items()) if isinstance(dispatches, dict) else []
    live = [(str(key), rec) for key, rec in rows if isinstance(rec, dict) and rec.get("status") == "running" and rec.get("role") == role]
    if name:
        live = [(key, rec) for key, rec in live if key == name or str(rec.get("id") or "") == name]
    if len(live) != 1:
        return None
    record = live[0][1]
    stage_id = str(record.get("stage") or "")
    row = optional_row(model, stage_id, role, _record_purpose(record))
    if row is None:
        return None
    stage = next(st for st in model.get("stages") or [] if st.get("id") == stage_id)
    return stage, row, record


def known_roles(model: dict) -> list:
    out = []
    for st in model.get("stages") or []:
        for r in st.get("roles") or ([st["role"]] if st.get("role") else []):
            if r not in out:
                out.append(r)
    return out


# --- reading the event -------------------------------------------------------------------

def requested_role(event: dict, model: dict) -> str:
    """The role this dispatch asks for: subagent_type first (the harness's own field),
    then the description/prompt text — an orchestrator that writes "dispatch qa-automator"
    into a Task description is asking for the same thing. The field arrives namespaced
    (`qa-factory:qa-automator`); `role_name` strips that, or every rule below silently
    decides this is not a factory role."""
    ti = (event or {}).get("tool_input") or {}
    explicit = role_name(ti.get("subagent_type"))
    if explicit:
        return explicit
    haystack = " ".join(str(ti.get(k) or "") for k in ("description", "prompt"))
    for role in known_roles(model):
        if re.search(r"(?<![\w-])" + re.escape(role) + r"(?![\w-])", haystack):
            return role
    return ""


def ticket_slug(ticket: str) -> str:
    """`TP2-2556` -> `tp2_2556`. The spelling a Codex desktop `task_name`
    carries: the SKILL's dispatch contract is `task_name=<role>__<ticket-slug>[_suffix]`."""
    return str(ticket or "").lower().replace("-", "_")


def host_task_name(event: dict) -> str:
    """The desktop dispatch's task name, from the host's own arguments and from the
    normalized input (host_adapter copies the key through, but a raw event may carry only
    one of them). Both are returned, space separated, because either may name the story."""
    ti = (event or {}).get("tool_input") or {}
    raw = ((event or {}).get("_qa_host") or {}).get("input") or {}
    names = [str(raw.get("task_name") or ""), str(ti.get("task_name") or "")]
    return " ".join(dict.fromkeys(n for n in names if n))


def slug_in_task_name(slug: str, task_name: str, anchored: bool = False) -> bool:
    """Does this existing story's slug appear in the part of the task name after the role
    prefix, bounded by `_` or the end of the string?

    The boundary is what keeps `abc_12` out of `abc_123_s5_11`; the "after `__`" rule is
    what keeps a role name (`qa_automator`) from ever being read as a story.

    `anchored` (a prefix-less key form, B-405 F9): the slug must START the tail. A numeric story
    `11` is a slug that any window suffix spells (`qa_automator__tp3c_s5_11`), so only the tail's
    first word may name it; a Jira slug carries its own letters and is never mistaken for one."""
    if not slug:
        return False
    pattern = re.compile(("^" if anchored else r"(?:^|_)") + re.escape(slug) + r"(?=_|$)")
    for name in str(task_name or "").split():
        head, sep, tail = name.partition("__")
        if sep and pattern.search(tail):
            return True
    return False


ARCHIVE_PARTS = ("_archive", "archive")


def is_archived(pipeline_path: Path, data: dict | None = None) -> bool:
    """A story the person has put away — the `archived: true` flag, or an `_archive/`
    component in its path. `--stories` has always filtered both out of the listing; this
    guard did not, so on TP2-2556 a finished story still counted as a candidate,
    "the single running story" saw two, and every Codex dispatch of the live story was
    refused as ambiguous for two days."""
    if any(part in ARCHIVE_PARTS for part in pipeline_path.parts):
        return True
    return bool((read_json(pipeline_path) if data is None else data).get("archived"))


def _collect_story_facts(root: Path, task_name: str, facts: dict, anchored: bool = False) -> None:
    """The live stories under `root`, newest first, and which of them the desktop task name
    names. Archived ones are not candidates. Read only when an id is still to be inferred or
    a refusal has to be explained — a dispatch that already names its story pays nothing.

    A CLOSED story is not a candidate either (I-92): TP2-2534 was S1-S8 done with
    gate B approved and its MR merged, yet a stage left `running` made it "the second
    running story" and every Codex dispatch of the live 2556 was refused as ambiguous for
    two days. Closing changes only the GUESS: a closed story is still resolved when the
    dispatch names it — by id in the text, by the desktop task-name slug, by
    `QA_FACTORY_TASK` or by an explicit `task_id` — so S9 on a closed story dispatches as
    it always did. `hooklib.story_closed` is the one reading of "closed"; nothing here
    re-derives it from `gates`/`stages`."""
    from hooklib import story_closed
    try:
        paths = sorted(root.glob("*/pipeline.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        paths = []
    live = []
    for p in paths:
        data = read_json(p)
        if is_archived(p, data):
            continue
        live.append((p, data))
    facts["closed"] = [p.parent.name for p, data in live if story_closed(data)]
    open_stories = [(p, data) for p, data in live if not story_closed(data)]
    facts["pipelines"] = [p.parent.name for p, _ in open_stories]
    facts["running"] = [p.parent.name for p, data in open_stories
                        if _has_running_stage(p, data)]
    # Over every live story, closed ones included: a named story is never hidden by closure.
    facts["slug_matches"] = [p.parent.name for p, _ in live
                             if slug_in_task_name(ticket_slug(p.parent.name), task_name, anchored)]


def identity_facts(facts: dict) -> str:
    """The indented fact lines printed under an identity refusal.

    One line per fact, so a reader sees WHICH branch refused instead of guessing. On
    TP2-2556 the refusal was a single line that named neither the artifact root, nor
    the task name it could not read, nor the two running stories that made the fallback
    ambiguous — the host diagnosed "a defect in the package" and reinstalled twice."""
    def listed(names) -> str:
        return ", ".join(str(n) for n in (names or [])) or "none"

    lines = [f"  artifact root: {facts.get('root') or 'unresolved'}"]
    if facts.get("explicit"):
        lines.append(f"  explicit id: {facts['explicit']}, from {facts.get('explicit_source')}"
                     " — no pipeline.json under that root")
    else:
        lines.append("  explicit id: none, in the event or in this session's host binding")
    lines.append(f"  ids named by the dispatch text: {listed(facts.get('named'))}")
    lines.append(f"  ticket key form: {facts.get('key_form') or 'not read'}")
    lines.append(f"  desktop task_name: {facts.get('task_name') or 'none'}; "
                 f"story slugs it names: {listed(facts.get('slug_matches'))}")
    lines.append(f"  stories with a pipeline.json ({len(facts.get('pipelines') or [])}): "
                 f"{listed(facts.get('pipelines'))}")
    lines.append(f"  of them running: {listed(facts.get('running'))}")
    # Closed stories are listed rather than silently dropped: on TP2-2556 the person
    # had to read two pipeline.json files by hand to learn why the fallback saw two stories.
    lines.append(f"  closed (not candidates): {listed(facts.get('closed'))}")
    lines.append(f"  QA_FACTORY_TASK: {facts.get('env_task') or 'not set'}")
    return "\n" + "\n".join(lines)


def requested_ticket(event: dict) -> str:
    """The ticket this dispatch is about, or "" when nothing names one."""
    return resolve_ticket(event)[0]


def story_named_by_text(text: str, cfg: dict, root: Path, facts: dict) -> str:
    """Step 2 of `resolve_ticket`: the story the dispatch text NAMES, or "" (B-405, critic t-479 B2, F19 b).

    The names are the keys of the project's form: a prefixed form (Jira) reads every key in the text; a
    prefix-less one (bare numbers) reads only the `Ticket: <key>` line the factory writes into every
    dispatch (story_step), because `#1` in a PR title or `Step #1` in a prompt is not a story. The
    candidates are the names with a pipeline.json. Exactly one candidate answers. Two or more answer none
    - the error direction is "no story named", never a story the text did not clearly name - except that
    when the `Ticket:` line names exactly one of them, that line answers: the factory's own line is the
    word that settles which story this dispatch is about. `facts["named"]` keeps every name (the identity
    refusal prints them) and `facts["key_form"]` the form read."""
    form = AF.key_form(cfg, floor=True)
    labelled = AF.labelled_keys(text, cfg)
    facts["key_form"] = AF.describe_key_form(cfg)
    facts["named"] = AF.keys_in(text, cfg) if form.prefixed else labelled
    existing = [name for name in facts["named"]
                if name not in (".", "..") and not any(c in name for c in "/\\:")
                and (root / name / "pipeline.json").exists()]
    by_line = [name for name in labelled if name in existing]
    if len(by_line) == 1:
        return by_line[0]
    return existing[0] if len(existing) == 1 else ""


_STORY_TEXT_KEYS = ("description", "prompt", "command", "task_name")
_LABEL_TEXT_KEYS = ("description", "prompt", "task_name")       # no `command`: a shell command's text never names an exploration (XT1-2, t-734 B-1)


def _dispatch_text(event: dict, task_name=None, sep: str = " ", fields: tuple = _STORY_TEXT_KEYS) -> str:
    """The words of a dispatch that can name its story or its exploration: description, prompt, command, task_name, and the desktop
    task name with its `__` read as spaces. ONE join for `resolve_ticket` (sep " ", as it always was) and `exploration_named`
    (sep "\\n": a label is a whole LINE of the prompt, and a description must not glue itself to its front)."""
    ti = (event or {}).get("tool_input") or {}
    if task_name is None:
        task_name = host_task_name(event)
    text = sep.join(str(ti.get(k) or "") for k in fields)
    return text + sep + task_name.replace('__', ' ')


def _names_story(event: dict, explicit: str, texts: list, prefix: str) -> bool:
    """Does the dispatch also name a STORY: an explicit id that is no exploration id, or a `Ticket:` line with a story that exists."""
    if explicit and not explicit.startswith(prefix):
        return True
    root, cfg = artifact_root(event), load_config(event)
    return any(hooklib.is_one_component(key) and (root / key / "pipeline.json").is_file()
               for text in texts for key in AF.labelled_keys(text, cfg))


def exploration_named(event: dict, facts: dict | None = None) -> tuple:
    """`(slug, problem)`: THE one predicate that says a dispatch or a stop belongs to an exploration (qa-explore), asked by
    `resolve_ticket`, `exit_gate._identity` (so by `subagent_journal` too) and, through `resolve_ticket`, `host_dispatch.record`
    (AR-13, AR-15; the shape of `host_probe.is_probe_child`). `("", "")`: nothing names an exploration, the event goes the story way
    unchanged. `(slug, "")`: it names ONE that exists. `("", problem)`: it tries to name one and cannot - problem is `two` (two
    different names), `name` (not a slug), `missing` (no exploration folder), `both` (also a story: an explicit story id or a `Ticket:`
    line with a story that exists) - never read as a story. Three routes, each a word of THIS event: (A) a whole line
    `Exploration: <slug>` of the dispatch text; (B) an explicit `explore:<slug>` id (the Codex receipt `enrich` copies, or a dispatch
    that passed one); (C) a SubagentStop of an exploration role: the opening prompt of the child's OWN transcript
    (`agent_transcript_path`, never the parent's `transcript_path`). `$QA_FACTORY_TASK` is session-wide and is NOT read here (see
    `_env_exploration`). An unreadable exploration table is `("", "")` plus `facts["exploration_unreadable"]` and ONE person
    signal: the story dispatches go on fully checked, never failed open (AR-28). `facts` receives `exploration_detail`."""
    facts = facts if facts is not None else {}
    try:
        import exploration as EX
        tab = EX.table()
    except Exception as exc:          # noqa: BLE001 - a damaged table must not turn into a guard crash that ALLOWs every dispatch
        facts["exploration_unreadable"] = str(exc)
        hooklib.person_signal(event, "exploration_table_unreadable",
                              f"stage guard: the exploration table could not be read ({exc}); dispatches are judged as story dispatches",
                              task="", once_key="exploration-table")   # task given: `_signal_task` would ask `resolve_ticket` again
        return "", ""
    ti = (event or {}).get("tool_input") or {}
    explicit = str(event.get("task_id") or event.get("task") or ti.get("task_id") or "").strip()
    texts = [_dispatch_text(event, sep="\n", fields=_LABEL_TEXT_KEYS)]
    is_dispatch = str(event.get("tool_name") or "") in ("Task", "Agent") or "subagent_type" in ti
    # Route A (a label line) is read from a DISPATCH only: a Bash/PowerShell command that carries such a line (a commit message,
    # a heredoc) is no dispatch, and must not lose its story and skip every story command rule (t-734 B-1, AR-28).
    named = (EX.labels_in(texts[0]) if is_dispatch else []) + ([EX.env_slug(explicit)] if EX.env_slug(explicit) else [])
    if (event.get("hook_event_name") == "SubagentStop"
            and role_name(str(event.get("agent_type") or event.get("agent_name") or "")) in tab["roles"]):
        texts.append(EX.opening_prompt(event.get("agent_transcript_path")))
        named += EX.labels_in(texts[1])
    slugs = list(dict.fromkeys(named))
    if not slugs:
        return "", ""
    facts["exploration_detail"] = ", ".join(slugs)
    if len(slugs) > 1:
        return "", "two"
    slug = slugs[0]
    if not EX.is_slug(slug):
        return "", "name"
    if not EX.exists(slug, hooklib.project_root(event)):
        return "", "missing"
    if _names_story(event, explicit, texts, tab["env_prefix"]):
        return "", "both"
    return slug, ""


def _env_exploration(event: dict, env_task: str, facts: dict) -> tuple:
    """`$QA_FACTORY_TASK=explore:<slug>`: a person's word for a host whose dispatch cannot carry a label. Read only at step 5 of
    `resolve_ticket`: it never overrules a story the event itself named. `(slug, "")`, `("", problem)` as `exploration_named`."""
    if not env_task:
        return "", ""
    try:
        import exploration as EX
        slug = EX.env_slug(env_task)
        if not slug:
            return "", ""
        facts["exploration_detail"] = slug
        if not EX.is_slug(slug):
            return "", "name"
        return ("", "missing") if not EX.exists(slug, hooklib.project_root(event)) else (slug, "")
    except Exception:                  # noqa: BLE001 - an unreadable table: the story path, as before
        return "", ""


def _check_exploration(event: dict, facts: dict, role: str):
    """The verdict of `check_dispatch` for a dispatch that names an exploration, or None when it names none. Every refusal starts
    with a fixed literal (the registry key) and names the door its receiver can use: the dispatch is rebuilt from `explore_step.py
    brief`, or `explore_step.py frame` runs first (FR-1, FR-2, FR-46: a malformed call is the call's fault)."""
    problem, slug, detail = facts.get("exploration_problem"), facts.get("exploration"), facts.get("exploration_detail", "")
    if problem == "two":
        return deny("exploration identity: two explorations named (" + detail + "): dispatch again with the brief that "
                    "`explore_step.py brief` prints, which names one exploration")
    if problem == "name":
        return deny("exploration identity: not an exploration name (" + detail + "): dispatch again with the brief that "
                    "`explore_step.py brief` prints; its first line carries the name `explore_step.py frame` gave")
    if problem == "missing":
        return deny("exploration identity: no exploration `" + detail + "` under qa-factory/explorations/: run "
                    "`explore_step.py frame` first, then dispatch with the brief that `explore_step.py brief` prints")
    if problem == "both":
        return deny("exploration identity: the dispatch names both a story and an exploration (" + detail + "): a story "
                    "dispatch carries no exploration label; an exploration dispatch carries no story task_id or Ticket: line")
    if not slug:
        return None
    from exploration import table
    roles = table()["roles"]
    if role in roles:
        hooklib.notice(event, f"STAGE GUARD: {role} dispatched for exploration {slug} - no story stage checks apply",
                       reader="orchestrator")
        return ALLOW
    return deny("exploration identity: this role has no exploration step; an exploration dispatches only "
                + "; ".join(f"{name} ({', '.join(steps)})" for name, steps in roles.items()))


def resolve_ticket(event: dict) -> tuple:
    """(ticket, facts) — the story, and everything a refusal has to print when there is none.

    Order, and every step answers only with a story that EXISTS on disk — nothing here
    invents an id:
      1. an explicit id: the event's own, or the one `host_dispatch.enrich` copied out of
         this session's host binding;
      1b. for a Codex resume (`SendMessage`), the story of the recorded host receipts its recipient
         names (`_resume_recipient_story`): a native resume carries its identity in the recipient, not
         in `task_name` or its opaque message, and it is read AFTER the explicit id (a word on the event
         is never overruled by a receipt) and BEFORE the text and the single-running-story steps,
         because the story being resumed need not be `running` (an accepted stage with pending
         rework is not). It answers only when every receipt of every recipient alias names ONE story;
      2. a TICKET-ID in the dispatch text that has artifacts, in the project's key form
         (`adapter_forms`; see `story_named_by_text`: a prefix-less form reads only the
         `Ticket:` line, and two stories named without that line name none);
      3. the live story whose slug the desktop `task_name` carries (Codex desktop passes
         `task_name`, `fork_turns` and an OPAQUE encrypted `message` — see the first line of
         native_context.py — so on that host the task name is the only readable carrier);
      4. the single running story, a compatibility path for one unambiguous story only (withheld
         from a Codex resume: its identity is its recipient, step 1b, so a recipient no receipt
         names resolves no story rather than whichever one happens to be running; `check_resume`
         then decides, and refuses when the project has stories);
      5. `$QA_FACTORY_TASK` — a person's word for a host that cannot carry an id.
    Before step 1 stands one question that is no story step: `exploration_named` (a label line or an `explore:` id of the event
    itself); an exploration answers `("", facts)` with `facts["exploration"]` (or `exploration_problem`), never a story. The
    variable `QA_FACTORY_TASK=explore:<slug>` is read at step 5 only, after every story the event named (XT1-2).
    """
    ti = (event or {}).get("tool_input") or {}
    task_name = host_task_name(event)
    facts = {"root": "", "task_name": task_name, "explicit": "", "explicit_source": "",
             "named": [], "slug_matches": [], "pipelines": [], "running": [], "closed": [],
             "env_task": ""}
    from native_context import diagnostic
    if diagnostic(event):
        return "", facts
    root = artifact_root(event)
    facts["root"] = str(root)
    facts["env_task"] = str(os.environ.get("QA_FACTORY_TASK") or "").strip()
    # An exploration (qa-explore) has no story: its own word (the label, or an `explore:` id) is read BEFORE every story step, so a
    # dispatch that carries it is never handed to a story by a key in its text, its task name or a guess (XT1-2). `$QA_FACTORY_TASK`
    # is session-wide, not this dispatch's word: it is read only at step 5, after everything the event itself named.
    slug, problem = exploration_named(event, facts)
    if slug:
        facts["exploration"] = slug
        return "", facts
    if problem:
        facts["exploration_problem"] = problem
        return "", facts
    text = _dispatch_text(event, task_name)
    explicit = str(event.get("task_id") or event.get("task") or ti.get("task_id") or "")
    if explicit:
        facts["explicit"] = explicit
        facts["explicit_source"] = ("the host binding " + str(event.get("host_binding"))
                                    if event.get("host_binding")
                                    and (event.get("task_id") or event.get("task"))
                                    else "the dispatch event")
        if (root / explicit / "pipeline.json").is_file():
            return explicit, facts
        cfg = load_config(event)
        facts["key_form"] = AF.describe_key_form(cfg)
        _collect_story_facts(root, task_name, facts, not AF.key_form(cfg, floor=True).prefixed)  # only to explain
        return "", facts
    bound = _resume_recipient_story(event, root)
    if bound:
        facts["explicit"] = bound
        facts["explicit_source"] = "the recorded resume recipient binding"
        return bound, facts
    cfg = load_config(event)   # read only now: a dispatch that already names its story pays nothing for it
    named = story_named_by_text(text, cfg, root, facts)
    if named:
        return named, facts
    _collect_story_facts(root, task_name, facts, not AF.key_form(cfg, floor=True).prefixed)
    if len(facts["slug_matches"]) == 1:
        return facts["slug_matches"][0], facts
    # A person's word, for a host that cannot carry an id at all: it comes before the
    # single-story guess below (a person's word beats a guess) and after everything the
    # event itself named (it never overrules a named story).
    env_task = facts["env_task"]
    if env_task and not any(c in env_task for c in "/\\:") and env_task not in (".", "..") \
            and (root / env_task / "pipeline.json").is_file():
        return env_task, facts
    env_slug, env_problem = _env_exploration(event, env_task, facts)
    if env_slug or env_problem:
        facts["exploration" if env_slug else "exploration_problem"] = env_slug or env_problem
        return "", facts
    if _is_codex_resume(event):
        # A Codex resume's identity is its recipient (step 1b). One no receipt names must not inherit the
        # story that happens to be running (TP2-2406, 16.10: a follow-up to 2406's strategist was
        # judged against 2534). Steps 1-3 and the person's word above have had their turn; only the
        # guess is withheld. Any other dispatch (`Agent`, a Claude `SendMessage`) keeps it.
        return "", facts
    # Compatibility for one unambiguous legacy story only. Never select whichever
    # file was touched most recently when two tasks share a repository.
    candidates = facts["running"] or facts["pipelines"]
    if len(candidates) == 1:
        return candidates[0], facts
    return "", facts


def _is_codex_resume(event: dict) -> bool:
    """A `SendMessage` on the Codex host: the one call whose story is its recipient's, not a guess."""
    from host_adapter import is_codex
    return str((event or {}).get("tool_name") or "") == "SendMessage" and is_codex(event)


def resume_targets(event: dict) -> list:
    """Every alias a resume recipient can arrive under (`host_adapter.RECIPIENT_ALIASES`, read from the
    normalized tool input AND from the raw input the adapter keeps): every non-blank value, de-duplicated,
    in the order read. The host may act on any of them, so none may hide behind another (an `id` of
    agent-99 beside a recorded `to` resumed agent-99 while the guard looked only at `to`)."""
    from host_adapter import RECIPIENT_ALIASES
    ti = (event or {}).get("tool_input") or {}
    raw = ((event or {}).get("_qa_host") or {}).get("input")
    raw = raw if isinstance(raw, dict) else {}
    return list(dict.fromkeys(
        text for source in (ti, raw) for key in RECIPIENT_ALIASES
        for text in [str(source.get(key) or "").strip()] if text))


def _resume_recipient_story(event: dict, root: Path) -> str:
    """Step 1b of `resolve_ticket`: the story the receipts of a Codex resume's recipient name, or "" (FB-16,
    TP2-2406).

    `resolve_ticket` read a `followup_task` to 2406's case designer like any dispatch: its `task_name`
    carried no slug, its message is opaque on the desktop host, 2406's S4 was accepted with blocked rework
    (not `running`), so the single-running-story fallback answered 2534 and the resume was checked against
    the wrong story. The receipt the host (or `story_step bind`) wrote for the recipient's dispatch is the
    one record that ties it to its story. A forged argument cannot steer this: the receipts are found by
    the recipient alone. ONE story must answer for ALL the aliases and ALL the receipts of each (I-2);
    a name two stories hold names none. Another host (Claude) keeps the guess: the identity there is as
    on `main` (F-1)."""
    if not _is_codex_resume(event):
        return ""
    found = set()
    for target in resume_targets(event):
        found |= _recipient_stories(event, root, target)
    return next(iter(found)) if len(found) == 1 else ""


def _recipient_receipts(event: dict, root: Path, target: str) -> list:
    """`[(story, dispatch_id)]`, one per receipt that answers to `target` (`host_dispatch.matching_binding_paths`:
    the exact receipt alone, else every name match) AND names a story: it holds the target among its
    `binding_names`, carries a `dispatch_id`, and its `task_id` is one path component with a pipeline.json
    under `root`. A receipt that names no story (empty or odd `task_id`, no dispatch, no story on disk, an
    unreadable file) is neither evidence nor a veto."""
    from host_dispatch import binding_names, matching_binding_paths
    found = []
    for path in matching_binding_paths(hooklib.project_root(event), target):
        binding = read_json(path)   # an unreadable receipt reads as {} and names nothing
        story = binding.get("task_id")
        dispatch = binding.get("dispatch_id")
        if (target in binding_names(binding) and isinstance(dispatch, str) and dispatch
                and isinstance(story, str) and story and not any(c in story for c in "/\\:")
                and story not in (".", "..") and (root / story / "pipeline.json").is_file()):
            found.append((story, dispatch))
    return found


def _recipient_stories(event: dict, root: Path, target: str) -> set:
    """The distinct stories a resume recipient's receipts name - the one reader both step 1b and
    `check_resume` (the vouching) use. An unbound recipient names the empty set."""
    return {story for story, _ in _recipient_receipts(event, root, target)}


def _has_running_stage(path: Path, data: dict | None = None) -> bool:
    data = read_json(path) if data is None else data
    stages = data.get("stages") if isinstance(data.get("stages"), dict) else {}
    return any((v or {}).get("status") == "running" for v in stages.values() if isinstance(v, dict))


def read_json(path: Path) -> dict:
    """The JSON object in `path`, else {} (a guard reads objects only; a file it cannot read is "no rule to enforce").
    The `{}` is written here, in the `def`, so every call gets its own."""
    return hooklib.read_json(path, {}, kind=dict, errors=Exception)


def journal_lines(event: dict | None = None) -> list:
    cfg = load_config(event)
    from hooklib import project_root
    path = RP.configured(project_root(event), cfg.get("journal_path"), "journal.jsonl")
    out = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return out


# --- the four rules -----------------------------------------------------------------------

# The last refusal this process produced, so the hook that exits on it can write the denial
# down without re-deriving the reason from stderr. inject_context.py reads it to append a line
# to <task_root>/state/dispatch-denials.jsonl: a dispatch receipt without a launch left
# TP1-15045 answering `wait_existing_job` forever, and `recover` needs proof that the
# agent never started.
LAST_DENIAL: dict = {"message": "", "ticket": "", "stage": "", "role": ""}


def deny(message: str) -> int:
    LAST_DENIAL["message"] = message
    print("STAGE GUARD: " + message, file=sys.stderr)
    return DENY


# The phrase a person's `--block` has to name for `waiver.split_overridden` to drop a refusal.
# Kept next to the message that carries it: the guard prints the command, so the two can only
# drift if someone edits one of them alone.
BLOCK_MATCHES = ("required stages are not done", "gate A is not approved", "tracker route",
                 "unresolved cases without a reason", "could not be read", "is absent", "is held for code")


def block_match(message: str) -> str:
    for phrase in BLOCK_MATCHES:
        if phrase in message:
            return phrase
    return "*"


WAIVER_HINT_PREFIX = "Your word passes this:"


def waiver_hint(ticket: str, stage_id: str, message: str) -> str:
    # The orchestrator or the conductor reads this one, never the person: gate_preflight strips it
    # (`without_hint`) before a card is shown, so the placeholder is the plain file form. The
    # orchestrator writes their words, as given, to <story folder>/state/words/.
    return (f"{WAIVER_HINT_PREFIX} `" + person_words.door(
        f"waiver.py --task {ticket or '<TICKET>'} --stage {stage_id} "
        f"--block \"{block_match(message)}\"") + "`.")


def without_hint(message: str) -> str:
    """The refusal itself, without the command appended to it — what a caller matching the
    person's `--block` text against a standing refusal has to compare with."""
    return str(message).split(WAIVER_HINT_PREFIX)[0].strip()


def awaiting_state(pipeline: dict, ticket: str = "", task_root=None, event: dict | None = None) -> dict:
    """The controller's state of the story, for the ONE question "does a required stage await its consumer's acceptance" (X7-6); `{}` when
    it cannot be read (then nothing awaits and the order rule refuses as before - the safe direction)."""
    try:
        from controller import Controller
        root = Path(task_root) if task_root else artifacts_dir(str(ticket or (pipeline or {}).get("ticket") or ""), event)
        return Controller(root).state()
    except Exception:  # noqa: BLE001 - an unreadable state opens nothing
        return {}


def rule_order(model: dict, stage: dict, pipeline: dict, role: str | None = None, state_of=None) -> str | None:
    """Rule 1: the required stages are done. X7-6 (AR-13, AR-25): a required stage that AWAITS its consumer's acceptance
    (`acceptance.awaits_acceptance`, the one reader) is open to the role `acceptance_by` of THAT stage only; every other role is refused
    with the door. `state_of` is a callable returning the controller state (read only when a required stage is not done and has a consumer)."""
    stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), dict) else {}
    pending = []
    awaiting = []
    for req in stage.get("requires") or []:
        status = (stages.get(req) or {}).get("status") if isinstance(stages.get(req), dict) else None
        if status != "done":
            import acceptance
            consumer = acceptance.consumer_of(req)
            if consumer and state_of is not None and acceptance.awaits_acceptance(state_of(), req, pipeline):
                if role == consumer:
                    continue
                awaiting.append(f"{req} awaits the acceptance of {consumer}")
                continue
            pending.append(f"{req}={status or 'pending'}")
    if awaiting and not pending:
        return (f"stage {stage['id']} cannot start for {role or 'this role'} - " + "; ".join(awaiting) + f". Only that role is let into "
                f"{stage['id']} until the record stands: dispatch it, and its finish records the verdict "
                f"(`stage_done.py --task {pipeline.get('ticket') or '<T>'} --stage {stage['requires'][-1]} --acceptance work/handoffs/<its dispatch>.yaml`).")
    pending += awaiting
    if pending:
        return (f"stage {stage['id']} cannot start — required stages are not done: "
                f"{', '.join(pending)}. Finish them (or record why they were skipped) first.")
    return None


def rule_gate_a(model: dict, stage: dict, pipeline: dict) -> str | None:
    after = ((model.get("gates") or {}).get("A") or {}).get("after")
    if not after:
        return None
    if stage_index(model, stage["id"]) <= stage_index(model, after):
        return None
    import contract as C
    if C.gate_approved(pipeline, "A"):
        return None
    # `gates` that is not an object (a hand-damaged file) used to raise here and the crash read as an allow (t-1547, FR-59):
    # an unreadable record is "not approved", and the refusal below says so.
    gates = pipeline.get("gates")
    record = gates.get("A") if isinstance(gates, dict) else None
    record = record if isinstance(record, dict) else {}
    decision = record.get("decision") or record.get("status")
    return (f"stage {stage['id']} is past gate A, and gate A is not approved "
            f"(gates.A.decision = {decision!r}). Show understanding.md and test-plan.md to the "
            "human and record the decision in pipeline.json before dispatching.")


def rule_awaiting_code(model: dict, stage: dict, pipeline: dict) -> str | None:
    """Rule 8 (t-2181 PC-6 C13, t-2277 J-C8): a story HELD FOR CODE is not let into a stage from `held_from` (S6 for `s5_absent_side`,
    S3 for `first_look_stop`) - the controller refuses the dispatch of such a stage too; this is the guard's own line for the hook
    that sees a role launched by hand. The hold is read through `contract.awaiting` (the one reader, AR-13) from the story's own
    `pipeline.awaiting`; a record it cannot read is no record, and `held_from` that names no stage reads as the reader's default
    stage. A stage BELOW `held_from` is open: a rework of S0..held_from-1 runs inside the hold. A person's word passes it like any
    block (`waiver.py`, journaled as `gate_override`); the arrival of the code, `stop_waiting` and the rework below are the doors
    the line names."""
    import contract as C
    hold = C.awaiting(pipeline)
    if hold["state"] == "none":
        return None
    start = stage_index(model, hold["held_from"])
    if start < 0:
        start = stage_index(model, C.AWAITING_DEFAULT_HELD_FROM)
    if stage_index(model, stage["id"]) < start:
        return None
    stopped = hold["state"] == "stopped"
    return (f"stage {stage['id']} is held for code ({hold['cause']}) from {hold['held_from']}"
            + (": the person stopped the wait" if stopped else ": the code this story delivers is not there yet")
            + ". No role of this stage starts until the code arrives (relaunch the story with `--mr`, `--branch`, `--commit` or "
              "`--side <side>=real`), or the person ends the wait (`controller.py --operation stop_waiting --words-file <file>`); "
              f"a rework of the stages before {hold['held_from']} is open.")


def dispatch_errors(pipeline: dict, stage_id: str, *, assume_gate_approved: str | None = None,
                    journal: bool | None = None, model: dict | None = None, ticket: str | None = None,
                    event: dict | None = None, role: str | None = None,
                    task_root=None) -> list[str]:
    """Rules 1 and 2 for one stage - and rule 3 for S6-S8, the manifest those stages are judged against - already passed
    through a person's recorded word. `ticket` (default: the pipeline's own) and `event` locate the manifest; with no
    ticket there is nothing to look for and rule 3 is not asked. `role` is the dispatched role, when the caller knows
    it: rule 3's sentence then starts "dispatching <role> (<stage>)", as before it joined this list. `task_root` is the
    story's folder when the caller works on one of its own (the controller's `--task-root`): the manifest is read there
    and nowhere else; None (the hook) keeps `artifacts_dir(ticket)` of the cwd project.

    The one entry point for "may this stage be dispatched": the hook below, `controller.py
    --operation dispatch` (so a refusal leaves no receipt) and the gate rehearsal all
    ask it here, and all three get the same answer with the same waiver command at the end.

    `assume_gate_approved` names a gate to treat as approved — the rehearsal asks "what would
    stop S5 if the person approved A right now", which is the whole point of asking BEFORE the
    gate is shown. A hypothetical writes nothing, so it does not journal unless the caller
    insists with `journal=True`."""
    model = model or stage_model()
    stage = next((s for s in model.get("stages") or [] if s.get("id") == stage_id), None)
    if stage is None:
        return []
    ticket = str(ticket or (pipeline or {}).get("ticket") or "")
    raw = [rule_order(model, stage, pipeline, role=role,
                      state_of=lambda: awaiting_state(pipeline, ticket, task_root, event))]
    if str(assume_gate_approved or "").upper() != "A":
        raw.append(rule_gate_a(model, stage, pipeline))
    raw.append(rule_awaiting_code(model, stage, pipeline))
    ticket = str(ticket or (pipeline or {}).get("ticket") or "")
    if ticket and stage_id in MANIFEST_STAGES:
        what = f"dispatching {role} ({stage_id})" if role else f"dispatching stage {stage_id}"
        raw.append(rule_manifest(ticket, what, event, required=True, pipeline=pipeline, task_root=task_root))
    raw = [m for m in raw if m]
    import waiver
    blocking, passed = waiver.split_overridden(raw, pipeline, stage_id)
    if journal is None:
        journal = assume_gate_approved is None
    if passed and journal:
        journal_override(pipeline, stage_id, passed, event)
    return [f"{m} {waiver_hint(ticket, stage_id, m)}" for m in blocking]


def journal_override(pipeline: dict, stage_id: str, passed: list, event: dict | None = None) -> None:
    """A block passed by a person's word is a fact about the run, not a silence. Best-effort:
    a journal that cannot be written must never undo the person's decision (waiver.py says the
    same where it records one)."""
    try:
        from hooklib import project_root
        from datetime import datetime, timezone
        cfg = load_config(event)
        path = RP.configured(project_root(event), cfg.get("journal_path"), "journal.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        notes = (f"{stage_id}: {len(passed)} dispatch block(s) passed by the person's word; " +
                 "; ".join(f"{p['error'][:120]} <- \"{p['decision']}\"" for p in passed[:3]))
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "event": "gate_override", "agent": "stage_guard", "notes": notes}
        ticket = str((pipeline or {}).get("ticket") or "")
        if ticket:
            record["task"] = ticket
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def unresolved_rows_without_decision(manifest: dict) -> list:
    """The rows whose `reason` is outside the closed list. Only the reason is read: a row is
    free to carry anything else the writer found — a partition, an instance id, the `remedy`
    that would end an environment block — and this guard has no opinion about those fields."""
    out = []
    closed = set(closed_unresolved_reasons())
    for item in (manifest or {}).get("unresolved") or []:
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason") or "")
        base = reason.split(":", 1)[0]
        if not (base in closed or reason.startswith(DEFERRED_PREFIX)):
            out.append(f"{item.get('case') or '?'} ({reason or 'no reason'})")
    return out


MANIFEST_NAME = "automation-manifest.json"
MANIFEST_STAGES = ("S6", "S7", "S8")


def manifest_path(task_root: Path) -> Path:
    """The ONE resolution of the automation manifest in this guard: `read_manifest` and `_manifest_covers` both ask it.

    `work/automation-manifest.json` (the registry's path) when that exists - readable or not, it IS the manifest; the
    flat legacy name only when `work/` holds none. A stale flat copy is never read over an existing `work/` one: the first
    form of this resolver took `contract.artifact`, which raises on two different copies, and fell back to the flat file,
    so an open row under `work/` passed in silence (t-912 F-2). A registry that cannot be imported keeps the flat name.
    `ledger_path` below is a sibling resolver with the older pick (queued, not changed here)."""
    try:
        from artifact_registry import canonical  # local: a hook pays for this import only when it reaches this rule
    except ImportError:
        return task_root / MANIFEST_NAME
    chosen = canonical(task_root, MANIFEST_NAME)
    return chosen if chosen.exists() else task_root / MANIFEST_NAME


def read_manifest(ticket: str, event: dict | None = None, task_root=None) -> tuple:
    """(manifest, state, path): `state` is "read" (a JSON object, however few items), "absent" (no such file) or
    "unreadable" (the file is there but is not JSON, not UTF-8, or not an object). `read_json` alone answers `{}` to all
    three. `task_root`, when the caller works on a story root of its own (the controller's `--task-root`), is THE story:
    the cwd project's `artifacts/<ticket>` is then never consulted."""
    path = manifest_path(Path(task_root) if task_root else artifacts_dir(ticket, event))
    manifest = hooklib.read_json(path, None, kind=dict, errors=Exception)
    if manifest is not None:
        return manifest, "read", path
    return {}, ("unreadable" if path.exists() else "absent"), path


def unresolved_without_decision(ticket: str, event: dict | None = None) -> list:
    return unresolved_rows_without_decision(read_manifest(ticket, event)[0])


def s5_skipped(pipeline: dict) -> bool:
    """True when pipeline.json records S5 as a typed skip (a preparatory / no-implementation policy: no automator ran,
    so no manifest is expected). Anything else - done, pending, no S5 entry - is False: S5 is not recorded as skipped.
    The carrier is the pipeline the dispatch guard has already read (the controller projects S5's status into it,
    `skipped` unchanged), so there is no second file whose unreadable state would be an unknown."""
    stages = (pipeline or {}).get("stages")
    entry = stages.get("S5") if isinstance(stages, dict) else None
    return isinstance(entry, dict) and entry.get("status") == "skipped"


def manifest_unread(what: str, state: str, path: Path, skipped: bool) -> str | None:
    """S6-S8 only. The refusal for a manifest the stage cannot be judged without, or None when none is expected."""
    # an absent manifest is owed at the registry's path; an unreadable one is named where it is
    shown = MANIFEST_NAME if state == "unreadable" and path.parent.name != "work" else "work/" + MANIFEST_NAME
    door = ("qa-automator writes it in S5 through manifest_put.py; re-dispatch it for the window (the orchestrator "
            "does not write the file by hand), or run `controller.py --operation recover` and read what the controller holds")
    if state == "unreadable":
        fix = ("S5 is recorded as skipped by a policy, so no manifest is expected: remove the file, or repair it into "
               "a JSON object" if skipped else door)
        return (f"{what} is blocked — {shown} could not be read (it is there, but it is not a JSON object). Expected: the "
                f"manifest S5 wrote, a JSON object with tests[] and unresolved[]. {fix}.")
    if skipped:
        return None
    return (f"{what} is blocked — {shown} is absent: S5 is not recorded as skipped by a policy, so the manifest of its "
            f"instances is owed to S6-S8. {door}.")


def rule_manifest(ticket: str, what: str, event: dict | None = None, *, required: bool = False,
                  pipeline: dict | None = None, task_root=None) -> str | None:
    """Rule 3. `required` is the S6-S8 dispatch branch (asked by `dispatch_errors`, so a person's word reaches it): a
    manifest that is absent or unreadable is then a refusal, not "nothing found". The commit of test code (S5 writes tests
    BEFORE the manifest exists) stays on the default: no manifest, no open items."""
    manifest, state, path = read_manifest(ticket, event, task_root)
    if required and state != "read":
        message = manifest_unread(what, state, path, s5_skipped(pipeline or {}))
        if message:
            return message
    open_items = unresolved_rows_without_decision(manifest)
    if open_items:
        return (f"{what} is blocked — automation-manifest.json has unresolved cases without a reason "
                f"from the closed vocabulary: {DV.joined(open_items, noun='case', max_chars=None, sep=', ')}. "
                f"Give each a reason "
                f"({' | '.join(closed_unresolved_reasons())} | {DEFERRED_PREFIX}:<gate>).")
    return None


def rule_tracker_route(ticket: str, role: str, stage_id: str, pipeline: dict,
                       event: dict | None = None) -> str | None:
    """S1 reads the tracker itself — so the route has to be proven BEFORE S1 is dispatched.

    TP2-2553: `readiness` rated a tracker reached through the orchestrator's MCP tool
    `unknown / orchestrator`, S0 fetched the ticket with that tool and went green, and the
    qa-scout dispatched at S1 held no such tool and no other route. It stalled; the
    orchestrator spent 2 h 54 min fetching tickets by hand. The route readiness proves is the
    one the ROLE uses (`adapters.ticket.direct_api`), and this is where the difference stops
    costing a stage.

    Quiet by design where it would punish someone for an older version: with no
    `qa-factory/state/readiness.json` (or, in a project not yet re-onboarded, the old
    `qa-factory/readiness.json`), or none that measured this capability, nothing is refused —
    a story in flight on 0.7.9 must not stop because a new row was added above it."""
    if role != "qa-scout" or stage_id != "S1":
        return None
    from hooklib import project_root
    import local_keys
    if local_keys.is_local(ticket, project_root(event)):
        return None         # SS1-14: no tracker holds a local key, so no tracker route is owed; a tracker key is refused as before
    entry = (read_json(RP.readiness(project_root(event))).get("capabilities") or {}).get("ticket_adapter")
    if not isinstance(entry, dict) or not entry.get("status"):
        return None
    status = str(entry.get("status"))
    if status == "ok":
        return None
    if status == "unknown" and entry.get("route") == "role":
        return None         # SS1-15: the scout reads the tracker by the route onboarding recorded; a route only the orchestrator holds carries no such field and stays refused
    remedy = entry.get("remedy") if isinstance(entry.get("remedy"), dict) else {}
    steps = [str(s).strip() for s in (remedy.get("steps") or []) if str(s).strip()]
    fix = str(remedy.get("command") or "").strip() or (steps[0] if steps else "")
    raw = (f"dispatching {role} ({stage_id}) is blocked — the tracker route this role would "
           f"read through is not proven: readiness.py rates `ticket_adapter` {status} "
           f"(owner: {entry.get('owner') or 'unknown'}). {str(entry.get('note') or '').strip()}."
           + (f" Do this first: {fix}." if fix else "")
           + " Then `readiness.py --write` and dispatch again — S1 is the stage that reads the "
             "tracker, and a route only the orchestrator can use leaves the scout with nothing.")
    import waiver
    blocking, passed = waiver.split_overridden([raw], pipeline, stage_id)
    if passed:
        journal_override(pipeline, stage_id, passed, event)
        return None
    return f"{blocking[0]} {waiver_hint(ticket, stage_id, raw)}"


def ledger_path(task_root: Path) -> Path:
    """Where `ledger.py` actually wrote it. `artifact-registry.json` moved the ledger to
    `work/ledger.json` with the flat name kept as a legacy alias; this guard still read the
    flat path, so on a 0.7.7 story it found nothing and refused every delivery command with
    "delivery_ready was never computed" — the factory's own defect presented as the person's
    unfinished work. `contract.artifact` is the one resolver that knows both spellings."""
    try:
        import contract  # local: a hook pays for this import only when it reaches this rule
        return contract.artifact(task_root, "ledger.json")
    except Exception:
        return task_root / "ledger.json"


def _before_gate_b(pipeline) -> tuple:
    """(stage, status) when gate B is still ahead - the stage `gates.B.after` is not `done` in `pipeline` - else None.
    A `stages` that is no object or a stage with no status reads as not done (`pending`): an unreadable record never
    opens anything here, it only picks the sentence."""
    try:
        after = ((stage_model().get("gates") or {}).get("B") or {}).get("after")
    except Exception:   # the stage table is unreadable: the sentence stays today's, the verdict was already reached
        return None
    if not after or not pipeline:
        return None
    stages = pipeline.get("stages") if isinstance(pipeline, dict) else None
    record = stages.get(after) if isinstance(stages, dict) else None
    status = record.get("status") if isinstance(record, dict) else None
    return None if status == "done" else (after, str(status or "pending"))


RISK_REASON_SHOWN = 300     # the recorded reason shown in a refusal; the cut is named, the record keeps it whole (E6)
JUDGED_WHOLE = ("The guard judges a whole command before any of it runs: a journal write in the same command has not happened yet.")


def rule_delivery(ticket: str, what: str, event: dict | None = None, matched: tuple | None = None,
                  pipeline: dict | None = None) -> str | None:
    """Rule 4 for a COMMAND (the MR forms): since t-1547 a role is gated by its gate's decision (`rule_gate_ordered`), so
    this rule speaks for commands only. `matched` is (command, source) of the delivery form a Bash call ran
    (`_delivery_match`): the refusal names it and where the guard knows it from, so a person reads WHICH word gated it.
    With `matched` and the story's `pipeline` and gate B still ahead (CX2-27 b), the refusal does not name a door that
    cannot open yet (`deliver with known gaps`, `check_delivery`): it says the words were read as a delivery and how to
    write the command without them. ONLY the sentence changes - the verdict is the ledger's and the journal's as before."""
    ledger = read_json(ledger_path(artifacts_dir(ticket, event)))
    # t-305 N8 (Q3): the third verdict opens every verdict-gated act like `yes` - the person's checks are theirs to finish
    # ("the factory does not control what the person does", owner 03.10). The word is read by THE reader, so the string
    # "no" is never truthy and an inconsistent or unknown word, like an absent ledger, refuses.
    import delivery_verdict as DV
    if DV.word_of(ledger) in ("yes", "after_checks"):
        return None
    for row in journal_lines(event):
        if str(row.get("event") or row.get("type") or "") == "deliver_with_risks" and \
                str(row.get("task") or row.get("ticket") or "") == ticket:
            return None
    reasons = ledger.get("reasons") or []
    detail = "; ".join(str(r) for r in reasons[:3]) if reasons else "the ledger records no reason"
    if matched:
        what += f" (`{matched[0]}`, from {matched[1]})"
        ahead = _before_gate_b(pipeline)
        if ahead:
            return (f"{what} is blocked: the guard read these words as a delivery, and no delivery is possible yet: "
                    f"gate B comes after {ahead[0]}, which is {ahead[1]}. If this command does not deliver anything, write it "
                    "without those words in one command: split it into plain commands, or put the text in a file with the "
                    "Write tool and name the file. If it does deliver, it waits for gate B.")
    # The head names the condition that is true, built from the ledger's PRESENCE first: `read_json` answers `{}` for an
    # absent ledger and `word_of({})` says `no`, which would state a verdict that was never computed (FR-41). It names every
    # opener the code above knows: yes, after_checks, a deliver_with_risks journal line.
    if not ledger:
        head = (f"{what} is blocked — the delivery verdict for {ticket} was never computed (ledger.json is missing or "
                "unreadable) — run check_delivery.py. ")
    else:
        head = (f"{what} is blocked — the delivery verdict for {ticket} is `{DV.word_of(ledger)}`; it opens at yes or "
                f"after_checks, or with a deliver_with_risks line in the journal: {detail}. ")
    import contract     # late, as `ledger_path` does: a hook pays for it only when it reaches a refusal
    if isinstance(pipeline, dict) and contract.gate_approved(pipeline, "B"):
        # HF8-23: gate B IS recorded, so the person is not asked to say it at gate B again (FR-7). Reads the record only and opens
        # nothing: the pass is the journal line above. ERROR DIRECTION: toward refusal.
        door = contract.risk_journal_door(ticket)
        risk = contract.gate_risk_reason(pipeline)
        if risk:
            shown = risk if len(risk) <= RISK_REASON_SHOWN else risk[:RISK_REASON_SHOWN] + "... (cut here; pipeline.json gates.B.deliver_with_risks keeps it whole)"
            return (head + f"Gate B is recorded with the person's decision to deliver with known gaps (reason: {shown}), and the journal has "
                    f"no deliver_with_risks line for {ticket} yet. Write it, with that reason in the file, as its own call: `{door}`. "
                    + JUDGED_WHOLE)
        return (head + "Gate B is recorded, and it records no decision to deliver with known gaps. If the person's words say it, run "
                f"`{door}` with their reason, as its own call; if they do not, ask them once for the decision and its reason. A new "
                "gate B decision is not the way: it orders the reporter and the MR again. " + JUDGED_WHOLE)
    return (head + "Either close the gaps, or have the human say 'deliver with known gaps' at gate B "
            "(with a reason) so the journal carries a deliver_with_risks event.")


def gate_of_executor(role: str, model: dict | None = None) -> str:
    """The gate whose recorded decision opens `role`, from the ONE table of orders (`hooklib.gate_orders`, S8
    `gate_orders` in stages.json): the gate of the order whose executor is this role; "" when no order names the role. The
    pair role -> gate is data, never a literal of this guard (AR-1)."""
    for spec in hooklib.gate_orders(model).values():
        executor = spec.get("executor")
        if isinstance(executor, dict) and executor.get("role") == role and spec.get("gate"):
            return str(spec["gate"])
    return ""


def rule_gate_ordered(pipeline: dict, ticket: str, role: str, gate: str, task_root: Path | None = None) -> str | None:
    """Rule 4 for a role that executes an order of a gate: it runs once the person's decision of that gate is RECORDED.
    The verdict word of the ledger is not asked - a story whose checks say `no` is exactly the story whose bugs are
    filed (owner, 28.10.2026: how can the verdict be `yes` when there are bugs?).

    The reader is `contract.gate_approved` (AR-13). ERROR DIRECTION: its generosity only ever opens (a hand-written
    `{"status": "deferred", "decision": "approve"}` or `{"decision": "Approved "}` open, the controller writes neither);
    no `gates`, `gates` that is not an object, no record, `{}`, a string record, `declined`, `deferred` and `edit` all
    refuse - the reporter never runs before the decision (FR-59), and the refusal names the door (FR-57)."""
    import contract
    if contract.gate_approved(pipeline, gate):
        return None
    root = task_root if task_root is not None else f"qa-factory/artifacts/{ticket}"
    door = person_words.door(f'controller.py --task-root {root} --operation gate-decision --gate {gate} '
                             '--drafts "<the refs they chose>" --bugs ordered')
    return (f"dispatching {role} waits for the gate {gate} decision: the {role.removeprefix('qa-').replace('-', ' ')} "
            f"does what the person chose there, and no decision of gate {gate} is recorded for {ticket}. "
            f"Record the decision first: `{door}`.")


# --- the entry point ------------------------------------------------------------------------

def check(event: dict) -> int:
    """0 = allow, 2 = deny (the reason is already on stderr). A crash of the command walker is a deny with its door,
    never the fail-open below: the walker is what reads the command, so nothing judged it (CX1-20 N-1).

    A crash BEFORE a verdict allows, and leaves one `hook_signal` (`guard_crashed`: the tool and the exception) that
    the run report reads (RH1-5, owner's word 27.10.2026, F-9): a guard that crashes must not jam every repo on the
    machine, and its crash is never silent (FR-59). A crash AFTER `deny(...)` has spoken denies: the verdict was
    already given and a late crash does not take it back (E15). POSITION: `LAST_DENIAL` is cleared on entry, so a
    refusal of an earlier call is never read as this call's. Accepted residual risk: a delivery or commit command, or
    a resume of another's agent, may pass unread when the guard crashes - the signal is its trace."""
    LAST_DENIAL["message"] = ""
    try:
        return _check(event or {})
    except hooklib.WalkerError as e:
        return deny(hooklib.WALKER_DOOR.format(reason=e))
    except Exception as e:
        if LAST_DENIAL["message"]:
            return DENY
        hooklib.person_signal(event, "guard_crashed", f"{(event or {}).get('tool_name') or 'unknown tool'}: "
                                                      f"{type(e).__name__}: {e}")
        return ALLOW


def _check(event: dict) -> int:
    tool = str(event.get("tool_name") or "")
    if tool in ("Task", "Agent"):
        return check_dispatch(event)
    if tool in ("Bash", "PowerShell"):
        return check_command(event)
    if tool == "SendMessage":
        return check_resume(event)
    return ALLOW


def check_resume(event: dict) -> int:
    """Rule 6 — a resumed dispatch is addressed to an agent this story already ran.

    Resuming is how a critic confirms its own `fix_notes` were applied without a second
    review (s5.md), and it is worth having: the same review, five turns, against a fresh
    dispatch that re-runs everything. But `SendMessage` is not `Agent`, so rules 1–4 never
    saw it — and a guard that can be stepped around by changing the tool is not a guard. The
    id must be one this story recorded — on a stage in `pipeline.json`, or on a dispatch record
    in `state/controller.json`; anything else is a new dispatch wearing a different name, and
    it goes through `Agent` where the stage rules live.

    WHICH agents count (CX1-9). An agent a `superseded` or released dispatch carried is history, not a
    context to go back to (`_resumable_agents`), on both hosts. On Codex a receipt also vouches for a
    recipient, but only when EVERY receipt that answers to it names this story and a resumable dispatch of
    it (`_vouched`): a name another story's receipt also holds, or one a retired dispatch holds, is never
    resolved by luck. A CLOSED author (HF8-15 (2): all its work accepted, on a stage whose rework resumes its role, no
    rework waiting for a binding) is retired the same way, on both hosts: closed work goes back through the controller, and
    the refusal names that door (`_closed_author_door`), not a message.

    A `send_input(interrupt=true)` is judged HERE too, by the same recipient rule (B-1, t-1080): the host
    activates the recipient and delivers its message, so the call must go to an agent of THIS story, whatever
    `worker_lifecycle.guard` (which runs first and judges only live receipts) made of the stop. Nothing about
    the call's shape (`interrupt`, a message or none) lets it past the recipient check."""
    ticket = requested_ticket(event)
    targets = resume_targets(event)
    if not ticket:
        return _unidentified_resume(event, targets)
    pipeline = read_json(artifacts_dir(ticket, event) / "pipeline.json")
    if not pipeline:
        return ALLOW
    if not targets:
        # M13: a message that names no agent under any alias is not a resume. With a value
        # under any alias this branch is unreachable: each one goes through the check below.
        return ALLOW
    # The dispatch records hold an id pipeline.json has not projected yet: `--operation
    # dispatch` (and `checkpoint`/`accept`) may carry `agent_id`, and the controller keeps it
    # on the record before the stage's last one reaches pipeline.json.
    controller = read_json(artifacts_dir(ticket, event) / "state" / "controller.json")
    known, retired = _resumable_agents(pipeline, controller)
    why = {}   # a receipt's veto per target: a fact about ITS dispatch, never about a recorded agent (M-1)
    if _is_codex_resume(event):
        vouched, why = _vouched(event, ticket, targets, controller)
        known |= vouched
    # Allowed ONLY when every recipient named is one this story recorded.
    unrecorded = [target for target in targets if target not in known]
    if not unrecorded:
        # SC2-17: a known target whose only open dispatch is STOPPED (blocked/paused) is refused WHEN `resume` would open.
        # POSITION: here, after every refusal for a foreign or unknown agent (those stay first and byte for byte); the text is built
        # in this `try`, BEFORE `deny` (an exception here is today's ALLOW - the permitted direction: an unknown never refuses).
        stopped_text = ""
        try:
            stopped_text = _stopped_refusal(event, ticket, targets, controller)
        except Exception:
            stopped_text = ""
        if stopped_text:
            return deny(stopped_text)
        return ALLOW
    if not known:
        # TP2-2553: the only thing that ever wrote an agent_id was `stage_done.py
        # --agent-id`, which nobody called, so this refusal met every resume of a stopped
        # role — and named neither the place the id now lives nor the way past it. When
        # agents ARE recorded and the filter retired them all, the text says so (M-2).
        recorded = _none_resumable(retired) or "no agent_id is recorded for this story, so there is nothing to resume"
        recorded += "".join(f"; a receipt names {t}, but {why[t]}" for t in unrecorded if t in why)
        try:
            nothing_open = not _open_targets(event, ticket, unrecorded, retired, why, controller)
        except Exception:
            # POSITION: `check` answers ALLOW on an exception before `deny`; a failing helper keeps the invitation
            # this branch always had.
            nothing_open = False
        if nothing_open:
            # DC1-16 E11: no name is open (each is a retired agent, a vetoed receipt, or held by another story's
            # receipt), so the `bind` door would only re-invite what the filter retired (E2): the door is the new
            # dispatch alone.
            door = ("A new dispatch is the answer: `controller.py --task-root <T> --operation recover` prints the "
                    "ready retry packet, and `--operation dispatch --input <file>` sends it.")
        else:
            door = ("The id comes back with the host's task notification: pass it as `agent_id` on the dispatch "
                    "request (`controller.py --operation dispatch`, also accepted on `checkpoint`/`accept`), or "
                    f"bind it with `{_bind_command('<TICKET>', '<DISPATCH>', '<id>')}`. To go on without one, "
                    "`controller.py --task-root <T> --operation recover` prints the ready retry packet for the "
                    "stopped dispatch, and `--operation dispatch --input <file>` sends it.")
        try:
            # HF8-15 (2): a closed author's door replaces what would invite a bind or a new dispatch (FR-2); the old door
            # stays only for the neighbours that are not closed. POSITION: in this `try`, before `deny` (E8).
            doors = _closed_doors(event, ticket, unrecorded, controller)
            if doors:
                door = _closed_text(doors, unrecorded) + (f" {door}" if len(doors) < len(unrecorded) else "")
        except Exception:
            pass
        return deny(f"{ticket}: resuming a dispatch is blocked — {recorded}. {door}")
    names = ", ".join(unrecorded)
    facts = "; ".join(f"{t}: {'; '.join(dict.fromkeys(fact for fact in (retired.get(t), why.get(t)) if fact))}"
                      for t in unrecorded if t in retired or t in why)
    # DC1-16: the tail names the door when a live dispatch of this story can take the id. POSITION: the helper
    # runs in this `try` BEFORE `deny`, because `check` answers ALLOW on an exception that precedes the verdict
    # (guard_crashed): a crashing helper outside it would open the refusal. Any failure leaves today's tail.
    try:
        tail = _resume_doors(event, ticket, unrecorded, retired, why, controller, pipeline)
        doors = _closed_doors(event, ticket, unrecorded, controller)   # HF8-15 (2): only a closed target changes the tail
        if doors:
            text = _closed_text(doors, unrecorded)
            tail = text if tail == _RESUME_UNKNOWN_TAIL else f"{text} {tail}"
    except Exception:
        tail = _RESUME_UNKNOWN_TAIL
    return deny(f"{ticket}: resuming '{names}' is blocked — it is not a "
                f"dispatch this story ran{f' ({facts})' if facts else ''} (it knows {sorted(known)}). {tail}")


def _unidentified_resume(event: dict, targets: list) -> int:
    """`check_resume` when no story resolved (FB-16). A Codex resume that names a recipient but resolves to
    no story, in a project that HAS stories (closed and archived ones count), is a resume of something, and
    an unidentified one must not pass just because the guard could not say which story it belongs to: it
    is refused, with the door a Desktop `followup_task` (no task_id) can use. A project with no story at all
    is not the guard's business, and the Claude host keeps the answer it always had (F-1: its
    `SendMessage` carries no receipt to read, and its identity is as on `main`)."""
    if targets and _is_codex_resume(event) and any(artifact_root(event).glob("*/pipeline.json")):
        return deny("resume story identity is missing or ambiguous: the recipient(s) "
                    f"'{', '.join(targets)}' match no host binding of exactly one story on "
                    "disk (none, or receipts of two stories). Record the recipient first: "
                    f"`{_bind_command('<TICKET>', '<DISPATCH>', '<recipient>')}` (the path or name the "
                    "host gave), or pass an explicit task_id where the host carries one. "
                    "No story was selected.")
    return ALLOW  # no story here — not the guard's business


UNRESUMABLE = ("superseded", "released_by_person")   # controller.RELEASED; pinned equal by test_resume_story_isolation
RESUMABLE_STOPPED = ("blocked", "paused")   # Controller.RESUMABLE; pinned equal by test_resume_doors (DC1-16)
RETURNED_UNACCEPTED = "returned_unaccepted"   # controller.RETURNED; pinned equal by test_resume_doors
BUDGET_EXHAUSTED = "INFRA/BUDGET_EXHAUSTED"   # controller.BUDGET_EXHAUSTED: `resume` refuses it; pinned by test_resume_doors

# The tail of `SG-resume-unknown` when no live dispatch of this story can take the id (and the tail every failure of
# `_resume_doors` falls back to): today's text, byte for byte.
_RESUME_UNKNOWN_TAIL = ("A resume goes back to an agent that already holds this story's context; anything "
                        "else is a new dispatch and belongs in Agent, where the stage rules apply.")


def _bind_command(task: str, dispatch: str, agent: str) -> str:
    """The ONE spelling of `story_step.py bind` in this guard's refusals (three sites: the empty-record branch of
    `check_resume`, its unknown-agent door, `_unidentified_resume`), so the three cannot drift apart."""
    return f"story_step.py bind --task {task} --dispatch-id {dispatch} --agent-id {agent}"


def _receipt_stories(event: dict, target: str) -> set:
    """The stories whose receipts answer to `target` (DC1-16 F2), whatever else those receipts carry. Unlike
    `_recipient_receipts` this counts a receipt with NO `dispatch_id` (a Codex spawn receipt: `host_dispatch.record`
    writes the story's `task_id` and `dispatch_id: None`): vouching needs the stricter reading, the door must not
    miss a receipt of another story because of it. Withholding a door is the safe error."""
    from host_dispatch import binding_names, matching_binding_paths
    rows = [read_json(p) for p in matching_binding_paths(hooklib.project_root(event), target)]
    return {r["task_id"] for r in rows if target in binding_names(r)
            and isinstance(r.get("task_id"), str) and r["task_id"]}


def _open_targets(event: dict, ticket: str, unrecorded: list, retired: dict, why: dict, controller: dict) -> list:
    """The unrecorded names a `bind` or `resume` door may be offered to (the ONE list both `SG-resume-*` branches use):
    not a retired agent (a new record would make it known again), not one a receipt vetoes, not one whose receipts name
    another story (on either host, with or without a dispatch: a bind would hand that story's agent this dispatch's
    `agent_type` and `task_id`), and not one a receipt of THIS story ties to a dispatch that has no record here or is
    retired (the `_vouched` rule, on both hosts)."""
    records = controller.get("dispatches") if isinstance(controller.get("dispatches"), dict) else {}
    root = artifact_root(event)
    found = []
    for target in unrecorded:
        if target in retired or target in why or not _receipt_stories(event, target) <= {ticket}:
            continue
        if any(not isinstance(records.get(dispatch), dict) or records[dispatch].get("status") in UNRESUMABLE
               for story, dispatch in _recipient_receipts(event, root, target) if story == ticket):
            continue
        found.append(target)
    return found


def _story_is_open(controller: dict, pipeline: dict) -> bool:
    """The controller's own closure reading (`controller.closure_of`, the ONE reading) says the story is open. `resume`
    refuses a stopped dispatch on a closed or executing story (`_resume_problems` -> `_closed_dispatch_refusal`), so the
    door is not named there (DC1-16 F1, FR-2). Called on the refusal path only, inside `_resume_doors`' caller's `try`."""
    from controller import closure_of
    return closure_of(controller, pipeline)["state"] == "open"


def _resume_doors(event: dict, ticket: str, unrecorded: list, retired: dict, why: dict, controller: dict,
                  pipeline: dict) -> str:
    """The tail of `SG-resume-unknown` (DC1-16, the Dev6 review of TP2-2702): the door an unknown id can use, or
    `_RESUME_UNKNOWN_TAIL` when it has none. A door that will not open is never named (FR-2).

    The door is offered for the OPEN targets only: not a retired agent (a new record would make it known again in
    `_resumable_agents`), not one a receipt vetoes, and not one whose receipts name another story (on either host: a
    `bind` would hand that story's agent this dispatch's `agent_type`). Then, by what the story's dispatch records hold:
    - a `running` record with a stage, or a `returned_unaccepted` one whose stage the controller has not accepted:
      `story_step.py bind` writes the id to `pipeline.json` and the guard allows the repeat (`bind` of a returned
      dispatch on an accepted stage writes no id, so it is not offered);
    - otherwise a `blocked` / `paused` record with no agent, a reason other than the story budget, and NO `running`
      record anywhere in the store, and a story the controller reads as open: `story_step.py resume --agent-id` (the
      controller refuses the other four; a closed or executing story is the fourth, F1).
    Records are named by their KEY (`bind` and `resume` look the dispatch up by it). A record that is not an object,
    has no `id`, or has no stage is skipped. Returns a string only; the verdict stays the caller's."""
    open_targets = _open_targets(event, ticket, unrecorded, retired, why, controller)
    if not open_targets:
        return _RESUME_UNKNOWN_TAIL
    records = controller.get("dispatches") if isinstance(controller.get("dispatches"), dict) else {}
    stages = controller.get("stages") if isinstance(controller.get("stages"), dict) else {}
    rows = [(str(key), rec) for key, rec in records.items()
            if isinstance(rec, dict) and rec.get("id") and isinstance(rec.get("stage"), str) and rec["stage"]]

    def label(key: str, rec: dict) -> str:
        role = rec.get("role")
        text = f"{key} ({role})" if isinstance(role, str) and role.strip() else key
        held = rec.get("agent_id")
        if rec.get("status") in ("running", RETURNED_UNACCEPTED) and isinstance(held, str) and held.strip():
            text += f" (now bound to {held.strip()}; a bind replaces it, and {held.strip()} can be resumed as it is)"
        return text

    def accepted(rec: dict) -> bool:
        stage = stages.get(rec["stage"])
        return isinstance(stage, dict) and stage.get("status") == "completed"

    bindable = [(k, r) for k, r in rows if r.get("status") == "running"
                or (r.get("status") == RETURNED_UNACCEPTED and not accepted(r))]
    stopped = []
    if (not bindable and not any(isinstance(r, dict) and r.get("status") == "running" for r in records.values())
            and _story_is_open(controller, pipeline)):
        stopped = [(k, r) for k, r in rows if r.get("status") in RESUMABLE_STOPPED
                   and not (isinstance(r.get("agent_id"), str) and r["agent_id"].strip())
                   and r.get("reason") != BUDGET_EXHAUSTED]
    chosen = bindable or stopped
    if not chosen:
        return _RESUME_UNKNOWN_TAIL
    who = open_targets[0] if len(open_targets) == 1 else "<id>"
    if len(chosen) == 1:
        named, plain = label(*chosen[0]), chosen[0][0]
    else:
        named = "<one of: " + ", ".join(label(k, r) for k, r in chosen) + ">"
        plain = "<one of: " + ", ".join(k for k, _ in chosen) + ">"
    if bindable:
        step = f"If {who} is the agent working on {named}: bind it first with `{_bind_command(ticket, plain, who)}`"
    else:
        step = (f"If {who} is the agent working on {named}, stopped: "
                f"`story_step.py resume --task {ticket} --dispatch-id {plain} --agent-id {who}`")
    return (f"A resume goes back to an agent that already holds this story's context. {step}, then send again. "
            "Otherwise it is a new dispatch and belongs in Agent, where the stage rules apply.")


def _none_resumable(retired: dict) -> str:
    """The truthful half of `SG-resume-none` when the filter, not an empty record, emptied `known` (M-2):
    "N agents recorded for this story, none resumable: <agent> (<why>); ...". `retired` is
    `_resumable_agents`' own - agents a record of this story carries, one entry each - never a receipt's
    veto (M-1: a dispatch with no record here is no recorded agent); "" when nothing was retired."""
    if not retired:
        return ""
    return (f"{len(retired)} agent{'s' if len(retired) != 1 else ''} recorded for this story, none resumable: "
            + "; ".join(f"{agent} ({fact})" for agent, fact in retired.items()))


def _resumable_agents(pipeline: dict, controller: dict) -> tuple:
    """`(known, retired)`: the agent ids this story's resume may go back to, and why each retired one may not.

    The ids are `pipeline.json`'s `agent_id` on every stage and the `agent_id` of every dispatch record of
    the controller. A dispatch the controller marked `superseded` (a retry replaced it) or released by a
    person's word is history: its agent is not a context to return to, and it is dropped from `known`
    whichever source named it - unless a resumable record carries the same agent too (a status says nothing
    about another record of the same agent). Every other record counts, by its status alone (a record with
    no stage or role included; `stale` and `blocked` stay resumable: a stale critic is re-reviewed after
    rework). `retired` maps the dropped agent to the fact the refusal prints.

    One more agent is retired (HF8-15 (2)): one that `_closed_only` calls closed - every record it rides is `accepted`,
    one of them on a stage whose `rework_mode` is `resume`, and no record of that role waits for a binding. ERROR
    DIRECTION: this function used to forbid nothing the controller allowed; it now forbids a real move, so every
    doubt (a record that is no object, no status, no role, a table that does not read) leaves the agent known.

    Not complete in the world BEFORE CX1-13 (records carry `agent_id` rarely) and for an id only
    `pipeline.json` knows, with no record: such an id stays known, as on `main`."""
    stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), dict) else {}
    named = {str((v or {}).get("agent_id") or "") for v in stages.values() if isinstance(v, dict)}
    records = controller.get("dispatches") if isinstance(controller.get("dispatches"), dict) else {}
    live, retired, carrying = set(), {}, {}
    for key, record in records.items():
        agent = str(record.get("agent_id") or "") if isinstance(record, dict) else ""
        if not agent:
            continue
        carrying.setdefault(agent, []).append(key)
        if record.get("status") in UNRESUMABLE:
            retired.setdefault(agent, f"dispatch {record.get('id') or key} is {record['status']}")
        else:
            live.add(agent)
    known = (named | live) - {""}
    # HF8-15 (2): an author whose work is ALL accepted, on a stage that resumes its role, is closed work - the
    # controller takes it back (`rework`, `finish --needs-author`), a message does not. Retired like a superseded one,
    # but only by `_closed_only`'s three conditions; every doubt there leaves the agent known (the old answer).
    closed = {}
    for agent in sorted(live):
        shown = _closed_only(records, carrying.get(agent, []))
        if shown:
            closed[agent] = f"dispatch {shown} {_CLOSED_FACT}"
    kept = {a for a in known if (a in live or a not in retired) and a not in closed}
    return kept, {**{a: fact for a, fact in retired.items() if a not in live}, **closed}


def _vouched(event: dict, ticket: str, targets: list, controller: dict) -> tuple:
    """`(vouched, why)` for a Codex resume: the targets this story's receipts vouch for, and the fact for each
    target a receipt of THIS story refuses to vouch for.

    A target is vouched for only when ALL the receipts that answer to it name exactly this story
    (`_recipient_receipts`: the exact receipt alone, else every name match) and EVERY one of their
    dispatches is a resumable record of this story's controller (I-2, M-3): one receipt of another story,
    one retired dispatch, one dispatch with no record here vetoes the name - it is not dropped from the
    count. A receipt that names no story is no evidence and no veto. Why per target: the first vetoing
    dispatch, in the words of the refusal."""
    records = controller.get("dispatches") if isinstance(controller.get("dispatches"), dict) else {}
    vouched, why = set(), {}
    root = artifact_root(event)
    for target in targets:
        pairs = _recipient_receipts(event, root, target)
        if not pairs or {story for story, _ in pairs} != {ticket}:
            continue
        for _, dispatch in pairs:
            record = records.get(dispatch)
            if not isinstance(record, dict):
                why[target] = f"dispatch {dispatch} has no record in this story"
            elif record.get("status") in UNRESUMABLE:
                why[target] = f"dispatch {dispatch} is {record['status']}"
            if target in why:
                break
        else:
            # HF8-15 (2): a receipt does not vouch for a closed author either (the same `_closed_only` as `_resumable_agents`)
            shown = _closed_only(records, _closed_keys(records, target, [dispatch for _, dispatch in pairs]))
            if shown:
                why[target] = f"dispatch {shown} {_CLOSED_FACT}"
            else:
                vouched.add(target)
    return vouched, why


def _probe_refusal_tail(probe, event) -> str:
    """What the context-diagnostic refusal adds after its fixed door: which condition of the probe failed (RH2-5).
    Session ids are never printed. It never raises and never judges (a raise would be exit 1, which is not a block):
    what it cannot establish it says so, it does not guess a reason."""
    unknown = " The reason is not established."
    try:
        if not isinstance(probe, dict):
            return " The probe could not be read, so the reason is not established."
        from host_probe import unmet_text
        sid, recorded = event.get("session_id"), probe.get("session_id")
        tail = ""
        if probe.get("status") != "verified":
            tail = unmet_text(probe.get("missing")) or unknown
        elif not sid:
            return " This dispatch carries no session id, so it cannot be matched to the probe (owner: factory)."
        if sid and isinstance(recorded, str) and recorded and recorded != sid:
            tail += " The probe on record belongs to another host session: run the pair in this session."
        return tail or unknown
    except Exception:  # noqa: BLE001 - see the docstring
        return unknown


# HF8-15 (2): the fact a closed author's refusal prints, and the rule that makes an agent closed.
_CLOSED_FACT = "is accepted; closed work goes back through the controller"
_PENDING_BIND = ("running", "blocked", "paused", RETURNED_UNACCEPTED)   # a record in one of these with no agent_id waits for a bind
_CRITIC_ROLE, _CRITIC_STAGE = "qa-code-critic", "S5"   # story_step.DEBT_ROLE / DEBT_STAGE; pinned equal by test_resume_closed_author


def _rework_resumes(stage) -> bool:
    """Does a rework of `stage` resume its role (`rework_mode: resume`)? Read from `references/stages.json` through the
    ONE reader, `contract.rework_mode` (AR-13, AR-1: data, not a list here). Any failure of the read is `False`: not closed."""
    try:
        import contract
        return isinstance(stage, str) and contract.rework_mode(stage) == "resume"
    except Exception:
        return False


def _closed_keys(records: dict, agent: str, extra=()) -> list:
    """The record keys an agent rides: the records whose `agent_id` is it, plus `extra` (a receipt's dispatches)."""
    keys = [key for key, record in records.items() if isinstance(record, dict) and str(record.get("agent_id") or "") == agent]
    return keys + [key for key in extra if key not in keys]


def _closed_only(records: dict, keys) -> str:
    """The dispatch id the refusal names when the agent riding `keys` is CLOSED work, else "" (HF8-15 (2)). Closed means ALL:
    - every record it rides is an object with status `accepted`;
    - at least one is on a stage whose `rework_mode` is `resume` (`_rework_resumes`; a `fresh` stage is not closed here, F-H2 b);
    - no record of that role waits for a binding (`running`, `blocked`, `paused`, `returned_unaccepted` with no `agent_id`):
      a rework the controller started and nobody bound yet is where a `bind` or today's pass leads.
    INVARIANT of the error direction: the answer "closed" locks a role out of a message, so a record that is not an object, has no
    status, no stage or no role, no keys at all, and any exception are all "" (not closed): an unknown never refuses (E5)."""
    try:
        rows = [(key, records.get(key)) for key in keys]
        if not rows or any(not isinstance(record, dict) or record.get("status") != "accepted" for _, record in rows):
            return ""
        resuming = [(key, record) for key, record in rows if _rework_resumes(record.get("stage"))]
        roles = {record.get("role") for _, record in resuming}
        if not resuming or any(not isinstance(role, str) or not role for role in roles):
            return ""
        if any(isinstance(record, dict) and record.get("role") in roles and record.get("status") in _PENDING_BIND
               and not str(record.get("agent_id") or "").strip() for record in records.values()):
            return ""
        key, record = resuming[0]
        return str(record.get("id") or key)
    except Exception:
        return ""


def _closed_author_door(event: dict, ticket: str, target: str, controller: dict) -> str:
    """The sentence a refusal prints for a CLOSED author (`_closed_only`), or "" when `target` is not one. A door that would not
    open is never named (FR-2): while a `qa-code-critic` of S5 is `running` the way back is the critic's own
    `finish --needs-author` (the controller refuses `rework` beside a running dispatch); otherwise `rework`, whose card
    then goes to this agent. Called on the refusal path only, inside the caller's `try`."""
    records = controller.get("dispatches") if isinstance(controller.get("dispatches"), dict) else {}
    extra = [dispatch for story, dispatch in _recipient_receipts(event, artifact_root(event), target) if story == ticket]
    keys = _closed_keys(records, target, extra)
    if not _closed_only(records, keys):
        return ""
    head = "A closed dispatch does not take more work by message. Send it back through the controller: "
    critics = [str(key) for key, record in records.items() if isinstance(record, dict) and record.get("role") == _CRITIC_ROLE
               and record.get("stage") == _CRITIC_STAGE and record.get("status") == "running"]
    if critics:
        who = critics[0] if len(critics) == 1 else "<one of: " + ", ".join(critics) + ">"
        return head + (f"`story_step.py finish --task {ticket} --dispatch-id {who} --needs-author <cases> "
                       "--reason \"<words>\"`.")
    record = next(r for r in (records.get(key) for key in keys) if isinstance(r, dict) and _rework_resumes(r.get("stage")))
    return head + (f"`controller.py --task-root <T> --operation rework --stage {record['stage']} --role {record['role']} "
                   "--cases <ids> --reason \"<words>\" --brief`, then its card goes to this agent.")


_SETTLED_BESIDE_STOP = ("accepted", "superseded", "released_by_person")   # the other records of a stopped agent that leave it stopped


def _stopped_target(event: dict, ticket: str, target: str, controller: dict, get_ctl) -> tuple:
    """`(dispatch id, has_agent, status)` when `target` is STOPPED and `resume` would open, else `("", False, "")` (SC2-17).

    Stopped: of the records the agent rides (`_closed_keys`, plus this story's receipts for it, both hosts) EXACTLY ONE is
    `blocked`/`paused` and every other is `accepted`/`superseded`/`released_by_person`; any other status, or a record that is not an
    object, means the agent may be doing other work or it is unclear: not stopped. The door must open: the controller's own
    `_resume_problems` judges the request the printed door would build (AR-15, not a copy of its conditions). ERROR DIRECTION: a
    DENY is only ever given with a door that works, so every doubt (a build that raises, a refused request) is "not stopped" = ALLOW.
    `get_ctl` returns the Controller, called ONLY at the first stopped candidate (F-S3C-1b: a message to a settled agent never pays
    the controller import); a raise from it is the caller's (ALLOW). Reading the controller writes nothing."""
    records = controller.get("dispatches") if isinstance(controller.get("dispatches"), dict) else {}
    extra = [dispatch for story, dispatch in _recipient_receipts(event, artifact_root(event), target) if story == ticket]
    rows = [(key, records.get(key)) for key in _closed_keys(records, target, extra)]
    if not rows or any(not isinstance(rec, dict) for _, rec in rows):
        return "", False, ""
    stopped = [(key, rec) for key, rec in rows if rec.get("status") in RESUMABLE_STOPPED]
    if len(stopped) != 1 or any(rec.get("status") not in _SETTLED_BESIDE_STOP + RESUMABLE_STOPPED for _, rec in rows):
        return "", False, ""
    key, rec = stopped[0]
    ident = str(rec.get("id") or key)
    held = isinstance(rec.get("agent_id"), str) and bool(rec["agent_id"].strip())
    ctl = get_ctl()
    request = ctl.build_resume_request(ident, None if held else target)
    if ctl._resume_problems(request, ctl.state()):
        return "", False, ""
    return ident, held, str(rec["status"])


def _stopped_refusal(event: dict, ticket: str, targets: list, controller: dict) -> str:
    """The refusal text for the targets `_stopped_target` calls stopped, each as its own sentence, or "" when none is. Raises are the
    caller's: `check_resume` calls this in a `try` before `deny` and reads a raise as today's ALLOW."""
    built = []

    def get_ctl():
        if not built:
            from controller import Controller
            built.append(Controller(artifacts_dir(ticket, event)))
        return built[0]

    parts = []
    for target in targets:
        ident, held, status = _stopped_target(event, ticket, target, controller, get_ctl)
        if not ident:
            continue
        door = get_ctl()._resume_door(ident) + ("" if held else f" --agent-id {target}")
        parts.append(f"{ticket}: resuming '{target}' is blocked - dispatch {ident} is {status}, stopped for a person, and the "
                     f"controller does not know it goes on. Run `{door}` first (the same agent goes on; `finish` then accepts "
                     "it), then send again.")
    return " ".join(parts)


def _closed_doors(event: dict, ticket: str, unrecorded: list, controller: dict) -> dict:
    """`{target: sentence}` for the unrecorded targets that are closed authors; one refusal never launders a neighbour (E9)."""
    found = {}
    for target in unrecorded:
        sentence = _closed_author_door(event, ticket, target, controller)
        if sentence:
            found[target] = sentence
    return found


def _closed_text(doors: dict, unrecorded: list) -> str:
    """The doors as one text: the bare sentence when the refusal names one target, each prefixed by its name when it names
    several (the command belongs to the closed one, never to a neighbour)."""
    if len(unrecorded) == 1:
        return next(iter(doors.values()))
    return " ".join(f"{target}: {sentence}" for target, sentence in doors.items())


def check_dispatch(event: dict) -> int:
    model = stage_model()
    from native_context import diagnostic
    if diagnostic(event):
        # Doctor has no story: never infer one from existing pipeline files. Only
        # a bounded context probe may bypass story ordering, not normal work.
        from hooklib import project_root
        from host_probe import inspect as inspect_probe
        ti = event.get("tool_input") or {}
        raw = (event.get("_qa_host") or {}).get("input") or ti
        if (requested_role(event, model) != "qa-scout"
                or any(source.get(key) for source in (event, ti, raw) for key in ("task_id", "task"))):
            return deny("context diagnostic requires qa-scout without a task_id")
        probe = None
        try:
            probe = inspect_probe(project_root(event))
            ready = (probe.get("status") == "verified" and bool(event.get("session_id"))
                     and probe.get("session_id") == event.get("session_id"))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            ready = False
        if not ready:
            # The literal stays the FIRST operand: refusal_registry (A24) reads the first argument of `deny` as the
            # refusal's text (`SG-probe-evidence`). The tail only says which condition failed; it never decides `ready`.
            return deny("context diagnostic requires current allow/deny evidence in this host session; "
                        "run host_probe.py --prepare, its two native commands, then --check"
                        + _probe_refusal_tail(probe, event))
        return ALLOW  # Injection verification is the result of this dispatch, not its prerequisite.
    if not model.get("stages"):
        return ALLOW
    role = requested_role(event, model)
    stage = stage_of_role(model, role)
    if stage is None:
        return ALLOW  # not a factory role — the roster guard in inject_context says the same
    ticket, facts = resolve_ticket(event)
    if not ticket:
        verdict = _check_exploration(event, facts, role)   # an exploration is judged by its own identity, never by a story's rules (XT1-2)
        if verdict is not None:
            return verdict
        if facts.get("explicit"):
            # A different refusal, and a different repair: the person DID name the story.
            # Telling them to "pass the explicit task_id" they had just passed is what sent
            # TP2-2556 through two reinstalls (I-90).
            return deny("the explicit task id names no story under this artifact root — the id "
                        "is not the repair; either the hook and the orchestrator resolved "
                        "different project roots, or the story was never initialized here."
                        + identity_facts(facts))
        if any((artifact_root(event)).glob("*/pipeline.json")):
            return deny("task identity is missing or ambiguous; name the story with task_id on "
                        "the dispatch, or with QA_FACTORY_TASK=<TICKET> in the environment on a "
                        "host whose dispatch arguments cannot carry one."
                        + identity_facts(facts))
        # An advice to the ORCHESTRATOR that made the call (RH1-5): stderr at exit 0 reached nobody. Said only in a
        # project that is onboarded (`qa-factory/config.json`): in any other repository the guard has no business.
        if hooklib.config_path(event).is_file():
            hooklib.notice(event, f"STAGE GUARD: no pipeline.json found - {role} dispatched without stage checks "
                                  "(this repository is not running a qa-story)", reader="orchestrator")
        return ALLOW
    pipeline = read_json(artifacts_dir(ticket, event) / "pipeline.json")
    if not pipeline:
        return deny(f"{ticket}: unreadable pipeline; recover task state before dispatch")

    # A role on several stages is placed by its live dispatch, AFTER the foreign-role allow and the pipeline read above (X2-2b):
    # a role on one stage meets no new branch, and "not established" is a refusal with a door, never the home stage by default.
    on_stages = stages_of_role(model, role)
    controller = read_json(artifacts_dir(ticket, event) / "state" / "controller.json") \
        if len(on_stages) > 1 or role in optional_roles(model) else None
    # An OPTIONAL dispatch (t-2277 FL-5) is placed on the stage whose `optional_dispatches` row its registered dispatch matches, so the
    # first look is judged by S3's order rules (S2 done, no gate before it), not by S6's. INVARIANT: only a role with a registered RUNNING
    # dispatch of the row's purpose gets this stage; a qa-runner with none is placed exactly as before (S6's rules refuse it before S5).
    optional = optional_stage_of_dispatch(model, role, (controller or {}).get("dispatches"))
    if optional is not None:
        stage = optional[0]
    elif len(on_stages) > 1:
        placed = stage_of_dispatch(model, role, dispatches=(controller or {}).get("dispatches"))
        if placed is None:
            names = ", ".join(str(st.get("id")) for st in on_stages)
            return deny(f"{role} is a role of {names} and no running dispatch of it names the stage: register it with "
                        f"`story_step.py start --task {ticket} --stage <stage> --role {role}`, then dispatch again.")
        stage = placed

    LAST_DENIAL.update({"ticket": ticket, "stage": stage["id"], "role": role})
    # EVERY refusal of the order and gate A rules and (S6-S8) of the manifest rule - each already passed through a
    # person's recorded word (`dispatch_errors`) - as `explain` lists them: a dispatch refused for two reasons used to
    # name the first, and the second came back one round later. The combined form with the head on a line of its own
    # (`DV.compound`, the form the controller raises): a router that reads the refusal gives each reason its own part,
    # whatever the length of the list, and one reason is the same sentence as before. The route and delivery rules
    # below stay behind this refusal (F-7).
    blocking = dispatch_errors(pipeline, stage["id"], model=model, ticket=ticket, event=event, role=role)
    if blocking:
        return deny(DV.compound(blocking, prefix=f"{ticket}:"))

    route = rule_tracker_route(ticket, role, stage["id"], pipeline, event)
    if route:
        return deny(f"{ticket}: {route}")

    # Rule 4 for a role (t-1547, GB-2): the executor of a gate's order is opened by that gate's RECORDED decision, not by the
    # delivery verdict. POSITION: after rules 1-3 and the tracker route have spoken, so a role outside `gate_orders` is
    # untouched and a gate-ordered role never gets past order, gate A or the manifest by way of its own gate.
    gate = gate_of_executor(role, model)
    if gate:
        message = rule_gate_ordered(pipeline, ticket, role, gate, artifacts_dir(ticket, event))
        if message:
            return deny(f"{ticket}: {message}")
    return ALLOW


# --- what a command is: the shapes the guard cares about --------------------------------------------
#
# The shell's own reader is B-404's, one walker for the four command readers (`hooklib.walk`, CX1-20: its quoting
# rules for both dialects, every `$( )` / backtick / group region flat and masked, the shell table of
# launch-causes.json); a second tokenizer or a region search here would be a second copy of one grammar. The other
# three names are still taken from hooklib by their own spelling, once, here (queued: they have no public name yet).
_walk = hooklib.walk
_program_name = functools.lru_cache(maxsize=4096)(hooklib._name)   # the same few program words recur in a long command
_STRIP_TABLE = hooklib._STRIP_TABLE


_KEYED_ARGUMENT = re.compile(r"[\w.\-]+=")


def _payload_text(word: str) -> str:
    """The command a quoted argument may carry: `alias.x=!gh pr create` (git -c) and `CMD=gh pr create` hold it after
    the `=` (and a `!`); any other argument is read as it stands."""
    return _KEYED_ARGUMENT.match(word) and word.split("=", 1)[1].lstrip("!") or word


def _gated_forms(text: str, forms: list) -> list:
    """The delivery forms whose words `text` could hold (`adapter_forms.could_be_in`: every word of a form occurs in
    the text with the quote and escape characters taken out, OR in the text as written; a text with a `$(` or a backtick
    is admitted whole - a substitution may build a word - and with any mark the program word may be absent). A payload
    that cannot hold a form's words is not read further, which keeps the cost linear."""
    squeezed, raw = text.lower().translate(_STRIP_TABLE), text.lower()
    return [(form, source) for form, source in forms if AF.could_be_in(form, squeezed, raw)]


def _delivery_in_text(text: str, dialect: str, forms: list):
    """(form, source) of the first delivery command RUN by `text`, read in one shell dialect, or None.

    The walker (`hooklib.walk`, one for R1-R4) hands over every command the shell would read - the text's own, each
    `$( )`, backtick, `<( )` and PowerShell group/block region at any depth - and this reader's payload rule opens the
    rest: a command is run when its words stand in one shell segment (quoted runs are single tokens, so a command named
    inside one quoted argument of a MENTION command - echo, grep, git commit: the table's `vcs.mention_commands` - is
    text); the quoted arguments of every other command (`bash -c`, `eval`, `ssh host "..."`, `python -c "..."`,
    `git -c alias.x='!...'`) are commands again, read one hop down in the dialect of the shell before them, and a `$var`
    or a word with a substitution in program position may be the program. `echo gh pr create` with the words bare is
    read as a delivery: the gate errs toward refusing, and a refusal has its doors (a person's word,
    `deliver_with_risks`). Every character of a text is read once, so the cost is linear."""
    found: list = []
    shells = hooklib.run_forms()["shells"]
    said, heads = AF.mention_commands(), AF.list_heads()

    def hops(tokens: list, reading: str) -> list:
        if found:
            return []
        # CX2-27 Rule H: the head decides whether pure substitutions (`echo $(a) $(b)`, `$a $(f) $(g)`, `for f in $(a) $(b)`)
        # are arguments to the shell; a form word written anywhere in the segment still refuses (see `segment_matches`)
        script = script_run(tokens)   # OH3-22: a launch of a .py file reads its quoted arguments as text, like a mention command
        released = script or AF.releases(tokens, _program_name, said, heads, hooklib.is_wild)
        fits = [(form, source) for form, source in forms
                if AF.segment_matches(form, tokens, _program_name, hooklib.cleaned_word, hooklib.is_wild, released=released)]
        if fits:
            # the refusal names what the ROLE wrote, not the first form a substitution fits (Q-5, FR-1): a form whose
            # program is written in the segment comes first, and the substitution's slot is shown as an ellipsis
            form, source = next((fit for fit in fits if AF.program_written(fit[0], tokens, _program_name, hooklib.cleaned_word)),
                                fits[0])
            found.append((AF.written_form(form, tokens, _program_name, hooklib.cleaned_word), source))
            return []
        if script or AF.mention_command(tokens, _program_name, said):
            return []   # echo, grep, git commit, a script run: its quoted arguments are text
        out = []
        for word, quoted in tokens:   # a shell in the segment sets the dialect of the quoted arguments after it
            shell = shells.get(_program_name(word))
            if shell is not None:
                reading = shell[1]
            elif quoted:
                payload = _payload_text(word)
                if payload.strip() and _gated_forms(payload, forms):
                    out.append((payload, reading))
        return out

    _walk(text, dialect, hops)
    return found[0] if found else None


# --- OH3-22: what a command only CARRIES is text to the gate -----------------------------------------------------------------
#
# `cat > answers.txt <<'EOF'` / `ok, gh pr create later` / `EOF` stores a line; the gate read it as a delivery and refused 7
# commands of one S5 window. `hooklib.scan_bodies` finds the bodies (the ONE scan, shared with the advice reader of
# guard_pre_tool); THIS is the gate's decision on them, and it is stricter on purpose. The advice reader may be wrong about
# "text" and cost a mention a refusal; here a wrong "text" PASSES A DELIVERY. So the error direction is fixed: a body stays
# executable (an extra refusal, with its door) unless every condition below holds, and what it cannot establish keeps it.
#   G0 the operator's LINE is plain (no ban member, backtick, `$'`, `$"`, pipe; every quote and `$(` closes on it)
#   G1 the operator is code in the dialect's reading: in a span of the top unit, in no comment, in no `$( )` region
#   G2 the body is closed (a closer line was found)         G6 an unquoted delimiter's body holds no `$(`, `${`, backtick
#   G3 the receiver of the operator's segment is a text receiver (a mention command, `vcs.text_receivers`, a script run)
#   G4 every pipe target of the text is a text receiver     G5 no `>(` in the text
# A PowerShell here-string must also meet: no shell program (`iex`, `eval`, `sh`) anywhere in the text, and a body with no
# character that closes the bash quote, so `@'` / `it's` / `gh pr create` / `'@` (a command to bash) stays refused.
# Each record is judged on the text with the bodies already taken out (an apostrophe in an earlier body never flips the quote
# state of a later one); the set is settled by rounds, and a set that does not settle takes nothing out.
MAX_BODY_ROUNDS = 12


def script_run(tokens: list) -> bool:
    """Does this segment launch a script FILE: a python launcher (`launch-causes.json` launchers whose subcommand is `-m`,
    with a version tail) or a `vcs.script_runners` word, then only `vcs.script_plain_flags`, then a word that is no option,
    no `-`, no substitution and no bare `$var`, whose last path component ends in `.py`; and no word of the segment is a
    shell? A script can deliver with no words on the command line, and the guard reads no script file, so its arguments add
    no hole that is not already there; `python -c`, `python -`, `python /dev/stdin`, `python $S` read their program from
    somewhere else and are no script run (a body they receive stays executable). Accepted, not defended: `python w.py ssh
    host "gh pr create"`. An empty table gives no script run."""
    head = AF.head_at(tokens)
    if head is None:
        return False
    forms = hooklib.run_forms()
    program = AF.head_program(tokens[head][0], _program_name)
    launcher, subs = hooklib._launcher_subs(program, forms["launchers"])
    if not (program in AF.script_runners() or (launcher and subs == {"-m"})):
        return False
    if any(_program_name(word) in forms["shells"] for word, _quoted in tokens):
        return False
    flags = AF.script_plain_flags()
    for word, quoted in tokens[head + 1:]:
        if not quoted and word in flags:
            continue
        bare_variable = re.fullmatch(r"\$\{?\w+\}?", word) is not None
        return (not word.startswith("-") and not hooklib.is_wild(word) and not bare_variable
                and re.split(r"[\\/]", word)[-1].lower().endswith(".py"))
    return False


def _text_receiver(tokens: list) -> bool:
    """Does this segment only STORE or count what it is handed on stdin: a mention command (`vcs.mention_commands`), a
    `vcs.text_receivers` word, or a script run? The head is read from the walker's tokens, never from the text before the
    operator (`bash "a;b" <<'E'` has a quoted separator and a head `bash`)."""
    head = AF.head_at(tokens)
    if head is None:
        return False
    word, quoted = tokens[head]
    return (AF.mention_command(tokens, _program_name, AF.mention_commands()) or script_run(tokens)
            or (not quoted and not hooklib.is_wild(word) and AF.head_program(word, _program_name) in AF.text_receivers()))


_NOT_PLAIN_MARKS = ("`", "$'", '$"', "${", "$[", "((")   # the shell reads these in ways the scan does not: a quote the scan
# closes and the shell keeps open (`$'a\'`, `${x:-"`), arithmetic where `<<` is a shift (`$[1<<E]`, `${x:1<<E}`, `((1<<E))`)


def _quote_states(mine: str, points: list) -> list:
    """For each offset of `points` (ascending): is every quote and `$(` that `mine` opens before it closed before it (the
    scan's own reading of quotes, a backslash skipping the next character outside single quotes)? One pass, so a text with
    many operators costs linear time."""
    opened: list = []   # the quotes and `$(` open at this point, innermost last
    out, i = [], 0
    for point in points:
        while i < point and i < len(mine):
            char, inside = mine[i], (opened[-1] if opened else "")
            if inside == "'":
                if char == "'":
                    opened.pop()
            elif char == chr(92):
                i += 1
            elif inside == '"' and char == '"':
                opened.pop()
            elif char == '"' or (char == "'" and inside != '"'):
                opened.append(char)
            elif mine.startswith("$(", i):
                opened.append("$(")
                i += 1
            elif char == ")" and inside == "$(":
                opened.pop()
            i += 1
        out.append(not opened)
    return out


def _quotes_close(mine: str) -> bool:
    """Does every quote and `$(` that `mine` opens close inside it?"""
    return _quote_states(mine, [len(mine)])[0]


_UNPLAIN_RE = re.compile("(?:" + hooklib.SHELL_OPAQUE_BAN.pattern + ")|" + "|".join(re.escape(mark) for mark in _NOT_PLAIN_MARKS))


def _line_is_plain(src: str, record) -> bool:
    """G0: the operator's own line is read exactly as the scan reads it. It holds no member of `SHELL_OPAQUE_BAN` (its line
    feed counts, so a trailing backslash is a continuation and fails), none of `_NOT_PLAIN_MARKS`, no pipe, no backslash
    right before the operator (`\\<<E` is a literal `<` and a redirect: nothing opens a body), and every quote and `$(` it
    opens closes on it (a here-string's own opener is not counted)."""
    start = src.rfind("\n", 0, record.op_at) + 1
    end = src.find("\n", record.op_at)
    line = src[start:end + 1 if end >= 0 else len(src)]
    if (hooklib.SHELL_OPAQUE_BAN.search(line) or "|" in line or any(mark in line for mark in _NOT_PLAIN_MARKS)
            or (record.op_at > start and src[record.op_at - 1] == chr(92))):
        return False
    return _quotes_close(src[start:record.op_at] if record.kind == "ps_herestring" else line)


def _before_is_plain(text: str, offsets: list) -> list:
    """G0 on EVERYTHING kept before each operator offset (`text` has the bodies already taken out; one answer per offset,
    ascending): an earlier line can leave the shell inside a string the scan reads as closed, and the body then closes it, so
    the rest of the "body" runs (`echo $'a\\'` / `cat <<E` / `'; gh pr create` / `E`). Same conditions as the operator's
    line (no ban member, none of `_NOT_PLAIN_MARKS`, every quote closed), over all the text before the operator; one pass."""
    first = _UNPLAIN_RE.search(text)
    clean_to = first.end() if first else len(text) + 1   # a member ending at or before an offset is in the text before it
    return [offset < clean_to and closed for offset, closed in zip(offsets, _quote_states(text, offsets))]


def _blank_before(src: str, at: int) -> bool:
    """Is `at` the start of a line or right after a blank or tab? PowerShell 5.1 reads `<<` as a parser error only then
    (M-1); glued to a word (`cat > n.txt<<'E'`) it is a plain token and the next line RUNS (OH3-22 round 2, measured)."""
    return at == 0 or src[at - 1] in " \t\n"


def _body_is_plain(src: str, record) -> bool:
    """G2, G6 and the here-string rule on the record's own text: a closed body whose delimiter, quoting and characters leave
    the shell nothing to expand or to close a quote with."""
    body = hooklib.body_of(src, record)
    if not record.closed or not _line_is_plain(src, record):
        return False
    if record.kind == "herestring":
        return not hooklib.EXPANSION_RE.search(body)
    if record.kind == "heredoc":
        # an unquoted delimiter: bash joins a line that ends in a backslash with the next, so `E\` + an empty line is the closer
        # and the scan's body runs past the real one (G6's sibling, F3b)
        return record.quoted_delimiter or not (hooklib.EXPANSION_RE.search(body) or re.search(r"\\\r?\n", body))
    # a PowerShell here-string: bash reads the same bytes, so no character that closes the quote the body sits in
    return not any(char in body for char in ("'" if record.quoted_delimiter else '"$`' + chr(92)))


def _stays_text(units: list, text: str) -> bool:
    """G5 and G4 on the whole kept text: `>(` anywhere, or a pipe target in any unit that is no text receiver (the first
    segment after a `|` or `|&`, blanks, line ends and comments skipped), keeps every body executable."""
    if ">(" in text:
        return False
    for unit in units:
        for at in range(len(unit.spans) - 1):
            gap = re.sub(r"#[^\n]*", "", unit.text[unit.spans[at][1]:unit.spans[at + 1][0]])   # a comment holds no pipe
            if "|" in gap and not _text_receiver(unit.segments[at + 1]):
                return False
    return True


def _holds_shell(units: list) -> bool:
    """Is a shell program (`run_forms.shells`: `sh`, `eval`, `iex`, ...) a word of any segment of the text?"""
    names = hooklib.run_forms()["shells"]
    return any(_program_name(word) in names for unit in units for tokens in unit.segments for word, _q in tokens)


def _code_in_receiver(top):
    """G1 and G3 as a test of one operator offset in the text's top unit: the offset is in a span and in no region, and the
    segment holding it is a text receiver (or, for a PowerShell here-string, `$name = ...`)."""
    starts, opens = [a for a, _b in top.spans], [a for a, _b in top.kids]

    def test(offset: int, assignment: bool) -> bool:
        at = bisect.bisect_right(starts, offset) - 1
        if at < 0 or offset > top.spans[at][1]:
            return False
        kid = bisect.bisect_right(opens, offset) - 1
        if kid >= 0 and offset < top.kids[kid][1]:
            return False
        tokens = top.segments[at]
        return _text_receiver(tokens) or (assignment and len(tokens) > 1 and tokens[1][0] == "="
                                          and re.fullmatch(r"\$\w+", tokens[0][0]) is not None)
    return test


@functools.lru_cache(maxsize=64)
def _taken_bodies(src: str, dialect: str, tables: tuple) -> tuple:
    """The records of `src` that come out of the gate's reading in `dialect` ("bash" or "powershell"); `tables` only keys the
    cache to the data in force. A heredoc and a `<<<` come out in PowerShell exactly when they came out in bash AND the `<<`
    stands at a line start or after a blank or tab (M-1: a `<<` so placed is a parser error there, so that script runs
    nothing; glued to a word it is a plain token and the next line RUNS); a PowerShell here-string is judged in each dialect."""
    judged = [record for record in hooklib.scan_bodies(src) if _body_is_plain(src, record)]
    stored: set = set()
    if dialect == "powershell":
        stored = {record.op_at for record in _taken_bodies(src, "bash", tables)}
        judged = [record for record in judged
                  if record.kind == "ps_herestring" or (record.op_at in stored and _blank_before(src, record.op_at))]
    for _round in range(MAX_BODY_ROUNDS):
        text, ops = hooklib.cut_bodies(src, judged)
        units = hooklib.walk(text, dialect)
        if not units:
            return ()
        whole, shell, test = _stays_text(units, text), _holds_shell(units), _code_in_receiver(units[0])
        keep = [record for record, offset, plain in zip(judged, ops, _before_is_plain(text, ops))
                if record.op_at in stored or (whole and plain and test(offset, record.kind == "ps_herestring")
                                              and not (shell and record.kind == "ps_herestring"))]
        if len(keep) == len(judged):
            return tuple(judged)
        judged = keep
    return ()   # the set did not settle: nothing comes out, the command is read raw


def _executable_text(command: str, dialect: str) -> str:
    """The command as the shell would RUN it in `dialect` ("bash" / "powershell"): the bodies the gate is sure the shell only
    stores are taken out (see the conditions above), everything else stays - a command with no body is itself. The one
    reader of "what is run, what is stored" for the delivery, commit and stash shapes and the typed-runner rule (AR-13)."""
    src = hooklib.argv_text(command)
    if "<<" not in src and "@" not in src:
        return src   # no operator of a body in it
    tables = (AF.text_receivers(), AF.script_runners(), AF.script_plain_flags(), AF.mention_commands(),
              id(hooklib.run_forms()))
    return hooklib.cut_bodies(src, list(_taken_bodies(src, dialect, tables)))[0]


def _delivery_match(command: str, cfg: dict | None = None):
    """(form, source) of the delivery command this command runs, or None. The forms are the table's and
    the project's (`adapter_forms.delivery_forms`; a damaged table gives the declared floor, never a pass).
    A cheap gate comes first (`_gated_forms`, `adapter_forms.could_be_in`) so an ordinary command never pays for
    tokenizing. BOTH shell dialects read the text, always (CX1-20: the host label decides nothing, and the dialects
    differ in more than the escapes - `<#`, `(`, `{`): either one finding a delivery is a delivery."""
    text = command or ""
    forms = _gated_forms(text, AF.delivery_forms(cfg, floor=True)) if text.strip() else []
    if not forms:
        return None
    for dialect in ("bash", "powershell"):
        # OH3-22: each dialect reads the command with the bodies it surely only stores taken out (`_executable_text`)
        run = _executable_text(text, dialect)
        found = _delivery_in_text(run, dialect, _gated_forms(run, forms) if run != text else forms)
        if found:
            return found
    return None


def _is_delivery_shape(command: str, cfg: dict | None = None) -> bool:
    return _delivery_match(command, cfg) is not None


def _shell_segments(text: str, dialect: str) -> list:
    """Every command segment RUN by `text`, as (word, came_from_a_quoted_run) tokens: the text's own and those of each
    `$( )`, backtick or group region at any depth (the walker hands them over flat, `hooklib.walk`); and, when a shell
    stands in a segment (`bash -c "..."`, `eval "..."`: the shells of launch-causes.json), those of its quoted
    arguments, read in that shell's dialect one hop down. The quoted arguments of any other command are TEXT - a
    delivery's `--body "git commit -m x tests/x.py"` is no commit - and so are those of a mention command (echo, grep,
    git commit)."""
    out: list = []
    shells = hooklib.run_forms()["shells"]
    said = AF.mention_commands()

    def hops(tokens: list, reading: str) -> list:
        out.append(tokens)
        if AF.mention_command(tokens, _program_name, said):
            return []
        payloads, in_shell = [], False
        for word, quoted in tokens:
            shell = shells.get(_program_name(word))
            if shell is not None:
                reading, in_shell = shell[1], True
            elif quoted and in_shell:
                payloads.append((_payload_text(word), reading))
        return payloads

    _walk(text, dialect, hops)
    return out


def _git_words(tokens: list) -> tuple:
    """("commit" | "add", the tokens after it) for a segment that runs `git commit ...` or `git add ...`, else
    ("", []). Like a delivery program, `git` may stand ANYWHERE in the segment, unquoted, behind a wrapper or a
    keyword (`sudo git commit`, `env X=1 git commit`, `time`, `nohup`, `command`, `exec`, `! git`, `{ git commit; }`,
    `then git commit`, `do git commit`): a commit that main caught must not pass because of what stands before it.
    The verb is the word right after `git`: `git -C dir commit` and `git -c x=1 commit` are not recognised, as
    before (E-A12). The words after the verb are the paths. A segment whose head is a mention command other than
    git (`echo git commit tests/x.py`) is text.

    A word with an unquoted substitution (`hooklib.is_wild`) fills in at run time, so it can be anything (CX1-20 B-1,
    NM-4): it may BE `git` (`$(echo git) commit ...`), a run of them may stand between `git` and the verb
    (`git $(true) commit ...`), and the last of such a run may BE the verb (`git $(echo commit) -m x tests/t.py`:
    a commit). The error direction is a commit shape; a commit shape names test files or the factory's paths
    besides, so `git $(true) status` is still no commit."""
    at_head = AF.head_at(tokens)
    if (at_head is None or AF.head_program(tokens[at_head][0], _program_name) != "git") and AF.mention_command(tokens, _program_name, AF.mention_commands()):
        return "", []
    for at, (word, quoted) in enumerate(tokens):
        if quoted or not (_program_name(word) == "git" or hooklib.is_wild(word)):
            continue
        after = at + 1
        while after < len(tokens) and not tokens[after][1] and hooklib.is_wild(tokens[after][0]):
            after += 1
        if after < len(tokens) and tokens[after][0] in ("commit", "add"):
            return tokens[after][0], tokens[after + 1:]
        if after > at + 1:
            return "commit", tokens[after:]
    return "", []


def _path_words(tokens: list, commit: bool) -> list:
    """The words of a `git commit` / `git add` segment that may be paths: no option, no empty or `.` word, and
    for a commit not the value of an option that takes one (`COMMIT_VALUE_OPTS`, the same reading as rule 5)."""
    paths, skip = [], False
    for word, _quoted in tokens:
        if skip:
            skip = False
        elif commit and word in COMMIT_VALUE_OPTS:
            skip = True
        elif not word.startswith("-") and word not in ("", "."):
            paths.append(word)
    return paths


def _names_test_or_factory(word: str, cfg: dict | None, event: dict | None) -> bool:
    """Does this path word name a factory path, or a test (the union: the project's word or the usual names)? A
    word the usual names cannot judge (the markers file is unreadable) counts: the guard errs toward checking."""
    if FACTORY_PATH_RE.search(word):
        return True
    import test_files
    return test_files.is_test_for("commit", word, cfg, base=(event or {}).get("cwd") or None,
                                  root=hooklib.project_root(event)) is not False


def _is_commit_shape(command: str, cfg: dict | None = None, event: dict | None = None) -> bool:
    """A real `git commit` that names test files or the factory's paths.

    The segments are cut by the one walker in BOTH shell dialects, whatever the tool's label says (CX1-20: a Codex host
    labels a PowerShell command `Bash`): a commit either reading sees is a commit, so a Windows path keeps its
    backslashes where PowerShell reads them and text inside another command's quoted argument is never a commit
    (E-A10). A commit segment is `git commit ...`; the paths are the words of the commit and of the `git add`
    segments of the same command (a bare `git commit` after `git add tests/x.py` is a commit of that test: E-A3).

    Positional invariant (E-A2): the config and the markers are read only after the `git commit` hint is found
    (`hooklib.hint_gate`: in the text, in its cleaned view, or a substitution mark in it - `git com$(true)mit`), so a
    command without it reads no file. An unterminated quote is not an error here: the tokenizer drops it and reads the
    tail as unquoted words, so the words after it are checked (such a command is a syntax error to either shell, and
    commits nothing)."""
    cmd = command or ""
    if not hooklib.hint_gate(cmd, COMMIT_HINTS, groups=True):
        return False
    committing, paths = False, []
    for dialect in ("bash", "powershell"):
        for tokens in _shell_segments(_executable_text(cmd, dialect), dialect):   # OH3-22: a stored body is no commit
            verb, rest = _git_words(tokens)
            if verb:
                committing = committing or verb == "commit"
                paths += _path_words(rest, verb == "commit")
    return committing and any(_names_test_or_factory(word, cfg, event) for word in paths)


def _is_stash_shape(command: str) -> bool:
    cmd = command or ""
    if not any(h in cmd for h in STASH_HINTS):
        return False
    run = _executable_text(cmd, "bash")   # OH3-22: `git stash` written into a file is no stash (the rules read the bash text)
    return any(h in run for h in STASH_HINTS) and _stash_saves(run)


def command_shapes(command: str, cfg: dict | None = None, event: dict | None = None) -> list:
    """Every shape this command has, in the order delivery, commit, stash; [] when it is none of the
    guard's business. A command can be several (`git commit -a -m x tests/t.py && gh pr create`), and every
    rule of every shape it has must run: a delivery form must never be the way past rules 5 and 7."""
    shapes = []
    if _is_delivery_shape(command, cfg):
        shapes.append("delivery")
    if _is_commit_shape(command, cfg, event):
        shapes.append("commit")
    if _is_stash_shape(command):
        shapes.append("stash")
    return shapes


def command_shape(command: str, cfg: dict | None = None, event: dict | None = None) -> str:
    """The first of `command_shapes`, '' when this command is none of the guard's business."""
    shapes = command_shapes(command, cfg, event)
    return shapes[0] if shapes else ""


def _stash_tokens(command: str) -> list:
    """The tokens of the `git stash` in this command."""
    idx = (command or "").find("git stash")
    if idx < 0:
        return []
    tail = command[idx + len("git stash"):]
    for sep in (" && ", " || ", ";", "\n", " | "):
        cut = tail.find(sep)
        if cut >= 0:
            tail = tail[:cut]
    try:
        import shlex
        return shlex.split(tail, posix=True)
    except Exception:
        return tail.split()


def _stash_saves(command: str) -> bool:
    """True for the stash subcommands that MOVE files out of the tree. `list`, `show`,
    `pop`, `apply`, `branch` and `drop` put things back or only look — they are not this
    rule's business, and blocking a `pop` would strand the human's work in the stash."""
    tokens = [t for t in _stash_tokens(command) if not t.startswith("-")]
    return not tokens or tokens[0] in ("push", "save")


def _commit_tokens(command: str) -> list:
    """The tokens of the `git commit` in this command, quotes resolved where possible."""
    idx = command.find("git commit")
    if idx < 0:
        return []
    tail = command[idx + len("git commit"):]
    for sep in (" && ", " || ", ";", "\n", " | "):
        cut = tail.find(sep)
        if cut >= 0:
            tail = tail[:cut]
    try:
        import shlex
        return shlex.split(tail, posix=True)
    except Exception:
        return tail.split()


def rule_pathspec(command: str) -> str:
    """Rule 5 — a factory commit names its own files, and takes nothing else.

    `git add <file>` was already the rule, and it was followed; what nobody had accounted
    for was an index that already held somebody else's work. On TP1-14501 the delivery
    commit swept in two scripts a teammate had staged before the session started, and the
    orchestrator only noticed because it read the output afterwards. A pathspec makes the
    commit independent of whatever is staged: `git commit -m "..." -- <paths>` commits
    those paths and nothing else."""
    tokens = _commit_tokens(command)
    if not tokens:
        return ""
    if any(t in COMMIT_ALL_OPTS for t in tokens):
        return ("this commit carries -a/--all, which takes every tracked change in the tree "
                "— including work that was already there when the story started. Name the "
                "files instead: git commit -m \"...\" -- <paths from the manifest/artifacts>")
    if "--" in tokens:
        return ""
    paths, skip = [], False
    for token in tokens:
        if skip:
            skip = False
            continue
        if token in COMMIT_VALUE_OPTS:
            skip = True
            continue
        if token.startswith("-"):
            continue
        paths.append(token)
    if paths:
        return ""
    return ("this commit names no files, so it takes whatever the index happens to hold — "
            "on TP1-14501 that was two scripts a teammate had staged before the story "
            "began. Name them: git commit -m \"...\" -- <paths>. Three commits, each by an "
            "explicit path allowlist (s8.md): test code, then the documents, then "
            "pipeline.json with the ledgers.")


def _names_factory(path: str) -> bool:
    p = str(path or "").strip().strip("'\"").rstrip("/\\")
    return bool(FACTORY_PATH_RE.search(p)) or p.endswith("qa-factory")


def _excludes_factory(token: str) -> bool:
    """git's exclude pathspec, in either spelling: `:(exclude)qa-factory` or `:!qa-factory`."""
    t = str(token or "").strip().strip("'\"")
    return t.startswith((":(exclude)", ":!", ":^")) and "qa-factory" in t


def rule_stash(command: str) -> str:
    """Rule 7 — a stash names what it takes, and never takes the factory's own state.

    S5 checks the working tree before cutting the story branch, and "stash" is one of the
    four answers a human may give. `git stash push -u` includes untracked files, and the
    running story's artifacts — pipeline.json, test-plan.md, the designed cases — are
    untracked: on TP2-2104 they went into the stash, and the inputs of every role
    after S5 disappeared with them. The orchestrator noticed and restored it; the next one
    might not, and a later restore can conflict.

    Two shapes pass: an explicit pathspec after `--` that does not name qa-factory, and an
    exclude pathspec. Everything else is refused with the command that does the same job
    safely."""
    if not _stash_saves(command):
        return ""
    tokens = _stash_tokens(command)
    if any(_excludes_factory(t) for t in tokens):
        return ""
    if "--" in tokens:
        paths = [t for t in tokens[tokens.index("--") + 1:] if not t.startswith(":")]
        if not paths:
            return ("this stash ends at `--` without naming a path, so it takes the whole "
                    "tree — the story's own artifacts included. Name the human's files.")
        if not any(_names_factory(p) for p in paths):
            return ""
        return ("this stash names qa-factory/ among its paths: that is the running story's "
                "own state (pipeline.json, the plan, the cases), and every role after S5 "
                "reads it. Stash the human's files only.")
    return ("this stash takes everything, and with -u that includes the running story's own "
            "untracked artifacts — pipeline.json, test-plan.md, test-cases/. On "
            "TP2-2104 the next role's inputs went into the stash with them. Name the "
            "paths you showed the human: git stash push -u -- <their paths>  (or, to sweep "
            "the rest of the tree, git stash push -u -- . ':(exclude)qa-factory')")


def _request_path(command: str) -> str:
    """Extract --request without evaluating shell syntax or substitutions."""
    try:
        import shlex
        tokens = shlex.split(command, posix=False)
    except ValueError:
        return ""
    for index, token in enumerate(tokens):
        clean = token.strip('"\'')
        if clean in {"--request", "--schedule"} and index + 1 < len(tokens):
            return tokens[index + 1].strip('"\'')
        if clean.startswith("--request=") or clean.startswith("--schedule="):
            return clean.split("=", 1)[1].strip('"\'')
    return ""


# `run_suite.py` flags that cannot start a test. `references/execution-lifecycle.md:71`
# prescribes `--reparse-block --mapping` as THE remedy for a missing reporter row, and this
# rule refused it because the allowlist held only --request/--schedule: 10 refusals over six
# windows on TP1-15045, `--help`, `--detail` and `--recover` among them, not one of which
# could have run a test. A rule that exists to stop untyped EXECUTION must let reading through.
NON_EXECUTING_FLAGS = ("--reparse-block", "--recover", "--detail", "--help", "-h",
                       "--selftest", "--template",
                       # `run_suite.py --task <T> --collect-only --tests ... -- <cmd>` lists tests and launches none: the door
                       # `check_witness` and `run_suite` name for a manifest whose every test is pending (t-2181 PC-4, B4)
                       "--collect-only")

# A command may MENTION the runner without launching it — `find / -name run_suite.py`,
# `grep -n report_test_id .../run_suite.py`. Five of those same ten refusals were roles
# LOOKING the runner up (three of them to find out which flags exist, because the refusal
# had just told them the interface had changed).
READER_COMMANDS = frozenset((
    "grep", "rg", "find", "ls", "cat", "head", "tail", "sed", "awk", "wc", "stat", "file",
    "less", "more", "type", "cp", "mv", "diff", "which", "dirname", "basename", "echo",
    "md5sum", "sha256sum", "select-string", "get-content", "get-childitem"))

# Shapes that create a file. Used only to tell "the request is about to be written by this
# very command" from "the path is wrong".
WRITER_HINTS = ("json.dump", "write_text", "writelines", ".write(", "open(", ">", "cp ",
                "mv ", "tee ", "Set-Content", "Out-File", "shutil.copy")

SAME_COMMAND_FIX = "write the request in one call, run it in the next"


class _Slice(NamedTuple):
    """One command of a command text as the typed-runner rule judges it: `raw` is the text behind it (its regions'
    bodies inside), `masked` the same with each region directly inside it replaced by the mask (a region is judged as
    its own slice), `tokens` its words, `region` whether it holds a region, `hint` whether it names the runner."""
    text: str
    a: int
    b: int
    masked: str
    tokens: list
    region: bool
    hint: bool

    @property
    def raw(self) -> str:
        """The text behind the slice, cut ON DEMAND: N nested regions hold N overlapping raw texts, so copying them all
        would cost N squared characters (CX1-20 I-LIN)."""
        return self.text[self.a:self.b]


def _hint_offsets(text: str) -> list:
    """Every (start, end) of a runner hint in `text`, sorted by start, found ONCE over the whole source (CX1-20 M-2):
    a slice asks `bisect` whether one lies inside it, so the hint costs one pass however many slices there are."""
    found = []
    for hint in RUNNER_HINTS:
        at = text.find(hint)
        while at != -1:
            found.append((at, at + len(hint)))
            at = text.find(hint, at + 1)
    return sorted(found)


def _names_runner(tokens: list, raw_hint: bool) -> bool:
    """Does this slice name the runner? Its raw text holds a hint (`raw_hint`), OR one WORD of it does once the word's
    substitutions, quotes and escapes are deleted (`hooklib.cleaned_word`: `run_sui$(true)te.py`, `run_sui\\te.py`) -
    the cleaned view looks for `run_suite.py` inside ONE word only, so a quoted mention of the name in a search
    (`git log --grep "run_suite"`) is no launch (CX1-20 NM-3)."""
    return raw_hint or any("run_suite.py" in hooklib.cleaned_word(word) for word, _quoted in tokens)


def _slices(command: str, dialect: str) -> tuple:
    """([_Slice of every command the shell reads in `command`], whether any bash slice borders a bare parenthesis),
    read in one shell dialect by `hooklib.walk` (no payloads: a `bash -c` argument is part of its slice).

    The walker hands over the text's own slices and each `$( )`, backtick and group region's, flat; so a `|` or `;`
    inside quotes is text and the guard keeps no second grammar and no search for substitutions of its own. A slice
    bordering a BARE `(` or `)` of bash is where the tokenizer cuts a word the shell keeps whole: its pieces are not
    commands of their own, and `rule_typed_runner` withdraws the reader exemption for that command. The border of a
    region itself (its own opener and closer) is no bare parenthesis."""
    text = str(command or "")
    offsets = _hint_offsets(text)
    starts = [start for start, _ in offsets]
    out, bare = [], False
    for unit in _walk(text, dialect):
        for (a, b, masked, region), tokens in zip(hooklib.masked_slices(unit), unit.segments):
            at = bisect.bisect_left(starts, a)   # the first hint that starts inside the slice: it fits or none does
            out.append(_Slice(text, a, b, masked, tokens, region,
                              _names_runner(tokens, at < len(offsets) and offsets[at][1] <= b)))
            if dialect == "bash":
                bare = bare or (a > unit.start and text[a - 1] in "()") or (b < unit.end and text[b] in "()")
    return out, bare


def _reader_head(masked: str) -> str:
    tokens = masked.strip().split()
    return Path(tokens[0].strip('"\'')).name.lower() if tokens else ""


def _is_reader(name: str) -> bool:
    return name.rstrip(".exe") in READER_COMMANDS or name in READER_COMMANDS


def _reader_launches(words: list) -> bool:
    """Does this READER-headed command (`words`, the program first) make the reader run another program (`find -exec`,
    `rg --pre`, awk `system(`, sed `e`: the one table `launch-causes.json` `reader_runs`, `hooklib.reader_runs`)? Not
    when the program it runs is a reader that itself runs nothing (`find ... -exec grep -n x {} +`); a program the
    command does not name, or a word with a substitution, counts as a launch."""
    found = hooklib.reader_runs(words)
    if found is None:
        return False
    program = found[1]
    if not program or hooklib.is_wild(program[0]):
        return True
    return not (_is_reader(_reader_head(program[0])) and not _reader_launches(program))


def _launches_runner(piece: _Slice, readers_exempt: bool = True) -> bool:
    """True only where this slice actually invokes run_suite.py. A reader-headed slice (`rg`, `cat` ...) only
    MENTIONS it - unless the reader runs a program (`_reader_launches`); `readers_exempt=False` withdraws that (a slice
    cut at a bare parenthesis may be the tail of a command whose real head the cut took away - `python -X (true)cat
    run_suite.py` - so any mention counts). The head is read on the MASKED slice: a substitution in program position
    (`$(echo python) run_suite.py`) is the mask, which is no reader."""
    if not piece.hint:
        return False
    if readers_exempt:
        if _is_reader(_reader_head(piece.masked)) and not _reader_launches([word for word, _quoted in piece.tokens]):
            return False
    return True


def _non_executing_flag(command: str) -> str:
    for flag in NON_EXECUTING_FLAGS:
        if re.search(r"(?<![\w-])" + re.escape(flag) + r"(?=[\s=]|$)", command):
            return flag
    return ""


def _writes_request(slices: list, path_text: str) -> bool:
    """True when THIS command creates the request file it then passes to `--request`.

    `slices` are the command's raw slices (`_slices`), whole: the launch is judged one slice at a time but
    the write may stand in an earlier one.

    A PreToolUse hook reads the path BEFORE the shell runs it, so a role that writes the
    request and launches the runner in one Bash call is refused with FileNotFoundError over
    a file that is perfectly correct — 11 times on TP1-15045, every role rediscovering
    it from scratch. Whether the file is about to exist is knowable: an earlier part of the
    same command names it, or writes JSON into its directory."""
    launch_at = next((i for i, s in enumerate(slices)
                      if any(h in s for h in RUNNER_HINTS) and _request_path(s)), len(slices))   # raw texts
    before = " ".join(slices[:launch_at])
    if not before.strip():
        return False
    name = Path(str(path_text).replace("\\", "/")).name
    if name and name in before:
        return True
    return ".json" in before and any(hint in before for hint in WRITER_HINTS)


# The two shapes one instance id is written in: the readable one a RunRequest carries, and
# the file-safe one an evidence path or a generated request may carry instead.
INSTANCE_SEPARATORS = ("::", "--")


def _contract_fn(name: str):
    """`contract` owns the definition of "one test"; resolve it lazily so a project on an
    older build keeps working and this guard keeps its own answer."""
    try:
        import contract
        return getattr(contract, name, None)
    except Exception:
        return None


def _instance_case(value: str) -> str:
    """The case an instance id belongs to, in either shape: `TC-012::test_fn[param]` and the
    file-safe `TC-012--test_fn--param`. Until `contract.instance_case` ships, the split at the
    separator is the same answer for every id the factory has written."""
    text = str(value or "")
    resolver = _contract_fn("instance_case")
    if resolver is not None:
        try:
            case = str(resolver(text) or "")
            if case:
                return case
        except Exception:
            pass
    for separator in INSTANCE_SEPARATORS:
        if separator in text:
            return text.split(separator, 1)[0]
    return ""


def _manifest_covers(ticket: str, event: dict) -> dict:
    """instance id (and its file-safe stem) -> the cases that instance covers.

    Since 0.7.7 an instance id carries no case at all, so the only thing that can say whether
    `test_validate[eu]` belongs to a dispatch scoped to TC-012 is the manifest's own `covers`.
    Unreadable manifest: an empty map, and the guard falls back to the id's own shape —
    never a refusal built on a file it could not read."""
    covers: dict = {}
    try:
        import contract
        manifest = json.loads(manifest_path(artifacts_dir(ticket, event)).read_text(encoding="utf-8"))
        for entry in contract.manifest_tests(manifest):
            cases = {str(c) for c in contract.manifest_test_links(entry)}
            if not cases:
                continue
            for alias in contract.instance_id_aliases(entry):
                covers.setdefault(alias, set()).update(cases)
                covers.setdefault(contract.instance_file_stem(alias), set()).update(cases)
    except Exception:
        return {}
    return covers


def _in_scope(instance, scope: set, covers: dict | None = None) -> bool:
    """`stage-scope` hands out CASE ids while a RunRequest names INSTANCES, so a scope of
    {TC-012} refused TC-012::test_validate_per_partition[missing-assistant] five times on
    TP1-15045, and the roles fell back to one request per case — which is how 13 of 15
    tests ended the story with no reporter row. An instance of a case in scope IS in scope,
    and so is the same instance written file-safely.

    An instance that COVERS a case of the scope is in scope too, whatever its own id spells:
    a consolidated test proving TC-003/004/005 is one request, not three."""
    text = str(instance or "")
    if text in scope:
        return True
    if (covers or {}).get(text, set()) & scope:
        return True
    case = _instance_case(text)
    if case and case in scope:
        return True
    stem = _contract_fn("instance_file_stem")
    if stem is not None:
        for entry in scope:
            try:
                if str(stem(entry)) == text:
                    return True
            except Exception:
                break
    # With no helper at all: the id starts with a case of the scope and then breaks off.
    return any(text.startswith(str(entry)) and len(text) > len(str(entry))
               and not text[len(str(entry))].isalnum() for entry in scope if entry)


# A name that is in the story but is not a running dispatch (closed, returned): its request names no live dispatch.
_NO_LIVE_DISPATCH = {"id": object(), "scope": []}


def _current_dispatch(dispatches, active: list):
    """The running dispatch a typed run request must name, or None = "decide by the request's own dispatch_id" (TR3-14,
    AR-13; error direction: never another window's dispatch). A session that carries its dispatch's name
    (`dispatch_identity.named`) is that dispatch when it is running; a name this story holds that is not running is a
    dispatch that cannot run tests (a stand-in no request id equals). No name, or a name this story does not hold: one active
    dispatch is the one (today's road); two or more are told apart by the request's id in `_judge_slice`."""
    import dispatch_identity
    name = dispatch_identity.named()
    if name:
        if dispatch_identity.held(dispatches, name):
            mine = dispatch_identity.own(dispatches)
            return mine if mine is not None else _NO_LIVE_DISPATCH
    return active[0] if len(active) == 1 else None


def rule_typed_runner(command: str, event: dict, ticket: str,
                      controller: dict | None = None, notes: list | None = None) -> str:
    """Factory-managed dispatches must use a request matching active identity and scope.

    `notes` collects what the guard lets through with a remark rather than a refusal: the
    caller prints them and returns ALLOW.

    The command is refused whole when it holds a form the tokenizer reads differently from the shell
    (`hooklib.SHELL_OPAQUE_BAN`), and otherwise judged one slice at a time (FB-25, FB-40): a reader-headed
    slice only mentions the runner and a non-executing flag frees only ITS slice, so a quoted `|` is text and
    `run_suite.py --template; run_suite.py` still launches. Both shell dialects cut the text and a refusal
    in either one is the answer - the guard runs under Windows PowerShell as often as under bash. The order is
    the invariant: no open dispatch, nothing is read or refused; then the ban on the WHOLE command, before any
    slice exemption can free a banned command."""
    if controller is None:
        controller = read_json(artifacts_dir(ticket, event) / "state" / "controller.json")
    dispatches = (controller or {}).get("dispatches") or {}
    active = [d for d in dispatches.values() if isinstance(d, dict) and d.get("status") == "running"]
    if not active:
        return ""  # standalone user invocation retains the legacy interface
    what, door = hooklib.shell_opaque_found(command)
    if what:
        return (f"the command holds {what}, which the shell reads differently from this guard, so the guard "
                "cannot tell where one command ends and the next begins and refuses the command whole. "
                f"Write it without that: {door}. Or launch the runner in its own form, one command with the "
                "path written out in full: `run_suite.py --request FILE`")
    current = _current_dispatch(dispatches, active)
    readings = []
    for dialect in ("bash", "powershell"):
        reading = _slices(command, dialect)
        if reading not in readings:
            readings.append(reading)
    for slices, bare in readings:
        for piece in slices:
            message = _judge_slice(piece, slices, bare, event, ticket, current, notes, active=active)
            if message:
                return message
    return ""


# The door of a runner launch whose arguments hold a substitution or a group (CX1-20, t-995 section 4 (4)): the guard
# cannot read what `$(...)` or `(Join-Path ...)` expands to, so it names what to write instead (FR-1, FR-2).
REGION_REFUSAL = ("an active factory dispatch may run tests only through `run_suite.py --request FILE` "
                  "or `run_suite.py --schedule FILE`; this launch of the runner has a substitution or a group in its "
                  "arguments (`$(...)`, a backtick pair, `(Join-Path ...)`), and the guard cannot read what it expands to. "
                  "Write the runner's path and its flags literally, for example `run_suite.py --request FILE`, with the "
                  "path in the command itself (build the path in a call before this one if you need to). "
                  f"Flags that launch nothing pass as they are: {', '.join(NON_EXECUTING_FLAGS[:4])}")
BARE_PAREN_NOTE = (". This command has parentheses around the runner's words, and the guard reads a command "
                   "cut at every parenthesis as a launch whatever its words are: expand `(Join-Path ...)` or "
                   "`$(...)` into a plain path and write the command without them")


def _judge_slice(piece: _Slice, slices: list, bare: bool, event: dict, ticket: str,
                 current: dict | None, notes: list | None, *, active: list | None = None) -> str:
    """The typed-runner verdict on ONE slice of a command ("" = it passes); `slices` are the whole command's, for
    `_writes_request`; `bare` (a bare parenthesis of bash) withdraws the reader exemption (see `_launches_runner`).
    `current` is the running dispatch the request must name; None with `active` (the running ones) = the request's own
    `dispatch_id` picks among them (two or more running, no name; TR3-14).

    The order is the invariant (CX1-20 section 4 R4): (1) the slice names the runner - on its RAW text or one cleaned
    word - else nothing is read; (2) a reader head (on the MASKED text) only mentions it; (3) a non-executing flag, on
    the masked text, frees the slice as on main; (4) a region in the slice is a refusal - what it expands to is unknown;
    (5) `--mine` and the request file are read only from a slice with no region."""
    if not _launches_runner(piece, readers_exempt=not bare):
        return ""  # the slice reads the runner, it does not run it
    if _non_executing_flag(piece.masked):
        return ""  # launches no test, so the typed interface has nothing to protect here
    if piece.region:
        return REGION_REFUSAL
    if re.search(r"(?<![\w-])--mine(?=[\s=]|$)", piece.raw):
        return ""  # `--mine` builds the request from the open dispatch and checks its scope itself
    path_text = _request_path(piece.raw)
    if not path_text:
        return ("an active factory dispatch may run tests only through `run_suite.py --request FILE` "
                "or `run_suite.py --schedule FILE`; "
                "legacy --task/--label and the default full suite are standalone user interfaces. "
                f"Flags that launch nothing pass as they are: {', '.join(NON_EXECUTING_FLAGS[:4])}"
                + (BARE_PAREN_NOTE if bare else ""))
    path = Path(path_text)
    if not path.is_absolute():
        path = Path(str(event.get("cwd") or os.getcwd())) / path
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if _writes_request([each.raw for each in slices], path_text):
            note = (f"{path.name} does not exist yet — this command writes it before "
                    "running it, so the guard could not check its dispatch id or scope. "
                    "run_suite.py checks both itself.")
            if notes is not None and note not in notes:
                notes.append(note)
            return ""
        return ("typed run request is unreadable: FileNotFoundError. If the same command was "
                f"going to create it, {SAME_COMMAND_FIX} — a PreToolUse hook reads the path "
                "before the shell runs")
    except (OSError, json.JSONDecodeError) as exc:
        return f"typed run request is unreadable: {type(exc).__name__}"
    requests = request.get("requests") if isinstance(request, dict) and "requests" in request else [request]
    if not isinstance(requests, list) or not requests:
        return "typed schedule requires a non-empty requests array"
    covers = _manifest_covers(ticket, event)
    for item in requests:
        # `current` None: two or more are running and the session carries no name - the request's own id picks the
        # running dispatch it names (its scope is then the one judged); an id no running dispatch holds is the old refusal.
        mine = current
        if mine is None and isinstance(item, dict):
            mine = next((d for d in (active or []) if d.get("id") == item.get("dispatch_id")), None)
        if not isinstance(item, dict) or mine is None or item.get("dispatch_id") != mine.get("id"):
            return "RunRequest dispatch_id does not match the active controller dispatch"
        scope = {str(s) for s in (mine.get("scope") or [])}
        selected = item.get("selected_instance_ids")
        if not isinstance(selected, list):
            return "RunRequest selected instances exceed the active dispatch scope"
        outside = [str(i) for i in selected if not _in_scope(i, scope, covers)]
        if outside:
            return ("RunRequest selected instances exceed the active dispatch scope: "
                    + ", ".join(sorted(outside)[:3])
                    + " — an instance is in scope when the manifest says it `covers` a case "
                      "of the scope; add the case to its `covers` through manifest_put.py")
    return ""


def check_command(event: dict) -> int:
    command = hooklib.argv_text((event.get("tool_input") or {}).get("command"))   # an argv list: its line, never str(list)
    ticket = requested_ticket(event)
    if hooklib.hint_gate(command, RUNNER_HINTS) and ticket:
        notes: list = []
        message = ""
        for dialect in ("bash", "powershell"):   # OH3-22: the runner rule reads what each shell RUNS, not what a body stores
            message = message or rule_typed_runner(_executable_text(command, dialect), event, ticket, notes=notes)
        if message:
            return deny(f"{ticket}: {message}")
        for note in notes:
            hooklib.notice(event, f"STAGE GUARD (note, not a block): {note}", reader="role")   # the automator reads it (RH1-5)
    cfg = load_config(event)
    shapes = command_shapes(command, cfg, event)
    if not shapes:
        return ALLOW
    if not ticket:
        return ALLOW  # no story in this repo — not the guard's business
    pipeline = read_json(artifacts_dir(ticket, event) / "pipeline.json")
    if not pipeline:
        return ALLOW
    # EVERY shape the command has, delivery first: the first refusal denies. A command that is a delivery AND
    # a commit of test files meets rule 4 and then rules 5 and 3 - the delivery form is never the way past them.
    for shape in shapes:
        if shape == "commit":
            message = rule_pathspec(_executable_text(command, "bash")) or rule_manifest(ticket, "committing test code", event)
        elif shape == "stash":
            message = rule_stash(_executable_text(command, "bash"))
        else:
            message = rule_delivery(ticket, "this delivery command", event, _delivery_match(command, cfg), pipeline)
        if message:
            return deny(f"{ticket}: {message}")
    return ALLOW


def needs_stage_guard(command: str, cfg: dict | None = None) -> bool:
    """guard_pre_tool.py's fast gate: load the stage model only for the Bash shapes rules
    3-5 and 7 name. `cfg` is the config the hook already holds (the project's own delivery commands).

    Every `git commit` passes the gate: which commits are test commits is `command_shapes`' question, and it
    needs the config and the usual test names, which a gate that runs on every command must not read (B-407 A).
    Invariant: a command with none of these words (`ls -la`) reads no file. The words are read by
    `hooklib.hint_gate`, the one gate rule of the readers (CX1-20 NB-2): in the text, in its cleaned view (quotes,
    escapes out, blank runs collapsed), or a `$(` / backtick in it - `git com$(true)mit`, `git $(true) commit`,
    `python C:/p/run_sui$(true)te.py` - so a command the walker would read is never stopped here, on the hook path."""
    cmd = command or ""
    if hooklib.hint_gate(cmd, COMMIT_HINTS + RUNNER_HINTS, groups=True):
        return True
    return _is_delivery_shape(cmd, cfg) or _is_stash_shape(cmd)


# --- CLI ---------------------------------------------------------------------------------------

def explain(ticket: str, stage_id: str) -> int:
    model = stage_model()
    stage = next((s for s in model.get("stages") or [] if s.get("id") == stage_id), None)
    if stage is None:
        print(f"unknown stage {stage_id} — stages.json knows "
              f"{[s.get('id') for s in model.get('stages') or []]}", file=sys.stderr)
        return 1
    pipeline = read_json(artifacts_dir(ticket) / "pipeline.json")
    if not pipeline:
        print(f"{ticket}: no pipeline.json — every stage would be allowed (fail-open)")
        return 0
    problems = dispatch_errors(pipeline, stage_id, journal=False, model=model, ticket=ticket)
    if problems:
        print(f"{ticket} {stage_id}: BLOCKED")
        for p in problems:
            print(f"  - {p}")
        return DENY
    print(f"{ticket} {stage_id}: allowed (roles: {', '.join(stage.get('roles') or []) or 'code only'})")
    return 0


STALE_AFTER_CLOSURE = "STALE ACTIVE STATE AFTER CLOSURE"


def _stale_after_closure(pipeline_path: Path, stages: dict, order: list) -> str:
    """The tail a closed story earns when it still looks busy, with its one next action.

    S9 is not counted: the retro legitimately runs after gate B and S8, which is the whole
    reason `story_closed` calls such a story closed. Anything else `running`/`halted`, or a
    dispatch still `running` in `state/controller.json`, is the ghost tail of TP2-2534
    — an open dispatch on a running stage, which `recover` used to read as "nothing is
    broken". Naming the command here is the contract with `controller.py --operation
    recover`: this line never asks the person to repair the factory's own bookkeeping."""
    stale = [sid for sid in (order or list(stages))
             if sid != "S9" and str((stages.get(sid) or {}).get("status") or "")
             in ("running", "halted")]
    if not stale:
        dispatches = (read_json(pipeline_path.parent / "state" / "controller.json")
                      .get("dispatches") or {})
        stale = [str(d.get("id") or "") for d in dispatches.values()
                 if isinstance(d, dict) and d.get("status") == "running"
                 and d.get("stage") != "S9"]
    if not stale:
        return ""
    # Exact wording: qa-doctor quotes this line, and `recover` is the only action it offers.
    return (f"  {STALE_AFTER_CLOSURE} — "
            f"controller.py --task-root {pipeline_path.parent} --operation recover")


def stories(event: dict | None = None) -> int:
    """One line per open story — the whole of qa-doctor's step 4, in one call.

    The doctor used to Glob `artifacts/*/pipeline.json` and Read each one: a 3,393-byte
    file (~850 tokens) per story, to produce a twenty-token line. Six stories meant six
    tool calls and ~5K tokens of JSON in context for six lines — the same "read a slice,
    not a file" the roles are told to follow, and the same mechanics-belong-in-a-script
    rule that `run_suite.py` exists for. Archived stories are filtered here too, so the
    skill cannot forget to — but an archived story that still carries an unresolved halt
    or an unanswered gate is named in the closing line. The flag is a person saying "stop
    showing me this", and it must not also mean "and stop checking it".
    """
    from hooklib import story_closure
    model = stage_model()
    order = [s.get("id") for s in model.get("stages") or []]
    root = artifact_root(event)
    if not root.exists():
        print("no stories yet")
        return 0
    rows, archived, archived_open = [], 0, []
    for pj in sorted_paths(root.glob("*/pipeline.json")) + sorted_paths(root.glob("*/*/pipeline.json")):
        data = read_json(pj)
        # One filter, shared with `requested_ticket` (0.7.12): the guard used to count an
        # archived story as a dispatch candidate while this listing hid it, so the two
        # disagreed about which stories exist.
        if is_archived(pj, data):
            archived += 1
            # Archiving is a person saying "stop showing me this" — it must not also
            # mean "stop checking it". A hidden story that still carries an open item
            # is named below rather than silenced by the flag.
            try:
                from archive_task import open_items
                if open_items(data):
                    archived_open.append(pj.parent.name)
            except Exception:
                pass
            continue
        if not data:
            rows.append(f"{pj.parent.name}  unreadable pipeline.json — inspect it by hand")
            continue
        stages = data.get("stages") if isinstance(data.get("stages"), dict) else {}
        done = [sid for sid in order if (stages.get(sid) or {}).get("status") == "done"]
        active = [f"{sid} {(stages.get(sid) or {}).get('status')}" for sid in order
                  if (stages.get(sid) or {}).get("status") in ("running", "halted")]
        gates = data.get("gates") if isinstance(data.get("gates"), dict) else {}
        ga = (gates.get("A") or {}).get("decision") or "not reached"
        gb = (gates.get("B") or {}).get("decision") or "not reached"
        open_halts = [h for h in (data.get("halts") or [])
                      if isinstance(h, dict) and not h.get("resolved")]
        # "Closed" is a state the listing says out loud, not something the reader infers from
        # `last done: S8` standing next to `active: S3 running` (I-92): that pair is exactly
        # what TP2-2534 printed for two days while nobody read it as a contradiction.
        closure = story_closure(data)
        closed_at = closure["closed_at"] if closure["state"] == "closed" else ""
        if closed_at:
            active = active + [f"closed {closed_at.split('T')[0]}"]
        elif closure["state"] == "executing":
            active = active + [f"executing gate B: {', '.join(closure['due'])}"]
        line = (f"{pj.parent.name}  last done: {done[-1] if done else 'none'}  "
                f"active: {', '.join(active) or 'none'}  gate A: {ga}  gate B: {gb}")
        if closed_at:
            line += _stale_after_closure(pj, stages, order)
        # t-2181 PC-6: a story held for code says so, with the cause, so the doctor never reads "last done: S5" as a stall; a
        # stopped one says it was stopped. One text, `archive_task.hold_line`, shared with the archive's open items.
        from archive_task import hold_line
        held = hold_line(data)
        if held:
            line += "  " + held
        if open_halts:
            line += f"  UNRESOLVED HALTS ({len(open_halts)}): " + " | ".join(
                str(h.get("reason") or h.get("digest") or "no reason recorded")[:120] for h in open_halts)
        # A stage that finished before it started (TP2-2553: S0 13:20 -> 11:42) is a
        # fact about the factory's own clock, shown where the story is listed.
        from stage_done import clock_anomalies
        anomalies = clock_anomalies(data)
        if anomalies:
            line += "  CLOCK ANOMALY: " + " | ".join(
                f"{sid} {v['started_at']} -> {v['finished_at']}" for sid, v in anomalies)
        rows.append(line)
    tail = ""
    if archived:
        tail = f"({archived} archived, not listed"
        if archived_open:
            tail += ("; " + str(len(archived_open)) + " of them still carry an open "
                     "item — " + ", ".join(archived_open))
        tail += ")"
    if not rows:
        print("no open stories" + (" " + tail if tail else ""))
        return 0
    for r in rows:
        print(r)
    if tail:
        print(tail)
    return 0


def selftest() -> int:
    import tempfile

    failures: list[str] = []

    def case(name: str, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    model = stage_model()
    case("stages.json parses with 10 stages", len(model.get("stages") or []), 10)
    case("gate A sits after S4", ((model.get("gates") or {}).get("A") or {}).get("after"), "S4")
    case("gate B sits after S8", ((model.get("gates") or {}).get("B") or {}).get("after"), "S8")
    case("role lookup: qa-case-critic is an S4 role", (stage_of_role(model, "qa-case-critic") or {}).get("id"), "S4")
    case("role lookup: qa-case-critic stands on the stages stages.json lists (S2, S3 and S4 since X2-7: the stage critic)",
         [st.get("id") for st in stages_of_role(model, "qa-case-critic")], ["S2", "S3", "S4"])
    case("role lookup: qa-bug-reporter is an S8 role",(stage_of_role(model, "qa-bug-reporter") or {}).get("id"), "S8")
    case("role lookup: a foreign agent has no stage", stage_of_role(model, "general-purpose"), None)
    case("command shape: git commit of a test file", command_shape("git commit -m x tests/test_a.py"), "commit")
    case("command shape: git commit of a doc", command_shape("git commit -m x README.md"), "")
    case("command shape: glab mr create", command_shape("glab mr create --fill"), "delivery")
    case("command shape: plain ls", command_shape("ls -la"), "")
    case("command shape: git commit of a factory artifact",
         command_shape("git commit -m x qa-factory/artifacts/QA-1/test-plan.md"), "commit")

    # The desktop dispatch contract: `task_name=<role>__<ticket-slug>[_suffix]`.
    case("slug: a ticket's desktop spelling", ticket_slug("TP2-2556"), "tp2_2556")
    case("slug: the live story's slug is found after the role prefix",
         slug_in_task_name("tp2_2556", "qa_automator__tp2_2556_s5_11"), True)
    case("slug: with no suffix at all",
         slug_in_task_name("tp2_2556", "qa_scout__tp2_2556"), True)
    case("slug: a shorter ticket is not found inside a longer one",
         slug_in_task_name("abc_12", "qa_scout__abc_123_s1"), False)
    case("slug: the role prefix itself is never a story",
         slug_in_task_name("qa_automator", "qa_automator__abc_1"), False)
    case("slug: a task name with no role prefix names nothing",
         slug_in_task_name("abc_1", "abc_1"), False)

    # Rule 6 - a resume is addressed to an agent this story already ran. SendMessage is
    # not Agent, so without this the tool that reopens a dispatch skipped every stage rule.
    case("resume: a shape the guard does not recognize is allowed",
         _check({"tool_name": "SendMessage", "tool_input": {}}), ALLOW)

    # Rule 5 - a factory commit names its files, so the index it inherits cannot ride along.
    case("pathspec: a bare -m commit is refused",
         bool(rule_pathspec('git commit -m "docs: x"')), True)
    case("pathspec: its message names the fix",
         "-- <paths>" in rule_pathspec('git commit -m "docs: x"'), True)
    case("pathspec: -a is refused by name",
         "-a/--all" in rule_pathspec('git commit -am "docs: x"') or
         "-a/--all" in rule_pathspec('git commit -a -m "docs: x"'), True)
    case("pathspec: an explicit -- passes",
         rule_pathspec('git commit -m "x" -- tests/test_a.py'), "")
    case("pathspec: trailing paths pass",
         rule_pathspec('git commit -m "x" tests/test_a.py qa-factory/artifacts/QA-1'), "")
    case("pathspec: a message containing -a is not an -a flag",
         rule_pathspec('git commit -m "fix -a handling" -- tests/test_a.py'), "")
    case("pathspec: options with values are not paths",
         bool(rule_pathspec('git commit -m "x" --author "A B <a@b.c>"')), True)

    # Rule 7 - a stash names what it takes; the story's own untracked artifacts stay put.
    case("stash: a bare push -u is refused",
         bool(rule_stash("git stash push -u")), True)
    case("stash: its message names the safe command",
         "':(exclude)qa-factory')" in rule_stash("git stash push -u"), True)
    case("stash: an explicit pathspec passes",
         rule_stash("git stash push -u -- src/app.py docs/readme.md"), "")
    case("stash: an exclude pathspec passes",
         rule_stash("git stash push -u -- . ':(exclude)qa-factory'"), "")
    case("stash: qa-factory named among the paths is refused",
         bool(rule_stash("git stash push -u -- src/app.py qa-factory/artifacts")), True)
    case("stash: a trailing -- with no path is refused",
         bool(rule_stash("git stash push -u --")), True)
    case("stash: pop is not this rule's business",
         rule_stash("git stash pop"), "")
    case("stash: list is not this rule's business",
         rule_stash("git stash list"), "")
    case("stash: save is the same shape as push",
         bool(rule_stash('git stash save -u "wip"')), True)
    case("stash: a stash command is a shape the guard sees",
         command_shape("git stash push -u"), "stash")
    case("stash: pop is not a shape the guard sees",
         command_shape("git stash pop"), "")

    # The typed-runner tax (TP1-15045, 42 guard refusals over six S5 windows). Every
    # command below is one the live run was refused; none of them could have run a test
    # outside the typed interface.
    open_dispatch = {"dispatches": {"d-1": {"id": "d-1", "status": "running",
                                            "scope": ["TC-012", "TC-013"]}}}
    runner = "/c/plugins/qa-factory/0.7.6/scripts/run_suite.py"

    def typed(command: str, notes: list | None = None) -> str:
        return rule_typed_runner(command, {"cwd": str(Path(__file__).parent)}, "QA-1",
                                 open_dispatch, notes)

    case("runner: an untyped full-suite run is still refused",
         bool(typed(f"python {runner} --task QA-1 --label all")), True)
    for flag in ("--help", "--detail tests/test_a.py::test_b", "--recover KEY",
                 "--reparse-block block.json --mapping m.json"):
        case(f"runner: `{flag.split()[0]}` launches no test and passes",
             typed(f"python {runner} --task QA-1 {flag}"), "")
    case("runner: looking the runner up with find is not running it",
         typed("find / -name run_suite.py 2>/dev/null | head -3"), "")
    case("runner: grepping inside it is not running it",
         typed(f'grep -n "report_test_id" {runner}'), "")
    case("runner: a real launch inside a compound command is still seen",
         bool(typed(f"ls /tmp | head -3; python {runner} --task QA-1 --label all")), True)
    notes: list = []
    case("runner: a request written by the same command is a note, not a refusal",
         typed(f"cp $S/probe.json work/requests/redprobe-1.json && "
               f"python {runner} --request work/requests/redprobe-1.json", notes), "")
    case("runner: and the note says the guard could not check the scope",
         bool(notes and "could not check" in notes[0]), True)
    missing = typed(f"python {runner} --request work/requests/never-written.json")
    case("runner: a request nothing writes is still refused",
         "FileNotFoundError" in missing, True)
    case("runner: and the refusal names the two-call shape", SAME_COMMAND_FIX in missing, True)
    scope = {"TC-012", "TC-013"}
    case("runner: the readable instance id of a case in scope is in scope",
         _in_scope("TC-012::test_validate_per_partition[missing-assistant]", scope), True)
    case("runner: and the file-safe form of the same id",
         _in_scope("TC-012--test_validate_per_partition--missing-assistant", scope), True)
    case("runner: and the case id itself", _in_scope("TC-013", scope), True)
    case("runner: an instance of a case outside the scope is outside",
         _in_scope("TC-099::test_other[x]", scope), False)
    case("runner: a case id the scope only PREFIXES is outside",
         _in_scope("TC-0123::test_other[x]", scope), False)
    case("runner: the case of a readable instance id",
         _instance_case("TC-012::test_validate_per_partition[missing-assistant]"), "TC-012")
    case("runner: the case of a file-safe instance id",
         _instance_case("TC-012--test_validate_per_partition--missing-assistant"), "TC-012")
    case("runner: a bare case id has no case prefix", _instance_case("TC-012"), "")
    # an id no longer carries a case, so the manifest's `covers` is what puts one
    # consolidated instance inside a scope of three cases — and one request runs the group.
    covers = {"test_validate[eu]": {"TC-012", "TC-013"},
              "test_elsewhere": {"TC-099"}}
    case("runner: an instance is in scope when the manifest says it covers a case of it",
         _in_scope("test_validate[eu]", scope, covers), True)
    case("runner: an instance covering nothing in scope is still outside",
         _in_scope("test_elsewhere", scope, covers), False)
    case("runner: with no manifest to read, the id's own shape still answers",
         _in_scope("TC-012::test_x", scope, {}), True)

    import hooklib
    with tempfile.TemporaryDirectory(prefix="qa-factory-stage-") as td, \
            hooklib.selftest_root_restored():
        proj = Path(td)
        art = proj / "qa-factory" / "artifacts" / "QA-1"
        art.mkdir(parents=True)
        (proj / "qa-factory" / "state").mkdir(parents=True)
        (proj / "qa-factory" / "config.json").write_text('{"schema_version": 1}', encoding="utf-8")
        # Pin it, cache and env var both: the cache is per process and the selftest moves the
        # root, and clearing it alone asked cwd again — from a cwd inside a real project that
        # walk answers with the project's own stories (macOS 0.7.11).
        hooklib.pin_project_root(proj)
        print(f"SELFTEST ROOT: {hooklib.project_root()}")
        def pipeline(done: list, gate_a, overrides: list | None = None) -> dict:
            stages = {s["id"]: {"status": "done" if s["id"] in done else "pending"}
                      for s in model["stages"]}
            record = gate_a if isinstance(gate_a, dict) else ({"decision": gate_a} if gate_a else {})
            data = {"ticket": "QA-1", "stages": stages, "gates": {"A": record}}
            if overrides:
                data["stage_overrides"] = overrides
            (art / "pipeline.json").write_text(json.dumps(data), encoding="utf-8")
            return data

        def dispatch(role: str) -> int:
            return check({"tool_name": "Task", "tool_input": {"subagent_type": role, "prompt": "QA-1"}})

        # Rule 1 — order.
        pipeline(["S0"], None)
        case("rule 1: qa-scout runs after S0", dispatch("qa-scout"), ALLOW)
        case("rule 1: qa-test-strategist blocked while S2 is pending", dispatch("qa-test-strategist"), DENY)

        # The tracker route S1 reads through (TP2-2553). No readiness.json above:
        # that case has already passed, and it is the one a story in flight depends on.
        readiness_file = RP.readiness_write(proj)

        def readiness_says(status: str, note: str = "reached through the session mcp_tool") -> None:
            readiness_file.parent.mkdir(parents=True, exist_ok=True)
            readiness_file.write_text(json.dumps({"capabilities": {"ticket_adapter": {
                "status": status, "owner": "user", "note": note,
                "remedy": {"steps": ["/qa-factory:qa-onboarding — topic 7: how the tracker is READ"]}}}}),
                encoding="utf-8")

        pipeline(["S0"], None)
        readiness_says("not_configured")
        case("tracker route: S1 is refused while the route is not proven",
             dispatch("qa-scout"), DENY)
        case("tracker route: and the refusal quotes what readiness said",
             "mcp_tool" in LAST_DENIAL["message"], True)
        case("tracker route: with the waiver command the person's word goes in",
             '--block "tracker route"' in LAST_DENIAL["message"], True)
        case("tracker route: a role that does not read the tracker is unaffected",
             dispatch("qa-requirements-tester") == DENY
             and "tracker route" not in LAST_DENIAL["message"], True)
        readiness_says("ok", "adapter `jira` — direct read access verified")
        case("tracker route: a proven route passes", dispatch("qa-scout"), ALLOW)
        readiness_says("unknown", "the read-only probe has not run")
        case("tracker route: an unproven one does not", dispatch("qa-scout"), DENY)
        pipeline(["S0"], None, [{"stage": "S1", "match": "tracker route",
                                 "decision": "go on without the parent", "at": "T1",
                                 "by": "human"}])
        case("tracker route: the person's recorded word passes it", dispatch("qa-scout"), ALLOW)
        readiness_file.unlink()
        pipeline(["S0"], None)
        case("tracker route: a project with no readiness.json is refused nothing",
             dispatch("qa-scout"), ALLOW)
        RP.record(proj, "journal.jsonl").unlink(missing_ok=True)

        # Rule 2 — gate A.
        pipeline(["S0", "S1", "S2", "S3"], None)
        case("rule 2: qa-case-designer completes before gate A", dispatch("qa-case-designer"), ALLOW)
        case("rule 2: qa-automator blocked without gate A", dispatch("qa-automator"), DENY)
        pipeline(["S0", "S1", "S2", "S3"], "approve")
        case("rule 2: qa-case-designer allowed after gate A", dispatch("qa-case-designer"), ALLOW)

        # Rule 2, one vocabulary. The controller projects its own decision record as
        # `decision: "approved"` with `status: "approved"` beside it; the orchestrator used
        # to write `"approve"` by hand. Both are the same answer, and this rule compared
        # against one string until TP1-15045 refused S5 after a recorded approval.
        pipeline(["S0", "S1", "S2", "S3", "S4"], "approved")
        case("rule 2: the controller's 'approved' is the same approval",
             dispatch("qa-automator"), ALLOW)
        pipeline(["S0", "S1", "S2", "S3", "S4"], {"status": "approved"})
        case("rule 2: a decision record carrying only status passes",
             dispatch("qa-automator"), ALLOW)
        pipeline(["S0", "S1", "S2", "S3", "S4"], {"decision": "declined", "status": "declined"})
        case("rule 2: a declined gate is still a block", dispatch("qa-automator"), DENY)

        # A person's word passes it. `waiver.py --stage` wrote the override, the
        # guard never read it, and the person was told to edit a line in the plugin.
        blocked = pipeline(["S0", "S1", "S2", "S3", "S4"], None)
        errors = dispatch_errors(blocked, "S5", journal=False)
        case("rule 2: a refusal names the ready waiver command", len(errors), 1)
        case("rule 2: with the block text the person has to pass",
             '--block "gate A is not approved"' in errors[0], True)
        case("rule 2: and the story's own ticket", "--task QA-1" in errors[0], True)
        passed = pipeline(["S0", "S1", "S2", "S3", "S4"], None,
                          [{"stage": "S5", "match": "gate A is not approved",
                            "decision": "Go on", "at": "T1", "by": "human"}])
        case("rule 2: the person's recorded word passes the block",
             dispatch_errors(passed, "S5", journal=False), [])
        case("rule 2: and the dispatch itself goes through", dispatch("qa-automator"), ALLOW)
        case("rule 2: which is journaled as a gate_override",
             any(row.get("event") == "gate_override"
                 for row in journal_lines({"cwd": str(proj)})), True)
        case("rule 1: an order block carries its own waiver command",
             '--block "required stages are not done"' in
             dispatch_errors(pipeline(["S0"], None), "S3", journal=False)[0], True)
        case("rehearsal: assume_gate_approved answers what would stop S5 after approval",
             dispatch_errors(pipeline(["S0", "S1", "S2", "S3", "S4"], None), "S5",
                             assume_gate_approved="A"), [])
        RP.record(proj, "journal.jsonl").unlink(missing_ok=True)

        # Rule 3 — manifest completeness.
        pipeline(["S0", "S1", "S2", "S3", "S4", "S5"], "approve")
        (art / "automation-manifest.json").write_text(
            json.dumps({"tests": [], "unresolved": [{"case": "TC-004", "reason": "because"}]}),
            encoding="utf-8")
        case("rule 3: qa-runner blocked by an unresolved case with an unknown reason", dispatch("qa-runner"), DENY)
        commit = {"tool_name": "Bash", "tool_input": {"command": "git commit -m x tests/test_a.py"}}
        case("rule 3: a test-code commit is blocked too", check(commit), DENY)
        (art / "automation-manifest.json").write_text(
            json.dumps({"tests": [], "unresolved": [{"case": "TC-004",
                                                     "reason": "deferred_by_decision:gateA"}]}),
            encoding="utf-8")
        case("rule 3: a decided unresolved case unblocks the run", dispatch("qa-runner"), ALLOW)
        case("rule 3: and unblocks the commit", check(commit), ALLOW)
        (art / "automation-manifest.json").write_text(
            json.dumps({"tests": [], "unresolved": [{"case": "TC-004", "reason": "impossible"}]}),
            encoding="utf-8")
        case("rule 3: a vocabulary reason (impossible) travels into the ledger, run allowed", dispatch("qa-runner"), ALLOW)
        # t-910 (C4-1): the manifest is found where the registry puts it, and "not read" is not "nothing found".
        (art / "automation-manifest.json").unlink()
        (art / "work").mkdir(exist_ok=True)
        (art / "work" / "automation-manifest.json").write_text(
            json.dumps({"tests": [], "unresolved": [{"case": "TC-004", "reason": "because"}]}), encoding="utf-8")
        case("rule 3: the same unknown reason under work/ (the registry's path) blocks too", dispatch("qa-runner"), DENY)
        (art / "work" / "automation-manifest.json").write_text(json.dumps({"tests": [], "unresolved": []}), encoding="utf-8")
        case("rule 3: a manifest read with no items passes", dispatch("qa-runner"), ALLOW)
        (art / "work" / "automation-manifest.json").unlink()
        case("rule 3: S6 with no manifest and S5 not recorded as skipped is refused", dispatch("qa-runner"), DENY)
        case("rule 3: ...and the refusal says exactly that the manifest is absent and S5 is not recorded as skipped",
             "work/automation-manifest.json is absent: S5 is not recorded as skipped by a policy" in LAST_DENIAL["message"],
             True)
        skipped_pipeline = pipeline(["S0", "S1", "S2", "S3", "S4"], "approve")
        skipped_pipeline["stages"]["S5"] = {"status": "skipped", "mode": "preparatory"}
        (art / "pipeline.json").write_text(json.dumps(skipped_pipeline), encoding="utf-8")
        dispatch("qa-runner")
        case("rule 3: a policy-skipped S5 expects no manifest (rule 1 still speaks for the skipped stage, rule 3 is silent)",
             "S5=skipped" in LAST_DENIAL["message"] and "automation-manifest" not in LAST_DENIAL["message"], True)
        pipeline(["S0", "S1", "S2", "S3", "S4", "S5"], "approve")
        (art / "work" / "automation-manifest.json").write_text("{oops", encoding="utf-8")
        case("rule 3: an unreadable manifest is refused", dispatch("qa-runner"), DENY)
        (art / "work" / "automation-manifest.json").write_text(json.dumps({"tests": [], "unresolved": []}), encoding="utf-8")

        # Rule 4 — delivery.
        pipeline(["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"], "approve")
        (art / "ledger.json").write_text(
            json.dumps({"rows": [], "delivery_ready": False, "reasons": ["a requirement has no outcome"]}),
            encoding="utf-8")
        mr = {"tool_name": "Bash", "tool_input": {"command": "glab mr create --fill # QA-1"}}
        case("rule 4: qa-bug-reporter blocked while gate B has no recorded decision", dispatch("qa-bug-reporter"), DENY)
        case("rule 4: and the refusal names the gate B door", "--gate B" in LAST_DENIAL["message"], True)
        case("rule 4: glab mr create blocked too", check(mr), DENY)
        RP.record(proj, "journal.jsonl").parent.mkdir(parents=True, exist_ok=True)
        RP.record(proj, "journal.jsonl").write_text(
            json.dumps({"event": "deliver_with_risks", "task": "QA-1", "reason": "release window"}) + "\n",
            encoding="utf-8")
        case("rule 4: deliver_with_risks in the journal does not open the reporter (only gate B's decision does)",
             dispatch("qa-bug-reporter"), DENY)
        case("rule 4: but it unblocks the MR command", check(mr), ALLOW)
        gated = pipeline(["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"], "approve")
        gated["gates"]["B"] = {"status": "approved", "decision": "approved", "selected_drafts": ["d-1"]}
        (art / "pipeline.json").write_text(json.dumps(gated), encoding="utf-8")
        case("rule 4: qa-bug-reporter opens on the recorded gate B decision even though the verdict is no",
             dispatch("qa-bug-reporter"), ALLOW)
        RP.record(proj, "journal.jsonl").unlink(missing_ok=True)
        case("rule 4: ... and the MR command still waits for the verdict or deliver_with_risks", check(mr), DENY)
        # The ledger lives where artifact-registry.json says: work/ledger.json, with the
        # flat name a legacy alias. Reading the flat path only would refuse delivery on
        # every 0.7.7 story for a file that is there.
        RP.record(proj, "journal.jsonl").unlink(missing_ok=True)
        (art / "ledger.json").unlink()
        (art / "work").mkdir(exist_ok=True)
        (art / "work" / "ledger.json").write_text(
            json.dumps({"rows": [], "delivery_ready": True}), encoding="utf-8")
        case("rule 4: the ledger is found where the registry puts it", check(mr), ALLOW)
        case("rule 4: and the resolved path is the registry's",
             ledger_path(art).name == "ledger.json" and ledger_path(art).parent.name == "work",
             True)

        # Fail-open.
        (art / "pipeline.json").unlink()
        case("fail-open: no pipeline.json -> allow", dispatch("qa-test-strategist"), ALLOW)
        case("fail-open: a foreign agent is never touched", dispatch("general-purpose"), ALLOW)

        # Story identity on a host that cannot carry an id in its dispatch text (I-90).
        # Codex desktop passes `task_name`, `fork_turns` and an OPAQUE encrypted `message`,
        # so the task name is the only readable carrier — and a finished story left `running`
        # made every dispatch of the live one "ambiguous" for two days (TP2-2556).
        def desktop(task_name: str, **extra) -> dict:
            opaque = "gAAAAABo" + "x" * 40
            return dict({"tool_name": "Agent",
                         "tool_input": {"subagent_type": "qa-automator",
                                        "task_name": task_name, "prompt": opaque},
                         "_qa_host": {"name": "collaboration.spawn_agent",
                                      "input": {"task_name": task_name, "fork_turns": "none",
                                                "message": opaque}}}, **extra)

        closed_stamp = "2026-09-21T10:00:00+00:00"

        def story(name: str, running: bool = True, archived: bool = False,
                  closed: bool = False) -> None:
            folder = art.parent / name
            folder.mkdir(parents=True, exist_ok=True)
            data = {"ticket": name,
                    "stages": {"S1": {"status": "running" if running else "done"}}}
            if archived:
                data["archived"] = True
            if closed:
                # Shaped by hand, as TP2-2534 was shaped on disk: gate B decided and
                # S8 done is what `hooklib.story_closed` reads, with or without `closed_at`.
                data["stages"]["S8"] = {"status": "done", "finished": closed_stamp}
                data["gates"] = {"A": {"decision": "approve"},
                                 "B": {"decision": "approve", "at": closed_stamp}}
                data["closed_at"] = closed_stamp
            (folder / "pipeline.json").write_text(json.dumps(data), encoding="utf-8")

        story("TP2-2556")
        story("TP2-2534")
        case("identity: the desktop task name names the story among two running ones",
             requested_ticket(desktop("qa_automator__tp2_2556_s5_11")),
             "TP2-2556")
        case("identity: a task name naming no existing story stays ambiguous",
             requested_ticket(desktop("qa_automator__unmatched_1")), "")
        case("identity: and that dispatch is refused", check(desktop("qa_automator__unmatched_1")), DENY)
        for fact in (str(art.parent.resolve()), "qa_automator__unmatched_1", "TP2-2534",
                     "TP2-2556", "QA_FACTORY_TASK"):
            case(f"identity: the refusal names {fact}", fact in LAST_DENIAL["message"], True)

        story("TP2-2534", archived=True)
        case("identity: an archived story is not a candidate, so the live one is unambiguous",
             requested_ticket(desktop("qa_automator__unmatched_1")), "TP2-2556")

        story("TP2-2534")
        os.environ["QA_FACTORY_TASK"] = "TP2-2556"
        try:
            case("identity: a person's word in QA_FACTORY_TASK passes the block",
                 requested_ticket(desktop("qa_automator__unmatched_1")), "TP2-2556")
            os.environ["QA_FACTORY_TASK"] = "NOPE-1"
            case("identity: and only ever names a story that exists",
                 requested_ticket(desktop("qa_automator__unmatched_1")), "")
        finally:
            os.environ.pop("QA_FACTORY_TASK", None)

        case("identity: an explicit id with no story here is a different refusal",
             check(desktop("qa_automator__x", task_id="TP2-9999",
                           host_binding=str(proj / "binding.json"))), DENY)
        case("identity: which does not ask for the id the person already passed",
             LAST_DENIAL["message"].startswith("the explicit task id names no story"), True)
        case("identity: and names where that id came from",
             "host binding" in LAST_DENIAL["message"], True)

        # The ghost tail (I-92). 2534 was S1-S8 done with gate B approved and its MR
        # merged, and ONE stage left `running` made it the second running story for two
        # days — so every dispatch of the live 2556 was refused as ambiguous.
        story("TP2-2534", closed=True)
        ghost = desktop("qa_automator__unmatched_1")
        case("identity: a closed story with a ghost running stage is not a candidate",
             requested_ticket(ghost), "TP2-2556")
        case("identity: and the facts name it as closed rather than drop it",
             resolve_ticket(ghost)[1].get("closed"), ["TP2-2534"])
        case("identity: closing changes the guess, never a named story — S9 still dispatches",
             requested_ticket(desktop("qa_retro_analyst__tp2_2534_s9")),
             "TP2-2534")
        os.environ["QA_FACTORY_TASK"] = "TP2-2534"
        try:
            case("identity: and a person's word still names the closed story",
                 requested_ticket(desktop("qa_scout__unmatched_1")), "TP2-2534")
        finally:
            os.environ.pop("QA_FACTORY_TASK", None)

        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            stories()
        listing = {line.split()[0]: line for line in buf.getvalue().splitlines() if line.strip()}
        case("stories: a closed story says the word, with the date",
             "closed 2026-09-21" in listing.get("TP2-2534", ""), True)
        case("stories: and its ghost running stage ends the line with one next action",
             STALE_AFTER_CLOSURE in listing.get("TP2-2534", "")
             and "--operation recover" in listing.get("TP2-2534", ""), True)
        case("stories: the still-running stage is not hidden either",
             "S1 running" in listing.get("TP2-2534", ""), True)
        case("stories: an open story is neither closed nor stale",
             "closed" in listing.get("TP2-2556", "")
             or STALE_AFTER_CLOSURE in listing.get("TP2-2556", ""), False)

        story("TP2-2534", running=False, closed=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            stories()
        settled = next((line for line in buf.getvalue().splitlines()
                        if line.startswith("TP2-2534")), "")
        case("stories: a closed story with no tail reads `active: closed <date>`",
             "active: closed 2026-09-21" in settled, True)
        case("stories: and is not accused of a stale state it does not have",
             STALE_AFTER_CLOSURE in settled, False)

    if failures:
        print(f"STAGE GUARD: VIOLATIONS ({len(failures)})")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("STAGE GUARD: no violations (stage model, role lookup, command shapes, seven rules, fail-open)")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage dispatch guard")
    ap.add_argument("--ticket", default="")
    ap.add_argument("--stage", default="")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--stories", action="store_true",
                    help="one line per open story (qa-doctor step 4) — no JSON in the caller's context")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if args.stories:
        sys.exit(stories())
    if args.ticket and args.stage:
        sys.exit(explain(args.ticket, args.stage))
    ap.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
