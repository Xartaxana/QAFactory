"""Role context injection at dispatch (PreToolUse: Task|Agent).

Layer 1 — factory-wide rules (the Tester's Manifesto + the role's own slice of the cross-cutting rules),
Layer 2 — the role's project slice (map: references/inject-map.json in the plugin).
We deliver instead of asking to read: a donor measurement showed 0 of 290
dispatched subagents opened a file they were told to read.

Path prefixes (unified-factory root split): every entry in inject-map.json is either
`plugin:<rel>` (resolved against PLUGIN_ROOT — rules, templates, checklists shipped in
the plugin's own git) or `project:<rel>` (resolved against project_root() — strategy,
config, anything onboarding or a story generated for THIS project). An entry with no
recognized prefix is treated as `project:` for backward compatibility with hand-written
maps, and a warning is printed once.

Stage guard hook point (C0): before injecting, this script imports stage_guard from the
scripts/ directory and runs its check(event) first. A non-zero return blocks the dispatch
before the role ever sees a prompt. A missing stage_guard.py is a no-op, not an error.
Every refusal on this path also appends one line to
`<task_root>/state/dispatch-denials.jsonl` — proof the agent never started, which is what
lets `recover` close a receipt left `running` instead of polling it forever (`note_denial`).

Rules:
- roster guard: an agent not in the map -> exit silently (never seed other
  agents of the same project — a real field incident at the donor);
- fail-open: a missing file / any failure -> the dispatch proceeds without the
  injection, with a note on stderr (unlike security guards, jamming the
  pipeline is not allowed here); a missing/absent inject-map.json (references/
  is being authored elsewhere) is treated as an empty map, not an error;
- mechanics: a PreToolUse JSON response with updatedInput — blocks are appended
  to the end of the dispatch prompt with explicit source headers. If the
  harness version does not support updatedInput, behavior degrades to no
  injection.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contract_slices import COMMON_LAYER_SUBJECTS, parse  # noqa: E402  (the one owner of "which slice is never named instead", and of what a section is)
from hooklib import PLUGIN_ROOT, person_signal, project_root, read_event, ref, role_name, take_notices, warn_once  # noqa: E402

MAX_BLOCK_CHARS = 26000  # fuse against inflating a dispatch with a giant file
# The heading of the resolved task packet: the one text the dispatch hook hands every real role dispatch of a story and the
# diagnostic probe never gets. `host_probe.check_role_context` looks for it in the first rows of a child's transcript as the
# evidence that a role's context was delivered (HF8-12, W-5); one constant so the writer and the reader cannot drift.
PACKET_HEADING = "# Resolved task packet"
# Field measurement: a project's test-strategy.md weighed 22,151 chars and at a fuse of
# 20,000 reached the strategist TRUNCATED - silently. The role that needs the strategy most
# got it without its tail, and nobody found out. The fuse stays (a dispatch must not inflate
# without bound) but is raised above the canon's typical size and made LOUD: truncation is
# now visible to the operator on stderr, not only as a line inside the prompt itself.


def load_map() -> dict:
    """references/inject-map.json is missing -> {} (fail-open: another agent may be
    authoring references/ right now; the plugin must not crash or block on it)."""
    try:
        return json.loads(ref("inject-map.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_entry(rel: str, event: dict | None = None) -> Path:
    """`plugin:<rel>` -> PLUGIN_ROOT/<rel>; `project:<rel>` -> project_root()/<rel>;
    no recognized prefix -> project:<rel> (backward-compat default)."""
    if rel.startswith("plugin:"):
        return PLUGIN_ROOT / rel[len("plugin:"):]
    if rel.startswith("project:"):
        root = project_root(event)
        default = root / rel[len("project:"):]
        # A separate or opted-in pre-existing strategy file replaces the conventional
        # generated path by basename.  This keeps inject-map portable and centralizes the
        # exact path decision in config.json.
        if "/strategy/" in rel.replace("\\", "/"):
            try:
                from config_contract import strategy_document
                from hooklib import load_config
                found = strategy_document(load_config(event), default.name)
                if found:
                    return root / found
            except Exception:
                pass
        return default
    return project_root(event) / rel


SLICE_REL_PREFIX = "plugin:references/slices/"


def slices_mode() -> str:
    """`inline` (default) or `on_demand` — how the role's own rule slices are delivered.

    The slices are the heaviest layer of a dispatch: 23.6 KB for the code critic against 8.9 KB
    of charter, re-billed on every turn (plan section 12). `on_demand` hands the role the paths
    and one line of what each file carries - the generated `references/slices/<role>/index.md` -
    and lets it read what its work touches, saving 15-20 KB a dispatch.

    It is OFF by default because of the measurement at the top of this file: 0 of 290 dispatched
    subagents opened a file they were told to read. That is the whole reason this layer delivers
    instead of naming, and one number against it is not enough to turn it off - `stage_compare` on
    a real story is. Until that number exists, a project that wants the saving asks for it.
    """
    try:
        from hooklib import load_config
        return str(((load_config() or {}).get("prompts") or {}).get("slices") or "inline")
    except Exception:
        return "inline"


def unavailable_block(event: dict | None, role: str, key: str, line: str) -> str:
    """H10-H12 (RH1-5 B9, FR-4, FR-59): what the dispatch could not give the role is said TO THE ROLE, as a block of its
    prompt, and to the person as a `hook_signal` of kind `inject` (once per session per `key`). A stderr note at exit 0
    reaches nobody on Claude Code; a role that does not know its rules file is missing works as if it had read it."""
    person_signal(event, "inject", f"role {role}: {line}", once_key=f"unavailable:{key}")
    return "\n\n---\n# Factory context unavailable\n" + line


def missing_line(rel: str, why: str) -> str:
    return f"your factory rules file {rel} {why}; work from the prompt and name it under blocked"


# --------------------------------------------------------------------------- dispatch kinds (RC1-14 part 2, N1)
# The kind of a dispatch decides which NAMED SECTIONS of a role's own slice the role is handed (`inject-map.json` `kinds`);
# `first` is the full text and the safe default. The one reader of the kinds: the hook, `role_load` (and through it audit A22)
# and the driver call `dispatch_kind`, `entries_for`, `delivered_text`; nothing else parses `kinds` (AR-13).
DISPATCH_KINDS = ("first", "repair", "rework")


def _filled(value) -> str:
    """The stripped text of a string value, "" for anything else (None, 0, a list): a field that is not a word is not a signal."""
    return value.strip() if isinstance(value, str) else ""


def dispatch_kind(record) -> str:
    """`repair` when the dispatch RECORD names the work it reworks AND a cause (`rework_of` and `repair_cause`), `rework` when
    it names only the work it reworks, else `first`. Pure, never raises, and errs only toward `first` (more rules, never fewer):
    a record that is not an object, an empty or blank field, a field that is not text are all `first`.

    The shapes are the controller's: a rework request carries `rework_of` (and `repair_cause` for a repair); a retry or a
    relaunch copies its parent's binding (`request_binding`), so a continuation of a repair is a repair BY ITS OWN FIELDS.
    `parent_retry` is therefore never read: a checkpoint-resumed FIRST window has it and no `rework_of` (`first`), and the
    environment stamp (`repair_cause: environment` on a start) has no `rework_of` either (`first`)."""
    try:
        if not isinstance(record, dict) or not _filled(record.get("rework_of")):
            return "first"
        return "repair" if _filled(record.get("repair_cause")) else "rework"
    except Exception:
        return "first"


def entries_for(role: str, imap: dict, kind: str = "first") -> list:
    """The inject-map entries a role is delivered: `common` then its own list. A kind never removes a WHOLE entry (it drops
    named sections of one, `delivered_text`), so `kind` does not change this list; it is in the signature so that every
    caller says which dispatch it speaks for."""
    common = imap.get("common") if isinstance(imap, dict) else None
    roles = imap.get("roles") if isinstance(imap, dict) else None
    own = roles.get(role) if isinstance(roles, dict) else None
    return list(common if isinstance(common, list) else []) + list(own if isinstance(own, list) else [])


def _dropped_headings(rel: str, role: str, imap: dict, kind: str) -> list:
    """The headings `imap["kinds"][kind][role]["drop_sections"][rel]` names, or [] for everything the map must not do (E1-E4): a
    missing or wrongly typed table, kind `first` or an unknown kind, an entry the role is not delivered, a `common` entry or a
    `common-rules.md` slice, an entry that is not a `plugin:` file. Never raises."""
    try:
        if kind == "first" or kind not in DISPATCH_KINDS or not isinstance(rel, str) or not rel.startswith("plugin:"):
            return []
        common = imap.get("common")
        if (rel in (common if isinstance(common, list) else []) or Path(rel).name in COMMON_LAYER_SUBJECTS
                or rel not in entries_for(role, imap, kind)):
            return []
        heads = imap["kinds"][kind][role]["drop_sections"][rel]
    except (KeyError, TypeError, AttributeError, IndexError):
        return []
    return [h for h in heads if isinstance(h, str)] if isinstance(heads, list) else []


def delivered_text(rel: str, text: str, role: str, imap: dict, kind: str = "first") -> str:
    """`text` of the entry `rel` as the role of dispatch `kind` is handed it: minus every section whose heading line the map lists
    under `kinds.<kind>.<role>.drop_sections.<rel>`. A section is what `contract_slices.parse` makes of the text (its own lines
    up to the next heading of any level: a `##` with `###` children drops only its own lines); a heading is matched exactly. A
    heading the text does not hold is ignored here and named by `map_problems`. The same text is the one `role_load` measures."""
    drop = _dropped_headings(rel, role, imap, kind)
    if not drop:
        return text
    lead, sections = parse(text)
    if not any(s.heading in drop for s in sections):
        return text
    lines = ([lead.rstrip("\n"), ""] if lead.strip() else [])
    for s in sections:
        if s.heading not in drop:
            lines += [s.heading] + s.lines
    return "\n".join(lines)


def map_problems(imap) -> list:
    """What the map's `kinds` table says that would not happen (E1-E4), one sentence each; [] for a table that is absent (E1) or
    sound. The shipped map is asserted clean by a test: the map says only what actually happens."""
    if not isinstance(imap, dict) or "kinds" not in imap:
        return []
    kinds = imap["kinds"]
    if not isinstance(kinds, dict):
        return ["`kinds` is not an object of dispatch kind -> role -> row: every dispatch is delivered the full text"]
    problems, common = [], imap.get("common") if isinstance(imap.get("common"), list) else []
    for kind, rows in kinds.items():
        if kind == "first" or kind not in DISPATCH_KINDS:
            problems.append(f"kinds.{kind}: not a kind that takes rows ({', '.join(k for k in DISPATCH_KINDS if k != 'first')}); "
                            f"`first` is always the full text")
            continue
        if not isinstance(rows, dict):
            problems.append(f"kinds.{kind}: not an object of role -> row")
            continue
        for role, row in rows.items():
            drop = row.get("drop_sections") if isinstance(row, dict) else None
            if not isinstance(drop, dict):
                problems.append(f"kinds.{kind}.{role}: `drop_sections` is not an object of entry -> headings")
                continue
            listed = entries_for(role, imap, kind)
            for rel, heads in drop.items():
                where = f"kinds.{kind}.{role}.drop_sections[{rel}]"
                if rel not in listed:
                    problems.append(f"{where}: the entry is not in the list of {role} in `roles`")
                elif rel in common or Path(str(rel)).name in COMMON_LAYER_SUBJECTS:
                    problems.append(f"{where}: a common entry or a common-rules slice is never cut (it reaches every dispatch)")
                elif not str(rel).startswith("plugin:"):
                    problems.append(f"{where}: only a `plugin:` entry can lose sections")
                elif not isinstance(heads, list) or not heads or not all(isinstance(h, str) for h in heads):
                    problems.append(f"{where}: not a non-empty list of heading lines")
                else:
                    try:
                        found = {s.heading for s in parse(resolve_entry(rel).read_text(encoding="utf-8", errors="replace"))[1]}
                    except OSError as exc:
                        problems.append(f"{where}: the file could not be read ({type(exc).__name__})")
                        continue
                    problems += [f"{where}: no section with the heading {h!r} in the text" for h in heads if h not in found]
    return problems


def collect_blocks(role: str, imap: dict, event: dict | None = None, kind: str = "first") -> list[str]:
    blocks: list[str] = []
    entries = entries_for(role, imap, kind)
    if slices_mode() == "on_demand":
        # The role's slice of the common rules is the one slice that is never "named instead":
        # the exclusion sits INSIDE the filter, before the catalogue is appended, so in either mode
        # the rules are in the prompt itself and not only a name in a list (the rules are obeyed,
        # not looked up).
        def named_instead(e) -> bool:
            return str(e).startswith(SLICE_REL_PREFIX) and Path(str(e)).name not in COMMON_LAYER_SUBJECTS
        named = [e for e in entries if named_instead(e)]
        if named:
            entries = [e for e in entries if not named_instead(e)]
            entries.append(f"{SLICE_REL_PREFIX}{role}/index.md")
    for rel in entries:
        f = resolve_entry(rel, event)
        if not f.exists():
            blocks.append(unavailable_block(event, role, rel, missing_line(rel, "is missing")))
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace").strip()
        except Exception as e:
            blocks.append(unavailable_block(event, role, rel,
                                            missing_line(rel, f"could not be read ({type(e).__name__})")))
            continue
        if len(text) > MAX_BLOCK_CHARS:
            warn_once(
                event,
                f"inject2-truncated:{rel}",   # a new key: an `inject-truncated` marker of the interim code said nothing to anybody
                f"INJECT: {rel} ({len(text)} chars) exceeds {MAX_BLOCK_CHARS} - "
                f"role {role} is blocked until a complete bounded slice is supplied. Split the file or raise "
                f"MAX_BLOCK_CHARS in scripts/inject_context.py.",
            )
            # No silent loss of required invariants. The bundle must be split by
            # its producer rather than giving the role a misleading partial file.
            raise ValueError(f"required context {rel} exceeds budget; prepare a bounded role slice")
        # AFTER the budget check, which judged the WHOLE file: a kind never hides an oversized one
        text = delivered_text(rel, text, role, imap, kind).strip()
        header = ("Your factory rules" if rel.endswith("common-rules.md")
                  else "Your rule files, by path" if rel.endswith("/index.md")
                  else "Your project context")
        note = ("read the files it names before you write your artifact"
                if rel.endswith("/index.md")
                else "delivered by injection at dispatch; no need to read the file again")
        blocks.append(f"\n\n---\n# {header} — {rel}\n({note})\n\n{text}")
    return blocks


DISPATCH_ID_RE = re.compile(r"(?im)^\s*dispatch[ _]id\s*[:=]\s*([\w.\-]+)")


def dispatch_id_of(event: dict) -> str | None:
    """The receipt this dispatch belongs to: the `Dispatch id: <id>` line the orchestrator
    puts in the prompt, or the field if a host passes one. None is an honest answer — the
    controller then matches the denial by role and stage instead."""
    ti = event.get("tool_input") or {}
    m = DISPATCH_ID_RE.search(str(ti.get("prompt") or ""))
    return m.group(1) if m else (str(ti.get("dispatch_id") or "") or None)


def note_denial(event: dict, ticket: str, stage, role, reason: str) -> None:
    """One JSON line in <task_root>/state/dispatch-denials.jsonl for a dispatch this hook
    refused.

    TP1-15045: `--operation dispatch` wrote a receipt, the `Agent` call was denied here,
    and nothing anywhere recorded that the agent never started. The controller then answered
    `wait_existing_job` with `cancel_allowed: false` forever — a story nobody, person or
    orchestrator, could move. `recover` closes such a dispatch as `never_started` on the
    strength of this file, so it is written before the hook exits. Best-effort by
    construction: a denial that cannot be written down must still be a denial.

    A denial with NO ticket has nowhere per-story to go, and until 0.7.12 it went nowhere at
    all — so `task identity is missing or ambiguous`, the one refusal whose diagnosis lives
    entirely in the event, was the only one never written down (TP2-2556: four denials
    over two days, no record). Those go to the project-level
    `qa-factory/state/dispatch-denials.jsonl` with the argument KEYS of both the normalized
    and the host's own input, the task name, and the reason — never the message body, which
    on Codex desktop is an opaque encrypted string and elsewhere a whole prompt."""
    try:
        from datetime import datetime, timezone
        from hooklib import artifact_root, is_story_folder
        if not ticket:
            return note_ticketless_denial(event, stage, role, reason)
        if not is_story_folder(artifact_root(event), ticket):
            # a ticket that names no story folder has nowhere per-story to go, and a hook never makes a story's folder
            # (CX1-18, E-8): the denial goes to the project's own list, naming the ticket, and is not lost
            return note_ticketless_denial(event, stage, role,
                                          f"{reason or 'denied'} (ticket {str(ticket)!r} names no story folder)")
        path = artifact_root(event) / ticket / "state" / "dispatch-denials.jsonl"
        path.parent.mkdir(exist_ok=True)               # `state/` under the story folder shown to exist, never above it
        row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "stage": stage or None, "role": role or None,
               "dispatch_id": dispatch_id_of(event), "reason": reason or "denied"}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def note_ticketless_denial(event: dict, stage, role, reason: str) -> None:
    """The project-level half of `note_denial` — see its docstring for why."""
    try:
        from datetime import datetime, timezone
        from hooklib import state_dir
        ti = (event or {}).get("tool_input") or {}
        raw = ((event or {}).get("_qa_host") or {}).get("input") or {}
        path = state_dir(event) / "state" / "dispatch-denials.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "ticket": None, "stage": stage or None, "role": role or None,
               "dispatch_id": dispatch_id_of(event),
               "tool_name": (event or {}).get("tool_name") or None,
               "host_tool_name": ((event or {}).get("_qa_host") or {}).get("name") or None,
               "tool_input_keys": sorted(str(k) for k in ti) if isinstance(ti, dict) else [],
               "host_input_keys": sorted(str(k) for k in raw) if isinstance(raw, dict) else [],
               "task_name": str(raw.get("task_name") or ti.get("task_name") or "") or None,
               "session_id": (event or {}).get("session_id") or None,
               "reason": reason or "denied"}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def run_stage_guard(event: dict) -> None:
    """C0 hook point: scripts/stage_guard.py gets first say on a dispatch. Its check()
    returns 0 (allow) or 2 (deny — the reason is already on stderr); a denial ends the
    hook here, so the role never sees a prompt. Its absence is not an error."""
    try:
        import stage_guard  # type: ignore
    except ImportError as exc:
        # still an allow (a missing guard is not a reason to stop every dispatch), but no longer a silent one: the
        # package ships stage_guard.py, so its absence or a broken import is an unknown the person is told (FR-59)
        person_signal(event, "inject", f"stage_guard.py could not be imported ({type(exc).__name__}: {exc}); "
                                       f"this dispatch was not checked against the stage order", once_key="stage_guard-import")
        return
    rc = stage_guard.check(event)
    if rc:
        last = getattr(stage_guard, "LAST_DENIAL", {}) or {}
        note_denial(event, str(last.get("ticket") or ""), last.get("stage"), last.get("role"),
                    str(last.get("message") or "denied"))
        sys.exit(rc)


def role_block(role: str, plugin_root=None, *, desktop_guide: bool = True):
    """The role file as a prompt block - ONE function for the two readers of the body (the Codex hook and the
    driver's `codex exec` prompt, CX1-15 F-3): `"\\n\\n# Factory role instructions: <role>\\n" + guide + body`, or None
    when the role file cannot be read. `plugin_root` is the package the role is read from (the hook: its own).

    TP2-2406 S3-4 (16.10): the frontmatter `tools:` line is split off here, and every other text names the
    Claude tools, so a role without Bash on Codex Desktop (no Read, Grep, Glob, Write or Edit there) never learned
    that it reads with `tools.exec_command` and edits with `tools.apply_patch`. The file is read ONCE and the
    question is asked of the same text (`host_adapter.tools_line`, the reader the guard also uses): a role without
    Bash (a missing or empty `tools:` line counts as none) gets `host_adapter.CODEX_DESKTOP_TOOLS` right under the
    heading, before the charter; a role with Bash gets today's bytes. `desktop_guide=False` leaves the Desktop block
    out: the driver's child is `codex exec` (a CLI), for which that text is wrong (the gap is named in the driver's
    journal instead)."""
    from host_adapter import CODEX_DESKTOP_TOOLS, tools_line
    try:
        text = (Path(plugin_root or PLUGIN_ROOT) / "agents" / (role + ".md")).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    body = text.split("---", 2)[-1] if text.startswith("---") else text
    guide = ("# Your tools on Codex Desktop\n" + CODEX_DESKTOP_TOOLS + "\n"
             if desktop_guide and "Bash" not in tools_line(text) else "")
    return "\n\n# Factory role instructions: " + role + "\n" + guide + body


def codex_role_instructions(blocks: list, role: str, event: dict | None = None) -> None:
    """Put the role file's body first among `blocks`, as Codex has no `agents/*.md` frontmatter to load (`role_block`
    builds it). The event is a Codex one, whichever of its hosts (CLI or Desktop); the block says itself that it is
    about Codex Desktop. A role file that cannot be read adds a line to the prompt that says so and a signal to the person
    (FR-4: an informed pass; injection never blocks a dispatch)."""
    block = role_block(role)
    if block is None:
        blocks.insert(0, unavailable_block(event, role, f"role-file:{role}",
                                           f"your role instructions file agents/{role}.md could not be read, so the Codex "
                                           f"tool guide is not in this prompt; work from the prompt and name it under blocked"))
        return
    blocks.insert(0, block)


def dry_run(raw_role: str) -> int:
    role = role_name(raw_role)
    imap = load_map()
    entries = entries_for(role, imap)
    if not entries:
        print(f"INJECT --dry-run: role '{role}' — no entries (inject-map.json missing or role not listed)")
        return 0
    for rel in entries:
        f = resolve_entry(rel)
        print(("ok      " if f.exists() else "missing ") + rel + f"  ({f})")
    for kind in DISPATCH_KINDS[1:]:
        for rel in entries:
            heads = _dropped_headings(rel, role, imap, kind)
            if heads:
                print(f"kind {kind} drops from {rel}: " + "; ".join(heads))
    for problem in map_problems(imap):
        print("map problem: " + problem)
    return 0


RECEIPT_REASON = "controller dispatch receipt required before role invocation"


def refuse_receipt(event: dict, ticket, role) -> None:
    """The refusal of a dispatch the controller's receipt does not cover (and of one whose controller.json cannot be read,
    E24): the same text, the same `note_denial` line, exit 2."""
    print("INJECT: " + RECEIPT_REASON, file=sys.stderr)
    # The same line the stage guard's denials leave: this refusal also ends a
    # dispatch that a receipt may already claim is running.
    note_denial(event, ticket, None, role, RECEIPT_REASON)
    sys.exit(2)


def main() -> None:
    """The PreToolUse hook of a dispatch. An unknown never passes silently (RH1-5 B9, AR-28): an event that cannot be
    parsed (H13) and any exception (H14) ALLOW the dispatch and leave a `hook_signal` of kind `inject` - the injection is
    not security-critical (F-11) - EXCEPT an existing controller.json that cannot be read AS A RECEIPT, which refuses as a
    missing receipt does (E24): a role never starts on a model the factory did not choose when the receipt cannot be read.
    Residual, by the owner's word (F-9/F-11): a crash AFTER the receipt was read allows the dispatch and leaves its signal.
    The advice queued on the way is delivered ONCE, at the end (on a rewrite: through `rewrite_output`)."""
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--role", default="")
    args, _ = ap.parse_known_args()
    if args.dry_run:
        sys.exit(dry_run(args.role))

    event = read_event()
    code, out = 0, {"rewritten": False}
    if event is None:
        person_signal(None, "inject", "the dispatch hook could not parse the host's event; this dispatch went ahead with no "
                                      "context injection and no stage check", once_key="event-unparsed")
    else:
        try:
            dispatch(event, out)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        except Exception as exc:
            # One signal per DISTINCT crash (type + message): a second, different crash in the session is not silent (F2).
            import hashlib
            crash = hashlib.sha1(f"{type(exc).__name__}|{exc}".encode("utf-8", "replace")).hexdigest()[:10]
            person_signal(event, "inject", f"the dispatch hook failed ({type(exc).__name__}: {exc}); this dispatch went ahead "
                                           f"with no context injection and no stage check",
                          once_key=f"dispatch-crashed-{type(exc).__name__}-{crash}")
    # After a rewrite the queue was already drained into `rewrite_output` (stdout keeps its one JSON object).
    take_notices(event, code)
    sys.exit(code)


# The keys of a dispatch RECORD a role is handed, beyond `id`, `stage`, `role`, `kind`, `scope` (which are always there): each is
# read by a role-facing text or by the brief (the builder's N1 report lists the readers of every key of the record, kept or
# dropped). Everything else on the record is the controller's bookkeeping (`input_hash`, `idempotency_key`, `expected_revision`,
# `resolved_model`, `budget`, `status`, `agent_id`, `request_binding`, `dispatched_seq`, stamps, `limits`, `person_words`, ...)
# and the role never reads it; `known_paths` travels ONCE, at the top of the packet.
PACKET_DISPATCH_KEYS = ("purpose", "reason", "rework_of", "parent_retry", "relaunch_of", "repair_cause", "repair_cause_source",
                        "read_first", "checkpoint", "case_version_links", "plan_rows", "manual_case_ids", "execution_kind",
                        "retry_reason", "retry_words")


def _has_value(value) -> bool:
    """Present AND non-empty: None, "" (blank), [] and {} carry nothing a role could read."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return not (isinstance(value, (list, dict)) and not value)


def task_packet(ticket, state: dict, record, known: dict, dispatch_id=None, role=None, scope=None) -> dict:
    """The task packet the hook hands a role: ONE `known_paths`, and the running dispatch as a whitelisted projection.

    `known` is the state's `known_paths` ALREADY resolved for this project and package (the caller resolves; a stored path is
    never handed over unresolved, axis 8). The record's own `known_paths`, when the caller has resolved it too, is laid over
    it: the record wins on a key both name, a key only the state holds is kept (E10). The projection of the record is
    `{id, stage, role, kind, scope}` plus the keys of `PACKET_DISPATCH_KEYS` that are present and non-empty; `kind` is
    `dispatch_kind(record)`. A record that is not an object (no running dispatch) projects as kind `first`, with `role` and
    `scope` from the arguments (the state's scope when `scope` is None); a record that lacks `role` or `scope` takes them from
    the arguments the same way."""
    rec = record if isinstance(record, dict) else {}
    merged = dict(known) if isinstance(known, dict) else {}
    if isinstance(rec.get("known_paths"), dict):
        merged.update(rec["known_paths"])
    state_scope = state.get("scope", []) if isinstance(state, dict) else []
    own_scope = rec.get("scope") if isinstance(rec.get("scope"), list) else (scope if scope is not None else state_scope)
    projection = {"id": rec.get("id") or dispatch_id, "stage": rec.get("stage"), "role": rec.get("role") or role,
                  "kind": dispatch_kind(record), "scope": own_scope}
    projection.update({key: rec[key] for key in PACKET_DISPATCH_KEYS if _has_value(rec.get(key))})
    return {"task_id": ticket, "revision": state.get("revision") if isinstance(state, dict) else None,
            "known_paths": merged, "scope": state_scope, "dispatch": projection}


def dispatch(event: dict, out: dict) -> None:
    """The body of the hook; leaves through `sys.exit`, as it always did. `out["rewritten"]` is set before the rewrite
    object is printed."""
    tool = event.get("tool_name")
    if tool not in ("Task", "Agent", "SendMessage"):
        sys.exit(0)

    from host_adapter import is_codex, role_policy
    if is_codex(event):
        from worker_lifecycle import guard
        from hooklib import load_config
        guard(event)
        role_policy(event, load_config(event))
    run_stage_guard(event)

    if tool == "SendMessage":
        # A resume goes to an agent that already carries its injected context; sending it
        # again would deliver every reference twice. The guard above is the whole reason
        # this tool is matched at all (stage_guard rule 6).
        sys.exit(0)

    ti = dict(event.get("tool_input", {}) or {})
    role = role_name(ti.get("subagent_type", ""))
    prompt = ti.get("prompt")
    imap = load_map()
    if not imap or not prompt or role not in imap.get("roles", {}):
        sys.exit(0)  # roster guard: foreign agent / nothing to inject
    # The receipt is read BEFORE the fail-open injection, so a crash in the injection cannot skip it (E24). An existing
    # controller.json that cannot be read AS A RECEIPT (not JSON, not an object, `dispatches` not an object of objects,
    # `resolved_model` not an object) refuses: a role never starts on a model the factory did not choose (F-11, AR-28).
    from stage_guard import requested_ticket
    ticket = requested_ticket(event)
    state, task_root, matching = None, None, []
    if ticket:
        from hooklib import artifacts_dir, read_json
        task_root = artifacts_dir(ticket, event)
        controller_path = task_root / "state" / "controller.json"
        if controller_path.exists():
            state = read_json(controller_path, kind=dict, errors=Exception)
            if state is None:
                refuse_receipt(event, ticket, role)       # E24: an existing controller.json that cannot be read refuses
            try:
                matching = [d for d in state.get("dispatches", {}).values()
                            if d.get("role") == role and d.get("status") == "running"]
                resolved = matching[0].get("resolved_model", {}) if matching else {}
                if not isinstance(resolved, dict):
                    raise TypeError("resolved_model is not an object")
                has_source = bool(state.get("source_revision"))
            except (AttributeError, TypeError):
                refuse_receipt(event, ticket, role)
            if has_source and len(matching) != 1:
                refuse_receipt(event, ticket, role)
            if matching:
                from host_adapter import is_codex
                if resolved.get("model") not in (None, "inherit"):
                    ti["model"] = resolved["model"]
                if is_codex(event):
                    if resolved.get('effort') not in (None,'inherit'):
                        ti['reasoning_effort'] = resolved['effort']
                    native = (event.get('_qa_host') or {}).get('input', {})
                    if 'agent_type' in native:
                        from codex_roles import check_override
                        from hooklib import project_root
                        try: check_override(project_root(event), role, resolved)
                        except ValueError as exc:
                            print(str(exc), file=sys.stderr); sys.exit(2)
    last = matching[-1] if matching else None          # the running dispatch of this role: the one record the hook speaks for
    try:
        blocks = collect_blocks(role, imap, event, dispatch_kind(last))
        from host_adapter import is_codex
        if is_codex(event):
            codex_role_instructions(blocks, role, event)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        # TP1-15045 class: a receipt says running and the agent never starts. The refusal leaves the same line every other
        # refusal of this hook leaves, so `recover` can close the receipt (the over-budget path wrote none before)
        note_denial(event, ticket, None, role, str(exc))
        sys.exit(2)
    if state is not None:
        # t-304 N1 (readers #3 and #6): the paths a role is handed are the paths of THIS project and THIS package,
        # resolved now - the state's stored ones are hints (a copied story kept the old worktree's root and the
        # frozen package of another generation, and the role was told to work there). A value that cannot be
        # resolved is left out, never named; a failure here leaves the paths out and never falls back to the stored
        # ones (the injection is fail-open, a foreign path is not an acceptable fallback).
        paths_line = ""
        try:
            from runtime_paths import state_paths
            from hooklib import project_root as hook_project_root      # `project_root` is imported again below
            here = hook_project_root(event)
            known = state_paths(state.get("known_paths", {}), task_root, project=here, plugin=PLUGIN_ROOT, kind="INJECT")
            if isinstance(last, dict) and isinstance(last.get("known_paths"), dict) and last["known_paths"]:
                last = dict(last, known_paths=state_paths(last["known_paths"], task_root, project=here,
                                                          plugin=PLUGIN_ROOT, kind="INJECT"))
        except Exception as exc:
            paths_line = (f"the task packet carries no paths: the stored paths could not be resolved "
                          f"({type(exc).__name__}: {exc}); work from the prompt and name it under blocked")
            known = {}
            if isinstance(last, dict) and "known_paths" in last:
                last = dict(last, known_paths={})
        packet = task_packet(ticket, state, last, known, role=role)
        blocks.append("\n\n" + PACKET_HEADING + " (reuse paths and completed checks)\n" + json.dumps(packet))
        if paths_line:
            blocks.append(unavailable_block(event, role, "packet-paths", paths_line))
    from metric_signals import context as signal_context
    from hooklib import project_root
    notice = signal_context(project_root(event))
    if notice:
        blocks.append('\n\n' + notice)
    if not blocks:
        sys.exit(0)
    from host_adapter import is_codex
    if is_codex(event):
        # Native spawn messages can be encrypted. Rewriting them corrupts host history.
        from native_context import stage
        from host_probe import injection_marker
        context = ''.join(blocks) + injection_marker(project_root(event), event)
        try:
            stage(project_root(event), event, role, context, ticket)
        except ValueError as exc:
            print('INJECT: ' + str(exc), file=sys.stderr)
            sys.exit(2)
        sys.exit(0)
    ti["prompt"] = str(prompt) + "".join(blocks)
    from host_probe import injection_marker
    ti["prompt"] += injection_marker(project_root(event), event)
    from host_adapter import rewrite_output, rewritten_input
    try: ti = rewritten_input(event, ti)
    except ValueError as exc:
        print(str(exc), file=sys.stderr); sys.exit(2)
    # The advice queued on the way goes to `rewrite_output` as its `context`: the host adapter alone decides where an
    # advice beside `updatedInput` goes (it reaches nobody there, B0 a), so the queue is empty when `main` ends.
    import hooklib
    queued = hooklib.drain_notices()
    out["rewritten"] = True
    rewrite_output(event, ti, "\n".join(text for text, _reader in queued))
    sys.exit(0)


if __name__ == "__main__":
    main()
