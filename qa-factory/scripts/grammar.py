"""Closed lists of artifact form (shared artifact contracts).

The single canonical home of the grammars referenced by validate_artifacts.py,
check_witness.py and the role prompts. Principle: "do it well" is replaced by "walk a
finite list and fill a cell for every element" — walking the list is checked by code,
the quality of the cell — by a human at the gate.

RULE_CUTOFF — the date-cutoff of the form rules (law FB-12): the rules apply to artifacts
dated (created / updated / audited_at) no earlier than this date; older artifacts are
validated by the previous schema. No backfill is done — old cases get filled in at their
next edit (the same policy as est_manual_minutes).
"""
import json
import re
from pathlib import Path

RULE_CUTOFF = "2026-09-07"

# WP1 — requirement sources of the register. Each source = a field of the scout's context-manifest.
REQ_SOURCES = {"story", "feature", "assumption", "discussion", "ac", "derived"}
# derived must name the finite set it was derived from. case: and baseline: — the parity
# profile (refactoring, migration, upgrade): the requirement = existing behavior of the
# radius, derived from an area case or the "before" snapshot (Phase 2b).
DERIVED_FROM_RE = re.compile(r"^(aspect|seam|invariant|bug|case|baseline|norm|test):\S.*$")

# Phase 8n — NFR specialist reports (nfr-<type>.json). The type is a closed list of specialist roles;
# matrix item statuses and results are closed lists; positive_control is mandatory.
NFR_TYPES = {"performance", "security", "accessibility", "privacy", "localization"}
NFR_MODES = {"assess", "release"}
NFR_MATRIX_STATUS = {"applicable", "n/a"}
NFR_RESULTS = {"meets", "violates", "not-measured"}
NFR_CONTROL_RESULTS = {"detected", "not-detected"}
NFR_REQUIRED = ["type", "mode", "matrix", "positive_control", "findings", "verdict", "limitations", "confidence", "witness"]
# Plan/register profile: feature (new behavior) | parity (behavior must not change).
PLAN_PROFILES = {"feature", "parity"}
REQ_ID_RE = re.compile(r"^R-\d+$")

# WP2 — cells of the contradiction matrix: ok must carry a reference (positive control),
# silent — the default of silence, contradicts — with a quote, n/a — with a reason.
CONTRADICTION_CELL_RE = re.compile(r"^(ok:\S.*|contradicts:\S.*|silent|n/a:\S.*)$")

# WP3 — defect classes of a plan row ("what can go wrong"). A seed; the project extends it
# via config.json → "defect_classes_extra".
DEFECT_CLASSES = {
    "boundary", "state", "order", "concurrency", "permission", "data-loss",
    "contract", "seam", "error-path",
}
# A class of the list, or the door `new:<word> -- <why>` (`new` group: the whole door text, checked by
# `contract.open_word_errors`; `cls` is None then). Either way `@ <place>` follows (spec t-1765 X2-4, S-X2-c).
DEFECT_CLASS_RE = re.compile(r"^(?:(?P<cls>[a-z][a-z-]*|regression:BUG-\d+)|(?P<new>new:.+?))\s*@\s*\S.*$")
# Which of those classes say the case's own outcome is a refusal or a failure path. This is
# the FIELD that answers "is this a negative case", and it lives here because this is where
# the class list lives; a project's `defect_classes_extra` is not in it, and a class this file
# does not know answers `None` — not `no` (`negative_outcome` below).
#
# Why a field at all: `judge_cases.py` and `judge_code.py` decided it by running a phrase list
# (`negative|invalid|refus|reject|denied|forbidden|unauthori[sz]ed|error|4\d\d`) over the case's
# title and its Then, so a negative case worded otherwise silently lost the dimension that
# exists for it — rubric 5 in one judge, `narrow_negative` in the other (factory rule FR-12).
NEGATIVE_OUTCOME_CLASSES = {"permission", "error-path"}
SMOKE = "smoke"

# WP3/WP4 — the impact scale (the plan's "impact", the bug's "impact"). A plan row's priority and
# a bug's severity are DERIVED from the impact class, not assigned. Override — config.json
# → "impact_scale": {"<class>": {"priority": "P1", "severity": "major"}}.
IMPACT_SCALE = {
    "data-loss":    {"priority": "P0", "severity": "blocker"},
    "money":        {"priority": "P0", "severity": "blocker"},
    "access":       {"priority": "P0", "severity": "critical"},
    "blocked-flow": {"priority": "P1", "severity": "major"},
    "degraded":     {"priority": "P2", "severity": "minor"},
    "cosmetic":     {"priority": "P3", "severity": "minor"},
    "none":         {"priority": "P3", "severity": "minor"},
}

# WP4 — the oracle grammar (the plan's "basis of the expected", the bug's violates, a hypothesis's oracle).
# A finding without an oracle from the list is an observation, not a bug.
ORACLE_RE = re.compile(
    r"^(requirement:R-\d+|invariant:\S.*|consistency:\S.*|history:\S.*|impact:\S.*|external:\S.*)$"
)

# WP5 — charter hypotheses: binding to a finite set and finding statuses.
HYPOTHESIS_ID_RE = re.compile(r"^H-\d+$")
HYPOTHESIS_BINDING_RE = re.compile(r"^(perturbation|seam|bug-class|reading):\S.*$")
HYPOTHESIS_STATUSES = {"probed-confirmed", "probed-refuted", "not-probed", "unplanned"}

# WP3 — requirement statuses in the PTR "Readiness within what was verified" (the three outcomes
# of the common-rules skip rule, lifted from the case to the requirement). Kept for artifacts
# written before the report was rebuilt around the traceability appendix.
PTR_REQ_STATUSES = {"verified", "not verified", "deferred by design", "deferred by decision"}

# WP3 — the sections of `test-report.md`, in the order a person reads them. The order IS the
# rule: TP1-15045 was assembled from the machine ledger upwards, so its first line was
# "24 reasons on the product side" and it carried no list of what had been proven, no single
# list of what was left with the person, and no size. A reader who stops after the third
# section now already has the verdict, what is proven and what is broken; everything the
# factory owes itself sits below that line. A heading may carry a count after it
# ("## Proven — 20 green tests"), so these are prefixes, not whole lines.
#
# Two sections joined the list with the code-owned blocks (B-211, t-189): "Open questions" stands
# right after "Left with you" (the person reads what is still asked of them next to what is
# handed to them), and "Decided at gate A" stands after "Not proven", before gate B's section.
REPORT_SECTIONS = ("## Proven", "## Product bugs", "## Left with you", "## Open questions",
                   "## Not proven", "## Decided at gate A", "## Decided at gate B",
                   "## Factory defects", "## Size", "## Where to look", "## Appendix")
# "Decided at gate B" does not exist until the gate happened; every other section is owed.
REPORT_SECTIONS_AFTER_GATE_B = ("## Decided at gate B",)
# The two new sections are owed only by a report that carries code-owned blocks. A report written
# before the blocks existed (no marker at all, `validate_artifacts.report_is_unmarked`) keeps the
# nine-section contract it was written against: refusing it would make the factory's own release
# the person's problem (builder-rules item 9). The first `report_facts.py --write` converts it.
REPORT_SECTIONS_WITH_BLOCKS = ("## Open questions", "## Decided at gate A")

# --- code-owned blocks of the report (t-109 F1: code-owned blocks between markers, prose outside) ---
# Code owns every count and status the person reads; the scribe owns "The change", the `How:` /
# `Needed:` words of each "Left with you" item and the "Factory defects" paragraphs. A block is
# the span between two marker lines:
#
#     <!-- facts:<name> -->
#     ...what code renders, its own heading line first...
#     <!-- /facts:<name> -->
#
# Marker grammar (pinned here, read by `find_blocks`, `replace_block` and by the report checks):
#   * a marker is a WHOLE line: the exact text above, at column 0, with nothing after it but
#     spaces or a CR. An indented marker, or one with other text on its line, is not a marker.
#   * a line inside a fenced code block (``` or ~~~, the CommonMark rule: up to three spaces of
#     indent, at least three fence characters, closed by the same character at least as long) is
#     never a marker. A block whose closing marker sits inside a fence is therefore unterminated.
#   * a block name is one of REPORT_BLOCKS; each appears once; blocks do not nest.
#   * `find_blocks` returns the body with the file's own line endings; `replace_block` writes the
#     body with LF whatever the file uses (R-S9.3), and leaves the marker lines as they were.
# The names are in template order. `verdict` is the verdict paragraph with its `delivery_ready:`
# line, above the first section; every other block opens with its own section heading line, so the
# count in a heading ("Proven - 3 green tests") is code's too. "Left with you", "Factory defects",
# "The change", the notation line and the appendix are prose or pasted text, not blocks.
#
# `manual-checks` (t-250, F10) stands right after `proven`: what an agent checked by hand is shown to the
# person beside what tests proved, and a case with no valid record is "not checked" there, never under
# Proven. Its heading is deliberately NOT in REPORT_SECTIONS: that tuple is the scribe's section list (its
# card, the handoff, the report-text tests), and the block is code's - the scribe never writes it. A marked
# report written before the block has none: `report_facts.py --write` inserts it, and `--check` names it.
#
# `review-gaps` (C1-5c) stands right after `bugs`: the tests the code critic rejected whose window closed anyway (the repair
# limit was spent), each with what the critic asked, and the runs of S7 left failing under a `### ` heading of their own
# (the validator allows one `## ` heading per block). It is always there; with nothing to list it says so in one line.
#
# `left-gate-b` and `regression` (t-305 N8) stand INSIDE the "Left with you" section, after the scribe's items and in
# this order, and open with an `### ` heading (the section's own `## ` heading is the scribe's, not a block's): the first
# holds what the person's gate B answers left with them (it exists only after the gate, and only when an answer did),
# the second the plan's `## Recommended regression` verbatim (it never decides the verdict). The scribe's span of the
# section ends at the FIRST marker, so code never reads a scribe's item as its own line or the reverse.
#
# `skipped-by-plan` (owner amendment 03.10) stands right before `not-proven` and splits what used to be one list: the
# requirements whose null outcome is the approved plan's own decision (a plan row `skip` with its reason, a gate A waiver
# with their words) stand there, and "Not proven" keeps the checks that could not execute. Like `manual-checks` its
# heading is not in REPORT_SECTIONS (the scribe's list): the block is code's.
REPORT_BLOCKS = ("verdict", "proven", "manual-checks", "bugs", "exploratory", "review-gaps", "left-branches", "left-gate-b", "regression",
                 "open-questions", "skipped-by-plan", "not-proven", "branches-not-proven", "gate-a", "gate-b", "size", "where-to-look")
REPORT_BLOCK_HEADINGS = {
    "verdict": "",
    "proven": "## Proven",
    "manual-checks": "## Checked by hand",
    "bugs": "## Product bugs",
    "exploratory": "## Exploratory findings and unresolved questions",
    "review-gaps": "## Review gaps",
    "left-branches": "### Branches left with you",
    "left-gate-b": "### Added after gate B",
    "regression": "### Regression to run",
    "open-questions": "## Open questions",
    "skipped-by-plan": "## Skipped by the plan (approved at gate A)",
    "not-proven": "## Not proven",
    "branches-not-proven": "## Branches not proven",
    "gate-a": "## Decided at gate A",
    "gate-b": "## Decided at gate B",
    "size": "## Size",
    "where-to-look": "## Where to look",
}
# The gate B block does not exist until the gate happened (same rule as its heading).
REPORT_BLOCKS_AFTER_GATE_B = ("gate-b", "left-gate-b")
# The exploratory block exists only while the findings register holds a line (or a damaged one): a story without a
# register is byte-identical to one before the block was born, so the template carries no `exploratory` block.
# The two branch blocks (r0107 S6 step 3): `left-branches` (inside "Left with you", before `left-gate-b`) holds the branches, parts of
# the ticket and pictures left with the person; `branches-not-proven` the ones a recorded answer of theirs excluded. A story with
# neither is byte-identical to one before them.
REPORT_BLOCKS_WHEN_PRESENT = ("exploratory", "left-branches", "branches-not-proven")
# The three phase words of a manual-evidence capture, as every surface that shows one to a person prints it
# (the report's block, the ledger's `## Manual evidence` line, the dashboard table). Records written before
# the rename carry `before` / `after`; `manual_evidence.py` reads them as the same two phases and never
# writes them, and `manual_phase_word` shows them with the words below. A phase it does not know keeps its
# own word: never hidden, never renamed.
#
# The words themselves are DATA (FR-13, t-277 F9): `references/manual-capture-steps.json` `phases[]` and
# `phase_aliases` are the one source. Before, the same three words stood in this file, in
# `manual_evidence.PHASES` and in the capture-steps file, and a fourth word added to one would have been
# refused by the other two with no one the wiser. `manual_capture.py` reads the file itself and
# `manual_evidence.py` imports these two tables (its `PHASE_ALIAS` is their inverse).
MANUAL_STEPS_PATH = Path(__file__).resolve().parents[1] / "references" / "manual-capture-steps.json"


def load_manual_phases(path=None) -> tuple:
    """(words, aliases) from `phases[]` / `phase_aliases` of the capture-steps data file.

    A missing, unreadable or malformed table is a refusal that names the file and the shape it expects
    (FR-1): the three consumers cannot agree on words nobody can read, and a built-in copy here would be the
    very duplicate this loader removes."""
    path = Path(path) if path else MANUAL_STEPS_PATH
    shape = ("Expected `phases`: a non-empty list of words, and `phase_aliases`: an object of old word -> one "
             "of those phases. This is a defect of the factory's install: record it as a finding")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path.name} cannot be read ({exc.__class__.__name__}): it holds the phase words of a "
                         f"manual capture. {shape}")
    words, aliases = (data.get("phases"), data.get("phase_aliases")) if isinstance(data, dict) else (None, None)
    if (not isinstance(words, list) or not words
            or any(not isinstance(w, str) or not w.strip() for w in words) or len(set(words)) != len(words)):
        raise ValueError(f"{path.name}: `phases` is missing, empty, holds a non-word or repeats a word. {shape}")
    if (not isinstance(aliases, dict)
            or any(not isinstance(k, str) or not k.strip() or k in words or v not in words for k, v in aliases.items())):
        raise ValueError(f"{path.name}: `phase_aliases` is missing, or an old word in it is a phase itself, or "
                         f"points at none of {', '.join(words)}. {shape}")
    return tuple(words), dict(aliases)


MANUAL_PHASE_WORDS, MANUAL_PHASE_ALIASES = load_manual_phases()


def manual_phase_word(phase) -> str:
    """The display word of an evidence ref's `phase` ("evidence" when it names none)."""
    word = str(phase or "").strip()
    word = MANUAL_PHASE_ALIASES.get(word, word)
    return word or "evidence"


# The ONE wording of what a delivered text says about a screenshot (the owner's word 31.10.2026: screenshots are the person's
# to confirm the manual cases, never in the repository; a delivered text says only provided or not). The writers are the
# report's case line and exploratory line (`report_facts`) and the ledger's manual-evidence line (`ledger`): none writes its own.
# "provided" is said only for pictures the gate B packet's own section lists (`report_facts.screenshot_groups`, one reader).
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")
SHOTS_PROVIDED = "screenshots: provided"
SHOTS_NONE = "screenshots: not provided (none were taken for this check)"
SHOTS_NO_COPY = "screenshots: not provided (no copy on this machine)"


def is_image(path) -> bool:
    """Is this evidence path a picture, by the suffix of the file it names (the captured file, whatever its hash says)."""
    return str(path or "").lower().endswith(IMAGE_SUFFIXES)


def shots_words(taken: int, provided: int) -> str:
    """The one sentence about screenshots: none taken (an API check has none by design: a fact, not a debt), all taken ones
    provided, or some taken one with no copy on this machine (a refused export, a partial copy, a clean checkout)."""
    if not taken:
        return SHOTS_NONE
    return SHOTS_PROVIDED if provided >= taken else SHOTS_NO_COPY


# The line a report without any marker is read by: the new sections and blocks are not required.
LEGACY_FACTS_LINE = "legacy report: facts not checked"
# The door every refusal about a missing or stale block names.
REPORT_BLOCKS_DOOR = "report_facts.py --task <T> --write"
# One item of "Left with you" answers three questions: which requirement and case it belongs
# to, what a person would have to observe, and how they would do it (or what is needed for it).
REPORT_LEFT_WITH_YOU_REQUIRED = ("To check:",)
REPORT_LEFT_WITH_YOU_ONE_OF = ("Needed:", "How:")
# Spellings the report may not carry: the factory's internal paths and content addresses and the machine fragment.
REPORT_FORBIDDEN = {
    "work/": "a path under work/ — those files are machine inputs, name the document instead",
    "cv_": "a content-addressed case version — a person cannot open a hash",
    "ti_": "a selector-hash instance id — name the test function instead",
    "<!-- factory-summary": "the generated verification fragment — it lives in work/ now",
}
# A decision id with no words beside it. `S5-160` told the person nothing; they asked for the
# decision's own sentence, every time it is cited.
REPORT_BARE_DECISION_RE = re.compile(r"\bS[0-9]-\d+\b(?!\s*[:\-—])")

# WP6 — the escape ledger (a machine index of qa-escape post-mortems). The layer vocabulary is
# the same as in mode E of qa-failure-analyst (artifacts/escapes/<BUG>.json → layer).
ESCAPE_STAGES = {
    "requirements", "plan", "regression", "cases", "automation", "run",
    "exploratory", "env", "out_of_scope", "unknown",
}
# Layers whose hole is a missing element of one of the factory's finite sets: the line must
# name it (aspect: | seam: | perturbation: | class: | oracle:). The remaining layers
# (automation, run, env, out_of_scope, unknown) are explained by the reason field.
ESCAPE_STAGES_WITH_ELEMENT = {"requirements", "plan", "regression", "cases", "exploratory"}
ESCAPE_MISSING_RE = re.compile(r"^(aspect|seam|perturbation|class|oracle):\S.*$")


def load_overrides(config_path: Path) -> dict:
    """Project extensions from config.json (fail-open: no file/key — defaults)."""
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return cfg if isinstance(cfg, dict) else {}


def defect_classes(cfg: dict) -> set:
    extra = cfg.get("defect_classes_extra") or []
    return DEFECT_CLASSES | {str(x) for x in extra if isinstance(x, str)}


def negative_outcome(defect_class: str) -> bool | None:
    """Does a case of this defect class assert a refusal or a failure path?

    `True` or `None`, and the two are different answers. `None` means no field says so — never
    "no": a `boundary` case whose Then is a 422 is as negative as a `permission` one, so no class
    outside the set denies it. What follows from `None` is that the judge does not ask the
    dimension, says so in `not_judged` with this reason, and the critic scores it — which is what
    FR-12 means by "the meaning is decided by a role", and what a phrase list over the case's
    title and Then did silently and sometimes wrongly.
    """
    name = str(defect_class or "").strip().lower()
    return True if name in NEGATIVE_OUTCOME_CLASSES else None


# A status code fixed in a Then, with a word that makes it a response: a case says "3 retries"
# and "404" in the same voice. The code itself is the fact - 4xx and 5xx are refusals and
# failures, and that is arithmetic on a value, not a synonym read off a list.
STATUS_IN_THEN_RE = re.compile(
    r"(?i)(?:status|code|returns?|respond(?:s|ed)?|answers?|http)\D{0,24}\b([1-5]\d\d)\b|`([1-5]\d\d)`")


def negative_then(text: str) -> bool | None:
    """True when a Then demands a 4xx/5xx; `None` when it names no status at all (see above)."""
    codes = [int(a or b) for a, b in STATUS_IN_THEN_RE.findall(str(text or ""))]
    if not codes:
        return None
    return True if any(code >= 400 for code in codes) else None


def negative_case(defect_class: str = "", then: str = "", scenarios=()) -> bool | None:
    """Is this a negative case, by the fields a case and its plan row carry? True or None.

    Three fields, in the order of how directly they say it: the case's own `defect_class`, a
    `negative` variant among the plan row's applicable scenarios, and a status code its Then
    fixes. `None` is the honest answer when none of the three says anything, and the caller
    records it as not judged rather than as "positive" (FR-12, FR-41).
    """
    if negative_outcome(defect_class):
        return True
    for scenario in scenarios or ():
        if str(scenario or "").strip().lower() == "negative":
            return True
    return negative_then(then)


def json_type(value) -> str:
    """The JSON name of a parsed value's type, for a line a person reads (a bool is not a number here)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return {str: "string", list: "list", dict: "map"}.get(type(value), type(value).__name__)


def _override_problem(value) -> str:
    """Why one `impact_scale` entry is not a usable override, or "" when it is: the ONE drop rule, read by the merge and by
    `impact_scale_problems` alike (OH3-3). A usable entry is a map holding both `priority` and `severity`."""
    if not isinstance(value, dict):
        shown = json.dumps(value, ensure_ascii=False)[:40]
        tail = "; a numeric legacy value waits for its decision (config migration conflict)" if json_type(value) == "number" else ""
        return f"is a {json_type(value)} ({shown}), not a {{priority, severity}} map{tail}"
    missing = [key for key in ("priority", "severity") if key not in value]
    return f"is a map without {' and '.join(missing)}, not a {{priority, severity}} map" if missing else ""


def impact_scale(cfg: dict) -> dict:
    scale = dict(IMPACT_SCALE)
    override = cfg.get("impact_scale") or {}
    if isinstance(override, dict):
        for k, v in override.items():
            if not _override_problem(v):
                scale[k] = {"priority": v["priority"], "severity": v["severity"]}
    return scale


def impact_scale_problems(cfg: dict) -> dict:
    """{class: reason} for every override `impact_scale` dropped, and why; `{}` for a valid map and for a whole value that is not a map
    (that case is `impact_scale_state`'s)."""
    override = (cfg or {}).get("impact_scale")
    if not isinstance(override, dict):
        return {}
    return {k: why for k, v in override.items() if (why := _override_problem(v))}


def impact_scale_state(cfg: dict) -> str:
    """The whole-map situation the merge hides: "absent" (no key), "empty" (a map with no class), "not a map" (any other value);
    "" when the project gave a map with classes. The raw value, never the merged scale, which is never empty."""
    if "impact_scale" not in (cfg or {}):
        return "absent"
    value = cfg["impact_scale"]
    if isinstance(value, dict):
        return "" if value else "empty"
    return "not a map"


def impact_scale_phrase(cfg: dict) -> str:
    """The whole-map situation as a phrase for a line a person reads (FR-41; a non-map names its JSON type): "is absent", "is empty",
    "is a string, not a map of classes"; "" when `impact_scale_state` is "". The raw value is read here and nowhere else (AR-13)."""
    state = impact_scale_state(cfg)
    if state == "not a map":
        return f"is a {json_type(cfg['impact_scale'])}, not a map of classes"
    return f"is {state}" if state else ""


def impact_scale_unmapped(cfg: dict) -> set:
    """The package classes a PARTIAL project map does not mention (GW1-10 F-2): they keep the package's row in the merge, and a
    row that moves a weight must say so. Empty for a whole-map situation (`impact_scale_state` is not ""): that has its own line.
    The raw value is read here and nowhere else (AR-13)."""
    if impact_scale_state(cfg):
        return set()
    return set(IMPACT_SCALE) - set(cfg["impact_scale"])


def date_prefix(value) -> str:
    """'2026-09-07T10:00:00Z' → '2026-09-07'; unrecognized → '' (the rule does not apply)."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(value or ""))
    return m.group(1) if m else ""


def after_cutoff(value) -> bool:
    d = date_prefix(value)
    return bool(d) and d >= RULE_CUTOFF


def parse_inline_list(value) -> list:
    """'[R-1, R-2]' / 'R-1, R-2' / '' → a list of strings without quotes."""
    s = str(value or "").strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return [x.strip().strip('"').strip("'") for x in s.split(",") if x.strip()]


def parse_inline_dict_int(value) -> dict:
    """'{story: 2, ac: 3}' → {'story': 2, 'ac': 3}; a non-numeric value is skipped."""
    out = {}
    s = str(value or "").strip().strip("{}")
    for part in s.split(","):
        if ":" not in part:
            continue
        k, _, v = part.partition(":")
        v = v.strip().strip('"').strip("'")
        if v.isdigit():
            out[k.strip().strip('"').strip("'")] = int(v)
    return out


_UNESCAPED_BAR = re.compile(r"(?<!\\)\|")
# Every line break `str.splitlines` knows: CRLF counts once, like LF (a table row is ONE line).
LINE_BREAKS = re.compile("\r\n|[\n\r\x0b\x0c\x1c-\x1e\x85" + chr(0x2028) + chr(0x2029) + "]")


def split_cells(line: str, max_cells: int | None = None) -> list:
    """THE reader of one markdown table row (G2-10, AR-13/AR-15): the cells of `| a \\| b | c |` are `["a | b", "c"]`.
    A row is cut only on an UNESCAPED bar, EXACTLY one bar is taken off each end (a cell that ends in `\\|` right
    before the closing bar keeps it), every cell is stripped and only then unescaped. Whoever writes a cell turns a
    `|` of its words into `\\|` (`escape_cell`); a bare bar is a cell border, so a reader never takes a cell from
    another column silently. An empty line gives `[""]`, `||` gives `[""]`, `|---|---|` gives `["---", "---"]`.
    `max_cells` (default: none) cuts at most `max_cells - 1` times: the LAST cell keeps every later bar, bare ones too; a row with
    fewer cells reads as without it."""
    body = str(line or "").strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cut = _UNESCAPED_BAR.split(body, maxsplit=max(max_cells - 1, 0)) if max_cells else _UNESCAPED_BAR.split(body)
    return [cell.strip().replace("\\|", "|") for cell in cut]


def escape_cell(value) -> str:
    """A cell as a table row writes it (the inverse of `split_cells`): a `|` becomes `\\|`, and every line break
    (LF, CRLF, a lone CR, ...) one space - a row is ONE line, a break would cut it in two."""
    return LINE_BREAKS.sub(" ", str(value if value is not None else "")).replace("|", "\\|")


def table_rows(lines: list, heading: str) -> list:
    """Rows of the markdown table under the heading (up to the next '## '), split into
    cells without the enclosing '|'. The table header and the separator row are skipped."""
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith(heading):
            start = i
            break
    if start is None:
        return []
    rows = []
    for line in lines[start + 1:]:
        st = line.strip()
        if st.startswith("## "):
            break
        if not st.startswith("|"):
            continue
        cells = split_cells(st)
        if not cells or set(cells[0]) <= set("-: ") or cells[0] in ("R", "TS", "H", "#", "ID"):
            continue
        rows.append(cells)
    return rows


def section_present(lines: list, heading: str) -> bool:
    return any(line.strip().startswith(heading) for line in lines)


# --- the marker grammar of the report's code-owned blocks (see REPORT_BLOCKS above) -----------------

class BlockError(ValueError):
    """The report's markers are damaged, or the block asked for is not there. The text is one FR-1
    line per problem: what is wrong, what was expected, and where."""


_MARKER_RE = re.compile(r"^<!-- (/?)facts:([A-Za-z0-9_-]+) -->[ \t]*$")


def _lines_of(text: str):
    """(offset of the line, its content without LF / CRLF, offset of the next line). Only LF ends a
    line: `str.splitlines` also splits on U+2028, form feeds and the like, which a person's own words
    can carry, and an offset that drifts would make `replace_block` cut the wrong bytes."""
    pos, size = 0, len(text)
    while pos < size:
        stop = text.find("\n", pos)
        end, following = (size, size) if stop < 0 else (stop, stop + 1)
        content = text[pos:end]
        yield pos, (content[:-1] if content.endswith("\r") else content), following
        pos = following


def _fence(content: str):
    """(character, length, rest of the line) when the line can open or close a fenced code block."""
    stripped = content.lstrip(" ")
    if len(content) - len(stripped) > 3 or not stripped or stripped[0] not in "`~":
        return None
    char = stripped[0]
    length = len(stripped) - len(stripped.lstrip(char))
    return (char, length, stripped[length:]) if length >= 3 else None


def _scan(text: str) -> tuple:
    """(blocks, seen, problems, markers). `blocks` is {name: (start, end, body)}, `text[start:end] ==
    body`: the span strictly between the start marker's line (its terminator included) and the first
    character of the end marker's line. `seen` is every known block name that has a start marker,
    well formed or not. `problems` is one FR-1 line per defect. `markers` counts the marker lines
    found OUTSIDE code fences (a marker inside a fence is not one)."""
    found, fenced = [], []
    fence = None
    for number, (begin, content, following) in enumerate(_lines_of(text), start=1):
        shape = _fence(content)
        if fence is None:
            if shape and not (shape[0] == "`" and "`" in shape[2]):
                fence = (shape[0], shape[1])
                continue
        elif shape and shape[0] == fence[0] and shape[1] >= fence[1] and not shape[2].strip(" \t"):
            fence = None
            continue
        hit = _MARKER_RE.match(content)
        if hit:
            (fenced if fence else found).append((number, begin, following, hit.group(1) == "/", hit.group(2)))
    blocks, seen, problems = {}, set(), []
    opened = None  # (name, line number, offset where its body begins)
    first_line: dict = {}

    def unterminated(name: str, line: int, before: str = "") -> str:
        inside = [n for n, _b, _f, closing, nm in fenced if closing and nm == name]
        where = (f" (line {inside[0]} carries it inside a code fence, where it is not a marker)"
                 if inside else "")
        return (f"block `{name}` opened at line {line} is never closed{before} - expected "
                f"`<!-- /facts:{name} -->` at the start of a line, outside a code fence{where}; "
                "put it after the block's last line")

    for number, begin, following, closing, name in found:
        mark = f"<!-- {'/' if closing else ''}facts:{name} -->"
        if name not in REPORT_BLOCKS:
            problems.append(f"line {number}: `{mark}` names a block the report does not have; the blocks "
                            f"are {', '.join(REPORT_BLOCKS)} - remove the marker or spell it as one of them")
            continue
        if not closing:
            seen.add(name)
            if opened and opened[0]:
                problems.append(unterminated(
                    opened[0], opened[1], f" when block `{name}` opens at line {number} (blocks do not nest)"))
            if name in first_line:
                problems.append(f"line {number}: block `{name}` opens a second time (first at line "
                                f"{first_line[name]}) - a block appears once; delete the copy")
                opened = (None, number, following)
                continue
            first_line[name] = number
            opened = (name, number, following)
            continue
        if opened is None:
            problems.append(f"line {number}: `{mark}` closes a block that is not open - restore the "
                            f"opening `<!-- facts:{name} -->` line above it, or delete the marker")
        elif opened[0] is None:
            opened = None  # the end of a copy already reported above
        elif opened[0] != name:
            problems.append(f"line {number}: `{mark}` closes block `{opened[0]}` (opened at line "
                            f"{opened[1]}) - a block is closed by its own marker")
            opened = None
        else:
            blocks[name] = (opened[2], begin, text[opened[2]:begin])
            opened = None
    if opened and opened[0]:
        problems.append(unterminated(opened[0], opened[1]))
    return blocks, seen, problems, len(found)


def has_markers(text: str) -> bool:
    """True when the report carries at least one marker line outside a code fence - the report was
    written with code-owned blocks. False is a report of the generation before them."""
    return _scan(text)[3] > 0


def marker_problems(text: str) -> list:
    """Every defect of the report's markers, one FR-1 line each ([] for a clean or an unmarked one).
    A block of REPORT_BLOCKS with no marker at all is not here: that is a missing block, not a
    damaged one (`validate_artifacts.check_report_blocks` names it with its door)."""
    return _scan(text)[2]


def blocks_seen(text: str) -> set:
    """The known block names that have an opening marker, well formed or not."""
    return set(_scan(text)[1])


def blocks_found(text: str) -> dict:
    """The well-formed blocks, like `find_blocks`, but never raising: a damaged block is simply not in
    the answer. For a reader that reports the damage itself (`marker_problems`) and still wants to
    check the blocks that are sound."""
    return _scan(text)[0]


def heading_lines(text: str) -> list:
    """The `## ` heading lines of `text` (stripped) that stand OUTSIDE code fences, in order."""
    out, fence = [], None
    for _begin, content, _following in _lines_of(text):
        shape = _fence(content)
        if fence is None:
            if shape and not (shape[0] == "`" and "`" in shape[2]):
                fence = (shape[0], shape[1])
                continue
        elif shape and shape[0] == fence[0] and shape[1] >= fence[1] and not shape[2].strip(" \t"):
            fence = None
            continue
        if fence is None and content.strip().startswith("## "):
            out.append(content.strip())
    return out


def find_blocks(text: str) -> dict:
    """{name: (start, end, body)} for every block, `text[start:end] == body` - the body verbatim, with
    the file's own line endings, from the first character after the start marker's line to the first
    character of the end marker's line (a clean block therefore ends with its last line's own
    terminator). Pure. Raises BlockError, listing every defect, when the markers are damaged: a
    partial answer would let a writer believe a block is missing and insert a second one."""
    blocks, _seen, problems, _count = _scan(text)
    if problems:
        raise BlockError("; ".join(problems))
    return blocks


def canonical_body(body: str) -> str:
    """The body as `replace_block` writes it: LF line endings, and one LF after the last line
    (a block with no text stays empty). Two bodies that differ only in line endings, or in the
    final line's terminator, are equal under it - the comparison a stale-block check makes."""
    text = str(body or "").replace("\r\n", "\n")
    return text if not text or text.endswith("\n") else text + "\n"


def replace_block(text: str, name: str, body: str) -> str:
    """`text` with the body of block `name` replaced by `canonical_body(body)`; the marker lines, the
    bytes outside the block and the file's line endings outside it are untouched (LF inside the block
    whatever the file uses, R-S9.3). Raises BlockError when the block is absent or the markers are
    damaged; inserting a block that is not there yet is the caller's move, with `render_block`."""
    blocks = find_blocks(text)
    if name not in blocks:
        raise BlockError(f"block `{name}` is not in the report - expected `<!-- facts:{name} -->` ... "
                         f"`<!-- /facts:{name} -->`; a report without its blocks is converted by "
                         f"{REPORT_BLOCKS_DOOR}")
    start, end, _old = blocks[name]
    return text[:start] + canonical_body(body) + text[end:]


def render_block(name: str, body: str) -> str:
    """The marked block, ready to insert: both marker lines, LF, a final newline."""
    if name not in REPORT_BLOCKS:
        raise BlockError(f"`{name}` is not a block of the report; the blocks are {', '.join(REPORT_BLOCKS)}")
    return f"<!-- facts:{name} -->\n{canonical_body(body)}<!-- /facts:{name} -->\n"
