#!/usr/bin/env python3
"""report_facts.py - the facts of `test-report.md`, built ONCE by code, and the blocks that state them.

On TP1-13797 (cmp1) the report said "No product bug is recorded" while BUG-1 lay in the story's
folder, printed "Fact: not recorded" for a size the factory had computed, listed the gate A decision
under "Decided at gate B", and put two items into "Left with you" whose only gap was the factory's own
bookkeeping. Every number in it was typed by a role from its own recount. Now code owns every count and
status the person reads; the scribe owns the prose around them (t-109 F1, B-211).

    report_facts.py --task T            print the rendered blocks (read-only)
    report_facts.py --task T --json     print the facts as JSON, and nothing else (FR-14)
    report_facts.py --task T --write    refresh the blocks of test-report.md; convert a report that has none
    report_facts.py --task T --check    read-only (FR-45): exit 1 with one FR-1 line per problem, else 0

The API the stage exits call: `build(task_root) -> facts`, `render(facts) -> {block: text}`,
`write(task_root) -> {...}`, `check(task_root) -> [problem lines]`.

What the facts stand on (one reader each; a count is never taken from a second source, FR-10):
  requirements and their results   traceability.build (the appendix's own rows)
  bugs                             traceability.story_bug_records -> bug_records.story_bugs
  tests                            work/ledger.json rows + the manifest's critic verdicts
  reasons and their owners         work/ledger.json `reason_records`
  questions                        question_register.load
  gates, overrides, size           pipeline.json, work/sizing.json
  plan rows (priority, risk)       contract.parse_plan, words in references/report-risk-words.json
  checks made by hand              the plan's `manual-agent` rows (contract.parse_plan), the reducer's
                                   `current_manual_checks` (work/run-report.json, finalize_task.py), the
                                   `request.json` a refused `manual_evidence.py prepare` leaves, and the
                                   obligation join of manual_evidence.py (t-250, F10)

`manual_checks_text(task_root)` renders the one block `manual-checks` for the gate B packet (story_run.py), so
the report and that packet read one renderer (FR-10).

A number code cannot compute is an `unknown` entry with its reason, printed in words, never 0 (FR-41).
A block is rendered with sorted ids, no timestamps and LF line endings, so the same facts give the same
bytes (R-S9.3). Nothing in a block is cut except the first-reason sentence (200 characters, on a word
boundary, with an ellipsis).
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bug_records as BR  # noqa: E402  (`reproduction_words`: the one sentence about a bug's step, HF8-16)
import contract as C  # noqa: E402
import detector_verdict as DV  # noqa: E402
import grammar as G  # noqa: E402
import hooklib  # noqa: E402
import profile_contract as PC  # noqa: E402
import question_register as QR  # noqa: E402
import traceability as T  # noqa: E402

FIRST_REASON_LIMIT = 200
ELLIPSIS = "…"
RISK_WORDS_PATH = Path(__file__).resolve().parents[1] / "references" / "report-risk-words.json"
REPORT_NAME = "test-report.md"
HISTORY_REL = ("state", "report-history")
APPROVING = ("approved", "approved_with_fixes")
# Reasons a test that reached no live check still counts as proven (owner decision 30.09, V9).
COUNTED_WITHOUT_CHECK = ("unchanged", "unmeasured")
# A requirement whose rows hold no pass and no bug is listed under "Not proven"; these classes say how.
UNPROVEN_CLASSES = ("unproven", "wait", "deferred")
# A requirement whose `pass` rows hold a green test that `_tests` does not count (HF2-6b): the basis, and the two reasons.
NOT_COUNTED_WORDS = "its test ran green but is not counted as proven: "
NOT_COUNTED_REASON = "the code critic has not approved it, or a live check of it is still owed"
# `traceability._merge_outcomes`' own order of worst-first, reused to name a requirement's state.
WORST_FIRST = {"blocked": 1, "wait": 2, "not run": 3, "unreachable": 4, "deferred": 5, "not planned": 6}
GATE_A_STAGES = ("S0", "S1", "S2", "S3", "S4")
GATE_B_STAGES = ("S8", "S9")
# The order the report's parts stand in (the template's): where a block that is missing is inserted.
SLOTS = (("block", "verdict"), ("line", "Notation:"), ("block", "proven"), ("block", "manual-checks"), ("block", "bugs"),
         ("block", "exploratory"), ("block", "review-gaps"), ("heading", "## Left with you"), ("block", "left-branches"),
         ("block", "left-gate-b"), ("block", "regression"),
         ("block", "open-questions"), ("block", "skipped-by-plan"), ("block", "not-proven"), ("block", "branches-not-proven"),
         ("block", "gate-a"), ("block", "gate-b"), ("heading", "## Factory defects"),
         ("block", "size"), ("block", "where-to-look"), ("heading", "## Appendix"))
# Code-owned sections of a report written before the blocks, by heading prefix (conversion, R-212.1).
LEGACY_SECTIONS = (("## Proven", "proven"), ("## Product bugs", "bugs"), ("## Open questions", "open-questions"),
                   ("## Not proven", "not-proven"), ("## Decided at gate A", "gate-a"),
                   ("## Decided at gate B", "gate-b"), ("## Size", "size"), ("## Where to look", "where-to-look"))
ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+\S")
CHANGED_NOTICE_RE = re.compile(r'^Changed since gate B: the verdict read "(.*)"; it now reads "(.*)"\.$')


# --- small helpers ------------------------------------------------------------------------------

def _words(text) -> str:
    return " ".join(str(text or "").split())


def _plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else many


def _cut(text, limit: int = FIRST_REASON_LIMIT) -> str:
    """The first-reason sentence, at most `limit` characters INCLUDING the ellipsis: a text of exactly
    `limit` is whole, one character more is cut on a word boundary (a single word longer than the room is
    cut where it stands) and ends with the ellipsis. The one truncation the blocks make (spec, section 7)."""
    flat = _words(text)
    if len(flat) <= limit:
        return flat
    room = flat[:limit - 1]
    if not flat[limit - 1].isspace() and " " in room:
        room = room.rsplit(" ", 1)[0]
    return room.rstrip(" ,;:.-") + ELLIPSIS


def _fence(text: str) -> str:
    """A code fence longer than any run of backticks in `text`, so the person's words cannot close it."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _quoted(text) -> str:
    """The words verbatim in a code block (line breaks kept; a marker line inside one is not a marker)."""
    body = str(text or "").replace("\r\n", "\n").strip("\n")
    fence = _fence(body)
    return f"{fence}\n{body}\n{fence}"


def _qa_root(task: Path) -> Path:
    parents = task.resolve().parents
    return parents[1] if len(parents) > 1 else task.parent


def _why(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:160]}"


def _rank(priority) -> int:
    m = re.fullmatch(r"P(\d)", str(priority or "").strip())
    return int(m.group(1)) if m else 9


def _risk_words() -> dict:
    try:
        data = json.loads(RISK_WORDS_PATH.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _person_line(pipeline: dict, token: str) -> str:
    """The first line of the person's recorded words (gate A, gate B, then the stage overrides) that names
    `token` as a word; "" when none does. A presence check (FR-12), never a reading of meaning."""
    gates = pipeline.get("gates") if isinstance(pipeline.get("gates"), dict) else {}
    sources = []
    for key in ("A", "B"):
        record = gates.get(key)
        if isinstance(record, dict):
            sources.append(str(record.get("authorization_source") or ""))
    sources += [str(e.get("decision") or "") for e in C.live_stage_overrides(pipeline)]      # a revoked word is no word (GW1-1)
    for text in sources:
        line = QR._line_with(text, token)
        if line:
            return _words(line)
    return ""


PERSON_WORDS_LIMIT = 120


# The lead of the line that quotes a person's words (t-305 N8 attempt 2, F7): `references/human-text.json`
# `action_lines.quoted_words.prefixes` lists it, and that data is what exempts the backquoted span of such a line from the
# text rules - by the span's POSITION (the same mechanism as an action line's command), never by a phrase.
PERSON_LINE_LEAD = "On a build you confirmed"


def _clean_line(line: str) -> bool:
    """Does the FACTORY's own writing in a finished line obey the report's text rules? The person's quoted span is taken out
    first (`human_text.without_quoted_words`: their words are data, verbatim, and may carry a flag, a snake_case name or a
    path); what is left - the profile, the date, the caveat - must pass the shape rows of `human_text` (kind `report`), the
    validator's forbidden needles (`G.REPORT_FORBIDDEN`) and a bare decision id (`G.REPORT_BARE_DECISION_RE`)."""
    import human_text
    import validate_artifacts as V
    own = human_text.without_quoted_words(line)
    return (not human_text.shape_problems(own, kind="report")
            and not V.report_id_shape_hit(own)
            and not G.REPORT_BARE_DECISION_RE.search(own))


def _shows_clean(text: str) -> bool:
    """May this text of ours or a role's stand in the report as it is? No spelling the validator forbids (`G.REPORT_FORBIDDEN`:
    a `work/` path, a `cv_` / `ti_` hash, ...) and no selector-hash instance id. THE one filter: the reds of the verdict and
    the review-gaps block (function names, the critic's words) both call it, so the report cannot refuse its own text."""
    import validate_artifacts as V
    return not V.report_id_shape_hit(text)


def _shown(text) -> tuple:
    """(the words the report may print, whether some were left out). Text that passes `_shows_clean` stands whole; otherwise the
    words that fail are left out one by one and what is left is printed if it passes as a whole - a needle that spans words
    takes the text with it, never a half of it. Nothing left is `""` with `True`: the caller says so."""
    flat = _words(text)
    if _shows_clean(flat):
        return flat, False
    kept = " ".join(word for word in flat.split() if _shows_clean(word))
    return (kept if _shows_clean(kept) else ""), True


def _person_build_words(words) -> str:
    """The person's words for ONE line, exactly as recorded but for the whitespace: newlines and runs of blanks become single
    spaces (`_words`), and a text over `PERSON_WORDS_LIMIT` characters is cut on a word boundary with a visible ellipsis
    (`_cut`, the limit includes it) - never silently. Nothing else is changed: a quote, a flag, a path stay."""
    return _cut(_words(words), PERSON_WORDS_LIMIT)


def _inline_code(text: str) -> str:
    """`text` as ONE Markdown code span whatever it holds: a run of backquotes longer than any inside it opens and closes
    the span (a space pads a text that starts or ends with one), so the words can neither close their own quotation nor
    leave it. The reader that takes the span out (`human_text.QUOTED_SPAN_RE`) reads the same rule."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _person_build(art: Path, unknown: dict):
    """[{profile, words, at, tested_build, expected}] - the profiles whose CURRENT run block (the last one of the profile that
    carries a `runtime_provenance`, in `run_history.read_run_blocks` order: a reparse block carries none and a later `matched`
    block of the same profile replaces a person's word) holds the build a PERSON confirmed (`profile_contract.person_confirmed`).
    [] when no profile does. A run block that cannot be read may have been that block: then the answer is `unknown` (FR-41),
    never an empty list."""
    try:
        import profile_contract as PC
        import run_history as RH
        blocks, bad = RH.read_run_blocks(art)
        current: dict = {}
        for block in blocks:
            data = block["data"]
            prov = data.get("runtime_provenance")
            if not isinstance(prov, dict):
                continue
            profile = _words(data.get("profile_id") or prov.get("profile_id"))
            if profile:
                current[profile] = prov
        out = []
        for profile, prov in sorted(current.items()):
            if not PC.person_confirmed(prov):
                continue
            said = prov["person_confirmation"]
            out.append({"profile": profile, "words": _words(said.get("words")), "at": str(said.get("at") or "")[:10],
                        "tested_build": _words(prov.get("tested_build")),
                        "expected": _words(prov.get("expected_source_revision")),
                        "kind": _words(said.get("kind")),
                        "accepted_files": [_words(f) for f in prov.get("accepted_files") or [] if _words(f)]})
    except Exception as exc:
        unknown["person_build"] = f"the run blocks could not be read ({_why(exc)})"
        return None
    if bad:
        unknown["person_build"] = (f"{len(bad)} run {_plural(len(bad), 'block', 'blocks')} could not be read, so it is not known "
                                   "whether the tests ran on a build you confirmed")
        return None
    return out


# --- the facts ----------------------------------------------------------------------------------

def build(task_root, project_root=None) -> dict:
    """The one dict every block is rendered from. Pure: it reads, and writes nothing (FR-45). Every
    section is read inside its own guard: a source that cannot be read becomes an `unknown` entry."""
    art = Path(task_root)
    qa = (Path(project_root) / "qa-factory") if project_root else _qa_root(art)
    facts: dict = {"task": art.name, "unknown": {}}
    unknown = facts["unknown"]

    pipeline = _load_pipeline(art, unknown)
    ledger = _load_ledger(art, unknown)
    manifest = C.load_json(C.artifact(art, "automation-manifest.json"))
    plan_rows = C.parse_plan(C.artifact(art, "test-plan.md"))
    try:
        trace = T.build(qa, art)
    except Exception as exc:
        trace = None
        unknown["requirements"] = f"the traceability table could not be built ({_why(exc)})"
    if isinstance(trace, dict):
        _reason_vs_table(art, trace.get("rows"))     # RD1-19: a stderr finding only, the table is never changed
    try:
        case_index = C.case_index(art)
    except Exception as exc:
        case_index = None
        unknown["cases"] = f"the case files could not be read ({_why(exc)})"

    key_of = _key_fn(case_index)
    unconfirmed = _unconfirmed_list(art, manifest, case_index, key_of, unknown)
    facts["bugs"] = _bugs(qa, art, unknown)
    facts["exploratory"] = _exploratory(art, unknown)
    facts["branches"] = _branches(art, unknown)     # before `_requirements`: a branch left with the person keeps its R off `Proven`
    facts["requirements"] = _requirements(art, trace, plan_rows, pipeline, unknown, unconfirmed, key_of,
                                          _remainder_entries(manifest, key_of), _branch_debts(ledger))
    facts["manual"] = _manual_guarded(art, plan_rows, case_index, key_of, unknown)
    if facts["manual"] is not None:
        facts["manual"]["table_rows"] = _manual_table_rows(trace, manifest, key_of)   # RD1-18: what the table reads, per case
        # t-593 F-6: said ONCE per build on stderr (the channel of `_regression`), kept for the block; `render` runs at several sites
        # and only appends these lines, it never prints
        facts["manual"]["vs_table"] = _manual_vs_table(facts)
        for line in facts["manual"]["vs_table"]:
            print(f"report: {line}", file=sys.stderr)
    facts["cases"] = _cases(facts["requirements"], trace, case_index, plan_rows, manifest, unknown, art,
                            unconfirmed, [c for c in (facts["manual"] or {}).get("cases", []) if c["refused"]])
    facts["tests"] = _tests(art, ledger, manifest, facts["requirements"], case_index, unknown)
    facts["reference_runs"] = _reference_runs(art)
    _count_by_tests(facts["requirements"], facts["tests"], manifest, trace)
    facts["changes"] = _changes(art, manifest, case_index, pipeline, facts["tests"], unknown)
    facts["probe_debt"] = _probe_debt(art, qa, manifest, unknown)
    facts["person_build"] = _person_build(art, unknown)
    facts["ledger"] = _ledger_facts(ledger)
    _count_bookkeeping(facts["requirements"], facts["ledger"], trace)
    measure = _sides_measure(art, pipeline, manifest, ledger)     # t-2181 §8 (PC-10): a key only for a story with a sides record
    if measure is not None:
        facts["sides_measure"] = measure
    facts.update(_knowledge_facts(art, qa.parent, pipeline, ledger))
    facts["integrations"] = _integrations(art, unknown)
    facts["owed_rework"] = _owed_rework_gap(art)
    facts["passed_over"] = _passed_over_gap(art)
    facts["regression"] = _regression(art, project_root)
    facts["collect_gaps"] = _collect_gaps(art, unknown)
    facts["quality_not_run"] = _quality_not_run(art, project_root, unknown)
    facts["questions"] = _questions(art, unknown, facts["ledger"])
    facts["delivery"] = _delivery(art)
    facts["gate_a"] = _gate_a(pipeline, facts["requirements"], unknown)
    facts["gate_b"] = _gate_b(pipeline, facts["bugs"], facts["delivery"], C.case_config(art))
    facts["attachments"] = _attachments(art, unknown)
    facts["grounding"] = _grounding(art, unknown)
    facts["size"] = _size(art, pipeline, plan_rows, manifest, case_index, facts)
    facts["where"] = _where(art, pipeline)
    facts["where"]["hook_signals"] = _hook_signals(art, qa, pipeline, unknown)
    # D1-C2 (Q3): a requirement the person called not implemented stands in ONE place, the product reasons (D2-A's ledger key);
    # the report reads that derived key, never the carrier (AR-13). No key -> frozenset(): the requirement stays where it is today
    gap_ids = frozenset(str(g.get("requirement")) for g in (facts["ledger"] or {}).get("product_gaps") or [] if isinstance(g, dict))
    facts["not_proven"] = _not_proven(facts["requirements"], plan_rows, pipeline, _stopped_by_case(facts["ledger"]), gap_ids=gap_ids)
    facts["skipped"] = _skipped_by_plan(facts["requirements"], plan_rows, pipeline, gap_ids=gap_ids)
    facts["over_cap_windows"] = _over_cap_windows(art)
    facts["verdict"] = _verdict(facts)
    return facts


EXPLORATORY_WHAT = "what the run saw but could not settle"
RECORD_UNREADABLE = "the record of findings could not be read"     # a person reads this; the exception goes to stderr (HF8-20)
EXPLORATORY_HEAD = G.REPORT_BLOCK_HEADINGS["exploratory"].removeprefix("## ")
# Why a block of `grammar.REPORT_BLOCKS_WHEN_PRESENT` is taken out of a marked report: its source holds nothing now.
WHEN_PRESENT_WHY = {"exploratory": "the findings register holds no line",
                    "left-branches": "no branch, part of the ticket or file is left with you",
                    "branches-not-proven": "no branch was left out by an answer of yours"}
WHEN_PRESENT_ADDED = {"exploratory": "the findings register holds lines",
                      "left-branches": "a branch, a part of the ticket or a file is left with you",
                      "branches-not-proven": "an answer of yours left a branch out"}


def _unreadable_words(unreadable) -> str:
    """The words a person reads when register lines are damaged: how many, never why. The per-line reasons (`not valid JSON`,
    `id is 'EX-2'`) are machine shapes (HF8-20); they stay in the role channel (`exploratory_findings.py check`)."""
    return f"{len(unreadable)} line(s) of the findings record cannot be read"


def _register(art: Path, unknown: dict):
    """The findings register as `exploratory_findings.read` gives it - `{"lines", "unreadable", "active"}`, `active` the list
    of live lines in file order - or None when there is no file (the story has no register: AC-8). A register that cannot be
    read at all, and every damaged line, is `unknown["exploratory"]`, never "none" (AR-28). Pure. What the role still
    decides: nothing."""
    try:
        import exploratory_findings as EF
        if not EF.register_path(art).is_file():
            return None
        got = EF.read(art)
    except Exception as exc:
        print(f"report_facts: the findings register could not be read ({_why(exc)})", file=sys.stderr)
        unknown["exploratory"] = RECORD_UNREADABLE
        return None
    if got["unreadable"]:
        unknown["exploratory"] = _unreadable_words(got["unreadable"])
    return {"lines": got["lines"], "unreadable": got["unreadable"],
            "active": [line for line in got["lines"] if line.get("_status") == "active"]}


def _probe_count(art: Path):
    """The investigation probes made: the captures `investigation_probe.capture_lines` reads (the ONE reader of
    `captures.jsonl`, with the probe's own damaged-line rule); 0 when no pass exists (the tool may not have run); None
    ("unknown") when the reader is not installed or a capture file cannot be read or counted - never a number that only looks
    right (AR-28)."""
    try:
        import investigation_probe as IP      # looked up now: a story without the probe module has no count, not a wrong one
        return len(IP.capture_lines(art))
    except Exception:
        return None


def _exploratory(art: Path, unknown: dict):
    """`facts["exploratory"]`: None when there is no register; else the register plus `formal` - the executions of the run
    report (`contract.current_instance_results`, None when unknown), the probes made, the findings (active lines that are not
    coverage gaps) and the gaps (active `coverage_gap` lines: what the factory could not check) - the numbers the Proven block's "formal line" sets side by side. The test count is `_r_proven`'s own (AR-13)."""
    got = _register(art, unknown)
    if got is None:
        return None
    executions = None
    report, _problem = _read_object(C.artifact(art, "run-report.json"))
    if report is not None:
        try:
            executions = len(C.current_instance_results(report))
        except Exception:
            executions = None
    gaps = sum(1 for line in got["active"] if line.get("kind") == "coverage_gap")
    got["formal"] = {"executions": executions, "probes": _probe_count(art), "findings": len(got["active"]) - gaps, "gaps": gaps}
    _annotate_cases(art, got["lines"])
    return got


def _annotate_cases(art: Path, lines: list) -> None:
    """`_case` of every line: the case id its `refs` name (the project's own id form), "" when none - for the words of the report
    and the gate B lines; and `_shots`, its pictures counted against the disk (`_exploratory_shots`) - the one count the report's
    words and `screenshot_groups` both read."""
    try:
        cfg = C.case_config(art)
        for line in lines:
            refs = [r for r in (line.get("refs") or []) if isinstance(r, str)]
            line["_case"] = next(iter(C.case_ids(" ".join(refs), cfg=cfg)), "")
    except Exception:
        for line in lines:
            line["_case"] = ""
    for line in lines:
        line["_shots"] = _exploratory_shots(art, line)


def _register_shown(facts: dict) -> bool:
    """The ONE predicate of the exploratory block, the Proven block's formal line and the gate B lines: the register holds
    at least one line, or something in it cannot be read. No file, and a 0-byte file, show nothing (AC-8)."""
    got = facts.get("exploratory")
    return bool((got and got.get("lines")) or "exploratory" in (facts.get("unknown") or {}))


def _collect_gaps(art: Path, unknown: dict) -> dict:
    """`{"paths": [{"path", "head", "profiles", "sources"}]}`: test files or folders (the project's and the story's) the runner could not collect
    (RH1-3), from the story's own `state/collect-gaps.json` through its ONE reader (`collect_gaps.read`; the gate and the
    runner write it, AR-14). One entry per PATH, whichever source and profile named it. No file is no entry and no line - the
    report never says "everything was collected" (AR-23); a file that cannot be read is `unknown["collect_gaps"]` (AR-28)."""
    out: dict = {"paths": []}
    try:
        import collect_gaps as CG
        got = CG.read(art)
    except Exception as exc:
        unknown["collect_gaps"] = f"the record of test files that could not be collected cannot be read ({_why(exc)})"
        return out
    if got["unreadable"]:
        unknown["collect_gaps"] = got["unreadable"]
    by_path: dict = {}
    for row in got["rows"]:
        for gap in row["broken"]:
            entry = by_path.setdefault(gap["path"], {"path": gap["path"], "head": "", "profiles": [], "sources": [],
                                                     "owner": ""})
            entry["head"] = entry["head"] or gap.get("head") or ""
            # the owner by source (F4, AR-27): what gate A found is the project's (the story's tests did not exist yet), an S5
            # row carries the writer's word; a path any row calls the project's stays the project's; no word is no claim
            owner = gap.get("owner") or ("project" if row["source"] == "gate_a" else "")
            if owner == "project" or (owner and not entry["owner"]):
                entry["owner"] = owner
            for key, value in (("profiles", row["profile"]), ("sources", row["source"])):
                if value and value not in entry[key]:
                    entry[key].append(value)
    out["paths"] = [by_path[p] for p in sorted(by_path)]
    return out


def _r_collect_gaps(facts: dict) -> str:
    """`### Test files the run could not collect`: one line per path - the file, its cause when the runner gave one, that
    the tests in it were not run, and the owner BY SOURCE (F4, AR-27): the project's for a file it owns, the story's for a
    test file the story's own S5 request names, "not established" when the record states none. The body is empty
    when nothing was recorded; an unreadable record is an `Unknown` line. Typed rows rendered, nothing composed (FR-47)."""
    head = "### Test files the run could not collect"
    if "collect_gaps" in facts["unknown"]:
        return head + "\n\n" + _unknown_line(facts, "collect_gaps", "which test files could not be collected") + "\n"
    paths = (facts.get("collect_gaps") or {}).get("paths") or []
    if not paths:
        return ""
    out = [head, ""]
    for gap in paths:
        cause = f" ({gap['head']})" if gap.get("head") else ""
        profiles = f" [profile: {', '.join(sorted(gap['profiles']))}]" if gap.get("profiles") else ""
        whose, owner = {"project": ("the project's", "project"),
                        "story": ("the story's own", "the story (its S5 automation)")}.get(
            gap.get("owner") or "", ("a", "not established"))
        out.append(f"- {whose} test file {gap['path']} could not be collected{cause}; tests in it were not run — "
                   f"owner: {owner}{profiles}")
    return "\n".join(out) + "\n"


def _quality_not_run(art: Path, project_root, unknown: dict) -> list:
    """`[{"id", "why"}]`: the project's quality checks the factory did not run (HF4-10, FR-4/FR-59), over every S5 window of
    the story (`work/windows/*.json`), ids once, in order of first appearance. A window's own `quality_not_run` is read as it
    stands; a window of an older build (no such key) is read through the SAME reader that writes it
    (`window_record.demanded_quality_checks`, rule QNR), so it cannot hide a check. A check the readiness step ran
    (`checked_at_s0`) is not here: that is no unrun quality check (FR-41). No window or nothing unrun is `[]` and no line
    (AR-23); a window that cannot be read is `unknown["quality_not_run"]` (AR-28)."""
    out: list = []
    seen: set = set()
    try:
        import window_record as WR
        paths = sorted((art / WR.WINDOW_DIR).glob("*.json"))
    except Exception as exc:
        unknown["quality_not_run"] = f"the windows cannot be listed ({_why(exc)})"
        return out
    for path in paths:
        try:
            window = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(window, dict):
                raise ValueError("the window is not an object")
            rows = window.get("quality_not_run")
            if not isinstance(rows, list):
                rows = WR.demanded_quality_checks(window.get("required_quality_checks"), art, project_root)[1]
        except Exception as exc:
            unknown["quality_not_run"] = f"the window {path.name} cannot be read ({_why(exc)})"
            continue
        for row in rows:
            if not isinstance(row, dict) or "id" not in row:
                continue
            name = str(row["id"])
            if row.get("why") != "checked_at_s0" and name not in seen:
                seen.add(name)
                out.append({"id": name, "why": str(row.get("why") or "")})
    return out


def _r_quality_not_run(facts: dict) -> str:
    """The one line `Quality checks the factory did not run: <id> (<why words>), ...`, or "" when there is nothing to say.
    The words are the data file's (`quality-receipt-producers.json`, FR-13); typed rows rendered, nothing composed (FR-47)."""
    unknown = ("quality_not_run" in facts["unknown"])
    rows = facts.get("quality_not_run") or []
    out = ""
    if rows:
        import window_record as WR
        words = WR.quality_why_words()
        out = "Quality checks the factory did not run: " + ", ".join(
            f"{r['id']} ({words.get(r['why']) or r['why']})" for r in rows) + "\n"
    if unknown:     # the ids known from the readable windows stay printed; the unreadable window is named beside them
        out += _unknown_line(facts, "quality_not_run", "which quality checks the factory did not run") + "\n"
    return out


def _over_cap_windows(art: Path) -> list:
    """`[{"window", "cases", "cap", "surface"}]`: the S5 windows that went over their cap because one test of the plan covers
    their cases (the owner's word: the cap yields, F-J2 (b)), as the controller's cut says it NOW (`stage_scope("S5")`, the one
    cut: `over_cap` and `cap` of each window, so the report names the cap the cut counted by at the time of the report, E-FJ14).
    Empty - and the report has no line - when there is no such window, when the story's S5 is the earlier (`legacy`) form
    (the cut then carries no `window_cut`), or when the cut cannot be read: the report never claims an overload it did not
    establish (E-FJ39, FR-41). Reads; writes nothing."""
    try:
        import controller as CT
        scope = CT.Controller(art).stage_scope("S5")
        if not scope.get("derived") or not isinstance(scope.get("window_cut"), dict):
            return []
        return [{"window": window["index"], "cases": len(window["scope"]), "cap": window["cap"], "surface": window.get("surface")}
                for window in scope.get("windows") or [] if window.get("over_cap")]
    except Exception:
        return []


def _load_pipeline(art: Path, unknown: dict) -> dict:
    path = art / "pipeline.json"
    if not path.is_file():
        unknown["pipeline"] = "the factory's record of the stages was not found, so no gate words, override or size could be read"
        return {}
    data = C.load_json(path)
    if not data:
        unknown["pipeline"] = "the factory's record of the stages cannot be read, so no gate words, override or size could be read"
    return data


def _load_ledger(art: Path, unknown: dict):
    path = C.artifact(art, "ledger.json")
    if not path.is_file():
        unknown["ledger"] = "the factory's record of the checks was not found, so the tests, the open reasons and their owners are not known"
        return None
    data = C.load_json(path)
    if not isinstance(data.get("rows"), list):
        unknown["ledger"] = "the factory's record of the checks cannot be read, so the tests, the open reasons and their owners are not known"
        return None
    return data


def _bugs(qa: Path, art: Path, unknown: dict):
    """The story's bugs from THE one reader (`traceability.story_bug_records` -> `bug_records.story_bugs`)."""
    try:
        found = T.story_bug_records(qa, art)
    except Exception as exc:
        unknown["bugs"] = f"the bug folders could not be read ({_why(exc)})"
        return None
    records = []
    # HF8-16 (K5): a bug's severity is DERIVED from its `impact` by the project's scale (`validate_artifacts`: "derived, not
    # assigned"), so a draft that states `impact` has a severity; the filed `.md` still wins when it writes one. No `impact`,
    # or one outside the scale, leaves "" and the report prints "severity not recorded" (FR-41).
    try:
        scale = G.impact_scale(C.case_config(art))
    except Exception:
        scale = {}
    choice = BR.gate_b_choice(art)
    for record in found.get("records") or []:
        title, severity = record.get("title"), ""
        for raw in record.get("paths") or []:
            if str(raw).lower().endswith(".md"):
                try:
                    import hooklib
                    fm = hooklib.parse_frontmatter(Path(raw).read_bytes().decode("utf-8-sig").replace("\r\n", "\n")) or {}
                except (OSError, UnicodeDecodeError):
                    fm = {}
                title = _words(fm.get("title")) or title
                severity = _words(fm.get("severity"))
                break
        if not severity:
            derived = scale.get(_words(record.get("impact")))
            severity = _words(derived.get("severity")) if isinstance(derived, dict) else ""
        records.append({"id": str(record.get("id") or ""), "title": _words(title), "severity": severity,
                        "state": str(record.get("state") or "unknown"),
                        "confirmation": str(record.get("confirmation") or ""),
                        "reproduced_how": list(record.get("reproduced_how") or []),
                        "reproduction_problems": list(record.get("reproduction_problems") or []),
                        "requirements": sorted(set(record.get("requirements") or []), key=T._numeric_key),
                        "cases": sorted(set(record.get("cases") or []), key=T._numeric_key),
                        "homes": sorted(record.get("homes") or []),
                        # t-2187 (5.9): one bug, many ways it shows - the lines, the cause and the draft stems a possible
                        # same cause is named by; `draft_names` is how a row finds the bug a draft became
                        "manifestations": [_words(m) for m in record.get("manifestations") or []],
                        "cause": dict(record.get("mechanism") or {}),
                        "same_cause_as": [str(s) for s in record.get("possibly_same_cause") or []],
                        "draft_names": [str(s) for s in record.get("draft_names") or []],
                        # HF8-21: where the bug lies and whether the tracker has it (`bug_records.filing_of`, derived by code), and
                        # a FACT of the gate B decision for a draft nobody filed (never a reading of the person's words, FR-12)
                        "filing": BR.filing_of(art, record),
                        "gate_b_not_chosen": BR.not_chosen_at_gate_b(art, record, choice),
                        "gate_b_words": choice["words"]})
    order = {"confirmed": 0, "reproduced": 1, "unconfirmed": 2}
    records.sort(key=lambda r: (order.get(r["state"], 3), T._numeric_key(r["id"])))
    return {"records": records,
            "confirmed": sum(r["state"] == "confirmed" for r in records),
            "reproduced": sum(r["state"] == "reproduced" for r in records),
            "unconfirmed": sum(r["state"] == "unconfirmed" for r in records),
            "unreadable": sum(r["state"] not in order for r in records),
            "outside_home": sorted(str(o.get("id") or "") for o in found.get("outside_home") or []),
            "sources": [{k: v for k, v in s.items() if k in ("home", "exists", "files", "unattributed")}
                        for s in found.get("sources") or []]}


def _classify(results: list, held: bool = False) -> str:
    """The class of a requirement from the results of its rows. `held`: one of its Thens is a row whose
    expected value nobody confirmed (`then_bindings` reason `expectation_unconfirmed`). Such a Then was never
    checked against anything, so a requirement that also holds a `pass` row is NOT "proven by tests" - it waits
    for the person (t-250 B3; before it, one passing Then of two made the whole requirement read proven, and
    the verdict counted it with the proven ones). A `bug` still outranks it: a red check is a fact.

    HF2-5 (5a-K3, A1): a `pass` row beside a row that is `blocked` (a Then behind another check's red: not executed, so
    not proven) waits, and beside a `deferred` row (a Then a person's decision put off) reads `deferred`; both are
    "not proven", never "proven by tests". A `wait` (the held Then) is worse than a `deferred`, and `bug` is above all.
    Every other pair of a `pass` with a non-pass result is unchanged here (HF2-6 reads them: the `wait` and `not run`
    pairs)."""
    if "bug" in results:
        return "bug"
    if "pass" in results:
        if held or "blocked" in results:
            return "wait"
        return "deferred" if "deferred" in results else "proven"
    worst = min(results, key=lambda r: WORST_FIRST.get(r, 9)) if results else ""
    return {"wait": "wait", "deferred": "deferred"}.get(worst, "unproven")


def _key_fn(case_index):
    """case id -> the case_index key that names it (the bare id when it names more than one case or none)."""
    def key_of(case: str) -> str:
        found = case_index.matching(case) if (case and case_index is not None) else []
        return found[0] if len(found) == 1 else str(case)
    return key_of


def _partly_words(entry: dict) -> str:
    """One unconfirmed Then in the words of the verdict: which Then, and what it waits for."""
    then = f"Then {entry['then']}" if entry.get("then") else "a Then"
    if entry.get("remainder"):   # GW1-14: a Then the person took beside the case's green test
        return f"{then} is left with you ({entry['case']})"
    qid = entry.get("question") or ""
    if entry.get("answered"):
        return f"{then} has not run since {qid} was answered ({entry['case']})"
    return f"{then} waits for " + (f"{qid} ({entry['case']})" if qid else f"a question nobody has raised yet ({entry['case']})")


def _held_thens(rows: list, unconfirmed, key_of) -> list:
    """The unconfirmed Thens ({case, then, question, answered, line}) that stand in this requirement's rows:
    a row names its case and the Thens it speaks for, an unconfirmed entry names the same pair. Matched by
    those two fields, never by the wording of a row's basis (FR-12)."""
    pairs = {(e["case"], e["then"]): e for e in unconfirmed or []}
    held = {}
    for row in rows:
        case = key_of(str(row.get("case") or ""))
        for then in row.get("then") or []:
            entry = pairs.get((case, then))
            if entry is not None:
                held[(case, then)] = entry
    return [held[k] for k in sorted(held, key=lambda k: (T._numeric_key(k[0]), k[1]))]


def _remainder_entries(manifest: dict, key_of) -> list:
    """[{case, then, remainder, owner, part}] - the Thens a person took beside a green test (GW1-14), read from the
    contract's ONE list (`contract.then_remainders`) in the case spelling the trace rows use. A Then so held makes its
    requirement `wait`, never `proven`; a manifest with none gives []. Never raises: a report does not crash over it."""
    try:
        return [{"case": key_of(r["case"]), "then": r["then"], "remainder": True, "owner": r["owner"],
                 "part": r["part"]} for r in C.then_remainders(manifest)]
    except Exception:
        return []


BRANCH_REF_WORDS = {"branches": "the branches of this story", "ticket-text": "the ticket text", "test-candidates": "the existing tests",
                    "linked-tickets": "the kept tickets", "attachments-unseen": "the attachments of this story"}


def _branch_ref_words(key) -> str:
    """The words a person reads for the `item_key` of a `source: branches` item (P9: `branches`, `ticket-text`, `test-candidates`
    are machine keys); a `BN-n` or a part id stands as it is."""
    key = str(key or "")
    if key in BRANCH_REF_WORDS:
        return BRANCH_REF_WORDS[key]
    name, _sep, rest = key.partition(":")
    if rest and name == "ticket-text":
        return f"the ticket text of {rest}"
    if rest and name == "attachment":
        return f"the file {rest}"
    return key


def _branches(art: Path, unknown: dict):
    """`{"state", "records", "not_obligation", "left_out"}` of `branch_accounting.account` (the one reader of the branches, AR-13),
    read again here because a debt that is no `left_items` row (`branch_excluded_by_word`, `none`) and the counts of the size lines
    live only in the records. None, with `unknown["branches"]`, when it cannot be read: the report then says so, never "all accounted"."""
    try:
        import branch_accounting as BA
        got = BA.account(art)
    except Exception as exc:
        print(f"report_facts: the branch record could not be read ({_why(exc)})", file=sys.stderr)      # a person reads the words, the cause is for the log (HF8-20)
        unknown["branches"] = "the record of the story's branches could not be read"
        return None
    return {"state": got["state"], "records": got["records"], "not_obligation": got["not_obligation"], "left_out": got["left_out"]}


def _branch_items(ledger) -> list:
    """The ledger's `left_items` that are a debt of a branch, of the ticket text or of a file (`source: branches`) and COUNT."""
    return [i for i in (ledger or {}).get("left_items") or [] if isinstance(i, dict) and i.get("source") == "branches" and i.get("counts")]


def _branch_debts(ledger) -> dict:
    """`{R-n: [words]}` for `_requirements` (`branch_accounting.branch_debts` over the counted items)."""
    import branch_accounting as BA
    return BA.branch_debts(_branch_items(ledger))


def _requirements(art: Path, trace, plan_rows: list, pipeline: dict, unknown: dict, unconfirmed=(), key_of=None,
                  remainders=(), debts=None):
    if trace is None:
        return None
    if not C.artifact(art, "requirements-register.md").is_file():
        unknown["requirements"] = "no requirements register was found, so the requirements are not known"
        return None
    key_of = key_of or _key_fn(None)
    register = T.register_requirements(art)
    by_req: dict = {}
    for row in trace.get("rows") or []:
        by_req.setdefault(row.get("requirement"), []).append(row)
    items = []
    for record in sorted(register, key=lambda r: T._numeric_key(r["id"])):
        rid = record["id"]
        rows = by_req.get(rid, [])
        named = [p for p in plan_rows if rid in (p.get("requirements") or [])]
        plan = min(named, key=lambda p: (_rank(p.get("priority")), T._numeric_key(p.get("ts")))) if named else {}
        bases = list(dict.fromkeys(_words(r.get("basis")) for r in rows if _words(r.get("basis"))))
        held = _held_thens(rows, list(unconfirmed or ()) + list(remainders or ()), key_of)
        results = [r["result"] for r in rows]
        # a branch (or a file) of this requirement left with the person: the requirement is not proven while it stands (F-4b), the
        # same footing as a Then nobody confirmed - else `Proven` would contradict "Left with you" (FR-10)
        owed = [f"{_branch_ref_words(w)} is left with you" for w in (debts or {}).get(rid, [])]
        # "partly proven" is said only when something WAS proven: a requirement with no pass is just waiting.
        partly = ([_partly_words(e) for e in held] + owed) if (held or owed) and "pass" in results and "bug" not in results else []
        items.append({"id": rid, "text": _words(record.get("text")), "class": _classify(results, bool(held) or bool(owed)),
                      "results": sorted({r["result"] for r in rows}), "bases": bases, "partly": partly,
                      "cases": sorted({r["case"] for r in rows if r.get("case")}, key=T._numeric_key),
                      "plan_row": str(plan.get("ts") or ""), "priority": _rank(plan.get("priority")) if plan else 9,
                      "impact": _words(plan.get("impact")), "hypothesis": _words(plan.get("hypothesis"))})
    counts = {name: sum(i["class"] == name for i in items) for name in ("proven", "bug", "unproven", "wait", "deferred")}
    return {"total": len(items), "items": items, "counts": counts,
            "testable": _testable(art)}


def _testable(art: Path):
    try:
        import sizing
        rows = sizing.parse_register(C.artifact(art, "requirements-register.md"))["rows"]
        return sum(not sizing.is_unverifiable(r) for r in rows)
    except Exception:
        return None


def _cases(reqs, trace, case_index, plan_rows: list, manifest: dict, unknown: dict, art=None,
           unconfirmed=None, refused=()):
    """`refused`: the manual-agent cases whose `prepare` was refused (`_manual`); each is left with the person
    too (Decision 9) - nothing else will ever check it - so it joins `to_check` beside the manual-human ones."""
    if trace is None or case_index is None:
        unknown.setdefault("cases", "the cases could not be counted: the traceability table or the case files were not readable")
        return None

    key_of = _key_fn(case_index)
    rows_by_case: dict = {}
    for row in trace.get("rows") or []:
        if row.get("case"):
            rows_by_case.setdefault(key_of(row["case"]), []).append(row["result"])
    partly = sorted((k for k, res in rows_by_case.items() if "pass" in res and any(r != "pass" for r in res)),
                    key=T._numeric_key)
    manual_rows = {str(p.get("ts")) for p in plan_rows if p.get("disposition") == "manual-human"}
    to_check = {k for k, res in rows_by_case.items() if "wait" in res}
    to_check |= {k for k, meta in case_index.items() if str(meta.get("plan_row") or "") in manual_rows}
    to_check |= {key_of(h["case"]) for h in C.handed_tests(manifest, thens=True) if h.get("case")}
    to_check |= {c["case"] for c in refused}
    if unconfirmed is None:
        unconfirmed = _unconfirmed_list(art, manifest, case_index, key_of, unknown) if art is not None else []
    return {"total": len(case_index), "partly": partly, "to_check": sorted(to_check, key=T._numeric_key),
            "unconfirmed": unconfirmed}


def _unconfirmed_list(art, manifest: dict, case_index, key_of, unknown: dict) -> list:
    """`_unconfirmed_thens`, never raising: a report never crashes over this list (P1); it says what it could
    not read (FR-41)."""
    if case_index is None or art is None:
        return []
    try:
        return _unconfirmed_thens(art, manifest, case_index, key_of)
    except Exception as exc:
        unknown["unconfirmed"] = f"the Thens whose expected value nobody confirmed could not be listed ({_why(exc)})"
        return []


def gap_needed_line(what, needed) -> str:
    """`To check: <what>. Needed: <needed>` - the ONE assembly of what a gap in "Left with you" says (HF8-17, E17): what is left
    to check, and the one thing wanted of the person. `left_with_you_line` (a Then nobody confirmed) and `left_gap_line` (every
    other gap: a requirement, a case, a branch, an integration) both call it; nothing else spells these words (AR-19)."""
    return f"To check: {what}. Needed: {needed}"


def left_with_you_line(then_text: str, question: str) -> str:
    """The "Left with you" line of a Then whose expected value nobody confirmed (P20, F7): what to check,
    and the one thing wanted of the person. The report states it in the task's own terms and never as a
    delivery block - nothing was executed against an expectation nobody confirmed."""
    needed = f"your answer to {question}" if question else "a question about it, which nobody has raised yet"
    what = " ".join(str(then_text or "").split()).rstrip(".")  # the clause's own full stop would double the one below
    return gap_needed_line(what, needed)


NO_REF_WORDS = "a check the run does not name"
NO_WHAT_WORDS = "the requirement as written"
NO_NEEDED_WORDS = "not named yet — a factory gap"


def left_gap_line(ref, what, needed, requirements=()) -> str:
    """The ONE form of a gap line in "Left with you" (HF8-17, E17):

        - **<ref>** (<R-n, R-m>) — To check: <what>. Needed: <needed>

    `ref` is an R-n, a case id or a `BN-n` (a branch - `BN`, never `BR`: a `BR-1` is not a requirement id to `REQ_ID_RE`, but the two prefixes stay apart for the reader's eye). One line, no
    path, no code, no attempt id: `what` and `needed` pass `_words` and `_cut` (`FIRST_REASON_LIMIT`: exactly the limit stands
    whole, one character more ends with the ellipsis). The invariant (I7): a gap never disappears and never reads as checked -
    a field that is empty is said in words and the line is still there: no `ref` is `**a check the run does not name**`, no
    `what` is `the requirement as written`, no `needed` is `Needed: not named yet — a factory gap`."""
    name = _cut(_words(ref)) or NO_REF_WORDS
    reqs = [r for r in dict.fromkeys(_words(r) for r in (requirements or ())) if r]
    shown = _cut(_words(what).rstrip(".")) or NO_WHAT_WORDS
    wanted = _cut(_words(needed)) or NO_NEEDED_WORDS
    return f"- **{name}**" + (f" ({', '.join(reqs)})" if reqs else "") + " — " + gap_needed_line(shown, wanted)


def _unconfirmed_thens(art: Path, manifest: dict, case_index, key_of) -> list:
    """[{case, then, question, answered, line}] - one entry per `then_bindings` row whose reason is
    `expectation_unconfirmed`, read from the structured row (a field, never wording, FR-12). `answered`
    says the question has since been answered by a person: the test was written before the answer and
    has not run against it (F19), so no "Needed" line is owed for it and `line` is `""`. A manifest with
    no such row - every story before t-227 - gives `[]`."""
    import ledger as L
    out = []
    questions = None
    for row in manifest.get("then_bindings") or []:
        if not (isinstance(row, dict) and row.get("reason") == L.EXPECTATION_UNCONFIRMED
                and str(row.get("status") or "") != "covered"):
            continue
        if questions is None:
            questions = T.question_rows(art)
        case = key_of(str(row.get("case") or ""))
        qid = str(row.get("question") or "").strip()
        meta = case_index.get(case) if hasattr(case_index, "get") else None
        then = C.then_number(row.get("then"))   # the one reader of a row's `then`: 0 is "a Then the row does not number"
        clauses = T.case_thens(Path(meta["path"])) if isinstance(meta, dict) and meta.get("path") else {}
        asked = questions.get(qid) or {}
        # F3 (t-269): `answered` is the resolver's reading, not the raw status - Q7 answered `b` while its
        # `before` is the designer's `unknown` settles nothing (`contract.before_value_needed`, the test
        # `resolve_then_oracle` itself uses), so the gap stays and its "Needed" line is still owed (FR-41). HF2-6b: and an
        # answer given to an earlier wording of the question (`changed_since_answer`) settles nothing either -
        # `QR.settled` is the one predicate for both.
        answered = asked.get("status") == "answered" and QR.settled(asked)
        out.append({"case": case, "then": then, "question": qid, "answered": answered,
                    "line": "" if answered else left_with_you_line(
                        clauses.get(then) or (f"Then {then}" if then else "a Then the row does not number"), qid)})
    out.sort(key=lambda item: (T._numeric_key(item["case"]), item["then"]))
    return out


# --- checked by hand (t-250 section 4, F10) ----------------------------------------------------------------------

NOT_RECORDED = "not recorded by the requirements"
RESULT_WORDS = {"pass": "passed", "fail": "failed", "inconclusive": "inconclusive (it counts toward nothing)"}
# `current_reason` words the reducer puts on a record it can no longer stand behind (finalize_task.py).
STALE_WORDS = {"invalidated_evidence": "its record no longer stands: the case or its plan changed after it was taken, so "
                                       "it is taken again",
               "ambiguous_attempt_order": "the order of its attempts cannot be told, so no record of it is current"}
NO_THEN = "the case states no Then"


def _read_object(path: Path):
    """(data, problem): `problem` is "" for a JSON object, "missing" when there is no such file, else "unreadable"."""
    if not path.is_file():
        return None, "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):   # UnicodeDecodeError is a ValueError
        return None, "unreadable"
    return (data, "") if isinstance(data, dict) else (None, "unreadable")


CREATED_SHOWN = 5      # how many created user names the report line names; the rest are counted


def created_accounts_line(art: Path) -> str:
    """The line about the users this story's checks made on the stand (`<T>/state/created-accounts.json`, written by
    `manual_capture.py http` - NAMES only): `Users this story created on the stand: a, b, ..., +K more; they are left in
    place.` ("" when none was made). The file is there but cannot be read: said as unknown, never as none (FR-41). The
    users are test data of the stand, owned by the factory (FR-53); cleaning them up is not done here."""
    from manual_capture import UNCONFIRMED, created_names_path      # the ONE path of the file (the store that writes it owns it)
    path = created_names_path(art)
    data, problem = _read_object(path)
    if problem == "missing":
        return ""
    if problem:
        return "Users this story created on the stand: unknown - the record of them cannot be read."
    rows = [r for r in data.get("accounts") or [] if isinstance(r, dict) and r.get("name")]
    # F15: a sign-up that was never confirmed made no user the report may promise; it is counted, and listed by `unconfirmed_accounts_line`
    unconfirmed = list(dict.fromkeys(str(r["name"]) for r in rows if r.get("status") == UNCONFIRMED))
    # a name confirmed by the walker's word, not by the code's proof (`confirmed_by` set and not `code`), carries that word: FR-41, AR-22
    said = {str(r["name"]): " ".join(str(r.get("why") or "no reason recorded").split())
            for r in rows if r.get("confirmed_by") not in (None, "", "code") and r.get("status") != UNCONFIRMED}
    names = [n + (f" (on the walker's word: {said[n]})" if n in said else "")
             for n in dict.fromkeys(str(r["name"]) for r in rows) if n not in unconfirmed]
    k = len(unconfirmed)
    left = f"; {k} sign-up(s) not confirmed" if k else ""
    if not names:
        if not k:
            return ""
        return f"Users this story tried to create on the stand: none was confirmed ({k} sign-up(s) not confirmed)."
    more = f", +{len(names) - CREATED_SHOWN} more" if len(names) > CREATED_SHOWN else ""
    return f"Users this story created on the stand: {', '.join(names[:CREATED_SHOWN])}{more}; they are left in place{left}."


def unconfirmed_accounts_line(art: Path) -> str:
    """The line about accounts the checks could not confirm (TR3-10 A): the users the story made whose sign-up stayed `unconfirmed` (with
    their reason) and the given accounts a walker doubted (`manual_capture.account_doubt_rows`, with its why): `Accounts the checks could not
    confirm (not used to sign in): <name> (created: <why>), the stand's account <handle> (given: <why>), ..., +K more`. "" when there is
    none; a record that cannot be read is said as unknown (FR-41)."""
    from manual_capture import UNCONFIRMED, account_doubt_rows, created_names_path
    data, problem = _read_object(created_names_path(art))
    doubts, doubt_problem = account_doubt_rows(art)
    if problem not in ("", "missing") or doubt_problem:
        return "Accounts the checks could not confirm: unknown - the record of them cannot be read."
    items = []
    for row in (data.get("accounts") or []) if data else []:
        if isinstance(row, dict) and row.get("name") and row.get("status") == UNCONFIRMED:
            items.append(f"{row['name']} (created: {' '.join(str(row.get('reason') or 'no reason recorded').split())})")
    for row in doubts:
        items.append(f"the stand's account {row['handle']} (given: {' '.join(str(row.get('why') or 'no reason recorded').split())})")
    if not items:
        return ""
    more = f", +{len(items) - CREATED_SHOWN} more" if len(items) > CREATED_SHOWN else ""
    return f"Accounts the checks could not confirm (not used to sign in): {', '.join(items[:CREATED_SHOWN])}{more}."


def _export_path(ref: dict) -> str:
    """The public path of an evidence ref: `evidence/<content hash><suffix>` - the rule of
    `manual_evidence.export_records` (the suffix of the captured file when it is one of SAFE_EXPORT_SUFFIXES,
    else `.bin`). Computed here and not exported here: a report writes nothing (FR-45), and the ledger run
    before it copies the files. A test pins this to what `export_records` really writes (FR-37). "" when the
    ref holds no usable hash."""
    import manual_evidence as ME
    digest = str(ref.get("content_hash") or ref.get("sha256") or "")
    if len(digest) != 64:
        return ""
    suffix = "".join(c for c in Path(str(ref.get("path") or "")).suffix.lower() if c.isalnum() or c == ".") or ".bin"
    return f"evidence/{digest}{suffix if suffix in ME.SAFE_EXPORT_SUFFIXES else '.bin'}"


SHOTS_PROVIDED, SHOTS_NONE, SHOTS_NO_COPY = G.SHOTS_PROVIDED, G.SHOTS_NONE, G.SHOTS_NO_COPY    # the words live in grammar (AR-13)


def _manual_shots(art: Path, refs, phase_refs=None) -> dict:
    """What a case's evidence says about screenshots, with no path in the part the report prints (the owner's word
    31.10.2026: screenshots are the person's to confirm the manual cases, never in the repository; the report says
    only provided or not). `refs` = every ref of EVERY record of the case. `taken` = pictures they hold (counted by the
    suffix of the captured file, BEFORE any hash test: a picture whose hash is unusable is taken and has no copy),
    `provided` = those whose exported copy is on disk, `files` = those copies' task-relative paths, for `screenshot_groups`
    (the gate B packet's section and `--screenshots`: the one list "provided" is computed from). `post_image` / `post_other` =
    a picture / any other capture after the action, read from `phase_refs` (the record that speaks, default `refs`;
    the phase word is `grammar.manual_phase_word`)."""
    out: dict = {"taken": 0, "provided": 0, "post_image": False, "post_other": False, "files": []}
    speaking = phase_refs if phase_refs is not None else refs
    for ref in speaking if isinstance(speaking, list) else []:
        if isinstance(ref, dict) and G.manual_phase_word(ref.get("phase")) == "post_action":
            if G.is_image(ref.get("path")):
                out["post_image"] = True
            elif _export_path(ref):
                out["post_other"] = True
    seen: set = set()
    for ref in refs if isinstance(refs, list) else []:
        if not isinstance(ref, dict) or not G.is_image(ref.get("path")):
            continue
        path = _export_path(ref)
        key = path or "source:" + str(ref.get("path"))
        if key in seen:
            continue
        seen.add(key)
        out["taken"] += 1
        if path and (art / path).is_file():
            out["provided"] += 1
            out["files"].append(path)
    return out


def _shots_words(shots: dict) -> str:
    """The one sentence about a checked case's screenshots (`grammar.shots_words`, shared with the ledger and the
    exploratory lines): provided, none taken, or a taken one with no copy on this machine."""
    return G.shots_words(shots["taken"], shots["provided"])


def _then_quote_words(row) -> str:
    """What the runner quoted for the Thens of its verdict (`then_quotes` of a record from HF8-19): `the captured page says:
    <quote>` for a quote of captured text, `the screenshot shows: <quote>` for one it read from a picture; several are
    joined by ` / `. `""` for a record with none (an older one) or an entry that is no quote (`reached: false`)."""
    said, shown = [], []
    for entry in (row.get("then_quotes") if isinstance(row, dict) else None) or []:
        quote = _words(entry.get("quote")) if isinstance(entry, dict) else ""
        if quote:
            (shown if entry.get("kind") == "seen" else said).append(quote)
    return " · ".join(part for part in (
        "the captured page says: " + " / ".join(said) if said else "",
        "the screenshot shows: " + " / ".join(shown) if shown else "") if part)


def _rejudge_words(row) -> str:
    """The sentence a re-judged record carries (`manual_evidence.REJUDGE_SENTENCE`, ONE wording): that the verdict was
    re-read from captures already taken and the check was not run again, with the reason. No attempt number: a person
    never reads one. `""` for a record that was not re-judged."""
    if not isinstance(row, dict) or not row.get("rejudge_of"):
        return ""
    import manual_evidence as ME
    return ME.REJUDGE_SENTENCE.replace("of attempt {attempt}", "taken earlier").format(
        attempt="", reason=_words(row.get("rejudge_reason")) or "no reason was recorded")


def _before_words(change) -> str:
    """The ONE "before" a person is shown (`before_change` of the record): the requirements' claim and where it
    comes from. `source: not_recorded` - or no line at all, a record of the generation before it - is "not
    recorded by the requirements": silence is never a value and never "unchanged" (P20)."""
    if isinstance(change, dict) and change.get("source") == "claim" and _words(change.get("value")) and _words(change.get("ref")):
        value, ref = _words(change["value"]), _words(change["ref"])
        return value if value.lower() == ref.lower() else f"{value} · {ref}"
    return NOT_RECORDED


def _row_valid(row) -> bool:
    """A current record the reducer stands behind: schema 2, its evidence validated against the plan, and not
    marked stale or of an unorderable attempt. Direction of error: anything else is not counted."""
    return (isinstance(row, dict) and row.get("schema_version") == 2 and row.get("evidence_validated") is True
            and not row.get("current_reason"))


def _runner_said(row: dict, raw) -> str:
    """The runner's own result of a record the reducer downgraded (finalize_task.py marks it `inconclusive` when
    the evidence is invalid): the same attempt in `manual_checks[]`, which keeps the record as it was written."""
    for other in raw if isinstance(raw, list) else []:
        if (isinstance(other, dict) and other.get("case") == row.get("case")
                and other.get("attempt_id") == row.get("attempt_id") and other.get("result") in RESULT_WORDS):
            return str(other["result"])
    return ""


def _invalid_words(row: dict, raw) -> str:
    reason = str(row.get("current_reason") or "")
    if reason:
        return STALE_WORDS.get(reason, f"its record no longer stands ({reason})")
    if row.get("evidence_validated") is False:
        errors = [_words(e) for e in row.get("evidence_errors") or [] if _words(e)]
        said = _runner_said(row, raw)
        # EVERY reason the record carries (the runner record's own list, bounded by the checks of one record, so no
        # ceiling); one reason is the same text as before
        return ((f"runner said {said}; " if said else "") + "evidence invalid: "
                + (DV.joined(errors, noun="reason", max_chars=None) if errors else "no reason was recorded"))
    return "its record is of an older form that carries no evidence check"


def _refusal(art: Path, case: str):
    """(reason, door) the refused `prepare` left in `request.json` (`{"refused": {...}}`, C3), else None."""
    import manual_capture as MC
    try:
        data, _problem = _read_object(MC.case_root(art, case) / "request.json")
    except ValueError:   # a case id the evidence folder cannot be named for
        return None
    refused = (data or {}).get("refused")
    if not isinstance(refused, dict):
        return None
    return _words(refused.get("reason")) or "the check could not be prepared", _words(refused.get("door"))


def _stand_blocked_why(folder: Path, attempt: str) -> str:
    """The `env_blocked.json` a capture left in the attempt when the stand's runtime probe was unmatched or failed:
    "the stand could not be verified — <probe line>; <remedy>", the two sentences as the capture recorded them
    (FR-20: the task's own terms; FR-41: the probe line says what was read, never "unknown" turned into a fact). "" when
    the attempt has no such file; a file that cannot be read is named by its attempt, like an unreadable record."""
    path = folder / "env_blocked.json"
    if not path.is_file():
        return ""
    data, problem = _read_object(path)
    if problem:
        return "the record of the stand check cannot be read"
    probe, remedy = _words(data.get("probe_line")), _words(data.get("remedy"))
    return ("the stand could not be verified — " + (probe or "no probe line was recorded")
            + (f"; {remedy}" if remedy else ""))


def _record_file_why(art: Path, case: str) -> str:
    """Why a case with no row in the reduced run report has no record: the stand could not be verified (the latest
    attempt's `env_blocked.json`), nothing was written, the file that was written cannot be read (named by its
    attempt, never by a path under work/), or it was never reduced. The order is the order of what the person can
    act on: a refused `request.json` is judged before this (the caller), then the blocked stand, then the record."""
    import manual_capture as MC
    try:
        root = MC.case_root(art, case)
        names = MC.attempts_of(root)
    except ValueError:
        return "no record was written"
    if names:
        blocked = _stand_blocked_why(root / names[-1], names[-1])
        if blocked:
            return blocked
    if not names or not (root / names[-1] / "record.json").is_file():
        return "no record was written"
    _data, problem = _read_object(root / names[-1] / "record.json")
    if problem:
        return "the record of the check cannot be read"
    return "its record was written, but the run has not been finalized since, so it is not counted"


def _manual(art: Path, plan_rows: list, case_index, key_of, unknown: dict) -> dict:
    """{total, checked, note, cases[]}: one entry per `manual-agent` case of the plan, in plan-row order. `total`
    is m, `checked` is n - the cases with a VALID current record. A case with none says why (`why`); one whose
    `prepare` was refused is also `refused`, and carries the line it adds to "Left with you" (Decision 9)."""
    import manual_evidence as ME
    out: dict = {"total": 0, "checked": 0, "note": "", "cases": []}
    if not art.is_dir():
        out["note"] = f"the story folder {art.name} was not found"
        return out
    if not C.artifact(art, "test-plan.md").is_file():
        out["note"] = "the plan (test-plan.md) was not found"
        return out
    if case_index is None:
        out["note"] = "the case files could not be read"
        return out
    rows = [p for p in plan_rows if p.get("disposition") == "manual-agent"]
    by_row: dict = {}
    for key, meta in case_index.items():
        by_row.setdefault(str(meta.get("plan_row") or ""), []).append(key)
    order: list = []
    for row in rows:
        for key in sorted(by_row.get(str(row.get("ts")), []), key=T._numeric_key):
            if key not in order:
                order.append(key)
    if rows and not order:
        # A manual-agent row no case was written for has nothing to check by hand and nothing to count: the report
        # must not read "no case was planned" over it.
        out["note"] = "the plan's manual rows (" + ", ".join(str(p.get("ts")) for p in rows) + ") have no case written for them"
        return out
    report, report_problem = _read_object(C.artifact(art, "run-report.json"))
    raw = (report or {}).get("manual_checks") or []
    by_case: dict = {}
    for row in (report or {}).get("current_manual_checks") or []:
        if isinstance(row, dict) and row.get("case"):
            by_case.setdefault(key_of(str(row["case"])), []).append(row)
    problem = ""
    plan_obligations: list = []
    if order:
        try:
            from coverage_contract import plan_rows as obligation_rows
            plan_obligations = obligation_rows(art)
        except Exception as exc:   # an unreadable plan file means no obligation can be joined: said, not hidden
            problem = f" (the plan's obligations could not be read: {_why(exc)})"
    for key in order:
        meta = case_index[key]
        clauses = T.case_thens(Path(meta["path"])) if meta.get("path") else {}
        then = " / ".join(clauses[n] for n in sorted(clauses)) or NO_THEN
        try:
            obligations = ME._case_obligation_mapping(art, plan_obligations, key) if not problem else set()
        except Exception:
            obligations = set()
        group = by_case.get(key, [])
        refusal = _refusal(art, key)
        case = {"case": key, "plan_row": str(meta.get("plan_row") or ""), "requirements": list(meta.get("requirements") or []),
                "then": then, "state": "not_checked", "result": "", "before": "", "actual": "", "shots": _manual_shots(art, None), "quotes": "",
                "rejudged": "", "why": "",
                "refused": False, "left_line": ""}
        if group and all(_row_valid(r) for r in group) and obligations:
            first = group[0]
            result = str(first.get("result") or "")
            case.update(state="checked", result=RESULT_WORDS.get(result, result or "unknown"),
                        before=_before_words(first.get("before_change")),
                        actual=_words(first.get("actual")) or "the runner wrote no words",
                        shots=_manual_shots(art, [ref for r in group for ref in r.get("evidence_refs") or []], first.get("evidence_refs")),
                        quotes=_then_quote_words(first), rejudged=_rejudge_words(first))
            out["checked"] += 1
        elif refusal:
            case.update(why=refusal[0] + (f" — {refusal[1]}" if refusal[1] else ""), refused=True,
                        left_line=gap_needed_line(then.rstrip("."), 'the way out named under "Checked by hand" for this case'))
        elif not obligations:
            case["why"] = "no obligation" + problem
        elif group:
            # every record that does not stand says why, not only the first (a case with two invalid attempts showed one
            # reason); one invalid record is the same text as before, equal reasons are said once; the records are
            # told apart by ` | ` because one record's own text holds `; ` (`runner said pass; evidence invalid: a; b`)
            case["why"] = DV.joined(dict.fromkeys(_invalid_words(r, raw) for r in group if not _row_valid(r)),
                                    noun="reason", max_chars=None, sep=" | ")
        elif report_problem == "unreadable":
            case["why"] = "the run's results cannot be read"
        else:
            case["why"] = _record_file_why(art, key)
        out["cases"].append(case)
    out["total"] = len(out["cases"])
    return out


def _manual_guarded(art: Path, plan_rows: list, case_index, key_of, unknown: dict):
    try:
        out = _manual(art, plan_rows, case_index, key_of, unknown)
        line = created_accounts_line(art)      # the users the checks made, a line of the block that lists the checks (HF5-3)
        if line:
            out["created_accounts"] = line
        doubted = unconfirmed_accounts_line(art)      # the accounts the checks could not confirm: the person can fix them (A.2, AR-27)
        if doubted:
            out["unconfirmed_accounts"] = doubted
        return out
    except Exception as exc:   # a report never crashes over this block (P1); it says what it could not read (FR-41)
        unknown["manual"] = f"the checks made by hand could not be listed ({_why(exc)})"
        return None


def _manual_line(c: dict) -> str:
    head = f"- **{c['case']}**" + (f" ({', '.join(c['requirements'])})" if c["requirements"] else "") + f" — \"{c['then']}\""
    if c["state"] != "checked":
        return f"{head} — not checked: {c['why']}"
    # a person reads words: no capture of any kind is named by a path or a link, a screenshot is only said to be provided or not
    # (HF8-20, I5; the owner's word 31.10.2026); the verdict is the runner's, this line never changes it (AR-27, P21)
    shots = c["shots"]
    quotes = c.get("quotes") or ""
    if shots["post_image"]:
        now = c["actual"]
    elif shots["post_other"]:
        now = c["actual"] if quotes else f"the captured page says: {c['actual']}"
    else:
        now = f"{c['actual']} · no capture was taken after the action"
    if quotes:
        now += f" · {quotes}"
    return (f"{head} — before the change: {c['before']} — now: {now} — result: {c['result']}"
            + (f" — {c['rejudged']}" if c.get("rejudged") else "") + f" — {_shots_words(shots)}")


SHOTS_HEAD = ("Screenshots of the manual checks, for you to confirm the cases (they stay on this machine, not in the repository "
              "or the merge request):")


def screenshot_groups(task_root) -> list:
    """THE list of the screenshots a person is given: `[(label, [absolute path, ...])]`, per manual case that was checked and per
    live line of the findings register, in the order of the report. The report's `screenshots: provided` is computed from
    the same counts (`_manual_shots`, `_exploratory_shots`), so a picture is called provided only when it stands in this list.
    The list is whole: a long one is not cut, because a cut would leave a provided picture unlisted. It goes to a person in
    chat and in the gate B packet, never into a delivered file. Raises when the checks cannot be read (the callers say so)."""
    art = Path(task_root).resolve()
    unknown: dict = {}
    got = _manual_of(art, unknown)
    if got is None:
        raise ValueError(unknown.get("manual") or "the checks made by hand could not be read")
    groups: dict = {}
    for c in got.get("cases") or []:
        if c["state"] == "checked" and c["shots"]["files"]:
            groups[f"{c['case']} ({_cut(c['then'], 80)})"] = [str(art / p) for p in c["shots"]["files"]]
    register = _register(art, {})
    lines = (register or {}).get("lines") or []
    _annotate_cases(art, lines)
    for line in lines:
        if line.get("_status") in ("superseded", "withdrawn", "withdraw") or not line["_shots"]["files"]:
            continue       # a struck line prints no pictures in the report, so none is promised for it
        label = "finding " + (line["_case"] or _cut(_plain(line.get("statement")) or "without a statement", 80))
        for p in line["_shots"]["files"]:       # one entry per label, a file once (several findings of one case share it)
            if str(art / p) not in groups.setdefault(label, []):
                groups[label].append(str(art / p))
    return list(groups.items())


def screenshot_section(task_root) -> list:
    """The lines gate B shows for the screenshots (`gate_brief.render_gate_b`): heading, the sentence, one line per case. `[]` when
    there is no picture to give (the section is absent and nothing is promised). A list that cannot be made is said (FR-41)."""
    try:
        groups = screenshot_groups(task_root)
    except Exception as exc:
        return ["## Screenshots of the manual checks", "", f"The screenshots of the manual checks could not be listed ({_why(exc)})."]
    if not groups:
        return []
    return ["## Screenshots of the manual checks", "", SHOTS_HEAD] + [f"- {label}: {', '.join(paths)}" for label, paths in groups]


def screenshots_chat_text(task_root) -> str:
    """What the conductor tells the person in CHAT when they ask for the list again (`--screenshots`; gate B shows it by itself,
    `screenshot_section`): the same list, as absolute paths of the copies. They stay on this machine for the person to confirm the
    cases. No picture: one sentence. Never raises."""
    lines = screenshot_section(task_root)
    if not lines:
        return "No screenshots were provided for the manual checks."
    return "\n".join(lines[2:])


def _manual_of(art: Path, unknown: dict):
    """The prelude of the manual-checks block and of the screenshot list: the plan rows, the case index (unreadable: said in
    `unknown["cases"]`) and `_manual_guarded`. One reader for both (the facts, `unknown["manual"]` when it fails)."""
    plan_rows = C.parse_plan(C.artifact(art, "test-plan.md")) if art.is_dir() else []
    try:
        case_index = C.case_index(art) if art.is_dir() else None
    except Exception as exc:
        case_index = None
        unknown["cases"] = f"the case files could not be read ({_why(exc)})"
    return _manual_guarded(art, plan_rows, case_index, _key_fn(case_index), unknown)


def _manual_table_rows(trace, manifest: dict, key_of) -> dict:
    """{case: [{"result", "held"}]}: what the traceability table reads for each case, with `held` true for a row that is
    a live test's, a found bug's or an `unresolved[]` partition's - rows a manual reading never closes (RD1-18, AR-13: the
    rows are the table's own, not a second parse)."""
    out: dict = {}
    if not isinstance(trace, dict):
        return out
    unresolved = {key_of(str(e.get("case") or "")) for e in T.live_unresolved(manifest or {})}
    for row in trace.get("rows") or []:
        if row.get("case"):
            key = key_of(row["case"])
            held = bool(row.get("tests") or row.get("bug") or row.get("partition") or key in unresolved)
            out.setdefault(key, []).append({"result": row.get("result"), "held": held})
    return out


def _manual_vs_table(facts: dict) -> list:
    """The safety check of RD1-18: a case the manual block counts as PASSED, whose table rows (none of them a live test's,
    a bug's or an `unresolved[]` row's) read something other than `pass`. One line per case, naming both; never a refusal
    (the block and the table are two views of ONE reader, so a line here is a defect to look at, not a gate)."""
    manual = facts.get("manual") or {}
    rows = manual.get("table_rows") or {}
    out = []
    for case in manual.get("cases") or []:
        read = rows.get(case.get("case")) or []
        if case.get("state") != "checked" or case.get("result") != RESULT_WORDS["pass"] or not read:
            continue
        if any(r["held"] for r in read):
            continue
        seen = list(dict.fromkeys(str(r["result"]) for r in read if r["result"] != "pass"))
        if seen:
            out.append(f"The table reads {case['case']} as {' / '.join(seen)}; the check says pass")
    return out


def _reason_vs_table(art, rows) -> list:
    """The safety check of RD1-19: a table row whose basis says "no reason recorded" beside a triage row (bound by the exact
    test name) that HAS a reason by the one reader `contract.triage_reason` - a return to the old, wrong read of the row. One
    `report: ...` line on stderr per such row (the same channel as `_regression`); the table row is never changed and nothing
    is refused (F-2). An unreadable triage file or a row that names no test gives no line: the safe error is "not found"."""
    triage = C.triage_rows(C.load_json(C.artifact(Path(art), "triage.json")) or {})
    by_name: dict = {}
    for row in triage:
        for name in C.row_names(row):
            by_name.setdefault(name, row)
    out = []
    for row in rows or []:
        basis = str(row.get("basis") or "")
        if "triaged" not in basis or "no reason recorded" not in basis:
            continue
        for test in row.get("tests") or []:
            reason = C.triage_reason(by_name.get(str(test.get("instance_id") or "")))
            if reason:
                out.append(f"The table gives no reason for {row.get('case') or row.get('requirement')}; "
                           f"the triage row says: {reason}")
                break
    for line in out:
        print(f"report: {line}", file=sys.stderr)
    return out


def _r_manual_checks(facts: dict) -> str:
    m = facts.get("manual")
    if m is None:
        return "## Checked by hand — unknown\n\n" + _unknown_line(facts, "manual", "which cases were checked by hand") + "\n"
    out = [f"## Checked by hand — {m['checked']} of {m['total']}", ""]
    if not m["cases"]:
        out.append("Nothing to show: " + (m["note"] or "no case was planned for a manual check") + ".")
    out += [_manual_line(c) for c in m["cases"]]
    for line in m.get("vs_table") or []:        # computed and said at `build`; the render only appends
        out += ["", line]
    if m.get("created_accounts"):
        out += ["", m["created_accounts"]]
    if m.get("unconfirmed_accounts"):
        out += ["", m["unconfirmed_accounts"]]
    return "\n".join(out) + "\n"


def manual_checks_text(task_root) -> str:
    """The block `manual-checks` of one story as text (heading and lines, no markers): what the gate B packet
    pastes (story_run.py `gate_text`) and the report holds. Never raises. A missing plan, case folder or story
    folder is the heading with `0 of 0` and one line naming what is missing; a record that cannot be read is a
    case "not checked: unreadable record <file>"; a failure of the renderer itself is `unknown`, in words."""
    try:
        art = Path(task_root)
        unknown: dict = {}
        manual = _manual_of(art, unknown)
        return _r_manual_checks({"manual": manual, "unknown": unknown})
    except Exception as exc:
        return "## Checked by hand — unknown\n\nUnknown which cases were checked by hand — " + _why(exc) + ".\n"


def _ledger_has_marks(ledger) -> bool:
    """t-2277 W3: does this ledger carry `real_or_mock` on any test row? A ledger written before the field existed carries it on none - then no
    line renders a mark (the legacy line, as the report's other generation checks)."""
    return any(isinstance(r, dict) and r.get("kind") == "test" and "real_or_mock" in r for r in (ledger or {}).get("rows") or [])


def _test_mark(row, has_marks: bool, owed: bool) -> str:
    """THE words of where a test's result came from, for ONE ledger test row (AR-13: every renderer of a test line - Proven, the rejected
    tests, the runs left failing - reads them here, from the row `ledger.real_or_mock` wrote; nothing is re-derived). "" on a ledger with no
    marks (legacy). A row on a marked ledger without a reading is `real or mock: not established`, never `real code` (AR-28) - when it
    `owed` one (it has a run: Proven, a run left failing); a test with no run (a rejected one never run) has no result to mark and gets ""."""
    if not has_marks or not isinstance(row, dict):
        return ""
    words = str(row.get("real_or_mock") or "")
    if words:
        return words
    from ledger import REAL_OR_MOCK_UNKNOWN
    return REAL_OR_MOCK_UNKNOWN if (owed or "real_or_mock" not in row) else ""


def _mark_tail(test: dict) -> str:
    """` · <mark>` for a rendered test line, "" when it has none (the one tail every renderer appends)."""
    return f" · {test['real_or_mock']}" if test.get("real_or_mock") else ""


def _tests(art: Path, ledger, manifest: dict, reqs, case_index, unknown: dict):
    """Proven = a green ledger test whose critic verdict approves it and whose proof is reached OR whose
    `proof_reason` is `unchanged` / `unmeasured` (V9). A handed test, and a new, changed or unknown one with
    no live check, is not counted."""
    if ledger is None:
        return None
    import ledger as L
    import proof_level as PL
    entries = T.instances_by_id(manifest)
    cfg = C.case_config(art)
    req_text = {i["id"]: i["text"] for i in (reqs or {}).get("items", [])}
    proven, green_not_counted, unverified = [], 0, 0
    # t-2277 W3: a ledger written before the field existed carries it on no test row - then no mark is rendered (the legacy line, as the
    # report's other generation checks); on a ledger that has it, a row without a reading is NOT established, never `real code` (AR-28)
    has_marks = _ledger_has_marks(ledger)
    for row in ledger.get("rows") or []:
        if not isinstance(row, dict) or row.get("kind") != "test" or row.get("dead"):
            continue
        prefix = C.ledger_state_prefix(row.get("state", ""))
        if prefix == "review_unverified":
            unverified += 1
            continue
        if prefix != "passed_green":
            continue
        entry = entries.get(str(row.get("ref") or ""))
        verdict = L.verdict_of(entry)
        level = row.get("proof_level")
        reason = row["proof_reason"] if "proof_reason" in row else (PL.not_required_why(entry, manifest) if entry else "")
        reached = level not in (None, L.PROOF_NOT_REQUIRED, L.PROOF_UNKNOWN, L.UNVERIFIED)
        if entry is None or verdict not in APPROVING or not (
                reached or (level == L.PROOF_NOT_REQUIRED and reason in COUNTED_WITHOUT_CHECK)):
            green_not_counted += 1
            continue
        cases = sorted(set(C.manifest_test_links(entry, cfg)), key=T._numeric_key)
        areas, requirements = [], set()
        for case in cases:
            meta = case_index.get(case) if case_index is not None else None
            if meta:
                areas.append(str(meta.get("area") or ""))
                requirements.update(meta.get("requirements") or [])
        try:
            critic = PL.review_words(verdict)
        except PL.LevelsUnavailable:
            critic = verdict
        level_words = _words(row.get("proof_words")) or _words(PL.words_for(reason))
        proven.append({"instance": str(row.get("ref") or ""), "file": str(entry.get("file") or ""),
                       "area": next((a for a in areas if a), ""), "cases": cases,
                       "requirements": sorted(requirements, key=T._numeric_key),
                       "texts": {r: req_text.get(r, "") for r in sorted(requirements, key=T._numeric_key)},
                       "critic": critic, "level": level_words, "change": "",
                       "real_or_mock": _test_mark(row, has_marks, owed=True)})
    proven.sort(key=lambda t: (t["area"], t["file"], t["instance"]))
    return {"proven": proven, "count": len(proven), "green_not_counted": green_not_counted,
            "unverified": unverified}


def _reference_runs(art: Path) -> list:
    """t-2277 W1: `[{stand, side, runs}]` of the samples (`work/reference-runs`, `stand_identity.reference_runs`): runs made on a reference
    stand, which never reach the ledger or the delivery verdict. `[]` when there is none. Read-only."""
    import stand_identity as SI
    counted: dict = {}
    seen: set = set()
    for number, block in enumerate(SI.reference_runs(art)):
        # a reparse of a sample re-reads the SAME attempt (same `attempt_id`, `supersedes_block_id`): one run, not two; a block with no
        # attempt id is counted on its own
        attempt = str(block.get("attempt_id") or "") or f"no-attempt-{number}"
        if attempt in seen:
            continue
        seen.add(attempt)
        mark = block.get("reference_run") if isinstance(block.get("reference_run"), dict) else {}
        key = (str(mark.get("stand") or "an unnamed stand"), str(mark.get("side") or ""))
        counted[key] = counted.get(key, 0) + 1
    return [{"stand": stand, "side": side, "runs": n} for (stand, side), n in sorted(counted.items())]


def _reference_lines(facts: dict) -> list:
    """The report's line for the samples: named, counted apart, never among the story's tests (`stand_identity.REFERENCE_RUN_WORDS`)."""
    import stand_identity as SI
    out = []
    for item in facts.get("reference_runs") or []:
        side = f", the `{item['side']}` side" if item["side"] else ""
        out.append(f"{_n(item['runs'], 'run', 'runs')} on the reference stand `{item['stand']}`{side}: {SI.REFERENCE_RUN_WORDS}; "
                   "none of it is counted above or in the verdict.")
    return out


def _handed_words() -> str:
    """The words of a test a person took (`proof_level.handed_words`, the same ones the Proven block uses: FR-10)."""
    import proof_level as PL
    try:
        return PL.handed_words()
    except PL.LevelsUnavailable:
        return "handed to the person"


def _count_by_tests(reqs, tests, manifest, trace) -> None:
    """HF2-6b (RD1-8, F-7): "proven by tests" is said once. `_tests` is the one carrier of which green tests count
    (the critic approved them and their proof is reached or owed nothing); a requirement keeps the class `proven` only
    when every `pass` row of its trace that names tests has a counted one, matched by `contract.instance_id_aliases` -
    otherwise the verdict's "N proven by tests" and "M green tests count as proven" are two numbers for one fact.
    A `pass` row with NO tests (a manual record, D5) is not touched. The requirement then reads:
      - `wait`, with the hand-off words, when every uncounted test is one a person took (`proof_reason` handed): the
        critic has nothing to say about it, so "the critic has not approved it" would be untrue (FR-35; P21);
      - `unproven`, with the critic/probe words, otherwise (the error goes toward not proven, FR-59).
    A ledger that could not be read: the count is UNKNOWN (`None`) and the `proven` items read `unknown`, never
    `proven` and never `unproven` (FR-41). `_classify` is not touched (5a); this runs on its result, in place."""
    if reqs is None:
        return
    counts = reqs["counts"]
    if tests is None:
        counts["proven"] = None
        for item in reqs["items"]:
            if item["class"] == "proven":
                item["class"] = "unknown"
        return
    import proof_level as PL
    manifest = manifest or {}
    entries = T.instances_by_id(manifest)

    def aliases(ref) -> set:
        entry = entries.get(str(ref or ""))
        return (set(C.instance_id_aliases(entry)) | {str(ref)}) if ref else set()

    counted = set().union(*(aliases(t["instance"]) for t in tests["proven"]))
    rows_of: dict = {}
    for row in (trace or {}).get("rows") or []:
        if row.get("result") == "pass" and row.get("tests"):
            rows_of.setdefault(row.get("requirement"), []).append(row)
    for item in reqs["items"]:
        if item["class"] != "proven":
            continue
        loose = []      # the tests of this requirement's `pass` rows that no counted test answers
        for row in rows_of.get(item["id"], []):
            if not any(aliases(test.get("instance_id")) & counted for test in row["tests"]):
                loose += row["tests"]
        if not loose:
            continue
        handed = all(PL.not_required_why(entries.get(str(test.get("instance_id") or "")), manifest) == "handed"
                     for test in loose)
        words = NOT_COUNTED_WORDS + (_handed_words() if handed else NOT_COUNTED_REASON)
        item["bases"] = [words] + [b for b in item["bases"] if b != words]
        item["class"] = "wait" if handed else "unproven"
        counts["proven"] -= 1
        counts[item["class"]] += 1


def _changes(art: Path, manifest: dict, case_index, pipeline: dict, tests, unknown: dict):
    """The expectation changes (t-108, F21) in words, attached to the proven test each belongs to; the
    ones that match no proven test are listed apart. Read-only (the detector and `word_passed_pairs`)."""
    if case_index is None:
        unknown["expectation_changes"] = "the case files could not be read, so no test changed after a red run could be listed"
        return None
    try:
        import run_history as RH
        import s5_precheck as S5
        cases = list(case_index.keys())
        found = RH.expectation_changes(art, cases, manifest)
        # a line is a string; the lines the factory's own tool earned are also listed in `unmeasured_tool` (run_history)
        tooled = {str(w) for w in found.get("unmeasured_tool") or []}
        found["unmeasured"] = [str(w) for w in found.get("unmeasured") or []]
        S5.word_passed_pairs(art, found, cases)     # may add a line of its own: the code below judges the list as it stands after
        if found["unmeasured"]:
            unknown["expectation_changes"] = "; ".join(found["unmeasured"])
            if all(line in tooled for line in found["unmeasured"]):
                unknown["expectation_changes_code"] = "tool"    # the reader is the factory's: not a gap of the product (FR-19)
        try:
            import acceptance as AC
            word = AC.change_word
        except Exception:
            word = lambda *_a, **_k: ""  # noqa: E731
        overrides = [e for e in C.live_stage_overrides(pipeline, ("S5",))
                     if (str(e.get("match") or "").strip() == "*" or "changed-after-red" in str(e.get("match") or "").lower())]
        listed = []
        for pair in found.get("pairs") or []:
            record = pair.get("record") if isinstance(pair.get("record"), dict) else None
            if record:
                verdict = _words(record.get("critic_verdict"))
                said = (word("recorded_and_judged", verdict=verdict) if verdict else word("recorded_not_judged")) \
                    or ("recorded and judged: " + verdict if verdict else "recorded, not judged")
                text = (f"its expectation changed after a red run — {_words(record.get('what_changed')) or 'what changed is not stated'}"
                        f" ({_words(record.get('reason')) or 'no reason stated'}); {said}")
            elif pair.get("passed_by_word"):
                said = word("not_recorded_passed_by_word") or "not recorded, passed by a person's word"
                quoted = _words(overrides[0].get("decision")) if overrides else ""
                text = ("its expectation changed after a red run — " + said + (f': "{quoted}"' if quoted else ""))
            else:
                text = "its expectation changed after a red run — nothing records what was changed or why"
            listed.append({"function": C.function_name(pair.get("function")), "cases": sorted(pair.get("cases") or []),
                           "instances": sorted(pair.get("instance_ids") or []), "text": text})
        listed.sort(key=lambda p: (p["function"], p["text"]))
        attached = set()
        for test in (tests or {}).get("proven", []):
            own = [p for p in listed if test["instance"] in p["instances"]
                   or C.function_name(test["instance"]) == p["function"]]
            if own:
                test["change"] = "; ".join(dict.fromkeys(p["text"] for p in own))
                attached.update(id(p) for p in own)
        return {"pairs": listed, "unattached": [p for p in listed if id(p) not in attached]}
    except Exception as exc:
        unknown["expectation_changes"] = f"the expectation-change measurement failed ({_why(exc)})"
        return None


def _probe_debt(art: Path, qa: Path, manifest: dict, unknown: dict):
    try:
        import probe_debt
        return {"count": len(probe_debt.find(art, manifest, project=qa.parent).get("items") or [])}
    except Exception as exc:
        unknown["probe_debt"] = f"the live checks that were not receipted could not be counted ({_why(exc)})"
        return None


def _ledger_facts(ledger):
    if ledger is None:
        return None
    import check_delivery as CD
    import delivery_verdict as DV
    import ledger as L
    owners = {o: len(r) for o, r in L.reasons_by_owner(ledger).items()}
    lifted = sorted({str(f.get("entity") or "") for f in ledger.get("factory_findings") or []
                     if isinstance(f, dict) and f.get("code") == "OWNER_LIFTED_TO_FACTORY"} - {""}, key=T._numeric_key)
    items = [i for i in ledger.get("left_items") or [] if isinstance(i, dict)]
    # the ledger's own failed rows, in its order (F5): what holds a `no` the report's requirement classes may not show - a
    # red test the manifest still calls green, a failure no bug record names yet. The plan row speaks for its cases
    # (`TS-1`), a test row only when no plan row does.
    # (a stand's `ENV_ISSUE` is the person's answer to its card, held as an item once answered - never named here as a failure)
    # G2: a row a gate's waiver wraps (`waived:failed:APP_BUG`) is still a failure that holds the `no` (the kinds file: L13 keeps a
    # waived bug `red`), so the prefix is stripped before the test. A test row is NEVER named by its `ref` (`ti_<hash>`: a
    # person cannot open it, and the report refuses it): by its case id, else by its selector, else it is no candidate
    # at all and the residual sentence speaks.
    rows = []
    for r in ledger.get("rows") or []:
        state = str(r.get("state") or "") if isinstance(r, dict) else ""
        state = state[len("waived:"):] if state.startswith("waived:") else state
        if state.startswith("failed:") and state != "failed:ENV_ISSUE":
            rows.append((r, state))
    plan_reds = [(r, s) for r, s in rows if r.get("kind") == "plan_row"]
    reds = []
    for r, state in (plan_reds or rows):
        detail = _words(r.get("detail"))
        if r.get("kind") == "plan_row":
            name = str(r.get("ref") or "")
        else:
            cases = C.case_ids(detail)
            selector = detail if detail and _shows_clean(detail) else ""
            name = ", ".join(cases) or selector
            detail = selector if cases and selector and selector not in cases else ""
        if name:
            verdict = state.split(":", 1)[1]
            # RN1-16: whose problem the red is, read from the delivery check's own table (AR-13): the head of a `no` names the
            # product's reds before the factory's. A word the table does not hold is the factory's (E-A4).
            reds.append({"ref": name, "detail": detail if detail != name else "", "verdict": verdict,
                         "owner": CD.triage_verdict_owner(verdict)})
    # t-305 N8 (D9, F11): the word is the ledger's own, read through THE reader; this report never recomputes it. A
    # ledger that says `no`/`after_checks` is quoted as it says it, and what the report's own facts add is a sentence.
    gaps = review_gaps(ledger)
    # RN1-15: the requirements the person said the product does not implement, from the typed part of the ledger's reason records
    # (`check_delivery.product_gap_records`: `requirements` and `words` travel on the record, the sentence is never parsed)
    product_gaps = [{"requirement": str(req), "words": _words(r.get("words"))}
                    for r in ledger.get("reason_records") or []
                    if isinstance(r, dict) and r.get("kind") == "product_gap" and isinstance(r.get("requirements"), list)
                    for req in r["requirements"][:1]]
    return {"ready": bool(ledger.get("delivery_ready")), "word": DV.word_of(ledger), "owners": owners,
            "lifted_cases": lifted, "n_items": DV.count_items(items), "items": items, "reds": reds, "gaps": gaps,
            "product_gaps": product_gaps,
            # the windows whose repair limit was spent and whose tests are still rejected: the head's residual names them
            "limit_windows": len(gaps["windows"]),
            # what the ledger's own reasons are about (the id each one starts with): a requirement a reason names HOLDS the `no`
            "entities": sorted({str(r.get("entity") or "") for r in ledger.get("reason_records") or [] if isinstance(r, dict)} - {""}),
            # the typed part of each reason (owner, entity, the ids it names): what `_count_bookkeeping` reads (HF8-17, M-F). A record
            # written before `refs` existed has no such key and is not used there (a legacy ledger gives no segment)
            # RD1-21: how many of the factory's reasons are a behaviour no test proves (the ledger's own count, `L.factory_coverage_gaps`),
            # and the reasons whose owner no rule established (their details): the verdict block says each in its own words
            "factory_coverage": L.factory_coverage_gaps(ledger),
            "unowned": [_words(r.get("detail")) for r in ledger.get("reason_records") or []
                        if isinstance(r, dict) and r.get("owner_established") is False],
            "records": [{"owner": str(r.get("owner") or ""), "entity": str(r.get("entity") or ""),
                         "code": str(r.get("code") or ""),
                         "refs": [str(x) for x in r["refs"]] if isinstance(r.get("refs"), list) else None,
                         # F-7: the reason is about an EXECUTION OUTCOME (a check that never ran, or the runner's misread red) - the ledger
                         # state the reason quotes, read by the owner classifier's own pattern; that is not the factory's bookkeeping
                         "execution": _execution_outcome(r.get("detail"))}
                        for r in ledger.get("reason_records") or [] if isinstance(r, dict)]}


# --- the measures of a story with a sides record (t-2181 §8, PC-10; FR-51, FR-55, AR-12) --------------------------------------
# Counters only: nothing here judges, and nothing is printed in the report (AR-29). Every counter is read through the reader that owns
# its fact (`contract.story_sides`, `contract.manifest_provisional`, `contract.awaiting`, the ledger's state words, the driver
# journal's `pair_records`); an input that is absent or cannot be read makes that counter `unmeasured: <why>`, never 0 (FR-41).
# The facts key `sides_measure` exists ONLY for a story that has a sides record, so every older story's facts are what they were.
PHASE2_CAUSE = "source_arrived"   # a member of controller.REPAIR_CAUSES, read through controller.repair_cause
PHASE2_PURPOSE = "bind"           # a controller.PURPOSES word: the bind round's dispatches


def _unmeasured(why: str) -> str:
    return f"unmeasured: {why}"


def _provisional_counter(art: Path, manifest: dict):
    """`{settled_matched, total, skipped}` of the manifest's `provisional[]` rows (`contract.manifest_provisional`, the one reader), or
    `unmeasured` when the manifest is absent or cannot be read."""
    path = C.artifact(art, "automation-manifest.json")
    if not path.is_file():
        return _unmeasured("the story has no automation manifest")
    if not manifest:
        return _unmeasured("the automation manifest cannot be read")
    read = C.manifest_provisional(manifest)
    from collections import Counter
    by_status = Counter(str(row.get("status") or "") for row in read["rows"])
    return {"settled_matched": by_status.get("settled_matched", 0), "total": len(read["rows"]),
            "by_status": dict(sorted(by_status.items())), "skipped": len(read["skipped"])}


def _absent(why: str) -> str:
    return f"absent: {why}"


def _conductor_sum(pairs: list) -> dict:
    import math
    return {"dispatches": 0, "cost_usd": round(math.fsum(p["cost"] for p in pairs), 6)}


def _side_cost(pairs: list, ids, why_unknown: dict):
    """`{dispatches, cost_usd}` of the journal pairs whose dispatch is in `ids`, or `unmeasured`: a dispatch the controller names that the
    journal has no pair for, or a pair whose cost is None (unknown, never 0), makes the side unmeasured (FR-41, AR-28)."""
    import math
    chosen = [p for p in pairs if p["dispatch"] in ids]
    missing = sorted(set(ids) - {p["dispatch"] for p in chosen} - {""})
    if missing:
        return _unmeasured(f"the journal has no record of dispatch(es) {', '.join(missing)}")
    unknown = [p for p in chosen if p["cost"] is None]
    if unknown:
        reasons = sorted({why_unknown.get(p["session"], "") for p in unknown} - {""})
        return _unmeasured("the journal marks the cost of a dispatch unknown" + (f" ({'; '.join(reasons)})" if reasons else ""))
    return {"dispatches": len({p["dispatch"] for p in chosen if p["dispatch"]}),
            "cost_usd": round(math.fsum(p["cost"] for p in chosen), 6)}


def _journal_pairs(art: Path) -> tuple:
    """`(state, pairs, why_unknown)`: the ONE reading of the story's driver journal money (FR-24) that the phase costs and the
    first-look cost share. `state` is `none` (no driver journal), `empty` (it names no session) or `ok`; `pairs` are
    `{session, dispatch, cost}` (cost None = unknown, never 0); `why_unknown` maps a session to why its cost is unknown. The journal's money is
    read as `factory_dashboard.journal_records` reads it (the root rule, `driver_journal.root_charged`)."""
    import driver_journal as DJ
    import factory_dashboard as FD
    import retro_numbers as RN
    sessions = RN.journal_sessions(art)
    if sessions is None:
        return "none", [], {}
    if not sessions:
        return "empty", [], {}
    driver = {sid: {"rows": rows} for sid, rows in sessions.items()}
    charged, unknown = DJ.root_charged(driver)
    records_ = FD.journal_records(driver, charged)
    return ("ok", [{"session": r["session"], "dispatch": r["dispatch"], "cost": r["cost"]} for r in records_],
            {sid: why for sid, why in unknown})


def _phase_costs(art: Path) -> dict:
    """`{"phase1", "phase2", "conductor_cost"}`, each `{"dispatches", "cost_usd"}` or `unmeasured: <why>` (one shape, AR-12).
    phase2 = (`absent: <why>` when the story has no phase-2 dispatch or the journal names no session) the journal cost of the controller dispatches whose repair cause is `source_arrived` (`controller.repair_cause`) or
    whose purpose is `bind` (t-2181 section 8). phase1 = the dispatches made BEFORE the first phase-2 dispatch (a lower
    `dispatched_seq`; every dispatch when the story has no phase 2). The conductor's own pairs (dispatch "") are in neither phase:
    `conductor_cost` carries them (P18). A dispatch the journal has no pair for, a pair of unknown cost, an empty journal, or a
    dispatch with no integer `dispatched_seq` makes the affected side `unmeasured` (FR-41). The journal's money is read as
    `factory_dashboard.journal_records` reads it (the root rule, `driver_journal.root_charged`); the median of other stories is
    `stage_compare.py`'s (one metric per comparison)."""
    import controller as CT
    state = hooklib.read_json(art / "state" / "controller.json", {}, kind=dict)
    records = state.get("dispatches")
    if not isinstance(records, dict) or not records:
        why = _unmeasured("the story has no controller record of its dispatches")
        return {"phase1": why, "phase2": why, "conductor_cost": why}
    named = {}   # dispatch id -> its record
    for name, record in records.items():
        if isinstance(record, dict):
            named[str(record.get("id") or name)] = record
    phase2_ids = set()
    for dispatch, record in named.items():
        binding = record.get("request_binding") if isinstance(record.get("request_binding"), dict) else {}
        # `purpose: bind` has no reader function (`controller.s5_part_of` knows only `s5_plan`): read raw, by its one writer's word
        if CT.repair_cause(record) == PHASE2_CAUSE or binding.get("purpose") == PHASE2_PURPOSE:
            phase2_ids.add(dispatch)
    seqs = {d: r.get("dispatched_seq") for d, r in named.items()}
    seq_ok = lambda v: isinstance(v, int) and not isinstance(v, bool)   # noqa: E731
    journal, pairs, why_unknown = _journal_pairs(art)
    if journal == "none":
        why = _unmeasured("the story has no driver journal")
        return {"phase1": why, "phase2": why, "conductor_cost": why}
    if journal == "empty":
        why = _unmeasured("the driver journal names no session")
        return {"phase1": why, "phase2": _absent("the driver journal names no session"), "conductor_cost": why}
    if not phase2_ids:
        phase1_ids = set(named)
    elif all(seq_ok(seqs[d]) for d in named):
        first = min(seqs[d] for d in phase2_ids)
        phase1_ids = {d for d in named if d not in phase2_ids and seqs[d] < first}
    else:
        phase1_ids = None
    out = {"phase2": _side_cost(pairs, phase2_ids, why_unknown) if phase2_ids else _absent("the story has no phase-2 dispatch")}
    out["phase1"] = (_side_cost(pairs, phase1_ids, why_unknown) if phase1_ids is not None
                     else _unmeasured("a dispatch has no sequence"))
    conductor = [p for p in pairs if p["dispatch"] == ""]
    out["conductor_cost"] = (_unmeasured("the journal marks the cost of the conductor unknown")
                             if any(p["cost"] is None for p in conductor) else _conductor_sum(conductor))
    return out


def _delivery_counters(ledger) -> dict:
    """`on_substitute` and `sides_unknown` plan rows of the ledger (its own state words, `ledger.ON_SUBSTITUTE_STATE`,
    `ledger.SIDES_UNKNOWN_STATE`), the ledger's verdict word, and `unmeasured` for each when the ledger is absent."""
    import delivery_verdict as DV
    import ledger as L
    if ledger is None:
        why = _unmeasured("the story has no readable ledger")
        return {"on_substitute_count": why, "sides_unknown_count": why, "verdict": why}
    counts = _plan_row_counts(ledger, (L.ON_SUBSTITUTE_STATE, L.SIDES_UNKNOWN_STATE))
    return {"on_substitute_count": counts[L.ON_SUBSTITUTE_STATE], "sides_unknown_count": counts[L.SIDES_UNKNOWN_STATE],
            "verdict": str(DV.word_of(ledger))}


def _plan_row_counts(ledger, states) -> dict:
    """`{state word: how many plan rows of the ledger stand in it}` - the ONE count of plan rows by state (the delivery counters and the
    first-look `placeholder_open` share it). The caller handles an absent ledger."""
    rows = [r for r in (ledger or {}).get("rows") or [] if isinstance(r, dict) and r.get("kind") == "plan_row"]
    return {state: sum(1 for r in rows if r.get("state") == state) for state in states}


def _sides_measure(art: Path, pipeline: dict, manifest: dict, ledger):
    """The §8 counters of a story that has a sides record, or None for a story that has none (a `pipeline.sides` record, a hold in
    `pipeline.awaiting`, `pipeline.sides_unknown` or provisional rows in the manifest): its facts carry no such key at all.

    `non_real_sides` and `verdict` feed the calibration check (a non-real side whose report says `yes`); `awaiting` is the hold read
    through `contract.awaiting`. `test_body_edits_at_bind` and `green_after_bind_only` have no producer in the factory today (no record
    of the bind round's edits outside the marked homes, no per-test arrival moment): they read `unmeasured` until one exists."""
    pipeline = pipeline if isinstance(pipeline, dict) else {}
    provisional = _provisional_counter(art, manifest)
    hold = C.awaiting(pipeline)
    sides = C.story_sides(pipeline)
    # a recorded side is one `story_sides` did not take from the default table (its `source` word); `sides_unknown` has no reader yet
    recorded = any(s["source"] != "default" for s in sides.values()) or hold["state"] != "none" \
        or bool(pipeline.get("sides_unknown")) or (isinstance(provisional, dict) and provisional["total"] > 0)
    if not recorded:
        return None
    costs = _phase_costs(art)
    delivered = _delivery_counters(ledger)
    return {"provisional": provisional,
            "test_body_edits_at_bind": _unmeasured("no record of the bind round's edits outside the marked homes is kept"),
            "phase2_cost": costs["phase2"], "phase1_cost": costs["phase1"],
            "conductor_cost": costs["conductor_cost"],
            "green_after_bind_only": _unmeasured("no per-test record of the moment the implementation arrived is kept"),
            "on_substitute_count": delivered["on_substitute_count"], "sides_unknown_count": delivered["sides_unknown_count"],
            "verdict": delivered["verdict"],
            "non_real_sides": (sorted(name for name, side in sides.items() if side["reality"] != "real") if sides
                               else _unmeasured("the side-realities table cannot be read")),
            "sides_unknown": bool(pipeline.get("sides_unknown")),
            "awaiting": {"state": hold["state"], "since": str(hold.get("since") or "")}}


# --- the price and the USE of the first look and of the registry (t-2277 FL-8; FR-24, FR-41, AR-12, AR-13, AR-28, AR-29) ---------------
# Counters only. Nothing here refuses, blocks or judges whether a fact was USED WELL: it counts whether it reached a brief and whether
# its string stands in a test home / a case / the strategist's form - a comparison of strings, never a reading of meaning (AR-29). An
# input with no carrier is `unmeasured: <why>`, never 0 (FR-41, AR-28). The ONE reader of the usage is `knowledge_use`; the facts, the
# retro table and the finding lines read its return and count nothing a second time (AR-13).
KNOWLEDGE_MARK_RE = re.compile(r"\[knowledge:([A-Za-z0-9_.]+)\]")      # brief_pack.SIDE_KNOWLEDGE_MARK / S3_ROSTER_MARK (briefs). gate_preflight.ACCOUNT_MARK is NOT in a brief
FIRST_LOOK_MARK_RE = re.compile(r"\[first-look:(R-\d+)\]")             # brief_pack.FIRST_LOOK_MARK
FIRST_LOOK_CITE_RE = re.compile(r"first_look:(R-\d+)")                 # a case step's citation of the walked path (contract.FIRST_LOOK_REF_RE)
BRIEFS_PARTS = ("work", "briefs")                                      # brief_pack writes `<dispatch id>.md` here
BRIEF_ID_RE = re.compile(r"^S\d+-(?P<role>.+?)-\d+$")                  # a MAIN brief; its side files (-decisions, -digests, -files) end otherwise
BRIEFS_NOT_KEPT = "briefs are not kept"
# Step 0 of FL-8 (J-16, J-17): the critics' findings carry a `failure_class` of spec|capability|data|tooling and no class word
# `invented_not_asked`, and an answer's scope is not a field of the registry row - so both counter-metrics have no carrier.
NO_INVENTED_CLASS = "the critics' findings carry no class `invented_not_asked`, so none can be counted"
NO_ANSWER_SCOPE = "answer scope is not recorded"
SIDE_KEYS_OF_REGISTRY = ("product.sides", "environments.sides", "environments.reference_for")
NO_S5_PROBE_CARRIER = "no S5 automator probe record keeps the probe's selector (queued: a carrier written by the S5 probe step)"
NO_ACCOUNT_REACH = "the account mark lives in the gate-A rehearsal note, which the story does not keep, and a brief never carries it"
NO_START = "the story records no start time, so whether it already knew this fact is not established"
NO_ROW_TIME = "the registry row records no readable time, so whether the story already knew it is not established"
NO_DRIVER_STATE = "the story has no driver state (a conductor-run story), so whether gate A asked again is not recorded"


def _first_look_present(art: Path) -> bool:
    import first_look as FL
    return art.joinpath(*FL.RECORD_PARTS).exists() or art.joinpath(*FL.ATTEMPT_PARTS).exists()


def _registry_present(root: Path) -> bool:
    import project_knowledge as PK
    return PK.record_path(root).exists()


def _briefs_read(art: Path):
    """`(briefs, why)`: `[{dispatch, role, knowledge: set of registry keys, first_look: set of R-n}]` of the MAIN briefs of the story's
    dispatches (`work/briefs/<dispatch id>.md`, the marker tokens are data for counting), or `(None, why)` when there is none or one cannot be
    read: `briefs are not kept` is the answer of a story whose briefs are not on disk (FR-41). The role is the controller record's own
    `role` for that dispatch id, else read from the id."""
    folder = art.joinpath(*BRIEFS_PARTS)
    if not folder.is_dir():
        return None, BRIEFS_NOT_KEPT
    state = hooklib.read_json(art / "state" / "controller.json", {}, kind=dict)
    records = state.get("dispatches") if isinstance(state.get("dispatches"), dict) else {}
    roles = {str(r.get("id") or n): str(r.get("role") or "") for n, r in records.items() if isinstance(r, dict)}
    out = []
    try:
        for path in sorted(folder.glob("*.md")):
            found = BRIEF_ID_RE.match(path.stem)
            if not found:
                continue
            text = path.read_text(encoding="utf-8-sig")
            marked = [(keys, line) for line in text.splitlines()
                      if (keys := {_key_of_mark(t) for t in KNOWLEDGE_MARK_RE.findall(line)})]
            out.append({"dispatch": path.stem, "role": roles.get(path.stem) or found.group("role"),
                        "knowledge": set().union(*[k for k, _ in marked]), "lines": marked,
                        "first_look": set(FIRST_LOOK_MARK_RE.findall(text))})
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"a brief cannot be read ({type(exc).__name__})"
    return (out, "") if out else (None, BRIEFS_NOT_KEPT)


def _key_of_mark(token: str) -> str:
    """The registry key a marker token names - the ONE normalisation of a marker against the registry's own key names: a token that is a
    key is itself; one that is the key without its scope word (`credentials_by_role` for `environments.credentials_by_role`) is that key,
    when exactly one key ends so; anything else is returned unchanged (it will match nothing)."""
    import project_knowledge as PK
    if token in PK.KEYS:
        return token
    named = [k for k in PK.KEYS if k.split(".", 1)[-1] == token]
    return named[0] if len(named) == 1 else token


def _line_forms(key: str, line: str) -> set:
    """The element names a brief line names, each in the key's own form: a line of the shape `- <name>[: <body>] [knowledge:<key>]`
    (the roster and side lines of `brief_pack`). A line that is no list item names no element. A name holding `: ` with a body is read as
    its head only - a known limit: such an element reads as not reached."""
    import project_knowledge as PK
    head = line.strip()
    if not head.startswith("- "):
        return set()
    head = head[2:]
    return {PK._form(key, c) for c in {head.split(" [knowledge:", 1)[0], head.split(": ", 1)[0]}}


def _reached_by_element(briefs, why: str, key: str, element: str):
    """The roles whose brief names THIS element with the marker of `key` on the same line (sorted, once each; [] is measured: no brief
    did), or `unmeasured`. The roster is capped and its empty-roster line carries the marker too, so the key alone proves nothing of an
    element (rule 15). A name `brief_pack` clipped to 60 characters is compared by its clipped form too."""
    if briefs is None:
        return _unmeasured(why)
    import brief_pack
    import project_knowledge as PK
    forms = {PK._form(key, element), PK._form(key, brief_pack._clip(element, 60))}
    return sorted({b["role"] for b in briefs for keys, line in b["lines"] if key in keys and forms & _line_forms(key, line)})


def _reached_by_request(briefs, why: str, req: str):
    """The roles whose brief carries `[first-look:R-n]` of this requirement (sorted, once each; [] is measured), or `unmeasured`."""
    if briefs is None:
        return _unmeasured(why)
    return sorted({b["role"] for b in briefs if req in b["first_look"]})


def _home_texts(art: Path, root: Path, manifest: dict):
    """`(texts, why)`: the text of every S5 test file (`tests[].file`) and every placeholder home (`provisional[].home.file`) of the manifest,
    read inside the project; `(None, why)` when the manifest names none or one cannot be read - the count is then `unmeasured`, never a
    smaller number."""
    names = {str(t.get("file") or "").strip() for t in C.manifest_tests(manifest)}
    for row in C.manifest_provisional(manifest)["rows"]:
        home = row.get("home") if isinstance(row.get("home"), dict) else {}
        names.add(str(home.get("file") or "").strip())
    names.discard("")
    if not names:
        return None, "the automation manifest names no S5 test file or placeholder home"
    texts = []
    for name in sorted(names):
        try:
            path = (root / name).resolve()
            if Path(name).is_absolute() or not path.is_relative_to(root.resolve()):
                return None, f"{name} is not a path inside the project"
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            return None, f"{name} cannot be read ({type(exc).__name__})"
    return texts, ""


def _cases_citing(art: Path):
    """`({R-n: [case keys]}, "")` - the S4 cases whose text cites `first_look:R-n` (`contract.case_index`, the one reader of the case files) - or
    `(None, why)`."""
    try:
        index = C.case_index(art)
        if not len(index):
            return None, "the story has no case file"
        cites: dict = {}
        for key, meta in index.items():
            text = Path(meta["path"]).read_text(encoding="utf-8-sig")
            for req in set(FIRST_LOOK_CITE_RE.findall(text)):
                cites.setdefault(req, []).append(str(key))
        return {k: sorted(v) for k, v in cites.items()}, ""
    except Exception as exc:       # noqa: BLE001 - a count never crashes the report
        return None, f"the case files could not be read ({_why(exc)})"


def _probe_use():
    """u3: how many S5 automator probes touched an element the first look already saw. No S5 probe record keeps the probe's selector (the
    only capture that exists, `investigation_probe.capture_lines`, is S7's and keeps none either), so the count is `unmeasured` and names
    the carrier that is missing (FR-41); an S7 capture is never read under an S5 label."""
    return _unmeasured(NO_S5_PROBE_CARRIER)


def _role_used(art: Path, element: str):
    """`product.roles`: does the role stand in the strategist's accepted `product_roles` section (`project_knowledge.story_roles`, one reader)?"""
    import brief_pack
    import project_knowledge as PK
    try:
        if not brief_pack.last_accepted_form(art, "S3", "qa-test-strategist"):
            return _unmeasured("the strategist's form is not accepted yet")
        roles, reason = PK.story_roles(art)
    except Exception as exc:       # noqa: BLE001
        return _unmeasured(f"the strategist's form could not be read ({_why(exc)})")
    if reason:
        return _unmeasured(reason)
    form = PK._form(PK.ROLES_KEY, element)
    return any(PK._form(PK.ROLES_KEY, r["role"]) == form for r in roles)


def _account_used(art: Path, stand: str, role: str):
    """`environments.credentials_by_role`: gate A did NOT ask again for the known (stand, role) pair - none of the cards the packet SHOWED at
    gate A (the driver's own record, `state/driver-state.json` `shown_gaps.A.gaps[].id`) is the role card of the pair. A card shown and
    answered with "go on" still counts as asked again (what was SHOWN, not what the words name). The shown id is matched by its stand and role
    tokens (`gate_preflight.role_gap_tokens`, or the 16-hex widening of a collision), never recomputed against the packet's forms. No driver
    state (a conductor-run story) or a gate A never shown is `unmeasured`, never `used`."""
    path = art / "state" / "driver-state.json"
    if not path.is_file():
        return _unmeasured(NO_DRIVER_STATE)
    state = hooklib.read_json(path, {}, kind=dict)
    shown = state.get("shown_gaps", {}).get("A") if isinstance(state.get("shown_gaps"), dict) else None
    if not isinstance(shown, dict):
        return _unmeasured("gate A was not shown yet, or the driver state cannot be read (it keeps no shown gaps for gate A)")
    try:
        import gate_preflight as GP
        import project_knowledge as PK
        stok, tok = GP.role_gap_tokens(stand, role)
        wide = hashlib.sha1(PK._form(PK.ROLES_KEY, role).encode("utf-8")).hexdigest()[:16]
    except Exception as exc:       # noqa: BLE001
        return _unmeasured(f"the role card of the pair cannot be named ({_why(exc)})")
    prefix = f"{GP.ROLE_GAP_PREFIX}{stok}-"
    asked = any(isinstance(g, dict) and str(g.get("id") or "").startswith(prefix) and str(g["id"])[len(prefix):] in (tok, wide)
                for g in shown.get("gaps") or [])
    return not asked


def _side_used(pipeline: dict, name: str):
    """`product.sides` / `environments.sides` / `environments.reference_for`: the story's own sides record holds the side with `source: registry`
    (S0 took it from the registry, `contract.story_sides`) instead of asking whose side it is."""
    if not (isinstance(pipeline.get("sides"), dict) and pipeline["sides"]):
        return _unmeasured("the story has no sides record")
    entry = pipeline["sides"].get(name)
    return isinstance(entry, dict) and entry.get("source") == "registry"


def knowledge_use(task_root, project_root=None) -> dict:
    """THE one reader of the USE of what the factory knew (t-2277 FL-8, AR-13): `{"entries": [...], "first_look_use": {...},
    "counter_metrics": {...}, "briefs": "ok" | "unmeasured: <why>", "problems": [...]}`.

    One entry per knowledge, `{source: "registry" | "first_look", key, reached, used, available_unused}` (+ `environment`, `element` for a
    registry row, `used_by` for a first-look row). `reached`: the roles whose brief carries the marker `[knowledge:<key>]` / `[first-look:R-n]`
    (a list, [] = no brief did) or `unmeasured: briefs are not kept`. `used`: True / False or `unmeasured: <why>` - a registry role stands in the
    strategist's `product_roles`; a known account pair was not asked again at gate A; a known side is the story's side from the registry;
    a first-look row has a seen locator / route string in an S5 test home, or a case citing `first_look:R-n` (True if any measured part is
    positive, False if all are measured and zero, `unmeasured` otherwise). `available_unused`: reached AND used is False (None when either is
    unknown). The first-look aggregate counters u1 (seen locators and routes found in the S5 homes), u2 (cases citing the walked path), u3 (probes
    on seen elements) are under `first_look_use`. Counter-metric (2) is `known_not_reaching_a_decision`; (1) and (3) have no carrier (J-16, J-17:
    `unmeasured`). Reads only; writes nothing; never raises."""
    art = Path(task_root)
    out: dict = {"entries": [], "first_look_use": {}, "counter_metrics": {}, "briefs": "ok", "problems": []}
    try:
        qa = (Path(project_root) / "qa-factory") if project_root else _qa_root(art)
        root = qa.parent
        briefs, why = _briefs_read(art)
        if briefs is None:
            out["briefs"] = _unmeasured(why)
        pipeline = hooklib.read_json(art / "pipeline.json", {}, kind=dict)
        _registry_entries(art, root, briefs, why, pipeline, out, _story_start(pipeline))
        _first_look_entries(art, root, briefs, why, out)
        out["counter_metrics"] = _counter_metrics(out)
    except Exception as exc:       # noqa: BLE001 - a counter never stops the report; what it could not read is named
        out["problems"].append(f"the use of the knowledge could not be counted ({_why(exc)})")
        out["counter_metrics"] = _counter_metrics(out)
    return out


def _entry(source: str, key: str, reached, used, **more) -> dict:
    known = isinstance(reached, list) and isinstance(used, bool)
    return {"source": source, "key": key, "reached": reached, "used": used,
            "available_unused": (bool(reached) and not used) if known else None, **more}


def _known_before(row, start):
    """`(True | False | None, why)`: did the registry record this fact BEFORE the story began? The row's own time against the story's start
    (`_story_start`). No start, or a row with no readable time (a fact the settings carry has no row at all), is `None` with its reason - the
    fact is `unmeasured`, never known: a fact this story taught is not a fact it ignored."""
    if start is None:
        return None, NO_START
    moment = _instant(row.get("at")) if isinstance(row, dict) and row.get("at") else None
    if moment is None:
        return None, NO_ROW_TIME
    return moment < start, ""


def _registry_entries(art: Path, root: Path, briefs, why: str, pipeline: dict, out: dict, start) -> None:
    """One entry per registry fact `known` to THIS story: recorded before its start (B3). A fact recorded after is not an entry; one whose
    time or the story's start is unknown is an entry whose reach and use are `unmeasured`. The account pair has no brief carrier
    (`NO_ACCOUNT_REACH`): its reach is `unmeasured`, so it is never counted as a fact no brief carried."""
    import project_knowledge as PK
    for key in sorted(PK.KEYS):
        listed = PK.subjects(root, key)
        if listed["problem"]:
            out["problems"].append(listed["problem"])
            return
        for env, element in listed["subjects"]:
            got = PK.state(root, key, env, element)
            if got["state"] != PK.KNOWN:      # noticed / not needed is no known fact
                continue
            before, before_why = _known_before(got.get("row"), start)
            if before is False:
                continue
            if before is None:
                gone = _unmeasured(before_why)
                out["entries"].append(_entry("registry", key, gone, gone, environment=env, element=element))
                continue
            if key == PK.ROLES_KEY:
                used = _role_used(art, element)
            elif key == PK.ACCOUNTS_KEY:
                used = _account_used(art, env, element)
            elif key in SIDE_KEYS_OF_REGISTRY:
                used = _side_used(pipeline, element)
            else:
                used = _unmeasured("no carrier says whether this kind of fact was used")
            reached = _unmeasured(NO_ACCOUNT_REACH) if key == PK.ACCOUNTS_KEY else _reached_by_element(briefs, why, key, element)
            out["entries"].append(_entry("registry", key, reached, used, environment=env, element=element))


def _first_look_entries(art: Path, root: Path, briefs, why: str, out: dict) -> None:
    import first_look as FL
    got = FL.state(art)
    if got["kind"] != "ok":
        out["first_look_use"] = {"record": got["kind"]}
        return
    rows = got["got"]["rows"]
    manifest = C.load_json(C.artifact(art, "automation-manifest.json"))
    homes, homes_why = _home_texts(art, root, manifest)
    cites, cites_why = _cases_citing(art)
    seen_locators, seen_routes = [], []
    for row in sorted(rows, key=lambda r: T._numeric_key(str(r.get("req") or ""))):
        path = row.get("path") if isinstance(row.get("path"), dict) else {}
        locators = [str(x.get("selector")).strip() for x in path.get("locators") or []
                    if isinstance(x, dict) and x.get("seen") == "yes" and str(x.get("selector") or "").strip()]
        routes = [str(x.get("path")).strip() for x in path.get("api") or []
                  if isinstance(x, dict) and x.get("seen") == "yes" and str(x.get("path") or "").strip()]
        req = str(row.get("req") or "")
        parts = {"locators": _unmeasured(homes_why) if homes is None else sum(any(s in t for t in homes) for s in locators),
                 "routes": _unmeasured(homes_why) if homes is None else sum(any(s in t for t in homes) for s in routes),
                 "cases": _unmeasured(cites_why) if cites is None else len(cites.get(req, []))}
        seen_locators += locators
        seen_routes += routes
        counted = [v for v in parts.values() if isinstance(v, int)]
        used = (True if any(v > 0 for v in counted) else
                (False if len(counted) == len(parts) else _unmeasured("; ".join(sorted({_why_of(v) for v in parts.values() if not isinstance(v, int)})))))
        out["entries"].append(_entry("first_look", req, _reached_by_request(briefs, why, req), used, used_by=parts))
    if homes is None:
        u1 = _unmeasured(homes_why)
    else:
        found_l, found_r = (sum(any(s in t for t in homes) for s in seen_locators), sum(any(s in t for t in homes) for s in seen_routes))
        u1 = {"locators_seen": len(seen_locators), "locators_found": found_l, "routes_seen": len(seen_routes), "routes_found": found_r,
              "found": found_l + found_r}
    out["first_look_use"] = {"record": "ok", "rows": len(rows), "u1_locators_and_routes_in_s5_homes": u1,
                             "u2_cases_citing_the_walked_path": _unmeasured(cites_why) if cites is None else sum(len(v) for v in cites.values()),
                             "u3_probes_on_seen_elements": _probe_use()}


def _counter_metrics(use: dict) -> dict:
    """Counter-metric (2), "a known fact did not reach a decision" = the known registry facts no brief carried + the facts that reached a role and
    were not used; (1) and (3) are J-16 / J-17 and have no carrier (step 0 of FL-8). Facts whose use is unknown are counted apart."""
    entries = use["entries"]
    rest = {"used_unmeasured": sum(1 for e in entries if not isinstance(e["used"], bool)),
            "invented_not_asked": _unmeasured(NO_INVENTED_CLASS), "answer_scope_applied_as_rule": _unmeasured(NO_ANSWER_SCOPE)}
    # the three counters read the briefs AND the registry: either unknown makes them unknown, never 0 (B2, AR-28)
    reasons = ([_why_of(use["briefs"])] if use["briefs"] != "ok" else []) + list(use["problems"])
    if reasons:
        gone = _unmeasured("; ".join(reasons))
        return {"known_not_reached": gone, "available_unused": gone, "known_not_reaching_a_decision": gone, **rest}
    not_reached = sum(1 for e in entries if _not_reached(e))
    unused = sum(1 for e in entries if e["available_unused"])
    return {"known_not_reached": not_reached, "available_unused": unused, "known_not_reaching_a_decision": not_reached + unused, **rest}


def _not_reached(entry: dict) -> bool:
    """A known registry fact that no brief carried (measured: `reached` is the empty list) and that the story did not use anyway - a fact used
    (the strategist named the role, gate A did not ask again) never reads as one that did not reach a decision."""
    return entry["source"] == "registry" and entry["reached"] == [] and entry["used"] is not True


def _why_of(value) -> str:
    """The reason inside an `unmeasured: <why>` word (the word itself when it has no such prefix)."""
    text = str(value)
    return text[len("unmeasured: "):] if text.startswith("unmeasured: ") else text


def _first_look_price(art: Path):
    """The price of the first look's dispatch(es) by the story's own journal (FR-24): `{dispatches, cost_usd}`, `absent: <why>` when the story made
    none, `unmeasured: <why>` when the journal cannot say (a dispatch with no pair, a pair of unknown cost: `_side_cost`)."""
    import controller as CT
    state = hooklib.read_json(art / "state" / "controller.json", {}, kind=dict)
    records = state.get("dispatches")
    if not isinstance(records, dict) or not records:
        return _unmeasured("the story has no controller record of its dispatches")
    ids = {str(r.get("id") or n) for n, r in records.items() if isinstance(r, dict)
           and isinstance(r.get("request_binding"), dict) and r["request_binding"].get("purpose") == CT.FIRST_LOOK}
    if not ids:
        return _absent("the story has no first-look dispatch")
    journal, pairs, why_unknown = _journal_pairs(art)
    if journal != "ok":
        return _unmeasured("the story has no driver journal" if journal == "none" else "the driver journal names no session")
    return _side_cost(pairs, ids, why_unknown)


def _first_look_measure(art: Path, pipeline: dict, ledger, use: dict) -> dict:
    """The per-story counters of the first look (t-2277 FL-8): `record` (its state word), `cost`, `share`, `questions`, `attempt`, `placeholder_open`,
    and the two fields of the record nobody read before - `stand_needs` and `gaps` (how many the first look named; AR-22). The usage counters are
    `knowledge_use`'s (`use`), never counted again. Each counter the carrier cannot give is `unmeasured: <why>`."""
    import first_look as FL
    import ledger as L
    got = FL.state(art)
    kind, record = got["kind"], got["got"]
    why = (record.get("problem") if kind in ("absent", "unreadable") else
           "the record is about other code or another register" if kind == "stale" else
           f"the record could not be read ({got['error']})" if kind == "error" else "")
    countable = kind in ("ok", "null")
    attempt = FL.read_attempt(art)
    try:
        share = FL.share(art, C.case_config(art))
        share = _unmeasured(share["problem"]) if share["problem"] else {k: share[k] for k in ("reachable", "counted", "share", "floor")}
    except Exception as exc:       # noqa: BLE001
        share = _unmeasured(f"the share could not be read ({_why(exc)})")
    pipeline = pipeline if isinstance(pipeline, dict) else {}
    hold = C.awaiting(pipeline)
    import controller as CT
    answer = "continue" if FL.continued(art, pipeline) else ("stop" if hold["cause"] == CT.FIRST_LOOK_STOP else "none")
    return {"record": {"kind": kind, "rows": len(record.get("rows") or []) if countable else _unmeasured(why or kind),
                       "stale": bool(record.get("stale")), "problem": why},
            "cost": _first_look_price(art), "share": share,
            "questions": {"dead_asked": FL.asked(art) if attempt else _unmeasured("no first-look attempt is recorded"),
                          "same_code_asked": _unmeasured("the same-code question has no record on this build"),
                          "answer": answer},
            "attempt": {"outcome": attempt["outcome"], "open_failures": int(attempt.get("open_failures") or 0)} if attempt
                       else _unmeasured("no first-look attempt is recorded"),
            "placeholder_open": (_plan_row_counts(ledger, (L.PLACEHOLDER_OPEN_STATE,))[L.PLACEHOLDER_OPEN_STATE] if ledger is not None
                                 else _unmeasured("the story has no readable ledger")),
            "stand_needs": (sum(len(r["path"]["stand_needs"]) for r in record["rows"]
                                if isinstance(r.get("path"), dict) and isinstance(r["path"].get("stand_needs"), list))
                            if countable else _unmeasured(why or kind)),
            "gaps": len(record["gaps"]) if countable else _unmeasured(why or kind),
            "use": use.get("first_look_use") if isinstance(use, dict) else _unmeasured("the use was not counted")}


def _knowledge_facts(art: Path, root: Path, pipeline, ledger) -> dict:
    """The facts keys of the counters: `{knowledge_use, first_look_measure}` or `{}` (the ONE assembly, `build` and the retro both read it).
    `knowledge_use` is a key only for a story with a first look, or one whose registry holds a fact it knew before it began (or cannot
    place in time, or cannot read) - a project that LATER gained a registry gives an older story no key, so its facts are what they were."""
    out: dict = {}
    first_look = _first_look_present(art)
    if not (first_look or _registry_present(root)):
        return out
    use = knowledge_use(art, root)
    if first_look or use["entries"] or use["problems"]:
        out["knowledge_use"] = use
    if first_look:
        try:
            out["first_look_measure"] = _first_look_measure(art, pipeline, ledger, use)
        except Exception as exc:       # noqa: BLE001 - a counter never stops the report
            out["first_look_measure"] = {"record": {"kind": "error", "rows": _unmeasured(_why(exc)), "stale": False, "problem": _why(exc)}}
    return out


def knowledge_facts(task_root, project_root=None) -> dict:
    """`_knowledge_facts` for a reader that holds only the story folder (the retro): the pipeline and the ledger are read here, as `build`
    reads them, and whatever they cannot say stays in the counters as `unmeasured`. Reads only."""
    art = Path(task_root)
    qa = (Path(project_root) / "qa-factory") if project_root else _qa_root(art)
    unknown: dict = {}
    return _knowledge_facts(art, qa.parent, _load_pipeline(art, unknown), _load_ledger(art, unknown))


def question_count(task_root):
    """How many questions the story put to the person, for the retro's line: the questions of the story's register
    (`question_register.load`, the one reader of `work/requirements-readiness.json` `open_questions`) except those a designer took
    (`with_designer`: the person was not asked). A story with no readable register has no count: `unmeasured: <why>`, never 0; a register that
    is read and holds no question is a MEASURED zero."""
    try:
        got = QR.load(task_root)
    except Exception as exc:       # noqa: BLE001
        return _unmeasured(f"the question register could not be read ({_why(exc)})")
    if not got.get("register_present"):
        return _unmeasured("the story has no question register (work/requirements-readiness.json open_questions)")
    if got.get("problems") and not got.get("questions"):
        return _unmeasured("the question register could not be read: " + "; ".join(str(p) for p in got["problems"])[:160])
    return sum(1 for q in got.get("questions") or [] if q.get("status") != "with_designer")


# The retro's reading of the counters: lines of words, no money in them (the repository's files never print prices), nothing refused.

def finding_lines(facts: dict) -> list:
    """The finding lines of the retro (AR-27): "the record was not read" (zero by u1 AND u2 over a non-empty record, both MEASURED - an unmeasured
    counter is not zero), "the record could not be read" (an unreadable record is a gap line, not a crash) and "a known fact did not reach a
    decision" (a registry fact no brief carried, or one that reached a role and was not used). A null or absent record gives no "unread" line.
    Findings, never a refusal (AR-29)."""
    out: list = []
    fl = facts.get("first_look_measure")
    if isinstance(fl, dict):
        kind = (fl.get("record") or {}).get("kind")
        use = fl.get("use") if isinstance(fl.get("use"), dict) else {}
        if kind in ("unreadable", "error"):
            out.append(f"The first-look record could not be read ({(fl['record'].get('problem') or kind)}); how it was used is not known.")
        elif kind == "ok" and isinstance(fl["record"].get("rows"), int) and fl["record"]["rows"] > 0:
            u1, u2 = use.get("u1_locators_and_routes_in_s5_homes"), use.get("u2_cases_citing_the_walked_path")
            if isinstance(u1, dict) and isinstance(u2, int) and u1["found"] == 0 and u2 == 0:
                out.append(f"The first-look record was not read: none of its {fl['record']['rows']} rows reached a test home or a case "
                           "(0 seen locators or routes found in the S5 test homes, 0 cases cite the walked path).")
    for e in (facts.get("knowledge_use") or {}).get("entries") or []:
        if e["source"] != "registry":
            continue
        name = f"{e['key']} {e.get('element')}" + (f" on {e['environment']}" if e.get("environment") else "")
        if _not_reached(e):
            out.append(f"A known fact did not reach a decision: {name} was in no brief.")
        elif e["available_unused"]:
            out.append(f"A known fact did not reach a decision: {name} reached {', '.join(e['reached'])} and was not used.")
    return out


def _counter_words(metrics: dict) -> str:
    def say(v):
        return v if isinstance(v, str) else str(v)
    return (f"known facts no brief carried: {say(metrics['known_not_reached'])}; reached and not used: {say(metrics['available_unused'])}; "
            f"answer invented where a question was owed: {say(metrics['invented_not_asked'])}; "
            f"one story's answer applied as a project rule: {say(metrics['answer_scope_applied_as_rule'])}")


def question_count_line(count, facts: dict) -> str:
    """The count of questions put to the person, as the retro prints it. ZERO is printed only WITH the counter-metrics (a story that asked
    nothing because it already knew is not the same as one that asked nothing because it ignored what it knew); with no counter-metrics to
    print it, the zero is not printed at all (`unmeasured`)."""
    metrics = (facts.get("knowledge_use") or {}).get("counter_metrics")
    if count == 0 and not metrics:
        return _unmeasured("zero questions is not printed without its counter-metrics")
    line = f"Questions put to the person: {count}"       # a count with no carrier is its own `unmeasured: <why>` word, never 0
    return line + ("; " + _counter_words(metrics) if metrics else "")


def retro_lines(facts: dict) -> list:
    """The retro's table of knowledge (reached / used / not used) and the first-look counters, as lines of words, then the finding lines.
    Empty when the story has neither a first look nor a registry fact. `unmeasured: <why>` stands where a counter has no carrier."""
    use, fl = facts.get("knowledge_use"), facts.get("first_look_measure")
    if not isinstance(use, dict) and not isinstance(fl, dict):
        return []
    out = ["Knowledge: reached / used / not used"]
    for problem in (use or {}).get("problems") or []:
        out.append(f"- {_unmeasured(problem)}")
    for e in (use or {}).get("entries") or []:
        reached = e["reached"] if isinstance(e["reached"], str) else ("reached " + ", ".join(e["reached"]) if e["reached"] else "reached no brief")
        used = e["used"] if isinstance(e["used"], str) else ("used" if e["used"] else "not used")
        who = e["key"] + (f" {e['element']}" if e.get("element") else "") + (f" on {e['environment']}" if e.get("environment") else "")
        out.append(f"- {e['source']} {who}: {reached}; {used}")
    if isinstance(fl, dict):
        unknown = _unmeasured("the first-look counters could not be read")      # the error shape `build` writes has only `record`
        out.append(f"First look: stand needs named {fl.get('stand_needs', unknown)}; gaps named {fl.get('gaps', unknown)}; "
                   f"placeholder rows open at delivery {fl.get('placeholder_open', unknown)}")
    out += finding_lines(facts)
    return out


EXECUTION_OUTCOME_STATES = ("not_executed", "failed:NOT_EXECUTED", "failed:RUNNER_MISREAD_EVIDENCE")


def _execution_outcome(detail) -> bool:
    """Does a ledger reason quote the state of a check that never ran, or the runner's misread red (`ledger: <ref> is `<state>` ...`)?
    The owner of such a reason is `factory`, but the check was not done: the product was not looked at (F-7, FR-35, FR-41)."""
    import check_delivery as CD
    state = CD.LEDGER_STATE_IN_REASON.search(str(detail or ""))
    return bool(state) and (C.ledger_state_prefix(state.group(1)) == "not_executed" or state.group(1) in EXECUTION_OUTCOME_STATES)


def _count_bookkeeping(reqs, ledger, trace) -> None:
    """`counts["bookkeeping"]` (HF8-17, M-F, F-11 (a)): how many of the requirements counted `unproven` are open ONLY in the factory's
    own records - at least one reason of the ledger owned by the `factory` names one of the requirement's cases or tests (`refs`,
    typed ids, not wording), and no reason of another owner names its id, its plan row, its cases or its tests. `counts["unproven"]`
    and the classes do not change: this is a split of the same number, never a subtraction (I2, FR-35) - a requirement with a
    factory reason may hide a real gap, so it stays "open", never "proven". No typed reasons (no ledger, a ledger written before
    `refs`, an empty set): 0 - an unknown is not bookkeeping (I3)."""
    if reqs is None:
        return
    import ledger as L
    reqs["counts"]["bookkeeping"] = 0
    records = [r for r in (ledger or {}).get("records") or [] if r.get("refs") is not None]
    if not records:
        return
    tests_of: dict = {}
    for row in (trace or {}).get("rows") or []:
        for test in row.get("tests") or []:
            if isinstance(test, dict) and test.get("instance_id"):
                tests_of.setdefault(row.get("requirement"), set()).add(str(test["instance_id"]))
    for item in reqs["items"]:
        if item["class"] != "unproven":
            continue
        cases = {str(c).split("/")[-1] for c in item["cases"]}
        mine = ({item["id"], item["plan_row"]} | cases | tests_of.get(item["id"], set())) - {""}
        named = lambda r: bool(set(r["refs"]) & mine) or r["entity"] in mine  # noqa: E731
        # an execution outcome (a check that never ran, a misread red) is never "our records only", whoever owns it: it counts with the others.
        # `ours` needs no test of `execution` (t-427, the proof of t-424): a record in `ours` names a case or a test, which are in `mine`, so
        # `named` holds for it; if it has `execution` it is also in `others`, and `ours and not others` is False with or without it in `ours`
        ours = [r for r in records if r["owner"] == "factory" and set(r["refs"]) & (cases | tests_of.get(item["id"], set()))]
        # RD1-21: a `coverage:` reason is the factory's now, but the behaviour is unproven, not bookkeeping: it counts with the others
        # (a `coverage:` text that names a case id would otherwise grow the count of "open only in the factory's own records")
        others = [r for r in records if (r["owner"] != "factory" or r.get("execution") or r.get("code") == L.COVERAGE_GAP_CODE)
                  and named(r)]
        if ours and not others:
            reqs["counts"]["bookkeeping"] += 1


GAP_TESTS_MAX = 12
UNSAID = "not recorded"


def review_gaps(ledger) -> dict:
    """{"tests", "runs", "windows", "fixed", "problem"} - what the report and the gate B packet say of the tests the code critic
    rejected, read from a ledger dict only (`ledger.build` joined the carrier and the critic's form into it; nothing is read
    from a second source, FR-10). `tests` are the S5 rows still open: every row an S5 window speaks for
    whatever its state became (rejected, failed at S6, triaged at S7, delinked: the critic's words never drop out because the
    test later ran, I4) and every rejected row no window covers (it says its remarks were not recorded); `runs` the S7 rows
    left failing at their limit, `windows` the windows still holding something and `fixed` the ones a later review cleared. A
    ledger written before the carrier has none of the keys and reads as nothing to list. Names go through `_shown` here, once,
    so no consumer prints a spelling the validator refuses."""
    ledger = ledger if isinstance(ledger, dict) else {}
    rows = [r for r in ledger.get("rows") or [] if isinstance(r, dict) and r.get("kind") == "test"]

    def stage_of(row):
        limit = row.get("repair_limit")
        return limit.get("stage") if isinstance(limit, dict) else ""

    def in_s5_window(row):    # `remarks` is set by an S5 window only: an S7 window after it takes `repair_limit`, not that key
        return "remarks" in row or stage_of(row) == "S5"

    has_marks = _ledger_has_marks(ledger)

    def named(row, owed):
        function, cut_function = _shown(row.get("function"))
        case, cut_case = _shown(row.get("case"))
        # t-2277 W3: a rejected test and a run left failing say where their result came from, from the same ledger row as a Proven one
        return {"function": function, "case": case, "name_cut": cut_function or cut_case,
                "real_or_mock": _test_mark(row, has_marks, owed)}
    tests = [dict(named(r, False), remarks=r.get("remarks") or [], remarks_carrier=_words(r.get("remarks_carrier")), window=isinstance(r.get("repair_limit"), dict), dead=bool(r.get("dead")))
             for r in rows if in_s5_window(r) or (C.ledger_state_prefix(r.get("state", "")) == "review_rejected" and not r.get("dead"))]
    runs = [dict(named(r, True), words=_words(r.get("triage_words")))
            for r in rows if stage_of(r) == "S7" and C.ledger_state_prefix(r.get("state", "")) == "failed" and not r.get("dead")]
    windows = [w for w in ledger.get("repair_windows") or [] if isinstance(w, dict)]
    return {"tests": tests, "runs": runs, "windows": [w for w in windows if not w.get("fixed")],
            "fixed": [w for w in windows if w.get("fixed")], "problem": _words(ledger.get("repair_windows_problem"))}


def _regression(art: Path, project_root=None) -> dict:
    """`{"lines": [...], "machine_paths": [...], "story_tests": [...], "notes": [...]}` - the plan's `## Recommended regression`, line
    for line (`delivery_verdict.regression_lines`, the same reader `check_delivery` writes `left_items` with); `lines` is `[]` when
    the section is absent or blank. HF8-17 (M-E, AR-4): the only change to a line is the path of the developer's machine in front of
    OUR scripts (`portable_regression_line`); any other absolute path stays in its line and is named in `machine_paths`, and said once on
    stderr as the finding `report: regression line names a machine path`. RG1-4: `story_tests` are the files of this story's live
    manifest lines (they are never regression), `notes` say what could not be checked against the main branch; `lines` are not touched
    by either (FR-49). Never raises."""
    import delivery_verdict as DV
    try:
        lines = DV.regression_lines(C.read_text(C.artifact(art, "test-plan.md")))
    except Exception:
        lines = None
    lines = [DV.portable_regression_line(line) for line in lines or []]
    paths = list(dict.fromkeys(p for line in lines for p in DV.machine_paths(line)))
    for path in paths:
        print(f"report: regression line names a machine path ({path})", file=sys.stderr)
    story_tests, notes = _regression_vs_main(art, lines, project_root)
    return {"lines": lines, "machine_paths": paths, "story_tests": story_tests, "notes": notes}


def _regression_vs_main(art: Path, lines: list, project_root) -> tuple:
    """`(story_tests, notes)` of `_regression` (RG1-4): the files of the live manifest lines, sorted and without repeats (`[]` when the
    manifest cannot be read), and a note for an item that cannot be checked against the main branch or that is a test of this story
    missing from it (`regression_scope` is the one checker; the second also goes to stderr). Never raises: any failure is `([], [])`."""
    files = []
    try:
        import regression_scope as RS
        files = sorted({RS.normalize(t.get("file")) for t in T.live_tests(C.load_json(C.artifact(art, "automation-manifest.json")) or {})
                        if RS.normalize(t.get("file"))})
        items = list(dict.fromkeys(p.partition("::")[0] for p in RS.targets(lines) if p))
        if not items:
            return files, []
        try:
            import runtime_paths
            project = Path(project_root) if project_root else runtime_paths.project_for_task(art)
            cfg = RS.project_config(project)
            ref, why = RS.main_ref(project, cfg)
        except Exception as exc:  # noqa: BLE001 - an unknown is said, never a pass (FR-41)
            ref, why = "", f"the story's project could not be read ({type(exc).__name__})"
        if not ref:
            return files, [f"the paths could not be checked against the main branch: {why}"]
        notes = []
        for path, found in RS.on_main(RS.base_root(project, cfg), ref, items).items():
            if found is False and path in files:
                notes.append(f"{path} is a test of this story and not on {ref}; it is not regression")
                print(f"report: {notes[-1]}", file=sys.stderr)
        return files, notes
    except Exception:  # noqa: BLE001 - the measurer never raises
        return files, []


def left_asks(ledger) -> int:
    """How many things "Left with you" asks of the person that the question register does not hold (HF8-17, M-B, F-9 (a)): the
    typed `left_items` of the checks that COUNT (a check left with them), except the ones born at gate B (their own block, and
    an answer of theirs already) and the branch accounting's (`source: branches`, the `left-branches` block: a branch nobody
    proved is no question to the person, S5b M-B). A fact of typed rows, never of the scribe's prose (FR-12). No ledger: 0 - the segment is not
    said, and the verdict says the ledger is unknown."""
    return sum(1 for i in (ledger or {}).get("items") or [] if i.get("counts") and i.get("source") not in ("gate_b", "branches"))


def _questions(art: Path, unknown: dict, ledger=None):
    try:
        loaded = QR.load(art)
    except Exception as exc:
        unknown["questions"] = f"the question register could not be read ({_why(exc)})"
        return None
    if not loaded.get("register_present"):
        unknown["questions"] = "no question register was found, so whether any question is still open is not known"
        return None
    # HF2-6b (RD1-8): the one predicate is `QR.settled` - an answer on the bytes the person saw. A question the person
    # answered and whose row changed since, or one kept open until this report, is listed (before: by the raw status).
    listed = []
    for q in loaded.get("questions") or []:
        if QR.settled(q):
            continue
        listed.append({"id": str(q.get("id") or ""), "status": q.get("status"), "where": str(q.get("where") or ""),
                       "changed": q.get("changed_since_answer") is True,
                       "stray": QR.stray_line(q.get("id"), q.get("words")) if q.get("status") == "named" else "",
                       "owner": _words(q.get("owner_role")), "text": _words(q.get("question"))})
    listed.sort(key=lambda q: T._numeric_key(q["id"]))
    return {"listed": listed, "answered": sum(QR.settled(q) for q in loaded.get("questions") or []),
            "left_asks": left_asks(ledger)}


def _delivery(art: Path) -> dict:
    """What went outward, from the driver's own mark (`state["delivery"]`); `{}` when it holds none."""
    try:
        state = json.loads((art / "state" / "driver-state.json").read_text(encoding="utf-8-sig"))
        mark = state.get("delivery") if isinstance(state, dict) else None
        if isinstance(mark, dict) and _words(mark.get("did")):
            return {"did": _words(mark.get("did")), "action": _words(mark.get("action"))}
    except (OSError, ValueError):
        pass
    return {}


def _overrides(pipeline: dict, stages: tuple) -> list:
    out = []
    for entry in C.live_stage_overrides(pipeline, tuple(stages)):      # a revoked word is not shown as a decision (FR-35)
        if _words(entry.get("decision")):
            out.append({"stage": str(entry["stage"]), "match": _words(entry.get("match")) or "decision",
                        "decision": _words(entry.get("decision"))})
    return out


def _gate_words(pipeline: dict, gate: str) -> str:
    record = (pipeline.get("gates") or {}).get(gate) if isinstance(pipeline.get("gates"), dict) else None
    return str(record.get("authorization_source") or "").replace("\r\n", "\n").strip() if isinstance(record, dict) else ""


def _gate_a(pipeline: dict, reqs, unknown: dict) -> dict:
    words = _gate_words(pipeline, "A")
    blocked = None if reqs is None else sum("blocked" in i["results"] for i in reqs["items"])
    findings = []
    for check, what in sorted((_risk_words().get("project_wide_checks") or {}).items()):
        for found in sorted(set(re.findall(r"(?<![\w-])" + re.escape(check) + r"-\d+(?![\w-])", words))):
            findings.append({"id": found, "line": QR._line_with(words, found) and _words(QR._line_with(words, found)),
                             "what": str(what)})
    return {"words": words, "overrides": _overrides(pipeline, GATE_A_STAGES), "env_findings": findings,
            "stopped_cases": blocked, "pipeline_known": "pipeline" not in unknown}


def _gate_b(pipeline: dict, bugs, delivery: dict, cfg=None) -> dict:
    import validate_artifacts as V
    words = _gate_words(pipeline, "B")
    # The story's own case-id config, so a render from outside the project names the same cases as one
    # from inside it (t-202 F5); the other reads of this module already pass it.
    decided = T.decided_cases(pipeline, cfg)
    cases = {}
    for case in sorted(decided, key=T._numeric_key):
        source = [s for s in [words] + [str(e.get("decision") or "")
                                        for e in C.live_stage_overrides(pipeline, tuple(GATE_B_STAGES))]
                  if C.names_whole(case, s)]
        line = next((_words(ln) for s in source for ln in s.splitlines() if C.names_whole(case, ln)), "")
        cases[case] = line
    return {"decided": V.gate_b_has_words(pipeline), "words": words, "overrides": _overrides(pipeline, GATE_B_STAGES),
            "cases_named": cases, "delivery": delivery,
            "bugs": None if bugs is None else [{"id": r["id"], "homes": r["homes"], "state": r["state"]}
                                               for r in bugs["records"]]}


def _attachments(art: Path, unknown: dict):
    """What the report says about the attachments, from the one reader of them (`gate_brief.attachments_data` over
    `branch_accounting.attachments_view`, AR-13; "decided" is `gate_brief.gate_a_decided`, the one reader of that fact):
    `{"tickets", "total", "named", "decided"}`, `named` the list the plan gate's packet NAMED (None: no record of it); `{}` when the
    story keeps no list of its sources (nothing to say, byte-identical to before); None with `unknown["attachments"]` when the list
    cannot be read."""
    try:
        import gate_brief as GB
        data = GB.attachments_data(art)
    except Exception as exc:
        print(f"report_facts: the list of attachments could not be read ({_why(exc)})", file=sys.stderr)
        unknown["attachments"] = "the list of attachments could not be read"
        return None
    if data.get("state") == "absent":
        return {}
    if data.get("state") != "known":
        unknown["attachments"] = data.get("reason") or "the list of attachments cannot be read"
        return None
    decided = GB.gate_a_decided(art)
    if decided is None:
        unknown["attachments"] = "the plan gate's record cannot be read, so whether the attachments were offered to you is not known"
        return None
    return {"tickets": data["tickets"], "total": data["total"], "named": data.get("named"), "decided": decided}


def _size(art: Path, pipeline: dict, plan_rows: list, manifest: dict, case_index, facts: dict) -> dict:
    sizing = C.load_json(art / "work" / "sizing.json") if (art / "work" / "sizing.json").is_file() else {}
    from_sizing = str(sizing.get("size_override") or sizing.get("size") or "") if sizing else ""
    initial = str(pipeline.get("size_initial") or pipeline.get("size") or from_sizing or "")
    final = str(pipeline.get("size_final") or pipeline.get("size") or from_sizing or "")
    reqs = facts["requirements"]
    tests = None
    try:
        if C.artifact(art, "automation-manifest.json").is_file():
            tests = len(T.live_tests(manifest))
    except Exception:
        pass
    import sizing as SZ  # the same sentences as the gate line (`gate_brief.sizing_line`): one writer (AR-19)
    return {"initial": initial, "final": final, "reason": _words(pipeline.get("size_reason")),
            "budget": sizing.get("computed_budget") if sizing else None,
            "cap": sizing.get("cap") if sizing else None, "sizing_size": str(sizing.get("size") or "") if sizing else "",
            "functions": SZ.function_words(sizing), "heavy": SZ.heavy_words(sizing), "defect": SZ.defect_words(sizing),
            "overage": sizing.get("overage") if sizing else None,
            "from_pipeline": bool(pipeline.get("size_initial") or pipeline.get("size")),
            "counts": {"testable_requirements": None if reqs is None else reqs["testable"],
                       "plan_rows": len(plan_rows) if (art / "test-plan.md").is_file() or plan_rows else None,
                       # no case file at all is "none was found", which a story past S4 cannot have: unknown
                       "cases": len(case_index) if case_index else None, "tests": tests}}


def _where(art: Path, pipeline: dict) -> dict:
    files = {}
    for name in ("understanding.md", "test-plan.md", "retro.md"):
        path = C.artifact(art, name)
        if path.is_file():
            # each section once, in the order it first stands (HF8-17, M-C): a plan with one `## Given; When; Then; ...` group per case
            # listed them twelve times (run 12586)
            files[name] = list(dict.fromkeys(h[3:].strip() for h in G.heading_lines(C.read_text(path))))
    skip = ""
    if "retro.md" not in files and str(pipeline.get("retro_mode") or "") == "skip":
        skip = _words(pipeline.get("retro_mode_words")) or "no words were recorded"
    return {"files": files, "retro_skip_words": skip, "config_revert": _config_revert_line(art)}


def _config_revert_line(art: Path) -> str:
    """What the story's end did to the stand's config.json, as the revert left it in the story's copy ("" when it has not ended, kept
    no copy or had nothing to say). Read through `config_contract.stored_revert_line`, the one reader (AR-13); a source that cannot
    be read is "" here, the revert's own line is in the driver log."""
    try:
        import config_contract
        return config_contract.stored_revert_line(art)
    except Exception:
        return ""


def _instant(text):
    """A stamp as an INSTANT (N6): the signal's `ts` is UTC ISO with `+00:00`, a pipeline stamp may be `Z`, with another
    offset or naive (naive is read as UTC: an estimate, said here). Compared as instants, never as strings; None = unparsable."""
    from datetime import datetime, timezone
    try:
        moment = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _story_start(pipe: dict):
    """The story's start as an instant: the earliest of `created_at` and every stage's `started_at` that reads, or None when the pipeline
    records none (the ONE carrier of "when did this story begin" for the hook signals and the first-look counters)."""
    stages = [s for s in (pipe.get("stages") or {}).values() if isinstance(s, dict)] if isinstance(pipe.get("stages"), dict) else []
    begun = [_instant(s) for s in [pipe.get("created_at")] + [st.get("started_at") for st in stages] if s]
    return min((m for m in begun if m is not None), default=None)


def _hook_signals(art: Path, qa: Path, pipeline: dict = None, unknown: dict = None) -> dict:
    """The `hook_signal` events of this history (RH1-5, AR-22: `hooklib.person_signal` writes them, this reads them):
    `{"count", "kinds": {kind: n}, "path", "skipped", "no_task_unplaced"}`. A row counts when its `task` is this story;
    a row with no task counts when its `ts` is not earlier than the history's start, and when the pipeline records no
    start those rows are NOT taken (`no_task_unplaced` says how many). A journal that does not exist is "none recorded"
    (E21); one that cannot be read is `unknown` with the reason in `unknown["hook_signals"]` (FR-41, E26); a line that
    is not JSON is skipped and counted in `skipped`. The journal is JSON lines, read line by line here (axis 16)."""
    import runtime_paths as RP
    instant = _instant

    # N8: the config is read through the ONE reader (`hooklib.load_config`), pointed at THIS project by its folder
    cfg = hooklib.load_config({"cwd": str(Path(qa).parent)})
    journal = RP.configured(Path(qa).parent, cfg.get("journal_path"), "journal.jsonl")
    out = {"count": 0, "kinds": {}, "path": str(journal), "skipped": 0, "no_task_unplaced": 0}
    pipe = pipeline if isinstance(pipeline, dict) else {}
    stages = [s for s in (pipe.get("stages") or {}).values() if isinstance(s, dict)] if isinstance(pipe.get("stages"), dict) else []
    start = _story_start(pipe)       # the earliest instant the pipeline records (the instants, not the texts, are compared, N6)
    # N6: a task-less row is the story's only inside [start, end]. The end is the story's close or its latest stage stamp
    # (the retro S9 runs after the close); an open story, or a stamp nobody can read, has NO end (over-report beats loss).
    end = None
    if start is not None and hooklib.story_closed(pipe):
        stamps = [hooklib.story_closed(pipe)] + [str(v) for st in stages for k, v in st.items() if str(k).endswith("_at") and v]
        moments = [m for m in (instant(s) for s in stamps) if m is not None]
        end = max(moments) if moments else None
    try:
        text = journal.read_text(encoding="utf-8", errors="replace") if journal.is_file() else ""
    except OSError as exc:
        if unknown is not None:
            unknown["hook_signals"] = f"the journal {journal} could not be read ({_why(exc)})"
        return {"count": None, "kinds": {}, "path": str(journal), "skipped": 0, "no_task_unplaced": 0}
    notes_seen: set = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            out["skipped"] += 1
            continue
        if not isinstance(row, dict) or row.get("event") != "hook_signal":
            continue
        task = str(row.get("task") or "")
        if task:
            mine = task == art.name
        elif start is not None:
            when = instant(row.get("ts") or "")
            mine = when is None or (when >= start and (end is None or when <= end))   # an unreadable stamp is counted, not lost
        else:
            out["no_task_unplaced"] += 1
            mine = False
        if mine and row.get("kind") == "exit_gate_note":
            # N7: one note, said by the hook, by `finish` and by the driver for the same handoff, is ONE note of the story
            seen_note = (task, str(row.get("notes") or ""))
            if seen_note in notes_seen:
                continue
            notes_seen.add(seen_note)
        if mine:
            kind = str(row.get("kind") or "unknown")
            out["kinds"][kind] = out["kinds"].get(kind, 0) + 1
            out["count"] += 1
    return out


def _plan_decision(item: dict, plan_rows: list, pipeline: dict) -> str:
    """The reason, VERBATIM, when this requirement's null outcome is a decision of the PLAN the person approved at gate A
    (owner amendment 03.10, FR-12: the ledger's own facts, never wording), else "". Two facts say it:
      - a gate A waiver of the requirement (`gate_waivers[]`, gate `A`: the `waived:<inner>` rows of the ledger): their words;
      - every plan row that names the requirement is a `skip` or `unverifiable` one (low priority by the plan): its reason.
    A waiver of gate B is the person's word at THAT gate, not the plan's, so it stays under "Not proven"; a requirement the
    plan wants executed and that did not execute (NOT_EXECUTED, the stand, a deferral nobody worded) is never here.

    HF2-6b: a requirement with a RED trace row (`bug`, `blocked`) is never here either. A gate A waiver is the person's word
    about a check the plan will not run; it does not turn a test that RAN AND FAILED into "skipped by the plan" (the legacy join
    of 6a reads that failed row now, and the waiver used to file the requirement here). It stands under "Not proven", with the
    basis of its row."""
    if {"bug", "blocked"} & set(item.get("results") or ()):
        return ""
    waiver = C.waivers_by_requirement(pipeline).get(item["id"])
    if isinstance(waiver, dict) and str(waiver.get("gate") or "") == "A" and _words(waiver.get("decision")):
        return f'your words at gate A: "{_words(waiver["decision"])}"'    # the person's word closes the walk (t-604 F-5), a wait or not
    if "wait" in set(item.get("results") or ()):
        return ""  # an open question is no decision: the row waits for a person's answer (t-604 F-1)
    named = [p for p in plan_rows if item["id"] in (p.get("requirements") or [])]
    if named and all(str(p.get("disposition") or "") in ("skip", "unverifiable") for p in named):
        reasons = list(dict.fromkeys(str(p.get("reason") or "").strip() for p in named if str(p.get("reason") or "").strip()))
        rows = ", ".join(str(p.get("ts")) for p in named)
        return "; ".join(reasons or ["the plan gives no reason"]) + f" (plan row {rows}, skipped by the plan)"
    return ""


def _skipped_by_plan(reqs, plan_rows: list, pipeline: dict, gap_ids=frozenset()):
    """The requirements whose null outcome is the approved plan's own decision (`_plan_decision`), each with that reason. A requirement
    in `gap_ids` (the person's recorded product gaps) is never here: it is not "deferred by your decision", it is not implemented."""
    if reqs is None:
        return None
    words = _risk_words()
    out = []
    for item in reqs["items"]:
        if item["class"] not in UNPROVEN_CLASSES or item["id"] in gap_ids:
            continue
        reason = _plan_decision(item, plan_rows, pipeline)
        if reason:
            out.append({"id": item["id"], "class": item["class"], "cause": reason, "risk": _risk(item, words)})
    return out


def _stopped_by_case(ledger) -> dict:
    """{bare case id: what stopped its check, in the record's own words} from the ledger's typed `left_items` (`stopped`)."""
    out = {}
    for item in (ledger or {}).get("items") or []:
        if item.get("case") and _words(item.get("stopped")):
            out[str(item["case"]).split("/")[-1]] = _words(item["stopped"])
    return out


def _not_proven(reqs, plan_rows: list, pipeline: dict, stopped=None, gap_ids=frozenset()):
    """The checks that COULD NOT execute, each with its cause: the plan's own words for the check, and what stopped it
    (`stopped`: `_stopped_by_case`) when a record says."""
    if reqs is None:
        return None
    words = _risk_words()
    out = []
    for item in reqs["items"]:
        if item["class"] not in UNPROVEN_CLASSES:
            continue
        if item["id"] in gap_ids or _plan_decision(item, plan_rows, pipeline):
            continue            # a product gap stands among the product reasons; the plan's own decision under "Skipped by the plan"
        cause = "; ".join(item["bases"]) or "no result is recorded for it"
        stops = list(dict.fromkeys(stopped[c] for c in (str(x).split("/")[-1] for x in item.get("cases") or []) if c in (stopped or {})))
        if stops:      # " : " separates the cause from the risk in this block's lines (`check` reads it): never inside a cause
            cause += "; what stopped it: " + "; ".join(stops).replace(" : ", " - ")
        if item.get("partly"):
            cause = "partly proven — " + "; ".join(item["partly"]) + (f"; {cause}" if item["bases"] else "")
        if item["class"] == "deferred":
            said = _person_line(pipeline, item["id"])
            cause = "deferred — " + cause + (f'; your words: "{said}"' if said
                                                   else "; no word of yours about it is recorded")
        out.append({"id": item["id"], "class": item["class"], "cause": cause, "risk": _risk(item, words)})
    return out


def _risk(item: dict, words: dict) -> str:
    if not item["plan_row"]:
        return "risk: " + str(words.get("no_plan_row_words") or "not assessed at planning — no plan row")
    impact = item["impact"]
    if not impact:
        return "risk: " + str(words.get("no_impact_words") or "not assessed at planning: the plan row {ts} records no impact class"
                              ).format(ts=item["plan_row"])
    table = words.get("impact") or {}
    said = table.get(impact) or str(words.get("impact_unknown_words") or 'the plan row names the impact class "{impact}"'
                                    ).format(impact=impact)
    hypothesis = item["hypothesis"]
    return f"risk: {said}; the plan's defect hypothesis: {hypothesis or 'none recorded'}"


# --- the verdict ---------------------------------------------------------------------------------

def _verdict(facts: dict) -> dict:
    import check_delivery as CD      # hoisted out of the reds loop (F10 t-1753)
    import ledger as L
    ledger, reqs, bugs, tests = facts["ledger"], facts["requirements"], facts["bugs"], facts["tests"]
    # t-305 N8 (D9): the WORD is the ledger's, never recomputed here. The candidates below keep one job - the WORDING
    # of the `no` head ("Because ...") - and one more: a candidate the ledger does not hold is named beside a `yes` or an
    # `after_checks` head as the factory's own finding, never turned into a different word. Each carries `expected`: a
    # gap the third verdict already covers (a requirement that waits for a person or was deferred, a test the critic could
    # not verify) is what `after_checks` MEANS, so it is no disagreement there; a bug, an unproven requirement or a
    # residual is.
    candidates = []
    # what the ledger itself leaves with the person (typed `left_items`): a requirement or a case in it is HELD by the third
    # verdict, whatever the report's own class calls it ("not run" for a manual check that did not answer)
    held_items = [i for i in (ledger or {}).get("items") or [] if i.get("counts")]
    held_cases = {str(i.get("case")).split("/")[-1] for i in held_items if i.get("case")}
    held_reqs = {r for i in held_items for r in i.get("requirements") or []}
    # RN1-16: the head of a `no` names the product bug first. `ranked` is the order the HEAD reads the candidates in - (group, candidate),
    # stable inside a group, so the checks keep their order within it: 1 confirmed bugs, 2 bug drafts, 3 product gaps, 4 reds the
    # product owns, 5 unproven requirements, 6 tests the critic could not verify, 7 reds of the environment or a review, 8 reds of the
    # factory, 9 the residual sentence. `candidates` keeps its old order and members: `held`/`odd` (the disagreement) read it, and a
    # draft or a product gap is not a disagreement with a `yes` (FR-35: only the ORDER of the head changes, never the word).
    ranked = []
    for record in (bugs or {"records": []})["records"]:
        where = f" ({', '.join(record['requirements'])})" if record["requirements"] else ""
        if record["state"] == "confirmed":
            candidates.append(("bug", f"{record['id']} is a confirmed product bug{where}: {record['title']}", False, False))
            ranked.append((1, candidates[-1]))
        elif record["requirements"] and not record.get("gate_b_not_chosen"):
            # a draft of a bug found by this run that names a requirement (E-A3: none -> it cannot claim the product) and that
            # the person did not leave out at gate B (`gate_b_not_chosen`: a draft they did not choose is not a reason); the
            # `state` words of `bug_records.story_bugs` are confirmed / reproduced / unconfirmed / unknown (no rejected one)
            ranked.append((2, ("bug_draft", f"{record['id']} is a product bug found by this run, not confirmed yet{where}: "
                               f"{record['title']}", False, False)))
    for gap in (ledger or {}).get("product_gaps") or []:
        ranked.append((3, ("product_gap", f"{gap['requirement']} is not implemented" + (f": {gap['words']}" if gap["words"] else ""),
                           False, False)))
    # a failed row of the ledger holds a `no` itself (F5): named after the bugs, in the ledger's own order
    for red in (ledger or {}).get("reds") or []:
        candidates.append(("ledger_failure", f"{red['ref']}" + (f" ({red['detail']})" if red["detail"] else "")
                           + f" failed in the run - the triage verdict is {red['verdict']}", False, False))
        # the owner's place in the ledger's own order (`L.OWNER_ORDER`: product, environment, review, factory - the order its
        # headings print in, AR-13): the first is group 4, the last - and any owner outside it - group 8, the ones between 7
        owner = red.get("owner") or CD.triage_verdict_owner(red["verdict"])
        place = L.OWNER_ORDER.index(owner) if owner in L.OWNER_ORDER else len(L.OWNER_ORDER) - 1
        ranked.append((4 if place == 0 else 8 if place >= len(L.OWNER_ORDER) - 1 else 7, candidates[-1]))
    if reqs is not None:
        gaps = [i for i in reqs["items"] if i["class"] in UNPROVEN_CLASSES]
        gaps.sort(key=lambda i: (i["priority"], T._numeric_key(i["id"])))
        for item in gaps:
            basis = "; ".join(item["bases"])
            # `held`: the ledger itself holds it in `left_items` (the third verdict covers it HERE); `covered`: what the third
            # verdict MEANS, for the disagreement sentence under `after_checks`
            held = item["id"] in held_reqs or bool({str(c).split("/")[-1] for c in item["cases"]} & held_cases)
            covered = item["class"] in ("wait", "deferred") or held
            # whether it can HOLD a `no` (the head's question): not when the ledger holds it as an item, nor when it waits or
            # was deferred and no reason of the ledger names it (a plan skip, a person's word) - it holds nothing then
            held = held or (item["class"] in ("wait", "deferred") and item["id"] not in ((ledger or {}).get("entities") or []))
            if item.get("partly"):
                candidates.append(("requirement", f"{item['id']} ({item['text']}) is partly proven — "
                                   + "; ".join(item["partly"]), True, held))
                ranked.append((5, candidates[-1]))
                continue
            candidates.append(("requirement", f"{item['id']} ({item['text']}) is not proven" + (f": {basis}" if basis else ""),
                               covered, held))
            ranked.append((5, candidates[-1]))
    unverified = (tests or {}).get("unverified") or 0
    if unverified:
        candidates.append(("unverified", f"{unverified} {_plural(unverified, 'test', 'tests')} could not be verified by the code critic",
                           True, any(i.get("kind") in ("review_unverified", "review_unverified_factory") for i in held_items)))
        ranked.append((6, candidates[-1]))
    word = None if ledger is None else ledger["word"]
    # F5 (FR-20): the head of a `no` names a reason that actually HOLDS it - the first candidate the ledger does not already
    # hold as something left with the person (the third verdict covers that one), in the order above. When every candidate is
    # held and the ledger still says `no` (its reasons are the factory's own, or no requirement explains them), the
    # residual sentence says so: the head of a `no` is never the name of a thing the third verdict covers.
    ranked.sort(key=lambda pair: pair[0])     # stable: inside a group the order of the checks is kept
    uncovered = [c for _group, c in ranked if not c[3]]
    if ledger is not None and word == "no" and not uncovered:
        owners = ledger["owners"]
        parts = []
        if owners.get("product"):
            parts.append(f"{owners['product']} on the product side that no single requirement explains")
        waiting, windows = owners.get("environment", 0) + owners.get("review", 0), ledger["limit_windows"]
        if waiting or windows:
            parts.append((f"{waiting} waiting on the environment or a review" if waiting else "")
                         + (("; " if waiting else "") + f"repair limit exhausted on {_n(windows, 'window', 'windows')}" if windows else ""))
        # RD1-21: the factory's reasons that are a behaviour no test proves are said apart from its bookkeeping
        coverage = ledger.get("factory_coverage") or 0
        bookkeeping = max(0, (owners.get("factory") or 0) - coverage)
        if bookkeeping:
            parts.append(f"{bookkeeping} that are the factory's own bookkeeping, for which nothing is wanted from you")
        if coverage:
            parts.append(L.factory_coverage_line(coverage))
        residual = ("residual", "the checks still list open reasons: " + ("; ".join(parts) or "none of them is named"), False, False)
        candidates.append(residual)
        uncovered = [residual]
    first = uncovered[0] if uncovered else (candidates[0] if candidates else None)
    # a candidate the ledger's word does not hold: for `yes` every one; for `after_checks` those the third verdict
    # does not already mean
    held = [c for c in candidates if word == "yes" or (word == "after_checks" and not c[2])]
    odd = held[0] if held else None
    return {"word": word, "ready": None if word in (None, "unknown") else word == "yes",
            "ledger_ready": None if ledger is None else ledger["ready"],
            "first_kind": first[0] if first else "", "first_reason": _cut(first[1]) if first else "",
            "first_reason_full": _words(first[1]) if first else "",
            "disagreement": _words(odd[1]) if odd else ""}


# --- the blocks ----------------------------------------------------------------------------------

def _n(count: int, one: str, many: str) -> str:
    return f"{count} {_plural(count, one, many)}"


def _unknown_line(facts: dict, key: str, what: str = "") -> str:
    """One `Unknown ...` sentence. A `<key>_code` of `tool` in `facts["unknown"]` (EP1-37 M-6) says the gap is the factory's
    reader's, not the product's: the sentence names its owner (FR-19), so it is not read as a product gap."""
    owner = "a gap of the factory's tool, not of the product: " if facts["unknown"].get(f"{key}_code") == "tool" else ""
    return f"Unknown{(' ' + what) if what else ''} — {owner}{facts['unknown'].get(key, 'the source was not readable')}."


def render(facts: dict, previous_verdict: str = "") -> dict:
    """{block name: body} for every block that exists NOW: `gate-b` only once gate B has words. Bodies are
    LF text; `grammar.render_block` adds the markers. Pure and deterministic. `previous_verdict` is the
    verdict block as the report holds it, read only to keep the old sentence when a rebuild after gate B
    changes it (R-212.1)."""
    blocks = {"verdict": _r_verdict(facts, previous_verdict), "proven": _r_proven(facts),
              "manual-checks": _r_manual_checks(facts), "bugs": _r_bugs(facts), "review-gaps": _r_review_gaps(facts),
              "open-questions": _r_questions(facts), "skipped-by-plan": _r_skipped_by_plan(facts),
              "not-proven": _r_not_proven(facts), "gate-a": _r_gate_a(facts)}
    if _register_shown(facts):   # a story without a register renders byte-identically to one before the block existed
        blocks["exploratory"] = _r_exploratory(facts)
    if facts["gate_b"]["decided"]:
        blocks["gate-b"] = _r_gate_b(facts)
    # r0107 S6 step 3: what the branch accounting leaves with the person, in its own block before gate B's (a story with none
    # renders byte-identically to one before the block existed); a record that cannot be read is said, not left out
    if _branch_lines_of(facts) or (facts.get("branches") is None and "branches" in facts["unknown"]):
        blocks["left-branches"] = _r_left_branches(facts)
    if _excluded_by_word(facts):
        blocks["branches-not-proven"] = _r_branches_not_proven(facts)
    # the two code-owned blocks INSIDE "Left with you" (t-305 N8): what gate B's answers added, then the regression
    # list - last in the section, so the scribe's span ends at the first of them (`_section_span`)
    if _gate_b_items(facts) or _open_finding_lines(facts):
        blocks["left-gate-b"] = _r_left_gate_b(facts)
    # the project's test files that did not collect stand right after the regression list, in the same code-owned block:
    # no section of its own exists for what the factory found (the grammar's block list is the report's shape)
    gaps = _r_collect_gaps(facts)
    unrun = _r_quality_not_run(facts)
    gaps = gaps + ("\n" if gaps and unrun else "") + unrun
    unmatched = _r_integration_gap(facts) + str(facts.get("owed_rework") or "") + str(facts.get("passed_over") or "")       # TR1-9: the work a code close passed over; # HF8-17: the integrations no case could be tied to (a gap line, E17); r0107 F-4: the rework an approval passed over
    gaps = gaps + ("\n" if gaps and unmatched else "") + unmatched
    blocks["regression"] = _r_regression(facts) + ("\n" + gaps if gaps else "")
    blocks["size"] = _r_size(facts) + _r_grounding(facts)       # G2-5: what the change touches, in the size block (no block of its own)
    blocks["where-to-look"] = _r_where(facts)
    return blocks


def _gate_b_items(facts: dict) -> list:
    """The `left_items` rows born at gate B (`source: gate_b`): an `accept`/`apply`/`theirs`/`handed` answer of the person's
    that left a check with them. Typed rows of the ledger, nothing read from prose."""
    ledger = facts.get("ledger")
    return [i for i in (ledger or {}).get("items") or [] if i.get("source") == "gate_b" and i.get("counts")]


def _integrations(art: Path, unknown: dict) -> dict:
    """`{"names": [...], "readable": bool}` - the integrations the gate's collective line says the factory could not tie to the
    story's cases, read through `gate_preflight.unmatched_integrations`, the one reader of that fact (HF8-17, AR-13/AR-22: it was
    written for this report). Never raises: a reader that fails is `readable: False`, which the report says (FR-41, AR-28)."""
    try:
        import gate_preflight as GP
        got = GP.unmatched_integrations(art)
        return {"names": [str(n) for n in got.get("names") or []], "readable": bool(got.get("readable"))}
    except Exception:
        return {"names": [], "readable": False}


OWED_REWORK_OWNERS = {"strategist": "the test planner", "designer": "the case designer"}


def _owed_rework_gap(art: Path) -> str:
    """The gap lines of the rework the person's `approve as is` passed over (r0107 F-4, E17): the controller keeps one `answers_applied`
    record (`what: rework_left`) in the answers file when it records the approval over an owed rework; each (owner, row or case) is a
    line saying what was to be reworked, for which answer, that it was not done, and that it runs only on the person's word. No record
    gives NO line; a file that cannot be read gives one line that says so (AR-28), never the silence of an empty list. A rework the
    person later started is not retired here (the error goes toward keeping the line, FR-41). Reads only."""
    path = Path(art).joinpath(*QR.ANSWERS_REL)
    try:
        text = path.read_bytes().decode("utf-8-sig", errors="replace")
    except FileNotFoundError:
        return ""
    except OSError:
        return left_gap_line("approved rework", "whether a rework your answers owe was passed over by your approval could not be "
                             "established", "someone who can read the story's answers file") + "\n"
    owed: dict = {}
    for raw in text.split("\n"):
        try:
            record = json.loads(raw) if raw.strip() else None
        except (ValueError, RecursionError):
            continue
        if isinstance(record, dict) and record.get("kind") == "answers_applied" and record.get("what") == "rework_left":
            for item in record.get("owed") or []:
                if isinstance(item, dict) and item.get("where"):
                    owed.setdefault((str(item.get("owner")), str(item["where"])), []).append(_words(item.get("question")))
    out = []
    for (owner, where), questions in owed.items():
        asked = ", ".join(dict.fromkeys(q for q in questions if q))
        out.append(left_gap_line(where, f"{OWED_REWORK_OWNERS.get(owner) or 'someone'} was to rework it to follow your answer"
                                 + (f" to {asked}" if asked else "") + "; you approved the plan as it is, so it was not done",
                                 "your word to start that rework") + "\n")
    return "".join(out)


PASSED_OVER_ID_RE = re.compile(r"^(S\d+)-(.+)-\d+$")


def _passed_over_gap(art: Path) -> str:
    """The gap lines of the work a stage's CODE close passed over (TR1-9 B4, AR-27): the controller's `code_only` receipt keeps
    `passed_over: [{id, label}]` on the stage's entry of `pipeline.json` (`returned, never accepted`, `abandoned`, `stopped, never
    accepted`); each name is a line saying whose work, of which stage, and that the stage was closed over it. No names give NO
    line; a record that cannot be read gives one line that says so (AR-28), never the silence of an empty list. Reads only."""
    path = Path(art) / "pipeline.json"
    if not path.is_file():
        return ""           # the missing record is already said once (`unknown["pipeline"]`)
    stages = None           # an unreadable record and a record with no stages are one outcome: the line below
    try:
        stages = json.loads(path.read_bytes().decode("utf-8-sig", errors="replace")).get("stages")
    except (OSError, ValueError, AttributeError, RecursionError):
        pass
    if not isinstance(stages, dict):
        return left_gap_line("closed stages", "whether a stage was closed over work nobody accepted could not be established",
                             "someone who can read the story's record of the stages") + "\n"
    out = []
    for name, entry in stages.items():
        named = entry.get("passed_over") if isinstance(entry, dict) else None
        for item in named if isinstance(named, list) else []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            ident = str(item["id"])
            found = PASSED_OVER_ID_RE.match(ident)
            who = f"{found.group(2)}'s work of {found.group(1)}" if found else f"the work of {name} ({ident})"
            label = _words(item.get("label")) or "never accepted"
            out.append(left_gap_line(ident, f"{who} was {label}, and {name} was closed by code over it",
                                     "your word on whether that work mattered, or a re-run of the stage") + "\n")
    return "".join(out)


def _r_integration_gap(facts: dict) -> str:
    """The gap line of the integrations the cases could not be tied to (HF8-17, E17): no integration unmatched gives NO line; a
    list gives one line that names them; an answer that is not known gives one line that says it could not be established - never
    the silence of an empty list (I3, AR-28). The factory cannot say which tests need them: the person who knows is asked."""
    got = facts.get("integrations")
    if not isinstance(got, dict):
        return ""
    if not got.get("readable"):
        return left_gap_line("integration access", "whether the stand's integrations matter to this story's cases could not be "
                             "established", "someone who knows which integrations this story needs") + "\n"
    names = [n for n in got.get("names") or [] if n]
    if not names:
        return ""
    return left_gap_line(", ".join(names), f"access to {', '.join(names)} is not set on the stand, and the factory could not tie it to "
                         "a case of this story - a test that needs it stops and is reported as not run",
                         "your word on which tests of this story need it, or the access") + "\n"


def _open_finding_lines(facts: dict) -> list:
    """One gap line (E17) per finding of the run that is still a question to the person AFTER gate B has recorded words (HF8-17, M-G,
    F-12 (a)): a register line active and `oracle_status == owner_question` (a corrected or withdrawn one is not). Before gate B
    the question is put at the gate itself, so nothing is added to "Left with you" then. A finding is no requirement (AR-26): the
    line stands in the code-owned block beside the answers of gate B and changes no word of the verdict. []: no register, nothing open."""
    if not (facts.get("gate_b") or {}).get("decided"):
        return []
    out = []
    for line in ((facts.get("exploratory") or {}).get("active") or []):
        if line.get("oracle_status") == "owner_question":
            question = _plain(line.get("question"))
            out.append(left_gap_line(_words(line.get("_case")) or "a finding", _plain(line.get("statement")) or EXPLORATORY_WHAT,
                                     f"your answer: {question}" if question else ""))
    return out


def _r_left_gate_b(facts: dict) -> str:
    """`### Added after gate B (from your answers)`: one line per item their gate B answers left with them - the case, its
    requirements, THEIR words and how, verbatim from the typed row. Code renders typed data and composes nothing (FR-47,
    FR-49): the same footing as the regression block below it."""
    out = ["### Added after gate B (from your answers)", ""]
    for item in _gate_b_items(facts):
        reqs = f" ({', '.join(item['requirements'])})" if item.get("requirements") else ""
        line = f"- **{item.get('ref')}**{reqs}"
        if _words(item.get("words")):
            line += f" — you said: \"{_words(item['words'])}\""
        if _words(item.get("how")):
            line += f" — {_words(item['how'])}"
        out.append(line)
    found = _open_finding_lines(facts)
    if found:
        out += ([""] if _gate_b_items(facts) else []) + found
    return "\n".join(out) + "\n"


def _branch_limits() -> tuple:
    """`(report_units_shown, unit_text_shown)` of `references/branch-accounting.json` (FR-13: data, not a literal here)."""
    import branch_accounting as BA
    return BA.limit("report_units_shown"), BA.limit("unit_text_shown")


def _branch_lines_of(facts: dict) -> list:
    """The counted `source: branches` rows of the ledger, in the ledger's order."""
    return _branch_items({"left_items": (facts.get("ledger") or {}).get("items")})


def _branch_unit_lines(item: dict, source: str) -> list:
    """The parts of the ticket (or tests) under a `source_unreconciled` row: at most `report_units_shown`, one `   - <text>` line each,
    a text over `unit_text_shown` cut with `…` (the whole text stays in the ledger's `lines`), the rest `and <k> more`. Every text
    passes `_shown`; a text with nothing left to show is the one sentence that sends the person to the source (R-8)."""
    import branch_accounting as BA
    room, long = _branch_limits()
    units = [u for u in item.get("lines") or [] if isinstance(u, str)]
    out = []
    for unit in units[:room]:
        text, _cut_words = _shown(unit)
        out.append("   - " + (BA.cut(text, long) if text else f"the wording is in the ticket; find it by {source}"))
    if len(units) > room:
        out.append(f"   and {len(units) - room} more")
    return out


def _branch_item_lines(item: dict) -> list:
    """One gap line (E17, `left_gap_line`) for a `source: branches` row, then its parts. `to_check` and `how` pass `_shown` BEFORE the
    line is made: `validate_artifacts` refuses `work/`, `cv_`, `ti_` in the whole body and the scribe cannot repair a block of code (FR-57)."""
    key = item.get("item_key") or item.get("ref")
    ref, _left = _shown(_branch_ref_words(key))
    source = "the branches of this story" if str(key).startswith("BN-") else (ref or "the ticket")     # where the person finds the wording
    fallback = f"the wording is in the ticket; find it by {source}"
    what, how = _shown(item.get("to_check"))[0] or fallback, _shown(item.get("how"))[0] or fallback
    return [left_gap_line(ref or NO_REF_WORDS, what, how, item.get("requirements") or ())] + _branch_unit_lines(item, source)


def _r_left_branches(facts: dict) -> str:
    """`### Branches left with you`: one line per counted `source: branches` row of the ledger (a branch nobody proved, a part of
    the ticket nobody placed, a file that disagrees with a requirement or that nobody looked at), in the ledger's order; code renders typed rows and
    composes nothing (FR-47, FR-49). A branch record that cannot be read at all is said `Unknown` (FR-41, AR-28), never "all accounted"."""
    out = ["### Branches left with you", ""]
    if facts.get("branches") is None and "branches" in facts["unknown"]:
        out.append(_unknown_line(facts, "branches"))
    for item in _branch_lines_of(facts):
        out += _branch_item_lines(item)
    return "\n".join(out) + "\n"


def _r_branches_not_proven(facts: dict) -> str:
    """`## Branches not proven`: only the branches a recorded answer of the person's left out (`branch_excluded_by_word`):
    `BN-n (R-m) <text>: excluded by your answer to <Q>`. They are in no other block (FR-10): the ledger carries no row for them."""
    out = ["## Branches not proven", ""]
    for rec in _excluded_by_word(facts):
        text = _shown(rec.get("to_check"))[0] or "the wording is in the ticket"
        reqs = [r for r in rec.get("requirements") or [] if r]
        # a cut made by the person's QUOTED words has no question (t-1676): the line says so in their words, never "answer to " + nothing
        by = f'excluded by your words "{_cut(str(rec.get("quote")))}"' if rec.get("quote") and not rec.get("question") \
            else f"excluded by your answer to {rec.get('question')}"
        out.append(f"- {rec.get('item_key')}" + (f" ({', '.join(reqs)})" if reqs else "") + f" {_cut(text)}: {by}")
    return "\n".join(out) + "\n"


def _excluded_by_word(facts: dict) -> list:
    return [r for r in (facts.get("branches") or {}).get("records") or [] if r.get("kind") == "branch_excluded_by_word"]


def _r_regression(facts: dict) -> str:
    """`### Regression to run (from the plan approved at gate A)`: the S3 list VERBATIM, line for line (code never composes
    it, FR-49); a plan with no regression section, or a blank one, says so in one line - the factory's gap, never a block
    (Q13 a-2, FR-57)."""
    import delivery_verdict as DV
    lines = facts["regression"]["lines"]
    out = ["### Regression to run (from the plan approved at gate A)", ""]
    out += lines if lines else [DV.GAP_LINE]
    story_tests, notes = facts["regression"].get("story_tests") or [], facts["regression"].get("notes") or []
    if story_tests:       # RG1-4: this story's own tests are listed on their own line, never as regression
        out += ["", "Tests of this story (not regression): " + ", ".join(story_tests)]
    out += ([""] if notes and not story_tests else []) + notes
    return "\n".join(out) + "\n"


def _r_verdict(facts: dict, previous: str) -> str:
    import delivery_verdict as DV
    v, reqs, bugs, cases, tests = facts["verdict"], facts["requirements"], facts["bugs"], facts["cases"], facts["tests"]
    ready = v["ready"]
    word = v["word"]
    n_items = (facts["ledger"] or {}).get("n_items", 0)
    wording = DV.head_of(word) if word in DV.WORDS else None
    if ready is None or wording is None:
        # no ledger, a word that disagrees with its own bool, or a wording file that cannot be read: UNKNOWN, said so
        # (FR-41) - never the word of the other side
        why = (facts["unknown"].get("ledger") if word is None else
               "the checks' verdict word does not agree with its own readiness flag" if word == DV.UNKNOWN else
               "the file that holds the verdict's wording cannot be read")
        head = "**Verdict: unknown.** " + (_unknown_line(facts, "ledger", "whether the delivery is ready") if word is None
                                           else f"Unknown whether the delivery is ready — {why}.")
        line = "`delivery_ready: unknown — " + (why or "no recorded results of the checks") + "`"
    elif word == "yes":
        head, line = f"**{wording}**", f"`{DV.line_of(word)}`"
    elif word == "after_checks":
        head, line = f"**{wording}**", f"`{DV.line_of(word, n_items)}`"
    else:
        reason = v["first_reason"].rstrip(".")
        head = f"**{wording}** Because {reason}."
        line = f"`{DV.line_of(word, reason=reason)}`"
    sentences = [head]
    if bugs is None:
        sentences.append("Product bugs: unknown — " + facts["unknown"].get("bugs", "not readable") + ".")
    elif bugs["confirmed"] or bugs["reproduced"] or bugs["unconfirmed"] or bugs["unreadable"]:
        def severities(state: str) -> str:
            found = sorted({r["severity"] for r in bugs["records"] if r["state"] == state and r["severity"]})
            return f" ({', '.join(found)})" if found else ""
        sentences.append(f"Product bugs: {bugs['confirmed']} confirmed{severities('confirmed')}"
                         # a segment only when there is one: a story without the step reads byte for byte as it did (HF8-16, K3)
                         + (f", {bugs['reproduced']} reproduced by the factory{severities('reproduced')}" if bugs["reproduced"] else "")
                         + f", {bugs['unconfirmed']} unconfirmed"
                         + (f", {bugs['unreadable']} unreadable" if bugs["unreadable"] else "") + ".")
    else:
        sentences.append("Product bugs: none recorded.")
    if reqs is None:
        sentences.append("Requirements: unknown — " + facts["unknown"].get("requirements", "not readable") + ".")
    else:
        c = reqs["counts"]
        # the one reader of `counts["proven"]`: None is "the ledger could not say which tests count" (`_count_by_tests`)
        proven = ("proven by tests: unknown — " + facts["unknown"].get("ledger", "the factory's record of the checks was not readable")
                  if c["proven"] is None else f"{c['proven']} proven by tests")
        sentences.append(f"Of {_n(reqs['total'], 'requirement', 'requirements')}: {proven}, "
                         # a segment only when there is one (HF8-17, M-F): the same number split, never a smaller one
                         f"{c['bug']} with a product bug, {c['unproven']} not proven"
                         + (f" ({c['bookkeeping']} of them open only in the factory's own records)" if c.get("bookkeeping") else "")
                         + f", {c['wait']} waiting for a person, {c['deferred']} deferred by your decision"
                         + (" (the register is empty)." if not reqs["total"] else "."))
        # A requirement with one proven Then and one unconfirmed one is counted among those waiting for a
        # person, never among the proven; this says why, in the words of the Then (t-250 B3).
        for item in reqs["items"]:
            if item.get("partly"):
                sentences.append(f"{item['id']} is partly proven — {'; '.join(item['partly'])}.")
    if cases is None:
        sentences.append("Cases: unknown — " + facts["unknown"].get("cases", "not readable") + ".")
    else:
        sentences.append(f"A person must check {_n(len(cases['to_check']), 'case', 'cases')}; "
                         f"{_n(len(cases['partly']), 'case is', 'cases are')} closed only partly.")
    if tests is None:
        sentences.append("Tests: unknown — " + facts["unknown"].get("ledger", "not readable") + ".")
    else:
        sentences.append(f"{_n(tests['count'], 'green test counts', 'green tests count')} as proven.")
        if tests["unverified"]:
            sentences.append(f"{_n(tests['unverified'], 'test', 'tests')} could not be verified by the code critic.")
    ledger = facts["ledger"]
    if ledger is not None and ledger["owners"].get("factory"):
        import ledger as L
        coverage = ledger.get("factory_coverage") or 0
        f = max(0, ledger["owners"]["factory"] - coverage)
        if f:
            sentences.append(f"{_n(f, 'open reason in the checks is', 'open reasons in the checks are')} the factory's own "
                             "bookkeeping — you are told about it, nothing is asked of you.")
        if coverage:
            sentences.append(L.factory_coverage_line(coverage) + ".")
    for detail in (ledger or {}).get("unowned") or []:
        sentences.append("owner not established: " + detail.rstrip(".") + ".")
    if ledger is not None and ledger["lifted_cases"]:
        sentences.append("For " + ", ".join(ledger["lifted_cases"]) + " the factory's own reducer could not settle a "
                         "result, so the behaviour stays unproven until its tests are run again.")
    if v["disagreement"]:
        sentences.append(f"The report's facts name {v['disagreement']}, which the factory's record of the checks does not hold — "
                         "the factory's own finding.")
    delivery = facts["delivery"]
    if delivery:
        sentences.append("Delivery: " + delivery["did"].rstrip(".") + ".")
    lines = [" ".join(sentences)]
    if facts["gate_b"]["decided"]:
        old = _previous_sentence(previous)
        now = head
        if old and old != now:
            lines.append(f'Changed since gate B: the verdict read "{old}"; it now reads "{now}".')
    lines += ["", line]
    return "\n".join(lines) + "\n"


def _previous_sentence(body: str) -> str:
    """The verdict sentence the previous block stood on: the baseline its change notice keeps, else its
    first line's verdict sentence."""
    lines = str(body or "").replace("\r\n", "\n").split("\n")
    for ln in lines:
        m = CHANGED_NOTICE_RE.match(ln.strip())
        if m:
            return m.group(1)
    for ln in lines:
        m = re.match(r"^(\*\*Verdict:.*?\.\*\*(?: Because .*?\.)?)(?: Product bugs:|$)", ln.strip())
        if m:
            return m.group(1)
    return ""



def _content_line(profile: str, shown: str, said: str, when: str) -> str:
    """The ONE report line of a person's word of kind content_accepted (FB-8): the tests ran although `shown` differ."""
    return (f"{PERSON_LINE_LEAD}, the {profile} tests ran although {shown} on the stand differ from this story's "
            f"({_inline_code(said) + ', ' if said else ''}{when}): a green test proves this story's build only "
            "where those files do not matter.")


def _person_build_lines(facts: dict) -> list:
    """The lines that say, per PROFILE, that its tests ran on a build the person confirmed (never "every test below"), each
    followed by what a green test of it proves; an unreadable run block is one `Unknown` line. No person's word, no line.
    The person's words are quoted VERBATIM, always, in a code span of a line that starts with `PERSON_LINE_LEAD` (F7, the
    owner's ruling): the report's text rules are not applied to them, and are applied to everything the factory wrote in the
    line. No words recorded: the line says the build was confirmed, with the date, and has no empty quotation."""
    found = facts.get("person_build")
    if found is None:
        return [_unknown_line(facts, "person_build", "whether the tests ran on a build you confirmed")] \
            if "person_build" in facts["unknown"] else []
    out = []
    for entry in found:
        profile, when = entry["profile"], entry["at"]
        said = _person_build_words(entry["words"])
        if entry.get("kind") == "content_accepted":
            # FB-8: ONE line for this kind, in place of the base line (the person did not say which build is there)
            shown = PC.shown_files(entry.get("accepted_files") or [])
            line = _content_line(profile, shown or PC.CONTENT_FILES_FALLBACK, said, when)
            if not _clean_line(line):
                line = _content_line("named", "some files", said, when)
            out.append(line)
            continue
        tail = "The factory did not read which build the stand runs."
        line = (f"{PERSON_LINE_LEAD}, the {profile} tests ran: {_inline_code(said)} ({when}). {tail}" if said else
                f"{PERSON_LINE_LEAD}, the {profile} tests ran ({when}; no words of yours are recorded). {tail}")
        if not _clean_line(line):
            # only the factory's own part can be dirty here (the profile's name is the project's configuration): name it
            # by what it is, and the line - the caveat - still stands
            profile = "named"
            line = line.replace(f", the {entry['profile']} tests ran", f", the {profile} tests ran", 1)
        out.append(line)
        if entry["tested_build"]:
            out.append(f"{PERSON_LINE_LEAD}, the {profile} tests ran on build {entry['tested_build'][:12]}, not this story's "
                       f"{entry['expected'][:12]}, by your decision: a green test proves that build only.")
    return out


def _r_proven(facts: dict) -> str:
    tests = facts["tests"]
    built = _person_build_lines(facts)
    if tests is None:
        return ("## Proven — unknown\n\n" + "".join(line + "\n" for line in built) + ("\n" if built else "")
                + _unknown_line(facts, "ledger", "which tests are proven") + "\n")
    out = [f"## Proven — {_n(tests['count'], 'green test', 'green tests')}", ""]
    if built:
        out += built + [""]
    groups: dict = {}
    for t in tests["proven"]:
        texts: dict = {}
        for rid in t["requirements"]:
            texts.setdefault(t["texts"].get(rid, ""), []).append(rid)
        what = "; ".join((", ".join(ids) + " " + text).rstrip() for text, ids in texts.items()) \
            or "no requirement is named for it"
        line = (f"- {what} ({', '.join(t['cases']) or 'no case named'}) — {t['critic']} · {t['level']}"
                + _mark_tail(t),
                f"  Note: {t['change']}." if t["change"] else "")
        groups.setdefault((t["area"], t["file"]), {}).setdefault(line, 0)
        groups[(t["area"], t["file"])][line] += 1
    if not tests["count"]:
        out += ["No green test is counted as proven.", ""]
    for (area, file), lines in sorted(groups.items()):
        out.append(f"{area or 'Area not named'} — `{file}`:")
        for (line, note), n in sorted(lines.items()):
            out.append(line + (f" [{n} variants]" if n > 1 else ""))
            if note:
                out.append(note)
        out.append("")
    for line in _reference_lines(facts):
        out += [line, ""]
    if tests["green_not_counted"]:
        n = tests["green_not_counted"]
        out += [f"{_n(n, 'more green test is', 'more green tests are')} not counted: the code critic has not approved "
                "them, or a live check of them is still owed.", ""]
    changes = facts["changes"]
    if changes and changes["unattached"]:
        for pair in changes["unattached"]:
            out.append(f"Changed after a red run, not in the list above ({', '.join(pair['cases']) or 'no case named'}): "
                       f"{pair['text']}.")
        out.append("")
    if facts["probe_debt"] and facts["probe_debt"]["count"]:
        n = facts["probe_debt"]["count"]
        out += [f"{_n(n, 'live check ran and was', 'live checks ran and were')} not receipted — the factory's own "
                "bookkeeping (owner: factory).", ""]
    elif "probe_debt" in facts["unknown"]:
        out += [_unknown_line(facts, "probe_debt", "whether live checks were left unreceipted"), ""]
    if "expectation_changes" in facts["unknown"]:
        out += [_unknown_line(facts, "expectation_changes", "which tests changed after a red run"), ""]
    if _register_shown(facts) and isinstance(facts.get("exploratory"), dict):
        formal = facts["exploratory"]["formal"]
        runs = "an unknown number of executions" if formal["executions"] is None else _n(formal["executions"], "execution", "executions")
        probes = "an unknown number of probes" if formal["probes"] is None else _n(formal["probes"], "probe", "probes")
        out += [f"Formal test execution: {_n(tests['count'], 'test', 'tests')}, {runs}. Exploratory probes: {probes}; "
                f"{_n(formal['findings'], 'finding', 'findings')} and {_n(formal['gaps'], 'gap', 'gaps')} (what the factory "
                "could not check) — not tests, not counted as proven.", ""]
    return "\n".join(out).rstrip("\n") + "\n"


def _bug_cause_lines(r: dict, number_of: dict, own: int, named_by=()) -> list:
    """The indented lines under a bug's row (t-2187, 5.9 and 8.3): for a bug that shows in 2 or more ways, its cause, how it was
    confirmed (in words), every way it shows (none cut) and the claims nobody verified ("Not verified:", FR-41); for any bug, the
    number of another row it possibly shares a cause with ("not verified"). A bug with one way and no link adds NO line: its row is
    byte-equal to what it was. The cause is read from `bug_records.cause_view` (through `traceability`): `status` is already the effective
    word, so a cause the analyst called confirmed whose basis can no longer be re-read arrives as "not established", and the phrase of how
    it was confirmed is `bug_records.cause_how_words` - the packet and the bug text say it the same way. No file name and no field name
    is printed."""
    out = []
    ways = r.get("manifestations") or []
    cause = r.get("cause") or {}
    if len(ways) >= 2:
        statement = (cause.get("statement") or "").rstrip(" .")
        status, why = cause.get("status"), (cause.get("why") or "").rstrip(" .")
        if status == "confirmed":
            out.append(f"   One cause ({BR.cause_how_words(cause) or 'confirmed'}): {statement or 'no statement given'}.")
        elif status == "unverified":
            out.append(f"   Possibly one cause (not verified{': ' + why if why else ''}): {statement or 'no statement given'}.")
        else:
            out.append("   Cause not established" + (f": {why}" if why else "") + ".")
        out.append("   Shows as:")
        out += [f"   - {line}" for line in ways]
        if cause.get("unverified"):
            out.append("   Not verified: " + "; ".join(c.rstrip(" .") for c in cause["unverified"]) + ".")
    # m1: a link reads the same from both rows - `named_by` are the rows that name this one, so a one-way link shows on both sides
    others = sorted({number_of[s] for s in r.get("same_cause_as") or [] if s in number_of and number_of[s] != own}
                    | {n for n in named_by if n != own})
    if others:
        out.append(f"   Possibly the same cause as {', '.join(str(o) for o in others)} (not verified).")
    return out


def _r_bugs(facts: dict) -> str:
    bugs = facts["bugs"]
    if bugs is None:
        return "## Product bugs — unknown\n\n" + _unknown_line(facts, "bugs") + "\n"
    head = (f"## Product bugs — {bugs['confirmed']} confirmed"
            + (f" · {bugs['reproduced']} reproduced by the factory" if bugs["reproduced"] else "")
            + f" · {bugs['unconfirmed']} unconfirmed")
    if bugs["unreadable"]:
        head += f" · {bugs['unreadable']} unreadable"
    out = [head, ""]
    if not bugs["records"]:
        names = {"task": "the story's own bugs folder", "project": "the project's bug folder (qa-factory/bugs)",
                 "drafts": "unfiled drafts"}
        seen = []
        for src in bugs["sources"]:
            seen.append(f"{names.get(src.get('home'), src.get('home'))}: "
                        + (f"{src.get('files', 0)} {_plural(src.get('files', 0), 'file', 'files')}" if src.get("exists") else "no such folder"))
        out.append("None found" + (" (looked in " + "; ".join(seen) + ")" if seen else "") + ".")
    # the row number of a bug by its id and by the stem of every draft it came from: a "possibly the same cause" link names a draft
    number_of = {}
    for n, r in enumerate(bugs["records"], start=1):
        for name in [r["id"], *r.get("draft_names", [])]:
            number_of.setdefault(name, n)
    named_by: dict = {}
    for n, r in enumerate(bugs["records"], start=1):
        for stem in r.get("same_cause_as") or []:
            if stem in number_of and number_of[stem] != n:
                named_by.setdefault(number_of[stem], set()).add(n)
    for n, r in enumerate(bugs["records"], start=1):
        parts = [r["severity"] or "severity not recorded", ", ".join(r["requirements"]), ", ".join(r["cases"])]
        # the sentence is `bug_records.reproduction_words` - one function for the report, the legend, the gate and the
        # delivery fragment (FR-10); chosen by the record's fields, never by a phrase (FR-12)
        tail = {"unconfirmed": f" ({BR.reproduction_words(r, cut=_cut)})", "reproduced": f" ({BR.reproduction_words(r)})",
                "unknown": " (its file cannot be read, so its state is unknown)"}.get(r["state"], "")
        label = " · ".join(p for p in parts if p)
        where = BR.filing_words(r.get("filing"))
        if r.get("gate_b_not_chosen"):
            where = "you did not choose this one at gate B" + (f" (your words: {_cut(r['gate_b_words'])})" if r.get("gate_b_words") else "")
        out.append(f"{n}. **{label}** — {r['title'] or 'title unreadable'} ({r['id']}){tail}" + (f" — {where}" if where else ""))
        out += _bug_cause_lines(r, number_of, n, named_by.get(n, ()))
    unattributed = sum(int(s.get("unattributed") or 0) for s in bugs["sources"])
    if unattributed:
        out += ["", f"{_n(unattributed, 'bug file in', 'bug files in')} the project's bug folder joins to no story and "
                "was not counted."]
    if bugs["outside_home"]:
        out += ["", f"{', '.join(bugs['outside_home'])} lies in the story's own folder, not in the project's bug folder; "
                "it is counted anyway. This is the factory's own bookkeeping — nothing is asked of you."]
    return "\n".join(out) + "\n"


EXPLORATORY_SECTIONS = (("observation", "### Observations"), ("unresolved_question", "### Unresolved questions"),
                        ("coverage_gap", "### Coverage gaps"))


# Our own codes (`exploratory_findings.STATUSES` / `ORACLES`) in words for a person (HF8-20): closed variety of the contract, not of
# projects, so a constant here; a test holds the keys equal to the writer's (a code the writer adds without a word is a failure).
EXPLORATORY_STATUS_WORDS = {"unverified": "not checked again", "reproduced": "seen again", "not_reproduced": "not seen again",
                            "environment_event": "caused by the test environment, not the product"}
EXPLORATORY_ORACLE_WORDS = {"documented_text_only": "the expectation stands only on documentation text",
                            "person_confirmed": "confirmed by you at gate B, for this finding only"}
WAITS_WORDS = "left open with you"           # AFTER gate B: a question still owner_question is left with the person (F5 b)
WAITS_BEFORE_WORDS = "waits for your answer"  # BEFORE gate B is decided, the report the person reads at the gate still asks it (critic t-1592 m-3)


def _plain(text) -> str:
    """`_words` through the one path-scrub survivor, `manual_evidence.plain_words`: the last scrub before a person."""
    import manual_evidence
    return manual_evidence.plain_words(_words(text))


def _probe_words(probe) -> str:
    """` (k of n tries)` from the line's OWN probe only (C-7); nothing when it has none or it is malformed. It says only that
    the factory looked again - never that it proved something."""
    if isinstance(probe, dict) and all(isinstance(probe.get(k), int) and not isinstance(probe.get(k), bool)
                                       for k in ("runs", "reproduced")):
        return f" ({probe['reproduced']} of {probe['runs']} tries)"
    return ""


def _exploratory_shots(art, line: dict) -> dict:
    """The pictures of one register line, as `_manual_shots` counts a case's: `taken` = image files its evidence names (once
    each), `provided` = those that are on disk under the story folder (`art`; None = none is checked, so none is provided),
    `files` = their paths for `screenshot_groups`. No other file (.json, .txt) is a picture (HF8-20)."""
    out: dict = {"taken": 0, "provided": 0, "files": []}
    seen: set = set()
    for ref in (line.get("evidence_refs") or []) if isinstance(line, dict) else []:
        rel = _words(ref.get("path")).replace("\\", "/") if isinstance(ref, dict) else ""
        if not rel or rel in seen or not G.is_image(rel):
            continue
        seen.add(rel)
        out["taken"] += 1
        if art is not None and (Path(art) / rel).is_file():
            out["provided"] += 1
            out["files"].append(rel)
    return out


def _status_words(line: dict) -> str:
    """The verification status in words; a missing status reads as the writer's default, an unknown code says so (FR-41)."""
    code = _words(line.get("verification_status")) or "unverified"
    return EXPLORATORY_STATUS_WORDS.get(code, "status not recorded") + _probe_words(line.get("probe"))


def _exploratory_item(line: dict, decided: bool = True) -> str:
    """One line of the register as the report prints it, in words and with no id of the register: an active line whole, a
    superseded or withdrawn one struck through with the reason beside it. The renderer translates our own codes (status,
    oracle) into words and scrubs every text field through `plain_words`; it composes no judgment (FR-47, FR-49). `decided`: gate B
    has the person's words - a question still open then is `left open with you`; before that the report asks it (`waits for
    your answer`), because the same packet puts the question to the person (FR-10)."""
    statement = _plain(line.get("statement")) or "no statement recorded"
    status = line.get("_status")
    if status in ("superseded", "withdrawn"):
        how = "corrected later" if status == "superseded" else "withdrawn"
        return f"- ~~{statement}~~ — {how}: {_plain(line.get('_why')) or 'no reason recorded'}"
    case = _words(line.get("_case"))
    out = f"- {case + ' — ' if case else ''}{statement} — {_status_words(line)}"
    oracle, question = _words(line.get("oracle_status")), _plain(line.get("question"))
    if oracle == "owner_question":                 # the owner's role is never printed: the person reading is the one asked (decision B)
        out += f" — {WAITS_WORDS if decided else WAITS_BEFORE_WORDS}" + (f": {question}" if question else "")
    elif question:
        out += f" — question: {question}"
    if oracle in EXPLORATORY_ORACLE_WORDS:
        out += f" — {EXPLORATORY_ORACLE_WORDS[oracle]}"
    if line.get("kind") == "coverage_gap" and _plain(line.get("missing_prerequisite")):
        out += f" — missing: {_plain(line['missing_prerequisite'])}"
    out += f" — why it is not a bug: {_plain(line.get('why_not_a_bug')) or 'not recorded'}"
    shots = line.get("_shots") or _exploratory_shots(None, line)       # the same words as a manual case's line (AR-13)
    return out + (f" — {G.shots_words(shots['taken'], shots['provided'])}" if shots["taken"] else "")


def _r_exploratory(facts: dict) -> str:
    """`## Exploratory findings and unresolved questions`: what the run saw and could not settle - three lists by kind, an
    active line whole, a corrected or withdrawn one struck. Not a bug, not a draft, not a triage row, not proven (FR-18,
    AR-27). A line the register holds that cannot be read is an Unknown line, never "none" (AR-28)."""
    got = facts.get("exploratory")
    unknown = "exploratory" in facts["unknown"]
    out = [G.REPORT_BLOCK_HEADINGS["exploratory"], ""]
    if unknown:
        out += [_unknown_line(facts, "exploratory", EXPLORATORY_WHAT), ""]
    lines = [line for line in (got or {}).get("lines") or [] if line.get("_status") != "withdraw"]
    if not lines:
        return "\n".join(out).rstrip("\n") + "\n"
    for kind, heading in EXPLORATORY_SECTIONS:
        mine = [_exploratory_item(line, bool((facts.get("gate_b") or {}).get("decided"))) for line in lines if line.get("kind") == kind]
        out += [heading, ""] + (mine or ["none readable" if unknown else "none"]) + [""]
    return "\n".join(out).rstrip("\n") + "\n"


GATE_NOT_RECORDED = "not recorded"
UNKNOWN_VALUES = ("", "unknown")


def _value_of(row, key: str) -> str:
    """The `value` of a question row's `before` / `now` ({value, where}), or "not recorded" when the row has none or says
    `unknown` (FR-41: an unknown is never printed as a fact)."""
    side = row.get(key) if isinstance(row, dict) else None
    value = _plain(side.get("value")) if isinstance(side, dict) else ""
    return GATE_NOT_RECORDED if value.strip().lower() in UNKNOWN_VALUES else value


def _question_line(line: dict, row, addressable: bool, twin: bool) -> str:
    """One question line of gate B, in words: the case, what it checks, what was seen, the behaviour before the change and
    now (from the question row, through `question_register.load` - the one reader), the question, and how to answer. No register
    id, no question id, no status or role code (HF8-20, the owner's rule)."""
    case, title, seen = _words(line.get("_case")), _plain(line.get("title")).rstrip(". "), _plain(line.get("statement")).rstrip(". ")
    asked = _plain(line.get("question"))
    out = f"- {case + ' — ' if case else ''}{title + '. ' if title else ''}Seen: {seen or GATE_NOT_RECORDED}. " \
          f"Before the change: {_value_of(row, 'before')}. Now: {_value_of(row, 'now')}."
    out += f" The question: {asked}" + ("" if asked.endswith(("?", ".")) else ".") if asked else ""
    if not case:
        return out + " No test case is named for it - answer in words."
    if twin:
        return out + " Two questions name this case - answer in words."
    return out + " Is this intended?"


def exploratory_bug_preface(case: str, line: dict, row) -> str:
    """The code preface of the rework a `bug` answer at gate B sends back (critic t-1592 M-a, AR-24): which finding the person called
    a bug - the case, what it checks, what was SEEN (`not recorded` when the statement cannot be read, FR-41) and the behaviour
    before the change and now, only the sides the question row knows. It states facts of the register and composes no judgment; the
    person's words follow it whole."""
    title = _plain(line.get("title")).rstrip(". ") if isinstance(line, dict) else ""
    seen = _plain(line.get("statement")).rstrip(". ") if isinstance(line, dict) else ""
    known = [f"{label}: {value}" for label, value in (("Before the change", _value_of(row, "before")), ("Now", _value_of(row, "now")))
             if value != GATE_NOT_RECORDED]
    return (f"The person called this finding a bug - {case or 'no test case named'}{': ' + title if title else ''}. "
            f"Seen: {seen or GATE_NOT_RECORDED}." + (" " + ". ".join(known) + "." if known else ""))


def exploratory_gate_parts(task_root) -> dict:
    """What gate B shows of the findings register, as parts: `{"head": [lines], "questions": [{"text", "case", "line", "qid",
    "row_hash", "addressable"}], "left_open": [case/line words], "gaps": [lines], "unknown": bool}`. A question is any ACTIVE line with
    `oracle_status == owner_question`, of any kind (a closed coverage gap keeps its question, F4); a line `person_confirmed` is no
    question; a question whose row the person left open at gate B (`deferred_to_report`, the row still holds) is not asked again
    (FR-7) but named in `left_open`. A gap is an active `coverage_gap` that is no question. `head` is [] for a story without a
    register (byte-identical packet, AC-8). Never raises: an unreadable register is one fixed sentence and no question (AR-28)."""
    unknown: dict = {}
    parts = {"head": [], "questions": [], "left_open": [], "left_open_qids": [], "gaps": [], "unknown": False}
    try:
        root = Path(task_root)
        got = _register(root, unknown)
        facts = {"exploratory": got, "unknown": unknown}
        if not _register_shown(facts):
            return parts
        parts["unknown"] = "exploratory" in unknown
        if got is None:
            parts["head"] = [f"{EXPLORATORY_HEAD}: unknown — {unknown['exploratory']}."]
            return parts
        _annotate_cases(root, got["lines"])
        parts["head"] = [f"{EXPLORATORY_HEAD}: {len(got['active'])} — not bugs, nothing is filed from them"]
        if parts["unknown"]:
            parts["head"].append(_unknown_line(facts, "exploratory", EXPLORATORY_WHAT))
        rows = T.question_rows(root)               # the one mapper of question rows (never raises: an unreadable register is {})
        asked = [line for line in got["active"] if line.get("oracle_status") == "owner_question"]
        cases = [_words(line.get("_case")) for line in asked]
        for line in asked:
            row = next((rows[r] for r in line.get("refs") or [] if isinstance(r, str) and r in rows), None)
            case = _words(line.get("_case"))
            if isinstance(row, dict) and row.get("status") == QR.DEFERRED and not QR.is_open(row):
                parts["left_open"].append(case or _plain(line.get("title")) or GATE_NOT_RECORDED)
                parts["left_open_qids"].append(str(row.get("id")))     # named once: "Open before the MR" does not list it again (m-2, FR-10)
                continue
            twin = bool(case) and cases.count(case) > 1
            parts["questions"].append({"text": _question_line(line, row, bool(case), twin), "case": case, "line": _words(line.get("id")),
                                       "qid": str(row.get("id")) if isinstance(row, dict) else "",
                                       "row_hash": str(row.get("row_hash") or "") if isinstance(row, dict) else "",
                                       "addressable": bool(case) and not twin})
        for line in got["active"]:
            if line.get("kind") == "coverage_gap" and line.get("oracle_status") != "owner_question":
                missing = _plain(line.get("missing_prerequisite"))
                case = _words(line.get("_case"))
                parts["gaps"].append(f"- {case + ' — ' if case else ''}{_plain(line.get('statement'))} — missing: {missing or GATE_NOT_RECORDED}")
        return parts
    except Exception as exc:
        print(f"report_facts: the gate B lines of the findings could not be built ({_why(exc)})", file=sys.stderr)
        return dict(parts, head=[f"{EXPLORATORY_HEAD}: unknown — {RECORD_UNREADABLE}."], questions=[], left_open=[], left_open_qids=[], gaps=[], unknown=True)


def exploratory_gate_lines(task_root, answer_block=(), parts=None) -> list:
    """The lines gate B's packet holds ABOVE its bug headline when the findings register is not empty: the count, the questions
    for the person (with `answer_block` - the closed answers and their prices, built by `gate_brief` - right under them), then the
    gaps. [] for a story without a register, so the packet is byte-identical (AC-8). Never raises. Invariant (FR-10): with a
    register, "Bugs found - none" never stands alone in the packet. What the role still decides: nothing - a person answers the
    questions at gate B; nothing here is a bug."""
    parts = parts if parts is not None else exploratory_gate_parts(task_root)
    out = list(parts["head"])
    if parts["questions"]:
        out += [f"Questions for you — is this intended? ({len(parts['questions'])})"] + [q["text"] for q in parts["questions"]]
        out += list(answer_block)
    if parts["left_open"]:
        out.append("Left open by you at gate B, not asked again: " + ", ".join(parts["left_open"]))
    if parts["gaps"]:
        out += [f"What the factory could not check ({len(parts['gaps'])})"] + parts["gaps"]
    return out


def _said(text) -> str:
    """The critic's (or the triage's) words in quotation marks, or the plain statement that they were not recorded: an absent
    field is named, never a blank or `None` (FR-41)."""
    return f'"{_words(text)}"' if _words(text) else UNSAID


SHORTENED = "(a path in the critic's words was shortened)"


def _remark_line(remark: dict) -> tuple:
    """(the critic's words of one remark, whether the filter left some out). The words go through `_shown`, the filter the
    verdict's reds use: a word the report may not carry is left out, and a part that had words but lost them all is left out
    whole - never an empty quote. A part the critic never wrote says it was not recorded (FR-41)."""
    parts, cut = [], False
    for label, key in (("the critic", "problem"), ("expected", "expected"), ("to fix", "fix")):
        said, left_out = _shown(remark.get(key))
        cut = cut or left_out
        if said or not left_out:
            parts.append(f"{label}: {_said(said)}")
    return " — ".join(parts), cut


def _test_head(test: dict) -> str:
    """A rejected test as the report names it: its function and its case; a name the filter took out is said to be so (the
    test is real, only its spelling is not shown), a name the record lacks is `not recorded`."""
    cut = test.get("name_cut")
    name = f"`{test['function']}`" if test["function"] else ("a test whose name is not shown" if cut else f"`{UNSAID}`")
    case = test["case"] or ("case not shown" if cut else "case not recorded")
    return f"- {name} ({case})" + (" (the test no longer exists)" if test.get("dead") else "") + _mark_tail(test)


def _test_lines(test: dict) -> list:
    """The lines of one rejected test: the head with the first remark, one `also` line per further remark, and the shortening
    note ONCE at the end of the row when the filter left words out. No remark recorded says so."""
    from ledger import remarks_words
    head = _test_head(test)
    remarks = [_remark_line(remark) for remark in test["remarks"]]
    if not remarks:
        return [f"{head} — {remarks_words(test)}"]
    lines = [f"{head} — {remarks[0][0]}" if remarks[0][0] else head] + [f"  also {text}" for text, _cut in remarks[1:] if text]
    if any(cut for _text, cut in remarks):
        lines[-1] += f" — {SHORTENED}" if lines[-1] == head else f" {SHORTENED}"
    return lines


def _window_lines(window: dict) -> list:
    """One line per window that closed at its limit, then the critic's remarks no rejected test of it could take (a finding
    about a file none of them lives in is still the critic's word, so it is listed here, edge 7.2). A window a later review
    cleared says so in one line; a window with no test left open says that after its limit clause."""
    import ledger as L
    cases = _shown(", ".join(window.get("cases") or window.get("tests") or []))[0] or "cases not recorded"
    if window.get("fixed"):
        return [f"Earlier the repair limit was exhausted ({cases}); a later review cleared those tests."]
    clause = L.limit_words(window.get("reason"), window.get("counted"), window.get("cap"))
    line = f"{clause[:1].upper()}{clause[1:]} ({cases}); you chose: {_words(window.get('token')) or UNSAID}."
    out = [line + (" No test is left open." if "refs" in window and not window["refs"] else "")]
    for remark in window.get("remarks") or []:
        text, cut = _remark_line(remark)
        out.append("- not about one of these tests — " + " ".join(part for part in (text, SHORTENED if cut else "") if part))
    return out


def _overflow(shown: list, total: int) -> list:
    return [f"(+{total - len(shown)} more in the factory's record of the checks)"] if total > len(shown) else []


def review_gap_lines(gaps: dict) -> list:
    """THE renderer of the tests the code critic rejected (C1-5c, F7): the report's `review-gaps` block and the gate B packet
    both call it, so the two cannot disagree (FR-10). The window lines (stage S5), then per test its name, its case and
    what the critic said, expected and asked; a test with no recorded remark says so. At most GAP_TESTS_MAX tests."""
    out = []
    for window in gaps["windows"] + gaps["fixed"]:
        if window.get("stage") == "S5":
            out += _window_lines(window)
    shown = gaps["tests"][:GAP_TESTS_MAX]
    for test in shown:
        out += _test_lines(test)
    return out + _overflow(shown, len(gaps["tests"]))


def run_gap_lines(gaps: dict) -> list:
    """The S7 half: the runs left failing at their limit, with the triage's words ("the run failed: ..."), never the
    critic's remarks an S7 window does not have (A7)."""
    out = []
    for window in gaps["windows"] + gaps["fixed"]:
        if window.get("stage") == "S7":
            out += _window_lines(window)
    shown = gaps["runs"][:GAP_TESTS_MAX]
    for run in shown:
        words, cut = _shown(run["words"])
        said = words or ("the run failed" if cut else "the run failed; the run recorded no reason")
        out.append(f"{_test_head(run)} — {said}" + (" (a path in the run's words was shortened)" if cut else ""))
    return out + _overflow(shown, len(gaps["runs"]))


def gate_b_gap_lines(ledger) -> list:
    """The gate B packet's two sections - `## Rejected by the code critic (n)` and `## Runs left failing (n)` - from a ledger
    dict, built by the renderers above so the packet and the report say one thing (FR-10). Empty when there is nothing to list
    and nothing unreadable (the packet adds no empty section); an unreadable record is said."""
    gaps = review_gaps(ledger)
    rejected, failing = review_gap_lines(gaps), run_gap_lines(gaps)
    if gaps["problem"]:
        rejected.append(f"Unknown — {gaps['problem']}.")
    out = []
    for title, count, body in (("Rejected by the code critic", len(gaps["tests"]), rejected),
                               ("Runs left failing", len(gaps["runs"]), failing)):
        if body:
            out += ["", f"## {title} ({count})"] + body
    return out


def _r_review_gaps(facts: dict) -> str:
    """`## Review gaps - n tests the code critic rejected`: code renders the ledger's typed rows and composes nothing (FR-47).
    With nothing to list the block says so in one line, never nothing; the S7 runs stand under a `### ` heading of their own
    (the block holds one `## ` section)."""
    ledger = facts["ledger"]
    over = _over_cap_lines(facts)       # the cut's fact, not the ledger's: it stands whether or not the ledger is read
    tail = ["", f"### Windows over the cap — {len(over)}", ""] + over if over else []
    if ledger is None:
        return "## Review gaps — unknown\n\n" + _unknown_line(facts, "ledger", "which tests the code critic rejected") + "\n" + (
            "\n".join(tail) + "\n" if tail else "")
    gaps = ledger["gaps"]
    body, runs = review_gap_lines(gaps), run_gap_lines(gaps)
    if gaps["problem"]:
        body.append(f"Unknown — {gaps['problem']}.")
    out = [f"## Review gaps — {_n(len(gaps['tests']), 'test', 'tests')} the code critic rejected", ""]
    out += body or ([] if runs else ["None: the code critic left no test rejected."])
    if runs:
        out += ["", f"### Runs left failing — {len(gaps['runs'])}", ""] + runs
    return "\n".join(out + tail) + "\n"


def _over_cap_lines(facts: dict) -> list:
    """One line per S5 window that went over its cap (`facts["over_cap_windows"]`, the controller's cut): the person who reads
    the report sees the consolidation the owner allowed and what it cost the window's size. No such window, or a facts dict
    without the key: no line (AR-23); the line is the report's own, never the role's digest (FR-35)."""
    return [f"Window {w['window']} over the cap: {w['cases']} {_plural(w['cases'], 'case', 'cases')}, cap {w['cap']}."
            for w in facts.get("over_cap_windows") or []]


def _r_questions(facts: dict) -> str:
    q = facts["questions"]
    if q is None:
        return "## Open questions — unknown\n\n" + _unknown_line(facts, "questions") + "\n"
    # what "Left with you" asks beside the register is counted too, in its own segment, only when there is one (HF8-17, M-B):
    # "Open questions - 0" over a section that holds four asks read as "nothing is asked of you" (run 12586)
    asks = q.get("left_asks") or 0
    out = [f"## Open questions — {len(q['listed'])}" + (f" · {asks} asked under \"Left with you\"" if asks else ""), ""]
    if not q["listed"]:
        return "\n".join(out) + "\nnone\n"
    cards = []
    for c in q["listed"]:
        note = ""
        if c["status"] == "named":
            # a line of the person's that names the id and is no token is told as that, never as "no answer" (FR-10, FR-41; GW1-42, F-6 of t-596)
            note = (f" (named in your {c['where'] or 'recorded'} words, on a line the factory did not read as an answer: \"{c['stray']}\")"
                    if c.get("stray") else f" (named in your {c['where'] or 'recorded'} words; the factory recorded no answer)")
        elif c["status"] == "with_designer":
            note = " (with the test designer; not settled yet)"
        elif c["status"] == QR.DEFERRED:
            note = " (kept on your word until this report)"
        elif c["changed"]:
            note = " (your answer was given to an earlier wording of this question)"
        cards.append(f"{c['owner'] or 'owner not named'} · {c['text'] or 'the question text is not recorded'}{note}")
    out.append(_quoted("\n".join(cards)))
    return "\n".join(out) + "\n"


def _r_requirement_items(facts: dict, key: str, heading: str, unknown_what: str, empty_text: str) -> str:
    """The one renderer of a section whose items are `**R-n** — <cause> : <risk>` lines: `facts[key]` is None (unknown, said
    as such), empty (`empty_text`, the sentence after the heading) or the list. `_r_not_proven` and `_r_skipped_by_plan`
    differ only in these words (B-309 t-422)."""
    items = facts[key]
    out = [heading, ""]
    if items is None:
        return "\n".join(out) + "\n" + _unknown_line(facts, "requirements", unknown_what) + "\n"
    if not items:
        return "\n".join(out) + "\n" + empty_text
    for i in items:
        out.append(f"- **{i['id']}** — {i['cause']} : {i['risk']}")
    return "\n".join(out) + "\n"


def _r_not_proven(facts: dict) -> str:
    """`## Not proven, and what it costs`: the checks that COULD NOT execute - a manual check that did not answer, a test
    nothing could run, a stand gap, a deferral nobody worded - each with what stopped it. What the approved plan itself
    decided not to check stands in the section above (`_r_skipped_by_plan`)."""
    return _r_requirement_items(facts, "not_proven", "## Not proven, and what it costs", "what is not proven",
                                "Nothing: every requirement has a proving result, a product bug, or was skipped by the "
                                "plan.\n")


def _r_skipped_by_plan(facts: dict) -> str:
    """`## Skipped by the plan (approved at gate A)`: the requirements whose null outcome is the plan's own decision, which
    the person approved at gate A - a plan row `skip` with its reason, or a gate A waiver with their words - each with that
    reason verbatim (owner amendment 03.10). Not proof, and not a failure to execute: a different thing from "Not proven"."""
    return _r_requirement_items(facts, "skipped", "## Skipped by the plan (approved at gate A)", "what the plan skipped",
                                "Nothing: the approved plan skipped no requirement.\n")


def _r_gate_a(facts: dict) -> str:
    g = facts["gate_a"]
    out = ["## Decided at gate A", ""]
    if not g["pipeline_known"]:
        return "\n".join(out) + "\n" + _unknown_line(facts, "pipeline", "what was decided at gate A") + "\n"
    if g["words"]:
        out.append(_quoted(g["words"]))
        # F-5 (b): an id the person's words name with no answer recorded stays under Open questions and is told here,
        # read from the one carrier of a question's status (`facts["questions"]`, never a second scan of the words).
        # GW1-42: a line that starts with the id and is no token (`Q1: a (note)`) is told as a line the factory did not read, with the
        # line (FR-41: the person did write something; "no answer" is not said of it); `QR.stray_line` is its one reader (AR-13).
        # The letter is the person's to name (the question's readings are its own): no letter is written for them (F-5 of t-596).
        for q in (facts.get("questions") or {}).get("listed", []):
            if q["status"] == "named" and q["where"] == QR.GATE_WHERE["A"]:
                stray = QR.stray_line(q["id"], g["words"])
                if stray:
                    out.append(f"Your words here name {q['id']} in a line the factory did not read as an answer: \"{stray}\". "
                               f"Write `{q['id']}: <letter>` alone on a line (the letter of the reading you choose), or say what you meant "
                               "and the conductor records it.")
                else:
                    out.append(f"Your words here name {q['id']}, but no answer to it is recorded, so it stays under Open questions.")
    else:
        out.append("The pipeline shows no decision recorded at gate A.")
    for o in g["overrides"]:
        out.append(f"- {o['stage']} · {o['match']}: \"{o['decision']}\"")
    for f in g["env_findings"]:
        stopped = g["stopped_cases"]
        if stopped is None:
            tail = "whether a case was stopped by it is unknown"
        elif stopped == 0:
            tail = "no case of this story was stopped by it"
        else:
            tail = _n(stopped, "requirement has", "requirements have") + " a case stopped on the stand - see Not proven"
        out.append(f"- Accepted at gate A, bound to no requirement or case ({f['what']}): "
                   f"\"{f['line'] or f['id']}\" — {tail}.")
    return "\n".join(out) + "\n"


def _r_gate_b(facts: dict) -> str:
    g = facts["gate_b"]
    out = ["## Decided at gate B", ""]
    if g["words"]:
        out += [_quoted(g["words"])]
    for o in g["overrides"]:
        out.append(f"- {o['stage']} · {o['match']}: \"{o['decision']}\"")
    for case, line in g["cases_named"].items():
        out.append(f"- Your words name {case}: \"{line}\"")
    homes = {"task": "the story's own bugs folder", "project": "the project's bug folder (qa-factory/bugs)",
             "drafts": "an unfiled draft"}
    if g["bugs"] is None:
        out.append("- Bugs: unknown — " + facts["unknown"].get("bugs", "not readable") + ".")
    elif g["bugs"]:
        went = [b["id"] + " (" + b["state"] + ") in " + " and ".join(homes.get(h, h) for h in b["homes"])
                for b in g["bugs"]]
        out.append("- Bugs: " + "; ".join(went) + ".")
    else:
        out.append("- Bugs: none recorded.")
    d = g["delivery"]
    out.append("- What went outward: " + (d["did"] if d else "not recorded") + ("" if not d or d["did"].endswith(".") else "."))
    return "\n".join(out) + "\n"


def _names_shown(names: list, room: int) -> str:
    """At most `room` names, each through `_shown` (a name from a ticket is data, and `validate_artifacts` refuses some spellings);
    the rest `and <k> more`. A name with nothing left to show is said so, never dropped."""
    shown = [(_shown(n)[0] or "a name that is not shown") for n in names[:room]]
    return ", ".join(shown + ([f"and {len(names) - room} more"] if len(names) > room else []))


def _attachments_line(facts: dict) -> str:
    """The `size` lines about attachments (the owner's word 30.10): `Attachments were not turned into requirements: <N> (<names>).`
    and the tail the recorded decision of gate A allows - offered / arrived later and not offered / gate not reached / offered but the
    list shown is not recorded. No attachments, or no list of sources: no line. A list that cannot be read: `Attachments: not
    known (<why>)`, never a silent nothing (FR-41). The words `checked`, `verified`, `reconciled` stand only with `not`."""
    got = facts.get("attachments")
    if got is None:
        why = (facts.get("unknown") or {}).get("attachments")
        return f"Attachments: not known ({_shown(why)[0] or 'the list could not be read'})." if why else ""
    if not got or not got.get("total"):
        return ""
    room, _long = _branch_limits()
    names = [i["name"] for t in got["tickets"] for i in t["items"]]
    head = f"Attachments were not turned into requirements: {got['total']} ({_names_shown(names, room)})."
    now = [f"{t['key']}: {i['name']}" for t in got["tickets"] for i in t["items"]]
    if not got["decided"]:
        tail = "They were not offered: the plan gate was not reached."
    elif got.get("named") is None:
        tail = "Whether the plan gate's message named them is not recorded."
    else:
        new = [n for n in now if n not in got["named"]]
        tail = (f"{len(new)} arrived after that gate and were not offered: {_names_shown(new, room)}." if new
                else "They were offered to you at the plan gate.")
    unknown_lists = [t["key"] for t in got["tickets"] if not t.get("known")]
    more = (f" Attachments of {_names_shown(unknown_lists, room)}: not known." if unknown_lists else "")
    return f"{head} {tail}{more}"


def _left_out_line(facts: dict) -> str:
    """`<N> linked tickets were left out and not reconciled: <KEY> (<why>), ...` - the kept-or-not scope of the branch accounting
    (amendment 2.3): at most `report_units_shown` tickets, the rest `and <k> more`; a ticket out of scope is never read as reconciled."""
    left = (facts.get("branches") or {}).get("left_out") or []
    if not left:
        return ""
    room, _long = _branch_limits()
    named = [f"{k} ({_shown(w)[0] or 'no reason shown'})" for k, w in left]
    return (f"{_n(len(left), 'linked ticket was', 'linked tickets were')} left out and not reconciled: "
            f"{_names_shown(named, room)}.")


def _not_obligation_line(facts: dict) -> str:
    """`<N> parts of the ticket were read as no obligation: <the reasons shown>` when N > 0 (spec 3.3): a part read as no
    obligation raises no debt, but the fact does not stay silent."""
    got = (facts.get("branches") or {}).get("not_obligation") or []
    parts = sum(n for n, _why in got)
    if not parts:
        return ""
    room, _long = _branch_limits()
    reasons = list(dict.fromkeys(_cut(_shown(why)[0] or "no reason shown", 120) for _n_parts, why in got))
    return f"{_n(parts, 'part', 'parts')} of the ticket {_plural(parts, 'was', 'were')} read as no obligation: {_names_shown(reasons, room)}."


def _r_size(facts: dict) -> str:
    s = facts["size"]
    counts = s["counts"]
    shown = lambda v: "unknown" if v is None else str(v)  # noqa: E731
    out = ["## Size", ""]
    if s["initial"]:
        # t-342 (B-271): the same words as the gate B packet's size line (`gate_brief.sizing_line`) - what the
        # requirements weigh and the cap of the size - not "computed budget ... (a weighted count of expected cases)"
        # t-357 (critic t-346 F7): each half is said in its own words, and a half that is missing is NOT "the computed
        # budget is unknown" - the owner read that number as cases. The weight known and the cap not: "no cap is recorded
        # for size <size>"; the cap known and the weight not: the weight is "not recorded"; neither: no sizing record.
        size_name = s["sizing_size"] or s["initial"]
        weighs = f"the requirements weigh {s['budget']} (each weighted by its priority and area)"
        # OH3-15: in the functions unit the size is a count of functions and the number beside it is the TEST ceiling
        cap_is = "the test ceiling is" if s.get("functions") else f"the {size_name} cap is"
        if s["budget"] is not None and s["cap"] is not None:
            budget = f" — {weighs}; {cap_is} {s['cap']}" + (f", over it by {s['overage']}" if s.get("functions") and s.get("overage") else "")
        elif s["budget"] is not None:
            budget = f" — {weighs}; no cap is recorded for size {size_name}"       # t-342 F7's exact string, parenthetical kept
        elif s["cap"] is not None:
            budget = f" — {cap_is} {s['cap']}; what the requirements weigh is not recorded"
        else:
            budget = " — what the requirements weigh is unknown (no sizing record)"
        if s.get("defect"):            # one ceiling for the person (the gate line says the same words): the planned case count
            budget = f" — {s['defect']}"
        fn = s.get("functions")
        if fn and s["sizing_size"] and s["sizing_size"] != s["initial"]:      # a re-run moved the size after the pipeline recorded it: say both
            fn = f"recorded; work/sizing.json now says {s['sizing_size']}, {fn}"
        budget = (f" ({fn})" if fn else "") + budget + (f" — {s['heavy']}" if s.get("heavy") else "")
        out.append(f"Forecast: **{s['initial']}**{budget}.")
    else:
        out.append("Forecast: unknown — no size was recorded, the pipeline holds none and there is no sizing record.")
    tail = (f"{shown(counts['testable_requirements'])} testable requirements, {shown(counts['plan_rows'])} plan rows, "
            f"{shown(counts['cases'])} cases, {shown(counts['tests'])} tests")
    out.append(f"Fact: **{s['final']}** — {tail}." if s["final"] else f"Fact: size not recorded — {tail}.")
    if s["initial"] and s["final"]:
        out.append("Difference: none." if s["initial"] == s["final"] else
                   f"Difference: {s['initial']} -> {s['final']}" + (f" ({s['reason']})" if s["reason"] else "") + ".")
    else:
        out.append("Difference: unknown.")
    out += [line for line in (_attachments_line(facts), _left_out_line(facts), _not_obligation_line(facts)) if line]
    return "\n".join(out) + "\n"


def _grounding(art: Path, unknown: dict):
    """`facts["grounding"]` (G2-5): what the grounding table saved about the change, read through `planning_contract.read_grounding` (the
    one reader; nothing is measured again). None when the story has no table (no line). `{"world": "no_diff", "source", "words"}` for a
    story whose implementation is not a diff (`null_outcome`). `{"world": "diff", "share", "coverage", "orphans", "truncated", "languages"}`
    for a diff: the two saved keys as they are (None when absent), the number of orphaned records, the files of the areas whose caller list was
    cut and the languages of the areas measured by name search. A table that exists and cannot be read is `unknown["grounding"]`
    (AR-28), never "no table"."""
    try:
        import planning_contract as PLC
        doc, problem = PLC.read_grounding(art)
    except Exception as exc:
        unknown["grounding"] = f"the table of the changed code could not be read ({_why(exc)})"
        return None
    if doc is None:
        if getattr(problem, "kind", "") != "missing":
            unknown["grounding"] = "the table of the changed code exists and cannot be read"
        return None
    data = doc.data if isinstance(doc.data, dict) else {}
    if data.get("implementation_source") != "diff":
        null = data.get("null_outcome") if isinstance(data.get("null_outcome"), dict) else {}
        return {"world": "no_diff", "source": _words(null.get("source") or data.get("implementation_source") or "absent"),
                "words": _words(null.get("words"))}
    blast = data.get("blast_radius") if isinstance(data.get("blast_radius"), dict) else {}
    areas = [a for a in blast.get("areas") or [] if isinstance(a, dict)]
    named = lambda a: _words((a.get("touched") or {}).get("file") if isinstance(a.get("touched"), dict) else "") or _words(a.get("key"))  # noqa: E731
    return {"world": "diff", "share": data.get("refactoring_share") if isinstance(data.get("refactoring_share"), dict) else None,
            "coverage": data.get("requirement_coverage") if isinstance(data.get("requirement_coverage"), dict) else None,
            "orphans": len([o for o in data.get("orphans") or [] if isinstance(o, dict)]),
            "truncated": [named(a) for a in areas if a.get("truncated") == "yes"],
            "languages": sorted({_words(a.get("language")) for a in areas if _words(a.get("language"))})}


GROUNDING_STATE_WORDS = {"not_implemented": "not implemented", "unknown": "not known", "outside_diff": "outside the change, with no place named",
                         "absent": "not stated in the table", "": "not stated in the table"}


def _r_grounding(facts: dict) -> str:
    """The lines of what the change touches (G2-5), at the end of the Size block: the refactoring share and its road (`n/a` is printed,
    not hidden), the requirement coverage with the requirements left out, the hunks that are part refactoring, the files outside the measure,
    the orphaned records, the areas measured on a cut list or by name search, and, off a diff, the source the null outcome records. Below the
    notify mark this is a line of the report and never a gate. No table: nothing. A table that cannot be read, a measure the table saved as
    `unknown` or did not save: a line that says so (FR-41), never a number that only looks right. Typed values rendered; nothing is composed
    from a role's wording (FR-47). `_regression` is not read here (RG1-1)."""
    if facts.get("grounding") is None:
        return f"{_unknown_line(facts, 'grounding', 'what the change touches')}\n" if "grounding" in facts["unknown"] else ""
    g = facts["grounding"]
    if g["world"] == "no_diff":
        return f"What the change touches: no implementation diff was read for this story ({g['source']}). {g['words']}".rstrip() + "\n"
    room, _long = _branch_limits()
    out = []
    share = g["share"]
    if share is None:
        out.append("Refactoring share: not measured — the table holds no measure of it.")
    else:
        road = {"none": "no card was needed", "notify": "above the mark at which the gate tells you", "stop": "above the mark at which the factory stopped to ask",
                "unknown": "could not be measured" + (f" ({_cut(_shown(share.get('reason'))[0], 140)}); a gap of the factory" if share.get("reason") else "; a gap of the factory")
                }.get(share.get("road"), f"road not recognised ({_words(share.get('road'))[:30]})")
        total = share.get("total")
        out.append(f"Refactoring share: {_words(share.get('percent') or 'n/a')}%" if share.get("percent") not in (None, "", "n/a") else "Refactoring share: n/a")
        out[-1] += (f" of {_n(total, 'changed production line', 'changed production lines')}" if isinstance(total, int) else "") + f" — {road}."
        mixed = share.get("mixed_hunks") or []
        if mixed:
            out.append(f"{_n(len(mixed), 'changed block is', 'changed blocks are')} part refactoring and part change of behaviour, so it counts as behaviour.")
        for key, what in (("outside_files", "Files outside the measure (tests, documents, generated)"),
                          ("pseudo_files", "Files with no changed line (renames, mode changes)")):
            names = [n for n in share.get(key) or [] if isinstance(n, str)]
            if names:
                out.append(f"{what}: {_names_shown(names, room)}.")
    cov = g["coverage"]
    if cov is None:
        out.append("Requirement coverage: not measured — the table holds no measure of it.")
    elif cov.get("road") == "unknown":
        out.append("Requirement coverage: could not be measured" + (f" ({_cut(_shown(cov.get('reason'))[0], 140)})" if cov.get("reason") else "") + "; a gap of the factory.")
    elif cov.get("reading") == "nothing_asked":
        out.append("Requirement coverage: no requirement of the story is left for this change to implement.")
    else:
        done = int(cov.get("implemented") or 0) + int(cov.get("partial") or 0)
        line = f"Requirement coverage: {done} of {cov.get('n')} ({_words(cov.get('percent'))}%)"
        left = [f"{o.get('r')} ({GROUNDING_STATE_WORDS.get(str(o.get('state') or ''), 'not known')})" for o in cov.get("outside") or [] if isinstance(o, dict)]
        out.append(line + (f"; not covered: {_names_shown(left, room)}" if left else "") + ".")
    if g["orphans"]:
        out.append(f"{_n(g['orphans'], 'record of an earlier version of the table is', 'records of earlier versions of the table are')} kept and not counted.")
    if g["truncated"]:
        out.append(f"{_n(len(g['truncated']), 'changed file was', 'changed files were')} measured on a cut list of its callers: {_names_shown(g['truncated'], room)}.")
    if g["languages"]:
        out.append(f"Changed files in a language other than Python were measured by name search only: {_names_shown(g['languages'], room)}.")
    return "\n".join(out) + "\n"


def _r_where(facts: dict) -> str:
    w = facts["where"]
    out = ["## Where to look", ""]
    for name, about in (("understanding.md", "what we verify and why"), ("test-plan.md", "the plan rows and the case texts")):
        if name in w["files"]:
            out.append(f"- {name} — sections: " + ("; ".join(w["files"][name]) or "none written"))
        else:
            out.append(f"- {name} — not found ({about})")
    if "retro.md" in w["files"]:
        out.append("- retro.md — sections: " + ("; ".join(w["files"]["retro.md"]) or "none written"))
    elif w["retro_skip_words"]:
        out.append(f"- retro.md — not written: you chose to skip it — \"{w['retro_skip_words']}\"")
    else:
        out.append("- retro.md — not written: the retro has not run")
    out.append("- the appendix below — every requirement, case and test with its result")
    if w.get("config_revert"):
        out.append("- " + w["config_revert"])
    out.append(_r_hook_signals(w.get("hook_signals"), facts["unknown"].get("hook_signals", "")))
    return "\n".join(out) + "\n"


def _r_hook_signals(signals, why: str) -> str:
    """The line of the factory's own signals during the run (K10): the number, the kinds, the journal to open; `none
    recorded` when the readable journal holds none; `unknown` with the reason when it cannot be read (FR-41)."""
    lead = "- the factory's own signals during this run: "
    if not signals or signals.get("count") is None:
        return lead + "unknown - " + (why or "the journal was not read")
    if not signals["count"]:
        return lead + "none recorded" + (
            f" ({signals['no_task_unplaced']} signal(s) with no task could not be placed: the pipeline records no start)"
            if signals.get("no_task_unplaced") else "")
    # the number and where it is kept, in words: neither the kinds nor the journal's path nor the event's name reach a person (HF8-20, P9)
    skipped = f"; {signals['skipped']} line(s) could not be read" if signals.get("skipped") else ""
    return lead + f"{_n(signals['count'], 'signal', 'signals')}, kept in the factory's own log" + skipped


# --- the report file: positions --------------------------------------------------------------------

def _headings(text: str) -> list:
    """[(offset of the line, stripped heading)] for every `## ` line outside a code fence."""
    out, fence = [], None
    for begin, content, _following in G._lines_of(text):
        shape = G._fence(content)
        if fence is None:
            if shape and not (shape[0] == "`" and "`" in shape[2]):
                fence = (shape[0], shape[1])
                continue
        elif shape and shape[0] == fence[0] and shape[1] >= fence[1] and not shape[2].strip(" \t"):
            fence = None
            continue
        if fence is None and content.strip().startswith("## "):
            out.append((begin, content.strip()))
    return out


def _section_span(text: str, prefix: str):
    """(start, end) of the section whose heading starts with `prefix`, or None. The end is the next heading
    or the start marker of the next code-owned block, whichever comes first: a block's own heading stands
    AFTER its marker line, and a span that swallowed the marker would cut it away with the section's prose."""
    heads = _headings(text)
    blocks = G.blocks_found(text)
    marks = sorted(_marker_start(text, name, span[0]) for name, span in blocks.items())
    for index, (begin, heading) in enumerate(heads):
        if heading.startswith(prefix):
            ends = [heads[index + 1][0]] if index + 1 < len(heads) else [len(text)]
            ends += [m for m in marks if m > begin]
            return begin, min(ends)
    return None


def left_with_you_text(task_root):
    """The report's `## Left with you` section whole - from its heading to the next `## ` heading, the scribe's items and
    the code-owned blocks inside it - or None when there is no report or no such section. THE reader of the section for
    everything that quotes it (the MR description, `delivery_summary`): the items there and in the report cannot differ
    (t-305 N8, F9). Reads only; raises nothing but a report that is not UTF-8 text."""
    path = Path(task_root) / REPORT_NAME
    if not path.is_file():
        return None
    text = _read_report(path)[2]
    heads = _headings(text)
    for index, (begin, heading) in enumerate(heads):
        if heading.startswith("## Left with you"):
            end = heads[index + 1][0] if index + 1 < len(heads) else len(text)
            return text[begin:end].rstrip("\n") + "\n"
    return None


def _marker_start(text: str, name: str, body_start: int) -> int:
    return text.rfind(f"<!-- facts:{name} -->", 0, body_start)


def _slot_offset(text: str, name: str) -> int:
    """Where the block `name` goes when it is missing: before the first later part of the report that is
    there (a block, a known heading or the notation line); at the end when none is."""
    order = [s for s in SLOTS]
    index = order.index(("block", name))
    blocks = G.blocks_found(text)
    headings = _headings(text)
    for kind, key in order[index + 1:]:
        if kind == "block" and key in blocks:
            return _marker_start(text, key, blocks[key][0])
        if kind == "heading":
            hit = next((b for b, h in headings if h.startswith(key)), None)
            if hit is not None:
                return hit
        if kind == "line":
            at = next((begin for begin, content, _f in G._lines_of(text) if content.startswith(key)), None)
            if at is not None:
                return at
    return headings[0][0] if name == "verdict" and headings else len(text)


def _insert_block(text: str, name: str, body: str) -> str:
    at = _slot_offset(text, name)
    piece = G.render_block(name, body) + "\n"
    if at >= len(text) and text and not text.endswith("\n"):
        piece = "\n" + piece
    if 0 < at and not text[:at].endswith("\n\n"):
        piece = "\n" + piece
    return text[:at] + piece + text[at:]


def _remove_block(text: str, name: str) -> str:
    start, end, _body = G.find_blocks(text)[name]
    begin = _marker_start(text, name, start)
    stop = text.find("\n", end)
    stop = len(text) if stop < 0 else stop + 1
    if text[stop:stop + 1] == "\n":   # the blank line that separated the block from what follows
        stop += 1
    return text[:begin] + text[stop:]


# --- conversion of a report written before the blocks (R-212.1) -------------------------------------

def _convert(text: str, gate_b_decided: bool) -> str:
    """The report with an EMPTY block where each code-owned section stood, and the prose kept. The bodies
    are filled by the ordinary refresh; the old bytes are saved to report-history by the caller."""
    for prefix, name in LEGACY_SECTIONS:
        span = _section_span(text, prefix)
        if span is None:
            continue
        piece = "" if (name == "gate-b" and not gate_b_decided) else G.render_block(name, "") + "\n"
        text = text[:span[0]] + piece + text[span[1]:]
    lines = list(G._lines_of(text))
    first = _headings(text)
    limit = first[0][0] if first else len(text)
    start = next((b for b, c, _f in lines if b < limit and re.match(r"^\s*\*{0,2}Verdict\b", c)), None)
    last = None
    for b, c, f in lines:
        if b < limit and "delivery_ready:" in c and (start is None or b >= start):
            last = f
    if start is None:
        at = _slot_offset(text, "verdict")
        if last is not None:  # a stray delivery_ready line of the old verdict would double the new one
            drop = next(b for b, c, _f in lines if b < limit and "delivery_ready:" in c)
            text = text[:drop] + text[last:]
            at = min(at, drop)
        return text[:at] + G.render_block("verdict", "") + "\n" + text[at:]
    if last is None:
        stop = next((b for b, c, _f in lines if b > start and not c.strip()), limit)
    else:
        stop = last
    return text[:start] + G.render_block("verdict", "") + text[stop:]


# --- "Left with you" ----------------------------------------------------------------------------------

def _left_items(body_lines: list) -> tuple:
    """(lines before the first item, [item line lists])."""
    head, items = [], []
    for line in body_lines:
        if ITEM_RE.match(line):
            items.append([line])
        elif items:
            items[-1].append(line)
        else:
            head.append(line)
    return head, items


def _ownership(art: Path):
    try:
        import check_delivery as CD
        lift = CD.case_ownership(art)
        return CD, (lift if lift.get("factory_cases") else None)
    except Exception:
        return None, None


def _factory_owned(item: str, CD, lift, cfg) -> bool:
    """Every ref of the item (requirement, plan row, case) is the factory's own bookkeeping. Direction of
    error: toward keeping the item - a ref that resolves to nothing is not the factory's."""
    if not lift:
        return False
    owned = set(lift["factory_cases"])

    def case_owned(case: str) -> bool:
        return any(case == o or C.case_matches(o, case, cfg=cfg) for o in owned)

    def all_owned(cases) -> bool:
        return bool(cases) and all(case_owned(c) for c in cases)

    reqs = C.REQ_ID_RE.findall(item)
    plans = CD.TS_IN_TEXT.findall(item)
    cases = C.case_ids(item, cfg=cfg)
    if not (reqs or plans or cases):
        return False
    return (all(all_owned(lift["requirements"].get(r, ())) for r in reqs)
            and all(all_owned(lift["plan_rows"].get(p, ())) for p in plans)
            and all(case_owned(c) for c in cases))


def _prune_left(text: str, art: Path, pipeline: dict, gate_b_decided: bool) -> tuple:
    """(text, [what was taken out]): the items gate B's words answered by naming their case (`close_gate_b`'s
    rule, kept), and the items all of whose refs are the factory's own (FR-3). `--write` does this; `--check`
    only names it."""
    span = _section_span(text, "## Left with you")
    if span is None:
        return text, []
    body = text[span[0]:span[1]]
    lines = body.splitlines(keepends=True)
    head, items = _left_items(lines[1:])
    cfg = C.case_config(art)
    decided = T.decided_cases(pipeline, cfg) if gate_b_decided else {}
    CD, lift = _ownership(art)
    ledger = C.load_json(C.artifact(art, "ledger.json"))
    import delivery_verdict as DV
    kept, taken, quoted = [], [], False
    for item in items:
        flat = _words(" ".join(item))
        named = [c for c in C.case_ids(flat, cfg=cfg) if c in decided]
        # ONE predicate for this prune and for `check` (t-305 N8, F10, FR-57): an item whose case is still owed - not
        # executed, handed, deferred, unverified, or no ledger row says otherwise - is never removed and is always
        # demanded, so `--write` never takes out what `--check` then asks for.
        open_item = DV.left_item_is_open(flat, ledger, cfg)
        if named and not open_item:
            taken.append(f"answered by your gate B words: {flat[:60]}")
        elif _factory_owned(flat, CD, lift, cfg) and not open_item:
            taken.append(f"all its refs are the factory's own bookkeeping: {flat[:60]}")
        elif named:
            # their words answered it by naming it, but the check is still owed (Q16, FR-8): the item stays, and their
            # own line is quoted under it - once
            said = next((_words(ln) for case in named for ln in _gate_b_sources(pipeline) if case in ln), "")
            quote = f'   Your words at gate B: "{said}"\n'
            if said and not any(row.strip() == quote.strip() for row in item):
                item = [row if row.endswith("\n") else row + "\n" for row in item] + [quote]
                quoted = True
            kept.append(item)
        else:
            kept.append(item)
    if not taken and not quoted:
        return text, []
    rebuilt = lines[0] + "".join(head) + "".join("".join(i) for i in kept)
    return text[:span[0]] + rebuilt + text[span[1]:], taken


def _gate_b_sources(pipeline: dict) -> list:
    """The lines of the person's gate B words and of their S8/S9 stage overrides, in the order `T.decided_cases` reads
    them: where a line that names a case is looked up to be quoted."""
    gate = ((pipeline or {}).get("gates") or {}).get("B") or {}
    sources = [str(gate.get("authorization_source") or "")]
    sources += [str(e.get("decision") or "") for e in C.live_stage_overrides(pipeline, ("S8", "S9"))]
    return [line for text in sources for line in text.splitlines()]


# --- write / check ----------------------------------------------------------------------------------

def _absent_line(art: Path) -> str:
    return (f"{REPORT_NAME} does not exist in {art.name}; report_facts.py refreshes the code-owned blocks of a report the "
            f"scribe has begun, it does not start one - S8's scribe writes it: `story_step.py start --task {art.name} "
            "--stage S8 --role qa-doc-scribe`")


def _read_report(path: Path):
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    return raw, bom, raw[3:].decode("utf-8") if bom else raw.decode("utf-8")


def _is_older_contract(path: Path) -> bool:
    import validate_artifacts as V
    return V.is_legacy_report(path)


def _history(art: Path, raw: bytes) -> tuple:
    """(path, created): the old report saved to state/report-history/test-report-<sha12>.md. A file with that
    sha is already there: nothing is written (the same bytes are the same history)."""
    sha = hashlib.sha256(raw).hexdigest()[:12]
    target = art.joinpath(*HISTORY_REL) / f"test-report-{sha}.md"
    if target.exists():
        return target, False
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, target)
    return target, True


def write(task_root, project_root=None) -> dict:
    """Refresh the code-owned blocks of `test-report.md`. {"ok", "lines", "history"}; `ok` False means the
    report was left untouched and `lines` are FR-1 lines naming the door."""
    art = Path(task_root)
    path = art / REPORT_NAME
    res: dict = {"ok": False, "lines": [], "history": ""}
    if not path.is_file():
        res["lines"].append(_absent_line(art))
        return res
    try:
        raw, bom, text = _read_report(path)
    except UnicodeDecodeError:
        res["lines"].append(f"{REPORT_NAME} is not UTF-8 text, so no block can be placed in it; the scribe rewrites it: "
                            f"`story_step.py start --task {art.name} --stage S8 --role qa-doc-scribe`")
        return res
    if _is_older_contract(path):
        res["lines"].append(f"{REPORT_NAME} follows the older section list (it has `## Check coverage` and no appendix), "
                            "which has no place for the code-owned blocks; the scribe writes a current report: "
                            f"`story_step.py start --task {art.name} --stage S8 --role qa-doc-scribe`")
        return res
    marked = G.has_markers(text)
    if marked and G.marker_problems(text):
        res["lines"] += [f"{REPORT_NAME}: {p}; report_facts.py does not guess where the scribe's prose ends - repair the "
                         f"markers or have the scribe redo the report: `story_step.py start --task {art.name} --stage S8 "
                         "--role qa-doc-scribe`" for p in G.marker_problems(text)]
        return res
    facts = build(art, project_root)
    pipeline = C.load_json(art / "pipeline.json")
    decided = facts["gate_b"]["decided"]
    lost: list = []   # what this write replaces, removes or converts: the old bytes are saved when any
    notes: list = []
    working = text
    if not marked:
        working = _convert(text, decided)
        lost.append("converted")
        notes.append(f"{REPORT_NAME} carried no code-owned block: its code-owned sections became blocks and the prose "
                     "outside them was kept")
        if _section_span(text, "## Decided at gate B") and not decided:
            notes.append("the section \"Decided at gate B\" of the old report was removed: gate B has no recorded "
                         "words yet, and the section held another gate's content")
    blocks = G.find_blocks(working)
    previous = blocks["verdict"][2] if "verdict" in blocks and marked else ""
    fresh = render(facts, previous)
    for name in G.REPORT_BLOCKS:
        blocks = G.find_blocks(working)
        if name not in fresh:
            if name in blocks:
                working = _remove_block(working, name)
                lost.append(name)
                if name in G.REPORT_BLOCKS_WHEN_PRESENT:
                    # the content leaves the report (FR-35 on the bytes): the history copy below saves it
                    notes.append(f"removed block `{name}`: {WHEN_PRESENT_WHY.get(name, 'its source holds nothing')}; "
                                 "the block is removed")
                else:
                    notes.append(f"removed block `{name}`: it stands only once its gate has recorded words"
                                 if name != "left-gate-b" else
                                 f"removed block `{name}`: no answer of the person's at gate B leaves a check with them")
            continue
        if name in blocks:
            if G.canonical_body(blocks[name][2]) != G.canonical_body(fresh[name]):
                working = G.replace_block(working, name, fresh[name])
                if marked:
                    lost.append(name)
                    notes.append(f"replaced block `{name}`: it differed from a fresh render (stale, or edited by hand)")
        else:
            working = _insert_block(working, name, fresh[name])
            if marked and name == "manual-checks":
                # A report written before the block existed has none (the temporal edge of t-250): it is added at
                # its place, nothing else in the file moves, and nothing is lost, so no history copy is owed.
                notes.append("added block `manual-checks`: the report was written before it existed")
            elif marked and name in G.REPORT_BLOCKS_WHEN_PRESENT:
                # a block that exists only while its source holds lines: nothing is lost by adding it, no history copy
                notes.append(f"added block `{name}`: {WHEN_PRESENT_ADDED.get(name, 'its source holds lines')}")
    working, taken = _prune_left(working, art, pipeline, decided)
    if taken:
        lost.append("left-with-you")
        notes += [f"took an item out of \"Left with you\" ({why})" for why in taken]
    # HF8-22 (L-B): the appendix is code's, refreshed after the blocks (the trace reads the same facts); a change saves the old bytes
    qa = (Path(project_root) / "qa-factory") if project_root else _qa_root(art)
    working, said = _refresh_appendix(working, art, qa)
    if said:
        notes.append(said)
        if said.startswith("replaced"):
            lost.append("appendix")
    if working == text:
        res.update(ok=True, lines=notes + ["test-report.md: every code-owned block already matches a fresh render"])
        return res
    if lost and raw:
        target, created = _history(art, raw)
        res["history"] = target.as_posix()
        notes.append(f"the previous report is saved as state/report-history/{target.name}"
                     + ("" if created else " (already there)"))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + working.encode("utf-8"))
    os.replace(tmp, path)
    res.update(ok=True, lines=notes + [f"test-report.md: code-owned blocks refreshed ({', '.join(n for n in G.REPORT_BLOCKS if n in fresh)})"])
    return res


def check(task_root, notes=None, project_root=None) -> list:
    """One FR-1 line per problem, [] when the report matches the facts. Read-only (FR-45). A report with no
    marker prints the legacy line into `notes` and passes (P8's rule)."""
    art = Path(task_root)
    path = art / REPORT_NAME
    if not path.is_file():
        return [_absent_line(art)]
    try:
        _raw, _bom, text = _read_report(path)
    except UnicodeDecodeError:
        return [f"{REPORT_NAME} is not UTF-8 text; the scribe rewrites it: `story_step.py start --task {art.name} --stage S8 "
                "--role qa-doc-scribe`"]
    if not G.has_markers(text) or _is_older_contract(path):
        if notes is not None:
            notes.append(G.LEGACY_FACTS_LINE)
        return []
    door = f"report_facts.py --task {art.name} --write"
    scribe = f"story_step.py start --task {art.name} --stage S8 --role qa-doc-scribe"
    problems = [f"{REPORT_NAME}: {p}; repair the markers or have the scribe redo the report: `{scribe}`"
                for p in G.marker_problems(text)]
    if problems:
        return problems
    facts = build(art, project_root)
    blocks = G.find_blocks(text)
    fresh = render(facts, blocks["verdict"][2] if "verdict" in blocks else "")
    for name in G.REPORT_BLOCKS:
        if name not in fresh:
            if name in blocks:
                if name in G.REPORT_BLOCKS_WHEN_PRESENT:
                    why = f"stands though {WHEN_PRESENT_WHY.get(name, 'its source holds nothing')}"
                else:
                    why = ("stands though neither an answer of yours at gate B nor a finding left a check with you" if name == "left-gate-b"
                           else "stands before gate B has recorded words")
                problems.append(f"{REPORT_NAME}: block `{name}` {why} - expected none; "
                                f"run `{door}`, which takes it out")
            continue
        if name not in blocks:
            what = "gate B has recorded words but the report has no `gate-b` block" if name == "gate-b" else \
                f"block `{name}` is missing"
            problems.append(f"{REPORT_NAME}: {what} - expected `<!-- facts:{name} -->` ... `<!-- /facts:{name} -->`; "
                            f"run `{door}` to render it")
        elif G.canonical_body(blocks[name][2]) != G.canonical_body(fresh[name]):
            problems.append(f"{REPORT_NAME}: block `{name}` differs from a fresh render of the facts (stale, or edited by "
                            f"hand) - expected the text the facts give; run `{door}`")
    for name, label in (("skipped-by-plan", "Skipped by the plan"), ("not-proven", "Not proven")):
        if name not in blocks:
            continue
        for line in blocks[name][2].splitlines():
            if not line.startswith("- "):
                continue
            left, sep, right = line[2:].partition(" : ")
            if not C.REQ_ID_RE.search(left) or not sep or not left.partition("—")[2].strip() or not right.strip():
                problems.append(f"{REPORT_NAME}: a \"{label}\" item lacks its requirement, its cause or its risk "
                                f"(`{_words(line)[:60]}`) - expected `**R-n** — <cause> : <risk>`; run `{door}`")
    span = _section_span(text, "## Left with you")
    if span:
        CD, lift = _ownership(art)
        cfg = C.case_config(art)
        ledger = C.load_json(C.artifact(art, "ledger.json"))
        import delivery_verdict as DV
        _head, items = _left_items(text[span[0]:span[1]].splitlines(keepends=True)[1:])
        flats = [_words(" ".join(item)) for item in items]
        for flat in flats:
            # the SAME predicate `_prune_left` removes by: an item whose check is still owed is never refused here
            if _factory_owned(flat, CD, lift, cfg) and not DV.left_item_is_open(flat, ledger, cfg):
                problems.append(f"{REPORT_NAME}: a \"Left with you\" item has only the factory's own bookkeeping as its "
                                f"refs (`{flat[:60]}`), and nothing is asked of you for it - expected it in the verdict's "
                                f"told-not-asked part, not here; run `{door}`, which takes it out")
        # completeness (t-305 N8, F9): every check the ledger leaves with the person has an item the scribe wrote. The
        # items born at gate B are the code's own block (`left-gate-b`, held equal to a fresh render above), the
        # regression is its block too; a scribe's EXTRA item is allowed - code demands, it does not forbid.
        for item in ledger.get("left_items") or []:
            if not (isinstance(item, dict) and item.get("counts")) or item.get("source") in ("gate_b", "branches"):
                continue      # gate B's and the branches' rows are code's own blocks (`left-gate-b`, `left-branches`), equal to a fresh render above
            if not any(_names_item(flat, item, cfg) for flat in flats):
                what = f"case {item.get('case')}" if item.get("case") else str(item.get("ref"))
                problems.append(f"{REPORT_NAME}: \"Left with you\" has no item for {what}, which the checks leave with "
                                f"you ({item.get('kind')}) - expected an item that names it (R-n, the case, `To check:` "
                                f"and `Needed:` or `How:`); the scribe writes it (`{scribe}`), then run `{door}`")
    if "regression" in blocks:
        problems += _after_regression(text, blocks["regression"], door)
    problems += _appendix_problems(text, art, (Path(project_root) / "qa-factory") if project_root else _qa_root(art))
    return problems


APPENDIX_HEADING = "## Appendix"


def _appendix_body(text: str):
    """`(span, have)` of the `## Appendix` section of a report text: its (start, end) and its BODY (after the heading line,
    newlines trimmed both sides, CRLF read as LF); `(None, "")` when there is no such section."""
    span = _section_span(text, APPENDIX_HEADING)
    if span is None:
        return None, ""
    return span, text[span[0]:span[1]].partition("\n")[2].replace("\r\n", "\n").strip("\n")


def _appendix_render(art: Path, qa: Path) -> str:
    """The appendix the trace gives NOW: `traceability.py --render`, newlines trimmed both sides. Raises what `T.build` / `T.render` raise."""
    return T.render(T.build(qa, art)).replace("\r\n", "\n").strip("\n")


def _refresh_appendix(working: str, art: Path, qa: Path) -> tuple:
    """`(text, note)`: `working` with the BODY of its `## Appendix` section replaced by the render of the trace as it stands
    (HF8-22, L-B: the appendix is code's text, `traceability.py --render`, and a bug filed after the scribe wrote it moves its
    rows - the 12586 close of S9 asked for S8 again, after the MR). Only the body changes: the heading line, the blank lines
    around the body, every other section and every block keep their bytes; a body already equal is no change (`note` ""). No
    section: nothing. A trace that cannot be built leaves the appendix untouched and says so in `note` (FR-41: not a refresh
    that did not happen, and not a write over a table nobody could compare); `check` still refuses it."""
    span, have = _appendix_body(working)
    if span is None:
        return working, ""
    try:
        want = _appendix_render(art, qa)
    except Exception as exc:
        return working, f"the appendix was not refreshed: the trace could not be built ({_why(exc)})"
    if have == want:
        return working, ""
    head, nl, rest = working[span[0]:span[1]].partition("\n")
    if rest.strip("\r\n"):
        lead = rest[:len(rest) - len(rest.lstrip("\r\n"))]
        tail = rest[len(rest.rstrip("\r\n")):]
    else:                       # a heading with no body: a blank line before and after what is put there
        lead, tail = "\n", "\n"
    crlf = "\r\n" in rest or head.endswith("\r")
    body = want.replace("\n", "\r\n") if crlf else want
    return working[:span[0]] + head + nl + lead + body + tail + working[span[1]:], \
        "replaced the appendix: it differed from a fresh render of the trace (stale, or edited by hand)"


def _appendix_problems(text: str, art: Path, qa: Path) -> list:
    """HF2-6b (RD1-8, F-4 (a)), HF8-22 (L-B): the appendix is the `traceability.py --render` text and code owns it. The BODY of
    the `## Appendix` section is compared with a render NOW. Equal: no problem. Different: ONE line, worded as a stale block
    is (`block `appendix` differs from a fresh render`, the mark `stage_done.report_problems` reads), whose door is `--write`
    (`_refresh_appendix` renders it again) - never the scribe: the S9 exit rebuilds it itself and S8 is not reopened for a block
    of code. No section: no check (the slots refuse it). Reads only (FR-45); a trace that cannot be built is one line, not a
    pass (FR-59)."""
    span, have = _appendix_body(text)
    if span is None:
        return []
    door = f"report_facts.py --task {art.name} --write"
    try:
        want = _appendix_render(art, qa)
    except Exception as exc:
        return [f"{REPORT_NAME}: the appendix could not be compared: {_why(exc)} - expected a trace the factory can build; "
                f"run `traceability.py --task {art.name} --check`"]
    if have == want:
        return []
    return [f"{REPORT_NAME}: block `appendix` differs from a fresh render of the trace (stale, or edited by hand) - expected "
            f"exactly what `traceability.py --task {art.name} --render` prints under the heading; run `{door}`"]


def _names_item(flat: str, item: dict, cfg) -> bool:
    """Does this scribe item name the ledger's item: its `ref` as a WHOLE word (an R-n, a case id, a `BN-n`), the case by
    `contract.case_matches`, or any test of the item by its function name (a presence check of ids, FR-12). The whole word
    is `(?<![\\w-])ref(?![\\w-])`: `R-3` is no part of `BR-3` and `BN-3` names no requirement (HF8-17, E17 - on `**BR-3** (R-7)`
    the item `BR-3` was not found and the item `R-3`, which does not exist, was)."""
    def whole(name) -> bool:
        return bool(name) and re.search(rf"(?<![\w-]){re.escape(str(name))}(?![\w-])", flat) is not None
    case = str(item.get("case") or "")
    if case:
        if any(c == case or C.case_matches(c, case, cfg=cfg) or C.case_matches(case, c, cfg=cfg)
               for c in C.case_ids(flat, cfg=cfg)):
            return True
    elif whole(item.get("ref")):
        return True
    return any(whole(name) for name in item.get("tests") or [])


def _after_regression(text: str, found: tuple, door: str) -> list:
    """A line between the regression block's end marker and the next heading or marker stands OUTSIDE "Left with you" (the
    block is the section's last part): the scribe's prose goes above it."""
    start, end, _body = found
    stop = text.find("\n", end)
    tail = text[stop + 1:] if stop >= 0 else ""
    for line in tail.splitlines():
        if line.strip().startswith("## ") or line.startswith("<!-- facts:") or line.startswith("<!-- /facts:"):
            break
        if line.strip():
            return [f"{REPORT_NAME}: the line `{_words(line)[:60]}` stands outside \"Left with you\", after the regression "
                    f"block - move it above the regression block (the scribe's items go before the code-owned blocks); "
                    f"run `{door}` after"]
    return []


# --- command line ---------------------------------------------------------------------------------------

def main(argv=None) -> int:
    C.force_utf8()
    ap = argparse.ArgumentParser(description="The facts of test-report.md, and its code-owned blocks")
    ap.add_argument("--screenshots", action="store_true",
                    help="print, for the chat, the paths of the manual checks' screenshots (never put them in the report)")
    T.add_story_options(ap, "TP1-13797")
    ap.add_argument("--write", action="store_true", help="refresh the code-owned blocks of test-report.md")
    ap.add_argument("--check", action="store_true", help="read-only: exit 1 with one line per problem")
    ap.add_argument("--json", action="store_true", help="print the facts as JSON and nothing else")
    args = hooklib.exact_options(ap).parse_args(argv)
    story = T.story_of(args, "report_facts.py")      # the story first (CX1-18): a phantom is a refusal of the call, exit 2
    if story is None:
        return 2
    qa, art = story
    if args.screenshots:      # the chat text only; it writes nothing and shares no mode with the others
        print(screenshots_chat_text(art))
        return 0
    # With --json stdout carries the JSON only (FR-14); every human line goes to stderr.
    human = sys.stderr if args.json else sys.stdout
    code = 0
    if args.write:
        result = write(art, qa.parent)
        for line in result["lines"]:
            print(line, file=human)
        code = 0 if result["ok"] else 1
    if args.check and code == 0:
        notes: list = []
        problems = check(art, notes, qa.parent)
        for line in notes + problems:
            print(line, file=human)
        code = 1 if problems else 0
    if args.json:
        print(json.dumps(build(art, qa.parent), ensure_ascii=False, sort_keys=True, indent=2, default=str))
    elif not (args.write or args.check):
        facts = build(art, qa.parent)
        for name, body in render(facts).items():
            print(G.render_block(name, body), end="\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
