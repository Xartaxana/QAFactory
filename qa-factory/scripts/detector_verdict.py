"""The verdict of a detector: one contract for the producers, one reader, one renderer (library, no CLI).

A detector (`s5_precheck.py`, `planning_contract.py`, `critic_rollcall.py`, `check_coverage.py`, `sizing.py`
without arguments, and `check_witness.py <artifact>`) answers a gate with an exit code and a text. Until C2-1 the
reader of that text took the last three lines of it, so a role refused for four findings was shown one of them and
came back four times, one repair per turn (cmp3, S5). The contract below is the one shape every producer prints
and this module is the one reader of it (FR-14: the output shape is as much a contract as the arguments).

THE CONTRACT ("form 1")
  exit 0               stdout, any text: no findings.
  exit 1 (a verdict)   stdout, the WHOLE verdict:
                         (a) context: any lines, `- ` lists of warnings included;
                         (b) one or more blocks: a header `REJECT — <n> ...` (U+2014) and right after it exactly n
                             lines, each starting with `- `, one finding = one physical line, an optional family
                             label `[<check> <id>] ` straight after the `- `, the repair on the same line after
                             ` — fix: `; the block ends on the n-th line, the next line is not a `- ` line;
                             the header may carry `WORDS_AT_SOURCE`: the producer has already judged the recorded
                             words over its own findings;
                         (c) a tail: lines that start neither with `- ` nor with `REJECT` (the door, the marker
                             `role_cli.REPAIR_MARKER` / `PERSON_MARKER`, a summary);
                         (d) before the first header, one line `WORDS_REFUSED_AT_SOURCE: <finding id> <cause>`
                             for each finding the producer refused to every recorded word (cause: `family` or
                             `predating`); the finding line carries the same id in its label.
                       (e) ADVICE blocks, at exit 0 or 1: a header `ADVICE — <n>` (U+2014) and right after it exactly n
                           lines, each starting with `- `, one line = one piece of advice, the same shape as a `REJECT`
                           block. Advice is a judgment the detector prints for the stage critic (X2-2): it never blocks
                           and never goes to the role or the person; the gate files it. A detector that has only
                           advice exits 0. An ADVICE block that breaks the shape (no count, fewer lines than declared, a
                           `- ` line past the n-th) is a `defects` entry of `parse`, never silence.
  exit 3 (unreadable)  the detector could not run its check (an exception, a missing input it needs): stdout carries
                       one line `UNREADABLE: <reason>` (`unreadable_line`). The third state of RH1-5 (FR-59): not
                       "no findings", not a finding of the role's work - the factory's own defect, which the
                       conductor takes. A `REJECT` block next to exit 3 is not read.
  other exit codes     outside the contract (a refused call, an argparse exit 2, a future code): `parse` reads them
                       as `unreadable` too, with the tail of stderr as the reason - no code but 0 is ever "clean".

The word `UNREADABLE` in `refused` (the cause `unreadable` of `WORDS_REFUSED_AT_SOURCE`, `UNREADABLE` below) is a
different thing: a text that cannot be split into findings. The new state is the `unreadable` KEY of `parse` and the
`kind="unreadable"` of a `Record` - never the `refused` field (E25).

`parse` reads a run by that contract; what does not follow it is never dropped silently (FR-59): it comes back
as one `unmigrated` text, whole. `render` is the one text of a list for a role or the conductor: whole lines in
bytes up to a ceiling, and past it a count and the path of the file that holds the whole list. `split_items` and
`refusal_text` read the combined refusal head of the controller (`N problems - the request is refused whole`).

The one-line twins of `render` (C3-8/9): a sentence or a report cell cannot hold a `- ` block, so `joined` is the list
in one line (all items, or the items that fit and one trailing part `(+K more ... - the whole list: <place>)`), `named`
is the ids inside ONE finding (`a, b and K more (<where>)`), and `compound` builds the combined refusal that
`split_items` reads. A site that shows a computed list calls one of the three and keeps no `[:N]` / `and N more` of its
own: a count never appears without a place where the rest can be read (FR-1, FR-15).
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from role_cli import PERSON_MARKER, REPAIR_MARKER  # noqa: E402

# The ceiling of a list shown to a role or the conductor, in BYTES (UTF-8), never in lines. The precedent is the
# conductor prompt's question ceiling (`qtext[:6000]`); what lies past it is counted and kept in a file.
FINDINGS_MAX_BYTES = 6000
# The label of a producer that judged the recorded words at its own source. It rides in the header of the output.
WORDS_AT_SOURCE = "(words judged at source)"
# The line a producer prints for each finding it refused to every recorded word; `*` does not open it either.
WORDS_REFUSED_AT_SOURCE = "WORDS_REFUSED_AT_SOURCE:"
REFUSAL_CAUSES = ("family", "predating")
UNREADABLE = "unreadable"

HEAD_RE = re.compile(r"^REJECT — (\d+)\b")
ADVICE_HEAD_RE = re.compile(r"^ADVICE — (\d+)\b")
ADVICE_KIND = "advice"        # the `kind` of a Record that is advice: the gate never blocks on it (X2-2)
LABEL_RE = re.compile(r"^\[(\S+) (\S+)\] ")
COMPOUND_HEAD = "{n} problems - the request is refused whole, every one is listed:"
COMPOUND_HEAD_RE = re.compile(r"^(\d+) problems - the request is refused whole, every one is listed:$", re.MULTILINE)
ITEM_RE = re.compile(r"^\d+\) ")
STORY_STEP_PREFIX = "story_step: refused - "
# The end of the defect `parse` writes for a refusal that printed nothing: the ONE spelling, so the gate that tells the
# role whose defect it is (`exit_gate.detector_records`) matches a constant and not a copy of the sentence.
PRINTED_NOTHING = "printed nothing"
# The third state of the contract (RH1-5): a detector that could not run its check exits 3 and prints this prefix.
EXIT_UNREADABLE = 3
UNREADABLE_PREFIX = "UNREADABLE: "
EXIT_CODES = (0, 1, EXIT_UNREADABLE)
# Ids named inside one finding: how many are spelled out before `and K more` (`gate_preflight.LIST_LIMIT` is the twin).
LIST_LIMIT = 6


class Record(str):
    """One record of the exit gate: an ordinary string (printing, JSON, `finding_key`, `split_overridden` see a
    `str`) that also says where it came from and what may judge it. A plain `str` read without these attributes
    is `kind="finding"`, `words="gate"`, `refused=""`."""
    script = ""
    words = "gate"
    kind = "finding"
    refused = ""

    def __new__(cls, text, *, script="", words="gate", kind="finding", refused=""):
        obj = super().__new__(cls, text)
        obj.script, obj.words, obj.kind, obj.refused = script, words, kind, refused
        return obj


def one_line(text) -> str:
    """A finding is ONE physical line: a producer prints its text through this."""
    return re.sub(r"\s*[\r\n]+\s*", " ", str(text)).strip()


def id_token(finding_id) -> str:
    """The id of a finding as it is printed (no whitespace, no `]`): the label of the finding line and the
    `WORDS_REFUSED_AT_SOURCE` line are built from this one function, so the reader ties them by equality."""
    return re.sub(r"[\s\]]+", "_", str(finding_id))


def refusal_line(finding_id, cause) -> str:
    return f"{WORDS_REFUSED_AT_SOURCE} {id_token(finding_id)} {cause}"


# --- the reader ------------------------------------------------------------------------------------------------

def _tag_lines(lines: list) -> tuple:
    """`([(finding id, cause, line)], [defect])` for every `WORDS_REFUSED_AT_SOURCE` line. A line whose cause is
    missing or unknown names its finding all the same, with the cause `unreadable`: the finding stays refused."""
    tags, defects = [], []
    for line in lines:
        if not line.startswith(WORDS_REFUSED_AT_SOURCE):
            continue
        parts = line[len(WORDS_REFUSED_AT_SOURCE):].strip().rsplit(None, 1)
        if len(parts) == 2 and parts[1] in REFUSAL_CAUSES:
            tags.append((parts[0], parts[1], line))
            continue
        tags.append((parts[0] if parts else "", UNREADABLE, line))
        defects.append(f"the line '{line}' gives no known cause (family or predating): "
                       "the source refusal cannot be read")
    return tags, defects


def _has_head(lines: list) -> bool:
    return any(HEAD_RE.match(line) for line in lines)


def _blocks(lines: list) -> dict:
    """The blocks of one stream by the contract: `findings`, the `heads`, `short` (an output cut off at its end),
    `bad` (blocks that break the contract: `(head, line number, n, why)`), `tail_from` (the first line after the
    last block)."""
    found = {"findings": [], "heads": [], "short": [], "bad": [], "tail_from": 0}
    last = None
    i = 0
    while i < len(lines):
        line = lines[i]
        match = HEAD_RE.match(line)
        if match:
            n, got, j = int(match.group(1)), [], i + 1
            while len(got) < n and j < len(lines) and lines[j].startswith("- "):
                got.append(lines[j][2:])
                j += 1
            last = (line, i + 1, n)
            found["heads"].append(line)
            if len(got) < n and j < len(lines):
                found["bad"].append((line, i + 1, n, f"interrupted after {len(got)}"))
            elif len(got) < n:
                found["short"].append(f"declared {n} finding(s) and printed {len(got)}")
            found["findings"] += got
            found["tail_from"] = i = j
            continue
        if line.startswith("REJECT"):
            found["bad"].append((None, i + 1, 0, "a REJECT line with no count"))   # `parse` names it under a label
        elif line.startswith("- ") and last is not None:
            found["bad"].append((*last, "followed by one more '- ' line"))
            while i + 1 < len(lines) and lines[i + 1].startswith("- "):
                i += 1
        i += 1
    return found


def _advice_blocks(lines: list) -> tuple:
    """`(advice, defects, rest)` of one stream: the lines of every `ADVICE — <n>` block, the ways a block breaks its shape,
    and the stream with the blocks taken out (so the `REJECT` reader never meets them). The shape is the `REJECT` block's:
    n lines each starting with `- `. A header with count 0, fewer lines than declared, a `- ` line past the n-th and an
    `ADVICE` line with no count are defects; what was printed is kept (advice is never dropped silently, FR-59)."""
    advice, defects, rest = [], [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        match = ADVICE_HEAD_RE.match(line)
        if not match:
            if line.startswith("ADVICE —"):
                defects.append(f"the line {i + 1} '{line[:60]}' is an ADVICE line with no count")
            else:
                rest.append(line)
            i += 1
            continue
        n, got, j = int(match.group(1)), [], i + 1
        while len(got) < n and j < len(lines) and lines[j].startswith("- "):
            got.append(lines[j][2:])
            j += 1
        if n == 0 or len(got) < n:
            defects.append(f"the block '{line}' at line {i + 1} is malformed: declared {n} advice line(s) and printed {len(got)}")
        elif j < len(lines) and lines[j].startswith("- "):
            defects.append(f"the block '{line}' at line {i + 1} is malformed: followed by one more '- ' line")
            while j < len(lines) and lines[j].startswith("- "):
                j += 1
        advice += got
        i = j
    return advice, defects, rest


def _marker(tail: list) -> str:
    body = "\n".join(tail).lower()
    if REPAIR_MARKER.lower() in body:
        return "repair"
    return "person" if PERSON_MARKER.lower() in body else ""


def _refused_of(tags: list) -> str:
    """The `refused` value of a text that cannot be split into findings: the first cause, else `unreadable`."""
    return next((cause for _fid, cause, _line in tags if cause in REFUSAL_CAUSES), UNREADABLE) if tags else ""


def _unmigrated(out: dict, stdout: str, stderr: str, tags: list) -> None:
    out["findings"], out["refused"] = [], []
    out["unmigrated"] = " ".join((stdout + "\n" + stderr).split())
    out["unmigrated_refused"] = _refused_of(tags)


def _link(out: dict, tags: list) -> None:
    """Tie each `WORDS_REFUSED_AT_SOURCE` line to its finding by the id in the finding's label."""
    ids = []
    for line in out["findings"]:
        label = LABEL_RE.match(line)
        ids.append(label.group(2) if label else "")
    by_id = {}
    for fid, cause, _line in tags:
        by_id.setdefault(fid, cause)
    out["refused"] = [by_id.get(fid, "") if fid else "" for fid in ids]
    printed = set(ids)
    for fid, cause, line in tags:
        if cause in REFUSAL_CAUSES and fid not in printed:
            out["defects"].append(f"the line '{line}' names the finding '{fid}', which is not among the findings "
                                  "printed: the source refusal cannot be tied to a record")


def unreadable_line(reason) -> str:
    """The one line a detector prints (and exits `EXIT_UNREADABLE`) when it could not run its check."""
    return UNREADABLE_PREFIX + one_line(reason)


def _stderr_tail(stderr: str) -> str:
    """The tail of a stderr as the reason of an `unreadable` (one line; the cut points at where the rest is)."""
    lines = [line for line in stderr.splitlines() if line.strip()]
    if not lines:
        return ""
    return joined(lines[-3:], noun="line", where="the detector's stderr", max_chars=300)


def _marker_reason(stdout: str):
    """The reason of the first line that STARTS with `UNREADABLE: ` (a BOM before it is skipped), else None. The word
    elsewhere in a line is not the marker (FR-12: the prefix at the start is the contract, not a phrase list)."""
    for line in stdout.splitlines():
        line = line.lstrip("﻿")
        if line.startswith(UNREADABLE_PREFIX):
            return line[len(UNREADABLE_PREFIX):].strip() or "no reason printed"
    return None


def _unreadable_of(code: int, stdout: str, stderr: str):
    """The reason this run is `unreadable`, or None when the blocks of the contract are to be read. Direction of
    error: toward `unreadable` (one more call to the conductor), never toward clean."""
    marked = _marker_reason(stdout)
    if marked is not None:
        return marked
    if code == EXIT_UNREADABLE:
        return "exit 3, no reason printed"
    if code not in EXIT_CODES:
        tail = _stderr_tail(stderr)
        return f"exit {code}, outside the detector contract" + (f": {tail}" if tail else "")
    return None


def parse(code: int, stdout: str, stderr: str) -> dict:
    """`{"findings": [str], "refused": [str], "marker": "repair"|"person"|"", "defects": [str], "unmigrated": str,
    "unmigrated_refused": str, "words": "source"|"gate", "unreadable": str, "advice": [str]}`. `refused` runs parallel
    to `findings`: `""`, `family`, `predating` or `unreadable`. `advice` is the lines of the `ADVICE` blocks of stdout
    (X2-2), read at exit 0 and 1 alike, `[]` for an unreadable run; a block that breaks its shape is a `defects` entry.

    `unreadable` (RH1-5, FR-59) is the reason the check did not run, `""` when it did: exit 3 (the line
    `UNREADABLE: <reason>`, or "exit 3, no reason printed"), any exit outside {0, 1, 3}, a line starting with
    `UNREADABLE: ` at any code (the producer contradicts itself: refused), exit 1 with no head in either stream and an
    empty stdout (the tail of stderr, or "exit 1, printed nothing"). Then no finding is read.

    exit 0 is no findings. Otherwise the blocks of the contract are read (stdout; stderr only when stdout has no
    header). An output that breaks the contract - a block cut short by a non-`- ` line, a `- ` line past the n-th,
    a REJECT with no count, no header at all but a stdout - is ONE `unmigrated` text, whole, and no finding is
    invented from it; under `WORDS_AT_SOURCE` the broken block is also named in `defects` (the producer broke its
    own contract, which is the factory's defect and not the role's). An output cut off at its end keeps what it
    printed and says how many it declared. Nothing printed at all is `unreadable`, never a pass."""
    out = {"findings": [], "refused": [], "marker": "", "defects": [], "unmigrated": "",
           "unmigrated_refused": "", "words": "gate", "unreadable": "", "advice": []}
    reason = _unreadable_of(code, stdout, stderr)
    if reason is not None:
        out["unreadable"] = reason
        return out
    # the ADVICE blocks are read at exit 0 and exit 1 alike (a detector with only advice exits 0) and taken out of the stream
    # the REJECT reader sees; they are never findings
    out["advice"], out["defects"], out_lines = _advice_blocks(stdout.splitlines())
    if code == 0:
        return out
    err_lines = stderr.splitlines()
    tags, tag_defects = _tag_lines(out_lines)
    out["defects"] += tag_defects
    stream = out_lines if _has_head(out_lines) else (err_lines if _has_head(err_lines) else None)
    if stream is None:
        if stdout.strip():
            _unmigrated(out, stdout, stderr, tags)
        else:
            tail = _stderr_tail(stderr)
            out["unreadable"] = f"exit {code}, {PRINTED_NOTHING}" if not tail else f"exit {code}, no verdict printed: {tail}"
        return out
    found = _blocks(stream)
    labeled = any(WORDS_AT_SOURCE in head for head in found["heads"])
    out["words"] = "source" if labeled else "gate"
    if found["bad"]:
        _unmigrated(out, stdout, stderr, tags)
        if labeled:
            out["defects"] += [f"the block '{head}' at line {k} is malformed: declared {n} finding(s), {why}"
                               for head, k, n, why in found["bad"] if head and WORDS_AT_SOURCE in head]
            # a LABELLED producer judged its own words and then broke its contract with a REJECT that carries no
            # count: that is the producer's defect (FR-19), not a line to lose inside the unmigrated text
            out["defects"] += [f"the line {k} '{stream[k - 1]}' has no count" for head, k, _n, _why in found["bad"]
                               if head is None]
        return out
    out["findings"], out["defects"] = found["findings"], out["defects"] + found["short"]
    _link(out, tags)
    out["marker"] = _marker(stream[found["tail_from"]:])
    if not out["findings"] and not out["defects"]:
        out["defects"].append(f"refused (exit {code}) and declared no findings")
    return out


def unmigrated_text(text, code=None) -> str:
    """The sentence that shows an output outside the contract's form WHOLE. The exit gate says the exit code too
    (`code`); a reader with no records leaves it out. One builder, so the two spellings cannot drift (m4 of C2-1)."""
    said = f"exit {code}; " if code is not None else ""
    return (f"unmigrated detector output ({said}it is not in the one-line-per-finding form, so it is shown "
            f"whole): {text}")


def flatten(verdict: dict) -> list:
    """The plain lines of a verdict for a reader that has no records: findings, then defects, then the unmigrated
    text whole. Never empty for a verdict of a refusal."""
    lines = list(verdict["findings"]) + list(verdict["defects"])
    if verdict.get("unreadable"):
        lines.append(f"unreadable: {verdict['unreadable']} - the check did not run, so nothing is established")
    if verdict["unmigrated"]:
        lines.append(unmigrated_text(verdict["unmigrated"]))
    return lines


# --- the combined refusal of the controller ---------------------------------------------------------------------

def refusal_text(raw: str) -> str:
    """The text of a refusal as the controller wrote it, with the transport taken off: the `story_step: refused - `
    prefix and the JSON escaping of `--operation decision` (`{"error": "..."}`, newlines as `\\n`). Line by line;
    it cuts nothing and adds nothing, so on the controller's bare text it is the identity."""
    lines = []
    for line in str(raw).split("\n"):
        if line.startswith(STORY_STEP_PREFIX):
            lines.append(line[len(STORY_STEP_PREFIX):])
            continue
        if line.startswith("{"):
            try:
                parsed = json.loads(line)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
                line = parsed["error"]
        lines.append(line)
    return "\n".join(lines)


def split_items(text: str):
    """The items of the controller's combined refusal, or None when the text has no head. The head says how many
    items follow; an item count that differs from it gives `[]` (the head was there, so the route is the
    conductor's, never a match on the whole text). Pass it `refusal_text(...)`, never a raw `Refusal` text."""
    head = COMPOUND_HEAD_RE.search(text or "")
    if not head:
        return None
    items = []
    for line in text[head.end():].split("\n"):
        if ITEM_RE.match(line):
            items.append(line)
        elif items:
            items[-1] += "\n" + line
    items = [ITEM_RE.sub("", item, count=1).rstrip("\n") for item in items]
    return items if len(items) == int(head.group(1)) else []


# --- the renderer -----------------------------------------------------------------------------------------------

def _size(line: str) -> int:
    return 2 + len(line.encode("utf-8", "replace"))


def _cut(line: str, max_bytes: int) -> str:
    room = max(max_bytes - 2 - len("…".encode("utf-8")), 0)
    return line.encode("utf-8", "replace")[:room].decode("utf-8", "ignore") + "…"


def fit(lines: list, max_bytes: int = FINDINGS_MAX_BYTES) -> tuple:
    """`(whole lines that fit, a line was cut)`: lines as `- ` + line joined by newlines, in order, while the block
    stays within `max_bytes` UTF-8 bytes (exactly `max_bytes` is not a cut). A first line that alone is longer is
    cut at a character boundary and marked with `…`."""
    shown, used = [], 0
    for line in lines:
        size = _size(line) + (1 if shown else 0)
        if used + size > max_bytes:
            break
        shown.append(line)
        used += size
    if lines and not shown:
        return [_cut(lines[0], max_bytes)], True
    return shown, False


def _save(path, lines: list, noun: str, source: str) -> str:
    """Write the whole list; `""` on success, else the reason in words."""
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        head = f"# {len(lines)} {noun}(s), {datetime.now().isoformat(timespec='seconds')}, {source}\n"
        # `replace`: a lone surrogate in one item must not turn a refusal into a crash (as `_size` reads it)
        path.write_text(head + "".join(f"- {line}\n" for line in lines), encoding="utf-8", errors="replace")
        return ""
    except OSError as exc:
        return type(exc).__name__


def render(lines, *, max_bytes: int = FINDINGS_MAX_BYTES, full_path=None, noun: str = "finding",
           source: str = "detector output") -> str:
    """The text of a list for a role or the conductor: `- ` + each line, whole, in order, up to `max_bytes` bytes.
    If everything fits there is nothing else and no file. Past the ceiling the last line says how many are left
    out and where the whole list is: the file `full_path`, written by this very call. With no `full_path` it says
    the list could not be saved (FR-41). A first line longer than the ceiling is cut at a character boundary and
    `…` marks the cut. The pointer line is not counted against the ceiling."""
    lines = [str(line) for line in lines]
    shown, cut = fit(lines, max_bytes)
    body = ["- " + line for line in shown]
    left = len(lines) - len(shown) if not cut else len(lines) - 1
    if left == 0 and not cut:
        return "\n".join(body)
    body.append("- " + _pointer(left, cut, lines, noun, source, full_path))
    return "\n".join(body)


def _pointer(left: int, cut: bool, lines: list, noun: str, source: str, full_path, where=None) -> str:
    """`(+K more <noun>(s) — the whole list: <place>)`: the ONE wording of what is left out and where it is (I5).
    `full_path` is written by this very call (`could not be saved: <reason>` when it cannot); with no `full_path` and
    no `where` it says the list could not be saved, never a place that does not exist. `where` is a place the caller
    names and keeps (a command's output, a record), so nothing is written for it."""
    said = " and ".join(part for part in (f"+{left} more {noun}(s)" if left else "",
                                          "… marks a line cut here" if cut else "") if part)
    if full_path is None and where is not None:
        return f"({said} — the whole list: {where})"
    reason = "the story is not known" if full_path is None else _save(full_path, lines, noun, source)
    if full_path is not None and not reason:
        return f"({said} — the whole list: {full_path})"
    return f"({said}; the whole list could not be saved: {reason})"


def joined(items, *, noun: str, where=None, full_path=None, max_chars=FINDINGS_MAX_BYTES, sep: str = "; ") -> str:
    """A list in ONE line (a sentence, a report cell): the one-line twin of `render`. Items are `str()`-ed and folded to
    one physical line (`one_line`, so an item never forges a `- `, `N) ` or head line); no items is `none`.

    `max_chars=None` is no ceiling, for a list bounded by construction (the caller names the bound). Otherwise the
    ceiling is the length of the joined text in CHARACTERS (like `WINDOW_REASON_LIMIT`; `render`'s `max_bytes` is
    bytes; the pointer part is not counted): the items that fit, `sep`-joined, and one
    trailing part `(+K more <noun>(s) — the whole list: <place>)` of its own, so a router that splits at `sep` never
    glues it to an item. The place is `full_path` (written by this call) or `where` (a place the caller keeps);
    a ceiling with neither is a `ValueError`, because a site must name where the rest is (FR-15). EXACTLY the ceiling is
    not a cut. Precedence of the edges: no items, then the fold, then the cut: one item is unchanged unless it holds a
    line break (folded) or is alone longer than the ceiling (cut at a character boundary, marked with `…`, and the
    pointer says a line was cut)."""
    if max_chars is not None and where is None and full_path is None:
        raise ValueError("joined: a ceiling needs the place of the rest (`where` or `full_path`)")
    lines = [one_line(item) for item in items]
    if not lines:
        return "none"
    if max_chars is None:
        return sep.join(lines)
    shown, used = [], 0
    for line in lines:
        size = len(line) + (len(sep) if shown else 0)
        if used + size > max_chars:
            break
        shown.append(line)
        used += size
    cut = not shown
    if cut:
        shown = [lines[0][:max(max_chars - 1, 0)] + "…"]
    left = len(lines) - len(shown) if not cut else len(lines) - 1
    if left == 0 and not cut:
        return sep.join(shown)
    return sep.join(shown + [_pointer(left, cut, lines, noun, "the list of one refusal", full_path, where)])


def named(ids, limit: int = LIST_LIMIT, *, where=None, sep: str = ", ", tail: str | None = None) -> str:
    """Ids named inside ONE finding: `a, b, c and K more (<where>)`. The first `limit`, each once (a repeated id is
    named once), then how many were left out; exactly `limit` is no tail. `where` is the place the rest is (words for
    a person, never a script); with no `where` the tail is the bare `and K more` of `gate_preflight.named_ids`, whose
    body this is (the twin that part B switches over; the default `sep` keeps that text). `sep` joins the shown items:
    a list whose items hold commas themselves passes `"; "`, so the end of one item is visible. `tail` is another form
    of the cut's tail, a format string over `{n}` (how many ids in all, each once) and `{k}` (how many were left out):
    `" ({n} in all)"` names the whole count instead of the rest (CX2-17, the one list-cut of the controller's scope
    texts); with `tail` the `where` is not read."""
    ids = list(dict.fromkeys(str(i) for i in ids))
    if tail is None:
        tail = f" and {len(ids) - limit} more" + (f" ({where})" if where else "")
    else:
        tail = tail.format(n=len(ids), k=len(ids) - limit)
    return sep.join(ids[:limit]) + (tail if len(ids) > limit else "")


def compound(messages, *, prefix: str = "") -> str:
    """The combined refusal of `messages`, in the form `controller.Controller._raise_all` raises (a twin pin compares
    the two): one message is its own sentence, unchanged; several are the head `N problems - the request is refused
    whole, every one is listed:` and one `i) ` line each, a line break inside a message indented so it never reads
    as a numbered line, equal messages folded into the first one's place as `<message> (×K)`. Nothing is cut.
    `prefix` stands in front: before one message on its line (`<prefix> <message>`), before the head on a line of
    its own (so the head begins a line, where `COMPOUND_HEAD_RE` and `split_items` read it)."""
    texts = [str(message) for message in messages]
    counts = {text: texts.count(text) for text in texts}
    merged = [text if counts[text] == 1 else f"{text} (×{counts[text]})" for text in dict.fromkeys(texts)]
    if not merged:
        return ""
    if len(merged) == 1:
        return f"{prefix} {merged[0]}" if prefix else merged[0]
    lines = [COMPOUND_HEAD.format(n=len(merged))]
    lines += [f"{number}) " + text.replace("\n", "\n   ") for number, text in enumerate(merged, 1)]
    return "\n".join(([prefix] if prefix else []) + lines)


def one_of(values) -> str:
    """A closed list as the refusals print it (S-5, AR-15): the ONE renderer of `(one of a, b, c)` bodies. A `set` or
    `frozenset` is printed sorted, a tuple or list in its own order; items are `str()`-ed (a non-string is `json.dumps`-ed),
    joined by `, `. An EMPTY list renders `(none: the list is empty)`: an empty closed list accepts no value, and the
    refusal says so (fail-closed). Readers: `record_schema._problems`, `artifact_producer.validate`,
    `planning_contract.validate_plan`, `manual_evidence.validate`, `context_bundle._closed`."""
    items = sorted(values, key=str) if isinstance(values, (set, frozenset)) else list(values)
    if not items:
        return "(none: the list is empty)"
    return ", ".join(item if isinstance(item, str) else json.dumps(item) for item in items)
