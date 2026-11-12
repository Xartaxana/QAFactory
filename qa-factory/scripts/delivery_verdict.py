"""delivery_verdict.py - the delivery verdict word, decided from typed kinds, and the ONE reader of that word.

(t-305 N8; factory rules FR-10, FR-13, FR-35, FR-57.) A delivery has three outcomes, not two (PROJECT.md P21):
  yes           every planned check was made and passed
  after_checks  nothing found a bug or a gap in the product, but part of the checking is left with the person
                (a handed test, a manual-human case, a manual check that did not answer, a deferral they worded,
                a stand gap they accepted, a test the code critic could not verify, an expectation nobody
                confirmed, a branch of a requirement nobody proved): "ready once you finish the checks left with you"
  no            a bug, a gap of ours, or anything the factory cannot place

The word is NEVER read off the text of a reason (FR-12): every record the delivery check collects carries a KIND that
its producer fixes from typed fields - a ledger row's state, a triage row's verdict and source, a traceability gap
word, the person's recorded answer - and `references/delivery-verdict-kinds.json` says what each kind means for the
verdict (FR-13). `check_delivery.assess` collects the kinds and calls `decide`; every other reader of the word
(`stage_guard`, `gate_preflight`, `delivery_summary`, `report_facts`, `handoff_check`, the dashboard, the experiments'
measurers) calls `word_of`, so the string "no" is never read as a truthy value and a ledger written before this
module reads exactly as it did.

ERROR DIRECTION. Everything here may be wrong in ONE direction only - toward `no`. A kind the file does not hold, a
file that cannot be read, a word that is not one of the three, a bool that disagrees with its word: `no` (or, for a
reader that only reads, `unknown`, which every gate refuses). `after_checks` with nothing left with the person is
impossible by construction: `assess` re-checks it after `decide` (`VERDICT_WITHOUT_ITEMS`).

This module is a library (no CLI, stdlib only). `contract` is imported lazily, where a case id is read, so the
pre-tool guard that reads the word never pays for it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

KINDS_FILE = "delivery-verdict-kinds.json"
WORDS = ("yes", "after_checks", "no")
VERDICTS = ("no", "after_checks", "none")
UNKNOWN = "unknown"
OWNERS = ("product", "factory", "environment", "review")   # contract.DELIVERY_REASON_OWNERS (held equal by a test)
REGRESSION_KINDS = ("regression", "regression_missing")
_CACHE: dict = {}


def kinds_path() -> Path:
    return Path(__file__).resolve().parents[1] / "references" / KINDS_FILE


def _finding(code: str, entity: str, detail: str) -> dict:
    return {"code": code, "entity": entity, "owner": "factory", "detail": "factory: " + detail}


def _shape_problem(doc) -> str:
    """Why the document is not a kinds file, else "". Every problem names the key, so the repair is one edit."""
    if not isinstance(doc, dict):
        return "the file is not a JSON object"
    words = doc.get("words")
    if not (isinstance(words, dict) and set(words) == set(WORDS)
            and all(isinstance(words[w], dict) and str(words[w].get("head") or "").strip()
                    and str(words[w].get("line") or "").strip() for w in WORDS)):
        return f"`words` must hold exactly {', '.join(WORDS)}, each with a `head` and a `line`"
    kinds = doc.get("kinds")
    if not (isinstance(kinds, dict) and kinds):
        return "`kinds` must be a non-empty object"
    for name, entry in kinds.items():
        if not (isinstance(entry, dict) and entry.get("verdict") in VERDICTS and entry.get("owner") in OWNERS):
            return (f"the kind `{name}` needs a `verdict` ({', '.join(VERDICTS)}) and an `owner` "
                    f"({', '.join(OWNERS)})")
    for key in ("ledger_states", "trace_gaps", "env_options", "plan_dispositions", "waived"):
        if not isinstance(doc.get(key), dict):
            return f"`{key}` must be an object"
    named = []
    for table in ("ledger_states", "trace_gaps"):
        for key, entry in doc[table].items():
            named.append((f"{table}.{key}", entry.get("kind") if isinstance(entry, dict) else entry))
            if isinstance(entry, dict) and entry.get("met") is not None:
                named.append((f"{table}.{key}.met", entry["met"]))
    named += [(f"env_options.{k}", v) for k, v in doc["env_options"].items()]
    named += [(f"plan_dispositions.{k}", v) for k, v in doc["plan_dispositions"].items()]
    named += [(f"waived.{k}", doc["waived"].get(k)) for k in ("with_words", "without_words")]
    for where, kind in named:
        if kind not in kinds:
            return f"`{where}` names the kind `{kind}`, which `kinds` does not hold"
    return ""


def load_kinds(path=None) -> tuple:
    """`(document, "")`, or `({}, why)` when the file is absent, unreadable or not shaped like one. Never raises: a
    verdict that cannot be decided is `no` with the reason, not a crash. Cached by (path, mtime, size)."""
    target = Path(path) if path else kinds_path()
    try:
        stat = target.stat()
        key = (str(target), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return {}, f"references/{target.name} cannot be found, so no kind can be read"
    if key in _CACHE:
        return _CACHE[key]
    try:
        doc = json.loads(target.read_text(encoding="utf-8-sig"))
        problem = _shape_problem(doc)
    except (OSError, ValueError) as exc:
        doc, problem = {}, f"references/{target.name} cannot be read ({type(exc).__name__})"
    if len(_CACHE) > 8:
        _CACHE.clear()
    _CACHE[key] = ({} if problem else doc, (f"references/{target.name}: " + problem) if problem else "")
    return _CACHE[key]


def verdict_of_kind(kind, doc=None):
    """`no`, `after_checks` or `none`; None when the kind is not in the file (the caller treats it as `no`)."""
    doc = load_kinds()[0] if doc is None else doc
    entry = (doc.get("kinds") or {}).get(kind) if isinstance(kind, str) else None
    return entry.get("verdict") if isinstance(entry, dict) else None


def owner_of_kind(kind, doc=None) -> str:
    doc = load_kinds()[0] if doc is None else doc
    entry = (doc.get("kinds") or {}).get(kind) if isinstance(kind, str) else None
    return entry.get("owner") if isinstance(entry, dict) else "factory"


def decide(kinds, doc=None) -> tuple:
    """`(word, findings)` for the kinds one delivery collected. Pure.
      `no` when any kind says no, or is not in the file (plus one `VERDICT_KIND_UNKNOWN` finding per such kind), or
      when the file cannot be read (one `VERDICT_KINDS_UNREADABLE` finding);
      else `after_checks` when any kind says it; else `yes`."""
    if doc is None:
        doc, problem = load_kinds()
        if problem:
            return "no", [_finding("VERDICT_KINDS_UNREADABLE", "delivery-verdict-kinds",
                                   problem + "; the verdict is `no` until it can be read")]
    verdicts, findings, seen = set(), [], set()
    for kind in kinds or ():
        verdict = verdict_of_kind(kind, doc)
        if verdict is None:
            verdicts.add("no")
            label = str(kind)
            if label not in seen:
                seen.add(label)
                findings.append(_finding("VERDICT_KIND_UNKNOWN", label[:60] or "none",
                                         f"a record names the kind `{label[:60]}`, which references/{KINDS_FILE} does "
                                         "not hold, so it is read as `no`: add the kind there in the change that "
                                         "writes it"))
        else:
            verdicts.add(verdict)
    word = "no" if "no" in verdicts else "after_checks" if "after_checks" in verdicts else "yes"
    return word, findings


def _lookup(word: str, table: dict):
    """The entry of `table` for `word`: the whole word first, then its colon-prefixes from the longest to the
    shortest (`failed:TEST_BUG:collection`, `failed:TEST_BUG`, `failed`). None when no prefix is a key - a state or a gap
    word the file does not hold is an unknown, never a default."""
    parts = str(word or "").split(":")
    for end in range(len(parts), 0, -1):
        entry = table.get(":".join(parts[:end]))
        if entry is not None:
            return entry
    return None


def _resolve(entry, doc: dict, *, disposition="", env_option="", code_row=False, words=False, stand_word=False):
    if isinstance(entry, str):
        return entry
    if not isinstance(entry, dict):
        return None
    need = entry.get("needs")
    if need == "env_decision":
        return (doc.get("env_options") or {}).get(env_option) or entry.get("kind")
    if need == "plan_disposition":
        return (doc.get("plan_dispositions") or {}).get(disposition) or entry.get("kind")
    # the needs that are one fact: true -> the entry's `met` kind, else (and when there is no `met`) its `kind`
    facts = {"code_row": code_row, "waiver_words": words, "stand_word": stand_word}
    if need in facts:
        return entry.get("met") if facts[need] and entry.get("met") else entry.get("kind")
    return entry.get("kind")


def kind_of_state(state, doc=None, *, disposition="", env_option="", words=False, stand_word=False):
    """The kind of one ledger row's state, or None when the state is not in the file (the caller reads None as `no`).
      disposition  the plan row's disposition word (`manual-human` makes a `not_executed` row a manual-human debt)
      env_option   the closed answer (`apply`/`theirs`/`handed`/`accept`) the person recorded for the row's case, else ""
      words        the row carries a gate waiver with the person's words
      stand_word   the person's word that passes the stand block is recorded for the story (`check_delivery.stand_word`): a
                   test that changed after its run can only be run again on a stand, so it is the person's to run
    `waived:<inner>`: a red inner state stays red (a waiver never lifts a found bug); an inner state that is a plain
    `not_executed`, an environment block or a deferral becomes a deferral with words when `words`, else an undecided one."""
    doc = load_kinds()[0] if doc is None else doc
    state = str(state or "")
    if state.split(":", 1)[0] == "waived":
        inner = state.split(":", 1)[1] if ":" in state else ""
        inner_kind = kind_of_state(inner, doc, disposition=disposition, env_option=env_option, words=False,
                                   stand_word=stand_word)
        if inner_kind is None:
            return None
        rule = doc.get("waived") or {}
        lifted = any(inner == name or inner.startswith(name + ":") for name in rule.get("lifted_inner") or [])
        if not lifted:
            return inner_kind
        return rule.get("with_words") if words else rule.get("without_words")
    return _resolve(_lookup(state, doc.get("ledger_states") or {}), doc, disposition=disposition,
                    env_option=env_option, words=words, stand_word=stand_word)


def kind_of_gap(gap, doc=None, *, env_option="", code_row=False):
    """The kind of one traceability gap word (`check_traceability.gap_of_case`), or None when it is not in the file."""
    doc = load_kinds()[0] if doc is None else doc
    return _resolve(_lookup(str(gap or ""), doc.get("trace_gaps") or {}), doc, env_option=env_option, code_row=code_row)


def counts(kind, doc=None) -> bool:
    """Does an item of this kind count toward `after_checks` (and the `{n}` of its line)?"""
    return verdict_of_kind(kind, doc) == "after_checks"


def count_items(items, doc=None) -> int:
    """The number of items left with the person: one per item whose kind (or one of its kinds) counts; the regression
    row never does (it stands in Left with you and decides nothing)."""
    doc = load_kinds()[0] if doc is None else doc
    n = 0
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and any(counts(k, doc) for k in ([item.get("kind")] + list(item.get("kinds") or []))):
            n += 1
    return n


def word_of(ledger):
    """THE reader of the verdict word. `ledger` is `work/ledger.json` as a dict.
      None                                   -> None (no ledger at all: the caller says "not recorded")
      a word of the three that agrees with the bool (`yes` <=> `delivery_ready is True`) -> that word
      a word that disagrees with the bool, is not a word, or a non-bool `delivery_ready` -> "unknown"
      no word (a ledger written before N8)   -> derived from the bool: `yes` when it is True, else `no`
    The error is only ever toward `no` or `unknown`; both are refused by every gate."""
    if ledger is None:
        return None
    if not isinstance(ledger, dict):
        return UNKNOWN
    ready = ledger.get("delivery_ready")
    word = ledger.get("delivery_verdict")
    if word is None:
        if ready is None or isinstance(ready, bool):
            return "yes" if ready is True else "no"
        return UNKNOWN
    if word not in WORDS or not isinstance(ready, bool) or (word == "yes") != ready:
        return UNKNOWN
    return word


def head_of(word):
    """The report's verdict sentence for a word (data: the kinds file), or None when it cannot be read."""
    entry = (load_kinds()[0].get("words") or {}).get(word)
    return str(entry["head"]) if isinstance(entry, dict) else None


def line_of(word, n: int = 0, reason: str = ""):
    """The `delivery_ready:` line (without its backquotes) for a word, or None when the file cannot be read."""
    entry = (load_kinds()[0].get("words") or {}).get(word)
    if not isinstance(entry, dict):
        return None
    template = str(entry.get("line_one") or entry["line"]) if (word == "after_checks" and n == 1) else str(entry["line"])
    return template.replace("{n}", str(n)).replace("{reason}", str(reason))


# --- the regression list (F3, Q13 a-2): the plan's own words, carried, never composed (FR-49) ------------------------

REGRESSION_HEADING = "## Recommended regression"
GAP_LINE = "no regression scope was recorded at S3 — a factory gap"


def appendix_marker_prefix() -> str:
    """The start of BOTH case-appendix marker lines (`<!-- qa-factory:case-appendix:`), derived from the one constant that writes
    them (`render_case_appendix.START`) - no second copy of the marker (AR-13). Imported where used: this module is read by
    the pre-tool guard, which must not pay for the renderer."""
    from render_case_appendix import START
    return START.rsplit(":", 1)[0] + ":"


PLUGIN_ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}"
# an absolute path that ends in `scripts/<file>`: quoted (it may hold spaces) or not; a drive letter or a leading slash
_SCRIPT_PATH_RE = re.compile(
    r"""(?P<q>["'])(?P<quoted>(?:[A-Za-z]:[\\/]|/)[^"']*?[\\/]scripts[\\/](?P<qfile>[\w.-]+))(?P=q)"""
    r"""|(?<![\w${}.-])(?P<bare>(?:[A-Za-z]:[\\/]|/)[^\s"'`]*?[\\/]scripts[\\/](?P<bfile>[\w.-]+))""")
# the absolute paths that are left: a drive-letter path, or a slash path of three parts or more standing on its own
_ABSOLUTE_PATH_RE = re.compile(r"""(?<![\w${}.:/\\-])(?:[A-Za-z]:[\\/][^\s"'`]+|/[\w.-]+/[\w.-]+/[^\s"'`]+)""")


def machine_paths(line: str) -> list:
    """The absolute paths a regression line still names (a drive-letter path, or a slash path of three parts or more): after
    `portable_regression_line` these are the ones that are not ours to rewrite, so the caller says them (HF8-17, M-E)."""
    return _ABSOLUTE_PATH_RE.findall(str(line))


def portable_regression_line(line: str) -> str:
    """A regression command with the path of the developer's machine taken out of OUR scripts (HF8-17, M-E, AR-4): an absolute
    path ending in `scripts/<file>`, where `<file>` is a file of the package's own `scripts/` folder, becomes
    `${CLAUDE_PLUGIN_ROOT}/scripts/<file>` (quotes kept; both slash forms; every other byte of the line kept). Any OTHER
    absolute path is not ours to rewrite: the line keeps it verbatim and `machine_paths` names it (a path no person can run is
    a finding, not something to guess into another path - FR-49, FR-41). Error direction: a path that does not name a file of
    our scripts is never touched."""
    scripts = Path(__file__).resolve().parent

    def swap(found):
        quoted = found.group("quoted") is not None
        name = found.group("qfile" if quoted else "bfile")
        if not (scripts / name).is_file():
            return found.group(0)
        root = f"{PLUGIN_ROOT_VAR}/scripts/{name}"
        return f"{found.group('q')}{root}{found.group('q')}" if quoted else root

    return _SCRIPT_PATH_RE.sub(swap, str(line))


def regression_lines(plan_text):
    """The lines of `test-plan.md`'s `## Recommended regression` section, VERBATIM (leading and trailing blank lines cut,
    every other byte kept), from the heading to the next `## ` heading outside a code fence - or to the case-appendix marker
    (a line that STARTS with it, outside a fence): `render_case_appendix.embed` writes the appendix after the plan's last
    section, so when the regression section is last the marker stood inside the list, then in the report's regression block, and
    `check` looped S9 on it (HF8-17, DC1-23). `None` when the heading is absent; `[]` when it is there with nothing under it.
    The reader of the words never judges them (FR-12): a section that says only why there is no regression is carried like a
    list, and a missing or blank one is the gap. Direction of the one cut: only a marker of OURS ends the section, so a marker
    word inside a line (not its start) or inside a fence is text; a plan with no marker reads byte for byte as before."""
    head = re.compile(r"^##\s+recommended regression\b", re.IGNORECASE)
    marker_start = appendix_marker_prefix()
    lines = str(plan_text or "").replace("\r\n", "\n").split("\n")
    out, inside, fence = [], False, None
    for line in lines:
        stripped = line.strip()
        marker = re.match(r"^(`{3,}|~{3,})", stripped)
        if marker:
            if fence is None:
                fence = marker.group(1)[0]
            elif marker.group(1)[0] == fence:
                fence = None
        if fence is None and not marker and line.startswith(marker_start):
            if inside:
                break
            continue
        if fence is None and not marker and stripped.startswith("## "):
            if inside:
                break
            inside = bool(head.match(stripped))
            continue
        if inside:
            out.append(line)
    if not inside:
        return None
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


# --- one list, one predicate (F9, F10) ----------------------------------------------------------------------------

def item_cases(item) -> list:
    """The case ids an item of `left_items` stands for: its `case` (the key), else nothing."""
    return [str(item.get("case"))] if isinstance(item, dict) and str(item.get("case") or "").strip() else []


def left_item_is_open(item_text, ledger, cfg=None) -> bool:
    """Is this line of "Left with you" still owed to the person? ONE predicate for the prune and the check (FR-57:
    what `--write` removes, `--check` never demands).
      1. the case ids the item names are read;           2. none -> open (the error is toward keeping);
      3. a named case that stands in `left_items` -> open;
      4. closed ONLY when every named case has ledger rows and every one is `passed_green` or `failed:<triaged
         verdict>` (a verdict of `contract.TRIAGE_VERDICTS` other than NOT_EXECUTED);
      5. a case no ledger row names -> open."""
    import contract as C
    ledger = ledger if isinstance(ledger, dict) else {}
    cases = C.case_ids(item_text, cfg=cfg)
    if not cases:
        return True
    held = [i for i in ledger.get("left_items") or [] if isinstance(i, dict)]
    rows = [r for r in ledger.get("rows") or [] if isinstance(r, dict) and r.get("kind") == "plan_row"]
    closed_verdicts = {v for v in C.TRIAGE_VERDICTS if v != "NOT_EXECUTED"}
    for case in cases:
        if any(case == key or C.case_matches(key, case, cfg=cfg) or C.case_matches(case, key, cfg=cfg)
               for item in held for key in item_cases(item)):
            return True
        mine = [r for r in rows if case in C.case_ids(str(r.get("detail") or ""), cfg=cfg)]
        if not mine:
            return True
        for row in mine:
            state = str(row.get("state") or "")
            verdict = state.split(":", 1)[1] if state.startswith("failed:") else ""
            if state != "passed_green" and verdict not in closed_verdicts:
                return True
    return False
