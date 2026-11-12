"""Builds the gate A brief BY CODE, so closing S4 and asking gate A always fits in a window.

On TP1-15045 the orchestrator stopped one step short of gate A "because this window is
far past its turn budget, and the gate brief should be built in a fresh one". That is only
true of a brief assembled out of the orchestrator's context — reading the plan, the cases,
the critic's findings and the waivers costs more than the window had left. Built by code
from the files those roles already wrote, the brief costs one tool call, so the rule "the
gate is asked in the window that closed the stage before it" (window_budget.py) can hold.

  gate_brief.py --task TP1-15045
  gate_brief.py --task TP1-15045 --output <path>     # an extra copy elsewhere, not the gate's record
  gate_brief.py --task TP1-15045 --json

Gate A on the skill path also writes the message it prints, whole, to `<task>/work/gate-a-message.md` (and the record of
that write to `<task>/state/gate-message.json`): that file is what the person reads, and the conductor prints it as it is
(`gate_shown.py` checks the turn). `--output` is a second copy wherever the caller asks.

What it reads, all of it already on disk: `work/test-plan.json` (the pyramid: rows per
level and disposition), the pinned case links (`state/story-case-links.json`), the case
critic's verdict and the rows it did not review semantically, the decisions a person already
made (`pipeline.json` `gate_waivers[]` and `stage_overrides[]` — the same data
`waiver.py --list` prints), accepted source gaps and sources found after the S1 review
(`source_inventory.completeness` / `review_rows(only_unreviewed=True)`), the open questions
of `work/requirements-readiness.json`, and the warnings `pipeline.json` carries.

It also WRITES one thing: on the skill path, `--gate A` (not `--json`) records which attachments the printed packet NAMED
(`state/driver-state.json` `shown_attachments`, `keep_shown_attachments`), unless a current approved decision of gate A already
stands (the person has answered; a later print shows nothing new to them) or the story folder does not exist.

It never summarises the long documents — it links them. The brief is a cover sheet of at
most ~40 lines with the paths of what the person may open; the plan, the appendix and the
findings stay where they are. A missing input is reported as a missing input, never guessed
and never silently dropped: a brief that hides what it could not read is worse than one
that says so.

`--gate B` renders the numbered bug list the person answers — by code, from the drafts on
disk. The owner's decision of 21.09.2026: the factory shows the bugs as a list in the chat and
files the ones the person approved. Each row is self-contained — number, title, impact turned
into a priority, one line of what is broken and how to see it, the draft's path, and the
duplicate the draft itself names — so the answer can be "file 1 and 3, 2 is not a bug" without
opening anything. This list REPLACES the one-line-per-draft item s8.md used to compose; the
delivery summary and the test report stay where they are and are linked, never summarised.
"""
import argparse
import functools
import json
import os
import re
import string
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hooklib  # noqa: E402
from hooklib import artifacts_dir, require_project  # noqa: E402
import contract as C  # noqa: E402
from hooklib import sorted_paths  # noqa: E402

MAX_LINES = 40
# Gate B's list is three lines per bug by construction, so its cap is a count of BUGS, not of
# lines: a delivery with fourteen bugs is a real delivery, and folding its list would put the
# person back to opening files to answer.
MAX_BUGS = 15
# One bug drafted from several ways it shows (t-2187): the packet lists this many ways under a bug and says how many more there are;
# the readable text of the bug holds them all.
MAX_MANIFESTATIONS_SHOWN = 6
# There is no cap on the number of questions the cover sheet shows. It was 6, and on TP1-13797
# the packet said "Open questions (11)" over six cards: five questions a person had to decide
# were cut without a word (FR-41, B-216). Every open question gets its card; a story that has
# many of them says so in the count, and the cards stay whole (see `question_card`).
VERDICT_RE = re.compile(r"verdict(?:\s+round\s+\d+)?\s*:\s*([A-Za-z_]+)", re.IGNORECASE)
# The draft's own way of naming a tracker issue it may duplicate. The role writes one of
# these; the person decides whether it really is one.
DUPLICATE_KEYS = ("possible_duplicate", "duplicate_of", "similar_to", "duplicate")


def judge_facts(task: str, task_root: Path) -> dict:
    """What the System One judge did for this story - empty when no judge is configured.

    The person approving a plan or a delivery is entitled to know that something other than
    the roles they can name had a say, how much of the work it decided, and - the part that
    matters - every block of the factory's own it let through. `judge.passes()` is that list;
    it is small by construction, because only refusals of FORM and DIAGNOSIS may be judged.
    """
    try:
        import judge
        cfg = judge.settings(task_root)
        if cfg["provider"] == "none":
            return {}
        root = cfg["project_root"]
        bill = judge.summary(root, task)
        return {"provider": cfg["provider"], "mode": cfg["mode"], "questions": bill["questions"],
                "decided": bill["decided"], "cost_usd": bill["cost_usd"], "errors": bill["errors"],
                "passes": [{"refusal": row.get("refusal"), "judgment": row.get("judgment"),
                            "stage": row.get("stage"),
                            "strength": row.get("probability") if row.get("probability") is not None
                            else row.get("confidence")}
                           for row in judge.passes(root, task)]}
    except Exception:
        return {}  # a judge that cannot be read is not a reason to withhold the brief


def judge_lines(facts: dict) -> list:
    """The `## Judge` block, or nothing at all when `judge.provider` is `none`."""
    if not facts:
        return []
    share = f"{facts['decided']} of {facts['questions']} decided" if facts["questions"] else "nothing asked"
    lines = ["## Judge",
             f"- `{facts['provider']}` in mode `{facts['mode']}`: {share}, "
             f"${facts['cost_usd']:.4f}."
             + (" Answers were journalled and nobody acted on them." if facts["mode"] != "on" else "")]
    if facts.get("errors"):
        lines.append(f"- {facts['errors']} question(s) the judge could not answer; the role did those.")
    passes = facts.get("passes") or []
    if not passes:
        lines.append("- No block of the factory's own was passed by the judge.")
    else:
        lines.append(f"- {len(passes)} block(s) it let through - say the word and any of them comes back:")
        for row in passes[:8]:
            lines.append(f"  - `{row.get('refusal')}` passed by `{row.get('judgment')}` "
                         f"p={row.get('strength')} ({row.get('stage') or 'stage unrecorded'})")
        if len(passes) > 8:
            lines.append(f"  - (+{len(passes) - 8} more in `state/judgments.jsonl`)")
    return lines


# The shared reader with this module's direction: any file or path that cannot be read is the caller's `default` (t-666 R2).
# A partial is safe here: `default` is passed by the caller on each call, and nothing is shared between calls.
read_json = functools.partial(hooklib.read_json, errors=Exception)


def plan_rows(task_root: Path) -> tuple:
    """(rows, path) from work/test-plan.json, whichever shape it has on disk.

    0.7.4 writes a bare list; an older build wrapped it in `{"rows": [...]}`. A story in
    flight must not be refused over the shape of a file written by the build before this
    one."""
    path = task_root / "work" / "test-plan.json"
    data = read_json(path)
    if isinstance(data, dict):
        for key in ("rows", "scenarios", "plan"):
            if isinstance(data.get(key), list):
                return data[key], path
        return [], path
    return (data if isinstance(data, list) else []), path


def pyramid(rows: list) -> dict:
    """Rows per level and disposition — the count the owner's 11.09 rule is argued from
    (`automate` only for the greatest risk), shown at the gate instead of asserted."""
    levels = Counter()
    dispositions = Counter()
    pairs = Counter()
    for row in rows:
        if not isinstance(row, dict):
            continue
        level = str(row.get("level") or "unstated") or "unstated"
        disposition = str(row.get("disposition") or "unstated") or "unstated"
        levels[level] += 1
        dispositions[disposition] += 1
        pairs[(level, disposition)] += 1
    return {"total": len(rows), "by_level": dict(levels), "by_disposition": dict(dispositions),
            "by_level_disposition": {f"{a}/{b}": n for (a, b), n in sorted(pairs.items())}}


def critic_path(task_root: Path) -> Path | None:
    candidates = sorted_paths((task_root / "work" / "test-cases").rglob("critic-findings.md")) \
        if (task_root / "work" / "test-cases").is_dir() else []
    return candidates[0] if candidates else None


def roll_call(task_root: Path, findings: Path | None) -> dict:
    """The critic's completeness roll-call: the machine-readable one when the case critic
    wrote it, otherwise parsed out of the findings table.

    The case critic may write a machine-readable form; until every project has it, the markdown
    table is the fallback. `source: none` means the roll-call could not be read at all —
    which is itself a line in the brief, because "the critic reviewed 8 of 15 rows" is
    exactly the fact TP1-15045 lost."""
    for name in ("critic-roll-call.json", "roll-call.json", "critic-findings.json"):
        for base in ([findings.parent] if findings else []) + [task_root / "work" / "test-cases",
                                                               task_root / "work"]:
            data = read_json(Path(base) / name)
            rows = data.get("rows") if isinstance(data, dict) else data
            if isinstance(rows, list) and rows:
                unreviewed = [str(r.get("case") or r.get("case_id") or r.get("ts") or "?")
                              for r in rows if isinstance(r, dict)
                              and not _row_reviewed(r)]
                return {"source": str(Path(base) / name), "total": len(rows),
                        "unreviewed": unreviewed}
    if findings and findings.is_file():
        try:
            text = findings.read_text(encoding="utf-8")
        except Exception:
            text = ""
        # One reader for one fact (FR-10, FR-17): `critic_rollcall` owns this table, and the
        # gate brief used to parse it again with a regex of its own — including the phrase list
        # over the status cell that FR-12 is about. A row the table says nothing about is
        # `unstated` here too, and the brief prints that word instead of "reviewed".
        import critic_rollcall as R
        rows = R.parse_rollcall(text)
        if rows:
            facts = R.derive(rows)
            named = {row["case"] or row["plan_row"]: f"{row['plan_row']} ({row['case']})".strip()
                     for row in rows}
            return {"source": str(findings), "total": facts["total"],
                    "unreviewed": [named.get(case, case) for case in facts["unreviewed"]],
                    "unstated": [named.get(case, case) for case in facts["unstated"]]}
    return {"source": "", "total": 0, "unreviewed": [], "unstated": []}


def _row_reviewed(row: dict) -> bool:
    if isinstance(row.get("reviewed"), bool):
        return row["reviewed"]
    status = str(row.get("status") or row.get("review") or "").lower()
    return bool(status) and "not semantically reviewed" not in status and "not reviewed" not in status


def verdict(findings: Path | None) -> str:
    """The critic's latest verdict. Later rounds are prepended above earlier ones, so the
    first match in the file is the current one."""
    if not findings or not findings.is_file():
        return ""
    try:
        match = VERDICT_RE.search(findings.read_text(encoding="utf-8"))
    except Exception:
        return ""
    return match.group(1).strip() if match else ""


# The same caps as the section's other lines: five per group, a reason clipped to 120 characters.
LEFT_OUT_CAP = 5
LEFT_OUT_CLIP = 120


def left_out_sources(task_root: Path) -> list:
    """The person's word about sources, given before the run (`work/source-exclusions.json`), as rows
    - ONE reader for the fact, used by gate A and by the retro (FR-10, FR-17):

      {id, as_written, reason (whole), origin, matched, revoked, revoked_words}

    `matched` is True when a source or an item of the inventory carries the exclusion's mark (a revoked
    one: carried it before it was taken back), False when the inventory was read and nothing did, and
    None when the inventory could not be read - "matched nothing" is never claimed without looking
    (FR-41). [] when the story has no record (a story without a list is today's story). An unreadable
    record RAISES `source_exclusions.ExclusionRecordError`: the caller says it could not read it."""
    import source_exclusions
    record = source_exclusions.read_record(Path(task_root) / "work")
    if not record or not record.get("exclusions"):
        return []
    inventory = read_json(Path(task_root) / "work" / "source-inventory.json")
    carried = None
    if isinstance(inventory, dict):
        import source_inventory
        carried = {ident for _sid, _url, ident in source_inventory.marks_in(inventory)}
        for item in inventory.get("sources", []):
            rows = source_inventory._item_rows((item.get("materials") or {}).get("external_media") or {})
            for entry in [item, *rows]:
                carried.update(mark.get("exclusion") for mark in entry.get("excluded_by_history") or []
                               if isinstance(mark, dict))
    return [{"id": e.get("id"), "as_written": str(e.get("as_written") or ""),
             "reason": str(e.get("reason") or ""), "origin": e.get("origin"),
             "matched": None if carried is None else e.get("id") in carried,
             "revoked": bool(e.get("revoked_at")),
             "revoked_words": str(e.get("revoked_words") or "")}
            for e in record["exclusions"] if isinstance(e, dict)]


def left_out_lines(rows, clip_to: int | None = None, cap: int | None = None) -> list:
    """What the person is told about the sources they left out before the run, as plain lines (no bullet).

    In three groups, each in the record's order: what was left out (the reason in the person's own words,
    clipped to `clip_to` when given), what the list named that no source carried (never an error: a stale
    word is information, F2e), and what the person took back (`taken back: ...`, history and not a
    pass - never counted among what is left out). `cap` limits each group, then "and N more". A word whose
    origin is not the person's own (B-232's marker of the factory) says so instead of "by your word"."""
    import source_exclusions

    def said(text: str) -> str:
        return source_exclusions.clip(text, clip_to) if clip_to else str(text)

    def own(row) -> bool:
        return row.get("origin") == source_exclusions.ORIGIN_PERSON

    rows = [r for r in rows or [] if isinstance(r, dict)]
    left = [r for r in rows if not r.get("revoked") and r.get("matched")]
    stale = [r for r in rows if not r.get("revoked") and r.get("matched") is False]
    unchecked = [r for r in rows if not r.get("revoked") and r.get("matched") is None]
    back = [r for r in rows if r.get("revoked")]
    groups = (
        (left, lambda r: (f"left out before the run by your word: {r['as_written']} — \"{said(r['reason'])}\""
                          if own(r) else
                          f"left out by the factory's own marker: {r['as_written']} — \"{said(r['reason'])}\""),
         "left out before the run"),
        (stale, lambda r: (f"your list named {r['as_written']}, and no source of this story carried it"
                           if own(r) else
                           f"the factory's own marker named {r['as_written']}, and no source of this story "
                           "carried it"),
         "named and carried by no source"),
        (unchecked, lambda r: f"your list named {r['as_written']}; whether a source of this story carried it "
                              "could not be read",
         "not checked"),
        (back, lambda r: f"taken back: {r['as_written']}" + (f" — \"{said(r['revoked_words'])}\""
                                                              if r.get("revoked_words") else ""),
         "taken back"))
    lines = []
    for members, text, label in groups:
        shown = members if cap is None else members[:cap]
        lines += [text(r) for r in shown]
        if len(shown) < len(members):
            lines.append(f"and {len(members) - len(shown)} more {label}")
    return lines


def left_out_block(task_root: Path) -> dict:
    """The keys `sources()` adds: the rows split by what the person is told, and - when the record exists
    and cannot be read - that, in its own key (a factory defect reported, FR-3; never a silent skip)."""
    try:
        rows = left_out_sources(task_root)
        unread = ""
    except Exception as exc:
        rows, unread = [], f"{type(exc).__name__}: {' '.join(str(exc).split())[:200]}"
    return {"left_out_by_word": [r for r in rows if not r["revoked"] and r["matched"]],
            "unmatched_words": [r for r in rows if not r["revoked"] and r["matched"] is False],
            "unchecked_words": [r for r in rows if not r["revoked"] and r["matched"] is None],
            "taken_back": [r for r in rows if r["revoked"]],
            "left_out_unread": unread}


def sources(task_root: Path) -> dict:
    """Accepted gaps and sources the S1 review has not seen, straight from the inventory; and what the
    person left out before the run (`left_out_block`)."""
    out = sources_inventory(task_root)
    out.update(left_out_block(task_root))
    return out


def sources_inventory(task_root: Path) -> dict:
    inventory = read_json(task_root / "work" / "source-inventory.json")
    if not isinstance(inventory, dict):
        return {"read": False, "accepted_gaps": [], "unreviewed": [], "blocking": []}
    try:
        import source_inventory
        kinds = source_inventory.class_kwargs(task_root)
        state = source_inventory.completeness(inventory, **kinds)
        late = source_inventory.review_rows(inventory, only_unreviewed=True)
    except Exception:
        return {"read": False, "accepted_gaps": [], "unreviewed": [], "blocking": []}
    by_id = {item.get("source_id"): item for item in inventory.get("sources", [])}

    def key_of(source_id: str) -> str:
        item = by_id.get(source_id) or {}
        return str(item.get("canonical_ref") or source_id).rsplit("/browse/", 1)[-1]

    def gap_line(source_id: str) -> str:
        """The ticket and the person's own words - the point acceptance's and the kind record's, ONE helper
        (`source_inventory.gap_words`) - and, for a kind, whose answer it was and when (D-0047): a bare SRC-hash tells the
        person nothing."""
        key = key_of(source_id)
        words = " ".join(source_inventory.gap_words(by_id.get(source_id) or {}, state.get("closed_by_class"),
                                                    kinds["classes"]).split())
        basis = source_inventory.class_basis(state.get("closed_by_class"), kinds["classes"], source_id)
        line = f'{key}: "{words[:120]}"' if words else key
        return line + (f" ({basis})" if basis else "")

    # What the factory itself established it cannot reach (D-0043): recorded, not asked. One row per point, with the
    # cause and the carrier - the person who restores access (a VPN, a login) says so to the conductor (FR-57).
    defaulted = [f"{key_of(sid)}: {point['name']} - {point['cause']} ({point['basis']})"
                 for sid, points in (state.get("defaulted_points") or {}).items() for point in points]
    return {"read": True,
            "accepted_gaps": [gap_line(sid) for sid in (state.get("accepted_gaps") or [])],
            "defaulted": defaulted,
            "unreviewed": [f"{row.get('key')} ({row.get('decision')})" for row in late],
            "blocking": list(state.get("errors") or state.get("blocking") or [])}


def portable(path, task_root: Path) -> str:
    """Project-relative with forward slashes: the brief is pasted into a message, and a
    machine path in it is neither clickable nor anybody else's path."""
    try:
        target = Path(path).resolve()
        base = _project_root_of(task_root)
        if base is not None:
            return target.relative_to(base).as_posix()
        return target.relative_to(task_root.resolve().parent).as_posix()
    except Exception:
        return Path(str(path)).name


def unearned_automation(rows) -> list:
    """Plan rows automated at e2e-ui level without a highest-risk reason.

    `planning_contract.plan_warnings` prints these at the S3 exit, where a passing detector's
    output reaches nobody. Whether ten e2e tests are worth writing is the strategist's judgement,
    shown for information: the ids go in front of the person at gate A, as a line and not a question.
    A branch entry is `TS-1 (Q2 = a): ...`; the id is the part before the first space, once per row."""
    try:
        import planning_contract
        found = planning_contract.plan_warnings(rows)
    except Exception:
        return []
    ids = [str(w).split(":", 1)[0].strip().split(" ", 1)[0] for w in found]
    return list(dict.fromkeys(i for i in ids if i))


def rehearsal(task_root: Path, gate: str = "A") -> dict:
    """The gate rehearsal, so the packet can say what happens AFTER the approval.

    The owner's rule of 21.09: a gate is not shown while the factory still lacks something it
    will need once the person has answered. The brief carries the rehearsal's verdict because
    the brief is what the person reads — a check whose result nobody sees is not a check."""
    try:
        import gate_preflight
        return gate_preflight.run(task_root, gate)
    except Exception as exc:
        return {"gate": gate, "next_stage": "", "can_proceed": False, "findings": [],
                "unavailable": f"{type(exc).__name__}: {exc}"}


# RH1-6 (owner's F-2, 27.10.2026): a `person_decides` finding that a FRESH rehearsal still lists has not been answered - `Rehearsal.add`
# already drops what a person's recorded word passes (`waiver.split_overridden` over `matched_text`), so "answered" has ONE reading and this
# is its ONE reader (AR-13): the controller's recording check, the gate packet's line and `open_before_mr` all read it.
OPEN_ITEM_BLOCK_LIMIT = 60       # `Rehearsal.door` cuts a block at 60 characters, and so does the `words` block of an item


def _words_block(message, stage, finding_id="") -> str:
    """The block a recorded word can pass a doorless item by: the longest prefix of the STORED message, at most 60 characters, that
    holds no `"` (a quote is read back as another character by the CLI) and not the finding's own id (the rehearsal drops by the RAW
    message, where that id is still the `<check-id>` placeholder; `Rehearsal.add` has replaced it in the stored text, so a block that
    crossed it would never match the raw text - the stop is on the id itself, not on the placeholder, which the stored text no longer
    holds), spaces normalised - or "" when no such prefix PASSES the item. A `<gap-name>` replaced the same way cannot be stopped at
    (its text is the gap's own name); the messages that hold one all carry a card door, so they are `line` items, never reach here.

    The prefix is offered only after the SELF-CHECK: `waiver.split_overridden` over `gate_preflight.matched_text` themselves, the very pair
    `Rehearsal.add` drops a finding by - never a second normaliser (AR-13). A block that cannot drop its item would be an endless
    refusal (AR-25), so it is never offered; the caller reads "" as door kind `none`."""
    try:
        import gate_preflight
        from waiver import split_overridden
        text = " ".join(str(message or "").split())
        cut = len(text)
        for stop in ('"', str(finding_id or "")):
            at = text.find(stop) if stop else -1
            if at != -1:
                cut = min(cut, at)
        block = text[:min(cut, OPEN_ITEM_BLOCK_LIMIT)].strip()
        shown = gate_preflight.matched_text(str(message or ""), [])
        while block:
            probe = {"stage_overrides": [{"stage": stage, "match": block, "decision": "x"}]}
            if split_overridden([shown], probe, stage)[1]:
                return block
            # A cut in the middle of a word is no whole identifier of the message (`contract.names_whole`): the door the code
            # prints must pass its own check (AR-25, GW1-1 P10), so the block steps back to the previous space and is asked again.
            space = block.rfind(" ")
            block = block[:space].strip() if space > 0 else ""
        return ""
    except Exception:
        return ""


def _open_item(finding: dict, stage: str) -> dict:
    """One open `person_decides` finding as `{id, check, message, door}` (spec RH1-6 A-AC2). The door is the finding's own
    `accept`/`any` entry of `waives` (kind `line`: the person writes it while the gate question is open), else a self-verified
    `words` block, else `none` (only `approve as is` passes it). A `handed` door is never chosen for the person (A-E18)."""
    waives = [w for w in finding.get("waives") or [] if isinstance(w, dict)] if isinstance(finding.get("waives"), list) else []
    says = " ".join(str(finding.get("fix") or "").split()) or "your word on it, in your own words"
    message = " ".join(str(finding.get("message") or "").split())
    usable = next((w for w in waives if str(w.get("block") or "").strip() and w.get("option") in ("accept", "any")), None)
    if usable:
        door = {"kind": "line", "says": says, "block": " ".join(str(usable["block"]).split()),
                "stage": str(usable.get("stage") or stage), "waives": waives}
    else:
        block = _words_block(finding.get("message"), stage, finding.get("id"))
        door = {"kind": "words" if block else "none", "says": says, "block": block, "stage": stage if block else "",
                "waives": waives}
    return {"id": str(finding.get("id")), "check": str(finding.get("check") or ""), "message": message, "door": door}


AS_IS_STAGE = "S4"       # the stage `approve as is` records its per-item words at (`none_item_block`)


def none_item_block(gate: str, item: dict) -> str:
    """The block `approve as is` records for ONE item whose door is `none` (nothing a recorded word on the rehearsal's own text can
    pass), at `AS_IS_STAGE`: `gate A item without a door: [<id>] <the first 60 characters of its message>` - one waiver per item, never
    one block for all of them and never `*`. The message is part of the block on purpose: the rehearsal numbers its findings afresh
    on every run, so a waiver written for `[X-1]` must not pass a different finding that has become `[X-1]` (the id alone would; the
    allowed error is asking again). The generic `gate A open items: unreadable` (an unreadable LIST) is not a substring of it.

    Since R7 (D1-B B6) an id built from a SUBJECT (`Rehearsal.add(..., subject=...)`: `case_environment-TS-10`, `vcs-test-repo`) keeps
    its form between rehearsals, so a recorded word keeps meeting the same item; a finding without a subject still carries the
    ordinal, and the message in the block stays the guard for it (the allowed error is asking again)."""
    message = " ".join(str(item.get("message") or "").split())[:OPEN_ITEM_BLOCK_LIMIT].strip()
    return f"gate {gate} item without a door: [{item.get('id')}] {message}"


def _drop_as_is_items(task_root, gate: str, items: list) -> list:
    """The items still open once the person's `approve as is` words are read: a `none` item whose `none_item_block` carries a live,
    non-revoked override at `AS_IS_STAGE` is answered (`waiver.split_overridden`, the very matcher the rehearsal drops by). Nothing is
    dropped when there is no task root or no readable pipeline.json (the allowed error is asking again, AR-28)."""
    if task_root is None or not any(i["door"]["kind"] == "none" for i in items):
        return items
    pipeline = read_json(Path(task_root) / "pipeline.json")
    if not isinstance(pipeline, dict):
        return items
    from waiver import split_overridden
    return [i for i in items
            if i["door"]["kind"] != "none" or split_overridden([none_item_block(gate, i)], pipeline, AS_IS_STAGE)[0]]


def open_rehearsal_items(task_root, gate: str = "A", rehearsed: dict | None = None) -> dict:
    """`{"status": "read" | "unknown", "items": [...], "why": str}` - the open `person_decides` items of the gate's rehearsal.

    A `none` item that the person's `approve as is` has been recorded for (`none_item_block`) is not open: the rehearsal cannot drop it
    by its message, so THIS reader does - the one place "answered" is read for every kind (packet line, `open_before_mr`, controller).

    `rehearsed` is a rehearsal already run (the packet passes its own, so the stand is probed once); None runs a fresh one. `unknown` -
    the rehearsal could not run, or holds a finding with no id or no class (it is counted, never skipped: a finding this cannot read
    is an item it cannot judge, AR-28) - says why and lists nothing; the caller decides what an unknown means. Read-only."""
    try:
        import gate_preflight
        result = rehearsed if isinstance(rehearsed, dict) else rehearsal(task_root, gate)
        if result.get("unavailable"):
            return {"status": "unknown", "items": [], "why": " ".join(str(result["unavailable"]).split())}
        findings = result.get("findings")
        if not isinstance(findings, list):
            return {"status": "unknown", "items": [], "why": "the rehearsal's findings are not a list"}
        stage = str(result.get("next_stage") or gate_preflight.GATE_STAGE.get(str(gate), ""))
        items, unread = [], 0
        for finding in findings:
            if not isinstance(finding, dict) or not str(finding.get("id") or "").strip() or not str(finding.get("class") or "").strip():
                unread += 1
            elif finding.get("class") == gate_preflight.PERSON_DECIDES:
                items.append(_open_item(finding, stage))
        if unread:
            return {"status": "unknown", "items": [], "why": f"{unread} finding(s) of the rehearsal have no id or no class"}
        return {"status": "read", "items": _drop_as_is_items(task_root, str(gate), items), "why": ""}
    except Exception as exc:
        return {"status": "unknown", "items": [], "why": f"{type(exc).__name__}: {exc}"}


# A stand gap is the one thing at a gate that costs a card rather than a line: requirement,
# case, what the test does, what is missing, the exact change and the four answers. Three of
# them are the most a packet can carry before it stops being a cover sheet; the rest are one
# command away. Before 0.7.11 these rows reached the person as `blocked_by_env` and a sentence.
MAX_GAP_CARDS = 3


def stand_gap_gaps(task_root, gate: str = "A", rehearsed: dict | None = None) -> list:
    """The stand gaps one gate shows a card for - the ONE list the packet is built from and the person's answer is
    read against (`read_stand_gap_answers`).

    Gate B: the manifest's and the run report's stand rows (`gate_b_gaps`). Gate A: the case preconditions the
    rehearsal found unmet (`stand_gaps.collect`); the rehearsal result is passed in so the stand is probed once per
    packet and not twice. Raises what `stand_gaps.collect` raises: the caller decides what an unreadable list means."""
    if gate == "B":
        return gate_b_gaps(task_root)
    import stand_gaps
    return stand_gaps.collect(task_root, gate, rehearsal=rehearsed)


ADAPTED_LINES_LIMIT = 5      # the adapted block names this many adaptations, then "and N more"


def report_kind_words() -> dict:
    """{report kind: how a person reads it} from the data file (`question-vocabulary.json` `report_kind_words`, FR-13); {} when unreadable."""
    try:
        import hooklib
        words = (hooklib.load_ref_json("question-vocabulary.json") or {}).get("report_kind_words")
    except Exception:
        return {}
    return {str(k): str(v) for k, v in words.items()} if isinstance(words, dict) else {}


def adapted_lines(task_root) -> list:
    """`## What the factory adapted by itself` (B-416 N8, FR-41): the `reporter_kind` rows of THIS story that a later proof of the same command
    confirms - at most five lines, then `and N more`; [] when there is none or either record cannot be read. Words only: `the web tests: their
    report is read as a .NET (trx) report since <date>`. Nothing the proof did not confirm is listed, and a `not_adapted` row never is."""
    try:
        import report_adapt
        import stand_gaps
        project = stand_gaps.project_of(task_root)
        ticket = str((read_json(Path(task_root) / "pipeline.json", {}) or {}).get("ticket") or Path(task_root).name)
        rows = report_adapt.proven_adaptations(project, ticket) if project is not None else []
    except Exception:
        return []
    if not rows:
        return []
    words = report_kind_words()
    lines = ["## What the factory adapted by itself", ""]
    for row in rows[:ADAPTED_LINES_LIMIT]:
        reader = str(row.get("reader") or "")
        lines.append(f"- the {row.get('profile_id')} tests: their report is read as {words.get(reader, reader)} since {str(row.get('at') or '')[:10]}")
    if len(rows) > ADAPTED_LINES_LIMIT:
        lines.append(f"- and {len(rows) - ADAPTED_LINES_LIMIT} more")
    return lines


def stand_gap_cards(task_root, gate: str = "A", rehearsed: dict | None = None) -> tuple:
    """(the card block as lines, the gap ids the packet now states itself).

    The rehearsal result is passed in, so the stand is probed once per packet and not twice.

    Both gates are answered in WORDS and rendered by ONE function (`stand_gap_card_lines`; t-342 B-272 for gate B,
    t-357 for gate A, FR-10): the card used to end in the command that records the answer (`waiver.py --task ...
    --block "stand gap: ..."`), a script name, flags and an internal block id in the body of a question. The person
    writes a case id and one word; at gate B the driver records it (`story_run.take_answer`, from the line
    `read_stand_gap_answers` reads). Gate A has no code reader of that line yet - the recording is the driver's
    (story_run.py), and until it is wired the answer reaches the conductor with the gate's words."""
    try:
        import stand_gaps
    except Exception:
        return ([], [])
    had_gate_a = False
    covered = []
    try:
        if gate == "B":
            gaps, covered = gate_b_split(task_root)
        else:
            gaps = stand_gap_gaps(task_root, gate, rehearsed)
            covered = stand_gaps.covered_a(task_root, rehearsed)       # B-414: what the environment record decided once
        decided = stand_gaps.decisions(task_root)
    except Exception:
        return ([], [])
    if not gaps and not covered:
        return ([], [])
    if gate == "B" and gaps:
        # B-361 (FR-7, FR-10): gate B reads the view that also carries a gate A answer given under the case key, with what
        # changed since; the delivery check reads the same helpers. A view that cannot be built drops every gate A record
        # (the allowed error is asking again, never a pass).
        try:
            decided, had_gate_a = stand_gaps.gate_b_answers(task_root, gaps)
        except Exception:
            decided = {k: v for k, v in decided.items() if v.get("stage") != stand_gaps.CARRY_STAGE}
    return (stand_gap_card_lines(task_root, gaps, decided, had_gate_a=had_gate_a, covered=covered),
            [str(g.get("id")) for g in gaps])


# --- gate B: a stand gap is answered in words (t-342, B-272) ----------------------------------------
# The closed list of words lives in `references/question-vocabulary.json` (`stand_gap_words`, FR-13) and is
# ENGLISH ONLY on purpose: a person answers in their own language, and code does not guess across languages
# (FR-12, P2). What this reads is a line `<case id>: <word>` whose word is on the list; any other wording goes
# to the conductor, which maps it to the form. The two readers of the list - the card that offers the words
# and the parser of the answer - are the two functions below, so the packet and the reading cannot drift.
STAND_GAP_FORM = "<case id or level name>: <word>"
APPROVAL_WORDS_FILE = "gate-approval-words.json"


def approval_words(gate: str) -> tuple:
    """The RAW approval words of gate "A" or "B" from `references/gate-approval-words.json` (`gate_approval_words`, FR-13), in the
    file's order; `()` when the file or the key cannot be read, or the gate has none (C1-4b, H13). THE one reader: the packet text
    names the word from it and the driver's check compares against it, so the two cannot drift (the STAND_GAP_FORM precedent). It
    normalizes nothing: the driver reads both sides with its one normalizer (`s0_normalize`). An unreadable file approves nothing
    (FR-59): the caller records no gate by code and says no word in the packet."""
    return _approval_rows(gate, passes_open_items=False)


def as_is_words(gate: str) -> tuple:
    """The approval words of `gate` whose row says `passes_open_items: true` (RH1-6, the owner's word of 27.10.2026: `approve as
    is`, a closed data word of gate A), in the file's order; `()` for a gate with none, and when the file cannot be read. THE
    one reader of that key: the driver compares the first line of an answer against it (`Driver.as_is_word`) and hands the
    controller `--as-is`; nothing else decides that a word passes the open items (FR-13, FR-12 - no phrase list)."""
    return _approval_rows(gate, passes_open_items=True)


def as_is_word_of(gate: str) -> str:
    """THE word a text names for `approve as is` at `gate` (the first of `as_is_words`); "" when there is none - the caller then drops
    its clause (M4, AR-13: the packet line, the controller's closing sentence and the driver's two texts read it from here)."""
    words = as_is_words(gate)
    return words[0] if words else ""


def risk_form() -> str:
    """The sentence that tells a person HOW to say at gate B that they deliver over a verdict that is not `yes` (HF8-23): the approval
    word on the first line (the only thing `Driver.gate_approval` reads from a gate answer), then the vocabulary's `risk_word` and their
    reason on a line of its own (the form `question_register.risk_reason_of` reads). ONE text for the packet of the skill road
    (`render_gate_b`) and of the driver road (its twin in `story_run.py`), built from the two data files, so the instruction and the reader
    cannot drift (FR-10, AR-19). "" when either word cannot be read: the caller then names the word alone, as before."""
    approve = approval_words("B")
    try:
        import question_register
        risk = question_register.vocabulary().get("risk_word")
    except Exception:
        risk = None
    if not approve or not isinstance(risk, str) or not risk.strip():
        return ""
    return (f"write `{approve[0]}` on the first line of your answer, then, on a line of its own, `{risk.strip()}: <your reason>`")


def _approval_rows(gate: str, passes_open_items: bool) -> tuple:
    """The words of `approval_words` / `as_is_words`: one read of the data file, the second only narrows by the row's flag."""
    try:
        block = (hooklib.load_ref_json(APPROVAL_WORDS_FILE) or {}).get("gate_approval_words")
        if not isinstance(block, dict):
            return ()
        return tuple(str(word) for word, row in block.items()
                     if isinstance(row, dict) and str(gate) in (row.get("gates") or []) and str(word).strip()
                     and (not passes_open_items or row.get("passes_open_items") is True))
    except Exception:
        return ()


_FORM_LINE_RE = re.compile(r"^\s*(?:[-*•]\s+)?(?P<id>[^\s:]+?)\s*:\s*(?P<word>\S.*?)\s*$")


def _word_key(text) -> str:
    """A word as it is compared: lower case, backquotes and quotes removed, spaces collapsed, a closing `.`/`!` dropped."""
    cleaned = str(text or "")
    for mark in ("`", '"', "'"):
        cleaned = cleaned.replace(mark, "")
    return " ".join(cleaned.split()).lower().rstrip(".!").strip()


def _id_key(text) -> str:
    """A case id as it is compared: markdown around it (`` ` ``, `*`, `_`, brackets) removed, case folded."""
    return str(text or "").strip().strip("`*_[]()<>").strip().lower()


def stand_gap_words(lasting: bool = False) -> list:
    """[{option, word, says, synonyms, lasting}] - the closed answers of a stand-gap card, from the data file.

    A row whose option is not one of `contract.STAND_GAP_OPTIONS`, or that names no word, is dropped (a damaged
    file reads as fewer answers, never as a wrong one); an unreadable file is [] and the card then offers no
    words, which the caller says (FR-41).

    B-414 (R4): a row may be `lasting` - `accept always`, the same option `accept` with a longer life (it is recorded in the
    environment record too). The DEFAULT list holds the standing rows only, so every reader that maps an option to its word
    (`word_of`, the delivery check's sentence, the conductor's relay) keeps one word per option; `lasting=True` returns every
    row, each with its `lasting` flag, for the two readers that need the lasting word: the card and the answer reader."""
    try:
        import hooklib
        data = hooklib.load_ref_json("question-vocabulary.json") or {}
    except Exception:
        return []
    rows = (data.get("stand_gap_words") or {}).get("answers") if isinstance(data, dict) else None
    out = []
    for row in rows if isinstance(rows, list) else []:
        if (isinstance(row, dict) and str(row.get("option") or "") in C.STAND_GAP_OPTIONS
                and str(row.get("word") or "").strip() and (lasting or row.get("lasting") is not True)):
            out.append({"option": str(row["option"]), "word": str(row["word"]).strip(),
                        "says": " ".join(str(row.get("says") or "").split()),
                        "synonyms": [str(s) for s in (row.get("synonyms") or []) if str(s).strip()],
                        "lasting": row.get("lasting") is True})
    return out


def stand_gap_word_of(rows=None) -> dict:
    """{option: word} - the ONE map a person's option is shown by (the card, the relay line, the recorded answer, the door
    text; t-666 R2). Built from the standing rows of `stand_gap_words()` (the data file), or from `rows`, a caller's own list,
    with its `lasting` rows left out - so one word per option, as the default list holds. A NEW dict on every call, so a caller
    may add a key to its own copy. From the data file it never carries `command` (that word is `probe_answers()`'s, which
    `_answer_vocab` adds to its own copy) nor any option outside `contract.STAND_GAP_OPTIONS` (critic t-648 F-4). `{}` when the
    file cannot be read. A damaged file with one option twice keeps the last row."""
    return {row["option"]: row["word"]
            for row in (stand_gap_words() if rows is None else [r for r in rows if not r.get("lasting")])}


def environment_words() -> list:
    """[{option, word, synonyms}] - the words about what the environment record holds (`ask again`), from the data file's
    `environment_words` block. Read ONLY against a gap the record covers (`read_stand_gap_answers`, `revokes`); [] when the
    block is missing or unreadable (the card then does not offer the line)."""
    try:
        import hooklib
        block = (hooklib.load_ref_json("question-vocabulary.json") or {}).get("environment_words") or {}
    except Exception:
        return []
    return [{"option": str(row["option"]), "word": str(row["word"]).strip(),
             "synonyms": [str(s) for s in (row.get("synonyms") or []) if str(s).strip()]}
            for row in (block.get("answers") if isinstance(block, dict) and isinstance(block.get("answers"), list) else [])
            if isinstance(row, dict) and str(row.get("option") or "") == "revoke" and str(row.get("word") or "").strip()]


FINDING_DOOR_OPTIONS = ("product_gap",)


def finding_door_words() -> list:
    """[{option, word, says, synonyms}] - the words a rehearsal finding's OWN door takes besides the stand-gap answers, from the data
    file's `finding_door_words` block (D1-C2; AR-1). Read ONLY by `story_run.Driver.read_finding_doors`. A row whose option is not in
    `FINDING_DOOR_OPTIONS`, or that names no word, is dropped; [] when the block or the file cannot be read (no door is then offered, E-C9)."""
    try:
        import hooklib
        block = (hooklib.load_ref_json("question-vocabulary.json") or {}).get("finding_door_words") or {}
        rows = block.get("answers") if isinstance(block, dict) else None
    except Exception:
        return []
    return [{"option": str(row["option"]), "word": str(row["word"]).strip(),
             "says": " ".join(str(row.get("says") or "").split()),
             "synonyms": [str(s) for s in (row.get("synonyms") or []) if str(s).strip()]}
            for row in (rows if isinstance(rows, list) else [])
            if isinstance(row, dict) and str(row.get("option") or "") in FINDING_DOOR_OPTIONS and str(row.get("word") or "").strip()]


def finding_door_option(rest, rows=None) -> tuple:
    """`(option, reason)` the text after a finding id's colon says by a finding door's own word (`finding_door_words`; `rows` given, else read), or
    `("", "")`. The word alone (or a synonym alone) is read; the word followed by a separator and the person's reason is read with the reason kept
    whole; the word followed by a letter (`product gaps`) is not the word. The ONE reader of that block's rows (`story_run.Driver.read_finding_doors`)."""
    said = _word_key(rest)
    for row in finding_door_words() if rows is None else rows:
        key = _word_key(row["word"])
        if said == key or said in {_word_key(s) for s in row["synonyms"]}:
            return row["option"], ""
        if key and said.startswith(key) and said[len(key)] in " ,;:.-—–":
            spelled = re.match(r"[`\"']*" + r"\s+".join(re.escape(w) for w in row["word"].split()) + r"[`\"']*[\s,;:.\-—–]*(.*)",
                               str(rest).strip(), re.IGNORECASE | re.DOTALL)
            return row["option"], (spelled.group(1).strip() if spelled else "")
    return "", ""


def finding_door_word_of() -> dict:
    """{option: word} of `finding_door_words()`; {} when the block cannot be read."""
    return {row["option"]: row["word"] for row in finding_door_words()}


def probe_answers() -> dict:
    """{live, command, reporter_accept, problem} - the answers of a reporter card that are not `stand_gap_words`, from the
    data file (`question-vocabulary.json` `probe_answers`, B-220 part 2, FR-13).

    `command` is the row of the word that is followed by the person's own command line, or None when the file has none, cannot
    be read, or the row is damaged (no word, or a `value` that is not a regular expression): the card then does not offer the
    word and a line that uses it is not read - fewer answers, never a wrong one - and `problem` says why in words (FR-41), '' when
    there is nothing wrong. `live` is the file's switch: True only when the factory executes a `command` line."""
    out = {"live": False, "command": None, "reporter_accept": "", "problem": ""}
    try:
        import hooklib
        data = (hooklib.load_ref_json("question-vocabulary.json") or {}).get("probe_answers")
    except Exception as exc:
        out["problem"] = f"the list of answers could not be read ({type(exc).__name__})"
        return out
    if not isinstance(data, dict):
        out["problem"] = "the file has no `probe_answers`"
        return out
    out["live"] = data.get("live") is True
    out["reporter_accept"] = " ".join(str(data.get("reporter_accept") or "").split())
    row = data.get("command")
    if not isinstance(row, dict) or not str(row.get("word") or "").strip():
        out["problem"] = "the `command` row names no word"
        return out
    try:
        re.compile(str(row.get("value") or r"\S.*"))
    except re.error as exc:
        out["problem"] = f"the `command` row's `value` is not a regular expression ({exc}), so the row is dropped"
        return out
    out["command"] = {"option": "command", "word": str(row["word"]).strip(),
                      "value": str(row.get("value") or r"\S.*"),
                      "continuation_marks": [str(m) for m in (row.get("continuation_marks") or []) if str(m)],
                      "says": " ".join(str(row.get("says") or "").split()),
                      "note": " ".join(str(row.get("note") or "").split())}
    return out


def stand_gap_word_index(rows=None) -> dict:
    """{normalised word or synonym: option}. A word that two options claim stays with the first (a test holds
    the data file free of such a word)."""
    index: dict = {}
    for row in stand_gap_words() if rows is None else rows:
        for text in [row["word"], *row.get("synonyms", [])]:
            index.setdefault(_word_key(text), row["option"])
    return index


def gate_b_gaps(task_root) -> list:
    """The stand gaps gate B shows a card for - the ONE list the packet is built from and the person's answer is read
    against. A row the person already handed to themselves has its own heading with what to run; a second telling
    of it here would be the same fact twice in one packet. [] when they cannot be collected."""
    return gate_b_split(task_root)[0]


def gate_b_split(task_root) -> tuple:
    """`(the gate B gaps that are asked, the level gaps the environment record covers)` - the ONE split every gate B reader
    uses (B-414 R7: `stand_gaps.gate_b_split`). The rows the person already handed to themselves are in neither. A split that
    cannot be made asks every row, covers none (the allowed error is asking); gaps that cannot be collected are ([], [])."""
    try:
        import stand_gaps
        rows = [g for g in stand_gaps.collect(task_root, "B") if g.get("reason") != "handed_to_person"]
    except Exception:
        return [], []
    try:
        return stand_gaps.gate_b_split(task_root, rows)
    except Exception:
        return rows, []


def _role_card(gap) -> bool:
    """Is this gap the role card (one stand, one role, several cases) or the confirm card of a noticed role? (`stand_gaps.ROLE_SCOPES`)"""
    import stand_gaps
    return isinstance(gap, dict) and gap.get("scope") in stand_gaps.ROLE_SCOPES


def _offers_nothing(gap) -> bool:
    """A card whose `remedy.offers` is the EMPTY list takes no word: it informs and is never an open id of the answer block."""
    remedy = gap.get("remedy") if isinstance(gap, dict) and isinstance(gap.get("remedy"), dict) else {}
    return isinstance(remedy.get("offers"), list) and not remedy["offers"]


def stand_gap_form_ids(gaps) -> dict:
    """{gap id: the id the person writes}: the bare case id, or - when two gaps share one (two areas, one number) -
    the gap's own key, which is the one thing that tells them apart. A LEVEL gap is written by its contour (`web: accept`
    answers every web test of the story); a contour and a case id that clash are two gaps sharing one id, so both fall back
    to their own keys (B-414 R3)."""
    def written(g) -> str:
        if _role_card(g):
            return ""       # a role card (t-2142 PK0-4) holds several cases: it is written by its own gap id (`RA-dev-auditor`)
        return str((g.get("contour") if g.get("scope") == "level" else g.get("case_id")) or "")
    counts = Counter(written(g) or str(g.get("id") or "") for g in gaps)
    return {str(g.get("id")): (written(g) if written(g) and counts[written(g)] == 1 else str(g.get("id"))) for g in gaps}


def lasting_offered(gap: dict) -> bool:
    """Does this card take `accept always`? Only a card whose gap has a key to record it under (`property_key`, B-414 R4/M13:
    never a gap whose cause is a file or the machine) and that takes `accept` at all."""
    return bool(isinstance(gap, dict) and gap.get("property_key") and "accept" in offered_options(gap))


def read_stand_gap_answers(words: str, gaps: list, rows=None, covered=()) -> dict:
    """Read the person's answer for stand-gap lines: {"read": [...], "unread": [...]}.

    A line is `<id>: <word>` (a bullet in front is forgiven). It is READ when the id names exactly one gap of
    `gaps` (by its case id or its key) and the word, whole, is on the closed list; `read` rows are
    `{gap, option, word, line, replaced}` in the order the gaps were first answered, and a gap answered twice keeps
    the LAST line with the earlier ones in `replaced` (the caller says so). `apply` for a gap whose card shows no
    exact change is not read: it was never offered. A line that LOOKS like the form but cannot be read is `unread`
    `{line, why}` and is never dropped - the id of no gap of this gate, a word outside the list, an id that two
    gaps share. A line that is not the form at all (a bug number, prose, a question id with no known word) is
    neither: it stays in the person's words, which the gate decision keeps whole.

    Meaning is never read here (FR-12): the whole text after the colon is compared with the data file's list.
    A story with no stand gap at this gate has no form to read an answer against: nothing is read, nothing unread.

    B-220 part 2 (the reporter card of gate A). A card may carry `remedy.offers`, the options it takes (gate_preflight writes it for
    a reporter card); a word outside it is `unread` with the words that DO apply (FR-1): on a reporter card with no cure that is one
    change of its command, `change` is such a word (F12 - it was recorded as a waiver, which closed the card on a promise). The
    form `command <the person's own command line>` (`probe_answers`) is read the same way, but its rows go to `commands`, NEVER to
    `read`: a `command` line is not a waiver, and a caller that records every `read` row must not record it. A `command` row is
    `{gap, option: "command", word, line, arg, replaced}`; `arg` is the rest of the line, case kept, one pair of backquotes round
    the whole value peeled. NOT read, in words, nothing written: no command after the word, a `?` anywhere in the line (a question is
    never consent), a value ending in a continuation mark, one over 1000 characters, one that does not split into words (an unbalanced
    quote), one that is itself an answer word (two answers in one line). A `command` line inside a code fence is not an answer
    (it is left in the person's words). Whether a command is a place on this machine, or needs a shell, is the probe's to refuse
    (`onboarding_probe.probe_person_command`, one definition) - this reader only reads.

    B-414 (R4, M4). `covered` are the gaps the environment record decided once (no card): the only gaps `ask again`
    (`environment_words`) is read against, into `revokes` - NEVER into `read`, so a caller that records every `read` row cannot
    record it. The reader stands even when every gap is covered (`gaps` empty). `accept always` (a `lasting` word) is read as
    `accept` with `lasting: True` - only for a gap that has a key to record it under (`property_key`); for any other it is
    `unread`, saying why: a gap whose cause is a file or the machine is a fault, and the door is `accept` for this story."""
    covered = [g for g in covered or [] if isinstance(g, dict)]
    if not gaps and not covered:
        return {"read": [], "unread": [], "commands": [], "revokes": []}   # no stand gap, no form to read an answer against
    vocab = _answer_vocab(rows)
    index, spec, word_of = vocab["index"], vocab["spec"], vocab["word_of"]
    by_id, by_covered = _ids_of(gaps), _ids_of(covered)
    read: dict = {}
    revokes: dict = {}
    unread = []
    last_unread: set = set()      # gaps whose LAST line could not be read (critic t-346 F2)
    in_fence = False
    for raw in str(words or "").splitlines():
        if raw.lstrip().startswith("```"):
            in_fence = not in_fence      # a fence line is no answer line; what is inside one is read only for the old words
            continue
        if raw.lstrip().startswith(">"):
            continue                     # a quoted line is no answer: the same rule as `read_exploratory_answers` and `parse_choices` (m-5)
        hit = _FORM_LINE_RE.match(raw)
        if not hit:
            continue
        line = " ".join(raw.split())
        named = by_id.get(_id_key(hit.group("id")), {})
        word = _word_key(hit.group("word"))
        refused = _covered_line(by_covered.get(_id_key(hit.group("id")), {}), named, word in vocab["revoke_keys"], revokes, line, word)
        if refused is not None:
            unread.extend(refused)
            continue
        option = index.get(word, "")
        form = _command_form(hit.group("word"), spec, raw) if spec and not option else None
        if form is not None:
            if in_fence:
                continue
            option = "command"
        one = str(next(iter(named))) if len(named) == 1 else ""
        if len(named) > 1:
            unread.append({"line": line, "why": "that id names more than one stand gap of this gate"})
        elif named and not option:
            # t-409 H4: the words that apply to THAT card (its own `offers`; a card with none names the four standing words)
            unread.append({"line": line, "why": "the word is not one of the answers the card offers"
                           + _words_that_apply(offered_options(next(iter(named.values()))), word_of)})
            last_unread.add(one)
        elif option and not named:
            unread.append({"line": line, "why": "that id is not a stand gap of this gate"})
        elif named and option:
            gap = next(iter(named.values()))
            refusal = _line_refusal(gap, option, word, form, vocab, line)
            if refusal is not None:
                unread.append(refusal)
                last_unread.add(one)
                continue
            key = str(gap.get("id"))
            last_unread.discard(key)
            earlier = read.get(key)
            read[key] = {"gap": gap, "option": option, "word": word if form is None else spec["word"], "line": line,
                         "lasting": word in vocab["lasting_keys"],
                         "replaced": ((earlier["replaced"] + [earlier["line"]]) if earlier else [])}
            if form is not None:
                read[key]["arg"] = form["arg"]
    unread.extend(_set_aside(read, last_unread))      # the person's LAST word on a gap decides it (see there)
    return {"read": [e for e in read.values() if e["option"] != "command"], "unread": unread,
            "commands": [e for e in read.values() if e["option"] == "command"], "revokes": list(revokes.values())}


def _answer_vocab(rows) -> dict:
    """The words `read_stand_gap_answers` reads a line against, from the data file (or from `rows`, a caller's own list):
    {"index": word key -> option, "lasting_keys": the keys of the `accept always` words, "revoke_keys": the keys of the `ask
    again` words, "spec": the `command` form's spec (empty when the file has none), "word_of": option -> the word written}."""
    index = stand_gap_word_index(stand_gap_words(lasting=True) if rows is None else rows)
    lasting_keys = {_word_key(t) for row in (stand_gap_words(lasting=True) if rows is None else rows) if row.get("lasting")
                    for t in [row["word"], *row.get("synonyms", [])]}
    revoke_keys = {_word_key(t) for row in environment_words() for t in [row["word"], *row["synonyms"]]}
    spec = probe_answers()["command"]
    word_of = stand_gap_word_of(rows)       # a fresh dict: `command` is added to THIS copy only (critic t-648 F-4)
    if spec:
        word_of["command"] = spec["word"]
    return {"index": index, "lasting_keys": lasting_keys, "revoke_keys": revoke_keys, "spec": spec, "word_of": word_of}


def _words_that_apply(options, word_of) -> str:
    """The clause that ends a refusal of a word (t-409 H4, FR-1): the words that DO apply to the card, in the order the card
    offers them, the options with no written word left out. It starts with its own `; ` - it follows a reason."""
    return "; the words that apply here are: " + ", ".join(f"`{word_of[o]}`" for o in options if o in word_of)


# --- gate B: the QUESTIONS of the exploratory findings are answered in words (P2 fix round, critic t-1579 M1) ----------
# A question line of the findings (`report_facts.exploratory_gate_parts`) is answered `<case id>: intended|bug|open`. The closed
# words and their three price lines are a data block (`question-vocabulary.json` `exploratory_question_words`, FR-13); the packet
# that offers them and the reader that reads them are the two functions below, so they cannot drift. The line grammar and the
# normalisers are the stand-gap reader's (AR-15: imported above, never copied).
EXPLORATORY_OPTIONS = ("intended", "bug", "open")
# The closing sentence of an answer form, true in every case (critic t-1592 M-b): when the answer STARTS with the gate's approval word
# the gate is recorded by code (`Driver.gate_approval` reads the first line only) and only the lines in the form are carried out,
# so the helper reads the rest only when the first line is not that word.
# GW1-32: ONE sentence for "what happens to the words that fit no form" - the answer block, the stand-gap block and the attachment
# blocks say it with this constant (it was three texts: "a person's helper", "a helper", "a helper"). The question block of gate B has
# branches with no form above ("answer in your own words"): the constant there would point to a form that is not shown (FR-10), so
# those branches keep their own sentence.
ANYTHING_ELSE_SENTENCE = ("Anything else, in your own words, goes to the assistant running this story, who turns it into one of these "
                          "or asks you back; only the forms above are read by code.")
APPROVAL_FIRST_LINE_TAIL = (ANYTHING_ELSE_SENTENCE + " That holds unless your answer starts with the word that approves this gate: "
                            "then only the lines in the form above are read, so do not start the answer with that word if you want "
                            "your own words read.")
EXPLORATORY_FORM = "<case id>: <word>"


def exploratory_question_words() -> list:
    """[{option, word, says, factory, you, story, synonyms}] - the closed answers of a question line, from the data file. A row
    whose option is not one of `EXPLORATORY_OPTIONS`, that names no word or lacks a price line is dropped (a damaged file reads as
    fewer answers, never as a wrong one); an unreadable file is [] and the packet then offers no words and says so (FR-41)."""
    try:
        import hooklib
        rows = ((hooklib.load_ref_json("question-vocabulary.json") or {}).get("exploratory_question_words") or {}).get("answers")
    except Exception:
        return []
    out, seen = [], set()
    for row in rows if isinstance(rows, list) else []:
        if not (isinstance(row, dict) and str(row.get("option") or "") in EXPLORATORY_OPTIONS and str(row.get("option")) not in seen
                and str(row.get("word") or "").strip()):
            continue
        prices = {key: " ".join(str(row.get(key) or "").split()) for key in ("says", "factory", "you", "story")}
        if not all(prices.values()):
            continue
        seen.add(str(row["option"]))
        out.append({"option": str(row["option"]), "word": str(row["word"]).strip(), **prices,
                    "synonyms": [str(s) for s in (row.get("synonyms") or []) if str(s).strip()]})
    return out


def exploratory_word_index(rows=None) -> dict:
    """{normalised word or synonym: option}; a word two options claim stays with the first (a test holds the file free of one)."""
    index: dict = {}
    for row in exploratory_question_words() if rows is None else rows:
        for text in [row["word"], *row.get("synonyms", [])]:
            index.setdefault(_word_key(text), row["option"])
    return index


def _foreign_word_keys() -> set:
    """The words OTHER readers of a `<id>: <word>` line own (the stand-gap words, `ask again`, the reporter `command`, the case
    decisions, `accept as blocked`, the question tokens): a line carrying one of them is theirs - never an unreadable exploratory
    line, so the same case id on a stand-gap card and a question line stays answerable (the id-overlap edge)."""
    keys = {_word_key(t) for row in stand_gap_words(lasting=True) for t in [row["word"], *row.get("synonyms", [])]}
    keys |= {_word_key(t) for row in environment_words() for t in [row["word"], *row["synonyms"]]}
    keys |= {"manual", "automate", "accept as blocked", "not needed", "until the report"}
    command = probe_answers()["command"]
    if command:
        keys.add(_word_key(command["word"]))
    return keys


def _price_labels() -> list:
    """The three labels that follow an option (`human_text.price_labels`, item 6), with the last-resort set when the rules file
    cannot be read: the ONE place of that fallback (the exploratory block and the attachments block share it)."""
    try:
        import human_text
        return human_text.price_labels()
    except Exception:
        return ["the factory:", "you:", "the story:"]


def exploratory_answer_block(parts: dict) -> list:
    """The lines under the question lines of gate B: how to answer (the form, an example, the closed words) and, under each word,
    the three price lines of human-questions.md item 6. [] when there is no question; the sentence that says the words could not be
    loaded when the data file gives none (FR-41); one sentence when no line names a test case."""
    questions = parts.get("questions") or []
    if not questions:
        return []
    addressable = [q for q in questions if q.get("addressable")]
    if not addressable:
        return ["None of these questions names one test case, so there is no line to write for them: answer in your own words. "
                "The assistant running this story turns the words into a decision or asks you back."]
    rows = exploratory_question_words()
    if not rows:
        return ["The list of answers to these questions could not be read - that is the factory's own gap; say in your own words "
                "what should happen to each one."]
    labels = _price_labels()
    lines = [f"Answer each question on a line of its own: `{EXPLORATORY_FORM}`, for example `{addressable[0]['case']}: {rows[0]['word']}`. "
             "A question you do not answer stays open. The words:"]
    for letter, row in zip(string.ascii_lowercase, rows):
        lines.append(f"({letter}) `{row['word']}` — {row['says']}.")
        lines += [f"{label} {row[key]}" for label, key in zip(labels, ("factory", "you", "story"))]
    lines.append(APPROVAL_FIRST_LINE_TAIL)
    return lines


def exploratory_shown(task_root) -> list:
    """[{case, line, qid, row_hash, addressable}] - the question lines gate B shows now, from the same function that renders them
    (`report_facts.exploratory_gate_parts`). The driver keeps it when the packet is shown; the answer is read against it."""
    from report_facts import exploratory_gate_parts
    return [{key: q[key] for key in ("case", "line", "qid", "row_hash", "addressable")}
            for q in exploratory_gate_parts(task_root)["questions"]]


def read_exploratory_answers(words: str, shown: list, current=None, rows=None, card_ids=None) -> dict:
    """Read the person's answers to the question lines: {"read": [{case, line, qid, row_hash, option, word, line_text, replaced}],
    "unread": [{line, why}]}.

    A line is `<id>: <word>` (a bullet in front is forgiven; a fenced or quoted line is no answer). It is READ when the id names
    exactly ONE question line of `shown` and the word, whole, is on the closed list. It is UNREAD, with a why, when it LOOKS like
    the form and cannot be read: a word outside the list on a shown id (the words that apply are named; a word of another reader
    - stand-gap, case decision, question token - is that reader's and is neither, but only on an id in `card_ids` (the ids a
    stand-gap card answers; None = every id, the old reading): on any other id nobody reads it, so it is unread); a word on the list on an id that is no question
    shown; an id two lines share (or a line with no case); a shown line that is no longer the live line of its chain (`current`: the
    ids of the live lines; None skips the test) - the finding changed since the person saw it; two DIFFERENT words for one line
    (neither is applied, FR-12: code does not choose between contradicting tokens). The same word twice is one answer, the earlier
    line kept in `replaced`. Any other line is neither. Meaning is never read (FR-12). Nothing shown, or no word list: nothing is
    read and nothing is unread (AR-28: no answer is taken on an unknown)."""
    out: dict = {"read": [], "unread": []}
    vocab = exploratory_question_words() if rows is None else rows
    shown = [s for s in shown or [] if isinstance(s, dict) and s.get("line")]
    if not shown or not vocab:
        return out
    index, foreign = exploratory_word_index(vocab), _foreign_word_keys()
    command = (probe_answers()["command"] or {}).get("word", "")            # `command <the person's own command line>` is the stand-gap reader's
    word_of = {row["option"]: row["word"] for row in vocab}
    by_case: dict = {}
    for item in shown:
        if item.get("case"):
            by_case.setdefault(_id_key(item["case"]), []).append(item)
    entries: dict = {}
    fenced = False
    for raw in str(words or "").lstrip(chr(0xFEFF)).splitlines():
        if raw.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or raw.lstrip().startswith(">"):
            continue
        hit = _FORM_LINE_RE.match(raw)
        if not hit:
            continue
        line, word = " ".join(raw.split()), _word_key(hit.group("word"))
        named, option = by_case.get(_id_key(hit.group("id")), []), index.get(word, "")
        if not named:
            if option:
                out["unread"].append({"line": line, "why": "that id is not one of the questions shown"})
        elif not option:
            theirs = word in foreign or bool(command and word.startswith(_word_key(command) + " "))
            if not theirs or (card_ids is not None and _id_key(hit.group("id")) not in card_ids):
                # a word of another reader is THAT reader's only on an id it can answer (a stand-gap card); on any other id nobody
                # reads it, so it is unread and goes to the conductor (m-6)
                out["unread"].append({"line": line, "why": "the word is not one of the answers these questions take"
                                      + _words_that_apply(EXPLORATORY_OPTIONS, word_of)})
        elif len(named) > 1:
            out["unread"].append({"line": line, "why": "that id names more than one question; answer in words"})
        elif current is not None and named[0]["line"] not in current:
            out["unread"].append({"line": line, "why": "the finding changed since you saw it"})
        else:
            entries.setdefault(named[0]["line"], []).append((option, line, named[0]))
    for found in entries.values():
        if len({option for option, _line, _item in found}) > 1:
            out["unread"] += [{"line": line, "why": "two different answers for one question; neither is applied"}
                              for _option, line, _item in found]
            continue
        option, line, item = found[-1]
        out["read"].append({**item, "option": option, "word": word_of[option], "line_text": line,
                            "replaced": [earlier for _o, earlier, _i in found[:-1]]})
    return out


def _line_refusal(gap: dict, option: str, word: str, form, vocab: dict, line: str) -> dict | None:
    """Why a line that names ONE gap with a word on the list is still not an answer: the `unread` row, or None when it is
    one. Pure - the caller records the gap as one whose last line was unread. The order of the three refusals is the old
    order: an option the card does not take, a `command` value that cannot be taken, `accept always` with nothing to
    record it under."""
    taken = _gap_options(gap)
    if option not in taken:
        if option == "apply":
            why = ("the card offers no exact change for this gap, so `change` was never one of its answers"
                   if C.remedy_errors(gap.get("remedy")) else
                   "this card has no change the factory can make (the cure is not one change of the command), so "
                   "`change` is not one of its answers")
        else:
            why = f"`{vocab['word_of'].get(option, option)}` is not an answer this card takes"
        return {"line": line, "why": why + _words_that_apply(taken, vocab["word_of"])}
    if form is not None and form["why"]:
        return {"line": line, "why": form["why"]}
    if word in vocab["lasting_keys"] and not lasting_offered(gap):
        return {"line": line, "why": _lasting_refusal(gap) + _words_that_apply(taken, vocab["word_of"])}
    return None


def _set_aside(read: dict, last_unread: set) -> list:
    """The person's LAST word on a gap decides it. A readable line followed by an unreadable one for the same gap is not
    recorded by code: the earlier line is set aside beside the later one and the whole gap goes to the conductor. Pops
    those gaps out of `read` (the caller's dict, as the loop always did) and returns the `unread` rows, gap by gap in
    key order."""
    unread = []
    for key in sorted(last_unread & set(read)):
        entry = read.pop(key)
        unread.append({"line": entry["line"], "why": "an earlier line for this gap, set aside: its last line could "
                                                     "not be read, so the person's last word is unread"})
        unread.extend({"line": earlier, "why": "an earlier line for this gap, set aside (see its last line)"}
                      for earlier in entry["replaced"])
    return unread


def _ids_of(gaps) -> dict:
    """{normalised id a person may write: {gap id: gap}} - a gap by its id, its case id and (a level gap) its contour."""
    out: dict = {}
    for gap in gaps or []:
        names = {_id_key(gap.get("id")), _id_key(gap.get("case_id")),
                 _id_key(gap.get("contour")) if gap.get("scope") == "level" else ""}
        for key in names - {""}:
            out.setdefault(key, {})[str(gap.get("id"))] = gap
    return out


def _covered_line(named_covered: dict, named: dict, revoke: bool, revokes: dict, line: str, word: str):
    """The part of a line that concerns a gap the environment record covers (B-414 R4, E18): None when the line is not about one
    (the open gaps' reading goes on); else a list of `unread` rows - EMPTY when the line was read (`ask again`, into `revokes`,
    the last line for a gap wins). `ask again` for a gap that is not covered, and any other word for a covered one, are `unread`
    with the reason, never dropped and never recorded."""
    if revoke:
        if len(named_covered) == 1:
            gap = next(iter(named_covered.values()))
            revokes[str(gap.get("id"))] = {"gap": gap, "option": "revoke", "word": word, "line": line}
            return []
        if named_covered:
            return [{"line": line, "why": "that id names more than one stand gap of this gate"}]
        return [{"line": line, "why": ("this gap is not recorded for the environment, so there is nothing to ask again"
                                       if named else "that id is not a stand gap of this gate")}]
    if named_covered and not named:
        return [{"line": line, "why": "this gap was decided once for this environment; to have it asked again write "
                                      "`<its name>: ask again`"}]
    return None


def _lasting_refusal(gap: dict) -> str:
    """Why `accept always` was not read for this gap (FR-4, an informed refusal; M13): the cause is a file or the machine - a
    fault that gets fixed, with the door `accept` for this story - or the gap has nothing to record it by."""
    if gap.get("lasting") == "fault":
        import environment_record
        return environment_record.fault_line(gap.get("reason_class"))
    return "`accept always` is not an answer this card takes: nothing identifies this gap well enough to record it for the environment"


# --- gate A, the reporter card's `command` answer: the two legs of the SAME sealed-proposal path as the onboarding (B-220 F3) ----
# `read_stand_gap_answers` reads the line (`commands`); these two functions are what the driver calls for it - the person's own
# command is probed and sealed as ONE proposal (leg 1), asked once more as "Do it?" in the sentence the proposal carries, and
# applied only on the person's recorded yes (leg 2): `onboarding_probe.probe_person_command`, then
# `config_contract.record_approval` + `apply_plan` - no new writer, and the line is never written raw. Both legs return a dict and
# raise nothing: `state` says where it stands, `text` is what the person is told (no script name, no flag, no exit code), `says`
# is the reason for code and for the conductor.
REPORTER_ANSWER_BLOCK = ("\n\n---\nAnswer: write the line again with a command that fits, or answer with one of the other words "
                         "the card lists.\n")


def _person_says(says: str, block: str = REPORTER_ANSWER_BLOCK) -> str:
    return " ".join(str(says or "").split()) + block


def probe_reporter_command(project_root, gap: dict, line: str, proposals_dir=None, kind=None) -> dict:
    """Leg 1 of a `command` answer: probe the person's own command for the card's profile, and seal ONE proposal when it proves.
    `kind` (junit-xml or trx) is passed through for a profile that records no report kind; the line itself has no slot for it.

    -> {state, profile, command, says, text, proposal, old, new}. `state`: `ask` (the command left a report the factory can read
    and S5's own contract takes it: `proposal` is sealed and `text` is its sentence, rendered from the sealed file, which ends
    in the "Do it?" the person answers), `explain` (it did not prove: `text` says what came out), `refused` (the line is not a
    command the factory can run, or the folder for sealed files is inside the project, or the card is not about a test
    command: `text` says why - an absolute path, a shell word, an unbalanced quote, all in words), `already_done` (it is the
    command the profile already has). Nothing is written to the project in any state: the probe's own run leaves no
    proof behind (`probe_candidate` is not durable) and the proposal file goes where the caller says, outside it.
    POSITION INVARIANT: the person's line reaches the config only through leg 2, after a recorded yes."""
    out = {"state": "refused", "profile": "", "command": None, "says": "", "text": "", "proposal": None, "old": None, "new": None}
    remedy = gap.get("remedy") if isinstance(gap.get("remedy"), dict) else {}
    profile = str(remedy.get("profile") or "")
    if not profile or "command" not in (remedy.get("offers") or []):
        out["says"] = "this card is not about a test command that writes no report, so it takes no command line"
        out["text"] = _person_says(out["says"])
        return out
    out["profile"] = profile
    try:
        import onboarding_probe
        got = onboarding_probe.probe_person_command(project_root, profile, line, proposals_dir, kind)
    except ValueError as exc:
        out["says"] = str(exc)
        out["text"] = _person_says("The command could not be checked: " + out["says"].split(". ")[0].rstrip(".") + ".")
        return out
    except Exception as exc:        # noqa: BLE001 - the direction is "refuse", and the person is told, never shown a traceback
        out["says"] = f"{type(exc).__name__}: {exc}"
        out["text"] = _person_says("The command could not be checked, so nothing was changed.")
        return out
    out.update(command=got.get("command"), says=str(got.get("says") or ""))
    move = got.get("move")
    if move == "do_it":
        proposal = got["proposal"]
        sealed = proposal.get("sealed")
        try:
            if sealed is None:
                sealed = json.loads(Path(proposal["path"]).read_text(encoding="utf-8"))
            import config_contract as CC
            out["text"] = CC.command_question(sealed)
        except (OSError, ValueError, KeyError) as exc:
            out["says"] = f"the sealed proposal could not be read back: {exc}"
            out["text"] = _person_says("The command was checked, but the question about it could not be put, so nothing was "
                                       "changed.")
            return out
        change = (sealed.get("changes") or [{}])[0]
        out.update(state="ask", proposal=proposal, old=change.get("from"), new=change.get("to"))
    elif move == "nothing":
        out.update(state="already_done", text=_person_says(out["says"], "\n\n---\nAnswer: nothing to answer; that is already the "
                                                                          "command, and the next check reads its report again.\n"))
    elif move == "explain_and_ask":
        out.update(state="explain", text=_person_says(out["says"]))
    else:
        out.update(state="refused", text=_person_says(out["says"]))
    return out


def apply_reporter_command(project_root, sealed: dict, task: str, gap: dict, line: str, approval_ref: str = "") -> dict:
    """Leg 2 of a `command` answer, on the person's recorded yes: the approval is recorded, then the proposal is applied.

    -> {state, says, text, approval_ref, old, new, backup}. `state`: `applied`, `already_done` (the config already holds this
    command - a second yes is "already done", never the stale refusal a repeated approval would give once the first apply
    moved the config), or `refused` (stale, not sealed, a `headless:` approval, an invalid result - `says` is the reason and
    `text` what the person is told; nothing was written). The approval ref is `gate-a:<task>:<card>:<proposal hash, 12>:<sha256
    of the line, 8>`, so a re-approval with other words never collides; the evidence is the person's line, WHOLE (FR-8). A
    `headless:` ref is refused for a command proposal exactly as for a cure: only a person's word approves a changed command (F9)."""
    import hashlib
    import config_contract as CC
    root = Path(project_root)
    out = {"state": "refused", "says": "", "text": "", "approval_ref": "", "old": None, "new": None, "backup": None}
    state = CC.command_state(root, sealed)
    change = ((sealed.get("changes") or [{}])[0]) if isinstance(sealed, dict) else {}
    out.update(old=change.get("from"), new=change.get("to"))
    if state["state"] == "already_done":
        out.update(state="already_done", says=state["why"],
                   text=_person_says("That is already the command, so nothing was changed.",
                                     "\n\n---\nAnswer: nothing to answer; the next check reads its report again.\n"))
        return out
    if state["state"] in ("stale", "invalid"):
        out.update(says=state["why"], text=_person_says(
            "The configuration changed after I made the proposal, so your yes was not applied and nothing was changed. Give "
            "the command again and I will check it again." if state["state"] == "stale" else
            "The proposal is not one I can apply, so nothing was changed. Give the command again and I will check it again."))
        return out
    ref = approval_ref or ":".join(("gate-a", str(task), str(gap.get("id")), str(sealed.get("proposal_hash"))[:12],
                                    hashlib.sha256(str(line).encode("utf-8")).hexdigest()[:8]))
    out["approval_ref"] = ref
    try:
        CC.record_approval(root, sealed, ref, str(line))
        backup = CC.apply_plan(root, sealed, ref)
    except ValueError as exc:
        headless = str(exc).startswith("this proposal changes a test command, and only a person's word")
        out.update(says=str(exc), text=_person_says(
            "Only your own word approves a change to a test command, and that approval was not accepted, so nothing was changed."
            if headless else "The change was refused, so nothing was changed. Give the command again and I will check it again."))
        return out
    out.update(state="applied", backup=str(backup) if backup is not None else None,
               says=f"the command of `{(sealed.get('listing') or {}).get('target', {}).get('profile_id')}` is now "
                    f"{(sealed.get('listing') or {}).get('command')}",
               text="The command is changed, and the next check runs it and reads its report again.")
    return out


def offered_options(gap: dict) -> list:
    """The options a card OFFERS the person, in order: its own `remedy.offers` (a reporter card writes one), else the four of the
    record (`contract.STAND_GAP_OPTIONS`) - every card before `offers` existed keeps all four. ONE function for the three readers
    of the list: the card's words, the answer reader's refusal, and the conductor relay in `story_run` (t-409 H3, FR-10)."""
    remedy = gap.get("remedy") if isinstance(gap.get("remedy"), dict) else {}
    if isinstance(remedy.get("offers"), list):
        return [str(o) for o in remedy["offers"]]
    return list(C.STAND_GAP_OPTIONS)


def relay_card_line(gap: dict, form, default_stage: str = "") -> str:
    """The line the conductor relay (`story_run.take_stand_gap_answers`) gives for ONE gap: what the person writes for it, the block
    its word passes, the stage - and the options THIS card takes (t-409 H3, FR-10). A card with `remedy.offers` takes ONLY those and
    the line says so, with the words, and that any other word is not recorded (the person is told the words that apply to that
    card); a card with none takes every option the relay's map lists, as every card did before. The per-card words come from
    `offered_options`, the function the card and the answer reader use, so the three cannot disagree about `change`."""
    word_of_option = stand_gap_word_of()
    line = (f"- {form}: block `{C.STAND_GAP_MATCH_PREFIX} {gap.get('id')}`, stage {gap.get('stage') or default_stage}; ")
    lasting = ("; this card also takes `accept always` (the option `accept`, and one row in the environment record - "
               "`references/conductor-actions.json`)" if lasting_offered(gap) else "")
    if not isinstance((gap.get("remedy") or {}).get("offers"), list):
        return line + "takes every option above" + lasting
    offered = offered_options(gap)
    return (line + "takes ONLY " + ", ".join(f"`{o}`" for o in offered) + " (the words: "
            + ", ".join(f"`{word_of_option[o]}`" for o in offered if o in word_of_option)
            + "); any other word is NOT recorded - tell the person the words that apply to this card" + lasting)


def _gap_options(gap: dict) -> list:
    """The options a card takes, in order: its own `remedy.offers` when it carries one (a reporter card), else the four of the
    record, `apply` only when the card shows an exact change - the rule that held before cards carried `offers`."""
    remedy = gap.get("remedy") if isinstance(gap.get("remedy"), dict) else {}
    if isinstance(remedy.get("offers"), list):
        return [str(o) for o in remedy["offers"]]
    return [o for o in C.STAND_GAP_OPTIONS if o != "apply" or not C.remedy_errors(remedy)]


def _command_form(text: str, spec: dict, raw: str):
    """`{arg, why}` when `text` (what follows the colon) is the word `command` - alone, or with a value after it - else None.
    `why` is '' for a line that can be read, else the reason it cannot (in words); `arg` is the value as the person wrote it:
    case and inner spacing kept, one pair of backquotes round the whole value peeled."""
    match = re.match(r"^[`'\"]?" + re.escape(spec["word"]) + r"[`'\"]?(?:\s+(?P<arg>\S.*?))?\s*$", text.strip(), re.IGNORECASE)
    if not match:
        return None
    arg = match.group("arg") or ""
    if arg.startswith("`") and arg.endswith("`") and len(arg) >= 2 and arg.count("`") == 2:
        arg = arg[1:-1].strip()
    out = {"arg": arg, "why": ""}
    if not arg:
        out["why"] = f"the word `{spec['word']}` needs the command after it, written as you would type it; nothing is changed"
    elif "?" in raw:
        out["why"] = "the line asks a question, and a question is never an answer; nothing is changed"
    elif any(arg.endswith(mark) for mark in spec["continuation_marks"]):
        out["why"] = ("the line ends with a mark that says the command goes on in the next line; give the whole command in one "
                      "line; nothing is changed")
    elif not re.fullmatch(spec["value"], arg):
        out["why"] = "the command is longer than 1000 characters, or has no word in it; give a shorter one; nothing is changed"
    else:
        try:
            from stand_identity import command_argv
            command_argv(arg)
        except ValueError as exc:
            out["why"] = f"the command cannot be split into words ({exc}); close the quote and give it again; nothing is changed"
        except Exception:
            pass        # the splitter is not importable here: the probe splits it again and refuses in words
        if not out["why"] and stand_gap_word_index().get(_word_key(arg)):
            out["why"] = ("the line holds two answers: after `" + spec["word"] + "` comes a word that is an answer of its own; "
                          "give the command, or give that one word alone; nothing is changed")
    return out


def _clip_whole_spans(text: str, limit: int) -> str:
    """`text` cut to `limit` characters, never inside a backquoted span: a cut that would leave a span open is moved to
    before it, and the cut is marked with an ellipsis. Whole text when it fits."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if cut.count("`") % 2:
        cut = cut[:cut.rfind("`")]
    return cut.rstrip(" ,;:(") + "…"


def _one_line(text, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(",;:. ") + "…"


LEVEL_CASES_NAMED = 6           # a level card names this many of its cases, then "and K more"
COVERED_WORDS_LIMIT = 160       # the person's words in the covered block: whole up to here, cut at a word beyond
LASTING_LEVEL = ("Is this how this command always is, or temporary? A word alone answers for this story; `accept always` "
                 "records it in the project's environment record for this exact command, on every machine that uses this "
                 "project, and no story asks it again until the command changes or you take it back.")
LASTING_CASE = ("Is this temporary, or how {stand} always is? A word alone answers for this story; `accept always` records it "
                "in the project's environment record for {stand} as it is configured now, and no story asks it again until "
                "the stand's address changes or you take it back.")


def _gap_heading(gap: dict, forms: dict, files: dict, card: bool = True) -> str:
    """The heading of one card (B-414 R3): a LEVEL gap says it is a whole level and which cases it costs (six named, then "and K
    more"); a case gap is today's heading and, on its card (`card`), says it is one case - the one-line list of the cards beyond the
    limit keeps today's text."""
    if _role_card(gap):
        role, form = str(gap.get("role") or ""), forms[str(gap.get("id"))]
        if gap.get("scope") == "product_role":
            return f"{form} — \"{role}\", a role the test strategist found in this story's requirements"
        count = len(gap.get("cases") or [])
        return (f"{form} — the account of the role \"{role}\" on the stand \"{gap.get('stand') or 'this stand'}\" "
                f"({count} case{'' if count == 1 else 's'})")
    if gap.get("scope") == "level":
        cases = [str(c) for c in gap.get("cases") or []]
        shown = ", ".join(case_ref(c, files) for c in cases[:LEVEL_CASES_NAMED])
        if len(cases) > LEVEL_CASES_NAMED:
            shown += f" and {len(cases) - LEVEL_CASES_NAMED} more"
        count = f"{len(cases)} case{'' if len(cases) == 1 else 's'}: {shown}" if cases else "no case named"
        return f"the {gap.get('contour')} tests — a whole level: every {gap.get('contour')} test of this story ({count})"
    needs = str(gap.get("requirement") or "").strip()
    form, case_id = forms[str(gap.get("id"))], str(gap.get("case_id") or "")
    who, more = case_ref(form, files), []
    if case_id and form != case_id and form != str(gap.get("case") or ""):
        more.append(f"case {case_ref(case_id, files)}")   # a gap named by its own id: the case it costs
    parts = [str(p) for p in (gap.get("partitions") or [])][:6]
    if parts:
        more.append(", ".join(parts))
    if more:
        who += f" ({'; '.join(more)})"
    return f"{who} — " + (f"needs {needs}" if needs else "a test the stand cannot run yet") + (" — one case" if card else "")


def _covered_block(covered: list, forms: dict) -> list:
    """`## Decided once for this environment (N)` (B-414 R3): one line per gap the environment record covers - what it says
    cannot be checked here, the date and the person's own words (names only, at most 160 characters) - and the line that has one
    asked again. Shown at both gates, for a level and for a case gap alike."""
    import stand_gaps
    if not covered:
        return []
    lines = [f"## Decided once for this environment ({len(covered)})", ""]
    for gap in covered:
        row = gap.get("property") if isinstance(gap.get("property"), dict) else {}
        name = forms.get(str(gap.get("id")), stand_gaps._label(gap))
        words = _one_line(stand_gaps.names_only(row.get("words")), COVERED_WORDS_LIMIT)
        if stand_gaps.pk_property_of(gap):       # PK0-9: a not-a-role answer says its own date inside the sentence
            lines.append(f"- {name}: {stand_gaps.covered_says(gap)} — you wrote: \"{words}\"")
        else:
            lines.append(f"- {name}: {stand_gaps.covered_says(gap)} — you wrote on {str(row.get('at') or '')[:10]}: \"{words}\"")
    ask = next(iter(environment_words()), None)
    if ask:
        lines += ["", f"To have one asked again, write `<name>: {ask['word']}` on a line of its own."]
    return lines


def _lasting_lines(open_gaps: list) -> list:
    """The ONE lasting question, once per kind of card that offers `accept always` (B-414 R3): shown only when an open card
    offers it - never for a gap whose cause is a file or the machine, which has no key (M13)."""
    offering = [g for g in open_gaps if lasting_offered(g)]
    out = []
    if any(g.get("scope") == "level" for g in offering):
        out.append(LASTING_LEVEL)
    case = next((g for g in offering if g.get("scope") != "level"), None)
    if case is not None:
        out.append(LASTING_CASE.format(stand=str(case.get("stand") or "this stand")))
    return out


class CardCtx(NamedTuple):
    """What every card of one packet reads (t-683 D9). Immutable, and tuple unpacking still gives `rows, word_of, forms, files`:
    `word_of` is the dict `stand_gap_word_of` builds, `forms` the id the person writes for each gap, `files` the case files linked."""
    rows: list
    word_of: dict
    forms: dict
    files: dict


def _card_context(task_root, gaps: list, covered: list) -> CardCtx:
    """(rows, word_of, forms, files) - what every card of one packet reads, taken before the first line is made: the data file's
    answers, the option -> word map, the id the person writes for each gap (the covered ones too) and the case files the cards link.
    `task_root` may be None (no case file to link)."""
    rows = stand_gap_words()
    word_of = stand_gap_word_of(rows)       # `rows` is the default (standing) list: one read of the file, as before
    forms = stand_gap_form_ids(list(gaps) + covered)
    links = read_json(Path(task_root) / "state" / "story-case-links.json", {}) or {} if task_root else {}
    files = case_files(Path(task_root), links, [forms[str(g.get("id"))] for g in gaps]
                       + [str(g.get("case_id") or "") for g in gaps]
                       + [str(c) for g in gaps if g.get("scope") == "level" for c in g.get("cases") or []]) if task_root else {}
    return CardCtx(rows, word_of, forms, files)


def _short_line(gap: dict, answer: dict, asked_again: str, ctx: CardCtx) -> tuple:
    """(the one line of a gap beyond the card limit, whether the gap is still open): its heading, what is missing and a tail that says
    it was answered (here, or at gate A) or asked again - open when it has no answer or the answer was given for a world that moved."""
    import stand_gaps
    if asked_again:
        tail = f" (asked again: {_one_line(stand_gaps.names_only(asked_again), 120)})"
    elif answer:
        tail = (f" (answered at gate A: {ctx.word_of.get(answer.get('option'), 'in your own words')})"
                if answer.get("gate") == "A" else
                f" (answered: {ctx.word_of.get(answer.get('option'), 'in your own words')})")
    else:
        tail = ""
    line = f"- {_gap_heading(gap, ctx.forms, ctx.files, card=False)}: " +_one_line(stand_gaps.names_only(gap.get("missing")), 160) + tail
    return line, bool(not answer or asked_again)


def _understood_line(gap: dict) -> str:
    """The card's line for what the factory's helper read of the unread report (B-416 N7): the text when it is fit to print, else
    the note that there is one. The cut is `report_adapt.UNDERSTOOD_SHOWN`, read in the same `try` as the rule that says what may be
    printed: when that module cannot be loaded nothing is printed (FR-59), and the import stays where a failure is caught."""
    import stand_gaps
    said = stand_gaps.names_only(gap["understood"])
    try:
        import report_adapt                        # ONE definition of "fit to print": the rule `understood` refuses by
        said = said[:report_adapt.UNDERSTOOD_SHOWN]
        printable = not report_adapt.unfit_words(said)
    except Exception:
        printable = False                      # an unknown is never printed (FR-59)
    # TEMPORAL: a record written before `report_adapt.py understood` refused such text may still hold a script name, a flag or
    # a path; the person is told there is a note, never shown it (FR-6)
    return "  the factory's helper read it: " + (said if printable
                                                else "the factory's helper left a note it cannot print here (names only)")


def _option_lines(gap: dict, options: list, ctx: CardCtx) -> list:
    """The answers of a card of project knowledge, each followed by the three price lines (`_price_labels`; t-2142 §3 (2), (6)). An
    option of an offered word (`says`) is written with its word from the data file and the card's own id; any other option is the
    person's own words on a line of their own (`head`). The labels and the words are data: nothing here is a word of code."""
    labels = _price_labels()
    role = str(gap.get("role") or "")
    lines = [f"  the answers, in your own words on a line of their own, naming \"{role}\":" if gap.get("scope") == "product_role"
             else "  the answers:"]
    form = ctx.forms[str(gap.get("id"))]
    for option in options:
        word = ctx.word_of.get(str(option.get("option")))
        if option.get("says") and word:
            head = f"`{form}: {word}` - {option['says']}"
        else:
            head = str(option.get("head") or option.get("says") or "")
        lines.append(f"  - {head}")
        lines += [f"    {label} {option.get(key, '')}" for label, key in zip(labels, ("factory", "you", "story"))]
    return lines


def _card(gap: dict, answer: dict, asked_again: str, task_root, had_gate_a: bool, ctx: CardCtx) -> tuple:
    """(the lines of one card in full, ending with a blank line, whether the gap is still open): the test, what is missing, the fix, and
    the answer the person already gave - or, with none, that it is asked here (and, at a story that holds a gate A word, that none covers it)."""
    import stand_gaps
    word = "Product role to confirm" if gap.get("scope") == "product_role" else "Stand gap"
    lines = [f"{word}: {_gap_heading(gap, ctx.forms, ctx.files)}"]
    # a card of project knowledge writes its two lines whole: `_role_card_words` already bounds them (3 titles of 70 characters, then
    # "and K more", then the sign-in phrase) and a cut would drop the end of the sentence (t-2142 PK0-4, F2)
    whole = _role_card(gap)
    lines.append(f"  the test: {stand_gaps.names_only(gap.get('the_test'))[:None if whole else 200]}")
    lines.append(f"  missing:  {stand_gaps.names_only(gap.get('missing'))[:None if whole else 240]}")
    if gap.get("scope") == "role" and gap.get("in_roster") is False:
        lines.append(f"  \"{gap.get('role')}\" is not among the product's roles yet; an account for it adds it.")
    if gap.get("changed_since"):
        lines.append("  your earlier answer for this environment does not apply now: "
                     + stand_gaps.names_only(gap["changed_since"])[:240])
    if gap.get("ran_red"):
        # the test RAN and failed: the person is the last reader who can tell the stand from the product
        lines.append(f"  {stand_gaps.names_only(gap.get('ran_red'))[:240]}")
    if gap.get("understood"):
        # B-416 N7: what the factory's helper read of the unread report - the card is the person's only stop for it, with this
        lines.append(_understood_line(gap))
    options = [o for o in gap.get("options") or [] if isinstance(o, dict)] if _role_card(gap) else []
    if options:
        # a card of project knowledge: the answers with their price lines (human-questions.md item 6) instead of `the fix:`; an
        # answered card shows the answer, not the question (FR-7)
        if not answer or asked_again:
            lines.extend(_option_lines(gap, options, ctx))
    else:
        fix = stand_gaps.fix_line(gap.get("remedy"))
        # a reporter card's line may carry the command the profile records (B-220 F6): it is longer, so it gets a longer limit,
        # and a limit never cuts INSIDE a backquoted command - half a command is worse than none
        lines.append(f"  the fix:  {_clip_whole_spans(fix, 480) if (gap.get('remedy') or {}).get('kind') == 'reporter' else fix[:240]}")
    if gap.get("lasting") == "fault":
        import environment_record
        lines.append("  " + environment_record.fault_line(gap.get("reason_class")))    # why `accept always` is not offered (M13)
    is_open = True
    if answer:
        # the word the person gave; for words of their own, the words (the recorded decision of a word on the
        # list carries the driver's own bookkeeping sentence, which is not for the person to read back)
        said = (ctx.word_of[answer["option"]] if answer.get("option") in ctx.word_of else
                "in your own words - " + stand_gaps.names_only(answer.get("words"))[:160])
        at_gate_a = answer.get("gate") == "A"
        lead = ("at gate A you answered" if asked_again else "answered at gate A") if at_gate_a else "answered"
        applied = (stand_gaps.level_applied(task_root, gap)
                   if task_root and gap.get("scope") == "level" and answer.get("option") == "accept" else None)
        partial = bool(applied) and len(applied) < len(stand_gaps.gap_cases(gap))    # an answer from before the level took every case (E2)
        lines.append(f"  {lead}: {said}"
                     + (f" — applied to {', '.join(applied)} only; the other {len(stand_gaps.gap_cases(gap)) - len(applied)} are asked"
                        if partial else "")
                     + (f" ({answer['at']})" if answer.get("at") else ""))
        if asked_again:
            lines.append(f"  since then: {stand_gaps.names_only(asked_again)}")
        is_open = bool(asked_again or partial)
    elif had_gate_a:
        lines.append("  I hold no answer from gate A that covers this case, so it is asked here.")
    lines.append("")
    return lines, is_open


def _answer_words(gaps: list, open_ids: list, rows: list, forms: dict, word_of: dict) -> list:
    """The lines that tell the person how to answer the open cards: the form with an example, the words some open card takes (a
    reporter card takes only its own `offers`), the lasting question, and the one line a case with several gaps needs (B-220 part 2)."""
    lines = []
    example = forms[open_ids[0]]
    # the example uses a word of the data file too - none of the words is spelled in code
    sample = word_of.get("accept") or rows[0]["word"]
    lines.append(f"To answer a stand gap, write a line of its own: `{STAND_GAP_FORM}`, for example "
                 f"`{example}: {sample}`. The words:")
    # B-220 part 2: a card that carries `remedy.offers` (the reporter card) takes only those words. A word is listed when
    # some OPEN card takes it, so a packet of reporter cards with no cure never lists `change`, and `command` (not one of
    # `stand_gap_words`: `probe_answers`) is listed only while a card offers it.
    by_gap = {str(g.get("id")): g for g in gaps}
    # (a card with no `offers` lists all four, as before: `change` carries its own note, and the reader holds the rule)
    taken = {o for gid in open_ids for o in offered_options(by_gap[gid])}
    probe = probe_answers()
    listed = list(rows)
    if probe["command"] and "command" in taken:
        at = next((i for i, row in enumerate(listed) if row["option"] == "theirs"), len(listed))
        listed.insert(at, {"option": "command", "word": probe["command"]["word"], "says": probe["command"]["says"]})
    lasting_open = [by_gap[g] for g in open_ids if lasting_offered(by_gap[g])]
    if lasting_open:                       # `accept always` is listed right after `accept`, only while a card offers it
        row = next((r for r in stand_gap_words(lasting=True) if r["lasting"]), None)
        at = next((i for i, r in enumerate(listed) if r["option"] == "accept"), len(listed) - 1) + 1
        if row:
            listed.insert(at, row)
    for row in listed:
        if row["option"] not in taken:
            continue
        note = (" (offered only for a gap whose card shows an exact change)" if row["option"] == "apply" else
                f" ({probe['command']['note']})" if row["option"] == "command" and probe["command"]["note"] else "")
        lines.append(f"- `{row['word']}` — {row['says']}{note}")
    if probe["reporter_accept"] and "accept" in taken and any(
            (by_gap[gid].get("remedy") or {}).get("kind") == "reporter" for gid in open_ids):
        lines.append(probe["reporter_accept"])
    lines.extend(_lasting_lines(lasting_open))
    if any(forms[g] != str(next((x.get("case_id") for x in gaps if str(x.get("id")) == g), ""))
           for g in open_ids if by_gap[g].get("scope") != "level"):
        # a case with several gaps: the card is headed by the gap's own id, and that is what the line must start with
        lines.append("Where a card is headed by something other than a case id (a case with several gaps), start "
                     "the line with exactly what the card is headed by.")
    lines.append(APPROVAL_FIRST_LINE_TAIL)
    return lines


def stand_gap_card_lines(task_root, gaps: list, decided: dict | None = None, limit: int | None = MAX_GAP_CARDS,
                         had_gate_a: bool = False, covered: list | None = None) -> list:
    """The `## Stand gaps (N)` block of a gate packet, in words: a card per gap (the first `limit` in full, the rest
    as one line each; `limit=None` shows every card in full), the answers the person can give and the ONE form to
    give them in. THE renderer of both gates (t-357, FR-10): gate A's rehearsal and gate B's packet cannot tell the
    same person two different things about one kind of gap.

    No script name, no flag, no block id: the card never says how the factory records the answer. A gap the person
    already answered shows the answer, not the question (FR-7). `task_root` may be None (no case file to link).

    B-361: an answer of `stand_gaps.gate_b_answers` may carry `gate: "A"` (the person gave it at gate A, for the case) and
    `change` (what happened since that stops it covering the gap): a gate A answer with no change shows `answered at
    gate A: <word>` and stays closed; one with a change shows the word, then `since then: <change>`, and the gap is
    OPEN again with its words. `had_gate_a` says the story holds some gate A word: a gap with no answer then says that
    none covers it, so the person is not left to think it was lost. With the defaults the text is exactly what it was.

    B-414: a card says whether it speaks of one case or of a whole level (`scope`); a card that offers `accept always` says
    in one line what the word records; a gap the environment record covers (`covered`) is no card - it is one line of the
    block `Decided once for this environment`, which is all the packet holds when every gap is covered."""
    decided = decided or {}
    covered = [g for g in covered or [] if isinstance(g, dict)]
    ctx = _card_context(task_root, gaps, covered)
    rows, word_of, forms, _files = ctx           # the cards read `files` from `ctx`

    if not gaps:
        return _covered_block(covered, forms)
    lines = [f"## Stand gaps ({len(gaps)})", ""]
    open_ids = []
    for position, gap in enumerate(gaps):
        gid = str(gap.get("id"))
        answer = decided.get(gid) or {}
        asked_again = str(answer.get("change") or "")       # a gate A answer that no longer covers the gap (B-361)
        if limit is not None and position >= limit:
            line, is_open = _short_line(gap, answer, asked_again, ctx)
            lines.append(line)
        else:
            card, is_open = _card(gap, answer, asked_again, task_root, had_gate_a, ctx)
            lines.extend(card)
        if is_open and not _offers_nothing(gap):        # a card that takes no word (the confirm card) is no open id of the answer block
            open_ids.append(gid)
    if limit is not None and len(gaps) > limit:
        # one line each, and the same words answer them: the card above is the explanation of the four
        lines.append("")
    if open_ids and rows:
        lines.extend(_answer_words(gaps, open_ids, rows, forms, word_of))
    elif open_ids:
        lines.append("The list of answers to a stand gap could not be read — that is the factory's own gap; say in "
                     "your own words what should happen to each one.")
    while lines and not lines[-1].strip():
        lines.pop()
    if covered:
        lines += ["", *_covered_block(covered, forms)]
    return lines


gate_b_card_lines = stand_gap_card_lines   # the name t-342 gave it; one renderer for both gates (t-357)


def case_files(task_root: Path, links: dict, case_ids) -> dict:
    """{case id: project-relative path of the case file the person can open}, for the cases that
    have one; a case with no file on disk is absent, never given a guessed path.

    The brief names a case by its id, and an id the person cannot look up explains nothing
    (`references/human-questions.md`, `explained_ids`). The file beside the id is the
    explanation: the authoring copy under `work/test-cases/` when there is one (it is named for
    the case), otherwise the pinned version the story's own links record. B-009 part 2, critic
    t-039 F3: twelve ids of a real gate A brief were journalled as unexplained."""
    task_root = Path(task_root)
    authoring = task_root / "work" / "test-cases"
    index = {}
    if authoring.is_dir():
        for path in sorted_paths(authoring.rglob("*.md")):
            index.setdefault(path.stem, path)
    pinned = {str(link.get("case_id")): link for link in (links.get("links") or [])
              if isinstance(link, dict) and link.get("case_id")}
    out = {}
    for case_id in dict.fromkeys(str(c) for c in case_ids or []):
        path = index.get(case_id)
        if path is None:
            raw = str((pinned.get(case_id) or {}).get("path") or "")
            candidate = task_root / raw if raw and not Path(raw).is_absolute() else None
            path = candidate if candidate is not None and candidate.is_file() else None
        if path is not None:
            out[case_id] = portable(path, task_root)
    return out


def case_ref(case_id, files: dict) -> str:
    """`[TC-001](path)` when the case has a file to open, the bare id when it has none."""
    path = (files or {}).get(str(case_id))
    return f"[{case_id}]({path.replace(' ', '%20')})" if path else str(case_id)


def plan_gloss(rows, limit: int = 60) -> dict:
    """{plan row id: what the row verifies, in a few words}, from the row's own field.

    The words are the strategist's; this only shortens them, at a word, so that `TS-3 (what it
    verifies)` can stand where a bare `TS-3` used to. A row that says nothing has no entry."""
    out = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not str(row.get("id") or "").strip():
            continue
        words = " ".join(str(row.get("what_we_verify") or row.get("title") or "").split())
        words = words.replace("(", "").replace(")", "")
        if not words:
            continue
        if len(words) > limit:
            words = words[:limit].rsplit(" ", 1)[0].rstrip(",;:. ") + "…"
        out[str(row["id"]).strip()] = words
    return out


# THE list of what the person approves at gate A (AR-14): exactly two documents. The pinned cases are part of the plan (the
# plan embeds them, `render_case_appendix.embed`), so `case-appendix.md` and `requirements-register.md` are working files and
# are not named; the brief is a summary, not a document to approve (the owner's word of 22.10.2026, variant (a); GW1-11).
# Code reads the names from here (the first line of the message, `gate_a_approval_line`). The texts that name them -
# `phases/s4.md`, the `understanding.md` template - hold literals; `test_gate_a_two_documents.py` K6 pins that they agree.
GATE_A_DOCUMENTS = (("understanding", "understanding.md"), ("plan", "test-plan.md"))

# RN1-4: the message of gate A is a FILE the code writes (the one writer is `write_gate_message`), and the conductor prints
# it whole. `GATE_MESSAGE` lives under `work/`; its record - what `gate_shown.py` (the Stop hook) reads as "gate A was asked in
# this session" - under `state/`. `phases/s4.md` names the message file as a literal; `test_gate_shown.py` pins that it agrees.
GATE_MESSAGE = "gate-a-message.md"
REFERENCE_BEHAVIOURS = "reference-behaviours.md"      # F1 (t-2551): every behaviour of the old version the factory saw, written beside the message
GATE_MESSAGE_RECORD = "gate-message.json"


def gate_a_approval_line() -> str:
    """The first line of the gate A message after the title, built by code from `GATE_A_DOCUMENTS` (AR-16): the two
    documents the person approves and the brief as a summary. It names both documents even when one is not on disk yet
    (the paths list below shows only the files that exist - today's handling of an absent document)."""
    names = ", ".join(f"`{name}`" for _, name in GATE_A_DOCUMENTS)
    return f"**Approve: {names}.** This brief is a summary of them, not a document to approve."


def documents(task_root: Path) -> dict:
    """The documents the person approves at gate A, each wherever the registry puts it.

    Both are written FOR a person and live at the story root (`artifact-contract.md`);
    looking for them under `work/` dropped the plan and understanding.md from the first line of the message
    — the two documents gate A is actually about. `contract.artifact` reads the canonical path
    and the pre-`work/` spelling a 0.7.4 story still has."""
    out = {}
    for name, artifact_name in GATE_A_DOCUMENTS:
        try:
            import contract
            path = contract.artifact(task_root, artifact_name)
        except Exception:
            path = task_root / "work" / artifact_name
        if Path(path).is_file():
            out[name] = portable(path, task_root)
    return out


def documents_with_reference(task_root: Path, reference: dict) -> dict:
    """`documents` plus, for a story whose reference snapshot was read and holds behaviours, the document of every behaviour seen
    (`work/reference-behaviours.md`, F1). It is listed because `write_gate_message` writes it with the message; the driver path
    (`QA_FACTORY_RUN_MODE=driver`) writes no message file, so it names no document there (FR-37: a path named is a path written).
    Sets `reference["document"]` (the path) for the count line's pointer."""
    out = documents(task_root)
    if reference.get("state") == "read" and reference.get("total") and os.environ.get(RUN_MODE_ENV, "").strip() != "driver":
        reference["document"] = f"work/{REFERENCE_BEHAVIOURS}"
        out["reference behaviours"] = reference["document"]
    return out


def register_view(task_root):
    """(question_register.load(task_root), "") or (None, why it could not be read).

    The ONE reader of a question's status is `question_register.load` (FR-17); this wraps it so
    that a register that cannot be read degrades to today's behaviour plus one sentence saying
    so, never to an exception and never to a status that was not read (FR-41). A register file
    that is absent is a story older than the register: the same degradation."""
    try:
        import question_register
        view = question_register.load(task_root)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not view.get("register_present"):
        return None, "the story has no questions register file"
    if view.get("problems") and not view.get("questions"):
        return None, "; ".join(str(p) for p in view["problems"][:2])
    return view, ""


def _mentions(text: str, ident: str) -> bool:
    """Does `text` name `ident` as a word? Bounded by the ends, spaces or punctuation, but not by
    a word character or by `/ . # -`: `Q1` is not in `Q10`, `R-1` is not in `R-14`, and an id
    inside a path or a URL is not the person naming it. Same rule as `question_register`, and the
    same error direction: toward NOT naming, so a question stays open (FR-41). An id is never
    matched as a substring (B-181 - `Q1` was found inside `Q10`)."""
    ident = str(ident or "").strip()
    if not ident:
        return False
    import question_register as QR
    return re.search(QR.ID_BOUNDARY_BEFORE + re.escape(ident) + QR.ID_BOUNDARY_AFTER, str(text or "")) is not None


def _fork_closes(question_ids, by_question: dict) -> bool:
    """Is a reading fork closed by the questions it names? Every one of them is in the register and `question_register.closes`;
    a fork that names none, or one the register does not hold, is not closed."""
    import question_register as QR
    ids = [str(q) for q in question_ids or []]
    return bool(ids) and all(QR.closes(by_question.get(q)) for q in ids)


def _answers_whole(task_root) -> bool:
    """Was the answers file read in full? False when a line was broken, was no object, or the file could not be
    read at all (`question_register.answers_for_brief(...)["unreadable"]`) - or when that cannot be asked: then no
    answer closes a card, and the questions it may settle are shown again (FR-41)."""
    try:
        import question_register as QR
        return not QR.answers_for_brief(task_root)["unreadable"]
    except Exception:
        return False


ANSWERS_SHOWN = 10        # lines of "Already decided" for answered questions; the rest is counted, not cut silently
ANSWER_WORDS = 160        # characters of one answer's words in that section
UNREAD_ANSWERS_LINE = ("some of your earlier answers could not be read; questions they settle are shown again above")


def answered_questions(task_root, view) -> dict:
    """`{"items": [...], "unreadable": bool}` - the questions the person has closed, for "Already decided by you".

    Read ONLY through `question_register.answers_for_brief` (AR-13: the answers file is the carrier, and this is the
    same reader the next role's brief uses); an entry is kept only when `question_register.closes` says the question is
    closed on the row as it stands, so the section never lists as decided what a card above asks again. When the answers
    file could not be read in full NO item is listed (`contradiction_questions` closes no card then, so none may be
    claimed decided - FR-10); `unreadable` is True and the section says so. Each item is `{id, status, reading,
    reading_text, words, where}` in the register's order. A kept-open (`deferred_to_report`) question is not here: it is
    not closed."""
    try:
        import question_register as QR
        brief = QR.answers_for_brief(task_root)
    except Exception:
        return {"items": [], "unreadable": True}
    if brief["unreadable"]:
        return {"items": [], "unreadable": True}
    by_question = {str(q.get("id")): q for q in (view or {}).get("questions", [])}
    items = [{"id": a["id"], "status": a["status"], "reading": a["reading"], "reading_text": a["reading_text"],
              "words": a["words"], "where": a["where"]}
             for a in brief["answers"] if QR.closes(by_question.get(a["id"]))]
    return {"items": items, "unreadable": False}


def _answered_lines(data: dict) -> list:
    """The lines of the answered questions inside "Already decided by you" (without the heading): one line when the
    answers could not be read in full, then up to ANSWERS_SHOWN question lines, then `(+K more - <file>)`.
    The text of one answer is `question_register.answer_text`, whitespace squeezed and cut here at ANSWER_WORDS characters
    with `…` (this is a recap for a person, who has the whole text in the answers file; the role-facing line in the S5
    brief is NOT cut)."""
    import question_register as QR
    answered = data.get("answered") or {}
    items = [i for i in answered.get("items") or [] if isinstance(i, dict)]
    lines = [f"- {UNREAD_ANSWERS_LINE}"] if answered.get("unreadable") else []

    def clipped(text) -> str:
        text = " ".join(str(text or "").split())
        return text if len(text) <= ANSWER_WORDS else text[:ANSWER_WORDS] + "…"

    for item in items[:ANSWERS_SHOWN]:
        where = QR.where_words(item.get("where"))
        text, is_words = QR.answer_text(item)
        text = clipped(text)
        if not text:
            lines.append(f"- {item['id']}: answered, no words recorded (your answer {where})")
        elif is_words:
            lines.append(f"- {item['id']}: \"{text}\" (your words {where})")
        else:
            lines.append(f"- {item['id']}: {text} (your answer {where})")
    if len(items) > ANSWERS_SHOWN:
        lines.append(f"- (+{len(items) - ANSWERS_SHOWN} more — {'/'.join(QR.ANSWERS_REL)})")
    return lines


def contradiction_questions(task_root: Path, rows: list, pipeline: dict | None = None) -> list:
    """A plan row flagged `source_conflict` / `oracle_unknown` is a question for the owner.

    S2 records the disagreement in the register's `## Contradiction matrix`, S3 carries it onto
    the row, and the person is the only one who can settle which reading is right — so the
    quote reaches gate A with the row that rests on it, in the same shape as the readiness
    questions beside it. A conflict whose id the person has already answered about is not
    asked twice.

    The matrix names BOTH sides, so the question is built with both: reading a is the
    requirement as the register wrote it, reading b is what the source it contradicts says,
    and each carries what the factory does once it is chosen. On TP1-15045 the same
    question went out as one sentence with no readings, stayed unanswered for the whole story,
    and the factory tested the letter of the AC — the owner answered it in one minute the
    moment the two readings were put side by side."""
    pipeline = pipeline if pipeline is not None else (read_json(Path(task_root) / "pipeline.json", {}) or {})
    recorded = _decision_text(pipeline)
    try:
        import planning_contract
        register = planning_contract.story_register_text(task_root)
        quotes = planning_contract.register_contradictions(register)
        readings = planning_contract.register_contradiction_readings(register)
    except Exception:
        return []
    # A row that names its register question(s) (`question_refs`) is ALREADY a card: the register
    # question carries the row's consequence, and a second `R-n` card for the same fork is the
    # duplicate cmp1 showed (Q1 and R-9 for one disagreement). Only when EVERY ref resolves to an
    # id of the register, exactly: a row with no refs, or one ref that resolves nowhere, still
    # produces its question - nothing a person must decide disappears (B-216).
    view, _unread = register_view(task_root)
    register_ids = {str(q.get("id")) for q in (view or {}).get("questions", [])}
    # HF4-8: a contradicted R whose reading fork NAMES register questions (the `Decision` cell starts with the id) is
    # closed when every one of them is closed by the person's answer (`_fork_closes`). Nothing reads as closed when
    # the register cannot be read or when the answers file could not be read in full: those questions are asked.
    try:
        forks = planning_contract.register_fork_questions(register)
    except Exception:
        forks = {}
    by_question = {str(q.get("id")): q for q in (view or {}).get("questions", [])}
    answers_whole = _answers_whole(task_root)
    # RN1-14 (D1-B B3): a contradiction is not asked when (1) the person decided its fork in their OWN words (the quote form, checked
    # against state/words by the one reader), or (2) it is a contradiction with the CODE and the register row already carries
    # `code_says: contradicts` (a candidate bug, not a question). A contradiction between two REQUIREMENT sources keeps its card. An
    # unreadable register closes nothing (FR-59).
    try:
        import branch_accounting as BA
        by_words = BA.decided_by_words(task_root, register)
        code_rows = {row["r"] for row in C.register_rows(register) if BA.code_says_contradicts(row)}
    except Exception:
        by_words, code_rows = {}, set()
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not (row.get("source_conflict") or row.get("oracle_unknown")):
            continue
        question_refs = row.get("question_refs")
        if isinstance(question_refs, list) and question_refs and all(
                isinstance(ref, str) and ref.strip() in register_ids for ref in question_refs):
            continue
        try:
            refs = planning_contract.row_requirements(row)
        except Exception:
            refs = []
        named = [r for r in refs if r in quotes]
        if named:
            # The card is built for the FIRST contradiction nobody has settled; a row with some of them settled keeps
            # the rest (a contradiction the person was not asked about does not vanish because a neighbour was).
            open_refs = [r for r in named if not (_mentions(recorded, r) or (
                answers_whole and _fork_closes(forks.get(r), by_question)) or r in by_words or (
                r in code_rows and set((readings.get(r) or {}).get("origins") or ()) == {"code"}))]   # F3: ONLY code contradicts
            if not open_refs:
                continue
        else:
            if any(_mentions(recorded, ref) for ref in refs):
                continue
            open_refs = []
        named = open_refs
        row_id = str(row.get("id", "?"))
        what = ("; ".join(f"{ref}: {quotes[ref]}" for ref in named) if named
                else "no settled expected value for this row")
        # `TS-3 (what it verifies)`: a row id alone is not something the person can look up.
        said = plan_gloss([row]).get(row_id)
        label = f"{row_id} ({said})" if said else row_id
        question = {"id": named[0] if named else row_id,
                    "question": f"{label} rests on a contradiction — {what}. "
                                "Which reading do we test?",
                    "severity": "blocker" if row.get("source_conflict") else "major",
                    "owner_role": "po_ba"}
        both = readings.get(named[0]) if named else None
        if both:
            question["question"] = (f"{row_id} ({named[0]}) rests on a contradiction between two "
                                    "sources. Which reading do we test?")
            question["source_says"] = [
                {"quote": both["statement"] or what,
                 "where": f"requirements-register.md, {named[0]}"},
                {"quote": both["quote"],
                 "where": f"requirements-register.md contradiction matrix, {both['against']}"}]
            first_from = both["first_from"]       # the register's own columns decide (planning_contract.register_reading_origin)
            question["readings"] = [
                {"reading": both["statement"] or what, "from": first_from,
                 "if_chosen": f"{row_id} keeps its disposition and its Then asserts the "
                              "requirement as the register wrote it"},
                {"reading": both["quote"], "from": both["origin"],
                 "if_chosen": f"the Then of {row_id} is rewritten to what {both['against']} "
                              "says; until you answer, that assertion stays `oracle_unknown` "
                              "and the row is not automated on it"}]
        out.append(question)
    return out


def _case_id_example(task, task_root) -> str:
    """One well-formed case id in THIS story's project form, for the "how to answer" block."""
    try:
        return str(C.case_id_example(task, task_root) or "")
    except Exception:
        return ""


def accepted_review_summary(task_root: Path) -> list:
    """`[{plan_row, verdict[, basis][, no_critic]}]`: the critic's word on each critical plan row AS GATE A READS IT, or []
    when there is none to show. `basis` (only on a row that is not accepted and was read per row) is the review's
    `verdict_basis`, the field the brief words its reason from (never the conductor's prose, which names dispatches);
    `no_critic: True` marks a row no accepted case critic covered, whose word is the older whole-file rule's and not a
    review of that row (m-4 of t-1103). `stale: True` marks a row whose case designer was accepted after its critic
    (RN1-20; `Controller.review_is_stale`): the critic's word is not a review of the cases as they stand.

    FB-19: the brief's `critic_verdict` is the newest findings file's word, while the decision gate A records
    carries one word per plan row from the accepted critic's own receipt. The same rows are read here through the
    route the driver uses (`build_gate_decision`, which writes nothing), so the three readers of the critic's
    word cannot disagree (FR-10) and the brief is no second plan reader. The word is the critic's (FR-35); the
    gate's other checks (pins, author, revision) are not repeated. [] for a story with no controller state, no
    critical row, or any exception: the brief must not fail for want of a receipt."""
    task_root = Path(task_root)
    if not (task_root / "state" / "controller.json").is_file():
        return []
    try:
        from controller import Controller
        controller = Controller(task_root)
        request = controller.build_gate_decision("A", "<the words the person is about to say>")
        order = controller.accept_order()      # RN1-20: the same order the gate's refusal reads
        return [dict({"plan_row": str(review.get("plan_row")), "verdict": str(review.get("verdict") or "")},
                     **({"basis": str(review["verdict_basis"])} if review.get("verdict_basis") else {}),
                     **({"stale": True} if Controller.review_is_stale(review, order) else {}),
                     **({} if review.get("reviewer_dispatch_id") else {"no_critic": True}))
                for review in request.get("design_reviews") or [] if isinstance(review, dict)]
    except Exception:
        return []


def carried_concern_cases(task_root: Path) -> list:
    """The cases whose concerns the case critic carries to the S5 automator (HF4-11), once each, in the order of the rows:
    read through `s5_plan.case_concerns`, the one reader of them (the automator's brief and C12 read the same list). [] when
    there is none or the state cannot be read - the brief must not fail for want of a receipt."""
    task_root = Path(task_root)
    if not (task_root / "state" / "controller.json").is_file():
        return []
    try:
        import s5_plan
        from controller import Controller
        concerns = s5_plan.case_concerns(task_root, Controller(task_root).state())
        return list(dict.fromkeys(str(item["case"]) for item in concerns if item.get("case")))
    except Exception:
        return []


# The machine prefix of a capability line S0 records (`artifact-contract-json.md`: `S0 vcs_api: <the script's own line>`). Only this
# prefix is read - what the line SAYS is never judged (FR-12); a line that does not match it, in another case or with the name
# in the middle, is left exactly as it is (E22).
_CAPABILITY_LINE = re.compile(r"^(S0 |WARN )?(vcs_api|host_hooks)\b:")
# The same prefix with the status token `unknown` right after the colon (OH1-11): a probe that did not answer. Only the
# prefix and the status token are read (FR-12); `unknown-ish`, `unknown token` after another word, another name or case stay.
_NOT_ESTABLISHED_LINE = re.compile(r"^(?:S0 |WARN )?(vcs_api|host_hooks|base_slice)\b:\s*unknown(?![\w-])")


def _not_established(warnings) -> tuple:
    """`(kept, not_established)`: the capability lines whose status is `unknown` (`vcs_api`, `host_hooks`, `base_slice`) leave the
    text gate A shows - an unknown is not a finding for the person, it is a gap the report names (OH1-11). Nothing is
    rewritten: `pipeline.json` keeps every line (AR-28, FR-45); the error direction is a line too many, never one too few, so
    anything that is not a plain string line matching the prefix stays, and a failure keeps every line. Each removed line is
    `{"capability": <name>, "line": <line>}` (the shape of `proved_warnings`)."""
    try:
        kept, out = [], []
        for line in warnings:
            match = _NOT_ESTABLISHED_LINE.match(line) if isinstance(line, str) else None
            if match:
                out.append({"capability": match.group(1), "line": line})
            else:
                kept.append(line)
        return kept, out
    except Exception:  # noqa: BLE001 - a doubt keeps the line (non-iterable input, etc.)
        try:
            return list(warnings), []
        except Exception:  # noqa: BLE001
            return [], []


def _aware(value):
    """A datetime with a UTC offset from an ISO string, or None."""
    try:
        seen = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return seen if seen.tzinfo is not None else None


def _proved_warnings(task_root: Path, warnings: list) -> tuple:
    """`(kept, proved)`: the warning lines of `pipeline.json`, and the capability lines this story has since proved (HF8-12).

    S0 writes `vcs_api: ...` and `host_hooks: ...` once, when it ran; a merge request the scout read later, or a role the
    story dispatched later, proves what the line doubted, and gate A must not carry it as "not verified". A line goes only when
    the capability was proved AFTER this story's S0 finished (`pipeline.stages.S0.finished`): evidence older than the doubt does not
    lift it (E25). `vcs_api`: the newest fresh `ok` receipt, and `api_capability` over the receipts says `ok` (a fresh `denied` on
    any host forbids it). `host_hooks`: `host_capabilities.hooks_proved` and the real dispatch's receipt (`role_context`).

    The error direction is a line too many, never one too few (AR-28): no `S0.finished`, a time with no offset, a layout of the task
    root that is not `<project>/qa-factory/artifacts/<T>`, a reader that raises - every line stays. `proved` lists what left, each
    with its name, the line and the time of the evidence (the `proved_warnings` key of `collect`, for whoever reads `--json`)."""
    kept, proved = list(warnings), []
    try:
        names = {m.group(2) for m in (_CAPABILITY_LINE.match(w) for w in warnings) if m}
        if not names:
            return kept, proved
        pipeline = read_json(task_root / "pipeline.json", {}) or {}
        stages = pipeline.get("stages") if isinstance(pipeline.get("stages"), dict) else {}
        s0 = stages.get("S0") if isinstance(stages.get("S0"), dict) else {}
        started = _aware(s0.get("finished"))
        if started is None or task_root.parents[1].name != "qa-factory":
            return kept, proved
        project = task_root.parents[2]
        evidence = {}
        if "vcs_api" in names:
            from vcs_evidence import api_capability, read_api_receipts
            receipts = read_api_receipts(project)
            capability = api_capability(None, receipts)
            newest = _aware(receipts["ok"][0].get("observed_at")) if receipts.get("ok") else None
            if capability and capability.get("status") == "ok" and newest is not None and newest > started:
                evidence["vcs_api"] = newest
        if "host_hooks" in names:
            from host_capabilities import hooks_proved, inspect as inspect_host
            answer = inspect_host(project)
            role = answer.get("role_context") if isinstance(answer, dict) else None
            seen = _aware(role.get("observed_at")) if isinstance(role, dict) else None
            if hooks_proved(answer) and seen is not None and seen > started:
                evidence["host_hooks"] = seen
        if not evidence:
            return kept, proved
        kept = []
        for line in warnings:
            match = _CAPABILITY_LINE.match(line)
            if match and match.group(2) in evidence:
                proved.append({"capability": match.group(2), "line": line,
                               "proved_at": evidence[match.group(2)].isoformat()})
            else:
                kept.append(line)
        return kept, proved
    except Exception:  # noqa: BLE001 - an unknown never lifts a warning: every line stays (E23)
        return list(warnings), []


def collect(task: str, root: Path | None = None) -> dict:
    task_root = Path(root) if root is not None else artifacts_dir(task)
    pipeline = read_json(task_root / "pipeline.json", {}) or {}
    rows, plan_path = plan_rows(task_root)
    findings = critic_path(task_root)
    links = read_json(task_root / "state" / "story-case-links.json", {}) or {}
    readiness = read_json(task_root / "work" / "requirements-readiness.json", {}) or {}
    pinned = [link.get("case_id") for link in (links.get("links") or [])
              if isinstance(link, dict) and link.get("case_id")]
    missing = [str(p) for p in (plan_path, findings, task_root / "state" / "story-case-links.json")
               if p is None or not Path(p).is_file()]
    rehearsed = rehearsal(task_root, "A")
    cards, _ = stand_gap_cards(task_root, "A", rehearsed)
    # One function decides which readiness questions are still open, and `unanswered_questions`
    # (gate B, the MR list) is the same function: the two lists cannot disagree (FR-10, FR-17).
    view, unread = register_view(task_root)
    open_questions = (still_open(readiness.get("open_questions"), view, pipeline, task_root)
                      + contradiction_questions(task_root, rows, pipeline))
    try:
        effects, effect_problems = question_effects(task_root, rows, open_questions)
    except Exception as exc:  # a consequence that cannot be computed is said, never guessed
        effects, effect_problems = {}, [f"what each answer changes could not be worked out "
                                        f"({type(exc).__name__}: {exc})"]
    # The selection runs BEFORE the render's cut to five lines, so a line that left frees its place (E24).
    warnings, proved_warnings = _proved_warnings(task_root, [str(w) for w in (pipeline.get("warnings") or [])])
    # After `_proved_warnings` (a proved line is reported as proved, never as not established), before the cut (OH1-11).
    warnings, not_established = _not_established(warnings)
    excluded = _excluded_by_words(task_root)
    reference = reference_facts(task_root)
    return {
        "task": task,
        "gate": "A",
        "pyramid": pyramid(rows),
        "plan_path": str(plan_path),
        "pinned_cases": pinned,
        "case_files": case_files(task_root, links, pinned),
        "plan_gloss": plan_gloss(rows),
        "rehearsal": rehearsed,
        "stand_gap_cards": cards,
        "adapted_lines": adapted_lines(task_root),
        "attachments": attachments_data(task_root),
        "critic_verdict": verdict(findings),
        "critic_path": portable(findings, task_root) if findings else "",
        "roll_call": roll_call(task_root, findings),
        "gate_reviews": accepted_review_summary(task_root),
        "carried_concern_cases": carried_concern_cases(task_root),
        "gate_waivers": [w for w in (pipeline.get("gate_waivers") or []) if isinstance(w, dict)],
        "stage_overrides": [o for o in (pipeline.get("stage_overrides") or []) if isinstance(o, dict)],
        "sources": sources(task_root),
        "excluded_by_words": excluded[0],
        "excluded_by_words_unread": excluded[1],
        "decided_by_words": _decided_by_words(task_root),
        "open_questions": open_questions,
        "answered": answered_questions(task_root, view),
        "question_status_unread": unread,
        "question_effects": effects,
        "question_effect_problems": effect_problems,
        "no_diff": no_diff_story(task_root),
        "case_id_example": _case_id_example(task, task_root),
        "warnings": warnings,
        "proved_warnings": proved_warnings,
        "not_established": not_established,
        "unearned_automation": unearned_automation(rows),
        "sizing": sizing_line(task_root),
        "grounding": grounding_facts(task_root),
        "reference": reference,
        "halts": [h for h in (pipeline.get("halts") or []) if isinstance(h, dict)],
        "documents": documents_with_reference(task_root, reference),
        "judge": judge_facts(task, task_root),
        "missing_inputs": [m for m in missing if m != "None"] + ([] if findings else ["critic-findings.md"]),
    }


# Letters a..z. `zip` over an eight-letter alphabet dropped a ninth reading in silence (cmp1,
# F-10), so a reading is never lost for want of a letter: nine readings get a ninth letter. More
# than 26 cannot be lettered at all; that is a defect of the factory's own question, and the card
# says so instead of cutting it (FR-3, FR-41).
QUESTION_LETTERS = string.ascii_lowercase
NOT_NEEDED = "not needed"
# What a plan row's disposition is called to a person. A hint, not a decision (FR-13): a
# disposition this table does not hold is printed as it was written.
DISPOSITION_WORDS = {"automate": "an automated test", "manual-agent": "a check by an agent, by hand",
                     "manual-human": "a check by a person, by hand", "skip": "not checked",
                     "unverifiable": "not verifiable"}


def disposition_word(word, has_branches=False) -> str:
    """How a person reads a disposition. `unverifiable` on a row that holds `if_answered` waits for a gate A question: the
    person must not read "not verifiable" beside the question whose answer gives the check (FR-10, P9). Otherwise the
    table's word, else the disposition as written."""
    if word == "unverifiable" and has_branches:
        return "waits for your answer"
    return DISPOSITION_WORDS.get(word, word)


CASE_BOM = chr(0xFEFF)  # built, never typed (FR-29): a literal BOM in a source file is invisible


def _letters_for(count: int) -> str:
    """The letters of a question with `count` readings: "" when it has none or more than 26."""
    return QUESTION_LETTERS[:count] if 0 < count <= len(QUESTION_LETTERS) else ""


def _split_case(text) -> tuple:
    """(front matter as {key: text}, body) of a case file. The parser is flat, like the contract's:
    `question_thens` is ONE line of JSON. Never raises; a file with no front matter has an empty one."""
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if text[:1] == CASE_BOM:
        text = text[1:]
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    front = {}
    for line in text[4:end].split("\n"):
        found = re.match(r"([A-Za-z_][\w-]*):[ \t]*(.*)", line)
        if found:
            front.setdefault(found.group(1), found.group(2).strip())
    return front, text[end + 4:]


def _then_numbers(body: str) -> list:
    """The numbers of the numbered items under `## Then`, in order (S5 binds clauses by them)."""
    start = re.search(r"(?m)^##[ \t]+Then[ \t]*$", body)
    if not start:
        return []
    rest = body[start.end():]
    stop = re.search(r"(?m)^##[ \t]", rest)
    section = rest[:stop.start()] if stop else rest
    return [int(n) for n in re.findall(r"(?m)^[ \t]*([0-9]{1,4})[.)][ \t]", section)]


def _read_case(path: Path, cfg: dict, task_name: str):
    """(case, problem): the case file as a dict, None when it is not this story's case, or a
    `problem` saying what could not be read. Never raises."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, f"{path.name} could not be read ({type(exc).__name__})"
    front, body = _split_case(text)
    declared = front.get("id", "").strip().strip("\"'")
    if not declared and not C.is_case_id(path.stem, cfg=cfg):
        return None, ""  # critic-findings.md and the like: not a case
    owner = front.get("task", "").strip().strip("\"'")
    if owner and task_name and owner != task_name:
        return None, ""  # a shared library holds other stories' cases too
    case_id = declared or path.stem
    plan_row = front.get("plan_row", "").strip().strip("\"'")
    if not plan_row:
        found = re.search(r"(?m)^Plan row:[ \t]*(\S+)", body)
        plan_row = found.group(1).strip() if found else ""
    thens, problem = [], ""
    raw = front.get("question_thens", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError("not a list")
            thens = [entry for entry in parsed if isinstance(entry, dict)]
            if len(thens) != len(parsed):
                problem = f"{case_id}: some `question_thens` entries are not objects and were left out"
        except (ValueError, RecursionError):
            problem = (f"{case_id}: its per-answer Then texts could not be read (`question_thens` "
                       "is not one line of JSON holding a list)")
    return {"id": case_id, "path": path, "title": " ".join(front.get("title", "").strip("\"'").split()),
            "plan_row": plan_row, "then_numbers": _then_numbers(body), "thens": thens}, problem


def story_cases(task_root: Path) -> tuple:
    """({case id: case}, [what could not be read]) of this story, from the authoring files.

    `work/test-cases/` (or the project's own case store) holds one authoring file per case, named
    for it; the content-addressed versions beside them (`cv_*.md`) are the same case pinned, and
    are skipped so one case is not read twice. A case pinned in the story's links with no
    authoring file is read from the pinned path. Nothing here decides anything: it reads what the
    designer wrote (FR-47)."""
    task_root = Path(task_root)
    roots = []
    try:
        roots.append(Path(C.cases_root(task_root)))
    except Exception:
        pass
    authoring = task_root / "work" / "test-cases"
    if authoring not in roots:
        roots.append(authoring)
    cfg = C.case_config(task_root)
    cases, problems, done = {}, [], set()

    def take(path: Path) -> None:
        if path in done:
            return
        done.add(path)
        case, problem = _read_case(path, cfg, task_root.name)
        if problem:
            problems.append(problem)
        if case is not None:
            cases.setdefault(case["id"], case)

    for base in roots:
        if base.is_dir():
            for path in sorted_paths(base.rglob("*.md")):
                if not path.stem.startswith("cv_"):
                    take(path)
    links = read_json(task_root / "state" / "story-case-links.json", {}) or {}
    for link in (links.get("links") or []) if isinstance(links, dict) else []:
        raw = str(link.get("path") or "") if isinstance(link, dict) else ""
        if raw and str(link.get("case_id")) not in cases and not Path(raw).is_absolute():
            candidate = task_root / raw
            if candidate.is_file():
                take(candidate)
    return cases, problems


def _patch_for(spec: dict, answer: str) -> dict:
    """The row patch an answer applies, as the card shows it: {} when nothing is written for it.

    Not a reader of its own (t-227b, C5): `planning_contract.resolve_patch` is the one reader the S3
    check, this card and the applier (`apply_gate_answers`) share, so the card can never show a row
    the applier does not produce. This module says `not needed` (two words, the person's) where the
    plan says `not_needed`; the translation is the only thing done here."""
    import planning_contract
    key = planning_contract.NOT_NEEDED if answer == NOT_NEEDED else answer
    return planning_contract.resolve_patch(spec, key) or {}


def _row_effects(row: dict, patch: dict, by_row: dict, cases: dict) -> list:
    """What one patch does to one plan row, as effects. Only a change of DISPOSITION is one: a
    patch that rewrites the reason or the obligations changes no check a person decides about."""
    old = str(row.get("disposition") or "").strip()
    new = patch.get("disposition")
    if not isinstance(new, str) or not new.strip() or new.strip() == old:
        return []
    new = new.strip()
    row_id = str(row.get("id") or "").strip()
    case_ids = by_row.get(row_id, [])
    manual = tuple(d for d in C.DISPOSITIONS if d.startswith("manual"))
    leaves = old in manual and new == "automate"
    if leaves and case_ids:
        return [{"kind": "leaves_manual", "case": cid, "title": cases[cid]["title"], "row": row_id}
                for cid in case_ids]
    label = (plan_gloss([row]).get(row_id)
             or (cases[case_ids[0]]["title"] if case_ids and cases[case_ids[0]]["title"] else "")
             or row_id or "a plan row")
    return [{"kind": "row", "row": row_id, "label": label, "from": old, "to": new,
             "cases": case_ids, "leaves_manual": leaves}]


def _then_effect(case: dict, entry: dict, answer: str, question: dict | None = None):
    """What one `question_thens` entry says for one answer, or None when it says nothing for it.

    The text is `contract.question_then_text`'s - the one reader the resolver and the applier share (HF4-7): for a
    before/now question the entry is keyed by meaning (`now` / `before`) and the letter of the answer is turned into
    the meaning by the question itself, so a text is never put under a reading it was not written for. No text carries
    its reason in `why`."""
    if answer == NOT_NEEDED and "not_needed" not in entry:
        return None
    text, why = C.question_then_text(question, entry, C.NOT_NEEDED_KEY if answer == NOT_NEEDED else answer)
    text = None if text is None else " ".join(str(text).split())
    raw = entry.get("then")
    number = raw if isinstance(raw, int) and not isinstance(raw, bool) else None
    if number is None and isinstance(raw, str) and raw.strip().isdigit():
        number = int(raw.strip())
    problem = ""
    if number is None:
        problem = f"its Then number ({raw!r}) is not a number"
    elif not case["then_numbers"]:
        problem = f"the case lists no numbered Then, so Then {number} cannot be found"
    elif number not in case["then_numbers"]:
        listed = ", ".join(str(n) for n in case["then_numbers"])
        problem = f"the case has no Then {number} (its Thens are {listed})"
    return {"kind": "then", "case": case["id"], "title": case["title"],
            "then": number if number is not None else raw, "text": text, "problem": problem,
            "why": why if text is None else ""}


def question_effects(task_root: Path, rows: list, questions: list) -> tuple:
    """({question id: {answer: [effect]}}, [what could not be read]): what each answer changes.

    Computed from the two fields the strategist and the designer write BEFORE the gate, and that
    the applier reads after it (FR-10, one source): a plan row's `if_answered` (`{qid: {letter:
    patch, "*": patch for every reading, "not_needed": patch}}`) and a case's `question_thens`.
    An answer is a letter of a reading (by position, a..z) or `not needed`. A question no row and
    no case speaks about is absent from the result, and a story with none of the two fields has
    an empty result: no consequence lines, no refusal (a story started before this field existed,
    builder-rules 9). What cannot be read is returned as a sentence; nothing raises."""
    questions = [q for q in questions or [] if isinstance(q, dict)]
    if not questions:
        return {}, []
    rows = [r for r in rows or [] if isinstance(r, dict)]
    cases, problems = story_cases(task_root)
    by_row = {}
    for case_id, case in cases.items():
        if case["plan_row"]:
            by_row.setdefault(case["plan_row"], []).append(case_id)
    effects = {}
    for question in questions:
        qid = str(question.get("id") or question.get("ref") or "").strip()
        if not qid or qid in effects:
            continue
        readings = [r for r in (question.get("readings") or []) if isinstance(r, dict)]
        answers = list(_letters_for(len(readings))) + [NOT_NEEDED]
        per = {answer: [] for answer in answers}
        touched = False
        for row in rows:
            ifa = row.get("if_answered")
            spec = ifa.get(qid) if isinstance(ifa, dict) else None
            if not isinstance(spec, dict):
                continue
            touched = True
            for answer in answers:
                patch = _patch_for(spec, answer)
                if patch:
                    per[answer].extend(_row_effects(row, patch, by_row, cases))
        for case in cases.values():
            for entry in case["thens"]:
                if str(entry.get("question") or "").strip() != qid:
                    continue
                touched = True
                for answer in answers:
                    effect = _then_effect(case, entry, answer, question)
                    if effect is not None:
                        per[answer].append(effect)
        if touched:
            for answer in answers:
                # What the case would say first, then the change of how it is checked: the token
                # that keeps a case manual ends the block, next to the answer block that follows.
                per[answer].sort(key=lambda effect: effect["kind"] != "then")
            effects[qid] = per
    return effects, problems


def _who(effect: dict) -> str:
    case = str(effect.get("case") or "?")
    title = " ".join(str(effect.get("title") or "").split())
    return f"{case} ({title})" if title else case


def render_effect(effect: dict) -> str:
    """One consequence, in the words a person reads. Every case token it offers carries the FULL
    case id exactly as the case file names it: a short id is not one the factory reads back."""
    kind = effect.get("kind")
    if kind == "then":
        number, text, problem = effect.get("then"), effect.get("text"), effect.get("problem")
        who = _who(effect)
        if text is None:
            line = f"Then {number} of {who}: no text is written for this answer"
            if effect.get("why"):
                line += f" ({effect['why']})"
        elif text == "":
            line = f"Then {number} of {who}: nothing is asserted here for this answer"
        else:
            # The Then's own text ends in its own punctuation; no full stop is added after it.
            return (f'Then {number} of {who} would read: "{text}"'
                    + (f" (but {problem}, so it cannot be placed)." if problem else ""))
        return line + (f" (but {problem}, so it cannot be placed)" if problem else "") + "."
    if kind == "leaves_manual":
        case = str(effect.get("case") or "?")
        return (f"{_who(effect)} would no longer be kept checked by hand. The factory does not "
                "switch it by itself yet: after your answer, how it is checked is decided again, "
                "starting from an automated test, and the report says what was decided. To keep "
                f"it checked by hand, write `{case}: manual`.")
    words = DISPOSITION_WORDS
    label = str(effect.get("label") or effect.get("row") or "a plan row")
    if effect.get("leaves_manual"):
        return (f"{label} would no longer be kept checked by hand. The factory does not switch it "
                "by itself yet: after your answer, how it is checked is decided again, starting "
                "from an automated test, and the report says what was decided. No case of it "
                "could be read here, so the case to keep by hand cannot be named.")
    old, new = str(effect.get("from") or ""), str(effect.get("to") or "")
    cases = effect.get("cases") or []
    # an answer moves this row, so it holds `if_answered`: its `unverifiable` is "waits for your answer" (A8), not "not verifiable"
    return (f"{label}: {disposition_word(old, True) if old else 'unstated'} becomes {words.get(new, new)}"
            + (f" (cases: {', '.join(str(c) for c in cases)})" if cases
               else " - no case of it could be read here") + ".")


# RN1-11 (LOCAL-1): a story with no diff has no earlier version under test, so the before/now card must not offer a
# "regression, say what it was" letter whose value nobody can write. The card says what the code will do with the letter.
NO_DIFF_BEFORE_READING = ("Not intended: the expected behaviour is the one the case states for this answer (there is no "
                          "earlier version under test, so nothing has to be said about 'before').")
NO_DIFF_BEFORE_CHOSEN = ("The expected value of each Then is the text its case writes for this answer; the behaviour "
                         "now is reported as a defect.")


def no_diff_story(task_root) -> bool:
    """Is this story one with no diff under test? True only when `pipeline.json` `implementation_source` is a string
    other than `diff`. An absent key or an unreadable file is False: the card never says less than the code records
    (the old card stays)."""
    try:
        value = (read_json(Path(task_root) / "pipeline.json", {}) or {}).get("implementation_source")
    except Exception:
        return False
    return isinstance(value, str) and bool(value.strip()) and value.strip() != "diff"


def question_card(question: dict, index: int, effects: dict | None = None, no_diff: bool = False) -> list:
    """One gate-A question printed in the form a person can answer without opening a file.

    TP1-15045: the question `Where must a removed node appear when the YAML has no layout
    meta?` was printed as one clipped line with no quote, no readings and no consequence, and
    the person scrolled past it for the length of the story. The same question with what the
    source says, the two readings and what each costs was answered in one minute — so a
    question is a card here, never a `[:200]` one-liner. A question written before 0.7.16
    carries only its statement; it is printed as it stands (the gate rehearsal is what names
    it as something the requirements tester must rewrite), never dropped.

    Under each reading the card says what that answer would change in the plan and the cases
    (`effects`, from `question_effects`): TP1-13797 showed Q4 with two readings and no word
    that one of them would let a case leave manual testing, so the person answered "as they
    stand" about a case they never knew was in play. A story whose roles wrote no per-answer
    fields has no `effects`, and its card reads as it always did."""
    qid = str(question.get("id") or question.get("ref") or f"Q{index}").strip()
    lines = [f"- **{qid}** [{question.get('severity', '?')}, owner "
             f"{question.get('owner_role', '?')}] "
             + " ".join(str(question.get("question") or "").split())]
    note = " ".join(str(question.get("status_note") or "").split())
    if note:
        lines.append(f"  - {note}.")
    for quote in question.get("source_says") or []:
        if not isinstance(quote, dict):
            continue
        lines.append(f"  - the source says: \"{' '.join(str(quote.get('quote') or '').split())[:240]}\""
                     f" — {' '.join(str(quote.get('where') or '').split())[:120]}")
    # O3 (t-227, P20): a behaviour-claim question asks the person to choose between what the code did
    # BEFORE the change and what it does NOW; the card printed neither, so the choice was blind. A
    # question written before this field carries neither key and prints nothing extra.
    # RN1-11: on a no-diff story the before reading is rewritten and its "before the change" side line is not printed
    before_index = C.claim_reading_index(question, C.CLAIM_KEYS[1]) if no_diff and C.is_claim_question(question) else None
    for key, label in (("before", "before the change"), ("now", "now")):
        side = question.get(key)
        if key == "before" and before_index is not None:
            continue
        if isinstance(side, dict) and str(side.get("value") or "").strip():
            where = " ".join(str(side.get("where") or "").split())[:120]
            lines.append(f"  - {label}: {' '.join(str(side['value']).split())[:200]}" + (f" — {where}" if where else ""))
    readings = [r for r in (question.get("readings") or []) if isinstance(r, dict)]
    letters = _letters_for(len(readings))
    mine = (effects or {}).get(qid)
    if readings and not letters:
        # More readings than letters: a defect of the factory's own question, which is reported
        # as one and never shown cut (FR-3). The readings stay visible, unlettered.
        lines.append(f"  - The factory wrote {len(readings)} readings for this question, more than "
                     f"it can letter ({len(QUESTION_LETTERS)}). That is the factory's own defect, "
                     f"not yours: answer in your own words, or write `{qid}: {NOT_NEEDED}`.")
        for position, reading in enumerate(readings, start=1):
            lines.append(f"  - reading {position}: "
                         f"{' '.join(str(reading.get('reading') or '').split())[:200]}"
                         f" (from {reading.get('from', '?')})")
        lines.append(_answer_line(qid, []))
        return lines
    for position, (letter, reading) in enumerate(zip(letters, readings)):
        reading_text, chosen_text = str(reading.get("reading") or ""), str(reading.get("if_chosen") or "")
        if before_index is not None and position == before_index:
            reading_text, chosen_text = NO_DIFF_BEFORE_READING, NO_DIFF_BEFORE_CHOSEN
        lines.append(f"  - {letter}) {' '.join(reading_text.split())[:200]}"
                     f" (from {reading.get('from', '?')})")
        if chosen_text.strip():
            lines.append("    if chosen: "
                         + " ".join(chosen_text.split())[:200])
        if mine is not None:
            lines.append(f"    what changes if you choose {letter}:")
            shown = mine.get(letter) or []
            lines.extend("    - " + render_effect(effect) for effect in shown)
            if not shown:
                lines.append("    - nothing in the plan or the cases changes.")
    if mine is not None and mine.get(NOT_NEEDED):
        lines.append(f"  - if you write `{qid}: {NOT_NEEDED}`, what changes:")
        lines.extend("    - " + render_effect(effect) for effect in mine[NOT_NEEDED])
    if mine is None and readings:
        import planning_contract
        if planning_contract.question_names_requirement(question):
            # GW1-41 (A6, F-2): no row and no case speaks about the question (it has no `effects` entry): it stays (the
            # person decides, FR-8) and says out loud that no answer moves a row or a case. A question with `effects`
            # already printed "nothing ... changes" under each letter, so this line is not repeated there (t-604 F-3).
            lines.append("  - no row or case changes with this answer.")
    if readings:
        # Never a fake extra reading in `readings[]`: the readings are what the sources say,
        # and the person's own wording is always open to them without being listed as one.
        lines.append("  - or your own wording — the readings are what the sources say, not a "
                     "closed list of answers.")
    elif question.get("readings_unnameable") is True:
        # The role could name no reading (a scope or structure question): there is no letter to
        # choose, so the card asks for the person's own words and offers nothing else.
        lines.append("  - No reading can be named for this one. Answer in your own words, or write "
                     f"`{qid}: {NOT_NEEDED}`.")
    lines.append(_answer_line(qid, letters[:len(readings)]))
    return lines


def _answer_line(qid: str, letters) -> str:
    """GW1-32: the last line of a question's card - the lines `question_register.parse_choices` reads for THIS question, with its own
    id: one per lettered reading it has, and `not needed`. A question with no letter (no reading, or more readings than letters) is
    offered `not needed` alone: a form is printed only where its reader takes it."""
    forms = [f"`{qid}: {letter}`" for letter in letters] + [f"`{qid}: {NOT_NEEDED}`"]
    return "  - Answer: " + (", ".join(forms[:-1]) + " or " if len(forms) > 1 else "") + forms[-1]


# The fingerprint of the register row a card was rendered from, as a hidden comment line after the card
# (`render` adds it; `question_card` itself is unchanged - a story from before the field reads today's card, E-9)
# (t-271 F5, t-279 K-HASH). The person never needs it; the applier does: an answer is stored against THIS hash, so a row that
# changed after the card was shown reads `changed_since_answer` instead of passing as the row the person saw.
# A comment, not text: no field name, no script, no id for a reader to decode (FR-6).
CARD_MARKER = re.compile(r"^\s*<!-- card (?P<id>\S+) (?P<hash>[0-9a-f]{64}) -->\s*$")


def card_marker(qid: str, shown_hash) -> str:
    """The hidden line of a card, or "" when the card has no fingerprint to carry (a row the register cannot place:
    the answer is then stored against the row as it stands when it is applied, as it always was)."""
    shown_hash = str(shown_hash or "").strip()
    if not qid or " " in qid or not re.fullmatch(r"[0-9a-f]{64}", shown_hash):
        return ""
    return f"  <!-- card {qid} {shown_hash} -->"


def shown_hashes(text) -> dict:
    """{question id: the row fingerprint its card carried} read back from a rendered gate packet. A question with
    two cards in the text (a packet shown twice) keeps the LAST one: that is the card the person answered. An
    empty dict for a text with no marker; nothing is guessed."""
    found: dict = {}
    for line in str(text or "").splitlines():
        hit = CARD_MARKER.match(line)
        if hit:
            found[hit.group("id")] = hit.group("hash")
    return found


# GW1-32: the forms of an answer, ONE list. Each row is {form, example, says, where, reader}: `reader` names the function that takes the
# line (a test feeds `example` to it), so a form nothing reads cannot be printed without a red test (FR-11).
CASE_FORM_MANUAL = "<full case id>: manual"
CASE_FORM_AUTOMATE = "<full case id>: automate"
CASE_FORM_BLOCKED = "<full case id>: accept as blocked"
LETTER_FORM = "<question id>: <letter>"


def _form(form: str, example: str, says: str, where: str, reader: str) -> dict:
    return {"form": form, "example": example, "says": says, "where": where, "reader": reader}


def _question_forms(questions: list, case_example: str) -> list:
    """The forms of the open questions (`question_register.parse_choices`): the letter of a reading - only when some question has a
    letter to choose -, `not needed`, and the two case words (the cards say when a case can leave manual)."""
    asked = [q for q in questions if isinstance(q, dict)]
    if not asked:
        return []
    ids = [str(q.get("id") or q.get("ref") or "").strip() for q in asked]
    lettered = next((i for q, i in zip(asked, ids) if i and q.get("readings")
                     and _letters_for(len([r for r in q["readings"] if isinstance(r, dict)]))), "")
    first = next((i for i in ids if i), "")
    forms = []
    if lettered:
        forms.append(_form(LETTER_FORM, f"{lettered}: a", "the reading you choose", "Open questions", "parse_choices"))
    forms.append(_form(f"<question id>: {NOT_NEEDED}", f"{first}: {NOT_NEEDED}" if first else "", "", "Open questions", "parse_choices"))
    forms.append(_form(CASE_FORM_MANUAL, f"{case_example}: manual" if case_example else "", "keep that case checked by hand",
                       "Open questions", "parse_choices"))
    forms.append(_form(CASE_FORM_AUTOMATE, f"{case_example}: automate" if case_example else "",
                       "have that case checked by an automated test", "Open questions", "parse_choices"))
    return forms


def _gap_form(data: dict) -> list:
    """The stand-gap form, when this packet's gap cards state it (the card block prints it only while a card is open: a gap the
    environment record already decided has no form to answer). Its example is the card's own - the id the card is headed by."""
    card = next((str(line) for line in data.get("stand_gap_cards") or [] if STAND_GAP_FORM in str(line)), "")
    if not card:
        return []
    found = re.search(r"for example `([^`]+)`", card)
    return [_form(STAND_GAP_FORM, found.group(1) if found else "", "answer a stand gap with one of the words its card lists",
                  "Stand gaps", "read_stand_gap_answers")]


def _finding_forms(data: dict) -> list:
    """The forms of the open items of the rehearsal (`open_rehearsal_items`, the one reader of what is open): an item with a line door
    takes `<item id>: accept <your reason>` (`Driver.read_finding_doors`); an item with only a words door, or none, takes no line -
    `approve as is`, when the data file has the word, passes every one of them (`Driver.as_is_word`)."""
    rehearsed = data.get("rehearsal")
    if not isinstance(rehearsed, dict) or not rehearsed:
        return []
    read = open_rehearsal_items(None, "A", rehearsed)
    items = read["items"] if read["status"] == "read" else []
    if not items:
        return []
    forms = []
    door = next((i for i in items if i["door"]["kind"] == "line"), None)
    word = stand_gap_word_of().get("accept", "")
    if door and word:
        forms.append(_form(f"<item id>: {word} <your reason>", f"{door['id']}: {word} this is known and accepted",
                           "pass one open item of the list above anyway, with your reason", "After your approval",
                           "Driver.read_finding_doors"))
    as_is = as_is_word_of("A")
    if as_is:
        forms.append(_form(as_is, as_is, "alone on the first line: approves over every open item, each recorded with your words",
                           "After your approval", "Driver.as_is_word"))
    return forms


def _blocked_form(data: dict, case_example: str) -> list:
    """`accept as blocked` (`parse_choices`), when a stand card of the rehearsal is open: the condition the line had in
    `_after_approval` (a `case_preconditions` finding the person decides)."""
    try:
        import gate_preflight
        wanted = any(f.get("check") == "case_preconditions" and f.get("class") == gate_preflight.PERSON_DECIDES
                     for f in (data.get("rehearsal") or {}).get("findings") or [] if isinstance(f, dict))
    except Exception:
        return []
    if not wanted:
        return []
    return [_form(CASE_FORM_BLOCKED, f"{case_example}: accept as blocked" if case_example else "",
                  "accept a case's missing stand needs as blocked", "After your approval", "parse_choices")]


def answer_forms(data: dict, questions: list) -> list:
    """GW1-32: [{form, example, says, where, reader}] - EVERY form of an answer this gate-A packet offers, and only those the packet
    has something to apply to. Pure: it reads `data` and the data files, prints nothing, writes nothing. It is no detector (AR-18:
    `detector_verdict` is untouched) - it is the list `how_to_answer_lines` renders, so the packet says each form once.

    Questions: the letter (only when a reading has a letter), `not needed`, `manual`, `automate`. Open items of the rehearsal: the
    accept line of an item with a line door, `approve as is`. Stand gaps: the gap form. Cases: `accept as blocked` when a stand card
    is open. Nothing to answer gives []."""
    case_example = str(data.get("case_id_example") or "")
    return (_question_forms(list(questions or []), case_example) + _gap_form(data) + _finding_forms(data)
            + _blocked_form(data, case_example))


def how_to_answer_lines(forms: list, case_example: str = "") -> list:
    """The "how to answer" block: the forms of `answer_forms`, printed ONCE for the whole packet.

    Each form is a line a reader takes (`reader`, FR-11); anything else goes to the assistant running the story, who reads words -
    never to code (FR-12). [] when there is no form: no question, no open item, no gap - nothing is promised. A script name or a
    flag may appear in this block and nowhere else in the card (references/human-questions.md, part 5)."""
    if not forms:
        return []
    lines = ["", "## How to answer", "Write each answer on its own line, in one of these forms:"]
    for row in forms:
        if row["form"] == CASE_FORM_BLOCKED:
            lines.append(blocked_answer_line(case_example))      # the one line, its text unchanged (O6)
            continue
        by_example = f", for example `{row['example']}`" if row["form"] == LETTER_FORM and row["example"] else ""
        lines.append(f"- `{row['form']}`" + (f" - {row['says']}" if row["says"] else "") + by_example)
    if case_example and any(row["form"] in (CASE_FORM_MANUAL, CASE_FORM_AUTOMATE) for row in forms):
        lines.append(f"A full case id is the whole id, as written in this packet, for example `{case_example}`.")
    lines.append(ANYTHING_ELSE_SENTENCE)
    return lines


def blocked_answer_line(case_example: str = "") -> str:
    """The one line that says HOW to accept a case's missing stand needs as blocked (O6): the form the
    register's parser reads (`question_register.parse_choices`, a whole line, one case per line). The
    stand cards offer the answer; without this line the packet showed the card and not the words."""
    example = f", for example `{case_example}: accept as blocked`" if case_example else ""
    return ("- To accept a case as blocked on this stand, write `<full case id>: accept as blocked` on a line "
            f"of its own{example}; S5 then reports exactly those as not executed.")


def _head_lines(data: dict) -> list:
    """The cover sheet of the gate A packet: the title, the plan, the pinned cases, the critic, the size
    (t-683 D8: moved out of `render` as it stood)."""
    task = data.get("task", "?")
    pyr = data.get("pyramid") or {}
    lines = [f"# Gate A — {task}", "", gate_a_approval_line(), ""]
    levels = ", ".join(f"{k} {v}" for k, v in sorted((pyr.get("by_level") or {}).items()))
    disps = ", ".join(f"{k} {v}" for k, v in sorted((pyr.get("by_disposition") or {}).items()))
    lines.append(f"**Plan** — {pyr.get('total', 0)} rows. Levels: {levels or 'none'}. "
                 f"Dispositions: {disps or 'none'}.")
    mix = pyr.get("by_level_disposition") or {}
    if mix:
        lines.append("Pyramid: " + ", ".join(f"{k} {v}" for k, v in sorted(mix.items())) + ".")
    pinned = data.get("pinned_cases") or []
    files = data.get("case_files") or {}
    lines.append(f"**Cases** — {len(pinned)} pinned"
                 + (f": {', '.join(case_ref(c, files) for c in pinned[:15])}" if pinned else " (none)")
                 + ("..." if len(pinned) > 15 else "") + ".")
    roll = data.get("roll_call") or {}
    unreviewed = roll.get("unreviewed") or []
    # "every row reviewed" is a claim, and it may only be made about rows whose table SAYS so.
    # A roll-call with no `reviewed` column says nothing about its rows, and the brief prints
    # that instead of the reassurance (FR-41, FR-10).
    unstated = roll.get("unstated") or []
    if unreviewed:
        said = (f"{len(unreviewed)} not reviewed semantically: " + ", ".join(unreviewed[:8])
                + ("..." if len(unreviewed) > 8 else ""))
    elif unstated:
        said = (f"whether {len(unstated)} row(s) were reviewed is not stated — the roll-call has "
                "no `reviewed` column: " + ", ".join(unstated[:8])
                + ("..." if len(unstated) > 8 else ""))
    else:
        said = "every row reviewed"
    lines.append(f"**Critic** — verdict `{data.get('critic_verdict') or 'not recorded'}`, "
                 f"roll-call {roll.get('total', 0)} rows, " + said + ".")
    carried = [str(case) for case in data.get("carried_concern_cases") or [] if str(case).strip()]
    if carried:      # HF4-11: the case critic's concerns that are not a failing case travel to the automator
        lines.append("Concerns carried to automation: " + ", ".join(carried))
    reviews = [r for r in data.get("gate_reviews") or [] if isinstance(r, dict)]
    if reviews:
        # The person's line: plan rows, the critic's own words and a plain reason, worded from the review's basis -
        # no dispatch ids, no field names (FR-6, n-1 of t-1115). A row no case critic reviewed is said as such,
        # never counted as accepted (m-4); rows past the eighth are counted, not dropped (m-5).
        plain = {"column": "the critic's own word for a case of the row is {}",
                 "round_word": "the critic gave no word per case, and its review as a whole says {}",
                 "round_word_rule": "the critic's review as a whole says reject, yet no case it reviewed fails: the critic "
                                    "is asked to rewrite that line",
                 "no_review": "the critic's review does not cover every case of the row",
                 "unreadable": "the critic's review of the row could not be read",
                 "receipt_mismatch": "the critic's findings were edited after the review was accepted",
                 "two_rollcalls": "the critic's findings do not show where one review ends"}
        reviewed = [r for r in reviews if not r.get("no_critic")]
        refused = [r for r in reviewed if r.get("verdict") != "accepted"]
        kept, unreviewed = len(reviewed) - len(refused), len(reviews) - len(reviewed)
        named = ", ".join(f"{r.get('plan_row')} {r.get('verdict') or 'not recorded'}" for r in refused[:8])
        first = next((r for r in refused if r.get("basis") in plain), None)
        said = ((named + (f" and {len(refused) - 8} more" if len(refused) > 8 else "")
                 + (f"; {kept} accepted" if kept else "")) if refused else f"all {kept} accepted" if kept else "")
        said += (("; " if said else "") + f"{unreviewed} with no case critic review") if unreviewed else ""
        reason = (f" First reason ({first.get('plan_row')}): " + plain[first["basis"]].format(first.get("verdict"))
                  + ".") if first else ""
        lines.append(f"**Critic, per plan row (as gate A reads it)** — {said}.{reason}")
        if any(r.get("stale") for r in reviews):    # RN1-20: a receipt older than the last edit of its cases
            lines.append("- after the last edit of its cases the case critic has not reviewed them")
    if data.get("sizing"):
        lines.append(data["sizing"])
    return lines


def _needs_words_line(rehearsed: dict) -> list:
    """RH1-6 A-AC7: ONE line naming EVERY open item that stops `approve` - whatever its door (`line` items too, the Lead's decision on
    the critic's Q3) - so none hides under "+N more" (`brief_lines` shows five): the item stops `approve` until the person words it (the
    owner's F-2). Ids only (no messages: the rehearsal block below carries them) and the count stated. Names the closed word
    `approve as is` from the data file (`as_is_words`), and drops that clause when the file has none. [] when nothing is open or the
    items cannot be read (the rehearsal block above says that itself)."""
    read = open_rehearsal_items(None, "A", rehearsed)
    ids = [item["id"] for item in read["items"]] if read["status"] == "read" else []
    if not ids:
        return []
    word = as_is_word_of("A")
    return [f"- needs your word before your approval counts ({len(ids)} open): " + ", ".join(f"[{i}]" for i in ids)
            + ' (each is under "Rehearsal of gate A" below)'
            + (f" — or answer `{word}` to approve over all of them, each recorded with your words" if word else "")]


def _after_approval(data: dict) -> list:
    """The "After your approval" block: the rehearsal in short, or the word that it could not run or be shown.
    The `try` and its `except` stay together - a rehearsal that fails to print is one line, never a crash."""
    # Before anything else the person may skim: what happens once they say yes. Placed above
    # the optional sections so the line cap can never truncate it away.
    rehearsed = data.get("rehearsal") or {}
    lines = ["", "## After your approval"]
    if rehearsed.get("unavailable"):
        lines.append(f"- the rehearsal could not run ({rehearsed['unavailable']}) — what would "
                     "have stopped the next stage is unknown; that is the factory's own gap.")
    else:
        try:
            import gate_preflight
            lines.extend(gate_preflight.brief_lines(rehearsed, skip_checks=("critic_rollcall",)))
            lines.extend(_needs_words_line(rehearsed))
        except Exception:
            lines.append("- the rehearsal could not be shown, so what it would have asked is unknown — that is the "
                         "factory's own gap, not yours.")
    return lines


def _question_lines(data: dict, questions: list) -> list:
    """The "Open questions" section with its cards and their hidden fingerprints, then the "How to answer" block (`answer_forms`):
    the block stands whenever the packet has a form to offer - with no question too, for an open item or a stand gap -, and
    nothing at all when there is neither a question nor a form."""
    question_lines = []
    if questions:
        question_lines.append("")
        question_lines.append(f"## Open questions ({len(questions)})")
        if data.get("question_status_unread"):
            # One line, and the cards below are then shown as they stand: a status that could not
            # be read is never presented as "answered" (FR-41).
            question_lines.append("- Question status could not be read "
                                  f"({' '.join(str(data['question_status_unread']).split())[:160]}), "
                                  "so every question below is shown as it stands.")
        effects = data.get("question_effects") or {}
        for index, q in enumerate(questions, start=1):
            question_lines.extend(question_card(q, index, effects, no_diff=bool(data.get("no_diff"))))
            marker = card_marker(str(q.get("id") or "").strip(), q.get("shown_hash"))
            if marker:
                question_lines.append(marker)
        for problem in data.get("question_effect_problems") or []:
            question_lines.append(f"- Not read, so not shown above: {' '.join(str(problem).split())}.")
    question_lines.extend(how_to_answer_lines(answer_forms(data, questions), str(data.get("case_id_example") or "")))
    return question_lines


def _excluded_by_words(task_root) -> tuple:
    """`(rows, unread)`: the `excluded:` rows of the register that QUOTE the person's words and hold (`branch_accounting.exclusions`, the
    one reader of an exclusion's reason, AR-13). Any failure is `([], True)`: the packet then says it could not read them (FR-41)."""
    try:
        import branch_accounting as BA
        return [r for r in BA.exclusions(task_root) if r.get("form") == "quote" and r.get("decided")], False
    except Exception:  # noqa: BLE001
        return [], True


def _decided_by_words(task_root) -> list:
    """`[{"r", "quote", "file"}]`: the reading forks the person closed in their own words, register order (D1-B B2). The quote is read
    through `branch_accounting.decided_by_words` (the one reader of the quote form and of the words file, AR-13). Any failure is `[]`:
    an unknown closes nothing, and the card stays as it is (FR-59)."""
    try:
        import branch_accounting as BA
        return [{"r": r, "quote": v["quote"], "file": v["file"]} for r, v in BA.decided_by_words(task_root).items()]
    except Exception:  # noqa: BLE001
        return []


def _by_words_lines(data: dict) -> list:
    """The lines `decided by your words` of the "Already decided by you" section: one per fork the person closed in their own words
    (`decided_by_words`), at most `LEFT_OUT_CAP`, then `(+K more - the requirements register names them all)`."""
    rows = [r for r in data.get("decided_by_words") or [] if isinstance(r, dict)]
    lines = []
    for row in rows[:LEFT_OUT_CAP]:
        quote = " ".join(str(row.get("quote") or "").split())
        quote = quote if len(quote) <= LEFT_OUT_CLIP else quote[:LEFT_OUT_CLIP].rstrip() + "… (cut)"
        lines.append(f'- {row.get("r")}: decided by your words "{quote}" ({row.get("file")})')
    if len(rows) > LEFT_OUT_CAP:
        lines.append(f"- (+{len(rows) - LEFT_OUT_CAP} more - the requirements register names them all)")
    return lines


def _left_by_words_lines(data: dict) -> list:
    """"Left out by your words": every cut the S2 role made in the person's NAME, with the words it rests on (t-1676, WG1-1). The code
    check sees that the quote is theirs, not that the cut matches what they meant (LOCAL-1: "only the add-to-cart function" became
    the whole cart-edit territory), so this list is where they catch an over-reach - it is NOT a settled list, and it has a door:
    their words go to the assistant, which sends the story back to the requirements step. At most `LEFT_OUT_CAP` rows."""
    rows, unread = data.get("excluded_by_words") or [], bool(data.get("excluded_by_words_unread"))
    if not rows and not unread:
        return []
    lines = ["", "## Left out by your words — say which part to keep if you meant otherwise"]
    for row in rows[:LEFT_OUT_CAP]:
        quote = " ".join(str(row.get("quote") or "").split())
        quote = quote if len(quote) <= LEFT_OUT_CLIP else quote[:LEFT_OUT_CLIP].rstrip() + "… (cut)"
        texts = [" ".join(str(t).split()) for t in row.get("texts") or [] if t]
        first = (texts[0][:LEFT_OUT_CLIP].rstrip() + ("…" if len(texts[0]) > LEFT_OUT_CLIP else "")) if texts else "a part of the ticket"
        lines.append(f'- your words "{quote}" left out: {first}' + (f" (and {len(texts) - 1} more sentences)" if len(texts) > 1 else ""))
    if len(rows) > LEFT_OUT_CAP:
        lines.append(f"- (+{len(rows) - LEFT_OUT_CAP} more - the requirements register names them all)")
    if unread:
        lines.append("- the factory could not read which parts of the ticket your words left out; that is the factory's defect, nothing is "
                     "asked of you")
    if rows:
        lines.append("If you meant a smaller cut, say in your own words which part to keep: the assistant running this story sends the story "
                     "back to the requirements step with your words.")
    return lines


def _decided_lines(data: dict) -> list:
    """The "Already decided by you" section - the person's passes, the source gaps they accepted and the
    sources they left out - or nothing when there is none of the three."""
    lines = []
    decisions = (data.get("gate_waivers") or []) + (data.get("stage_overrides") or [])
    gaps = (data.get("sources") or {}).get("accepted_gaps") or []
    # The sources the person left out BEFORE the run are a decision of theirs too, and the only place
    # they see it again is here: the section renders when there is one even with no decision and no
    # gap (C7 of t-172). The reason is clipped to 120 here, whole in the retro.
    left_lines = left_out_lines(
        sum(((data.get("sources") or {}).get(key) or [] for key in
             ("left_out_by_word", "unmatched_words", "unchecked_words", "taken_back")), []),
        clip_to=LEFT_OUT_CLIP, cap=LEFT_OUT_CAP)
    if (data.get("sources") or {}).get("left_out_unread"):
        left_lines.append("the record of the sources you left out before the run could not be read, so this "
                          "brief cannot say what it names; that is a defect of the factory's own record, not "
                          "something you have to repair")
    answered_lines = _answered_lines(data)
    by_words_lines = _by_words_lines(data)
    if decisions or gaps or left_lines or answered_lines or by_words_lines:
        lines.append("")
        lines.append("## Already decided by you — repeated, not re-asked")
        # t-373 (FR-10): ONE renderer for the person's passes - `waiver.person_lines`, the same lines the driver's
        # "Blocks passed by your word so far" section carries - so the two sections of one packet cannot disagree and
        # neither shows a block key (`S5 block [stand gap: RP-api]` was shown raw here). Five of each, as before.
        import waiver
        lines.extend("- " + line for line in waiver.person_lines(
            {"stage_overrides": [o for o in (data.get("stage_overrides") or [])[:5] if isinstance(o, dict)],
             "gate_waivers": [w for w in (data.get("gate_waivers") or [])[:5] if isinstance(w, dict)]}))
        for gap in gaps[:5]:
            lines.append(f"- accepted source gap: {gap}")
        lines.extend("- " + line for line in left_lines)
        lines.extend(answered_lines)       # the register questions the person closed - after the passes, never before an open card
        lines.extend(by_words_lines)       # the forks they closed in their own words (RN1-14), after the answered questions
    lines.extend(_left_by_words_lines(data))   # its own heading and a door: not a settled list (C-6)
    return lines


def _unreachable_lines(data: dict) -> list:
    """"Not reachable by the factory - recorded without asking you": the gaps the factory's own probe established (a
    dropped VPN, a tool it does not have, a file no role can open). Five rows, then "(+K more)", then the door (N10, FR-57)."""
    rows = (data.get("sources") or {}).get("defaulted") or []
    if not rows:
        return []
    lines = ["", "## Not reachable by the factory - recorded without asking you"]
    lines.extend("- " + " ".join(str(row).split())[:LEFT_OUT_CLIP + 80] for row in rows[:LEFT_OUT_CAP])
    if len(rows) > LEFT_OUT_CAP:
        lines.append(f"- (+{len(rows) - LEFT_OUT_CAP} more - the inventory names them all)")
    lines.append("- To try again after you restore access (a VPN, a login), say so to the conductor: the factory collects "
                 "these again at the next scout handover.")
    return lines


def _tail_sections(data: dict, judged: list) -> list:
    """The optional sections after the person's own decisions, in the order the packet prints them: sources
    found late, automation the plan did not justify, warnings, the judge block (`judged`, computed by
    `render`, which the cap counts), what could not be read, and the paths of the long documents."""
    lines = []
    late = (data.get("sources") or {}).get("unreviewed") or []
    if late:
        lines.append("")
        lines.append("## Sources found after the S1 review — new to you")
        lines.append("- " + ", ".join(late[:10]) + ("..." if len(late) > 10 else ""))
    unearned = data.get("unearned_automation") or []
    if unearned:
        lines.append("")
        lines.append(f"## e2e rows without a highest-risk field ({len(unearned)}), for your information")
        gloss = data.get("plan_gloss") or {}
        lines.append("- " + ", ".join(f"{row} ({gloss[row]})" if gloss.get(row) else row
                                      for row in unearned[:15]) + ("..." if len(unearned) > 15 else "")
                     + ": `automate` at e2e-ui, as written or after an answer to a question, while `impact`, `likelihood` and `verification_depth` do not say "
                       "highest risk. The strategist judged them so; this is no question to you, and a critic of "
                       "the plan reads the level. Say so in your answer if you want them changed.")
    warnings = data.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("## Warnings the factory is carrying")
        for w in warnings[:5]:
            lines.append("- " + " ".join(w.split())[:180])
    if judged:
        lines.append("")
        lines.extend(judged)
    missing = data.get("missing_inputs") or []
    if missing:
        lines.append("")
        lines.append("## Not readable by this brief — say so rather than guess")
        lines.append("- " + ", ".join(sorted(set(missing))[:6]))
    docs = data.get("documents") or {}
    if docs or data.get("critic_path"):
        lines.append("")
        lines.append("## The long documents (paths, not summaries)")
        for name, path in sorted(docs.items()):
            lines.append(f"- {name}: {path}")
        if str(data.get("critic_path") or "").lower().endswith(".md"):
            lines.append(f"- critic findings: {data['critic_path']}")
        elif data.get("critic_path"):
            # a person is named a readable file only (HF8-20, FR-37); anything else is said in words, never as a path
            lines.append("- critic findings: recorded by the factory; ask if you want them")
    return lines


# --- gate A: the attachments that were not turned into requirements (r0107 S6 step 1c, the owner's word of 30.10.2026) --------
# The factory turns the TEXT of the story and of the tickets kept for it into requirements; their attachments are not units. The
# person is told so, with the names, and asked once whether any of them holds a requirement. Code writes the block (FR-47: no
# role is paid for a list code knows); the reader of the list is `branch_accounting.attachments_view` (AR-13) and the answer
# words are data (`question-vocabulary.json` `attachment_question_words`, FR-13). `approve` = nothing to add; the person's own
# words are not an approval, so they go to the conductor, which offers the `rework` of S2 (`conductor.md`).
ATTACHMENTS_HEAD = "## Attachments: not turned into requirements ({n})"
ATTACHMENTS_INTRO = ("The factory turned the text of this ticket and of the tickets kept for it into requirements, sentence by "
                     "sentence. It did not do that with their attachments, so a requirement that stands only in an attachment is "
                     "in this plan only if you add it.")
ATTACHMENTS_ASK = "Do you want to add a requirement because of any of these?"
ATTACHMENTS_UNKNOWN_HEAD = "## Attachments: not known"
ATTACHMENTS_STATE_FILE = "driver-state.json"
RUN_MODE_ENV = "QA_FACTORY_RUN_MODE"      # the driver exports "driver" (`launch_card.RUN_MODE_ENV`; named here, as `conductor_stop` does)

def attachment_question_words() -> dict:
    """`{"nothing_to_add": row, "own_words": row}` from `question-vocabulary.json` (`attachment_question_words`), each row with
    `says`, `says_without_word` and the three price lines; `{}` when the block is missing or a row is damaged (the packet then
    says the attachments are not known, never a question with no price lines - FR-41)."""
    try:
        block = (hooklib.load_ref_json("question-vocabulary.json") or {}).get("attachment_question_words")
    except Exception:
        return {}
    out = {}
    for name in ("nothing_to_add", "own_words"):
        row = block.get(name) if isinstance(block, dict) else None
        if not isinstance(row, dict):
            return {}
        clean = {key: " ".join(str(row.get(key) or "").split()) for key in ("says", "says_without_word", "factory", "you", "story")}
        if not all(clean.values()):
            return {}
        out[name] = clean
    return out


def attachment_ids(view: dict) -> list:
    """The identity of every attachment a view lists, `<KEY>: <name>`, in order: what `Driver.gate` keeps as shown."""
    return [f"{t['key']}: {i['name']}" for t in view.get("tickets") or [] for i in t.get("items") or []]


def gate_a_decided(task_root):
    """THE reader of "a current approved decision of plan gate A stands" (AR-13): `state/controller.json` holds a decision of
    gate A `approved` on the controller's current `source_revision`, the fact the driver's `decided("A")` reads. True or False;
    None when the file exists and cannot be read (FR-41: no claim, and no caller counts it as a decision)."""
    path = Path(task_root) / "state" / "controller.json"
    if not path.is_file():
        return False
    try:
        ctl = json.loads(path.read_text(encoding="utf-8-sig"))
        return any(isinstance(d, dict) and d.get("gate") == "A" and d.get("status") == "approved"
                   and d.get("source_revision") == ctl.get("source_revision") for d in (ctl.get("decisions") or {}).values())
    except (OSError, ValueError, AttributeError):
        return None


def _listed_items(view: dict, shown: int) -> list:
    """`[(ticket key, item)]` the packet names: the first `shown` files in order. THE one selection, for the lines of the packet
    (`_attachment_name_lines`) and for the record of what was named (`named_attachment_ids`)."""
    out = []
    for ticket in view.get("tickets") or []:
        for item in ticket["items"]:
            if len(out) < shown:
                out.append((ticket["key"], item))
    return out


def named_attachment_ids(view: dict) -> list:
    """`<KEY>: <name>` of the files the packet NAMES, not of the files it counts: at most `attachments_shown`; [] when the packet
    prints no list (`## Attachments: not known`, no inventory, no file listed, the answer words unreadable - the conditions of
    `_attachment_lines`). What nobody was shown by name must not read as seen (AR-28)."""
    try:
        if view.get("state") != "known" or not view.get("known") or not view.get("total") or not attachment_question_words():
            return []
        import branch_accounting
        shown = branch_accounting.limit("attachments_shown")
        return attachment_ids({"tickets": [{"key": key, "items": [item]} for key, item in _listed_items(view, shown)]})
    except Exception:  # noqa: BLE001 - a record that cannot be made names nothing
        return []


def _shown_record(task_root) -> tuple:
    """`(whole, named)` of the attachments the plan gate shows NOW: `whole` is `attachment_ids` over `attachments_view` ([] when
    nothing is listed, None when the list is not known), `named` is what the packet names (`named_attachment_ids`)."""
    try:
        import branch_accounting
        view = branch_accounting.attachments_view(task_root)
        return (attachment_ids(view) if view["known"] else None), named_attachment_ids(view)
    except Exception:  # noqa: BLE001 - no record is better than no gate
        return None, []


def shown_attachments(task_root) -> list:
    """The whole list the plan gate has NOW; the driver keeps it with the packet (`state["shown_attachments"]["A"]`) so a later
    gate can say what is new. [] when nothing is listed; None when the list is not known (a later gate then claims nothing is new)."""
    return _shown_record(task_root)[0]


def keep_shown_attachments(task_root, state=None) -> None:
    """THE write of `state["shown_attachments"]` (`A`: the whole list, for the `new since` line; `A_named`: what the packet named,
    the only list that counts as seen). The driver passes its own `state` dict and saves it. The skill path (`main`, after the
    brief is printed) passes none and the record goes into `state/driver-state.json`, and only when it can be told apart from
    nobody having seen it: no write when the story folder does not exist (a typo in `--task` creates nothing), when a current
    approved decision of gate A stands or cannot be read (the person has answered; the way out is a `rework` of a stage up to S4,
    which stales that decision), or when there is no file to keep other keys in and nothing is known to record. A file that exists
    and is not a JSON object is left alone (no record: nothing counts as shown; the error goes only toward a debt)."""
    shown, named = _shown_record(task_root)
    if state is not None:
        held = state.setdefault("shown_attachments", {})
        held["A"], held["A_named"] = shown, named
        return
    root = Path(task_root)
    if not root.is_dir() or gate_a_decided(root) is not False:
        return
    path = root / "state" / ATTACHMENTS_STATE_FILE
    held = {}
    if path.exists():
        held = read_json(path, None)
        if not isinstance(held, dict):
            return
    elif shown is None:
        return
    if not isinstance(held.get("shown_attachments"), dict):
        held["shown_attachments"] = {}
    held["shown_attachments"]["A"], held["shown_attachments"]["A_named"] = shown, named
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(held, ensure_ascii=False, indent=2), encoding="utf-8")


def write_gate_message(task_root, text, session_id, now=None):
    """THE one writer of gate A's message file (RN1-4, AR-14): `text` - exactly what `main` prints - goes whole to
    `<task_root>/work/gate-a-message.md`, and THEN its record to `<task_root>/state/gate-message.json`:
    `{"gate": "A", "sha256", "session_id", "written_at" (UTC, ms, Z), "path"}`. The record is written LAST - it is the
    "asked" fact the Stop hook reads (`gate_shown.py`); a message without its record is not an open gate, and a failed
    message write leaves no record. Returns the message path; None, and nothing written, when `task_root` is not a
    directory (a typo in `--task` creates nothing, as `keep_shown_attachments`). A failed write raises OSError: the caller
    says it. `session_id` "" is an unbound record: the hook refuses nobody for it (FR-2).
    Also the one writer of `work/reference-behaviours.md` (F1, AR-14), for a story whose reference snapshot was read: written BEFORE the
    message, from the same `reference_facts` the block counts from; a story with no reference, or an unreadable snapshot, gets no file."""
    import hashlib
    from datetime import timezone
    import event_store
    root = Path(task_root)
    if not root.is_dir():
        return None
    path = root / "work" / GATE_MESSAGE
    behaviours = reference_behaviours_text(reference_facts(root))      # F1: a story with a reference; None otherwise, nothing written
    if behaviours:
        event_store.atomic_text(root / "work" / REFERENCE_BEHAVIOURS, behaviours)
    event_store.atomic_text(path, text)
    stamp = (datetime.now(timezone.utc) if now is None else now).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    event_store.atomic_json(root / "state" / GATE_MESSAGE_RECORD, {
        "gate": "A", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "session_id": str(session_id or ""),
        "written_at": stamp, "path": f"work/{GATE_MESSAGE}"})
    return path


def _strings(value):
    """`value` when it is a list of strings, else None."""
    return value if isinstance(value, list) and all(isinstance(v, str) for v in value) else None


def attachments_data(task_root) -> dict:
    """The view of gate A's attachments block, plus the record of the last time this gate was shown (`None` = never recorded, or
    the record cannot be read): `before` the whole list (nothing is claimed to be new when None), `named` what the packet named
    (nothing counts as seen when None)."""
    import branch_accounting
    view = branch_accounting.attachments_view(task_root)
    before = named = None
    try:
        state = read_json(Path(task_root) / "state" / ATTACHMENTS_STATE_FILE, {}) or {}
        held = state.get("shown_attachments") if isinstance(state, dict) else None
        if isinstance(held, dict):
            before, named = _strings(held.get("A")), _strings(held.get("A_named"))
    except Exception:
        before = named = None
    return {**view, "before": before, "named": named}


def _unknown_attachment_lines(cause: str, word: str) -> list:
    """The block that says the list is not known (FR-41): a report, not a question - one move, no options (human-questions.md item 6)."""
    instead = f" instead of `{word}`" if word else ""
    return [ATTACHMENTS_UNKNOWN_HEAD,
            f"The factory could not read which attachments the ticket and the tickets kept for it have ({cause}), so it cannot "
            "name them. That is the factory's own gap. If you know of one that holds a requirement, say which requirement in "
            f"your own words{instead}."]


def _attachment_name_lines(view: dict, shown: int) -> list:
    """`- <KEY>: <name> (opened), <name> (not opened: <cause>)` per ticket, at most `shown` names in all; what does not fit is
    `- (+<K> more on <KEY>, <KEY>)`, a ticket with none listed `- <KEY>: not known`. The head's `N` is never cut by this."""
    lines, over = [], {}
    chosen = {id(item) for _key, item in _listed_items(view, shown)}       # the selection the record of "named" uses too
    for ticket in view.get("tickets") or []:
        names = []
        for item in ticket["items"]:
            if id(item) in chosen:
                shown_as = ("opened in part" if item.get("part") else "opened") if item["opened"] else f"not opened: {item['cause']}"
                names.append(f"{item['name']} ({shown_as})")
            else:
                over[ticket["key"]] = over.get(ticket["key"], 0) + 1
        if names:
            lines.append(f"- {ticket['key']}: {', '.join(names)}")
    if over:
        lines.append(f"- (+{sum(over.values())} more on {', '.join(over)})")
    lines += [f"- {t['key']}: not known" for t in view.get("tickets") or [] if not t["known"]]
    return lines


def _new_attachment_line(view: dict, shown: int) -> list:
    """`new since you last saw this list: ...` when this gate was shown before and an attachment is not in what was recorded."""
    before = view.get("before")
    if before is None:
        return []
    held = set(before)
    fresh = [(t["key"], i["name"]) for t in view.get("tickets") or [] for i in t.get("items") or []
             if f"{t['key']}: {i['name']}" not in held]
    if not fresh:
        return []
    named = ", ".join(f"{name} ({key})" for key, name in fresh[:shown])
    return ["new since you last saw this list: " + named + (f" and {len(fresh) - shown} more" if len(fresh) > shown else "")]


NO_REQUIREMENT_HEAD = "## Tickets you kept: no requirement taken from their text ({n})"


def _no_requirement_lines(data: dict) -> list:
    """The block of the kept tickets none of whose sentences obliges anything (the zero outcome, V1): `- <KEY>: read; no requirement
    taken from it: <why>` (+ ` (and <k> other reasons)` when its homes differ), under the same limit as the names, `N` the whole
    count. A report, one move, no options (human-questions.md item 6); the person's words that name a ticket with a requirement go
    to the conductor, and the approval-first-line tail stands even when this block is alone (F-10). [] when no ticket is such and the
    list is known, and when the inventory cannot be read (`## Attachments: not known` has named that once). A register that cannot be
    read is named (AR-28). The block shows; it never changes a verdict."""
    view = data.get("attachments")
    if not isinstance(view, dict) or view.get("state") != "known" or not view.get("known"):
        return []
    rows, known = view.get("no_requirement") or [], view.get("no_requirement_known") is not False
    if not rows and known:
        return []
    word_rows = approval_words("A")
    word = word_rows[0] if word_rows else ""
    try:
        import branch_accounting
        shown = branch_accounting.limit("attachments_shown")
    except Exception:  # noqa: BLE001 - the limit is only a form
        shown = 15
    lines = [NO_REQUIREMENT_HEAD.format(n=len(rows) if known else "not known")]
    for key, whys in rows[:shown]:
        more = f" (and {len(whys) - 1} other reasons)" if len(whys) > 1 else ""
        lines.append(f"- {key}: read; no requirement taken from it: {whys[0]}{more}")
    if len(rows) > shown:
        lines.append(f"- (+{len(rows) - shown} more tickets read, with no requirement taken from them)")
    if not known:
        lines.append(f"- the tickets read with no requirement taken from them: not known ({view.get('no_requirement_reason')})")
    instead = f", instead of `{word}`" if word else ""
    lines.append(f"If one of them holds a requirement, say which, in your own words{instead}.")
    if word:
        lines.append(APPROVAL_FIRST_LINE_TAIL)
    return lines


def _nothing_listed_lines(view: dict, unknown: list, shown: int, word: str) -> list:
    """No attachment is listed: [] when every ticket is known; else the `not known` block naming each ticket that could not be
    read and why (at most `shown`, the rest counted). A kept ticket with no requirement taken from it has its own block
    (`_no_requirement_lines`), listed files or none (F-D11)."""
    import branch_accounting
    if not unknown:
        return []
    causes = [branch_accounting.attachment_name(f"{t['key']}: {t['reason']}", 160) for t in unknown[:shown]]
    if len(unknown) > shown:
        causes.append(f"{len(unknown) - shown} more tickets")
    return _unknown_attachment_lines("; ".join(causes), word)


def _attachment_lines(data: dict) -> list:
    """The block of gate A (spec amendment 3.2, 3.4): [] when there is nothing to say (no inventory on disk, or every ticket of
    the scope has no attachment); `## Attachments: not known` when the list cannot be read or the answer words cannot; else the
    list, the question and its two answers, each with its price lines (AR-16). Never raises: no block is better than no gate."""
    view = data.get("attachments")
    if not isinstance(view, dict) or view.get("state") == "absent":
        return []
    rows = approval_words("A")
    word = rows[0] if rows else ""
    try:
        import branch_accounting
        shown = branch_accounting.limit("attachments_shown")
        unknown = [t for t in view.get("tickets") or [] if not t["known"]]
        if not view.get("known"):
            return _unknown_attachment_lines(view.get("reason") or "the list could not be read", word)
        if view["total"] == 0:
            return _nothing_listed_lines(view, unknown, shown, word)
        answers = attachment_question_words()
        if not answers:
            return _unknown_attachment_lines("the factory's list of answers to this question could not be read", word)
        labels = _price_labels()
        lines = [ATTACHMENTS_HEAD.format(n=view["total"]), ATTACHMENTS_INTRO, *_new_attachment_line(view, shown),
                 *_attachment_name_lines(view, shown), ATTACHMENTS_ASK]
        for letter, name in (("a", "nothing_to_add"), ("b", "own_words")):
            row = answers[name]
            if name == "nothing_to_add":
                head = f"(a) `{word}` - {row['says']}." if word else f"(a) {row['says_without_word']}."
            else:
                head = f"(b) {row['says'].replace('{word}', word)}." if word else f"(b) {row['says_without_word']}."
            lines.append(head)
            lines += [f"{label} {row[key]}" for label, key in zip(labels, ("factory", "you", "story"))]
        if word:
            lines.append(APPROVAL_FIRST_LINE_TAIL)
        return lines
    except Exception:  # noqa: BLE001
        return _unknown_attachment_lines("the factory's own record of them could not be worked out", word)


def grounding_facts(task_root: Path) -> dict:
    """What gate A shows of the grounding table (G2-5): `{"state", "share", "coverage", "statements", "why"}`. THE reader is
    `planning_contract.read_grounding` and the two keys are the measures the S3 step saved (`refactoring_share`, `requirement_coverage`;
    their bytes are judged at the S3 exit, R6): nothing is measured again here. `state`: `none` (no table, or a story with no diff: nothing to
    say), `table`, or `unreadable` (a table that exists and cannot be read; `why`). `statements` = the register's words for the requirements
    the coverage leaves out, `{R-n: text}` ({} when the register cannot be read: the id is shown alone). Never raises."""
    try:
        import planning_contract as PC
        doc, problem = PC.read_grounding(task_root)
        if doc is None:
            return {"state": "none"} if getattr(problem, "kind", "") == "missing" else {"state": "unreadable", "why": str(problem)[:160]}
        data = doc.data if isinstance(doc.data, dict) else {}
        if data.get("implementation_source") != "diff":
            return {"state": "none"}
        share, cov = data.get("refactoring_share"), data.get("requirement_coverage")
        statements: dict = {}
        if isinstance(cov, dict) and cov.get("outside"):
            try:
                import grounding_table as GT
                statements = dict(GT.register_info(task_root).texts)   # the words; `.statements` holds a digest of each (F-1)
            except Exception:  # noqa: BLE001
                statements = {}
        return {"state": "table", "share": share if isinstance(share, dict) else None,
                "coverage": cov if isinstance(cov, dict) else None, "statements": statements}
    except Exception as exc:  # noqa: BLE001
        return {"state": "unreadable", "why": f"{type(exc).__name__}: {str(exc)[:120]}"}


def _named_requirement(r: str, statements: dict, asked: str) -> str:
    said = " ".join(str(statements.get(r) or "").split())
    said = (said[:90].rstrip() + "...") if len(said) > 90 else said
    return f"{r}" + (f" ({said})" if said else "") + (" — asked as a question below" if re.search(rf"(?<![A-Za-z0-9-]){re.escape(r)}(?![0-9])", asked) else "")


def _grounding_lines(data: dict) -> list:
    """The grounding lines of gate A (G2-5), a bounded block that starts with a blank line; [] when there is nothing to say (no table, a
    story with no diff, a share at or under the notify mark, every requirement covered). A line only for a person: no field names, no
    `K-n` / `B-n`. It asks nothing: a requirement a question below is about is said to be asked there (one packet does not argue with
    itself, FR-10). A measure the table saved as `unknown` is a gap of the factory, said as such (FR-41); a table that cannot be read is
    ONE line, not silence."""
    g = data.get("grounding") or {}
    if g.get("state") == "unreadable":
        return ["", "**What the change touches** — the factory could not read its table of the changed code, so the share of refactoring and "
                    "the requirements the change covers are not known; that is a gap of the factory, not yours."]
    if g.get("state") != "table":
        return []
    out = []
    share, cov = g.get("share") or {}, g.get("coverage") or {}
    road = share.get("road")
    policy = share.get("policy") if isinstance(share.get("policy"), dict) else {}
    if road in ("notify", "stop"):
        mark = policy.get("notify_above_percent" if road == "notify" else "stop_above_percent")
        out.append(f"**Refactoring** — {share.get('percent')}% of the changed production lines are refactoring or not classified"
                   + (f", above the {mark}% mark" if mark is not None else "")
                   + (": the plan was written after you chose to go on." if road == "stop" else ": the plan is checked against what really changed in behaviour."))
    elif road == "unknown":
        out.append("**Refactoring** — the share of refactoring in the change could not be measured"
                   + (f" ({' '.join(str(share.get('reason')).split())[:140]})" if share.get("reason") else "") + "; that is a gap of the factory, not yours.")
    if cov.get("road") == "unknown":
        out.append("**Coverage** — what part of the story's requirements the change implements could not be measured"
                   + (f" ({' '.join(str(cov.get('reason')).split())[:140]})" if cov.get("reason") else "") + "; that is a gap of the factory, not yours.")
    elif cov.get("reading") == "nothing_asked":
        out.append("**Coverage** — no requirement of the story is left for this change to implement.")
    elif cov.get("road") in ("highlight", "stop"):
        asked = " ".join(f"{q.get('question')} {q.get('source_says')}" for q in data.get("open_questions") or [] if isinstance(q, dict))
        names = [_named_requirement(str(o.get("r")), g.get("statements") or {}, asked) for o in cov.get("outside") or [] if isinstance(o, dict)]
        shown = "; ".join(names[:6]) + (f"; and {len(names) - 6} more" if len(names) > 6 else "")
        out.append(f"**Coverage** — the change implements {int(cov.get('implemented') or 0) + int(cov.get('partial') or 0)} of {cov.get('n')} "
                   f"requirements of the story. Not implemented, or not shown to be: {shown}.")
    return [""] + out if out else []


# --- gate A: a story with a reference, the OLD version as a second stand (t-2181 PC-9c; the owner's D3 and F-7, W1 of 11.11.2026) --------
# In "as before" mode the packet shows only what the person must look at: where the story differs from the old version, the requirements
# that ask to match it with nothing seen to match, what was seen and no case uses, and the gaps of the walk; the rest is ONE count. Code
# reads and counts (AR-26: the unit is the requirement; the reader of the snapshot is `reference_snapshot.read`, of the register `contract`,
# AR-13); whether an item shows what a Then says is the case critic's judgment, not this block's. What was seen on the reference stand is
# a SAMPLE of the old version: the block names it so, and reads no run of the story, so a run recorded there is never shown as evidence (W1).
REFERENCE_SHOWN = 8          # names listed per list (differences, requirements with nothing seen, unused items, gaps, parity requirements), then "and K more"
REFERENCE_CLIP = 100         # characters of one requirement text, one behaviour name or one old/new text in the block
REFERENCE_SAMPLE = ("What the factory saw of the old version is a sample of how it behaved. It is not a test result of this story and is not "
                    "evidence for it.")


def _project_root_of(task_root):
    """The project root above a story folder (the nearest ancestor that carries `qa-factory/config.json`), None when there is none."""
    try:
        resolved = Path(task_root).resolve()
        for base in (resolved, *resolved.parents):
            if (base / "qa-factory" / "config.json").is_file():
                return base
    except Exception:  # noqa: BLE001
        pass
    return None


def _reference_clip(text, limit: int = REFERENCE_CLIP) -> str:
    said = " ".join(str(text or "").split())
    return said if len(said) <= limit else said[:limit].rstrip() + "..."


def _reference_item_name(item: dict) -> str:
    """A behaviour of the old version by its words (area and the user's path), never by its id."""
    area, path = _reference_clip(item.get("area"), 50), _reference_clip(item.get("user_path"), 70)
    return " — ".join(part for part in (area, path) if part) or _reference_clip(item.get("observed")) or "a behaviour without a description"


def _reference_uses(task_root, ids: set) -> tuple:
    """(snapshot item ids that a Then of some case cites with `precedent` `reference:<item>`, requirement ids those cases rest on).
    The case reader of record is `story_cases`; the `then_oracles` and `basis` lines are read by `contract` (AR-13). A case that cannot be
    read cites nothing here: the unused list then names more, never fewer."""
    used, rests = set(), set()
    try:
        cases, _problems = story_cases(task_root)
    except Exception:  # noqa: BLE001
        return used, rests
    for case in cases.values():
        try:
            text = Path(case["path"]).read_text(encoding="utf-8", errors="replace")
            entries, _ = C.then_oracles_from_text(text)
            basis = C.requirement_id(str(C.front_line(text, "basis") or "").strip().strip("\"'"))
        except Exception:  # noqa: BLE001
            continue
        for entry in entries or []:
            found = C.REFERENCE_REF_RE.match(str(entry.get("ref") or "").strip()) if entry.get("source") == "precedent" else None
            if found and found.group(1) in ids:
                used.add(found.group(1))
                if basis:
                    rests.add(basis)
    return used, rests


def reference_facts(task_root) -> dict:
    """What gate A shows of a story's reference: `{"state": "none"}` (no side has a reference: the packet is as it was), `{"state":
    "unreadable", "env"}` (a reference is named and its snapshot is absent or cannot be read), or `{"state": "read", "env", "total",
    "differing": [{r, words, before, now, differs}], "parity_gaps": [{r, words}], "unused": [names], "gaps": [lines], "carried",
    "parity": [R ids], "register_unread", "behaviours": [{name, observed, standing, r}]}` (`behaviours`: every item with its standing
    carried / differs / unused, the facts of the document). Never raises, writes nothing. The error direction is toward saying more: a
    register that cannot be read is `register_unread` (differences and gaps are then NOT known, never none). An item cited by a differing
    claim is counted under its difference and is not "unused" (N1): unused means no case uses it AND no difference shows it.
    With two sides that each carry a reference only the first stand's name is the default `env` (N3: one snapshot per story, whose own
    `reference_env` wins). A story archived under `_archive` names no reference stand and reads `none` (N4: gate A is not built for one)."""
    project = _project_root_of(task_root)
    if project is None:
        return {"state": "none"}
    try:
        import stand_identity as SI
        named = SI.reference_stands(project, Path(task_root).name)
    except Exception:  # noqa: BLE001
        return {"state": "none"}
    if not named:
        return {"state": "none"}
    env = sorted(named)[0]
    try:
        import reference_snapshot as RS
        snap = RS.read(task_root)
    except Exception:  # noqa: BLE001
        snap = None
    if snap is None:
        return {"state": "unreadable", "env": env}
    items = [i for i in snap["items"] if isinstance(i, dict) and str(i.get("id") or "").strip()]
    by_id = {str(i["id"]): i for i in items}
    gaps = [_reference_clip(g, 160) for g in (snap.get("gaps") if isinstance(snap.get("gaps"), list) else []) if str(g).strip()]
    register_unread, rows, claims, parity = False, {}, [], set()
    try:
        path = Path(C.artifact(task_root, "requirements-register.md"))
        text = C.read_text(path) if path.is_file() else ""
        rows = {row["r"]: row for row in C.register_rows(text)}
        claims, parity = C.behaviour_claims(text), C.parity_ids(text)
        register_unread = not text.strip() or not rows
    except Exception:  # noqa: BLE001
        register_unread = True
    used, rests = _reference_uses(task_root, set(by_id))

    def words(r):
        return _reference_clip((rows.get(r) or {}).get("requirement"), 90)

    differing, seen_by_claim, cited, differs_in = [], set(), set(), {}
    for claim in claims:
        found = C.REFERENCE_REF_RE.match(str(claim.get("before_ref") or "").strip())
        if not found:
            continue
        item = found.group(1)
        if item in by_id:
            cited.add(str(claim["r"]))
        if claim.get("differs") in ("yes", "unknown"):
            differing.append({"r": claim["r"], "words": words(claim["r"]), "before": _reference_clip(claim.get("before")),
                              "now": _reference_clip(claim.get("now")), "differs": claim.get("differs")})
            if item in by_id:
                seen_by_claim.add(item)
                differs_in.setdefault(item, []).append(str(claim["r"]))
    parity_gaps = [{"r": r, "words": words(r)} for r in sorted(parity - cited - rests)]
    unused_ids = [ident for ident in by_id if ident not in used and ident not in seen_by_claim]
    standing = {ident: ("differs" if ident in seen_by_claim else "unused" if ident in unused_ids else "carried") for ident in by_id}
    # `behaviours`: EVERY item by its words with its standing, the facts of the document `work/reference-behaviours.md` (F1); the block above
    # counts from the same lists, so the file and the count line cannot disagree
    behaviours = [{"name": _reference_item_name(item), "observed": _reference_clip(item.get("observed"), 400), "standing": standing[ident],
                   "r": differs_in.get(ident, [])} for ident, item in by_id.items()]
    return {"state": "read", "env": str(snap.get("reference_env") or env), "total": len(by_id), "differing": differing,
            "parity_gaps": parity_gaps, "unused": [_reference_item_name(by_id[ident]) for ident in unused_ids], "gaps": gaps,
            "parity": sorted(parity), "register_unread": register_unread, "behaviours": behaviours,
            "carried": len(by_id) - len(seen_by_claim) - len(unused_ids)}


def _reference_names(names: list, shown: int = REFERENCE_SHOWN) -> str:
    return "; ".join(names[:shown]) + (f"; and {len(names) - shown} more" if len(names) > shown else "")


def _reference_lines(data: dict) -> list:
    """The gate A block of a story with a reference (D3): a bounded block that starts with a blank line; [] for a story with no reference
    (the packet is byte for byte what it was). A snapshot that cannot be read is ONE line saying so (the rest of the brief is shown as it is,
    AR-28); zero differences and zero gaps is ONE line with the count, never an empty heading (F-7: the approval confirms the requirements
    that ask to match the old version). Words for a person: no ids of snapshot items, no keys, no paths."""
    ref = data.get("reference") or {}
    env = " ".join(str(ref.get("env") or "").split())
    if ref.get("state") == "unreadable":
        return ["", f"**The old version, as the reference** — this story has the old version ({env}) as a reference, but what the factory saw "
                    "of it could not be read, so where the story differs from it is not known; the rest of this brief is as it is for a story "
                    "with no reference."]
    if ref.get("state") != "read":
        return []
    total, parity = int(ref.get("total") or 0), [str(r) for r in ref.get("parity") or []]
    differing, parity_gaps = ref.get("differing") or [], ref.get("parity_gaps") or []
    unused, gaps, unread = ref.get("unused") or [], ref.get("gaps") or [], bool(ref.get("register_unread"))
    # F-7: the approval confirms the parity scope, in BOTH forms; with no parity requirement it says it confirms none (F4)
    confirms = (" Your approval confirms that these requirements ask to match the old version: " + _reference_names(parity).replace("; ", ", ") + "."
                ) if parity else ("" if unread else
                                  " No requirement is marked as asking to match the old version, so your approval confirms none.")
    listed = " All of them are listed in the document below." if ref.get("document") else ""
    if not (differing or parity_gaps or unused or gaps or unread) and total:
        return ["", f"**The old version, as the reference** — this story matches the old version ({env}) on all {total} behaviours the factory saw "
                    f"of it.{listed} {REFERENCE_SAMPLE}{confirms}"]
    out = ["", f"## The old version as the reference ({env})", REFERENCE_SAMPLE]
    if unread:
        out.append("- The list of requirements could not be read, so where the story differs from the old version, and which requirements "
                   "ask to match it, is not known.")
    out.extend(_reference_list("Where the story differs from the old version, or it is not known whether it does", [
        f"{d['r']}" + (f" ({d['words']})" if d["words"] else "") + f": the old version {d['before'] or 'is not described'}; "
        f"the story now {d['now'] or 'is not described'}" + ("" if d["differs"] == "yes" else " (not known whether this is a difference)")
        for d in differing]))
    out.extend(_reference_list("Requirements that ask to match the old version, with nothing seen of it to match",
                               [f"{g['r']}" + (f" ({g['words']})" if g["words"] else "") for g in parity_gaps]))
    out.extend(_reference_list("Seen in the old version and used by no test case", unused))
    out.extend(_reference_list("What the factory could not see of the old version", gaps))
    carried = int(ref.get("carried") or 0)
    out.append(f"{carried} of the {total} behaviours the factory saw in the old version are carried over as they are.{listed}" if total
               else "The factory saw no behaviour of the old version.")
    if confirms:
        out.append(confirms.strip())
    return out


def _reference_list(heading: str, items: list) -> list:
    """ONE list of the reference block: `heading (n):`, at most REFERENCE_SHOWN `- item` lines, then `- and K more`; [] for no item (F2: the
    four lists of the block are this one renderer, so the cap is one rule with one test)."""
    if not items:
        return []
    out = [f"{heading} ({len(items)}):"] + [f"- {item}" for item in items[:REFERENCE_SHOWN]]
    if len(items) > REFERENCE_SHOWN:
        out.append(f"- and {len(items) - REFERENCE_SHOWN} more")
    return out


def reference_behaviours_text(ref: dict):
    """The document `work/reference-behaviours.md` (F1): every behaviour of the old version the factory saw, by its words (area, the user's
    path, what was seen), each marked carried over / differs from the story (with the requirement) / used by no test case; then what the
    walk could not see. From the SAME facts as the gate A block (`reference_facts`), so the file and the count line cannot disagree. Not
    capped (a long document, linked from the brief). None when there is no behaviour to list: no reference, an unreadable snapshot, or none seen."""
    if not isinstance(ref, dict) or ref.get("state") != "read" or not ref.get("behaviours"):
        return None
    env = " ".join(str(ref.get("env") or "").split())
    out = [f"# The old version as the factory saw it ({env})", "", REFERENCE_SAMPLE, "",
           f"{len(ref['behaviours'])} behaviours were seen. Each is marked: carried over as it is, differs from the story, or used by no test case.", ""]
    marks = (("differs", "Differs from the story"), ("carried", "Carried over as they are"), ("unused", "Used by no test case"))
    for key, title in marks:
        rows = [b for b in ref["behaviours"] if b.get("standing") == key]
        if not rows:
            continue
        out += [f"## {title} ({len(rows)})", ""]
        for b in rows:
            said = f" ({', '.join(b['r'])})" if key == "differs" and b.get("r") else ""
            out.append(f"- {b['name']}{said}: " + (b.get("observed") or "what was seen is not described"))
        out.append("")
    if ref.get("gaps"):
        out += [f"## What the factory could not see ({len(ref['gaps'])})", ""] + [f"- {g}" for g in ref["gaps"]] + [""]
    return "\n".join(out)


def render(data: dict) -> str:
    lines = _head_lines(data)
    grounding = _grounding_lines(data)       # G2-5: right after the cover sheet; the cap grows by exactly their length
    lines.extend(grounding)
    reference = _reference_lines(data)       # PC-9c: a story with a reference; [] otherwise, so the packet of a story with none is unchanged
    lines.extend(reference)
    lines.extend(_after_approval(data))
    questions = data.get("open_questions") or []
    question_lines = _question_lines(data, questions)
    lines.extend(question_lines)
    cards = data.get("stand_gap_cards") or []
    if cards:
        lines.append("")
        lines.extend(cards)
    attachments = _attachment_lines(data)         # S6 step 1c: after the questions and cards, before what is already decided
    if attachments:
        lines.append("")
        lines.extend(attachments)
    no_requirement = _no_requirement_lines(data)  # S6 1d: its own block, after the attachments, listed files or none
    if no_requirement:
        lines.append("")
        lines.extend(no_requirement)
    if data.get("adapted_lines"):
        lines.append("")
        lines.extend(data["adapted_lines"])
    lines.extend(_decided_lines(data))
    lines.extend(_unreachable_lines(data))
    judged = judge_lines(data.get("judge") or {})
    lines.extend(_tail_sections(data, judged))
    # The cap is about the cover sheet, not about the cards: a card is the question itself, in
    # the form the person answers, so the budget grows by exactly what the cards take and the
    # paths at the bottom survive. Without this a story with two stand gaps lost its document
    # links to the truncation — the one thing the brief exists to carry.
    # The same reasoning covers the question cards: the cap protects the cover sheet, and a
    # question printed in full IS the thing the person is at the gate for. The budget grows by
    # exactly what the cards beyond a one-liner each take, so the document links at the bottom
    # survive a story with three questions and two stand gaps.
    shown = len(questions)
    cap = (MAX_LINES + 2      # GW1-11: the approval line and its blank line are not part of the cover sheet's budget
           + len(cards) + max(0, len(question_lines) - ((2 + shown) if questions else 0))      # GW1-32: the answer block outlives the cap with no question too
           + (len(judged) + 1 if judged else 0)
           + len(grounding)      # G2-5: a bounded block (<= 5 lines) of the head, never cut by the cap
           + len(reference)      # PC-9c: a bounded block (<= 6 * (REFERENCE_SHOWN + 2) lines) of the head, the same way
           + len(_answered_lines(data))      # HF4-8: a bounded block (<= ANSWERS_SHOWN + 2 lines) the links below must outlive
           + len(_by_words_lines(data))      # RN1-14: a bounded block (<= LEFT_OUT_CAP + 1 lines) the same way
           + (len(data["adapted_lines"]) + 1 if data.get("adapted_lines") else 0)     # B-416 N8: a bounded block (<= 7 lines) the links must outlive
           + (len(attachments) + 1 if attachments else 0)     # S6 1c: the block is the question itself (bounded by `attachments_shown`), the links outlive it
           + (len(no_requirement) + 1 if no_requirement else 0))     # S6 1d: the same for the zero-outcome block
    if len(lines) > cap:
        kept = lines[:cap - 1]
        kept.append(f"_(brief truncated at {cap} lines; the documents above carry the rest)_")
        lines = kept
    return "\n".join(lines) + "\n"


def project_config(task_root: Path) -> dict:
    """The onboarded project's config, found by the same marker everything else uses."""
    base = _project_root_of(task_root)
    return (read_json(base / "qa-factory" / "config.json", {}) or {}) if base is not None else {}


def _first(data: dict, *keys):
    """The first of several spellings that is actually present.

    `work/sizing.json` is written by another part of this build; a brief that refused to show
    a size because a key was spelled differently would be the thing it exists to prevent."""
    for key in keys:
        if isinstance(data, dict) and data.get(key) is not None:
            value = data[key]
            if isinstance(value, dict):
                for inner in ("cases", "value", "total", "count"):
                    if value.get(inner) is not None:
                        return value[inner]
                continue
            return value
    return None


def sizing_line(task_root: Path) -> str:
    """The story's size as the code computed it, or "" when nothing computed one.

    A story sized by a sentence is how a fourteen-case window became three. The numbers belong
    in front of the person approving the plan; an absent `work/sizing.json` is simply an absent
    line, never a complaint — a project on an older build has none."""
    data = read_json(task_root / "work" / "sizing.json")
    if not isinstance(data, dict):
        return ""
    import sizing  # the ONE writer of the function and defect sentences, shared with report_facts._r_size (AR-19)
    parts = []
    size = _first(data, "size", "size_class", "class", "result")
    functions = sizing.function_words(data)       # "" in the old world (no `size_unit`, or "requirements")
    defect = sizing.defect_words(data)            # "" unless the defect cap applied AND the uncapped weight is recorded
    if size is not None:
        parts.append(f"size **{size}**" + (f" ({functions})" if functions else ""))
    if sizing.heavy_words(data):
        parts.append(sizing.heavy_words(data))
    # `sizing.py` writes `computed_budget` (what the requirements weigh) and
    # `recommended_budget` (that number held to the cap). The brief asked for `budget` and
    # showed no budget at all on a story that had one.
    # t-342 (B-271): "budget 84 (recommended 28), cap 28" asked the person to know what a budget is. The words are
    # the report's too (`report_facts._r_size`, the template): what the requirements weigh, and the cap of the
    # size - one sentence, said the same way in both carriers. The "recommended" figure is the budget held to the
    # cap, which the cap already says; the overage below still says by how much the cap is passed.
    budget = _first(data, "computed_budget", "budget", "cases_budget", "case_budget", "weighted")
    cap = _first(data, "cap", "size_cap", "budget_cap")
    weighs = f"the requirements weigh {budget} (each weighted by its priority and area)" if budget is not None else ""
    capped = (f"the {size} cap is {cap}" if size is not None else f"the cap is {cap}") if cap is not None else ""
    overage = _first(data, "overage", "over_cap", "excess")
    if functions:                    # the size is a count of functions: the number beside it is the TEST ceiling, a different fact
        capped = f"the test ceiling is {cap}" if cap is not None else ""
    if defect:                       # ONE ceiling for the person: the planned case count; the cap is only the band of 1
        weighs, capped, overage = defect, "", None
    if weighs or capped:
        parts.append("; ".join(part for part in (weighs, capped) if part))
    if overage:
        parts.append(f"**over it by {overage}**" if functions else f"**over the cap by {overage}**")
    # A list of `{r, reason}` rows, not a number: printed as itself it put a Python repr in
    # front of the person.
    unverifiable = _first(data, "unverifiable", "unverifiable_count", "not_observable")
    count = len(unverifiable) if isinstance(unverifiable, (list, tuple, dict)) else unverifiable
    if count:
        parts.append(f"{count} requirement(s) nothing here can verify")
    override = _first(data, "size_override", "override")
    if override:
        reason = _first(data, "size_override_reason")
        parts.append(f"your own override: {override}" + (f" ({reason})" if reason else ""))
    if not parts:
        return ""
    line = "**Size** — " + ", ".join(parts) + ". Arithmetic: work/sizing.json."
    # The XXL recommendation lived in `reasoning[]`, which nothing rendered: the one size that
    # is a message to the person was the one size the person never saw.
    if str(size) == "XXL":
        line += " " + (sizing.XXL_ADVICE_FUNCTIONS if functions else sizing.XXL_ADVICE_ROWS)
        if functions and len((data.get("functions") or [])) + len(data.get("functions_unlisted") or []) > sizing.NAMES_ON_LINE:
            line += " The functions are listed in full in work/sizing.json."
    return line


# --- what is still open when the MR is about to be opened ------------------------------------
# The owner's decision of 21.09.2026: at a gate the factory WAITS for the person. An answer
# that misses the question is re-asked once only when the information is critical for testing;
# otherwise it is kept as a REMARK and carried, not turned into a second stop. Before the MR
# the person is shown, in one list, everything not done and every question or decision left
# open — and may still say "open the MR anyway", in which case this same list goes into the MR
# description. One builder, so the list in the gate and the list in the MR cannot disagree.

MAX_OPEN_BEFORE_MR = 12


def remarks(task_root: Path) -> list:
    """`pipeline.json` `remarks[]` — `{stage, text, at}` per entry.

    Written by `waiver.py` / `log_append.py` when a person's answer is kept as a remark rather
    than re-asked. Read with a default: a story that recorded none, or one from 0.7.x, simply
    has an empty list. A bare string is read as a remark with no stage, so an older spelling is
    carried rather than dropped."""
    pipeline = read_json(Path(task_root) / "pipeline.json", {}) or {}
    out = []
    for item in pipeline.get("remarks") or []:
        if isinstance(item, dict) and str(item.get("text") or "").strip():
            out.append({"stage": str(item.get("stage") or ""), "at": str(item.get("at") or ""),
                        "text": " ".join(str(item["text"]).split())})
        elif isinstance(item, str) and item.strip():
            out.append({"stage": "", "at": "", "text": " ".join(item.split())})
    return out


WAIVER_WORDS = "waiver"
OVERRIDE_WORDS = "stage override"
REMARK_WORDS = "remark"


def _recorded_words(pipeline: dict) -> list:
    """[(kind, text)] of the person's words recorded OUTSIDE the gates, in the order they are read:
    a waiver (`gate_waivers[]`: `requirement` and `decision`) is kind `waiver`; a stage override
    (`stage_overrides[]`: `match` and `decision`) is kind `stage override`. A kept remark
    (`remarks[]`) is the third record kind and is read by `still_open` through `remarks()`. The
    kind is the `where` a `named` question says it was named in."""
    out = []
    for w in pipeline.get("gate_waivers") or []:
        if isinstance(w, dict):
            out.append((WAIVER_WORDS, f"{w.get('requirement', '')} {w.get('decision', '')}"))
    import contract
    for o in contract.live_stage_overrides(pipeline):        # a revoked word answers nothing: the question is asked again (GW1-1)
        out.append((OVERRIDE_WORDS, f"{o.get('match', '')} {o.get('decision', '')}"))
    return out


def _decision_text(pipeline: dict, with_gates: bool = True) -> str:
    """Everything a person's recorded word is stored in, as one blob to look an id up in.

    A gate record keeps the whole answer in `authorization_source` (`build_gate_decision` stores the
    words there, and `decision` is the bare word `approved`): on TP1-13797 this function read
    only `words` and `decision`, so the five questions the person answered at gate A by name
    looked unanswered (B-181). All three keys are read, since an older record may hold the words
    in either of the first two. `with_gates=False` leaves the gates out: what a gate's words NAME
    is the register's business (`named`, never `answered`)."""
    parts = [text for _kind, text in _recorded_words(pipeline)]
    gates = pipeline.get("gates") if with_gates else None
    for record in (gates.values() if isinstance(gates, dict) else []):
        if isinstance(record, dict):
            parts.append("\n".join(str(record.get(key) or "")
                                   for key in ("authorization_source", "words", "decision")))
    return "\n".join(parts)


NAMED_NOTE = "named in your {where} words; the factory recorded no answer"
NAMED_LINE_NOTE = "named in your {where} words, on a line the factory did not read as an answer: \"{line}\""   # GW1-42
KEPT_OPEN_NOTE = "kept open until the report, on your word {where}; it is not asked again here"
BEFORE_VALUE_NOTE = ("you chose the behaviour before the change, but nobody knows what it was: "
                     "say what it was")


def unmarked_value_note(question: dict) -> str:
    """The note of an answer to a question that does not say which reading is the behaviour before (FR-41): the reading
    the person chose in its own words, never "before" or "now"."""
    letter = str(question.get("reading") or "").strip()
    readings = question.get("readings")
    position = string.ascii_lowercase.find(letter) if len(letter) == 1 else -1
    item = readings[position] if isinstance(readings, list) and 0 <= position < len(readings) else None
    text = " ".join(str(item.get("reading") if isinstance(item, dict) else item or "").split())
    return (f"you chose {letter}: {text}; " if text else f"you chose {letter}; ") + (
        "the question does not say what the behaviour before the change was: say what it was")


def question_note(question: dict) -> str:
    """The plain note a question carries when its status is not simply `open`, or "".

    `named` (an older story: the id stands in the person's gate words and no answer was
    recorded) is said as exactly that, never as answered (FR-41). The suffix "answered <where>"
    belongs to an `answered` question ONLY; `not_needed` is a different thing and does not get it, and
    `<where>` is the person's reading of the place (`question_register.where_words`: "at gate A",
    "when the requirements were checked"), never the raw code of the vocabulary (FR-6).
    A question whose text changed after the answer is asked again, and says so (FR-7); so is an answer
    that chose the behaviour BEFORE the change while nobody wrote that value down. A deferred question whose
    record holds is said to be kept open on the person's word and not asked here (T4); one whose row changed
    since is asked again, like an answered one."""
    import question_register as QR
    status = str(question.get("status") or "")
    where = str(question.get("where") or "").strip()
    suffix = f" (answered {QR.where_words(where)})" if status == "answered" and where else (
        " (answered)" if status == "answered" else "")
    if status == "named":
        # GW1-42: a line that STARTS with the id and is no token (`Q1: a (note)`) is told as that, with the line, never as "no answer";
        # the one reader of such a line is `QR.stray_line` (AR-13). A history `named` with no words keeps the old text.
        stray = QR.stray_line(question.get("id"), question.get("words"))
        if stray:
            return NAMED_LINE_NOTE.format(where=where or "gate", line=stray)
        return NAMED_NOTE.format(where=where or "gate")
    if status == "with_designer":
        return "with the designer; no answer is recorded yet"
    if question.get("changed_since_answer") is True:
        return "its text changed after your answer, so it is asked again" + suffix
    if status == QR.DEFERRED:
        return KEPT_OPEN_NOTE.format(where=QR.where_words(where))
    if C.before_value_needed(question):
        # an unmarked question answered `b` keeps today's reading (O2: `b` is the behaviour before); any other letter is the
        # person's own reading, and is said in its own words, never as "before" (F2)
        if (isinstance(question.get("readings"), list) and C.claim_reading_index(question, C.CLAIM_KEYS[1]) is None
                and str(question.get("reading") or "").strip() != "b"):
            return unmarked_value_note(question)
        return BEFORE_VALUE_NOTE
    return ""


def still_open(rows, view, pipeline: dict, task_root) -> list:
    """The readiness questions a person still has to decide, each with `status` and `status_note`.

    The status comes from the register (`view` = `question_register.load`), matched by the
    question's id exactly and case-sensitively: a question `question_register.settled` calls settled
    (`answered` / `not_needed` on the bytes the person saw: the ONE definition, AR-13) is not listed; `named`,
    `with_designer`, a deferred one (with its note) and an answered one whose text changed ARE listed.
    A row the register cannot place (no id, a repeated id, or no register at all) is listed
    as it stands: the error direction is toward asking, never toward "answered" (FR-41).
    A row that itself carries an `answer`/`resolution` is decided by it, as before. An id that a
    waiver, a stage override or a kept remark names exactly (an exact token: not inside `Q10`,
    a URL or a path; the three records `_recorded_words` and `remarks` read) is NOT an answer
    either (t-155, FR-41): the question stays listed, `named` where it had no other status, with
    the record kind as its `where`. An id in a record of a question the register already marked
    `named` (gate words) or `with_designer` keeps that status; only an `open` one is upgraded."""
    import question_register as QR
    records = _recorded_words(pipeline or {}) + [(REMARK_WORDS, r["text"]) for r in remarks(task_root)]
    out = []
    dict_rows = [row for row in (rows if isinstance(rows, list) else []) if isinstance(row, dict)]
    # Match over ALL dict rows first: the register's answer belongs to the FIRST row of an id (as `load` keeps it), even when that
    # row is itself answered or the conductor's; only then are the filters applied (B-12 F-1).
    for row, mine in zip(dict_rows, QR.matches(dict_rows, view)):   # the first-row-of-an-id rule: `question_register.matches` (AR-13)
        if QR.row_answered(row):
            continue
        if QR.driver_owned(row):
            continue         # t-1815 F2: a role's question with no person class is the conductor's, never listed to a person
        qid = str(row.get("id") or "").strip() if isinstance(row.get("id"), str) else ""
        ident = qid or str(row.get("ref") or row.get("requirement") or "").strip()
        item = dict(row)
        if mine is not None:
            status = mine.get("status")
            # F3 (t-269): an answer that SETTLES nothing is not an answer - Q7 answered `b` ("the behaviour
            # before the change") while the question's own `before` is the designer's `unknown` leaves the
            # expected value missing, so it stays in this list; so does one whose row changed since. Both are
            # `QR.settled`'s test (HF2-7: the one definition the plan check, the stop and this list share), and
            # `question_note` says why. The error direction is toward asking (FR-41).
            if QR.settled(mine):
                continue
            item.update({"status": status, "where": mine.get("where", ""),
                         "changed_since_answer": mine.get("changed_since_answer"),
                         # t-271 F5 / t-279 K-HASH: the fingerprint of the readiness row THIS card is rendered from.
                         # It is printed on the card (`question_card`) and is what an answer to the card must be
                         # stored against: the row can change between the card and the answer.
                         "shown_hash": str(mine.get("row_hash") or "")})
            item["status_note"] = question_note(mine)
        kind = next((kind for kind, text in records if ident and _mentions(text, ident)), "")
        if kind and item.get("status") in (None, "", "open"):
            item.update({"status": "named", "where": kind})
            item["status_note"] = question_note(item)
        out.append(item)
    return out


def unanswered_questions(task_root: Path, pipeline: dict | None = None) -> list:
    """Gate-A open questions with no recorded answer, status from `question_register.load`.

    The one list the gate B / MR section and the gate A packet both read (`still_open`). Before
    this, answered meant "the id appears in the gate's words" - a substring test over a text that
    lacked `authorization_source`, so `Q1` matched inside `Q10` and the real answers of cmp1 were
    never found (B-181). Now: the register's status, exact ids; `named` is listed with its note."""
    pipeline = pipeline if pipeline is not None else (read_json(Path(task_root) / "pipeline.json", {}) or {})
    readiness = read_json(Path(task_root) / "work" / "requirements-readiness.json", {}) or {}
    view, _unread = register_view(task_root)
    return still_open(readiness.get("open_questions") if isinstance(readiness, dict) else [],
                      view, pipeline, task_root)


def open_debts(task_root: Path, carded: tuple = ()) -> list:
    """Rows nobody resolved, each with the owner that carries it: the critic's `## Gate A
    debts` lines, and the automation manifest's `unresolved[]` cases.

    `carded` are the case keys the packet now shows as a stand-gap card. A card states the
    requirement, the missing thing and the exact change; repeating it here as
    "TC-007 not automated: blocked_by_env" is the raw manifest text the card replaces."""
    out = []
    findings = critic_path(task_root)
    if findings:
        try:
            import critic_rollcall
            text = Path(findings).read_text(encoding="utf-8", errors="replace")
            for fix in critic_rollcall.parse_fixes(text):
                owed = critic_rollcall.debt_owner(text, str(fix.get("case_id") or ""))
                if owed and owed not in out:
                    out.append(owed)
        except Exception:
            pass
    manifest = read_json(task_root / "work" / "automation-manifest.json", {}) or {}
    for row in manifest.get("unresolved") or []:
        if not isinstance(row, dict) or not row.get("case"):
            continue
        if str(row.get("reason") or "") == "handed_to_person":
            continue  # it has its own heading, with the command; it is not a loose end
        if str(row.get("case")) in set(carded):
            continue
        out.append(f"{row['case']} not automated: {row.get('reason') or 'no reason recorded'}"
                   + (f" (owner: {row['owner']})" if row.get("owner") else ""))
    return out


def handed_runs(task_root) -> list:
    """The tests the person took over, with what to run for each.

    Its own heading at gate B, not a line inside "Open before the MR": these are not open
    questions — they were decided at gate A — and the person asked for them is the one who
    will run them, so they need the file and the command, not a reason code."""
    task_root = Path(task_root)
    manifest = read_json(task_root / "work" / "automation-manifest.json", {}) or {}
    try:
        import contract
        return contract.handed_tests(manifest)
    except Exception:
        return []


def ticket_gap_line(task_root) -> str:
    """The known gap of a story that went on with the old ticket text, or "".

    `ticket_adapter.py freshness --decline` records, in `work/ticket-freshness.json`, when the
    declined text was read, which requirement fields moved and the person's words; this line is
    built from those fields by code, no wording is read (FR-12). The fields are named in the
    plain words ticket_adapter keeps for them (a person reads this). A decline recorded by an
    older run has no `changed` and gets no line - the remark, if any, still shows."""
    record = read_json(Path(task_root) / "work" / "ticket-freshness.json", {}) or {}
    mark = record.get("declined") if isinstance(record, dict) else None
    if not isinstance(mark, dict) or not mark.get("changed"):
        return ""
    try:
        from ticket_adapter import FIELD_WORDS
    except Exception:
        FIELD_WORDS = {}
    fields = ", ".join(FIELD_WORDS.get(name, str(name).replace("_", " ")) for name in mark["changed"])
    words = " ".join(str(mark.get("words") or "").split())[:200]
    return (f"- Ticket requirements changed on {mark.get('fetched_at') or mark.get('at') or 'an unknown date'} "
            f"({fields}); the person kept the old text: \"{words}\"")


def open_before_mr(task_root, gate: str = "B", carded: tuple = (), shown_questions: tuple = ()) -> list:
    """Everything still open before the MR, as markdown bullets, newest concern first.

    Shared with `external_writes.py`: when the person says "open the MR anyway", these exact
    lines go into the MR description, so what they were shown and what the MR says are the
    same text.

    `shown_questions` are the ids of the readiness questions the packet already shows as a question line of the findings (the
    `carded` precedent, FR-10): they are not listed a second time. The default lists everything, as before."""
    task_root = Path(task_root)
    pipeline = read_json(task_root / "pipeline.json", {}) or {}
    lines: list = []
    unanswered = [q for q in unanswered_questions(task_root, pipeline) if str(q.get("id") or "") not in set(shown_questions)]
    if unanswered:
        _view, unread = register_view(task_root)
        if unread:
            lines.append(f"- question status could not be read ({' '.join(unread.split())[:160]}), so "
                         "every question below is listed as it stands")
    for question in unanswered:
        text = " ".join(str(question.get("question") or "").split())[:200]
        note = " ".join(str(question.get("status_note") or "").split())
        lines.append(f"- unanswered question [{question.get('severity', '?')}, owner "
                     f"{question.get('owner_role', '?')}]: {text}" + (f" - {note}" if note else ""))
    # `Rehearsal.add` already drops what a person's recorded word passed, so a person_decides finding standing
    # here is one nobody has answered; `open_rehearsal_items` is the one reader of that (RH1-6, M2).
    read = open_rehearsal_items(task_root, gate)
    if read["status"] != "read":
        lines.append(f"- the gate rehearsal could not be read ({' '.join(str(read['why']).split())[:160]}), so what it would have asked "
                     "is unknown — that is the factory's own gap, not yours")
    for item in read["items"]:
        lines.append(f"- not decided: {item['message']}")
    gap = ticket_gap_line(task_root)
    if gap:
        lines.append(gap)
    for remark in remarks(task_root):
        lines.append(f"- remark kept, not re-asked{' (' + remark['stage'] + ')' if remark['stage'] else ''}: "
                     + remark["text"][:200])
    for debt in open_debts(task_root, carded):
        lines.append(f"- unresolved: {debt[:200]}")
    return lines


def bug_drafts(task_root: Path) -> list:
    """Every draft S7 left for gate B, in a stable order, each with its file. The files are
    `bug_records.draft_paths` (the one reader of the draft folder); only the parse policy is this one's:
    a draft that is not a JSON object is not listed."""
    import bug_records as BR
    out = []
    for path in BR.draft_paths(task_root):
        data = read_json(path)
        if isinstance(data, dict):
            out.append((path, data))
    return out


# The ids of the packet that have ONE fixed shape. A case id is not among them: its shape is the
# project's (`config.case_id_form`), so it is read by `C.case_ids` beside these, never by a regex
# here (B-013, FR-13/FR-17 - the pattern used to carry the default case form, so a project-form
# case was never named in a gate packet).
ITEM_ID_RE = re.compile(r"\b(?:TS-\d+|R-\d+|BUG-\d+|BD-\d+|OQ-\d+)\b")


def _item_ids(text, cfg) -> list:
    """Every id the packet puts to a person that `text` names: plan rows, requirements, drafts and cases."""
    return ITEM_ID_RE.findall(text) + C.case_ids(text, cfg=cfg)


def packet_items(task_root: Path, gate: str = "A") -> list:
    """The ids the packet puts to a person, so an answer can be read against them.

    A gate decision keeps the person's words whole (`authorization_source`), and that was the
    first half of P3. The second is this: on TP1-15045 the readings the person signed — AC-7,
    400 to 200, TS-10, the toolchain, the credentials, the stand card — travelled into
    `stage_overrides[]` and `state/driver-answers.jsonl` and nothing checked that each item of the
    packet had a record. It worked only because the wording happened to match the cards; an answer
    matching none of them would have been lost in silence.

    Ids, never wording (FR-12): a case, a plan row, a requirement, a draft. What an answer says
    about an item is the person's to mean and the conductor's to read.
    """
    task_root = Path(task_root)
    cfg = C.case_config(task_root)  # this story's project decides what a case id looks like
    found = []
    if str(gate).upper() == "B":
        import bug_records as BR
        for _path, draft in bug_drafts(task_root):
            # the draft's cases are THE reader's (t-2187: a case a merged bug names only in one of its manifestations is still in the packet)
            for item in (draft.get("id"), *BR.draft_cases(draft)):
                found += _item_ids(str(item or ""), cfg)
        for row in undrafted_discrepancies(task_root):
            found += _item_ids(str(row.get("case") or ""), cfg)
        return sorted(dict.fromkeys(found))
    data = collect(task_root.name, task_root)
    found += [str(case) for case in data.get("pinned_cases") or []]
    for question in data.get("open_questions") or []:
        found += _item_ids(json.dumps(question, ensure_ascii=False), cfg)
    for waiver in data.get("gate_waivers") or []:
        found += _item_ids(str(waiver.get("requirement") or ""), cfg)
    for card in data.get("stand_gap_cards") or []:
        found += _item_ids(str(card), cfg)
    for row in (data.get("unearned_automation") or []):
        found += _item_ids(json.dumps(row, ensure_ascii=False) if not isinstance(row, str)
                           else row, cfg)
    return sorted(dict.fromkeys(item for item in found
                                if ITEM_ID_RE.fullmatch(str(item)) or C.is_case_id(str(item), cfg=cfg)))


def attribute(items, answer: str, artifacts=None) -> dict:
    """{"named": [...], "not_named": [...]} for the person's answer against the packet's items.

    `not_named` is not a complaint: a person answers what they choose to answer. It is what the
    factory must PRINT instead of dropping, so nobody later believes an item was settled because
    the decision was recorded (FR-41, and P3's own check). `artifacts` names the story whose
    project decides the case id form; None is the process's own project."""
    said = set(_item_ids(str(answer or ""), C.case_config(artifacts)))
    ordered = [str(item) for item in (items or [])]
    return {"named": [item for item in ordered if item in said],
            "not_named": [item for item in ordered if item not in said]}


def undrafted_discrepancies(task_root: Path) -> list:
    """Cases the manifest says disagree with a requirement and that no draft speaks for.

    One packet may not contradict itself (FR-10). On TP1-15045 gate B opened with "Bugs found
    — none, so there is nothing to file" while the report three screens down carried "its bug
    proposal is unfiled": the role knew about the debt and the code did not, because it counted
    bugs only from the drafts S7 leaves — and the other road to a bug, a requirement the product
    does not deliver, leaves no draft at all (FR-22, still open). Both sections read this now, so
    "nothing to file" is said only when both sources agree.
    """
    manifest = read_json(task_root / "work" / "automation-manifest.json")
    drafted = set()
    import bug_records as BR
    for _path, draft in bug_drafts(task_root):
        # `case`, `cases` and `manifestations[].case` are THE reader's (t-2187): a case covered only by a manifestation is spoken for
        cells = list(BR.draft_cases(draft))
        value = draft.get("case_id")
        cells += list(value if isinstance(value, list) else [value])
        for case in cells:
            if str(case or "").strip():
                drafted.add(C.split_case_key(str(case).strip())[1])
    out = []
    for row in C.manifest_unresolved(manifest if isinstance(manifest, dict) else {}):
        reason = str(row.get("reason") or "")
        if reason not in ("contradicts_requirement", "impossible"):
            continue
        case = C.split_case_key(str(row.get("case") or "").strip())[1]
        if case and case in drafted:
            continue
        out.append({"case": case or "?", "reason": reason,
                    "detail": " ".join(str(row.get("detail") or "").split())[:160]})
    return out


def bug_rows(task_root: Path, config: dict | None = None) -> list:
    """One self-contained row per draft: number, title, priority, the one line, path, duplicate.

    "Impact → priority" is derived, never assigned: `grammar.impact_scale` holds the one
    mapping, and the project may override it in config.json."""
    scale = {}
    try:
        import grammar
        scale = grammar.impact_scale(config if config is not None else {})
    except Exception:
        scale = {}
    rows = []
    import bug_records as BR
    facts = None   # the triage rows and the run report, read once for all the drafts
    texts = {p: t for p, t in BR.draft_text_paths(task_root)}   # the readable text of each draft, written by delivery_summary
    try:   # D1-C2: the OPEN bugs of the story's sources, read once; an unreadable scan verifies no mark (E-C16)
        scan = BR.source_bug_scan(task_root)
        open_keys = {str(b["key"]): b for b in scan["bugs"]}
        scan_notes = [str(n) for n in scan.get("notes") or []]     # E-C3/E-C4: what the scan could not read; said at gate B beside a mark (F6b)
    except Exception:
        open_keys, scan_notes = {}, []
    drafts = bug_drafts(task_root)
    numbers = {}     # a draft's file name and stem -> its number in this packet, so `possibly_same_cause` is said in numbers, never in file names
    for number, (path, _data) in enumerate(drafts, start=1):
        numbers.setdefault(path.name, number)
        numbers.setdefault(path.stem, number)
    for number, (path, data) in enumerate(drafts, start=1):
        if facts is None:
            facts = BR.step_facts(task_root)
        # the step of the bug is THE one reader's (HF8-16, AR-13): the packet, the report and the summary count the same
        word, kinds, problems = BR.confirmation_of(task_root, data, *facts, draft=True)
        impact = str(data.get("impact") or data.get("damage_class") or "").strip()
        priority = str((scale.get(impact) or {}).get("priority") or "")
        duplicate = ""
        for key in DUPLICATE_KEYS:
            if str(data.get(key) or "").strip():
                duplicate = " ".join(str(data[key]).split())[:60]
                break
        # D1-C2 (Q4-e): `extends_open_bug` is the role's mark, believed only when the scan holds that exact key; the summary is the scan's,
        # never the draft's. An unverified mark asks (the old line) - it may err only toward asking (E-C15)
        mark = data.get("extends_open_bug")
        raw_key = mark.get("key") if isinstance(mark, dict) else mark
        mark_key = str(raw_key or "").strip()      # no key (`{"summary": "x"}`, `{"key": null}`, None) is no mark: never the word "None" (F6a)
        extends = {"key": mark_key, "summary": str(open_keys[mark_key].get("summary") or "")} if mark_key in open_keys else None
        if mark_key and extends is None and not duplicate:
            duplicate = mark_key[:60]
        row = {
            "n": number,
            "extends": extends,
            "title": " ".join(str(data.get("title") or path.stem).split())[:110],
            "impact": impact,
            "priority": priority,
            "evidence": _bug_evidence(data),
            "duplicate": duplicate,
            "confirmation": word,
            "reproduced_how": kinds,
            "reproduction_problems": problems,
        }
        if mark_key and scan_notes:
            row["scan_notes"] = scan_notes
        # one bug, many manifestations (t-2187): keys exist only when the draft carries them, so an ordinary bug's row is as before
        ways = BR.manifestation_summary(data)
        if len(ways) >= 2:
            row["manifestations"] = [way[:MANIFESTATION_CLIP] for way in ways]
        mechanism = _mechanism_row(task_root, data)
        if mechanism:
            row["mechanism"] = mechanism
        linked = _linked_rows(data, numbers, number)
        if linked:
            row["possibly_same_cause"] = linked
        if BR.is_code_reading(data):
            # a bug candidate found by reading the code against an oracle, never by a run (t-1676): the packet marks it and shows the
            # oracle's words and the code place, all from the draft's own fields (the checker already held them against their sources)
            oracle, fact = data.get("oracle"), data.get("fact")
            oracle, fact = oracle if isinstance(oracle, dict) else {}, fact if isinstance(fact, dict) else {}
            note = " ".join(str(fact.get("note") or "").split())[:120]
            row.update(code_reading=True, oracle_quote=" ".join(str(oracle.get("quote") or "").split())[:220],
                       oracle_where="your answer at gate A" if oracle.get("question") else "the requirement",
                       fact_where=f"{fact.get('path') or '?'}:{fact.get('line') or '?'}", fact_note=note)
        text = texts.get(path)
        if text is not None and text.is_file():
            row["text"] = portable(text, task_root)   # a readable file only; no text written yet means no path field (HF8-20, I5)
        rows.append(row)
    _symmetric_links(rows)
    return rows


MANIFESTATION_CLIP = 220     # characters of one way-it-shows line in the packet; the readable text of the bug holds it whole


def _mechanism_row(task_root: Path, data: dict) -> dict:
    """What gate B says about a draft's `mechanism` (t-2187), from `bug_records.cause_view` - the one reader of the cause facts the bug text
    and the report print from too (M3): {status, statement, why, how, unverified}; {} for a draft with no `mechanism` object (an old draft
    is never re-litigated). `status` is `confirmed` ONLY when the view says so (the draft says so AND its basis stands: FR-59). `how` is
    `{code_line, runs, person}` - which basis kinds stand and how many distinct start states the runs were tried from. Judges nothing
    about whether the statement is the cause."""
    import bug_records as BR
    view = BR.cause_view(task_root, data)
    if not view:
        return {}
    return {"status": view["status"], "statement": view["statement"][:300], "why": view["why"][:200],
            "how": {"code_line": view["by_code"], "runs": view["runs"], "person": view["by_person"]},
            "unverified": [says[:200] for says in view["unverified"]]}


def _symmetric_links(rows: list) -> None:
    """Make `possibly_same_cause` read the same from both rows of a link (m1): `_linked_rows` shows a link on the row that wrote it, and
    `_linked_groups` takes it from either side, so B shows "Possibly the same cause as A" also when only A names B (the sentence "each
    naming the other" is then true of what the person sees). Mutates the rows; a link to a number that is no row of the packet adds nothing."""
    by_n = {r["n"]: r for r in rows}
    for row in rows:
        for link in list(row.get("possibly_same_cause") or []):
            other = by_n.get(link["n"])
            if other is not None and other is not row and row["n"] not in [x["n"] for x in other.get("possibly_same_cause") or []]:
                other.setdefault("possibly_same_cause", []).append({"n": row["n"], "why": link["why"]})


def _linked_rows(data: dict, numbers: dict, own: int) -> list:
    """`[{"n": <number in this packet>, "why": <one sentence>}]` for the drafts this one names in `possibly_same_cause`; a name that is
    no draft of this packet, or this draft itself, is skipped (a file name is never shown). The other side of a one-way link is added by
    `_symmetric_links` once every row exists."""
    import bug_records as BR
    out = []
    for link in BR.cause_links(data):
        name = link["draft"]
        n = numbers.get(Path(name).name) or numbers.get(Path(name).stem)
        if n and n != own and n not in [x["n"] for x in out]:
            out.append({"n": n, "why": _one_line(link["why"], 200)})
    return out


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".!?" else text + "."


def merged_bug_row_lines(row: dict) -> list:
    """The lines a bug row gets under its head and evidence line (t-2187, spec 8.1): the cause, what is not verified, the ways it shows
    (letters a), b), ... up to `MAX_MANIFESTATIONS_SHOWN`, then how many more), and the drafts it may share a cause with. A bug with one
    manifestation and no mechanism gives []; with one manifestation and a cause that is not established it gives that one line."""
    lines = []
    mech = row.get("mechanism") or {}
    ways = row.get("manifestations") or []
    if mech and mech.get("status") == "unverified":
        # a hypothesis is printed as one, never as the cause and never as confirmed (FR-41, FR-59): its words, then the draft's reason
        lines.append("   " + _sentence("Possible cause, not verified: " + mech["statement"])
                     + (" " + _sentence(mech["why"]) if mech.get("why") else ""))
    elif mech and mech.get("status") != "confirmed":
        # an unknown cause is never printed as a cause (FR-41): what is missing, in the draft's words
        lines.append("   " + _sentence("Cause not established" + (f": {mech['why']}" if mech.get("why") else "")))
    elif mech and len(ways) >= 2:
        import bug_records as BR
        how = BR.cause_how_words({"by_code": mech["how"]["code_line"], "runs": mech["how"]["runs"], "by_person": mech["how"].get("person")})
        lines.append("   " + _sentence("Cause, confirmed" + (" " + how if how else "")
                                       + (": " + mech["statement"] if mech["statement"] else "")))
        lines += [f"   Not verified: {claim.rstrip('.')}." for claim in mech["unverified"]]
    if len(ways) >= 2:
        for letter, way in zip(QUESTION_LETTERS, ways[:MAX_MANIFESTATIONS_SHOWN]):
            lines.append(f"   {letter}) {way}")
        if len(ways) > MAX_MANIFESTATIONS_SHOWN:
            more = len(ways) - MAX_MANIFESTATIONS_SHOWN
            lines.append(f"   (+{more} more" + (", in the bug text)" if row.get("text") else ")"))
    for link in row.get("possibly_same_cause") or []:
        lines.append(f"   Possibly the same cause as {link['n']}" + (f" (not verified: {link['why'].rstrip('.')})." if link["why"] else " (not verified)."))
    return lines


def _linked_groups(rows: list) -> list:
    """Groups of SHOWN rows tied by `possibly_same_cause`, as sorted lists of numbers (t-2187, F-6). A link counts from either side (A names B,
    B need not name A) and chains join (1-2, 2-3 is one group 1 2 3); a link to a draft that is not shown in this packet joins nothing, so
    no `merge` is ever offered for a bug the person cannot see."""
    shown = {r["n"] for r in rows}
    parent = {n: n for n in shown}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    linked = set()
    for row in rows:
        for other in row.get("possibly_same_cause") or []:
            if other["n"] in shown and other["n"] != row["n"]:
                parent[find(row["n"])] = find(other["n"])
                linked.update((row["n"], other["n"]))
    out = {}
    for n in sorted(linked):
        out.setdefault(find(n), []).append(n)
    return sorted(out.values())


def _numbers_in_words(group: list) -> str:
    names = [str(n) for n in group]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def merged_bug_block(rows: list) -> list:
    """ONE question after the list of bugs when some of them were drafted as one bug from several ways it shows, or are linked as possibly
    the same cause (t-2187, human-questions rule 3 and 6): what the factory did, why it cannot decide alone, and the closed answers each with
    the three price lines. `file` and `not a bug` are answers the gate already reads; `split` (these are different bugs) and `merge` (for
    drafts linked as possibly the same cause: they are one bug) are words that ask a change, so no code parses them (FR-12): the conductor
    reads the answer and runs the analyst's rework (skills/qa-story/phases/s8.md). `file`, `split`, `not a bug` are offered for the rows
    with two or more ways it shows only; `merge` for the linked groups only. The intro says "has one cause" only of a row whose cause is
    confirmed (M2); the other merged rows are said as drafted one bug with the cause not confirmed. The linked groups always get both
    `merge` and `file` (keep them apart, each naming the other: the display of a link is symmetric, `_symmetric_links`), in the mixed
    packet too (m2); with no merged row the block has its own intro. [] when there is neither."""
    merged = [r for r in rows if len(r.get("manifestations") or []) >= 2]
    groups = _linked_groups(rows)
    if not merged and not groups:
        return []
    labels = _price_labels()
    rework = ("one more working session of the failure analyst, then the report is rebuilt and this gate is shown again",
              "this answer, and one more look at this gate",
              "nothing stays unverified by this choice; delivery waits until the gate is shown again")
    merge_head = ("or ".join(f"`merge` {' '.join(str(n) for n in g)} " for g in groups).rstrip()
                  + " — they are one bug; draft them together.")      # last, as the spec orders it (F-6)
    options = []
    linked_file = (f"`file` {', '.join(str(n) for g in groups for n in g)} — file them as separate bugs, each naming the other as possibly "
                   "the same cause.",
                   ("nothing beyond filing them", "nothing more",
                    "if one fix does not cure both, nothing is lost: each bug keeps its own checks, and the link tells whoever fixes it to look "
                    "at the other; delivery unchanged"))
    if merged:
        numbers = ", ".join(str(r["n"]) for r in merged)
        # M2: the intro says "has one cause" only of a row whose cause is confirmed and standing (`mechanism.status`); any other merged
        # row (the person waived the rehearsal finding, or its basis stopped standing after S7) is said as drafted one bug, cause not confirmed
        sure = [r for r in merged if (r.get("mechanism") or {}).get("status") == "confirmed"]
        unsure = [r for r in merged if r not in sure]

        def intro_of(group: list, confirmed: bool) -> str:
            if len(group) == 1:
                n, k = group[0]["n"], len(group[0]["manifestations"])
                return (f"The factory found that {n} has one cause behind {k} different-looking problems and drafted it as one bug, so a "
                        "fix is checked against all of them." if confirmed else
                        f"The factory drafted {n} as one bug from {k} different-looking problems, but could not confirm one cause behind "
                        "them; a fix is checked against all of them.")
            named = " and ".join(f"{r['n']} ({len(r['manifestations'])} problems)" for r in group)
            return (f"The factory found that {named} each have one cause behind several different-looking problems and drafted each as one "
                    "bug, so a fix is checked against all of them." if confirmed else
                    f"The factory drafted {named} each as one bug from several different-looking problems, but could not confirm one cause "
                    "behind them; a fix is checked against all of them.")
        intro = " ".join(intro_of(group, flag) for group, flag in ((sure, True), (unsure, False)) if group)
        intro += " It cannot know whether you want them tracked apart. For each such bug:"
        options = [
            (f"`file` {numbers} — file it as one bug listing every way it shows.",
             ("one working session of the bug writer", "nothing more",
              "each way it shows keeps its own test or check; after the fix every one is re-checked, and one still failing becomes its own "
              "bug; delivery unchanged")),
            (f"`split` {numbers} — these are different bugs; draft them apart.", rework),
            (f"`not a bug` {numbers} — do not file it.",
             ("a record only", "nothing more", "the problems stay in the report as found and not filed; delivery unchanged"))]
        if groups:
            options += [(merge_head, rework), linked_file]      # m2: a linked pair in a mixed packet also gets its keep-apart option
    else:
        # linked drafts only: the factory suspects one cause and could not confirm it. `file` is the word gate B already has for
        # "file what is drafted"; here it keeps them apart, each draft already naming the other as possibly the same cause
        suspected = (f"bugs {_numbers_in_words(groups[0])}" if len(groups) == 1
                     else "the bugs in each of these groups: " + "; ".join(_numbers_in_words(g) for g in groups))
        intro = (f"The factory suspects that {suspected} share one cause, but it could not confirm it, so it drafted them as separate bugs. "
                 "It cannot know whether you want them tracked together or apart. For each group:")
        options = [(merge_head, rework), linked_file]
    lines = ["", "## One bug or several", intro]
    for letter, (head, prices) in zip(QUESTION_LETTERS, options):
        lines.append(f"({letter}) {head}")
        lines += [f"{label} {text}." for label, text in zip(labels, prices)]
    return lines


def code_reading_block(rows: list) -> list:
    """ONE question after the list of bugs when some of them were found by reading the code (human-questions rule 3): what the factory did,
    why it cannot decide alone, three closed answers each with the three price lines (rule 6). No parser (FR-12): the answer is read by the
    conductor, and each answer has an executor (FR-9): `file` is the recorded selection, `not needed` leaves it out, `prove by a run` is a
    rework the conductor runs (skills/qa-story/phases/s8.md). [] when none of the rows is one."""
    shown = [r["n"] for r in rows if r.get("code_reading")]
    if not shown:
        return []
    numbers = ", ".join(str(n) for n in shown)
    labels = _price_labels()
    options = (
        ("file", f"(a) `file` {numbers} — file it as a bug.",
         ("one working session of the bug writer", "nothing more",
          "it is filed marked as found by reading the code, not by a run; the delivery word does not change")),
        ("not needed", f"(b) `not needed` {numbers} — do not file it.",
         ("a record only", "nothing more",
          "the requirement stays not proven, and the report names the declined candidate; the delivery word does not change")),
        ("prove", f"(c) `prove` {numbers} `by a run` — check it by running the product before you decide.",
         ("the stages that plan, write and run that check run again, as far back as it needs", "one more look at this gate",
          "the delivery waits until this gate is shown again")))
    lines = ["", "## What each answer costs and does",
             f"The factory read the code against your words or the requirement for {numbers} and found the code disagrees, but no test "
             "ran that check, so it cannot say for sure. It does not decide this alone. For each of them:"]
    for _word, head, prices in options:
        lines.append(head)
        lines += [f"{label} {text}" for label, text in zip(labels, prices)]
    return lines


def _bug_evidence(data: dict) -> str:
    """"What is broken and how to see it" in one line, out of the draft's own fields.

    Never invented: when the draft has neither an actual nor an expected, the line says the
    draft does not carry one, so the person knows to open it rather than trusting a summary."""
    def clean(value, limit=130):
        return " ".join(str(value or "").split())[:limit]

    actual = clean(data.get("actual") or data.get("observed"))
    expected = clean(data.get("expected"), 90)
    steps = data.get("manual_steps") or data.get("steps") or data.get("repro") or []
    step = clean(steps[0] if isinstance(steps, list) and steps else steps, 90)
    if actual and expected:
        return f"{actual} (expected: {expected})" + (f" — {step}" if step else "")
    if actual:
        return actual + (f" — {step}" if step else "")
    if expected:
        return f"expected: {expected}" + (f" — {step}" if step else "")
    return clean(data.get("violates") or "the draft records no expected/actual pair — open it")


def filing_line(task_root: Path, config: dict) -> str:
    """Where the approved bugs go, and whether anything has proved they can get there.

    Read-only: the receipt `tracker_write.py` left, never a fresh probe — a brief that opened a
    network connection would not be a brief.

    An experiment (t-017 D3, FR-36/FR-53) says the channel is closed instead of confirming or
    advertising it: the run's own record decides, before the config is even read."""
    try:
        import external_writes
        closed = external_writes.closed_by_run(task_root)
    except Exception:
        closed = ""  # a reader that cannot load closes nothing; the config line below still holds
    if closed:
        return (f"**Filing** — closed for this run: {closed}; bugs stay as files in this "
                "repository.")
    channel = str((config.get("external_writes") or {}).get("bugs") or "markdown").strip()
    if channel in ("", "markdown", "none", "file"):
        return ("**Filing** — bugs stay in this repository (`external_writes.bugs: markdown`); "
                "nothing is sent to a tracker.")
    receipt = {}
    try:
        import tracker_write
        base = _project_root_of(task_root)
        if base is not None:
            receipt = tracker_write.load_receipt(base)
        state = tracker_write.readiness_line(dict(receipt or {}, channel=receipt.get("channel")
                                                  or channel))
    except Exception:
        state = f"tracker write: not checked — `{channel}`"
    how = ""
    method = ""
    try:
        import external_writes
        delivery = external_writes.channel_delivery(config.get("external_writes") or {}, channel)
        method = str(delivery.get("method") or "")
        if method in getattr(external_writes, "DIRECT_METHODS", ("api", "direct", "direct_api")):
            how = " through the tracker's direct API"
        elif delivery.get("invoke"):
            how = f" through the {method or 'agent'} `{delivery['invoke']}`"
        elif delivery.get("command"):
            how = " through the configured command"
    except Exception:
        pass
    line = f"**Filing** — channel `{channel}`{how}; {state}."
    if method in ("api", "direct", "direct_api"):
        # The one sentence naming the author of a direct-API write, from the SAME
        # cached receipt `state` above already read — never a second live call.
        display = str((receipt.get("author") or {}).get("display_name") or "").strip()
        if display:
            line += f" Bugs and comments will be written to `{channel}` as **{display}**."
    return line


def read_ledger(task_root):
    """The story's `ledger.json` as a dict, or None when it cannot be read (two copies that differ, a damaged file): the ONE
    guarded read of the ledger in this module, shared by `delivery_word` and gate B's review-gaps sections (C1-5c F5)."""
    try:
        return C.load_json(C.artifact(Path(task_root), "ledger.json"))
    except Exception:
        return None


def delivery_word(task_root) -> str:
    """The ledger's verdict word (`yes`, `after_checks`, `no`), read by THE reader; a ledger that is absent, unreadable or
    inconsistent is `no` here - this packet offers an act only on a word that opens it (t-305 N8)."""
    ledger = read_ledger(task_root)
    if ledger is None:
        return "no"
    try:
        import delivery_verdict as DV
        word = DV.word_of(ledger)
    except Exception:
        return "no"
    return word if word in ("yes", "after_checks") else "no"


def render_gate_b(task: str, root: Path | None = None) -> str:
    """The numbered bug list the person answers, and the two documents behind it."""
    task_root = Path(root) if root is not None else artifacts_dir(task)
    config = project_config(task_root)
    rows = bug_rows(task_root, config)
    undrafted = undrafted_discrepancies(task_root)
    lines = [f"# Gate B — {task}", ""]
    from report_facts import exploratory_gate_lines, exploratory_gate_parts
    parts = exploratory_gate_parts(task_root)
    gate = exploratory_gate_lines(task_root, exploratory_answer_block(parts), parts)   # the findings, above the bug headline (FR-10); [] changes no byte
    if gate:
        lines += gate + [""]
    if not rows and not undrafted:
        # the packet never says "nothing to answer" while it offers answers (FR-10): with a question line the clause is dropped
        lines.append("**Bugs found — none.** S7 left no bug drafts, so there is nothing to "
                     "file" + ("" if parts["questions"] else " and nothing to answer here") + ".")
    elif not rows:
        # Ours to say, never a question (FR-3): the drafts are empty and the story still carries
        # a discrepancy with a requirement. The road from "the product does not do this and no
        # test can fail" to a file under `bugs/` is missing (FR-22), and that is our gap.
        lines.append(f"**No bug drafts, and {len(undrafted)} discrepancy(ies) with a requirement "
                     "that nobody drafted.** Nothing is asked of you here: this is the factory's "
                     "own gap — the only road to a bug runs through S7's triage of a failing "
                     "test, and a requirement the product does not deliver produces no failing "
                     "test. The rows, so they are not lost:")
        for row in undrafted[:MAX_BUGS]:
            lines.append(f"- {row['case']} · `{row['reason']}`"
                         + (f" — {row['detail']}" if row["detail"] else ""))
    else:
        from traceability import bug_headline
        lines.append("**" + bug_headline(rows) + "** Answer by number: which to file and which "
                     "is not a bug (\"file 1 and 3; 2 is not a bug\"). A title or a priority you "
                     "want changed, say it in words and it is changed before anything is filed.")
        lines.append("")
        for row in rows[:MAX_BUGS]:
            head = f"{row['n']}. **{row['title']}**"
            if row["impact"] or row["priority"]:
                head += f" — impact `{row['impact'] or 'unstated'}`" \
                        + (f" → {row['priority']}" if row["priority"] else "")
            if row.get("extends"):
                head += (f". Extends the open bug {row['extends']['key']} ({row['extends']['summary'][:60]}) - add this evidence to it "
                         "rather than filing a new bug; name its number only if you want a separate one")
            elif row["duplicate"]:
                head += f". Possibly a duplicate of {row['duplicate']} — your call"
            ways = len(row.get("manifestations") or [])
            if ways >= 2:    # "one cause" only when the cause is confirmed; an unknown cause is never named as one (FR-41)
                head += f" · {'one cause, ' if (row.get('mechanism') or {}).get('status') == 'confirmed' else ''}{ways} ways it shows"
            if row.get("code_reading") and row.get("confirmation") != "reproduced_by_factory":
                head += " · by reading the code, not proven by a run"   # INSTEAD of the reproduction words: no factory test spoke (t-1676); a walk of the analyst may be its receipt (t-1991)
            elif row.get("confirmation") in ("unconfirmed", "reproduced_by_factory"):
                # one sentence for the report, the table legend, this packet and the fragment (bug_records, FR-10)
                import bug_records as BR
                head += " · " + BR.reproduction_words(row)
            lines.append(head + ".")
            lines.append(f"   {row['evidence']}")
            lines += merged_bug_row_lines(row)
            if row.get("code_reading"):
                lines.append(f"   {row['oracle_where']}: \"{row['oracle_quote']}\"; the code: {row['fact_where']}"
                             + (f" - {row['fact_note']}" if row.get("fact_note") else ""))
            if row.get("text"):
                lines.append(f"   {row['text']}")
        if len(rows) > MAX_BUGS:
            lines.append(f"   (+{len(rows) - MAX_BUGS} more bug drafts, listed in the delivery summary)")
        notes = list(dict.fromkeys(n for row in rows[:MAX_BUGS] for n in row.get("scan_notes") or []))
        if notes:      # a draft carries a mark the scan could not check (E-C3/E-C4): said, so "your call" is not read as a verified duplicate
            lines.append("Note: " + "; ".join(notes))
        lines += code_reading_block(rows[:MAX_BUGS])      # the numbers of the shown rows only (E-26)
        lines += merged_bug_block(rows[:MAX_BUGS])        # t-2187: the door of a bug drafted from several ways it shows; [] changes no byte
        if undrafted:
            # The same fact, in the packet that has drafts too: a list of drafts a person answers
            # must not read as the whole of what this story found (FR-10).
            lines.append("")
            lines.append(f"Beside them, {len(undrafted)} discrepancy(ies) with a requirement that "
                         "no draft speaks for — the factory's own gap, nothing asked of you: "
                         + ", ".join(f"{row['case']} (`{row['reason']}`)" for row in undrafted[:8]))
    # C1-5c: the tests the code critic rejected whose window closed at its repair limit - what the critic asked, in the report's
    # own renderer (`report_facts.review_gap_lines`, imported, never copied: FR-10). Nothing to list, no section; the person
    # answers on the bugs, and this is what they hold besides.
    # A ledger that cannot be read is said, never read as "nothing rejected" (FR-41): the guarded read is `read_ledger`.
    from report_facts import gate_b_gap_lines
    ledger = read_ledger(task_root)
    lines += gate_b_gap_lines(ledger if ledger is not None else {"repair_windows_problem": "the ledger cannot be read"})
    lines.append("")
    lines.append(filing_line(task_root, config))
    size = sizing_line(task_root)
    if size:
        lines.append(size)
    handed = handed_runs(task_root)
    if handed:
        lines.append("")
        lines.append(f"## Run these yourself ({len(handed)})")
        lines.append("Nothing in my session could launch them, and you said you would run them. "
                     "The code is written and reviewed; I am not waiting for any result.")
        for row in handed[:MAX_OPEN_BEFORE_MR]:
            lines.append(f"- {row.get('case') or '?'}: "
                         + (str(row.get('detail') or row.get('what') or '')[:200]
                            or "no command recorded — that is my gap, not yours"))
        if len(handed) > MAX_OPEN_BEFORE_MR:
            # words, not a command: a script name in the body of a question is jargon (human-questions.md, rule 5)
            lines.append(f"- (+{len(handed) - MAX_OPEN_BEFORE_MR} more; the delivery summary below lists them all)")
    cards, carded = stand_gap_cards(task_root, "B")
    if cards:
        lines.append("")
        lines.extend(cards)
    # the questions the packet shows AND the ones it names as left open by the person are listed once, not again as unanswered (FR-10)
    still_open = open_before_mr(task_root, "B", tuple(carded), tuple(q["qid"] for q in parts["questions"] if q.get("qid"))
                                + tuple(parts.get("left_open_qids") or ()))
    if still_open:
        # An experiment opens no merge request (t-017 D3, FR-36/FR-9/FR-10): the list stays - what
        # is open is still open - but it is not titled "before the MR" and does not offer to put
        # itself into one. Same reader of the run's record as the filing line above.
        try:
            import external_writes
            experiment = bool(external_writes.closed_by_run(task_root))
        except Exception:
            experiment = False
        lines.append("")
        lines.append(f"## Open items ({len(still_open)})" if experiment
                     else f"## Open before the MR ({len(still_open)})")
        lines.extend(still_open[:MAX_OPEN_BEFORE_MR])
        if len(still_open) > MAX_OPEN_BEFORE_MR:
            lines.append(f"- (+{len(still_open) - MAX_OPEN_BEFORE_MR} more of the same kinds, not listed here)")
        # t-305 N8 (R6, E13): the packet never offers an act the guard will refuse. The MR is offered on `yes` and on
        # `after_checks` (its description then carries what is left with the person); on `no` the only item is
        # "deliver with known gaps", which needs its reason. A bug is NOT on that road since t-1547 (GB-2, owner 28.10.2026):
        # the reporter is opened by the recorded gate B decision (the drafts the person chose), whatever the verdict says.
        word = delivery_word(task_root)
        if experiment:
            lines.append("None of this blocks you: answer what you want answered.")
        elif word in ("yes", "after_checks"):
            lines.append("None of this blocks you: answer what you want answered, or say \"open the "
                         "MR anyway\" and this list goes into the MR description as it stands"
                         + (", with what is left with you." if word == "after_checks" else "."))
        else:
            form = risk_form()
            lines.append("None of this blocks you: answer what you want answered. The checks do not say the "
                         "delivery is ready, so no MR is offered; to open one, "
                         + (form + "." if form else "say \"deliver with known gaps\" and give your reason."))
    judged = judge_lines(judge_facts(task, task_root))
    if judged:
        lines.append("")
        lines.extend(judged)
    # The screenshots of the manual checks are the person's to confirm the cases (the owner's word 31.10.2026): their paths are
    # printed HERE, by code, on both roads (the driver pastes this brief into its packet, the skill road quotes it), and nowhere in
    # a delivered file. `report_facts.screenshot_groups` is the one list the report's `screenshots: provided` is computed from.
    # No picture: no section, and nothing is promised (the report says `not provided`).
    from report_facts import screenshot_section
    shots = screenshot_section(task_root)
    if shots:
        lines.append("")
        lines.extend(shots)
    lines.append("")
    lines.append("## The long documents (paths, not summaries)")
    summary_text = task_root / "work" / "delivery-summary.md"   # the readable file; the JSON beside it is the factory's (HF8-20, I5)
    lines.append(f"- delivery summary: {portable(summary_text, task_root)}" if summary_text.is_file()
                 else "- delivery summary: the delivery summary is not written yet")
    lines.append(f"- test report: {portable(task_root / 'test-report.md', task_root)}")
    import brief_pack          # t-1884 M-2: the scribe's form (its `tried` table) is read here, by the person at gate B
    scribe_form = brief_pack.last_accepted_form(task_root, "S8", "qa-doc-scribe")
    if scribe_form:
        lines.append(f"- the scribe's form (what it tried): {portable(task_root / scribe_form, task_root)}")
    return "\n".join(lines) + "\n"


def selftest() -> int:
    import tempfile
    failures: list = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    rows = [{"level": "e2e-ui", "disposition": "automate"},
            {"level": "e2e-ui", "disposition": "automate"},
            {"level": "api", "disposition": "manual-human"}]
    pyr = pyramid(rows)
    case("the pyramid counts rows", pyr["total"], 3)
    case("by level", pyr["by_level"], {"e2e-ui": 2, "api": 1})
    case("by disposition", pyr["by_disposition"], {"automate": 2, "manual-human": 1})
    case("a row with no level is counted, not dropped",
         pyramid([{"disposition": "automate"}])["by_level"], {"unstated": 1})

    with tempfile.TemporaryDirectory(prefix="qa-gate-brief-") as td:
        task_root = Path(td) / "TP1-1"
        (task_root / "work" / "test-cases" / "wf").mkdir(parents=True)
        (task_root / "state").mkdir(parents=True)
        (task_root / "work" / "test-plan.json").write_text(json.dumps(rows), encoding="utf-8")
        (task_root / "work" / "test-cases" / "wf" / "critic-findings.md").write_text(
            "Verdict: approve_with_concerns (2 concerns)\n\n"
            "## Roll-call\n\n"
            "| TS | case | reviewed | status |\n|---|---|---|---|\n"
            "| TS-1 | TC-001 | yes | found |\n"
            "| TS-2 | TC-002 | no | found, not read yet |\n", encoding="utf-8")
        (task_root / "state" / "story-case-links.json").write_text(json.dumps(
            {"links": [{"case_id": "TC-001"}, {"case_id": "TC-002"}]}), encoding="utf-8")
        (task_root / "pipeline.json").write_text(json.dumps(
            {"ticket": "TP1-1", "warnings": ["case_store not_configured"],
             "gate_waivers": [{"gate": "A", "requirement": "R-9", "decision": "scope is enough"}],
             "stage_overrides": [{"stage": "S1", "match": "video", "decision": "go on without it"}]}),
            encoding="utf-8")
        (task_root / "work" / "requirements-readiness.json").write_text(json.dumps(
            {"open_questions": [{"question": "where does a removed node go?",
                                 "severity": "minor", "owner_role": "po_ba"}]}), encoding="utf-8")
        data = collect("TP1-1", task_root)
        case("the verdict is read", data["critic_verdict"], "approve_with_concerns")
        case("the unreviewed rows are named", data["roll_call"]["unreviewed"], ["TS-2 (TC-002)"])
        # And the same table without its `reviewed` column says nothing about its rows: the
        # brief prints that, where it used to read the status cell's wording (FR-12, FR-41).
        no_column = (task_root / "work" / "test-cases" / "wf" / "critic-findings.md")
        kept = no_column.read_text(encoding="utf-8")
        no_column.write_text(kept.replace(" reviewed |", " seen |").replace(" yes | found |", " y | found |"),
                             encoding="utf-8")
        unstated = roll_call(task_root, critic_path(task_root))
        case("a table with no `reviewed` column states nothing", unstated["unreviewed"], [])
        case("and says so by name", unstated["unstated"], ["TS-1 (TC-001)", "TS-2 (TC-002)"])
        case("the brief prints the word instead of the reassurance",
             "no `reviewed` column" in render(dict(data, roll_call=unstated)), True)
        no_column.write_text(kept, encoding="utf-8")
        case("pinned cases are counted", len(data["pinned_cases"]), 2)
        case("the person's earlier decisions are carried",
             len(data["gate_waivers"]) + len(data["stage_overrides"]), 2)
        text = render(data)
        case("the brief fits the cap", len(text.splitlines()) <= MAX_LINES, True)
        case("it shows the pyramid", "e2e-ui/automate 2" in text, True)
        case("it repeats what the person already decided",
             "Already decided by you" in text, True)
        case("it names the open question", "removed node" in text, True)
        # FB-19: one line says the critic's word per plan row as gate A reads it; none without controller state.
        case("no controller state, no per-row line", "as gate A reads it" in text, False)
        case("and no rows collected", data["gate_reviews"], [])
        rowwise = render(dict(data, gate_reviews=[{"plan_row": "TS-1", "verdict": "accepted"},
                                                  {"plan_row": "TS-2", "verdict": "reject"}]))
        case("a refused row is named with the critic's word, the rest counted",
             "(as gate A reads it)** — TS-2 reject; 1 accepted." in rowwise, True)
        case("all rows accepted is said once",
             "(as gate A reads it)** — all 1 accepted." in render(dict(
                 data, gate_reviews=[{"plan_row": "TS-1", "verdict": "accepted"}])), True)
        many = next(line for line in render(dict(data, gate_reviews=[
            {"plan_row": f"TS-{n}", "verdict": "reject", "basis": "column"} for n in range(1, 11)]
            + [{"plan_row": "TS-99", "verdict": "accepted", "no_critic": True}])).splitlines() if "as gate A reads it" in line)
        case("rows past the eighth are counted, and a row no case critic reviewed is not counted as accepted",
             "TS-8 reject and 2 more; 1 with no case critic review." in many, True)
        case("the reason is worded for the person: plain words, no dispatch id",
             "First reason (TS-1): the critic's own word for a case of the row is reject." in many
             and "dispatch" not in many, True)
        case("it links the findings rather than quoting them",
             "critic-findings.md" in text, True)
        # judge.provider is none here, as in every project that never configured one: the
        # brief must then read exactly as it did before the judge existed.
        case("no judge configured, no Judge block", "## Judge" in text, False)
        case("and no judge facts collected", data["judge"], {})

        # A machine-readable roll-call, when the case critic writes one, wins.
        (task_root / "work" / "test-cases" / "wf" / "critic-roll-call.json").write_text(
            json.dumps({"rows": [{"case": "TC-001", "reviewed": True},
                                 {"case": "TC-002", "reviewed": False},
                                 {"case": "TC-003", "reviewed": False}]}), encoding="utf-8")
        case("the machine-readable roll-call is preferred when present",
             collect("TP1-1", task_root)["roll_call"]["unreviewed"], ["TC-002", "TC-003"])

    with tempfile.TemporaryDirectory(prefix="qa-gate-brief-bare-") as td:
        bare = Path(td) / "TP1-2"
        bare.mkdir(parents=True)
        data = collect("TP1-2", bare)
        text = render(data)
        case("a story with nothing on disk still produces a brief", bool(text.strip()), True)
        case("and says what it could not read", "Not readable by this brief" in text, True)

    if failures:
        print("GATE_BRIEF SELFTEST: VIOLATIONS")
        for f in failures:
            print("  - " + f)
        return 1
    print("GATE_BRIEF SELFTEST: no violations (pyramid, verdict, roll-call, decisions, cap)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--task", default="")
    ap.add_argument("--gate", default="A", choices=["A", "B"])
    ap.add_argument("--output", default="", help="write the brief to this path as well")
    ap.add_argument("--json", action="store_true", help="print the collected facts instead")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.task:
        print("gate_brief.py: --task is required", file=sys.stderr)
        return 2
    require_project("gate_brief")
    if args.gate == "B":
        if args.json:
            task_root = artifacts_dir(args.task)
            text = json.dumps({"task": args.task, "gate": "B",
                               "bugs": bug_rows(task_root, project_config(task_root)),
                               "open_before_mr": open_before_mr(task_root)},
                              indent=2, ensure_ascii=False)
        else:
            text = render_gate_b(args.task)
    else:
        data = collect(args.task)
        text = json.dumps(data, indent=2, ensure_ascii=False) if args.json else render(data)
    print(text)
    if args.gate == "A" and not args.json and os.environ.get(RUN_MODE_ENV, "").strip() != "driver":
        # the skill path: this print is the moment gate A reaches the person; the driver keeps its own record (`Driver.gate`)
        try:
            keep_shown_attachments(artifacts_dir(args.task))
        except Exception as exc:  # noqa: BLE001 - no record is a debt, never a refused gate
            print(f"gate_brief: could not keep the list of shown attachments: {exc}", file=sys.stderr)
        # RN1-4: the message the person reads is this file, printed whole by the conductor. The driver (the branch above) never
        # gets here: `story_run.py` runs with QA_FACTORY_RUN_MODE=driver, shows the packet itself (`Driver.gate`) and writes no file.
        try:
            import session_identity
            session = session_identity.resolve(script="gate_brief.py").get("session_id") or ""
            write_gate_message(artifacts_dir(args.task), text, session)
        except OSError as exc:
            print(f"gate_brief: could not write the gate A message file: {exc}; print the brief above whole instead", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001 - no session or no folder: no record, never a refused gate
            print(f"gate_brief: could not record the gate A message: {exc}", file=sys.stderr)
    if args.output:
        try:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        except Exception as exc:
            print(f"gate_brief: could not write {args.output}: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
