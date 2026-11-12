"""The shape of a role's last word: a header, one line per item, a path.

The orchestrator needs nothing from a finished role but status. On TP1-15045 it got
pages instead — the automator's closing message ran 3,401 characters of prose, the code
critic's 1,577, the runner's 786 — and it compacted in the middle of S5. Every one of those
characters was re-billed on every later turn of the orchestrator, and not one of them said
anything the artifact did not already hold.

So the last message has a form, and the form is the whole message:

    <role> <stage> <window or scope> · ok|concerns|halt|impossible
    <instance or case id> · <state> · <reason, at most 80 characters>
    <task-relative path of the artifact>

Exactly one row per item the dispatch was scoped to, then the path, and nothing else before it.
Whatever follows the path is not part of the form and not a refusal: `parse` keeps it in
`notes`. What an "item" is depends on the role — `ROLE_ITEM` below: a test instance for the three roles
that run tests, and the role's own unit of work (a source, a requirement, a plan row, a
case, a bug, a routed obligation) for the rest.

`parse` reads a digest, `check` judges one against the ids the dispatch was scoped to, and
`exit_gate` refuses a handoff whose digest fails `check` — a refusal a person's word passes
like any other (`waiver.py --stage <S> --block "digest"`).

Two kinds of leniency are deliberate. Decoration is forgiven (bold, backticks, a bullet, a
code fence): the rule is about structure, not typography. And the one-line digest the 0.7.x
charters ask for — `<role> <stage> done|halt · <path> · <one fact>` — still parses clean,
because a story in flight must not be refused over a role file that has not been updated yet.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as C  # noqa: E402
import detector_verdict as DV  # noqa: E402

# What the orchestrator branches on. `done` and `review` are the 0.7.x spellings of `ok` and
# `concerns`; they stay readable so an un-updated role file is not a blocked handoff.
HEADER_VERDICTS = ("ok", "concerns", "halt", "impossible")
LEGACY_VERDICTS = ("done", "review")
HALTING_VERDICTS = ("halt", "impossible")

# The state of one item. The seven the owner named, plus the vocabularies the artifacts are
# already validated against — a role that triaged a test says `APP_BUG` here, not a second
# word invented for the digest. Read from contract.py, so a verdict added there is accepted
# here without a matching edit.
BASE_STATES = ("green", "red", "handed", "unresolved", "impossible", "passed", "failed")
# The words the roles without test instances need for their own items.
ITEM_STATES = ("found", "not_found", "created", "updated", "routed", "deferred", "blocked",
               "waived", "skipped", "reviewed",
               # The critic's charter orders "rejected, unverified and blocked" recorded
               # separately, never as green; without the word here the gate refused every
               # honest line about a probe that could not run, and the role could not hand
               # off at all (TP1-13797, driver run 3: four resumes, three conductors).
               "unverified",
               # The run contract's own words for a manual-agent case:
               # `result: pass|fail|inconclusive` plus `manual_skipped`
               # (references/artifact-contract-run.md). Without them here the runner's honest
               # line about a case it could not conclude was refused (TP1-13797, run 3).
               "inconclusive", "manual_skipped",
               # What a retro analyst does with a backlog item or an obligation it wrote
               # down: the same family as `created` and `routed`, and the word the role
               # reaches for (TP1-13797, run 3: three resumes over it).
               "filed")
def _vocabulary_states() -> tuple:
    """`handoffs/vocabulary.yaml` is the factory's single list of words (P1 of the handoff
    plan). A word added there works here without a matching edit in Python - three lists that
    have to be kept in step by hand is exactly what cost four handoffs on TP1-13797. The
    literals below stay as the offline fallback: a factory whose vocabulary file is missing
    still refuses and accepts what it always did, and a test asserts the two never diverge."""
    try:
        import handoff                                 # local: role_digest is imported by hooks
        states = handoff.vocabulary().get("row_states")
        return tuple(str(word) for word in states) if isinstance(states, dict) else ()
    except Exception:
        return ()


def _review_verdict_words() -> tuple:
    """The case critic's verdict words, from the ONE constant that holds them (`critic_rollcall.
    CASE_CRITIC_VERDICTS`) - the role file tells the critic those words, so the digest row accepts them
    (run 12586: the critic wrote `approved (approve_with_concerns)` and the gate knew no such word). The
    vocabulary is shared: a verdict word on any role's row is accepted."""
    try:
        import critic_rollcall
        return tuple(critic_rollcall.CASE_CRITIC_VERDICTS)
    except Exception:
        return ()


ROW_STATES = tuple(dict.fromkeys(
    BASE_STATES + ITEM_STATES + C.UNRESOLVED_REASONS + C.EXECUTION_STATUS + C.RESULT_STATUS
    + C.TRIAGE_VERDICTS + C.CRITIC_VERDICTS + _review_verdict_words() + C.LEDGER_STATE_PREFIXES
    + C.DISPOSITIONS + _vocabulary_states()))

# One row of the digest, per role. The charter's digest line names the same word, so the
# person reading a role file and the check reading its output mean the same thing.
ROLE_ITEM = {
    "qa-scout": "source of the context manifest's inventory",
    "qa-requirements-tester": "requirement of the register",
    "qa-test-strategist": "plan row",
    "qa-case-designer": "case written or updated",
    "qa-case-critic": "case reviewed",
    "qa-automator": "test instance of the window",
    "qa-code-critic": "test instance reviewed",
    "qa-runner": "instance or manual-agent case executed",
    "qa-failure-analyst": "failing test triaged",
    "qa-doc-scribe": "ledger row that is not passed_green",
    "qa-bug-reporter": "bug created or updated",
    "qa-retro-analyst": "obligation, backlog item or strategy edit routed out of the story",
}

REASON_MAX = 80
# `·` is the separator the charters print. `|` and the two dashes are accepted because a
# model reaches for them under a narrow terminal; a hyphen is not, because ids contain one.
SEPARATOR = re.compile(r"\s*[·•|]\s*|\s+[—–]\s+")
FORM = ("<role> <stage> <window> · ok|concerns|halt|impossible / "
        "<id> · <state> · <reason ≤ 80 chars> (one line per item in scope) / "
        "<task-relative path>")
STAGE_RE = re.compile(r"^S\d$")
FENCE_RE = re.compile(r"^```")
ABSOLUTE_RE = re.compile(r"^(/|[A-Za-z]:[\\/]|\\\\)")


def _clean(line: str) -> str:
    """One line without the typography a chat answer puts around it."""
    text = line.strip()
    text = re.sub(r"^[-*>•]\s+", "", text)
    text = text.strip("`").strip()
    while text.startswith("**") and text.endswith("**") and len(text) > 4:
        text = text[2:-2].strip()
    return text.replace("**", "").replace("`", "").strip()


def _lines(text: str) -> list:
    """The digest's own lines: blanks, code fences and horizontal rules are not content."""
    out = []
    for raw in str(text or "").splitlines():
        line = _clean(raw)
        if not line or FENCE_RE.match(line) or set(line) <= set("-*_ "):
            continue
        out.append(line)
    return out


def _is_state(token: str) -> bool:
    word = token.strip()
    if not word or " " in word:
        return False
    return any(word == s or word.startswith(s + ":") for s in ROW_STATES)


PAREN_STATE_RE = re.compile(r"^(\S+)\s*\(([^()]*)\)$")


def _row_state(token: str) -> str:
    """The state a row's second field names, or "". A bare state is itself. `<word> (<state>)` is the spelling
    the case critic wrote on run 12586 (`approved (approve_with_concerns)`): both known -> the first word wins;
    the first not a state -> the parenthesised known state; empty parentheses, or neither a state -> "" (a
    refusal, as before). The error direction is refusal: an unknown inside the parentheses is never read."""
    word = str(token or "").strip()
    if _is_state(word):
        return word
    match = PAREN_STATE_RE.match(word)
    if not match:
        return ""
    first, inner = match.group(1), match.group(2).strip()
    if not _is_state(inner):
        return ""
    return first if _is_state(first) else inner


def _is_path(text: str) -> bool:
    """A path, not a sentence: one token, and it names a file or a directory."""
    if not text or " " in text or SEPARATOR.search(text):
        return False
    return "/" in text or "\\" in text or bool(re.search(r"\.(md|json|jsonl|txt|xml|html)$", text))


def _parse_header(line: str) -> tuple:
    """(header dict, error). The header carries the role, the stage, the scope it worked on
    and the verdict — as the last field, or, in the 0.7.x form, as the last word before the
    path."""
    fields = [f.strip() for f in SEPARATOR.split(line)]
    words = fields[0].split()
    role = words[0] if words else ""
    stage = words[1] if len(words) > 1 and STAGE_RE.match(words[1]) else ""
    header = {"role": role, "stage": stage, "scope": "", "verdict": "", "path": "", "raw": line}
    if not stage:
        return header, ("the first line is not a digest header: it must read "
                        f"`<role> <stage> <window> · ok|concerns|halt|impossible`, not {line[:60]!r}")
    known = HEADER_VERDICTS + LEGACY_VERDICTS
    if len(fields) > 1 and fields[-1].split() and fields[-1].split()[0] in known and len(fields[-1].split()) == 1:
        header["verdict"] = fields[-1]
        header["scope"] = " ".join(words[2:])
    elif len(words) > 2 and words[-1] in known:
        # 0.7.x: `<role> <stage> done · <path> · <one fact>`
        header["verdict"] = words[-1]
        header["scope"] = " ".join(words[2:-1])
        header["path"] = fields[1] if len(fields) > 1 and _is_path(fields[1]) else ""
    else:
        return header, ("the header states no verdict: it ends with one of "
                        f"{'|'.join(HEADER_VERDICTS)}, not {line[-40:]!r}")
    return header, ""


def _parse_row(line: str) -> tuple:
    """(row dict, error). A row is `<id> · <state>` with an optional reason."""
    fields = [f.strip() for f in SEPARATOR.split(line, 2)]
    if len(fields) < 2 or not fields[0] or " " in fields[0]:
        return {}, ""
    state = _row_state(fields[1])
    if not state:
        return {}, ""
    row = {"id": fields[0], "state": state,
           "reason": fields[2] if len(fields) > 2 else "", "raw": line}
    if len(row["reason"]) > REASON_MAX:
        return row, (f"{row['id']}: the reason is {len(row['reason'])} characters, the form allows "
                     f"{REASON_MAX} — the long version belongs in the artifact")
    return row, ""


def parse(text: str) -> dict:
    """{"header": {...}, "rows": [...], "path": str, "errors": [...], "notes": [...]} for one
    final message. `notes` are the lines after the form's path; `file_notes` keeps them whole in a file the
    conductor reads, `role_digest.py --json` prints them.

    The errors here are about the form alone. Whether the rows cover the dispatch's scope is
    `check`'s question, because only the caller knows what the scope was."""
    result = {"header": {}, "rows": [], "path": "", "errors": [], "notes": []}
    lines = _lines(text)
    if not lines:
        result["errors"].append("the final message is empty — the orchestrator was told nothing")
        return result
    header, error = _parse_header(lines[0])
    result["header"] = header
    if error:
        result["errors"].append(error)
    result["path"] = header.get("path", "")
    body = lines[1:]
    # The path line CLOSES the form. A good header, then rows, then the first path line: whatever
    # follows is not part of it, and is kept in `notes` instead of refused - on TP1-15045
    # (cmp2, F-cmp2-9) a role's whole form plus a paragraph and a file list after the path was
    # refused three times, and a person passed it by word. Only with a header that parsed and
    # does not already carry its own path (the 0.7.x one-line digest): a failed header, prose
    # between the rows and the path, and a missing path are judged exactly as they always were.
    form_open = not error and not result["path"]
    for index, line in enumerate(body):
        row, row_error = _parse_row(line)
        if row and row_error:
            result["rows"].append(row)
            result["errors"].append(row_error)
            continue
        if row:
            result["rows"].append(row)
            continue
        if _is_path(line) and (form_open or index == len(body) - 1):
            result["path"] = line
            if ABSOLUTE_RE.match(line):
                result["errors"].append(
                    f"the artifact path is absolute ({line[:60]}) — a digest names a path "
                    "relative to the task root, which is the only frame the next role shares")
            if form_open:
                result["notes"] = body[index + 1:]
                break
            continue
        # A line that IS in the shape `<id> · <word> · <reason>` but whose word is not a
        # state fails for one reason only, and the role cannot guess the closed list unless
        # the refusal prints it: TP1-13797 run 3 lost four handoffs to `unverified`,
        # `inconclusive`, `filed` and `appended`, each invented because nothing named the words.
        fields = [f.strip() for f in SEPARATOR.split(line, 2)]
        if len(fields) >= 2 and fields[0] and " " not in fields[0] and not _row_state(fields[1]):
            result["errors"].append(
                f"{fields[0]}: `{fields[1][:30]}` is not a state of the form — use one of: "
                + ", ".join(sorted(ROW_STATES)))
            continue
        result["errors"].append(
            f"this line is not in the form: {line[:70]!r} — a digest is a header, one line per "
            "item and a path; an explanation lives in the artifact, not in the handoff")
    return result


# --- what follows the form is kept whole, never dropped (t-1685 N3-2) -------------------------------------------
# On run LOCAL-1 the roles' "Notes for the conductor" lines carried two real findings (the Q1/Q2 id mismatch, a basis
# conflict) and a refusal discarded them each time. `parse` already keeps the lines after the path in `notes`, cleaned of
# decoration; a refusal or an acceptance never kept them anywhere. The tail is written WHOLE, as the role wrote it, to
# `state/findings/<dispatch>-digest-notes.md` (the folder the conductor reads for remarks). ONE writer: `file_notes` below.
# The form lines are judged by `check` alone; a tail never changes that verdict, and a tail is written whether the form
# passed or not (a refused role is resumed with the same notes still on disk).
NOTES_DIR = ("state", "findings")
NOTES_SUFFIX = "-digest-notes.md"


def notes_tail(text: str) -> str:
    """The raw text after the digest's path line, exactly as written (line endings, decoration, fences and blank lines
    kept), or "" when the form has no path line closing it or nothing but blanks/fences follows. The path line is the one
    `parse` took (its `notes` are the cleaned lines after it); an empty or decoration-only tail is "" (no empty file)."""
    count = len(parse(text)["notes"])
    if not count:
        return ""
    total = len(_lines(text))
    path_at = total - count - 1               # the cleaned index of the path line; the notes are the cleaned lines after it
    seen = -1
    raw = str(text or "").splitlines(keepends=True)
    for position, line in enumerate(raw):
        cleaned = _clean(line)
        if not cleaned or FENCE_RE.match(cleaned) or set(cleaned) <= set("-*_ "):
            continue
        seen += 1
        if seen == path_at:
            return "".join(raw[position + 1:])
    return ""


def file_notes(task_root, dispatch_id: str, text: str) -> str:
    """Write `notes_tail(text)` whole to `<task root>/state/findings/<dispatch>-digest-notes.md` and return its
    task-relative path; "" when there is no tail, the id is not a plain file name, or the write failed (never raises: the
    digest's own verdict does not depend on it). An existing file of an earlier stop of the same dispatch is replaced."""
    tail = notes_tail(text)
    name = str(dispatch_id or "")
    if not tail or not name or name != Path(name).name or name in (".", ".."):
        return ""
    try:
        target = Path(task_root).joinpath(*NOTES_DIR, name + NOTES_SUFFIX)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(tail.encode("utf-8"))
    except (OSError, ValueError):
        return ""
    return "/".join(NOTES_DIR + (name + NOTES_SUFFIX,))


def with_notes_line(text: str, relative: str) -> str:
    """The accepted digest with `notes: <path>` as its last line, so whoever reads the digest finds the notes; `text`
    itself when `relative` is empty."""
    return str(text).rstrip("\n") + f"\nnotes: {relative}\n" if relative else str(text)


def covers(scoped: str, row_id: str) -> bool:
    """Does this row answer for that scoped id? An automator scoped to TC-012 answers with
    its four instance ids (`TC-012#3`, `TC-012::valid`), and a role scoped to instances may
    answer per case — the run of 2026-09-22 used both spellings in one window."""
    left, right = str(scoped).strip().lower(), str(row_id).strip().lower()
    if not left or not right:
        return False
    if left == right:
        return True
    longer, shorter = (right, left) if len(right) > len(left) else (left, right)
    return longer.startswith(shorter) and not longer[len(shorter)].isalnum()


def is_halting(text: str) -> bool:
    """The role handed the decision back instead of finishing.

    Read from a header's verdict, so a sentence that merely contains the word "halt" is not
    one. Looked for on ANY line, not only the first: a role that halts and buries its header
    under prose is refused for the prose, but the halt itself must still be heard — the whole
    point of the exemption the gate gives it (0.7.7 review, finding A-F4)."""
    for line in _lines(text):
        header, error = _parse_header(line)
        if not error and header.get("verdict") in HALTING_VERDICTS:
            return True
    return False


def check(text: str, expected_ids: list | None = None) -> list:
    """Every way this final message fails the form, in the order a person would read them.

    An empty list means the digest is one the orchestrator can act on without reading prose.
    A halting digest is not asked to account for the scope it never reached — the same
    exemption `exit_gate` gives it on required outputs, for the same reason."""
    parsed = parse(text)
    errors = list(parsed["errors"])
    halting = is_halting(text)
    if not parsed["path"] and not halting:
        errors.append("the digest names no artifact path — the last line is the task-relative "
                      "path of what you wrote, and it is where everything else went")
    for scoped in [str(i).strip() for i in (expected_ids or []) if str(i).strip()]:
        if halting:
            break
        if not any(covers(scoped, row["id"]) for row in parsed["rows"]):
            errors.append(f"{scoped} was in this dispatch's scope and has no line — one line per "
                          "item, including the ones that went nowhere (`unresolved`, `impossible`)")
    return errors


# --- the words a judge may be asked to map ---------------------------------------------------
# A digest fails the form in two different ways, and only one of them is a spelling question.
# A line of prose is prose: nothing can be asked about it, because the role never meant it as a
# row. But a header that names its role and its stage and then ends in `rejected`, and a line
# that reads `TC-008 · red/undiagnosed · ...`, are the form with one word spelled outside the
# closed list — and the closed list is the factory's bookkeeping, not the role's. `askable`
# names exactly those words, `apply` puts the mapped spelling back, and `check` then judges the
# result as it judges any other digest. Nothing here decides anything: `exit_gate` reads the spots
# (`askable`) to advise on a digest word (X2-3); no judge maps it any more.

def _verdict_candidate(line: str) -> dict:
    """The word a header ends with when it is not one of the four, or {}."""
    fields = [f.strip() for f in SEPARATOR.split(line)]
    words = fields[0].split()
    if len(words) < 2 or not STAGE_RE.match(words[1]):
        return {}  # no role and stage: the judge cannot invent a header that was never written
    known = HEADER_VERDICTS + LEGACY_VERDICTS
    # The 0.7.x header puts the verdict inside the first field and the path in the second
    # (`<role> <stage> done · <path> · <one fact>`), so there the word to ask about is the
    # last word of field one — never the closing fact, which is a sentence about the work.
    legacy_shape = len(fields) > 1 and _is_path(fields[1])
    if not legacy_shape and len(fields) > 1:
        tail = fields[-1].split()
        if tail and not (len(tail) == 1 and tail[0] in known) and len(tail) <= 6 \
                and not _is_path(fields[-1]):
            return {"word": fields[-1], "where": "field"}
    if len(words) > 2 and words[-1] not in known:
        return {"word": words[-1], "where": "word"}
    return {}


def _row_candidate(line: str) -> dict:
    """`<id> · <word>` whose word is not a state of the vocabulary, or {}."""
    fields = [f.strip() for f in SEPARATOR.split(line, 2)]
    if len(fields) < 2 or not fields[0] or " " in fields[0] or _row_state(fields[1]):
        return {}
    word = fields[1]
    # A row's state is one token in the form; two or three words are still a word somebody
    # reached for (`stays red`, `never executed`), a sentence is a sentence. A path in that
    # place is the 0.7.x digest's second field, not a state nobody spelled right.
    if not word or len(word.split()) > 3 or _is_path(word):
        return {}
    return {"id": fields[0], "word": word}


def askable(text: str) -> dict:
    """{"verdict": {...} or {}, "rows": [{"index", "id", "word", "line"}]} — the spelling
    questions a failing digest raises, each carrying the one line it lives on."""
    lines = _lines(text)
    out = {"verdict": {}, "rows": []}
    if not lines:
        return out
    header, error = _parse_header(lines[0])
    if error:
        candidate = _verdict_candidate(lines[0])
        if candidate:
            out["verdict"] = {**candidate, "index": 0, "line": lines[0],
                              "role": header.get("role", ""), "stage": header.get("stage", "")}
    for index, line in enumerate(lines[1:], start=1):
        row, _ = _parse_row(line)
        if row:
            continue
        candidate = _row_candidate(line)
        if candidate:
            out["rows"].append({**candidate, "index": index, "line": line})
    return out


def apply(text: str, mapping: dict) -> str:
    """The digest with the mapped spellings in place of the words the judge was asked about.

    `mapping` is {"verdict": "<one of HEADER_VERDICTS>", "rows": {index: "<state>"}}. The
    result is the digest's own lines, decoration removed — which is all `parse` ever reads."""
    lines = _lines(text)
    verdict = str((mapping or {}).get("verdict") or "")
    rows = (mapping or {}).get("rows") or {}
    spots = askable(text)
    out = []
    for index, line in enumerate(lines):
        if index == 0 and verdict and spots["verdict"]:
            fields = [f.strip() for f in SEPARATOR.split(line)]
            if spots["verdict"]["where"] == "field":
                fields[-1] = verdict
            else:
                words = fields[0].split()
                words[-1] = verdict
                fields[0] = " ".join(words)
            out.append(" · ".join(fields))
            continue
        if index in rows:
            fields = [f.strip() for f in SEPARATOR.split(line, 2)]
            fields[1] = str(rows[index])
            out.append(" · ".join(fields))
            continue
        out.append(line)
    return "\n".join(out)


# --- the form defects code repairs itself --------------------------------------------------------
# On project run 14857, 21 of the 26 gate blocks said "your final message is not the handoff form"; why
# they said it was NOT investigated, so how many of them the four defects below cover is unknown (not
# measured). The four are the form defects whose fix is a fact the digest and the dispatch already
# hold: prose before the header, a missing path line, a reason of 81+ characters, an absolute path
# (trailing prose after the path line, junk between rows, missing rows, two headers and a halt under
# prose are NOT covered). The repair is code's
# because every one of the four is a fact the digest and the dispatch already hold; nothing here
# is a judgment about the work. The CLOSED list below is the whole of what `canonical` may touch:
# the verdict, the item ids and the states are never edited, no row is added or removed, and a
# digest with any other defect (or a halt) is left exactly as refused today. The direction of
# error is "not repaired": `None` is the refusal the gate gave before this existed.
FIXABLE = ("prose_before_header", "path_from_witness", "reason_cut", "path_relative")


def _relative_under(path: str, task_root) -> str:
    """The task-relative spelling of an absolute `path` that lies UNDER `task_root`, else "" (outside it, `..` that
    leaves it, a symlink that leaves it, the root itself, no root given, anything unresolvable: all "")."""
    if not task_root:
        return ""
    try:
        root = Path(task_root).resolve()
        rel = Path(path).resolve().relative_to(root)
    except (OSError, ValueError, RuntimeError):
        return ""
    text = rel.as_posix()
    return "" if text in ("", ".") else text


def _cut_reason(line: str) -> str:
    """The row `line` with its reason cut to 79 characters + `…` (80 in all); the id, the state and the separators stay."""
    seps = list(SEPARATOR.finditer(line))
    if len(seps) < 2:
        return line
    head, reason = line[:seps[1].end()], line[seps[1].end():].strip()
    return head + reason[:REASON_MAX - 1] + "…" if len(reason) > REASON_MAX else line


def canonical(text: str, expected_ids: list | None = None, witness_path: str | None = None,
              task_root=None) -> tuple:
    """`(digest text | None, [repairs applied, each a member of FIXABLE])`.

    The digest `text` with exactly the `FIXABLE` defects mended, or None: nothing to mend, or a defect outside the
    list. (i) prose BEFORE the one header line is dropped; (ii) no path line and `witness_path` (the caller has
    checked the file is there) is appended as the path; (iii) a row reason over `REASON_MAX` is cut to 79 + `…`;
    (iv) an absolute path UNDER `task_root` becomes task-relative. INVARIANTS: the verdict, the id and the state of
    every row are those of the input; no row is added or deleted (a row for an id outside `expected_ids` stays); a
    halting digest is never mended (the halt is heard as written, and a halt under prose keeps its refusal); two
    header lines, a line before the header that is itself a row or a path, and any other line out of the form are
    left for `check` to refuse. The caller judges the result with `check` before it trusts it."""
    lines = _lines(text)
    heads = [i for i, line in enumerate(lines) if not _parse_header(line)[1]]
    if len(heads) != 1:
        return None, []
    at = heads[0]
    header, _ = _parse_header(lines[at])
    if header.get("verdict") in HALTING_VERDICTS:
        return None, []
    repairs = []
    if at:
        if any(_parse_row(line)[0] or _is_path(line) for line in lines[:at]):
            return None, []
        repairs.append("prose_before_header")
    out = [lines[at]]
    body = lines[at + 1:]
    has_path = bool(header.get("path"))
    for index, line in enumerate(body):
        if _parse_row(line)[0]:
            cut = _cut_reason(line)
            if cut != line:
                repairs.append("reason_cut")
            out.append(cut)
            continue
        if _is_path(line) and (not has_path or index == len(body) - 1):
            has_path = True
            if ABSOLUTE_RE.match(line):
                relative = _relative_under(line, task_root)
                if relative:
                    repairs.append("path_relative")
                    line = relative
            out.append(line)
            out.extend(body[index + 1:])
            break
        out.append(line)
    if not has_path and witness_path:
        repairs.append("path_from_witness")
        out.append(str(witness_path))
    if not repairs:
        return None, []
    return "\n".join(out), list(dict.fromkeys(repairs))


def refusal(role: str, errors: list) -> str:
    """The one message the exit gate prints: the form once, then what did not fit it."""
    item = ROLE_ITEM.get(role, "item in scope")
    head = (f"digest: your final message is not the handoff form. The orchestrator reads it "
            f"whole on every later turn, so it is exactly: `{FORM}` — one row per {item}. ")
    # EVERY error, in one line: a role shown five of twelve repairs one turn at a time. No ceiling here, because the one
    # consumer (`exit_gate.digest_errors`) hands this text to the gate's record, whose own ceiling and file
    # (`state/findings/exit-gate-<role>.txt`) hold a long one; the CLI below prints the same whole text.
    shown = DV.joined(errors, noun="error", max_chars=None)
    # Whose work this is, in the one sentence a driver routes on: the form is the role's own
    # last line, and nobody else — a person least of all — can write it for them.
    from role_cli import REPAIR_MARKER
    return head + "What does not fit: " + shown + f". {REPAIR_MARKER}."


# --- the template a brief carries (F11, t-1701 D5-C) -------------------------------------------------------------
# Code fills in what code KNOWS about the dispatch - the label, the ids of its scope and the stage's witness path - and
# leaves every `<...>` (the verdict, each state, each reason) to the role (AR-7). Advice only: `check`, `parse`, `canonical`
# and `refusal` do not read it, and a role that ignores it is judged as before.
TEMPLATE_ROWS = 40          # ids written as rows; beyond it ONE tail line names the rest
TEMPLATE_TAIL_CHARS = 600   # the tail line is cut here and ends with "..." (at most TEMPLATE_TAIL_CHARS + 1 characters)
TEMPLATE_PATH_PLACEHOLDER = "<task-relative path of the artifact>"


def template(role: str, stage: str, label: str, scope, path, max_rows: int = TEMPLATE_ROWS) -> str:
    """The digest form of one dispatch with every id of its scope already a row. An id is written as it is (never edited);
    a repeated id is written once; an empty scope gives the header and the path line; no path gives a placeholder."""
    ids = list(dict.fromkeys(str(i).strip() for i in (scope or []) if str(i).strip()))
    lines = [f"{role} {stage} {label} · <ok|concerns|halt|impossible>"]
    lines += [f"{i} · <state> · <reason, at most {REASON_MAX} characters>" for i in ids[:max_rows]]
    rest = ids[max_rows:]
    if rest:
        tail = f"… and {len(rest)} more ids of your scope, one line each: {', '.join(rest)}"
        if len(tail) > TEMPLATE_TAIL_CHARS:
            tail = tail[:TEMPLATE_TAIL_CHARS] + "…"
        lines.append(tail)
    lines.append(str(path).strip() if path and str(path).strip() else TEMPLATE_PATH_PLACEHOLDER)
    lines.append("States: " + ", ".join(BASE_STATES + ITEM_STATES))
    return "\n".join(lines)


def main() -> int:
    C.force_utf8()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="a file holding the final message (default: stdin)")
    ap.add_argument("--scope", default="", help="comma-separated ids the dispatch was scoped to")
    ap.add_argument("--role", default="", help="the role, for the item named in the refusal")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args()
    text = Path(ns.file).read_text(encoding="utf-8", errors="replace") if ns.file else sys.stdin.read()
    ids = [part.strip() for part in ns.scope.split(",") if part.strip()]
    errors = check(text, ids)
    if ns.json:
        import json
        print(json.dumps({**parse(text), "scope_errors": errors}, ensure_ascii=False, indent=1))
    elif errors:
        print(refusal(ns.role, errors))
    else:
        print("digest: in the form")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
