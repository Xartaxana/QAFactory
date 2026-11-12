"""proof_level.py — which level of proof a test has that its check works, in one place.

D-0010 / D-0012: every NEW or CHANGED test instance gets the live check (`probe_by_code.py`, "the
check is live"); the product level (`red_sandbox.py --probe`, "catches a broken product") is a rare
exception on the code critic's doubt; an unchanged reused test is not probed and blocks nothing;
only a failed or absent live check blocks delivery. Before this module that rule was spread over
seven readers, each with its own idea of what a receipt is: `acceptance` demanded
`mutation_kind: real_behavior` of every probe (which `probe_by_code.py` never makes), the
controller and `ledger` and `check_delivery` each spelled "is a proof required" by hand, and
`window_record` read the two receipt shapes with two different rules. The levels themselves are
data (`references/verification-levels.json`, FR-13); this module is the ONE reader, and it reads
the contract and never writes it (FR-45).

Public surface:
  levels() / document()     the vocabulary, loaded once and cached
  level_of(record)          the level id a receipt / probe record / window probe block carries
  proof_required(e, m)      THE predicate: is a live check demanded of this manifest row
  novelty_of(e, project)    THE reader of a row's stored, code-measured novelty (only ever degrades it)
  not_required_why(e, m)    why none is demanded: unchanged | handed | unmeasured, "" when one is
  reached(e, m, task_root)  the best valid receipt of a row: {level, words, ref, issues}
  binding_facts(task, iid)  the immutable facts a receipt binds, read from what the author wrote
  current_test_bytes/_sha(entry)  THE reader of a row's current test bytes (raw sha256 of the file)
  code_sha(bytes) / current_code_sha(entry)  diff_scope.executable_sha: the code without comments
  instance_identity(e, task_root)  what identifies ONE test now: the file's raw and code shas, and the
                            per-test shas `--mine` writes into `instance_contracts`, re-measured
  proof_identity(record)    the same three values of any carrier (review, probe, receipt, record)
  same_test(now, bound)     THE predicate: does a carrier still speak for this test, and by which rule
  compare_identity(a, b)    the one comparison of two per-test identities: (same|different|unknown, basis)
  same_path(a, b)           the one rule "these two paths name the same file" (case counts, on every OS)
  already_probed(...)       THE predicate both probe tools ask before they mutate anything
  probe_record_path(...)    the one naming of a probe's record (`work/probes/[product/]<stem>.json`)
  holds_over_comments(e, r) a receipt for other raw bytes whose code is the same (D-0017)
  claimed_test_sha(entry)   the bytes the row is bound to (trace_binding), else the reader's
  words(level) / review_words(verdict) / not_required_words() / handed_words() / words_for(reason) /
  unknown_words() / comment_only_words() / code_unchanged_words() / held_words(how)
  probe_problem(block)      what is wrong between a window probe block's level and its mutation kind
  run_identity(row)         the per-test identity a run row recorded (both shas or nothing)
  run_freshness(e, row, t)  THE predicate: did the latest run of this test run the code it holds now:
                            fresh | stale | unknown, and why (HF2-11; the sibling of `same_test`, which
                            says the same of a review, a probe or a receipt)
  probe_freshness(...)      the same for a test's live check: not_required | fresh | stale | missing |
                            unknown, and what a re-probe by code would need (`replay`)
  reprobe_admitted(e, m, t) (admitted, why): a stale live check may be re-probed outside the dispatch's scope
  staleness(task, m, ids)   both, per instance, from ONE `instance_identity` each; writes nothing

Before `references/verification-levels.json` exists nothing here is called; after it exists every
reader loads it; when it is missing or malformed at runtime `LevelsUnavailable` names the file and
the door (reinstall the plugin) — a `ValueError`, so every caller that already treats a refusal to
read as a message keeps doing so.
"""
import hashlib
import json
import os
import re
import stat
import sys
import time
from pathlib import Path, PurePosixPath, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract as C  # noqa: E402

# The block name of a repeated probe: the words of a refusal carry it, and a person's recorded word
# (`waiver.py --block`) matches it. One constant, so the refusal and the door cannot drift apart.
PROBE_BLOCK = "already probed on these bytes"

LEVELS_REL = "references/verification-levels.json"
LEVELS_FILE = Path(__file__).resolve().parents[1] / "references" / "verification-levels.json"

# The two level ids the logic itself must be able to name: which level a `probe_by_code.py` record
# is, and which level demands a product mutation. Their words, ranks, producers and mutation kinds
# are data; only the identity of the two is code, in this one place, so no reader spells them.
LIVE = "live"
PRODUCT = "catches_broken_product"

# The producers a record names itself by, when it carries no explicit `proof_level`.
LIVE_TOOL = "probe_by_code.py"

_LEVEL_KEYS = {"id": str, "rank": int, "words": str, "meaning": str, "producer": str,
               "mutation_kinds": list, "required": bool}
_DOC = None


class LevelsUnavailable(ValueError):
    """The level vocabulary cannot be read — names the file and the way to get it back."""


def _unavailable(why: str) -> LevelsUnavailable:
    return LevelsUnavailable(
        f"{LEVELS_REL} {why}: it is the plugin's own vocabulary of proof levels and is not "
        "something a project or a role edits; reinstall the plugin to bring it back")


def _reset() -> None:
    """Forget the cached vocabulary and the process's identity caches (tests point LEVELS_FILE
    elsewhere, or edit a helper under a cached identity, and call this)."""
    global _DOC
    _DOC = None
    _JOBS_CACHE.clear()
    _IDENTITY_CACHE.clear()
    _HASH_CACHE.clear()


def _shape_error(doc) -> str:
    if not isinstance(doc, dict):
        return "is not a JSON object"
    rows = doc.get("levels")
    if not isinstance(rows, list) or not rows:
        return "has no `levels` list"
    ids, ranks = set(), set()
    for row in rows:
        if not isinstance(row, dict):
            return "has a level that is not an object"
        for key, kind in _LEVEL_KEYS.items():
            value = row.get(key)
            if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
                return f"has a level whose `{key}` is missing or of the wrong type"
        if not row["id"] or not row["words"]:
            return "has a level with an empty id or words"
        if any(not isinstance(k, str) or not k for k in row["mutation_kinds"]):
            return f"has level {row['id']!r} with a bad `mutation_kinds`"
        if row["id"] in ids or row["rank"] in ranks:
            return f"names level id or rank {row['id']!r}/{row['rank']} twice"
        ids.add(row["id"])
        ranks.add(row["rank"])
    for key in ("none_words", "not_required_words", "handed_words", "unknown_words", "red_words",
                "comment_only_words", "code_unchanged_words"):
        if not isinstance(doc.get(key), str) or not doc[key]:
            return f"has no `{key}`"
    review = doc.get("review_words")
    if not isinstance(review, dict) or "" not in review or any(
            not isinstance(k, str) or not isinstance(v, str) or not v for k, v in review.items()):
        return "has no usable `review_words` (every verdict, and \"\" for none, maps to words)"
    return ""


def document() -> dict:
    """The whole vocabulary file, loaded once. Failures are not cached, so a reinstalled file is
    picked up by the next call."""
    global _DOC
    if _DOC is not None:
        return _DOC
    try:
        text = Path(LEVELS_FILE).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise _unavailable("is missing") from None
    except OSError as exc:
        raise _unavailable(f"cannot be read ({type(exc).__name__})") from None
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise _unavailable(f"is not valid JSON ({exc})") from None
    problem = _shape_error(doc)
    if problem:
        raise _unavailable(problem)
    doc = dict(doc, levels=sorted(doc["levels"], key=lambda row: row["rank"]))
    _DOC = doc
    return _DOC


def levels() -> list:
    """The levels, lowest rank first."""
    return document()["levels"]


def _by_id(level_id) -> dict | None:
    if not isinstance(level_id, str):
        return None
    return next((row for row in levels() if row["id"] == level_id), None)


def rank(level_id) -> int:
    """The rank of a level id; 0 for none/unknown (below every real level)."""
    row = _by_id(level_id)
    return row["rank"] if row else 0


def mutation_kinds(level_id) -> list:
    row = _by_id(level_id)
    return list(row["mutation_kinds"]) if row else []


def words(level=None) -> str:
    """The plain words of a level id (or of no level); an id this vocabulary lacks is said, not
    dressed as "not probed" (FR-41)."""
    if level is None or level == "":
        return document()["none_words"]
    row = _by_id(level)
    return row["words"] if row else f"unknown proof level {level}"


def not_required_words() -> str:
    """The words of a test that is not probed because no live check is demanded of it: a measured,
    fresh `unchanged` test, AND a legacy row whose novelty was not measured (owner decision 30.09: a
    green test whose novelty nobody measured is counted as proven, with no words of its own). A handed
    test has its own words, below; `words_for(reason)` picks the words of a `not_required_why` reason."""
    return document()["not_required_words"]


def handed_words() -> str:
    """The words for a test that is not probed because a case it proves was handed to the person."""
    return document()["handed_words"]


def words_for(reason) -> str:
    """The words of a `not_required_why` reason: "unchanged" and "unmeasured" share `not_required_words()`
    (the reason code tells them apart for a reader that needs to; the words do not), "handed" has
    `handed_words()`, and "" (a check is demanded), an unknown reason, None or a non-string is "" -
    it never raises for what it is given (it reads the vocabulary, so `LevelsUnavailable` still
    speaks for a file that is gone)."""
    if reason in ("unchanged", "unmeasured") and isinstance(reason, str):
        return not_required_words()
    if reason == "handed" and isinstance(reason, str):
        return handed_words()
    return ""


def unknown_words() -> str:
    """The words for a row whose receipts cannot be compared with its test (the file is gone)."""
    return document()["unknown_words"]


def red_words() -> str:
    """The words for a RED test with no level (RD1-20): a probe of a check that failed in its own run is not applicable -
    the run already showed what the check does. Such a test is not "not probed" (that says nobody looked)."""
    return document()["red_words"]


def comment_only_words() -> str:
    """What a level's words carry when its receipt holds over a comment-only change (D-0017)."""
    return document()["comment_only_words"]


def code_unchanged_words() -> str:
    """What a level's words carry when its receipt holds over a change that left the TEST's code the same
    (`same_test` answered `instance_code`: another test was added, or a comment moved - the change is not
    said to be a comment, because it may have been a test; FB-10, Lead F-6)."""
    return document()["code_unchanged_words"]


def held_words(how) -> str:
    """The words a receipt shows after its level, chosen by the `same_test` answer and never re-derived:
    `instance_code` -> `code_unchanged_words`, `file_code` -> `comment_only_words` (the whole file's code is
    equal), `instance` / `raw` / anything else -> none."""
    if how == "instance_code":
        return code_unchanged_words()
    if how == "file_code":
        return comment_only_words()
    return ""


def review_words(verdict) -> str:
    """The words for a critic verdict; a verdict this vocabulary lacks is said as unrecognised."""
    table = document()["review_words"]
    key = "" if verdict is None else str(verdict)
    return table[key] if key in table else f"review verdict not recognised: {key}"


# --- which level a record carries ----------------------------------------------------------------

def _explicit(record: dict):
    """(present, value) of a record's own `proof_level` — an empty value counts as absent."""
    value = record.get("proof_level")
    return (value not in (None, ""), value)


def level_of(record) -> str | None:
    """The level id a receipt, probe record or window probe block carries; the first rule that
    matches wins:
      1. an explicit KNOWN `proof_level` (an explicit unknown one is None, never guessed past);
      2. `probe_tool == "probe_by_code.py"` or a `window_probe` key: the live check;
      3. `mutation_kind`, else `mutation`, among a level's `mutation_kinds`;
      4. a receipt carrying every `contract.PROOF_FIELDS` and no `probe_tool`: a pre-change
         `red_sandbox.py` receipt, which caught a broken product;
      5. otherwise None."""
    if not isinstance(record, dict):
        return None
    present, value = _explicit(record)
    if present:
        return value if _by_id(value) else None
    if record.get("probe_tool") == LIVE_TOOL or "window_probe" in record:
        return LIVE
    kind = record.get("mutation_kind") or record.get("mutation")
    if isinstance(kind, str) and kind:
        for row in levels():
            if kind in row["mutation_kinds"]:
                return row["id"]
    if not record.get("probe_tool") and all(
            record.get(key) not in (None, "") for key in C.PROOF_FIELDS):
        return PRODUCT
    return None


def probe_problem(probe) -> str:
    """"" when a window probe block's level and mutation kind agree, else what is wrong:
    `level` (an explicit proof_level the vocabulary does not know) or `mutation_kind` (a block
    that claims to catch a broken product, or names no level at all as every window before
    levels did, without the mutation kind that level is made of). The live level has no demand:
    its mutation is the assertion, and that is what it proves."""
    probe = probe if isinstance(probe, dict) else {}
    present, value = _explicit(probe)
    if present and not _by_id(value):
        return "level"
    level = value if present else PRODUCT
    if level != PRODUCT:
        return ""
    return "" if probe.get("mutation_kind") in mutation_kinds(PRODUCT) else "mutation_kind"


# --- is a proof demanded -------------------------------------------------------------------------

def _handed_keys(manifest) -> set:
    try:
        rows = C.handed_tests(manifest) if isinstance(manifest, dict) else []
    except Exception:
        rows = []
    return {str(key) for row in rows for key in (row.get("case"), row.get("case_id")) if key}


# The stored novelty of a row (t-134 P5): code measures once whether a test is new, changed or
# unchanged against the story's base and writes it on the row (`manifest_from_tests.py`); this module
# only READS it. The four values are the closed set of that contract - their identity is code, in
# this one place, like the two level ids above. A reader never computes a value; it can only degrade
# one (`unchanged` -> `unknown`), so every doubt lands on "a live check is required".
NOVELTY_VALUES = ("new", "changed", "unchanged", "unknown")
_NOVELTY_DEMANDS = ("new", "changed", "unknown")
WHY_NOVELTY_MALFORMED = "the recorded novelty is malformed"
WHY_NOVELTY_NO_FILE = ("the recorded novelty is malformed (an unchanged test names no file it was "
                       "measured on)")

# A measured file is re-hashed once per (path, size, mtime_ns) in a process (FR-27). Such a key has
# ONE known weakness: a file rewritten with the SAME size inside the same mtime tick keeps its key.
# The error direction is kept by not trusting a young key: a hash is cached only when the file's
# mtime is older than `_RACY_NS` (the coarsest tick in use, FAT's 2 s) at the moment it is taken, and
# when the file did not move while it was read - a younger file is re-hashed on every question.
# What stays open (named, not hidden): a rewrite of the same size whose mtime is put back by hand
# (`os.utime`, a copy that keeps times) after the hash was cached; `_reset()` forgets the cache.
_RACY_NS = 2_000_000_000
_HASH_LIMIT = 4096
_HASH_CACHE: dict = {}


def _raw_sha(path: Path) -> str:
    """The raw sha256 of a file, cached per (path, size, mtime_ns) once the file has settled; `""`
    when it is not a readable regular file (never raises)."""
    try:
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            return ""
        key = (str(path), before.st_size, before.st_mtime_ns)
        if key in _HASH_CACHE:
            return _HASH_CACHE[key]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        after = path.stat()
    except (OSError, ValueError):
        return ""
    unmoved = (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    if unmoved and time.time_ns() - before.st_mtime_ns > _RACY_NS:
        if len(_HASH_CACHE) >= _HASH_LIMIT:
            _HASH_CACHE.clear()
        _HASH_CACHE[key] = digest
    return digest


def _measured_path(name) -> str:
    """The project-relative form of a path a measurement names, `""` when it is not one: not text,
    empty, absolute (a drive, a UNC root, a leading slash) or climbing out of the project (`..`)."""
    if not isinstance(name, str) or not name.strip() or "\x00" in name:
        return ""
    if PureWindowsPath(name).anchor or PurePosixPath(name).anchor:
        return ""
    if ".." in re.split(r"[\\/]+", name):
        return ""
    return name


def _stale_measurement(measured, project) -> str:
    """"" when every file the novelty was measured on still hashes as recorded, else the first
    path that does not (sorted, so the answer is stable) - or the words for a record that names none."""
    if not isinstance(measured, dict) or not measured:
        return WHY_NOVELTY_NO_FILE
    root = Path(project) if project is not None else _project()
    for name in sorted(measured, key=str):
        good = _measured_path(name)
        recorded = measured[name]
        if (not good or root is None or not isinstance(recorded, str) or not recorded
                or _raw_sha(root / good) != recorded):
            return f"{name} changed since the measurement, or cannot be read"
    return ""


def novelty_of(entry, project=None) -> tuple:
    """`(value | None, basis)` - THE one reader of a row's stored `novelty`. It only degrades a value,
    never computes one, and writes nothing.
      key absent                          (None, "")        a legacy row: today's rule applies to it
      not an object, or a `value` outside NOVELTY_VALUES (exact text)
                                          ("unknown", malformed)
      `resolved: true` (a window item: the block carries NEITHER `measured_on` NOR `measured_by`, by
                        key presence)     the value as stored; nothing is re-hashed. On a block that
                                          carries either key (the row form) `resolved` is ignored.
      row form `unchanged`                every `measured_on` path re-hashed under the project root
                                          (`_project()` unless given) and compared; any mismatch or
                                          failure gives ("unknown", "<path> changed since the
                                          measurement, or cannot be read")
      `new`, `changed`, `unknown`         as stored (a later edit cannot make "absent at base" untrue)
    This function cannot tell a window item from a manifest row, so it honours the item form on
    whatever it is handed. What keeps the item form off ROWS is the writer, not this reader:
    `manifest_put` refuses a `tests[]` row whose `novelty` carries `resolved` or lacks `measured_on` /
    `measured_by` (t-187, F-B), so a row written through it always has the row form and an `unchanged`
    on it is re-hashed. A manifest edited by hand, or written before that refusal, is not covered by it.
    """
    if not isinstance(entry, dict) or "novelty" not in entry:
        return None, ""
    raw = entry["novelty"]
    value = raw.get("value") if isinstance(raw, dict) else None
    if not isinstance(value, str) or value not in NOVELTY_VALUES:
        return "unknown", WHY_NOVELTY_MALFORMED
    basis = raw.get("basis") if isinstance(raw.get("basis"), str) else ""
    item_form = raw.get("resolved") is True and "measured_on" not in raw and "measured_by" not in raw
    if value == "unchanged" and not item_form:
        stale = _stale_measurement(raw.get("measured_on"), project)
        if stale:
            return "unknown", stale
    return value, basis


def _binding_says_new(entry: dict, manifest) -> bool:
    """True when an obligation binding of the manifest lists this row under any live alias of its
    instance id and says `change_disposition == new_or_changed`. An alias the manifest retracted
    (`retracted_instances[]`) does not connect a binding to the row."""
    bindings = manifest.get("obligation_bindings") if isinstance(manifest, dict) else None
    if not isinstance(bindings, list):
        return False
    try:
        aliases = set(without_retracted(C.instance_id_aliases(entry), manifest))
    except Exception:  # a row whose ids cannot be told: the layer cannot be read, so it demands
        return True
    for binding in bindings:
        if isinstance(binding, dict) and binding.get("change_disposition") == "new_or_changed":
            listed = binding.get("instance_ids")
            if isinstance(listed, list) and aliases & {str(i) for i in listed}:
                return True
    return False


def _wanted(entry: dict, manifest) -> bool:
    """Before the handed exemption: does any layer say this row is new or changed. The row's own
    flags decide alone when the row carries no `novelty` key (today's rule, and a binding's
    disposition is not read); when it carries the key, the measured value and the manifest's
    obligation bindings can each only ADD a requirement."""
    if (entry.get("sensitivity_proof_required") or entry.get("new_or_changed")
            or entry.get("change_disposition") == "new_or_changed"):
        return True
    if "novelty" not in entry:
        return False
    return novelty_of(entry)[0] in _NOVELTY_DEMANDS or _binding_says_new(entry, manifest)


def _handed(entry: dict, manifest) -> bool:
    mine = {str(case) for case in C.manifest_test_links(entry) if case}
    if entry.get("case"):
        mine.add(str(entry["case"]))
    return bool(mine & _handed_keys(manifest))


def proof_required(entry, manifest) -> bool:
    """THE predicate: a live check is demanded of a manifest row that is new or changed and that
    none of the cases it proves was handed to the person — nothing runs here for a handed test, so
    nothing can be asked to have been proven (TP2-2536). Order:
      (a) `entry` is not an object: False.
      (b) no `novelty` key: only the row's own flags count (`sensitivity_proof_required`,
          `new_or_changed`, `change_disposition == new_or_changed`) - a story in flight is never
          refused over a field it does not have (builder-rules 9), and a binding is not read.
      (c) the key is there: required when a flag says so, OR `novelty_of(entry)` is new, changed or
          unknown, OR an obligation binding lists the row (any live alias) as new_or_changed. A layer
          can only add a requirement: a role's or a binding's `unchanged` never overrules a measured
          new, changed or unknown.
      (d) the handed exemption applies last, to whatever (a)-(c) wanted.
    A row that is not required keeps whatever receipt it reached, shown as before."""
    if not isinstance(entry, dict):
        return False
    return _wanted(entry, manifest) and not _handed(entry, manifest)


def not_required_why(entry, manifest) -> str:
    """Why no live check is demanded of a row, as one word; the words of each are `words_for(reason)`
    (data in `verification-levels.json`): `""` - one IS demanded; `handed` - a case it proves was handed
    to the person; `unmeasured` - a legacy row, whose novelty nobody measured (no `novelty` key, or not
    a row at all); `unchanged` - a measured, fresh `unchanged`. The reason codes `unchanged` and
    `unmeasured` are the only way to tell those two apart: by the owner's decision (30.09) both read
    with the same words. `handed` is decided FIRST, whatever else says about the row (keyless, fresh
    `unchanged`, flagged): a case handed to the person is never "unchanged" in words (FR-10). It moves
    only the reason: `proof_required` is untouched, and a handed row is never required."""
    if not isinstance(entry, dict):
        return "unmeasured"
    if _handed(entry, manifest):
        return "handed"
    if _wanted(entry, manifest):
        return ""
    return "unchanged" if "novelty" in entry else "unmeasured"


# --- the bytes of a row's test -------------------------------------------------------------------
# `test_content_sha` / `test_content_hash` mean ONE thing everywhere: the raw sha256 of the test
# file's bytes — what `manifest_from_tests.py` writes into `trace_binding` and what
# `validate_artifacts.check_manifest_v0` enforces against the file ("actual file hash required").
# A run block's `source_fingerprint.test_content_sha` is a DIFFERENT quantity (a content hash of the
# path/sha records of the test AND helper files, `execution_fingerprint.build`) and is never compared
# with it. On TP1-13797 (driver3) the same bytes read 6992616693fc... raw and bd6d28d6aade... as
# a fingerprint, and a gate that compared the two refused a live receipt to every row it should
# have written one for (critic t-035).
#
# The CURRENT bytes of a row's test have one reader, below: the file as it is on disk now. A row
# that binds no bytes is not waved through (that leniency let a receipt for old bytes stand for
# a changed test); only when the file cannot be found are the bytes unknown, and then no level is
# shown as reached (FR-41).

def test_file_of(entry) -> str:
    """The project-relative test file a manifest row names: its `file`, else the file part of its
    node path (`trace_binding.selector`, `selector`, `node_id`)."""
    if not isinstance(entry, dict):
        return ""
    raw = str(entry.get("file") or "")
    if not raw:
        binding = entry.get("trace_binding") if isinstance(entry.get("trace_binding"), dict) else {}
        for node in (binding.get("selector"), entry.get("selector"), entry.get("node_id")):
            if isinstance(node, str) and "::" in node:
                raw = node.split("::", 1)[0]
                break
    return raw.replace("\\", "/")


def _project() -> Path | None:
    try:
        from hooklib import project_root
        return project_root()
    except Exception:  # no project to read from: the bytes are unknown, never guessed
        return None


def current_test_bytes(entry, project=None) -> bytes | None:
    """THE reader of "the current bytes of this row's test": the file the row names, read under the
    project (`hooklib.project_root()` unless given) — the same place `validate_artifacts` reads it
    from; manifests name files relative to the project, never absolute
    (`manifest_from_tests._relative`, audit A20). None when the file cannot be found."""
    file = test_file_of(entry)
    root = Path(project) if project is not None else _project()
    if not file or root is None or Path(file).is_absolute():
        return None
    path = root / file
    try:
        return path.read_bytes() if path.is_file() else None
    except OSError:
        return None


def current_test_sha(entry, project=None) -> str:
    """The raw sha256 of the row's test as it is now; `""` when the file cannot be found."""
    data = current_test_bytes(entry, project)
    return hashlib.sha256(data).hexdigest() if data is not None else ""


def code_sha(data, name: str = "") -> str:
    """`diff_scope.executable_sha` of these bytes — what can execute in them by Python's tokenizer,
    comments, blank lines, docstrings and the factory's case markers left out (D-0017: "cosmetic is
    measured, not judged", ONE classifier). `""` - the raw rule only, the safe direction - for bytes
    that are not UTF-8, source that does not tokenize, or a file `name` that is not `.py`."""
    if data is None:
        return ""
    try:
        text = bytes(data).decode("utf-8")
    except (UnicodeDecodeError, TypeError):
        return ""
    import diff_scope
    return diff_scope.executable_sha(text, name)


def current_code_sha(entry, project=None) -> str:
    """`code_sha` of the row's test as it is now; `""` when the file is gone, not UTF-8, not
    Python, or does not tokenize."""
    return code_sha(current_test_bytes(entry, project), test_file_of(entry))


def claimed_test_sha(entry) -> str:
    """The bytes the author BOUND the row to (`trace_binding.test_content_sha`), else — a row that
    binds none — the current bytes from the one reader. What a receipt claims to be about."""
    if not isinstance(entry, dict):
        return ""
    binding = entry.get("trace_binding") if isinstance(entry.get("trace_binding"), dict) else {}
    return str(binding.get("test_content_sha") or entry.get("test_content_sha") or "") \
        or current_test_sha(entry)


# --- one identity of a test, and the one predicate that compares it (t-043 C) --------------------
# A review, a probe, a receipt and a probe's record each used to be bound to the raw bytes of the
# WHOLE test file (with a code sha beside it for the receipts): fixing test_b after test_a was
# reviewed made test_a's review and probe stale, and the run budget already knew better - `--mine`
# writes `instance_contracts[<iid>].instance_content_sha` / `.instance_code_sha`, the shas of ONE
# test over its own function, its class, the fixtures and helpers it uses and the module skeleton
# (`execution_fingerprint.function_sha`). Here that identity is measured again over the bytes on
# disk now, by the same producer, and ONE predicate says whether a carrier of it still speaks for
# the test. Its only allowed error is "different": a wrong "same" would let a proof of other code
# stand for changed code. Identity v2 (FB-10) forgives exactly one difference: a test FUNCTION ADDED
# to the file (`execution_fingerprint._test_gaps`: the definition and the blank/comment gap before
# it); any other module-level change stales every sibling, and a file that does not parse is its own
# identity. The code sha is byte-equal to v1's, so a carrier recorded before stays `instance_code`.

# Why a test has no per-test identity now. The sentences ARE the closed set: a carrier records one,
# and `same_test` reads it by equality, never by what it says. The first two are not a defect of the
# measurement - nothing could be measured because no run of the story selected the test yet, or no
# story folder was given - and the file rules of before apply. Every other cause is a MEASUREMENT
# that failed, and a proof that has an identity is never kept by a measurement that has none.
WHY_NO_TASK = "no story folder was given, so no run of the test can be looked up"
WHY_NO_REQUEST = "no run of this story selected the test yet"
WHY_NO_FILE = "the test file cannot be found under the project"
WHY_UNMEASURED = ("the run's command is not pytest, or its selector, its files or its bytes "
                  "could not be measured")
WHY_NO_CODE = ("the code of the test or of a file it depends on cannot be told (not UTF-8, "
               "not Python, or it does not tokenize)")
WHY_CHANGED = "the test file changed while it was measured"
# The set is CLOSED: these six sentences are the only causes. A window item records one as
# `instance_identity_why` (only when a MEASUREMENT cause left it without an identity) and `proof_identity`
# reads it back as `why`; `same_test` compares by equality, never by what the sentence says.
FALL_THROUGH = frozenset({WHY_NO_TASK, WHY_NO_REQUEST})
MEASUREMENT = frozenset({WHY_NO_FILE, WHY_UNMEASURED, WHY_NO_CODE, WHY_CHANGED})

IDENTITY_KEYS = ("instance_content_sha", "instance_code_sha", "job_id")

# For one process only (FR-27): the jobs of a story read once per state of its job directory, and the
# identity of a row once per (story, instance, raw bytes, job directory, inputs of the run's request).
_JOBS_CACHE: dict = {}
_IDENTITY_CACHE: dict = {}


def _job_directory_signature(directory: Path):
    """None when the directory is not there (a reader never creates it, FR-45); False when it cannot be
    read; else the name, size and mtime of every job file - the state the cache is keyed on."""
    try:
        with os.scandir(directory) as scan:
            rows = []
            for item in scan:
                if item.name.endswith(".json"):
                    stat = item.stat()
                    rows.append((item.name, stat.st_size, stat.st_mtime_ns))
            return tuple(sorted(rows))
    except FileNotFoundError:
        return None
    except OSError:
        return False


def _story_jobs(directory: Path, signature):
    """[(job_id, request)] of the story's behavioral jobs other than a red probe, oldest first; None
    when they cannot be read. Read once per directory state."""
    key = (str(directory), signature)
    if key not in _JOBS_CACHE:
        try:
            from execution_request import BEHAVIORAL, JobStore
            jobs = JobStore(directory).jobs()
            _JOBS_CACHE[key] = [(str(job.get("job_id") or ""), job["request"]) for job in jobs
                                if job["request"].get("purpose") in BEHAVIORAL - {"red_probe"}]
        except Exception:
            _JOBS_CACHE[key] = None
    return _JOBS_CACHE[key]


def _row_ids(entry: dict) -> list:
    ids = [C.test_instance_id(entry), *C.instance_id_aliases(entry)]
    return [str(i) for i in dict.fromkeys(ids) if i]


def node_selects_row(entry: dict, selected: str, node_file, strict: bool = False) -> bool:
    """The ONE rule "this test node / selected id is this manifest row" (AR-13): the selected id is the row's own
    id, one of its aliases, or a parametrized form of it (`covered_by`), AND the node's file is the row's file.
    A bare alias is shared by the rows of several files, so the id alone never says WHICH test ran. Without a node
    file (a job with no selector) the path is not asked, unless `strict` (a caller that must name the row: no
    file, no row)."""
    from execution_request import covered_by
    row_file = test_file_of(entry)
    if strict or (node_file is not None and row_file):
        if not same_path(node_file, row_file):
            return False
    return any(covered_by(one, [selected]) for one in _row_ids(entry))


def _newest_request(jobs, entry: dict) -> tuple:
    """(request, the first selected id the row covers, job id) of the NEWEST job that selected the row
    (its own id, one of its aliases, or a parametrized form of it), else None."""
    from execution_request import selector_file
    for job_id, request in reversed(jobs):
        for selected in request.get("selected_instance_ids") or []:
            # A bare alias (`test_x`) is shared by the rows of several files, and a parametrized form
            # is covered from any file: the id alone never says WHICH test ran. The node the job ran
            # must be in the row's own file, else this job is another test's (the dangerous error:
            # an identity measured on the wrong file keeps a proof over a real code edit).
            # the file the job selected the test in: the contract's own, else the first selector token as a node id (B-2)
            if node_selects_row(entry, selected, selector_file(request, selected)):
                return request, str(selected), job_id
    return None


def _inputs_signature(project: Path, request: dict) -> tuple:
    """(path, size, mtime) of every file the request's derivation reads - its test files, its helpers and
    the conftest chain as they are now - so a helper edited under a cached identity is not missed."""
    from execution_request import _conftest_chain
    records = [r for r in request.get("fingerprint_files") or [] if isinstance(r, dict) and r.get("path")]
    tests = [str(r["path"]) for r in records if r.get("kind") == "test_files"]
    helpers = [str(r["path"]) for r in records if r.get("kind") == "helper_files"]
    command = request.get("command") if isinstance(request.get("command"), dict) else {}
    cwd = Path(str(command.get("cwd") or "."))
    try:
        run_cwd = (cwd if cwd.is_absolute() else Path(project) / cwd).resolve()
        paths = tests + helpers + _conftest_chain(tests, run_cwd)
    except Exception:
        paths = tests + helpers
    out = []
    for path in dict.fromkeys(paths):
        try:
            stat = Path(path).stat()
            out.append((path, stat.st_size, stat.st_mtime_ns))
        except OSError:
            out.append((path, None, None))
    return tuple(out)


def instance_identity(entry, task_root, project=None) -> dict:
    """`{"input_hash", "test_code_sha", "instance_identity", "why"}` of a manifest row's test as it is NOW.

    ONE read of the file gives the raw sha256 (`input_hash`) and `code_sha` of those same bytes.
    `instance_identity` is `{"instance_content_sha", "instance_code_sha", "job_id"}` - the shas
    `--mine` wrote into the newest behavioral job (not a red probe) that selected the row's test,
    re-measured over the bytes on disk by `execution_request.instance_shas`, the producer of the
    originals (FR-16) - or `{}`, and then `why` says which cause (one of the closed sets above). It is
    kept only when its code sha is non-empty: a per-test identity nobody can classify is not one. The
    file is read again after the measurement; bytes that moved in between give no identity, so the two
    shas are never those of different bytes. Nothing is created here: a story without a job
    directory has no identity, and the directory is not made for it (FR-45)."""
    entry = entry if isinstance(entry, dict) else {}
    out = {"input_hash": "", "test_code_sha": "", "instance_identity": {}, "why": WHY_NO_FILE}
    data = current_test_bytes(entry, project)
    if data is None:
        return out
    raw = hashlib.sha256(data).hexdigest()
    out.update(input_hash=raw, test_code_sha=code_sha(data, test_file_of(entry)), why="")
    if task_root is None:
        out["why"] = WHY_NO_TASK
        return out
    directory = Path(task_root) / "state" / "execution-jobs"
    signature = _job_directory_signature(directory)
    if signature is None:
        out["why"] = WHY_NO_REQUEST
        return out
    jobs = _story_jobs(directory, signature) if signature is not False else None
    if jobs is None:
        out["why"] = WHY_UNMEASURED
        return out
    found = _newest_request(jobs, entry)
    if found is None:
        out["why"] = WHY_NO_REQUEST
        return out
    request, instance_id, job_id = found
    root = Path(project) if project is not None else _project()
    key = (str(task_root), instance_id, raw, signature, _inputs_signature(root, request))
    shas = _IDENTITY_CACHE.get(key)
    if shas is None:
        from execution_request import instance_shas
        shas = instance_shas(root, request, instance_id)
    again = current_test_bytes(entry, project)
    if again is None or hashlib.sha256(again).hexdigest() != raw:
        out["why"] = WHY_CHANGED
        return out
    _IDENTITY_CACHE[key] = shas
    if not shas:
        out["why"] = WHY_UNMEASURED
    elif not shas.get("instance_code_sha") or not shas.get("instance_content_sha"):
        out["why"] = WHY_NO_CODE
    else:
        out["instance_identity"] = {"instance_content_sha": shas["instance_content_sha"],
                                    "instance_code_sha": shas["instance_code_sha"], "job_id": job_id}
    return out


def _kept(identity) -> dict:
    """A carrier's per-test identity as it counts: only one with a code sha, and only its keys."""
    if not isinstance(identity, dict) or not str(identity.get("instance_code_sha") or ""):
        return {}
    return {key: str(identity.get(key) or "") for key in IDENTITY_KEYS}


def proof_identity(record) -> dict:
    """`{"input_hash", "test_code_sha", "instance_identity"}` of any carrier - one normalisation of
    the fields each of them spells its own way:

      window item, review, probe      `input_hash`
      live / product receipt          `test_content_hash`
      probe records (either tool)     `test_file_sha256` (their `input_hash` is the run's fingerprint,
                                      another quantity - t-035 - and is never read as bytes)

    The flat `instance_content_sha` of a probe record written before per-test binding was that tool's
    own conftest-only derivation, never the shas `--mine` writes into `instance_contracts`; it is not
    read as an identity. A carrier that recorded why it has none (`instance_identity_why`, a window
    item) carries that too."""
    record = record if isinstance(record, dict) else {}
    out = {"input_hash": str(record.get("test_content_hash") or record.get("test_file_sha256")
                             or record.get("input_hash") or ""),
           "test_code_sha": str(record.get("test_code_sha") or ""),
           "instance_identity": _kept(record.get("instance_identity"))}
    why = record.get("instance_identity_why")
    if isinstance(why, str) and why:
        out["why"] = why
    return out


def compare_identity(a, b) -> tuple:
    """The ONE comparison of two per-test identities (AR-13): `(verdict, basis)`, verdict in
    {"same", "different", "unknown"}, basis in {"code", "content", ""}. `a`/`b` are dicts read ONLY at
    `instance_content_sha` / `instance_code_sha`; a value is `str(v or "").strip()` and empty means "none"
    (a non-dict is "unknown"). The rule: 1. the code sha is non-empty on both sides: equal -> "same" (basis
    "content" when the content sha is also non-empty on both and equal, else "code" - a comment-only edit),
    not equal -> ("different", "code") even when the content sha is equal; 2. else the content sha is
    non-empty on both: equal -> ("same", "content"), else ("different", "content"); 3. else "unknown".

    The error direction: a false "same" lies to delivery (a proof, a run or a red/green pair of other code
    is counted), so every caller that decides one of those folds "unknown" and "different" to "not the
    same". The one caller with the opposite safe side (`execution_request._same_identity_for_count`, a
    budget) folds it itself - this function never collapses "unknown". Cost of rule 1 over equal content
    (E2): a change of `case-markers.json` or `executable_sha` re-proves every carrier of an affected test; a
    release doing so says it in CHANGELOG.

    Accepted risk (RH1-9 m3): the strip makes a whitespace-only sha "none". No producer writes one (shas are
    hex digests or ""), so no branch is added for it; were one ever written it would read as absent, which
    can move a red/green pair from "changed" to the `file` basis in `run_history._compare_shas`."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return "unknown", ""

    def pick(side: dict, key: str) -> str:
        return str(side.get(key) or "").strip()
    code_a, code_b = pick(a, "instance_code_sha"), pick(b, "instance_code_sha")
    content_a, content_b = pick(a, "instance_content_sha"), pick(b, "instance_content_sha")
    if code_a and code_b:
        if code_a != code_b:
            return "different", "code"
        return "same", ("content" if content_a and content_a == content_b else "code")
    if content_a and content_b:
        return ("same" if content_a == content_b else "different"), "content"
    return "unknown", ""


def same_test(now, bound) -> str:
    """Does a carrier `bound` still speak for the test as it is `now`? Both are `proof_identity`-shaped
    (`instance_identity()`'s own answer is too, and adds `why`). "raw" | "instance" | "instance_code" |
    "file_code" | "" - the FIRST rule that matches wins; every equality needs two NON-EMPTY values, so
    two absent or unmeasured things are never "the same".

    ACCEPTED RISK (F5), beside `run_freshness`'s: a legacy carrier with no identity and a test with no run
    at its new path compare by the raw file: a moved file with the same bytes under another `conftest.py`
    reads `raw`.

      1. both carry a per-test identity (`compare_identity`): the same, decided by content -> "instance";
         decided by code (a comment-only edit inside the test's identity) -> "instance_code"; else "" -
         different code is "" even when the content sha is equal. The file's raw
         or code sha is NOT consulted: a fixture or helper inside the identity changing makes the
         proof stale, as it makes the run due.
      1b. exactly one side carries one, and the OTHER side has none because its MEASUREMENT failed (its
         `why` in MEASUREMENT - `now`'s own, or the one a review copied from its receipt): "". A proof
         that had an identity is not kept by a measurement that has none, and an identity is not
         matched to a proof whose measurement failed. When the side without has none only because no
         run selected the test or no story folder was given (FALL_THROUGH), or is the older carrier
         (a review or receipt from before per-test binding, no `why`), the file rules below apply as
         they always did.
      2. both raw file shas equal -> "raw".
      3. both file code shas equal -> "file_code" (a legacy carrier that recorded `test_code_sha`).
      4. otherwise "".
    """
    now = now if isinstance(now, dict) else {}
    bound = bound if isinstance(bound, dict) else {}
    ours, theirs = _kept(now.get("instance_identity")), _kept(bound.get("instance_identity"))
    if ours and theirs:
        verdict, basis = compare_identity(ours, theirs)
        if verdict == "same":
            return "instance" if basis == "content" else "instance_code"
        return ""
    if bool(ours) != bool(theirs) and (bound if ours else now).get("why") in MEASUREMENT:
        return ""
    raw = str(now.get("input_hash") or "")
    if raw and raw == str(bound.get("input_hash") or ""):
        return "raw"
    code = str(now.get("test_code_sha") or "")
    if code and code == str(bound.get("test_code_sha") or ""):
        return "file_code"
    return ""


# --- did the latest run of a test run the code it holds now (HF2-11) --------------------------------
# `same_test` says whether a REVIEW, a PROBE or a RECEIPT still speaks for a test. This is the same
# question asked of a RUN: a green run of other code is not a green test. The run row already carries
# the answer's other half - `run_suite.build_run_block` writes `instance_content_sha` and
# `instance_code_sha` into it, the producer's own shas of the test it ran - and `instance_identity`
# measures the same two over the bytes on disk now; the comparison is `same_test`'s, not a second one.

WHY_RUN_NO_IDENTITY = "the run recorded no per-test identity"
WHY_RUN_CHANGED = "the test, or a fixture or helper it uses, changed since {run}"
WHY_RUN_UNMEASURABLE = "the test or a file it depends on cannot be measured now"
WHY_RUN_NOT_COMPARED = ("the test has no per-test identity to compare: no run of the story selected it, "
                        "or no story folder was given")
WHY_NO_RUN = "no run of this instance reached a result"
RUN_SHA_KEYS = ("instance_content_sha", "instance_code_sha")


def run_identity(row) -> dict:
    """The per-test identity a run row recorded: `{"instance_content_sha", "instance_code_sha"}` and, when
    the row names its attempt, `"attempt_id"` - or `{}`. BOTH shas or nothing: a row with one of them (or
    with an empty one) recorded no identity, and an empty placeholder would read as a value (FR-59). The ONE
    reader of the row's shas, for `run_freshness` and for the window item that copies them (`window_record.build`)."""
    row = row if isinstance(row, dict) else {}
    shas = {key: str(row.get(key) or "") for key in RUN_SHA_KEYS}
    if not all(shas.values()):
        return {}
    attempt = str(row.get("attempt_id") or "")
    return dict(shas, attempt_id=attempt) if attempt else shas


def _run_freshness(entry, run_row, task_root, now) -> tuple:
    if not isinstance(now, dict):
        now = instance_identity(entry, task_root)
    if not now.get("input_hash"):
        return "stale", WHY_NO_FILE            # a pass belongs only to bytes that are on disk
    shas = run_identity(run_row)
    if not shas:
        return "unknown", WHY_RUN_NO_IDENTITY
    if not _kept(now.get("instance_identity")):
        why = str(now.get("why") or "")
        if why in MEASUREMENT:
            # a helper that cannot be measured now (deleted, not UTF-8, does not tokenize) is a CHANGE of what
            # the test depends on, not an absence of news: `function_sha` gives "" for it, and "" never reads fresh
            return "stale", WHY_RUN_UNMEASURABLE
        return "unknown", why or WHY_RUN_NOT_COMPARED
    if same_test(now, {"instance_identity": dict(shas, job_id="")}) in ("instance", "instance_code"):
        return "fresh", ""
    attempt = shas.get("attempt_id")
    return "stale", WHY_RUN_CHANGED.format(run=f"run {attempt}" if attempt else "its run")


def run_freshness(entry, run_row, task_root, *, now=None) -> tuple:
    """`(state, why)` - did the run `run_row` ran the code the manifest row `entry` holds NOW? `state` is
    `fresh`, `stale` or `unknown`, `why` is "" for `fresh` and the sentence for the others. Pure: nothing is
    written, no exception comes out (a measurement that raises is `unknown`, said so). `now` is
    `instance_identity()`'s answer (or `proof_identity(window item)`, which is how the window asks about a record
    and stays pure over it); without it the identity is measured here.

    In this order, the first that applies:
      1. the test file is not there: `stale`, `WHY_NO_FILE` - a pass belongs only to bytes on disk.
      2. the row has no per-test identity (no shas, or only one of them): `unknown`. The run recorded nothing
         to compare; this is PRINTED, never a pass by itself, and today's reading of the run stays.
      3. the test has no identity now: its `why` in `FALL_THROUGH` (no run of the story selected it, no story
         folder) -> `unknown`; in `MEASUREMENT` (a helper that cannot be measured now) -> `stale`, as
         `same_test` rule 1b does: a run that had an identity is not kept by a measurement that has none.
      4. `same_test` of the two identities says `instance` or `instance_code` (a comment, a docstring or a
         blank line changed, D-0017): `fresh`; anything else: `stale`.

    The error direction is the cheap one: `stale` or `unknown` cost one more run; `fresh` for changed code lets
    an old result cover a new test. Time and file mtimes decide NOTHING here.

    ACCEPTED RISK (not a safe side): what the closure of `execution_fingerprint.function_sha` does not read can
    change under a `fresh`. The blind spots are the data files a test reads (json, csv, ...); fixtures that come
    from `pytest_plugins` or an installed plugin whose module is not a declared helper of the run; and a
    `conftest.py` ABOVE the run's working directory (`execution_request._conftest_chain` stops at it). An edit
    there reads `fresh` wrongly. Naming a plugin module as a helper of the run, or running from the directory
    that holds the conftest, closes the first and the last; the data files stay out of scope (HF2-11, F-2)."""
    try:
        return _run_freshness(entry, run_row, task_root, now)
    except Exception as exc:
        return "unknown", f"run freshness could not be measured ({type(exc).__name__})"


# --- has this test been probed already -------------------------------------------------------------
# D-0018: a test is probed once over its bytes, and only a person's word repeats it. A probe that
# is asked again over the same bytes is ANSWERED (nothing is mutated, launched or written) instead of
# run - and every way the answer could be wrong goes toward running: a wrong refusal costs the person a
# question, a wrong run costs one run.

NAME_LIMIT = 100  # a file name of a probe's own record; the receipt stem has its own limit in contract
_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\s]+')


def _file_hash(file) -> str:
    """The first 8 hex of the sha256 of a test file's path, `\\` read as `/` (one name for both spellings); "" for no file."""
    text = str(file or "").replace("\\", "/").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8] if text else ""


def probe_record_path(task_root, instance_id: str, kind: str = "", target_line=None, ordinal: int = 1, file=None) -> Path:
    """`work/probes/<stem>.json` (`probe_by_code.py`) or, for kind "product", `work/probes/product/<stem>.json`
    (`red_sandbox.py --probe`) or, for kind "alternative", `work/probes/alternative/<stem>.json` (`probe_by_code.py --alternative
    <case>:ALT-n`, stem `<IID>--<CASE>--<ALT>`; the readers of `work/probes/*.json` glob non-recursively and do not see it, by
    design). An id is an identity, not a file name: a long one is cut and told apart
    by the hash of the WHOLE id, so one id's record never answers for another's.

    `target_line` (an int, the default kind only; t-2045 N1b, t-2064 P4a): the PER-CHECK form
    `work/probes/checks/<stem>--L<line>.json`, where a probe of another line is kept so that it never overwrites a proved record of
    the obligation's check (the beside record) and where the per-check records of one probe live. The readers of `work/probes/*.json`
    (`probe_debt._scan`, `handoff_check`) glob non-recursively and do not see the sub-directory, the convention of `alternative/`.
    `ordinal` (2 or more; a second check on the same line, EP-O) adds `-<ordinal>` after the line: `<stem>--L<line>-2.json`. The
    suffix is added after the cut, so it survives a long id; anything but an int `target_line` (a bool included) is today's path,
    byte for byte, whatever `ordinal` says.
    `file` (the per-check form only; the repo-relative path of the file the check lives in): adds `-<hash8>` after the line and
    ordinal, so two files' checks on the same line have two record files. None or "" is today's name, byte for byte (an old record
    stays where it was; `record_read_path` reads it only for the file it names)."""
    name = _UNSAFE_FILENAME.sub("-", str(instance_id)).strip("-.") or "instance"
    if len(name) > NAME_LIMIT:
        name = name[:NAME_LIMIT] + "-" + hashlib.sha256(str(instance_id).encode("utf-8")).hexdigest()[:8]
    base = Path(task_root) / "work" / "probes"
    if not kind and _int_line(target_line) is not None:
        more = f"-{ordinal}" if _int_line(ordinal) is not None and ordinal >= 2 else ""
        mark = f"-{_file_hash(file)}" if _file_hash(file) else ""
        return base / "checks" / f"{name}--L{target_line}{more}{mark}.json"
    return (base / kind if kind in ("product", "alternative") else base) / f"{name}.json"


def record_read_path(task_root, instance_id: str, target_line, ordinal: int = 1, file=None) -> Path:
    """The path a by-line reader reads for the check at `file`:`target_line` (the `ordinal`-th on it). With no `file` it is
    `probe_record_path`'s old name. With one: the hashed record when it exists; else the OLD un-hashed record when it exists AND
    the record inside names this same file (`target.file`, `mutation_detail.file` or `mutated_file.path`, `same_path`); else the
    hashed path (absent). INVARIANT: a check never reads a record written for another file's check; an old record that names no
    file, or another, is treated as absent."""
    hashed = probe_record_path(task_root, instance_id, target_line=target_line, ordinal=ordinal, file=file)
    if not _file_hash(file) or hashed.is_file():
        return hashed
    old = probe_record_path(task_root, instance_id, target_line=target_line, ordinal=ordinal)
    if old == hashed or not old.is_file():
        return hashed
    try:
        stored = json.loads(old.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        return old          # unreadable proves nothing; the reader's own note ("cannot be read") still says so
    if not isinstance(stored, dict):
        return old          # the same: the reader notes "not a JSON object" and treats it as absent
    parts = [stored.get(k) if isinstance(stored.get(k), dict) else {} for k in ("target", "mutation_detail")]
    moved = stored.get("mutated_file") if isinstance(stored.get("mutated_file"), dict) else {}
    named = parts[0].get("file") or parts[1].get("file") or moved.get("path")
    return old if same_path(named, file) else hashed


TOOLING_GAP_PREFIX = C.PROBE_GAP_TOOLING_PREFIX   # the value of a person's `probe gap: tooling:<language>` word (a class of instances, EP1-36); one constant, `contract` owns it


def tooling_gap_key(task_root, identity: str, current_hash: str) -> str:
    """`tooling:<language>` when the probe's own record of THIS instance says the tool could not read the test, else "". The
    ONE reader (AR-15) of the class a person's `probe gap: tooling:<language>` word names; the window
    (`window_record.probe_gap_block`) and the acceptance (`acceptance.probe_gap_named`) both ask it.

    A key only for a record that says `cause: tooling`, whose verdict is `not_executed` or `incomplete`, that names a
    `language` (one token), and whose `test_file_sha256` EQUALS the current hash of the test (both non-empty: a record of
    other bytes says nothing about these). A record that judged the test (`intended_failure`, `no_failure`,
    `wrong_location`), no record, an unreadable one, a stand that did not run (no `cause`) and a call that was refused with
    no record give "": the class never covers what it was not asked about. Error direction: "" - the instance then needs the
    word of its own, as before. Never raises."""
    try:
        record = _read_record(probe_record_path(task_root, identity), [])
        if not record or record.get("cause") != "tooling" or record.get("verdict") not in ("not_executed", "incomplete"):
            return ""
        language = str(record.get("language") or "")
        bound, current = str(record.get("test_file_sha256") or ""), str(current_hash or "")
        if not (language and not any(ch.isspace() for ch in language) and bound and current and bound == current):
            return ""
        return TOOLING_GAP_PREFIX + language
    except Exception:
        return ""


PROBE_JUDGED_VERDICTS = ("intended_failure", "no_failure", "wrong_location")   # a record that JUDGED the test (E8)


def probe_record_state(task_root, identity: str, input_hash: str) -> dict:
    """`{"state", "record", "why", "refused"}` - what the probe's own record of THIS instance says about THESE bytes. The ONE
    reader (AR-13) of that fact: the window (`window_record.probe_gap_block`) and the class word (`probe_could_not_run`) ask it.

    `state` is one of `not_run` (no record, an unreadable one, one of other bytes - `input_hash` or `test_file_sha256` empty or
    different - or one with no verdict), `not_executed`, `incomplete` (the verdict as it stands), `judged` (`intended_failure`,
    `no_failure`, `wrong_location`: a probe that caught something is not one that could not run). `cause` is the record's own
    `cause` word for `not_executed` and `incomplete` ("" otherwise): `tooling` (the tool could not read the test), `judgment`
    (the run failed at the mutated line on a text the tool cannot read; the code critic judges it, t-1968). `judgment` is the
    verdict word of that critic's `judgment` block (`fires` / `other_failure` / `cannot_judge`) or "" when none is written.
    `record` is the record's
    path under `task_root` (posix) or None when there is no file; `why` is the one line a person reads for the state ("" when
    judged); `refused` is the record's `refused` word ("tool" for a refusal of the tool, "" otherwise). Error direction: toward
    `not_run`, never toward 'probed'. Never raises."""
    try:
        path = probe_record_path(task_root, identity)
        record = _read_record(path, [])
        rel = path.relative_to(Path(task_root)).as_posix() if path.is_file() else None
    except Exception:
        return {"state": "not_run", "record": None, "why": "no probe of these bytes was run", "refused": ""}
    current = str(input_hash or "")
    verdict = str(record.get("verdict") or "") if record else ""
    bound = str(record.get("test_file_sha256") or "") if record else ""
    refused = str(record.get("refused") or "") if record and isinstance(record.get("refused"), str) else ""
    notes = [n for n in (record.get("notes") or []) if isinstance(n, str) and n.strip()] \
        if record and isinstance(record.get("notes"), list) else []
    if not record:
        state, why = "not_run", "no probe of these bytes was run"
    elif not (current and bound and current == bound):
        state, why = "not_run", "the probe record is of other bytes"
    elif verdict == "incomplete" and record.get("plan_unfinished") is True:
        # t-2064 P4b item 7, EP-J: a walk left unfinished (its time ran out): the same call again continues it. It is neither a tool that
        # could not run nor a judgment owed; an old record has no such key and reads as before
        state, why = "plan_unfinished", notes[-1] if notes else "the plan is not finished: the same call again continues it"
    elif verdict in ("not_executed", "incomplete"):
        state, why = verdict, notes[-1] if notes else "the probe did not run"
    elif verdict in PROBE_JUDGED_VERDICTS:
        state, why = "judged", ""
    else:
        state, why = "not_run", "the probe record has no verdict"
    cause = str(record.get("cause") or "") if record and isinstance(record.get("cause"), str) else ""
    judgment, owed = "", None
    if record and state == "incomplete" and cause == "judgment":
        if isinstance(record.get("judgment"), dict):
            word = record["judgment"].get("verdict")
            judgment = word if isinstance(word, str) else ""
        # a walk's aggregate (`probe_by_code._judgment_fold`, its one producer) lists the checks that owe `--judge`; an old aggregate and
        # the single-record form carry no such list: None = "not said", read as before
        if isinstance(record.get("judgment_owed"), list):
            owed = [str(k) for k in record["judgment_owed"]]
    return {"state": state, "record": rel, "why": why, "refused": refused if state == "not_executed" else "",
            "cause": cause if state in ("not_executed", "incomplete") else "", "judgment": judgment, "judgment_owed": owed}


def probe_could_not_run(task_root, identity: str, input_hash: str) -> bool:
    """True when the probe's record of THESE bytes says the TOOL could not read the test: `incomplete`, or `not_executed` with
    `refused: tool` or with `cause: tooling` (an unbound report row; the record that says it is the tool's, as
    `tooling_gap_key` reads it). `not_executed` with neither (the stand was down, a report status, an empty report) is its own
    door, and a probe nobody ran (`not_run`) or one that judged is not 'could not run'. The ONE predicate (AR-13) the class word
    asks, in the window and in the acceptance. NEVER true for `incomplete` with `cause: judgment` (`probe_owes_judgment`: the run
    was read and failed at the mutated line; the code critic judges it, judged or not - a person's class word does not cover it,
    t-1968). Error direction: False - the instance then needs the word of its own. Never raises."""
    try:
        got = probe_record_state(task_root, identity, input_hash)
        if got["state"] == "incomplete":
            return got["cause"] != "judgment"     # `judgment` is the critic's, read from the same record
        return got["state"] == "not_executed" and (got["refused"] == "tool" or got["cause"] == "tooling")
    except Exception:
        return False


def probe_owes_judgment(task_root, identity: str, input_hash: str) -> str:
    """`"unjudged"` when the probe's record of THESE bytes (`probe_record_state`, the ONE reader) is `incomplete` with `cause:
    judgment` and no `judgment` block (the code critic owes its `--judge`); `"cannot_judge"` with that judgment written; `""`
    otherwise (another cause, a judged verdict, a record of other bytes, none). `fires` / `other_failure` turn the record into
    `intended_failure` / `wrong_location`, so they never reach here. Error direction: "" - the roads of a tooling gap then apply.
    Never raises."""
    try:
        got = probe_record_state(task_root, identity, input_hash)
        if got["state"] != "incomplete" or got["cause"] != "judgment":
            return ""
        if got["judgment"] == "cannot_judge":
            return "cannot_judge"
        # still the critic's (delivery, acceptance and the reach read "owed, unnamed by any word"); WHICH door he takes - `--judge`, or the
        # plain call when no check owes a judgment - is `probe_plain_call_owed`'s answer, read by the window's notes and refusal doors
        return "unjudged"
    except Exception:
        return ""


def probe_plain_call_owed(task_root, identity: str, input_hash: str) -> bool:
    """True when the probe's record of THESE bytes is a walk's aggregate `incomplete` with `cause: judgment` that lists no check owing the
    critic's `--judge` and holds no `cannot_judge`: what is left is a plain call of the probe (rows `--at` did not select, a check with no
    model entry yet; `--judge` would refuse). `probe_owes_judgment` still answers "unjudged" for it (the record is the critic's and no
    person's word names it); THIS says which door: the window's probe note and `probe_word_door` ask it before they name `--judge`. The
    ONE reader (AR-13) of that. An aggregate with no `judgment_owed` list (written before this fix, or the single-record form) is False:
    read as before. Error direction: False. Never raises."""
    try:
        got = probe_record_state(task_root, identity, input_hash)
        return got["state"] == "incomplete" and got["cause"] == "judgment" and got["judgment"] != "cannot_judge" and got["judgment_owed"] == []
    except Exception:
        return False


def cannot_judge_facts(task_root, identity: str, current: str):
    """The facts of a test whose probe the code critic could not judge, or None. The ONE reader (AR-13) of them: the window
    (`window_record.probe_gap_block`), the acceptance (`acceptance.probe_gap_named`) and the seam (`window_record.probe_judgment_cases`).

    None unless `probe_owes_judgment` says `cannot_judge` for THESE bytes. Otherwise `{at, why, file, line, statement_inverted,
    statement_after, failure_text}` read from the record's `judgment` and `judgment_facts` (each `""`/None when the record lacks it;
    nothing is invented). Never raises."""
    try:
        if probe_owes_judgment(task_root, identity, current) != "cannot_judge":
            return None
        record = _read_record(probe_record_path(task_root, identity), []) or {}
        said = record.get("judgment") if isinstance(record.get("judgment"), dict) else {}
        facts = record.get("judgment_facts") if isinstance(record.get("judgment_facts"), dict) else {}
        return {"at": str(said.get("at") or ""), "why": " ".join(str(said.get("why") or "").split()),
                "file": facts.get("file"), "line": facts.get("line"), "statement_inverted": facts.get("statement_inverted"),
                "statement_after": facts.get("statement_after"), "failure_text": str(facts.get("failure_text") or "")}
    except Exception:  # noqa: BLE001 - a reader that offers a door must never stop the window
        return None


def not_proved_word(facts, keys, proved: dict):
    """`(key, {"words", "at"})` of the person's `probe not proved: <case key>` word that names a `cannot_judge` test, or None.

    `facts` is `cannot_judge_facts`; `keys` the case keys of the instance (never its id, never a `probe gap:` word); `proved` is
    `contract.probe_not_proved_words`. A word answers the facts it was shown (E5.2): it is read only when its `at` is not older
    than the judgment's `at`; an unreadable stamp on either side reads nothing. Error direction: None (the person is asked
    again). Never raises."""
    try:
        if not facts:
            return None
        judged = C._answer_moment(facts.get("at"))
        for key in keys:
            said = proved.get(key)
            if said and judged != float("-inf") and C._answer_moment(said.get("at")) >= judged:
                return key, said
    except Exception:  # noqa: BLE001
        pass
    return None


def _read_record(path: Path, notes: list):
    """The record at `path` as a dict; None when there is none, and None with a note when it cannot be
    read (an unreadable verdict never blocks, and the person is told, not left to guess)."""
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        notes.append(f"the probe record {path.name} cannot be read ({type(exc).__name__}): it is treated "
                     "as absent")
        return None
    if not isinstance(value, dict):
        notes.append(f"the probe record {path.name} is not a JSON object: it is treated as absent")
        return None
    return value


def same_path(named, other) -> bool:
    """The ONE rule "these two paths name the same file" (AR-13, AR-4): `\\` read as `/`, outer `/` stripped,
    equal or one is the other's tail on a `/` boundary; the case counts, on every OS. The safe error is "not
    the same" for every caller (a false "same" keeps a proof, skips a byte check or compares another file)."""
    a, b = str(named or "").replace("\\", "/").strip("/"), str(other or "").replace("\\", "/").strip("/")
    return bool(a and b) and (a == b or a.endswith("/" + b) or b.endswith("/" + a))


def _mutated_files_hold(record: dict, entry: dict, project) -> bool:
    """Does every file the probe MUTATED other than the row's own test file still hold the bytes it
    held then? The test file is `same_test`'s; an oracle in a helper or the product is not, and a verdict
    measured on other oracle or product bytes says nothing about these ones (t-061 fixes 2 and 6). Each
    recorded file needs its raw sha equal or its code sha equal, both NON-EMPTY (a file that cannot be
    read has neither). A record from before this key existed that names an oracle outside the test
    (`mutation_detail.file`) cannot be checked, and never holds; one that names none mutated the test."""
    files = record.get("mutated_files")
    if not isinstance(files, list):
        one = record.get("mutated_file")
        files = [one] if isinstance(one, dict) else None
    if files is None:
        outside = (record.get("mutation_detail") or {}).get("file") if isinstance(
            record.get("mutation_detail"), dict) else None
        return not (outside and not same_path(outside, test_file_of(entry)))
    root = Path(project) if project is not None else _project()
    for one in files:
        if not isinstance(one, dict):
            return False
        path = str(one.get("path") or "")
        if same_path(path, test_file_of(entry)):
            continue
        try:
            data = (root / path).read_bytes() if root is not None and path and not Path(path).is_absolute() else None
        except OSError:
            data = None
        if data is None:
            return False
        raw, code = hashlib.sha256(data).hexdigest(), code_sha(data, Path(path).name)
        was_raw, was_code = str(one.get("sha256") or ""), str(one.get("code_sha") or "")
        if not ((was_raw and was_raw == raw) or (was_code and was_code == code)):
            return False
    return True


def _stage_of(task_root, dispatch: str = "", stage: str = "") -> str:
    """The stage a person's word is looked up under: the dispatch's own (controller.json), else the
    running stage, else S5 - where a probe lives."""
    if stage:
        return stage
    try:
        state = json.loads((Path(task_root) / "state" / "controller.json").read_text(encoding="utf-8-sig"))
        found = str(((state.get("dispatches") or {}).get(dispatch) or {}).get("stage") or "") if dispatch else ""
    except (OSError, ValueError, AttributeError):
        found = ""
    if found:
        return found
    try:
        from execution_request import running_stage
        return running_stage(task_root) or "S5"
    except Exception:
        return "S5"


def _repeat_words(prior: str, when: str, where: str, stage: str) -> str:
    return (f"the probe of these bytes said {prior} on {when[:10] or 'an earlier date'} ({where}); nothing "
            "was mutated or run. Change the test before probing it again; a person's word passes a repeat "
            f"(waiver.py, stage {stage}, block \"{PROBE_BLOCK}\").")


def _int_line(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


# t-2045 N7 / t-2096 F2: a probe record stored with a kind the tool no longer runs still reads, and BOTH readers of a stored
# `mutation` (`_replay` here, `probe_debt._replay_plan`) replay it as the one inversion that remains - one map, one function.
REMOVED_MUTATION = "expected"
LEGACY_MUTATIONS = {REMOVED_MUTATION: "invert"}


def replay_mutation(stored):
    """The `--mutation` a stored record's `mutation` is replayed with: a legacy kind maps to its successor, anything else
    (including a non-string) is returned unchanged for the caller to judge."""
    return LEGACY_MUTATIONS.get(stored, stored) if isinstance(stored, str) else stored


def _same_target(source, target) -> bool:
    """Does the probe `source` (a probe record or a receipt) speak for the check `target` (`{file, line | None, source}`, the
    caller's `_target_of`) names? t-2045 N1b, B10: a repeat is answered by bytes AND target, or a `no_failure` on a toast that
    vanished closes the door on the retarget its own note prints.

    Requested line None has two targets. `first` (the first check): the same when the source carries no `target`, or a `target` with
    no `source`, or with `first`. `oracle` (`--oracle` without `--at`): the same only when the source's `target.source` is `oracle`,
    the file it mutated is the requested one and its `mutation_detail.oracle_function` is the requested `oracle_function`; another
    function or file, or a `first` record, is different. Requested line n: the same only when the source carries a `target`, the file
    it mutated (`mutation_detail.file`, else `mutated_file.path`) is the requested one and `line <= n <= end_line`. Anything else is
    different. ERROR DIRECTION: toward running (the module's own rule) wherever the answer can be told: an unknown file, an
    unreadable line and a record from before `target` read as different, never as the same; a wrong "different" costs one run, a
    wrong "same" refuses a probe the person asked for. The one exception is the `first` target, where a record from before `target`
    is the same on purpose (today's repeat answer, byte for byte). `target` None is not a question about a target (any other
    caller): the same, today's behaviour byte for byte."""
    if not isinstance(target, dict):
        return True
    fact = source.get("target") if isinstance(source, dict) and isinstance(source.get("target"), dict) else None
    wanted = _int_line(target.get("line"))
    detail = source.get("mutation_detail") if isinstance(source, dict) and isinstance(source.get("mutation_detail"), dict) else {}
    moved = source.get("mutated_file") if isinstance(source, dict) and isinstance(source.get("mutated_file"), dict) else {}
    if wanted is None:
        if target.get("source") == "oracle":
            return (fact is not None and fact.get("source") == "oracle"
                    and bool(target.get("oracle_function")) and detail.get("oracle_function") == target.get("oracle_function")
                    and same_path(detail.get("file") or moved.get("path"), target.get("file")))
        return fact is None or not fact.get("source") or fact.get("source") == "first"
    if fact is None:
        return False
    line = _int_line(fact.get("line"))
    end = _int_line(fact.get("end_line")) or line
    if line is None or end is None or not line <= wanted <= end:
        return False
    return same_path(detail.get("file") or moved.get("path"), target.get("file"))


def _earlier_line_note(source, target) -> str:
    """The note a different target leaves: which line the earlier probe had, so the person sees why this one runs."""
    fact = source.get("target") if isinstance(source, dict) and isinstance(source.get("target"), dict) else {}
    had = f"line {fact['line']}" if _int_line(fact.get("line")) is not None else "no recorded line"
    asked = f"line {target.get('line')}" if _int_line(target.get("line")) is not None else "the first check"
    return (f"an earlier probe of these bytes had {had}; this one asks for {asked} of {target.get('file') or 'the test'}, "
            "so it runs (a repeat is answered by the bytes and the target)")


def _product_receipt_repeat(entry, ids, now, task_root, project, check_key, notes):
    """The `already_probed` hit of a repeated PRODUCT probe (t-2064 fix round H), or None - the probe runs.

    A product receipt is `one_check` and published nowhere (it gives the test no level), so it is found in `work/sensitivity-receipts/`
    (newest first; an unreadable file is skipped) and accepted only through `product_receipt_holds` (the one reader: bytes, identity,
    scope). With `check_key` it must name that key in `checks[]`; without one, the bytes guard stands alone. Either way the product
    record of the same instance must say `intended_failure` on the same test bytes (`same_test`) and the product bytes it broke
    (`_mutated_files_hold`) - the comparison item 3 makes for `survived`. A `whole_unlisted` or no-`scope` receipt, other bytes, another
    check, a missing or unreadable record: None. Reads; writes nothing."""
    from pathlib import Path as _P
    folder = _P(task_root) / "work" / "sensitivity-receipts"
    for one in ids:
        record = _read_record(probe_record_path(task_root, one, "product"), notes)
        if not (record is not None and record.get("verdict") == "intended_failure"
                and same_test(now, proof_identity(record)) and _mutated_files_hold(record, entry, project)):
            continue
        try:
            stem = C.instance_file_stem(one)
            files = sorted((p for p in folder.glob(stem + "-*.json") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            continue
        for path in files:
            try:
                ref = {"path": path.relative_to(task_root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                got = product_receipt_holds(entry, ref, task_root, project)
            except (OSError, ValueError):
                continue
            receipt = got.get("receipt") or {}
            if not got["holds"] or receipt.get("scope") != ONE_CHECK or str(receipt.get("instance_id")) != str(one):
                continue
            if check_key and check_key not in got["keys"]:
                continue
            return {"by": "product_receipt", "level": None, "receipt_ref": ref,
                    "record": probe_record_path(task_root, one, "product").relative_to(task_root).as_posix(),
                    "prior_verdict": "intended_failure", "recorded_at": str(record.get("recorded_at") or ""),
                    "holds": same_test(now, proof_identity(record))}
    return None


def already_probed(entry, manifest, task_root, *, now=None, project=None, stage: str = "",
                   dispatch: str = "", target=None, entry_sha: str = "", kind: str = "", check_key: str = "") -> dict:
    """`{"probed": False, "notes": [...]}` - the probe runs - or `{"probed": True, "by": "receipt" |
    "probe_record" | "product_record", "instance_id", "level", "receipt_ref", "record", "prior_verdict",
    "recorded_at", "holds", "words", "block", "notes"}` - it is answered, and nothing is to be written.

    In this order, the first that applies:
      1. RECEIPT: `reached()` shows a valid level over these bytes (per test, `same_test`), and every
         file the probe behind it mutated other than the test passes `_mutated_files_hold`; a receipt
         whose mutated file cannot be checked does not block (a refusal that leaves no road to a
         receipt is a dead end - the probe that republishes it must run).
      2. PROBE RECORD (`probe_by_code.py`): the newest verdict is `no_failure` or `wrong_location` on
         the same bytes. `intended_failure` blocks only through 1; `not_executed` never blocks.
      3. PRODUCT RECORD (`red_sandbox.py --probe`): the newest verdict is `survived` on the same bytes.
      4. PRODUCT RECEIPT (only `kind="product"`, t-2064 fix round H; any other `kind` is "" and never reaches it): a `one_check` receipt
         `product_receipt_holds` accepts, naming `check_key` (none given: the bytes guard alone), over the same test bytes and the same
         product bytes the product record says were broken. `_product_receipt_repeat` is its one reader.
    `target` (t-2045 N1b; `{file, line | None, source}`, the caller's `_target_of`): items 1 and 2 answer only a probe of the
    SAME target (`_same_target`; item 2 also reads the record kept beside the standing one for that line); a probe of another
    line runs, with a note naming the line the earlier one had. `target=None` is today's behaviour, byte for byte.
    `entry_sha` (t-2064 P4a; the sha of the model entry the probe would run, default "" = not asked): the per-check record of the
    requested line (`work/probes/checks/`) answers only a record that carries the same `entry_sha`; another sha, or none recorded,
    runs the probe. A record that is missing or cannot be read is "not probed" as ever, never a pass (AR-28).
    A person's recorded word (`execution_request.person_word`, the block `PROBE_BLOCK`) passes the
    repeat if it was said after the record it repeats. It may err only toward "not probed": the run
    budget file unreadable, the vocabulary of levels unavailable and a record that cannot be read are all
    "not probed", each with its note, and never a refusal."""
    entry = entry if isinstance(entry, dict) else {}
    notes: list = []
    from execution_request import load_run_budget, person_word, word_passes
    policy, budget_note = load_run_budget()
    if policy is None:
        return {"probed": False, "notes": [budget_note + " A repeated probe is answered under the run "
                                           "budget; without it the probe runs."]}
    now = now if isinstance(now, dict) else instance_identity(entry, task_root, project)
    if not now.get("input_hash") or task_root is None:
        return {"probed": False, "notes": notes}
    ids = _row_ids(entry)
    iid = ids[0] if ids else ""
    hit = None
    try:
        got = reached(entry, manifest, task_root, now=now)
    except LevelsUnavailable as exc:
        return {"probed": False, "notes": [f"the proof levels cannot be read ({exc}); the probe runs"]}
    if got["level"]:
        ref = got["ref"] or {}
        receipt = _read_record(Path(task_root) / str(ref.get("path")), notes) if ref.get("path") else None
        if receipt is None and not ref:
            receipt = entry.get("sensitivity_proof") if isinstance(entry.get("sensitivity_proof"), dict) else None
        if isinstance(receipt, dict):
            behind = None
            if receipt.get("probe_record"):
                behind = _read_record(Path(task_root) / str(receipt["probe_record"]), notes)
            elif level_of(receipt) == PRODUCT:
                behind = _read_record(probe_record_path(task_root, iid, "product"), notes)
            # The record a receipt names is the tool's record of the LATEST probe, which every later run
            # overwrites (a `not_executed` rerun over another oracle, say). It is the receipt's own probe
            # only while it says `intended_failure` and names this very receipt; otherwise it says
            # nothing about what the receipt's probe mutated.
            own = (behind if behind is not None and behind.get("verdict") == "intended_failure"
                   and (level_of(receipt) == PRODUCT
                        or (behind.get("receipt") or {}).get("path") == ref.get("path")) else None)
            # What the probe mutated is carried by the receipt itself (`mutated_file`); a receipt from
            # before that falls back to its own record, and with neither it cannot be checked.
            carried = "mutated_files" in receipt or "mutated_file" in receipt
            checked = _mutated_files_hold(receipt, entry, project) if carried else (
                own is not None and _mutated_files_hold(own, entry, project))
            if checked and not _same_target(receipt, target):
                notes.append(_earlier_line_note(receipt, target))
            elif checked:
                holds = same_test(now, proof_identity(receipt))
                hit = {"by": "receipt", "level": got["level"], "receipt_ref": ref,
                       "record": str(receipt.get("probe_record") or ""),
                       "prior_verdict": "intended_failure",
                       "recorded_at": str((own or behind or {}).get("recorded_at") or ""), "holds": holds}
    if hit is None:
        line = _int_line(target.get("line")) if isinstance(target, dict) else None
        for one in ids:
            # the standing record, then the one kept BESIDE it for the requested line (`_finish_record`, N1b)
            for path in (probe_record_path(task_root, one),
                         *((record_read_path(task_root, one, line, file=target.get("file")),) if line is not None else ())):
                record = _read_record(path, notes)
                if (record is not None and path.parent.name == "checks" and entry_sha
                        and record.get("entry_sha") != entry_sha):
                    # the per-check record of this line speaks for another model entry (or for none recorded): the probe runs
                    notes.append(f"the check record {path.name} was made for another model entry; this probe runs")
                    continue
                if (record is not None and record.get("verdict") in ("no_failure", "wrong_location")
                        and same_test(now, proof_identity(record)) and _mutated_files_hold(record, entry, project)):
                    if not _same_target(record, target):
                        notes.append(_earlier_line_note(record, target))
                        continue
                    hit = {"by": "probe_record", "level": None, "receipt_ref": {},
                           "record": path.relative_to(task_root).as_posix(),
                           "prior_verdict": str(record["verdict"]), "recorded_at": str(record.get("recorded_at") or ""),
                           "holds": same_test(now, proof_identity(record))}
                    break
            if hit is not None:
                break
    if hit is None:
        for one in ids:
            record = _read_record(probe_record_path(task_root, one, "product"), notes)
            if (record is not None and record.get("verdict") == "survived"
                    and same_test(now, proof_identity(record)) and _mutated_files_hold(record, entry, project)):
                hit = {"by": "product_record", "level": None, "receipt_ref": {},
                       "record": probe_record_path(task_root, one, "product").relative_to(task_root).as_posix(),
                       "prior_verdict": "survived", "recorded_at": str(record.get("recorded_at") or ""),
                       "holds": same_test(now, proof_identity(record))}
                break
    if hit is None and kind == "product":
        hit = _product_receipt_repeat(entry, ids, now, task_root, project, check_key, notes)
    if hit is None:
        return {"probed": False, "notes": notes}
    stage_name = _stage_of(task_root, dispatch, stage)
    if hit["by"] == "receipt":
        shown = words(hit["level"])
        if hit["holds"] in ("instance_code", "file_code"):
            shown += f" ({held_words(hit['holds'])})"
        ref_text = (hit["receipt_ref"] or {}).get("path") or "the receipt on the row"
        hit["words"] = (f"{iid} already holds a receipt that {shown} for these bytes ({ref_text}); nothing was "
                        "mutated or run. Change the test before probing it again; a person's word passes a "
                        f"repeat (waiver.py, stage {stage_name}, block \"{PROBE_BLOCK}\").")
    else:
        hit["words"] = _repeat_words(hit["prior_verdict"], hit["recorded_at"], hit["record"], stage_name)
    word = person_word(task_root, stage_name, hit["words"])
    if word_passes(word, hit["recorded_at"]):
        notes.append(f"a person's recorded word passes this repeat of the probe: {word['decision']}")
        return {"probed": False, "notes": notes, "word": word["decision"]}
    return {"probed": True, "instance_id": iid, **hit, "block": PROBE_BLOCK, "notes": notes}


# --- what a row reached --------------------------------------------------------------------------

def _current_sha(entry: dict) -> str:
    return current_test_sha(entry)


def other_bytes(entry: dict, receipt) -> bool:
    """Is this receipt for OTHER bytes than the row's test holds NOW (the one reader)? A record
    that hashes none (the old mutable probe record) says nothing to compare; a test whose file
    cannot be found is not "other bytes" but unknown ones — `_evaluate` says that on its own.
    Raw bytes only: whether other bytes are still the same CODE is `holds_over_comments`."""
    if not isinstance(receipt, dict):
        return False
    claimed, current = str(receipt.get("test_content_hash") or ""), _current_sha(entry)
    return bool(claimed and current and claimed != current)


def holds_over_comments(entry: dict, receipt, now=None) -> bool:
    """A receipt for other raw bytes still counts when the change was cosmetic: `same_test` says its
    proof holds by the CODE of the test (`instance_code`, the per-test identity's own code sha, or
    `file_code` for a receipt that predates the identity and recorded `test_code_sha`) and not by
    equal bytes. `now` is `instance_identity()`'s answer; without it the file rules (today's) apply.
    A receipt without any code sha (written before the rule) never does: raw equality is all it can
    show."""
    if not isinstance(receipt, dict):
        return False
    now = now if isinstance(now, dict) else instance_identity(entry, None)
    return same_test(now, proof_identity(receipt)) in ("instance_code", "file_code")


def without_retracted(ids, manifest) -> list:
    """`ids` minus the instance ids the manifest records as retracted
    (`manifest_put.py retracted_instances[]`): a binding's list must not resurrect a row that was
    taken out on purpose when a publisher unions what it holds with what it adds."""
    gone = {str(i) for i in (manifest or {}).get("retracted_instances") or [] if i} \
        if isinstance(manifest, dict) else set()
    return [str(i) for i in ids or [] if str(i) not in gone]


ONE_CHECK = "one_check"          # `scope` of a receipt that proves the one check its `checks` name (a product receipt, EP-W)
WHOLE_UNLISTED = "whole_unlisted"  # `scope` of a receipt of a test whose language has no reader: no list of checks can exist
WHY_ONE_CHECK = ("a product receipt proves the one check it names; the critic names it with a `product` entry, and the other "
                 "checks of this test stay owed")


def _evaluate(variant: dict, task_root, instance_id: str, now=None, scope_ok: bool = False) -> tuple:
    """(level id or None, issues, receipt, bytes unknown, over comments, how) of ONE candidate: a row
    whose `sensitivity_proof` names the receipt. Valid = no `contract.sensitivity_proof_issues`, a
    level the vocabulary knows, and the test as it is NOW: `same_test` of the row's current identity
    and the receipt's says "raw" or "instance" (the same bytes, or the same test), or "instance_code" /
    "file_code" (a change that left the CODE the same, D-0017: `over_comments`). A receipt for other
    code proves nothing about this test: it is not valid, shields nothing, and shows no level. When the
    test file cannot be found the comparison cannot be made: not valid either, and the level is unknown
    rather than "not probed" (FR-41). A receipt that binds no bytes at all has nothing to compare (the
    old mutable record: it is not valid for other reasons). `now` is `instance_identity()`'s answer,
    taken once by the caller. `scope_ok` (fix round D, B1) lifts ONLY the last line below - the one-check scope - and is passed by
    `product_receipt_holds` alone: every byte/identity guard above it stands for that caller too."""
    receipt, load_errors = C.sensitivity_proof_receipt(variant, task_root)
    issues = list(C.sensitivity_proof_issues(variant, task_root))
    level = level_of(receipt) if receipt else None
    now = now if isinstance(now, dict) else instance_identity(variant, task_root)
    if not issues and not now["input_hash"]:
        return None, [f"its test file {test_file_of(variant) or '(the row names none)'} cannot be found "
                      "under the project, so the bytes this receipt proves cannot be compared with the "
                      "test as it is now: proof level unknown; the automator records the test's "
                      "project-relative `file` in the row (manifest_from_tests.py)"], receipt, True, False, ""
    over_comments, how = False, ""
    claims = proof_identity(receipt)
    if not issues and (claims["input_hash"] or claims["instance_identity"]):
        how = same_test(now, claims)
        if not how:
            said = (f"its receipt is for other bytes (test_content_hash {receipt.get('test_content_hash')}, "
                    f"the test file now hashes {now['input_hash']}) and other code"
                    if claims["input_hash"] != now["input_hash"] else
                    "its receipt was measured on this very file, and something the test depends on (its "
                    "function, its class, a fixture or a helper) has changed since, or cannot be told now")
            return None, [f"{said}: probe the current bytes again with {LIVE_TOOL} --instance "
                          f"{instance_id}"], receipt, False, False, ""
        over_comments = how in ("instance_code", "file_code")
    if not issues and level is None:
        proof = receipt.get("proof_level") or receipt.get("probe_tool") or "none"
        issues = [f"unknown proof level {proof}"]
    elif issues and not load_errors and level == LIVE and receipt.get("immutable") is not True:
        issues = [f"its live-check record predates receipts; rerun {LIVE_TOOL} --instance "
                  f"{instance_id}"]
    if not scope_ok and not issues and isinstance(receipt, dict) and receipt.get("scope") == ONE_CHECK:
        # t-2064 P6 (EP-W, AR-28): a product receipt proves the ONE check its `checks` name, whatever its wording. Position: LAST, after
        # every validity check above, so a receipt of other bytes keeps its own, more useful issue; what stays unreachable is a level
        # for a receipt that names one check of several (`reached`, `already_probed` and `check_delivery` read this return). A receipt
        # with no `scope` is an old one and reads as before (EP-I); `whole_unlisted` keeps its level.
        return None, [WHY_ONE_CHECK], receipt, False, False, how
    return (level if not issues else None), issues, receipt, False, over_comments and not issues, how


def receipt_off_target(source) -> str:
    """The why, when a receipt (or a window `probe` block, or a probe record) carries a `target` that says the probe
    broke a line other than the obligation's check (`target.is_assertion_id is False`), else "". THE reader
    (AR-13): the window gap `semantic_sensitivity`, `reached` and the probe's own `keep_standing_record` ask this
    one function. A missing `target` (a receipt that records none reads as unknown, AR-23), a `null` and anything not a dict read
    as "" - an unknown is never off-target (FR-41); the residual that an unknown target still proves is named, not
    widened. Evidence of execution is not evidence of coverage (FR-18): decided by the recorded fact, not by a role."""
    target = source.get("target") if isinstance(source, dict) else None
    if not isinstance(target, dict) or target.get("is_assertion_id") is not False:
        return ""
    return (f"the probe broke line {target.get('line')}, not the obligation's check at "
            f"{target.get('assertion_id')}")


def valid_level(entry: dict, ref, task_root) -> str | None:
    """The level id of the receipt `ref` ({path, sha256}) names FOR THIS ROW when that receipt is
    valid, else None — what the publishers ask before they replace a ref (never downgrade)."""
    if not isinstance(entry, dict) or not isinstance(ref, dict) or not ref.get("path"):
        return None
    variant = dict(entry, sensitivity_proof={"receipt_ref": {"path": ref["path"],
                                                             "sha256": ref.get("sha256")}})
    return _evaluate(variant, task_root, C.test_instance_id(entry),
                     instance_identity(entry, task_root))[0]


def product_receipt_holds(entry: dict, ref, task_root, project=None) -> dict:
    """`{"holds": bool, "why": str, "receipt": dict | None, "keys": [str]}` - whether the product receipt `ref` ({path, sha256}) is valid
    FOR THIS TEST AS IT STANDS and may be named by a `product` entry for ONE of its checks (t-2064 fix round D, B1; EP-W). The ONE reader
    (AR-13) of that join: `probe_by_code._product_entry_holds` asks it, and it is not `valid_level`, whose answer is None for a
    `one_check` receipt by design (the test as a whole has no level from one check).

    The guards are the receipt's own, unchanged (`_evaluate`: the contract's issues, the bytes or the same test); this lifts only the
    one-check scope line. `holds` needs the product level and a scope that is ABSENT (an old receipt, EP-I: it names no key, so the
    caller joins it by its location alone) or `one_check`; a `whole_unlisted` receipt (a test whose checks the factory cannot list) never
    stands for one check, and an unknown scope word does not either. `keys` are the `checks[].key` the receipt names (`[]` for an old
    one). `why` is the TRUE reason when it does not hold (what the guard that failed said). Reads; writes nothing. Error direction: not
    holding; never raises. `project` is the project root the test file is read under (`None`: the host's)."""
    nope ={"holds": False, "why": "", "receipt": None, "keys": []}
    try:
        if not isinstance(entry, dict) or not isinstance(ref, dict) or not ref.get("path"):
            return dict(nope, why="no receipt is named")
        variant = dict(entry, sensitivity_proof={"receipt_ref": {"path": ref["path"], "sha256": ref.get("sha256")}})
        level, issues, receipt, _unknown, _over, _how = _evaluate(variant, task_root, C.test_instance_id(entry),
                                                                  instance_identity(entry, task_root, project), scope_ok=True)
        if not isinstance(receipt, dict):
            return dict(nope, why="the receipt cannot be read")
        scope = receipt.get("scope")
        keys = [str(c.get("key")) for c in receipt.get("checks") or [] if isinstance(c, dict) and c.get("key")] \
            if isinstance(receipt.get("checks"), list) else []
        base = dict(nope, receipt=receipt, keys=keys)
        if level != PRODUCT:
            say = issues[0] if issues else f"its level is {level!r}, not the product's ({PRODUCT})"
            return dict(base, why=f"it does not speak for the test as it stands: {say}")
        if scope == WHOLE_UNLISTED:
            return dict(base, why="it is the receipt of a test whose checks the factory cannot list: it proves that test as a whole, "
                                  "never one check named by an entry")
        if scope is not None and scope != ONE_CHECK:
            return dict(base, why=f"its scope {scope!r} is not one the factory reads for a product entry")
        return dict(base, holds=True)
    except Exception:       # noqa: BLE001 - a receipt that cannot be measured does not hold
        return dict(nope, why="the receipt could not be measured against the test as it stands")


# How much a proof stands on, for the tie of two receipts of the same level: the very bytes, then
# the same test, then only the same code of it.
_HOLDS_RANK = {"raw": 3, "instance": 2, "instance_code": 1, "file_code": 1}


def reached(entry, manifest, task_root, *, now=None) -> dict:
    """{level, words, ref, issues} — the best valid receipt a manifest row reaches.

    Candidates: the row's own `sensitivity_proof` (a `receipt_ref`, or a legacy inline receipt) and
    the receipt of the proven `obligation_bindings[]` row that lists the instance
    (`contract.binding_receipt_ref`), de-duplicated by path; each is validated by
    `contract.sensitivity_proof_issues` and against the test's current bytes (`current_test_sha`;
    other raw bytes count when the change was comment-only, `holds_over_comments`, and then the
    words say so). The level is the best valid one: the highest rank, and on a tie the receipt
    whose `test_content_hash` is the current bytes, then the first found (the row's own before the
    binding's). `issues` is non-empty only when no candidate is valid; when a candidate could not
    be compared because the test file is gone, `words` says the level is unknown (FR-41)."""
    entry = entry if isinstance(entry, dict) else {}
    instance_id = C.test_instance_id(entry)
    now = now if isinstance(now, dict) else instance_identity(entry, task_root)
    proof = entry.get("sensitivity_proof")
    candidates, seen = [], set()
    if isinstance(proof, dict):
        ref = proof.get("receipt_ref")
        if isinstance(ref, dict) and ref.get("path"):
            seen.add(str(ref["path"]).replace("\\", "/"))
        candidates.append((entry, ref if isinstance(ref, dict) and ref.get("path") else {}))
    binding = C.binding_receipt_ref(manifest, entry, task_root) if task_root is not None else {}
    if binding and str(binding["path"]).replace("\\", "/") not in seen:
        ref = {"path": binding["path"], "sha256": binding["sha256"]}
        filled = dict(proof) if isinstance(proof, dict) else {}
        filled["receipt_ref"] = ref
        candidates.append((dict(entry, sensitivity_proof=filled), ref))
    issues, valid, unknown = [], [], False
    for variant, ref in candidates:
        level, found, receipt, bytes_unknown, over_comments, how = _evaluate(variant, task_root, instance_id, now)
        unknown = unknown or bytes_unknown
        if level is None:
            issues.extend(i for i in found if i not in issues)
        elif receipt_off_target(receipt):
            # a receipt of a probe of another line stays on disk and proves nothing about this obligation
            why = (f"{receipt_off_target(receipt)}: probe the Then's line with {LIVE_TOOL} --instance "
                   f"{instance_id} --at <line> (a test that is not Python), or return the item unverified")
            if why not in issues:
                issues.append(why)
        else:
            valid.append((level, ref, receipt, over_comments, how))
    if not valid:
        # A receipt whose test cannot be found may well prove the test: the level is unknown, and
        # it is said so - "not probed" would report the absence of evidence as a fact (FR-41).
        if not issues and task_root is not None and probe_owes_judgment(task_root, instance_id, str(now.get("input_hash") or "")):
            # t-1968 N2 (E2.11): a probe that failed at its line on a text the tool cannot read and was never judged to fire is
            # NOT proved; the reason says why, in the factory's words (FR-41: said as not proved, never as a fact of proof)
            issues = ["no sensitivity receipt: its probe owes the code critic's judgment (`cause: judgment`), and none "
                      "proved that the broken check fired"]
        return {"level": None, "words": unknown_words() if unknown else words(None), "ref": {},
                "issues": issues or ["no sensitivity receipt"]}
    # Equal rank: a receipt for these very bytes, then one for this same test, before one that holds
    # only with the test's code unchanged (a comment-only change, an added test) - the proof that needs no classifier to stand is the one shown.
    # A receipt that binds nothing to compare (how "") comes last, as it did.
    best = max(valid, key=lambda item: (rank(item[0]), _HOLDS_RANK.get(item[4], 0)))
    shown = words(best[0])
    if best[3] and held_words(best[4]):
        # FR-41: say which proof - this receipt was measured on other bytes and stands because the
        # test's code is the same (`held_words`: chosen by the `same_test` answer, never re-derived).
        shown = f"{shown} ({held_words(best[4])})"
    return {"level": best[0], "words": shown,
            "ref": {"path": best[1]["path"], "sha256": best[1].get("sha256")} if best[1] else {},
            "issues": []}


# --- the facts a receipt binds -------------------------------------------------------------------

def binding_facts(task_root, instance_id: str) -> dict:
    """The immutable facts a proof receipt binds, read from what the author already wrote:
    the case version and the test bytes in the instance's manifest row (`claimed_test_sha`: the
    raw sha256 the row is bound to, else the file as it is now), the source and build identity in
    the run block that executed it. A fact nobody wrote is `""` — the caller decides
    what to do about it (`red_sandbox.manifest_bindings` refuses; `probe_by_code.py` writes no
    receipt and says which). Moved here from `red_sandbox.manifest_bindings`: two probes write
    receipts, and a receipt one of them can write and the other cannot is FR-17's class."""
    task = Path(task_root)
    manifest = json.loads(C.artifact(task, "automation-manifest.json").read_text(encoding="utf-8"))
    rows: dict = {}
    # The last row per instance wins, so the ORDER is the fact: the story's one block order
    # (`run_history.read_run_blocks` - the block's own clock, a reparse right after the block it
    # supersedes), not file-name order, under which a reparse block of an attempt whose id starts
    # with a low digit sorts before every `2026...` block and an OLDER block's source revision and
    # build identity were bound into the receipt (t-149, F-order).
    import run_history
    for item in run_history.read_run_blocks(task)[0]:
        block = item["data"]
        for row in block.get("results") or []:
            if isinstance(row, dict) and row.get("instance_id"):
                rows[str(row["instance_id"])] = {**row, "_block": block}
    entry = next((t for t in C.manifest_tests(manifest)
                  if C.test_instance_id(t) == instance_id), {})
    row = rows.get(instance_id) or {}
    fingerprint = row.get("source_fingerprint") or {}
    provenance = (row.get("_block") or {}).get("runtime_provenance") or {}
    return {
        "case_version": next((str(link.get("version")) for link in
                              entry.get("case_version_links") or []
                              if isinstance(link, dict) and link.get("version")), ""),
        # The bytes the author bound the row to, else the test file as it is now - raw sha256 in
        # both cases. Never the run block's `source_fingerprint.test_content_sha`: that is a
        # fingerprint over several files, and a receipt carrying it matches no row (t-035).
        "test_content_hash": claimed_test_sha(entry),
        "source_revision": str(fingerprint.get("source_sha") or manifest.get("head") or ""),
        "build_id": str(provenance.get("observed_runtime_identity")
                        or provenance.get("environment_id") or ""),
    }


# --- what a test's edit left behind: the run and the live check, per instance (HF2-11) -------------------
# Readers only (FR-45): the driver (`story_run`, 11b) and the ledger (11c) ask, and nothing here runs or
# writes anything.

WHY_PROBE_CHANGED = "the live check was measured on other code than the test holds now"
WHY_PROBE_OTHER_INSTANCE = ("the live check was measured under another spelling of this test (its parameter "
                            "changed since) and on other code than the test holds now")
WHY_PROBE_NOT_REQUIRED = "no live check is demanded of this test"
WHY_PROBE_MISSING = ("no receipt of a live check reaches this test, or the one that does is of another spelling of it "
                     "and the test was not edited since")
NO_MANIFEST_ROW = "the manifest has no row for this instance"


def _receipt_variants(entry: dict, manifest, task_root) -> list:
    """The rows `reached` validates, in its order: the row's own `sensitivity_proof`, then the receipt of the
    proven `obligation_bindings[]` row that lists the instance (de-duplicated by path)."""
    proof = entry.get("sensitivity_proof")
    variants, seen = [], set()
    if isinstance(proof, dict):
        ref = proof.get("receipt_ref")
        if isinstance(ref, dict) and ref.get("path"):
            seen.add(str(ref["path"]).replace("\\", "/"))
        variants.append(entry)
    binding = C.binding_receipt_ref(manifest, entry, task_root) if task_root is not None else {}
    if binding and str(binding["path"]).replace("\\", "/") not in seen:
        filled = dict(proof) if isinstance(proof, dict) else {}
        filled["receipt_ref"] = {"path": binding["path"], "sha256": binding["sha256"]}
        variants.append(dict(entry, sensitivity_proof=filled))
    return variants


def _instance_record(receipt: dict, task_root) -> dict | None:
    """The record of the probe behind a receipt, read by the receipt's OWN names - its `probe_record` (a path
    under the task), else `work/probes/<its instance_id>.json` - never by a name guessed from the row (a row
    renamed after the probe has no record under its new name, and the old one is the only evidence). None when
    there is none or it cannot be read."""
    ref = str(receipt.get("probe_record") or "")
    if ref:
        root = Path(task_root).resolve()
        path = (root / ref).resolve() if not Path(ref).is_absolute() else Path(ref)
        if path.is_relative_to(root):
            return _read_record(path, [])
        return None
    iid = str(receipt.get("instance_id") or "")
    return _read_record(probe_record_path(task_root, iid), []) if iid else None


def _wrong_instance_only(entry: dict, variant: dict, task_root) -> bool:
    """Is the ONLY thing wrong with this receipt that it was measured under another spelling of the SAME test
    (`test_x` before the row became `test_x[p]`, or the neighbour's `test_x[a]` reaching `test_x[b]` through
    the obligation binding)? Exactly when: the receipt reads, its one `contract.sensitivity_proof_issues` is
    the instance mismatch, its level is one the vocabulary knows, its `instance_id` names the same test
    function as the row (`contract.function_name`, the one parse; a `ti_` hash names none), and the record of
    its probe is in the row's own file (`node_selects_row`, the one rule; an unknown file is False).
    The error direction is "no": this answer opens the door to a new probe on the current bytes and to
    nothing else - it never makes the old receipt count (`reached` and the issues are not touched)."""
    try:
        receipt, _errors = C.sensitivity_proof_receipt(variant, task_root)
        if not receipt or level_of(receipt) is None:
            return False
        issues = C.sensitivity_proof_issues(variant, task_root)
        if len(issues) != 1 or "instance_id does not match" not in issues[0]:
            return False
        theirs, mine = str(receipt.get("instance_id") or ""), C.test_instance_id(entry)
        if not theirs or not mine or any(
                part.rsplit(C.INSTANCE_SEP, 1)[-1].startswith("ti_") for part in (theirs, mine)):
            return False
        function = C.function_name(theirs)
        if not function or function != C.function_name(mine):
            return False
        record = _instance_record(receipt, task_root)
        node = str(record.get("test_node") or "") if record else ""
        if "::" not in node:
            return False
        from execution_request import _split_node
        return node_selects_row(entry, mine, _split_node(node)[0], strict=True)
    except Exception:
        return False


def _stale_receipt(entry: dict, manifest, task_root, now: dict, found=None) -> str:
    """`WHY_PROBE_CHANGED` when there is a receipt that is valid but for the test as it was - `_evaluate`'s own
    reading of it: no `contract.sensitivity_proof_issues`, it binds bytes or an identity, and `same_test` says
    it does not speak for the test now; else `WHY_PROBE_OTHER_INSTANCE` when the receipt is for another
    spelling of the same test (`_wrong_instance_only`) and does not speak for the bytes now either; else "".
    A receipt of the row's own always wins over a neighbour's. `found`, a list, gets the receipt chosen."""
    other = None
    for variant in _receipt_variants(entry, manifest, task_root):
        receipt, _errors = C.sensitivity_proof_receipt(variant, task_root)
        if not receipt:
            continue
        claims = proof_identity(receipt)
        speaks = bool(claims["input_hash"] or claims["instance_identity"]) and not same_test(now, claims)
        if not C.sensitivity_proof_issues(variant, task_root):
            if speaks:
                if isinstance(found, list):
                    found.append(receipt)
                return WHY_PROBE_CHANGED
        elif speaks and other is None and _wrong_instance_only(entry, variant, task_root):
            other = receipt
    if other is not None:
        if isinstance(found, list):
            found.append(other)
        return WHY_PROBE_OTHER_INSTANCE
    return ""


def _replay(entry: dict, task_root, receipt: dict | None = None) -> dict | None:
    """What `probe_by_code.py` needs to prove the test again, from the record of its last probe
    (`work/probes/<iid>.json`): `{"test", "instance", "mutation", "oracle"}`; `oracle` is `<mutated file>::<function>`
    when the probe mutated an oracle outside the test, else "". None when the record is not there, names no
    `test_node` or `mutation`, or was made with `--at` (a line anchor does not survive the edit that made the
    probe stale: it is the person's, or the critic's, to place again). The record of a walk of the plan (t-2064 P4b/P4c: the aggregate,
    `mutation: "invert"`, `mutation_detail` with no `at`) is read as it stands: it replays, and the replay is a call with no line anchor
    that joins the aggregate's stored entries itself (`probe_by_code._entries_for`); nothing is added to the key set. With no record under any spelling of the
    row, the record of `receipt` (a stale receipt of another spelling) is read by the receipt's own names, and the
    replay's `test` is the row's own node `<file>::<function>[<param>]`, not the old spelling."""
    record, other = None, False
    for one in _row_ids(entry):
        record = _read_record(probe_record_path(task_root, one), [])
        if record is not None:
            break
    if record is None and isinstance(receipt, dict):
        record, other = _instance_record(receipt, task_root), True
    if record is None:
        return None
    detail = record.get("mutation_detail") if isinstance(record.get("mutation_detail"), dict) else {}
    test, mutation = str(record.get("test_node") or ""), str(replay_mutation(record.get("mutation")) or "")
    if other:
        from execution_request import _split_node      # the record's class chain stays: `file::Class::function[param]`
        file, mine = test_file_of(entry), C.test_instance_id(entry).split(C.INSTANCE_SEP)[-1]
        test = "::".join([file, *_split_node(test)[1], mine]) if file and mine and test else ""
    if not test or not mutation or detail.get("at") is not None:
        return None
    function = str(detail.get("oracle_function") or "")
    mutated = record.get("mutated_file") if isinstance(record.get("mutated_file"), dict) else {}
    path = str(mutated.get("path") or "")
    oracle = (f"{path}::{function}" if path else function) if function else ""
    return {"test": test, "instance": C.test_instance_id(entry), "mutation": mutation, "oracle": oracle}


def probe_freshness(entry, manifest, task_root, now=None) -> dict:
    """`{"state", "why", "replay"}` - does the live check of a manifest row still speak for its test?
    `state` is `not_required` (`proof_required` is false), `fresh` (`reached` shows a level), `stale` (a valid
    receipt exists and `same_test` says it is for other code - `_evaluate`'s reading, the same one; also a
    receipt of another spelling of the same test, `_wrong_instance_only`, that does not speak for these bytes
    either - HF8-18), `missing` (no receipt, one of another test, or one of another spelling of the same test
    on bytes nothing edited - its bytes are current, so nothing is stale and the row never had a proof of its own:
    a gap of S5, not of an edit) or `unknown` (the test file is gone, or the levels cannot be read: nothing could be
    compared, said so). `replay` is `_replay` for `stale`, else None. `now` is
    `instance_identity()`'s answer, taken once by the caller; nothing is written."""
    entry = entry if isinstance(entry, dict) else {}
    out = {"state": "unknown", "why": "", "replay": None}
    try:
        if not proof_required(entry, manifest):
            return dict(out, state="not_required", why=WHY_PROBE_NOT_REQUIRED)
        now = now if isinstance(now, dict) else instance_identity(entry, task_root)
        if not now.get("input_hash"):
            return dict(out, why=WHY_NO_FILE)
        if reached(entry, manifest, task_root, now=now)["level"]:
            return dict(out, state="fresh")
        chosen: list = []
        why = _stale_receipt(entry, manifest, task_root, now, chosen)
        if why:
            return dict(out, state="stale", why=why,
                        replay=_replay(entry, task_root, chosen[0] if chosen else None))
        return dict(out, state="missing", why=WHY_PROBE_MISSING)
    except LevelsUnavailable as exc:
        return dict(out, why=f"the proof levels cannot be read ({exc})")
    except Exception as exc:
        return dict(out, why=f"the live check could not be compared ({type(exc).__name__})")


def reprobe_admitted(entry, manifest, task_root, now=None) -> tuple:
    """`(admitted, why)`: may a live check of this row be re-probed OUTSIDE the dispatch's scope? Exactly when
    `probe_freshness` says `stale` - a valid receipt exists and `same_test` says it is for other code (FB-10), or
    the receipt is of another spelling of the same test (HF8-18: a row with no probe of its own is then admitted
    too, by `execution_request._admitted_outside` and `probe_debt._outside_scope_door`; the error stays toward
    "not admitted"). A test with no receipt (`missing`), a fresh or unrequired one, and a state that could not be
    told are not admitted: new proof outside the scope stays the orchestrator's or a person's. The one reader of the state is
    `probe_freshness` (a gate opener that errs toward refusal); never raises; reads only."""
    try:
        got = probe_freshness(entry, manifest, task_root, now)
        if got["state"] == "stale":
            return True, ""
        return False, str(got.get("why") or f"the live check is {got['state']}: nothing is stale to re-probe")
    except Exception as exc:
        return False, f"could not be compared ({type(exc).__name__})"


def staleness(task_root, manifest, instance_ids) -> dict:
    """`{instance id: {"run": (state, why), "probe": {...}}}` for each id of `instance_ids`: the latest terminal
    run of the instance (`window_record._terminal_runs`, the one reader of "latest") through `run_freshness`, and
    its live check through `probe_freshness`. ONE `instance_identity` per instance serves both. An id the manifest
    has no row for, or one with no run, is `unknown` and says so. Nothing is written."""
    try:
        import window_record
        runs = window_record._terminal_runs(Path(task_root))
    except Exception:
        runs = {}
    rows = {}
    for entry in C.manifest_tests(manifest if isinstance(manifest, dict) else {}):
        for alias in _row_ids(entry):
            rows.setdefault(alias, entry)
    out = {}
    for iid in dict.fromkeys(str(i) for i in instance_ids or []):
        entry = rows.get(iid)
        if entry is None:
            out[iid] = {"run": ("unknown", NO_MANIFEST_ROW),
                        "probe": {"state": "unknown", "why": NO_MANIFEST_ROW, "replay": None}}
            continue
        now = instance_identity(entry, task_root)
        last = next((runs[alias] for alias in _row_ids(entry) if alias in runs), None)
        out[iid] = {"run": run_freshness(entry, last[0], task_root, now=now) if last else ("unknown", WHY_NO_RUN),
                    "probe": probe_freshness(entry, manifest, task_root, now)}
    return out
