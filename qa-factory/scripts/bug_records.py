"""bug_records.py — the one reader that answers "which bugs belong to THIS story".

Four readers used to answer it four ways (traceability, delivery_summary, factory_dashboard and
the audit trio), and on TP1-13797 every report reader returned zero bugs while `bugs/BUG-1.md`
lay in the story's own folder: the reporter wrote it there after gate B, the readers looked in
`qa-factory/bugs/`. Counting every project bug for every story is the opposite failure (case ids
are numbered per story, `TC_003` and `BUG-1` exist in several stories), so nothing here matches on
a case id or on a bare `BUG-n` number.

The canonical home of a bug file is the PROJECT's `qa-factory/bugs/` (owner, 30.09: bugs are not
pushed with the tests). A bug file of this story is read from either place:
  - it lies in the story's own `bugs/` folder (the folder is the story's), or
  - it lies in the project's `qa-factory/bugs/` AND its front matter `gate_b_decision_id`
    (required of every filed bug by artifact_producer.validate) is one of THIS story's gate B
    decision ids: every decision the controller recorded for gate B of this story
    (`state/controller.json`), not only the last one in `pipeline.json` -> `gates.B.id`. Gate B
    can be decided again (`gateB-T-1`, `gateB-T-1-2`) and a bug filed under the first decision is
    still this story's bug.
A project-home file that carries no decision id, an unreadable one, or one whose id carries no
ticket (a hand-made "B", which can collide between stories) and has no same-name file of this
story to hold it, is returned under `unattributed` and is not counted; one that carries another
story's id is another story's bug and is not listed at all. A record that lies ONLY in the story's
folder is still counted and is also listed under `outside_home`: being in the wrong folder never
hides a bug.

Read-only (FR-45): nothing is created, changed or deleted. The one exception is `write_draft_texts` (the readable text of
each draft, `work/bug-text/`), which only `delivery_summary.write` calls; a reader never does.
"""
import datetime
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import case_stamp as CS  # noqa: E402  (is_red_row: the one reader of a red run row)
import contract as C  # noqa: E402
import hooklib  # noqa: E402  (load_ref_json)
from hooklib import is_story_folder, parse_frontmatter, sorted_paths  # noqa: E402

TITLE_UNREADABLE = "title unreadable"
UNKNOWN = "unknown"
# Both homes are read the way audit_factory, exit_gate and factory_dashboard read the project
# home: *BUG-*.md. Any other .md file in a bug folder (a README) is named in `sources`, never a bug.
BUG_GLOB = "*BUG-*.md"
NOT_BUG_GLOB = "*.md"
DRAFT_SUFFIX = ".json"
DRAFT_GLOB = "*" + DRAFT_SUFFIX
DRAFT_DIR = "bug-drafts"
# What the writer of the drafts (qa-failure-analyst, S7) never produces: a hand-laid `*.md` in the draft
# folder is no draft (I1) and is NAMED by `legacy_md_drafts`, never counted and never silent.
LEGACY_DRAFT_SUFFIX = ".md"
APP_BUG = "APP_BUG"
_NUM_RE = re.compile(r"(\d+)\s*$")
_TICKET_ID_RE = re.compile(r"^gate[A-Z]-\S+$")   # the controller's own form: gate<G>-<ticket>[-n]
SAME_BUG_MAYBE = "may be the same bug: the filed file does not name its draft"


def _natural_key(path: Path) -> tuple:
    """`BUG-10` sorts after `BUG-9`."""
    m = _NUM_RE.search(path.stem)
    return (0 if m else 1, int(m.group(1)) if m else 0, path.name)


def _one_line(text) -> str:
    return " ".join(str(text or "").split())


def _ref(value) -> str:
    """A path as a filed bug writes it in `source_draft`, comparable to a draft's path relative
    to the task root: forward slashes, no leading `./` (a `../` stays, and then matches nothing)."""
    text = str(value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def _pipeline_gate_b_id(task: Path) -> str:
    """The id of the gate B record `pipeline.json` holds (the LAST decision; '' when there is none
    yet, or the record is an old one that never carried an id)."""
    try:
        data = json.loads((task / "pipeline.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    gates = data.get("gates") if isinstance(data, dict) else None
    gate = gates.get("B") if isinstance(gates, dict) else None
    value = gate.get("id") if isinstance(gate, dict) else None
    return value.strip() if isinstance(value, str) else ""


def _controller_gate_b_ids(task: Path) -> list | None:
    """Every gate B decision id the controller recorded for this story, read the way
    delivery_summary reads them (`state/controller.json` -> `decisions`, id or key). None when the
    decisions cannot be read (no file, not JSON, no `decisions` object)."""
    try:
        data = json.loads((task / "state" / "controller.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    decisions = data.get("decisions") if isinstance(data, dict) else None
    if not isinstance(decisions, dict):
        return None
    found = []
    for key, decision in decisions.items():
        if isinstance(decision, dict) and decision.get("gate") == "B":
            value = str(decision.get("id") or key).strip()
            if value:
                found.append(value)
    return found


def _gate_b_ids(task: Path) -> tuple:
    """(sorted ids, latest id, where they came from, note). The set is the controller's decisions
    plus `gates.B.id`; when the controller's decisions cannot be read it is `gates.B.id` alone."""
    latest_pipeline = _pipeline_gate_b_id(task)
    from_controller = _controller_gate_b_ids(task)
    ids = set(from_controller or [])
    if latest_pipeline:
        ids.add(latest_pipeline)
    if from_controller is None:
        return (sorted(ids), latest_pipeline, "pipeline.json gates.B.id only",
                "state/controller.json decisions could not be read; a bug filed under an earlier "
                "gate B decision of this story cannot be joined")
    # the latest: what pipeline.json holds (the controller writes it from the last decision);
    # else the longest id (gateB-T, gateB-T-2, gateB-T-10 grow with each new decision)
    latest = latest_pipeline if latest_pipeline in ids else max(ids, key=lambda i: (len(i), i), default="")
    return sorted(ids), latest, "controller decisions", ""


def _project_home(task: Path, project_root) -> Path | None:
    """`<project>/qa-factory/bugs`, the project the story lives in: the nearest ancestor that
    carries `qa-factory/config.json` (`runtime_paths.nearest_project`, the one walk)."""
    if project_root:
        return Path(project_root).resolve() / "qa-factory" / "bugs"
    from runtime_paths import nearest_project
    base = nearest_project(task)
    return base / "qa-factory" / "bugs" if base else None


def _listing(directory: Path | None, pattern: str, not_bug_pattern: str | None = None) -> tuple:
    """(exists, files sorted naturally, names of other .md files, error text). A folder that
    cannot be listed is named, never taken for an empty one."""
    if directory is None:
        return False, [], [], ""
    try:
        if not directory.is_dir():
            return False, [], [], ""
        files = sorted((p for p in directory.glob(pattern) if p.is_file()), key=_natural_key)
        others = []
        if not_bug_pattern:
            taken = {p.name for p in files}
            others = sorted(p.name for p in directory.glob(not_bug_pattern)
                            if p.is_file() and p.name not in taken)
        return True, files, others, ""
    except OSError as exc:
        return True, [], [], f"cannot list: {exc}"


# ----------------------------------------------------------------- the drafts of a story (G1-9, t-1078)
# ONE reader of the draft folder and ONE pairing of a draft with its triage row, for every site that
# reads either: the S7 claim (handoff_check), the gate B packet (gate_brief) and its rehearsal
# (gate_preflight), the delivery summary, the judge, the dashboard and `story_bugs` below. The census in
# `test_bug_records.py` fails a reader that walks the folder with its own glob (FR-17, FR-10).

def draft_dir(task) -> Path:
    """`<task>/work/bug-drafts`: where the writer (qa-failure-analyst, S7) puts the drafts of gate B."""
    return Path(task) / C.WORK_DIR / DRAFT_DIR


def _draft_homes(task) -> list:
    """`[(label, folder)]`: `work/` first, then the old flat home `<task>/bug-drafts` of a story written before the
    move into `work/` (the order gate B numbers the drafts in: I4). The label is what a message calls the folder."""
    return [(f"{C.WORK_DIR}/{DRAFT_DIR}", draft_dir(task)), (DRAFT_DIR, Path(task) / DRAFT_DIR)]


def _files_with_suffix(directory: Path, suffix: str) -> tuple:
    """`(files, why)`: the regular files of a folder whose suffix is `suffix` (case folded, on every OS: `BD-1.JSON` is
    a draft on Windows and on Linux alike), in the one order of `hooklib.sorted_paths`. A folder that is absent is
    `([], "")`, an empty one too. A folder that cannot be listed (OSError) is NOT empty: it is `([], "cannot list:
    <reason>")`, a state the caller must see (FR-41, FR-59: what could not be read is not 'nothing there')."""
    try:
        if not directory.is_dir():
            return [], ""
        return sorted_paths(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == suffix), ""
    except OSError as exc:
        return [], f"cannot list: {exc}"


def draft_listing(task) -> tuple:
    """`(paths, unreadable)`: `paths` is `draft_paths(task)`; `unreadable` is one `"<home>: cannot list: <reason>"` per
    home that exists and cannot be listed (empty when every home could be read). A caller that gives a VERDICT on the
    drafts (the S7 claim: 'nothing claims a bug') reads this, not `draft_paths`: an unlistable folder is no verdict,
    never 'no drafts'. An absent home and an empty one are not unreadable."""
    paths: list = []
    unreadable: list = []
    for label, home in _draft_homes(task):
        found, why = _files_with_suffix(home, DRAFT_SUFFIX)
        paths.extend(found)
        if why:
            unreadable.append(f"{label}: {why}")
    return paths, unreadable


def draft_paths(task) -> list:
    """Every bug draft of the story: the `*.json` files of `work/bug-drafts/`, then of the old `bug-drafts/`.

    Only what the writer produces counts (I1): a `*.md` laid by hand, a folder called `x.json` and a file of
    another suffix are no draft (`legacy_md_drafts` names the `.md` ones). No folder, an empty folder: `[]`; a folder
    that cannot be listed adds nothing to the list and is never an exception - for a reader that only walks the
    drafts. A reader that gives a verdict on them, or reports how many there are, asks `draft_listing`, which says
    the folder was not read. The caller reads each file and owns the parse policy."""
    return draft_listing(task)[0]


def legacy_md_drafts(task) -> list:
    """The `*.md` files lying in the draft folders: a story from before the drafts were `*.json`, or a file laid by
    hand. NOT drafts (`draft_paths` never returns them); named so that a refusal can say they were not counted."""
    return [path for _label, home in _draft_homes(task)
            for path in _files_with_suffix(home, LEGACY_DRAFT_SUFFIX)[0]]


# ----------------------------------------------------------------- the text of a draft, for a person (HF8-20, AR-16)
# A person never opens a JSON draft (owner, 29.10.2026). `write_draft_texts` writes one readable text per draft into a
# folder of its own: NOT into the draft folder, where `legacy_md_drafts` would name any `*.md` a stray hand-made draft
# and `gate_preflight` a finding. The gate packet and the delivery summary only READ it (`draft_text_paths`, FR-45).
TEXT_DIR = "bug-text"
TEXT_SUFFIX = ".md"


def text_dir(task) -> Path:
    """`<task>/work/bug-text`: where the readable text of each draft lies."""
    return Path(task) / C.WORK_DIR / TEXT_DIR


def draft_text_paths(task) -> list:
    """`[(draft path, text path)]` in the order of `draft_paths`: the ONE mapping of a draft to its text, shared by the
    writer and by the gate packet. The text is named by the draft's stem; a second draft with the same stem (the two
    homes of the drafts) is numbered, so no text overwrites another's."""
    taken: dict = {}
    out = []
    for path in draft_paths(task):
        stem = path.stem
        taken[stem] = taken.get(stem, 0) + 1
        name = stem if taken[stem] == 1 else f"{stem}-{taken[stem]}"
        out.append((path, text_dir(task) / (name + TEXT_SUFFIX)))
    return out


def _step_words(value) -> list:
    """The steps of a draft as one-line strings: a list's entries, or a lone string; nothing else is a step."""
    items = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    return [_one_line(item) for item in items if isinstance(item, (str, int, float)) and _one_line(item)]


def _cause_lines(view: dict) -> list:
    """`## Cause` of a bug with 2+ manifestations (t-2187 N2, 5.17), printed from `cause_view` (M3: the one reader the packet and the
    report print from too): the statement, how it was confirmed IN WORDS (`cause_how_words`), and one `Not verified:` line per claim no
    basis entry confirms (FR-41). A cause that is not confirmed - or whose basis no longer stands - is never printed as one: it says
    "Cause not established" / "Not confirmed"."""
    view = view or {}
    status, statement, why = view.get("status"), view.get("statement") or "", view.get("why") or ""
    lines = ["## Cause"]
    if status == "confirmed":
        how = cause_how_words(view)
        lines.append(statement or "The draft states no cause.")
        lines.append(f"Confirmed {how}." if how else "How the cause was confirmed is not stated.")
    elif status == "unverified":
        lines.append("Not confirmed: " + (statement or "the draft states no cause"))
        lines.append("What is missing: " + (why or "not stated"))
    else:
        lines.append(f"Cause not established: {why or 'the draft does not say why'}.")
    lines += [f"Not verified: {says}" for says in view.get("unverified") or []]
    return lines


RECHECK_SENTENCE = "After the fix, re-check every manifestation; one that still fails is a separate bug."


def _manifestation_lines(data: dict) -> list:
    """`## Manifestations` of a bug with 2+ manifestations (t-2187 N2, 5.17): ALL of them, no cap, one numbered line each: its case (M4:
    `validate_artifacts.check_bug_form` asks the filed bug's section for each manifestation's case and red test, and this text is what
    its refusal tells the reporter to copy from, so every part it asks for is here), the action, the start state, what was seen, the
    requirement it breaks (a manifestation carries no `expected` text of its own: the requirement is what it is expected against) and
    its red test command or `no test: <reason>`. A part a manifestation does not carry is said ("no test stated", "no requirement named",
    "no case named"), never left out (FR-41)."""
    lines = ["## Manifestations"]
    for number, entry in enumerate(manifestation_entries(data), start=1):
        case = _one_line(entry.get("case"))
        parts = [f"case {case}" if case else "no case named",
                 _one_line(entry.get("action")) or "an action the draft does not state"]
        for label, key in (("start", "start_state"), ("seen", "seen")):
            text = _one_line(entry.get(key))
            if text:
                parts.append(f"{label}: {text}")
        requirement = _one_line(entry.get("requirement"))
        parts.append(f"expected: as requirement {requirement} says" if requirement else "expected: no requirement named")
        test = entry.get("red_test")
        command = _one_line(test.get("command")) if isinstance(test, dict) else ""
        reason = _one_line(entry.get("red_test_none"))
        parts.append(f"red test: {command}" if command else f"no test: {reason}" if reason else "no test stated")
        lines.append(f"{number}. " + "; ".join(parts))
    lines.append(RECHECK_SENTENCE)       # spec 8.4: the way a merged bug is closed; the executor is the person after this run
    return lines


def bug_text(data: dict, priority: str = "", word: str = "", kinds=None, problems=None, cause=None) -> str:
    """A draft as text a person reads: the title, the impact with its priority, the steps, what was expected, what was
    seen and how sure the factory is. No field names and no JSON: a part the draft does not carry says so in a
    sentence (FR-41), it is never left out silently. A draft with 2+ manifestations (t-2187 N2) adds `## Cause` and
    `## Manifestations` AFTER the rest (every manifestation, no cap: the packet shows up to six and points here); a draft with
    one manifestation or none gets the text it always got, byte for byte. `cause` is `cause_view(task, data)` as the caller that holds
    the task root built it (so a basis that no longer stands is not printed as confirmed); a caller with no task root passes none and
    gets the draft-only reading (`cause_view(None, data)`)."""
    data = data if isinstance(data, dict) else {}
    impact = _one_line(data.get("impact") or data.get("damage_class"))
    title = _one_line(data.get("title")) or "A bug without a title"
    lines = [f"# {title}", ""]
    if impact or priority:
        lines += [f"Impact: {impact or 'not stated'}" + (f" - priority {priority}" if priority else ""), ""]
    steps = _step_words(data.get("manual_steps")) or _step_words(data.get("steps") or data.get("repro"))
    lines.append("## Steps to see it")
    lines += [f"{n}. {step}" for n, step in enumerate(steps, start=1)] or ["The draft records no steps a person can follow."]
    for heading, value, absent in (("Expected", data.get("expected"), "The draft records no expected result."),
                                   ("What was seen", data.get("actual") or data.get("observed"),
                                    "The draft records no observed result.")):
        lines += ["", f"## {heading}", _one_line(value) or absent]
    lines += ["", "## How sure the factory is",
              reproduction_words({"confirmation": word, "reproduced_how": kinds or [], "reproduction_problems": problems or []})]
    if len(manifestation_entries(data)) >= 2:
        lines += [""] + _cause_lines(cause if cause is not None else cause_view(None, data)) + [""] + _manifestation_lines(data)
    return "\n".join(lines) + "\n"


def write_draft_texts(task) -> list:
    """Write `work/bug-text/<stem>.md` for every draft of the story, from the draft alone, through the one step reader
    (`confirmation_of`) and the one priority scale (`grammar.impact_scale`). Returns `[{"draft": <path relative to the task>,
    "text": <path relative to the task, "" when none was written>, "problem": <why, "" when written>}]`. A draft that is not
    a JSON object, or a text that cannot be written, is skipped with its problem and the others are still written (a bug
    the person is to read must not wait for another one). Called from `delivery_summary.write` ONLY: gate B reads these
    files, it never writes them (FR-45). The text of a draft with 2+ manifestations holds all of them (`bug_text`, t-2187 N2, 5.17)."""
    from event_store import atomic_text   # the one atomic text writer (AR-13); newline="" keeps the "\n" of the text
    task = Path(task)
    out = []
    pairs = draft_text_paths(task)
    if not pairs:
        return out
    try:
        import grammar
        scale = grammar.impact_scale(C.case_config(task))
    except Exception:
        scale = {}
    facts = step_facts(task)
    for draft, target in pairs:
        ref = draft.relative_to(task).as_posix() if draft.is_relative_to(task) else draft.name
        entry = {"draft": ref, "text": "", "problem": ""}
        try:
            data = C.load_json(draft)
            if not isinstance(data, dict) or not data:
                entry["problem"] = "the draft is not readable"
                out.append(entry)
                continue
            word, kinds, problems = confirmation_of(task, data, *facts, draft=True)
            impact = _one_line(data.get("impact") or data.get("damage_class"))
            atomic_text(target, bug_text(data, str((scale.get(impact) or {}).get("priority") or ""), word, kinds, problems,
                                         cause_view(task, data)))
            entry["text"] = target.relative_to(task).as_posix()
        except (OSError, ValueError) as exc:
            entry["problem"] = f"the text could not be written ({type(exc).__name__})"
        out.append(entry)
    return out


def _row_instance(row: dict) -> str:
    return str(row.get("instance_id") or row.get("test") or "").strip()


def draft_triage_key(draft) -> tuple:
    """`(instance_id, attempt_id)` the draft's `triage_ref` names; `("", "")` when it names nothing. The ref is a
    mapping, or `instance@attempt` as a string."""
    ref = draft.get("triage_ref") if isinstance(draft, dict) else None
    if isinstance(ref, str):
        instance, _, attempt = ref.partition("@")
        ref = {"instance_id": instance, "attempt_id": attempt}
    if not isinstance(ref, dict):
        ref = {}
    return str(ref.get("instance_id") or "").strip(), str(ref.get("attempt_id") or "").strip()


def triage_verdicts(rows) -> dict:
    """`{(instance_id, attempt_id): [verdict]}` of the triage rows, plus the same rows under the bare instance
    `(instance_id, "")`: a draft written before 0.7.16 names the instance and no attempt. A row that is not an
    object, or names no instance, answers nobody."""
    out: dict = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        instance = _row_instance(row)
        attempt = str(row.get("attempt_id") or "").strip()
        verdict = str(row.get("verdict") or "").strip()
        if instance:
            out.setdefault((instance, attempt), []).append(verdict)
            out.setdefault((instance, ""), []).append(verdict)
    return out


def draft_verdicts(draft, verdicts: dict) -> list:
    """The verdicts of the triage row(s) a draft rests on (`verdicts` is `triage_verdicts(rows)`); `[]` when the
    draft names no row or the row is not there."""
    return verdicts.get(draft_triage_key(draft)) or []


def pair_drafts(drafts: list, rows, filed=()) -> dict:
    """Both ways of the pairing the S7 claim and the gate B rehearsal share. `drafts` is `[(name, draft dict)]`,
    `rows` the rows of `work/triage.json`.

    - `no_row`: the names of the drafts whose `triage_ref` finds no row (or names none);
    - `not_app_bug`: `[(name, [verdict])]` for the drafts whose row exists but none of its verdicts is APP_BUG;
    - `app_bug_rows`: how many rows carry APP_BUG;
    - `app_bug_without_draft`: the labels of the APP_BUG rows no draft rests on (a row names an instance and, when it
      has one, an attempt; a draft naming the instance alone covers every attempt of it; a row with no instance can
      be covered by nobody).
    Several drafts may rest on one row; the pairing refuses a draft with no APP_BUG row and a row with no draft.

    A red that is ANOTHER case's defect (R6, t-1508): an APP_BUG row with `blocking_check` is covered by no draft of its
    own - it is covered when the blocker resolves, BY THE TRIAGE ROWS, to an APP_BUG row of another case that has a draft
    whose `cases` names this row's case (one bug, two cases; the road to `bugs/` is `cases`, AR-27). The blocker is a case
    key (`contract.case_matches`: an area-qualified spelling is the same case) or a test id (`contract.same_id`). Two more
    keys: `duplicate_draft` (the names of the drafts that rest on a row with `blocking_check`: the bug is the blocker's,
    a second draft is a second bug) and `blocker_draft_misses_case` (`[(row label, blocker label)]`: the blocker has its
    draft, which does not list the case in `cases`). Error direction: a blocker that is no APP_BUG row, has no draft, is the
    row's own case, or resolves to nothing leaves the row in `app_bug_without_draft` - a draft is then owed, never waived.

    `same_location` (D1-C2, Q4-d): `[(location, [names])]`, the triage-road drafts that name ONE defect place (`draft_location`), two
    or more of them, sorted by location. Left out: a draft with no place, a code-reading draft (its own one-per-requirement rule),
    a draft that says `distinct_defect`, and a draft in `filed` (the names of the drafts a filed bug names in `source_draft`: a filed
    bug is not rewritten, E-C18).

    One bug, many manifestations (t-2187 N2, 5.1): an APP_BUG row named by a `manifestations[].triage_row` of a draft is covered by
    that draft as well (a bare instance covers every attempt, as a `triage_ref` does) - EXCEPT a row with `blocking_check`, which a
    manifestation never covers (the blocker rule above stands). Two more keys: `manifestation_no_row` (`[(name, label)]`: a
    manifestation names a `triage_row` that is no row, or none that can be read) and `manifestation_not_app_bug` (`[(name, label,
    [verdict])]`: its row exists and none of its verdicts is APP_BUG). A probe or an absorbed code-reading entry names no row and covers
    nothing. Error direction: only toward `app_bug_without_draft` (a draft is owed). PURE: it reads no file - what reads files
    (`merged_unconfirmed`) is a separate function."""
    verdicts = triage_verdicts(rows)
    no_row: list = []
    not_app_bug: list = []
    code_reading: list = []
    for name, draft in drafts:
        if is_code_reading(draft):
            code_reading.append(name)     # rests on no triage row: `code_reading_problems` is its checker (the claim and the rehearsal call it)
            continue
        found = draft_verdicts(draft, verdicts)
        if not found:
            no_row.append(name)
        elif APP_BUG not in found:
            not_app_bug.append((name, sorted({v for v in found if v})))
    keys = {draft_triage_key(draft) for _name, draft in drafts if not is_code_reading(draft)}
    covered_by_manifestation: set = set()
    manifestation_no_row: list = []
    manifestation_not_app_bug: list = []
    for name, draft in drafts:
        if is_code_reading(draft):
            continue
        for entry in manifestation_entries(draft):
            if not entry.get("triage_row"):
                continue      # a probe, or an entry absorbed from a code-reading draft: it names no row and covers none
            key = draft_triage_key({"triage_ref": entry["triage_row"]})
            label = (f"{key[0]}@{key[1]}" if key[1] else key[0]) or "(a triage_row that names no instance_id)"
            found = verdicts.get(key) or []
            if not found:
                if (name, label) not in manifestation_no_row:
                    manifestation_no_row.append((name, label))
            elif APP_BUG not in found:
                if not any(n == name and lab == label for n, lab, _v in manifestation_not_app_bug):
                    manifestation_not_app_bug.append((name, label, sorted({v for v in found if v})))
            else:
                covered_by_manifestation.add(key)
    app_rows = 0
    uncovered: list = []
    duplicate: list = []
    misses: list = []
    pool = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    for row in pool:
        if str(row.get("verdict") or "").strip() != APP_BUG:
            continue
        app_rows += 1
        instance, attempt = _row_instance(row), str(row.get("attempt_id") or "").strip()
        label = f"{instance}@{attempt}" if attempt else instance
        blocker = row.get("blocking_check") if isinstance(row.get("blocking_check"), str) else ""
        if blocker.strip():     # (a manifestation never covers such a row: `covered_by_manifestation` is read below for the others only)
            own = [name for name, draft in drafts
                   if draft_triage_key(draft) in ((instance, attempt), (instance, "")) and instance]
            if own:
                duplicate += [name for name in own if name not in duplicate]
                continue
            verdict = _blocker_cover(row, blocker.strip(), pool, drafts)
            if verdict is True:
                continue
            if verdict:
                misses.append((str(row.get("case") or "").strip() or label, verdict))
                continue
        if not instance:
            uncovered.append("(a row with no instance_id)")
        elif (instance, attempt) not in keys and (instance, "") not in keys:
            # a row a manifestation names is covered, unless the row says its red is another case's defect (`blocking_check`)
            if (blocker.strip() or ((instance, attempt) not in covered_by_manifestation
                                    and (instance, "") not in covered_by_manifestation)):
                uncovered.append(label)
    places: dict = {}
    for name, draft in drafts:
        place = draft_location(draft)
        if (place and name not in filed and isinstance(draft, dict)
                and not _one_line(draft.get("distinct_defect"))):
            places.setdefault(place, []).append(name)
    same = [(place, sorted(names)) for place, names in sorted(places.items()) if len(names) > 1]
    return {"no_row": no_row, "not_app_bug": not_app_bug, "app_bug_rows": app_rows, "code_reading": code_reading,
            "app_bug_without_draft": uncovered, "duplicate_draft": duplicate, "blocker_draft_misses_case": misses,
            "same_location": same, "manifestation_no_row": manifestation_no_row,
            "manifestation_not_app_bug": manifestation_not_app_bug}


def _blocker_cover(row: dict, blocker: str, pool: list, drafts: list):
    """How the draft of a blocker covers `row` (an APP_BUG row with `blocking_check`): True when some APP_BUG row of ANOTHER
    case that the blocker names has a draft listing the row's case in `cases`; the blocker's label (a string) when such a row
    has a draft that does not list it (the draft's cases are `draft_cases`: `case`, `cases` and `manifestations[].case`); False when
    nothing covers it. The blocker resolves among the triage rows only
    (`contract.case_matches` on the row's `case`, `contract.same_id` on its names); a row naming no case is covered by nobody."""
    case = str(row.get("case") or "").strip()
    if not case:
        return False
    miss = ""
    for other in pool:
        if other is row or str(other.get("verdict") or "").strip() != APP_BUG:
            continue
        if isinstance(other.get("blocking_check"), str) and other["blocking_check"].strip():
            continue    # a row that is itself another case's defect is no root: a chain or a cycle covers nothing
        other_case = str(other.get("case") or "").strip()
        if other_case and C.case_matches(case, other_case):
            continue    # the blocker is the row's own case: nothing outside it carries its defect
        if not (C.case_matches(blocker, other_case) if other_case else False) \
                and not any(C.same_id(blocker, n) for n in C.row_names(other)):
            continue
        instance, attempt = _row_instance(other), str(other.get("attempt_id") or "").strip()
        for _name, draft in drafts:
            if not instance or draft_triage_key(draft) not in ((instance, attempt), (instance, "")):
                continue
            listed = draft_cases(draft)      # t-2187 N2: the union of `case`, `cases` and `manifestations[].case`, through the one reader
            if any(isinstance(c, str) and C.case_matches(case, c) for c in listed):
                return True
            miss = other_case or instance
    return miss or False


# --- the code-reading draft (t-1676, RN1-12): a bug candidate no run spoke for -------------------------------------------
# LOCAL-1: the person's settled answers (Q7/Q8/Q9) and S1 code facts predicted three bugs, and none reached gate B, because
# the only road to a draft started at a red test. The second form of a draft (`evidence: "code-reading"`) is the road: an
# ORACLE (a question the person settled, or a register requirement whose `code_says` is `contradicts`) joined with an S1 FACT
# of the code. Code is never the oracle (FR-58, P20): no oracle, no draft. This is the ONE checker (AR-13); the S7 claim and the
# gate B rehearsal call it, the gate packet and the report only read the draft's own fields. Error direction: a refusal.
CODE_READING = "code-reading"
R_CR_FIELDS = "a field of the code-reading draft is missing"
R_CR_NO_ORACLE = "no oracle behind the code-reading draft"
R_CR_QUOTE = "the quote is not in its source"
R_CR_NO_FACT = "the code fact is not one S1 recorded or the code does not hold it"
R_CR_CHECK_STATE = "the check state is not one of not_executed / unverifiable"
R_CR_SUPERSEDED = "a failing test speaks for this requirement now"
R_CR_TWICE = "two code-reading drafts for one requirement"
# The red test travels with the bug (P28, X7-5): the draft check, shape only - `contract.red_test_problems` is the one reader.
R_RED_TEST = "the red test (or why there is none) is not with the draft"


def is_code_reading(draft) -> bool:
    """True for a draft whose `evidence` is exactly `code-reading` (case and spelling are the writer's: `Code-Reading` is no
    such draft and goes the triage road, which refuses it for the lack of a `triage_ref`)."""
    return isinstance(draft, dict) and draft.get("evidence") == CODE_READING


def _norm(text) -> str:
    return " ".join(str(text if text is not None else "").split())


def _read_bundle(task) -> tuple:
    """`(bundle object | None, why)`: `context-bundle.json` read once, the ONE place that opens it (AR-13)."""
    try:
        path = Path(C.artifact(Path(task), "context-bundle.json"))
    except Exception as exc:  # noqa: BLE001 - two diverging copies, an unreadable folder
        return None, f"context-bundle.json cannot be located ({type(exc).__name__})"
    if not path.is_file():
        return None, "context-bundle.json is not there"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None, "context-bundle.json is not readable JSON"
    return (data, "") if isinstance(data, dict) else (None, "context-bundle.json is not a JSON object")


def bundle_fact_list(task) -> tuple:
    """`(facts | None, why)`: THE reader of `context-bundle.json` `facts[]` (AR-13) as the raw list of the dict entries.
    The bundle missing, not JSON, not an object or with no list `facts` is `(None, why)`, never `[]` (FR-41)."""
    data, why = _read_bundle(task)
    if data is None:
        return None, why
    facts = data.get("facts")
    if not isinstance(facts, list):
        return None, "context-bundle.json has no list `facts`"
    return [f for f in facts if isinstance(f, dict)], ""


def bundle_repo_ids(task) -> list:
    """The repository ids the bundle's `source_revisions` name (the places `user_path_failures.resolve_code_path` may look in); `[]` when none."""
    data, _why = _read_bundle(task)
    revisions = data.get("source_revisions") if isinstance(data, dict) else None
    return [str(r.get("repo_id") or r.get("repo")) for r in revisions if isinstance(r, dict) and (r.get("repo_id") or r.get("repo"))] \
        if isinstance(revisions, list) else []


def bundle_facts(task) -> tuple:
    """`({id: [fact, ...]} | None, why)`: the facts of the bundle by id. An id is NOT unique (LOCAL-1 holds `XPANBFLFA-44 AC2
    out-of-stock product` twice, on two files: `record-schemas.json` requires only `id` and `source_refs`), so a value is a
    list, and a caller matches on the id AND the place."""
    facts, why = bundle_fact_list(task)
    if facts is None:
        return None, why
    out: dict = {}
    for fact in facts:
        key = _norm(fact.get("id"))
        if key:
            out.setdefault(key, []).append(fact)
    return out, ""


def _fact_line(fact) -> int | None:
    value = fact.get("line") if isinstance(fact, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _fact_problem(task, fact, by_id, bundle_why) -> str:
    """Why the draft's `fact` does not stand, or `""`. Two forms: `{id, path, line}` of a fact of `facts[]` (any fact of that id with
    this path and line), or a code place `{path, line, quote}` (a place S1 did not record, e.g. the line a later answer makes
    relevant) that code verifies: the path resolves through the one resolver (`user_path_failures.resolve_code_path`) and the
    whitespace-normalized `quote` is the whole text of that line."""
    if not isinstance(fact, dict):
        return "`fact` must be an object"
    path, line = str(fact.get("path") or "").strip(), _fact_line(fact)
    fid = _norm(fact.get("id"))
    if not path or line is None:
        return "`fact` names no `path` and integer `line`"
    if fid:
        if by_id is None:
            return f"the S1 facts cannot be read ({bundle_why}), so fact `{fid}` cannot be checked"
        held = by_id.get(fid)
        if not held:
            return f"`{fid}` is not the id of a fact in context-bundle.json"
        if not any(str(f.get("path") or "").strip() == path and _fact_line(f) == line for f in held):
            return f"no fact `{fid}` of context-bundle.json is at {path}:{line} - copy the path and line of the fact"
        return ""
    quote = _norm(fact.get("quote"))
    if not quote:
        return "a code place needs its `quote` (the text of that line) when no fact `id` is given"
    try:
        import user_path_failures as UPF
        target, why = UPF.resolve_code_path(UPF._project_of(Path(task)), path, bundle_repo_ids(task))
        if target is None:
            return f"the code place {path}:{line} cannot be read ({why})"
        lines = UPF._file_lines(target)
    except Exception as exc:  # noqa: BLE001 - the verification could not run: not a pass
        return f"the code place {path}:{line} could not be verified ({type(exc).__name__})"
    if lines is None or line not in lines:
        return f"{path} has no line {line}"
    if _norm(lines[line]) != quote:
        return f"the text of {path}:{line} is not the quote: quote the whole line as it stands"
    return ""


def _walk_stands_for(task, draft, wanted) -> bool:
    """Does a `walk` entry of this draft stand (`_walk_receipt_problem` says nothing is wrong: record of THIS draft and its place,
    answer `bug`, `answer_problems` == [] now) AND its record's `expectation` is the requirement `wanted` from source `requirement`?
    Data only. Error direction DOWN: anything unreadable, unnamed or unproven is False (AR-28); it may refuse a true bug."""
    try:
        entries = draft.get("reproduction") if isinstance(draft, dict) else None
        if not isinstance(entries, list):
            return False
        names = _names_of_draft(task, draft)
        for entry in entries:
            if not (isinstance(entry, dict) and str(entry.get("kind") or "").strip() == "walk"):
                continue
            if _evidence_problem(Path(task), entry.get("evidence"))[0]:
                continue
            record = json.loads((Path(task).resolve() / str(entry.get("evidence")).strip()).read_bytes().decode("utf-8-sig"))
            expectation = record.get("expectation") if isinstance(record, dict) else None
            if not (isinstance(expectation, dict) and expectation.get("source") == "requirement"
                    and _norm(expectation.get("id")) == wanted):
                continue
            if any(not _walk_receipt_problem(task, name, draft, entry)[0] for name in names):
                return True
    except Exception:  # noqa: BLE001 - an unknown never lifts
        return False
    return False


def _oracle_problems(task, draft, rid, questions, register) -> list:
    """`[(code, detail)]` for the draft's `oracle`. Question form: `branch_accounting._confirmed` (answered, the row unchanged, settled:
    `not_needed` is no expectation) and the quote in the recorded words or the chosen reading. Requirement form (an unambiguous
    requirement with no question): the register row of that R says `code_says: contradicts: <this draft's fact id>` and the quote is
    in its `requirement` cell. Anything else is no oracle."""
    oracle = draft.get("oracle")
    if not isinstance(oracle, dict):
        return [(R_CR_NO_ORACLE, "`oracle` must be an object: {question, quote} or {requirement, quote}")]
    quote = _norm(oracle.get("quote"))
    if not quote:
        return [(R_CR_QUOTE, "`oracle.quote` is empty: quote the person's words, the chosen reading or the requirement as written")]
    qid = _norm(oracle.get("question"))
    if qid:
        import branch_accounting as BA
        import question_register as QR
        if questions is None:
            try:
                questions = {q["id"]: q for q in QR.load(task)["questions"]}
            except Exception:  # noqa: BLE001
                questions = {}
        if not BA._confirmed(questions, qid):
            status = (questions.get(qid) or {}).get("status") or "not in the register"
            return [(R_CR_NO_ORACLE, f"question {qid} is not settled by the person ({status}): no answer, no draft - code is never the oracle")]
        try:
            item = next(a for a in QR.answers_for_brief(task)["answers"] if a["id"] == qid)
        except Exception:  # noqa: BLE001
            item = None
        if item is None:
            return [(R_CR_NO_ORACLE, f"the answer to {qid} cannot be read")]
        held = [_norm(QR.answer_text(item)[0]), _norm(item.get("words")), _norm(item.get("reading_text"))]
        if not any(quote in text for text in held if text):
            return [(R_CR_QUOTE, f"`oracle.quote` is not in the answer to {qid}: quote their words or the reading they chose as written")]
        return []
    wanted = _norm(oracle.get("requirement"))
    if not wanted:
        return [(R_CR_NO_ORACLE, "`oracle` names neither a `question` nor a `requirement`")]
    if wanted != rid:
        return [(R_CR_NO_ORACLE, f"`oracle.requirement` {wanted} is not the requirement the draft violates ({rid or 'none named'})")]
    try:
        rows = {row["r"]: row for row in C.register_rows(register if register is not None else C.read_text(C.artifact(Path(task), "requirements-register.md")))}
    except Exception:  # noqa: BLE001
        rows = {}
    row = rows.get(wanted)
    import branch_accounting as BA
    fid = _norm((draft.get("fact") or {}).get("id")) if isinstance(draft.get("fact"), dict) else ""
    contradicts = bool(row and fid and BA._says((row or {}).get("code_says")) == ("contradicts", fid))
    if row and not contradicts and _walk_stands_for(task, draft, wanted):
        contradicts = True      # t-1991 U2b: a standing walk receipt of this draft whose expectation is this requirement
    if not contradicts:
        return [(R_CR_NO_ORACLE, f"{wanted} does not say `code_says: contradicts: <fact id>` for this draft's fact: with no settled answer "
                 "the requirement must be unambiguous and its register row must record the contradiction")]
    if quote not in _norm(row.get("requirement")):
        return [(R_CR_QUOTE, f"`oracle.quote` is not in the requirement text of {wanted}: quote it as the register has it")]
    return []


def code_reading_problems(task, draft, drafts=None, questions=None, register=None) -> list:
    """`[(code, detail)]` of a code-reading draft; `[]` when it stands. Pure reads, never raises (a check that could not run is
    one problem, never a pass). `drafts` is `[(name, draft)]` of the story (read through `draft_paths` when None); the draft
    itself is found among them by identity. `questions` is `{id: question}` of `question_register.load`, `register` the text of
    `requirements-register.md` (both read when None). Codes: `R_CR_FIELDS`, `R_CR_NO_ORACLE`, `R_CR_QUOTE`, `R_CR_NO_FACT`,
    `R_CR_CHECK_STATE`, `R_CR_SUPERSEDED`, `R_CR_TWICE`."""
    try:
        return _code_reading_problems(task, draft, drafts, questions, register)
    except Exception as exc:  # noqa: BLE001
        return [(R_CR_FIELDS, f"the draft could not be checked ({type(exc).__name__}: {str(exc)[:80]})")]


def _code_reading_problems(task, draft, drafts, questions, register) -> list:
    problems: list = []
    missing = [f for f in C.BUG_DRAFT_CODE_READING_REQUIRED if not draft.get(f)]
    if missing:
        problems.append((R_CR_FIELDS, "missing " + ", ".join(f"`{f}`" for f in missing)))
    if C.red_test_owed(draft, datetime.date.today().isoformat()):   # an undated draft is read as written today
        problems += [(R_RED_TEST, detail) for detail in C.red_test_problems(draft)]
    state = _norm(draft.get("check_state"))
    if "check_state" not in missing and state not in C.CODE_READING_CHECK_STATES:
        problems.append((R_CR_CHECK_STATE, f"`check_state` {state!r} is not one of {list(C.CODE_READING_CHECK_STATES)}: a code-reading "
                         "draft exists only where no factory test spoke; a walk of the analyst may be its receipt"))
    found = C.REQ_ID_RE.findall(str(draft.get("violates") or ""))
    rid = found[0] if found else ""
    if "violates" not in missing and not rid:
        problems.append((R_CR_FIELDS, "`violates` names no requirement (`requirement:R-n`)"))
    if "oracle" not in missing:
        problems += _oracle_problems(task, draft, rid, questions, register)
    if "fact" not in missing:
        by_id, why = bundle_facts(task)
        reason = _fact_problem(task, draft.get("fact"), by_id, why)
        if reason:
            problems.append((R_CR_NO_FACT, reason))
    if rid:
        if drafts is None:
            drafts = [(p.name, C.load_json(p)) for p in draft_paths(task)]
        others = [(n, d) for n, d in drafts if d is not draft]
        twin = [str(n) for n, d in others if is_code_reading(d) and rid in C.REQ_ID_RE.findall(str(d.get("violates") or ""))]
        if twin:
            problems.append((R_CR_TWICE, f"{', '.join(twin)} is also a code-reading draft for {rid}: one requirement, one draft"))
        verdicts = triage_verdicts(step_facts(task)[0])
        import traceability as T
        speaking = [str(n) for n, d in others if not is_code_reading(d) and APP_BUG in draft_verdicts(d, verdicts)
                    and (rid in C.REQ_ID_RE.findall(T._dumped_for_ids([d.get(f) for f in T.DRAFT_REQUIREMENT_FIELDS if d.get(f)]))
                         or rid in draft_requirements(d))]       # m5: a merged draft's `manifestations[].requirement` speaks for R too
        if speaking:
            problems.append((R_CR_SUPERSEDED, f"a failing test now speaks for {rid} ({', '.join(speaking)}): add this draft's code fact "
                             "to that draft as a manifestation (`from_draft: <this draft's file>` and its `evidence`), or to its "
                             "existing fields, and withdraw this one"))
    return problems


# --- the step "reproduced by the factory" (HF8-16, run 12586) ---------------------------------------------------------
# The analyst reproduced a red three times and the report said "nobody has reproduced it". The analyst writes a typed
# receipt (`reproduction` on the draft); THIS module is the one reader of it (AR-13): the word is derived here from the
# receipts, never trusted from the role. Error direction is DOWN everywhere: a receipt that cannot be checked reads
# `unconfirmed` and says why (FR-41). Read-only (FR-45).
REPRODUCED = "reproduced_by_factory"
_PERSON, _RERUN = "confirmed_by_person", "confirmed_by_rerun"
# A run row that is not a product run (a probe of our own checks) never proves a reproduction.
_PROBE_PURPOSES = {"red_probe", "review_probe", "sensitivity_probe"}
# Red is read by `case_stamp.is_red_row` (the one reader of "did the run observe this row red", AR-13).
# The closed words of a reason, the only form of it a person reads (a path or a task root never reaches the report:
# AR-4). `detail` stays with the role-facing finding (`gate_preflight.check_bug_drafts`).
R_NOT_LIST = "not a list of entries"
R_NOT_OBJECT = "an entry that is not an object"
R_KIND = "an unknown kind"
R_OBSERVED = "no observation written"
R_NO_FILE = "no such file"
R_EMPTY_FILE = "empty file"
R_OUTSIDE = "outside the evidence folder"
R_NO_ATTEMPT = "no attempt id"
R_NO_ROW = "no run row for that attempt"
R_SAME_ATTEMPT = "the same attempt as the triage"
R_GREEN = "the test is green now"
R_NOT_RED_NOW = "the test did not fail in its current result"
R_ATTEMPT_NOT_RED = "that attempt did not fail"
R_NO_CURRENT = "the current result of this test is not known"
R_NO_REPORT = "the run report could not be read"
R_NO_TRIAGE = "no APP_BUG triage row"
R_NO_DRAFT = "the draft of this bug is not there"
R_NO_RECEIPT = "no reproduction receipt behind it"
# The walk receipt (t-1991 U2): the record `place_answers.py write` keeps. The words are closed; the detail never carries a path.
R_WALK_RECORD = "the walk record cannot be read"
R_WALK_ANSWER = "the walk did not say bug, or its answer does not stand"
R_WALK_PLACE = "the walk was of another place"
_WALK_WRITER = "place_answers.py"


def _evidence_problem(task: Path, evidence) -> tuple:
    """(code, detail) of a receipt path that does not hold, ('', '') when it holds: a file under `evidence/` of the
    story that is not empty. The judging is `contract.evidence_ref_issue` (the one reader of a path against a root)."""
    if not isinstance(evidence, str) or not evidence.strip():
        return R_NO_FILE, "an entry carries no `evidence` path"
    try:
        issue = C.evidence_ref_issue(task, {"path": evidence}, require_hash=False, under="evidence")
        if issue:
            code = R_NO_FILE if ("is not a file" in issue or "has no path" in issue) else R_OUTSIDE
            return code, issue
        if (task.resolve() / evidence.strip()).resolve().stat().st_size == 0:
            return R_EMPTY_FILE, f"evidence path {evidence.strip()} is an empty file"
    except (OSError, ValueError) as exc:   # ValueError: a NUL in the path; any other junk reads as a file that is not there
        return R_NO_FILE, f"evidence path {evidence.strip()!r} cannot be read: {exc}"
    return "", ""


def _attempt_rows(report, instance: str, attempt: str) -> list:
    """The RAW run rows of one instance in one attempt (not `contract.instance_results`: it drops `diagnostic` rows, and
    an analyst's rerun IS a diagnostic run - the fixture of run 12586, attempt a5ba). Read for the step only: the product
    outcome (FR-18) is read from `product_result_rows` as before. A probe row of our own checks is no run of the product."""
    out = []
    rows = report.get("results") if isinstance(report, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if (row.get("evidence_phase") == "baseline" or row.get("red_probe") or row.get("is_red_probe")
                or str(row.get("purpose") or "").lower() in _PROBE_PURPOSES):
            continue
        name = str(row.get("instance_id") or row.get("test_instance_id") or "").strip() or C.test_instance_id(row)
        if name == instance and str(row.get("attempt_id") or "").strip() == attempt:
            out.append(row)
    return out


def _names_of_draft(task, draft) -> list:
    """The file names of the drafts of the story whose JSON equals `draft` (the callers of the step hand over the draft, not its
    name; a walk record names a draft by file). `[]` when none is found or the folders cannot be read."""
    names: list = []
    try:
        for path in draft_paths(task):
            try:
                if C.load_json(path) == draft:
                    names.append(path.name)
            except Exception:  # noqa: BLE001 - an unreadable draft is no match
                continue
    except Exception:  # noqa: BLE001
        return []
    return names


def _draft_is_of_place(PA, task, name, place) -> bool:
    """True when the live draft file `name` is a draft of `place` by `place_answers.place_of_draft` - the one reading of "which place a
    draft belongs to" (F13: one answer of a place raises every draft of that place, not only the one it names). False for a name that
    is no listed, readable draft: the error goes down (a record never lifts a draft of another place)."""
    name = str(name or "").strip()
    try:
        path = next((p for p in draft_listing(task)[0] if p.name == name), None) if name else None
        draft = hooklib.read_json(path, None, kind=dict) if path is not None else None
        return draft is not None and PA.place_of_draft(task, name, draft) == place
    except Exception:  # noqa: BLE001 - an unknown never lifts
        return False


def _walk_receipt_problem(task, draft_name, draft, entry) -> tuple:
    """`(code, detail)` of a `walk` entry whose record does not stand, `("", "")` when it stands (t-1991 §3.3). Data only (AR-29): the
    record is `evidence/place-answer-<id>.json`, an object written by `place_answers.py`, whose answer is `bug`, names THIS draft
    and the place `place_answers.place_of_draft` gives it, and passes `place_answers.answer_problems` NOW (the one judge of an
    answer, AR-13: the capture is in the recorder's index and unchanged, the expectation has a source). The error goes DOWN: a
    record that cannot be read or checked never lifts a draft. The marker `writer` names the writer; it is not a security boundary."""
    record = hooklib.read_json(Path(task).resolve() / str(entry.get("evidence")).strip(), None, kind=dict)   # the package's one JSON reader (F16)
    if record is None:
        return R_WALK_RECORD, "the walk record is not readable JSON (an object was expected)"
    if record.get("writer") != _WALK_WRITER:
        return R_WALK_RECORD, f"the walk record is not an object written by {_WALK_WRITER}"
    try:
        import place_answers as PA
    except Exception:  # noqa: BLE001 - an unknown never lifts
        return R_WALK_RECORD, "the walk record cannot be checked"
    if record.get("answer") != "bug":
        return R_WALK_ANSWER, f"the walk answered {record.get('answer')!r}, not bug"
    try:
        place = PA.place_of_draft(task, draft_name, draft)
    except Exception:  # noqa: BLE001
        return R_WALK_RECORD, "the walk record cannot be checked"
    if record.get("place") != place or not (record.get("draft") == draft_name or _draft_is_of_place(PA, task, record.get("draft"), place)):
        return R_WALK_PLACE, f"the walk record is of {record.get('place')!r} and draft {record.get('draft')!r}, not this draft"
    problems = PA.answer_problems(task, record, dispatch=record.get("dispatch"))
    if problems:
        return R_WALK_ANSWER, "the walk answer does not stand: " + problems[0][:200]
    return "", ""


def _app_bug_problem(draft, rows) -> tuple:
    """The draft-wide fact 1: its triage row says APP_BUG. `(code, detail)` or `()`."""
    if APP_BUG not in draft_verdicts(draft, triage_verdicts(rows)):
        return (R_NO_TRIAGE, "the draft's `triage_ref` finds no triage row with the verdict APP_BUG")
    return ()


def _current_red_problem(draft, report) -> tuple:
    """The draft-wide fact 2: when the report is readable, the instance's CURRENT result is red. `(code, detail)` or `()`; a report
    that cannot be read adds none (as before: the entries then rest on their own checks)."""
    if not (isinstance(report, dict) and bool(report)):
        return ()
    instance = draft_triage_key(draft)[0]
    try:
        current = C.current_instance_results(report).get(instance)
    except Exception:
        return ()
    if current is None:
        return (R_NO_CURRENT, f"the run report holds no current row of {instance!r}")
    if not CS.is_red_row(current):
        status = C.result_status(current)
        code = R_GREEN if status == "passed" else R_NOT_RED_NOW   # a skipped / not-run / unknown row is not "green"
        return (code, f"the current result of {instance!r} is {status or 'not recorded'}")
    return ()


def _walk_has_no_run(draft, report) -> bool:
    """Is a draft one with no `current_results` row by construction: a code-reading draft, or a triage key that names a failure of
    kind `manual` / `observation` (F6)? An unreadable report or key is False (the red-now fact then stays on)."""
    if is_code_reading(draft):
        return True
    instance = draft_triage_key(draft)[0]
    if not instance or not isinstance(report, dict):
        return False
    try:
        failures = C.triage_failures(report)[0]
    except Exception:  # noqa: BLE001
        return False
    return any(kind in ("manual", "observation") and instance in (got.get("names") or [])
               for (kind, _name), got in failures.items())


def reproduction_problems(task, draft, rows, report) -> tuple:
    """`(valid_entries, problems)` of a draft's `reproduction` receipts; pure, never raises. `problems` is a list of
    `(code, detail)`: `code` is a closed word (a person may read it), `detail` names the path or the field (the role
    reads it, in the finding of `gate_preflight.check_bug_drafts`).

    No field, `None` or `[]` is "nobody reproduced it": `([], [])`, no finding. An entry is valid when its `kind` is one of
    `contract.BUG_REPRODUCTION_KINDS`, `observed` says something, `evidence` names a non-empty file under `evidence/` of the
    story, and for a `fresh_data_rerun` the `attempt_id` is another attempt than the one the triage row rests on AND the run
    report holds a red row of THIS instance in THAT attempt. Whether the data was fresh is the role's word (FR-47, P2);
    an `own_script` is not judged by the code. On top of the entries, two facts of the draft: its triage row says APP_BUG
    (`draft_verdicts`) and, when the report is readable, the instance's CURRENT result is red (`current_instance_results`;
    a current row that is not found reads as "not known" - the error goes down). Any of these failing makes every entry
    void: `([], [(code, detail)])`. One valid entry out of three is a step; the other two are problems."""
    entries = draft.get("reproduction") if isinstance(draft, dict) else None
    if entries is None or entries == []:
        return [], []
    if not isinstance(entries, list):
        return [], [(R_NOT_LIST, f"`reproduction` must be a list of {{kind, evidence, observed}} entries, not {type(entries).__name__}")]
    task = Path(task)
    instance, attempt = draft_triage_key(draft)
    report_ok = isinstance(report, dict) and bool(report)
    if report_ok:
        try:
            C.current_instance_results(report)
        except Exception:
            report_ok = False
    # The two draft-wide facts, per entry kind (t-1991 §3.3 POSITION). Every non-walk entry is judged by BOTH, exactly as before;
    # a `walk` entry skips the APP_BUG fact only for a code-reading draft (no triage row by construction) and the red-now fact
    # only for a draft with no current result by construction (code-reading, or a manual check / observation).
    wide = _app_bug_problem(draft, rows) or _current_red_problem(draft, report)
    has_walk = any(isinstance(e, dict) and str(e.get("kind") or "").strip() == "walk" for e in entries)
    if wide and not has_walk:
        return [], [wide]
    walk_wide = ()
    if has_walk:
        no_report = () if (report_ok or is_code_reading(draft)) else (R_NO_REPORT, "run-report.json cannot be read")   # an unknown never lifts
        walk_wide = (() if is_code_reading(draft) else _app_bug_problem(draft, rows)) or no_report \
            or (() if _walk_has_no_run(draft, report) else _current_red_problem(draft, report))
    valid: list = []
    problems: list = []
    wide_said = False
    for number, entry in enumerate(entries, start=1):
        label = f"reproduction[{number}]"
        walking = isinstance(entry, dict) and str(entry.get("kind") or "").strip() == "walk"
        if wide and not walking:
            if not wide_said:
                problems.append(wide)
                wide_said = True
            continue
        if not isinstance(entry, dict):
            problems.append((R_NOT_OBJECT, f"{label} must be an object"))
            continue
        kind = str(entry.get("kind") or "").strip()
        if kind not in C.BUG_REPRODUCTION_KINDS:
            problems.append((R_KIND, f"{label} kind {kind!r} is not one of {list(C.BUG_REPRODUCTION_KINDS)}"))
            continue
        observed = entry.get("observed")
        if not (isinstance(observed, str) and observed.strip()):
            problems.append((R_OBSERVED, f"{label} has no `observed` (what the rerun or the script showed)"))
            continue
        code, detail = _evidence_problem(task, entry.get("evidence"))
        if code:
            problems.append((code, f"{label}: {detail}"))
            continue
        if kind == "walk":
            if walk_wide:
                problems.append((walk_wide[0], f"{label}: {walk_wide[1]}"))
                continue
            first = (R_WALK_PLACE, "no draft file of the story has this content")   # the name is the file's: found by content
            for index, name in enumerate(_names_of_draft(task, draft)):
                got = _walk_receipt_problem(task, name, draft, entry)
                if not got[0]:
                    first = got
                    break
                first = got if index == 0 else first        # the first file's reason stands (no branching on a reason's text, F17)
            if first[0]:
                problems.append((first[0], f"{label}: {first[1]}"))
                continue
        if kind == "fresh_data_rerun":
            wanted = entry.get("attempt_id")
            wanted = wanted.strip() if isinstance(wanted, str) else ""
            if not wanted:
                problems.append((R_NO_ATTEMPT, f"{label} (fresh_data_rerun) needs the `attempt_id` of the rerun"))
                continue
            if wanted == attempt:
                problems.append((R_SAME_ATTEMPT, f"{label} names attempt {wanted}, the attempt the triage row rests on"))
                continue
            if not report_ok:
                problems.append((R_NO_REPORT, f"{label}: run-report.json cannot be read"))
                continue
            of_attempt = _attempt_rows(report, instance, wanted)
            if not any(CS.is_red_row(r) for r in of_attempt):
                code = R_ATTEMPT_NOT_RED if of_attempt else R_NO_ROW
                problems.append((code, f"{label}: run-report.json holds no red row of {instance!r} in attempt {wanted}"))
                continue
        valid.append(entry)
    return valid, problems


def _load_triage_rows(task: Path) -> list:
    try:
        return C.triage_rows(C.load_json(C.artifact(task, "triage.json")))
    except Exception:
        return []


def _load_run_report(task: Path) -> dict:
    try:
        return C.load_json(C.artifact(task, "run-report.json"))
    except Exception:
        return {}


def step_facts(task) -> tuple:
    """`(triage rows, run report)` of a story, for a caller that asks `confirmation_of` about many bugs and reads them once.
    A file that is not there reads `[]` / `{}` (the receipts are then unchecked, which is `unconfirmed`, never a pass)."""
    task = Path(task)
    return _load_triage_rows(task), _load_run_report(task)


def _draft_of(task: Path, ref) -> dict:
    """The draft a filed bug names in `source_draft`, read through `draft_paths` (the one reader of the folders), `{}` when
    it is not there (deleted, renamed, or a path that is no draft)."""
    ref = _ref(ref)
    if not ref:
        return {}
    wanted = {ref, f"{C.WORK_DIR}/{ref}"}
    for path in draft_paths(task):
        try:
            if path.relative_to(task).as_posix() in wanted:
                return C.load_json(path)
        except ValueError:
            continue
    return {}


def confirmation_of(task, data, rows=None, report=None, *, draft=False) -> tuple:
    """`(word, kinds, problems)`: THE reader of the step of one bug (AR-13). `data` is a draft, or what a filed bug / a
    proposal carries: `{confirmation, source_draft}`. `kinds` are the kinds of the valid receipts (closed words),
    `problems` the closed REASON words (`reproduction_problems` codes, deduplicated), never a path. `rows` / `report` are
    the triage rows and the run report; `None` reads them from the story (a caller with many bugs reads them once).

    - `confirmed_by_person` / `confirmed_by_rerun` and a record with no `confirmation` (legacy, `confirmed_by_person`) are
      returned as `contract.bug_confirmation` gives them: nothing here lowers a word a person stood behind, and no receipt
      check is made for them (a filed bug is never re-litigated);
    - `unconfirmed` stays `unconfirmed` unless the draft carries `reproduction` that holds: on the draft itself, or - for a
      filed bug - on the draft its `source_draft` names (the form tells the analyst to ALWAYS write `unconfirmed`, so
      the filed file says it beside a valid receipt, F-1; the receipt is the step, the file's word is the default). A
      draft that is not there, or has no receipts, adds no reason for an `unconfirmed` word;
    - `reproduced_by_factory` written by a role holds only if a valid receipt backs it, same places; otherwise
      `unconfirmed` with the reason. A typo reads `unconfirmed` (`contract.bug_confirmation`).
    - `draft=True` (the CALLER says it read a DRAFT, never guessed from content): a draft with no `confirmation` word, or an empty one,
      is `unconfirmed` - the form says the analyst ALWAYS writes it, and an unknown is never a pass (FR-59, AR-28). The default
      (`draft=False`) is the legacy reading of a FILED bug: no word is `confirmed_by_person`."""
    if draft and not (isinstance(data, dict) and str(data.get("confirmation") or "").strip()):
        return "unconfirmed", [], []
    word = C.bug_confirmation(data)
    if word in (_PERSON, _RERUN):
        return word, [], []
    task = Path(task).resolve()
    data = data if isinstance(data, dict) else {}
    draft = data
    if "reproduction" not in data:
        if "source_draft" not in data:
            return "unconfirmed", [], []     # no receipts anywhere: "nobody has reproduced it" (a role's bare word is no step)
        draft = _draft_of(task, data.get("source_draft"))
        if not draft:
            # a draft that is not there is a fact worth a reason only for a bug that CLAIMS the step
            return "unconfirmed", [], ([R_NO_DRAFT] if word == REPRODUCED else [])
    if "reproduction" not in draft:
        return "unconfirmed", [], ([R_NO_RECEIPT] if word == REPRODUCED else [])
    if rows is None:
        rows = _load_triage_rows(task)
    if report is None:
        report = _load_run_report(task)
    valid, problems = reproduction_problems(task, draft, rows, report)
    codes = list(dict.fromkeys(code for code, _detail in problems))
    if valid:
        return REPRODUCED, list(dict.fromkeys(str(e.get("kind")) for e in valid)), codes
    return "unconfirmed", [], codes


_FRESH_WORDS = "failed again on another run, and the analyst says on fresh data"
_SCRIPT_WORDS = "the analyst's own script reproduced it"
_WALK_WORDS = "the analyst walked it on the stand"


def reproduction_words(record, cut=None) -> str:
    """The sentence about a bug's step, ONE function for every surface that prints it (the report, the table legend, the
    gate B packet, the delivery fragment: FR-10). Three cases, chosen by the record's fields alone (FR-12):
    a step (`confirmation` is `reproduced_by_factory`): says it was reproduced by the factory and that no person has
    confirmed it; `reproduction_problems` and no step: says a reproduction is recorded but could not be checked, by the closed
    reason words (`cut` is the caller's truncation of that list); otherwise the bug is `unconfirmed` and nobody has
    reproduced it. No path, no JSON."""
    record = record if isinstance(record, dict) else {}
    if record.get("confirmation") == REPRODUCED:
        kinds = [k for k in (record.get("reproduced_how") or []) if k in C.BUG_REPRODUCTION_KINDS]
        parts = ([_FRESH_WORDS] if "fresh_data_rerun" in kinds else []) + ([_SCRIPT_WORDS] if "own_script" in kinds else []) \
            + ([_WALK_WORDS] if "walk" in kinds else [])
        return "reproduced by the factory — " + " and ".join(parts or ["it failed again"]) + "; no person has confirmed it yet"
    reasons = [str(r) for r in (record.get("reproduction_problems") or []) if str(r).strip()]
    if reasons:
        text = "; ".join(reasons)
        if cut is not None:
            text = cut(text)   # the report's one truncation (`report_facts._cut`); the closed words are short anyway
        return f"unconfirmed — a reproduction is recorded but could not be checked: {text}; it counts toward nothing"
    return "unconfirmed — nobody has reproduced it; it counts toward nothing"


# --- where a filed bug lies and whether the tracker has it (HF8-21) ---------------------------------------------------------
# The reporter writes a proposal and never calls the tracker, so it cannot say "sent"; THIS is the one reader of the answer
# (AR-13), derived from the files and the config. Error direction is DOWN: a state that cannot be established is `unknown`
# or `not_sent`, never `sent` (FR-41, FR-59). Read-only (FR-45).
_MARKDOWN_CHANNELS = ("", "markdown")   # the executor's own pair (`external_writes.py`: `bugs_channel not in ("", "markdown")`)
UNKNOWN_TRACKER_WORDS = "the tracker receipt could not be read"
_TRACKER_STATE_WORDS = {"sent": "sent", "pending": "the write is proposed and not made yet", "unknown": UNKNOWN_TRACKER_WORDS}


def _json_object(path: Path):
    """`(dict, False)`, or `(None, True)` for a file that is not a JSON object (the caller names it as unreadable)."""
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, ValueError):
        return None, True
    return (data, False) if isinstance(data, dict) else (None, True)


def _proposals_of(task: Path, name: str) -> tuple:
    """`(matches, unreadable)`: the bug proposals of the story that name the bug file `name`, and whether a proposal file could
    not be read at all (it may have been this bug's)."""
    found, broken = [], False
    for home in (task / C.WORK_DIR / "proposals", task / "proposals"):
        for path in _files_with_suffix(home, DRAFT_SUFFIX)[0]:
            data, bad = _json_object(path)
            broken = broken or bad
            if data and data.get("kind") == "bug" and Path(str(data.get("bug_file") or "")).name == name:
                found.append(data)
    return found, broken


def _kept_local_by_word(task: Path) -> bool:
    """Did the person say at gate B that the bugs stay in the repository: the rows `waiver.py` recorded, read with the
    executor's own words (`external_writes.LOCAL_ONLY_RE`), in S8/S9 or with no stage."""
    import external_writes as EW
    data, _bad = _json_object(task / "pipeline.json")
    # `gate_waivers` as before; a revoked override is no word (`contract.live_stage_overrides`, GW1-1), the twin of the executor's read.
    rows = [r for r in ((data or {}).get("gate_waivers") or []) if isinstance(r, dict)] + C.live_stage_overrides(data)
    # The twin of `external_writes.local_only_decision` (AR-13): a row with EMPTY words is skipped there before the pattern is
    # tried, so it is skipped here too - else the report says "you said keep it local" over a write the executor attempts.
    return any(_one_line(r.get("decision"))
               and EW.LOCAL_ONLY_RE.search(_one_line(r.get("decision")) + " " + _one_line(r.get("requirement") or r.get("match")))
               and str(r.get("stage") or "S8") in ("S8", "S9") for r in rows)


def filing_of(task, record) -> dict:
    """`{"file": "bugs/BUG-1.md" | "", "tracker": {"state": sent | not_sent | pending | unknown, "key", "url", "why"}}` of one bug
    record of `story_bugs`: THE reader of "where did it land" (AR-13). `file` is empty for a draft nobody filed (then nothing was
    to be sent: `not_sent`, `why` empty). For a filed bug: a recorded id (the proposal's result or the file's own `external_id`)
    is `sent`; otherwise the first that holds of: the run is closed (`run_closed`), the project keeps bugs in markdown
    (`project_choice`), the person said to keep it local (`gate_b_word`), a proposal waits (`pending`), no delivery is configured
    (`no_access`); else, and on any read problem, `unknown`. `why` is a word of `contract.BUG_NOT_SENT_REASONS` for `not_sent`
    only. Never raises."""
    task = Path(task)
    out = {"file": "", "tracker": {"state": "not_sent", "key": "", "url": "", "why": ""}}
    tracker = out["tracker"]
    md = next((Path(str(p)) for p in (record or {}).get("paths") or [] if str(p).lower().endswith(".md")), None)
    if md is None:
        return out
    out["file"] = f"bugs/{md.name}"
    try:
        fm = parse_frontmatter(md.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")) or {}
        proposals, broken = _proposals_of(task, md.name)
        done = next((p["result"] for p in proposals if isinstance(p.get("result"), dict) and p["result"].get("external_id")), {})
        key = _one_line(done.get("external_id") or fm.get("external_id"))
        if key:
            tracker.update(state="sent", key=key, url=_one_line(done.get("url") or fm.get("external_url")))
            return out
        import external_writes as EW
        ew = (C.case_config(task) or {}).get("external_writes")
        ew = ew if isinstance(ew, dict) else {}
        channel = _one_line(ew.get("bugs") or "markdown")
        why = ("run_closed" if EW.closed_by_run(task) else "project_choice" if channel in _MARKDOWN_CHANNELS
               else "gate_b_word" if _kept_local_by_word(task) else "")
        if why:
            tracker.update(state="not_sent", why=why)
        elif any(p.get("pending") or not p.get("result") for p in proposals):
            tracker["state"] = "pending"
        elif EW.channel_delivery(ew, channel)["method"] == "none" and not broken:
            tracker.update(state="not_sent", why="no_access")
        else:
            tracker["state"] = "unknown"
    except Exception:
        tracker.update(state="unknown", why="")
    return out


def gate_b_choice(task) -> dict:
    """`{"decided": bool, "selected": [draft refs], "words": the person's words}` of the NEWEST gate B decision of the story
    (`state/controller.json`, the one the pipeline names, else the last recorded). Not decided, or unreadable: `decided` False."""
    task = Path(task)
    data, _bad = _json_object(task / "state" / "controller.json")
    found = [(str(d.get("id") or k), d) for k, d in ((data or {}).get("decisions") or {}).items()
             if isinstance(d, dict) and d.get("gate") == "B" and d.get("status") == "approved"] if data else []
    if not found:
        return {"decided": False, "selected": [], "words": ""}
    latest = _pipeline_gate_b_id(task)
    decision = next((d for i, d in found if i == latest), found[-1][1])
    return {"decided": True, "selected": [_ref(r) for r in decision.get("selected_drafts") or []],
            "words": _one_line(decision.get("authorization_source"))}


def not_chosen_at_gate_b(task, record, choice=None) -> bool:
    """True for a draft nobody filed that the newest gate B decision did NOT choose: a FACT of the decision's `selected_drafts`
    (`gate_b_choice`), never a reading of the person's words (FR-12). A filed bug, or a gate B not yet decided, is never so."""
    choice = gate_b_choice(task) if choice is None else choice
    if not choice["decided"] or not (record or {}).get("paths") or (record or {}).get("filed"):
        return False
    task = Path(task).resolve()
    refs = set()
    for raw in record["paths"]:
        try:
            ref = Path(raw).resolve().relative_to(task).as_posix()
        except (ValueError, OSError):
            continue
        refs |= {ref, ref.removeprefix(C.WORK_DIR + "/")}
    return not refs & {s.removeprefix(C.WORK_DIR + "/") for s in choice["selected"]} and not refs & set(choice["selected"])


def filing_words(filing) -> str:
    """The sentence of `filing_of` for a person, one function for every surface (FR-10): `file: bugs/BUG-1.md · tracker: not sent
    — the project keeps bugs in markdown`; `""` for a draft nobody filed. The reason words are data (`handoffs/vocabulary.yaml`
    `bug_not_sent_reasons`); a reason with no word there reads as the factory not being able to say why. No path but the bug
    file's own."""
    filing = filing if isinstance(filing, dict) else {}
    tracker = filing.get("tracker") if isinstance(filing.get("tracker"), dict) else {}
    if not filing.get("file"):
        return ""
    state = tracker.get("state")
    if state == "not_sent":
        try:
            import handoff
            said = (handoff.vocabulary().get("bug_not_sent_reasons") or {}).get(tracker.get("why"))
        except Exception:
            said = None
        text = "not sent — " + (str(said) if said else "the factory cannot say why")
    elif state == "sent":
        text = "sent as " + (tracker.get("key") or "an issue") + (f" ({tracker['url']})" if tracker.get("url") else "")
    else:
        text = _TRACKER_STATE_WORDS.get(state) or UNKNOWN_TRACKER_WORDS
        text = "unknown — " + text if state != "pending" else text
    return f"file: {filing['file']} · tracker: {text}"


def _bug_file(path: Path) -> dict:
    """One bug file, read once. Unreadable (not UTF-8, empty, no front matter, an OS error) is a
    state of the file, never a reason to skip it."""
    fm: dict = {}
    try:
        text = path.read_bytes().decode("utf-8-sig")
        fm = parse_frontmatter(text.replace("\r\n", "\n")) or {}
    except (OSError, UnicodeDecodeError):
        fm = {}
    readable = bool(fm)
    return {"name": path.name, "path": path.as_posix(), "readable": readable,
            "title": _one_line(fm.get("title")),
            "gate": str(fm.get("gate_b_decision_id") or "").strip(),
            # the raw `task` front matter, for `owner_of` (the one place that reads it: not a third reader)
            "task": fm.get("task"),
            "source_draft": _ref(fm.get("source_draft")),
            # the bug's own `impact` (severity is derived from it, K5): the file first, the draft after (story_bugs)
            "impact": _one_line(fm.get("impact") or fm.get("damage_class")),
            # ONE rule for the state of a READABLE file, the contract's: no `confirmation` reads
            # as confirmed (a bug filed before 0.7.16), the same as traceability, delivery_summary
            # and the dashboard. An unreadable file has no state to default: it is `unknown`.
            # This is the WORD AS WRITTEN; `reproduced_by_factory` is checked in `story_bugs` (`confirmation_of`).
            "confirmation": (C.bug_confirmation({"confirmation": fm.get("confirmation")})
                             if readable else UNKNOWN)}


def _new_record(facts: dict, home: str) -> dict:
    return {"id": Path(facts["name"]).stem, "title": facts["title"] or TITLE_UNREADABLE,
            "confirmation": facts["confirmation"], "state": "", "filed": True,
            "paths": [facts["path"]], "homes": [home], "gate_b_decision_id": facts["gate"],
            "impact": facts["impact"], "reproduced_how": [], "reproduction_problems": [],
            "notes": [], "_readable": facts["readable"], "_drafts": {facts["source_draft"]}}


def _carries_ticket(decision_id: str) -> bool:
    return bool(_TICKET_ID_RE.match(decision_id or ""))


def _not_merged_notes(task_record: dict, project_record: dict) -> None:
    """Two same-name files that are not one bug: each names the other."""
    task_gate = task_record["gate_b_decision_id"] if task_record["_readable"] else "(unreadable)"
    task_record["notes"].append(
        f"a file with the same name lies in the project's bug folder ({project_record['paths'][0]}) with "
        f"gate_b_decision_id {project_record['gate_b_decision_id']!r}; this file has {task_gate!r}; "
        f"read as two bugs")
    project_record["notes"].append(
        f"a file with the same name lies in the story's folder ({task_record['paths'][0]}) with "
        f"gate_b_decision_id {task_gate!r}; this file has {project_record['gate_b_decision_id']!r}; "
        f"read as two bugs")


MINE, OTHER = "mine", "other"
# What a caller passes as `owner_of(..., facts=)` when its own join failed: not a mapping, so the join cannot say "mine".
NO_JOIN = "no-join"
_DIGIT_TAIL_RE = re.compile(r"-\d+$")


def _story_exists(root: Path, name) -> bool:
    """`name` is a story of `root` (`hooklib.is_story_folder`, the one rule: ONE path component, a folder of that exact
    spelling found in the listing) that also holds a `pipeline.json` file: the stricter test is this module's own.
    Anything else, an OS error included, is no story (the error direction is "unknown", which is then checked)."""
    try:
        return is_story_folder(root, name) and (Path(root) / name / "pipeline.json").is_file()
    except OSError:
        return False


def _gate_id_stories(gate_id: str, root: Path, me: str) -> tuple:
    """(names this story, the OTHER existing stories it names) for a controller-form id `gate<G>-<ticket>[-n]`.
    The ticket and the `-n` of a repeated decision are told apart only by the disk: every cut of the digit tails
    is a candidate, and a candidate counts only if it is this story's name or an existing story's."""
    candidate = gate_id.split("-", 1)[1]
    names = [candidate]
    while _DIGIT_TAIL_RE.search(candidate):
        candidate = _DIGIT_TAIL_RE.sub("", candidate, count=1)
        names.append(candidate)
    mine = any(n.casefold() == me.casefold() for n in names)
    return mine, {n for n in names if n.casefold() != me.casefold() and _story_exists(root, n)}


def owner_of(bug, task_root, facts=None) -> str:
    """`mine`, `other` or `unknown`: whose is the project-home bug file `bug`, as seen from the story `task_root`.

    `other` only when something POSITIVELY names another story that exists on disk (the front matter `task`, or a
    controller-form `gate_b_decision_id` naming it) and nothing names this one. `mine` when `task` is this story's
    (casefold) or the id names it or the join below counted the file. Everything else is `unknown`, and the gate
    CHECKS `unknown` like `mine` (FR-59): a ticket-less id, this story's earlier decision whose `controller.json`
    cannot be read, `task` and id naming different stories, a `task` that is no story here or no string, an
    unreadable file, a story with no `pipeline.json` (no folder to hold a bug against). Never raises.

    `facts` is `story_bugs(task_root)` read once by the caller (one join per audit, not per bug); `None` reads it
    here. A join that failed (`NO_JOIN`, or anything that is not a mapping; a `story_bugs` that raises here) cannot
    say "mine", so a file that neither `task` nor the id names as this story's is `unknown` and is checked - never
    `other`, which the join's silence would otherwise leave standing (spec edge 12)."""
    try:
        task_root = Path(task_root)
        root, me = task_root.parent, task_root.name
        if not (task_root / "pipeline.json").is_file():
            return UNKNOWN
        bug = Path(bug)
        record = _bug_file(bug)
        if not record["readable"]:
            return UNKNOWN
        named_me, others = False, set()
        value = record["task"]
        if isinstance(value, str) and value.strip():
            name = value.strip()
            if name.casefold() == me.casefold():
                named_me = True
            elif _story_exists(root, name):
                others.add(name)
            else:
                return UNKNOWN    # a story we cannot find: a typo of this one is as likely as another story
        elif value is not None and not isinstance(value, str):
            return UNKNOWN
        if record["gate"] and _carries_ticket(record["gate"]):
            mine, elsewhere = _gate_id_stories(record["gate"], root, me)
            named_me = named_me or mine
            if len(elsewhere) > 1:
                return UNKNOWN
            others |= elsewhere
        if not named_me:
            joined = story_bugs(task_root) if facts is None else facts
            if not isinstance(joined, dict):
                return UNKNOWN
            counted = {Path(p).resolve() for r in joined.get("records") or [] for p in r.get("paths") or []}
            named_me = bug.resolve() in counted
        if named_me:
            return UNKNOWN if others else MINE
        return OTHER if others else UNKNOWN
    except Exception:
        return UNKNOWN


def story_bugs(task_root, project_root=None) -> dict:
    """{"records": [...], "sources": [...], "unattributed": [...], "outside_home": [...],
        "gate_b_decision_ids": [str], "gate_b_decision_id": str}

    records: one per bug of THIS story, each {id, title, confirmation, state, filed, paths,
      homes, gate_b_decision_id, impact, reproduced_how, reproduction_problems, notes}. `state` is
      "confirmed", "reproduced" (`reproduced_by_factory`, HF8-16: backed by a receipt `confirmation_of` checked),
      "unconfirmed" or "unknown" (an unreadable file: it is a record, and is in none of the groups);
      `confirmation` is the contract's value, derived by `confirmation_of` ("unknown" for an unreadable
      file); `source_drafts` the refs a filed bug names in `source_draft` (sorted, `[]` for a draft and for a bug
      naming none; `_draft_of` reads one); `impact` is the file's, else its draft's; `reproduced_how` the kinds of the valid receipts and
      `reproduction_problems` the closed reason words of the ones that did not hold. `paths` are absolute, the project copy first when
      a record lies in both homes, a draft last; `homes` say where copies were found: "task",
      "project", "drafts". A copy in both homes with EQUAL gate_b_decision_ids is ONE record; two
      same-name files with different ids (or an unreadable one) are two records, each with a note
      naming the other. A draft and the filed bug whose `source_draft` resolves to it (with or
      without a `work/` prefix) are ONE record; a draft that only has the same title as a filed
      bug is NOT merged: both carry a note, and `sources` counts such pairs.
    sources: one entry per place looked at: {home, path, exists, files, ...}; a directory that
      does not exist is named, not skipped; `not_a_bug_file` lists the other .md files of a bug
      folder; the project entry says where the gate B ids came from.
    unattributed: project-home files that cannot be joined to any story (no decision id, an
      unreadable file, or a ticket-less id with no same-name file of this story): {id, title,
      paths, homes, reason}. Not counted.
    outside_home: records that exist ONLY in the story's folder (the project's `qa-factory/bugs/`
      is the canonical home): {id, title, paths, homes, reason}. Still counted in `records`.
    gate_b_decision_ids: every gate B decision id of this story the project-home files were
      joined on (sorted; [] = no gate B record yet, so no project-home file could be joined).
    gate_b_decision_id: the latest of them ('' when none)."""
    task = Path(task_root).resolve()
    gate_ids, gate_id, ids_from, ids_note = _gate_b_ids(task)
    gate_set = set(gate_ids)
    records: list = []
    unattributed: list = []
    sources: list = []

    # 1. The story's own folder: every bug file in it is the story's.
    exists, files, others, error = _listing(task / "bugs", BUG_GLOB, NOT_BUG_GLOB)
    sources.append({"home": "task", "path": (task / "bugs").as_posix(), "exists": exists,
                    "files": len(files),
                    **({"not_a_bug_file": others} if others else {}),
                    **({"error": error} if error else {})})
    by_name: dict = {}
    for path in files:
        record = _new_record(_bug_file(path), "task")
        records.append(record)
        by_name[path.name] = record

    # 2. The project home: only what joins to THIS story's gate B.
    home = _project_home(task, project_root)
    exists, files, others, error = _listing(home, BUG_GLOB, NOT_BUG_GLOB)
    counted = other_id = 0
    for path in files:
        facts = _bug_file(path)
        if not facts["gate"]:
            unattributed.append({
                "id": path.stem, "title": facts["title"] or TITLE_UNREADABLE, "paths": [facts["path"]],
                "homes": ["project"],
                "reason": ("front matter unreadable" if not facts["readable"]
                           else "no gate_b_decision_id in front matter")})
            continue
        if facts["gate"] not in gate_set:
            other_id += 1   # another story's bug (or this story has no gate B record to join to)
            continue
        twin = by_name.get(path.name)
        same_id = bool(twin and twin["_readable"] and twin["gate_b_decision_id"] == facts["gate"])
        if not _carries_ticket(facts["gate"]) and not same_id:
            # a hand-made id ("B") can collide between stories: only the story's own file holds it
            unattributed.append({
                "id": path.stem, "title": facts["title"] or TITLE_UNREADABLE, "paths": [facts["path"]],
                "homes": ["project"],
                "reason": (f"gate_b_decision_id {facts['gate']!r} carries no ticket, so it could belong "
                           f"to any story; it joins only a file of the same name in this story's folder "
                           f"with the same id")})
            continue
        counted += 1
        if same_id:
            # The same bug in both homes: the project copy (the canonical home) is named first.
            twin["paths"].insert(0, facts["path"])
            twin["homes"].append("project")
            twin["_drafts"].add(facts["source_draft"])
            continue
        record = _new_record(facts, "project")
        if twin is not None:
            _not_merged_notes(twin, record)
        records.append(record)
    sources.append({"home": "project", "path": home.as_posix() if home else None, "exists": exists,
                    "files": len(files), "counted": counted, "unattributed": len(unattributed),
                    "other_id": other_id, "gate_b_ids_from": ids_from,
                    **({"gate_b_ids_note": ids_note} if ids_note else {}),
                    **({"not_a_bug_file": others} if others else {}),
                    **({"error": error} if error else {}),
                    **({} if home else {"note": "no qa-factory/config.json above the task folder"})})

    # 3. Unfiled drafts, added as traceability.bug_records adds them; a draft that a filed bug
    #    names in `source_draft` (delivery_summary's pairing key; a real file writes it with or
    #    without the `work/` prefix, the reporter's charter says without) is that bug, not a
    #    second one. Never a case id: numbering is per story. A title alone is not a name: it
    #    leaves both and says so.
    #    The files come from `draft_paths` (both homes, the suffix case folded: the claim, the gate and the
    #    reports read the same set). `exists` is true when the story's `work/` folder is there OR a draft lies in
    #    either home (never 'exists: False, files: 1'); `error` is a home that could not be listed - the count is
    #    then not 0 'drafts' but a count of what could be read, and the entry says so.
    draft_home = draft_dir(task)
    exists, _, _, error = _listing(draft_home, DRAFT_GLOB)
    listed, unreadable = draft_listing(task)
    files = sorted(listed, key=_natural_key)
    exists = exists or bool(files) or bool(unreadable)   # a home that cannot be listed is there
    error = "; ".join(unreadable) or error
    skipped: list = []
    paired = 0
    named: dict = {}
    for record in records:
        for ref in record["_drafts"]:
            if ref:
                named.setdefault(ref, record)
                named.setdefault(f"{C.WORK_DIR}/{ref}", record)
    draft_records: list = []
    cache: dict = {}

    def facts_once():
        """The triage rows and the run report, read ONCE per call (a story with many drafts reads them once)."""
        if not cache:
            cache["facts"] = step_facts(task)
        return cache["facts"]
    for path in files:
        data = C.load_json(path)
        if not data:
            skipped.append(path.name)   # today's rule (not an object, or empty), but named
            continue
        ref = path.relative_to(task).as_posix()
        record = named.get(ref)
        if record is not None:
            if not record["impact"]:
                record["impact"] = _one_line(data.get("impact") or data.get("damage_class"))
            record["paths"].append(path.as_posix())
            if "drafts" not in record["homes"]:
                record["homes"].append("drafts")
            paired += 1
            continue
        word, kinds, problems = confirmation_of(task, data, *facts_once(), draft=True)
        draft_records.append({"id": str(data.get("id") or path.stem),
                              "title": _one_line(data.get("title") or data.get("summary")) or TITLE_UNREADABLE,
                              "confirmation": word, "state": "", "filed": False,
                              "paths": [path.as_posix()], "homes": ["drafts"], "gate_b_decision_id": "",
                              "impact": _one_line(data.get("impact") or data.get("damage_class")),
                              "reproduced_how": kinds, "reproduction_problems": problems,
                              "notes": [], "_readable": True, "_drafts": set()})
    maybe_same = 0
    for filed in records:
        if not filed["filed"] or not filed["_readable"] or filed["title"] == TITLE_UNREADABLE:
            continue
        if "drafts" in filed["homes"]:
            continue   # its draft is named and paired: nothing to guess
        for draft in draft_records:
            if draft["title"] != TITLE_UNREADABLE and draft["title"].casefold() == filed["title"].casefold():
                maybe_same += 1
                filed["notes"].append(f"{SAME_BUG_MAYBE} ({draft['paths'][0]})")
                draft["notes"].append(f"{SAME_BUG_MAYBE} ({filed['paths'][0]})")
    records.extend(draft_records)
    sources.append({"home": "drafts", "path": draft_home.as_posix(), "exists": exists,
                    "files": len(files), "paired_with_filed": paired, "maybe_same_by_title": maybe_same,
                    **({"skipped_unreadable": skipped} if skipped else {}),
                    **({"error": error} if error else {})})

    outside_home: list = []
    for record in records:
        if not record["_readable"]:
            record["state"] = UNKNOWN
        else:
            says = record["confirmation"]
            refs = sorted(r for r in record["_drafts"] if r)
            if record["filed"] and (says == REPRODUCED or (says == "unconfirmed" and refs)):
                # a filed bug is read against its draft's receipts, before `_drafts` goes (a draft paired with it, or
                # named in `source_draft`, whichever backs it): one that SAYS it was reproduced is checked, and one that
                # says `unconfirmed` (the analyst's default) is lifted by a valid receipt (F-1)
                answers = [confirmation_of(task, {"confirmation": says, "source_draft": ref}, *facts_once())
                           for ref in refs or [""]]
                word, kinds, problems = next((a for a in answers if a[0] == REPRODUCED), answers[-1])
                record["confirmation"], record["reproduced_how"], record["reproduction_problems"] = word, kinds, problems
            word = record["confirmation"]
            record["state"] = ("unconfirmed" if word == "unconfirmed"
                               else "reproduced" if word == REPRODUCED else "confirmed")
        if "task" in record["homes"] and "project" not in record["homes"]:
            outside_home.append({
                "id": record["id"], "title": record["title"], "paths": record["paths"][:1],
                "homes": list(record["homes"]),
                "reason": "this bug file lies in the story's own folder, not in the project's bug folder "
                          "(qa-factory/bugs); it is counted anyway"})
        # HF8-22 (L-A): the drafts a filed bug names, public, so that the one reader of "which case does this bug belong
        # to" (`traceability.story_bug_records`) reads the draft the filed file's front matter did not copy. A draft
        # record and a bug that names none read [].
        record["source_drafts"] = sorted(ref for ref in record["_drafts"] if ref)
        del record["_readable"], record["_drafts"]
    return {"records": records, "sources": sources, "unattributed": unattributed,
            "outside_home": outside_home, "gate_b_decision_ids": gate_ids, "gate_b_decision_id": gate_id}


# --- open bugs of the story's own sources (RN1-18) ----------------------------------------------------------------------
# A draft that says what an OPEN bug of the story's sources already says is not a new bug (FR-22: the road to a bug is kept,
# the person is told). Read-only (FR-45); the hint never files or drops a draft.
BUG_STATUS_WORDS_FILE = "bug-status-words.json"
_SOURCE_TICKETS = ("work", "sources")
_LOCATION_RE = re.compile(r"(?<![\w./\\-])[\w.\\/-]+\.[A-Za-z]\w*:\d+(?!\d)")


def bug_status_words() -> tuple:
    """`({"bug_types": [...], "closed_statuses": [...]}, "")` from `references/bug-status-words.json`, case-folded; `(None, <why>)`
    when the file is absent or not that shape (E-C3: an unknown list never marks a duplicate, so the caller dedups nothing)."""
    try:
        data = hooklib.load_ref_json(BUG_STATUS_WORDS_FILE)      # the one reference reader (axis 16); {} (absent or broken) fails the key lookup below
        words = {}
        for key in ("bug_types", "closed_statuses"):
            if not (isinstance(data[key], list) and all(isinstance(w, str) for w in data[key])):
                raise ValueError(f"`{key}` is not a list of words")
            words[key] = [w.strip().casefold() for w in data[key] if w.strip()]
        return words, ""
    except Exception as exc:  # noqa: BLE001 - any unreadable list is the same state: no list
        return None, f"references/{BUG_STATUS_WORDS_FILE} could not be read ({type(exc).__name__}: {str(exc)[:80]})"


def normalize_location(text) -> str:
    """A `file:line` place in one spelling: forward slashes, whitespace squeezed away; '' when it is not that form."""
    one = "".join(str(text or "").replace("\\", "/").split())
    return one if _LOCATION_RE.fullmatch(one) else ""


def source_bug_scan(task_root) -> dict:
    """`{"bugs": [{"key","summary","status","locations","requirements"}], "notes": [str]}`: the tickets under
    `work/sources/*/*/ticket.json` whose `type` is a bug type and whose `status` is not a closed one (RN1-18 C4).
    `locations`: the `file:line` places the title and description name (`normalize_location`; `[]` when none).
    `requirements`: the R ids whose register Source cell names the ticket key as a whole word (`C.names_whole`; the register is
    read once; unreadable -> `[]`). An unreadable ticket is skipped and COUNTED in a note (E-C4); a missing or unreadable word list
    gives no bugs and a note (E-C3). A ticket with no key is not listed (nothing to point at)."""
    words, why = bug_status_words()
    if words is None:
        return {"bugs": [], "notes": [f"{why}: no draft is compared with the open bugs of the sources"]}
    root = Path(task_root).joinpath(*_SOURCE_TICKETS)
    try:
        tickets = sorted(root.glob("*/*/ticket.json"))
    except OSError:
        tickets = []
    try:
        rows = C.register_rows(C.read_text(C.artifact(Path(task_root), "requirements-register.md")))
    except Exception:  # noqa: BLE001
        rows = []
    bugs, unreadable = [], 0
    for path in tickets:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except (OSError, ValueError):
            unreadable += 1
            continue
        key = _one_line(data.get("key"))
        if not key or _one_line(data.get("type")).casefold() not in words["bug_types"]:
            continue
        status = _one_line(data.get("status"))
        if status.casefold() in words["closed_statuses"]:
            continue
        text = " ".join(str(data.get(k) or "") for k in ("title", "description"))
        places = []
        for hit in _LOCATION_RE.findall(text):
            place = normalize_location(hit)
            if place and place not in places:
                places.append(place)
        bugs.append({"key": key, "summary": _one_line(data.get("title"))[:110], "status": status, "locations": places,
                     "requirements": sorted({row["r"] for row in rows if C.names_whole(key, row.get("source"))})})
    notes = [f"{unreadable} source ticket file(s) could not be read and were skipped"] if unreadable else []
    return {"bugs": sorted(bugs, key=lambda b: b["key"]), "notes": notes}


def open_source_bugs(task_root) -> list:
    """The `bugs` of `source_bug_scan` (RN1-18 C4)."""
    return source_bug_scan(task_root)["bugs"]


def matching_open_bug(location, requirements, bugs) -> dict | None:
    """RN1-18 C5: the first open source bug (in the order given) a draft extends - its `location` equals one of the bug's
    `locations`, or one of the draft's `requirements` is one of the bug's - else None. An empty location equals nothing and an
    empty intersection matches nothing (E-C5: a bug with no location and no requirements is never matched)."""
    place = normalize_location(location)
    wanted = {str(r).strip() for r in requirements or [] if str(r).strip()}
    for bug in bugs or []:
        if (place and place in bug.get("locations", [])) or (wanted and wanted & set(bug.get("requirements", []))):
            return bug
    return None


# --- the place and the requirements of a draft, and the instrument that checks them (D1-C2, Q4) -------------------------
def draft_location(data) -> str:
    """The `file:line` of the defect a draft names in `defect_location` (`normalize_location`); '' when it names none, is not that
    form, or is a code-reading draft (its place is the S1 fact's, and its own rule is one draft per requirement)."""
    if not isinstance(data, dict) or is_code_reading(data):
        return ""
    return normalize_location(data.get("defect_location"))


def draft_requirements(data) -> list:
    """The requirements a draft says it breaks: the valid ids of its `requirements` list (sorted, unique); when that gives none, the
    R ids in `violates` (a string) and in `oracle.requirement`; else []. Plus, always, the valid ids of
    `manifestations[].requirement` (t-2187: the bug's requirements are the union of its manifestations')."""
    if not isinstance(data, dict):
        return []
    listed = data.get("requirements")
    ids = {str(r).strip() for r in (listed if isinstance(listed, list) else []) if C.REQ_ID_RE.fullmatch(str(r).strip())}
    if not ids:
        oracle = data.get("oracle")
        for text in (data.get("violates"), oracle.get("requirement") if isinstance(oracle, dict) else None):
            if isinstance(text, str):
                ids.update(C.REQ_ID_RE.findall(text))
    # t-2187 N1 (AR-26): the requirement each manifestation names is one the bug breaks - the union, on top of the reading above
    for entry in manifestation_entries(data):
        text = entry.get("requirement")
        if isinstance(text, str) and C.REQ_ID_RE.fullmatch(text.strip()):
            ids.add(text.strip())
    return sorted(ids)


def filed_draft_names(task) -> set:
    """The file names of the drafts a filed bug names in `source_draft` (`story_bugs`: the one reader of the bug files); an
    unreadable scan gives the empty set, so a draft is counted rather than dropped."""
    try:
        return {Path(ref).name for record in story_bugs(task)["records"] for ref in record.get("source_drafts") or []}
    except Exception:  # noqa: BLE001
        return set()


def same_location_problems(paired: dict) -> list:
    """One line per group of `pair_drafts(...)["same_location"]`: what is wrong and the two doors out of it (FR-1, FR-57). The merge
    door names `manifestations` (t-2187 N2, 5.16): a merged draft covers each row through its `manifestations[].triage_row`, so no APP_BUG
    row is left without a draft by either door."""
    return [f"the drafts {', '.join(names)} name one defect place {place}; merge them into one draft whose `manifestations` hold "
            "every row, or write `distinct_defect: <why>` on each draft that is another defect"
            for place, names in (paired or {}).get("same_location") or []]


# --- one bug, many manifestations (spec t-2187, node N1): the readers and the problem lists of the merged draft ------------
# A draft may carry the shared cause (`mechanism`) and every way it shows (`manifestations[]`). These are the ONE readers of
# those keys (AR-13). Code checks DATA here: the shape of the keys, that each reference stands (a code line through
# `_fact_problem`, a run through `place_answers.capture_stands`, a triage row in the rows), and that a witness is PRESENT. Whether a
# run discriminates, whether two rows share a cause, whether to merge is the analyst's judgment, accepted by the scribe and the
# person at gate B (AR-29). Error direction: DOWN - what cannot be re-read does not stand, never a pass. A draft with neither key
# (an old one) yields no problem: it is never re-litigated (AR-23). Nothing here refuses itself; the callers (`handoff_check`,
# `gate_preflight`, the gate B packet, the bug text, the report) print what these return, with the door.
R_MECH_SHAPE = "`mechanism` is not shaped as {statement, status, basis, claims, why}"
R_MECH_STATUS = "`mechanism.status` is not one of confirmed / unverified / unknown"
R_MECH_STATEMENT = "`mechanism.statement` is missing: say in one sentence what the cause is when the status is confirmed or unverified"
R_MECH_WHY = "`mechanism.why` is missing: say what is missing when the cause is unknown or unverified"
R_MECH_BASIS_SHAPE = "`mechanism.basis` is not a list of objects"
R_MECH_BASIS_ID = "a `mechanism.basis` entry has no `id`, or two share one"
R_MECH_BASIS_KIND = "a `mechanism.basis` entry has a `kind` that is not code_line / run / person"
R_MECH_CODE_LINE = "a `code_line` basis does not stand"
R_MECH_RUN = "a `run` basis does not stand"
R_MECH_NO_BASIS = "`mechanism.status` is confirmed and no basis entry stands"
R_MECH_CLAIM = "a `mechanism.claims` entry is malformed, or cites a basis id that is not there or does not stand"
R_MAN_SHAPE = "`manifestations` is not a list of objects"
R_MAN_FIELDS = "a manifestation lacks `action`, `start_state`, `seen` or `evidence`"
R_MAN_SOURCE = "a manifestation names neither a `triage_row` nor a `probe` (nor `from_draft` with `evidence`), or names both"
R_MAN_NO_ROW = "a manifestation's `triage_row` is no row of work/triage.json"
R_MAN_NOT_APP_BUG = "a manifestation's `triage_row` is a row whose verdict is not APP_BUG"
R_MAN_PROBE = "a manifestation's `probe` does not stand"
R_MAN_RED_TEST = "a manifestation carries no red test (or why there is none), or both"
R_MAN_PRIMARY = "the first manifestation is not the draft's own row"


def manifestation_entries(draft) -> list:
    """The dict entries of `draft["manifestations"]`; [] when the key is absent or not a list (a caller that must refuse says so
    through `manifestation_problems`: this reader never raises)."""
    items = draft.get("manifestations") if isinstance(draft, dict) else None
    return [e for e in items if isinstance(e, dict)] if isinstance(items, list) else []


def is_absorbed(entry) -> bool:
    """A manifestation absorbed from a code-reading draft: it names `from_draft` and neither a `triage_row` nor a `probe` (nothing was
    run for it: spec t-2187 3.2). The ONE test of that shape (AR-13): `manifestation_problems` does not ask it for `seen` and
    `start_state`, and `manifestation_summary` marks it as found by reading the code."""
    return (isinstance(entry, dict) and bool(_text(entry.get("from_draft"))) and not entry.get("triage_row")
            and not entry.get("probe"))


def draft_cases(draft) -> list:
    """Every case a draft speaks for: `case`, `cases` and `manifestations[].case`, in that order, as written (no case-form parsing:
    a cell is kept whole), without repeats; [] for a draft that names none. The ONE reader of a draft's cases (AR-13)."""
    if not isinstance(draft, dict):
        return []
    out: list = []
    for value in (draft.get("case"), draft.get("cases"), *[e.get("case") for e in manifestation_entries(draft)]):
        for item in value if isinstance(value, list) else [value]:
            text = item.strip() if isinstance(item, str) else ""
            if text and text not in out:
                out.append(text)
    return out


def manifestation_refs(draft) -> list:
    """`[(instance_id, attempt_id)]` the manifestations' `triage_row`s name, in order, without repeats (the shapes `draft_triage_key`
    reads; a bare instance is `(instance, "")` and covers every attempt, as a `triage_ref` does). An entry that is not an object,
    names no row or no instance is skipped: it covers nothing (error direction: a draft is owed, never waived)."""
    out: list = []
    for entry in manifestation_entries(draft):
        key = draft_triage_key({"triage_ref": entry.get("triage_row")})
        if key[0] and key not in out:
            out.append(key)
    return out


def manifestation_summary(draft) -> list:
    """One line per manifestation: `<action>; start: <start_state>; seen: <seen>` (an empty part is left out; whitespace squashed);
    [] when the draft has no `manifestations`. A reader that shows an ordinary bug as today prints nothing for fewer than two. An
    entry absorbed from a code-reading draft (`is_absorbed`: nothing was run) ends with "(found by reading the code, not run)"."""
    lines = []
    for entry in manifestation_entries(draft):
        parts = [_one_line(entry.get("action"))]
        for label, key in (("start", "start_state"), ("seen", "seen")):
            text = _one_line(entry.get(key))
            if text:
                parts.append(f"{label}: {text}")
        if is_absorbed(entry):
            parts.append("(found by reading the code, not run)")
        lines.append("; ".join(p for p in parts if p))
    return lines


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _fold(text) -> str:
    """Whitespace squashed, casefolded: how a quote is compared with the words it claims to come from."""
    return " ".join(str(text or "").split()).casefold()


PERSON_QUOTE_MIN = 12       # non-space characters: a shorter quote ("one bug", "e") says nothing about THESE bugs and never stands


def _person_gap(task, draft, entry) -> str:
    """"" when a `person` basis entry stands, else why not, in words the analyst can act on (FR-1). The entry NAMES its dispatch
    (t-2187 M1): `{id, kind: person, dispatch, quote}`. It stands only when (i) that dispatch is an S7 rework record marked as the
    person's words (`place_answers.person_words_of`, the one reader the `person` source of a place answer uses too), (ii) the cases the
    rework was asked for (its `scope` - the record names no drafts) COVER every case of the merged draft (`draft_cases`; a draft that
    names no case is covered by nothing), and (iii) the quote, whitespace-squashed and casefolded, is in THAT dispatch's words and has
    at least `PERSON_QUOTE_MIN` non-space characters. Invariant: a merge is accepted on the person's word only when the words were
    spoken about these bugs; words against the merge, or about another rework, never legitimise it - the error goes toward "split".
    Whether the words mean "merge" stays the scribe's and the person's question (AR-29). An entry in the old shape (no `dispatch`) does
    not stand. A story with no event journal or an unreadable state gives no words."""
    expected = ("name the S7 rework dispatch the person's words were recorded in (`dispatch`), whose cases cover this draft's, and quote "
                f"at least {PERSON_QUOTE_MIN} non-space characters of those words (`quote`)")
    dispatch = _text(entry.get("dispatch"))
    if not dispatch:
        return f"it names no `dispatch`; {expected}"
    try:
        import place_answers as PA
        info, why = PA.person_words_of(Path(task), dispatch)
    except Exception:  # noqa: BLE001 - an unreadable record confirms nothing
        return "the recorded words could not be read"
    if info is None:
        return f"dispatch {dispatch} is not a recorded person's words ({why}); {expected}"
    if info["stage"] != "S7":
        return f"dispatch {dispatch} is not a rework of S7; {expected}"
    cases = draft_cases(draft)

    def covered(case) -> bool:
        return any(case == member or _case_match(member, case) for member in info["scope"])
    if not cases or not all(covered(case) for case in cases):
        return f"the rework {dispatch} was not asked for the cases of this draft ({', '.join(cases) or 'none named'}); {expected}"
    quote = _fold(entry.get("quote")) if isinstance(entry.get("quote"), str) else ""
    if len("".join(quote.split())) < PERSON_QUOTE_MIN:
        return f"`quote` is shorter than {PERSON_QUOTE_MIN} non-space characters; {expected}"
    if quote not in _fold(info["words"]):
        return f"`quote` is not in the words of dispatch {dispatch}; {expected}"
    return ""


def _case_match(member, case) -> bool:
    try:
        return bool(C.case_matches(str(member), case))
    except Exception:  # noqa: BLE001 - a case that cannot be compared is not covered
        return False


def mechanism_problems(task, draft) -> list:
    """`[(reason, detail)]`: why the draft's `mechanism` does not stand; [] when it stands, and [] for a draft with no `mechanism` key
    (an old draft; the obligation to write one is `contract.BUG_MECHANISM_CUTOFF`'s, not this function's). Checked:
    - shape: an object; `status` exactly one of `contract.MECHANISM_STATUSES` (`Confirmed` is no such word); `statement`, when
      present, text - and non-empty text when the status is `confirmed` or `unverified` (t-2187 A2; optional for `unknown`, whose
      `why` is the text); `why` non-empty when the status is `unknown` or `unverified`; `basis` a list of objects when present (absent
      reads as the empty list), each with a unique `id` and a `kind` of `contract.MECHANISM_BASIS_KINDS`;
    - a `code_line` entry stands by `_fact_problem(task, {path, line, quote}, None, "")` - no `id` goes in, so the code-place branch
      runs and no second code-line verifier exists; a `run` entry stands by `place_answers.capture_stands` (the capture is in the
      recorder's index of the case it names, unchanged, and holds the quote); a `person` entry is a known kind that is not checkable
      by code, but stands (t-2187 A1, M1) by `_person_gap`: it names its `dispatch`, an S7 rework recorded as the person's words whose
      cases cover the draft's, and its `quote` (at least `PERSON_QUOTE_MIN` non-space characters) is in THAT dispatch's words; otherwise
      it does not stand (and is no problem, unless it was the only basis of a confirmed cause: then the problem names what is expected);
    - `confirmed` needs at least one standing entry; every `claims[].confirmed_by` id must be a basis entry that stands (an empty
      list is a claim that is NOT verified, and is not a problem: the packet prints it as such, FR-41).
    Not checked, by design (AR-29): whether a run discriminates, whether the statement is the cause. A capture that is also a
    manifestation's `evidence` is not a problem. Reads only (FR-45)."""
    return _mechanism_scan(task, draft)[0]


def _mechanism_scan(task, draft) -> tuple:
    """`(problems, standing)`: `mechanism_problems`' list and the ids of the basis entries that stand - the ONE walk of the basis, so the
    problem list and `cause_view`'s count of how a cause was confirmed cannot disagree (M3)."""
    if not isinstance(draft, dict) or "mechanism" not in draft:
        return [], set()
    mech = draft["mechanism"]
    if not isinstance(mech, dict):
        return [(R_MECH_SHAPE, f"`mechanism` is {type(mech).__name__}, not an object")], set()
    out = _mech_head_step(mech)
    basis, standing, seen_ids, person_gaps = _mech_basis_walk(task, draft, mech, out)
    if mech.get("status") == "confirmed" and not standing:
        detail = "no `code_line`, `run` or `person` entry stands" if basis else "`basis` is empty"
        out.append((R_MECH_NO_BASIS, detail + ("; " + "; ".join(person_gaps) if person_gaps else "")))
    out += _mech_claim_step(mech, standing, seen_ids)
    return out, standing


def _mech_head_step(mech: dict) -> list:
    """The `status`, `statement` and `why` checks of a `mechanism` object, in the order the reasons are reported."""
    out: list = []
    status = mech.get("status")
    if not isinstance(status, str) or status not in C.MECHANISM_STATUSES:
        out.append((R_MECH_STATUS, f"got {status!r}; the words are {', '.join(C.MECHANISM_STATUSES)}, written exactly"))
    if mech.get("statement") is not None and not isinstance(mech.get("statement"), str):
        out.append((R_MECH_SHAPE, "`mechanism.statement` is not text"))
    elif status in ("confirmed", "unverified") and not _text(mech.get("statement")):
        out.append((R_MECH_STATEMENT, f"status is {status}"))       # t-2187 A2: a cause that is not said is not a cause
    if status in ("unknown", "unverified") and not _text(mech.get("why")):
        out.append((R_MECH_WHY, f"status is {status}"))
    return out


def _mech_basis_step(task, kind: str, entry: dict, label: str) -> list:
    """`[(reason, detail)]` of one basis entry of a checkable kind: a `code_line` by `_fact_problem`, a `run` by `place_answers.capture_stands`."""
    if kind == "code_line":
        why = _fact_problem(task, {k: entry.get(k) for k in ("path", "line", "quote")}, None, "")
        return [(R_MECH_CODE_LINE, f"{label}: {why}")] if why else []
    if kind == "run":
        import place_answers as PA
        try:
            found = PA.capture_stands(Path(task), _text(entry.get("case")), entry.get("capture"), entry.get("quote"), field="basis")
        except Exception as exc:  # noqa: BLE001 - a check that could not run is not a pass
            found = [f"the capture could not be verified ({type(exc).__name__})"]
        return [(R_MECH_RUN, f"{label}: {line}") for line in found]
    return []


def _mech_basis_walk(task, draft: dict, mech: dict, out: list) -> tuple:
    """The ONE walk of `mechanism.basis`: appends its problems to `out`; returns `(basis list, standing ids, seen ids, person gaps)`."""
    basis = mech.get("basis", [])
    standing: set = set()
    seen_ids: set = set()
    person_gaps: list = []
    if not isinstance(basis, list):
        out.append((R_MECH_BASIS_SHAPE, f"`mechanism.basis` is {type(basis).__name__}"))
        basis = []
    for index, entry in enumerate(basis, 1):
        label = f"basis entry {index}"
        if not isinstance(entry, dict):
            out.append((R_MECH_BASIS_SHAPE, f"{label} is not an object"))
            continue
        bid = _text(entry.get("id"))
        if not bid or bid in seen_ids:
            out.append((R_MECH_BASIS_ID, f"{label}: id {bid!r}"))
        label = f"basis entry {bid or index}"
        kind = entry.get("kind")
        if not isinstance(kind, str) or kind not in C.MECHANISM_BASIS_KINDS:
            out.append((R_MECH_BASIS_KIND, f"{label}: kind {kind!r}"))
            seen_ids.add(bid)
            continue
        problems = _mech_basis_step(task, kind, entry, label)
        out += problems
        stands = not problems
        if kind == "person":
            gap = _person_gap(task, draft, entry)
            stands = not gap
            if gap:
                person_gaps.append(f"{label}: {gap}")
        if stands and bid and bid not in seen_ids:
            standing.add(bid)
        seen_ids.add(bid)
    return basis, standing, seen_ids, person_gaps


def _mech_claim_step(mech: dict, standing: set, seen_ids: set) -> list:
    """The `claims[]` checks: each claim has `says` and a `confirmed_by` list, and every id it cites is a basis entry that stands."""
    out: list = []
    claims = mech.get("claims", [])
    if not isinstance(claims, list):
        out.append((R_MECH_CLAIM, "`mechanism.claims` is not a list"))
        claims = []
    for index, claim in enumerate(claims, 1):
        cited = claim.get("confirmed_by", []) if isinstance(claim, dict) else None
        if not isinstance(claim, dict) or not _text(claim.get("says")) or not isinstance(cited, list):
            out.append((R_MECH_CLAIM, f"claim {index} needs `says` (text) and `confirmed_by` (a list of basis ids)"))
            continue
        for bid in cited:
            if not isinstance(bid, str) or bid not in standing:
                out.append((R_MECH_CLAIM, f"claim {index} cites {bid!r}: "
                            + ("not a basis id" if not isinstance(bid, str) or bid not in seen_ids else "that entry does not stand")))
    return out


LOST_EVIDENCE = "the evidence behind it could not be re-read"
_COUNT_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def count_word(n: int) -> str:
    """A count as a word up to ten, as digits beyond: how every carrier says "from two starting states" (FR-10)."""
    return _COUNT_WORDS[n] if isinstance(n, int) and 0 <= n < len(_COUNT_WORDS) else str(n)


def cause_view(task, draft) -> dict:
    """The ONE reader of a draft's cause facts (t-2187 M3, AR-13): the bug text, the gate B packet and the report print from it and can no
    longer disagree. `{}` for a draft with no `mechanism` object (an old draft is read as today). Else:
    `status` - the EFFECTIVE word: `confirmed` only when the draft says so AND `mechanism_problems` finds nothing (a basis that cannot be
    re-read is a cause not established: `unknown`, with `why` = `LOST_EVIDENCE`, never a pass: FR-41, FR-59); a word that is none of the
    contract's three, or `unverified` with no statement, reads `unknown`; `written` - the word the draft wrote ("" when it is not one of
    the three); `statement`, `why` (one line each, whole: the carriers clip); `by_code` - a `code_line` entry stands; `runs` - the number
    of DISTINCT start states of the `run` entries that stand (a run with no start state counts for none: one counting rule); `by_person` -
    a `person` entry stands; `unverified` - the `says` of every claim no basis entry confirms; `links` - `[{"draft", "why"}]` of
    `possibly_same_cause`. With `task` None (a caller that holds no task root) nothing is re-read: the `code_line` and `run` entries count as
    written, a `person` entry never counts, and `status` is the written word. Judges nothing about whether the statement is the cause (AR-29)."""
    mech = draft.get("mechanism") if isinstance(draft, dict) else None
    if not isinstance(mech, dict):
        return {}
    written = mech.get("status") if isinstance(mech.get("status"), str) and mech["status"] in C.MECHANISM_STATUSES else ""
    statement, why = _one_line(mech.get("statement")), _one_line(mech.get("why"))
    status = written or "unknown"
    if status == "unverified" and not statement:
        status = "unknown"         # a hypothesis with no words has nothing to print as one: it is said as not established
    if task is None:
        problems, standing = [], None
    else:
        try:
            problems, standing = _mechanism_scan(task, draft)
        except Exception:  # noqa: BLE001 - a check that could not run is not a pass
            problems, standing = [("the cause could not be checked", "")], set()
    if status == "confirmed" and problems:
        status, why = "unknown", LOST_EVIDENCE
    basis = [b for b in (mech.get("basis") if isinstance(mech.get("basis"), list) else []) if isinstance(b, dict)]
    live = [b for b in basis if (b.get("kind") in ("code_line", "run") if standing is None else _text(b.get("id")) in standing)]
    states = {_fold(b.get("start_state")) for b in live if b.get("kind") == "run" and _fold(b.get("start_state"))}
    claims = [c for c in (mech.get("claims") if isinstance(mech.get("claims"), list) else []) if isinstance(c, dict)]
    return {"status": status, "written": written, "statement": statement, "why": why,
            "by_code": any(b.get("kind") == "code_line" for b in live), "runs": len(states),
            "by_person": any(b.get("kind") == "person" for b in live),
            "unverified": [_one_line(c.get("says")) for c in claims
                           if _one_line(c.get("says")) and not (isinstance(c.get("confirmed_by"), list) and c["confirmed_by"])],
            "links": cause_links(draft)}


def cause_links(draft) -> list:
    """`[{"draft": <as written>, "why": <one line>}]`: the drafts this one names in `possibly_same_cause`, in order, whatever its
    `mechanism` (a draft with no cause can still be linked). The ONE reader of the key (AR-13): the packet and the report map the names to
    their own row numbers."""
    links = draft.get("possibly_same_cause") if isinstance(draft, dict) else None
    return [{"draft": _text(e.get("draft")), "why": _one_line(e.get("why"))}
            for e in (links if isinstance(links, list) else []) if isinstance(e, dict) and _text(e.get("draft"))]


def cause_how_words(view: dict) -> str:
    """How a cause was confirmed, IN WORDS, from `cause_view`: "by the line of the application code that does it", "by trying it from
    <two> starting states", "on your word at gate B", joined by " and "; "" when it names none. The one phrase builder of the three
    carriers (M3)."""
    view = view or {}
    parts = []
    if view.get("by_code"):
        parts.append("by the line of the application code that does it")
    if view.get("runs"):
        parts.append(f"by trying it from {count_word(view['runs'])} starting state{'' if view['runs'] == 1 else 's'}")
    if view.get("by_person"):
        parts.append("on your word at gate B")
    return " and ".join(parts)


def manifestation_problems(task, draft, rows) -> list:
    """`[(reason, detail)]`: why the draft's `manifestations[]` do not stand; [] when they do, and [] for a draft with no
    `manifestations` key (an old draft). `rows` is the list of `work/triage.json` rows. Per entry: an object with non-empty text
    `action`, `start_state`, `seen`, `evidence`; EXACTLY one of `triage_row` (a row of `rows` whose verdicts include APP_BUG: the
    shapes `draft_triage_key` reads, a bare instance covers every attempt) and `probe` (`{case, capture, quote}` that
    `place_answers.capture_stands` accepts) - except an entry absorbed from a code-reading draft (`is_absorbed`), which names `from_draft`
    and its `evidence` and neither of the two (spec t-2187 3.2) and is not asked for `start_state` and `seen` (nothing was run); a red test or a reason there is none, through `contract.red_test_problems`.
    The first entry rests on the draft's own row: with a draft-level `triage_ref`, `manifestations[0].triage_row` names the same row -
    equal instance, and equal attempt or no attempt on either side (a bare instance and a full key of it are one row).
    Shape and cross-references only; whether the entry is the same bug is the analyst's judgment (AR-29). Reads only (FR-45)."""
    if not isinstance(draft, dict) or "manifestations" not in draft:
        return []
    items = draft["manifestations"]
    if not isinstance(items, list) or any(not isinstance(e, dict) for e in items):
        return [(R_MAN_SHAPE, f"`manifestations` is {type(items).__name__}" if not isinstance(items, list) else "an entry is not an object")]
    verdicts = triage_verdicts(rows)
    out: list = []
    for index, entry in enumerate(items, 1):
        label = f"manifestation {index}"
        asked = ("action", "evidence") if is_absorbed(entry) else ("action", "start_state", "seen", "evidence")    # m4: nothing was run for an absorbed one
        lacking = [k for k in asked if not _text(entry.get(k))]
        if lacking:
            out.append((R_MAN_FIELDS, f"{label} lacks {', '.join(lacking)}"))
        has_row, has_probe = bool(entry.get("triage_row")), bool(entry.get("probe"))
        absorbed = bool(_text(entry.get("from_draft"))) and bool(_text(entry.get("evidence")))
        if has_row == has_probe and not (absorbed and not has_row):
            out.append((R_MAN_SOURCE, f"{label}: " + ("both are given" if has_row else "neither is given")))
        if has_row:
            found = verdicts.get(draft_triage_key({"triage_ref": entry["triage_row"]})) or []
            if not found:
                out.append((R_MAN_NO_ROW, f"{label}: {entry['triage_row']!r}"))
            elif APP_BUG not in found:
                out.append((R_MAN_NOT_APP_BUG, f"{label}: verdicts {sorted({v for v in found if v})}"))
        if has_probe:
            probe = entry["probe"]
            if not isinstance(probe, dict):
                out.append((R_MAN_PROBE, f"{label}: `probe` is not an object"))
            else:
                import place_answers as PA
                try:
                    found = PA.capture_stands(Path(task), _text(probe.get("case")), probe.get("capture"), probe.get("quote"), field="probe")
                except Exception as exc:  # noqa: BLE001 - a check that could not run is not a pass
                    found = [f"the capture could not be verified ({type(exc).__name__})"]
                out += [(R_MAN_PROBE, f"{label}: {line}") for line in found]
        out += [(R_MAN_RED_TEST, f"{label}: {line}") for line in C.red_test_problems(entry)]
    own = draft_triage_key(draft)
    if items and own != ("", ""):
        first = draft_triage_key({"triage_ref": items[0].get("triage_row")})
        # t-2187 A-first: the SAME row when the instances are equal and the attempts are equal OR either side names none (a bare
        # instance covers every attempt, the rule `triage_ref` has always had); a different instance is never the same row
        if not (first[0] == own[0] and (first[1] == own[1] or not first[1] or not own[1])):
            out.append((R_MAN_PRIMARY, f"the draft's row is {own[0]}@{own[1]}, the first manifestation's is {first[0]}@{first[1]}"))
    return out


def merged_unconfirmed(task, drafts) -> list:
    """`[(name, first problem)]` (t-2187 N2, F-2 (a)): every draft that merges 2+ manifestations under one cause the factory cannot
    re-read - `mechanism` absent, or its status not exactly `confirmed`, or `mechanism_problems(task, draft)` non-empty. `drafts` is
    `[(name, draft dict)]`; `task` the task root (code lines and captures are read from it). A draft with 0 or 1 manifestation is
    never listed (an ordinary bug, an old draft: no refusal). A `manifestations` list of 2+ items counts even when an item is junk:
    the shape is `manifestation_problems`' business, and an unreadable merge is not a pass. A `person` basis stands here only through
    `_person_gap` (it names its dispatch, the rework covers the draft's cases, the quote is in that dispatch's words: M1). Error direction: only toward "split" - what cannot be
    re-read does not stand. Whether the run discriminates is the analyst's judgment, accepted by the scribe and the person (AR-29).
    Reads only (FR-45): the callers that hold the task root (`handoff_check._claim_bug_has_a_draft`, `gate_preflight.check_bug_drafts`)
    print what it returns, with the door; `pair_drafts` stays pure and does not call it."""
    out: list = []
    for name, draft in drafts or []:
        items = draft.get("manifestations") if isinstance(draft, dict) else None
        if not isinstance(items, list) or len(items) < 2:
            continue
        found = mechanism_problems(task, draft)
        if found:
            reason, detail = found[0]
            out.append((name, f"{reason} ({detail})"))
        elif "mechanism" not in draft:
            out.append((name, "the draft names several manifestations and no `mechanism`"))
        elif draft["mechanism"].get("status") != "confirmed":
            out.append((name, f"the cause is {_text(draft['mechanism'].get('status'))!r}, not confirmed"))
    return out


def main(argv=None) -> int:
    """`bug_records.py open-bugs --task-root <r> [--draft <draft.json>]`: ONE JSON line `{"bugs", "notes", "match"}` - the open bugs of
    the story's sources and, with a draft, the one it extends (`matching_open_bug`; the role decides whether it is the same defect).
    Reads only (FR-45). Exit 0 when the arguments parse (a missing word list is a note), 2 otherwise."""
    import argparse
    ap = argparse.ArgumentParser(prog="bug_records.py")
    sub = ap.add_subparsers(dest="command", required=True)
    one = sub.add_parser("open-bugs")
    one.add_argument("--task-root", required=True)
    one.add_argument("--draft", default="")
    try:
        ns = hooklib.exact_options(ap).parse_args(argv)
    except SystemExit:
        return 2
    task_root = hooklib.story_cli("bug_records.py", root=ns.task_root, key_flag=None)      # CX1-18: a phantom root is refused, exit 2
    scan = source_bug_scan(task_root)
    match, notes = None, list(scan["notes"])
    if ns.draft:
        try:
            draft = json.loads(Path(ns.draft).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            draft = {}
            notes.append(f"the draft {ns.draft} could not be read ({type(exc).__name__}): nothing is matched")
        match = matching_open_bug(draft_location(draft), draft_requirements(draft), scan["bugs"])
    print(json.dumps({"bugs": scan["bugs"], "notes": notes, "match": match}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
