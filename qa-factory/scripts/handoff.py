"""The handoff contracts: read them, fill them, check them, repair what code can derive.

`handoffs/*.yaml` is both the contract between two roles and the form the sending role fills.
This module is the only reader of those files, and it treats the CONTRACT ITSELF AS THE SCHEMA:
a placeholder like `<one of vocabulary.row_states>`, `<true|false>` or `<= 80 characters>` is
what the check enforces. Nothing is declared twice, so nothing drifts - which is the defect the
whole folder exists to remove.

Three things live here:

  parse()       a small YAML subset, stdlib only (no factory script may need pyyaml on a
                project we have never seen), line-aware, so a value can be written back into
                the file without losing a comment;
  spec()        the schema derived from a contract template;
  derive()      what a filled form can be repaired with FROM THE ARTIFACTS ON DISK.

The last one is the point. On TP1-13797 twenty-three role sessions were resumed at S5 and
nineteen conductor sessions ran, mostly on refusals like "required key `run_witness` is
missing" - while `run_witness` sat in `runs[]` of the very manifest being refused. Waking a
218k-token role to copy a path it already wrote is the most expensive way a factory can be
wrong. Whatever code can derive, code derives.
"""
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
CONTRACTS = PLUGIN / "handoffs"
PLACEHOLDER = re.compile(r"^<(.+)>$", re.S)
VOCAB_REF = re.compile(r"one of vocabulary\.([a-z_]+)")
MAXLEN = re.compile(r"<=\s*(\d+)\s*characters")
# A placeholder that says so is not required: the role may leave it out entirely.
OPTIONAL_WORDS = ("or a dash", "or omit", "optional", "or the empty list", "or none",
                  "when ", "only when", "or `-`", ", or ")
# A key may be quoted (`"TEST_BUG:collection"`) or carry a hyphen (`manual-agent`): both are
# vocabulary words, and a parser that cannot read the vocabulary is worth nothing.
KEY_LINE = re.compile(r"^(\s*)(-\s+)?(\"[^\"]*\"|'[^']*'|[A-Za-z_][A-Za-z0-9_.\-]*):(?:\s(.*)|())$")
ITEM_LINE = re.compile(r"^(\s*)-\s+(.*)$")


# --------------------------------------------------------------------------- the YAML subset
class Node:
    """One scalar of a parsed document, with the line it lives on."""

    __slots__ = ("path", "value", "line", "end_line", "indent", "key", "comment")

    def __init__(self, path, value, line, end_line, indent, key, comment=""):
        self.path, self.value, self.line, self.end_line = path, value, line, end_line
        self.indent, self.key, self.comment = indent, key, comment

    def __repr__(self):                                       # pragma: no cover - debugging
        return f"Node({self.path!r}={self.value!r} @{self.line})"


class Doc:
    """A parsed contract or filled form: the data, the source lines, the scalar index."""

    def __init__(self, lines, data, nodes):
        self.lines, self.data, self.nodes = lines, data, nodes

    def text(self) -> str:
        return "\n".join(self.lines) + ("\n" if self.lines else "")

    def get(self, path, default=None):
        node = self.nodes.get(path)
        return node.value if node else default

    def rows(self, section: str) -> list:
        """The indices of a list-of-maps section, in order: scope[0], scope[1], ..."""
        seen, out = set(), []
        prefix = section + "["
        for path in self.nodes:
            if path.startswith(prefix):
                index = path[len(prefix):path.index("]", len(prefix))]
                if index not in seen and index != "":
                    seen.add(index)
                    out.append(int(index))
        return sorted(out)


def _strip_comment(raw: str) -> tuple:
    """(value, comment) - a `#` inside quotes is text, a `#` after a space is a comment."""
    out, quote, escaped = [], "", False
    for i, ch in enumerate(raw):
        if quote:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and (i == 0 or raw[i - 1] in " \t"):
            return "".join(out).rstrip(), raw[i:]
        out.append(ch)
    return "".join(out).rstrip(), ""


def _scalar(text: str):
    """The few scalar shapes a contract uses. Everything else stays a string."""
    t = text.strip()
    if t in ("", "~", "null"):
        return None
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
        if t[0] == '"':
            try:
                return json.loads(t)
            except ValueError:
                pass
        return t[1:-1]
    low = t.lower()
    if low in ("true", "false"):
        return low == "true"
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        if not inner:
            return []
        return [_scalar(p) for p in _split_flow(inner)]
    if t.startswith("{") and t.endswith("}"):
        # A flow map: the vocabulary writes a whole row that way
        # (`found: {used_by: [...], meaning: ...}`), and an entry with no `:` is a bare key.
        out = {}
        for part in _split_flow(t[1:-1].strip()):
            key, sep, value = part.partition(":")
            out[_unquote(key.strip())] = _scalar(value) if sep else None
        return out
    return t


def _split_flow(inner: str) -> list:
    parts, depth, quote, cur = [], 0, "", []
    for ch in inner:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return [p for p in parts if p != ""]


def _is_structural(line: str) -> bool:
    body = line.strip()
    return bool(body) and (body.startswith("- ") or body == "-" or bool(KEY_LINE.match(line)))


def parse(text: str) -> Doc:
    """The subset the contracts and the forms use: maps, lists of maps, scalars, block
    scalars, comments, and a quoted or plain scalar wrapped over several lines.

    It never raises on odd input: an unparseable line becomes a string, because a refusal that
    the role cannot read is worse than a value the check refuses with a name.
    """
    lines = text.splitlines()
    data, nodes = {}, {}
    # stack of (indent, container, path); a container is a dict or a list
    stack = [(-1, data, "")]
    i, pending_key = 0, None
    while i < len(lines):
        raw = lines[i]
        body = raw.strip()
        if not body or body.startswith("#"):
            i += 1
            continue
        indent = len(raw) - len(raw.lstrip())
        while len(stack) > 1 and indent <= stack[-1][0] and not (
                ITEM_LINE.match(raw) and indent == stack[-1][0] and isinstance(stack[-1][1], list)):
            stack.pop()
        parent_indent, container, parent_path = stack[-1]
        item = ITEM_LINE.match(raw)
        if item and isinstance(container, list):
            rest = item.group(2)
            index = len(container)
            key_in_item = KEY_LINE.match("  " + rest)
            if key_in_item:
                row = {}
                container.append(row)
                row_path = f"{parent_path}[{index}]"
                stack.append((indent, row, row_path))
                # re-read this line as a key of the new row, at the item's own indent
                lines_key, lines_val = key_in_item.group(3), key_in_item.group(4) or ""
                i = _assign(lines, i, indent + 2, row, row_path, lines_key, lines_val, nodes, stack)
                continue
            value, comment = _strip_comment(rest)
            value, i = _continuation(lines, i, indent, value)
            container.append(_scalar(value))
            nodes[f"{parent_path}[{index}]"] = Node(f"{parent_path}[{index}]", _scalar(value),
                                                    i, i, indent, "", comment)
            i += 1
            continue
        key_match = KEY_LINE.match(raw)
        if key_match and isinstance(container, dict):
            key, value = key_match.group(3), key_match.group(4) or ""
            i = _assign(lines, i, indent, container, parent_path, key, value, nodes, stack)
            continue
        # a continuation the shapes above did not claim: fold it into the previous scalar
        if pending_key and pending_key in nodes:
            node = nodes[pending_key]
            node.value = f"{node.value} {body}".strip()
            node.end_line = i
        i += 1
    return Doc(lines, data, nodes)


def _unquote(key: str) -> str:
    return key[1:-1] if len(key) >= 2 and key[0] == key[-1] and key[0] in "'\"" else key


def _assign(lines, i, indent, container, parent_path, raw_key, value, nodes, stack) -> int:
    """Write one `key: value` into its container; returns the index of the last line used."""
    key = _unquote(raw_key)
    path = f"{parent_path}.{key}" if parent_path else key
    value, comment = _strip_comment(value)
    if value in ("|", ">", ">-", "|-", "|+", ">+"):
        block, j = [], i + 1
        while j < len(lines) and (not lines[j].strip() or
                                  len(lines[j]) - len(lines[j].lstrip()) > indent):
            block.append(lines[j].strip())
            j += 1
        text = " ".join(b for b in block if b) if value.startswith(">") else "\n".join(block)
        container[key] = text
        nodes[path] = Node(path, text, i, j - 1, indent, raw_key, comment)
        return j
    if value == "":
        # a nested block: a list when the next meaningful line is an item, a map otherwise
        j = i + 1
        while j < len(lines) and (not lines[j].strip() or lines[j].strip().startswith("#")):
            j += 1
        child = [] if (j < len(lines) and ITEM_LINE.match(lines[j])
                       and len(lines[j]) - len(lines[j].lstrip()) > indent) else {}
        if j < len(lines) and ITEM_LINE.match(lines[j]) and \
                len(lines[j]) - len(lines[j].lstrip()) == indent:
            child = []                      # a list whose items sit at the key's own indent
        container[key] = child
        stack.append((indent, child, path))
        return i + 1
    value, last = _continuation(lines, i, indent, value)
    container[key] = _scalar(value)
    nodes[path] = Node(path, _scalar(value), i, last, indent, raw_key, comment)
    return last + 1


def _unclosed(value: str) -> bool:
    """A scalar the next line continues: an open quote, or a flow map or list still open.

    Only a quote the scalar STARTS with delimits it. An apostrophe inside prose (`the
    project's own ledger`) is text - reading it as an opening quote swallowed the next line
    of the vocabulary and cost an hour of confusion.
    """
    text = value.strip()
    if text[:1] in ("'", '"'):
        quote = text[0]
        closed, escaped = False, False
        for ch in text[1:]:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
            elif ch == quote:
                closed = True
            else:
                closed = False
        if not closed:
            return True
    return value.count("{") > value.count("}") or value.count("[") > value.count("]")


def _continuation(lines, i, indent, value) -> tuple:
    """A scalar wrapped over the following, more indented, non-structural lines."""
    unbalanced = _unclosed(value)
    open_angle = value.startswith("<") and not value.rstrip().endswith(">")
    j = i
    while j + 1 < len(lines):
        nxt = lines[j + 1]
        if not nxt.strip():
            break
        nxt_indent = len(nxt) - len(nxt.lstrip())
        if nxt.strip().startswith("#"):
            break
        if nxt_indent <= indent or (_is_structural(nxt) and not (unbalanced or open_angle)):
            break
        if not (unbalanced or open_angle or not _is_structural(nxt)):
            break
        value = f"{value} {nxt.strip()}".strip()
        j += 1
        unbalanced = _unclosed(value)
        open_angle = value.startswith("<") and not value.rstrip().endswith(">")
        if not unbalanced and not open_angle and _is_structural(lines[j + 1] if j + 1 < len(lines) else ""):
            break
    return value, j


# ------------------------------------------------------------------------------ the registry
def _read(path: Path) -> Doc:
    return parse(path.read_text(encoding="utf-8"))


def index() -> dict:
    return _read(CONTRACTS / "index.yaml").data


def vocabulary() -> dict:
    return _read(CONTRACTS / "vocabulary.yaml").data


def allowed(name: str) -> list:
    """The closed list `name` of the vocabulary, whatever shape it is written in."""
    value = vocabulary().get(name)
    if isinstance(value, dict):
        return sorted(str(k) for k in value)
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def grounding_vocabulary_line() -> str:
    """The ONE line that hands a role the closed words of `work/grounding.yaml`: `labels: ...; requirement states: ....` (OH3-14).
    The role cannot read the vocabulary file (the pre-tool guard refuses a role the plugin's `handoffs/`), so the S3 window-1 brief
    (`brief_pack.s3_labelling_vocabulary_lines`) carries the words itself, built here through `allowed`. The driver's own dispatch
    line (`story_run.py`) is still built by hand there, and without the declaration below: its swap to this builder is queued to conductor/1. An unreadable
    vocabulary or an empty list is DECLARED in the line (a blank list would read as "any word"); never raises."""
    parts = []
    for title, name in (("labels", "grounding_labels"), ("requirement states", "requirement_grounding_states")):
        try:
            words = allowed(name)
        except Exception:     # a missing or unparseable file: the same declaration as an empty list, the caller must not die on it
            words = []
        parts.append(f"{title}: {', '.join(words)}" if words else f"{title}: NONE READABLE (the vocabulary holds no `{name}` words)")
    return "; ".join(parts) + "."


def contract_of(stage: str, role: str, to_role: str = "", purpose: str = "") -> str:
    """The contract id for this handover, from index.yaml - never guessed from a file name.

    Three roles hand over twice (the designer's manual cases, the automator's instances, the
    analyst's triage all travel past the next role). Without a named receiver this returns the
    DISPATCH-TIME contract and never a `secondary: true` one, so the form `story_step start`
    writes is the one the role is about to fill.

    A row may name the `purpose` of the dispatch it serves (S5's plan dispatch, `s5_plan`). It matches ONLY a
    lookup that asks for that purpose: a lookup with no purpose never returns it, so a stage's usual contract
    stays what it was, and a lookup with a purpose returns only a row that names it - a purpose nobody
    registered resolves to `""`, never to the stage's usual contract.
    """
    for row in index().get("handoffs", []):
        if str(row.get("stage") or "") != str(stage) and str(row.get("gate") or "") != str(stage):
            continue
        if str(row.get("from") or "") != role:
            continue
        if str(row.get("purpose") or "") != str(purpose or ""):
            continue
        if to_role:
            if str(row.get("to") or "") == to_role:
                return str(row.get("contract") or "")
            continue
        if row.get("secondary"):
            continue
        return str(row.get("contract") or "")
    return ""


def repair_carries(contract_id: str) -> tuple:
    """The paths of the contract's form that a REPAIR dispatch's form takes from the accepted form it reworks (`repair_carries:`
    in index.yaml, HF9-2): whole-stage facts about the inputs, which a rework repeats unchanged. `inputs_read[].rows` names the
    field in every row, `inputs_read[0].path` in one. An unlisted contract, a missing or malformed block, an unreadable index:
    `()`, so nothing is carried and every field is asked as before (AR-28). The ONE reader of the block."""
    try:
        block = index().get("repair_carries")
        listed = block.get(contract_id) if isinstance(block, dict) else None
        if not isinstance(listed, list):
            return ()
        return tuple(str(path).strip() for path in listed if isinstance(path, str) and path.strip())
    except Exception:
        return ()


def template(contract_id: str) -> Doc:
    path = CONTRACTS / f"{contract_id}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"no contract `{contract_id}` in {CONTRACTS}")
    return _read(path)


AUTHOR_TOKEN = "<the author's dispatch>"          # the ONE token of the contracts that review a dispatch: S2-S4 stage critics, S7/S8 consumers (AR-15)


def only_template(value) -> bool:
    """Is every leaf of `value` (nested rows, lists, maps) still a placeholder? A real value anywhere - a word, a number, a
    boolean - says the section was filled (carried, prefilled). The one reader of an untouched template row (AR-15): the
    skeleton's emptying and the rows-owed check both call it."""
    if isinstance(value, dict):
        return all(only_template(v) for v in value.values())
    if isinstance(value, list):
        return all(only_template(v) for v in value)
    return is_placeholder(value)


# -------------------------------------------------------------------------------- the schema
class FieldSpec:
    __slots__ = ("path", "options", "optional", "max_len", "kind", "hint")

    def __init__(self, path, options, optional, max_len, kind, hint):
        self.path, self.options, self.optional = path, options, optional
        self.max_len, self.kind, self.hint = max_len, kind, hint


def _spec_of_value(path: str, value) -> FieldSpec:
    text = "" if value is None else str(value)
    inner = PLACEHOLDER.match(text.strip())
    hint = inner.group(1).strip() if inner else text
    options, kind, max_len = [], "text", 0
    optional = any(w in hint.lower() for w in OPTIONAL_WORDS)
    vocab = VOCAB_REF.search(hint)
    if vocab:
        options = allowed(vocab.group(1))
        kind = "choice"
    elif inner and "|" in hint and len(hint) < 160 and " " not in hint.split("|")[0].strip():
        options = [p.strip() for p in hint.split("|") if p.strip()]
        kind = "boolean" if options == ["true", "false"] else "choice"
    size = MAXLEN.search(text)
    if size:
        max_len = int(size.group(1))
        optional = False
        hint = f"a verdict of at most {max_len} characters - the explanation lives in the artifact"
    return FieldSpec(path, options, optional, max_len, kind, hint)


# The contract writes these itself - they are what the receiving role is promised, not what the
# sending role fills. A check that refuses them refuses the contract for being a contract.
CONTRACT_OWNED = ("schema_version", "contract", "stage", "gate", "kind", "from_role", "to_role",
                  "inputs", "expected_of_the_receiver", "rules", "not_shown", "message_sections",
                  "common_shape", "handoffs", "escalation", "judged_row", "judged", "null_outcome", "required_when", "rows_owed_when")
# Every contract's item list. It is the one list a role may not leave empty: a handover with no
# items is not a handover. Every other list may legitimately be empty (`unresolved` above all).
# One contract may name its own exception: a `null_outcome` block (see `null_outcomes` below).
REQUIRED_LISTS = ("scope",)

# What a declaration is made of. An entry holding any other key is not read at all (fail closed): `joint` and
# `only_when` are the next node's, and a key with no reader behind it must never look like a declaration.
NULL_ENTRY_KEYS = ("condition", "params", "words", "source")
# The pilot's block (t-299) had no condition: it was a map `{section, repair_verdicts, listed_in, window}`. It is
# still READ, as a one-entry map, so a tree between the reader's edit and the yaml's never behaves differently;
# the detector (`null_outcomes.audit`) is red on it, so it cannot stay in the package.
LEGACY_NULL_KEYS = ("section", "repair_verdicts", "listed_in", "window")
LEGACY_NULL_CONDITION = "triage_has_no_repair"
LEGACY_NULL_MEANS = "nothing is handed for repair"


def null_outcome_entries(block) -> dict:
    """`{section: entry}` read out of a contract's raw `null_outcome` block; PURE (the detector feeds it synthetic
    blocks), and every shape that is not a well-formed declaration is left out - never guessed at.

    An empty block, a block that is not a map, a mixed block (the legacy `section:` string beside keyed
    entries), an entry that is not a map, an entry with no `condition`, `params` or `words` of the wrong shape,
    a key outside the entry's four, and an entry under a key that is not in REQUIRED_LISTS all give nothing for
    that entry. The contract then behaves as if it declared nothing, so the old refusal stands: a half-edit of a
    yaml form can only make the check stricter, never looser (FR-23's allowed error is the refusal)."""
    if not isinstance(block, dict) or not block:
        return {}
    if isinstance(block.get("section"), str):
        if any(key not in LEGACY_NULL_KEYS for key in block):
            return {}
        section = block["section"].strip()
        if section not in REQUIRED_LISTS:
            return {}
        params = {key: block[key] for key in ("repair_verdicts", "listed_in") if key in block}
        # the pilot compared the header against `window`, `none` when the block named none: the bridge keeps
        # that, or a legacy block without the key would accept a `window: none` beside a repair
        words = {"header.window": {"word": str(block.get("window") or "none"), "means": LEGACY_NULL_MEANS}}
        return {section: {"condition": LEGACY_NULL_CONDITION, "params": params, "words": words}}
    out = {}
    for section, entry in block.items():
        if section not in REQUIRED_LISTS or not isinstance(entry, dict):
            continue
        if any(key not in NULL_ENTRY_KEYS for key in entry):
            continue
        condition = entry.get("condition")
        params, words = entry.get("params", {}), entry.get("words", {})
        if not isinstance(condition, str) or not condition.strip() or not isinstance(params, dict) \
                or not isinstance(words, dict):
            continue
        if any(not isinstance(spec_of_word, dict) or set(spec_of_word) != {"word", "means"}
               or not all(isinstance(spec_of_word[k], str) and spec_of_word[k].strip() for k in ("word", "means"))
               for spec_of_word in words.values()):
            continue
        if "source" in entry and not isinstance(entry["source"], str):
            continue
        out[section] = entry
    return out


def null_outcomes(contract_id: str) -> dict:
    """`{section: entry}`: the contract's own `null_outcome` declarations, `{}` when it has none.

    FR-23: "nothing to repair" is a result. S7's `scope` is the one list the check refuses empty, and on
    TP1-15045 a triage of two product bugs and five stand blocks - nothing the automator could repair - had
    no legal handover: the form refused `scope: []`, the conductor could not write a scope row without
    inventing a repair, and the story stopped. A contract opts in by carrying the block, keyed by the section
    that may be empty; each entry names a CONDITION (registered in `null_outcomes.CONDITIONS`, its logic in code)
    with its parameters as data (FR-13) - the verdicts that make the section non-empty, the list that must then
    hold the triage, the header word that says the null. Every other contract has no block and behaves exactly
    as it did, so the exception is opt-in per contract and never a property of the word `scope`.

    The old name `null_outcome` is gone with no alias: an alias is what lets a test's patch hit the wrong
    function (t-305 F2)."""
    try:
        block = template(contract_id).data.get("null_outcome")
    except FileNotFoundError:
        return {}
    return null_outcome_entries(block)


def relaxed_sections(contract_id: str, header_value) -> set:
    """The sections a form owes ONLY under a `header.verdict` word, and does not owe now (AR-23: their empty outcome).

    The form's own `required_when:` block says `<verdict word>: [<section>, ...]`: those sections are owed under that
    word. `header_value` is the verdict the form being checked holds. A section is relaxed ONLY when the verdict is a
    real word and no entry for that word lists the section; a missing or unfilled verdict, or a malformed block, relaxes
    nothing (AR-28: the safe default is the refusal). Nothing present is refused for being present: this only lifts
    the 'not filled' check."""
    owed_now, listed = _verdict_block(contract_id, "required_when", header_value)
    return listed - owed_now


def rows_owed(contract_id: str, header_value) -> set:
    """The list sections that must hold at least one real row under the verdict `header_value` (F4, AR-10, AR-28).

    The form's own `rows_owed_when:` block says `<verdict word>: [<section>, ...]`: under that word each listed section
    is owed rows (the verdicts that send a window back owe the findings the author must act on). A missing or unfilled
    verdict, an absent block or a malformed block owes nothing. It reads the contract only - never what a row says."""
    return _verdict_block(contract_id, "rows_owed_when", header_value)[0]


def _verdict_block(contract_id: str, key: str, header_value) -> tuple:
    """`(owed_now, listed)` of the contract's `<key>:` block (`<verdict word>: [<section>, ...]`): the sections listed
    under the word the form holds, and the sections listed under any word. `(set(), set())` for a missing or unfilled
    verdict, an absent or malformed block (AR-28: nothing is relaxed or owed on a doubt); a malformed entry is skipped."""
    try:
        block = template(contract_id).data.get(key)
    except FileNotFoundError:
        return set(), set()
    word = str(header_value if header_value is not None else "").strip()
    if not isinstance(block, dict) or not word or is_placeholder(word):
        return set(), set()
    owed_now, listed = set(), set()
    for said, sections_listed in block.items():
        if not isinstance(sections_listed, list) or not all(isinstance(x, str) and x.strip() for x in sections_listed):
            continue
        listed |= {x.strip() for x in sections_listed}
        if str(said).strip() == word:
            owed_now |= {x.strip() for x in sections_listed}
    return owed_now, listed


def owned_by_contract(path: str) -> bool:
    head = path.split(".")[0].split("[")[0]
    return head in CONTRACT_OWNED


def options_for_role(field, role: str, vocab: dict | None = None) -> list:
    """The values THIS role may write, not the whole vocabulary.

    A refusal that prints fifty-one words is a refusal nobody reads. `used_by` narrows the
    list to the role's own words (it is documentation, so a word outside it is still accepted
    and only warned about); `restricted_to` removes a word the role may not write at all.
    """
    if not field.options or not role:
        return field.options
    vocab = vocab or vocabulary()
    states = vocab.get("row_states")
    if not isinstance(states, dict):
        return field.options
    mine, generic = [], []
    for option in field.options:
        spec_of = states.get(option)
        if not isinstance(spec_of, dict):
            generic.append(option)
            continue
        restricted = spec_of.get("restricted_to")
        used = spec_of.get("used_by")
        if restricted:
            if role in _as_list(restricted):
                mine.append(option)
            continue
        if used in (None, "any", "") or role in _as_list(used):
            mine.append(option)
        else:
            generic.append(option)
    return mine or field.options


def _as_list(value) -> list:
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)] if value else []


def set_list(doc: Doc, section: str, values: list) -> bool:
    """Replace a list of scalars (`artifacts.tests`) with the values code derived."""
    node = doc.nodes.get(f"{section}[0]")
    if not node or not values:
        return False
    head = doc.lines[node.line]
    indent = head[:len(head) - len(head.lstrip())]
    rendered = [f"{indent}- {_render(v)}" for v in values]
    tail = doc.lines[node.end_line + 1:]
    doc.lines = doc.lines[:node.line] + rendered + tail
    return True


def spec_of(doc: Doc) -> dict:
    """{path: FieldSpec} of one parsed contract text - pure, so a detector can read a synthetic contract."""
    out = {}
    for path, node in doc.nodes.items():
        generic = re.sub(r"\[\d+\]", "[]", path)
        if generic in out:
            continue
        out[generic] = _spec_of_value(generic, node.value)
    return out


def spec(contract_id: str) -> dict:
    """{path: FieldSpec} derived from the contract's own placeholders. List sections carry
    their row shape under `section[].field`, which is how a filled row is checked."""
    return spec_of(template(contract_id))


def sections_of(doc: Doc) -> dict:
    return {k: ("list" if isinstance(v, list) else "map" if isinstance(v, dict) else "scalar")
            for k, v in doc.data.items()}


def sections(contract_id: str) -> dict:
    """{name: 'map'|'list'|'scalar'} for the top level, so a check can tell an empty list
    (a legitimate answer) from a missing map (an unfilled form)."""
    return sections_of(template(contract_id))


# ------------------------------------------------------------------------------- the filling
def is_placeholder(value) -> bool:
    text = str(value if value is not None else "").strip()
    return bool(PLACEHOLDER.match(text)) or text in ("<fill>", "")


def set_value(doc: Doc, path: str, value) -> bool:
    """Write one scalar back into the file, keeping the line's own trailing comment.

    A value with a newline, a leading `<` or a trailing space is quoted, so what code writes
    reads back as what code meant.
    """
    node = doc.nodes.get(path)
    if not node:
        return False
    rendered = _render(value)
    line = doc.lines[node.line]
    head = line[:len(line) - len(line.lstrip())]
    # Keep whatever stood before the value - including the `- ` of a list item. Writing
    # `  id: x` over `  - id: <fill>` silently dissolves the row and every field under it
    # goes somewhere else; the next check then says the row's own fields do not exist.
    if node.key:
        match = re.match(r"^(\s*(?:-\s+)?)" + re.escape(node.key) + r"\s*:", line)
        prefix = (match.group(1) + node.key + ":") if match else f"{head}{node.key}:"
    else:
        match = re.match(r"^(\s*-)", line)
        prefix = match.group(1) if match else f"{head}-"
    comment = f"  {node.comment}" if node.comment else ""
    doc.lines[node.line] = f"{prefix} {rendered}{comment}".rstrip()
    for extra in range(node.line + 1, node.end_line + 1):
        doc.lines[extra] = None
    doc.lines = [line for line in doc.lines if line is not None]
    return True


def _render(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_render(v) for v in value) + "]"
    text = str(value)
    if text == "":
        return '""'
    if any(ch in text for ch in "\n:#") or text[0] in "<>[]{}&*!|'\"%@`" or text != text.strip():
        return json.dumps(text, ensure_ascii=False)
    return text


def sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
