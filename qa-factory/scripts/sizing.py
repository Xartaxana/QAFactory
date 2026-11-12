"""Story size, computed by code — not chosen by the role that also wrote the register.

on TP1-15045 nothing behind "14 testable requirements, size L" was checkable. The
formula in `qa-requirements-tester.md` step 5 multiplied by "the strategy's risk multiplier",
a number that has never existed in a project's config (`impact_scale_note` in the config
template says numeric area multipliers are invalid — they were removed on purpose). The role
wrote 14 testable requirements in `understanding.md` and used 12 in the formula, and nobody
could tell which was right because the arithmetic lived only in prose. The precedent ledger
(`estimation-ledger.jsonl`) was empty, so "check the nearest precedent" had nothing to check.

This module replaces the formula with code and the multiplier with a weight per requirement,
drawn from the requirement's own impact class (`config.impact_scale`), the same closed list a
bug's severity already comes from — one scale, not two.

THE UNIT (OH3-15, the owner 22.10.2026: "measure in functions, not in how thoroughly they are described"). When the register
carries a `## Functions` table (the tester names what a person can do or rely on separately, and the requirement ids each one
holds), `size` = `size_for(2 x N)` for the N functions it names, and `size_unit` says "functions". The weighted budget, the
test ceiling (`cap`), `overage` and `recommended_budget` keep their numbers and keep their own keys: how much there is to
test and how many functions there are are two facts. No table (an old register, a story in flight): `size` is the weighted
budget's band exactly as before and `size_unit` says "requirements". A role writes the table, so code may err only UPWARD: a
row it cannot place is one more function, never fewer (a role's downward error is made visible by `functions[]` and
`cited_files`, not prevented). The sibling STLC factory
(`ai-packages/stlc-factory`, `references/risk-coverage-model.md`) sizes the same way in
spirit (`2 x criteria`, the same cap table, reducers, a defect-ticket cap, "report overage,
never truncate") but with one multiplier for the whole story. A mixed story breaks that: on
15045, `validate` returning "nothing written to the database" (a P0 fact) and the color of a
node's border (a P3 fact) sit in the same register, and one number cannot represent both.

  sizing.py --task TP1-15045
  sizing.py --task TP1-15045 --json
  sizing.py --task-root <TASK_ROOT> --project-root <PROJECT_ROOT>

Tolerant by construction: a register with no `impact` column, a project with no config.json,
a story with no context-manifest.json, a project with no strategy file or no ledger — every
one of these still produces `work/sizing.json`, and `reasoning[]` names exactly what was
missing rather than silently guessing. Nothing here blocks a stage; `stages.json` owns that
(see "Needed from integration" in the P6 report).
"""
from __future__ import annotations

import argparse
import functools
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hooklib  # noqa: E402  (`read_json`, the one JSON reader)

from contract import (CLAIM_ORIGIN_S3, REQ_ID_RE, _header_index, behaviour_claims, md_table,  # noqa: E402
                      observable_source, register_rows, strip_cell)  # pure parser, no writes, no exits (see its docstring)
import grammar as G  # noqa: E402 — the one reader of the impact scale (`impact_scale`, `impact_scale_problems`, `impact_scale_state`; AR-13)
import runtime_paths as RP  # noqa: E402 — where the estimation ledger lives (records/, or state/ in an old-layout project)
from critic_rollcall import project_root_of  # noqa: E402 — the onboarded project a story lives in, or None: found by its marker (`qa-factory/config.json`), never guessed (TP1-14336); the ONE walk

# --- the weight table -------------------------------------------------
# P0 (data-loss/money/access) x1.6 * P1 (blocked-flow, OR an area named in the strategy's P1
# list) x1.3 * P2 (degraded/unclassified) x1.0 * P3 (cosmetic/none) x0.6. Overridable per
# project via config.json "sizing": {"weights": {"P0": ..., ...}} (decision #9) — onboarding
# asks nothing new, a project that sets nothing keeps exactly this table.
DEFAULT_WEIGHTS = {"P0": 1.6, "P1": 1.3, "P2": 1.0, "P3": 0.6}
TIER_ORDER = ("P3", "P2", "P1", "P0")  # low risk -> high risk, for the diff-signal step-up

# The STLC cap table (references/risk-coverage-model.md), unchanged here: "report overage,
# never truncate" holds for us too.
CAP_TABLE = (("XS", 2), ("S", 5), ("M", 10), ("L", 18), ("XL", 28))

# Reducers adopted from STLC (decision #4). Whole-story factors, applied after the
# per-requirement weights are summed — a single multiplier on one number, same as STLC.
REDUCER_SINGLE_CRITERION = 0.8
REDUCER_COPY_ONLY = 0.5
REDUCER_LOGGING_ONLY = 0.7

COPY_RE = re.compile(r"\b(copy|label(?:l?ing)?|translat\w*|wording|placeholder text|"
                      r"tooltip text|caption)\b", re.IGNORECASE)
LOG_RE = re.compile(r"\b(log(?:ging|s)?|metrics?|telemetry|audit trail|analytics event)\b",
                     re.IGNORECASE)
MIGRATION_RE = re.compile(r"migrat", re.IGNORECASE)  # migration / migrations / migrating
# The two boundary pairs 4a names explicitly: UI<->API, API<->DB. A requirement whose own
# observables touch both sides of one of these pairs is "bound to the touched place"; one
# that only touches UI (or only API) is not, however many surfaces the STORY touches.
BOUNDARY_PAIRS = ({"ui", "api"}, {"api", "db"})

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z-]{4,}")  # words of 5+ letters — short words are noise
_STOPWORDS = {"about", "which", "other", "their", "after", "before", "across", "using",
              "including", "without", "these", "those", "where", "every", "there", "still"}


def _words(text: str) -> set:
    return {w for w in _WORD_RE.findall((text or "").lower()) if w not in _STOPWORDS}


# The package's one JSON reader. This module's direction: whatever goes wrong while reading is `default`, None unless passed.
_read_json = functools.partial(hooklib.read_json, errors=Exception)


def _read_text(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _read_error(path: Path) -> str:
    """The name of the exception when `path` EXISTS and reading it raises (a folder, a locked file), else "" (absent, or readable):
    the one thing `_read_text` hides, so a caller can tell "no register" from "a register that could not be read" (OH3-23 Q6)."""
    try:
        if not Path(path).exists():
            return ""
        Path(path).read_text(encoding="utf-8", errors="replace")
        return ""
    except Exception as exc:
        return type(exc).__name__


# --- register --------------------------------------------------------------------------------

REGISTER_COLUMNS = ("r", "requirement", "source", "derived_from", "verifiable", "ac_ref",
                    "observable")


def parse_register(path: Path) -> dict:
    """THIN ADAPTER over `contract.register_rows` (AR-13: the one reader of a register row; OH3-34). The rows are the reader's
    (`r`, `requirement`, `source`, `derived_from`, `ac_ref`, `observable`, `delta`); the two columns the reader does not carry and
    sizing needs, `verifiable` and `impact`, are added here by their header. `has_impact`: whether an `impact` column exists at
    all (an older register has none - the module still produces a number). A register with no `Requirement` column is refused
    by the reader: `found` is False and `problem` names it (FR-41), never rows with an empty key."""
    text = _read_text(path)
    if not text:
        return {"rows": [], "has_impact": False, "found": False}
    raw = md_table(text, "## Register")
    if not raw:
        return {"rows": [], "has_impact": False, "found": False}
    try:
        rows = register_rows(text)
    except ValueError as exc:
        return {"rows": [], "has_impact": False, "found": False, "problem": str(exc)}
    extra = {name: _header_index(raw[0], name, -1, exact=True) for name in ("verifiable", "impact")}
    cells_of = [c for c in raw[1:] if c and REQ_ID_RE.fullmatch(strip_cell(c[0]))]   # the reader's own row filter, same order
    for row, cells in zip(rows, cells_of):
        for name, i in extra.items():
            row[name] = strip_cell(cells[i]) if 0 <= i < len(cells) else ""
    return {"rows": rows, "has_impact": extra["impact"] >= 0, "found": True}


def is_unverifiable(row: dict) -> str:
    """"" when the requirement counts toward the budget; otherwise the reason it does not
    (decision #5 — a requirement nobody can name an observable check for is a requirements
    defect, not a test, and contributes zero)."""
    reasons = []
    if str(row.get("verifiable", "")).strip().lower() == "no":
        reasons.append("verifiable: no")
    observable = str(row.get("observable", "")).strip().lower()
    if observable == "none" or observable.startswith("none "):
        reasons.append("observable: none")
    return "; ".join(reasons)


# --- config / strategy / manifest / ledger ----------------------------------------------------

def read_config(project_root) -> tuple:
    """(cfg, state, detail) of the project's `qa-factory/config.json` (OH3-23 Q6): `state` is `no_root`, `absent` (no such file),
    `unreadable` (it exists and reading or parsing raised; `detail` is the exception's name), `not_object` (valid JSON of another
    type; `detail` is `grammar.json_type` of it) or `ok`. `cfg` is `{}` in every state but `ok`: the module's tolerance, never a raise (FR-41)."""
    if not project_root:
        return {}, "no_root", ""
    path = Path(project_root) / "qa-factory" / "config.json"
    if not path.exists():
        return {}, "absent", ""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {}, "unreadable", type(exc).__name__
    if not isinstance(data, dict):
        return {}, "not_object", G.json_type(data)         # the package's one JSON-kind namer (OH3-3)
    return data, "ok", ""


def resolve_weights(cfg: dict) -> tuple:
    """(weights, source). `sizing.weights` is the one optional config key this module reads
    (decision #9); a project that sets nothing gets exactly DEFAULT_WEIGHTS."""
    raw = ((cfg or {}).get("sizing") or {}).get("weights")
    weights = dict(DEFAULT_WEIGHTS)
    source = "default"
    if isinstance(raw, dict):
        applied = {}
        for tier in DEFAULT_WEIGHTS:
            value = raw.get(tier)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                applied[tier] = float(value)
        if applied:
            weights.update(applied)
            source = "config.sizing.weights"
    return weights, source


def impact_scale_line(cfg: dict) -> str:
    """The whole-map line (FR-41, OH2-6 (a)): three situations, three phrases, read from the RAW value through `grammar`;
    "" when the project gave a map with classes."""
    phrase = G.impact_scale_phrase(cfg)
    return f"config.impact_scale {phrase} — the package's default classes apply" if phrase else ""


def parse_p1_areas(strategy_text: str) -> list:
    """The strategy's "P1 areas." paragraph (`·`-separated phrases), e.g.
    `test-strategy.md`: "Assistant chat including tool invocation · workflow execution
    (...) · ...". Absent or differently worded -> [] and the caller notes it; this module
    never invents an area list of its own (the same rule the STLC risk model states for risk
    classification: a keyword list is a guess about someone else's product)."""
    match = re.search(r"\*\*P1 areas\.\*\*(.*?)(?:\*\*P2 areas\.\*\*|\Z)", strategy_text or "",
                       re.DOTALL)
    if not match:
        return []
    phrases = []
    for part in match.group(1).split("·"):
        phrase = re.sub(r"\s+", " ", part).strip(" .\n*")
        if phrase:
            phrases.append(phrase)
    return phrases


# The two literals of the PRODUCER (skills/qa-onboarding/phases/p4-generate.md, "Risk and impact scale") this reader keys on to tell
# an answer from a hole. A rename on either side is caught by test_sizing.py (K2), which takes both FROM p4-generate.md (AR-22).
RISK_AREAS_DEFERRED_MARKER = "[DEFERRED: risk areas not named]"
NO_AREA_SENTENCE = "No area stands out:"
_STRATEGY_REL = "qa-factory/strategy/test-strategy.md"
_BUMP_UNAVAILABLE = "the area-based weight bump is unavailable"


def strategy_area_state(project_root) -> tuple:
    """(areas, state, lines): the P1 areas of the project's strategy, and when there are none WHICH state the file is in, with the
    reasoning line(s) that say so (FR-41, AR-28) instead of one generic "no paragraph" line for seven different situations.
    The first state that holds wins: `areas` (a non-empty P1 paragraph; a human's value stands; no line), `no_file`, `unreadable`
    (the file exists and reading raised), `deferred` (the marker), `none_stands_out` (a line that STARTS with the none sentence),
    `label_empty` (the P1 label with no phrase after it), `not_asked` (nothing of the above: the generic line, never a claimed
    answer). The deferral comes before the none sentence: when both are there the file contradicts itself, and a second line says so.
    `no_root` (no project root) has no line here: the caller already names that. Reports only: no weight depends on the state (AR-2)."""
    if not project_root:
        return [], "no_root", []
    path = Path(project_root) / "qa-factory" / "strategy" / "test-strategy.md"
    if not path.exists():
        return [], "no_file", [f"no {_STRATEGY_REL} — {_BUMP_UNAVAILABLE}"]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return [], "unreadable", [f"{_STRATEGY_REL} could not be read ({type(exc).__name__}) — {_BUMP_UNAVAILABLE}"]
    areas = parse_p1_areas(text)
    if areas:
        return areas, "areas", []
    sentence = NO_AREA_SENTENCE.rstrip(":")
    has_sentence = bool(re.search(r"^" + re.escape(NO_AREA_SENTENCE), text, re.MULTILINE))
    if RISK_AREAS_DEFERRED_MARKER in text:
        lines = [f"risk areas deferred: test-strategy.md carries {RISK_AREAS_DEFERRED_MARKER} and its row should be in "
                 f"qa-factory/factory-backlog.md — no area-based weight bump until the team answers"]
        if has_sentence:
            lines.append(f"test-strategy.md holds both the deferral marker and the '{sentence}' sentence — one of them is stale")
        return [], "deferred", lines
    if has_sentence:
        return [], "none_stands_out", [f"the team named no risk area (test-strategy.md: '{sentence}') — "
                                       f"no area-based weight bump, by the team's answer"]
    if "**P1 areas.**" in text:
        return [], "label_empty", [f"a '**P1 areas.**' label with no phrase after it in {_STRATEGY_REL} — {_BUMP_UNAVAILABLE}"]
    return [], "not_asked", [f"test-strategy.md holds no 'P1 areas.' paragraph, no answer and no deferral: topic 4 was not asked "
                             f"(an onboarding without the risk-areas question, or one older than it) — {_BUMP_UNAVAILABLE}"]


# A path token needs a `/` or a known code-file suffix: a bare dotted word of prose ("Node.js", "e.g") is not a path (OH3-34 m-4).
# `js` is left out of the suffix set on purpose: it is also the tail of product names ("Node.js", "Vue.js"); a `.js` file is still a
# token when it sits under a `/` ("src/app.js").
_FILE_SUFFIXES = ("py", "ts", "tsx", "jsx", "java", "kt", "go", "rs", "rb", "php", "cs", "sql", "yaml", "yml", "json", "md", "html", "css", "scss", "vue")
_PATH_TOKEN_RE = re.compile(r"[\w.-]+(?:/[\w.-]+)+|(?<![\w./-])[\w-]+\.(?:" + "|".join(_FILE_SUFFIXES) + r")(?![\w-])", re.IGNORECASE)


def area_surface_tokens(area: str, signals: dict) -> tuple:
    """(kinds, paths) of the P1 area `area` (OH3-34 item 3, narrowed by the critic's B-1): `paths` are its path tokens (see
    `_PATH_TOKEN_RE`), each as a lower-case tuple of path segments; `kinds` are the words of the area that are surface kinds this
    story's manifest declares (`signals["surfaces"]`: that set is READ, no list of kinds lives here). An area names a surface ONLY
    through a path token: `kinds` can only FILTER a path match (a kind word alone names where the story's diff is, not a product
    area), so an area with no path token names no surface and matches nothing (FR-41: `area_without_surface_lines` says so)."""
    known = {str(k).lower() for k in (signals or {}).get("surfaces") or []}
    text = str(area or "")
    kinds = sorted({w for w in re.findall(r"[A-Za-z]+", text.lower()) if w in known})
    paths = [tuple(seg for seg in tok.lower().split("/") if seg) for tok in _PATH_TOKEN_RE.findall(text)]
    return kinds, [p for p in paths if p]


def area_names_surface(area: str, signals: dict) -> bool:
    """Whether code can place requirements in `area` at all: it holds a path token."""
    return bool(area_surface_tokens(area, signals)[1])


def area_without_surface_lines(p1_areas: list, signals: dict) -> list:
    """One reasoning line per P1 area that names no surface (so can bump nothing), in strategy order."""
    return [f"P1 area «{area}» names no surface — no bump" for area in p1_areas if not area_names_surface(area, signals)]


def area_state(p1_areas: list, signals: dict, state: str, register_read: bool) -> dict:
    """The record of how the areas stood for `work/sizing.json` (OH3-34 B-2; FR-41, AR-28): the strategy's state (`strategy_area_state`),
    whether the register was read, the areas that name a surface (`named`: code could check them) and those that do not (`no_surface`:
    left to the role's judgment). The brief states "no requirement falls in a P1 area" only from this record."""
    return {"state": state, "register_read": bool(register_read),
            "named": [a for a in p1_areas if area_names_surface(a, signals)],
            "no_surface": [a for a in p1_areas if not area_names_surface(a, signals)]}


def _segments_hold(path_segments: list, wanted: tuple) -> bool:
    """`wanted` is a run of consecutive segments of `path_segments` (a one-segment `wanted` is a segment equal to it)."""
    n = len(wanted)
    return any(tuple(path_segments[i:i + n]) == wanted for i in range(len(path_segments) - n + 1))


def find_area_match(row: dict, p1_areas: list, signals: dict):
    """The first P1 area (strategy order) that names a surface this row's `observable` cell is on, else None. An area MATCHES
    when a path token of it lies, by path segments and case-insensitively, inside a path the cell names; a surface kind word
    of the area (e.g. "API") only narrows that to rows whose manifest observable (the one join `requirement_signal` uses,
    `_cell_observables`; AR-13) is of that kind, and never matches alone. The requirement's own words are never read.
    A row with an empty cell, or one the cell does not join, matches no area."""
    candidates, _problem = _observable_ref((row or {}).get("observable"))
    if not candidates:
        return None
    paths = [[seg for seg in path.lower().replace("\\", "/").split("/") if seg] for _repo, path in candidates]
    kinds = {str(o.get("kind", "")).strip().lower() for o in _cell_observables(candidates, signals) if o.get("kind")}
    for area in p1_areas:
        area_kinds, area_paths = area_surface_tokens(area, signals)
        if area_kinds and not set(area_kinds) & kinds:
            continue                          # the kind word filters: the row is not on a surface of that kind
        if any(_segments_hold(have, want) for want in area_paths for have in paths):
            return area
    return None


def parse_ledger(project_root) -> list:
    if not project_root:
        return []
    path = RP.record(project_root, "estimation-ledger.jsonl")
    if not path.is_file():
        return []
    rows = []
    for line in _read_text(path).splitlines():
        line = line.strip()
        if not line:
            continue
        row = None
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def nearest_precedents(rows: list, computed_budget: float, area_words: set, limit: int = 2) -> list:
    """A second check, never a decider (decision #8) — the divergence is named, the size is
    not changed by it. Matched best-effort by driver/area word overlap, then by closeness of
    the recorded forecast size; a ledger with no usable `forecast` numbers or no `drivers`
    contributes nothing rather than a wrong match."""
    scored = []
    for row in rows:
        forecast = row.get("forecast") if isinstance(row.get("forecast"), dict) else {}
        size_value = forecast.get("computed_budget", forecast.get("budget"))
        if not isinstance(size_value, (int, float)) or isinstance(size_value, bool):
            continue
        drivers = row.get("drivers") if isinstance(row.get("drivers"), list) else []
        driver_words = set()
        for driver in drivers:
            if isinstance(driver, str):
                driver_words |= _words(driver)
        overlap = len(driver_words & area_words)
        scored.append({"task": row.get("task"), "budget": size_value,
                       "overlap": overlap, "gap": abs(size_value - computed_budget)})
    scored.sort(key=lambda item: (-item["overlap"], item["gap"]))
    return scored[:limit]


# --- diff signals (decision #4, 4a) -----------------------------------------------------------

def diff_signals(manifest: dict) -> dict:
    manifest = manifest if isinstance(manifest, dict) else {}
    repos = set()
    for impl in manifest.get("implementations") or []:
        if isinstance(impl, dict) and impl.get("repo"):
            repos.add(str(impl["repo"]))
    single = manifest.get("implementation")
    if isinstance(single, dict) and single.get("repo"):
        repos.add(str(single["repo"]))

    observables = manifest.get("observables") or []
    kinds = set()
    by_requirement: dict = {}
    migration_files = []
    for obs in observables:
        if not isinstance(obs, dict):
            continue
        kind = str(obs.get("kind") or "").strip().lower()
        if kind:
            kinds.add(kind)
        req = obs.get("requirement")
        if req:
            by_requirement.setdefault(str(req), []).append(obs)
        haystack = " ".join(str(obs.get(k, "")) for k in ("path", "note"))
        if MIGRATION_RE.search(haystack):
            migration_files.append({"path": obs.get("path"), "repo": obs.get("repo"),
                                    "note": obs.get("note")})
    for area in manifest.get("changed_areas") or []:
        if isinstance(area, str) and MIGRATION_RE.search(area):
            migration_files.append({"path": None, "repo": None, "note": area})

    repo_map = manifest.get("repo_map") if isinstance(manifest.get("repo_map"), dict) else None
    return {"repos": sorted(repos), "surfaces": sorted(kinds),
            "surfaces_signal": len(kinds) > 2, "migration_signal": bool(migration_files),
            "migration_files": migration_files, "by_requirement": by_requirement,
            "observables": [o for o in observables if isinstance(o, dict)], "repo_map": repo_map}


def _crosses_boundary(kind_set: set) -> bool:
    return any(pair <= kind_set for pair in BOUNDARY_PAIRS)


def _next_tier(weights: dict, weight: float) -> tuple:
    """The tier one step riskier than `weight` currently sits at (P3->P2->P1->P0, P0 stays
    P0). Matched by value against `weights` so a project's own `sizing.weights` override is
    respected for the step, not just for the starting point."""
    ordered = [(tier, weights.get(tier, DEFAULT_WEIGHTS[tier])) for tier in TIER_ORDER]
    idx = 0
    for i, (_tier, value) in enumerate(ordered):
        if weight >= value:
            idx = i
    idx = min(idx + 1, len(ordered) - 1)
    return ordered[idx]


_NO_OBSERVABLE_CELLS = ("", "-", "—", "none")      # a cell that names nothing: the row has no observable at all


def _observable_ref(cell) -> tuple:
    """(candidates, problem) of a register row's `observable` cell. The cell is read through the register's one parser
    (`contract.strip_cell` / `observable_source`: the backticks and the closed prefix list are NOT re-listed here); the
    forms are `diff:<path>:<line>`, `diff:<repo>:<path>:<line>` and the same with `current-code:` (backslashes read as slashes,
    the `:line` optional). `candidates` is a list of `(repo, path)` - a cell with a `:` after the prefix is read both as a
    bare path and as `<repo>:<path>`, so a path that itself holds a colon is never lost; `problem` is the TRUE reason the cell
    yields no file ('' when it yields one, or when the cell names nothing at all: that is not a defect of the cell)."""
    value = strip_cell(cell).replace("\\", "/")
    if value.lower() in _NO_OBSERVABLE_CELLS:
        return ([], "")
    source = observable_source(value)
    if not source:
        return ([], f"the observable cell `{value}` is neither diff:... nor current-code:... (no file to join by)")
    if source == "expected-contract":
        return ([], "the observable is an expected contract, not a file")
    rest = re.sub(r":\d*$", "", value[len(source) + 1:].strip())      # the optional `:line` (an empty one too)
    if not rest:
        return ([], f"`{source}:` names no path")
    candidates = [(None, rest)]
    if ":" in rest:
        repo, _, path = rest.partition(":")
        if not repo.strip():
            return ([], f"`{source}:` names no repo before the path `{path.strip()}`")
        if not path.strip():
            return ([], f"`{source}:{repo.strip()}:` names no path after the repo")
        candidates.append((repo.strip(), path.strip()))
    return (candidates, "")


def _same_path(manifest_path, path: str) -> bool:
    """A manifest observable's `path` against the one a register cell names, slashes and a leading `./` ignored."""
    return str(manifest_path or "").replace("\\", "/").removeprefix("./") == path.removeprefix("./")


def _joins_cell(obs: dict, candidates: list) -> bool:
    """Whether the manifest observable `obs` is the place a register cell names: the path equal, and - when the cell
    carries a repo and the observable has one - the repo equal too (another repo's file of the same name is not it)."""
    for repo, path in candidates:
        if _same_path(obs.get("path"), path) and (repo is None or not obs.get("repo") or str(obs.get("repo")) == repo):
            return True
    return False


def _cell_observables(candidates: list, signals: dict) -> list:
    """The manifest observables the register cell's `candidates` (`_observable_ref`) join: the one join of a row to its kinds."""
    return [o for o in (signals or {}).get("observables", []) if _joins_cell(o, candidates)]


def _no_join_note(ac_ref: str, problem: str, candidates: list) -> str:
    """The note of a requirement nothing could be joined to: names the TRUE cause of each key (FR-41). The wording
    'no ac_ref and no observable path' is written only when both keys are really absent."""
    ac_part = f"ac_ref {ac_ref} is in no manifest observable" if ac_ref else "no ac_ref"
    if problem:
        cell_part = problem
    elif candidates:
        repo, path = candidates[-1]
        cell_part = "no manifest observable holds " + (f"{repo}:{path}" if repo else path)
    else:
        cell_part = "no observable path"
    if not ac_ref and not problem and not candidates:
        return "no per-requirement signal: no ac_ref and no observable path"
    return f"no per-requirement signal: {ac_part}; {cell_part}"


def requirement_signal(row: dict, signals: dict) -> tuple:
    """(signal_label, note) for this ONE requirement, or (None, None). 4a: the STLC signal
    raises the whole story's one multiplier; here each requirement has its own weight, so the
    signal raises only the requirements bound to the touched place — never the whole story."""
    ac_ref = str(row.get("ac_ref") or "").strip()
    observables = signals["by_requirement"].get(ac_ref, [])
    if not observables:
        # A task with no AC has no `ac_ref` to join by (P23, t-928): the row's own `observable` cell
        # (`diff:<path:line>`, `current-code:<path:line>`) names the file instead. Over-signalling is the
        # accepted direction - one file shared by two requirements lifts both - never a silent loss.
        candidates, problem = _observable_ref(row.get("observable"))
        observables = _cell_observables(candidates, signals)
    if not observables and (signals["surfaces_signal"] or signals["migration_signal"]):
        return (None, _no_join_note(ac_ref, problem, candidates))      # said, not dropped (FR-41)
    kind_set = {str(o.get("kind", "")).strip().lower() for o in observables if o.get("kind")}
    req_repos = {o.get("repo") for o in observables if o.get("repo")}

    if signals["surfaces_signal"] and kind_set and _crosses_boundary(kind_set):
        pair = "-".join(sorted(kind_set & (BOUNDARY_PAIRS[0] | BOUNDARY_PAIRS[1])))
        return (f"surfaces:{pair}",
                f"requirement's own check crosses a surface boundary ({pair}) and the story "
                f"touches more than two surfaces overall ({', '.join(signals['surfaces'])})")

    if signals["migration_signal"] and req_repos:
        mig_repos = {m.get("repo") for m in signals["migration_files"] if m.get("repo")}
        if mig_repos and (req_repos & mig_repos):
            repo = sorted(req_repos & mig_repos)[0]
            if signals["repo_map"]:
                mig_modules = {str(m.get("path", "")).split("/")[0]
                               for m in signals["migration_files"] if m.get("repo") == repo}
                req_modules = {str(o.get("path", "")).split("/")[0]
                               for o in observables if o.get("repo") == repo}
                if not (mig_modules & req_modules):
                    return (None, None)
                return (f"migration:{repo}",
                        f"same repo and top-level module as a migration file ({repo})")
            return (f"migration:{repo}",
                    f"same repo as a migration file ({repo}); no repo module map in the "
                    f"manifest, so the signal was applied at repo grain, not module grain")
    return (None, None)


# --- weighting ---------------------------------------------------------------------------------

def classify_requirement(row: dict, impact_scale: dict, weights: dict, p1_areas: list, problems: dict | None = None,
                         unmapped: set | frozenset = frozenset(), signals: dict | None = None) -> dict:
    """`impact_scale` is `grammar.impact_scale(cfg)` (the package's classes with the project's valid overrides); `problems` is
    `grammar.impact_scale_problems(cfg)`; `unmapped` is `grammar.impact_scale_unmapped(cfg)` (a partial map's silent classes). A class the project's map dropped is checked BEFORE the `in impact_scale` branch: a dropped
    override is never read as a valid class without its note (OH3-3)."""
    raw_impact = str(row.get("impact", "") or "").strip()
    notes = []
    problem = (problems or {}).get(raw_impact) if raw_impact in impact_scale else None
    if problem:
        # OH2-6 (a): the project's entry for this class is not a {priority, severity} map (config_contract.py refuses it too).
        # A note and the weight the package's own class gives, never an exception: this is the command that is to tell the
        # person what is wrong. (A dropped class the package has no row for is "outside" below: nothing to fall back to.)
        priority = str(impact_scale[raw_impact].get("priority") or "P2")
        if priority not in weights:
            priority = "P2"
        notes.append(f"{row.get('r')}: config.impact_scale['{raw_impact}'] {problem} — "
                     f"weight {weights.get(priority, DEFAULT_WEIGHTS['P2'])} ({priority} default)")
    elif raw_impact and raw_impact in impact_scale:
        raw_priority = impact_scale[raw_impact].get("priority")
        priority = str(raw_priority or "P2")
        if raw_priority in (None, ""):
            # GW1-10 F-5: a null or empty priority is not a P2 the project chose; the line names it
            notes.append(f"{row.get('r')}: config.impact_scale['{raw_impact}'] has an empty priority — "
                         f"weight {weights.get('P2', DEFAULT_WEIGHTS['P2'])} (P2 default)")
        elif priority not in weights:
            notes.append(f"{row.get('r')}: impact class '{raw_impact}' maps to priority '{priority}', which has no weight — "
                         f"weight {weights.get('P2', DEFAULT_WEIGHTS['P2'])} (P2 default)")
            priority = "P2"
        elif raw_impact in unmapped and weights[priority] != weights.get("P2", DEFAULT_WEIGHTS["P2"]):
            # GW1-10 F-2: a partial project map; this class kept the package's row and its weight is not the P2 one
            notes.append(f"{row.get('r')}: class '{raw_impact}' is not in config.impact_scale — "
                         f"the package's weight {weights[priority]} ({priority})")
    elif raw_impact:
        priority = "P2"
        notes.append(f"{row.get('r')}: impact value '{raw_impact}' is outside "
                     f"config.impact_scale — weight 1.0 (P2 default)")
    else:
        priority = "P2"
        notes.append(f"{row.get('r')}: no impact class recorded — weight 1.0 (P2 default)")

    area_match = find_area_match(row, p1_areas, signals or {})
    base_weight = weights.get(priority, DEFAULT_WEIGHTS.get(priority, 1.0))
    p1_weight = weights.get("P1", DEFAULT_WEIGHTS["P1"])
    if area_match and p1_weight > base_weight:
        notes.append(f"{row.get('r')}: area '{area_match}' is a P1 area per the strategy -> "
                     f"weight raised to {p1_weight} (was {base_weight})")
        priority, base_weight = "P1", p1_weight

    return {"priority": priority, "weight": base_weight, "area_match": area_match, "notes": notes}


# --- the computation ----------------------------------------------------------------------------

def size_for(budget: float) -> tuple:
    """(size, cap) — the STLC cap table; above XL's 28 is XXL, with the same cap as XL: the label
    does not grow a bigger number (decision #6)."""
    for name, cap in CAP_TABLE:
        if budget <= cap:
            return name, cap
    return "XXL", CAP_TABLE[-1][1]


# --- the unit: functions (OH3-15) --------------------------------------------------------------

FUNCTIONS_HEADING = "## Functions"
NAME_SHOWN = 60          # a function's name is CLIPPED for display at this many characters; the count and `sizing.json` never clip
NAMES_ON_LINE = 6        # names a gate line / report line shows; the rest are "and k more", the whole list stays in sizing.json
HEAVY_ROWS = 5           # ONE function holding MORE requirements than this is said aloud (a role's downward error is visible)
# What a person may do at the top of the ladder (§3.3). Neither tells the person to break the ticket up: every move offered has an executor.
XXL_ADVICE_FUNCTIONS = ("This is above XL. Your word tests it as one story; or name the functions to leave out, "
                        "and the plan is narrowed to the rest.")
XXL_ADVICE_ROWS = ("This is above XL by the weight of the register's rows; the functions were not named. Your word tests "
                   "it as one story; or say what to leave out, and the plan is narrowed to the rest.")


def clip_name(name) -> str:
    """A function's name as it is SHOWN: whitespace collapsed, at most NAME_SHOWN characters then `...`. Display only."""
    text = " ".join(str(name or "").split())
    return text if len(text) <= NAME_SHOWN else text[:NAME_SHOWN] + "..."


def _function_cells(cells: list, name_at: int, req_at: int) -> tuple:
    return (cells[name_at] if name_at < len(cells) else "", cells[req_at] if req_at < len(cells) else "")


def functions_of(register_text: str, verifiable_rows: list, unverifiable_ids=()) -> dict:
    """The ONE reader of the register's `## Functions` table (AR-13). `{read, functions, unlisted, unknown_ids, notes}`.

    `read` is True when the table names at least one requirement id cell: only then is the unit "functions". `functions` =
    `[{name, requirements}]` for the table's COUNTED functions (a name folded by case and whitespace; a function counts when it
    holds at least one VERIFIABLE register row; two table rows with one folded name are one function). `unlisted` = verifiable
    rows no counted function holds, each of which is one more function (the error direction is upward) - except a row the
    grounding step added after S2 (`origin: S3-grounding`), which is named in `notes` and does not inflate N on an S2 re-run.
    `unknown_ids` = tokens that are no register row (`R-99`, `r-1`, `R-1..R-5`: only a token that FULLY matches the id form is
    an id). `notes` = the reasoning lines. Pure: no write, no raise on any text (a role writes this input)."""
    notes: list = []
    out = {"read": False, "functions": [], "unlisted": [], "unknown_ids": [], "notes": notes}
    heads = [line for line in str(register_text or "").splitlines() if line.strip().startswith(FUNCTIONS_HEADING)]
    if not heads:
        notes.append(f"the register has no '{FUNCTIONS_HEADING}' table - sized by what the requirements weigh, as before "
                     f"(the unit is requirements, not functions)")
        return out
    if len(heads) > 1:
        notes.append(f"the register holds {len(heads)} '{FUNCTIONS_HEADING}' headings - the first is read")
    raw = md_table(register_text, FUNCTIONS_HEADING)
    header = raw[0] if raw else []
    name_at, req_at = _header_index(header, "function", -1), _header_index(header, "requirements", -1)
    if name_at < 0 or req_at < 0 or name_at == req_at:
        missing = " and ".join(label for label, at in (("function", name_at), ("requirements", req_at)) if at < 0) or "distinct function and requirements"
        notes.append(f"the '{FUNCTIONS_HEADING}' table has no {missing} header - sized by what the requirements weigh, as before")
        return out
    verifiable = {str(row.get("r")) for row in verifiable_rows}
    known_unverifiable = {str(r) for r in unverifiable_ids}
    folded: dict = {}                 # folded name -> {name, ids}, in table order
    blank_cells, unreadable, unnamed, unknown = [], [], [], []
    for cells in raw[1:]:
        name, cell = _function_cells(cells, name_at, req_at)
        key, shown = " ".join(str(name).split()).casefold(), clip_name(name) or "(no name)"
        if not cell.strip():
            blank_cells.append((key, shown))
            continue
        out["read"] = True
        for sep in ",;`":
            cell = cell.replace(sep, " ")
        tokens = cell.split()
        ids = [t for t in tokens if REQ_ID_RE.fullmatch(t)]
        unknown += [t for t in tokens if t not in ids or (t not in verifiable and t not in known_unverifiable)]
        if str(name).strip().lower() in _NO_OBSERVABLE_CELLS:
            unnamed += ids               # a row with no name places nothing: its ids stay unlisted
            continue
        entry = folded.setdefault(key, {"name": " ".join(str(name).split()), "ids": []})
        for t in ids:
            if t in verifiable and t not in entry["ids"]:
                entry["ids"].append(t)
        if not any(t in verifiable for t in ids):
            unreadable.append((key, shown, [t for t in ids if t in known_unverifiable]))
    out["unknown_ids"] = sorted(set(unknown), key=lambda t: (len(t), t))
    out["functions"] = [{"name": e["name"], "requirements": e["ids"]} for e in folded.values() if e["ids"]]
    if not out["read"]:
        notes.append(f"the '{FUNCTIONS_HEADING}' table is there and empty (no function lists a requirement) - sized by what the "
                     f"requirements weigh, as before")
        return out
    placed = {r for f in out["functions"] for r in f["requirements"]}
    claimed = {r["r"] for r in behaviour_claims(register_text) if r.get("origin") == CLAIM_ORIGIN_S3}
    after_s2 = [str(row.get("r")) for row in verifiable_rows if str(row.get("r")) not in placed and str(row.get("r")) in claimed]
    out["unlisted"] = [str(row.get("r")) for row in verifiable_rows if str(row.get("r")) not in placed and str(row.get("r")) not in claimed]
    notes.extend(_function_notes({k for k, e in folded.items() if e["ids"]}, placed, blank_cells, unreadable, unnamed,
                                 out["unknown_ids"], after_s2))
    return out


def _function_notes(counted: set, placed: set, blank_cells: list, unreadable: list, unnamed: list, unknown_ids: list,
                    after_s2: list) -> list:
    """The reasoning lines of `functions_of`, built AFTER the folding: a row whose name folds into a COUNTED function is not
    called "not counted", and an id another row placed is not called "not placed" (the words follow the arithmetic)."""
    notes = []
    blank = [shown for key, shown in blank_cells if key not in counted]
    if blank:
        notes.append("function(s) with a blank requirements cell are not counted: " + ", ".join(blank))
    for key, shown, ids in unreadable:
        if key not in counted:
            notes.append(f"function '{shown}' holds no verifiable requirement - not counted"
                         + (f" ({', '.join(ids)} unverifiable)" if ids else ""))
    loose = sorted({t for t in unnamed if t not in placed})
    if loose:
        notes.append("requirements listed on a row with no name are not placed: " + ", ".join(loose))
    if unknown_ids:
        notes.append("not a requirement of this register (not counted): " + ", ".join(unknown_ids))
    if after_s2:
        notes.append("added after S2 by the grounding step, in no function and not counted as one: " + ", ".join(after_s2))
    return notes


def _cited_files(verifiable_rows: list) -> int:
    """U (the plan critic's C-1): distinct files the NON-derived verifiable rows' observables cite. Printed beside N, decides
    nothing: when N is far below U, a role may have named too few functions."""
    files = set()
    for row in verifiable_rows:
        if str(row.get("source", "")).strip().lower() == "derived":
            continue
        head = str(row.get("observable") or "").split(" (")[0].split(" + ")[0].strip()
        candidates, _problem = _observable_ref(head)
        if candidates:
            files.add(candidates[-1][1])
    return len(files)


def _function_reasoning(fx: dict, n: int, size: str, cited: int) -> list:
    """The reasoning lines of a story sized by its functions: what N is made of, that the weight is a different fact, U beside N,
    and a loud note on one function holding many requirements (K17: a downward error of the role is visible, never silent)."""
    lines = [f"size {size} from the function table: {function_words({'size_unit': 'functions', 'function_count': n, 'functions': fx['functions'], 'functions_unlisted': fx['unlisted']})}"
             f" (2 x {n}); what the requirements weigh sets the test ceiling, not the size",
             f"cited_files {cited}: distinct files the non-derived rows' observables cite, beside {n} functions (reported, decides nothing)"]
    if fx["unlisted"]:
        lines.append(f"{len(fx['unlisted'])} requirement(s) in no function, each counted as one more: " + ", ".join(fx["unlisted"]))
    heavy = heavy_words({"size_unit": "functions", "function_count": n, "functions": fx["functions"]})
    return lines + ([heavy] if heavy else [])


def function_words(data) -> str:
    """'5 functions: a, b, c, d, e' for a sizing record in the "functions" unit, else ''. THE sentence of the gate line
    (`gate_brief.sizing_line`) and the report (`report_facts._r_size`) - one writer, so the twins cannot drift (AR-19). A partial
    table never reads as a plain count: `functions_unlisted` rows are said ("k of them requirements nobody placed")."""
    if not isinstance(data, dict) or data.get("size_unit") != "functions":
        return ""
    listed = [clip_name(f.get("name")) for f in data.get("functions") or [] if isinstance(f, dict)]
    unlisted = [str(r) for r in data.get("functions_unlisted") or []]
    names = listed + unlisted
    count = data.get("function_count")
    count = count if isinstance(count, int) and not isinstance(count, bool) else len(names)
    head = f"{count} function" + ("" if count == 1 else "s")
    if unlisted:
        head += f", {len(unlisted)} of them requirements nobody placed"
    if not names:
        return head
    more = len(names) - NAMES_ON_LINE
    return head + ": " + ", ".join(names[:NAMES_ON_LINE]) + (f" and {more} more" if more > 0 else "")


def heavy_words(data) -> str:
    """The note of ONE function holding more than HEAVY_ROWS requirements, else ''."""
    if not isinstance(data, dict) or data.get("size_unit") != "functions" or data.get("function_count") != 1:
        return ""
    funcs = [f for f in data.get("functions") or [] if isinstance(f, dict)]
    held = len(funcs[0].get("requirements") or []) if len(funcs) == 1 else 0
    return f"one function named for {held} requirements (a coarse grain sizes the story low)" if held > HEAVY_ROWS else ""


def defect_words(data) -> str:
    """'a defect ticket: 1 regression case is planned (uncapped, the requirements weigh 32)' when the defect cap applied and the
    uncapped weight is recorded, else '' (an older record has no `computed_budget_uncapped`: its old sentence stands). One ceiling
    for the person: the planned case count; the `cap` of a capped story is only the XS band of `size_for(1)`."""
    if not isinstance(data, dict) or data.get("computed_budget_uncapped") is None:
        return ""
    if not any(isinstance(r, dict) and r.get("name") == "defect-cap" for r in data.get("reducers_applied") or []):
        return ""
    planned = data.get("recommended_budget")
    planned = planned if isinstance(planned, int) and not isinstance(planned, bool) else 1
    return (f"a defect ticket: {planned} regression case{'' if planned == 1 else 's'} is planned "
            f"(uncapped, the requirements weigh {data['computed_budget_uncapped']})")


# --- the steps of `compute` (OH3-23 Q9: private helpers, the output and the order of `reasoning` unchanged) ----------------------

def _register_state(task_root: Path, reasoning: list) -> dict:
    """The parsed register and its two lines. A register that EXISTS but raised on reading has its own line: it is not "no register"."""
    path = task_root / "work" / "requirements-register.md"
    register = parse_register(path)
    if not register["found"]:
        error = _read_error(path)
        if register.get("problem"):
            reasoning.append(f"work/requirements-register.md: {register['problem']} — sizing computed as an empty story")
        elif error:
            reasoning.append(f"work/requirements-register.md could not be read ({error}) — sizing computed as an empty story")
        else:
            reasoning.append("no work/requirements-register.md (or it has no '## Register' "
                             "table) — sizing computed as an empty story")
    if register["found"] and not register["has_impact"]:
        reasoning.append("register has no 'impact' column — every requirement weighted at "
                         "x1.0 (default); add the column to weight by impact class")
    return register


def _config_state(project_root, reasoning: list) -> tuple:
    """(weights, weights_source, (impact_scale, problems, unmapped)): the config read, its state said, the scale through `grammar`."""
    cfg, state, detail = read_config(project_root)
    where = f"qa-factory/config.json under {project_root}"
    tail = "the package's default impact classes and weights apply"
    if not project_root:
        reasoning.append("no project root found above the task (no qa-factory/config.json "
                         "in any ancestor) — config, strategy and the ledger are unavailable")
    elif state == "absent":
        reasoning.append(f"no {where} — {tail}")
    elif state == "unreadable":
        reasoning.append(f"{where} could not be read ({detail}) — {tail}")
    elif state == "not_object":
        reasoning.append(f"{where} is a JSON {detail}, not an object — {tail}")
    elif not cfg:
        reasoning.append(f"{where} is an empty object — {tail}")
    weights, weights_source = resolve_weights(cfg)
    scale = (G.impact_scale(cfg), G.impact_scale_problems(cfg), G.impact_scale_unmapped(cfg))
    scale_line = impact_scale_line(cfg)
    if scale_line:
        reasoning.append(scale_line)
    return weights, weights_source, scale


def _story_signals(task_root: Path, project_root, reasoning: list) -> tuple:
    """(p1_areas, signals, manifest): the strategy's areas, the manifest and the diff signals read from it, with their lines."""
    p1_areas, area_kind, state_lines = strategy_area_state(project_root)
    reasoning.extend(state_lines)
    manifest = _read_json(task_root / "work" / "context-manifest.json", {}) or {}
    if not manifest:
        reasoning.append("no work/context-manifest.json — diff signals (surfaces, "
                         "migration, repo count) are unavailable")
    signals = diff_signals(manifest)
    reasoning.extend(area_without_surface_lines(p1_areas, signals))
    signals = dict(signals, area_state=area_kind)           # carried to compute() for the record; no weight reads it
    if len(signals["repos"]) > 1:
        reasoning.append(f"multi-repo change ({len(signals['repos'])} repos: "
                         f"{', '.join(signals['repos'])}) — noted only, does not raise any "
                         f"weight by itself")
    return p1_areas, signals, manifest


def _weigh_rows(verifiable_rows: list, scale: tuple, weights: dict, p1_areas: list, signals: dict, reasoning: list) -> tuple:
    """(requirements, total_area_words): one weighted entry per verifiable row, the notes of each appended to `reasoning` in row order."""
    impact_scale, impact_problems, impact_unmapped = scale
    requirements = []
    total_area_words = set()
    for row in verifiable_rows:
        classified = classify_requirement(row, impact_scale, weights, p1_areas, impact_problems, impact_unmapped, signals)
        reasoning.extend(classified["notes"])
        weight = classified["weight"]
        priority = classified["priority"]
        signal_label, signal_note = requirement_signal(row, signals)
        escalated_from = escalated_to = None
        if signal_label:
            new_tier, new_weight = _next_tier(weights, weight)
            if new_weight > weight:
                escalated_from, escalated_to = priority, new_tier
                reasoning.append(f"{row.get('r')}: signal {signal_label} raises the weight "
                                 f"tier {priority} -> {new_tier} ({signal_note})")
                priority, weight = new_tier, new_weight
            else:
                signal_label = None  # already at the top tier — nothing to escalate to
        elif signal_note:
            reasoning.append(f"{row.get('r')}: {signal_note}")
        contribution = round(2 * weight, 4)
        if classified["area_match"]:
            total_area_words |= _words(classified["area_match"])
        requirements.append({
            "r": row.get("r"), "impact": row.get("impact") or None, "priority": priority,
            "weight": weight, "area_match": classified["area_match"], "signal": signal_label,
            "escalated_from": escalated_from, "escalated_to": escalated_to,
            "contribution": contribution,
        })
    return requirements, total_area_words


def _apply_reducers(verifiable_rows: list, computed_raw: float, ticket_type, manifest: dict, task_root: Path, reasoning: list) -> tuple:
    """(computed_raw, reducers_applied, uncapped_floor): the whole-story reducers, then the defect-ticket cap (or the line that it was not evaluated)."""
    reducers_applied = []
    if len(verifiable_rows) == 1:
        computed_raw *= REDUCER_SINGLE_CRITERION
        reducers_applied.append({"name": "single-criterion", "factor": REDUCER_SINGLE_CRITERION})
    texts = [row.get("requirement", "") for row in verifiable_rows]
    if texts and all(COPY_RE.search(t) for t in texts):
        computed_raw *= REDUCER_COPY_ONLY
        reducers_applied.append({"name": "copy-or-label-only", "factor": REDUCER_COPY_ONLY})
    elif texts and all(LOG_RE.search(t) for t in texts):
        computed_raw *= REDUCER_LOGGING_ONLY
        reducers_applied.append({"name": "logging-or-metrics-only", "factor": REDUCER_LOGGING_ONLY})

    readiness = _read_json(task_root / "work" / "requirements-readiness.json", {}) or {}
    resolved_ticket_type = (ticket_type or manifest.get("issue_type")
                            or readiness.get("issue_type") or readiness.get("ticket_type") or "")
    is_defect = str(resolved_ticket_type).strip().lower() in {"bug", "defect", "incident"}
    uncapped_floor = None
    if is_defect:
        uncapped = round(computed_raw, 2)
        uncapped_floor = int(math.floor(uncapped))      # the carrier of the number the person reads (`defect_words`)
        computed_raw = 1.0
        note = (f"defect ticket — capped at 1 regression case (uncapped computed budget was "
                f"{uncapped} across {len(verifiable_rows)} verifiable requirements)")
        if len(verifiable_rows) > 3:
            note += ("; that many requirements implicated reads like a feature wearing a "
                     "defect label — say so at gate A rather than silently capping it")
        reducers_applied.append({"name": "defect-cap", "note": note})
        reasoning.append(note)
    elif not resolved_ticket_type:
        reasoning.append("ticket type unknown (no issue_type on the manifest or readiness, "
                         "and none passed in) — the defect-ticket cap was not evaluated")
    return computed_raw, reducers_applied, uncapped_floor


def _precedent_line(ledger_rows: list, precedents: list) -> str:
    if not ledger_rows:
        return RP.rel_text("estimation-ledger.jsonl") + " is absent or empty — no precedent to check against"
    if not precedents:
        return "estimation-ledger.jsonl has records, but none carried a usable forecast size — precedent check skipped"
    return "nearest precedent(s): " + "; ".join(
        f"{p['task']} (budget {p['budget']}, overlap {p['overlap']} words)"
        for p in precedents if p.get("task")) or "none named"


def _split_rows(rows: list) -> tuple:
    """(verifiable_rows, unverifiable): the register's rows split by `is_unverifiable`, each side in row order."""
    verifiable_rows = []
    unverifiable = []
    for row in rows:
        reason = is_unverifiable(row)
        if reason:
            unverifiable.append({"r": row.get("r"), "reason": reason})
        else:
            verifiable_rows.append(row)
    return verifiable_rows, unverifiable


def _ceiling_lines(fx_read: bool, computed_budget: int, cap: int, overage: int, size: str, reasoning: list) -> None:
    """The overage line and the XXL line, appended to `reasoning` in that order (a recommendation, never a block)."""
    if overage:
        reasoning.append(f"computed budget {computed_budget} exceeds the {'test ceiling' if fx_read else size + ' cap'} of "
                         f"{cap} by {overage} — shown, not silently trimmed; a gate-A "
                         f"question, not a block")
    if size == "XXL":
        reasoning.append("size XXL — " + (XXL_ADVICE_FUNCTIONS if fx_read else XXL_ADVICE_ROWS)
                         + " (a recommendation, not a block)")


def compute(task_root: Path,project_root=None, ticket_type: str = None) -> dict:
    """Pure computation — no file writes. `run()` below adds the write."""
    task_root = Path(task_root)
    project_root = Path(project_root) if project_root else project_root_of(task_root)
    reasoning = []
    register = _register_state(task_root, reasoning)
    weights, weights_source, scale = _config_state(project_root, reasoning)
    p1_areas, signals, manifest = _story_signals(task_root, project_root, reasoning)

    verifiable_rows, unverifiable = _split_rows(register["rows"])
    fx = (functions_of(_read_text(task_root / "work" / "requirements-register.md"), verifiable_rows, [u["r"] for u in unverifiable])
          if register["found"] else {"read": False, "functions": [], "unlisted": [], "unknown_ids": [], "notes": []})
    reasoning.extend(fx["notes"])

    requirements, total_area_words = _weigh_rows(verifiable_rows, scale, weights, p1_areas, signals, reasoning)
    for entry in unverifiable:
        reasoning.append(f"{entry['r']}: {entry['reason']} — contributes 0, flagged as a "
                         f"requirements defect for the ticket owner, not a test to invent")
    computed_raw = sum(item["contribution"] for item in requirements)
    computed_raw, reducers_applied, uncapped_floor = _apply_reducers(
        verifiable_rows, computed_raw, ticket_type, manifest, task_root, reasoning)

    computed_budget = int(math.floor(computed_raw))
    band, cap = size_for(computed_budget)          # the weighted budget's band and the test ceiling: today's numbers, own names
    n_functions = len(fx["functions"]) + len(fx["unlisted"])
    size = size_for(2 * n_functions)[0] if fx["read"] else band
    overage = max(0, computed_budget - cap)
    recommended_budget = min(computed_budget, cap)
    cited_files = _cited_files(verifiable_rows)
    if fx["read"]:
        reasoning.extend(_function_reasoning(fx, n_functions, size, cited_files))
    _ceiling_lines(fx["read"], computed_budget, cap, overage, size, reasoning)

    ledger_rows = parse_ledger(project_root)
    precedents = nearest_precedents(ledger_rows, computed_budget, total_area_words)
    reasoning.append(_precedent_line(ledger_rows, precedents))
    result = {
        "schema": 1,
        "task": task_root.name,
        "size": size,
        "size_unit": "functions" if fx["read"] else "requirements",
        "function_count": n_functions if fx["read"] else None,       # None: no table, so no count (FR-41), never 0
        "functions": fx["functions"],
        "functions_unlisted": fx["unlisted"],
        "functions_unknown_ids": fx["unknown_ids"],
        "cited_files": cited_files,
        "cap": cap,
        "computed_budget": computed_budget,
        "computed_budget_raw": round(computed_raw, 4),
        "recommended_budget": recommended_budget,
        "overage": overage,
        "verifiable_count": len(verifiable_rows),
        "unverifiable": unverifiable,
        "requirements": requirements,
        "areas": area_state(p1_areas, signals, signals.get("area_state", "no_root"), register["found"]),
        "reducers_applied": reducers_applied,
        "signals": {"repos": signals["repos"], "surfaces": signals["surfaces"],
                    "surfaces_signal": signals["surfaces_signal"],
                    "migration_signal": signals["migration_signal"],
                    "migration_files": signals["migration_files"]},
        "precedents": {"checked": bool(ledger_rows), "nearest": precedents},
        "config": {"weights": weights, "weights_source": weights_source,
                   "has_impact_column": register["has_impact"]},
        "size_override": None,
        "size_override_reason": None,
        "reasoning": reasoning,
    }
    if uncapped_floor is not None:
        result["computed_budget_uncapped"] = uncapped_floor
    return result


def record_size(pipeline: dict, value, task_root: Path) -> list:
    """Write the story's size into `pipeline.json` and keep the two ends of it.

    `size` alone answered "how big is this story" and nothing else. The dashboard's
    Precedents block asked what was forecast and what it turned out to be, found one field,
    and printed nothing at all (TP1-15045). So the FIRST call is kept as `size_initial`,
    every call becomes `size_final`, and `size_reason` says why the recorded size is not the
    one the formula produced — the role's own objection when `work/sizing.json` carries one,
    otherwise the re-estimation this call performed. Returns one line per field written, for
    the caller to print; the names are `contract.SIZE_KEYS` and the dashboard reads them.
    """
    written = []
    previous = pipeline.get("size")
    pipeline["size"] = value
    written.append(f"size = {json.dumps(value)}")
    if value is None:
        return written
    if not pipeline.get("size_initial"):
        pipeline["size_initial"] = value
        written.append(f"size_initial = {json.dumps(value)}")
    pipeline["size_final"] = value
    written.append(f"size_final = {json.dumps(value)}")
    computed = _read_json(Path(task_root) / "work" / "sizing.json", {}) or {}
    reason = ""
    if previous and previous != value:
        reason = f"re-estimated during the story: {previous} -> {value}"
    elif computed.get("size") and computed["size"] != value:
        reason = (str(computed.get("size_override_reason") or "").strip()
                  or f"recorded {value} where the formula gave {computed['size']}")
    if reason:
        pipeline["size_reason"] = reason
        written.append(f"size_reason = {json.dumps(reason)}")
    return written


def run(task_root: Path, project_root=None, ticket_type: str = None,
        size_override: str = None, size_override_reason: str = None) -> dict:
    """Computes and writes `<task_root>/work/sizing.json`. An existing `size_override` on
    disk is preserved across re-runs unless this call supplies a new one — decision #7: the
    role may object to the computed size with a reason, and that objection must survive S2
    being re-dispatched, not just the first run of this script."""
    task_root = Path(task_root)
    result = compute(task_root, project_root, ticket_type)

    existing_path = task_root / "work" / "sizing.json"
    existing = _read_json(existing_path, {}) or {}
    if size_override is not None:
        result["size_override"] = size_override
        result["size_override_reason"] = size_override_reason
    elif isinstance(existing, dict) and existing.get("size_override"):
        result["size_override"] = existing.get("size_override")
        result["size_override_reason"] = existing.get("size_override_reason")

    # TR3-15: published by replace (the one publisher, `event_store`), never written in place: the gate, the report and `story_step` read
    # this file while another window's exit may be rewriting it. The bytes are the same as before (no trailing newline added).
    from event_store import atomic_text
    atomic_text(existing_path, json.dumps(result, indent=2, ensure_ascii=False))
    return result


# --- selftest ------------------------------------------------------------------------------

def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def selftest() -> int:
    import tempfile
    import shutil
    failures = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    # --- pure helpers, no filesystem ---
    case("tier weights default", DEFAULT_WEIGHTS["P0"], 1.6)
    case("area phrase split", len(parse_p1_areas(
        "**P1 areas.** budgets and spend tracking · skills CRUD.\n\n**P2 areas.** search.")), 2)
    sig_ui = {"surfaces": ["ui"], "observables": [{"kind": "ui", "path": "src/budgets/page.tsx"}]}
    case("area path token inside the row's observable path matches",
         find_area_match({"observable": "diff:src/budgets/page.tsx:3"}, ["spend (budgets/page.tsx)"], sig_ui),
         "spend (budgets/page.tsx)")
    case("a word of the area in the requirement text matches nothing",
         find_area_match({"requirement": "The budgets dashboard must total correctly", "observable": "diff:a.py:1"},
                         ["budgets and spend tracking"], sig_ui), None)
    case("a surface kind word alone matches nothing (B-1)",
         find_area_match({"observable": "diff:src/budgets/page.tsx:3"}, ["ui polish"], sig_ui), None)
    case("prose is no path token: Node.js, e.g",
         area_surface_tokens("Node.js runtime, e.g. billing", sig_ui)[1], [])
    case("a row with an empty observable matches no area",
         find_area_match({"observable": ""}, ["ui polish", "x/y.py"], sig_ui), None)
    case("an area naming no surface says so",
         area_without_surface_lines(["budgets and spend tracking"], sig_ui),
         ["P1 area «budgets and spend tracking» names no surface — no bump"])
    case("copy-only detector", bool(COPY_RE.search("Button label reads Save")), True)
    case("copy-only detector does not fire on a real check",
         bool(COPY_RE.search("Restore is denied for a read-only user")), False)
    weights_default = dict(DEFAULT_WEIGHTS)
    case("next tier up from P2", _next_tier(weights_default, 1.0)[0], "P1")
    case("next tier up from P0 stays P0", _next_tier(weights_default, 1.6)[0], "P0")
    case("size for budget 2", size_for(2), ("XS", 2))
    case("size for budget 29", size_for(29), ("XXL", 28))

    td = Path(tempfile.mkdtemp(prefix="qa-sizing-test-"))
    try:
        project = td / "project"
        task_root = project / "qa-factory" / "artifacts" / "QA-1"
        _write(project / "qa-factory" / "config.json", json.dumps({
            "impact_scale": {
                "data-loss": {"priority": "P0", "severity": "blocker"},
                "blocked-flow": {"priority": "P1", "severity": "major"},
                "degraded": {"priority": "P2", "severity": "minor"},
                "cosmetic": {"priority": "P3", "severity": "minor"},
            }
        }))
        _write(project / "qa-factory" / "strategy" / "test-strategy.md",
               "## Risk and impact scale\n\n**P1 areas.** budgets and spend tracking (c.py) · "
               "authentication and role enforcement.\n\n**P2 areas.** search.\n")

        # A register with no impact column at all -> every requirement x1.0, and it says so.
        _write(task_root / "work" / "requirements-register.md",
               "## Register\n\n"
               "| R | Requirement | source | derived_from | verifiable | ac_ref | observable |\n"
               "|---|---|---|---|---|---|---|\n"
               "| R-1 | Save persists the record | ac | — | yes | AC-1 | diff:a.py:1 |\n"
               "| R-2 | Node border turns amber when modified | ac | — | yes | AC-2 | diff:b.tsx:1 |\n")
        result = compute(task_root, project)
        case("no impact column -> weight 1.0 for both rows",
             [r["weight"] for r in result["requirements"]], [1.0, 1.0])
        case("no impact column is named in reasoning",
             any("no 'impact' column" in line for line in result["reasoning"]), True)
        case("computed budget with two P2 requirements", result["computed_budget"], 4)
        case("size S at budget 4", result["size"], "S")

        # Now with an impact column: P0 row, P3 row, and a P2 row whose text matches a P1 area.
        _write(task_root / "work" / "requirements-register.md",
               "## Register\n\n"
               "| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact |\n"
               "|---|---|---|---|---|---|---|---|\n"
               "| R-1 | Save must not lose the record | ac | — | yes | AC-1 | diff:a.py:1 | data-loss |\n"
               "| R-2 | Node border turns amber when modified | ac | — | yes | AC-2 | diff:b.tsx:1 | cosmetic |\n"
               "| R-3 | Budgets dashboard totals stay correct after edit | ac | — | yes | AC-3 | diff:c.py:1 | degraded |\n"
               "| R-4 | Unclear intent, feels wrong somehow | derived | aspect:x | no | — | none |  |\n")
        result = compute(task_root, project)
        by_r = {r["r"]: r for r in result["requirements"]}
        case("data-loss maps to P0 weight", by_r["R-1"]["weight"], 1.6)
        case("cosmetic maps to P3 weight", by_r["R-2"]["weight"], 0.6)
        case("area match raises the budgets row to P1's weight", by_r["R-3"]["weight"], 1.3)
        case("R-3 area match is named", by_r["R-3"]["area_match"],
             "budgets and spend tracking (c.py)")
        case("R-4 excluded as unverifiable (verifiable:no + observable:none)",
             [u["r"] for u in result["unverifiable"]], ["R-4"])
        case("verifiable count excludes R-4", result["verifiable_count"], 3)
        expected_budget = int((2 * 1.6) + (2 * 0.6) + (2 * 1.3))
        case("computed budget sums the three weighted rows",
             result["computed_budget"], expected_budget)

        # A diff signal: a requirement's own observables cross UI/API, and the story touches
        # 3 distinct surfaces overall -> that one requirement steps up a tier; the others do
        # not, because 4a raises only what is bound to the touched place.
        _write(task_root / "work" / "context-manifest.json", json.dumps({
            "implementations": [{"repo": "backend"}, {"repo": "frontend"}],
            "observables": [
                {"requirement": "AC-3", "kind": "ui", "repo": "frontend", "path": "src/x.tsx"},
                {"requirement": "AC-3", "kind": "api", "repo": "backend", "path": "src/y.py"},
                {"requirement": "AC-1", "kind": "db", "repo": "backend", "path": "src/z.py"},
            ],
        }))
        result = compute(task_root, project)
        by_r = {r["r"]: r for r in result["requirements"]}
        case("surfaces signal escalates the boundary-crossing requirement",
             by_r["R-3"]["escalated_to"], "P0")
        case("a same-surface requirement is not escalated by the surfaces signal",
             by_r["R-1"]["signal"], None)
        case("multi-repo is noted, not applied as a weight change",
             any("multi-repo change (2 repos" in line for line in result["reasoning"]), True)

        # Defect-ticket cap: whatever the weighted sum was, it collapses to 1.
        capped = compute(task_root, project, ticket_type="Bug")
        case("defect ticket caps the budget at 1", capped["computed_budget"], 1)
        case("defect-cap reducer is recorded",
             any(r["name"] == "defect-cap" for r in capped["reducers_applied"]), True)

        # run() writes the file and preserves a size_override across a re-run that does not
        # supply a new one (decision #7).
        written = run(task_root, project, size_override="XL", size_override_reason="two teams")
        case("run() records the override", written["size_override"], "XL")
        again = run(task_root, project)
        case("a later run without a new override keeps the old one",
             again["size_override"], "XL")
        case("sizing.json exists on disk", (task_root / "work" / "sizing.json").is_file(), True)
        on_disk = json.loads((task_root / "work" / "sizing.json").read_text(encoding="utf-8"))
        case("the file on disk matches what run() returned",
             on_disk["size_override"], "XL")

        # Tolerance: nothing present at all still produces a result, not an exception.
        empty_root = td / "empty" / "qa-factory" / "artifacts" / "QA-2"
        empty_root.mkdir(parents=True)
        empty_result = compute(empty_root, None)
        case("an empty task still returns a size", empty_result["size"], "XS")
        case("an empty task says the register is missing",
             any("no work/requirements-register.md" in line
                 for line in empty_result["reasoning"]), True)
    finally:
        shutil.rmtree(td, ignore_errors=True)

    if failures:
        print("SIZING SELFTEST: VIOLATIONS")
        for line in failures:
            print("  - " + line)
        return 1
    print("SIZING SELFTEST: no violations (weights, area match, reducers, diff signals, "
          "defect cap, override persistence, tolerance)")
    return 0


def detector_main() -> int:
    """Zero-argument entry for the S2 exit gate: size the story the gate names and write
    `work/sizing.json`. Fail-open — a story the detector cannot find or size is not blocked
    by the arithmetic that was supposed to help it; the gate brief then shows no size line. A crash is no longer a
    silent 0 (RH1-5, FR-59): `UNREADABLE: ...` and exit 3; the gate reads sizing as an ADVISER (`stages.json`
    `advice`), so the crash is a signal to the person, never a block."""
    import detector_verdict as DV
    try:
        from planning_contract import detector_story
        task_root = detector_story(None, stage_id="S2")
    except Exception as exc:
        print(DV.unreadable_line(f"sizing could not resolve the story it was named ({type(exc).__name__}: {exc})"))
        return DV.EXIT_UNREADABLE
    if task_root is None:
        return 0
    try:
        result = run(Path(task_root))
    except Exception as exc:
        print(DV.unreadable_line(f"sizing could not size {Path(task_root).name} ({type(exc).__name__}: {exc})"))
        return DV.EXIT_UNREADABLE
    print(f"sizing: {Path(task_root).name} size={result.get('size')} cap={result.get('cap')} "
          f"budget={result.get('computed_budget')} overage={result.get('overage')} "
          f"unverifiable={len(result.get('unverifiable') or [])}")
    return 0


def main() -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--task", default=None)           # None is "not given": an empty value is a refusal (CX1-18)
    parser.add_argument("--task-root", dest="task_root", default=None)
    parser.add_argument("--project-root", dest="project_root", default="")
    parser.add_argument("--ticket-type", dest="ticket_type", default=None)
    parser.add_argument("--size-override", dest="size_override", default=None)
    parser.add_argument("--size-override-reason", dest="size_override_reason", default=None)
    parser.add_argument("--selftest", action="store_true")
    args = hooklib.exact_options(parser).parse_args()
    if args.selftest:
        return selftest()

    project_root = Path(args.project_root) if args.project_root else None
    if args.task is None and args.task_root is None:
        return detector_main()                    # the hook's zero-argument entry, as before
    # the story the flags name must EXIST (CX1-18); an explicit --project-root is where a KEY resolves (L-2 F-7)
    task_root = hooklib.story_cli("sizing.py", key=args.task, root=args.task_root, project=project_root)
    result = run(task_root, project_root, args.ticket_type, args.size_override,
                args.size_override_reason)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
