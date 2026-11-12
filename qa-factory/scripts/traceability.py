"""The traceability table — one row per requirement x case x Then group, built by code.

On TP1-15045 the person was handed the machine ledger instead of an answer: its first
line read "24 reasons on the product side" when about twenty of them were symptoms of the
factory's own defect, "verified 0" stood beside eighteen green tests, and the one paragraph
that carried a real decision was repeated eleven times. The ledger is a machine input; what a
person reads is this table — everything the story meant to check, each line with a result in
words they already know and a one-line basis for that result.

The row vocabulary lives in `contract.py` (TRACE_RESULTS / TRACE_LEVELS / TRACE_SHAPES /
TRACE_ROW_FIELDS), because the dashboard renders the same rows in its story expand. Nothing
here invents a status word.

Dead records never enter a row: a manifest test whose `note`/`critic_note` starts with
`SUPERSEDED DUPLICATE` (delinked aggregates the automator left behind), a run row that is a
bare case key with no manifest instance behind it (the join failure after the manifest schema
changed mid-story), and an `unresolved[]` row whose detail starts with `STALE`. On 15045 those
three classes alone accounted for six duplicate ledger rows and one "TC-014 blocked_by_env" the
person was asked to decide about twice.

  traceability.py --task TP1-15045 --write     # work/traceability.json
  traceability.py --task TP1-15045 --render    # the report's appendix, verbatim
  traceability.py --task TP1-15045 --check     # exit 1 on a missing R or TC
  traceability.py --task TP1-15045 --oracles   # where each Then's expected value comes from (JSON)
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import acceptance as AC  # noqa: E402  (`red_by_own_row`: the one predicate of "this instance is red by THIS case's row")
import bug_records as BR  # noqa: E402
import contract as C  # noqa: E402
import grammar as G  # noqa: E402
import hooklib  # noqa: E402
import ledger as L  # noqa: E402  (the one spelling of `expectation_unconfirmed`; ledger imports this module lazily)
import question_register as QR  # noqa: E402

SCHEMA_VERSION = 1
DEAD_NOTE_PREFIX = "SUPERSEDED DUPLICATE"
_LEVELS_NOTE_SHOWN = False   # the "proof levels unavailable" note is printed once per process
STALE_DETAIL_PREFIX = "STALE"
# The register's own table: `| R | Requirement ... |`.
REGISTER_HEADING = "## Register"
# The strategist writes the questions the plan could not answer here; a requirement that got
# no plan row is `not planned` and this is where its reason is written down in words.
QUESTION_PACKET_HEADING = "## Gate A question packet"
THEN_ITEM_RE = re.compile(r"^\s*(\d+)\.\s+(.*)$")
_NUM_RE = re.compile(r"(\d+)")
# The normalized run-result words (`contract.result_status`) that are red; the same pair `run_history.RED_STATUSES` holds.
_RED_RUN_STATUSES = ("failed", "error")
# What a person reads under the table. Kept beside the rows in traceability.json so the
# dashboard and the report never drift into two different legends.
LEGEND = {
    "pass": "every test of the row is green in the current run, or the check an agent made by hand "
            "was recorded as passed",
    "bug": "a product defect; the bug record is named beside it",
    "wait": "handed to a person - planned manual, automated where the factory has no access, "
            "or an expected value nobody confirmed yet (it waits for your answer)",
    "blocked": "the stand stops the test before its own checks, or the code critic rejected the test and has not "
               "reviewed the change",
    "not run": "no green or red result of the current run is recorded for it; the basis says what the run "
               "recorded, if anything",
    "unreachable": "the scenario cannot occur in the product as it is built",
    "deferred": "a person's recorded decision put it aside",
    "not planned": "a register requirement no plan row plans: none names it, or its plan row says it "
                   "cannot be verified",
}
# A plan row with no case of its own speaks for the requirements it names through its disposition
# (B-211 F9/R-new-F32): `skip` is a decision put aside, `unverifiable` is a requirement nothing
# observable can prove. Closed variety kept as data at the top of the module (FR-13); any other
# disposition of a case-less row keeps today's reading, `not planned` with the plan prose's reason.
CASELESS_PLAN_RESULTS = {"skip": "deferred", "unverifiable": "not planned"}
# the two plan dispositions that name WHO checks a case by hand (they are also the two manual `TRACE_LEVELS`)
MANUAL_LANES = ("manual-agent", "manual-human")
# The contract's error for a row with no case; a plan-row row (below) is the one row that has none.
_NO_CASE_ERROR = "trace.case is empty"
# The fields of a bug draft that name the requirement it breaks (HF8-22): the only places a requirement id is read from a
# draft the filed bug names; `actual`, `title` and the rest are prose.
DRAFT_REQUIREMENT_FIELDS = ("requirement", "requirements", "violates", "triage_ref")
# What an answered question's line in the appendix or the report carries (R-216a.1): said in the
# words of the place the person answered, which is the only place this suffix is true of.
ANSWERED_SUFFIX = " — answered at gate A"
ANSWERED_WHERE = "gate A"


def _dumped_for_ids(value) -> str:
    """`json.dumps` of a draft for `REQ_ID_RE`, with the dump's own escapes (`\\n`, `\\r`, `\\t`) turned into a space: in dumped
    text a newline is the two characters backslash and `n`, and the `n` would stand before `R-2` as a letter of a longer word
    (GW1-1 G-1: `R-1\\nR-2` lost `R-2`, and a filed bug lost a violated requirement). The edge of the id is still whole words."""
    return re.sub(r"\\[nrt]", " ", json.dumps(value, ensure_ascii=False))


def _numeric_key(value: str) -> tuple:
    """`R-10` sorts after `R-9`, and `speakers/TC-7` after `TC-7` - digits compare as digits."""
    text = str(value or "")
    m = _NUM_RE.search(text)
    return (0 if m else 1, int(m.group(1)) if m else 0, text)


def _one_line(text, limit: int = 110) -> str:
    """One short line. A basis a person has to scroll is a basis they do not read."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rsplit(" ", 1)[0]
    return (cut or flat[:limit]).rstrip(",;.:") + " ..."


def _first_sentence(text, limit: int = 110) -> str:
    flat = " ".join(str(text or "").split())
    for stop in (". ", "; ", " - ", " -- "):
        head, sep, _ = flat.partition(stop)
        if sep and len(head) >= 20:
            flat = head
            break
    return _one_line(flat, limit)


# --- inputs ----------------------------------------------------------------------------------

def register_requirements(artifacts: Path) -> list:
    """[{id, text}] in register order, from `work/requirements-register.md`."""
    path = C.artifact(Path(artifacts), "requirements-register.md")
    out, seen = [], set()
    for cells in C.md_table(C.read_text(path), REGISTER_HEADING)[1:]:
        if not cells:
            continue
        rid = C.strip_cell(cells[0])
        if not C.REQ_ID_RE.fullmatch(rid) or rid in seen:
            continue
        seen.add(rid)
        out.append({"id": rid, "text": C.strip_cell(cells[1]) if len(cells) > 1 else ""})
    return out


def case_thens(path: Path) -> dict:
    """{n: text} of the case's `## Then` clauses. The report quotes a clause, never its
    number: "see item 2" is exactly the cross-reference the person asked us to stop writing."""
    out: dict = {}
    inside = False
    for line in C.read_text(Path(path)).splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            inside = stripped.lower().startswith("## then")
            continue
        if not inside:
            continue
        m = THEN_ITEM_RE.match(line)
        if m:
            out[int(m.group(1))] = " ".join(m.group(2).split())
    return out


def is_dead_test(entry: dict) -> bool:
    """A manifest row the automator delinked instead of deleting (`manifest_put.py` forbids a
    fragment silently dropping a row). It names no case any more and proves nothing."""
    for field in ("note", "critic_note"):
        if str(entry.get(field) or "").lstrip().startswith(DEAD_NOTE_PREFIX):
            return True
    return False


def is_stale_unresolved(entry: dict) -> bool:
    return str(entry.get("detail") or "").lstrip().startswith(STALE_DETAIL_PREFIX)


def live_tests(manifest: dict) -> list:
    return [t for t in C.manifest_tests(manifest) if not is_dead_test(t)]


def live_unresolved(manifest: dict) -> list:
    return [u for u in C.manifest_unresolved(manifest) if not is_stale_unresolved(u)]


def instances_by_id(manifest: dict) -> dict:
    """Every spelling one live instance answers to -> its manifest entry."""
    out: dict = {}
    for entry in live_tests(manifest):
        for alias in C.instance_id_aliases(entry):
            out.setdefault(alias, entry)
        selector = str(entry.get("selector") or "")
        if selector:
            out.setdefault(C.instance_id(selector, C.instance_parameter(
                selector.partition("[")[2].rstrip("]"))), entry)
    return out


def _draft_cause_facts(artifacts: Path, data, shows: list, cause: dict, linked: list) -> tuple:
    """`(shows, cause, linked)` of a record after reading one more of its drafts (t-2187, rows 5.5 and 5.9). The FIRST draft that
    has each fact keeps it (a filed bug names one draft in practice; a second one never overwrites the first).

    `shows`: `bug_records.manifestation_summary(data)`, one line per manifestation (the reader of the lines is the bug reader's).
    `cause`: `{}` for a draft with no `mechanism` object (an old draft: read as today), else `{status, statement, why, by_code,
    runs, by_person, unverified}` printed from `bug_records.cause_view` - the ONE reader of the cause facts the bug text and the gate B
    packet print from too (M3): `status` is the EFFECTIVE word (`confirmed` only when the basis still stands: an entry that cannot be
    re-read makes the whole cause `unknown`, never a pass, FR-41); `runs` counts distinct start states by the one rule.
    `linked`: the file stems named by `possibly_same_cause[].draft` (`bug_records.cause_links`), which the report turns into row numbers.
    Presence and cross-references only: whether the run discriminates is the analyst's judgment, accepted by the scribe (AR-29)."""
    if not isinstance(data, dict):
        return shows, cause, linked
    shows = shows or BR.manifestation_summary(data)
    view = BR.cause_view(artifacts, data)
    if not cause and view:
        cause = {"status": view["status"], "statement": _one_line(view["statement"], 400), "why": _one_line(view["why"], 400),
                 "by_code": view["by_code"], "runs": view["runs"], "by_person": view["by_person"],
                 "unverified": [_one_line(says, 300) for says in view["unverified"]]}
    if not linked:
        linked = [Path(link["draft"]).stem for link in BR.cause_links(data)]
    return shows, cause, linked


def story_bug_records(root: Path, artifacts: Path) -> dict:
    """{"records": [...], "outside_home": [...], "sources": [...]} - the bugs of THIS story, read by
    `bug_records.story_bugs` (the one reader of which bug files belong to a story: the story's own
    `bugs/` folder, plus the project's `qa-factory/bugs/` files whose `gate_b_decision_id` is one of
    this story's gate B decisions, plus the drafts S8 has not filed yet).

    Until B-206 this function read every file of the project's `qa-factory/bugs/` for every story:
    TP1-13797's report said "no product bug is recorded" while `BUG-1.md` lay in the story's own
    folder, and the headline of any story counted its neighbours' bugs (case ids and `BUG-n` are
    numbered per story). `root` is the project's `qa-factory` folder (`resolve` below), so its parent
    is the project root `story_bugs` joins the project home on.

    Each record is the reader's own ({id, title, confirmation, state, filed, paths, homes,
    gate_b_decision_id, notes}) plus what a row is joined on: `cases` and `requirements`, read from the
    bug file's front matter (the filed file wins over its draft) or, for a draft, from the draft. A
    filed record keeps the naming over its draft: on 15045 the report named a row
    `tc009-tc014-404-error-details-help-not-null` while `BUG-3` sat in `qa-factory/bugs/` saying the
    same thing, and a draft id is not something a person can open. `outside_home` lists the records
    that lie ONLY in the story's folder: counted, and the report names them (owner, 30.09).

    `confirmation` comes from `contract.bug_confirmation`, so a bug filed before 0.7.16 reads
    as `confirmed_by_person` and nothing already delivered changes colour under the reader.
    A missing bugs directory is an empty answer, never an exception (the reader names what it looked at)."""
    artifacts = Path(artifacts)
    found = BR.story_bugs(artifacts, project_root=Path(root).parent)
    records = []
    for record in found.get("records") or []:
        paths = [Path(p) for p in record.get("paths") or []]
        filed_file = next((p for p in paths if p.suffix.lower() == ".md"), None)
        shows, cause, linked = [], {}, []
        if filed_file is not None:
            head = C.read_text(filed_file).split("\n## ", 1)[0]
            cases, requirements = C.case_ids(head), C.REQ_ID_RE.findall(head)
            # HF8-22 (L-A): the filed file's front matter does not copy what its draft says (12586: `BUG-1.md` held
            # `violates: requirement:R-6` and no case id, the draft `"case": "TC-004"`), so the cases and requirements
            # are the UNION of the head and of the drafts it names. Requirements from a draft come ONLY from its
            # structural fields (`DRAFT_REQUIREMENT_FIELDS`): an `R-99` mentioned in its `actual` is prose, not a link
            # (the direction of error is toward NOT calling a requirement "with a bug", as `confirmed_bug_of` does). A
            # draft that is not there adds nothing; the head alone is read as before.
            for ref in record.get("source_drafts") or []:
                data = BR._draft_of(artifacts, ref)
                if not data:
                    continue
                stem = Path(ref).stem
                # t-2187 (5.5, AR-13): the cases of a draft are `bug_records.draft_cases` - `case`, `cases` and every manifestation's
                # `case`; passed through `case_ids` here, where the artifacts config is held (spec 17, D3)
                cases = list(dict.fromkeys(cases + C.case_ids(
                    " ".join(BR.draft_cases(data)) or f"{stem} {stem.upper()}", artifacts)))
                structural = _dumped_for_ids([data.get(field) for field in DRAFT_REQUIREMENT_FIELDS if data.get(field)])
                requirements = list(dict.fromkeys(
                    requirements + C.REQ_ID_RE.findall(structural) + BR.draft_requirements(data)))
                shows, cause, linked = _draft_cause_facts(artifacts, data, shows, cause, linked)
        elif paths:
            data = C.load_json(paths[0])
            # A draft with no case field is read by its file name, in both spellings: the stem as
            # written and upper-cased (a draft file is `tc-009.json`, a project-form id is upper-case
            # letters plus digits, and a form with lower-case literals reads the stem as written).
            cases = C.case_ids(" ".join(BR.draft_cases(data))
                               or f"{paths[0].stem} {paths[0].stem.upper()}", artifacts)
            requirements = C.REQ_ID_RE.findall(_dumped_for_ids(data))
            shows, cause, linked = _draft_cause_facts(artifacts, data, shows, cause, linked)
        else:
            cases, requirements = [], []
        # the stems of the draft files this bug came from: how a "possibly the same cause" link finds the row of the draft it names
        names = [Path(str(ref)).stem for ref in record.get("source_drafts") or []] or (
            [paths[0].stem] if paths and filed_file is None else [])
        records.append(dict(record, title=_one_line(record.get("title")), cases=cases,
                            requirements=requirements, manifestations=shows, mechanism=cause,
                            possibly_same_cause=linked, draft_names=names))
    return {"records": records, "outside_home": list(found.get("outside_home") or []),
            "sources": list(found.get("sources") or [])}


def bug_records(root: Path, artifacts: Path) -> list:
    """The records of `story_bug_records` - `[{id, title, confirmation, state, filed, paths, homes,
    gate_b_decision_id, notes, cases, requirements}]`; the signature every caller already has."""
    return story_bug_records(root, artifacts)["records"]


def _question_statuses(artifacts: Path) -> list:
    """The story's questions with their status (`question_register.load`), or [] when the register
    cannot be read: a report never crashes over its own question file (P1), and a question whose
    status is unknown gets no suffix (the allowed direction of error)."""
    try:
        return list(QR.load(artifacts).get("questions") or [])
    except (OSError, ValueError, RuntimeError):
        return []


def mark_answered(text, questions: list) -> str:
    """`text` with " - answered at gate A" appended when it cites a question the person answered at
    gate A (R-216a.1). The role's own words stay whole (FR-35): nothing is cut or reworded.

    A question is cited by its register id, matched with the register's own matcher
    (`question_register._mention`: `Q1` is not in `Q10`, a URL, a path or a file name), or by another
    spelling of it that stands in the person's own line about it: the plan calls the same question
    `Q-R14`, the register `Q1`, and the person wrote "Q1 / Q-R14: ...". Such a spelling is a token of
    that line that has a digit, begins with the register id's first letter and is not itself a register
    id. The direction of error is toward NO suffix: only `answered` counts (`named` is an id the person
    mentioned, not a question settled, and `open` is neither), only an answer recorded at gate A is
    that place, and a text that also cites a register question that is not answered that way gets none. An answer
    that no longer holds - the row changed since the person saw it (`changed_since_answer`), a `before` value nobody
    wrote down - is not an answer: `question_register.settled` is the one predicate (HF2-6, AR-13)."""
    flat = str(text or "")
    if not flat.strip() or ANSWERED_SUFFIX.strip() in flat:
        return flat
    by_id = {str(q.get("id") or ""): q for q in questions or [] if isinstance(q, dict) and q.get("id")}

    def answered_here(question: dict) -> bool:
        return question.get("status") == "answered" and QR.settled(question) and question.get("where") == ANSWERED_WHERE
    cited_answered = False
    for qid, question in by_id.items():
        if not QR._mention(qid).search(flat):
            continue
        if answered_here(question):
            cited_answered = True
        else:
            return flat
    for qid, question in by_id.items():
        if not answered_here(question):
            continue
        for token in str(question.get("line") or "").replace("/", " ").split():
            token = token.strip(".,;:()[]{}*'\"`")
            if (token and token != qid and token not in by_id and any(c.isdigit() for c in token)
                    and token[0] == qid[0] and QR._mention(token).search(flat)):
                cited_answered = True
    return flat + ANSWERED_SUFFIX if cited_answered else flat


def bug_groups(records: list) -> dict:
    """{confirmation: [id]} over the bug records, in the contract's own order.

    TP1-15045: four bugs were shown as one list of four, and two of them were the tests'
    own defects nobody had reproduced. The two groups are kept apart everywhere a person reads
    a count, and an unconfirmed bug never counts toward what the story found."""
    groups = {name: [] for name in C.BUG_CONFIRMATIONS}
    for record in records or []:
        groups.setdefault(bug_word(record), []).append(str(record.get("id") or ""))
    return {name: ids for name, ids in groups.items() if ids}


def bug_word(record) -> str:
    """The step of one bug record as the tables read it: the contract's word, except that `unknown` (an unreadable bug file,
    `bug_records.UNKNOWN`) is its OWN group - not a confirmation word, and since HF8-16 not read as `confirmed_by_person`
    nor as `unconfirmed` either (FR-41: an unknown is never reported as a fact)."""
    if isinstance(record, dict) and str(record.get("confirmation") or "").strip() == BR.UNKNOWN:
        return BR.UNKNOWN
    return C.bug_confirmation(record)


def bug_headline(records: list) -> str:
    """"Product bugs — 1 confirmed · 1 reproduced by the factory · 3 unconfirmed", the one line the report and the gate
    share. A segment appears only when its count is above 0; "none" only when there is nothing of any kind."""
    groups = bug_groups(records)
    reproduced = len(groups.get(BR.REPRODUCED) or [])
    unconfirmed = len(groups.get("unconfirmed") or [])
    unreadable = len(groups.get(BR.UNKNOWN) or [])
    confirmed = sum(len(ids) for name, ids in groups.items() if name not in ("unconfirmed", BR.REPRODUCED, BR.UNKNOWN))
    if not (confirmed or reproduced or unconfirmed or unreadable):
        return "Product bugs — none."
    parts = []
    if confirmed:
        parts.append(f"{confirmed} confirmed")
    if reproduced:
        parts.append(f"{reproduced} reproduced by the factory")
    if unconfirmed:
        parts.append(f"{unconfirmed} unconfirmed")
    if unreadable:
        parts.append(f"{unreadable} unreadable")
    return "Product bugs — " + " · ".join(parts) + "."


# --- the expected value of a Then (P20, t-227c) ----------------------------------------------------

def question_rows(artifacts: Path) -> dict:
    """{question id: register row with `status`, `reading`, `before`, `now`} - `_question_statuses` keyed."""
    return {str(q.get("id") or ""): q for q in _question_statuses(artifacts) if isinstance(q, dict) and q.get("id")}


def then_oracle_states(text: str, questions: dict) -> list:
    """`contract.resolve_then_oracle` of every `then_oracles` entry of ONE case text - THE reader the
    code critic's `invented_expectation`, the coverage projection and `--oracles` share (C6/FR-16): an
    `unknown` Then whose question is answered by a reading letter reads `person` with the matching
    `question_thens` text; everything else stays as written, and the error direction is toward
    `open`. A case with no `then_oracles` line (it predates t-227) gives `[]`: nothing to read."""
    entries, _problem = C.then_oracles_from_text(text)
    asked, _ = C.question_thens_from_text(text)
    out = []
    for entry in entries or []:
        ref = str(entry.get("ref") or "").strip()
        match = next((q for q in asked or [] if q.get("then") == entry.get("then")
                      and str(q.get("question") or "").strip() == ref), None)
        out.append(C.resolve_then_oracle(entry, (questions or {}).get(ref), match))
    return out


def case_oracles(artifacts: Path) -> dict:
    """{case key: {"thens": [resolved oracle of each Then], "problem"?}} for every case of the story
    (`--oracles`). A case whose `then_oracles` line is absent (written before t-227) has `thens: []`; one
    whose line cannot be read says so under `problem` instead of raising - the caller is a role that
    needs the move, not a traceback (P1)."""
    questions = question_rows(artifacts)
    out = {}
    for key, meta in C.case_index(artifacts).items():
        text = C.read_text(Path(meta["path"])) if meta.get("path") else ""
        _entries, problem = C.then_oracles_from_text(text)
        out[key] = {"thens": then_oracle_states(text, questions), **({"problem": problem} if problem else {})}
    return out


def unconfirmed_basis(question, qid: str) -> str:
    """The one line a person reads for a Then that nobody confirmed: it was not executed, which
    question holds it, and what the behaviour was before and is now (the question's own `before` /
    `now`; `before: not recorded` when the question shows none - never a guess, FR-41)."""
    def side(name: str) -> str:
        shown = (question or {}).get(name)
        value = " ".join(str(shown.get("value") if isinstance(shown, dict) else "").split())
        return f"{name} {_one_line(value, 30)}" if value else f"{name}: not recorded"
    where = f"{qid}: {side('before')}, {side('now')}" if qid else "no question is named for it"
    return f"expectation unconfirmed, check not executed — {where}"


# --- one outcome -------------------------------------------------------------------------------

class Story:
    """Everything one story recorded, read once. A reader that re-opens the manifest per row
    turns a 15-requirement story into 300 file reads."""

    def __init__(self, root: Path, artifacts: Path):
        self.root = Path(root)
        self.artifacts = Path(artifacts)
        self.manifest = C.load_json(C.artifact(self.artifacts, "automation-manifest.json"))
        self.report = C.load_json(C.artifact(self.artifacts, "run-report.json"))
        self.triage = C.load_json(C.artifact(self.artifacts, "triage.json"))
        self.pipeline = C.load_json(self.artifacts / "pipeline.json")
        self.plan_rows = C.parse_plan(C.artifact(self.artifacts, "test-plan.md"))
        self.plan_by_ts = {r.get("ts"): r for r in self.plan_rows}
        self.cases = C.case_index(self.artifacts)
        self.case_levels = C.case_levels(self.artifacts)
        self.instances = instances_by_id(self.manifest)
        read = story_bug_records(self.root, self.artifacts)
        self.bugs = read["records"]
        self.bugs_outside_home = read["outside_home"]
        self.questions = _question_statuses(self.artifacts)
        self.question_by_id = {str(q.get("id") or ""): q for q in self.questions
                               if isinstance(q, dict) and q.get("id")}
        self.gap_decisions = C.stand_gap_decisions(self.pipeline)
        self.results = C.current_instance_results(self.report)
        # t-323 A1: the triage is read through `contract.bind_triage` (the one binding), over the failures of the run
        self.triage_rows = C.triage_rows(self.triage)
        self.run_failures = C.triage_failures(self.report)[0]
        self.bindings: dict = {}
        for binding in self.manifest.get("then_bindings") or []:
            if not isinstance(binding, dict):
                continue
            key = (str(binding.get("case") or ""), binding.get("then"))
            self.bindings.setdefault(key, []).append(binding)
        self.unresolved_by_case: dict = {}
        for entry in live_unresolved(self.manifest):
            self.unresolved_by_case.setdefault(str(entry.get("case") or ""), []).append(entry)
        self._open_oracles = None     # read on first use: most stories have no `then_oracles` at all
        self._manual_cases = None
        self._red = None              # `red_map`'s cache: the red instances, read once per Story (HF2-3 3c2)

    # -- lookups --------------------------------------------------------------------------
    def oracle_gaps(self, case_key: str) -> dict:
        """{Then number: `contract.resolve_then_oracle` reading} of the case's Thens whose expected value the
        resolver reads `open` or `invalid` - the ledger's `open_oracles`, one reader for both tables (FR-10).
        {} for a case with no `then_oracles` line (written before t-227)."""
        if self._open_oracles is None:
            self._open_oracles = L.open_oracles(self.artifacts, self.cases)
        return self._open_oracles.get(case_key) or {}

    _manual_problem = ""   # why the manual results could not be read ("" = they were, or not asked yet)

    def manual_case(self, case_key: str) -> dict:
        """The "Checked by hand" entry of one manual-agent case - `report_facts._manual`, the ONE reader that
        decides whether a record counts (schema 2, evidence validated, current, an obligation mapped), so this
        table and the report block cannot disagree (FR-10). {} when the report block cannot be read."""
        if self._manual_cases is None:
            self._manual_cases = {}
            try:
                import report_facts as RF
                got = RF._manual(self.artifacts, self.plan_rows, self.cases, RF._key_fn(self.cases), {})
                self._manual_cases = {c["case"]: c for c in got.get("cases") or [] if isinstance(c, dict)}
            except Exception as exc:
                # a table never crashes over the report's reader (P1), but it never reads a failed read as a result either
                # (RD1-18, AR-28): the reason is kept and `manual_outcome` says it
                self._manual_problem = f"{type(exc).__name__}: {exc}"
        return self._manual_cases.get(case_key) or {}

    def manual_outcome(self, case_key: str) -> dict:
        """What a `manual-agent` case's VALID record says (t-263 D5): `pass` for a passed record, with the
        runner's words as the basis, `wait` for an inconclusive one, `blocked` for a failed one (HF8-17,
        F-8: the check ran and did not hold - never `pass`, and never `wait`, which tells the person "your turn to check"
        about a check that already said no; a confirmed bug of the requirement stays above it). {} for no record and an
        invalid one. RD1-18 (AR-28): when the manual results could not be READ, a case with no record reads `not run` and
        says so - never `pass`, and not the plan's reason, which would blame the plan for a read that failed."""
        try:
            import report_facts as RF
        except Exception as exc:
            self._manual_problem = f"{type(exc).__name__}: {exc}"
            RF = None
        entry = self.manual_case(case_key) if RF is not None else {}
        if entry.get("state") != "checked":
            if self._manual_problem and not entry:
                return {"tests": [], "level": "manual-agent", "shape": "", "bug": "", "result": "not run",
                        "basis": _one_line("the manual results could not be read: " + self._manual_problem, 120)}
            return {}
        base = {"tests": [], "level": "manual-agent", "shape": "", "bug": ""}
        if entry.get("result") == RF.RESULT_WORDS["pass"]:
            # a person is shown words, never a path or a link of any capture (HF8-20, I5; the owner's word 31.10.2026)
            return dict(base, result="pass", basis="checked by hand: " + _one_line(entry.get("actual"), 120))
        if entry.get("result") == RF.RESULT_WORDS["inconclusive"]:
            return dict(base, result="wait", basis=_one_line("checked by hand, inconclusive: "
                                                             + (entry.get("actual") or "no words were recorded"), 120))
        if entry.get("result") == RF.RESULT_WORDS["fail"]:
            return dict(base, result="blocked", basis=_one_line("checked by hand, failed: "
                                                                + (entry.get("actual") or "no words were recorded"), 120))
        return {}

    def green_on_open_outcome(self, oracle: dict, case_key: str) -> dict:
        """A green run on a Then whose expected value the resolver reads open or invalid (t-269 F2): `wait`,
        never `pass` - the test asserted a value nobody confirmed, so it can only have passed against the
        implementation (P20)."""
        return {"tests": [], "level": self.level_for(case_key), "shape": self.shape_for(case_key, None),
                "bug": "", "result": "wait", "basis": L.green_on_open_words(oracle)}

    def proof_reading(self, case_key: str, then: int):
        """`(ledger state, detail)` when the green runs of this Then are no proof (`ledger.proof_readings`, read once per case), else
        None. A reader that cannot be built reads nothing: a table never crashes over it (P1), and the ledger still says the state."""
        cache = self.__dict__.setdefault("_proof_readings", {})
        if case_key not in cache:
            try:
                cache[case_key] = L.proof_readings(self.manifest, self.report, [case_key])
            except Exception:  # noqa: BLE001
                cache[case_key] = {}
        return next((got for (case, number), got in cache[case_key].items() if number == then and C.case_matches(case, case_key)), None)

    def proof_strength_outcome(self, state: str, case_key: str) -> dict:
        """A green Then whose proof is not one (substituted or unknown side, open placeholder): `wait`, never `pass`; the basis is the
        state's own words, the table the delivery summary reads (`delivery_summary.state_words`)."""
        import delivery_summary as DS
        return {"tests": [], "level": self.level_for(case_key), "shape": self.shape_for(case_key, None),
                "bug": "", "result": "wait", "basis": DS.state_words(state)[0]}

    def plan_row_for(self, case_key: str) -> dict:
        meta = self.cases.get(case_key) or {}
        return self.plan_by_ts.get(str(meta.get("plan_row") or "")) or {}

    def level_for(self, case_key: str) -> str:
        level = self.case_levels.get(case_key) or ""
        if level in C.TRACE_LEVELS:
            return level
        disposition = str(self.plan_row_for(case_key).get("disposition") or "")
        return disposition if disposition in C.TRACE_LEVELS else ""

    def shape_for(self, case_key: str, entry: dict | None) -> str:
        """The shape the automator actually chose, then the shape the plan asked for at gate A.
        The plan's `fit` reads `extend test_x` - the first word is the decision, the rest is
        which test."""
        shape = str((entry or {}).get("shape") or "").strip()
        if shape in C.TRACE_SHAPES:
            return shape
        fit = str(self.plan_row_for(case_key).get("fit") or "").strip().split()
        return fit[0] if fit and fit[0] in C.TRACE_SHAPES else ""

    def bug_for(self, case_key: str, requirement: str) -> dict:
        _, bare = C.split_case_key(case_key)
        wanted = {case_key, bare or case_key}
        by_case = [b for b in self.bugs if wanted & set(b["cases"])]
        filed = [b for b in by_case if b["filed"]]
        for pool in (filed, by_case):
            for bug in pool:
                if requirement in bug["requirements"]:
                    return bug
            if pool:
                return pool[0]
        return {}

    def _filed_without_case(self, requirement: str) -> list:
        """The ids of the FILED bug records that name no case (head and drafts read together, `story_bug_records`) and either
        name this requirement or name no requirement at all: a bug that exists but that no row can be joined to. `[]` when
        there is none - then "bug not filed" stays the true line. Ids only, no title."""
        return [str(b["id"]) for b in self.bugs
                if b.get("filed") and not b["cases"] and (requirement in b["requirements"] or not b["requirements"])]

    def bug_by_requirement(self, requirement: str) -> dict:
        return next((b for b in self.bugs if requirement in b["requirements"]), {})

    def confirmed_bug_of(self, requirement: str) -> dict:
        """The first CONFIRMED bug record that names `requirement`, else `{}`. It joins on the requirement
        alone: a case no test ever ran has no red run to join a bug to, and a bug that names no requirement
        proves nothing about this one. A draft (`unconfirmed`) and an unreadable file (`unknown`) are not
        confirmed, so they leave the row where it was - the direction of error is toward NOT calling a
        requirement "with a bug" (t-205 F2)."""
        return next((b for b in self.bugs
                     if b.get("state") == "confirmed" and requirement in (b.get("requirements") or [])), {})

    def triage_for(self, instance_id: str, entry: dict | None = None, run_row: dict | None = None) -> dict:
        """The triage row that answers this instance, through `contract.bind_triage` - the binding the ledger, gate B,
        S7 and the dashboard read too (t-323 A1). The instance's own attempt rides along: a row of another attempt
        is no verdict of this run's failure, here as everywhere. {} when no row answers it (never the first of
        several siblings).

        HF2-6 fix round 2: the instance is also asked by the ids of ITS run row - the row `case_stamp.run_row_for` joins
        (`_joined_row`: the one join, neighbour veto and legacy step included), spelled the way the ledger spells it
        (`ledger._triage_row`: the row's `instance_id` and `result_id`). The manifest's hash `ti_...` and the runner's
        function id never met under the exact id, so a triage row written for the run's id read "triage not recorded" here
        while the ledger reddened it APP_BUG (FR-10). A row of another test (`TestB::t` beside `TestA::t`) is no joined row,
        so its ids are never asked."""
        names = [instance_id] + (C.instance_id_aliases(entry) if entry is not None else [])
        joined = self._joined_row(entry)
        if joined is not None:
            names += [str(joined.get("instance_id") or ""), C.result_id(joined)]
        own = run_row if isinstance(run_row, dict) else self.results.get(instance_id) or {}
        return C.triage_row_for(self.run_failures, self.triage_rows, names, str(own.get("attempt_id") or ""),
                                C.result_status(own)) or {}

    def _joined_row(self, entry: dict | None):
        """The instance's own current run row - `case_stamp.run_row_for` - else None (also for no entry)."""
        return self._run_row(entry) if isinstance(entry, dict) else None

    def attempts(self, instance_id: str) -> tuple:
        """(failed, total) recorded attempts of one instance - the "fails n of n" a person
        reads instead of "blocked_by_env". The instance's attempts are the history rows under the key of its joined run
        row (`_joined_row`, as `triage_for` finds it), else under its own id: a manifest `ti_...` and a run row spelled by
        the runner are one instance (HF2-6 fix round 2)."""
        keys = {instance_id}
        joined = self._joined_row(self.instances.get(instance_id))
        if joined is not None:
            keys |= {key for key, row in self.results.items() if row is joined}
        history = C.instance_results(self.report)
        rows = [r for key in keys for r in history.get(key, [])]
        failed = [r for r in rows if C.result_status(r) not in ("passed", "pass")]
        return (len(failed), len(rows))

    def decision_words(self, case_key: str) -> str:
        """A person's own words about this case, from the stand-gap answers first and the
        stage overrides second. A decision id with no words beside it (`S5-160`) is exactly
        what the person told us to stop printing."""
        for gap, answer in self.gap_decisions.items():
            if C.names_whole(case_key, gap) or C.names_whole(case_key, str(answer.get("words") or "")):
                return _one_line(answer.get("words"))
        for entry in C.live_stage_overrides(self.pipeline):          # a revoked word is no word; a case key reads whole (GW1-1)
            if C.names_whole(case_key, str(entry.get("decision") or "")):
                return _one_line(entry.get("decision"))
        return ""

    # -- outcomes -------------------------------------------------------------------------
    def instance_outcome(self, instance_id: str, case_key: str, requirement: str) -> dict:
        """The result of one live instance, in the person's vocabulary."""
        entry = self.instances.get(instance_id)
        if entry is None:
            return {}
        test = {"instance_id": C.test_instance_id(entry) or instance_id,
                "file": str(entry.get("file") or "")}
        base = {"tests": [test], "level": self.level_for(case_key),
                "shape": self.shape_for(case_key, entry), "bug": ""}
        # HF2-6 (RD1-8): the RUN is the source of "passed", not the manifest's `status` word. The manifest's `green` /
        # `written` is what the automator wrote before the run; `pass` is read only from a green result row of THIS
        # instance (`case_stamp.run_row_for`, the one join the ledger asks too). Only the manifest's `red` is still read: it
        # refuses a pass a green row would give. The wording `LEGEND["pass"]` promises - green in the current run - is now true.
        row = self._run_row(entry)
        red_run = self._red_run_row(instance_id, entry) if str(entry.get("status") or "").lower() != "red" else None
        if red_run is not None:
            # t-412 (B-303, critic t-403 G4): the run result outranks the manifest `status` for EVERY case, not only a handed
            # one: a result row that says failed/error is what the run observed, and a table row may read `pass` only when
            # no red run result exists for the instance (the report printed `| R-1 | ... | pass |` beside verdict `no`).
            # t-414 (B-308 a): "the instance's run result" is found by the exact id AND by the dashboard's own tolerant rule
            # (`factory_dashboard.match_run_row`), because a manifest row and its run row often carry ids of different shapes
            # (a hash `ti_...` against the runner's function id) and the exact join then reads a red run as "no run result".
            # t-419: the join is `case_stamp.red_run_for`, the one every reader of "is this instance red" asks.
            row = red_run
        red = (red_run is not None or self._is_red(row)
               or (str(entry.get("status") or "").lower() == "red" and self._is_green(row)))
        if not red and self._handed(case_key) and self._case_failed(case_key):
            # t-305 N8 attempt 2 (F1): a handed case whose instance RAN and went red is not proven by the critic's
            # approval of the file: the observed failure outranks the hand-off, as in `check_traceability._case_chain`.
            red = True
        if not red:
            return self._unred_outcome(base, entry, row, case_key, requirement)
        row = row or {}
        triage_row = self.triage_for(instance_id, entry, row or None)
        verdict = str(triage_row.get("verdict") or "")
        if verdict == "ENV_ISSUE":
            return dict(base, result="blocked", basis=self._stand_basis(instance_id, case_key))
        bug = self.bug_for(case_key, requirement)
        if bug:
            return dict(base, result="bug", bug=bug["id"],
                        basis=self._bug_basis(row, bug))
        if verdict:
            # HF2-6 fix round 3 (t-128 fork, decided (a)): the word stays `blocked` - `bug` is allowed only with a bug record
            # (`bug_for`; `contract` refuses `result: bug` with an empty `bug`) - but the basis must not say "triage not
            # recorded" beside a triage row the ledger reads (`failed:APP_BUG`). A row with an empty verdict is no triage.
            # RD1-19: the schema of a triage row never had `reason`; the analyst's sentence is `detail` (or the control's
            # `observed`), read by the ONE reader `contract.triage_reason`. The phrase stays true only when no carrier holds one.
            reason = C.triage_reason(triage_row) or "no reason recorded"
            if verdict == C.TRIAGE_STRICTER_VERDICT:
                # HF2-18 (t-1338 Q1): this word is "no bug" by definition, and the same report lists the red under "Left with
                # you" - "bug not filed" beside it would be one packet contradicting itself (FR-10)
                return dict(base, result="blocked",
                            basis=_one_line(f"red run, triaged {verdict}: {reason}; no bug, left with you"))
            behind = self._behind_another_red(triage_row, verdict, requirement)
            if behind:
                return dict(base, result="blocked", basis=behind)
            unlinked = self._filed_without_case(requirement)
            if unlinked:
                # HF8-22 (L-A): a filed bug that names no case and no draft cannot be joined to this row; "bug not filed"
                # would be a false fact (FR-41) - what is known is that one is filed and says no case.
                return dict(base, result="blocked", basis=_one_line(
                    f"red run, triaged {verdict}: {reason}; bug {', '.join(unlinked)} is filed but names no case"))
            return dict(base, result="blocked", basis=_one_line(f"red run, triaged {verdict}: {reason}; bug not filed"))
        return dict(base, result="blocked",
                    basis=_one_line(f"red run, triage not recorded: {row.get('reason') or 'no reason recorded'}"))

    def _behind_another_red(self, triage_row: dict, verdict: str, requirement: str) -> str:
        """HF8-16 (K6): the basis of a red that is ANOTHER case's defect, '' when the row says no such thing. The analyst wrote
        `blocking_check` (R6, t-1508) and the report still said "no reason recorded; bug not filed" beside the blocker's own bug
        (run 12586, TC-005 behind TC-004). The branch is taken only for an APP_BUG row whose `blocking_check` is a non-empty string
        that `contract.triage_blocked_problems` accepts (the one reader of the fields: a blocker that is not red in THIS run, or is
        the row's own case, is a stale word and the old line stands). Position: AFTER `bug_for` (a found bug keeps `bug`) and AFTER
        the ASSERT_STRICTER branch; the result stays `blocked` - `bug` is only for a recorded bug. The words carry the verdict as
        read, the blocker's case with its title (`_named`, no instance id) and the title of its bug when one is recorded."""
        blocker = triage_row.get("blocking_check")
        if verdict != "APP_BUG" or not (isinstance(blocker, str) and blocker.strip()):
            return ""
        if C.triage_blocked_problems(triage_row, self.artifacts, self.triage_rows, self.report):
            return ""
        cases = L.blocker_cases(blocker.strip(), self.manifest, self.red_map())
        names = " and ".join(self._named(case) for case in cases) or "another check"
        words = self._bug_words(cases, requirement)
        text = f"red run, triaged {verdict}: this is the defect of {names}{words}; no separate bug"
        if not words:
            text += "; no bug is recorded for it yet"
        entries = triage_row.get("blocked_thens")
        for entry in entries if isinstance(entries, list) else []:
            detail = " ".join(str(entry.get("detail") or "").split()) if isinstance(entry, dict) else ""
            if detail:
                import report_facts as RF   # lazily: it imports this module; `_cut` is the one truncation the report makes
                return " ".join(f"{text} — {RF._cut(detail)}".split())   # not `_one_line`: its 110 would cut the sentence
        return " ".join(text.split())

    def _case_failed(self, case_key: str) -> bool:
        """Did the run record a FAILED result for this case (`contract.run_results`, the projection the chain and the ledger
        read: a result row names its case by `case` or its links, not always by the manifest instance's own id)?"""
        # D2-B3: by the identity lookup (the bare alias of an area row is no longer stored); several matching keys roll up, red first
        cfg = C.case_config(self.artifacts)       # F7 (t-1753): the STORY's config for both paths, not the process's
        results = C.run_results(self.report, cfg)
        word = C.case_lookup(results, case_key, cfg, exact_wins=False)
        # t-414 (B-308 c): the same red set as `instance_outcome` (`_RED_RUN_STATUSES`) - `error` is a failure here as there; the
        # word is normalized the way a result row's is (`fail` -> `failed`), so no second spelling of the set lives in this method.
        if C.result_status({"status": word}) in _RED_RUN_STATUSES:
            return True
        # B-310 (c): the projection above folds a row the reducer overwrote to `partial` (it could not join it to a manifest
        # row, `finalize_task`) into `partial`, and `partial` is not red - yet that row keeps what the run said in `raw_status`.
        # `case_stamp.is_red_row` is the ONE reader of "this current row is red" (the stamp, the coverage map and gate B read it
        # too), so a current row that names this case by the identity match (`contract.case_matches`) and is red by it counts
        # (AR-13). The direction is `failed`: it can only turn a False into True where the run observed a red.
        for row in self.results.values():
            if not self._is_red(row):
                continue
            # D2-B3: the keys keep the area a writer knew (`manifest_test_keys`); a bare id stripped from `api/TC-4` would match
            # `web/TC-4` (E-B3) and the red of one area would read as the red of another
            keys = [row.get("case"), *C.manifest_test_keys(row, cfg=cfg)]
            if any(str(k or "").strip() and C.case_matches(k, case_key, cfg=cfg) for k in keys):
                return True
        return False

    def _red_run_row(self, instance_id: str, entry: dict | None):
        """The red run result of this instance, else None (t-414, B-308 a; t-419: the join itself moved out).

        "Is there a red run for this manifest instance" is ONE function, `case_stamp.red_run_for`, asked here, by the stamp, by
        the coverage map and by gate B's lifecycle reasons (FR-17, FR-10: the table and the verdict cannot disagree about a run
        when they read it by one rule). It hosts the join because `case_stamp` is the module that already held the helper and
        imports neither this module nor the dashboard at load time; this module imports it. The rule (exact id, then the
        dashboard's own `match_run_row` over the red rows, then a bare instance standing for its whole function) and its error
        direction are written there. The index is built once per `self.results`. The import is NOT guarded: a build that cannot
        load the join fails loud here instead of printing `pass` for a red run. `instance_id` is the key this reader looked
        the entry up by; the join reads the entry's own ids (all its aliases), so an entry that is not an object joins
        nothing."""
        import case_stamp as CS   # lazy: nothing else in this module needs the stamp's imports
        return CS.red_run_for(entry, self._run_rows())

    def _run_rows(self) -> dict:
        """`case_stamp.run_rows_index` of this story's current results with its live manifest entries (the legacy join counts
        them), built once per `self.results`."""
        import case_stamp as CS
        cached = getattr(self, "_run_index", None)
        if cached is None or cached[0] is not self.results:
            index = CS.run_rows_index(self.results, live_tests(self.manifest), C.case_config(self.artifacts))
            cached = self._run_index = (self.results, index)
        return cached[1]

    def _run_row(self, entry: dict | None):
        """The run result row this instance has, whatever its status, else None: the run recorded nothing for it
        (`case_stamp.run_row_for`, the join the ledger reads too)."""
        import case_stamp as CS
        return CS.run_row_for(entry, self._run_rows())

    @staticmethod
    def _is_red(row) -> bool:
        import case_stamp as CS
        return CS.is_red_row(row)

    @staticmethod
    def _is_green(row) -> bool:
        return isinstance(row, dict) and C.result_status(row) == "passed"

    def _unred_outcome(self, base: dict, entry: dict, row, case_key: str, requirement: str) -> dict:
        """The outcome of an instance that is not red: `pass` only for a green result row of its own. No row at all is a
        hand-off (`wait`: what the person took stays `after_checks`, P21) or `not run` with the ledger's own words
        (`L.NO_RUN_RESULT`) - never `pass` (FR-41, FR-18: a manifest word is not an execution). A row whose word is neither
        green nor red (`skipped`, `partial`, a word nobody knows) is `not run` and says which word the run recorded (F-6)."""
        if row is None:
            handed = self._handed_row(case_key)
            if handed:
                return dict(base, result="wait", basis=self.unresolved_outcome(handed, case_key, requirement)["basis"])
            return dict(base, result="not run", basis=L.NO_RUN_RESULT)
        if not self._is_green(row):
            word = C.result_status(row)
            return dict(base, result="not run",
                        basis=f"the run recorded `{word}` for this test" if word else "the run recorded no result word for this test")
        if L.is_rejected(entry):
            # A green run of a test the critic rejected is not a pass until the critic has seen the changed test (RD1-9a, FR-18)
            return dict(base, result="blocked", basis="rejected by the code critic; the green run does not count until the critic reviews the changed test")
        return dict(base, result="pass", basis=self._review_basis(entry))

    def unresolved_rows(self, case_key: str) -> list:
        """F8 (t-1753, RD1-2): the live `unresolved[]` rows of this case, by the identity match (`contract.names_case`: a bare
        row names every area's case, two areas never meet, `TC-1` is not `TC-10`) and not by the raw key: the rows filed under
        the case's own spelling first, then those of every other key that names it. A blank case has none."""
        if not str(case_key or "").strip():
            return []
        cfg = C.case_config(self.artifacts)
        own = self.unresolved_by_case.get(case_key) or []
        return list(own) + [row for key, rows in self.unresolved_by_case.items()
                            if key != case_key and C.names_case([key], case_key, cfg) for row in rows]

    def _handed_row(self, case_key: str) -> dict:
        """The live `unresolved[]` row of this case that says the person took it (`handed_to_person`), else {}."""
        rows = self.unresolved_rows(case_key)
        return next((u for u in rows if str(u.get("reason") or "") == C.HANDED_TO_PERSON), {})

    def _handed(self, case_key: str) -> bool:
        """Does a live `unresolved[]` row of this case say the person took it (`handed_to_person`)?"""
        return bool(self._handed_row(case_key))

    @staticmethod
    def _bug_basis(row: dict, bug: dict) -> str:
        """What the run actually said, then the bug's own title. The assertion message is the
        shortest true sentence there is, and it is the one the person recognises."""
        reason = " ".join(str(row.get("reason") or "").split())
        for prefix in ("AssertionError:", "assert "):
            if reason.startswith(prefix):
                reason = reason[len(prefix):].strip()
        return _one_line(reason or bug.get("title"), 80)

    def _review_basis(self, entry: dict) -> str:
        """Green is not proof on its own. On 15045 eight green tests carried no critic verdict
        at all (the factory's own round cap), and the report said nothing about it."""
        import ledger as L
        import proof_level as PL
        verdict = L.verdict_of(entry)
        try:
            # Each verdict in its own words (FR-35): a rejected or unverified test is never shown as
            # "review not recorded", which says the critic never spoke.
            words = PL.review_words(verdict)
            if verdict not in ("approved", "approved_with_fixes"):
                return words
            # How sure the check is, from the one reader of receipts (`ledger.proof_shown` over
            # `proof_level.reached`), not from whether some probe key exists on the row.
            return words + " - " + L.proof_shown(entry, self.manifest, self.artifacts)[1]
        except PL.LevelsUnavailable as exc:
            # A report never crashes over its own vocabulary (P1): the basis says what it can and
            # the reader is told once, on stderr, how to get the levels back.
            global _LEVELS_NOTE_SHOWN
            if not _LEVELS_NOTE_SHOWN:
                _LEVELS_NOTE_SHOWN = True
                print(f"traceability: proof levels are not shown - {exc}", file=sys.stderr)
            return f"critic verdict: {verdict or 'not recorded'} (proof level not shown)"

    def _stand_basis(self, instance_id: str, case_key: str) -> str:
        failed, total = self.attempts(instance_id)
        head = f"fails {failed} of {total} on the stand" if total and failed == total else "blocked on the stand"
        words = self.decision_words(case_key)
        return _one_line(f"{head}; {'decision: ' + words if words else 'no decision recorded'}")

    def unresolved_outcome(self, entry: dict, case_key: str, requirement: str,
                           partition: str = "") -> dict:
        """An `unresolved[]` row or an unresolved Then binding, in the person's vocabulary."""
        reason = str(entry.get("reason") or "")
        if reason == C.BLOCKED_BY_CHECK:
            return self.blocked_outcome(entry, case_key, requirement)
        instance = str(entry.get("instance_id") or "")
        manifest_entry = self.instances.get(instance)
        base = {"tests": self._tests_of(instance), "level": self.level_for(case_key),
                "shape": self.shape_for(case_key, manifest_entry), "bug": ""}
        detail = str(entry.get("detail") or "")
        if partition:
            # One `unresolved[]` row often carries several partitions, each with its own
            # sentence and sometimes its own reason: on 15045 the P-mcp partition was
            # deferred by the designer inside a row whose top-level reason was
            # `handed_to_person`, and the report told the person to run both.
            segment = _partition_segment(detail, partition)
            if segment:
                detail = segment
                if "deferred_by_decision" in segment:
                    reason = "deferred_by_decision:" + segment.partition("deferred_by_decision:")[2].split(",")[0]
        if C.unresolved_decided(reason):
            return dict(base, result="deferred",
                        basis=_first_sentence(self.decision_words(case_key) or detail
                                              or reason.partition(":")[2] or reason))
        if reason == "impossible":
            return dict(base, result="unreachable", basis=_first_sentence(detail))
        if reason == "contradicts_requirement":
            bug = self.bug_for(case_key, requirement) or self.bug_by_requirement(requirement)
            if bug:
                return dict(base, result="bug", bug=bug["id"], basis=_one_line(bug["title"]))
            return dict(base, result="wait", basis=_first_sentence(detail))
        if reason == C.HANDED_TO_PERSON:
            return dict(base, result="wait",
                        basis=_first_sentence(self.decision_words(case_key) or detail))
        if reason == C.EXPECTATION_UNCONFIRMED:
            # D2 (t-269): a whole-case row naming its question waits for the person - the same words as a
            # Then nobody confirmed, never `not run` (nothing was left unrun by the factory's own fault).
            qid = str(entry.get("question") or "").strip()
            return dict(base, result="wait", basis=unconfirmed_basis(self.question_by_id.get(qid), qid))
        if reason == "blocked_by_env":
            # A case whose own `unresolved[]` row says the person took it reads as handed,
            # not as a stand outage: on 15045 the guardrail partitions were decided at S5 and
            # the report still listed them as an environment block nobody had answered.
            handed = [u for u in self.unresolved_rows(case_key)
                      if str(u.get("reason") or "") == C.HANDED_TO_PERSON]
            if handed:
                return dict(base, result="wait",
                            basis=_first_sentence(self.decision_words(case_key)
                                                  or handed[0].get("detail")))
            words = self.decision_words(case_key)
            return dict(base, result="blocked",
                        basis=_one_line("the stand stops it; "
                                        + ("decision: " + words if words else "no decision recorded")))
        return dict(base, result="not run", basis=_first_sentence(detail or reason or "no reason recorded"))

    # -- a Then behind another case's red (HF2-3, 3c2) ---------------------------------------
    # TP1-12586: ONE test covers TC-004, TC-005 and TC-006 and stops at TC-004's Then 2. The unit of an outcome is the
    # (Then, instance) pair (AR-26); a Then the stopped test never reached is `blocked`, never `pass` (FR-18, FR-58) and never
    # `bug` of the case that merely stands behind the red. Variant (b) of FA-11, the safe default: a covered Then on a test that
    # is red for ANOTHER case's requirement is "not proven" - the owner has not yet allowed a failure site to prove it.

    def red_map(self) -> dict:
        """`{instance id: [the unresolved[] rows that make it red]}` of the whole story, read ONCE per Story (the cache is
        `self._red`) through `ledger.red_instances` - `acceptance.red_by_requirement` with `report=`, the run report's CURRENT
        result as the source (AR-13: the trace, the ledger and the delivery check ask the one reader and cannot disagree about
        which instance is red). `{}` for a manifest or report that cannot be read: nothing is red, and an instance reads by
        its own result as it did before (FR-59)."""
        if self._red is None:
            self._red = L.red_instances(self.manifest, self.report)
        return self._red

    def _tests_of(self, instance_id: str) -> list:
        """`[{instance_id, file}]` of one manifest instance, else `[]` (an empty or unknown id names no test)."""
        entry = self.instances.get(instance_id)
        return [{"instance_id": C.test_instance_id(entry) or instance_id, "file": str(entry.get("file") or "")}] if entry else []

    def _named(self, case: str) -> str:
        """The case as a person reads it (D8): `TC-004 (<the title of its file>)`. A title that cannot be read makes the whole
        phrase `the check this one depends on (TC-004)` - the id once, never `TC-004 (the check this one depends on (TC-004))`."""
        meta = self.cases.get(case) or next((m for key, m in self.cases.items() if C.case_matches(case, key)), {})
        title = " ".join(C.case_title(Path(meta["path"])).split()) if meta.get("path") else ""
        return f"{case} ({title})" if title else f"the check this one depends on ({case})"

    def _bug_words(self, cases: list, requirement: str) -> str:
        """` - a product bug: <title>` for the bugs recorded against `cases` (titles, never ids), else ''."""
        titles = list(dict.fromkeys(" ".join(str(b["title"]).split())
                                    for b in (self.bug_for(case, requirement) for case in cases) if b and b.get("title")))
        return f" - a product bug: {' and '.join(titles)}" if titles else ""

    def blocked_outcome(self, binding: dict, case_key: str, requirement: str) -> dict:
        """A Then bound `blocked_by_check` (T1): `blocked`, never `pass` and never `{}`. `tests` is the test that holds the Then
        (the binding's `instance_id` in the manifest) - it lets `_merge_outcomes` print the generic test AND the stopped one
        on a Then both prove; a binding with no `instance_id` holds no test: `tests: []`, still `blocked` (a Then with no test
        never reads as checked). The blocker is named by `ledger.blocker_cases` (a case key is that case; an instance id is the
        cases that instance is red for; none -> no id at all), each with its title (`_named`)."""
        cases = L.blocker_cases(str(binding.get("blocking_check") or "").strip(), self.manifest, self.red_map())
        names = " and ".join(self._named(case) for case in cases) or "another check"
        entry = self.instances.get(str(binding.get("instance_id") or ""))
        return {"tests": self._tests_of(str(binding.get("instance_id") or "")), "level": self.level_for(case_key),
                "shape": self.shape_for(case_key, entry), "bug": "", "result": "blocked",
                "basis": f"not checked yet: in the same test, {names} fails first{self._bug_words(cases, requirement)}; "
                         "check this again once that is fixed"}

    def stopped_outcome(self, instance_id: str, rows: list, case_key: str, requirement: str) -> dict:
        """A covered Then of `case_key` on an instance that is red for ANOTHER case's requirement (T2, variant (b)): `blocked`,
        not proven - the test stopped at the red Then of `rows` and may not have reached this one. `rows` are the
        `contradicts_requirement` rows that make the instance red (`red_map`); the words name each row's case with its title and
        its `thens` as `Then m` (a row with no readable `thens` names the case alone - no number is invented). `tests` is the
        stopped instance. (`then` of this case is not an input: variant (b) does not compare it with the failure site.)"""
        entry = self.instances.get(instance_id)
        stops = []   # (case, the `Then m` words or '') per row, once each
        for row in rows:
            raw = row.get(C.UNRESOLVED_THENS_KEY)
            numbers = sorted({n for n in (C.then_number(x) for x in raw) if n}) if isinstance(raw, list) else []
            stops.append((str(row.get("case") or "").strip(), f"Then {', '.join(str(n) for n in numbers)}" if numbers else ""))
        stops = list(dict.fromkeys(stops))
        where = " and ".join(f"{self._named(case)}, {then}" if then else self._named(case) for case, then in stops)
        before = ", before" if stops and stops[-1][1] else " before"
        return {"tests": self._tests_of(instance_id), "level": self.level_for(case_key),
                "shape": self.shape_for(case_key, entry), "bug": "", "result": "blocked",
                "basis": f"not proven: the test stopped at {where}{before} reaching this check"
                         f"{self._bug_words(list(dict.fromkeys(case for case, _ in stops)), requirement)}; "
                         "check this again once that is fixed"}

    def _covered_outcomes(self, covered: list, case_key: str, requirement: str) -> list:
        """One outcome per covered instance of a Then. An instance that is red ONLY for other cases' requirements
        (`iid in red and not red_by_own_row`) reads `stopped_outcome`; one red by its OWN case's row, a green one, one the
        report calls `passed`/`error` (not red by D1) reads `instance_outcome`, as it always did."""
        red = self.red_map()
        out = []
        for instance in dict.fromkeys(covered):
            iid = C.test_instance_id(self.instances.get(instance)) or instance
            if iid in red and not AC.red_by_own_row(red, iid, case_key):
                out.append(self.stopped_outcome(iid, red[iid], case_key, requirement))
            else:
                out.append(self.instance_outcome(instance, case_key, requirement))
        return out

    def unanswered_claims(self) -> dict:
        """{R: question id} of the register's behaviour claims nobody has answered (`contract.
        unconfirmed_implementation_only`, `claim_questions`). Only an R the register's `## Behaviour claims`
        section names is a claim: a register written before t-227 has that section nowhere, and an
        implementation-only R of such a story keeps reading as it did (the temporal edge)."""
        text = C.read_text(C.artifact(self.artifacts, "requirements-register.md"))
        asked = C.claim_questions(text)
        if not asked:
            return {}
        open_r = C.unconfirmed_requirements(text, self.question_by_id)
        return {r: qid for r, qid in asked.items() if r in open_r}

    def unconfirmed_outcome(self, binding: dict, case_key: str) -> dict:
        """A Then whose expected value nobody confirmed (`then_bindings` reason `expectation_unconfirmed`,
        P20): `wait`, never a pass, a failure or `deferred` - nothing was executed against it and nobody
        decided anything. The question is the binding's own `question`; before/now are the question's."""
        qid = str(binding.get("question") or "").strip()
        return {"tests": [], "level": self.level_for(case_key), "shape": self.shape_for(case_key, None),
                "bug": "", "result": "wait",
                "basis": unconfirmed_basis(self.question_by_id.get(qid), qid)}

    def case_partitions(self, case_key: str) -> list:
        """The partition labels this case's `unresolved[]` rows carry."""
        out = []
        for entry in self.unresolved_rows(case_key):
            labels = [str(p) for p in (entry.get("partitions") or []) if str(p).strip()]
            if not labels and str(entry.get("partition") or "").strip():
                labels = [str(entry["partition"]).strip()]
            out.extend(labels)
        return out

    def _remainders(self) -> list:
        """The Thens a person took (`contract.then_remainders`), read once per table."""
        cached = getattr(self, "_then_remainders", None)
        if cached is None:
            cached = self._then_remainders = C.then_remainders(self.manifest)
        return cached

    def then_outcome(self, case_key: str, then: int, requirement: str) -> dict:
        """One Then clause: what proves it, or what stops it from being proven."""
        _, bare = C.split_case_key(case_key)
        bindings = (self.bindings.get((case_key, then)) or []) + (
            self.bindings.get((bare, then)) or [] if bare and bare != case_key else [])
        covered, unresolved = [], []
        for binding in bindings:
            instance = str(binding.get("instance_id") or "")
            if str(binding.get("status") or "") == "covered" and instance in self.instances:
                covered.append(instance)
            elif str(binding.get("status") or "") != "covered":
                unresolved.append(binding)
        # A Then the person took (GW1-14) is read FIRST: before the unconfirmed block and before the partition rule
        # below, which drops a binding with no instance "because the partition row says it once" (and a remainder has
        # no partition row, so the Then would vanish and read as verified). Whatever else binds this Then, the
        # remainder joins the outcomes and the worst wins: the Then is never `pass` and never `{}`.
        handed = [b for b in unresolved if str(b.get("reason") or "") == C.HANDED_TO_PERSON
                  and any(r["then"] == then and C.case_matches(r["case"], case_key)
                          for r in self._remainders())]
        # A Then bound `blocked_by_check` (HF2-3) joins the same way, and for the same reason: its binding may have no
        # instance (`instance_id: null`), and the partition rule below would drop it as "the partition row says it once" -
        # a Then with no test would vanish and read as checked. Every blocked binding of this Then joins, beside the handed
        # one if both exist; the worst wins (`bug` of another instance still outranks `blocked`). A covered instance that is
        # red only for another case's requirement reads `stopped_outcome` (`_covered_outcomes`).
        blocked = [b for b in unresolved if str(b.get("reason") or "") == C.BLOCKED_BY_CHECK]
        if handed or blocked:
            outcomes = self._covered_outcomes(covered, case_key, requirement)
            if handed:
                outcomes.append(self.unresolved_outcome(handed[0], case_key, requirement))
            outcomes += [self.blocked_outcome(b, case_key, requirement) for b in blocked]
            return _merge_outcomes(outcomes)
        # An unconfirmed expectation is read BEFORE the partition rule below: that rule drops a binding
        # with no instance because "the partition row says it once", and this gap has no partition row -
        # dropping it would leave the Then with no row at all, which reads as verified. A Then that is
        # BOTH covered and unconfirmed is never a pass: the worst outcome wins (`_merge_outcomes`).
        unconfirmed = [b for b in unresolved if str(b.get("reason") or "") == L.EXPECTATION_UNCONFIRMED]
        if unconfirmed:
            outcomes = self._covered_outcomes(covered, case_key, requirement)
            outcomes.append(self.unconfirmed_outcome(unconfirmed[0], case_key))
            return _merge_outcomes(outcomes)
        if covered:
            outcomes = self._covered_outcomes(covered, case_key, requirement)
            # F2 (t-269): a green run is a pass only when the Then's expected value is settled. The ONE
            # resolver reads it `open` (an `unknown` nobody answered, or answered in a way that settles
            # nothing) or `invalid`: the green then proves only that the implementation does what it does.
            # Error direction: toward `wait`; the worst outcome wins, so a red run still reads `bug`.
            gap = self.oracle_gaps(case_key).get(then)
            if gap:
                outcomes.append(self.green_on_open_outcome(gap, case_key))
            # t-2181 PC-5 / t-2277 J-C7 (AR-13, AR-15, FR-10): a green that met only a substituted or unknown side, or that rests on an
            # open first-look placeholder, is not `pass` here either - the ledger reads the same Then `not_verified:*` and "Left with
            # you" says "run it again": one packet never says both. The reader is the ledger's own (`proof_readings`); `wait` is the
            # worst-wins partner of a pass (`_merge_outcomes`), so a red or blocked outcome of the same Then still wins over it.
            reading = self.proof_reading(case_key, then)
            if reading:
                outcomes.append(self.proof_strength_outcome(reading[0], case_key))
            return _merge_outcomes(outcomes)
        if unresolved:
            if not str(unresolved[0].get("instance_id") or ""):
                # A binding with no instance behind it is the automator saying "one partition
                # of this Then is unrun". The partition row below says it once, with the
                # partition's own name; saying it here too is the eleven-times repetition the
                # person read on 15045.
                partitions = self.case_partitions(case_key)
                mine = {int(m.group(1)) for m in
                        (re.fullmatch(r"[Tt]hen[- ](\d+)", p) for p in partitions) if m}
                if partitions and then not in mine:
                    return {}
            return self.unresolved_outcome(unresolved[0], case_key, requirement)
        return {}

    def unbound_instances(self, case_key: str) -> list:
        """Live instances of this case that no Then binding names.

        `test_..._per_partition[self-reference]` was one of them on 15045: red, triaged
        APP_BUG, a filed BUG-4 against it — and invisible in every table the person read,
        because the binding that would have carried it still said `blocked_by_env` from
        before the stand was fixed."""
        _, bare = C.split_case_key(case_key)
        wanted = {case_key, bare or case_key}
        bound = {str(b.get("instance_id") or "") for key, group in self.bindings.items()
                 if key[0] in wanted for b in group}
        out = []
        for entry in live_tests(self.manifest):
            instance = C.test_instance_id(entry)
            if C.names_case(C.manifest_test_links(entry), case_key) and not (set(C.instance_id_aliases(entry)) & bound):
                out.append(instance)
        return out

    def case_outcome(self, case_key: str, requirement: str) -> dict:
        """The case as a whole, for a case no Then binding ever reached: its own instances,
        then its `unresolved[]` rows, then the plan's disposition."""
        instances = [C.test_instance_id(entry) for entry in live_tests(self.manifest)
                     if C.names_case(C.manifest_test_links(entry), case_key)]
        if instances:
            return _merge_outcomes([self.instance_outcome(i, case_key, requirement)
                                    for i in dict.fromkeys(instances)])
        rows = self.unresolved_rows(case_key)
        if rows:
            return self.unresolved_outcome(rows[0], case_key, requirement)
        row = self.plan_row_for(case_key)
        # HF8-17 (M-A): a plan row the plan DISPOSES to a manual lane is read at that lane whatever its `level` column says - the
        # column holds the layer a test would have run at (`e2e-ui`), the disposition says who checks it. Asked of the column first,
        # `e2e-ui` + `manual-agent` read `not run` with the plan's own reason beside a "Checked by hand" block that counted it, and
        # `e2e-ui` + `manual-human` read `not run` instead of `wait` (run 12586, FR-10).
        disposition = str(row.get("disposition") or "")
        level = disposition if disposition in MANUAL_LANES else self.level_for(case_key)
        bug = self.confirmed_bug_of(requirement)
        if bug:
            # A confirmed bug names this requirement: the row says so, instead of "wait" or "not run"
            # beside a verdict that counts the bug. On TP1-13797 BUG-1 named R-7 while R-7 stood under
            # "Not proven" and the verdict counted "0 with a product bug" (t-202, R-213.1): a requirement is
            # never both. The count and the appendix read these same rows (FR-10).
            return {"tests": [], "level": level, "shape": "", "bug": bug["id"], "result": "bug",
                    "basis": _one_line(bug["title"])}
        if level == "manual-agent":
            # D5 (t-263): a case an agent checked by hand reads what its VALID record says - a passed one
            # `pass`, an inconclusive one `wait`, a failed one `blocked` - instead of `not run` beside a "Checked by hand"
            # block that counts it (FR-10). No record, or one the block does not count, keeps today's reading below.
            # Position (HF8-17, M-A): BELOW the case's own instances, its `unresolved[]` rows and a confirmed bug - a live test
            # and a found bug are never covered by a manual reading (I2).
            checked = self.manual_outcome(case_key)
            if checked:
                return checked
        if level == "manual-human":
            # A case planned for a person to check by hand waits for that person; "not run" says
            # the factory should have run it and did not (legend: wait = "handed to a person -
            # planned manual"). On TP1-13797 five such cases read "not run" and every count of
            # what waits for the person came out wrong (B-211 F33).
            return {"tests": [], "level": level, "shape": "", "bug": "", "result": "wait",
                    "basis": _first_sentence(row.get("reason") or "planned for a person to check by hand; "
                                                                  "nothing is recorded yet")}
        return {"tests": [], "level": level, "shape": "", "bug": "", "result": "not run",
                "basis": _first_sentence(row.get("reason") or "no result recorded for this case")}

    def set_aside(self, case_key: str) -> bool:
        """A2: the case stayed on a plan row the plan excluded (`skip` / `unverifiable`, e.g. after the answer `b`) and never ran
        (`contract.case_set_aside`, the one predicate; the row is found EXACTLY by the case's `Plan row:`). A case that ran is never
        set aside, so a red run on a `skip` row still reads through the case."""
        row = self.plan_row_for(case_key)
        return bool(row) and C.case_set_aside(case_key, str(row.get("disposition") or ""), self.manifest, self.report)

    def open_question_of(self, requirement: str) -> tuple:
        """A3: `(question id, unknown)` for a requirement whose rows are all excluded: the first gate A question the JSON plan row
        rests on that is not settled (`planning_contract.open_questions_of_plan_rows`), `("", why)` when the plan or the register
        could not be read, `("", "")` when nothing waits."""
        import planning_contract as P
        state = P.open_questions_of_plan_rows(
            self.artifacts, [r.get("ts") for r in self.plan_rows if requirement in (r.get("requirements") or [])])
        return (state["open"][0]["id"] if state["open"] else "", state["unknown"])

    def caseless_plan_row(self, requirement: str) -> dict:
        """The plan row that speaks for a requirement no case covers: every plan row that names it has
        no case of its own and a disposition of CASELESS_PLAN_RESULTS. `{}` when any row naming it does
        something else (a planned row whose case is not authored yet is not "deferred"), or when no row
        names it - the reading stays today's `not planned`. Two such rows that disagree: `unverifiable`
        wins, because it claims no decision was taken."""
        named = [r for r in self.plan_rows if requirement in (r.get("requirements") or [])]
        # A2: a case set aside (it stayed on an excluded row and never ran) is no case of the row
        with_cases = {str(meta.get("plan_row") or "") for key, meta in self.cases.items() if not self.set_aside(key)}
        if not named or any(r.get("disposition") not in CASELESS_PLAN_RESULTS
                            or str(r.get("ts") or "") in with_cases for r in named):
            return {}
        return next((r for r in named if r.get("disposition") == "unverifiable"), named[0])


_SEGMENT_SPLIT_RE = re.compile(r"\s+--\s+|\s+—\s+")


def _partition_segment(detail: str, partition: str) -> str:
    """The sentence of a multi-partition `unresolved[]` detail that speaks about ONE
    partition. `""` when the detail never names it, or when it says the partition was
    resolved — a resolved partition is not a row a person has to answer."""
    flat = " ".join(str(detail or "").split())
    for segment in _SEGMENT_SPLIT_RE.split(flat):
        if partition and partition in segment:
            return "" if "RESOLVED" in segment else segment
    return ""


def _merge_outcomes(outcomes: list) -> dict:
    """Several instances proving one Then clause. The worst result wins - a person who reads
    "pass" beside a row half of whose tests are red has been told the expensive lie."""
    outcomes = [o for o in outcomes if o]
    if not outcomes:
        return {}
    order = {"bug": 0, "blocked": 1, "wait": 2, "not run": 3, "unreachable": 4, "deferred": 5, "pass": 6}
    worst = min(outcomes, key=lambda o: order.get(o.get("result"), 9))
    tests, seen = [], set()
    for outcome in outcomes:
        for test in outcome.get("tests") or []:
            key = (test.get("instance_id"), test.get("file"))
            if key not in seen:
                seen.add(key)
                tests.append(test)
    return dict(worst, tests=tests)


# --- rows ---------------------------------------------------------------------------------------

def _signature(outcome: dict) -> tuple:
    """What makes two Then clauses one row. The TEST, not the variant: `[self-reference]` and
    `[autonomous]` are one parameterized test proving the same thing about two inputs, and a
    table that gives each its own line stops being readable at the third partition."""
    functions = {(C.function_name(t.get("instance_id")), t.get("file"))
                 for t in outcome.get("tests") or []}
    return (outcome.get("result"), outcome.get("bug"), outcome.get("level"),
            outcome.get("shape"), tuple(sorted(functions)))


def case_rows(story: Story, requirement: str, case_key: str) -> list:
    """The rows of one requirement x case pair: consecutive Then clauses that share an outcome
    travel together, a Then whose outcome differs gets its own row, and each partition the
    automator left unresolved gets one row of its own."""
    meta = story.cases.get(case_key) or {}
    thens = case_thens(Path(meta["path"])) if meta.get("path") else {}
    what = _one_line(C.case_title(Path(meta["path"])) if meta.get("path") else "", 80)
    rows, group = [], None
    for then in sorted(thens):
        outcome = story.then_outcome(case_key, then, requirement)
        if not outcome:
            continue
        signature = _signature(outcome)
        if group and group[0] == signature:
            group[1].append(then)
            group[2].append(outcome)
            continue
        if group:
            rows.append(_row(requirement, what, case_key, group[1], _merge_outcomes(group[2])))
        group = (signature, [then], [outcome])
    if group:
        rows.append(_row(requirement, what, case_key, group[1], _merge_outcomes(group[2])))
    if not rows:
        outcome = story.case_outcome(case_key, requirement)
        if outcome:
            rows.append(_row(requirement, what, case_key, [], outcome))
    for instance in story.unbound_instances(case_key):
        outcome = story.instance_outcome(instance, case_key, requirement)
        if not outcome:
            continue
        row = _row(requirement, what, case_key, [], outcome)
        variant = instance.partition("[")[2].rstrip("]")
        row["partition"] = variant or C.function_name(instance)
        rows.append(row)
    rows.extend(_partition_rows(story, requirement, case_key, what, thens))
    return rows


def _partition_rows(story: Story, requirement: str, case_key: str, what: str, thens: dict) -> list:
    """A partition the automator could not run is a promise the person never got. On 15045 the
    guardrail partition of TC-012 was decided by the person at S5 and then vanished from the
    report, which said the case was covered."""
    out = []
    for entry in story.unresolved_rows(case_key):
        partitions = [str(p) for p in (entry.get("partitions") or []) if str(p).strip()]
        if not partitions and str(entry.get("partition") or "").strip():
            partitions = [str(entry["partition"]).strip()]
        for partition in partitions:
            m = re.fullmatch(r"[Tt]hen[- ](\d+)", partition)
            if m and int(m.group(1)) in thens:
                continue  # already a Then row above; one fact, printed once
            if len(partitions) > 1 and not _partition_segment(entry.get("detail"), partition):
                continue  # the detail says this partition is resolved, or never names it
            outcome = story.unresolved_outcome(entry, case_key, requirement, partition)
            row = _row(requirement, what, case_key, [], outcome)
            row["partition"] = partition
            out.append(row)
    return out


def _row(requirement: str, what: str, case_key: str, thens: list, outcome: dict) -> dict:
    return {"requirement": requirement, "what": what, "case": case_key, "then": list(thens),
            "tests": outcome.get("tests") or [], "level": outcome.get("level") or "",
            "shape": outcome.get("shape") or "", "result": outcome.get("result") or "not run",
            "bug": outcome.get("bug") or "", "basis": outcome.get("basis") or ""}


def not_planned_basis(story: Story, requirement: str) -> str:
    """Why a register requirement got no plan row - the strategist's own words, from the plan
    prose or from the gate-A question packet, never a bare question id."""
    text = C.read_text(C.artifact(story.artifacts, "test-plan.md"))
    # RD1-19: a requirement is matched by its WHOLE name (`R-1` is not `R-13`, `R-3` is not `BR-3`); the safe error is "not found"
    named = re.compile(rf"(?<![\w-]){re.escape(requirement)}(?![\w-])")
    packet = text.partition(QUESTION_PACKET_HEADING)[2]
    for line in packet.splitlines():
        if named.search(line) and line.strip():
            return _first_sentence(re.sub(r"^\s*[\d.\-*]+\s*", "", line), 110)
    reason = _not_planned_section_reason(text, named)
    if reason:
        return reason
    for line in text.splitlines():
        if named.search(line) and "not planned" in line.lower():
            return _first_sentence(line, 110)
    return "no plan row names this requirement and no reason is recorded"


def _not_planned_section_reason(text: str, named) -> str:
    """RD1-19: the reason a `## Not planned` line gives for the requirement `named` matches - the text after the line's first
    ` - ` / ` — `. A line with no reason, or no such section, gives '' (the caller's older branches and phrase follow)."""
    in_section = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_section = bool(re.match(r"##\s+not planned\b", line, re.IGNORECASE))
            continue
        stripped = line.strip()
        if in_section:
            parts = re.split(r"\s[—-]\s", stripped, maxsplit=1)
            # the name is looked for BEFORE the separator only (t-593 F-3): a requirement named inside another line's reason
            # (`- R-13 - duplicates R-1`) is that line's reason, never R-1's; the safe error is "not found"
            if len(parts) == 2 and parts[1].strip() and named.search(parts[0]):
                return _first_sentence(parts[1], 110)
    return ""


def build(root: Path, artifacts: Path) -> dict:
    story = Story(root, artifacts)
    cases_by_requirement: dict = {}
    for key, meta in story.cases.items():
        if story.set_aside(key):
            continue      # A2: an unrun case on an excluded row is the row's decision, not a case of the requirement
        for requirement in meta.get("requirements") or []:
            cases_by_requirement.setdefault(requirement, []).append(key)
    rows = []
    claims = story.unanswered_claims()
    for record in register_requirements(artifacts):
        requirement = record["id"]
        keys = sorted(cases_by_requirement.get(requirement, []), key=_numeric_key)
        if not keys:
            plan_row = story.caseless_plan_row(requirement)
            result = CASELESS_PLAN_RESULTS.get(str(plan_row.get("disposition") or ""), "not planned")
            basis = (_one_line(plan_row.get("reason") or f"plan row {plan_row.get('ts')} is marked "
                               f"{plan_row.get('disposition')} and records no reason")
                     if plan_row else not_planned_basis(story, requirement))
            if result == "not planned" and requirement in claims:
                # P20: a requirement that exists only in the diff and whose behaviour claim nobody has
                # answered is not "not planned" (a plan did not skip it) and never a pass: it waits for the
                # person, said with the same words as a Then that nobody confirmed. A DEFERRED row keeps
                # `deferred` - a person's recorded decision is the more specific fact.
                qid = claims[requirement]
                result, basis = "wait", unconfirmed_basis(story.question_by_id.get(qid), qid)
            elif plan_row and result in ("deferred", "not planned"):
                # A3: the row is excluded because a gate A question is still open (or could not be read): it waits, it does not
                # read as a decision (`deferred` / `not planned`). A settled question leaves the reading as it was.
                # A person's word (a gate waiver of the requirement) closes the walk, so the table does not say `wait` (t-604 F-5)
                open_qid, unknown = ("", "") if requirement in C.waivers_by_requirement(story.pipeline) \
                    else story.open_question_of(requirement)
                if open_qid:
                    result, basis = "wait", unconfirmed_basis(story.question_by_id.get(open_qid), open_qid)
                elif unknown:
                    # could not be read: said so, never "no question is named for it" (t-604 F-6, FR-41)
                    result, basis = "wait", _one_line(f"the plan or its questions could not be read for {requirement}: {unknown}", 120)
            row = {"requirement": requirement, "what": _one_line(record["text"], 80),
                   "case": "", "then": [], "tests": [], "level": "", "shape": "",
                   "result": result, "bug": "", "basis": basis}
            if plan_row:
                row["plan_row"] = str(plan_row.get("ts") or "")
            rows.append(row)
            continue
        for key in keys:
            rows.extend(case_rows(story, requirement, key))
    for row in rows:
        row["basis"] = mark_answered(row.get("basis"), story.questions)
    return {"schema_version": SCHEMA_VERSION, "task": Path(artifacts).name, "rows": rows,
            "legend": dict(LEGEND), "bugs": story.bugs, "bugs_outside_home": story.bugs_outside_home}


def write(artifacts: Path, table: dict) -> Path:
    from event_store import atomic_json
    path = C.artifact_write_path(Path(artifacts), C.TRACE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, table)
    return path


# --- render ----------------------------------------------------------------------------------

def file_letters(rows: list) -> dict:
    """{path: letter} - a test file is named once in the legend and by one letter in the
    table, so the Test column stays narrow enough to read on one screen."""
    files = []
    for row in rows:
        for test in row.get("tests") or []:
            path = str(test.get("file") or "")
            if path and path not in files:
                files.append(path)
    letters: dict = {}
    used = set()
    for path in files:
        # The distinctive word first: every file in a suite is called `test_<area>_<thing>`,
        # so a letter taken off the front labels them all `T`.
        stem = Path(path).stem
        words = [w for w in re.split(r"[^A-Za-z0-9]+", stem) if w and w.lower() != "test"]
        candidates = [w[0].upper() for w in reversed(words)]
        candidates += [c.upper() for c in reversed(stem) if c.isalpha()]
        for candidate in candidates + list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
            if candidate not in used:
                used.add(candidate)
                letters[path] = candidate
                break
    return letters


def _wrap(text: str, width: int = 22) -> str:
    """`<br>` breaks inside a cell instead of a table nobody can read sideways."""
    words = re.findall(r"[^_]+_?|_", str(text or ""))
    lines, current = [], ""
    for word in words:
        if current and len(current) + len(word) > width:
            lines.append(current)
            current = word
        else:
            current += word
    if current:
        lines.append(current)
    return "<br>".join(f"`{line}`" for line in lines) if lines else ""


def _test_cell(row: dict, letters: dict) -> str:
    parts, variants = [], []
    for test in row.get("tests") or []:
        instance = str(test.get("instance_id") or "")
        name, _, variant = instance.partition("[")
        letter = letters.get(str(test.get("file") or ""), "")
        if len(name) <= 34:
            tail = name
        else:
            # Cut on an underscore, never inside a word: `..ingle_graph_and_` reads as a typo,
            # `..single_graph_and_` as a name.
            cut = name.find("_", len(name) - 32)
            tail = ".." + name[cut + 1:] if 0 < cut < len(name) - 8 else ".." + name[-32:]
        cell = (letter + " " if letter else "") + _wrap(tail)
        variants.append(variant.rstrip("]") if variant else "")
        if cell not in parts:
            parts.append(cell)
    if not parts:
        return "—"
    named = [v for v in variants if v]
    suffix = ""
    if named and len(parts) == 1:
        suffix = " [" + (", ".join(named) if len(named) <= 2 else f"{len(named)} variants") + "]"
    return "<br>".join(parts[:3]) + (f"<br>+{len(parts) - 3} more" if len(parts) > 3 else "") + suffix


def _then_cell(row: dict) -> str:
    case = row.get("case") or row.get("plan_row") or "—"
    thens = row.get("then") or []
    if row.get("partition"):
        return f"{case}<br>{row['partition']}"
    if not thens:
        return case
    if len(thens) > 1 and thens == list(range(thens[0], thens[-1] + 1)):
        return f"{case}<br>Then {thens[0]}–{thens[-1]}"
    return f"{case}<br>Then " + ", ".join(str(t) for t in thens)


def _result_cell(row: dict, confirmation: dict | None = None) -> str:
    if row.get("result") == "bug" and row.get("bug"):
        # An unconfirmed bug is still shown by name — it is a real draft — but never as a
        # finding of equal standing: nobody has reproduced it yet (TP1-15045).
        word = (confirmation or {}).get(row["bug"], "confirmed_by_person")
        mark = {"unconfirmed": "<br>unconfirmed", BR.REPRODUCED: "<br>reproduced by the factory"}.get(word, "")
        return f"**{row['bug']}**{mark}"
    return f"**{row.get('result') or '?'}**"


def render(table: dict) -> str:
    rows = table.get("rows") or []
    letters = file_letters(rows)
    bugs = table.get("bugs") or []
    confirmation = {str(b.get("id") or ""): bug_word(b) for b in bugs
                    if isinstance(b, dict)}
    lines = [
        "Sorted by requirement, then by case. Result vocabulary: **pass** · **BUG-n** · **wait** "
        "(the case is handed to a person) · **blocked** (the stand) · **not run** · **unreachable** "
        "(the scenario cannot occur in the product) · **deferred** (a recorded decision) · "
        "**not planned**. Level: " + " · ".join(C.TRACE_LEVELS) + ". Shape: "
        + " · ".join(C.TRACE_SHAPES) + ".", ""]
    if bugs:
        # The legend is word for word what it was while no bug carries a reproduction record (the pins hold it); once one
        # does, "nobody has reproduced" would be false of it, so the sentence says only what is always true (HF8-16, M-2).
        history = any(isinstance(b, dict) and (b.get("reproduced_how") or b.get("reproduction_problems")
                                               or bug_word(b) == BR.REPRODUCED) for b in bugs)
        if not history:
            lines.append(bug_headline(bugs) + " An `unconfirmed` bug is a draft nobody has "
                         "reproduced yet — neither a person at gate B nor a second run on another "
                         "stand — and it counts toward nothing.")
        else:
            legend = bug_headline(bugs) + " An `unconfirmed` bug counts toward nothing."
            if any(bug_word(b) == BR.REPRODUCED for b in bugs if isinstance(b, dict)):
                legend += (" A bug reproduced by the factory failed again on another run or under the analyst's own"
                           " script; no person has confirmed it yet, and it changes no verdict.")
            lines.append(legend)
        lines.append("")
    if letters:
        lines.append("Test files: " + ", ".join(f"**{letter}** = `{path}`"
                                                for path, letter in letters.items()) + ".")
        lines.append("")
    lines.append("| R | What we verify | TC · Then | Test | Level · shape | Result | Basis |")
    lines.append("|:--|:--|:--|:--|:--|:--|:--|")
    for row in rows:
        level_cell = "<br>".join(x for x in (row.get("level"), row.get("shape")) if x) or "—"
        lines.append("| " + " | ".join([
            row.get("requirement") or "—",
            _escape(row.get("what")) or "—",
            _then_cell(row),
            _test_cell(row, letters),
            level_cell,
            _result_cell(row, confirmation),
            _escape(row.get("basis")) or "—",
        ]) + " |")
    return "\n".join(lines) + "\n"


def _escape(text) -> str:
    return " ".join(str(text or "").split()).replace("|", "\\|")


# --- gate B ------------------------------------------------------------------------------------

def decided_at_gate_b(pipeline: dict) -> str:
    """The `## Decided at gate B` section, in the person's own words.

    The 15045 report was written before the gate and still said the bugs "await your word"
    after the person had already said where they go. A report that outlives the decision it
    was written under has to be rewritten by the closure, not left standing."""
    gate = ((pipeline or {}).get("gates") or {}).get("B") or {}
    words = " ".join(str(gate.get("authorization_source") or "").split())
    # The ONE list of live S8/S9 words (`validate_artifacts.check_report_gate_b` quotes the same list, so the two cannot part).
    overrides = C.live_stage_overrides(pipeline, ("S8", "S9"))
    if not words and not overrides:
        return ""
    lines = ["## Decided at gate B", ""]
    if words:
        lines.append(f"- Delivery: \"{words}\"")
    for entry in overrides:
        decision = " ".join(str(entry.get("decision") or "").split())
        match = " ".join(str(entry.get("match") or "").split())
        if decision:
            lines.append(f"- {entry.get('stage')} · {match or 'decision'}: \"{decision}\"")
    lines.append("")
    return "\n".join(lines)


GATE_B_HEADING = "## Decided at gate B"
LEFT_HEADING = "## Left with you"
# The section the gate-B block stands in front of: everything below it is about ourselves.
GATE_B_BEFORE = "## Factory defects"
_ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+\S")


def decided_cases(pipeline: dict, cfg: dict | None = None) -> dict:
    """{case key: the words that decided it} from gate B and the S8/S9 stage overrides.

    Only a decision that NAMES a case closes an item. A person saying where the bugs go has
    not answered "can a read-only user Restore", and a report that quietly dropped the second
    because of the first would be the same silence this table exists to end.

    `cfg` is the story's case-id config (`contract.case_config(artifacts)`). With None the ids are read
    in the PROCESS's own project, so the same report rendered from outside the project (a harness run
    from the repo root) saw no `TP1-13797_TC_001` and pruned nothing, and two renders of one story
    differed in bytes (t-202 F5). A caller that holds the story passes it."""
    out: dict = {}
    gate = ((pipeline or {}).get("gates") or {}).get("B") or {}
    sources = [str(gate.get("authorization_source") or "")]
    sources += [str(entry.get("decision") or "") for entry in C.live_stage_overrides(pipeline, ("S8", "S9"))]
    for text in sources:
        for case in C.case_ids(text, cfg=cfg):
            out.setdefault(case, " ".join(text.split()))
    return out


def _sections(text: str) -> list:
    """[(heading or '', [lines])] in file order, so a section can be replaced in place."""
    out, heading, body = [], "", []
    for line in str(text or "").splitlines():
        if line.strip().startswith("## "):
            out.append((heading, body))
            heading, body = line.rstrip(), []
        else:
            body.append(line)
    out.append((heading, body))
    return out


def close_gate_b(artifacts: Path) -> dict:
    """Rewrite `test-report.md` with what the person decided at the gate.

    The 15045 report was written before gate B and never caught up: it still asked for a word
    on the bugs after the person had given it. The closure appends their words verbatim and
    takes out of "Left with you" every item those words answered."""
    artifacts = Path(artifacts)
    path = artifacts / "test-report.md"
    if not path.exists():
        return {"written": False, "reason": f"no test-report.md at {path}"}
    if G.has_markers(C.read_text(path)):
        # The section is a code-owned block now: cutting it out by heading would leave its markers
        # behind, and a rewrite by hand is exactly what the block exists to end (B-211).
        return {"written": False, "reason": "the report carries code-owned blocks (<!-- facts:... --> markers); "
                f"run `report_facts.py --task {artifacts.name} --write`, which renders \"Decided at gate B\" "
                "and takes the answered items out of \"Left with you\""}
    pipeline = C.load_json(artifacts / "pipeline.json")
    section = decided_at_gate_b(pipeline)
    if not section:
        return {"written": False, "reason": "gates.B carries no words yet"}
    decided = decided_cases(pipeline)
    moved, kept_sections = [], []
    for heading, body in _sections(C.read_text(path)):
        if heading.startswith(GATE_B_HEADING):
            continue  # replaced below; the section is never appended twice
        if heading.startswith(LEFT_HEADING):
            body, moved = _drop_decided_items(body, decided)
        kept_sections.append((heading, body))
    lines = []
    extra = [f"- {case}: \"{decided[case]}\"" for case in sorted(moved, key=_numeric_key)]
    block = section.rstrip("\n").splitlines() + extra + [""]
    inserted = False
    for heading, body in kept_sections:
        if heading.startswith(GATE_B_BEFORE) and not inserted:
            lines.extend(block)
            inserted = True
        if heading:
            lines.append(heading)
        lines.extend(body)
    if not inserted:
        lines.extend([""] + block)
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8", newline="\n")
    return {"written": True, "closed": sorted(moved), "path": str(path)}


def _drop_decided_items(body: list, decided: dict) -> tuple:
    """(the body without the items the person's words answered, the cases removed)."""
    kept, moved, current = [], [], []
    def flush():
        if not current:
            return
        named = [c for c in C.case_ids(" ".join(current)) if c in decided]
        if named:
            moved.extend(named)
        else:
            kept.extend(current)
    for line in body:
        if _ITEM_RE.match(line):
            flush()
            current = [line]
            continue
        if current:
            current.append(line)
        else:
            kept.append(line)
    flush()
    return kept, list(dict.fromkeys(moved))


# --- check -------------------------------------------------------------------------------------

def check(root: Path, artifacts: Path, table: dict | None = None) -> list:
    """One line per problem. A requirement or a case missing from the table is the failure
    this whole file exists to prevent: an absent row reads as a verified one."""
    artifacts = Path(artifacts)
    table = table or build(root, artifacts)
    rows = table.get("rows") or []
    problems = []
    covered_requirements = {str(r.get("requirement") or "") for r in rows}
    for record in register_requirements(artifacts):
        if record["id"] not in covered_requirements:
            problems.append(f"{record['id']} is in the register and in no row of the table")
    covered_cases = set()
    for row in rows:
        key = str(row.get("case") or "")
        if key:
            covered_cases.add(key)
            covered_cases.add(C.split_case_key(key)[1] or key)
    manifest = C.load_json(C.artifact(artifacts, "automation-manifest.json"))
    report = C.load_json(C.artifact(artifacts, "run-report.json"))
    for meta in C.parse_plan(C.artifact(artifacts, "test-plan.md")):
        ts = meta.get("ts")
        for key, case in C.case_index(artifacts).items():
            # A2: a case set aside (unrun, on an excluded row) is deliberately in no row: the plan row speaks for it
            if str(case.get("plan_row") or "") == ts and key not in covered_cases \
                    and not C.case_set_aside(key, str(meta.get("disposition") or ""), manifest, report):
                problems.append(f"{key} (plan row {ts}) is in no row of the table")
    for index, row in enumerate(rows, start=1):
        for error in C.trace_row_errors(row):
            if error == _NO_CASE_ERROR and row.get("plan_row") and not row.get("case"):
                continue  # a requirement a case-less plan row speaks for: the plan row is its place
            problems.append(f"row {index} ({row.get('requirement')}/{row.get('case') or '-'}): {error}")
    return problems


# --- selftest ----------------------------------------------------------------------------------

def selftest() -> int:
    failures = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    case("a delinked aggregate row is dead", is_dead_test({"note": "SUPERSEDED DUPLICATE - split"}), True)
    case("and so is one the critic marked", is_dead_test({"critic_note": "SUPERSEDED DUPLICATE"}), True)
    case("a live row is not", is_dead_test({"note": "extends the 8827 test"}), False)
    case("a STALE unresolved row never reaches the table",
         is_stale_unresolved({"detail": "STALE, kept as a labeled marker only"}), True)
    case("R-10 sorts after R-9", sorted(["R-10", "R-9"], key=_numeric_key), ["R-9", "R-10"])
    case("a basis is one line", _one_line("a\nb   c"), "a b c")
    case("a long basis is cut, not wrapped", _one_line("x" * 40 + " tail", 20).endswith("..."), True)
    row = {"requirement": "R-1", "case": "TC-001", "then": [1, 2, 3], "result": "pass"}
    case("a consecutive Then run renders as a range", _then_cell(row), "TC-001<br>Then 1–3")
    case("a gap renders every number", _then_cell(dict(row, then=[1, 3])), "TC-001<br>Then 1, 3")
    case("a partition names itself instead of a Then",
         _then_cell(dict(row, then=[], partition="guardrail variant")),
         "TC-001<br>guardrail variant")
    case("a bug row prints the record, not the word bug",
         _result_cell({"result": "bug", "bug": "BUG-4"}), "**BUG-4**")
    case("the worst result of several instances wins",
         _merge_outcomes([{"result": "pass", "tests": []}, {"result": "bug", "tests": []}])["result"],
         "bug")
    case("every legend word is a contract result",
         sorted(LEGEND) == sorted(C.TRACE_RESULTS), True)
    letters = file_letters([{"tests": [{"file": "tests/ui/test_visual_diff.py"},
                                       {"file": "tests/api/test_validate.py"}]}])
    case("each test file gets its own letter", len(set(letters.values())), 2)
    gate_b = decided_at_gate_b({"gates": {"B": {"authorization_source": "draft MR, bugs in a file"}},
                                "stage_overrides": [{"stage": "S8", "match": "keep it local",
                                                     "decision": "collect all bugs into a file"}]})
    case("gate B quotes the person", "\"draft MR, bugs in a file\"" in gate_b, True)
    case("and the S8 override beside it", "collect all bugs into a file" in gate_b, True)
    case("no gate, no section", decided_at_gate_b({}), "")
    pipeline = {"gates": {"B": {"authorization_source": "TC-015: accept the risk, do not run it"}},
                "stage_overrides": [{"stage": "S8", "match": "keep it local",
                                     "decision": "collect all bugs into a file"}]}
    case("a decision that names a case closes it", decided_cases(pipeline).get("TC-015"),
         "TC-015: accept the risk, do not run it")
    case("one that names no case closes nothing",
         "TC-001" in decided_cases(pipeline), False)
    body = ["", "1. **A read-only user cannot Restore (R-14, TC-015).** To check: nothing.",
            "2. **Guardrails (R-10, TC-012).** To check: the 400 names the guardrail."]
    kept, moved = _drop_decided_items(body, decided_cases(pipeline))
    case("the answered item leaves the list", moved, ["TC-015"])
    case("and the unanswered one stays",
         [line for line in kept if line.strip()][0].startswith("2."), True)
    for line in failures:
        print("FAIL " + line)
    print(f"traceability.py --selftest: {'ok' if not failures else str(len(failures)) + ' failed'}")
    return 1 if failures else 0


# --- cli ---------------------------------------------------------------------------------------

def resolve(task: str, root: str | None, task_root: str | None) -> tuple:
    if task_root:
        artifacts = Path(task_root).resolve()
        return (artifacts.parents[1], artifacts)
    from hooklib import artifact_root, project_root
    project = Path(root).resolve() if root else project_root()
    return (project / "qa-factory", artifact_root(root=project) / task)


def add_story_options(ap, example: str) -> None:
    """The three options that name a story (`--task`, `--root`, `--task-root`), declared once (AR-15) for this script and `report_facts`."""
    ap.add_argument("--task", default=None, help=f"ticket id, e.g. {example}")
    ap.add_argument("--root", default=None, help="project root (default: the current project)")
    ap.add_argument("--task-root", dest="task_root", default=None, help="the story's artifacts dir")


def story_of(args, script: str):
    """(bugs_root, artifacts) of the story the options name; None, with the refusal printed, when neither `--task` nor `--task-root`
    is given (the caller exits 2). The story first (CX1-18): a phantom is a refusal of the call, exit 2 like every other (E-6; it was 1),
    not a read of nothing. `--root` is the project the KEY resolves under."""
    if args.task is None and args.task_root is None:
        print(f"{script}: --task or --task-root is required", file=sys.stderr)
        return None
    hooklib.story_cli(script, key=args.task, root=args.task_root, project=args.root)
    return resolve(args.task, args.root, args.task_root)


def main() -> None:
    C.force_utf8()
    ap = argparse.ArgumentParser(description="The report's traceability table")
    add_story_options(ap, "TP1-15045")
    ap.add_argument("--write", action="store_true", help="write work/traceability.json")
    ap.add_argument("--render", action="store_true", help="print the report's appendix")
    ap.add_argument("--check", action="store_true", help="exit 1 on a missing R or TC")
    ap.add_argument("--close-gate-b", dest="close_gate_b", action="store_true",
                    help="append the person's gate-B words to test-report.md and drop what "
                         "they answered from 'Left with you'")
    ap.add_argument("--json", action="store_true", help="print the table as JSON")
    ap.add_argument("--oracles", action="store_true",
                    help="print, as JSON only, where the expected value of every Then comes from "
                         "(`contract.resolve_then_oracle`: state settled | open | invalid) - the reader "
                         "the code critic's `invented_expectation` rule asks; read-only")
    ap.add_argument("--selftest", action="store_true")
    args = hooklib.exact_options(ap).parse_args()

    if args.selftest:
        sys.exit(selftest())
    story = story_of(args, "traceability.py")
    if story is None:
        sys.exit(2)
    bugs_root, artifacts = story
    if args.close_gate_b:
        outcome = close_gate_b(artifacts)
        print(("test-report.md: gate B recorded"
               + (", closed " + ", ".join(outcome["closed"]) if outcome.get("closed") else ""))
              if outcome.get("written") else f"test-report.md untouched: {outcome.get('reason')}")
        if outcome.get("written"):
            import validate_artifacts as V
            problems: list = []
            V.check_test_report(artifacts / "test-report.md", problems)
            for line in problems:
                print(line, file=sys.stderr)
            if problems:
                sys.exit(1)
        sys.exit(0)
    if args.oracles:
        print(json.dumps(case_oracles(artifacts), ensure_ascii=False, indent=2))
        sys.exit(0)
    table = build(bugs_root, artifacts)
    if args.write:
        path = write(artifacts, table)
        print(f"traceability: {len(table['rows'])} rows -> {path}")
    if args.check:
        problems = check(bugs_root, artifacts, table)
        for line in problems:
            print(line)
        if problems:
            sys.exit(1)
        if not (args.render or args.json or args.write):
            print(f"traceability: {len(table['rows'])} rows, every register R and plan TC present")
    if args.render:
        print(render(table), end="")
    if args.json:
        print(json.dumps(table, ensure_ascii=False, indent=2))
    if not (args.write or args.check or args.render or args.json):
        print(render(table), end="")
    sys.exit(0)


if __name__ == "__main__":
    main()
