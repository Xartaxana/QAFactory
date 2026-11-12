"""driver_core.py - Driver members and names homed here by ai-packages/qa-factory/scripts/tests/fixtures/driver-layers.json (TD-11 cut by tools/source_split.py); no behaviour of its own."""

import hashlib
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hooklib
from driver_chains import _CHAIN, ThreadSlot
import adapter_forms as AF
import detector_verdict as DV
import project_decisions
import waiver


HERE = Path(__file__).resolve().parent


sys.path.insert(0, str(HERE))


EXIT_DONE, EXIT_ERROR, EXIT_PERSON, EXIT_GAVE_UP = 0, 1, 3, 4

# The infrastructure under `claude -p` failed and the person has nothing to decide (B-012): a login, a
# usage limit, or a transient answer that outlived its retries. Not 3: nothing is asked, so no
# question file exists to go with it.
EXIT_INFRA = 5

# The hosts a role can run under. `claude` is `claude -p` (the default, unchanged); `codex` is the Codex CLI's
# `codex exec` (verified against codex-cli 0.158.0 `--help` and the event names in its binary, not against a live
# run). Selected by `--host` or `driver.host` in config.json.
HOSTS = ("claude", "codex")

# `--until`: the story stops once an action past that gate is reached (same table as
# story_step.STOP_GATES: the gate itself is still asked and recorded).
UNTIL_PAST = {"gate_A": {f"S{i}" for i in range(5, 10)}, "gate_B": {"S9"}}

# --- the refusal loop (t-217: F-cmp2-22, -23, -28b, -28c) ---------------------------------------------

# A dispatch id by its SHAPE: used to tell a boundary part or a captured string that names a dispatch from one that
# does not (`S0:ticket`, `S5:TC-1,TC-2`, `<critic id>`), and to take real ids out of a finding before it is compared.
DISPATCH_ID_RE = re.compile(r"S\d+-qa-[a-z-]+-\d+")

# C1-4b (conductor/1, P22): at gate A / gate B the person's words are an approval only as the gate's own word (`Driver.gate_approval`);
# every other word reaches the conductor, which offers the moves open at the gate. The conductor never records a gate decision
# itself (I6): the driver records `approve` (cards applied first, FR-9), and `rework` goes through the controller with the words file.
GATE_KINDS = ("gate_A", "gate_B")


def finding_lines(lines) -> list:
    """The finding lines of a refusal as they are COMPARED: whitespace collapsed, a real dispatch id replaced by
    `<dispatch>` (the same findings of the next dispatch are the same findings), blanks dropped, de-duplicated and
    sorted - a set, never a count and never an order. `[]` is "no findings", which is never equal to anything (FR-41)."""
    found = set()
    for raw in lines or []:
        line = " ".join(DISPATCH_ID_RE.sub("<dispatch>", str(raw)).split())
        if line:
            found.add(line)
    return sorted(found)


def finding_key(lines) -> str:
    """The identity of a finding set: the sha256 of its `finding_lines`, `""` for an empty set."""
    found = finding_lines(lines)
    return hashlib.sha256("\n".join(found).encode("utf-8")).hexdigest() if found else ""


def gate_refusal(script: str, code, out: str, expect: str, retry=None) -> "Refusal":
    """THE refusal of a G step (C1-7b, §3.1/§3.6): a factory script that must leave something behind did not (FR-1: what failed, what
    was expected, the door). Marked `known = False`, so the known-refusals table never routes it (`route_known`). An empty `out` reads
    "the step said nothing" (E12). Built here once for `Driver.py(check=True, expect=...)` and for a G step that reads a record before
    it decides (readiness `--require`)."""
    refusal = Refusal(f"the factory step {script} did not complete (exit {code}): expected {expect}. The door: retry runs the "
                      f"same command; the step's own words: {(out or '')[-600:] or 'the step said nothing'}", retry=retry)
    refusal.known = False
    return refusal


def json_record(out: str) -> tuple:
    """THE read of a script's printed record (C1-7b fix round, F-1, FR-14; AR-13): `(the first JSON object in out, the text after it)`.
    `(None, out)` when there is no `{` or what follows it does not parse - an unreadable record is `None`, never a guess and never a
    pass: the caller refuses on it (S0's `readiness.py --require --json`, S8's and gate B's `check_delivery.py --json`). It raises
    nothing. The text after the record is what the script printed behind it (readiness's WARN lines)."""
    text = out or ""
    start = text.find("{")
    if start < 0:
        return None, text
    try:
        doc, end = json.JSONDecoder().raw_decode(text[start:])
    except ValueError:
        return None, text
    return doc, text[start + end:].strip()


class Refusal(Exception):
    """A factory script said no. `text` is its message verbatim; `retry` re-runs the step.

    `dispatch` is the id this refusal is about, when the raiser knows it. An id read back out of
    the message it was just written into is the FR-16 class in miniature — the driver wrote
    "exit gate for S1-qa-scout-2" and then went looking for that id with a regex over its own
    sentence. The field is the answer; the regex stays as the reader of refusals other scripts
    raise, whose text is all there is.
    """

    # `known` (C1-7b, F10): False on a refusal of a G step (`py(check=True, expect=...)`, a gate step that left no product): the
    # known-refusals table never routes it (`route_known` returns None), so words that its script's output happens to hold
    # (`already completed`, `STORY BUDGET`, ...) cannot turn it into `continue` past an unwritten product. A class attribute, so a
    # refusal built before this field existed (or by any other raiser) reads True and keeps its move.
    known = True
    chain = None            # TR3-17: a class default too, so a subclass that does not call `super().__init__` still reads None

    def __init__(self, text: str, retry=None, files=None, dispatch: str = "", findings=None, window_findings=None,
                 title: str = "", close=None):
        super().__init__(text)
        # `close` (C2-8): the mark of a refusal at a place where the CODE closes a stage with no role - `{site, stage, step, ...}`.
        # A non-empty `close` is the whole mark (no second field that could disagree); `handle_refusal` reads it.
        self.close = dict(close or {})
        # `title`: a NAME the raiser gives a refusal the driver must tell from its neighbours (`second_delivery`), so the
        # driver reads the field and never a regex over its own sentence (the anti-pattern this docstring names above).
        self.title = str(title or "")
        self.text = str(text or "").strip()
        self.retry = retry
        self.files = list(files or [])
        self.dispatch = str(dispatch or "")
        # `findings`: the lines the raiser itself judged (the handoff passes the exit gate's errors WHOLE; its `text`
        # is the head + the list as `Driver.listed` shows it - several lines, cut at the byte ceiling with a pointer
        # to the file, C2-1). `window_findings`: the gap lines `window_record.py` printed for this finish, read by the
        # window-round cap ONLY (t-217 C2) - the one-resume record keys on the refusal's own words, never on them,
        # and they are never part of `text`.
        self.findings = [str(x) for x in (findings or [])]
        self.window_findings = [str(x) for x in (window_findings or [])]
        # `chain` (TR3-17): the ChainRecord of the thread that raised this, None on the main thread and on the serial road. The seam's
        # retry on the main thread adopts it (`Driver.adopt_chain`) so `boundary` and `last_dispatch` read the chain's, not main's.
        self.chain = getattr(_CHAIN, "record", None)


@dataclass(frozen=True)
class OpenWork:
    """Work the driver KNOWS is left in a stage when its closing role finishes (t-721 §4.2; created by C1-5b2, used by S7 first):
    a `complete` callable returns it and `Driver.finish` sends `--not-complete --unresolved <unresolved> --reason <reason>`, so the
    stage stays open on a pair the controller accepts. NOT a `tuple` (a tuple there means "complete, with this pair"); a field that
    is empty after stripping makes the plain `--not-complete`."""
    unresolved: str
    reason: str


def open_work_reason(text: str, mark: str, limit: int = 300) -> str:
    """The reason of an `OpenWork`, at most `limit` characters: a longer text is cut and ends with `mark` (`… [list: <path>]`, the
    path of the whole list). The ONE cut of the two stages that return one (S7 `repairs_pending`, S4 `cases_in_repair`); the reason
    stays on the dispatch record after the close, so it is TIMELESS - what was done, never what 'now' is."""
    return text if len(text) <= limit else text[:limit - len(mark)] + mark


class ReworkRefused(Refusal):
    """The CONTROLLER refused to register a rework (or answered with no dispatch id), before any role ran.
    Raised by `Driver.rework` alone and still a `Refusal` for every other caller; the gate-entry repair
    tells it from the refusals the role's own run raises afterwards (a handoff form, a finish), which must
    keep going to `guarded` and its known table."""


class RepairFailed(Exception):
    """A move of the gate-entry repair failed before it did anything: `what` is the command, `text` the
    refusal's own words. Caught by `gate_repair` and by `take_stand_gap_answers` (a container a person named): the round
    is recorded as failed and the conductor gets the command and the end of its output (never a blind second try)."""

    def __init__(self, what: str, text: str):
        super().__init__(what)
        self.what, self.text = what, str(text or "")


class Priced(str):
    """The text of a closed question built by `Driver.closed_question` (C1-3): the str itself, plus `priced` - the tokens, as the
    site wrote them (not normalized), of those of its options that carry a token and their three price lines. `Person` reads it from the text it is given;
    `judge_own_question` checks `offered` and `priced` together; it is NEVER written into `asked.offered` (only the seam's
    questions carry `offered`, so the position invariant of `take_answer` holds)."""
    priced: tuple = ()
    sources: tuple = ()        # `s1_gap` only (C2-9): the source ids the question names / the causes it offers a kind-token for
    classes: tuple = ()
    details: str = ""          # the factory's own words that did not fit the body (the whole list of the sources named)

    def __new__(cls, text, priced=()):
        made = super().__new__(cls, text)
        made.priced = tuple(priced)
        return made


class Person(Exception):
    """The person is needed: kind, the text they read, and the dispatch it concerns.

    `details` is the factory's own words - a refusal, a detector's output - which the person
    may want and must not be handed instead of a question. `ask()` writes it beside the
    question and names the file in the answer block (references/human-questions.md).

    `answer_note` is a line for the answer block itself (t-335 B-n4): a path the person needs and the body must not
    carry - human-questions.md rule 5 allows a path only there, where it is an instruction."""

    def __init__(self, kind: str, text: str, stage: str = "", dispatch: str = "",
                 code: int = EXIT_PERSON, details: str = "", answer_note: str = ""):
        super().__init__(text)
        self.kind, self.text, self.stage, self.dispatch, self.code = kind, text, stage, dispatch, code
        self.details = str(details or getattr(text, "details", "") or "")
        self.answer_note = str(answer_note or "")
        # `s1_gap` (C2-9): what the question named, written into `asked` by `ask()` for that kind ALONE - its tokens close exactly this.
        self.sources, self.classes = tuple(getattr(text, "sources", ())), tuple(getattr(text, "classes", ()))
        # Set by `Driver.no_move` ALONE, and written into `asked` by `ask()`: the tokens this question offers (normalized),
        # `[{token, move}]`, the original words' file (task-root relative), why it was asked, the waivable block code knows.
        self.offered, self.options, self.words_file, self.why, self.block = (), (), "", "", ""
        # C1-7a (B-1): the ids of the owed rows a seam question is about, written into `asked` by `ask()`: the question's identity for
        # the pairing of the person's `go on` (`Driver.mark_rows_word`), never a clock.
        self.rows = ()
        # B-16: the case keys of the S5 probe gap a seam question named (`window_record.probe_gap_cases`); written into `asked` by
        # `ask()`; its `go on` records one `probe gap: <case key>` word for each (`seam_chosen`).
        self.probe_gap_cases = ()
        # t-1968 N5: the case keys of the S5 tests whose probe the code reviewer could not judge (`window_record.probe_judgment_cases`);
        # written into `asked` by `ask()`; its `go on` records one `probe not proved: <case key>` word for each (`seam_chosen`).
        self.probe_judgment_cases = ()
        # Set by `Driver.held_question` ALONE, and written into `asked` by `ask()`: the lead that helper put above the question's body,
        # so the next `held_question` takes exactly that off (the extent of a lead is kept, never read back by its words).
        self.held_lead = ""
        # RN1-9 (P22, FR-48): the question class (`person_owned.py`) this question answers, what the conductor read, and who
        # raised it (`conductor` / `fallback` / `code` / `delivery`); written into `driver-questions.jsonl` by `judge_own_question`.
        self.why_person, self.checked, self.source = "", "", "code"
        # The tokens of the priced options a `closed_question` text carries: checked by `judge_own_question` beside `offered`.
        self.priced = tuple(getattr(text, "priced", ()))
        # RN1-24 (P22): the case ids whose check waits for THIS question's answer, set by the sites that raise a question about
        # some cases (`stand_login_gate`, `gate_a_dry_person`) and read by `Driver.deferrable`. The field is `holds`, never `blocks`
        # (`asked["blocks"]` is the waiver blocks of a conductor question). Empty = the question holds everything: asked at once.
        self.holds = ()


class Stop(Exception):
    """An exit of the run (a usage error, a missing `claude`, a stop the infrastructure forced): nothing is asked, `run()` prints
    the reason and returns the code. The one exception is the conductor's `stop` of a gate or the S1 review (exit 4, not an
    `InfraStop`), which `run()` turns into the priced question. A Stop that carried a `state` for the seam had no producer after
    C1-3 (P01 became a closed question), so the field is gone (F4): code with no producer is a wish, not a mechanism."""

    def __init__(self, code: int, reason: str):
        super().__init__(reason)
        self.code, self.reason = code, reason


class InfraStop(Stop):
    """`claude -p` failed for a reason outside the story (`kind`: auth, limit, transient) and the
    retries, where there are any, are spent. Raised by `run_claude` only, and never turned into a
    Refusal or a Person: TP1-13877 turned a login error into a conductor question, and the
    person was asked about a call no role had made. `reason` is the whole message: what happened in
    plain words, then the command that goes on."""

    def __init__(self, kind: str, message: str):
        super().__init__(EXIT_INFRA, message)
        self.kind = kind


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _answer_note(prefix: str, words: str) -> str:
    """A journal note that carries a person's words: the prefix, then the words WHOLE (FR-8).
    Every later brief reads `human_answer` notes as the person's standing instructions, so a
    silent cut here loses them for every role after it. Only `brief_pack.PERSON_WORDS_MAX` cuts,
    and that cut says so (the one helper, `brief_pack.person_words_whole`)."""
    import brief_pack
    return prefix + brief_pack.person_words_whole(words)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path, default=None):
    """`hooklib.read_json` (the package's one JSON reader) with this driver's direction: a file that is absent or not
    JSON is `{}`, or the caller's own `default`."""
    return hooklib.read_json(path, {} if default is None else default)


def _write_json(path: Path, data) -> None:
    """The driver's JSON writer. Published by `event_store.atomic_json` (the package's one publisher: a unique temp name, and a replace
    that rides out a reader holding the file on Windows), so a reader across processes (`dispatch_liveness`, `story_step`, ...) never
    sees a torn file and never makes the write fail. A publisher that still fails is said in one note and the old in-place write
    follows - the write that worked before; it is never raised from here for a reader's sake."""
    import event_store
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        event_store.atomic_json(path, data)
    except OSError as exc:
        print(f"note: {path.name} could not be published atomically ({type(exc).__name__}); it is written in place", flush=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, record: dict) -> None:
    """One row appended through the package's ONE appender (AR-15, axis 29): a torn tail gets its `\\n` first, the folder is made, an
    `OSError` reaches the caller. `json.dumps` writes no raw line break, so `append_jsonl_line`'s `ValueError` cannot fire. TR4-11: the
    line ends `\\n` on Windows too (the text-mode write ended `\\r\\n`); every reader splits on `\\n` or takes `\\r` as JSON whitespace."""
    hooklib.append_jsonl_line(path, json.dumps(record, ensure_ascii=False))


def _read_jsonl(path: Path) -> list:
    """Every readable row of a journal. A half-written last line is skipped, never raised: a
    journal is read to decide something, and a crash mid-append must not stop the loop."""
    rows = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except OSError:
        return []
    return rows


def _read_answer(out: str):
    """The ONE reader of a script's answer in `Driver.py` text (t-2020; AR-13, AR-18, AR-28): the LAST line of stdout+stderr that
    parses as a JSON object. A warning a script prints to stderr before or after its answer (a path note, a deprecation) stays in
    the text and does not hide the answer. No such line is `None` - the caller names what came back; it is never an empty answer.
    The reader itself is `hooklib.read_answer`, shared with story_step.py."""
    return hooklib.read_answer(out)


# Refusals one boundary absorbs; the one after them ends in a question. `guarded` and the words of
# `refused_text` both read this, so the text and the cap cannot drift. (The three standing answers every such question
# offers are the `fallback` block of conductor-actions.json, rendered by the seam with their price lines: C1-1.)
REFUSALS_PER_BOUNDARY = 6

# C1-7a (P22, t-1162): a journal row of a person's words (or an FR-4 finding, or a `--warn` line) that its script refused is OWED: it is
# written again before any brief is built (`Driver.owed_rows_step`), and a row refused a second time is the seam's question. The block
# name is the person's `go on` over rows that cannot be written; it is a row of references/block-names.json (reader: `owed_rows_step`).
OWED_ROW_TRIES = 2

JOURNAL_ROWS_BLOCK = "journal rows not written"

# C1-7c (O1, O3; kind T as T1): the invariant of the `halted` stage record written right before `Person("halt")`. ONE text for the two
# sites that run the halt road (`run_role`, `_finish_saved_result`), so the `trace_failed` line and the code say the same thing. The
# question-threshold stop (`question_threshold`, T1) writes the same record with its own `why`: its role IS resumed (F-4 of t-1252).
HALT_RECORD_WHY = ("a halted role's record is a mark the later readers show (the gate brief, the retro); the person is asked about the "
                   "halt either way (the Person is raised next, from the role's own digest) and the role is not run again for it - a "
                   "missed mark is journalled as trace_failed, never silent")


def recorded_earlier(script: str, code: int) -> bool:
    """A row's script exit that means "this finding is already in the journal under that key" (project_decisions.py's own exit code,
    read as a number, never by its words - FR-12). Such a row is WRITTEN: not owed, not run again, no question."""
    return script == "project_decisions.py" and code == project_decisions.RECORDED_EARLIER_EXIT


# A stage the CODE closes with no role (conductor/2 C2-8, t-745; class K3): site id -> (stage, what the code does, in words for a person).
# The closed variety of the factory (FR-13). A refusal raised at one of these sites carries `close` (see `Refusal`), and the driver puts
# it to the person through `Driver.code_close` instead of calling the conductor. The S0 closes are not in the table (the record is made
# before the refusal; B1 of the review).
CODE_CLOSE_SITES = {
    "s6.nothing": ("S6", "there was nothing to run"),
    "s6.results_stand": ("S6", "every automated result still stands, so nothing was run again"),
    "s6.reprobed": ("S6", "the tests ran on their current code, and the live checks of the tests that changed were proved again or left as they were"),
    "s6.manual_close": ("S6", "the checks done by hand are counted"),
    "s6.accepted": ("S6", "the failure analyst accepted the runner's handoff"),
    "s7.accepted": ("S7", "the doc scribe accepted the failure analyst's triage"),
    "s7.no_failures": ("S7", "no test failed, so there is nothing to sort"),
    "s7.pretriaged": ("S7", "every failure already has a state the run recorded"),
    "s7.after_repairs": ("S7", "the repairs of the failed tests ended"),
    "s7.repair_verdicts": ("S7", "the failed tests to repair are named by a description of the factory's own"),
    "s9.skip": ("S9", "the retro is skipped, as you asked"),
    "s9.numbers": ("S9", "the retro is the numbers only, as you asked"),
}

STUCK_REPEATS = 4        # the same `where` answer this many times in a row: the stuck seam (B-20 N5); the lead text names the number

# The deferred record of a stage the code closed (`code_close_step`): at most this many idle turns before the person is asked.
CODE_CLOSE_IDLE_CAP = 2

BY_PERSON = "by: person"     # the quote prefix of a driver accept that a person's word made (`person_pass` writes it, `consumer_close_words` reads it)


def mr_record(value) -> str:
    """The delivery verdict's `mr` kept only when it has the SHAPE of a record of an opened MR, else `""` (a shape check, not a
    phrase list: FR-12/13). A record is a link (`scheme://...`), an id token (no spaces, a digit, at most 40 characters: `!42`,
    `#7`, `42`, `MR-42`), or a whole number. `none`, `N/A`, `not opened`, an empty or blank text, a bool or a float is no record:
    the order is then called off `delivered_without_mr`, never closed as done with a word that names no MR."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    text = value.strip() if isinstance(value, str) else ""
    if re.match(r"[A-Za-z][A-Za-z0-9+.-]*://\S", text) or (
            len(text) <= 40 and not re.search(r"\s", text) and re.search(r"\d", text)):
        return text
    return ""


def seam_rank(exc) -> int:
    """The rank of a failed chain's exception at the seam (t-2147 A; was the closure of `s5_seam`): an `InfraStop` first, then a `Stop`,
    then a `Refusal`, then a `Person`. F3: an exception that is none of the domain's (a TypeError, an OSError) is a crash, not a state
    that re-arises from a saved result: it is ranked with `Stop`, ahead of a question."""
    return 0 if isinstance(exc, InfraStop) else 1 if isinstance(exc, Stop) or not isinstance(exc, (Refusal, Person)) \
        else 2 if isinstance(exc, Refusal) else 3


class DriverCore:
    # TR3-17 (B4 parts 1-2): `boundary` and `last_dispatch` were single slots; they are now per thread AND per driver, under the same
    # names, so the 26 + 57 sites read and write them unchanged. The main thread's value is the one `__init__` and the serial road set.
    # A thread that never set one: `boundary` raises AttributeError (a bug to show, no default); `last_dispatch` reads "" (its only
    # silent default - and `getattr(self, "last_dispatch", "")` keeps answering "").
    boundary = ThreadSlot("boundary", hint="boundary was read on a thread that never set it (a chain starts with `as_chain`)")

    def __init__(self, ns):
        self.task = ns.task
        self.dry = bool(ns.dry_run)
        self.until = ns.until if ns.until in UNTIL_PAST else None
        self.plugin = Path(ns.plugin_dir).resolve() if ns.plugin_dir else HERE.parent
        self.scripts = self.plugin / "scripts"
        self.flags = ns
        self.max_boundaries = int(ns.max_boundaries)
        if ns.project:
            os.environ["CLAUDE_PROJECT_DIR"] = str(Path(ns.project).resolve())
            os.chdir(ns.project)
        import hooklib
        hooklib._PROJECT_ROOT_CACHE = None
        hooklib.require_project("story_run")
        self.project = Path(hooklib.project_root()).resolve()
        os.chdir(self.project)
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.project)
        self.task_root = Path(hooklib.artifacts_dir(self.task))
        self.state_dir = self.task_root / "state"
        self.config = hooklib.load_config() or {}
        if not AF.is_key(self.task, self.config):   # B-405 R14: a warning only (P1) - the run goes on
            print(f"WARN: --task {self.task!r} is not a ticket key of this project: "
                  f"{AF.describe_key_form(self.config)}; going on", flush=True)
        # The host: `--host` first, then `driver.host` of config.json (None/absent is no word; any other value is
        # compared after strip, with its case - an unknown one is refused at the end of this method, by `host_refusal`,
        # naming the hosts there are), else `claude`. `self.claude` is the executable of whichever host runs the roles
        # (the name is kept: every call site reads it). STORY_RUN_CODEX / STORY_RUN_CLAUDE replace it (a `.py` path runs
        # under this interpreter: the tests' stubs).
        driver_cfg = self.config.get("driver")
        driver_notes = []
        if driver_cfg is not None and not isinstance(driver_cfg, dict):
            driver_notes.append("`driver` in config.json is not an object: it is not read")
            driver_cfg = {}
        driver_cfg = driver_cfg or {}
        named_host = getattr(ns, "host", None)
        if named_host:
            self.host = str(named_host).strip()
        elif driver_cfg.get("host") is not None:
            self.host = str(driver_cfg["host"]).strip()
        else:
            self.host = "claude"
        if self.host == "codex":
            raw = os.environ.get("STORY_RUN_CODEX") or shutil.which("codex") or ""
        else:
            raw = os.environ.get("STORY_RUN_CLAUDE") or shutil.which("claude") or ""
        self.claude = [sys.executable, raw] if raw.endswith(".py") else ([raw] if raw else [])
        # The project's say on the Codex call (`driver.codex.sandbox`, `driver.codex.config`), normalised once: a key of
        # the wrong type is ignored with one note (FR-4), the others are passed as given. Read for Codex only.
        self.codex_cfg = {}
        if self.host == "codex":
            codex = driver_cfg.get("codex")
            if codex is not None and not isinstance(codex, dict):
                driver_notes.append("`driver.codex` in config.json is not an object: it is not read")
                codex = {}
            codex = codex or {}
            sandbox = codex.get("sandbox")
            self.codex_cfg["sandbox"] = "" if sandbox is None else str(sandbox).strip()
            overrides = codex.get("config")
            if overrides is not None and not isinstance(overrides, dict):
                driver_notes.append("`driver.codex.config` in config.json is not an object: it is not read")
                overrides = {}
            # `-c key=value` takes a TOML value. A string goes as given, a number / boolean / list as JSON (the same text in
            # TOML); an object has no one-line TOML form and `null` has none at all, so passing them would change the
            # project's word silently (E-17): such a key is left out, and the line says which and why (FR-4).
            kept = {}
            for key, value in (overrides or {}).items():
                if value is None or isinstance(value, dict):
                    driver_notes.append(f"`driver.codex.config.{key}` in config.json is "
                                        f"{'null' if value is None else 'an object'}, which `codex -c` cannot take as one value: "
                                        "it is not passed")
                else:
                    kept[key] = value
            self.codex_cfg["config"] = kept
            if not self.codex_cfg["sandbox"]:
                driver_notes.append("`driver.codex.sandbox` is not set: no `-s` is passed, the project's own "
                                    ".codex/config.toml decides the sandbox")
        # Every child speaks UTF-8: a script that prints a dash or a person's words under the machine's
        # code page (cp1252 on Windows) hands the driver bytes it then decodes as UTF-8 with
        # errors="replace" - the text arrives as replacement characters (B-012, K13). In code, not in
        # a data file: it is not variety, it is how this driver reads every pipe.
        # B-014: `CLAUDE_PLUGIN_ROOT` is this driver's own copy for every child. Hooks get their root
        # from the host, but the Bash tool of a role INHERITS this variable (step 0, R6b: a parent's
        # `C:\fake` reached the role's Bash), so a command in an agent body that says
        # `${CLAUDE_PLUGIN_ROOT}/scripts/...` resolves to the copy the driver runs, never to the
        # copy some other session or the host left in the environment. `QA_FACTORY_RUN_MODE` is the
        # mode `story_step start` stamps into the story (one story, one mode).
        self.env = dict(os.environ, CLAUDE_PROJECT_DIR=str(self.project),
                        CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS="0", PYTHONDONTWRITEBYTECODE="1",
                        PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
                        CLAUDE_PLUGIN_ROOT=str(self.plugin), QA_FACTORY_RUN_MODE="driver")
        # Factory scripts (`py`) get that environment as it is: one may use a gateway on purpose. Only
        # a `claude -p` child loses what a desktop-app host put in the driver's environment - its
        # proxy address without the per-process token, which made every role answer "Not logged in"
        # on TP1-13877 while a valid login sat in the credentials file. What goes is a data file's
        # list (references/driver-infra.json); `driver.child_env.keep` in config.json is the door back.
        import infra_failure
        self.infra_rules, infra_notes = infra_failure.rules()
        self.claude_env, self.env_removed, env_notes = infra_failure.child_env(
            self.env, self.infra_rules, driver_cfg)
        # The model: Claude - `--model` or `sonnet`; Codex - `--model`, else `default_model.codex` of the data file
        # (the owner's word 20.10.2026: the latest Terra, in data, not in code). The journal rows and the dry run name
        # THIS model, the one the child is given.
        named_model = getattr(ns, "model", None)
        self.model_explicit = named_model not in (None, "")
        default_models = self.infra_rules.get("default_model")
        data_model = default_models.get(self.host) if isinstance(default_models, dict) else None
        data_model = data_model.strip() if isinstance(data_model, str) else ""
        self.model = str(named_model) if self.model_explicit else (data_model if self.host == "codex" else "sonnet")
        for note in infra_notes + env_notes + driver_notes:
            print(f"note: {note}", flush=True)
        self.sleep = time.sleep          # tests replace it: a retry's wait is a decision, not a duration to sit through
        self.boundary = "start"
        self.conductor_calls: dict = {}
        self._in_no_move = False         # the re-entry guard of `no_move`: the seam never recurses
        self.gate_b_ran = set()          # the gate B executors this process started (GB-1b): none is started twice by one process
        self.gate_b_idle = 0             # the passes of `_act_execute_gate_b` in a row that moved no order (the seam is the second)
        self._price_notes = None         # a list while the seam renders a site's own question: price reasons join ONE defect (G8)
        self._answer = None              # the --answer being taken: {"text": raw, "rel": <words file, once written>}
        self.state = _read_json(self.state_dir / "driver-state.json")
        self.state.setdefault("sessions", {})
        self.state.setdefault("pending_words", {})
        self.state.setdefault("asked", {})
        self.state.setdefault("interrupted", {})   # key (a dispatch, or `S8:delivery`) -> the call an infrastructure failure cut off
        self.answer_kind = ""
        self.question_lines_shown = ""   # GW1-34 F4: the lines of that note, as the person reads them
        self.question_lines_note = ""    # GW1-34: the conductor's note on gate A lines about register questions no reader understood
        self.gate_refusal = ""           # the controller's own words when a gate decision did not record (t-214 C3)
        self.package_verdict = False     # B-014: this process has seen one session's hooks match its own root
        self.doors_tried: set = set()    # C2-4: the (dispatch, finding key) pairs the code doors already ran for in this process
        self.in_code_step = False        # C2-4 (t-909 F-2): True while a code step's own retry / nested refusal runs - it is not entered again
        refusal = self.host_refusal()
        if refusal:
            raise Stop(refusal[0], refusal[1])

    def host_refusal(self):
        """`(exit code, text)` when the host of this run cannot start, else None. ONE place decides every start refusal
        of the host (CX1-15), and `__init__` raises the one `Stop` for it. Each text says what is wrong, what was
        expected and the door (FR-1, FR-2); none of them names a path the person cannot use.

        1. `--host` / `driver.host` is not one of `HOSTS` (exit 1; the value as given, the hosts there are).
        2. The Codex host with no `--model` and no `default_model.codex` in `references/driver-infra.json` (an older data
           file): exit 2, never a silent host default - the model of a run is always one the factory can name.
        3. F-5: the story's state holds a session of ANOTHER host (exit 1): an id of one host is never offered to
           `resume` of the other. The door: the host the story started on, or a new story. A state with sessions and
           no `host` key is a Claude story (the key is written for Codex only)."""
        if self.host not in HOSTS:
            return EXIT_ERROR, (f"--host / driver.host {self.host!r} is not one of {', '.join(HOSTS)}. Name one of them "
                                "(`--host claude` or `--host codex`), or remove `driver.host` from qa-factory/config.json.")
        if self.host == "codex" and not self.model:
            models = self.infra_rules.get("default_model")
            named = models.get("codex") if isinstance(models, dict) else None
            problem = "is missing from" if named is None else "is not a model name in"
            return 2, ("The Codex host has no model: `--model` was not given and `default_model.codex` " + problem +
                       " references/driver-infra.json of the package this driver runs, so it would run a model the factory "
                       "cannot name. Pass `--model <name>`, or restore `default_model.codex` in that file.")
        held = bool(self.state.get("sessions")) or any(
            isinstance(r, dict) and r.get("session_id") for r in (self.state.get("interrupted") or {}).values())
        previous = str(self.state.get("host") or "") or ("claude" if held else "")
        if held and previous != self.host:
            # Both hosts are named: the one of the stored sessions (the story's own `host` key, kept by `mark_host` as the
            # sessions change) and the one this run is, from the flag / config - never a word taken from the other.
            return EXIT_ERROR, (f"This story already holds sessions of the {previous} host, and this run is {self.host}: a "
                                f"session id of one host cannot be resumed on the other. Run the story with `--host {previous}` "
                                "to go on, or start a new story for the other host.")
        return None

    # --- plumbing --------------------------------------------------------------------------

    def save_state(self) -> None:
        if not self.dry:
            # TR3-6: published through `_write_json` (`event_store.atomic_json`), so a reader (`story_step`, the dashboard, the watchdog's
            # `dispatch_liveness`) during a released `start` never sees a torn file and never makes the write fail; the caller holds
            # `_book` on the parallel road (one writer at a time)
            _write_json(self.state_dir / "driver-state.json", self.state)

    def pipeline(self) -> dict:
        return _read_json(self.task_root / "pipeline.json")

    def controller_state(self) -> dict:
        return _read_json(self.state_dir / "controller.json")

    def stages(self) -> dict:
        import hooklib
        return {s["id"]: s for s in hooklib.load_ref_json("stages.json")["stages"]}

    def mark_host(self) -> None:
        """F-5: the story's state names the host its stored sessions belong to - written whenever a session is stored (or
        a cut-off call's session is kept) off Claude, and rewritten whenever the key is already there, so it follows the
        sessions and never outlives them as a stale word (m-1: a Codex thread that was dropped must not leave `codex`
        behind a Claude story). A Claude story with no key keeps its bytes as they were."""
        if self.host != "claude" or "host" in self.state:
            self.state["host"] = self.host

    def drop_standing(self) -> None:
        """The way out of the record (FR-40), the ONE eraser: E1 `no_move` returned `continue` / `retry`, E2 `guarded` moved on
        (the stage moved, or the refused step went through), E3 `take_answer` closed the question, E4 `reconcile_question` found
        none open. While a `Person` stands the record lives with the question, between processes too. A dry run erases nothing."""
        if self.dry:
            return
        try:
            waiver.drop_standing(self.task)
        except OSError as exc:
            print(f"note: the record of the standing refusal could not be erased ({exc})", file=sys.stderr)

    @staticmethod
    def refusal_lines(refusal, items=None) -> list:
        """THE builder of "the lines of the refusal that reached the seam" (t-722 §3.1, N6): the driver's record of the standing
        refusal (`standing_refusal`) and `exit_limit`'s `lines` are this one result. The source: `items` when given (the S5
        window's own set); else the raiser's `findings`; else the items of the controller's combined refusal (`DV.split_items`
        over `DV.refusal_text`, the transport off - the C2-1 reader, no second stripper); else the text below its first line
        (the driver's header `story_step finish <id> (exit N):`); else the text whole. Then `waiver.refusal_parts`, the ONE
        normalisation the writer applies to a block too (the hint and the door cut, the number, the split at `"; "`).
        Never empty for a refusal: a source that normalises to nothing (all code in backticks) is returned as it is. `items` GIVEN
        is the whole source, `refusal` is then not read and may be `None` (`items=[]` is no lines - the caller's lines are
        the caller's, t-842 F3): only `items=None` reads the refusal."""
        if items is None:
            items = list(refusal.findings or [])
            if not items:
                text = DV.refusal_text(refusal.text)
                items = DV.split_items(text) or [line for line in text.splitlines()[1:] if line.strip()] or [text]
        raw = [str(item) for item in items if str(item).strip()]
        return waiver.refusal_parts(raw) or raw

    CUT = chr(0x2026)                       # the ellipsis that marks a quote cut at the limit

    # The `stop` option of every priced closed question (S0, the halt, the threshold, the package questions): ONE definition.
    STOP_OPTION = {"answer": "stop", "token": "stop", "says": "stop the story here; nothing runs"}

    @staticmethod
    def rework_dispatches(dispatches: dict, cause: str, *, by_person: bool, stage: str = "") -> dict:
        """`{id: dispatch}` of the reworks of `cause` (on `stage`, when given) of ONE ORIGIN: `by_person` - the person's words reached the
        controller by file (the record's `person_words`, `build_rework_request`), else the driver's own reason (`ticket_rework_step`).
        A rework of the other origin is never counted, so a `ticket_changed` rework is never taken for the person's and the other way."""
        return {did: d for did, d in dispatches.items()
                if isinstance(d, dict) and d.get("repair_cause") == cause and (not stage or d.get("stage") == stage)
                and (d.get("person_words") is True) == by_person}

    def newest(self, pattern: str) -> Path | None:
        files = [p for p in self.task_root.glob(pattern) if p.is_file()]
        return max(files, key=lambda p: p.stat().st_mtime) if files else None

    def no_trace(self) -> bool:
        """Is this run an experiment that leaves no trace? The record is `pipeline.no_trace`
        (read through `external_writes.closed_by_run`, the reader every other consumer shares);
        before pipeline.json exists, S0 has only the command line to go by. A flag absent from a
        later command line never reopens what pipeline.json closed.

        The launch record (`state["launch"]["no_trace"]`, kept by S0) closes too when pipeline.json
        cannot say: unreadable, or with no `no_trace` key at all - a damaged file must not reopen
        writes (Lead's decision Q6). A key that IS there and says false is the person's way out
        (`stage_done --set no_trace=false`, FR-40) and wins over the launch."""
        if (self.state.get("launch") or {}).get("no_trace") and "no_trace" not in self.pipeline():
            return True
        if (self.task_root / "pipeline.json").is_file():
            import external_writes
            return bool(external_writes.closed_by_run(self.task_root))
        return bool(getattr(self.flags, "no_trace", False))

    def delivery_word(self) -> str:
        """The ledger's verdict word as the gates read it (`yes`, `after_checks`, else `no`: an absent, unreadable or
        inconsistent ledger offers nothing)."""
        import gate_brief
        return gate_brief.delivery_word(self.task_root)
