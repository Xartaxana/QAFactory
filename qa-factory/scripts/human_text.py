#!/usr/bin/env python3
"""Does a text the factory shows a person obey `references/human-questions.md`?

The rules were written after two measured failures and then held only as prose, so the next
boundary broke them again: on TP1-13797 run 5, 16 of the 76 conductor sessions answered
`ask_person` with an EMPTY question, and the person got the filler "The conductor needs your
word." with the refusal's own text pasted underneath - seven detector lines and two form field
paths. That family cost more conductor money than any factory refusal did ($9.01 over 21
sessions), because a person answering a question that is not one answers in free prose, and
somebody then has to work out what it meant.

What this checks is the SHAPE of our own output, never anybody's meaning. That distinction is
the whole of FR-12: code may see that a script name stands in the body of a question; what a
person's answer means is theirs and the conductor's to read, and nothing here looks at an
answer. The shapes live in `references/human-text.json`, not in this file (FR-13), and the
prose that explains each of them is `references/human-questions.md`.

Rule 5 of that file gives the `how to answer` block the opposite licence: there a script name
and a flag are the instruction to type. So the body is what is checked and the block is not;
`split(text)` is where that line is drawn.

    human_text.py --file <path> [--json]     # exit 1 when the text breaks a rule
    human_text.py --selftest

`problems()` returns findings; it never edits the text and never refuses to show it. A question
that breaks a rule still reaches the person - our defect is not their problem - and the finding
is what the run records (FR-41: the defect is stated, not hidden).
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hooklib  # noqa: E402

RULES_FILE = "human-text.json"


def rules() -> dict:
    return hooklib.load_ref_json(RULES_FILE) or {}


def head_re(spec: dict | None = None):
    """The machine head the driver writes above a question (`# Driver question`, `kind:`,
    `stage:`, `dispatch: <id>`, `asked_at:`). One source: `story_run.QUESTION_HEAD_RE` is meant
    to be this pattern, so the text that is hashed and the text that is checked lose the same
    lines. A rules file that names none gives a pattern that matches nothing: nothing is
    stripped, and `selftest` says the file is incomplete."""
    spec = spec if spec is not None else rules()
    pattern = str(spec.get("head_pattern") or "")
    return re.compile(pattern) if pattern else re.compile(r"(?!)")


HEAD_RE = head_re()


def split(text: str, spec: dict | None = None, strip_head: bool = True) -> tuple:
    """(body, how to answer). The block starts at the first marker the rules name; the
    question head is not part of the body - it is our own machine line, and the person is
    not asked about a dispatch id that stands in it."""
    spec = spec if spec is not None else rules()
    body = str(text or "")
    if strip_head:
        body = head_re(spec).sub("", body, count=1)
    cut = len(body)
    for marker in spec.get("how_to_answer_markers") or []:
        found = body.find(marker)
        if 0 <= found < cut:
            cut = found
    return body[:cut], body[cut:]


def _applies(item: dict, kind: str) -> bool:
    kinds = item.get("applies_to")
    return not kinds or kind in kinds


def _linked(link: dict, token: str, body: str, start: int) -> bool:
    """Does the line this id stands on carry the file the id names? A case id that is the text
    of a link to its case file, or whose file path sits beside it, is explained by the file
    itself: the person opens it and reads what the case is. Which ids this holds for, and what
    a link or a path looks like, is data (`link_explains` in the rules file), and it is the
    SAME line only - a link two lines away explains nothing to a reader of this one."""
    if not re.match(str(link.get("ids") or "(?!)"), token):
        return False
    line = body[body.rfind("\n", 0, start) + 1:]
    line = line.split("\n", 1)[0]
    for shape in link.get("shapes") or []:
        for found in re.finditer(str(shape).replace("{token}", re.escape(token)), line):
            # A link written inside a code span is text about a link, not a link.
            if line[:found.start()].count("`") % 2 == 0:
                return True
    return False


def _unexplained(item: dict, body: str) -> list:
    """Distinct ids whose FIRST mention is not followed by an explanation shape. Later
    mentions are free: once said what `TS-14` is, the reader has it."""
    pattern, explanation = str(item.get("pattern") or ""), str(item.get("explanation") or "")
    link = item.get("link_explains") or {}
    # `{id}` in the explanation is the id shape itself: "TS-14, TS-15" is a list, not an
    # apposition, so a comma explains an id only when no other id follows it.
    explanation = explanation.replace("{id}", "(?:" + pattern + ")")
    parens = item.get("explained_in_parens") or {}
    if not pattern:
        return []
    seen, bad = set(), []
    for match in re.finditer(pattern, body):
        token = match.group(0)
        if token in seen:
            continue
        seen.add(token)
        after = body[match.end():]
        if explanation and re.match(explanation, after):
            continue
        # "the import limit (TS-14)": the id names the words before it, so the reader has it.
        if (parens.get("before") and parens.get("after")
                and re.search(str(parens["before"]), body[:match.start()])
                and re.match(str(parens["after"]), after)):
            continue
        # `[TC-014](work/test-cases/x/TC-014.md)`: the case file is one click away.
        if link and _linked(link, token, body, match.start()):
            continue
        bad.append(token)
    return bad


ONBOARDING_NOTE = "The onboarding step that records a stand: `/qa-factory:qa-onboarding`."


def onboarding_note(environment, stands) -> str:
    """The line for the ANSWER BLOCK of a stand question (`Person.answer_note`, t-373 F7: ONE shape for `stand_check` and
    the three `s1_review` sites): the plugin's command is something to type (human-questions.md rule 5), so it never
    stands in the body. It is given only in the case whose body says "the onboarding step named below": no stand named
    and none recorded. Lives here, with the rule that forbids the command in a body, so the text has one source."""
    return ONBOARDING_NOTE if not environment and not stands else ""


def config_roots(item: dict) -> set:
    """The roots of the factory's own configuration: the part before the first dot of every key of the table the row
    names (`roots_table` of the reference file `roots_file`, references/config-keys.json: one source for the keys,
    FR-13). A table that cannot be read gives no root, and the row then finds nothing - it never raises."""
    try:
        table = hooklib.load_ref_json(str(item.get("roots_file") or "")).get(str(item.get("roots_table") or ""))
    except Exception:
        return set()
    return {str(key).split(".", 1)[0] for key in table} if isinstance(table, dict) else set()


def config_keys(item: dict) -> set:
    """Every key the table lists, whole (`environment.access`, `driver.child_env.keep`, and the top-level ones)."""
    try:
        table = hooklib.load_ref_json(str(item.get("roots_file") or "")).get(str(item.get("roots_table") or ""))
    except Exception:
        return set()
    return {str(key) for key in table} if isinstance(table, dict) else set()


def _config_key(item: dict, body: str) -> str:
    """The first dotted path in `body` that is a key of OUR configuration: it matches the row's shape (a name may carry
    a `[...]` selector) and its first name, a trailing `[...]` dropped, is a root. Three or more names are enough; TWO
    names count only when the table LISTS that key whole (`environment.access`) - `external_writes.bugs` or
    `cost.json` is a root followed by a word, and is left to the person's own reading. An image label, a host name or a
    module path has the same shape and a first name that is not a root: it is a fact about the person's world, not our
    jargon."""
    roots = config_roots(item)
    if not roots:
        return ""
    listed = config_keys(item)
    # The action-line exemption (`action_lines`, t-373 F9, B-220 F3) is applied by `_row_text` before this row looks at the body.
    # a dotted name whose LAST name is a file extension or a top-level domain is a file or a host, never a key (F8)
    skip = {str(name).lower() for name in item.get("skip_last_names") or []}
    for match in re.finditer(str(item.get("pattern") or "(?!)"), body):
        names = re.findall(r"(?:^|\.)([a-z][a-z0-9_]*)(?:\[[^\]\n]*\])?", match.group(0))
        if names and names[0] in roots and names[-1].lower() not in skip and (len(names) > 2 or ".".join(names) in listed):
            return match.group(0)
    return ""


class LabelsUnreadable(Exception):
    """`price_lines.labels` of the rules file is missing or holds fewer than the three labels item 6 names."""


def price_labels(spec: dict | None = None) -> list:
    """The three labels that follow every option of a question (`price_lines` of the rules file; item 6 of
    references/human-questions.md names the same three). The renderer of the seam reads them from here: fewer than
    three raises `LabelsUnreadable`, so a question is never rendered with options that carry no (or half) price lines;
    the seam then asks the last-resort question and journals the defect (C1-1)."""
    spec = spec if spec is not None else rules()
    labels = [str(label) for label in (spec.get("price_lines") or {}).get("labels") or []]
    if len(labels) < 3:
        raise LabelsUnreadable(f"price_lines.labels holds {len(labels)} of the 3 labels item 6 names")
    return labels


PRICED_HEADING = "## What each answer costs and does"
OPTION_LINE = re.compile(r"\(?[a-z]\)\s+\S", re.IGNORECASE)


def _followed(lines: list, index: int, labels: list) -> bool:
    return all(lines[index + 1 + n:index + 2 + n][:1] and lines[index + 1 + n].startswith(label)
               for n, label in enumerate(labels))


def price_problems(text: str, offered, spec: dict | None = None) -> list:
    """[{rule, why, found}] for each option whose line is not followed by the three price labels in order (item 6).
    Two readings, both on the body (the part before the answer block):
      * each OFFERED token: an option line is `(a) `token` ...`; a prose list that repeats the option without the lines is fine
        as long as ONE option line of the token carries them;
      * EVERY option line `(x) ...` of the priced section (the lines under `PRICED_HEADING`, up to the next heading), token or
        not - an option with no token (`(b) paste the ticket`) is offered to nobody by name and was never checked by the first
        reading. A text with no such section has no second reading.
    Nothing is read from the words of the options (FR-12)."""
    try:
        labels = price_labels(spec)
    except LabelsUnreadable:
        return []                         # a detector never raises on its own data: no labels, no price check (as before)
    body = split(text, spec)[0]
    lines = [line.strip().removeprefix(">").strip() for line in body.splitlines()]
    why = "item 6: every option is followed by " + ", ".join(f"`{label}`" for label in labels)
    found = []
    for token in offered or []:
        starts = [i for i, line in enumerate(lines)
                  if re.match(r"\(?[a-z]\)\s*`" + re.escape(str(token)) + r"`", line, re.IGNORECASE)]
        if not any(_followed(lines, i, labels) for i in starts):
            found.append({"rule": "price_lines", "found": str(token), "why": why})
    if PRICED_HEADING in lines:
        start = lines.index(PRICED_HEADING) + 1
        end = next((i for i in range(start, len(lines)) if lines[i].startswith("#")), len(lines))
        named = [f"`{item['found']}`" for item in found]          # an option already reported by its token is not reported twice
        for i in range(start, end):
            if OPTION_LINE.match(lines[i]) and not _followed(lines, i, labels) and not any(mark in lines[i] for mark in named):
                found.append({"rule": "price_lines", "found": lines[i][:80], "why": why})
    return found


def problems(text: str, spec: dict | None = None, kind: str = "question", offered=None) -> list:
    """[{rule, why, found}] - every rule this text breaks, in the order of the rules file.

    kind="question": a text the driver or a role puts to a person - the head is removed, the
    body must carry the six parts and end in an answer block. kind="report": a section of a
    document a person reads (no answer block, no floor, no filler), checked by the shape rows
    that apply to a report. `offered`: the tokens the question offers; each must carry its price lines."""
    spec = spec if spec is not None else rules()
    report_kind = kind == "report"
    body, how = (str(text or ""), "") if report_kind else split(text, spec)
    found = []
    if not report_kind:
        stripped = body.strip()
        for filler in spec.get("filler") or []:
            if filler and filler in body:
                found.append({"rule": "filler", "found": filler,
                              "why": "a sentence that says a person is needed is not a question: say what "
                                     "the factory did, what it cannot decide, and what the answers are"})
        floor = int(spec.get("min_body_chars") or 0)
        if floor and len(stripped) < floor:
            found.append({"rule": "too_short", "found": f"{len(stripped)} characters",
                          "why": f"under {floor} characters the six required parts cannot all be there"})
        if not how.strip():
            found.append({"rule": "no_how_to_answer", "found": "",
                          "why": "rule 5: the text ends with how to answer, in its own block"})
        found += price_problems(text, offered, spec)
    return found + _shape_found(body, spec, kind)


def shape_problems(text: str, spec: dict | None = None, kind: str = "question") -> list:
    """The SHAPE rows alone (the `forbidden` table) for a fragment that will stand INSIDE a text a person reads - a line
    of a list, a name - with none of the whole-text rules (the five parts, the floor, the answer block). `kind` picks the
    rows that apply (`question`: the packet's own check, t-373 F3)."""
    spec = spec if spec is not None else rules()
    return _shape_found(str(text or ""), spec, kind)


def _action_lines(spec: dict) -> dict:
    """The `action_lines` block of the rules file (FR-13): the line prefixes of an ACTION slot (`the fix:` / `where:` of the
    stand-gap card, t-373 F9; `I propose to run` of the sentence that offers a changed test command; `To add a stand:`), the
    rows a backquoted COMMAND on such a line is exempt from, and the t-373 rule that a card's `the fix:` / `where:` line is a
    whole-line slot for the config-key row (the card writes the setting's place without quotes)."""
    block = spec.get("action_lines")
    return block if isinstance(block, dict) else {}


def _row_text(body: str, row_id: str, block: dict) -> str:
    """`body` as one row of the table is to see it. B-220 F3 (the Lead's decision after the critic): the owner allowed ONE
    thing on an action line - the proposed command, in backquotes - so for the `command_span_rows` the backquoted spans of
    an action line are taken out, and nothing else is: an exit code, a bare flag outside the quotes, a form field stay
    in the text for every row, and every other line is the body. A row listed in `whole_line` also drops the whole line of
    those prefixes (the t-373 config-key slot of a card).
    t-305 N8 attempt 2 (F7, the owner's ruling): a line that starts with a `quoted_words` prefix quotes a PERSON's own words
    in a code span - verbatim, as recorded - and that span is taken out for EVERY row (the factory's part of the line stays
    in the text and is still judged, row by row, as everywhere else); the exemption is the span's position, no phrase."""
    prefixes = tuple(str(p) for p in block.get("prefixes") or [] if p)
    quoted = quoted_prefixes(block)
    if not prefixes and not quoted:
        return body
    whole = tuple(str(p) for p in (block.get("whole_line") or {}).get(row_id) or [] if p)
    spans = row_id in (block.get("command_span_rows") or [])
    lines = []
    for line in body.split("\n"):
        head = line.lstrip()
        if whole and head.startswith(whole):
            continue
        split = quoted_split(line, block) if quoted else None
        if split:
            line = split[0] + split[2]
        elif spans and head.startswith(prefixes):
            line = re.sub(r"`[^`\n]*`", "", line)
        lines.append(line)
    return "\n".join(lines)


def quoted_prefixes(block: dict) -> tuple:
    """The line prefixes of `action_lines.quoted_words` (data, FR-13): the leads of the line that quotes a person's words."""
    found = block.get("quoted_words") if isinstance(block, dict) else None
    return tuple(str(p) for p in (found or {}).get("prefixes") or [] if p) if isinstance(found, dict) else ()


def quoted_split(line: str, block: dict | None = None):
    """`(before, span, after)` when `line` is EXACTLY the line the factory renders for a person's quoted words, else None -
    THE one definition of the exemption, read by `_row_text` (the shape rows) and `without_quoted_words` (the report
    validator). The line is `<lead>, the <profile> tests ran: <span> (<date>)...`: the lead is DATA (`quoted_words.prefixes`),
    the profile has no backquote, and `span` is ONE Markdown code span - a run of N backquotes, the words, the FIRST later
    run of exactly N backquotes (so words that carry a backquote are quoted with a longer run, `report_facts._inline_code`) -
    followed at once by ` (`, the date. Anything else is None, and the whole line is judged as usual: the lead followed by
    different text, a closing run not followed by the date (a second span after it), a line with no span (empty words), a
    line that does not begin with the lead. `before` ends where the span's opening run begins; `after` starts at ` (`."""
    block = block if block is not None else _action_lines(rules())
    leads = quoted_prefixes(block)
    if not leads:
        return None
    head = re.match(r"\s*(?:" + "|".join(re.escape(p) for p in leads) + r"), the [^`\n]+? tests ran: (`+)(?!`)", str(line))
    if not head:
        return None
    fence, rest = head.group(1), str(line)[head.end():]
    for run in re.finditer(r"`+", rest):
        if len(run.group()) == len(fence):
            after = rest[run.end():]
            return (str(line)[:head.start(1)], rest[:run.start()], after) if after.startswith(" (") else None
    return None


def without_quoted_words(text: str, spec: dict | None = None) -> str:
    """`text` with the quoted span of every line `quoted_split` recognises taken out: what is left is the FACTORY's own
    writing, which every reader of a finished text (the report's forbidden needles, a bare decision id) still judges."""
    block = _action_lines(spec if spec is not None else rules())
    if not quoted_prefixes(block):
        return str(text or "")
    out = []
    for line in str(text or "").split("\n"):
        split = quoted_split(line, block)
        out.append(split[0] + split[2] if split else line)
    return "\n".join(out)


def _shape_found(body: str, spec: dict, kind: str) -> list:
    found = []
    block = _action_lines(spec)
    full_body = body
    for item in spec.get("forbidden") or []:
        body = _row_text(full_body, str(item.get("id") or ""), block)
        if not _applies(item, kind):
            continue
        if item.get("kind") == "explained_ids":
            bad = _unexplained(item, body)
            if bad:
                found.append({"rule": str(item.get("id") or "explained_ids"),
                              "found": ", ".join(bad), "why": str(item.get("why") or "")})
            continue
        if item.get("kind") == "config_key_path":
            hit = _config_key(item, body)
            if hit:
                found.append({"rule": str(item.get("id") or "config_key_path"), "found": hit,
                              "why": str(item.get("why") or "")})
            continue
        whole = str(item.get("except_whole") or "")
        for match in re.finditer(str(item.get("pattern") or ""), body):
            # A code span that is ENTIRELY a file name or a path names a place, not a state.
            if whole and re.fullmatch(whole, match.group(0).strip("`")):
                continue
            found.append({"rule": str(item.get("id") or "forbidden"),
                          "found": match.group(0), "why": str(item.get("why") or "")})
            break
    return found


def section_of(markdown: str, heading: str) -> str:
    """The text under the first line that starts with `heading`, up to the next heading of the
    same or a higher level; the heading line itself is not part of it. '' when absent.

    A `#` line inside a fenced block (``` or ~~~) is a comment of the quoted code, not a
    heading: it does not end the section (a pasted error under a fence would otherwise be
    cut off from the check). A fence that never closes keeps the rest of the text inside the
    section - the check reads more, never less."""
    lines = str(markdown or "").splitlines()
    level = len(heading) - len(heading.lstrip("#"))
    fence, start, end = "", None, len(lines)
    for i, line in enumerate(lines):
        opener = re.match(r"\s*(```|~~~)", line)
        if fence:
            if opener and opener.group(1) == fence:
                fence = ""
            continue
        if opener:
            fence = opener.group(1)
            continue
        if start is None:
            if line.startswith(heading):
                start = i
            continue
        mark = re.match(r"(#+)\s", line)
        if mark and len(mark.group(1)) <= max(level, 1):
            end = i
            break
    return "" if start is None else "\n".join(lines[start + 1:end])


def section_problems(markdown: str, heading: str, spec: dict | None = None) -> list:
    """The report rules over one section of a document. An absent or empty section has no
    problem: whether it should exist is the report contract's question, not this one's."""
    text = section_of(markdown, heading)
    return problems(text, spec, kind="report") if text.strip() else []


def report(text: str, kind: str = "question") -> str:
    """One line per problem, for a log or a finding. '' when the text is clean."""
    return "\n".join(f"- {p['rule']}: `{p['found']}` — {p['why']}" for p in problems(text, kind=kind))


CLEAN = """The test plan for this story is written and every row but one is decided.

Row TS-14 (the import size limit) says the import must reject a payload over the size limit, and nothing in the code or
the ticket says what that limit is - the two places that mention it disagree, so the factory
cannot choose without inventing a requirement.

What I need from you is that number, or one of:
(a) I will test the limit the code has today and record it as the requirement;
(b) you name the limit;
(c) the limit is out of scope for this story.

---
Answer: write your words to a file and run
  python story_run.py --task QA-9 --answer <file>
"""

DIRTY = """The conductor needs your word.

Refusal:
exit gate for S3-qa-test-strategist-1 (qa-test-strategist, S3): planning_contract.py: REAL exit 1
- TS-14: low depth requires evidenced bounded effect; header.verdict: not filled

---
Answer: write your words to a file and run
  python story_run.py --task QA-9 --answer <file>
"""


TAIL = "\n\n---\nAnswer: write your words to a file and run\n  python story_run.py --task QA-9 --answer <file>\n"
PAD = "The plan is written and one row waits for a decision that only you can make here. "

# What TP1-13877 put in front of the person, and the rule each must break.
DIRTY_SHAPES = {
    "relayed_markup": PAD + "The service answered: <!DOCTYPE html><html><head><title>Just a moment"
                            "</title></head><body>cf-ray 8a1</body></html>" + TAIL,
    "relayed_traceback": PAD + "It failed with Traceback (most recent call last): File x" + TAIL,
    "dispatch_id": PAD + "S3-qa-test-strategist-1 stopped without a reason." + TAIL,
    "explained_ids": PAD + "OBL-7 is open and nothing says why." + TAIL,
    "slash_command": PAD + "The tool says: Not logged in - Please run /login" + TAIL,
    # t-363 B3: the config question once carried the adapter's own sentence in its body.
    "config_key": PAD + "The tracker's setting adapters.ticket.direct_api.base_url is not recorded." + TAIL,
    "plugin_command": PAD + "Run /qa-factory:qa-onboarding to record it." + TAIL,
}


def selftest() -> int:
    spec = rules()
    bad = []
    if not spec.get("forbidden"):
        bad.append(f"references/{RULES_FILE} carries no rules")
    if not spec.get("head_pattern"):
        bad.append(f"references/{RULES_FILE} names no head_pattern: the question head would be checked")
    clean = problems(CLEAN, spec)
    if clean:
        bad.append(f"a text that obeys the rules was refused: {clean}")
    dirty = {p["rule"] for p in problems(DIRTY, spec)}
    # The measured question, rule by rule: the filler, the relayed refusal, the script name,
    # the exit code and the form field - each of them was on the person's screen at S3.
    for rule in ("filler", "relayed_refusal", "script_name", "exit_code", "form_field"):
        if rule not in dirty:
            bad.append(f"the question the person was actually shown passes `{rule}`")
    # 13877's shapes: each dirty sample is caught by its own rule (an HTML page, a traceback,
    # a dispatch id, a bare row id, a slash command), and t-363's: a config key path, a plugin command.
    for rule, sample in DIRTY_SHAPES.items():
        if rule not in {p["rule"] for p in problems(sample, spec)}:
            bad.append(f"a text with the `{rule}` shape passes")
    key_row = next((r for r in spec.get("forbidden") or [] if r.get("kind") == "config_key_path"), None)
    if key_row is None or not config_roots(key_row):
        bad.append("the config_key row has no readable roots (references/config-keys.json): it would find nothing")
    if "config_key" in {p["rule"] for p in problems(PAD + "The image label org.opencontainers.image.revision is not set." + TAIL, spec)}:
        bad.append("an image label is taken for a key of the factory's configuration")
    # A case id whose file is linked on the same line is explained; the same id without the
    # link, or any other id with one, is not (the Lead's decision on gate A, t-039 F3).
    linked = PAD + "Cases: [TC-014](work/test-cases/x/TC-014.md) waits." + TAIL
    if "explained_ids" in {p["rule"] for p in problems(linked, spec)}:
        bad.append("a case id linked to its file on the same line is refused")
    for label, sample in (("a case id with no link", PAD + "Cases: TC-014 waits." + TAIL),
                          ("a link two lines away", PAD + "TC-014 waits.\n[TC-014](a/TC-014.md)" + TAIL),
                          ("another id's link", PAD + "TS-14 [TC-014](a/TC-014.md) waits." + TAIL),
                          ("a link to some other file", PAD + "TC-014 waits, see [plan](a/plan.md)." + TAIL)):
        if "explained_ids" not in {p["rule"] for p in problems(sample, spec)}:
            bad.append(f"{label} passes explained_ids")
    if problems("# Driver question - QA-9\nkind: halt\nstage: S3\ndispatch: S3-qa-test-strategist-1\n"
                "asked_at: 2026-09-29\n\n" + CLEAN, spec):
        bad.append("the question head is checked as if it were the question")
    if problems("Nothing this run; the plan was rewritten once.", spec, kind="report"):
        bad.append("a report in words was refused")
    if "review_rejected" not in {p["found"].strip("`") for p in problems("It is `review_rejected`.", spec,
                                                                          kind="report")}:
        bad.append("a ledger state in a report passes")
    body, how = split(CLEAN, spec)
    if "story_run.py" in body or "story_run.py" not in how:
        bad.append("the `how to answer` block is not where the command is allowed to be")
    if problems("x" * 400, spec) == []:
        bad.append("a text with no answer block passed")
    priced = CLEAN.replace("(a) I will test", "(a) `retry` — I will test").replace("(b) you name", "(b) `stop` — you name")
    with_lines = priced.replace(";\n(b)", ";\nthe factory: nothing runs\nyou: this answer only\nthe story: delivery waits\n(b)", 1)
    with_lines = with_lines.replace(";\n(c)", ";\nthe factory: nothing runs\nyou: nothing more\nthe story: delivery waits\n(c)", 1)
    if price_problems(with_lines, ["retry", "stop"], spec):
        bad.append("a priced option (three labels after its line) was refused")
    if len(price_problems(priced, ["retry", "stop"], spec)) != 2:
        bad.append("an option with no price lines passes `price_lines`")
    print("human_text selftest: " + ("VIOLATIONS\n  - " + "\n  - ".join(bad) if bad
                                     else f"{len(spec.get('forbidden') or [])} shapes, clean text clean, "
                                          "the measured question caught on five rules, "
                                          f"{len(DIRTY_SHAPES)} dirty shapes caught"))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--file", help="the text to check (a question file, a report section)")
    ap.add_argument("--kind", choices=("question", "report"), default="question",
                    help="report: the shape rows only, no answer block wanted")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ns = ap.parse_args()
    if ns.selftest:
        return selftest()
    if not ns.file:
        ap.error("--file or --selftest")
    text = Path(ns.file).read_text(encoding="utf-8", errors="replace")
    found = problems(text, kind=ns.kind)
    if ns.json:
        print(json.dumps({"file": ns.file, "problems": found}, ensure_ascii=False, indent=1))
    elif found:
        print(f"{ns.file}: {len(found)} rule(s) of references/human-questions.md broken:")
        print(report(text, ns.kind))
    else:
        print(f"{ns.file}: obeys references/human-questions.md")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
