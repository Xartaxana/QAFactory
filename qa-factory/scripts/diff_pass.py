"""One pass over a unified diff: which files changed, and the changed lines with their
numbers in the new file — the raw material for `observables[]`.

Why this exists. A diff is the scout's ground truth and its biggest single cost: on
TP1-14336 one `Read` of a diff dump pulled 102,214 characters into a dispatch at its
tenth turn of 140, and every later turn paid for it again. The charter's answer was "take
the `@@` headers and read the ranges around them", which in practice became a dozen
separate greps and `git show`s — eleven files read one at a time on QA-EXAMPLE. This
does that walk once, deterministically, and prints only the lines that changed.

  diff_pass.py --diff work/impl-diff.txt                 every file, its hunks, its lines
  diff_pass.py --diff ... --files-only                   one line per file (start here)
  diff_pass.py --diff ... --file src/a.py                one file's hunks
  diff_pass.py --diff ... --max-lines 12                 cap the lines shown per hunk
  diff_pass.py --diff ... --json                         the same as data
  diff_pass.py --selftest

Line numbers are the NEW file's, which is what an observable cites. A removed line is
printed with the number of the line it sat before, marked `-`.

The ONE reader of a recorded diff (G1-1, grounding/1). Three layers, one grammar:

  scan(text, name)    every section as a record with the facts the headers give (new, deleted, refused, labels)
  parse(text)         the same sections in the shape every older reader knows: path, old_path, added, removed,
                      hunks[{new_start, header, lines}] — NO new key (`--json`, `render`, `judge_diff` see this)
  index(work_dir)     every `work/impl-diff*.txt` (one per repository), each file once per diff it appears in, a
                      pseudo-hunk for a file with none (binary, rename, mode, new_empty, ...), and the refusals;
                      every hunk carries `body`: its raw lines in order (context included), a pseudo-hunk's `body`
                      is the file's git header lines (K10: the readers hash and window by it)

How a section is read (the grammar is git's, not a guess):
- A hunk header `@@ -a,b +c,d @@` carries a COUNT of lines for each side. Inside that range a line is a hunk line,
  whatever it says: a deleted SQL comment `-- drop table` is `--- drop table` in the diff, an added `++ x` is
  `+++ x`, and neither is a file header. A `---` / `+++` header is recognised only OUTSIDE a counted range — except the
  triple `---` then `+++` then `@@ -`, which is a header even inside one (a count larger than the body does not swallow
  the next file; the hunk before it is marked `truncated`) - unless those two lines would use up the range exactly (one old
  and one new line left): then they are a removed `-- x` and an added `++ y` that end a legal hunk, git's own reading.
- `hunks[].body` is the hunk's raw lines in order, and that includes the `\\ No newline at end of file` marker (verbatim, on
  whichever side git printed it): the marker is no line and moves no number, but a newline-only edit changes the body.
- Lines are split on LF alone, as git counts them (one `\\r` before the LF is dropped): a lone `\\r`, U+2028 and U+0085
  stay inside their line, so the numbers after them are git's. A file is read as `read_bytes().decode("utf-8-sig",
  "replace")` for the same reason (`read_text` would turn a lone `\\r` into a line break first).
- The path is read from the header that WRITES it: `+++ b/<path>` (exactly the prefix `b/` goes; the TAB git appends after
  a path with a blank goes), else `--- a/<path>` of a deleted file, else `rename to` / `copy to`, else the symmetric
  half of `diff --git a/X b/X`; git's quoted form (`"b/t\\303\\251st.py"`) is decoded. Otherwise the section is listed
  under the rest of its `diff --git` line with `path_uncertain` and a refusal (FR-1) — never under a guessed name.
- `old_path` is the raw `--- ` remainder (`a/<path>` or `/dev/null`); a section without one takes `rename from`.
- A combined diff (`diff --cc`, `diff --combined`, `@@@`) is REFUSED: the section is listed with no hunks and a text that
  says what is wrong, what is expected and what to do; its lines belong to nobody else; the other files are read.
- Error direction: when the reader cannot tell, it lists MORE (an `overflow` or `truncated` hunk, a `path_uncertain`
  file, a pseudo-hunk `unknown` the role must label) — it never drops a line a hunk counts and never gives a line to a
  file whose header is not above it.

Exit codes of the command line: 0 read in full, 1 `--file` names nothing, 2 no diff, 3 read with refusals (the output is
complete; the refusals are on stderr — the scout is told, the pass is not stopped).
"""
import argparse
import json
import re
import sys
from pathlib import Path

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
DEFAULT_MAX_LINES = 40
EXIT_REFUSED = 3
DEV_NULL = "/dev/null"
DEV_NULL_LINE = re.compile(r"^--- /dev/null[ \t]*$")
QUOTED_PAIR = re.compile(r'^("(?:[^"\\]|\\.)*") ("(?:[^"\\]|\\.)*")$')
ESCAPES = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11, '"': 34, "\\": 92}
EXTENDED = (("new file mode ", "new"), ("deleted file mode ", "deleted"), ("old mode ", "mode"), ("new mode ", "mode"),
            ("Binary files ", "binary"), ("GIT binary patch", "binary"), ("rename from ", "rename_from"),
            ("rename to ", "rename_to"), ("copy from ", "copy_from"), ("copy to ", "copy_to"))
SHOWN = 80      # characters of an offending line a refusal quotes


def split_lines(text: str) -> list:
    """The lines of a diff as git counts them: split on LF only, one `\\r` before it dropped (a CRLF diff reads as its LF
    twin); a lone `\\r`, U+2028, U+0085 stay inside their line. A leading BOM goes."""
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def read_diff(path) -> str:
    """The text of a recorded diff the way `split_lines` needs it (OSError is the caller's)."""
    return Path(path).read_bytes().decode("utf-8-sig", "replace")


def git_unquote(token: str) -> tuple:
    """(text, True) for a path git quoted (`"b/t\\303\\251st.py"`: C escapes and octal bytes, UTF-8), (token, True) for an
    unquoted one, (token, False) when the quoting is broken (a bare quote, an unknown escape, bytes that are not UTF-8)."""
    if not token.startswith('"'):
        return token, True
    if len(token) < 2 or not token.endswith('"'):
        return token, False
    body, out, at = token[1:-1], bytearray(), 0
    while at < len(body):
        char = body[at]
        if char == '"':
            return token, False
        if char != "\\":
            out += char.encode("utf-8")
            at += 1
            continue
        if body[at + 1:at + 2] in ESCAPES and body[at + 1:at + 2]:
            out.append(ESCAPES[body[at + 1]])
            at += 2
        elif re.fullmatch(r"[0-7]{3}", body[at + 1:at + 4]):
            out.append(int(body[at + 1:at + 4], 8) & 0xFF)
            at += 4
        else:
            return token, False
    try:
        return out.decode("utf-8"), True
    except UnicodeDecodeError:
        return token, False


def header_path(rest: str) -> tuple:
    """(path as written, ok) of the text after `--- ` / `+++ `: the part before git's TAB (a path with a blank, or a
    timestamp), unquoted. The prefix (`a/`, `b/`) is NOT taken off here."""
    return git_unquote(rest.split("\t", 1)[0].strip())


def without_prefix(path: str, prefix: str) -> str:
    return path[len(prefix):] if path.startswith(prefix) else path


def symmetric_half(rest: str):
    """X of `a/X b/X` (the text after `diff --git `, quoted or not), else None: a rename or a copy is not symmetric."""
    if rest.startswith('"'):
        pair = QUOTED_PAIR.match(rest)
        if not pair:
            return None
        (old, ok_old), (new, ok_new) = git_unquote(pair.group(1)), git_unquote(pair.group(2))
        if ok_old and ok_new and old.startswith("a/") and new.startswith("b/") and old[2:] == new[2:]:
            return new[2:]
        return None
    half, odd = divmod(len(rest) - 5, 2)
    if half < 0 or odd or not rest.startswith("a/") or rest[2 + half:5 + half] != " b/" or rest[2:2 + half] != rest[5 + half:]:
        return None
    return rest[2:2 + half]


class Entry:
    """One section of a diff: what its headers and hunks said. `finish()` settles the path and the label."""

    def __init__(self, line: int, first: str):
        self.line, self.first = line, first       # 1-based number and text of the section's first line
        self.git_rest = ""
        self.minus = ""                           # the raw `--- ` remainder
        self.minus_seen = self.plus_seen = False
        self.plus = None                          # the path `+++ b/<path>` wrote (None: no usable one)
        self.plus_ok = True
        self.facts = set()                        # new, deleted, mode, binary, rename_from, ... (EXTENDED)
        self.targets = {}                         # rename_from/rename_to/copy_from/copy_to values
        self.hunks, self.added, self.removed = [], 0, 0
        self.header = []                          # the raw header lines (the body of a pseudo-hunk)
        self.stray = False                        # a line the reader could not place
        self.combined = None                      # (line number, text) of the first combined-diff mark
        self.path, self.path_uncertain = "", False
        self.refused = ""

    def settle_path(self) -> None:
        """The order of the grammar: `+++`, `--- a/` of a deleted file, rename/copy target, symmetric `diff --git`."""
        if self.plus is not None:
            self.path, self.path_uncertain = self.plus, not self.plus_ok
            return
        minus, minus_ok = header_path(self.minus) if self.minus else ("", True)
        if "deleted" in self.facts and self.minus and minus != DEV_NULL and minus_ok:
            self.path = without_prefix(minus, "a/")
            return
        for key in ("rename_to", "copy_to"):
            if self.targets.get(key):
                self.path = self.targets[key]
                return
        if self.combined and self.combined[1].startswith(("diff --cc ", "diff --combined ")) and self.git_rest:
            named, ok = git_unquote(self.git_rest)      # `diff --cc <path>`: git names the file (refused, but not unlabelled)
            if ok:
                self.path = named
                return
        half = symmetric_half(self.git_rest) if self.git_rest else None
        if half is not None:
            self.path = half
            return
        self.path_uncertain = True
        self.path = without_prefix(minus, "a/") if self.minus and minus != DEV_NULL else self.git_rest

    def pseudo(self) -> str:
        """Why a section has no hunk: the first header that explains it, else `unknown` (the role must label the row)."""
        if self.stray:
            return "unknown"
        for kind, key in (("binary", "binary"), ("rename", "rename_to"), ("copy", "copy_to")):
            if key in self.facts:
                return kind
        for kind, key in (("new_empty", "new"), ("deleted_empty", "deleted"), ("mode", "mode")):
            if key in self.facts:
                return kind
        return "unknown"


class Scanner:
    """Walks the lines of one diff once. State: the open section, the open hunk and what is left of its counted range."""

    def __init__(self, lines: list, name: str):
        self.lines, self.name = lines, name
        self.entries: list = []
        self.cur = None
        self.pending = None                      # a `--- ` seen before any section to hang it on (headerless diffs)
        self.pending_raw = ""                    # ... and its raw line
        self.hunk = None
        self.old_left = self.new_left = self.new_no = 0

    # ---- the walk ------------------------------------------------------------------------------------------
    def run(self) -> list:
        for at, raw in enumerate(self.lines):
            if self.in_range() and self.body_line(raw, at):
                continue
            self.outside(raw, at)
        if self.in_range():
            self.hunk["truncated"] = True
        for entry in self.entries:
            self.finish(entry)
        return self.entries

    def in_range(self) -> bool:
        return self.hunk is not None and (self.old_left > 0 or self.new_left > 0)

    def close_range(self, truncated: bool) -> None:
        if truncated and self.hunk is not None:
            self.hunk["truncated"] = True
        self.old_left = self.new_left = 0

    def begin(self, at: int) -> Entry:
        self.cur = Entry(at + 1, self.lines[at])
        self.cur.header.append(self.lines[at])
        self.entries.append(self.cur)
        self.hunk = None
        self.old_left = self.new_left = 0
        return self.cur

    # ---- inside a counted range: everything that looks like a hunk line IS one -----------------------------
    def body_line(self, raw: str, at: int) -> bool:
        """True when `raw` was consumed as a line of the open hunk; False closes the range and the line is a header."""
        sign = raw[:1]
        if sign == "\\":
            self.hunk["body"].append(raw)        # the no-newline marker: no line, no number, but part of the body (G1-4 hashes it)
            return True
        if sign == "-" and raw.startswith("--- ") and self.lines[at + 1:at + 2] and self.lines[at + 1].startswith("+++ ") \
                and self.lines[at + 2:at + 3] and self.lines[at + 2].startswith("@@ -") \
                and not (self.old_left == 1 and self.new_left == 1):
            # the triple is a header: the count was larger than the body. Not when the two lines would exactly use up the
            # range (old_left == new_left == 1): a removed `-- x` and an added `++ y` that end a legal hunk, as git counts them.
            self.close_range(True)
            return False
        if sign in ("", " "):
            self.old_left, self.new_left = self.old_left - 1, self.new_left - 1
            self.new_no += 1
            self.hunk["body"].append(raw)
        elif sign in ("+", "-"):
            self.hunk_line(raw, self.new_left if sign == "+" else self.old_left)
        else:
            self.close_range(True)               # not a hunk line: the diff broke off before its count ran out
            return False
        return True

    def hunk_line(self, raw: str, left: int) -> None:
        """Record a `+` / `-` line (the counted ones and the strays): numbered in the NEW file, counted on its section."""
        sign = raw[0]
        self.hunk["lines"].append((self.new_no, sign, raw[1:]))
        self.hunk["body"].append(raw)
        if sign == "+":
            self.cur.added += 1
            self.new_no += 1
            self.new_left -= 1
        else:
            self.cur.removed += 1
            self.old_left -= 1
        if left <= 0:
            self.hunk["overflow"] = True         # the line is kept; the count of its side had run out

    # ---- outside a range: headers, hunk starts, strays -----------------------------------------------------
    def outside(self, raw: str, at: int) -> None:
        if raw == "":
            return                               # a separator (two after every file in a real export), not a hunk line
        if raw.startswith("diff --git "):
            self.pending = None
            self.begin(at).git_rest = raw[len("diff --git "):]
            return
        if raw.startswith(("diff --cc ", "diff --combined ")):
            self.pending = None
            entry = self.begin(at)
            entry.git_rest = raw.split(" ", 2)[2]
            entry.combined = (at + 1, raw)
            return
        if self.cur is not None and self.cur.combined:
            return                               # a refused section: its lines are nobody else's (and nobody's)
        if raw.startswith("@@@"):
            self.combined_mark(raw, at)
        elif raw.startswith("--- "):
            self.minus_line(raw)
        elif raw.startswith("+++ "):
            self.plus_line(raw, at)
        elif raw.startswith("@@"):
            self.hunk_start(raw, at)
        elif raw[0] == "\\":
            if self.hunk is not None:
                self.hunk["body"].append(raw)    # the marker after the last counted line of a hunk: part of its body, no line
        elif raw[0] in "+- ":
            self.stray_line(raw)
        else:
            self.extended(raw)

    def combined_mark(self, raw: str, at: int) -> None:
        entry = self.cur or self.begin(at)
        entry.combined = (at + 1, raw)
        entry.hunks, entry.added, entry.removed = [], 0, 0
        self.hunk = None
        self.close_range(False)

    def minus_line(self, raw: str) -> None:
        entry = self.cur
        if entry is None or entry.hunks or entry.plus_seen or entry.minus_seen:
            self.cur, self.hunk = None, None     # the next header starts a section of its own
            self.pending, self.pending_raw = raw[4:].split("\t", 1)[0].strip(), raw
            return
        entry.minus_seen, entry.minus = True, raw[4:].split("\t", 1)[0].strip()
        entry.header.append(raw)

    def plus_line(self, raw: str, at: int) -> None:
        entry = self.cur
        if entry is None or entry.hunks or entry.plus_seen:
            entry = self.begin(at)
            self.take_pending(entry)
        else:
            entry.header.append(raw)
        entry.plus_seen = True
        written, ok = header_path(raw[4:])
        if written == DEV_NULL:
            entry.facts.add("deleted")
        else:
            entry.plus, entry.plus_ok = without_prefix(written, "b/"), ok
        if at > 0 and DEV_NULL_LINE.match(self.lines[at - 1]):
            entry.facts.add("new")

    def take_pending(self, entry: Entry) -> None:
        """Hang a `--- ` that came before any section on the section the next header opens."""
        if self.pending is not None:
            entry.minus_seen, entry.minus = True, self.pending
            entry.header.insert(0, self.pending_raw)
            self.pending, self.pending_raw = None, ""

    def hunk_start(self, raw: str, at: int) -> None:
        match = HUNK_RE.match(raw)
        entry = self.cur
        if entry is None:
            entry = self.begin(at)
            self.take_pending(entry)
        if not match:
            entry.stray = True                   # an `@@` line that is no hunk header: said, not skipped
            return
        old_count = 1 if match.group(2) is None else int(match.group(2))
        new_count = 1 if match.group(4) is None else int(match.group(4))
        self.hunk = {"new_start": int(match.group(3)), "header": (match.group(5) or "").strip(), "lines": [],
                     "old_start": int(match.group(1)), "old_count": old_count, "new_count": new_count,
                     "truncated": False, "overflow": False, "body": []}
        entry.hunks.append(self.hunk)
        self.old_left, self.new_left, self.new_no = old_count, new_count, self.hunk["new_start"]

    def stray_line(self, raw: str) -> None:
        """A `+` / `-` / space line past the count: kept on the last hunk with `overflow` (a row too many, no loss)."""
        if self.cur is None:
            return                               # a commit message, a preamble: before any section
        if self.hunk is None:
            self.cur.stray = True                # no hunk to hold it: the section is `unknown` for the role to label
        elif raw[0] == " ":
            self.new_no += 1
            self.hunk["overflow"] = True
            self.hunk["body"].append(raw)
        else:
            self.hunk_line(raw, 0)

    def extended(self, raw: str) -> None:
        if self.cur is None:
            return
        self.cur.header.append(raw)
        for prefix, key in EXTENDED:
            if raw.startswith(prefix):
                self.cur.facts.add(key)
                if key.startswith(("rename_", "copy_")):
                    self.cur.targets[key] = git_unquote(raw[len(prefix):].split("\t", 1)[0])[0]
                return

    # ---- the end of a section ------------------------------------------------------------------------------
    def finish(self, entry: Entry) -> None:
        entry.settle_path()
        if entry.combined:
            entry.refused = combined_text(self.name, entry)
        elif entry.path_uncertain:
            entry.refused = uncertain_text(self.name, entry)


def combined_text(name: str, entry: Entry) -> str:
    at, raw = entry.combined
    return (f'diff_pass: {name} line {at}: "{raw[:SHOWN]}" opens a combined diff (diff --cc / @@@) - the form git prints '
            f"for a merge commit, where a line belongs to several parents at once and cannot be numbered in one new file. "
            f"{entry.path or '<the file>'} is listed with no hunks; the other files of this diff are read. Expected: a "
            f"two-way unified diff (diff --git a/<path> b/<path>, hunks @@ -a,b +c,d @@). Do: write the merge's diff "
            f"against its first parent (git diff <merge>^1 <merge>) to work/{name} and read it again; a role with no shell "
            f"says in its handoff that {entry.path or 'this file'} was not read (an informed pass, FR-4).")


def uncertain_text(name: str, entry: Entry) -> str:
    return (f'diff_pass: {name} line {entry.line}: "{entry.first[:SHOWN]}" starts a section whose file name cannot be read '
            f"from its headers (no usable `+++ b/<path>`, no rename target, and the `diff --git` line is not `a/<path> "
            f'b/<path>`); it is listed as "{entry.path}" with its hunks, and the other files of this diff are read. '
            f"Expected: a two-way unified diff as git prints it (diff --git a/<path> b/<path>, +++ b/<path>). Do: "
            f"re-export the diff (git diff > work/{name}) and read it again; a role with no shell says in its handoff "
            f"that this file was not named (an informed pass, FR-4).")


def scan(text: str, name: str = "diff") -> list:
    """Every section of the diff as an `Entry` (see the module docstring); `name` is the diff's file name in refusals."""
    return Scanner(split_lines(text), name).run()


def old_shape(entry: Entry) -> dict:
    """The record every older reader knows. NO new key: `--json`, `render` and `judge_diff` read this (FR-14)."""
    return {"path": entry.path, "old_path": entry.minus or entry.targets.get("rename_from", ""),
            "added": entry.added, "removed": entry.removed,
            "hunks": [{"new_start": h["new_start"], "header": h["header"], "lines": h["lines"]} for h in entry.hunks]}


def parse(text: str) -> list:
    """[{path, old_path, added, removed, hunks: [{new_start, header, lines: [(n, sign, text)]}]}] — the shape since the
    first version; a combined-diff section is listed with no hunks (see `scan` / `index` for the refusal)."""
    return [old_shape(entry) for entry in scan(text)]


def rich(entry: Entry, diff: str) -> dict:
    """An index record: the old shape plus the facts of `scan`. A section with no hunk carries one pseudo-hunk."""
    record = old_shape(entry)
    record["hunks"] = [dict(hunk) for hunk in entry.hunks]
    if not entry.hunks and not entry.combined:
        record["hunks"] = [{"new_start": 0, "header": "", "lines": [], "pseudo": entry.pseudo(),
                            "body": list(entry.header)}]
    name = diff.rpartition("/")[2]
    stem = name[:-len(".txt")] if name.endswith(".txt") else name
    repo = stem[len("impl-diff"):] if stem.startswith("impl-diff") else ""
    record.update({"diff": name, "repo": repo[1:] if repo.startswith("-") else repo, "new": "new" in entry.facts,
                   "deleted": "deleted" in entry.facts, "path_uncertain": entry.path_uncertain, "refused": entry.refused})
    return record


def unreadable_text(name: str, why: str) -> str:
    return (f"diff_pass: {name} cannot be read ({why}), so none of its files is in the index. Expected: a readable unified "
            f"diff at work/{name} (the scout writes one per repository). Do: re-export it (git diff > work/{name}) or, "
            f"with no shell, say in the handoff that this diff was not read (an informed pass, FR-4).")


def index(work_dir) -> dict:
    """{"files": [...], "refusals": [...]} over EVERY `impl-diff*.txt` of `work_dir`, in `hooklib.sorted_paths` order.
    A file record is `rich()`: the old shape, `diff` (file name), `repo` (the suffix after `impl-diff-`, "" for
    `impl-diff.txt`), `new`, `deleted`, `path_uncertain`, `refused`; one path in two diffs is two records. A refusal is
    {"diff", "kind": unreadable | combined | path_uncertain, "path", "text"} — a diff that cannot be read is a refusal,
    never silence (FR-59); there is no ceiling on files or hunks."""
    import hooklib
    files, refusals = [], []
    for diff in hooklib.sorted_paths(Path(work_dir).glob("impl-diff*.txt")):
        try:
            text = read_diff(diff)
        except OSError as exc:
            refusals.append({"diff": diff.name, "kind": "unreadable", "path": "", "text": unreadable_text(diff.name, str(exc))})
            continue
        for entry in scan(text, diff.name):
            files.append(rich(entry, diff.name))
            if entry.refused:
                refusals.append({"diff": diff.name, "kind": "combined" if entry.combined else "path_uncertain",
                                 "path": entry.path, "text": entry.refused})
    return {"files": files, "refusals": refusals}


def render(files: list, max_lines: int, files_only: bool) -> list:
    out = []
    for f in files:
        out.append(f"{f['path']}  +{f['added']} -{f['removed']}  "
                   f"{len(f['hunks'])} hunk(s)")
        if files_only:
            continue
        for h in f["hunks"]:
            head = f"  @@ {f['path']}:{h['new_start']}"
            if h["header"]:
                head += f"  ({h['header']})"
            out.append(head)
            shown = h["lines"][:max_lines]
            for n, sign, text in shown:
                out.append(f"  {n:6} {sign} {text.rstrip()}")
            if len(h["lines"]) > len(shown):
                out.append(f"  ... {len(h['lines']) - len(shown)} more changed line(s) in "
                           f"this hunk — read {f['path']} lines "
                           f"{h['new_start']}-{h['new_start'] + len(h['lines'])} if you need them")
    return out


def selftest() -> int:
    sample = (
        "diff --git a/src/app.py b/src/app.py\n"
        "index 111..222 100644\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -10,4 +10,5 @@ def delete_project(name):\n"
        " def delete_project(name):\n"
        "-    purge(name)\n"
        "+    purge(name)\n"
        "+    purge_membership(name)\n"
        "     return True\n"
        "diff --git a/ui/Page.tsx b/ui/Page.tsx\n"
        "--- a/ui/Page.tsx\n"
        "+++ b/ui/Page.tsx\n"
        "@@ -3,2 +3,2 @@\n"
        "-const x = 1\n"
        "+const x = 2\n"
    )
    failures = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    files = parse(sample)
    case("two files", [f["path"] for f in files], ["src/app.py", "ui/Page.tsx"])
    case("counts the added lines", files[0]["added"], 2)
    case("counts the removed lines", files[0]["removed"], 1)
    app = files[0]["hunks"][0]
    case("the hunk starts where the header says", app["new_start"], 10)
    case("the hunk carries its context header", app["header"], "def delete_project(name):")
    added = [(n, t.strip()) for n, s, t in app["lines"] if s == "+"]
    case("the new line is numbered in the NEW file", added[-1], (12, "purge_membership(name)"))
    text = "\n".join(render(files, DEFAULT_MAX_LINES, False))
    case("the render names a citable path:line", "src/app.py:10" in text, True)
    case("the render shows the changed line", "purge_membership(name)" in text, True)
    case("the render leaves out unchanged context", "return True" in text, False)
    short = "\n".join(render(files, 1, False))
    case("a capped hunk says how much it left out", "more changed line(s)" in short, True)
    only = "\n".join(render(files, DEFAULT_MAX_LINES, True))
    case("--files-only prints no lines", "purge_membership" in only, False)

    # the grammar: a count, not a prefix, says what a line is
    sql = parse("diff --git a/q.sql b/q.sql\n--- a/q.sql\n+++ b/q.sql\n@@ -1,2 +1 @@\n--- drop table t\n-x\n+z\n")
    case("a deleted SQL comment is a removed line, not a header", (sql[0]["path"], sql[0]["old_path"], sql[0]["removed"]),
         ("q.sql", "a/q.sql", 2))
    case("a path keeps its characters (no lstrip of `b/`)", parse("+++ b/build/x.py\n@@ -1 +1 @@\n-a\n+b\n")[0]["path"],
         "build/x.py")
    merge = scan("diff --cc f.py\n@@@ -1,2 -1,2 +1,3 @@@\n+x\ndiff --git a/g.py b/g.py\n+++ b/g.py\n@@ -1 +1 @@\n-a\n+b\n")
    case("a combined diff is refused and the next file is intact",
         ([e.path for e in merge], bool(merge[0].refused), merge[1].added), (["f.py", "g.py"], True, 1))

    if failures:
        print("DIFF_PASS SELFTEST: VIOLATIONS")
        for f in failures:
            print("  - " + f)
        return 1
    print("DIFF_PASS SELFTEST: no violations (parse, numbering, render, capping, counted ranges, refusals)")
    return 0


def main() -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", help="path to the unified diff (work/impl-diff*.txt)")
    ap.add_argument("--file", default="", help="only this path")
    ap.add_argument("--files-only", action="store_true")
    ap.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.diff:
        print("diff_pass.py: --diff <path> is required", file=sys.stderr)
        return 2
    path = Path(args.diff)
    if not path.is_file():
        print(f"diff_pass.py: no diff at {path} — the scout writes it at S1 "
              "(work/impl-diff.txt, one per repository)", file=sys.stderr)
        return 2
    entries = scan(read_diff(path), path.name)
    files = [old_shape(entry) for entry in entries]
    if args.file:
        files = [f for f in files if f["path"] == args.file or f["path"].endswith(args.file)]
        if not files:
            print(f"diff_pass.py: {args.file} is not in this diff", file=sys.stderr)
            return 1
    if args.json:
        print(json.dumps(files, indent=2))
    else:
        lines = render(files, args.max_lines, args.files_only)
        print("\n".join(lines) if lines else "diff_pass.py: the diff carries no file changes")
    refusals = [entry.refused for entry in entries if entry.refused]
    for text in refusals:
        print(text, file=sys.stderr)
    return EXIT_REFUSED if refusals else 0


if __name__ == "__main__":
    sys.exit(main())
