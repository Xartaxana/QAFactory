"""The case critic's verdict, computed from its own roll-call by code.

TP1-15045: `critic-findings.md` marked seven of fifteen rows "found (not semantically
reviewed)" in BOTH rounds, and the verdict line still read `approve_with_concerns` next to
"15 cases pinned". Nothing read that table, so the words "approve" and "15" reached Gate A
as if they covered the whole set. They are read here: an unreviewed row is a failed review,
not a note, so the verdict a roll-call of that shape computes is `partial`, the digest has to
carry "N of M reviewed", and the unreviewed ids have to be named for Gate A.

The second half of this file is the `approve_with_fixes` path. In round 2 the critic
asked for TC-014's Then 3 to be narrowed to "401 or 403" - a one-line replacement, with the
exact wording supplied - and it was not applied "because no repair round was left". The repair
cap exists to stop review LOOPS, not to swallow a finished sentence. A concern of the last
round that comes with an exact replacement is applied by CODE (`apply_fixes` below) —
no designer dispatch, the shape that stayed blocked on TP1-15045. It edits the
authoring case file, re-pins a new version, and verifies the replacement landed; anything
0/2+-way ambiguous stays a Gate A debt with an owner, exactly as an untouched fix already does
in `findings_errors`. This mirrors `approved_with_fixes` / `fix_notes[]`, which 0.4.0
introduced for exactly this shape of finding in code review.

    critic_rollcall.py                       # detector: the running story's findings files
    critic_rollcall.py <critic-findings.md>  # one file
    critic_rollcall.py <file> --task-root <TASK_ROOT>    # also check the fixes landed
    critic_rollcall.py --apply-fixes --task-root <TASK_ROOT> [<file> ...] [--store <S>]
        # write each exact replacement into its case file, re-pin, verify; JSON out,
        # default store `case_versions.store_root()` — the one default both CLIs share
"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import detector_verdict as DV  # noqa: E402  (`unreadable_line`, `EXIT_UNREADABLE`: a detector that could not run, RH1-5)
from detector_verdict import named, one_line  # noqa: E402  (a finding is one physical line in a detector's output)
from person_words import WHOLE_PART, door  # noqa: E402
from hooklib import sorted_paths  # noqa: E402

# The closed verdict list of the case critic. `partial` is what an incomplete roll-call
# computes to; `approve_with_fixes` carries the last round's exact replacements.
CASE_CRITIC_VERDICTS = ("approve", "approve_with_fixes", "approve_with_concerns", "partial", "reject")
APPROVING_VERDICTS = ("approve", "approve_with_fixes", "approve_with_concerns")

ROLLCALL_HEADING = "## Roll-call"
FIXES_HEADING = "## Fixes without a new round"
DEBTS_HEADING = "## Gate A debts"
GATE_A_LINE = "Unreviewed for Gate A:"

# TQ1-27: the S4 case critic answers duplicates and level. Closed words in code beside CASE_CRITIC_VERDICTS (a queued item moves the
# case critic's closed words to data together); `test_ahead_cards.VOCABULARIES` pins the card to them.
MERGE_HEADING = "## Merge candidates"
MERGE_COLUMNS = ("cases", "verdict", "reason")
MERGE_VERDICTS = ("merge", "keep")
KEEP_GROUNDS = ("P16", "P19")
PARAMETRISE_TOKEN = "parametrise into one test:"
LEVEL_TOKEN = "lower level:"
LEVEL_IMPOSSIBLE = "impossible"
BUDGET_LINE = "Over the plan case budget:"
MERGE_ROW_FORM = "| TC-a, TC-b | merge or keep | P16: <why> / P19: <why> / <what the merged test keeps> |"

VERDICT_RE = re.compile(r"(?im)^\s*verdict[^:\n]*:\s*`?([a-z_]+)`?")
DIGEST_RE = re.compile(r"\b(\d+)\s+of\s+(\d+)\s+reviewed\b")
# The cell values of the `reviewed` column that mean yes. Everything else in that column means
# no, and a table with no such column says NOTHING about a row - `reviewed: None`, never `True`.
# Until 0.7.19 a phrase list (`not reviewed|unreviewed|not read`) was run over the whole row
# instead, so a critic who worded the cell differently was counted as having reviewed the row and
# an `approve` over unreviewed cases passed (factory rule FR-12; the fourth site it names).
REVIEWED_YES = ("yes", "y", "true", "done")
UNSTATED = "no `reviewed` column"
FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)


def _section(text: str, heading: str) -> str:
    """The body under `heading`, up to the next `## ` heading. Empty when it is absent."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(heading):
            body = []
            for following in lines[i + 1:]:
                if following.strip().startswith("## "):
                    break
                body.append(following)
            return "\n".join(body)
    return ""


def parse_rollcall(text: str, artifacts=None) -> list:
    """[{'plan_row', 'case', 'reviewed': True|False|None, 'cell', 'ids', 'verdict', 'note', 'fix'}] from the `## Roll-call` table
    (`fix` is the cell of a column headed exactly `fix`, the critic's own fix for the row; '' when there is none).

    `reviewed is None` is a third answer, not a missing one: the table has no `reviewed` column,
    so nothing in it says whether the row was read. A reader that treats it as `True` approves
    over cases nobody reviewed, and that is what happened while the column was read out of the
    row's prose.

    `ids` is EVERY case id of the row's `case` cell (CX1-12: `case` stays the first id of the whole row, as
    its readers have it; `[]` when the table has no `case` column - a row then names no case), `verdict` the
    word of the column headed exactly `verdict` (lower case, backticks off), or None when there is no such
    column: no word was written, which is not the same as an empty word.

    The case of a row is the first case id its cells name, in the project's own id form
    (`config.case_id_form`, then `TC-NNN`): this used to carry a regex of its own for the default
    form, so a project-form roll-call read every row as having no case (B-013, FR-17). `artifacts` names the
    story whose project decides; None is the process's own project."""
    import contract as C
    raw = C.md_table(text, ROLLCALL_HEADING)
    if not raw:
        return []
    cfg = C.case_config(artifacts)
    header = [cell.strip().lower() for cell in raw[0]]
    reviewed_at = next((i for i, name in enumerate(header) if "reviewed" in name), None)
    bare = [name.strip("`") for name in header]
    case_at = next((i for i, name in enumerate(bare) if name.startswith("case")), None)
    verdict_at = next((i for i, name in enumerate(bare) if name == "verdict"), None)
    note_at = next((i for i, name in enumerate(bare) if name == "note"), None)
    fix_at = next((i for i, name in enumerate(bare) if name == "fix"), None)
    rows = []
    for cells in raw[1:]:
        if not cells or not any(cells):
            continue
        joined = " | ".join(cells)
        case = next(iter(C.case_ids(joined, cfg=cfg)), "")
        ids = C.case_ids(cells[case_at], cfg=cfg) if case_at is not None and case_at < len(cells) else []
        verdict = (None if verdict_at is None else
                   cells[verdict_at].strip().strip("`").lower() if verdict_at < len(cells) else "")
        plan_row = cells[0].strip()
        if reviewed_at is not None and reviewed_at < len(cells):
            value = cells[reviewed_at].strip().lower().strip("`")
            reviewed = value in REVIEWED_YES
            cell = cells[reviewed_at].strip()
        else:
            reviewed = None
            cell = cells[-1].strip()
        note = cells[note_at].strip() if note_at is not None and note_at < len(cells) else ""
        fix = cells[fix_at].strip() if fix_at is not None and fix_at < len(cells) else ""
        rows.append({"plan_row": plan_row, "case": case, "reviewed": reviewed, "cell": cell,
                     "ids": ids, "verdict": verdict, "note": note, "fix": fix})
    return rows


def parse_fixes(text: str) -> list:
    """The fenced JSON array under `## Fixes without a new round`, or []."""
    body = _section(text, FIXES_HEADING)
    match = FENCE_RE.search(body)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except Exception:
        return [{"__unreadable__": True}]
    if isinstance(data, dict):
        data = data.get("fixes") or []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def declared_verdict(text: str) -> str:
    """The latest round's verdict. Rounds are prepended, so the first line found is the last
    round - the same order the critic's own charter prescribes."""
    match = VERDICT_RE.search(text)
    return match.group(1) if match else ""


def _receipt_offset(data: bytes, sha256: str, memo=None):
    """The line-start offset in `data` from which the bytes measure to `sha256`, or None when none does.

    Rounds are PREPENDED to one `critic-findings.md` and the bytes of earlier rounds are never edited, so the
    file a critic's receipt hashed is always a SUFFIX of today's file, beginning at a line start (measured on
    three real two-round stories: from a `Verdict:` line 0 of 3 matched, from any line start 2 of 3). Only
    bytes the receipt measured are ever read; a file edited past that point matches nothing (I3, FR-59)."""
    want = str(sha256 or "").strip().lower()
    if not want or not data:
        return None
    key = (want, hashlib.sha256(data).hexdigest())
    if memo is not None and key in memo:
        return memo[key]
    found, offset = None, 0
    while offset < len(data):
        if hashlib.sha256(data[offset:]).hexdigest() == want:
            found = offset
            break
        newline = data.find(b"\n", offset)
        if newline < 0:
            break
        offset = newline + 1
    if memo is not None:
        memo[key] = found
    return found


FENCE_OPEN_RE = re.compile(r"\s*(`{3,}|~{3,})")


def _header_cut(lines: list, plain=frozenset()) -> tuple:
    """`(cut, unclosed)`: the index of the first line that starts an OLDER round (a `# ` heading in column 0,
    outside a code fence, after the text's own first non-blank line), and the index of a fence opener still open
    at the end (None when every fence closed). A fence closes only on a line of its own marker character, at
    least as long (a `~~~` line inside a ``` fence is text); the openers in `plain` are read as text."""
    started, fence, opened_at = False, "", None
    for at, line in enumerate(lines):
        bare = line.strip()
        if fence:
            if bare and set(bare) == {fence[0]} and len(bare) >= len(fence):
                fence = ""
            continue
        mark = FENCE_OPEN_RE.match(line)
        if mark and at not in plain:
            fence, opened_at = mark.group(1), at
        elif line.startswith("# ") and started:
            return at, None
        started = started or bool(bare)
    return None, (opened_at if fence else None)


def _round_slice(text: str) -> str:
    """The FIRST round of `text`: from its start to the next round header or the end.

    A round header is a level-1 heading (`# ` in column 0, outside a code fence); a round's own sections use
    `##` (the critic's card says so; every real findings file starts a round with `# Critic findings ... round
    N ...`, measured on cmp3, cmp3gb, driver2). The text opens with its own round, so its own header, when it
    is the first thing in the text, does not end it; text that holds something before its first header has no
    header of its own, so that header is the NEXT (older) round's. A fence that never closes hides nothing:
    an unclosed fence in the newest round never carries the older rounds into it. The caller has already cut
    the text at the next-older receipt (`scoped_verdict`), which holds whether or not a header is there."""
    lines = text.splitlines(keepends=True)
    plain = set()
    while True:
        cut, unclosed = _header_cut(lines, plain)
        if cut is not None:
            return "".join(lines[:cut])
        if unclosed is None:
            return text
        plain.add(unclosed)


def _row_outcome(case: str, row: dict, declared: str = "") -> tuple:
    """`(word, basis, reason)`: one roll-call row's outcome for `case`, where it came from, and why it is not
    `accepted` (`''` when it is). `word` is `accepted`, `reject`, `partial` or the round's own unknown word.

    A row not marked reviewed on ITS OWN line is `partial` (`no_review`): `reviewed: yes` alone approves
    nothing, and nothing approves without it. The word is the row's `verdict` cell (`column`); a cell outside
    `CASE_CRITIC_VERDICTS` (empty included) is a word gate A cannot read (`unreadable`, `partial`). A table with
    NO `verdict` column (`row['verdict']` is None: every receipt written before the column existed) gives the row
    the round's own `declared` word (`round_word`) - what the critic wrote, never one it did not (FR-35)."""
    if not row["reviewed"]:
        return "partial", "no_review", f"the roll-call does not mark {case} as reviewed"
    if row["verdict"] is None:
        word = "accepted" if declared in APPROVING_VERDICTS else declared
        return word, "round_word", ("" if word == "accepted" else
                                    f"no per-case verdict for {case} (the roll-call has no `verdict` column); "
                                    f"the round's word is {declared!r}")
    if row["verdict"] in APPROVING_VERDICTS:
        return "accepted", "column", ""
    if row["verdict"] in CASE_CRITIC_VERDICTS:
        return row["verdict"], "column", f"the roll-call's verdict for {case} is {row['verdict']!r}"
    return "partial", "unreadable", (f"the roll-call's verdict for {case} is {row['verdict']!r}, "
                                     "which is no word of the critic's list")


def _receipt_round(data: bytes, sha256: str, receipts=(), memo=None) -> tuple:
    """`(text, doubt)`: the ONE round a receipt measured, or `("", (basis, reason))` when it cannot be told (AR-13: the cut of
    `scoped_verdict` and of `carried_concerns` is this one). `doubt` is `receipt_mismatch` (no end of the file matches the
    receipt), `unreadable` (the receipt carries no hash) or `two_rollcalls`; the text is cut where the next-older receipt's
    suffix begins or at the next round header (`_round_slice`)."""
    start = _receipt_offset(data, sha256, memo)
    if start is None:
        measured = str(sha256 or "").strip().lower()
        return "", (("receipt_mismatch", f"no end of the file matches the receipt (sha256 {measured[:12]}): "
                                         "a round was edited after its review was accepted (a new round goes "
                                         "on top, earlier rounds are never edited)") if measured else
                    ("unreadable", "the receipt carries no sha256 of the file, so it measured nothing"))
    ends = [offset for offset in (_receipt_offset(data, other, memo) for other in receipts or ())
            if offset is not None and offset > start]
    text = _round_slice(data[start:min(ends, default=len(data))].decode("utf-8", errors="replace"))
    if sum(line.strip().startswith(ROLLCALL_HEADING) for line in text.splitlines()) > 1:
        return "", ("two_rollcalls", "two roll-calls in one round: where this round ends cannot be told")
    return text, None


def _round_word_rule(rows: list, declared: str):
    """`(basis, reason)` when the round says `reject` and no case of it fails, else None (HF4-11).

    The critic's rule (step 4 of its card): `reject` is a failing case; a round with concerns and no `fail` is
    `approve_with_concerns`, and its concerns travel to the automator. A round that declares `reject` over a table whose
    EVERY row is reviewed and carries an approving `verdict` cell contradicts that rule. Code does not settle it: the word
    is the critic's (FR-35) and is NOT rewritten to `approve_with_concerns`; the round is `partial` (the caller returns it),
    with the one door that mends it - the critic writes a new round on top with the `Verdict:` line it earns (earlier rounds
    are never edited, the receipt matches the end of the file).

    None when the word is not `reject`, the table has no `verdict` column (a row then has no word of its own, the round's
    word stands: nothing contradicts it), or any row is unreviewed, has a word outside the approving ones, or says `reject`
    (a failing case: `reject` always; an unreadable cell: the caller's older rules decide, `partial` at best). The error
    direction is one way: a doubt is never `accepted`."""
    if declared != "reject" or not rows:
        return None
    if any(row.get("verdict") is None or row.get("reviewed") is not True or row["verdict"] not in APPROVING_VERDICTS
           for row in rows):
        return None
    return ("round_word_rule", "the round says `reject`, and no case of it fails: by the rule a round without a failing "
                               "case is `approve_with_concerns`; rewrite the `Verdict:` line (a new round on top of the "
                               "file, earlier rounds are never edited)")


def scoped_verdict(data: bytes, sha256: str, cases, artifacts=None, area: str = "", memo=None, why=None,
                   receipts=()) -> tuple:
    """`(word, listed)`: what ONE critic receipt says about `cases`, and which of them its roll-call names.

    FB-19. `data` is today's `critic-findings.md`, `sha256` the receipt's hash of it, `area` the folder under
    `test-cases/` the file sits in (a bare id of the roll-call is read in that area, `contract.case_matches`),
    `receipts` the hashes of the OTHER receipts of the same file. `word` is `accepted`, `reject`, `partial`
    or the round's own unknown word over the LISTED cases, `''` when it lists none of them; a case the roll-call
    does not name is the caller's gap (it stays in `cases - listed`). Never raises: a doubt is `partial`, never
    `accepted` (I1, FR-59). A list passed as `why` gets one `(basis, reason)` per reason the word is not
    `accepted`, the one that decided the word first; `basis` is what code branches on (`column`, `round_word`,
    `no_review`, `unreadable`, `receipt_mismatch`, `two_rollcalls`), `reason` is prose in the critic's own terms.

    Rules: the receipt's bytes must be a line-start suffix of the file (else every case is `partial`), and ONLY
    the first round of that suffix is read: the text ends where the next-older receipt's suffix begins (the
    receipts are where rounds really end) or at the next round header (`_round_slice`), whichever comes first,
    and a slice that still holds two `## Roll-call` headings cannot tell where its round ends (`partial`). The
    cell word is read from the `verdict` column, on a row with `reviewed: yes`; a table with NO such column gives
    each row the round's own declared word (the prose of `note` is never read for a word, FR-12). A case on
    several rows takes the strictest word (`reject` over the rest, `accepted` only when all are); a declared
    round verdict that refuses beside approving cells only is kept (an unexplained overall rejection is never read
    as approval, FR-35), and an unknown declared word is kept as it is."""
    why = why if why is not None else []
    try:
        wanted = sorted({str(case) for case in cases})
    except Exception:
        return "partial", set()
    if not wanted:
        return "partial", set()
    try:
        import contract as C
        cfg = C.case_config(artifacts)
        text, doubt = _receipt_round(data, sha256, receipts, memo)
        if doubt:
            why.append(doubt)
            return "partial", set(wanted)
        rows = parse_rollcall(text, artifacts)
        if not rows:
            why.append(("unreadable", "the round has no roll-call table"))
            return "partial", set(wanted)
        declared = (declared_verdict(text) or "").lower()
        listed, hits = set(), []
        for want in wanted:
            found = [row for row in rows if any(C.case_matches(want, one, area, cfg=cfg) for one in row["ids"])]
            if found:
                listed.add(want)
                hits.extend((want, row) for row in found)
        if not listed:
            return "", set()
        if not declared:
            why.append(("unreadable", "the round declares no `Verdict:` line"))
            return "partial", listed
        if declared not in CASE_CRITIC_VERDICTS:
            why.append(("round_word", f"the round declares {declared!r}, which is no word of the critic's list"))
            return declared, listed
        if declared not in APPROVING_VERDICTS and all(_row_outcome("", row, declared)[0] == "accepted"
                                                       for row in rows):
            rule = _round_word_rule(rows, declared)
            if rule:     # the role's word is not rewritten (FR-35): the round is not read, and the critic is told how to mend it
                why.append(rule)
                return "partial", listed
            why.append(("round_word", f"the round's word is {declared!r}"))
            return declared, listed
        outcomes = [_row_outcome(want, row, declared) for want, row in hits]
        words = [outcome[0] for outcome in outcomes]
        word = "reject" if "reject" in words else "accepted" if all(w == "accepted" for w in words) else "partial"
        if word != "accepted":
            deciding = words.index(word)   # the reason of the word that decided goes first: its basis is the row's
            why.append(outcomes[deciding][1:])
            why.extend((basis, reason) for at, (w, basis, reason) in enumerate(outcomes)
                       if w != "accepted" and at != deciding)
        return word, listed
    except Exception:
        why.append(("unreadable", "its roll-call could not be read"))
        return "partial", set(wanted)


NO_NOTE = "the case critic marked a concern on this case and wrote no note"


def carried_concerns(data: bytes, sha256: str, receipts=(), artifacts=None, memo=None, review: str = "",
                     start: int = 1) -> list:
    """The concerns of ONE accepted case-critic round, to travel to the S5 automator (HF4-11, the owner's word 28.10.2026:
    a concern that is not a failing case is passed on, the automator takes it into account).

    `[{"id": "CC-n", "case", "kind": "remark", "problem", "review"}]`, one element per case of every roll-call row that is
    `reviewed: yes` and whose `verdict` cell is `approve_with_concerns`, in the order of the rows (`CC-n` counts from `start`).
    The round is the same one `scoped_verdict` reads (`_receipt_round`: the bytes the receipt measured, the first round
    of them). `problem` is the row's `note` word for word - it is carried, not judged (nothing is decided by its
    wording, FR-12); a row with no note says so. `review` is the dispatch id of the critic, which the caller knows.

    `fix` is the row's `fix` cell (the critic's own fix), '' when the critic wrote none.

    Never raises and never invents: at any doubt about the round (the receipt measures other bytes, two roll-calls,
    no table, an exception) the answer is `[]` and one line on stderr says why, so a concern is never taken from bytes
    the receipt did not measure (I3, FR-59)."""
    return _read_round(data, sha256, receipts, artifacts, memo, review, start)[1]


def _read_round(data: bytes, sha256: str, receipts, artifacts, memo, review: str, start: int = 1) -> tuple:
    """`(listed, concerns)` of ONE round, cut and parsed once: `listed` the cases of its `reviewed: yes` rows, `concerns` as
    `carried_concerns` words them. At any doubt `(set(), [])` and one line on stderr says why."""
    def silent(reason: str) -> tuple:
        print(f"critic_rollcall: no concern carried from this round: {reason}", file=sys.stderr)
        return set(), []
    try:
        text, doubt = _receipt_round(data, sha256, receipts, memo)
        if doubt:
            return silent(doubt[1])
        rows = parse_rollcall(text, artifacts)
        if not rows:
            return silent("the round has no roll-call table")
        listed, found, number = set(), [], int(start)
        for row in rows:
            if row.get("reviewed") is not True:
                continue
            cases = [str(case) for case in row.get("ids") or [row.get("case") or ""]]
            listed.update(cases)
            if row.get("verdict") != "approve_with_concerns":
                continue
            for case in cases:
                found.append({"id": f"CC-{number}", "case": case, "kind": "remark", "problem": row.get("note") or NO_NOTE,
                              "fix": row.get("fix") or "", "review": review})
                number += 1
        return listed, found
    except Exception as exc:  # noqa: BLE001 - a reader of a role's file never stops the stage
        return silent(f"the roll-call could not be read ({type(exc).__name__})")


def accepted_rounds(data: bytes, rounds, artifacts=None) -> list:
    """The accepted rounds of ONE findings file, read once each (AR-13: THE reader of which cases a round lists and which
    concerns it carries; `s5_plan.case_concerns` uses only this). `rounds` is `[(sha256, review dispatch id)]` in the order
    the reviews were accepted; the receipts of the file's other rounds are the other hashes, one memo serves them all.
    `[{"review", "listed": {case}, "concerns": [carried_concerns' elements]}]`, one per round, in the same order; a round in
    doubt lists nothing and carries nothing (stderr says why)."""
    memo, receipts = {}, [str(sha or "") for sha, _review in rounds]
    return [dict(zip(("listed", "concerns"), _read_round(data, sha, receipts, artifacts, memo, str(review or ""))),
                 review=str(review or "")) for sha, review in rounds]


def derive(rows: list) -> dict:
    """The counts the verdict is computed from. `unstated` is its own list: a row whose table
    has no `reviewed` column is not reviewed and is not a refusal to review either — it is a
    table missing the column, which is a repair with one named door (FR-41: it says `unstated`
    rather than borrowing either answer). `unreviewed` keeps naming the rows that SAY no, so
    every reader of that field means the same thing by it as before."""
    unreviewed = [row["case"] or row["plan_row"] for row in rows if row["reviewed"] is False]
    unstated = [row["case"] or row["plan_row"] for row in rows if row["reviewed"] is None]
    reviewed = sum(1 for row in rows if row["reviewed"] is True)
    return {"total": len(rows), "reviewed": reviewed, "unreviewed": unreviewed,
            "unstated": unstated, "digest": f"{reviewed} of {len(rows)} reviewed",
            "verdict_ceiling": "partial" if unreviewed or unstated else ""}


def task_root_of(path: Path):
    """The story directory a findings file lives in: the nearest ancestor with a pipeline.json."""
    for parent in Path(path).resolve().parents:
        if (parent / "pipeline.json").is_file():
            return parent
    return None


def fix_errors(fixes: list, task_root) -> tuple:
    """(errors, unapplied) for the last round's exact replacements.

    A fix has landed when the pinned case content contains the replacement text AND the pin
    moved off the version the critic reviewed: a replacement that is only in the authoring file
    is not what Gate A reads.
    """
    import contract as C
    task_root = Path(task_root)
    pinned = {str(link.get("case_id")): link for link in C.story_case_links(task_root)
              if isinstance(link, dict)}
    errors, unapplied = [], []
    for fix in fixes:
        cid = str(fix.get("case_id") or "")
        link = pinned.get(cid)
        if not link:
            errors.append(f"fix for {cid or '<no case_id>'}: that case is not pinned in "
                          "state/story-case-links.json — a fix Gate A cannot read is not a fix")
            continue
        try:
            content = (task_root / str(link.get("path") or "")).read_text(encoding="utf-8", errors="replace")
        except Exception:
            content = ""
        landed = str(fix.get("replace") or "") in content and content != ""
        moved = str(link.get("version") or "") != str(fix.get("reviewed_version") or "")
        if landed and moved:
            continue
        why = "the replacement text is not in the pinned case" if not landed else \
              "the pinned version is still the one the critic reviewed"
        unapplied.append({"case_id": cid, "reason": why, "fix": fix})
    return errors, unapplied


def fix_match_count(fix: dict, task_root) -> int:
    """How many places `apply_fixes` would find for this replacement.

    Exactly one is what it needs. Zero or several means no code can land the fix: the critic's
    `## Gate A debts` line is then the whole of what happens to it, and calling it
    `factory_fixable` afterwards asks for a repair that does not exist."""
    import contract as C
    task_root = Path(task_root)
    cid, find = str((fix or {}).get("case_id") or ""), str((fix or {}).get("find") or "")
    if not find:
        return 0
    link = next((l for l in C.story_case_links(task_root)
                 if isinstance(l, dict) and str(l.get("case_id")) == cid), None)
    if not link:
        return 0
    source = _resolve_source(task_root, link)
    if source is None:
        source = task_root / str(link.get("path") or "")
    try:
        return Path(source).read_text(encoding="utf-8", errors="replace").count(find)
    except Exception:
        return 0


def debt_owner(text: str, case_id: str) -> str:
    """The `## Gate A debts` line that carries this case with an owner, or "".

    A fix nobody could apply is not a defect of the factory once the critic has carried it to
    the gate with an owner: it is one of the things the person is approving. `findings_errors`
    and `gate_preflight.check_cases` have to read that the same way — on TP1-15045 one
    accepted the debt and the other kept calling it `factory_fixable`, so S4 could not close
    while nothing was left to repair."""
    for line in _section(text or "", DEBTS_HEADING).splitlines():
        if str(case_id or "") in line and "owner:" in line.lower():
            return " ".join(line.split()).strip("-* ")
    return ""


def findings_errors(path: Path, text: str | None = None, task_root=None) -> list:
    """Every rule this file has to satisfy. Importable so a test asserts on the message."""
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace") if text is None else text
    name = path.name
    errors: list = []
    rows = parse_rollcall(text, task_root)
    verdict = declared_verdict(text)
    if not rows:
        errors.append(f"{name}: no `{ROLLCALL_HEADING}` table — completeness is proven by "
                      "enumeration; an approve without the roll-call trail is not accepted")
    if verdict and verdict not in CASE_CRITIC_VERDICTS:
        errors.append(f"{name}: verdict '{verdict}' outside {list(CASE_CRITIC_VERDICTS)}")
    elif not verdict:
        errors.append(f"{name}: no `Verdict:` line — the verdict is the point of the review")

    facts = derive(rows)
    if rows and facts["unstated"]:
        # The column is the field. Reading the cell's prose for "not reviewed" instead let an
        # approve over unreviewed cases through whenever the critic worded it otherwise, and the
        # role's own card has asked for the column since 27.09 (FR-12, FR-38).
        listed = named(facts["unstated"], 8, where="the roll-call table")
        errors.append(
            f"{name}: the `{ROLLCALL_HEADING}` table has no `reviewed` column, so nothing says "
            f"whether {len(facts['unstated'])} of {facts['total']} rows were read ({listed}) — add "
            "the column and write `yes` or `no` for every row; the verdict this roll-call computes "
            "until then is `partial`")
    if rows and facts["unreviewed"]:
        listed = ", ".join(facts["unreviewed"])
        if verdict in APPROVING_VERDICTS:
            errors.append(
                f"{name}: verdict '{verdict}' with {len(facts['unreviewed'])} of {facts['total']} rows "
                f"not semantically reviewed ({listed}) — an unreviewed row is a failed review, not a "
                "note; the verdict this roll-call computes is `partial`. Review them, or record "
                "`partial`.")
        if not any(int(m.group(1)) == facts["reviewed"] and int(m.group(2)) == facts["total"]
                   for m in DIGEST_RE.finditer(text)):
            errors.append(f"{name}: the digest must say \"{facts['digest']}\" — \"approve\" beside "
                          "\"15 cases pinned\" read as a verdict about the whole set (TP1-15045)")
        gate_line = next((line for line in text.splitlines() if line.strip().startswith(GATE_A_LINE)), "")
        missing = [cid for cid in facts["unreviewed"] if cid not in gate_line]
        if missing:
            errors.append(f"{name}: a `{GATE_A_LINE}` line must name every unreviewed case "
                          f"({', '.join(missing)} absent) — Gate A decides on what was reviewed, "
                          "so it has to be told what was not")

    fixes = parse_fixes(text)
    if any(fix.get("__unreadable__") for fix in fixes):
        errors.append(f"{name}: the `{FIXES_HEADING}` block is not readable JSON")
        fixes = []
    if verdict == "approve_with_fixes" and not fixes:
        errors.append(f"{name}: approve_with_fixes with no `{FIXES_HEADING}` block — the verdict "
                      "exists to carry the replacements that need no second review round; "
                      "without them it is just `approve`")
    if fixes and verdict not in ("approve_with_fixes", ""):
        errors.append(f"{name}: exact replacements beside verdict '{verdict}' — they belong to "
                      "approve_with_fixes; a rejected case's findings go in the findings text")
    for i, fix in enumerate(fixes):
        for field in ("case_id", "locator", "find", "replace", "reviewed_version"):
            if not str(fix.get(field) or "").strip():
                errors.append(f"{name}: fixes[{i}] has no '{field}' — a fix applied without a new "
                              "review round has to name the case, the place, the old text, the new "
                              "text and the version it was read on")
                break

    root = task_root or task_root_of(path)
    if fixes and root and not [e for e in errors if "fixes[" in e]:
        applied_errors, unapplied = fix_errors(fixes, root)
        errors.extend(applied_errors)
        for item in unapplied:
            if not debt_owner(text, item["case_id"]):
                errors.append(
                    f"{name}: the fix for {item['case_id']} was not applied ({item['reason']}) and is "
                    f"not under `{DEBTS_HEADING}` with an owner — the designer applies a last-round "
                    "replacement without a new review round; what stays unapplied goes to Gate A as "
                    "a debt with an owner, never as a footnote")
    return errors


def project_root_of(task_root) -> Path | None:
    """The nearest ancestor of `task_root` that carries `qa-factory/config.json`, or None.

    `config.json` always lives there (`hooklib.state_dir`); only `artifact_root` inside it is
    configurable, so walking up for the fixed marker works even when a project's stories live
    somewhere other than the default `qa-factory/artifacts/<TICKET>`. Found by its marker, never
    guessed from the directory shape (a nested monorepo made that guess wrong once - TP1-14336).

    A delegate of `runtime_paths.nearest_project`, the ONE walk (B-309 (d), t-622): `case_stamp`,
    `gate_preflight` and `sizing` import THIS name (B-309 t-422), and it keeps it. The import is lazy and
    `runtime_paths` loads only the standard library, so no importer of this module can form a cycle.
    `runtime_paths.project_for_task` is a different question (it ADMITS a project by its artifact
    root and raises); this one only locates the marker.
    """
    from runtime_paths import nearest_project
    return nearest_project(task_root)


def _resolve_source(task_root: Path, link: dict):
    """The authoring case file a pin's provenance names — where `--apply-fixes` writes.

    A0.7.5+ link carries a project-relative `source_path` (A20); a link pinned before that
    audit rule kept only `source_name`, so fall back to a name search under the story's own
    case directories (`case_versions.discover_cases`'s default roots) before giving up.
    """
    import case_versions as V
    project_root = project_root_of(task_root)
    rel = V.read_source_path(link)
    if rel and project_root:
        candidate = project_root / rel
        if candidate.is_file():
            return candidate
    name = str((link.get("store_provenance") or {}).get("source_name") or "")
    if name:
        for source in V.discover_cases(task_root):
            if source.name == name:
                return source
    return None


def apply_fixes(path: Path, task_root, *, store: Path | None = None) -> dict:
    """Apply the last round's exact replacements from `## Fixes without a new round` by code.

    TP1-15045: the critic supplied exact replacement text for TC-012 and TC-014 twice
    (`approve_with_fixes`), and both times it needed a `qa-case-designer` dispatch to land —
    which was then blocked. The cap on repair ROUNDS was never meant to swallow a
    finished sentence; this writes the replacement into the authoring case file itself, creates
    a new immutable version and re-pins it, and verifies the text landed — no dispatch.

    A replacement whose `find` text does not match the pinned case's current bytes exactly once
    (0 or more than 1 occurrence) is left alone and reported: an ambiguous edit stays a Gate A
    debt with an owner, exactly as an unapplied fix already does in `findings_errors`.
    """
    path = Path(path)
    task_root = Path(task_root)
    text = path.read_text(encoding="utf-8", errors="replace")
    fixes = parse_fixes(text)
    if any(fix.get("__unreadable__") for fix in fixes):
        return {"applied": [], "skipped": [], "error": f"{path.name}: unreadable fixes block"}
    if not fixes:
        return {"applied": [], "skipped": []}

    import case_versions as V
    import contract as C

    store = Path(store) if store is not None else V.store_root(task_root)
    links = {str(link.get("case_id")): link for link in C.story_case_links(task_root)
             if isinstance(link, dict)}
    by_case: dict = {}
    for fix in fixes:
        by_case.setdefault(str(fix.get("case_id") or ""), []).append(fix)

    applied, skipped = [], []
    for case_id, case_fixes in by_case.items():
        link = links.get(case_id)
        if not link:
            skipped.extend({"case_id": case_id, "fix": fix,
                            "reason": "case is not pinned in state/story-case-links.json"}
                           for fix in case_fixes)
            continue
        source = _resolve_source(task_root, link)
        if source is None:
            skipped.extend({"case_id": case_id, "fix": fix,
                            "reason": "authoring case file not found from the pin's provenance"}
                           for fix in case_fixes)
            continue
        content = source.read_text(encoding="utf-8", errors="replace")
        original = content
        landed_here = []
        for fix in case_fixes:
            find, replace = str(fix.get("find") or ""), str(fix.get("replace") or "")
            count = content.count(find) if find else 0
            if count != 1:
                skipped.append({"case_id": case_id, "fix": fix,
                                "reason": f"{count} matches for the exact text (need exactly 1)"})
                continue
            content = content.replace(find, replace, 1)
            landed_here.append(fix)
        if not landed_here:
            continue
        if content != original:
            source.write_text(content, encoding="utf-8", newline="\n")
        record = V.create_version(store, source)
        V.pin(task_root, record, expected_previous_version=link.get("version"))
        new_links = {str(l.get("case_id")): l for l in C.story_case_links(task_root)
                     if isinstance(l, dict)}
        new_link = new_links.get(case_id) or {}
        pinned_path = task_root / str(new_link.get("path") or "")
        pinned = pinned_path.read_text(encoding="utf-8", errors="replace") if pinned_path.is_file() else ""
        for fix in landed_here:
            moved = str(new_link.get("version") or "") != str(fix.get("reviewed_version") or "")
            landed = str(fix.get("replace") or "") in pinned
            if landed and moved:
                applied.append({"case_id": case_id, "fix": fix, "version": new_link.get("version")})
            else:
                skipped.append({"case_id": case_id, "fix": fix,
                                "reason": "replacement written but did not verify after re-pin"})
    return {"applied": applied, "skipped": skipped}


def raise_pending(task_root, *, store: Path | None = None) -> dict:
    """The raise-and-re-pin step of O4 (t-227, P20): the questions the case designer could not raise.

    The designer has no Bash, so a Then whose expected value is unknown is written as `unknown` with the
    ref `raise` and ONE `raise_questions` line; this is the S4-exit step that applies the critic's
    `approve_with_fixes` and re-pins, and it does the same for those: for every pinned case it calls
    `question_register.raise_for_case` (the question goes into the readiness file, keyed by (case, Then),
    so a second run raises nothing twice), writes the case's authoring file with `raise` -> the new id and
    the `raise_questions` entry dropped, and re-pins a new version - no designer dispatch. A case with no
    `raise` is never read past one substring test and never written. Returns {"raised": [{case, then,
    question}], "skipped": [{case_id, reason}], "plan_notes": [line]}: a Then that could not be raised keeps its `raise` and the
    gate A rehearsal refuses it by name (`gate_preflight.check_unraised_questions`)."""
    task_root = Path(task_root)
    import case_versions as V
    import contract as C
    import question_register as QR
    store = Path(store) if store is not None else V.store_root(task_root)
    out: dict = {"raised": [], "skipped": [], "plan_notes": []}
    for link in C.story_case_links(task_root):
        if not isinstance(link, dict):
            continue
        case_id = str(link.get("case_id") or "")
        source = _resolve_source(task_root, link)
        if source is None:
            continue
        try:
            content = source.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if C.RAISE_REF not in content:
            continue
        result = QR.raise_for_case(task_root, content, case_id)
        out["plan_notes"].extend(result.get("plan_notes") or [])
        out["skipped"].extend({"case_id": case_id, "reason": problem} for problem in result["problems"])
        if result["text"] is None:
            continue
        source.write_text(result["text"], encoding="utf-8", newline="\n")
        record = V.create_version(store, source)
        V.pin(task_root, record, expected_previous_version=link.get("version"))
        out["raised"].extend(result["raised"])
    return out


def rounds(text: str):
    """`(index, round_text)` of every round of one findings file, NEWEST first (0 = the newest). Rounds are prepended and an older
    round's bytes are never edited; each is cut by `_round_slice`, the one cut (AR-13). `_round_homes` and the merge check read
    rounds through this."""
    rest, index = text, 0
    while rest.strip():
        first = _round_slice(rest) or rest
        yield index, first
        rest, index = rest[len(first):], index + 1


# --- TQ1-27: merge candidates, level, plan case budget (the S4 exit; code reads cells and three fixed tokens, never the Given/When) ---

def parse_merge_candidates(text: str, artifacts=None) -> tuple:
    """`(rows, bad_header)` of the `## Merge candidates` table of ONE round: `[{"ids": [case ids], "verdict", "reason"}]`.

    Columns are found by name (`MERGE_COLUMNS`, any order, backticks off); a missing one is `bad_header` ("the table has no `x`
    column") and no row is read. Ids by `contract.case_ids` in the project's own form (B-013). The verdict is lower case, backticks
    off. An absent section or a table with no row is `([], "")`: no pair answered, nothing malformed (AR-23)."""
    import contract as C
    raw = C.md_table(text, MERGE_HEADING)
    if not raw:
        return [], ""
    cfg = C.case_config(artifacts)
    header = [cell.strip().strip("`").lower() for cell in raw[0]]
    missing = next((name for name in MERGE_COLUMNS if name not in header), "")
    if missing:
        return [], f"the table has no `{missing}` column"
    at = {name: header.index(name) for name in MERGE_COLUMNS}
    rows = []
    for cells in raw[1:]:
        if not cells or not any(cells):
            continue
        cell = lambda name: cells[at[name]].strip() if at[name] < len(cells) else ""  # noqa: E731
        rows.append({"ids": C.case_ids(cell("cases"), cfg=cfg), "verdict": cell("verdict").strip("`").lower(),
                     "reason": cell("reason")})
    return rows, ""


def _read_rounds(files, artifacts, notes: list) -> list:
    """Every round of every findings file, parsed once, newest first: `{"index", "name", "rows", "bad", "roll", "note_col", "word", "text"}`. A file
    that cannot be read is a note naming it, never a pass of a pair (its pairs stay unanswered)."""
    out = []
    for path in files:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            notes.append(f"{Path(path).name} could not be read for the merge check ({type(exc).__name__})")
            continue
        for index, part in rounds(text):
            rows, bad = parse_merge_candidates(part, artifacts)
            out.append({"index": index, "name": Path(path).name, "rows": rows, "bad": bad,
                        "roll": parse_rollcall(part, artifacts), "note_col": _has_note_column(part), "word": (declared_verdict(part) or "").lower(), "text": part})
    return sorted(out, key=lambda r: r["index"])


def _has_note_column(text: str) -> bool:
    import contract as C
    raw = C.md_table(text, ROLLCALL_HEADING)
    return bool(raw) and any(cell.strip().strip("`").lower() == "note" for cell in raw[0])


def _pairs(ids) -> list:
    import itertools
    return list(itertools.combinations(sorted(set(ids)), 2))


def _merge_form_errors(newest: list, live: dict) -> list:
    """The form of the NEWEST round of each file only (an old malformed row could never be mended). Each text holds `Merge candidates`."""
    out = []
    for rnd in newest:
        if rnd["bad"]:
            out.append(f"`{MERGE_HEADING}`: {rnd['bad']} - fix: `{MERGE_ROW_FORM}`")
        seen: dict = {}
        for row in rnd["rows"]:
            label = ", ".join(row["ids"]) or "(no case)"
            if len(row["ids"]) < 2:
                out.append(f"`{MERGE_HEADING}` row `{label}` names fewer than two cases - fix: `{MERGE_ROW_FORM}`")
            for cid in (i for i in row["ids"] if i not in live):
                out.append(f"`{MERGE_HEADING}` row `{label}` names {cid}, which is no case of this story, or it is Archived - fix: "
                           f"name the story's own cases, `{MERGE_ROW_FORM}`")
            word, reason = row["verdict"], row["reason"]
            ground = re.match(r"\W*(" + "|".join(KEEP_GROUNDS) + r")\b", reason)   # `P16: x`, `(P19) x`, `P16. x`, `**P16** x`
            if word not in MERGE_VERDICTS:
                out.append(f"`{MERGE_HEADING}` row `{label}`: verdict `{word or '(empty)'}` is no word of {'|'.join(MERGE_VERDICTS)} - fix: "
                           f"`{MERGE_ROW_FORM}`")
            elif word == "keep" and not ground:
                out.append(f"`{MERGE_HEADING}` row `{label}`: `keep` starts with neither {' nor '.join(KEEP_GROUNDS)} - fix: start the reason "
                           "with P16 (one red line could not tell the branches apart) or P19 (the cases need different levels)")
            elif word == "merge" and not reason.strip():
                out.append(f"`{MERGE_HEADING}` row `{label}`: `merge` gives no reason - fix: say what the merged test keeps")
            for pair in _pairs(row["ids"]):
                seen.setdefault(pair, set()).add(word)
        for pair, words in sorted(seen.items()):
            if len(words & set(MERGE_VERDICTS)) > 1:
                out.append(f"`{MERGE_HEADING}`: {pair[0]}, {pair[1]} answered twice: merge and keep - fix: one row per pair in a round")
    return out


def _answers(rounds_new_first: list, live: dict) -> dict:
    """`{(a, b): {"verdict", "ids"}}`: the answer of each pair of live cases - the NEWEST row (any round, newest first) that holds both
    with a verdict of `MERGE_VERDICTS`. An older `merge` is never silently dropped by a newer round that is silent about the pair."""
    out: dict = {}
    for rnd in rounds_new_first:
        for row in rnd["rows"]:
            if row["verdict"] in MERGE_VERDICTS:
                ids = tuple(sorted({i for i in row["ids"] if i in live}))
                for pair in _pairs(ids):
                    out.setdefault(pair, {"verdict": row["verdict"], "ids": ids})
    return out


def _owed_pair_errors(live: dict, in_scope, answers: dict, shown: int) -> tuple:
    """`(errors, notes)`: every unordered pair of live cases that share an `R-n` (`covers`) and have no answer in any round."""
    errors, notes = [], []
    ordered = sorted(live.values(), key=lambda c: c["id"])
    for at, a in enumerate(ordered):
        for b in ordered[at + 1:]:
            shared = sorted(a["covers"] & b["covers"], key=lambda r: int(r[2:]))
            if not shared or (a["id"], b["id"]) in answers:
                continue
            if not (in_scope(a) or in_scope(b)):
                notes.append(f"{a['id']} and {b['id']} both cover {', '.join(shared)}, outside this review's scope: no round answers the pair")
                continue
            errors.append(f"`{a['id']}` and `{b['id']}` both cover {', '.join(shared)} and no round answers the pair under `{MERGE_HEADING}` - "
                          f"fix: a row `| {a['id']}, {b['id']} | merge or keep | <reason> |` under `{MERGE_HEADING}` of this round (`keep` only "
                          "with P16: one red line could not tell the branches apart, or P19: they need different levels; `merge`: both cases "
                          f"`approve_with_concerns` with `{PARAMETRISE_TOKEN} {a['id']}, {b['id']}` in the note)")
    if len(errors) > shown:
        total = len(errors)
        errors = errors[:shown] + [f"{total - shown} more pairs under {MERGE_HEADING.lstrip('# ')} ({total} in all); answer these first, the check runs again"]
    return errors, notes


def _carries(note: str, partners: list, cfg) -> bool:
    """Does `note` hold `PARAMETRISE_TOKEN` (any case, spaces collapsed) followed by every id of `partners`? (S9: a superset is fine.)"""
    import contract as C
    flat = " ".join(str(note or "").split())
    found = re.search(re.escape(PARAMETRISE_TOKEN), flat, re.IGNORECASE)
    return bool(found) and set(partners) <= set(C.case_ids(flat[found.end():], cfg=cfg))


def _merge_concern_errors(rounds_new_first: list, answers: dict, artifacts) -> tuple:
    """`(errors, notes)`: every case of a row whose answer is `merge` must be approved ONLY as `approve_with_concerns` carrying the token
    and its partners (the one concern carrier, `_read_round`). A case the newest listing round does not approve is not refused here
    (E8): the round that approves it is held to the same rule. No `verdict` column beside an approving round word is refused: the
    column is what carries the concern, so the merge would be lost silently (B-2)."""
    import contract as C
    cfg, errors, notes = C.case_config(artifacts), [], []
    merged = sorted({i for a in answers.values() if a["verdict"] == "merge" for i in a["ids"]})
    for case in merged:
        # partners of a case = the cases whose PAIR with it is answered `merge` NOW (`answers` is per pair): a newer `keep` on A,B
        # takes B out of A's partners even when an older merge row held A,B,C
        partners = [i for i in merged if i != case and answers.get(tuple(sorted((case, i))), {}).get("verdict") == "merge"]
        if not partners:
            continue
        group = ", ".join(sorted([case] + partners))
        hit = next(((rnd, row) for rnd in rounds_new_first for row in rnd["roll"]
                    if row["reviewed"] is True and case in row["ids"]), None)
        if hit is None:
            notes.append(f"the merge of {group} names {case}, which no round reviewed")
            continue
        rnd, row = hit
        word = row["verdict"]
        if word == "approve_with_concerns" and _carries(row["note"], partners, cfg):
            continue
        if word is None and rnd["word"] not in APPROVING_VERDICTS:
            continue
        if word is not None and word not in APPROVING_VERDICTS:
            continue
        why = ("the roll-call has no `verdict` column, so the round's own word approves it and no concern reaches S5; add the column"
               if word is None else "")
        errors.append(f"the round answers `merge` for {group} under `{MERGE_HEADING}`, and {case} is approved without the merge reaching S5"
                      f"{': ' + why if why else ''}: only an `approve_with_concerns` row whose note says `{PARAMETRISE_TOKEN} {group}` is "
                      f"carried to the automator - fix: give {case}'s roll-call row the `verdict` `approve_with_concerns` and that note, "
                      "or answer the pair `keep` with its P16/P19 reason")
    return errors, notes


def _plan_rows_of(cell: str, plan_rows: dict) -> list:
    """EVERY plan row a roll-call `plan_row` cell names: each known plan row id that stands in it as a whole token (the ids come from the
    plan itself, no id pattern of ours). A cell naming two rows owes both rows' lines: the error direction is a refusal, never a silent pass."""
    return [plan_rows[rid] for rid in plan_rows if re.search(rf"(?<![\w-]){re.escape(rid)}(?![\w-])", str(cell or ""))]


def _level_owed(plan: dict) -> bool:
    """Does this plan row owe a `lower level:` line? An e2e-ui row or a manual one, unless it checks nothing (`skip`/`unverifiable`)."""
    import branch_accounting as BA
    disposition = str(plan.get("disposition") or "")
    return disposition not in BA.PLAN_EXCLUDING and (plan.get("level") == "e2e-ui" or disposition in BA.MANUAL_DISPOSITIONS)


def _level_errors(newest: list, task_root) -> tuple:
    """`(errors, notes)`: an e2e-ui or manual row the newest round reviewed says `lower level: impossible - <why>` or a lower level word
    + ` - <why>` (a level below the row's own, `contract.PLAN_LEVELS` order); a level word reaches the automator only as a concern, so
    it needs `approve_with_concerns` (or `reject`). P17: the automator chooses the level; this only holds the critic to stating one."""
    import branch_accounting as BA
    import contract as C
    try:
        plan_rows = {str(r.get("id") or ""): r for r in BA._plan(task_root)[1] if r.get("id")}
    except BA.Unreadable as exc:
        return [], [f"the level of an e2e-ui or manual row was not checked: {exc}"]
    if not plan_rows:
        return [], [("the plan has no rows" if BA._plan(task_root)[0] is not None else "no test-plan.json")
                    + ": the level of an e2e-ui or manual row was not checked"]
    errors, levels = [], C.PLAN_LEVELS
    form = f"`{LEVEL_TOKEN} {LEVEL_IMPOSSIBLE} - <why>` or `{LEVEL_TOKEN} <unit|component|api|integration> - <why>`"
    for rnd in newest:
        owed = [(row, plan) for row in rnd["roll"] if row["reviewed"] is True
                for plan in _plan_rows_of(row["plan_row"], plan_rows) if _level_owed(plan)]
        if owed and not rnd["note_col"]:
            errors.append(f"the roll-call of {rnd['name']} has no `note` column, and an e2e-ui or manual row says its lower level there - fix: "
                          f"add the column and write {form}")
            continue
        for row, plan in owed:
            name, own = str(plan.get("id")), plan.get("level")
            said = re.search(re.escape(LEVEL_TOKEN) + r"\s*`?([A-Za-z0-9-]+)`?\s+[-–—]\s+(\S)", row["note"] or "", re.IGNORECASE)
            where = f"plan row {name} (level {own or 'not set'}, {plan.get('disposition')}): its roll-call row"
            word = said.group(1).lower() if said else ""
            if not said:
                errors.append(f"{where} has no `{LEVEL_TOKEN}` line in its note - fix: write {form}")
            elif word == LEVEL_IMPOSSIBLE:
                continue
            elif word not in levels or (own in levels and levels.index(word) >= levels.index(own)):
                errors.append(f"{where} says `{LEVEL_TOKEN} {word}`, which is no level below `{own or 'its own'}` - fix: write {form}")
            elif row["verdict"] not in ("approve_with_concerns", "reject"):
                errors.append(f"{where} names a lower level `{LEVEL_TOKEN} {word}` beside the verdict `{row['verdict']}`: a level word reaches the "
                              "automator only as a concern - fix: give the row the verdict `approve_with_concerns`")
    return errors, []


def _budget_errors(newest: list, live: dict, task_root) -> tuple:
    """`(errors, notes)`: more live cases than the S3 plan's `plan_case_budget` and no `Over the plan case budget: <why>` line in a newest
    round. Absent budget (always before SC5-6) is a note: a cost bound the factory does not know never refuses the role (E9)."""
    import branch_accounting as BA
    n = BA.plan_case_budget(task_root)
    if n is None:
        return [], ["the S3 plan sets no case budget yet (`plan_case_budget` in work/test-plan.json comes with SC5-6): the factory did not hold the case count "
                     "to one; nothing for the role to do"]
    if len(live) <= n:
        return [], []
    for rnd in newest:
        for line in rnd["text"].splitlines():
            stripped = line.strip().lstrip("-* ").strip()
            if stripped.startswith(BUDGET_LINE) and stripped[len(BUDGET_LINE):].strip():
                return [], []
    return [f"the story has {len(live)} cases and the S3 plan's case budget is {n}; the round does not say why the cases over it stay "
            f"(`{BUDGET_LINE}`) - fix: a line `{BUDGET_LINE} <why each case over {n} stays>` in this round, or merge"], []


def merge_candidate_errors(task_root, files=None) -> tuple:
    """`(errors, notes)` of the S4 exit for TQ1-27: pairs of cases that share a requirement are answered under `## Merge candidates`, a
    `merge` reaches S5 as a concern and changes no case, an e2e-ui or manual row states a lower level, the case count is held to the plan's
    budget. It composes the helpers above; the critic judges whether two cases ARE one form, code reads cells and three fixed tokens
    (FR-12). Never raises on a story artefact; its own defect propagates to `detector_main`'s `except` (UNREADABLE, exit 3)."""
    import branch_accounting as BA
    notes: list = []
    live = {c["id"]: c for c in BA._case_records(task_root) if c["status"] != "Archived"}   # over-include: only the exact word retires a case (E7)
    in_scope = BA._scoped(BA.critic_scope(task_root))
    files = findings_files(task_root) if files is None else files
    every = _read_rounds(files, task_root, notes)
    newest = [r for r in every if r["index"] == 0]
    answers = _answers(every, live)
    errors = _merge_form_errors(newest, live)
    for more, said in (_owed_pair_errors(live, in_scope, answers, BA.limit("refusal_units_shown")),
                       _merge_concern_errors(every, answers, task_root), _level_errors(newest, task_root),
                       _budget_errors(newest, live, task_root)):
        errors += more
        notes += said
    return errors, notes


FINDINGS_FILE_NAME = "critic-findings.md"   # the one spelling: the scan below and the Gate A reader of a critic's receipt


def findings_files(task_root) -> list:
    task_root = Path(task_root)
    found = sorted_paths(set(task_root.rglob(FINDINGS_FILE_NAME)))
    return [path for path in found if "test-cases" in path.parts]


def detector_main(root=None) -> int:
    """Zero-argument entry point for the S4 exit gate. Nothing to check until a findings file exists (exit 0); a check
    that could not run (`detector_story` raised, anything unhandled below) is `UNREADABLE: ...`, exit 3 (RH1-5, FR-59)."""
    try:
        return _detector_body(root)
    except Exception as exc:
        print(DV.unreadable_line(f"critic_rollcall could not complete ({type(exc).__name__}: {exc})"))
        return DV.EXIT_UNREADABLE


def _detector_body(root) -> int:
    from planning_contract import detector_story
    task_root = detector_story(root, stage_id="S4")
    if task_root is None:
        return 0
    files = findings_files(task_root)
    if not files:
        print(f"critic_rollcall: {task_root.name} has no critic-findings.md yet — nothing to check")
        return 0
    errors = [error for path in files for error in findings_errors(path, task_root=task_root)]
    more, notes = merge_candidate_errors(task_root, files)      # TQ1-27: exit-only, like `## Branch homes` (the write-time hook path is unchanged)
    errors += more
    for path in files:
        facts = derive(parse_rollcall(path.read_text(encoding="utf-8", errors="replace"), task_root))
        print(f"{path.name}: {facts['digest']}" +
              (f"; unreviewed: {', '.join(facts['unreviewed'])}" if facts["unreviewed"] else ""))
    for note in notes:      # before the verdict line: a non-`- ` line inside a REJECT block reads as unmigrated (`detector_verdict.parse`)
        print("note: " + one_line(note))
    if not errors:
        print(f"OK: {len(files)} critic findings file(s) carry a roll-call the verdict agrees with")
        return 0
    print(f"REJECT — {len(errors)} problem(s) in the case review:")
    for error in errors:
        print("- " + one_line(error))
    print("A person's word passes any of these: `" +
          door("waiver.py --task <TICKET> --stage S4 --block \"<part of the line>\"") + "` " + WHOLE_PART + ".")
    return 1


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--json"]
    task_root = None
    if "--task-root" in args:
        index = args.index("--task-root")
        task_root = Path(args[index + 1])
        del args[index:index + 2]
    store = None
    if "--store" in args:
        index = args.index("--store")
        if index + 1 >= len(args):
            # `--store` with nothing after it read args[index + 1] and raised IndexError,
            # which run_guarded can only report as OUR defect; it is a missing value.
            from role_cli import refuse
            return refuse("critic_rollcall.py --store",
                          "--store has no value after it: it takes the path of the store")
        store = Path(args[index + 1])
        del args[index:index + 2]
    if "--store" in sys.argv and "--apply-fixes" not in sys.argv:
        # `--store` alone left args empty, which fell through to the gate's zero-argument path:
        # the command printed nothing at all and exited 0, and the critic read that as accepted.
        from role_cli import refuse
        return refuse("critic_rollcall.py --store",
                      "--store is the destination of --apply-fixes and does nothing on its own")
    if "--apply-fixes" in args:
        args = [a for a in args if a != "--apply-fixes"]
        if task_root is None:
            print(json.dumps({"error": "--apply-fixes requires --task-root"}))
            return 1
        paths = [Path(a) for a in args] if args else findings_files(task_root)
        result = {"applied": [], "skipped": []}
        for path in paths:
            outcome = apply_fixes(path, task_root, store=store)
            if outcome.get("error"):
                result.setdefault("errors", []).append(outcome["error"])
                continue
            result["applied"].extend(outcome["applied"])
            result["skipped"].extend(outcome["skipped"])
        # O4: the questions the designer could not raise (no Bash) are raised here, with or without a
        # findings file: a story whose critic wrote `approve` still has its `raise` Thens.
        try:
            raised = raise_pending(task_root, store=store)
            if raised["raised"]:
                result["raised"] = raised["raised"]
            result["skipped"].extend(raised["skipped"])
            if raised["plan_notes"]:
                result["plan_notes"] = raised["plan_notes"]      # raised, but the plan row was not told: said, never dropped (FR-59)
        except Exception as exc:  # code informs, it never stops the factory on its own defect (P1)
            result.setdefault("errors", []).append(f"raise_questions: {type(exc).__name__}: {exc}")
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 1 if result["skipped"] or result.get("errors") else 0
    if not args:
        return detector_main()
    errors = []
    for raw in args:
        path = Path(raw)
        if not path.is_file():
            print("REJECT — 1 problem(s):")
            print(f"- no such findings file: {path}")
            return 1
        text = path.read_text(encoding="utf-8", errors="replace")
        facts = derive(parse_rollcall(text, task_root))
        if "--json" in sys.argv:
            print(json.dumps({"file": path.name, "verdict": declared_verdict(text), **facts},
                             ensure_ascii=False))
        else:
            print(f"{path.name}: verdict={declared_verdict(text) or '?'} {facts['digest']}" +
                  (f"; unreviewed: {', '.join(facts['unreviewed'])}" if facts["unreviewed"] else ""))
        errors.extend(findings_errors(path, text, task_root))
    if errors:
        print(f"REJECT — {len(errors)} problem(s): acceptance forbidden:")
        for error in errors:
            print("- " + one_line(error))
        return 1
    return 0


if __name__ == "__main__":
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    from role_cli import command_from_argv, run_guarded
    sys.exit(run_guarded(command_from_argv("critic_rollcall.py"), main))
