"""The deterministic check S5 passes before the code critic is dispatched.

TP1-15045 went to the critic with a manifest that said TC-013 was green while a run block
said "not run"; with TC-012 `green` at four of its eight partitions; with three Then clauses
that no assertion touched and one the test contradicted; with an expected status changed from
401 to 403 after a red run; and with a credential assert that fails on any other machine. A
critic reading prose cannot count those — code can, and it costs nothing. Everything here is
mechanical: the AUTHOR gets a list of repairs, the critic gets a clean input and spends its
round on meaning. No finding here is ever a question for the person.

Seven families:

  manifest      the invariants `manifest_put.py` owns (a hand edit shows up here)
  bindings      every Then clause of every case in scope maps to a test and an assertion, or is a
                remainder the person took (`then handed:` word, GW1-14), named and never silent
  oracle        an expected value the case left open (its `then_oracles` entry reads `open` or `invalid` through
                the one resolver) that a test nevertheless asserts, or changed after a red run (a test that
                went red and later passed on changed code needs an `expectation_changes[]`
                record — `expectation_changes()` below finds the pairs), or an unresolved row
                that disputes the approved case instead of asserting it
  run_mapping   every test of the scope has a reporter row (--reparse-block, not a rerun)
  smell         ADVICE for the code critic, never a refusal (X7-2): test-code smells by AST (env credentials,
                None==None, unnormalised bodies, a count of what a text substring matched, sleep), a relative
                oracle on a base nobody asserts, parametrisation candidates, copies of existing code. Printed
                in an `ADVICE — n` block and filed in `work/advice-S5.json`; the critic judges them
  environment   a `blocked_by_env` row of THIS dispatch carries the fix it found (`remedy`),
                names no credential value, and does not blame the stand for a fixture the
                approved case never asked for
  obligations   every coverage obligation of the plan row a scoped case belongs to has an
                `obligation_bindings[]` row, under the plan's own id, reaching that case

An eighth family, `plan`, exists only for a story whose S5 began with a plan (`s5_plan.mode`): the window is checked against its
slice of the plan (`check_plan_conformance`), a difference is a finding unless a `deviations[]` row of the window's form declares it,
and the PLAN dispatch itself (no manifest) is answered by `s5_plan.check` (`plan_result`).

Nothing here counts test methods per case. A case is a coverage specification and the
automator chooses the executable shape: one parametrized test proving three cases
passes, as long as every Then clause and partition is bound to an instance whose `covers`
names that case. What the shape check does produce is ADVICE — `advice[]`, never `ok: false`
— when two or more instances differ only in their data.

    s5_precheck.py                          # detector: the running story
    s5_precheck.py --task-root TASK_ROOT [--dispatch D] [--json]

Language-specific checks run on Python test files; any other language is noted, listed in the
result's `unchecked[]` ({case, file, checks}) and left to the code critic, never crashed on. A manifest without `then_bindings` is a 0.7.x manifest: that is a finding
for the author ("bindings missing"), not a refusal.
"""
import argparse
import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract as C  # noqa: E402
import detector_verdict as DV  # noqa: E402  (the contract of this output, its label and its refusal line)
import hooklib  # noqa: E402  (`read_json`, the one JSON reader)
from person_words import WHOLE_PART, door  # noqa: E402
from role_cli import REPAIR_MARKER  # noqa: E402
# The block reader and the "a test changed after its red run" detector live in `run_history.py`;
# these names stay importable from here (same objects), because readers import them from this module.
from run_history import (expectation_changes, expectation_records, function_key,  # noqa: E402,F401
                         read_run_blocks, record_for, record_functions)
from hooklib import sorted_paths

CHECKS = ("manifest", "bindings", "oracle", "run_mapping", "smell", "environment", "obligations", "plan", "sides")
# What the code does NOT check for a test file it cannot read by AST (any language but Python): the result's
# `unchecked[]` rows name them, so the OK line and the code critic never take silence for a pass (B-407 C, FR-41).
UNCHECKED_CHECKS = ("Then assertions", "contradictions", "smells")
# `Plan row: TS-n` in the case body, `plan_row: TS-n` in its frontmatter — both spellings are
# in the wild (`contract.case_levels` reads both), and either one is the join to the plan row
# whose coverage obligations this case is supposed to discharge.
PLAN_ROW_RE = re.compile(r"^\s*(?:Plan row|plan_row):\s*(TS-\d+)", re.MULTILINE)
# The families a recorded word can pass here. Everything else is a repair the author can make
# without asking anybody, and a waiver of one would only hide work that is still owed.
PASSABLE = {"environment", "obligations"}
# `changed-after-red`: a test that went red and later passed on different code. It is one finding
# of the `oracle` family, not the family: `oracle` is not in PASSABLE because the other oracle
# findings are repairs the author can always make, while this one can be a decision only a person
# can take (the author restored nothing and the reason is not in the artifacts). So a recorded
# word passes it BY TAG (`waiver.py --stage S5 --block "changed-after-red"`), the way
# `obligation-id-` is passed, and nothing else of the family.
CHANGED_AFTER_RED = "changed-after-red"
# `open-oracle-asserted-<n>`: Then n of a case reads `open` or `invalid` through the one resolver
# (`traceability.then_oracle_states`) and the manifest binds it to an asserting instance. Also one finding of the
# `oracle` family, outside WORD_PASSABLE_TAGS: a person settles it only by answering the question (the gate's
# INPUT changes), never by a waiver (FR-4, FR-58, FR-59).
OPEN_ORACLE_ASSERTED = "open-oracle-asserted"
# The family `sides` (t-2181 PC-4, C1-C6) is NOT in PASSABLE (S10): two tags of it are passable BY TAG, nothing else of it.
# `sides-undeclared` (C1): a test of a story with a non-real side that declares no `sides` - the person may say the
# declaration is not needed; `provisional-open-on-real` (C6 a): an open provisional row whose side is now real - the person's
# word `substitute kept: <side>` keeps it. A C2-C5 finding and the other C6 ones are repairs no word passes.
SIDES_UNDECLARED = "sides-undeclared"
PROVISIONAL_OPEN_ON_REAL = "provisional-open-on-real"
WORD_PASSABLE_TAGS = (CHANGED_AFTER_RED, SIDES_UNDECLARED, PROVISIONAL_OPEN_ON_REAL)
# Tags no judge may downgrade to a hint. A judge answers whether the code still demands the
# Then's value; the change a red run forced is a fact about two runs, which only the record and
# the critic's verdict speak to.
NEVER_JUDGED_TAGS = (CHANGED_AFTER_RED, OPEN_ORACLE_ASSERTED)
# The `unresolved[]` reason for "the code does not do what the requirement says". The
# automator may not change an expected value to match the code and `impossible` means the
# product offers no way to perform the step, which this is not — so until 0.7.7 the one
# outcome a contradiction found at S5 had was to be filed as something it is not.
CONTRADICTS = "contradicts_requirement"
# The `unresolved[]` reason for "I cannot execute this profile in this session at all, and the
# person said they will run these themselves" (TP2-2536: Maestro/iOS, no Xcode for the
# agent). The code is written and reviewed; there is no run, so no reporter row is owed and a
# case in tests[] AND unresolved[] is the sanctioned shape, not a contradiction.
HANDED = "handed_to_person"
# The `then_bindings` reason of a Then that sits behind a red assert of its own test (HF2-3): a fact read off a red,
# so no person's word is asked for it (`check_then_remainders`). One spelling, the contract's.
BLOCKED_BY_CHECK = C.BLOCKED_BY_CHECK
# The one road the findings of the red-row family (`red-two-cases-`, `red-links-unbound`, `contradicts-no-instance`,
# `blocked-check-*`) name for a repair: a fragment through `manifest_put.py` (FR-2: the one road a row written by hand
# has; a later `manifest_from_tests.py` run keeps such a row unless it writes the same Then of the same test itself).
# A door names that road, not the marker that writes the same rows from the test file. `<T>` is the
# task root's name where the caller has the root (`check_then_remainders`); `check_manifest` is not given one and
# prints `<TICKET>`, as the other doors of this file that carry no task do.
FRAGMENT_ROAD = "manifest_put.py --task <T> --fragment <file>"
# S5 runs only after gate A, so every case in its scope is an APPROVED case — and an approved
# case is the oracle. A test written to it that fails against the implementation is this
# factory's product, not a blocker: the assertion stays as the case wrote it, the test is
# handed over red, and `contradicts_requirement` carries the expected and observed value.
# TP1-15045 parked TC-009 and TC-014 on the designer instead, with the tests asserting the
# CODE's behaviour (non-null against a Then that says null) and an existing test written to
# the code as the arbiter; the story then stood on two "designer conflicts" that were findings.
ORACLE_FIX = (
    "assert the Then exactly as the approved case wrote it, hand the test over RED, and record "
    "`" + CONTRADICTS + "` with the requirement id and the expected and observed value. The "
    "doubt about the case travels WITH the red test to S7, where the failure analyst puts the red "
    "to its control experiment and decides what it is against the requirement register (a bug "
    "of the product is one outcome, a wrong case or a wrong test are others); an existing test "
    "written to the code is never the oracle.")

THEN_HEADING_RE = re.compile(r"(?im)^##+\s*Then\b.*$")
NEXT_HEADING_RE = re.compile(r"(?m)^##+\s")
THEN_ITEM_RE = re.compile(r"(?m)^\s*(\d+)[.)]\s+(.*)$")
PARTITION_RE = re.compile(r"\bP-[a-z][A-Za-z0-9-]*\b")
# What makes a Then clause checkable: the names it demands. Backticks, quotes, partition ids
# and snake_case are the case author naming something exactly; plain words are only read when
# a clause has none of those, because a clause is judged ONLY when nothing it names is in the
# code — one accidental common word ("validate") would otherwise hide a whole missing Then.
SPECIFIC_TOKEN_RES = (re.compile(r"`([^`\n]{2,60})`"), re.compile(r"\"([^\"\n]{2,60})\""),
                      PARTITION_RE, re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b"))
PLAIN_TOKEN_RE = re.compile(r"\b[a-z]{7,}\b")
# "details null", "`help` is null", "the body's `x` must be empty" — the field may be quoted
# or backticked, which is how a case author usually writes it.
NULL_DEMAND_RE = re.compile(r"[`'\"]?\b([A-Za-z_][A-Za-z0-9_]*)(?:\.[A-Za-z_][A-Za-z0-9_]*)?"
                            r"[`'\"]?\s+(?:is\s+|are\s+|must\s+be\s+|should\s+be\s+)?"
                            r"(?:null|none|empty)\b", re.IGNORECASE)
NOT_NONE_RE = re.compile(r"not_none|is\s+not\s+None|!=\s*None|assertIsNotNone|is_not\(\s*none")
STATUS_ASSERT_RE = re.compile(r"equal_to\(\s*([1-5]\d\d)\s*\)|==\s*([1-5]\d\d)\b")
# A Then that fixes a status code. The number alone is not enough — a case says "3 retries"
# and "404" in the same voice — so a word that makes it a response, or backticks, is required.
STATUS_DEMAND_RE = re.compile(
    r"(?i)(?:status|code|returns?|respond(?:s|ed)?|answers?|http)\D{0,24}\b([1-5]\d\d)\b"
    r"|`([1-5]\d\d)`")
# A Then that fixes a named field to a literal: "`kind` is `workflow`", 'error.message must
# be "Not found"'. The literal is quoted or backticked, which is how a case author writes an
# exact value; an unquoted word is prose and is judged by `clause_tokens` instead.
LITERAL_DEMAND_RE = re.compile(
    r"[`\"']?\b([A-Za-z_][A-Za-z0-9_.]*)[`\"']?\s+(?:is|are|must\s+be|should\s+be|equals?|reads)"
    r"\s+[`\"]([^`\"\n]{1,60})[`\"]")
# What a decided deferral says it disputes, in the row's own `disputes` field —
# `contract.UNRESOLVED_DISPUTES`. Until 0.7.19 this was two phrase lists over the row's prose
# (`case text|case Then|expected value|…` AND `code|live|returns|actual|…`), so a row phrased
# otherwise escaped the check that refuses a dispute with an approved case, and a row phrased
# like one was accused of a dispute it was not making. Twelve lines below, this same file
# already states the lesson for its neighbour: "So the trace is to a source, not to a
# vocabulary." (factory rule FR-12).
# Only a value that came FROM the environment is the smell this check is about: on a machine
# without those variables the test errors instead of skipping. Matching the WORD anywhere in an
# assert refused the opposite thing - `access_token` in the product's own response is exactly
# what the test must assert on, and TP1-13797 spent a review circle on that false positive.
# So the trace is to a source, not to a vocabulary: a read of the process environment or of a
# secret manager. `password` alone proves nothing about where the value came from.
ENV_SOURCE_RE = re.compile(r"(?i)\bgetenv\b|\benviron\b|\bget_parameter\b|\bget_secret_value\b"
                           r"|\bsecretsmanager\b|\bkeyring\b|\bdotenv_values\b")
NORMALISE_RE = re.compile(r"(?i)normali[sz]ed|normali[sz]ation")
BODY_RE = re.compile(r"(?i)\berror\b|\bbody\b|\.json\(\)|response")
# A matcher that selects by TEXT, case-insensitively and by substring. TP1-15045 filed
# BUG-1 ("two ADDED badges") out of
# `popup.popup_container.locator("span", has_text=DIFF_BADGE_ADDED).count() == 1`: the popup's
# legend chip says "Added" and sits in the same container, so the count was 1 badge + 1 chip
# on every run, deterministically, and the product was never at fault. Counting what a
# substring matched is not an observation of the node the Then is about.
SUBSTRING_MATCH_RE = re.compile(r"has_text\s*=|get_by_text\s*\(|getByText\s*\(|:has-text\(")
# The same assertion scoped to an element the page names is exactly the repair, never a
# finding: a test id (or the node's own chrome built on one) matches one element by identity.
SCOPED_SELECTOR_RE = re.compile(r"(?i)data-test-?id|get_by_test_id|getByTestId")

# --- a stand gap carries its own fix, and a fixture is not a stand ----------------------------
BLOCKED_BY_ENV = "blocked_by_env"
# The story version from which a `blocked_by_env` row with NO recorded run is refused (RH2-9, B-2); a story started earlier gets a
# note. The row carries no version of its own, so the story's start version (`pipeline.json`) stands for it.
ENV_EVIDENCE_SINCE = "0.10.9"
# `KEY=value` / `KEY: value` in prose. TP1-15045 wrote the cause of a blocked partition as
# a sentence; the next step after a sentence is a sentence with the password in it, and an
# artifact is read by everyone the story is shown to. The NAME is the fact; the value never is.
SECRET_ASSIGN_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\s*[=:]\s*([^\s,;]{4,})")
# What is not a value: a placeholder, a variable reference, ANOTHER variable name (a remedy
# often says `AUTH_TOKEN: NON_OWNER_TOKEN`, which is two names and the point of the rule), a
# path, a mask.
SECRET_PLACEHOLDER_RE = re.compile(r"^[<$({\[*\.\-'\"]|^(?:\.\.\.|xxx+|redacted|missing|unset|"
                                   r"present|absent|empty|null|none|true|false|yes|no|set)$"
                                   r"|^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$|[\\/]", re.IGNORECASE)
# And what reads as one: a digit or base64 punctuation in it. A secret that is pure prose
# ("correcthorse") is not caught here, and the `change` of a `credential` remedy is checked
# for the token shape by `contract.remedy_errors` besides — this rule's job is to be silent
# on the sentences a role really writes ("AUTH_TOKEN: unavailable on this stand").
SECRET_VALUE_SHAPE_RE = re.compile(r"[0-9+/=]")
# The names a `detail` / `remedy` mentions. Three characters is the shortest fixture name worth
# matching; anything shorter matches half the English language.
DETAIL_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
# pytest's own fixtures are never the test's choice of test data, so they are never the
# "fixture the case did not ask for".
BUILTIN_FIXTURES = {"request", "tmp_path", "tmp_path_factory", "tmpdir", "monkeypatch",
                    "capsys", "capfd", "caplog", "recwarn", "pytestconfig", "cache",
                    "doctest_namespace", "record_property", "event_loop"}
FIXTURE_FIX = (
    "return it as `test_defect`: build the minimum the Then requires, through the API, and "
    "drop the fixture the case never asked for. If the Then really does need that dependency, "
    "the CASE has to say so — a case change approved at gate A, not a stand gap.")


def _soft(value: str) -> str:
    """A name as the case might have spelled it: `sub_workflow`, `sub-workflow`, `SubWorkflow`
    are one name, and a case author writes whichever reads best in a sentence."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def secret_value_leaks(text: str) -> list:
    """The `KEY=value` shapes in prose whose KEY names a credential. Names only."""
    out = []
    for key, value in SECRET_ASSIGN_RE.findall(text or ""):
        if not _secret_name().search(key) or SECRET_PLACEHOLDER_RE.search(value):
            continue
        if not SECRET_VALUE_SHAPE_RE.search(value):
            continue
        if key not in out:
            out.append(key)
    return out


def _secret_name():
    """`env_probe.SECRET_NAME` — the one spelling of "this name holds a credential" in the
    factory. Imported lazily and copied only if that module cannot be read, so a check never
    fails on an import."""
    try:
        import env_probe
        return env_probe.SECRET_NAME
    except Exception:
        return re.compile(r"(pass|secret|token|key|credential|auth)", re.IGNORECASE)


def _load(path: Path) -> dict:
    return hooklib.read_json(path, {}, kind=dict, errors=Exception)


def _finding(check: str, case: str, message: str, fix: str, tag: str, level: str = "repair") -> dict:
    return {"id": f"{check}:{case or '-'}:{tag}", "check": check, "case": case,
            "message": message, "fix": fix, "level": level}


def _hint(check: str, case: str, message: str, fix: str, tag: str) -> dict:
    """A shape worth a second look that is NOT a defect. A hint never fails the gate.

    0.7.7: the automator picks the executable shape, and "these three new tests differ only in
    their data" is advice about that choice, not a rule it broke. Presented as a refusal it
    would do exactly what the removed "functions per case" finding did — push the author back
    to one test per case to keep the check quiet."""
    return _finding(check, case, message, fix, tag, level="hint")


def _advice(check: str, case: str, message: str, fix: str, tag: str) -> dict:
    """A pattern the code saw in the author's test code that is for the code critic to read and judge (X7-2): printed in an
    `ADVICE` block, filed in `work/advice-S5.json`, never a finding and never a hint to the author. A pattern hit from code is
    a hint to read, never the verdict (the critic's charter); whether it matters here is the role's call."""
    return _finding(check, case, message, fix, tag, level="advice")


# --- the case text ---------------------------------------------------------------------------

def then_clauses(text: str) -> list:
    """`[(number, text)]` of the case's Then section. An unnumbered Then is one clause."""
    match = THEN_HEADING_RE.search(text or "")
    if not match:
        return []
    body = (text or "")[match.end():]
    end = NEXT_HEADING_RE.search(body)
    body = body[:end.start()] if end else body
    items = [(int(n), t.strip()) for n, t in THEN_ITEM_RE.findall(body) if t.strip()]
    if items:
        return items
    stripped = "\n".join(line for line in body.splitlines() if line.strip())
    return [(1, stripped.strip())] if stripped.strip() else []


def clause_tokens(clause: str) -> list:
    """The names a clause demands, de-duplicated. Plain words only when nothing exact."""
    out: list = []
    for pattern in SPECIFIC_TOKEN_RES:
        for hit in pattern.findall(clause or ""):
            token = (hit if isinstance(hit, str) else hit[0]).strip()
            if 2 <= len(token) <= 60 and token not in out:
                out.append(token)
    if out:
        return out
    for token in PLAIN_TOKEN_RE.findall(clause or ""):
        if token not in out:
            out.append(token)
    return out


# A number that measures something is not a status code, however the sentence reads before it.
# Live TP1-13797, 27.09: TC-002's Then 4 says "The create call succeeds (2xx), and a
# subsequent GET returns the 500-character expression unchanged" - `returns` + `500` matched, and
# the gate told the automator its test contradicted a clause demanding HTTP 500. The case demands
# 2xx and says so; the 500 is the length of the expression. The automator was right and held its
# ground, which cost a boundary and a dispatch.
MEASURED_UNITS = ("characters", "chars", "bytes", "items", "rows", "lines", "entries",
                  "records", "ms", "milliseconds", "seconds", "minutes", "retries", "retry",
                  "attempts", "executions", "tests", "cases")
MEASURED_AFTER_RE = re.compile(
    "(?i)^(?:-[a-z]|\\s{0,2}(?:"
    + "|".join(unit + "?" for unit in MEASURED_UNITS) + ")\\b)")


def clause_status_codes(clause: str) -> list:
    """The HTTP statuses a Then FIXES. A number that turns out to measure something is dropped."""
    text = clause or ""
    out: list = []
    for match in STATUS_DEMAND_RE.finditer(text):
        code = match.group(1) or match.group(2)
        if not code or code in out:
            continue
        if MEASURED_AFTER_RE.match(text[match.end():]):
            continue
        out.append(code)
    return out


def case_partitions(text: str) -> list:
    out: list = []
    for token in PARTITION_RE.findall(text or ""):
        if token not in out:
            out.append(token)
    return out


# --- the test code ---------------------------------------------------------------------------

class PyFile:
    """One parsed Python test file. Everything language-specific lives behind this."""

    def __init__(self, path: Path, text: str):
        self.path, self.text = path, text
        self.tree = ast.parse(text)
        self.lines = text.splitlines()
        self.functions, self.fixtures = {}, {}
        for node in ast.walk(self.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("test"):
                self.functions[node.name] = node
            elif any("fixture" in self.source(d) for d in node.decorator_list):
                self.fixtures[node.name] = node

    def source(self, node) -> str:
        return "\n".join(self.lines[max(node.lineno - 1, 0):getattr(node, "end_lineno", node.lineno)])

    def marks(self, node) -> str:
        """Everything that can carry a case marker for one test: decorators and docstring."""
        parts = [ast.get_docstring(node) or ""]
        parts += [self.source(d) for d in getattr(node, "decorator_list", [])]
        return "\n".join(parts)


def read_python(path: Path):
    try:
        return PyFile(path, path.read_text(encoding="utf-8", errors="replace")), ""
    except SyntaxError as exc:
        return None, f"{path.name} does not parse as Python ({exc.msg}); code checks skipped"
    except OSError as exc:
        return None, f"{path.name} cannot be read ({type(exc).__name__}); code checks skipped"


def case_aliases(case: str, entries: list) -> list:
    """Every spelling a test file may use for this case id: `TC-012`, `TC_012`, its marker."""
    out = [case, case.replace("-", "_")] if case else []
    for entry in entries:
        marker = str((entry or {}).get("marker") or "").strip()
        for value in (marker, marker.replace("-", "_")):
            if value and value not in out:
                out.append(value)
    return [value for value in out if value]


def case_functions(entries: list) -> set:
    """The function names the manifest itself gives for these instances.

    Since 0.7.7 an instance id carries no case, and a consolidated test proving three cases
    usually carries the marker of one of them. Reading the manifest's own `test_function` /
    id is what tells the other two cases which function is theirs."""
    names = set()
    for entry in entries or []:
        raw = (entry or {}).get("test_function") or (entry or {}).get("function") \
            or C.test_instance_id(entry) or (entry or {}).get("test")
        name = C.function_name(raw)
        if name:
            names.add(name)
    return names


def functions_of_case(files: list, aliases: list, names=()) -> list:
    out = []
    for pyfile in files:
        for name, node in pyfile.functions.items():
            haystack = pyfile.marks(node) + "\n" + name
            if name in names or any(alias in haystack for alias in aliases):
                out.append((pyfile, name, node))
    return out


# --- the story's own records -----------------------------------------------------------------

def run_block_rows(task_root: Path) -> list:
    """Every run-block result row, oldest first (`read_run_blocks`: by the block's own clock,
    a reparse right after the block it supersedes — never by file name alone)."""
    rows = []
    blocks, _bad = read_run_blocks(Path(task_root))
    for item in blocks:
        block = item["data"]
        sha = str((block.get("source_fingerprint") or {}).get("test_content_sha") or "") \
            if isinstance(block.get("source_fingerprint"), dict) else ""
        results = block.get("results")
        for row in results if isinstance(results, list) else []:
            if isinstance(row, dict):
                rows.append({**row, "block": item["name"], "purpose": block.get("purpose"),
                             "test_content_sha": sha})
    return rows


def dispatch_scope(task_root: Path, dispatch_id: str | None) -> list | None:
    """The cases ONE dispatch was scoped to, or None when that cannot be read.

    Separate from `scope_cases` because the difference matters to a refusal: cases this
    dispatch owns are cases it can still repair, while an unscoped run speaks about rows a
    window closed days ago wrote — and a story that upgraded the plugin mid-flight carries
    those. Every new rule here refuses only inside the scope and reports the rest as a note."""
    if not dispatch_id:
        return None
    # One reader of the state view (`_state_view`, which also reads a 0.7.4 list of records).
    for dispatch in _state_view(Path(task_root))["dispatches"].values():
        if dispatch_id not in {str(dispatch.get("id")), str(dispatch.get("dispatch_id"))}:
            continue
        cases = [str(c) for c in (dispatch.get("scope") or dispatch.get("cases") or []) if c]
        if cases:
            return sorted(set(cases))
    return None


def scope_cases(task_root: Path, manifest: dict, dispatch_id: str | None) -> list:
    """The cases this check speaks about: the dispatch's scope when there is one, else every
    case the manifest names. A scope that cannot be read is never a reason to check nothing."""
    scoped = dispatch_scope(task_root, dispatch_id)
    if scoped:
        return scoped
    # Every case the manifest names, through `covers` as well as `case` — a consolidated
    # instance whose rows name only its `covers` used to put NO case in scope, so the check
    # silently had nothing to say about the very shape 0.7.7 asks the automator to choose.
    cases = {str(e.get("case") or "") for key in ("tests", "unresolved")
             for e in manifest.get(key) or [] if isinstance(e, dict)}
    cfg = C.case_config()
    cases |= {case for e in C.manifest_tests(manifest) for case in C.manifest_test_links(e, cfg)}
    return sorted(c for c in cases if c)


def case_files_named(root: Path, case: str, prefix: bool = False) -> list:
    """The `<case>.md` files under `root` (`prefix`: `<case>*.md`), the NAME matched exactly, on every platform.

    A case id is part of the file name, so the lookup is strict about case: `Path.rglob(f"{case}.md")` matches
    `tc-001.md` for `TC-001` on Windows and not on Linux, and the same story found its case file on a developer's
    machine and lost it in CI (t-911 / C4-13). The listing is `rglob("*.md")` and the name is compared here, not
    by `case_sensitive=True`, which needs Python 3.12 where the package promises 3.10. The suffix is exact too
    (`TC-001.MD` is no case file). The order is `sorted_paths`'. Two files of one name in two folders are both
    returned: which of them a caller takes is that caller's rule, as it was."""
    def named(name: str) -> bool:
        if prefix:
            return name.startswith(case) and name.endswith(".md") and len(name) >= len(case) + 3
        return name == f"{case}.md"
    return sorted_paths(p for p in root.rglob("*.md") if named(p.name))


def case_search_roots(task_root: Path) -> list:
    """The folders a case file is looked for under, in order, no repeats: the story's `work/test-cases`, the story
    itself, and the project's own case store (`contract.cases_root`, the one place a project that keeps its cases
    elsewhere has them). What a refusal that found no case file says it looked under (FR-1)."""
    roots = [Path(task_root) / "work" / "test-cases", Path(task_root)]
    try:
        roots.append(C.cases_root(Path(task_root)))
    except Exception:
        pass  # an unreadable config: the two roots every search has always used
    out: list = []
    for root in roots:
        if root not in out:
            out.append(root)
    return out


def find_case_file(task_root: Path, case: str) -> Path | None:
    """The case file of `case` (a bare id). The strict name search comes FIRST and decides everything it finds (the same
    file as before, `test_case_glob_strict.py`); only when it finds nothing the story's case index is asked, because a
    project keeps its cases where its config says (`cases_root`) and the index is the one reader of that (AR-13). A bare
    id that two areas both hold has no single file: the index keys it by area, so it resolves to nothing here and the
    caller says so (a Then of the other area must not answer, FR-59). An index that cannot be built finds nothing."""
    for root in (task_root / "work" / "test-cases", task_root):
        for path in case_files_named(root, case):
            return path
    try:
        index = C.case_index(task_root)
        _member, keys, _why = C.scope_member_resolution([case], index)[0]
        return Path(index[keys[0]]["path"]) if len(keys) == 1 else None
    except Exception:
        return None


def _case_file_of(task_root: Path, case: str, cfg) -> Path | None:
    """The case file one `then_refs` case names. The case is read by the contract's own parser
    (`split_case_key`), never by a local split: `feedback-api/TC-003` is THAT area's file, and when
    two areas hold TC-003 the other area's Then numbers must not answer for it (AR-13, AR-28). A bare
    id keeps the lookup by name. A qualified one is resolved through the story's case index by
    `contract.scope_member_resolution`; an index that cannot be built, or an area that holds no such
    case, finds no file - the caller then says so, which is the safe default (FR-59)."""
    area, number = C.split_case_key(case, cfg=cfg)
    if not area:
        return find_case_file(task_root, number)
    try:
        index = C.case_index(task_root)
        _member, keys, _why = C.scope_member_resolution([case], index, cfg=cfg)[0]
    except Exception:
        return None
    return Path(index[keys[0]]["path"]) if keys else None


def resolve_test_file(task_root: Path, relative: str) -> Path | None:
    """The manifest names a path relative to the project; the story sits three levels under
    it. Both spellings, plus an absolute one, are accepted — a path that cannot be found is
    reported by `validate_artifacts`, not here."""
    if not relative:
        return None
    candidates = [Path(relative)]
    root = task_root
    for _ in range(5):
        root = root.parent
        candidates.append(root / relative)
    return next((p for p in candidates if p.is_file()), None)


# --- the checks ------------------------------------------------------------------------------

def legacy_selectors(entries: list) -> list:
    """The oldest `tests[]` shape still in the wild: no `instance_id` of its own, a `case` and
    one function-level `selector` carrying every parameter at once
    (`test_validate_per_partition[valid|missing-assistant|...]`).

    The 0.7.9 migration rewrites `TC-012::test_x` and rows whose id IS the case number; it
    does not reach this one, so on TP1-15045 TC-012's legacy row survived and every check
    that reads instances read it as the case's only test. Naming the row is this check's job;
    retiring it is `migrate_artifacts.py --if-older`'s."""
    out = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("instance_id") or entry.get("test_instance_id") or "").strip():
            continue
        selector = str(entry.get("selector") or "").strip()
        if selector and selector not in out:
            out.append(selector)
    return out


def _legacy_note(entries: list) -> tuple:
    """(what to append to the message, what to prepend to the fix) when a legacy row is here."""
    selectors = legacy_selectors(entries)
    if not selectors:
        return "", ""
    return (f" — and tests[] still carries a row with no `instance_id` of its own "
            f"(selector `{selectors[0]}`), which is the row every instance-keyed check reads "
            "as this case's whole test",
            "retire that legacy row first (`migrate_artifacts.py --task-root <TASK_ROOT> "
            "--if-older` rewrites it into one instance per parameter), then ")


def _unresolved_targets(unresolved: dict, cases: list, by_case: dict, cfg, store_root, findings: list) -> list:
    """`[(scope case, unresolved row)]`: which scope case each `unresolved[]` row speaks about.

    A row answers the scope case that spells it exactly, as before. A row that names the BARE number
    (0.7.x wrote no area) also answers a qualified scope case of that number (`feedback-api/TC-003`)
    - the same generosity `contract.case_matches` gives every other reader of an unresolved row - but
    only while the number is held under ONE area: this scope's matching cases plus the areas the story's
    case store holds it under. Two areas make the bare row no evidence for either, and the row is a
    finding that names every spelling, never a skip (FR-59, AR-28)."""
    from execution_request import _store_areas  # the one reader of "which areas hold this number"

    def split(key):
        return C.split_case_key(key, cfg=cfg)

    pairs = []
    for ucase, entry in unresolved.items():
        if ucase in cases and ucase in by_case:
            pairs.append((ucase, entry))
            continue
        number = split(ucase)[1]
        if split(ucase)[0] or not number:
            continue  # a qualified row answers its own spelling only: no other area's case
        asked = [c for c in by_case if split(c)[0] and C.case_matches(ucase, c, cfg=cfg)]
        if not asked:
            continue
        areas = sorted({split(c)[0] for c in asked} | set(_store_areas(store_root, number, split)))
        if len(areas) > 1:
            spelled = ", ".join(f"{a}/{number}" for a in areas)
            findings.append(_finding(
                "manifest", ucase,
                f"the unresolved[] row {ucase} names no area, and {number} is held under more than one "
                f"area ({spelled}): the row is no evidence for any one of them",
                f"rewrite the row's `case` as one of {spelled} and re-send it through manifest_put.py",
                f"unresolved-area-{number}"))
            continue
        pairs.append((asked[0], entry))
    return pairs


def _road(task: str = "") -> str:
    """`FRAGMENT_ROAD` for the task `task`; with none, `<TICKET>` (a door the caller cannot fill in names the slot)."""
    return FRAGMENT_ROAD.replace("<T>", str(task or "") or "<TICKET>")


def _and(words: list) -> str:
    """`a`, `a and b`, `a, b and c`."""
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _slice_words(row: dict) -> str:
    """What a row's slice keys say, as words: `instance [x]`, `partitions [P-a, P-b]`, both joined; `the whole case`
    for a row with no slice key."""
    import acceptance as AC
    said = []
    for keys, noun in ((C.UNRESOLVED_INSTANCE_KEYS, "instance"), (C.UNRESOLVED_PARTITION_KEYS, "partition")):
        names = AC._slice_values(row, keys)
        if names:
            said.append(f"{noun}{'s' if len(names) > 1 else ''} [{', '.join(names)}]")
    return " and ".join(said) or "the whole case"


def _row_thens(row: dict) -> list:
    """The clause numbers a `contradicts_requirement` row names in `thens`, sorted; `[]` for a row that names none or
    whose `thens` is no list (such a row names no Then - the reader's rule, `acceptance.red_by_requirement`)."""
    raw = row.get(C.UNRESOLVED_THENS_KEY)
    return sorted({n for n in (C.then_number(x) for x in raw) if n}) if isinstance(raw, list) else []


def _distinct_cases(rows: list, cfg) -> list:
    """The cases the `unresolved[]` rows speak about, in the rows' order, one per case (`contract.case_matches`: a bare
    and a qualified spelling of one case are one)."""
    out: list = []
    for row in rows:
        case = str(row.get("case") or "").strip()
        if case and not any(C.case_matches(case, seen, cfg=cfg) or C.case_matches(seen, case, cfg=cfg) for seen in out):
            out.append(case)
    return out


def _green_tests(tests: list) -> list:
    """The tests of `tests` whose `status` is `green`."""
    return [t for t in tests if str(t.get("status") or "") == "green"]


def _greens_in_slice(row: dict, greens: list, case: str, cfg) -> list:
    """The `green` tests of `case` that `row`'s slice reaches: the ones `acceptance.row_slice` says the row speaks about,
    and the ones that declare no partition when the row names partitions - a green with no partition stands for ALL of
    them, so beside a partition row it is the evidence the row is refused on (the error direction is the finding). A row
    with no slice key reaches every green of the case. A green the row names another instance or another partition
    than is NOT reached: it is the normal state of a case with several instances."""
    import acceptance as AC
    return [t for t in greens if AC.row_slice(row, t, case, cfg) in ("", AC.SLICE_NO_PARTITIONS)]


def _check_contradicts_row(case: str, row: dict, tests: list, red: dict, cfg, findings: list) -> None:
    """A `contradicts_requirement` row of `case` against the tests that prove `case` (`tests`), by the row's own slice
    (AR-26: the pair is the unit, the whole case is not). `contradicts-but-green`: a green test the row's slice reaches
    (for a row with no slice key: any green test of the case, as it has always been). `contradicts-no-instance`, for a
    row WITH a slice only: no test of that slice is red by THIS row (`red` is `acceptance.red_by_requirement`, structural),
    so the manifest names a red that no test stands behind. Both can speak for one row."""
    import acceptance as AC
    greens = _greens_in_slice(row, _green_tests(tests), case, cfg)
    sliced = C._slice_scoped(row)
    if greens:
        ids = ", ".join(sorted({C.test_instance_id(t) for t in greens if C.test_instance_id(t)}))
        # A whole-case row keeps its sentence byte for byte; a row with a slice names the tests it reached.
        said = (f"{ids} is `green` while {case}'s unresolved[] row says {CONTRADICTS} for it" if sliced and ids
                else f"{case} is `green` while its unresolved[] row says {CONTRADICTS}")
        findings.append(_finding(
            "manifest", case,
            said + " — a test that passes does not prove the code contradicts the requirement",
            "hand the test over red with the observed and expected values in the "
            "unresolved[] row, or drop the row: the expected value is never changed "
            "to match the code", "contradicts-but-green"))
    if not sliced:
        return
    in_slice = [C.test_instance_id(t) for t in tests if AC.row_slice(row, t, case, cfg) == ""]
    if any(r is row for iid in in_slice for r in red.get(iid, [])):
        return
    thens = _row_thens(row)
    findings.append(_finding(
        "manifest", case,
        f"{case}'s unresolved[] row says {CONTRADICTS} for {_slice_words(row)}, and no test in that slice binds "
        f"{('Then ' + ', '.join(map(str, thens))) if thens else 'a Then'} of {case} - a red the manifest names with no "
        "test behind it",
        "bind the red Then to the red test in `then_bindings` (status covered, its `instance_id`) and name that test in "
        "the row (`instance_ids`, `thens`); if that test never reaches " + case + "'s check because another case's "
        f"assert fails first, retract the row (`retracted_unresolved: [\"{case}\"]`) and record those Thens as "
        f"`{BLOCKED_BY_CHECK}`; send the rows through `{_road()}`", "contradicts-no-instance"))


_REF_SPAN_RE = re.compile(r"^(.*):(\d+)(?:-(\d+))?$")


def _ref_span(ref) -> tuple | None:
    """`(file, first line, last line)` of an `assertion_ref` `path:a-b` (or `path:a`), None for anything else."""
    match = _REF_SPAN_RE.match(str(ref or "").strip())
    if not match:
        return None
    first = int(match.group(2))
    last = int(match.group(3) or first)
    return (match.group(1), first, last) if 0 < first <= last else None


def _red_order_hole(span_m, span_n) -> str:
    """How the assert lines of Then m and of the red Then n stand to each other: `behind` (m starts after n ends, same
    file), `before` (m ends before n starts), `unknown` for everything else - a missing or unreadable ref, another file,
    overlapping lines (the live shape: every Then of a test carries the test's one range). Error direction: `unknown`."""
    if span_m is None or span_n is None or span_m[0] != span_n[0]:
        return "unknown"
    if span_m[1] > span_n[2]:
        return "behind"
    return "before" if span_m[2] < span_n[1] else "unknown"


def _span_entry(span, task_root):
    """`(project file, language, detector entry)` of the file one `assertion_ref` span names, or None when the file is not
    found or its suffix has no entry in `detectors.json` (a `.py` never has one). Anything unreadable is None."""
    if span is None or task_root is None:
        return None
    try:
        import assertion_detectors as AD
        found = resolve_test_file(Path(task_root), span[0])
        language, entry = AD.entry_for_suffix(AD.assertion_detectors(), found.suffix) if found else (None, None)
    except Exception:
        return None
    return (found, language, entry) if entry is not None else None


def _all_soft(span, task_root) -> bool:
    """True only when EVERY assertion head inside the lines of `span` (`(file, first, last)`) is a soft form of the file's
    language (`soft_assert_patterns` of its `detectors.json` entry): the lines record their failures and let the test
    go on. The file is read the way the probe reads it (`probe_by_code.Source`: comments and strings are blanked, so a
    soft form named in a comment or in a string is no head). Error direction: False - no span, no project, an unreadable
    file, a language with no entry or no soft form, a lexer refusal, a hard head among the heads, NO head at all
    (a span with nothing in it proves nothing). Only False can come out of a doubt: it leaves the finding standing."""
    got = _span_entry(span, task_root)
    if got is None:
        return False
    found, _language, entry = got
    try:
        import assertion_detectors as AD
        import probe_by_code as PBC
        soft = [re.compile(p) for p in AD.soft_patterns(entry)]
        if not soft:
            return False
        src = PBC.Source(found.read_text(encoding="utf-8-sig"), entry["lexer"], span[0])
        heads = [m for form in entry["assertions"] for m in re.finditer(form["head"], src.skeleton)
                 if span[1] <= src.line(m.start()) <= span[2]]
        return bool(heads) and all(any(rx.match(src.skeleton, m.start()) for rx in soft) for m in heads)
    except Exception:
        return False


def _frame_in(frame, spans, root_file) -> bool:
    """Is the report frame `(path, line)` a line inside one of `spans`? The frame's path is the project file itself
    (absolute, resolved to the same file) or spelled exactly as the span spells it. Another file, or a relative path
    that is not the span's, is outside: the runner's working directory is not known, so it is never guessed."""
    path, line = frame
    for span in spans:
        if not span[1] <= line <= span[2]:
            continue
        shown = path[2:] if path.startswith("./") else path
        if shown == span[0].replace("\\", "/"):
            return True
        try:
            if os.path.isabs(path) and os.path.normcase(os.path.realpath(path)) == os.path.normcase(
                    os.path.realpath(root_file)):
                return True
        except OSError:
            pass
    return False


def _soft_release(task_root, iid: str, red_spans: list, entry=None) -> bool:
    """Does the run itself show that the asserts BEHIND a soft red did run (EP1-38, B-10)? True only when all hold: the
    project is known; every red span is made of soft heads only (`_all_soft`) and all are one language; the NEWEST
    run block that holds a row of `iid` says that row `failed`; that block's own raw report is established
    (`run_history.report_rows_of`: the recorded sha, a path inside the story); it lists the rows of the row's
    `test_id`; every such row yields its failure frames (`reporters.failure_frames`, the entry's grammar); and EVERY frame of
    them lies inside a red span (same file, line within). A frame anywhere else - a `throw` or a hard assert later in the
    test, a call into a helper - means the test stopped or went elsewhere, so the later asserts may never have run.
    `entry` is the language's detector entry (the frame grammar); None: read from the first span's suffix.
    Error direction: False on every unknown, which leaves `red-own-behind` as it is (FR-18, FR-59, AR-28)."""
    if task_root is None or not red_spans or any(s is None for s in red_spans):
        return False
    try:
        import assertion_detectors as AD
        import reporters
        import run_history as RH
        got = [_span_entry(s, task_root) for s in red_spans]
        if any(g is None for g in got) or len({g[1] for g in got}) != 1:
            return False
        entry = entry or got[0][2]
        if not all(_all_soft(s, task_root) for s in red_spans):
            return False
        row = data = None
        for block in reversed(RH.read_run_blocks(Path(task_root))[0]):
            results = block["data"].get("results")
            mine = [r for r in results if isinstance(r, dict) and str(r.get("instance_id") or "") == iid] \
                if isinstance(results, list) else []
            if mine:
                data, row = block["data"], mine[-1]
                break
        if row is None or row.get("status") != "failed" or not str(row.get("test_id") or ""):
            return False
        rows = RH.report_rows_of(Path(task_root), data)
        if not rows:
            return False
        named = [r for r in rows if isinstance(r, dict) and r.get("test_id") == row["test_id"]]
        if not named:
            return False
        frames, skip_frames, _how = AD.grammar_of(entry)
        error_head, after_frame_ok = AD.soft_report_of(entry)
        if error_head is None:
            return False   # the language does not say how its failure text is built: the finding stays (F-2)
        for report_row in named:
            seen = reporters.failure_frames(report_row, frames, skip_frames, error_head, after_frame_ok)
            if seen is None:
                return False
            for frame in seen:
                if not any(_frame_in(frame, [s], g[0]) for s, g in zip(red_spans, got)):
                    return False
        return True
    except Exception:
        return False


def _own_red_order(manifest: dict, case: str, test: dict, iid: str, rows: list, cfg, findings: list,
                   hints: list | None = None, task_root=None) -> None:
    """The instance `iid` is red by a row of `case` ITSELF. A test stops at its first failing assert, so a Then of `case`
    bound `covered` on it, that is not the red Then and is not recorded `blocked_by_check`, either sits ABOVE the red
    assert (it ran) or BEHIND it (it never ran, and `covered` is a claim with no run behind it, FR-18). Code reads the
    order only off the pinned lines (`then={m: "a-b"}` on the marker, `assertion_ref` of each binding) and never guesses
    it (FR-58, FR-59): `red-own-behind-<iid>-<m>` when the pinned lines of m come after a red Then's, `red-own-order-
    unknown-<iid>-<m>` when the order is not established (no pins, a shared range, another file), one
    `red-own-thens-unnamed-<iid>` when an own row names no `thens` (the red Thens are then unknown). Error direction: an
    extra finding, never a silent pass - except `behind` of a SOFT red, which the run's own report can lift
    (`_soft_release`, `task_root` given: a soft failure does not stop the test); a Then that waits for the defect (the case's own text) is answered by the door,
    not by moving it (a moved dependent Then is an empty green). `hints` given: the same words as hints, not findings
    (an S7 repair round of `TEST_BUG`/`FLAKY`: the round is not spent on them)."""
    own = [r for r in rows if isinstance(r, dict) and str(r.get("case") or "").strip()
           and C.case_matches(str(r["case"]).strip(), case, cfg=cfg)]
    out = findings if hints is None else hints
    make = _finding if hints is None else _hint
    road = _road()
    if not own:
        return
    if any(not _row_thens(r) for r in own):
        out.append(make(
            "manifest", case,
            f"{iid} is red for {case}'s own unresolved[] row, and the row names no `thens` - which Then of {case} failed "
            "is not established, so no other Then of it on this test can be told apart from one that never ran",
            f"name the failed Then in the row (`thens: [n]`) and send the rows through `{road}`",
            f"red-own-thens-unnamed-{iid}"))
        return
    reds = sorted({n for r in own for n in _row_thens(r)})
    aliases = set(C.instance_id_aliases(test, cfg))
    mine = [b for b in bindings_of_case(manifest, case, cfg) if str(b.get("instance_id") or "") in aliases]
    blocked = {C.then_number(b.get("then")) for b in mine if str(b.get("reason") or "") == BLOCKED_BY_CHECK}
    covered = [b for b in mine if str(b.get("status") or "covered") == "covered"]
    spans: dict = {}
    for b in covered:
        number = C.then_number(b.get("then"))
        if number:
            spans.setdefault(number, []).append(_ref_span(b.get("assertion_ref")))
    released = None   # `_soft_release`, asked at most once per call and only when a Then is `behind`
    for m in sorted(n for n in spans if n not in reds and n not in blocked):
        verdicts = {(n, _red_order_hole(sm, sn)) for sm in spans[m] for n in reds for sn in spans.get(n) or [None]}
        behind = sorted(n for n, v in verdicts if v == "behind")
        unknown = sorted(n for n, v in verdicts if v == "unknown")
        if behind:
            if released is None:
                released = _soft_release(task_root, iid, [s for n in reds for s in spans.get(n) or [None]])
            # A red that does not stop the test (every head of its lines is soft) and a run whose own report shows no
            # failure outside those lines: the Then behind it did run. `unknown` is never lifted (FR-59).
            if released is True:
                behind = []
        if not behind and not unknown:
            continue
        waiting = _and([f"Then {n}" for n in (behind or unknown)])
        door = (f"if Then {m} does not wait for {waiting}'s defect (the case's Then text and Self-probe notes), move its "
                f"assert above {waiting}'s; if it does wait, record it as `{BLOCKED_BY_CHECK}` with `blocking_check: "
                f"\"<the case whose defect it waits for>\"`; or pin the Then lines on the marker "
                f"(`then={{{m}: \"a-b\", {(behind or unknown)[0]}: \"c-d\"}}`); send the rows through `{road}`")
        if behind:
            lines = next((s for s in spans[m] if s), ("", 0, 0))
            out.append(make(
                "manifest", case,
                f"Then {m} of {case} is bound `covered` on {iid}, whose assert comes after the red {waiting} of {case} "
                f"(lines {lines[1]}-{lines[2]}): the test stops at the red, so Then {m} never ran",
                door, f"red-own-behind-{iid}-{m}"))
        else:
            out.append(make(
                "manifest", case,
                f"{iid} is red at {waiting} of {case}; Then {m} is bound `covered` on it, and the order of the asserts is "
                f"not established (the Then lines are not pinned apart): Then {m} may never have run",
                door, f"red-own-order-unknown-{iid}-{m}"))


def _check_red_rows(manifest: dict, by_case: dict, targets: list, red: dict, cfg, findings: list,
                    hints: list | None = None, task_root=None) -> None:
    """The two findings of an instance that is red for rows of the manifest (`red`, structural):

    `red-two-cases-<iid>` (under each case K whose row is among them): the instance is red for the rows of two or more
    different cases. A test stops at its first failing assert, so one of those cases failed and the others' Thens never
    ran; the manifest cannot say which, and code does not guess (FR-58). Error direction: the author keeps one row and
    records the rest as `blocked_by_check` - "not proven", never a pass.

    `red-links-unbound` (under each case C): a red instance covers C, none of the red rows is C's own, and the instance
    holds no Then of C - neither a covered `then_bindings` row nor a `blocked_by_check` row - so nothing says what
    became of C's Thens on it. Detects the loss of a blocked row: a fragment that replaced its unit, or a writer re-run
    that wrote the same Then of the same test."""
    import acceptance as AC
    for iid, rows in red.items():
        cases_of = _distinct_cases(rows, cfg)
        if len(cases_of) < 2:
            continue
        for case, entry in targets:
            if any(entry is row for row in rows):
                findings.append(_finding(
                    "manifest", case,
                    f"{iid} is red, and the unresolved[] rows of {_and(cases_of)} each say {CONTRADICTS} for it - a test "
                    "stops at its first failing assert, so only one of these cases' Thens failed and the others never ran",
                    "keep the row of the case whose assert failed (the run report names the line); retract every other "
                    "row with `retracted_unresolved: [\"<case>\"]` and record that case's Thens on " + iid +
                    f" as `{BLOCKED_BY_CHECK}` with `blocking_check: \"<kept case>\"` - one fragment through "
                    f"`{_road()}`", f"red-two-cases-{iid}"))
    for case, tests in by_case.items():
        unbound, said = [], []
        mine = bindings_of_case(manifest, case, cfg)
        for test in tests:
            iid = C.test_instance_id(test)
            if not iid or iid not in red:
                continue
            if AC.red_by_own_row(red, iid, case, cfg):
                # Red by the case's OWN row: `red-links-unbound` is unreachable here (its Thens are judged by the order
                # of the asserts, `_own_red_order`); it is reachable only for an instance red by another case's row.
                # Silent here: a green test (its row is judged by `contradicts-but-green`) and an instance red for two
                # or more cases (`red-two-cases` asks to keep one row first; the order is judged on the next run).
                if (str(test.get("status") or "") != "green" and len(_distinct_cases(red[iid], cfg)) < 2):
                    _own_red_order(manifest, case, test, iid, red[iid], cfg, findings, hints, task_root)
                continue
            if iid in unbound:
                continue
            aliases = set(C.instance_id_aliases(test, cfg))
            if any(str(b.get("instance_id") or "") in aliases and (
                    str(b.get("status") or "covered") != "unresolved" or str(b.get("reason") or "") == BLOCKED_BY_CHECK)
                   for b in mine):
                continue
            unbound.append(iid)
            said += [c for c in _distinct_cases(red[iid], cfg) if c not in said]
        if unbound:
            findings.append(_finding(
                "manifest", case,
                f"{_and(unbound)} {'is' if len(unbound) == 1 else 'are'} red for {_and(said)} and "
                f"{'covers' if len(unbound) == 1 else 'cover'} {case}, and nothing says what happens to {case}'s Thens "
                f"on {'it' if len(unbound) == 1 else 'them'}",
                "bind the Thens placed before the red, or record the ones behind it as "
                f"`{BLOCKED_BY_CHECK}`, and send the rows through `{_road()}` (a later `manifest_from_tests.py` run keeps "
                "them unless it writes the same Then of the same test itself)", "red-links-unbound"))


def check_manifest(manifest: dict, cases: list, findings: list, store_root=None, hints: list | None = None) -> None:
    cfg = C.case_config()  # once per check: every entry below asks the same question (B-013)
    # The scope `cases` keep the area the dispatch handed out (`feedback-api/TC-003`), the links are
    # bare: each scope case asks `entries_for_case` in its own spelling (t-044, the sweep of the
    # OB-3 defect). For a bare scope the answer is what `set(links) & set(cases)` gave.
    all_tests = C.manifest_tests(manifest)
    by_case: dict = {}
    for case in dict.fromkeys(cases):
        rows = C.entries_for_case(all_tests, case, cfg)
        if rows:
            by_case[case] = rows
    answering = {id(entry) for rows in by_case.values() for entry in rows}
    tests = [t for t in all_tests if id(t) in answering]
    unresolved = {str(u.get("case") or ""): u for u in C.manifest_unresolved(manifest)}

    seen: dict = {}
    for entry in tests:
        iid = C.test_instance_id(entry)
        if not iid:
            continue  # an entry with no identity at all is validate_artifacts' finding
        if iid in seen:
            findings.append(_finding(
                "manifest", str(entry.get("case") or ""),
                f"two tests[] entries carry the instance id {iid!r}",
                "one row per test: rewrite the fragment with contract.instance_id(function, "
                "parameter) and re-run manifest_put.py --fragment", f"dup-{iid}"))
        seen[iid] = entry
        # The id names a case in the spelling it was written in: `feedback-api/TC-003` against the
        # row's `covers: ["feedback-api/TC-003"]` is the same finding the bare pair gives (t-044
        # fix round, critic t-045 F2); `entries_for_case` is the one predicate.
        if C.entries_for_case([entry], iid, cfg) or iid == str(entry.get("case") or ""):
            said, do_first = _legacy_note([entry])
            findings.append(_finding(
                "manifest", str(entry.get("case") or ""),
                f"instance id {iid!r} names the CASE, not one test — a case with several test "
                "functions then gets one reporter row for all of them" + said,
                do_first + "one tests[] entry per test function/parameter, id "
                "`<function>[<parameter>]` (contract.instance_id); the cases it proves go in "
                "`covers`", f"shape-{iid}"))

    # The rows the ONE reader (`acceptance.blocked_instances`, t-219) says block an instance of this scope: the
    # structure of the manifest alone (no run is read here - `root` is not given, so "a passed run on the
    # current bytes" is not asked), which is what the both-lists rule below needs. {instance id: its row}.
    import acceptance as AC
    window_scope: dict = {}
    for case, rows in by_case.items():
        window_scope[case] = list(dict.fromkeys(C.test_instance_id(t) for t in rows if C.test_instance_id(t)))
    blocked_here = AC.blocked_instances(
        manifest, [{"instance_id": i} for ids in window_scope.values() for i in ids], window_scope)

    # Which instance of the story is red against which `contradicts_requirement` row, from the ONE reader, by the
    # manifest's structure alone (`strict=False`: no run is read here). A row's slice is `acceptance.row_slice` and
    # nothing else (AR-13); the unit of an outcome is the (Then, instance) pair (AR-26), so a green is compared with
    # the instances and partitions of ITS row, never with the whole case.
    story = AC.story_scope(manifest, cfg)
    red = AC.red_by_requirement(manifest, [{"instance_id": i} for ids in story.values() for i in ids], story,
                                strict=False)
    targets = _unresolved_targets(unresolved, cases, by_case, cfg, store_root, findings)
    for case, entry in targets:
        partitions = AC._slice_values(entry, C.UNRESOLVED_PARTITION_KEYS)
        greens = _green_tests(by_case[case])  # the whole case's greens: only a row with no slice key compares with them
        reason = str(entry.get("reason") or "")
        if reason == BLOCKED_BY_ENV:
            # The third sanctioned way a case is in both lists (t-219): the row blocks ONE instance of it, named
            # by `instance_ids` or reached by the single-instance rule (the cmp2 rows carry a partition and
            # no instance), and that instance's tests[] row is not green - it ran red on the stand's own page
            # or did not run. A green row of THAT instance is the contradiction ("blocked-but-green"); a green
            # row of another instance of the case is the normal state of a case with several.
            mine = {i for i, row in blocked_here.items() if row is entry}
            named = AC.blocked_row_instances(entry)
            if mine or (named and not partitions):
                # A row that names its instances is instance-scoped even when it is not a valid block (no
                # remedy): `check_environment` says what to repair, and it is not "both lists" as well.
                stale = [t for t in greens if set(C.instance_id_aliases(t, cfg)) & (mine | named)]
                if stale:
                    ids = ", ".join(sorted({C.test_instance_id(t) for t in stale}))
                    findings.append(_finding(
                        "manifest", case,
                        f"{ids} is `green` while its unresolved[] row says {BLOCKED_BY_ENV} - a test that passed "
                        "was not blocked, and the row hides a real result",
                        "send the green tests[] entry through manifest_put.py: it drops the stale blocked row "
                        "(or removes the instance from its `instance_ids`). Never hand-edit "
                        "automation-manifest.json", "blocked-but-green"))
                continue
        if reason == AC.PENDING_OUTCOME and AC.blocked_row_instances(entry):
            # The fourth sanctioned way a case is in both lists (t-2181 PC-4, B1): the row names the instances of the case that are
            # written and cannot run yet (their side does not exist). A row that names its instances is instance-scoped, so it is
            # not "both lists"; whether an instance is REALLY excused stays with `check_sides` (C5) and the run mapping - no second
            # excuse rule here. A green tests[] row of a named instance is the contradiction (the twin of `blocked-but-green`).
            named = AC.blocked_row_instances(entry)
            stale = [t for t in greens if set(C.instance_id_aliases(t, cfg)) & named]
            if stale:
                ids = ", ".join(sorted({C.test_instance_id(t) for t in stale}))
                findings.append(_finding(
                    "manifest", case,
                    f"{ids} is `green` while its unresolved[] row says {AC.PENDING_OUTCOME} - a test that passed was not pending, "
                    "and the row hides a real result",
                    "send the green tests[] entry through manifest_put.py and retract the pending row "
                    f"(`{{\"retracted_unresolved\": [\"{case}\"]}}`), or remove the instance from its `instance_ids`. Never hand-edit "
                    "automation-manifest.json", "pending-but-green"))
            continue
        if reason == BLOCKED_BY_CHECK:
            # That reason is a Then's (`then_bindings`), never a whole case's: a case row that says it hides which
            # Thens the red stops. The row is named, not read as anything else (no `both-lists`, no `partial-green`).
            findings.append(_finding(
                "manifest", case,
                f"{case}'s unresolved[] row says {BLOCKED_BY_CHECK}; that reason belongs to a Then, not to a whole case",
                "record each Then the red stops as a `then_bindings` row {case, then, instance_id, status: unresolved, "
                f"reason: {BLOCKED_BY_CHECK}, blocking_check, detail}}, retract this row with "
                f"`retracted_unresolved: [\"{case}\"]`, and send both through `{_road()}`", "blocked-check-row"))
            continue
        if reason == CONTRADICTS:
            # The one sanctioned way a case is in both lists: the test is handed over RED
            # because the code contradicts the requirement, and the unresolved row says so.
            # The red test IS the evidence; S7 decides what it is (an APP_BUG draft is one outcome). A green test
            # beside that row is the contradiction that needs explaining, not the red one.
            # A row with a slice (instances, partitions) speaks about that slice only: the branch is the same for it,
            # `partial-green` is never said for this reason (HF2-3, K1).
            _check_contradicts_row(case, entry, by_case[case], red, cfg, findings)
            continue
        if reason == HANDED and not partitions:
            # The other sanctioned way a case is in both lists: the test exists and was
            # reviewed, and nothing here ran it — by the person's own decision.
            if greens:
                findings.append(_finding(
                    "manifest", case,
                    f"{case} is `green` while its unresolved[] row says {HANDED} — nothing in "
                    "this session ran it, so `green` is a claim with no run behind it",
                    "leave the instance without an outcome of its own and keep the "
                    f"unresolved[] row with `{HANDED}`; the person runs it when they choose",
                    "handed-but-green"))
            continue
        if not partitions:
            findings.append(_finding(
                "manifest", case,
                f"{case} is in tests[] and in unresolved[] at the same time — the two lists "
                "disagree about whether it ran",
                "manifest_put.py owns this invariant: send the decision as a fragment (a green "
                "tests[] entry drops the whole-case unresolved row). Never hand-edit "
                "automation-manifest.json", "both-lists"))
        elif _greens_in_slice(entry, greens, case, cfg):
            # Which rows carry the green, and whether one of them is the legacy shape: a bare
            # "partial-green" verdict tells the author nothing about WHICH evidence is being
            # refused, and on TP1-15045 the answer was to re-run every test of the window.
            # Only a green the row's partitions reach is that evidence (a green of another partition is the normal
            # state of a case with several); one that declares no partition stands for all of them.
            greens = _greens_in_slice(entry, greens, case, cfg)
            said, do_first = _legacy_note(greens)
            ids = sorted({C.test_instance_id(g) for g in greens if C.test_instance_id(g)})
            claimed = ", ".join(ids[:2]) + (f" and {len(ids) - 2} more" if len(ids) > 2 else "")
            findings.append(_finding(
                "manifest", case,
                f"{case} is `green` while {len(partitions)} of its partitions are unresolved "
                f"({', '.join(partitions)}) — the green is claimed by "
                f"{claimed or 'a row with no instance id'} and stands for the whole case" + said,
                do_first + "split tests[] into one instance per covered partition, or move the "
                "case to unresolved[] with its reason; green may not stand for the remainder "
                "(the covered partitions keep their existing runs — nothing here asks for a rerun); or, "
                "when a person takes the rest of a Then, record that Then as a remainder "
                "(`qa_unresolved(case=, then=[n], reason=\"handed_to_person\", owner=, detail=<steps>)`) "
                "and drop this partition row; the orchestrator records the person's words under "
                "`" + C.THEN_HANDED_MATCH_PREFIX + " <case>#<n>`",
                "partial-green"))

    _check_red_rows(manifest, by_case, targets, red, cfg, findings, hints, task_root=store_root)

    keys = []
    for i, fix in enumerate(manifest.get("self_fixes") or []):
        token = json.dumps(fix, ensure_ascii=False, sort_keys=True, default=str)
        if token in keys:
            findings.append(_finding(
                "manifest", str((fix or {}).get("test") or "") if isinstance(fix, dict) else "",
                f"self_fixes[{i}] is byte-identical to an earlier entry — it reads as two "
                "repairs of the same line",
                "manifest_put.py drops an identical repeat; remove the copy and re-send the "
                "fragment", f"dup-fix-{i}"))
        keys.append(token)


def instances_of_case(manifest: dict, case: str, cfg: dict | None = None) -> list:
    """Every `tests[]` row that proves this case, not only the rows whose `case` field spells
    it. One instance may carry several `case_version_links` — a consolidated test is a
    legitimate shape (`contract.test_instance_id`), and filtering on `case` alone reported
    it as a missing test for every case but the owning one.

    The asked case keeps its spelling (TP2-2406 S5-6, 19.10.2026): the dispatch scope held
    `feedback-api/TC-003` and the row `covers: ["feedback-api/TC-003"]`, but the old test was
    `case in manifest_test_links(entry)`, which answers in BARE ids on purpose - so no row answered
    the qualified case, OB-3 read as unbound and the binding that named the instance exactly did
    not count. `contract.entries_for_case` is the one predicate (non-strict: a bare ask over a
    number two areas hold returns both rows, as before)."""
    cfg = C.case_config() if cfg is None else cfg  # once per call, not once per entry (B-013)
    return C.entries_for_case(C.manifest_tests(manifest), case, cfg)


def _covering_ids(manifest: dict, case: str, cfg: dict | None = None) -> set:
    """Every spelling of every instance that covers this case — Since 0.7.7 a `then_bindings`
    row may name an instance in its bare form while the manifest row still carries the
    0.7.7 case-prefixed one, and both mean the same test."""
    cfg = C.case_config() if cfg is None else cfg
    return {alias for entry in instances_of_case(manifest, case, cfg)
            for alias in C.instance_id_aliases(entry, cfg)}


def bindings_of_case(manifest: dict, case: str, cfg: dict | None = None) -> list:
    """Then-binding rows for this case: a row that names it, or — when a row names only the
    instance — a row whose instance proves it through `covers` / `case_version_links`."""
    # A row that NAMES a case answers through `contract.entries_for_case`, in the asker's own
    # spelling (t-044 fix round, critic t-045 B1): the old `case in C.case_ids(row case)` answers
    # in BARE ids, so the live rows `feedback-api/TC-003` never matched the qualified ask and
    # `bindings:feedback-api/TC-003:no-bindings` was reported over two exact bindings. A row is
    # read like a manifest row (`manifest_test_keys` reads its `case`); a bare ask still finds it.
    cfg = C.case_config() if cfg is None else cfg
    owned = _covering_ids(manifest, case, cfg)
    out = []
    for row in manifest.get("then_bindings") or []:
        if not isinstance(row, dict):
            continue
        value = row.get("case") or row.get("case_id")
        if C.case_ids(value, cfg=cfg):
            if C.entries_for_case([{"case": value, "area": row.get("area")}], case, cfg):
                out.append(row)
        elif str(row.get("instance_id") or "") in owned:
            out.append(row)
    return out


def check_bindings(manifest: dict, case: str, text: str, files: list, targets: list,
                   findings: list) -> None:
    clauses = then_clauses(text)
    if not clauses:
        return
    # A ghost of a retracted instance (HF3-2, F-4 (a)): the row a send of the retracted name left in a projection written
    # before `manifest_put` refused it. It makes the old spelling look covered (`_covering_ids`), so the Thens still bound
    # to that spelling would be silent here instead of `unlinked-`; it is named, with the road that takes it away. The
    # predicate is `manifest_put.is_ghost_row` - the one the refusal of a new write asks (AR-13); imported here because
    # the module is the writer's, and lazily, like `acceptance` below.
    import manifest_put as MP
    for entry in instances_of_case(manifest, case):
        if MP.is_ghost_row(entry, manifest):
            instance = C.test_instance_id(entry)
            findings.append(_finding(
                "bindings", case,
                f"tests[] row {instance!r} is the ghost of an instance this manifest retracted: it carries no `covers` "
                f"or `case_version_links`, proves no case, and makes that id look covered",
                f"retract it again with `{FRAGMENT_ROAD}` carrying "
                + json.dumps({"retracted_instances": [instance]}) + " (this also takes out the Then rows still bound "
                "to it), or, to bring the test back, send its whole row with `covers` and `case_version_links`",
                f"ghost-{instance}"))
    bindings = bindings_of_case(manifest, case)
    if not bindings:
        findings.append(_finding(
            "bindings", case,
            f"bindings missing: {case} has {len(clauses)} Then clause(s) and no `then_bindings` "
            "row — nothing says which test and which assertion proves each one",
            "add then_bindings[] to the fragment: {case, then, instance_id, assertion_ref, "
            "status} per clause; an uncovered clause is `status: unresolved` with a reason",
            "no-bindings"))
    else:
        bound = {C.then_number(b.get("then")) for b in bindings if str(b.get("status") or "covered") != "unresolved"
                 and (b.get("instance_id") and b.get("assertion_ref"))}
        recorded = {C.then_number(b.get("then")) for b in bindings}
        for number, _clause in clauses:
            if number in bound or number in recorded:
                continue
            findings.append(_finding(
                "bindings", case,
                f"Then {number} of {case} has no `then_bindings` row — neither a test and "
                "assertion that proves it nor a recorded reason it is unresolved",
                "bind it to an instance and an assertion line, or record it in unresolved[] "
                "with a reason from the closed list", f"unbound-{number}"))
        # a clause of case B may be bound to a test of any shape, as long as that test
        # SAYS it covers B. Without the link the consolidation is invisible to the ledger,
        # the roll-call and the stage guard, and B reaches gate B as `not_executed`.
        covering = _covering_ids(manifest, case)
        for row in bindings:
            instance = str(row.get("instance_id") or "")
            if not instance or instance in covering:
                continue
            findings.append(_finding(
                "bindings", case,
                f"Then {row.get('then')} of {case} is bound to {instance!r}, and no tests[] "
                f"entry with that id lists {case} among the cases it covers",
                f"add {case} to that instance's `covers` (and its pinned `case_version_links`) "
                "through manifest_put.py — one test may prove several cases, but only the "
                "cases it names", f"unlinked-{instance}-{row.get('then')}"))

    # A clause that rests on a partition the manifest itself records as NOT covered, in a case
    # the manifest calls green. TC-012's Then 2 (P-warn) and Then 5 (P-selfref) read as proved.
    # The partitions in question are those of the rows a GREEN test of this case covers (a green with no partition
    # covers all of them): a partition a green test never claimed is the normal state of a case with several
    # instances, and a `contradicts_requirement` row is a red test's row, not a claim that nothing proved the clause
    # (HF2-3, K2). A row's slice is `acceptance.row_slice`; the partition spelling is `contract.partition_key`.
    import acceptance as AC
    cfg = C.case_config()
    greens = _green_tests(instances_of_case(manifest, case, cfg))
    uncovered = {C.partition_key(p) for u in C.manifest_unresolved(manifest)
                 if str(u.get("case") or "") == case and str(u.get("reason") or "") != CONTRADICTS
                 and _greens_in_slice(u, greens, case, cfg)
                 for p in AC._slice_values(u, C.UNRESOLVED_PARTITION_KEYS)} - {""}
    if uncovered:
        for number, clause in clauses:
            named = sorted({p for p in PARTITION_RE.findall(clause) if C.partition_key(p) in uncovered})
            if named:
                findings.append(_finding(
                    "bindings", case,
                    f"Then {number} of {case} rests on {', '.join(named)}, which unresolved[] "
                    f"records as not covered, while {case} is green",
                    "green cannot stand for a clause nothing proved: bind the clause to a test, "
                    "or record the clause itself (not only the partition) as unresolved",
                    f"uncovered-partition-{number}"))

    if not files:
        return
    corpus = "\n".join(f.text for f in files).lower()
    asserts = [(pyfile, node) for pyfile, _name, function in targets
               for node in _assert_nodes(function)]
    # A Then the person took (a remainder) is not asked for an assertion; one that IS asserted and contradicts the
    # clause still gets the `contradicted-*` findings below (E13)
    # The same for a Then behind a red assert of its own test (`blocked_by_check`, HF2-3): no assertion is owed for a
    # clause the test never reaches. Only the reasons of `THEN_REMAINDER_REASONS` grant it; a `contradicts_requirement`
    # row that names this Then (`thens`) does NOT - a red Then is asserted, and an assert that is missing is still
    # `no-assert` (N4: the red is not commented out until the owner answers FA-10).
    # HF2-5 (5a-K4, A2): the same for a Then whose ONLY rows are unresolved ones with a reason of the closed list
    # (`UNRESOLVED_REASONS`: the stand, a hand-off, a pending implementation, an unconfirmed value, a check ahead of it) or a
    # decided deferral (`deferred_by_decision:*`) - the clause is recorded as not checked, so no assertion is owed. NOT
    # `contradicts_requirement` (N4), NOT a reason outside the list (the unknown never becomes a pass, FR-59), and NOT a Then
    # that also has a covered row (a test claims it: its assertion is owed, A2 (c)).
    claimed = {C.then_number(b.get("then")) for b in bindings if str(b.get("status") or "covered") != "unresolved"}
    handed = {C.then_number(b.get("then")) for b in bindings
              if str(b.get("status") or "") == "unresolved" and C.unresolved_reason_ok(b.get("reason"))
              and b.get("reason") != CONTRADICTS} - claimed - {0}
    for number, clause in clauses:
        tokens = clause_tokens(clause)
        if tokens and number not in handed and not any(token.lower() in corpus for token in tokens):
            findings.append(_finding(
                "bindings", case,
                f"Then {number} of {case} has no assertion: none of the names it demands "
                f"({', '.join(tokens[:4])}) occurs anywhere in the test code of this case",
                "write the assertion, or record the clause in unresolved[] with the reason it "
                "cannot be checked — a Then nothing reads is not covered", f"no-assert-{number}"))
        for field in {m.group(1) for m in NULL_DEMAND_RE.finditer(clause)}:
            word = re.compile(r"\b" + re.escape(field) + r"\b")
            for pyfile, node in asserts:
                fragment = pyfile.source(node)
                if word.search(fragment) and NOT_NONE_RE.search(fragment):
                    findings.append(_finding(
                        "bindings", case,
                        f"Then {number} of {case} demands `{field}` be null/empty, and "
                        f"{pyfile.path.name}:{node.lineno} asserts it is NOT none — the test "
                        "contradicts the clause it claims to prove",
                        ORACLE_FIX, f"contradicted-{number}-{field}"))
                    break
        # The same contradiction in its two other detectable shapes: a status code the clause
        # fixes and the test does not assert anywhere, and a literal the clause fixes and the
        # test compares against a different one.
        demanded = clause_status_codes(clause)
        asserted = _asserted_status_codes(asserts)
        if demanded and asserted and not set(demanded) & set(asserted):
            findings.append(_finding(
                "bindings", case,
                f"Then {number} of {case} fixes status {'/'.join(demanded)}, and the tests of "
                f"this case assert only {', '.join(asserted)} — the test contradicts the clause "
                "it claims to prove",
                ORACLE_FIX, f"contradicted-status-{number}"))
        for field, literal in sorted({(m.group(1), m.group(2))
                                      for m in LITERAL_DEMAND_RE.finditer(clause)}):
            leaf = field.split(".")[-1]
            for pyfile, node in asserts:
                constants = _string_constants(_compared_values(node))
                if not constants or literal in constants or literal in pyfile.source(node):
                    continue
                if leaf not in _referenced_names(node):
                    continue
                findings.append(_finding(
                    "bindings", case,
                    f"Then {number} of {case} fixes `{field}` at {literal!r}, and "
                    f"{pyfile.path.name}:{node.lineno} compares it with {constants[0]!r} — the "
                    "test contradicts the clause it claims to prove",
                    ORACLE_FIX, f"contradicted-literal-{number}-{leaf}"))
                break


# Re-exports of the contract's constants (the string is spelled once, in `contract.py`). THEN_REMAINDER_WAITS is the one
# finding of this family that WAITS for a person's word instead of asking the author for a repair: no
# `WORDS_REFUSED_AT_SOURCE` line is printed for it, and only `then_handed_words` (identifier equality) satisfies it.
THEN_REMAINDER_TAG = C.THEN_REMAINDER_TAG
THEN_REMAINDER_WAITS = C.THEN_REMAINDER_WAITS
_OWNER_WORDS = {"person": "the person", "other_environment": "another environment"}


def _tag_number(value) -> str:
    """A Then number as it stands in a finding tag: digits for a clause number, `_`-safe text for anything else."""
    return re.sub(r"[^0-9A-Za-z_-]", "_", str(value))


def _blocker_state(blocker: str, manifest: dict, story: dict, red: dict, cfg) -> str:
    """What the manifest says about the check a Then is recorded behind: `""` when it is red here, `"unknown"` when no
    case and no test of the manifest is called `blocker`, `"not-red"` when something is but nothing red stands behind it.
    Red is the ONE reader's word (`red`, structural): a case is red when one of its `contradicts_requirement` rows
    reaches a red test (`acceptance.red_by_own_row`), a test when it is in `red`. Error direction: an unreadable
    manifest has no case and no test, so the Then is `unknown`, never blocked by something (FR-59)."""
    import acceptance as AC
    case_keys = [k for k in [*story, *(str(u.get("case") or "") for u in C.manifest_unresolved(manifest))] if k]
    tests = [t for t in C.manifest_tests(manifest) if blocker in C.instance_id_aliases(t, cfg)]
    is_case = any(C.case_matches(blocker, key, cfg=cfg) for key in case_keys)
    if not is_case and not tests:
        return "unknown"
    if is_case and any(AC.red_by_own_row(red, iid, blocker, cfg) for iid in red):
        return ""
    return "" if any(C.test_instance_id(t) in red for t in tests) else "not-red"


def _check_blocked_then(case: str, row: dict, numbers: list, covered_rows: list, groups: list, blocker_state, road: str,
                        seen: set, findings: list, ran=lambda instance: frozenset()) -> None:
    """One `blocked_by_check` row of `then_bindings` (a Then behind a red assert of its own test): at most one finding,
    the first problem in this order - the shape (`contract.then_remainder_errors`), the Then (the case file states it),
    the same-instance conflict, the blocker (it exists, it is red). A well-formed row of a red blocker is valid and asks
    nobody for a word: it is a fact read off a red, not a person's decision. Every door names the fragment road (the
    road a row written by hand has, whoever wrote it). `groups` are the alias sets of the case's tests, `covered_rows` its covered
    `then_bindings`, `blocker_state` answers `_blocker_state` for a name."""
    then = row.get("then")
    tag = _tag_number(then)
    door_ = f"send the corrected `then_bindings` rows of {case} through `{road}`"
    errors = C.then_remainder_errors(row)
    if errors:
        findings.append(_finding(
            "bindings", case,
            f"the row of {case} that records Then {then!r} as behind a red check is malformed: " + "; ".join(errors),
            f"rewrite the row as {{case, then, instance_id, status: unresolved, reason: {BLOCKED_BY_CHECK}, blocking_check, "
            f"detail}} and {door_}", f"{THEN_REMAINDER_TAG}shape-{tag}"))
        return
    instance = row.get("instance_id") or ""
    if (then, instance) in seen:
        return
    seen.add((then, instance))
    if not numbers:
        findings.append(_finding(
            "bindings", case,
            f"Then {then} of {case} is recorded behind a red check, but the case file was not found (or states no "
            "Then), so the Then cannot be checked",
            f"make the case file {case}.md readable under the story's test-cases folder, or correct `case` in the row, "
            f"and {door_}", f"{THEN_REMAINDER_TAG}unknown-{tag}"))
        return
    if then not in numbers:
        findings.append(_finding(
            "bindings", case,
            f"Then {then} is not a Then of {case} (its Thens are numbered {', '.join(map(str, numbers))})",
            f"correct `then` in the row to the number of the clause the red stops, and {door_}",
            f"{THEN_REMAINDER_TAG}unknown-{tag}"))
        return
    blocker = str(row.get("blocking_check") or "").strip()
    # A Then that RAN and failed (it is a red Then of the case's own `contradicts_requirement` row on this very
    # instance) is not behind any check. This sits before the same-instance conflict: a red Then is `covered` by
    # construction (`acceptance.red_by_requirement`), so the conflict would always answer first and say the less
    # useful thing. The shape and the Then's existence above still refuse first.
    if instance and then in ran(instance):
        findings.append(_finding(
            "bindings", case,
            f"Then {then} of {case} ran and failed on {instance}; it is not behind a check",
            f"drop the `{BLOCKED_BY_CHECK}` row of Then {then} on {instance} (a Then that failed is the row "
            f"`{CONTRADICTS}` with `thens: [{then}]`), and {door_}", f"blocked-check-ran-{tag}"))
        return

    def same_test(other: str) -> bool:
        return other == instance or any(instance in g and other in g for g in groups)

    if instance and any(C.then_number(b.get("then")) == then and same_test(str(b.get("instance_id") or ""))
                        for b in covered_rows):
        findings.append(_finding(
            "bindings", case,
            f"Then {then} of {case} is both proved by {instance} and recorded on {instance} as behind {blocker}",
            f"a Then on one test either reached its check or did not: drop the covered row or the blocked row of Then "
            f"{then} on {instance}, and {door_}", f"{THEN_REMAINDER_TAG}conflict-{tag}"))
        return
    state = blocker_state(blocker)
    if state == "unknown":
        findings.append(_finding(
            "bindings", case,
            f"Then {then} of {case} is recorded behind {blocker}, and no case or test of this manifest is called that",
            f"correct `blocking_check` to the case key or the instance id of the red check and {door_}",
            f"blocked-check-unknown-{tag}"))
    elif state:
        findings.append(_finding(
            "bindings", case,
            f"Then {then} of {case} is recorded behind {blocker}, which is not red here",
            f"bind Then {then} to the test that now reaches it, or record it as `{BLOCKED_BY_ENV}` if a stand stopped it; "
            f"{door_}", f"blocked-check-not-red-{tag}"))


def check_then_remainders(task_root: Path, manifest: dict, cases: list, texts: dict, findings: list,
                          notes: list) -> None:
    """A Then left with its owner (GW1-14) passes S5 beside the case's green test only as an INFORMED pass: the Then
    is a clause of the case, no test proves it, the shape is whole, and the person's word for exactly that Then is
    recorded (`then handed: <case>#<n>`, `contract.then_handed_words`, joined by identifier). One finding per
    (case, Then, problem), family `bindings`, level `repair`; the unrecorded one is the only one a word answers.

    Invariants: nothing here passes on an unknown (no case file, no such Then, an unreadable `pipeline.json` all
    refuse: FR-59); no stage-override substring can remove these findings (the family is not in `PASSABLE`); a case
    with a whole-case `unresolved[]` row is not judged here (`contract.then_remainder_rows`).

    A Then behind a red assert of its own test (`blocked_by_check`, HF2-3) is judged by the same function and needs NO
    word of a person: it is a fact the factory reads off a red. It must be well formed (`contract.then_remainder_errors`),
    be a Then of the case, not be proved by a covered row of the SAME instance (`then-remainder-conflict-`; a covered row
    of another instance is the normal state of a Then proved twice), and name a blocker that exists
    (`blocked-check-unknown-`) and is red (`blocked-check-not-red-`: a case with a `contradicts_requirement` row that
    reaches a red test, or a test red by a row). Its doors name the fragment road, not the marker. The whole-case rule
    (`then-remainder-all`) counts the Thens left with their owner only."""
    import acceptance as AC
    from functools import partial
    cfg = C.case_config()
    rows = C.then_remainder_rows(manifest, cfg, C.THEN_REMAINDER_REASONS)
    if not rows:
        return
    road = _road(task_root.name)
    story = AC.story_scope(manifest, cfg)
    red = AC.red_by_requirement(manifest, [{"instance_id": i} for ids in story.values() for i in ids], story,
                                strict=False)
    blocker_state = partial(_blocker_state, manifest=manifest, story=story, red=red, cfg=cfg)
    pipeline = _load(task_root / "pipeline.json")
    words = C.then_handed_words(pipeline)
    by_case: dict = {}
    for row in rows:
        case = next((c for c in cases if C.case_matches(str(row.get("case") or ""), c, cfg=cfg)), None)
        if case is None:
            notes.append(f"{row.get('case')}: a Then left with its owner is recorded for a case outside this "
                         "check's scope; only the dispatch that owns the case can repair or confirm it")
            continue
        by_case.setdefault(case, []).append(row)
    for case, case_rows in by_case.items():
        text = texts.get(case) or ""
        numbers = C.case_then_numbers(task_root, case, text)   # THE one reader of a case's Then numbers (R6, t-1508)
        covered_rows = [b for b in bindings_of_case(manifest, case, cfg) if str(b.get("status") or "covered") == "covered"]
        covered = {C.then_number(b.get("then")) for b in covered_rows}
        groups = [set(C.instance_id_aliases(t, cfg)) for t in instances_of_case(manifest, case, cfg)]
        seen: set = set()
        valid: list = []

        def ran(instance: str, case=case, groups=groups) -> set:
            """The Thens the case's OWN red rows name on the test `instance` (any alias) stands for."""
            said: set = set()
            for iid, red_rows in red.items():
                if iid == instance or any(instance in g and iid in g for g in groups):
                    for r in red_rows:
                        if isinstance(r, dict) and str(r.get("case") or "").strip() \
                                and C.case_matches(str(r["case"]).strip(), case, cfg=cfg):
                            said |= set(_row_thens(r))
            return said

        for row in case_rows:
            then = row.get("then")
            tag = _tag_number(then)
            if row.get("reason") == BLOCKED_BY_CHECK:
                _check_blocked_then(case, row, numbers, covered_rows, groups, blocker_state, road, seen, findings, ran)
                continue
            errors = C.then_remainder_errors(row)
            if errors:
                findings.append(_finding(
                    "bindings", case,
                    f"the row of {case} that leaves Then {then!r} with its owner is malformed: " + "; ".join(errors),
                    "rewrite the marker `qa_unresolved(case=, then=[n], reason=\"handed_to_person\", owner=, part=, "
                    "detail=<steps>)` and re-run manifest_from_tests.py", f"{THEN_REMAINDER_TAG}shape-{tag}"))
                continue
            if then in seen:
                continue
            seen.add(then)
            if not numbers:
                findings.append(_finding(
                    "bindings", case,
                    f"Then {then} of {case} is left with its owner, but the case file was not found (or states "
                    "no Then), so the Then cannot be checked",
                    f"make the case file {case}.md readable under the story's test-cases folder, or correct `case` "
                    "in the row; a Then that cannot be found is not left with anybody",
                    f"{THEN_REMAINDER_TAG}unknown-{tag}"))
                continue
            if then not in numbers:
                findings.append(_finding(
                    "bindings", case,
                    f"Then {then} is not a Then of {case} (its Thens are numbered {', '.join(map(str, numbers))})",
                    "correct `then` in the marker to the number of the clause the owner takes, and re-run "
                    "manifest_from_tests.py", f"{THEN_REMAINDER_TAG}unknown-{tag}"))
                continue
            valid.append(row)
            owner = row.get("owner") if row.get("owner") in C.THEN_REMAINDER_OWNERS else C.THEN_REMAINDER_DEFAULT_OWNER
            if then in covered:
                findings.append(_finding(
                    "bindings", case,
                    f"Then {then} of {case} is both proved by a test and left with {_OWNER_WORDS[owner]}",
                    f"a Then is proved by a test or left with its owner, never both: drop the covered binding of "
                    f"Then {then} (name what the owner checks with `part=`), or bind the Then and drop the remainder",
                    f"{THEN_REMAINDER_TAG}conflict-{tag}"))
                continue
            word = words.get((str(row.get("case") or "").strip(), then))
            if word is None:
                block = f"{C.THEN_HANDED_MATCH_PREFIX} {str(row.get('case') or '').strip()}#{then}"
                findings.append(_finding(
                    "bindings", case,
                    f"Then {then} of {case} is left with {_OWNER_WORDS[owner]} and no word of the person's is "
                    "recorded for it",
                    "A role does not record anybody's word: return this item in your digest. The orchestrator asks "
                    "the person (or re-records words they already gave for this Then, without asking again) with `"
                    + door(f"waiver.py --task {task_root.name} --stage S5 --block \"{block}\"") + "`",
                    f"{THEN_REMAINDER_WAITS}{tag}"))
                continue
            notes.append(f"{case} Then {then} is left with {_OWNER_WORDS[owner]} by the person's word: "
                         f"{word['words']}")
        if numbers and valid and {r["then"] for r in valid} >= set(numbers):
            findings.append(_finding(
                "bindings", case,
                f"no Then of {case} is proved by a test: every one is left with its owner, which is a whole-case hand-off",
                "move the case to unresolved[] with `handed_to_person` (the whole case: s5.md \"A test I cannot run at "
                "all\"); green never stands for a case none of whose Thens it proves", THEN_REMAINDER_TAG + "all"))


def _asserting_rows(manifest: dict, case: str) -> dict:
    """{Then number: [the `then_bindings` rows of this case that CLAIM a proof of it]}: a row that is not `unresolved` and
    names an instance. `assertion_ref` is not asked (F-4): dropping it must not be a way around the gate."""
    out: dict = {}
    for row in bindings_of_case(manifest, case):
        number = C.then_number(row.get("then"))
        if number and str(row.get("status") or "covered") != "unresolved" and row.get("instance_id"):
            out.setdefault(number, []).append(row)
    return out


def _open_oracle_door(case: str, number: int, ref: str, task_name: str, door_a: bool) -> str:
    """The repair line of `open-oracle-asserted`: ONE door the author can use (FR-2). Door A: the question is in the
    register, so the Then is bound `expectation_unconfirmed` and a person settles it by answering it. Door B: the case
    names no question the register holds (an invented word, a missing or unknown ref), which is the CASE's defect (FR-46):
    the one route is back to S4, because `question_register.py --raise` alone refuses a Then that already has an oracle
    word and does not rewrite the approved case's `then_oracles`."""
    if door_a:
        return (f"do not assert a value for Then {number}: bind it with `@pytest.mark.qa_unresolved(case=\"{case}\", "
                f"then=[{number}], reason=\"expectation_unconfirmed\", question=\"{ref}\", observed=<what the test saw>)`, "
                f"keep an assert only for the part a source establishes (bound with `qa(then=[{number}])`; a status range "
                f"keeps `# oracle_unknown: {ref}` on its line), and re-run manifest_from_tests.py. A person settles it only "
                f"by answering {ref} with a reading letter, recorded by the orchestrator: `"
                + door(f"question_register.py --task {task_name} --answer {ref} --reading <letter> --where conductor "
                       "--by conductor --register-hash <row_hash>") + "`; no waiver passes this finding")
    return (f"remove the literal for Then {number} from the test and return this item in your digest: the case names no "
            f"question the register holds for it, so the case goes back to S4 - the case designer raises the question "
            f"(`question_register.py --raise`) and rewrites Then {number} as `unknown` with that id in `then_oracles`; "
            "no waiver passes this finding")


def check_open_oracle_asserted(task_root: Path, case: str, text: str, manifest: dict, findings: list, notes: list,
                               questions: dict) -> None:
    """A Then whose expected value nobody confirmed that a test asserts anyway (684-P3, TQ1-1).

    The state of each Then is read ONLY through `traceability.then_oracle_states` (THE resolver, AR-13): `open` or
    `invalid` - or no readable state at all - is an expected value nobody confirmed. The finding fires when the manifest
    binds that Then to an instance as proved, unless the same Then carries an `expectation_unconfirmed` row
    (`ledger.unconfirmed_bindings`), the declared open part; a Then whose established part is split off into its own Then
    is a settled Then and is never touched. The error direction is toward FIRING (the resolver errs to `open`, an unreadable
    entry is `missing`): a false fire costs one repair round, a false silence ships an invented expectation. A Then with no
    bound instance is silent (`check_bindings` owns "unbound"); a case with no `then_oracles` line is one note (the code
    critic reads it, 1d); no word and no judge removes the finding (family `oracle`, `NEVER_JUDGED_TAGS`).

    Known blind spot (F-6): a test that binds Then n `expectation_unconfirmed` and still asserts a literal in its code is
    invisible here - this gate reads bindings, not code; the code critic's 1d (`invented_expectation`) owns that."""
    numbers = [n for n, _clause in then_clauses(text)]
    if not numbers:
        return
    entries, problem = C.then_oracles_from_text(text)  # the presence test only: the states come from the one reader below
    if entries is None and not problem:
        notes.append(f"{case}: no then_oracles line; the open-oracle check had no oracle to read for its Then clauses "
                     "(the code critic reads them, 1d)")
        return
    import ledger as L
    import traceability as T
    states: dict = {}
    for state in T.then_oracle_states(text, questions):
        number = C.then_number(state.get("then"))
        if number and (number not in states or states[number].get("state") == "settled"):
            states[number] = state  # two entries for one Then: the one that is not settled wins
    declared = {C.then_number(row.get("then")) for row in L.unconfirmed_bindings(manifest, case)}
    asserting = _asserting_rows(manifest, case)
    for number in numbers:
        state = states.get(number)
        if number in declared or number not in asserting or (state and state.get("state") == "settled"):
            continue
        proof = ", ".join(f"{r.get('instance_id')} ({r.get('assertion_ref') or 'assertion line not named'})"
                          for r in asserting[number])
        ref = str((state or {}).get("ref") or "")
        if state is None:
            why = (f"the case's then_oracles line cannot be read ({problem})" if problem
                   else f"its then_oracles line has no entry for Then {number}")
        elif state.get("state") == "invalid":
            why = f"its oracle `{state.get('source')}` ({ref or 'no ref'}) is not an oracle word"
        else:
            why = f"its oracle is `unknown` ({ref or 'no ref'}): {state.get('why')}"
        door_a = bool(state) and state.get("state") == "open" and ref in questions
        findings.append(_finding(
            "oracle", case,
            f"Then {number} of {case} has no confirmed expected value ({why}), yet the manifest binds it to {proof} as proved",
            _open_oracle_door(case, number, ref, task_root.name, door_a), f"{OPEN_ORACLE_ASSERTED}-{number}"))


def _pair_tag(pair: dict, kind: str = "") -> str:
    """The finding tag of one pair. It starts with `changed-after-red`, which is what a person's
    word matches (`waiver.py --stage S5 --block "changed-after-red"` passes every pair,
    `--block "changed-after-red-<function>"` one), and it is unique per pair so that two pairs
    never collapse into one finding."""
    return "-".join(part for part in (CHANGED_AFTER_RED, kind, pair["function"],
                                      str(pair["red_attempt"])[:12],
                                      str(pair["green_attempt"] or "gone")[:12]) if part)


def _then_ref_problems(task_root: Path, record: dict, cases: list) -> list:
    """Why the record's `then_refs` do not resolve: no ref at all, a case outside this
    check's scope, or a Then number the case file does not have. Structure only (FR-12): whether
    the Then really covers the changed value is the critic's reading."""
    refs = record.get("then_refs")
    if not isinstance(refs, list) or not refs:
        return ["`then_refs` is empty or missing — name the Then the changed value belongs to"]
    cfg = C.case_config(task_root)
    problems: list = []
    for ref in refs:
        if not isinstance(ref, dict):
            problems.append(f"`then_refs` entry {ref!r} is not an object {{\"case\", \"then\"}}")
            continue
        case, then = str(ref.get("case") or ""), ref.get("then")
        if not any(C.case_matches(case, wanted, cfg=cfg) for wanted in cases):
            problems.append(f"{case or 'a ref with no case'} is not a case of this check's scope "
                            f"({', '.join(cases[:6])})")
            continue
        path = _case_file_of(task_root, case, cfg)
        numbers = {n for n, _t in then_clauses(path.read_text(encoding="utf-8", errors="replace"))} \
            if path else set()
        if isinstance(then, bool) or not isinstance(then, int) or then not in numbers:
            number = C.split_case_key(case, cfg=cfg)[1]
            problems.append(f"{case} has no Then {then!r}" + (
                f" (its Then clauses are numbered {sorted(numbers)})" if numbers
                else " (no case file with numbered Then clauses was found; looked for "
                     f"{number}.md and {number}-*.md under: "
                     + ", ".join(str(r) for r in case_search_roots(task_root)) + ")"))
    return problems


def check_expectation_changes(task_root: Path, changes: dict, cases: list, findings: list,
                              notes: list) -> None:
    """One finding per OWED pair with no record, one per record whose `then_refs` do not
    resolve — independent of the oracle checks of the case loop, so an open oracle can never swallow it.

    The exit is a record: `manifest_put.py --fragment` with the function and the attempts
    already filled in, or restoring the Then's value and handing the test RED with
    `contradicts_requirement` (FR-34). Neither exit is `work/triage.json`, which the automator
    cannot write (FR-2). A person's word passes the finding by its tag (`passed_by_word`)."""
    pairs = changes.get("pairs") or []
    groups: dict = {}
    for pair in pairs:
        if pair["owed"] and pair["record"] is None:
            groups.setdefault((pair["red_attempt"], pair["green_attempt"]), []).append(pair["function"])
    for pair in pairs:
        label = pair["cases"][0] if pair["cases"] else ""
        where = next((c for c in pair["cases"] if any(C.case_matches(c, w) for w in cases)), label)
        if not pair["owed"]:
            notes.append(f"{where or 'a test'}: {pair['function']} went red in {pair['red_attempt']} and "
                         f"{'passed in ' + str(pair['green_attempt']) if not pair['orphan'] else 'is gone'} "
                         "on changed code — listed, nothing is owed at S5 for it")
            continue
        record = pair["record"]
        if record is not None:
            verdict = str(record.get("critic_verdict") or "").strip()
            notes.append(f"{where}: {pair['function']} changed after its red run "
                         f"({pair['red_attempt']}) — recorded in expectation_changes[], "
                         + (f"the critic's verdict is {verdict}" if verdict else "not judged yet"))
            problems = _then_ref_problems(task_root, record, cases)
            if problems:
                findings.append(_finding(
                    "oracle", where,
                    f"the expectation_changes[] record for {pair['function']} "
                    f"(red {pair['red_attempt']}, green {pair['green_attempt']}) has `then_refs` "
                    "that do not resolve: " + "; ".join(problems),
                    _record_fix(task_root, pair, groups, "refs"), _pair_tag(pair, "refs")))
            continue
        if pair["orphan"]:
            message = (f"{pair['function']} went red in {pair['red_attempt']} "
                       f"({pair['red_status']}) and no test of that name exists any more — "
                       "renamed, moved or deleted — and nothing records where its expectation went")
        else:
            reason = ("its code changed" if pair["sha_basis"] != "unknown" else
                      "no sha of it could be compared, so a change cannot be ruled out")
            message = (f"{pair['function']} went red in {pair['red_attempt']} ({pair['red_status']}) "
                       f"and passed in {pair['green_attempt']}, and {reason} in between "
                       f"({pair['sha_basis']} sha) — nothing records what was changed or why"
                       + (f" [{pair['note']}]" if pair["note"] else ""))
        message += f"; the red run's own report is {pair['red_evidence']}" if pair["red_evidence"] else ""
        findings.append(_finding("oracle", where, message, _record_fix(task_root, pair, groups),
                                 _pair_tag(pair)))
        pair["finding_id"] = findings[-1]["id"]
        findings[-1]["pair_at"] = pair.get("pair_at", "")  # read by `passed_by_word`: a broad word covers what existed
    for why in changes.get("unmeasured") or []:
        notes.append("expectation changes not measured: " + why)


def _record_fix(task_root: Path, pair: dict, groups: dict, kind: str = "") -> str:
    """The way on for one pair: the record to write (inline and as a file), the other author door,
    the person's word (for this pair, and for every pair of the stage)."""
    same = groups.get((pair["red_attempt"], pair["green_attempt"])) or [pair["function"]]
    row: dict = ({"functions": same} if len(same) > 1 else {"function": pair["function"]})
    row.update({"red_attempt": pair["red_attempt"], "green_attempt": pair["green_attempt"],
                "then_refs": [{"case": (pair["cases"] or ["<case>"])[0], "then": "<the Then number>"}],
                "what_changed": "<what you changed in the test, before -> after>",
                "reason": "<why the approved case allows it>"})
    fragment = json.dumps({"expectation_changes": [row]}, ensure_ascii=False)
    task = task_root.name
    # The word names THIS pair's own tag: a word given for one pair passes that pair only (the
    # stage-wide `changed-after-red` stays, printed as the broad form). The function key alone is
    # no pair's own tag - `test_a` is inside `test_ab`, and one function can have two pairs.
    own = _pair_tag(pair, kind)
    return (f"record it: `manifest_put.py --task {task} --fragment '{fragment}'` — the function and "
            "the attempts are filled in; or put the same JSON in a file and run "
            f"`manifest_put.py --task {task} --fragment <path to that file>` (PowerShell 5.1 strips the "
            "inner quotes of the inline form, so the file form is the safe one there). Name the Then it "
            "concerns (`then_refs`), what you changed and why the approved case allows it"
            + (f" (one record covers all {len(same)} functions of this pair of runs)" if len(same) > 1 else "")
            + ". A value the Then FIXES is never changed to make a test pass: the other exit is to "
            "restore that value and hand the test over RED with `" + CONTRADICTS + "` (FR-34). "
            "If a person decided the test may stand as it is, the orchestrator records it with "
            "`" + door(f"waiver.py --task {task} --stage S5 --block \"{own}\"") + "` (this pair only; "
            "`--block \"" + CHANGED_AFTER_RED + "\"` passes every such "
            "pair of the stage that already had its green run when the word was given); the pair stays "
            "on the critic's list and in the report")


def check_case_is_oracle(manifest: dict, cases: list, findings: list) -> None:
    """A `deferred_by_decision:*` row that argues with the approved case's own expectation.

    S5 is dispatched only after gate A, so every case in its scope is approved, and an
    approved case is the oracle: "the case is wrong" is not a route out of S5. It is a
    triage question, and it reaches triage only by travelling WITH the red test.

    The row says what it disputes, in its `disputes` field (`C.UNRESOLVED_DISPUTES`), and a row
    that does not say is asked to — because a deferral is often legitimate and the two cannot be
    told apart from the prose. `P-mcp: expected status not derivable from the register or diff,
    the owner must supply the access-control contract` is `derivation` and is left alone."""
    for entry in C.manifest_unresolved(manifest):
        case = str(entry.get("case") or "")
        reason = str(entry.get("reason") or "")
        if case not in cases or not C.unresolved_decided(reason):
            continue
        detail = " ".join(str(entry.get("detail") or "").split())
        disputes = str(entry.get("disputes") or "").strip().lower()
        if disputes not in C.UNRESOLVED_DISPUTES:
            findings.append(_finding(
                "oracle", case,
                f"{case} is unresolved with `{reason}` and the row does not say what it disputes"
                + (f" (\"{detail[:120]}\")" if detail else "")
                + f" — `disputes` is one of {list(C.UNRESOLVED_DISPUTES)}"
                + (f", and `{disputes}` is not" if disputes else ""),
                "say it in the row: `manifest_put.py --task <T> --fragment "
                "'{\"unresolved\": [{\"case\": \"" + case + "\", \"reason\": \"" + reason + "\", "
                "\"disputes\": \"derivation\"}]}'` — `derivation` when the expected value cannot "
                "be derived at all, `nothing` when the deferral is about a stand or a dependency, "
                "`case_expectation` when you disagree with the approved case, which after gate A "
                "is not a route out of S5",
                "dispute-unstated"))
            continue
        if disputes != "case_expectation":
            continue
        findings.append(_finding(
            "oracle", case,
            f"{case} is unresolved with `{reason}` and the row says it disputes the case's own "
            f"expectation (\"{detail[:140]}\") — after gate A the approved case is the oracle "
            "for S5, and this role has no \"the case is wrong\" route: only `"
            + CONTRADICTS + "` or `impossible`",
            ORACLE_FIX, "case-is-oracle"))


def _why_no_row(entry: dict, rows: list) -> str:
    """WHY no run of this instance is recognised — which run was read and what did not match.

    `no run block carries a result row for X` is a verdict with no diagnosis: it does not say
    whether the run is missing, the id is spelled differently or only the reporter mapping is
    absent. On TP1-15045 the cheapest answer to it was to run pytest again, twenty times
    for four cases, for rows that were already on disk under another spelling."""
    iid = C.test_instance_id(entry)
    function = C.function_name(iid)
    if not rows:
        return "no run block has been written for this story yet"
    near = [r for r in rows if function
            and C.function_name(str(r.get("instance_id") or "")) == function]
    if near:
        spellings = sorted({str(r.get("instance_id") or "") for r in near})[:3]
        return (f"{near[-1].get('block')} carries {', '.join(spellings)} for the same test "
                f"function — the id spelling differs from {iid!r}, the run itself is there")
    reported = [r for r in rows if function
                and function in str(r.get("test_id") or r.get("report_test_id") or "")]
    if reported:
        named = str(reported[-1].get("test_id") or reported[-1].get("report_test_id") or "")
        return (f"{reported[-1].get('block')} has the reporter row {named!r} and nothing maps "
                f"it to {iid!r} — the mapping is missing, not the run")
    blocks = sorted({str(r.get("block") or "") for r in rows})
    shas = sorted({str(r.get("test_content_sha") or "")[:7] for r in rows
                   if r.get("test_content_sha")})
    return (f"{len(rows)} result row(s) in {len(blocks)} block(s) ({', '.join(blocks[-2:])}) and "
            f"none of them names this instance under any spelling"
            + (f"; those blocks ran test bytes {', '.join(shas[:3])}" if shas else ""))


def check_run_mapping(case: str, entries: list, targets: list, rows: list, findings: list,
                      handed: bool = False, blocked=(), pending=()) -> None:
    if handed:
        return  # nothing ran it here and nothing was supposed to: the person runs it
    by_instance: dict = {}
    for row in rows:
        by_instance.setdefault(str(row.get("instance_id") or ""), []).append(row)
    cfg = C.case_config()
    for entry in entries:
        iid = C.test_instance_id(entry)
        if iid in pending:
            # The side this test touches does not exist yet (t-2181 PC-4, C5, `acceptance.pending_instances`): it is written and
            # collected, never run, so no reporter row is owed. The excuse is the run mapping's ONLY: `check_sides` still
            # judges the test's declaration and its provisional rows (C1-C4), and a test not named by the reader runs.
            continue
        if iid in blocked:
            # The stand blocked this one (t-219, `acceptance.blocked_instances`): the manifest says no run
            # reached a verdict, and a run block that holds a red row of it - or none - is what that looks like.
            # Asking for a reporter row would send the automator to run it again on the same stand.
            continue
        # Any spelling of this instance answers: a run block written before 0.7.7 names the
        # test `TC-012::test_x`, one written by 0.7.4 names its selector hash, and a manifest
        # row merged today names it bare. Reading only today's spelling would report a test
        # that demonstrably ran as having no reporter row at all.
        series = next((by_instance[alias] for alias in C.instance_id_aliases(entry, cfg)
                       if by_instance.get(alias)), [])
        if not series:
            why = _why_no_row(entry, rows)
            findings.append(_finding(
                "run_mapping", case, f"no run block carries a result row for {iid} — {why}",
                ("`run_suite.py --task <TICKET> --reparse-block <block> --mapping "
                 "<instance->report_test_id JSON>` — the run named above happened, only the row "
                 "is unmapped; a rerun adds nothing"
                 if ("spelling differs" in why or "mapping is missing" in why) else
                 "run the instance once, or — if it did run and only the reporter row is "
                 "missing — `run_suite.py --task <TICKET> --reparse-block <block> --mapping "
                 "<json>`; a rerun does not add a missing row"), f"no-row-{iid}"))
            continue
        last = series[-1]
        if last.get("report_matched") is False or str(last.get("status")) == "not_run":
            findings.append(_finding(
                "run_mapping", case,
                f"{iid}: the newest run block says {str(last.get('status'))!r} "
                f"({last.get('reason') or 'no reporter row'}) while the manifest claims it",
                # Both flags, in the order run_suite.py demands them: printing the command
                # without --task made the one sanctioned remedy error out (0.7.7 review).
                "`run_suite.py --task <TICKET> --reparse-block " + str(last.get("block"))
                + " --mapping <instance->report_test_id JSON>` — the run happened; the "
                "mapping is what is missing, so a rerun buys nothing", f"unmatched-{iid}"))

    # There used to be a "this case covers N test functions but tests[] carries M instances"
    # finding here. It counted METHODS PER CASE, so the one shape 0.7.7 wants — one
    # parametrized test proving TC-003/004/005 — was reported as a defect, and the cheapest
    # way to silence it was to write one test per case. What matters is that every Then
    # clause and partition of the case is bound to an instance that covers it, which
    # `check_bindings` checks, and that every instance has a reporter row, which is above.


# --- the sides of the story (t-2181 PC-4, C1-C6) ------------------------------------------------------------------------
# DATA ONLY (AR-29): shape and cross-references of what the automator wrote - `tests[].sides`, `then_bindings[].about`,
# `provisional[]`, the `pending_implementation` rows - against the ONE sides reader (`contract.story_sides`, handed in) and
# the run blocks. Whether a placeholder is reasonable, a Then really speaks about a side, or the run "reached past the
# locator" is the code critic's judgment and is read nowhere here.
PROVISIONAL_KINDS_PATH = C.PROVISIONAL_KINDS_PATH   # read through `C.provisional_kinds()`, the one reader; the path is only named in a refusal
# The marker of ANY row (`contract.provisional_marker_re` builds the one of a given id and is what the hash uses; this one
# only lists the ids a file carries, for C4).
ANY_MARKER_RE = re.compile(r"qa-provisional:\s*(P-\d+)(?![\w-])")
SETTLED_STATUSES = C.PROVISIONAL_SETTLED      # the ONE tuple, in `contract` (the ledger reads it too, AR-13)


def _stamp_is_real(block: dict, side: str, plain: bool) -> bool:
    """Did the execution `block` record `side` as `real`? A block with no stamp recorded no non-real side, which reads as
    real ONLY when the story's sides are all real and `sides_unknown` is not set (`plain`, C6 b); a block that carries
    `sides_unknown`, or a stamp that does not say `real` for the side, is not."""
    if not isinstance(block, dict) or block.get("sides_unknown"):
        return False
    met = block.get("sides_met")
    if isinstance(met, dict):
        return met.get(side) == "real"
    return plain


def _scope_has(ctx, case: str) -> bool:
    """Is `case` one of the cases of the window this check was asked about? With no scope every case is (the whole-story read)."""
    return ctx.scope_cases is None or any(C.case_matches(str(case or ""), c, cfg=ctx.cfg) for c in ctx.scope_cases)


def _row_in_scope(ctx, row: dict) -> bool:
    """A provisional row belongs to a window when one of its `dependents` is a case of it. A row with no readable dependent in any
    case belongs to EVERY window: fail-closed, a row nobody owns is never skipped (B5)."""
    deps = row.get("dependents")
    cases = ([str(d.get("case") or "") for d in deps if isinstance(d, dict) and str(d.get("case") or "").strip()]
             if isinstance(deps, list) else [])
    return not cases or any(_scope_has(ctx, c) for c in cases)


def _run_blocks(ctx) -> list:
    """The story's run blocks, read once per check."""
    if ctx.blocks is None:
        ctx.blocks = read_run_blocks(ctx.task_root)[0]
    return ctx.blocks


def _latest_runs(ctx) -> dict:
    """`{instance_id: (status, block data)}`: the LATEST row of each instance over the story's run blocks, whatever its status
    (`contract.result_status`'s words); a collect-only block is no run and is skipped. ONE rule for a later non-terminal row: it wins
    (a `skipped` after a `failed` leaves the instance with no terminal run - the safe direction for J-C9 (d) and for C5 alike).
    A status is terminal when it is in `contract.TERMINAL_RESULT_STATUSES`."""
    latest: dict = {}
    for item in _run_blocks(ctx):
        data = item["data"]
        if str(data.get("kind") or "") == "collect":
            continue
        for result in data.get("results") or []:
            if isinstance(result, dict):
                latest[str(result.get("instance_id") or "")] = (C.result_status(result), data)
    return latest


def _sides_declared(ctx) -> None:
    """C1 / C2: what every test of the window declares about its sides, and what its Thens say they are about."""
    add, sides, names, non_real = ctx.add, ctx.sides, ctx.names, ctx.non_real
    for entry in ctx.tests:
        iid = C.test_instance_id(entry)
        if not iid:
            continue
        case = str(entry.get("case") or "")
        declared = entry.get("sides")
        if non_real and declared is None:
            add(case, f"{iid}: the story has a side that is not real ({', '.join(non_real)}) and this test declares no `sides`",
                "send `sides` for the test through `manifest_put.py --fragment` - `{side: real|substituted|absent}` for every side "
                "it touches, `{}` when it touches none (an empty declaration is read conservatively, never as proof)",
                f"{SIDES_UNDECLARED}-{iid}")
        elif declared is not None and not isinstance(declared, dict):
            add(case, f"{iid}: `sides` is {type(declared).__name__}, not an object of side -> reality",
                "send `sides` as `{side: real|substituted|absent}`", f"sides-shape-{iid}")
        elif isinstance(declared, dict):
            for name in sorted(str(n) for n in declared if str(n) not in sides):
                add(case, f"{iid}: `sides` names {name!r}, which is not a side of this story (its sides: {names})",
                    "use a side name exactly as the story records it (case and spelling), or drop the key", f"sides-name-{iid}-{name}")
    for row in ctx.manifest.get("then_bindings") or []:
        if not isinstance(row, dict) or row.get("about") is None or not _scope_has(ctx, row.get("case")):
            continue
        case, about = str(row.get("case") or ""), row.get("about")
        label = f"Then {row.get('then')} of {case or '-'}"
        if not isinstance(about, list):
            add(case, f"{label}: `about` is {type(about).__name__}, not a list of sides", "send `about` as `[<side>, ...]`",
                f"about-shape-{case}-{row.get('then')}")
            continue
        for name in sorted({str(n) for n in about if str(n) not in sides}):
            add(case, f"{label}: `about` names {name!r}, which is not a side of this story (its sides: {names})",
                "use a side name exactly as the story records it, or drop it from `about`",
                f"about-name-{case}-{row.get('then')}-{name}")


def _sides_provisional(ctx) -> None:
    """C3 / C4: the provisional rows of the window and the markers in its test files."""
    add, sides, names, cfg = ctx.add, ctx.sides, ctx.names, ctx.cfg
    for sentence in ctx.prov["skipped"]:
        add("", f"provisional registry: {sentence}", "repair the row or field through `manifest_put.py --fragment`",
            "provisional-unreadable-" + hashlib.sha256(sentence.encode("utf-8")).hexdigest()[:8])
    kinds = C.provisional_kinds()
    kinds = None if kinds is None else set(kinds)
    bound = [(str(b.get("case") or ""), C.then_number(b.get("then")))
             for b in ctx.manifest.get("then_bindings") or [] if isinstance(b, dict)]
    for row in ctx.rows_here:
        pid = str(row.get("id"))
        if str(row.get("status") or "") == "retracted":
            continue
        kind = str(row.get("kind") or "")
        if kinds is None:
            add("", f"provisional {pid}: the kinds file {PROVISIONAL_KINDS_PATH.name} could not be read, so its kind {kind!r} "
                "is not verified", "report it as a defect of the installed package; nothing here can settle it",
                f"provisional-kind-unverified-{pid}")
        elif kind not in kinds:
            add("", f"provisional {pid}: kind {kind!r} is not one of {', '.join(sorted(kinds))}",
                "use a kind of references/provisional-kinds.json", f"provisional-kind-{pid}")
        side = str(row.get("settles_on") or "")
        if side not in sides:
            add("", f"provisional {pid}: `settles_on` {side!r} is not a side of this story (its sides: {names})",
                "name the side whose becoming real settles the row, exactly as the story records it", f"provisional-side-{pid}")
        home = row.get("home") if isinstance(row.get("home"), dict) else {}
        file = str(home.get("file") or "").strip()
        if not file:
            add("", f"provisional {pid}: the row names no home file", "send `home: {file, line_hint}` - the project's one place for "
                "the locator, contract or mock", f"provisional-home-{pid}")
        else:
            # the WRITER's root (`manifest_put.stamp_provisional` hashes against `hooklib.project_root()`): one function for both (F8)
            _digest, why = C.marked_line_hash(hooklib.project_root(), file, pid)
            if why:
                add("", f"provisional {pid}: {why}", f"put the comment `qa-provisional: {pid}` on the line of the placeholder in "
                    f"{file} (the test language's comment syntax), or correct `home.file`", f"provisional-home-{pid}")
        dependents = row.get("dependents")
        for dep in dependents if isinstance(dependents, list) else []:
            ok = isinstance(dep, dict) and any(
                C.case_matches(bc, str(dep.get("case") or ""), cfg=cfg) and bt == C.then_number(dep.get("then"))
                for bc, bt in bound)
            if not ok:
                add("", f"provisional {pid}: dependent {dep!r} is not a (case, Then) of `then_bindings`",
                    "list only Thens that are bound in `then_bindings`, as `{case, then}`",
                    f"provisional-dependent-{pid}-{str(dep.get('case') if isinstance(dep, dict) else dep)}")
        if dependents is not None and not isinstance(dependents, list):
            add("", f"provisional {pid}: `dependents` is {type(dependents).__name__}, not a list", "send `dependents` as "
                "`[{case, then}]`", f"provisional-dependents-{pid}")
    held = {str(r.get("id")) for r in ctx.prov["rows"]}
    seen_files: set = set()
    for entry in ctx.tests:
        relative = str(entry.get("file") or "")
        path = resolve_test_file(ctx.task_root, relative) if relative else None
        if path is None or path in seen_files:
            continue
        seen_files.add(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pid in sorted({m.group(1) for m in ANY_MARKER_RE.finditer(text)} - held):
            add(str(entry.get("case") or ""), f"{relative} carries the marker `qa-provisional: {pid}` and the manifest has no "
                f"provisional[] row {pid}", "send the row through `manifest_put.py --fragment` (kind, what, assumed_from, home, "
                "settles_on), or take the marker out of the file", f"provisional-marker-{pid}")


def _sides_pending(ctx) -> None:
    """C5 / C6 (c): the pending rows of the window against the reader and the runs. One finding per row after an arrival: an
    instance whose latest run is terminal is not asked to run again (C6 c owns that state, F10)."""
    import acceptance as AC
    add, names, cfg, sides, manifest = ctx.add, ctx.names, ctx.cfg, ctx.sides, ctx.manifest
    rows = [r for r in AC.pending_rows(manifest) if _scope_has(ctx, r.get("case"))]
    if not (ctx.sided and rows):
        return
    by_alias = AC.tests_by_alias(manifest, cfg)
    latest = {iid: data for iid, (status, data) in _latest_runs(ctx).items() if status in C.TERMINAL_RESULT_STATUSES}
    for row in rows:
        case = str(row.get("case") or "")
        named = [n for n in AC.blocked_row_names({"instance_ids": row["instance_ids"]}) if n in by_alias]
        got = [next((latest[a] for a in [n, *C.instance_id_aliases(by_alias[n], cfg)] if a in latest), None) for n in named]
        excused = AC.pending_instances(manifest, [{"instance_id": n} for n in named], None, sides)
        for iid, run in zip(named, got):
            if iid not in excused and run is None:
                add(case, f"{iid} is listed as `pending_implementation`, but no side it declares is `absent` in the story "
                    f"(its sides: {names}; the test declares {by_alias[iid].get('sides')!r}): it can run, so it owes its run",
                    "run it (`run_suite.py --mine <case>`) and retract the row, or declare the absent side in the test's "
                    "`sides` when one really is", f"pending-not-excused-{iid}")
        if named and all(g is not None for g in got) and all(
                _stamp_is_real(g, s, ctx.plain) for n, g in zip(named, got)
                for s in (by_alias[n]["sides"] if isinstance(by_alias[n].get("sides"), dict) else {})):
            add(case, f"the `pending_implementation` row of {case or '-'} still stands, and every instance it names "
                f"({', '.join(named)}) has run stamped real on every side its test names",
                f"retract it so the runs decide: `{FRAGMENT_ROAD}` with `{{\"retracted_unresolved\": [\"{case}\"]}}` "
                "(a slice row is kept by design until the automator retracts it)", f"pending-row-leftover-{case}")


def _sides_settled(ctx) -> None:
    """C6 (a) / (b): the provisional rows of the window after an arrival. The hash relation reads only what the TOOL stamped
    (`home_hash`, `evidence.home_hash_after`); a role is never asked for either (F7)."""
    add, sides, manifest = ctx.add, ctx.sides, ctx.manifest
    for row in ctx.rows_here:
        pid, status = str(row.get("id")), str(row.get("status") or "")
        side = str(row.get("settles_on") or "")
        if status == "open" and (sides.get(side) or {}).get("reality") == "real" and not _accounting_row(ctx, row):
            add("", f"provisional {pid} is still open and its side {side!r} is now real - a placeholder that outlived its side "
                f"({row.get('what') or 'no description'})",
                f"settle it in the bind round (run the test on the real side, then status settled_matched or settled_edited with "
                f"`evidence.run`), or retract it; when the person decides the substitute stays, the automator marks it "
                f"kept_by_decision citing their word `substitute kept: {side}`", f"{PROVISIONAL_OPEN_ON_REAL}-{pid}")
        if status not in SETTLED_STATUSES:
            continue
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        run = str(evidence.get("run") or "").strip()
        fix = (f"run the test on the real side, then send the row with `status` and `evidence: {{run: <the run block id>}}` for "
               f"{pid} through `manifest_put.py --fragment` - the tool records the hash of the marked line itself")
        if not run:
            add("", f"provisional {pid} is {status} and cites no run block (`evidence.run`)", fix, f"provisional-evidence-{pid}")
            continue
        blocks = _run_blocks(ctx)
        block = next((i["data"] for i in blocks if run in (str(i["data"].get("block_id") or ""), i["name"][:-5])), None)
        collects = [r for r in manifest.get("runs") or [] if isinstance(r, dict) and r.get("kind") == "collect"
                    and run in (str(r.get("label") or ""), str(r.get("block_id") or ""))]
        if block is None or str(block.get("kind") or "") == "collect" or collects:
            add("", f"provisional {pid} cites {run!r} as its run, and " + ("that is a collect, which runs nothing"
                if (block is not None or collects) else "no run block has that id"), fix, f"provisional-evidence-{pid}")
            continue
        if not _stamp_is_real(block, side, ctx.plain):
            add("", f"provisional {pid} is {status} on run {run!r}, whose stamp does not say side {side!r} was real",
                "settle it on a run made while that side was real (the run block's `sides_met`)", f"provisional-stamp-{pid}")
        file = str((row.get("home") or {}).get("file") or "") if isinstance(row.get("home"), dict) else ""
        digest, why = C.marked_line_hash(hooklib.project_root(), file, pid)
        before, after = str(row.get("home_hash") or ""), str(evidence.get("home_hash_after") or "")
        if why:
            add("", f"provisional {pid} is {status}, but its marked line cannot be compared: {why}",
                f"keep the comment `qa-provisional: {pid}` on the line in {file or 'its home file'}", f"provisional-hash-{pid}")
        elif status == "settled_matched" and digest != before:
            add("", f"provisional {pid} is settled_matched, but the marked line changed since its `home_hash` was recorded",
                "record it settled_edited: send the row with `status: settled_edited` and `evidence.run` through "
                "`manifest_put.py --fragment` - the tool records the hash of the line as it is now", f"provisional-hash-{pid}")
        elif status == "settled_edited" and (digest == before or after != digest):
            add("", f"provisional {pid} is settled_edited, but " + ("the marked line is unchanged" if digest == before
                else "the marked line changed after the tool recorded its `evidence.home_hash_after`"),
                "record settled_matched, or send the row again (`status` and `evidence.run`) through `manifest_put.py --fragment` "
                "- the tool records the hash of the marked line as it is now", f"provisional-hash-{pid}")


def _accounting_row(ctx, row) -> bool:
    """The J-C5 accounting row: a `placeholder_locator` with `assumed_from: first_look:<R-n>` (`contract.first_look_row`) whose kind
    allows a real side (`on_real: first_look_only`) and whose side IS real. Only such a row escapes C6 (a); whether its basis holds is
    `_sides_placeholders`. A row of any other kind on a real side, or a first-look row of a kind that says `never`, is not one."""
    side = (ctx.sides.get(str(row.get("settles_on") or "")) or {}) if isinstance(row, dict) else {}
    return side.get("reality") == "real" and C.first_look_row(row) and C.provisional_kind_on_real(row.get("kind")) == "first_look_only"


def _first_look_basis(ctx) -> tuple:
    """`({R-n: row}, "")` of the first-look record, or `({}, why)` when it cannot ground an accounting row: absent or unreadable, stale
    (about other code or another register - `first_look.read` says so; a stale record never confirms anything), or a `null` record
    (no rows). Read once per check, through the ONE reader (`first_look.read`)."""
    if ctx.basis is None:
        import first_look as FL
        got = FL.read(ctx.task_root)
        if got["problem"]:
            ctx.basis = ({}, got["problem"])
        elif got["stale"]:
            ctx.basis = ({}, "the first-look record is about other code or another register than the current ones")
        else:
            ctx.basis = ({str(r.get("req") or ""): r for r in got["rows"]}, "")
    return ctx.basis


def _basis_refusal(ctx, row) -> str:
    """Why the first-look record does not hold the requirement of this accounting row as missing/unreachable because of the product
    ("" when it does). The words are the data file's (`first-look-statuses.json`, through `first_look.data`): the statuses that need a
    `blocked_by`, and the `blocked_by` words the share counts (all but `share_excludes`): `access` and `nature` are never the product's."""
    import first_look as FL
    recorded, why = _first_look_basis(ctx)
    req = str(row.get("assumed_from") or "").strip().split(":", 1)[-1]
    if why:
        return why
    held = recorded.get(req)
    words = FL.data()
    if held is None:
        return f"the first-look record has no row for {req}"
    ok_status = [str(w) for w in words.get("blocked_by_required_for") or []]
    ok_by = [str(w) for w in words.get("blocked_by") or [] if w not in (words.get("share_excludes") or [])]
    if held.get("status") not in ok_status:
        return f"the first-look record says {req} is {held.get('status')!r}, not {' or '.join(ok_status)}"
    if held.get("blocked_by") not in ok_by:
        return f"the first-look record blocks {req} by {held.get('blocked_by')!r}, not by {' or '.join(ok_by)}"
    return ""


def _linked_tests(ctx, row) -> list:
    """The tests of the window linked to an open accounting row (J-C9): those whose `provisional` names it, and those bound in
    `then_bindings` to a Then of its `dependents`. One entry per instance, in `tests[]` order."""
    import acceptance as AC
    pid, cfg = C.provisional_id(row), ctx.cfg
    by_alias = AC.tests_by_alias(ctx.manifest, cfg)
    names = {iid for iid, ids in ctx.prov["by_test"].items() if pid in ids}
    deps = [d for d in row.get("dependents") or [] if isinstance(d, dict)] if isinstance(row.get("dependents"), list) else []
    for b in ctx.manifest.get("then_bindings") or []:
        if isinstance(b, dict) and any(C.case_matches(str(b.get("case") or ""), str(d.get("case") or ""), cfg=cfg)
                                       and C.then_number(b.get("then")) == C.then_number(d.get("then")) for d in deps):
            entry = by_alias.get(str(b.get("instance_id") or "").strip())
            if entry is not None:
                names.add(C.test_instance_id(entry))
    return [t for t in ctx.tests if C.test_instance_id(t) in names]


def _terminal_run_of(ctx, entry) -> bool:
    """Does the story hold a run row of this test whose latest status is terminal (`contract.TERMINAL_RESULT_STATUSES`)? A skipped,
    xfail, deselected, collected-only or absent row is not a run (`_latest_runs`: a later non-terminal row wins)."""
    latest = _latest_runs(ctx)
    return any(latest.get(alias, ("", None))[0] in C.TERMINAL_RESULT_STATUSES for alias in C.instance_id_aliases(entry, ctx.cfg))


def _cases_of(entry) -> list:
    """The case of a test and the cases it covers."""
    return [str(entry.get("case") or ""), *[str(c) for c in entry.get("covers") or []]]


def _env_blocked(ctx, entry) -> bool:
    """Is an instance of this test in an `unresolved[]` row `blocked_by_env`? A row naming no instance counts for every test of its case
    (the safe direction: more refusals, never fewer)."""
    import acceptance as AC
    aliases = set(C.instance_id_aliases(entry, ctx.cfg))
    cases = _cases_of(entry)
    for r in C.manifest_unresolved(ctx.manifest):
        if str(r.get("reason") or "") != AC.BLOCKED_OUTCOME:
            continue
        named = set(AC.blocked_row_names(r))
        if aliases & named or (not named and any(C.case_matches(str(r.get("case") or ""), c, cfg=ctx.cfg) for c in cases if c)):
            return True
    return False


def _handed(ctx, entry) -> bool:
    """Is a case of this test handed to the person (`contract.handed_tests`, the one list of hand-offs)?"""
    return any(C.case_matches(str(h.get("case") or ""), c, cfg=ctx.cfg) for h in C.handed_tests(ctx.manifest) for c in _cases_of(entry) if c)


def _sides_placeholders(ctx) -> None:
    """J-C5 / J-C9 (t-2277): the open accounting rows of the window and the tests linked to them. DATA only: whether a test really leans
    on the placeholder is the code critic's judgment and is read nowhere here.

    J-C5: an open accounting row stands only while the first-look record holds its requirement missing/unreachable because of the
    product, fresh. J-C9 for every test T linked to such a row: (a) T declares the row in `tests[].provisional`; (b) no instance of T is
    `blocked_by_env`; (c) T is not handed to the person; (d) T has a terminal run row. ERROR DIRECTION of (a) (m-new-2): the declaration
    is required of a test that does not touch the placeholder too - the result is a needless `placeholder_open` (the ledger takes the
    green of a declaring test from every Then), never a green on an unsettled placeholder. The declaration is accounting, not a claim."""
    import ledger as L
    add = ctx.add
    held = {str(r.get("id")) for r in ctx.prov["rows"]}
    for entry in ctx.tests:
        iid = C.test_instance_id(entry)
        for pid in ctx.prov["by_test"].get(iid, []):
            if pid not in held:
                add(str(entry.get("case") or ""), f"{iid}: `provisional` names {pid}, which is no row of `provisional[]`",
                    "name only rows the manifest holds (send the row first), or drop the id from the test's `provisional`",
                    f"provisional-unknown-{iid}-{pid}")
    opened = L.open_placeholder_rows(ctx.manifest)
    for row in ctx.rows_here:
        pid = C.provisional_id(row)
        if pid not in opened or not _accounting_row(ctx, row):
            continue
        why = _basis_refusal(ctx, row)
        if why:
            add("", f"provisional {pid} is the accounting row of a red test on a real side (`{row.get('assumed_from')}`), and {why}",
                "retract the row (`status: retracted` through `manifest_put.py --fragment`): the test then runs on the real side and a red "
                "stays red; when the first look is what is missing or old, ask the conductor for a new one - a row on a real side is "
                "never a license, only the account of what the first look saw", f"placeholder-basis-{pid}")
        for entry in _linked_tests(ctx, row):
            iid, case = C.test_instance_id(entry), str(entry.get("case") or "")
            if pid not in ctx.prov["by_test"].get(iid, []):
                add(case, f"{iid} is linked to the open placeholder {pid} (a Then of its `dependents` is bound to it) and does not declare it",
                    f"send `provisional: [{pid}]` for {iid} through `manifest_put.py --fragment` - the declaration is accounting, not a claim "
                    f"that the test leans on the placeholder; a needless one costs a re-pass line, a missing one a green on a placeholder",
                    f"placeholder-undeclared-{iid}-{pid}")
            if _env_blocked(ctx, entry):
                add(case, f"{iid} is tied to the open placeholder {pid} and sits in an `unresolved[]` row `blocked_by_env`",
                    "take it out of that row and run it: its red on the real side is the account of the placeholder, not an env block",
                    f"placeholder-test-blocked-{iid}-{pid}")
            if _handed(ctx, entry):
                add(case, f"{iid} is tied to the open placeholder {pid} and its case is handed to the person",
                    "remove the hand-off row and run the test: it fails on the real side, and the red names the requirement",
                    f"placeholder-test-handed-{iid}-{pid}")
            if not _terminal_run_of(ctx, entry):
                add(case, f"{iid} is tied to the open placeholder {pid} and no run block holds a passed/failed row of it "
                    "(missing, skipped, xfail, deselected or collect-only)", "run it once (`run_suite.py --mine <case>`): the row of the open "
                    "placeholder never excuses the run", f"placeholder-test-norun-{iid}-{pid}")


def check_sides(manifest: dict, sides: dict, task_root, findings: list, scope=None) -> None:
    """C1-C6 of t-2181 §1.3: appends findings of the family `sides` (outside PASSABLE, S10). `sides` is `contract.story_sides`
    of the story's pipeline. A story with no `pipeline.sides` record, every side real, no `sides_unknown` and no provisional
    rows is read exactly as before: nothing here runs (TEMPORAL: until PC-2 nothing makes a side non-real). Which finding a
    person's word may pass: only `sides-undeclared` (C1) and `provisional-open-on-real` (C6 a), by tag.

    `scope` is the window's `{case: [instance ids]}` (the dispatch scope of `run`): tests, `then_bindings`, pending rows and
    provisional rows are judged only when they fall in it, so a window is not refused over another window's test (B5, the
    TP1-15045 class). A provisional row belongs to a window by its `dependents`; a row with no readable dependent is judged in
    every window. `scope=None` is the whole-story read."""
    task_root = Path(task_root)
    prov = C.manifest_provisional(manifest)
    rows = prov["rows"]
    unknown = bool(_load(task_root / "pipeline.json").get("sides_unknown"))
    non_real = sorted(name for name, side in sides.items() if side.get("reality") != "real")
    sided = bool(non_real) or unknown or any(side.get("source") != "default" for side in sides.values())
    if not (sided or rows or prov["skipped"] or any(prov["by_test"].values())):
        return          # (a test that declares a P-n is read even when no row exists: `provisional-unknown-*`, J-C9 (a))

    def add(case: str, message: str, fix: str, tag: str) -> None:
        findings.append(_finding("sides", case, message, fix, tag))

    ids = None if scope is None else {str(i) for v in scope.values() if isinstance(v, list) for i in v if i}
    ctx = SimpleNamespace(
        manifest=manifest, sides=sides, task_root=task_root, add=add, prov=prov, sided=sided, non_real=non_real,
        # every side real and nothing unknown: an absent stamp reads as real (C6 b)
        plain=not non_real and not unknown, cfg=C.case_config(), names=", ".join(sorted(sides)) or "(none)", blocks=None, basis=None,
        scope_cases=None if scope is None else [str(c) for c in scope], tests=[], rows_here=[])
    ctx.tests = [t for t in C.manifest_tests(manifest) if ids is None or C.test_instance_id(t) in ids]
    ctx.rows_here = [r for r in rows if _row_in_scope(ctx, r)]
    _sides_declared(ctx)
    _sides_provisional(ctx)
    _sides_pending(ctx)
    _sides_settled(ctx)
    _sides_placeholders(ctx)


def _asserted_status_codes(asserts: list) -> list:
    out: list = []
    for pyfile, node in asserts:
        for match in STATUS_ASSERT_RE.finditer(pyfile.source(node)):
            code = match.group(1) or match.group(2)
            if code and code not in out:
                out.append(code)
    return sorted(out)


def _referenced_names(node) -> set:
    """Every name one assertion reads: variables, attributes, string subscripts, `.get("k")`."""
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
        elif isinstance(child, ast.Subscript):
            key = getattr(child.slice, "value", None)
            if isinstance(key, str):
                names.add(key)
        elif isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) \
                and child.func.attr == "get" and child.args:
            first = child.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                names.add(first.value)
    return names


def _string_constants(values: list) -> list:
    return [v.value for v in values if isinstance(v, ast.Constant) and isinstance(v.value, str)]


def _assert_nodes(node) -> list:
    out = []
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            out.append(child)
        elif isinstance(child, ast.Call) and isinstance(child.func, ast.Name) \
                and child.func.id in ("assert_that", "assertEqual", "assertTrue"):
            out.append(child)
    return out


def _helpers_reading_optional(pyfile: PyFile) -> dict:
    """Module helpers whose returned value is built out of `.get(key)` with no default —
    the shape where a comparison degenerates to `None == None` and passes on both sides."""
    out: dict = {}
    for node in ast.walk(pyfile.tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # `.get(key, default)` and `.get(key) or <fallback>` both state what a missing key
        # means. A bare `.get(key)` does not, and two of them compared answer `None == None`.
        defaulted = {id(value) for boolop in ast.walk(node) if isinstance(boolop, ast.BoolOp)
                     for value in boolop.values}
        keys = []
        for child in ast.walk(node):
            if not (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "get" and len(child.args) == 1
                    and not child.keywords and id(child) not in defaulted):
                continue
            literal = child.args[0]
            if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                keys.append(literal.value)
        if keys:
            out[node.name] = sorted(set(keys))
    return out


def _compared_values(check) -> list:
    """The two sides of one assertion, WITHOUT its failure message. The message usually
    quotes `response.text`, so judging an assertion by its whole source text says that every
    assertion in the file compares a response body (37 such findings on the first draft)."""
    if isinstance(check, ast.Assert):
        test = check.test
        return list(test.comparators) + [test.left] if isinstance(test, ast.Compare) else [test]
    out = []
    for value in check.args[:2]:
        out.extend(_unwrapped(value))
    return out


def _unwrapped(value) -> list:
    """The values a matcher chain compares, EVERY level of it: `is_(equal_to(x))` is `x`. One level only (what this read
    first) left the inner `equal_to` a Call, and a comparison of two names read as a name and a call: a silent pass."""
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in ("equal_to", "is_", "is_not"):
        return [inner for arg in value.args for inner in _unwrapped(arg)]
    return [value]


def _is_body(value, helpers: dict) -> bool:
    """A parsed response, not a status code: `.json()`, a helper that returns one, or a
    variable spelled `error`/`body`/`payload`."""
    if isinstance(value, ast.Name):
        return value.id.lower() in ("error", "body", "payload", "content")
    source = ast.dump(value)
    if "'json'" in source or "'text'" in source:
        return True
    return (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
            and (value.func.id in helpers or "error" in value.func.id.lower()
                 or "body" in value.func.id.lower()))


def _counts_a_substring_match(check, fragment: str) -> bool:
    """True when this assertion compares a NUMBER with the count of whatever a text substring
    matched — the shape that produced BUG-1 on TP1-15045.

    Scoped by a test id in the same expression: not a finding. That is the repair, and a check
    that fires on it would push the author back to the matcher this rule exists to remove."""
    if not SUBSTRING_MATCH_RE.search(fragment) or SCOPED_SELECTOR_RE.search(fragment):
        return False
    counts = any(
        isinstance(node, ast.Call)
        and ((isinstance(node.func, ast.Attribute) and node.func.attr in ("count", "all", "all_text_contents"))
             or (isinstance(node.func, ast.Name) and node.func.id == "len"))
        for node in ast.walk(check))
    numbers = any(isinstance(node, ast.Constant) and isinstance(node.value, int)
                  and not isinstance(node.value, bool) for node in ast.walk(check))
    return counts and numbers


SLEEP_FIX = "wait for the condition the test needs (the project's wait helper), not for a number of seconds"


def _assign_facts(owner, scope, helpers: dict) -> tuple:
    """`(bodies, tainted)` over one function: the names assigned from a helper that reads with .get(), and the names
    assigned from the environment."""
    bodies: dict = {}
    tainted = set()
    for child in ast.walk(scope):
        if not isinstance(child, ast.Assign):
            continue
        if ENV_SOURCE_RE.search(owner.source(child.value)):
            # The TARGETS carry the value onwards, the right-hand side does not: walking the
            # whole assignment tainted `os` itself, after which every assert mentioning `os`
            # was a credential assert.
            tainted |= {t.id for t in ast.walk(child.targets[0])
                        if isinstance(t, ast.Name)}
        call = child.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) \
                and call.func.id in helpers:
            for target in ast.walk(child.targets[0]):
                if isinstance(target, ast.Name):
                    bodies[target.id] = (call.func.id, helpers[call.func.id])
    return bodies, tainted


# --- a relative oracle on a base that may be a refusal (TQ1-18) -------------------------------------------------------------

BASELINE_KEY = "baseline_names"
BASE_CHECKED_KW = "base_checked"
RELATIVE_TAG = "relative-oracle-"
RELATIVE_FIX = ("assert what a working base is before you compare (its status, its outcome: a value only a working call gives), "
                f"or say where it is checked: marker `{BASE_CHECKED_KW}=\"<file>::<function>\"` on the test")
MATCHER_WRAPPERS = ("equal_to", "is_")
# A matcher that asks nothing of a value but that it exists: its calls are all in this set.
TRIVIAL_MATCHERS = frozenset({"is_", "is_not", "not_", "not_none", "none"})
# A matcher that asks only the SHAPE of a value (its length, its type): a refusal has a shape too, so it is no proof of a working base.
SHAPE_MATCHERS = frozenset({"has_length", "instance_of", "empty", "is_empty"})
SHAPE_CALLS = frozenset({"isinstance", "len"})
# A call that builds a matcher, not a value: `is_(has_length(3))` compares nothing with anything taken before.
MATCHER_CALLS = TRIVIAL_MATCHERS | SHAPE_MATCHERS | frozenset({
    "equal_to", "has_item", "has_items", "has_entry", "has_entries", "has_key", "has_value", "has_property", "has_properties",
    "contains_string", "contains_exactly", "contains_inanyorder", "contains", "starts_with", "ends_with", "greater_than",
    "greater_than_or_equal_to", "less_than", "less_than_or_equal_to", "close_to", "any_of", "all_of", "anything", "matches_regexp",
    "string_contains_in_order", "only_contains", "is_in", "same_instance", "calling", "raises"})


def _baseline_tokens(notes: list, path=None) -> frozenset:
    """The words that make a variable the value taken BEFORE an action: the `baseline_names` row of `references/detectors.json`
    (AR-1, read by the one reader of that file, AR-13). A row that cannot be read is NO tokens and a note: the pair of one call
    before and after the action is still judged, the token half is not, and the gate says so (FR-59, D3-K14)."""
    import assertion_detectors as AD
    try:
        return frozenset(word.lower() for word in AD.shape_patterns(BASELINE_KEY, path))
    except AD.DetectorsError as exc:
        said = (f"relative-oracle check: `{BASELINE_KEY}` of references/detectors.json is not usable ({getattr(exc, 'kind', 'unreadable')}); "
                "only a value read by the same call before and after the action is judged - the code critic reads the rest")
        if said not in notes:
            notes.append(said)
        return frozenset()


def _root_name(value, through: bool = True) -> str:
    """The variable a value is read from: `before`, `before.status`, `before[0]` and `before.json()` all name `before`; with
    `through`, so do `len(before)` and `sorted(before)` (a plain call of ONE argument is read through). A literal and an operation
    (`before + 1`) name none; `through=False` also names none for the call of a plain function."""
    while True:
        if isinstance(value, (ast.Attribute, ast.Subscript)):
            value = value.value
        elif isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
            value = value.func.value
        elif through and isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and len(value.args) == 1 and not value.keywords:
            value = value.args[0]
        else:
            return value.id if isinstance(value, ast.Name) else ""


def _is_literal(value) -> bool:
    try:
        ast.literal_eval(value)
        return True
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False


def _is_matcher_call(value) -> bool:
    return isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in MATCHER_CALLS


def _call_name(check) -> str:
    func = getattr(check, "func", None)
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


def _equality_pair(check):
    """The two values an assertion says are EQUAL, else None: an inequality, an ordering, one value and any other matcher are not
    a comparison with something taken before. A hamcrest matcher counts only as `equal_to(x)` / `is_(x)` (nested to any depth, a
    negation anywhere is none), and neither value may be a matcher call: `is_(has_length(3))` builds a matcher, it is no value. A value
    that is a call of a plain function (`_u(c)`, `len(items(c))`) IS a value: the other side may be the base (F-2)."""
    if isinstance(check, ast.Assert):
        test = check.test
        if not (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], (ast.Eq, ast.Is))):
            return None
    elif _call_name(check) == "assert_that":
        matcher = check.args[1] if len(check.args) > 1 else None
        if matcher is None or any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "is_not"
                                  for n in ast.walk(matcher)):
            return None
        if isinstance(matcher, ast.Call) and not (isinstance(matcher.func, ast.Name) and matcher.func.id in MATCHER_WRAPPERS):
            return None
        values = _compared_values(check)
        return (values[0], values[1]) if len(values) == 2 and not any(_is_matcher_call(v) for v in values) else None
    elif _call_name(check) != "assertEqual":
        return None
    values = _compared_values(check)
    return (values[0], values[1]) if len(values) == 2 else None


def _assertions_of(node) -> list:
    """Every assertion of one test: `_assert_nodes` and the helpers that read like one (`assert_ok(x)`, `self.assertEqual(...)`,
    `verify_...`, `expect_...`: `manifest_from_tests.ASSERT_CALL_PREFIXES`, the one list)."""
    import manifest_from_tests as MFT
    out = list(_assert_nodes(node))
    seen = {id(n) for n in out}
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and id(child) not in seen and _call_name(child).lower().startswith(MFT.ASSERT_CALL_PREFIXES):
            out.append(child)
    return out


def _asks_the_base(check, base: str) -> bool:
    """Does this assertion ask something of `base` that a working answer gives and a refusal does not? NOT: a bare `assert base`, a
    test against None (a refusal is a non-empty tuple, an error body, a False), a matcher that only asks existence, a helper named
    for None, a SHAPE (`isinstance(base, tuple)`, `len(base) == 2`, `has_length(2)`, `not base`: the owner's refusal `("http", 400)` is a
    tuple of two too, F-3), and the relative comparison itself (two variables read for equality: that is what is being judged).
    `base[0] == "http"` and `base.status == 200` ask a value, and count."""
    if not _outside_shape(check, base):
        return False
    if isinstance(check, ast.Assert):
        test = check.test
        if isinstance(test, ast.Name) or (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and isinstance(test.operand, ast.Name)):
            return False
        if isinstance(test, ast.Compare) and any(isinstance(c, ast.Constant) and c.value is None for c in test.comparators):
            return False
    else:
        name = _call_name(check).lower()
        if "none" in name or name in ("asserttrue", "assertfalse"):
            return False
        if name == "assert_that" and len(check.args) > 1:
            calls = {n.func.id for n in ast.walk(check.args[1]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            if calls and calls <= TRIVIAL_MATCHERS | SHAPE_MATCHERS:
                return False
    pair = _equality_pair(check)
    return not (pair and all(_root_name(v, through=False) for v in pair))


def _outside_shape(check, base: str) -> bool:
    """True when `base` is read somewhere other than inside `len(...)` / `isinstance(...)`: a length or a type is a shape."""
    def seen(node) -> bool:
        if isinstance(node, ast.Name):
            return node.id == base
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in SHAPE_CALLS:
            return False
        return any(seen(child) for child in ast.iter_child_nodes(node))
    return seen(check)


def _chain_of(tree, target) -> list:
    """The class chain of one function node, `[]` for a module-level one."""
    def walk(body, chain):
        for item in body:
            if item is target:
                return chain
            if isinstance(item, ast.ClassDef):
                got = walk(item.body, chain + [item.name])
            elif isinstance(item, (ast.If, ast.Try, ast.With)):
                got = None
                for field in ("body", "orelse", "finalbody"):
                    got = walk(getattr(item, field, None) or [], chain)
                    if got is not None:
                        break
            else:
                continue
            if got is not None:
                return got
        return None
    return walk(tree.body, []) or []


def _relative_gaps(node, tokens: frozenset) -> list:
    """`[(line, compared-with, base)]` of the assertions of one test that compare a value taken BEFORE an action with another value
    while nothing above them asks that base to be a working answer.

    The base is, by (a) STRUCTURE, the earlier of two variables assigned from the same call with a statement between them (the
    action), or, by (b) TOKEN, a variable one of whose words is in `baseline_names` (`before`, `x_before`, a fixture argument).
    The error allowed is a FALSE refusal (a door follows); a false pass only for a comparison with no shared call and no token."""
    assigned = _assigned_calls(node)
    statement_lines = sorted({n.lineno for n in ast.walk(node) if isinstance(n, ast.stmt)})
    asserts = _assertions_of(node)
    import repo_map
    out, seen = [], set()
    for check in sorted(asserts, key=lambda a: a.lineno):
        pair = _equality_pair(check)
        if pair is None:
            continue
        names = [_root_name(v) for v in pair]
        bases = [(name, ast.unparse(pair[1 - index])) for index, name in enumerate(names)
                 if name and tokens & set(repo_map._split_ident(name)) and not _is_literal(pair[1 - index])]
        if names[0] and names[1] and names[0] != names[1]:
            bases += [(names[index], ast.unparse(pair[1 - index])) for index in (0, 1)
                      if _same_call_across(assigned, names[index], names[1 - index], statement_lines)]
        if not bases or any(a is not check and a.lineno < check.lineno and _asks_the_base(a, base)
                            for base, _w in bases for a in asserts):
            continue
        base, other = bases[0]
        if base not in seen:
            seen.add(base)
            out.append((check.lineno, other, base))
    return out


def _assigned_calls(node) -> dict:
    """`{variable: [(line, callee source)]}` over one test: every name a call is assigned to, tuple targets (`a, b = f()`) included."""
    assigned: dict = {}
    for child in ast.walk(node):
        if isinstance(child, ast.Assign) and len(child.targets) == 1:
            target, value = child.targets[0], child.value
        elif isinstance(child, ast.AnnAssign) and child.value is not None:
            target, value = child.target, child.value
        else:
            continue
        value = value.value if isinstance(value, ast.Await) else value
        if isinstance(value, ast.Call):
            for name in (n.id for n in ast.walk(target) if isinstance(n, ast.Name)):
                assigned.setdefault(name, []).append((child.lineno, ast.unparse(value.func)))
    return assigned


def _same_call_across(assigned: dict, first: str, second: str, statement_lines: list) -> bool:
    """Is `first` assigned from the same call as `second` is, EARLIER, with a statement (the action) between the two?"""
    return any(callee_a == callee_b and at_a < at_b and any(at_a < line < at_b for line in statement_lines)
               for at_a, callee_a in assigned.get(first, []) for at_b, callee_b in assigned.get(second, []))


def _base_checked_problem(value, task_root) -> str:
    """`""` when `value` (`<file>::<function>`) names a test-code function that exists, else why it does not (the finding stays and
    says so). Only the EXISTENCE is judged: what that function asserts is the code critic's (the fixture may check anything)."""
    if not isinstance(value, str) or "::" not in value:
        return "it is not a literal `<file>::<function>` string"
    import probe_by_code as PBC
    try:
        spec = PBC.parse_node(value)
        if not spec["file"].endswith(".py"):
            return f"`{spec['file']}` is not a Python file"
        path = resolve_test_file(Path(task_root), spec["file"]) if task_root is not None else None
        if path is None:
            return f"`{spec['file']}` is not a file under the project"
        parsed, problem = read_python(path)
        if parsed is None:
            return problem
        PBC.locate(parsed.tree, spec["chain"], spec["function"])
    except Exception as exc:
        return " ".join(str(exc).split())[:160]
    return ""


def check_relative_oracle(case: str, text: str, targets: list, advice: list, task_root, notes: list,
                          s7_round: bool = False, novelty=None, detectors_path=None) -> None:
    """A test that compares a value taken before an action with the same value after it, while nothing asks the first to be a
    working answer: a refusal before and after (400 and 400) is equal, and the test passes on the very thing it should catch
    (TP1-12586: an integration "still usable" after a move, green on a failing check of the connection).

    `text` (the case file) is NOT read: the check needs the test's AST only, so the caller runs it OUTSIDE its `if text`, and an
    empty or missing case file does not switch the gate off (FR-59). An ADVICE unit (X7-2): what it finds goes to `advice` for the
    code critic, which reads the run log and records the base outcome; the code reports the pattern, the role judges it (AR-2,
    AR-29). `base_checked="<file>::<function>"` is the test's own marker when the base is asserted elsewhere (a fixture): a marker
    that names a real function silences the advice. INVARIANT: a test whose base may be a refusal and is not asserted reaches the
    critic named, never silently.

    Only tests the story changed (`new`/`changed`; `unknown` is judged as changed, and said in a note): a neighbour's old test
    is not paid for by this window. In an S7 repair round the advice says the window and the critic already saw it."""
    del text
    tokens = _baseline_tokens(notes, detectors_path)
    candidates = []
    for pyfile, name, node in targets:
        gaps = _relative_gaps(node, tokens)
        if not gaps:
            continue
        marker = _base_checked_marker(node)
        why = _base_checked_problem(marker, task_root) if marker is not None else ""
        if marker is not None and not why:
            continue                        # the test names the function that asserts its base: its meaning is the critic's
        candidates.append((pyfile, name, node, gaps, marker, why))
    if not candidates:
        return
    project = _project_of(task_root) if task_root is not None else None
    tops = [(pyfile.path, _chain_of(pyfile.tree, node), name) for pyfile, name, node, *_rest in candidates]
    try:
        values = list((novelty or _copy_novelty(task_root, project))(tops))
    except Exception as exc:               # an unread novelty is `unknown`, which is judged as changed (the safe side)
        values = ["unknown"] * len(tops)
        notes.append(f"relative-oracle check: the novelty of the tests could not be measured ({type(exc).__name__}); "
                     "they are judged as changed")
    unknown = []
    for (pyfile, name, node, gaps, marker, why), value in zip(candidates, values):
        if value == "unchanged":
            continue
        if value not in ("new", "changed"):
            unknown.append(name)
        for line, other, base in gaps:
            where = f"{pyfile.path.name}:{line}"
            message = (f"{where} compares `{other}` with `{base}`, a value taken before the action, and nothing asks `{base}` to be "
                       "a working answer: if the base is a refusal, the same refusal after the action makes the two equal and "
                       "the test passes on it")
            if marker is not None:
                message += f"; `{BASE_CHECKED_KW}=\"{marker}\"` does not count: {why}"
            if s7_round:
                message += " - a repair round of S7: the window and the critic already saw it"
            advice.append(_advice("oracle", case, message, RELATIVE_FIX, RELATIVE_TAG + where))
    if unknown:
        said = (f"relative-oracle check: could not tell whether the story changed {len(unknown)} test(s) "
                f"({', '.join(unknown[:4])}{f' +{len(unknown) - 4} more' if len(unknown) > 4 else ''}); judged as changed")
        if said not in notes:
            notes.append(said)


def _base_checked_marker(node):
    """The `base_checked=` value of the test's marker: None when absent, `""` when it is not a literal string."""
    for decorator in node.decorator_list:
        for keyword in decorator.keywords if isinstance(decorator, ast.Call) else ():
            if keyword.arg == BASE_CHECKED_KW:
                value = keyword.value
                return value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else ""
    return None


def check_smells(case: str, text: str, files: list, targets: list, advice: list,
                 task_root=None, notes: list | None = None) -> None:
    """An ADVICE unit (X7-2): what it finds goes to `advice` for the code critic, never to the author as a repair. A smell
    hit from code is a pattern to read, not the verdict: whether a sleep is justified or an environment read is a defect is the
    critic's call (AR-2, AR-29).

    `targets` are the case's OWN test functions; a file's other tests belong to other
    cases and their author already got this list for theirs.

    The scope of each test is the test and the CLOSURE of the fixtures it reaches (`_fixture_closure`): its own file's
    and the `conftest.py` chain's. What lives in the test's own file is judged as it always was. A fixture of a
    conftest is the window's code only if the window changed it (`_fixture_changed`, against the story's S0): a smell
    in an unchanged one is somebody else's and is not named. When the change cannot be established (`unknown`, no story
    root) the advice says so and a note names it, not silence."""
    demands_normalisation = bool(NORMALISE_RE.search(text or ""))
    project = _project_of(task_root)
    notes = [] if notes is None else notes
    changed: dict = {}
    for pyfile, name, node in targets:
        helpers = _helpers_reading_optional(pyfile)
        test_bodies, test_tainted = _assign_facts(pyfile, node, helpers)
        # A fixture the test depends on is part of the test: the credential assert of
        # TP1-15045 sat in `non_owner_workflow_utils`, not in the test body.
        entries, closure_notes = _fixture_closure(pyfile, node, project)
        notes += [n for n in closure_notes if n not in notes]
        own = [(owner, scope, is_fixture) for owner, scope, rel, is_fixture in entries if rel is None]
        foreign = [(owner, scope, rel) for owner, scope, rel, _fx in entries if rel is not None]
        seen_here = set()
        work = [(owner, scope, owner.path.name, helpers, test_bodies, test_tainted, seen_here, advice)
                for owner, scope, _fx in own]
        found: dict = {}          # the advice per conftest fixture, judged for "changed" after the scan
        for owner, scope, rel in foreign:
            owner_helpers = _helpers_reading_optional(owner)
            bodies_there, tainted_there = _assign_facts(owner, scope, owner_helpers)
            work.append((owner, scope, rel, owner_helpers, bodies_there, tainted_there, set(),
                         found.setdefault((rel, scope.name, id(scope)), [])))
        for owner, scope, label, helpers, bodies, tainted, seen_here, out in work:
            for check in _assert_nodes(scope):
                fragment = owner.source(check)
                names = {n.id for n in ast.walk(check) if isinstance(n, ast.Name)}
                where = f"{label}:{check.lineno}"
                if where in seen_here:
                    continue
                from_env = ENV_SOURCE_RE.search(fragment)
                carried = sorted(names & tainted)
                if from_env or carried:
                    seen_here.add(where)
                    trace = (f"`{from_env.group(0)}` is read in the assert itself" if from_env
                             else f"`{carried[0]}` was assigned from the environment above")
                    out.append(_advice(
                        "smell", case,
                        f"{where} asserts on a credential read from the environment ({trace}) — "
                        "on any machine without those variables the test is an error, not a skip",
                        "skip the test when the account is absent (the project's own idiom: "
                        "`pytest.skip`, or a fixture that creates a throwaway user)",
                        f"env-assert-{where}"))
                    continue
                values = _compared_values(check)
                compared = [bodies[v.id] for v in values if isinstance(v, ast.Name) and v.id in bodies]
                if len(compared) >= 2:
                    seen_here.add(where)
                    out.append(_advice(
                        "smell", case,
                        f"{where} compares values `{compared[0][0]}` reads with .get() "
                        f"({', '.join(compared[0][1][:4])}) — a key missing on BOTH sides makes "
                        "the assertion pass on None == None",
                        "read the field with a default that cannot occur, or assert it is "
                        "present before comparing", f"both-none-{where}"))
                    continue
                if _counts_a_substring_match(check, fragment):
                    seen_here.add(where)
                    out.append(_advice(
                        "smell", case,
                        f"{where} compares a number with the count of what a text matcher "
                        "selected — `has_text` / `get_by_text` is a case-insensitive SUBSTRING "
                        "match over every descendant, so it counts whatever else says the same "
                        "word (on TP1-15045 the popup legend's 'Added' chip was counted as "
                        "a second ADDED badge: 1 + 1 == 2 on every run, and the bug filed for "
                        "it was the test's own)",
                        "count the scoped element instead — its `data-testid`, or the node's "
                        "own chrome; a Then about one node is observed through that node's "
                        "locator, never through the container's text",
                        f"substring-count-{where}"))
                    continue
                if demands_normalisation and len(values) >= 2 \
                        and all(_is_body(v, helpers) for v in values[:2]):
                    seen_here.add(where)
                    out.append(_advice(
                        "smell", case,
                        f"{where} compares a response body with `equal_to` while the case "
                        "demands the volatile fields be normalised",
                        "normalise before comparing (drop request id, timestamps and any other "
                        "per-call field the case names), then compare", f"raw-body-{where}"))
        # A bare sleep, by the AST (`_bare_sleep`): a poll with a ceiling in a FIXTURE is not one; in a test body it is.
        for _owner, scope, is_fixture in own:
            if _bare_sleep(scope, allow_poll=is_fixture):
                advice.append(_advice("smell", case, f"{pyfile.path.name}: `{scope.name}` waits with sleep()",
                                      SLEEP_FIX, f"sleep-{pyfile.path.name}-{scope.name}"))
        for owner, scope, rel in foreign:
            there = found[(rel, scope.name, id(scope))]
            if _bare_sleep(scope, allow_poll=True):
                there.append(_advice(
                    "smell", case, f"{rel}: `{scope.name}` waits with sleep()",
                    SLEEP_FIX, f"sleep-{rel.replace('/', '.')}-{scope.name}"))
            if not there:
                continue
            if (rel, scope.name) not in changed:
                changed[(rel, scope.name)] = _fixture_changed(task_root, project, rel, scope.name)
            answer, words = changed[(rel, scope.name)]
            if answer == "yes":
                advice.extend(there)
            elif answer == "unknown":
                said = (f"{rel}: could not establish whether fixture `{scope.name}` changed; the code critic reads it "
                        f"({words}); the check found: {there[0]['message']}")
                tag = f"fixture-unknown-{rel.replace('/', '.')}-{scope.name}"
                if not any(h.get("id") == f"smell:{case or '-'}:{tag}" for h in advice):
                    advice.append(_advice("smell", case, said, "read the fixture; if the window changed it, the smell above "
                                          "stands; if it is not the story's change, it is somebody else's", tag))
                if said not in notes:
                    notes.append(said)
    # A second copy of a helper is `check_copies`'s now (TQ1-19): the exact-body twin that stood here is one case of it.


class _BlankLiterals(ast.NodeTransformer):
    """Every literal becomes the same placeholder, so two tests that differ only in their
    data have the same shape and two tests that differ in what they DO do not."""

    def visit_Constant(self, node):  # noqa: N802 - ast's own spelling
        return ast.copy_location(ast.Constant(value="~"), node)


def _body_shape(node) -> tuple:
    """(shape, literals) of one test body, docstring excluded — the docstring is where the
    case marker lives, and two tests for two cases always differ there."""
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None),
                                                             ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    if len(body) < 2:
        return "", ()
    # Re-parsed from source, never the live tree: the transformer below rewrites what it
    # walks, and the other checks read these same nodes afterwards.
    module = ast.parse("\n".join(ast.unparse(stmt) for stmt in body))
    literals = tuple(repr(n.value) for n in ast.walk(module) if isinstance(n, ast.Constant))
    return ast.dump(_BlankLiterals().visit(module)), literals


def check_parameterization(targets: list, advice: list) -> None:
    """Two or more instances of this window with the same setup, action and oracle and
    different data: a parameterization candidate (0.7.7 point 3).

    This is the INVERSE of the finding it replaced. The old check counted test functions per
    case and so argued for splitting; this one names duplication the author may not have
    seen, and says so as ADVICE for the code critic (X7-2) — the executable shape is the automator's decision, the critic judges
    the choice (P17), and a refusal here would just be the old rule pointing the other way."""
    shapes: dict = {}
    for case, pyfile, name, node in targets:
        try:
            shape, literals = _body_shape(node)
        except Exception:
            continue  # a body that cannot round-trip through ast is not a duplicate claim
        if not shape:
            continue
        shapes.setdefault(shape, {})[f"{pyfile.path.name}::{name}"] = (case, literals)
    for group in shapes.values():
        if len(group) < 2 or len({data for _case, data in group.values()}) < 2:
            continue  # identical data is a copy, not a parameterization candidate
        names = sorted(group)
        cases = sorted({case for case, _data in group.values()})
        advice.append(_advice(
            "smell", cases[0],
            f"{len(names)} tests have the same setup, action and oracle and differ only in "
            f"their data ({', '.join(names[:4])}) — they read as one parametrized test over "
            f"{len(cases)} case(s): {', '.join(cases)}",
            "if one parametrized test keeps every Then clause diagnosable on its own, write "
            "it and let its `covers` name every case; if a failure of one would be harder to "
            "read apart, keep them and say so in the manifest's `shape` line",
            "parameterize-" + "+".join(names)))


def _class_twins(task_root, row_file: str, name: str, notes) -> list:
    """The methods of the SAME class as helper `name` (`Class.method`) whose names share a word with it: the ones to
    compare against. `[]` for a plain function, a file that is not Python or cannot be read (a note says which: nothing
    here is a clean bill, AR-28), or a class that is not there any more. Words are `repo_map._split_ident` (AR-13)."""
    if "." not in name:
        return []
    chain, method = name.split(".")[:-1], name.split(".")[-1]
    path = resolve_test_file(Path(task_root), row_file) if task_root is not None else None
    if path is None or path.suffix != ".py":
        if notes is not None and row_file not in "".join(notes):
            notes.append(f"{row_file}: the methods beside helper `{name}` were not read ("
                         + ("not a Python file" if path is not None else "file not found") + ")")
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError, OSError):
        if notes is not None:
            notes.append(f"{row_file}: the methods beside helper `{name}` were not read (does not parse)")
        return []
    body = tree.body
    for part in chain:
        body = next((n.body for n in body if isinstance(n, ast.ClassDef) and n.name == part), None)
        if body is None:
            return []
    import repo_map
    mine = set(repo_map._split_ident(method))
    return sorted(n.name for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name != method and not n.name.startswith("test") and mine & set(repo_map._split_ident(n.name)))


def helper_twin_hint(manifest: dict, hints: list, task_root=None, notes: list | None = None) -> None:
    """A hint for each helper this story made new (`introduced_helpers[]`, written by `manifest_from_tests.py`) whose row
    does not yet say where the author looked (`searched`) and what was found (`similar_found`), and for a method that
    shares a word with another method of its class. TQ1-7: a second helper beside an existing one is invisible to the
    textual-duplicate check, so the trail to the analogue is asked for; whether a new helper was needed is the role's.

    A HINT, never a finding: `ok` does not move (hint is advice). A manifest without the key reads as no rows (an old
    manifest does not fail); a row that is not an object, or names no file or helper, is skipped."""
    rows = manifest.get("introduced_helpers") if isinstance(manifest, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        file, name = str(row.get("file") or "").strip(), str(row.get("name") or "").strip()
        if not file or not name:
            continue
        blank = [f for f in ("searched", "similar_found") if not str(row.get(f) or "").strip()]
        twins = _class_twins(task_root, file, name, notes)
        if not blank and not twins:
            continue
        said = [f"`{', '.join(blank)}` of its `introduced_helpers[]` row {'is' if len(blank) == 1 else 'are'} empty"] if blank else []
        if twins:
            said.append("the same class already has " + ", ".join(f"`{t}`" for t in twins[:4]) + " (a shared word in the name)")
        hints.append(_hint(
            "smell", "", f"{file}: new helper `{name}` - " + "; ".join(said),
            "look for the existing one (the page object, the utils module, the conftest chain), then write in the row "
            "`purpose`, `searched` (where you looked) and `similar_found` (what you found, or `none`); a helper you keep "
            "beside an existing one says why in `keep`: `manifest_put.py --task <T> --fragment <file>`",
            f"helper-{file.replace('/', '.')}-{name}"))


# --- a copy of code that already exists (TQ1-19) -------------------------------------------------------------------------

COPY_KEEP = ("; a helper (new or changed) that cannot serve writes why in `keep` of its `introduced_helpers[]` row: "
             "`manifest_put.py --task <T> --fragment <file>`")
COPY_HINT_FIX = ("look at it: if it can serve, call or extend it; if one parametrized test or the existing code can carry "
                 "this one, say so in your digest; otherwise leave it and say why in the manifest's `shape` line")


def _copy_history(task_root, project, manifest: dict, notes: list) -> list:
    """The Python files a story's history touched: the file of every `tests[]` row of the manifest - ALL windows, not the
    dispatch's scope, so a copy between window 1 and window 3 is seen on the last (D2-K10) - and the `conftest.py` chain above
    each (`_conftest_files`, the one reader), each once, resolved. A file that is not Python is one note: copies in it are
    not checked and the code critic reads it whole."""
    files: list = []
    non_python: list = []
    for row in C.manifest_tests(manifest):
        resolved = resolve_test_file(Path(task_root), str(row.get("file") or "")) if task_root is not None else None
        if resolved is None:
            continue
        if resolved.suffix != ".py":
            if resolved.name not in non_python:
                non_python.append(resolved.name)
        elif resolved.resolve() not in files:
            files.append(resolved.resolve())
    for path in list(files):
        rows, chain_notes = _conftest_files(path, project)
        notes += [n for n in chain_notes if n not in notes]
        for conftest, _parsed in rows:
            if conftest.resolve() not in files:
                files.append(conftest.resolve())
    if non_python:
        said = ("copy check: " + ", ".join(non_python[:4]) + (f" (+{len(non_python) - 4} more)" if len(non_python) > 4 else "")
                + " is not a Python file; copies in it were not checked - the code critic reads it whole")
        if said not in notes:
            notes.append(said)
    return files


def _copy_novelty(task_root, project):
    """The measurer handed to `copy_detector.find_copies`: ONE `test_novelty.measure_many` call over the outermost functions
    that have a copy (the one reader of the story's base, AR-13), `unknown` for all when there is no story root or no project."""
    def measure(tops: list) -> list:
        if task_root is None or project is None:
            return ["unknown"] * len(tops)
        import test_novelty
        import test_repo_base
        items = [{"test_rel": _shown(path, project), "function": name, "class_chain": list(chain)} for path, chain, name in tops]
        results = test_novelty.measure_many(project, items, base_record=test_repo_base.load(task_root))
        return [r.get("value") if isinstance(r, dict) else None for r in results]
    return measure


def check_copies(task_root, manifest: dict, advice: list, notes: list, s7_round: bool = False,
                 novelty=None, limits_path=None) -> None:
    """A function of the story's history that repeats code which already exists, under other names (`copy_detector`), as ADVICE
    for the code critic (X7-2): "extend or write new" is the automator's choice (P17) and whether this copy is a defect is the
    critic's judgment (AR-2, AR-29); the code finds the copy and says where the original lives.

    A false pass is allowed for a copy outside the history and the modules it imports, and for code that is not Python (a note).
    INVARIANT: a copy of a helper or a fixture in the story's diff reaches the critic named, with the original's place. The units
    are the new or changed functions of every file of the manifest and of their conftest chain; the pool is those files and the
    project modules they import.

    The advice says why it is softer when: a copy whose novelty could not be established (`unknown`, and a note, FR-59), a copy a
    row of `introduced_helpers[]` explains with a non-empty `keep` (the row is the role's field on a scaffold the code wrote; the
    critic reads it), a `test*` body (it reads like its neighbours), and every copy in an S7 repair round (`s7_round`: the window
    and the critic already saw it). `limits_path` and `novelty` are seams for a test."""
    import copy_detector as CD
    project = _project_of(task_root) if task_root is not None else None
    try:
        files = _copy_history(task_root, project, manifest, notes)
        if not files:
            return
        lim, lim_notes = CD.limits(limits_path)
        notes += [n for n in lim_notes if n not in notes]
        result = CD.find_copies(files, project, lim, novelty or _copy_novelty(task_root, project))
    except Exception as exc:      # an unread check is said, never a pass and never a crash of the whole gate (FR-59, P1)
        notes.append(f"copy check did not complete ({type(exc).__name__}); copies were not checked - the code critic reads the diff")
        return
    notes += [n for n in result["notes"] if n not in notes]
    if result["dropped"]:
        names = ", ".join(_shown(p, project) for p in result["dropped"][:5]) + \
            (f" (+{len(result['dropped']) - 5} more)" if len(result["dropped"]) > 5 else "")
        said = (f"copy check: {len(result['dropped'])} file(s) beyond the limit of {lim['max_files']} were not read as units: {names} "
                "- copies in them are not checked; the code critic reads them")
        notes.append(said)
        advice.append(_advice("smell", "", said, "read those files for a second copy of a helper or a fixture",
                              "copy-limit"))
    held = manifest.get("introduced_helpers") if isinstance(manifest, dict) else None
    rows = {(str(r.get("file") or ""), str(r.get("name") or "")): r for r in held if isinstance(r, dict)} \
        if isinstance(held, list) else {}
    unknown: list = []
    for copy in result["copies"]:
        unit, old = copy["unit"], copy["old"]
        rel, old_rel = _shown(unit.path, project), _shown(old.path, project)
        row = rows.get((rel, ".".join(unit.top[0] + (unit.top[1],))))
        what = "the same body" if copy["how"] == "function" else f"{lim['fragment_window']} statements in a row"
        more = f" (and {len(copy['more'])} more place(s))" if copy["more"] else ""
        message = f"{rel}: `{unit.qname}` repeats `{old.qname}` ({old_rel}:{old.line}) - {what} under other names{more}"
        tag = f"copy-{rel.replace('/', '.')}-{unit.qname}"
        if copy["novelty"] == "unknown":
            unknown.append(f"{rel}::{unit.qname}")
        reason = ("a repair round of S7: the window and the critic already saw it" if s7_round
                  else "whether the story changed it could not be established" if copy["novelty"] == "unknown"
                  else "a test reads like its neighbours: the code critic judges whether one parametrized test or the "
                       "existing code can serve" if unit.kind == "test"
                  else "its `introduced_helpers[]` row says why it is kept; the code critic reads it"
                  if row and str(row.get("keep") or "").strip() else "")
        if reason:
            advice.append(_advice("smell", "", f"{message} - {reason}", f"`{old.qname}` ({old_rel}:{old.line}): " + COPY_HINT_FIX, tag))
            continue
        advice.append(_advice("smell", "", message,
                              f"call or extend `{old.qname}` ({old_rel}:{old.line}) instead of writing it again"
                              + (COPY_KEEP if row is not None else ""), tag))
    if unknown:
        notes.append(f"copy check: {len(unknown)} unit(s) repeat existing code but could not be placed as new or unchanged "
                     f"({', '.join(unknown[:4])}{f' +{len(unknown) - 4} more' if len(unknown) > 4 else ''}) - advice, not findings; "
                     "the code critic reads them")


# --- the environment rows ---------------------------------------------------------------------

CONFTEST_LEVELS = 5          # the folders from a test file upwards whose `conftest.py` is read
_CONFTEST_PARSED: dict = {}  # (path, mtime_ns, size) -> (PyFile or None, problem words): ONE parse of a conftest


def _same_folder(a: Path, b: Path) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def _shown(path: Path, project) -> str:
    """The project-relative posix spelling of a file (what a finding names), else the absolute one."""
    try:
        return Path(path).resolve().relative_to(Path(project).resolve()).as_posix()
    except (OSError, ValueError, TypeError):
        return Path(path).as_posix()


def _read_conftest(conftest: Path):
    try:
        stat = conftest.stat()
        key = (str(conftest), stat.st_mtime_ns, stat.st_size)
    except OSError:
        key = (str(conftest), 0, 0)
    if key not in _CONFTEST_PARSED:
        _CONFTEST_PARSED[key] = read_python(conftest)
    return _CONFTEST_PARSED[key]


def _conftest_files(path: Path, project=None) -> tuple:
    """`([(conftest path, PyFile), ...], notes)` - every `conftest.py` above one test file, the nearest first, at most
    `CONFTEST_LEVELS` folders (the 5th is read, the 6th is not). The ONE reader of the chain for the fixture names
    (`conftest_fixtures`) and for the fixture closure of the smell check (AR-13), with one parse cache.

    What it could not read is a note, never a clean bill (AR-28): a conftest that does not parse or cannot be read
    names itself, and a climb that stopped before the project root names the folder above which nothing was read."""
    rows, notes, visited = [], [], []
    folder = Path(path).parent
    for _ in range(CONFTEST_LEVELS):
        visited.append(folder)
        conftest = folder / "conftest.py"
        if conftest.is_file():
            parsed, problem = _read_conftest(conftest)
            if parsed is not None:
                rows.append((conftest, parsed))
            elif problem:
                notes.append(problem.replace(conftest.name, _shown(conftest, project), 1))
        if folder.parent == folder:
            return rows, notes
        if project is not None and _same_folder(folder, project):
            return rows, notes          # a conftest above the project is not in pytest's rootdir: foreign code
        folder = folder.parent
    if project is None or not any(_same_folder(v, project) for v in visited):
        notes.append(f"conftest above {_shown(visited[-1], project)} not read ({CONFTEST_LEVELS} levels); "
                     "a fixture defined higher up is not part of the smell check - the code critic reads it")
    return rows, notes


def conftest_fixtures(path: Path) -> set:
    """Fixture names from every `conftest.py` above one test file. A fixture a test asks for
    by argument name is almost never defined in the test file itself."""
    names: set = set()
    for _conftest, parsed in _conftest_files(path)[0]:
        names |= set(parsed.fixtures)
    return names


# --- the fixtures a test reaches (TQ1-16) -----------------------------------------------------------

def _fixture_alias(node) -> str:
    """The name a test asks a fixture by: `@pytest.fixture(name="x")` renames it, else the function's own."""
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Call):
            for keyword in decorator.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant) \
                        and isinstance(keyword.value.value, str):
                    return keyword.value.value
    return node.name


def _fixture_autouse(node) -> bool:
    return any(isinstance(d, ast.Call) and any(
        k.arg == "autouse" and isinstance(k.value, ast.Constant) and k.value.value is True for k in d.keywords)
        for d in node.decorator_list)


def _arg_names(node) -> list:
    args = node.args
    return [a.arg for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs) if a.arg != "self"]


def _usefixtures(exprs) -> list:
    """The names `pytest.mark.usefixtures("a", "b")` carries, anywhere inside these expressions."""
    out = []
    for expr in exprs:
        for sub in ast.walk(expr):
            if isinstance(sub, ast.Call) and (getattr(sub.func, "attr", None) == "usefixtures"
                                              or getattr(sub.func, "id", None) == "usefixtures"):
                out += [a.value for a in sub.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    return out


def _fixture_closure(pyfile, node, project=None) -> tuple:
    """`(entries, notes)`: the test and every fixture it reaches - the arguments of the test, `usefixtures` on the
    function, its class and the module, the autouse fixtures of its file and of its `conftest.py` chain - and, for each
    fixture, its own arguments in turn. An entry is `(owner PyFile, function node, rel or None, is_fixture)`; `rel` is
    None for what lives in the test's own file and the project-relative path of the conftest otherwise.

    A name is resolved the way pytest does: the test's file first, then the conftests from the nearest to the farthest;
    a fixture that asks for its own name (`def x(x)`) is resolved FARTHER than itself, and a fixture is never visited
    twice, so a circle ends. A name no file defines (a pytest builtin, a parameter, a plugin) is skipped here - the
    plugin case is the named residual of the check."""
    rows, notes = _conftest_files(pyfile.path, project)
    levels = [(None, pyfile)] + [(path, parsed) for path, parsed in rows]

    def lookup(name, after):
        for index, (_path, owner) in enumerate(levels):
            if index <= after:
                continue
            for fixture in owner.fixtures.values():
                if _fixture_alias(fixture) == name:
                    return index, fixture
        return None

    entries = [(pyfile, node, None, False)]
    asked = [(a, -1) for a in _arg_names(node)]
    for arg in _arg_names(node):          # the shape the check always had: a test function named by an argument
        other = pyfile.functions.get(arg)
        if other is not None and other is not node:
            entries.append((pyfile, other, None, False))
    exprs = list(getattr(node, "decorator_list", []))
    for cls in ast.walk(pyfile.tree):
        if isinstance(cls, ast.ClassDef) and any(sub is node for sub in ast.walk(cls)):
            exprs += list(cls.decorator_list)
    for stmt in pyfile.tree.body:
        if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets):
            exprs.append(stmt.value)
    asked += [(name, -1) for name in _usefixtures(exprs)]
    for _path, owner in levels:
        asked += [(_fixture_alias(f), -1) for f in owner.fixtures.values() if _fixture_autouse(f)]
    seen = set()
    while asked:
        name, after = asked.pop(0)
        found = lookup(name, after)
        if found is None:
            continue
        index, fixture = found
        if (index, id(fixture)) in seen:
            continue
        seen.add((index, id(fixture)))
        path, owner = levels[index]
        entries.append((owner, fixture, None if path is None else _shown(path, project), True))
        alias = _fixture_alias(fixture)
        asked += [(a, index if a == alias else -1) for a in _arg_names(fixture)]
        asked += [(n, -1) for n in _usefixtures(fixture.decorator_list)]
    return entries, notes


# --- a sleep that is not a poll with a ceiling (TQ1-16) ---------------------------------------------

_EXIT_NODES = (ast.Break, ast.Return, ast.Raise)
_LOOP_NODES = (ast.For, ast.AsyncFor, ast.While)
_SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _loop_exits(loop) -> list:
    """`[(statement, under an if)]` - the ways out of one loop: `break` of this loop (not of an inner one), `return`,
    `raise`; nothing inside a nested function."""
    found = []

    def visit(parent, under_if, inner_loop):
        for child in ast.iter_child_nodes(parent):
            if isinstance(child, _SCOPE_NODES):
                continue
            if isinstance(child, _EXIT_NODES) and not (isinstance(child, ast.Break) and inner_loop):
                found.append((child, under_if))
            visit(child, under_if or isinstance(child, ast.If), inner_loop or isinstance(child, _LOOP_NODES))

    visit(loop, False, False)
    return found


def _is_capped_poll(loop) -> bool:
    """A loop that waits for a condition and ends: a `for` that leaves under an `if` (`break` / `return` / `raise`), or
    a `while` whose condition compares (a deadline, a counter) or whose body has two ways out. `while True: sleep(1)`,
    `while not ready(): sleep(1)` and `for _ in range(3): sleep(2)` are not: nothing in them ends the wait on a
    condition or on a ceiling."""
    exits = _loop_exits(loop)
    if isinstance(loop, ast.While):
        return any(isinstance(n, ast.Compare) for n in ast.walk(loop.test)) or len(exits) >= 2
    return any(under_if for _node, under_if in exits)


def _bare_sleep(scope, allow_poll: bool = False):
    """The first call to a function named `sleep` in `scope` (`sleep(2)`, `time.sleep(DELAY)`, `asyncio.sleep(1)`, in a
    finalizer too), else None. By the AST, so a comment, a docstring or `not_a_sleep(2)` is not one. With `allow_poll`
    (a fixture) a call inside a capped poll is not bare; in a test body it still is (`test-code-patterns.md`: no
    hand-rolled polling there). Named residual: `from time import sleep as pause` is not seen."""
    parents = {}
    for parent in ast.walk(scope):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    for call in ast.walk(scope):
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if not ((isinstance(func, ast.Name) and func.id == "sleep")
                or (isinstance(func, ast.Attribute) and func.attr == "sleep")):
            continue
        if allow_poll:
            up, capped = parents.get(call), False
            while up is not None and up is not scope:
                if isinstance(up, _LOOP_NODES) and _is_capped_poll(up):
                    capped = True
                    break
                up = parents.get(up)
            if capped:
                continue
        return call
    return None


def _project_of(task_root):
    """The project a story lives in: the nearest folder above it holding the marker `qa-factory/config.json`, found by
    the ONE walk (`runtime_paths.nearest_project`, AR-4, AR-13), never by the depth of the story folder - the artifact
    root is configurable. None (a missed project, the allowed error) gives the `unknown` path of `_fixture_changed`."""
    from runtime_paths import nearest_project
    return nearest_project(task_root)


def _fixture_changed(task_root, project, rel: str, function: str) -> tuple:
    """`(answer, words)`, answer in `yes` / `no` / `unknown`: did the story change this conftest fixture?

    The measure is `test_novelty.measure_many` (the one reader of the story's base, AR-13) over the function of the
    conftest, against S0. Its direction is the one this gate needs: it errs only toward 'not unchanged', so a
    fixture the window did not touch may read `changed` when its conftest, a helper or `pytest.ini` did (the door is
    the fix text: say so in your digest), and never the other way round. `new` and `changed` are `yes`, `unchanged` is
    `no`; `unknown`, an exception, no story root, no project: `unknown`, which the caller turns into a hint, not a
    pass and not a block (FR-59: the declared safe default)."""
    if task_root is None or project is None:
        return "unknown", "no story root to read the base of"
    try:
        import test_novelty
        import test_repo_base
        result = test_novelty.measure_many(project, [{"test_rel": rel, "function": function}],
                                           base_record=test_repo_base.load(task_root))[0]
        value = result.get("value") if isinstance(result, dict) else None
        words = str(result.get("basis") or "") if isinstance(result, dict) else ""
    except Exception as exc:
        return "unknown", f"the measure failed ({type(exc).__name__})"
    if value in ("new", "changed"):
        return "yes", words
    if value == "unchanged":
        return "no", words
    return "unknown", words or "the measure gave no answer"


def fixture_names(files: list) -> set:
    """Every fixture the tests of this case could be using: the ones declared in their own
    files and the ones their `conftest.py` chain declares."""
    names: set = set()
    for pyfile in files:
        names |= set(pyfile.fixtures)
        names |= conftest_fixtures(pyfile.path)
    return {n for n in names if n not in BUILTIN_FIXTURES and len(n) > 2}


def project_integrations(task_root: Path) -> set:
    """The integration names the project's own config declares. A story lives at
    `<project>/qa-factory/artifacts/<TICKET>`, and the config beside it is read for names
    only — a project without one simply contributes no names."""
    config = _load(task_root.parent.parent / "config.json")
    names = set()
    for entry in ((config.get("environment") or {}).get("integrations") or []):
        if not isinstance(entry, dict):
            continue
        for key in ("name", "id", "service"):
            value = str(entry.get(key) or "").strip()
            if len(value) > 2:
                names.add(value)
    return names


def row_names(row: dict) -> list:
    """The names an unresolved row blames: the words of its `detail` and of its remedy."""
    remedy = row.get("remedy") if isinstance(row.get("remedy"), dict) else {}
    text = " ".join([str(row.get("detail") or ""), str(remedy.get("where") or ""),
                     str(remedy.get("change") or "")])
    out: list = []
    for token in DETAIL_NAME_RE.findall(text):
        if token not in out:
            out.append(token)
    return out


def check_environment(task_root: Path, manifest: dict, owned: list, texts: dict, parsed: dict,
                      findings: list, notes: list) -> None:
    """`blocked_by_env` rows: the fix, the names-only rule, and the fixture that is not a stand.

    TP1-15045 (22.09.2026) wrote both traps in one story. The automator FOUND the cause of
    a blocked partition — `customer-config.yaml:304-311`, `enabled: false` — and the manifest
    carried a paragraph, so the person read "blocked by the environment" instead of the one
    line that would have unblocked it. And a workflow-validation case was parked on the stand
    because the shared `assistant` fixture wanted a Jira tool and an integration that the
    case's own Then never mentions: the test's data choice, presented as the stand's fault.

    Only rows of the cases THIS dispatch owns are refused. A row written by an earlier version
    in a story in flight is a note — the window that wrote it is closed and cannot repair it."""
    integrations = project_integrations(task_root)
    cfg = C.case_config(task_root)  # once, not once per (row, owned case): B-013 performance
    for row in C.manifest_unresolved(manifest):
        if not isinstance(row, dict) or str(row.get("reason") or "") != BLOCKED_BY_ENV:
            continue
        case = str(row.get("case") or "")
        mine = any(C.case_matches(case, other, cfg=cfg) for other in owned) if case else False

        def record(message: str, fix: str, tag: str, _case=case, _mine=mine) -> None:
            if _mine:
                findings.append(_finding("environment", _case, message, fix, tag))
            else:
                notes.append(f"{_case or 'a case'}: {message} — a row this dispatch does not "
                             "own, so it is a note here, not a repair")

        remedy = row.get("remedy")
        if remedy is None:
            record(f"`{BLOCKED_BY_ENV}` with no `remedy` — the row says the stand is missing "
                   "something and never says what would put it there",
                   "add `remedy` to that unresolved[] row — {kind: flag|credential|data|"
                   "service, where: <file:lines, or the variable NAME>, change: <what to set>, "
                   "restart: <what to restart>} — and re-send the fragment through "
                   "manifest_put.py. Names only, never a credential value", "remedy-missing")
        else:
            for problem in C.remedy_errors(remedy):
                record(f"the `remedy` of this {BLOCKED_BY_ENV} row is not one: {problem}",
                       "correct that field in the unresolved[] row and re-send the fragment "
                       "through manifest_put.py", "remedy-" + _soft(problem)[:24])

        prose = str(row.get("detail") or "")
        if isinstance(remedy, dict):
            prose += " " + " ".join(str(remedy.get(field) or "") for field in
                                    (*C.REMEDY_FIELDS, "restart"))
        for key in secret_value_leaks(prose):
            record(f"the row carries a value for `{key}` — name the variable, never its value",
                   f"keep `{key}` and the file it belongs in; delete everything after the `=`. "
                   "An artifact is read by everyone this story is shown to", "secret-" + key)

        text = texts.get(case) or ""
        if not text:
            continue  # no approved case text here: the fixture question cannot be asked
        known = fixture_names(parsed.get(case) or [])
        soft_text = _soft(text)
        for name in row_names(row):
            what = "fixture" if name in known else ("integration" if name in integrations else "")
            if not what or _soft(name) in soft_text:
                continue
            record(f"the block is the {what} `{name}`, which the approved case never mentions "
                   "— the block comes from the test's own fixture, not from the case",
                   FIXTURE_FIX, "fixture-" + name)


# --- a stand block stands only on a run that shows the stand (RH2-9) --------------------------

def _evidence_names() -> list:
    """The exception names whose appearance in a failed run's own error line is evidence of the stand: the `names` of the
    `no_answer` rows of `stand-answers.json` that say `run_evidence: true` (read through `env_probe.stand_answers`, AR-1, AR-13)."""
    import env_probe
    names = []
    for row in env_probe.stand_answers()["no_answer"]:
        if row.get("run_evidence") is True:
            names += [str(n) for n in row.get("names") or [] if str(n)]
    return list(dict.fromkeys(names))


def _row_instances(row: dict, case: str, manifest: dict, blocks: list, cfg) -> list:
    """`[(label, spellings)]`: the instances a `blocked_by_env` row speaks about, each with every spelling it answers to. The
    names are `acceptance.blocked_row_names` (the one reader: `instance_ids`, the singular `instance_id`), with the aliases of the
    `tests[]` entry that holds them. A row that names none falls back to the `tests[]` entries covering its case AND the
    instances of the run blocks that cover it (a block keeps an instance that `manifest_put` moved out of `tests[]`)."""
    import acceptance as AC
    by_alias = {}
    for entry in C.manifest_tests(manifest):
        for alias in C.instance_id_aliases(entry, cfg):
            by_alias.setdefault(alias, entry)
    found = {}
    for name in AC.blocked_row_names(row):
        entry = by_alias.get(name)
        found[name] = set(C.instance_id_aliases(entry, cfg)) | {name} if entry else {name}
    if found or not case:
        return list(found.items())

    def covers(links) -> bool:
        return any(C.case_matches(case, link, cfg=cfg) for link in links)
    for entry in C.manifest_tests(manifest):
        if covers(C.manifest_test_links(entry, cfg)):
            found[C.test_instance_id(entry)] = set(C.instance_id_aliases(entry, cfg))
    for block in blocks:
        for result in block.get("results") if isinstance(block.get("results"), list) else []:
            iid = str(result.get("instance_id") or "") if isinstance(result, dict) else ""
            if iid and not any(iid in spellings for spellings in found.values()) and covers(C.manifest_test_links(result, cfg)):
                found[iid] = {iid}
    return list(found.items())


def _newest_run(blocks: list, spellings: set) -> tuple:
    """`(block, result row)` of the NEWEST run block (`blocks` is oldest first) that has a result row for any of `spellings`, else `(None, None)`."""
    for block in reversed(blocks):
        for result in block.get("results") if isinstance(block.get("results"), list) else []:
            if isinstance(result, dict) and str(result.get("instance_id") or "") in spellings:
                return block, result
    return None, None


def _run_facts(block: dict, result: dict, project) -> dict:
    """What the newest run of one instance shows, for `_stand_shown`: `summary` (its run summary, `{}` when unreadable),
    `refuted` (the PROJECT's timeout ended this test or the run: a `timeout` block of the summary, or the row's own
    `reason_code`), `timed` (the report ids a timeout block names) and `seen` (a few words for the refusal)."""
    import launch_check
    summary, read = {}, False
    evidence = block.get("evidence") if isinstance(block.get("evidence"), list) else []
    ref = next((str(e.get("summary")) for e in evidence if isinstance(e, dict) and e.get("summary")), "")
    if ref and project is not None:
        loaded = _load(Path(project) / ref)
        summary, read = loaded, bool(loaded)
    tblock = summary.get("timeout") if isinstance(summary.get("timeout"), dict) else {}
    own = result.get("reason_code") == launch_check.PROJECT_TIMEOUT_CODE
    refuted = own or tblock.get("how") in launch_check.PROJECT_TIMEOUT_HOWS
    failed = [f for f in summary.get("failed") or [] if isinstance(f, dict)]
    first = next((str(f.get("why")) for f in failed if f.get("why")), "") or next((str(h) for h in summary.get("error_head") or [] if h), "")
    status = block.get("execution_status") or summary.get("execution_status")
    if refuted:
        seen = tblock.get("sentence") or str(result.get("reason") or "the project's per-test timeout ended this test")
    else:
        seen = f"execution_status {status}, first line: {first[:160]}" if status else "no usable summary"
    return {"summary": summary, "read": read, "refuted": refuted, "own": own, "status": status, "seen": str(seen),
            "timed": set(tblock.get("tests") or []) if refuted else set()}


def _stand_shown(facts: dict, result: dict, names: list) -> bool:
    """Does the newest run show the stand? Any one of: E-a `execution_status` `env_blocked`; E-b a `stand_signal` on a run
    no timeout ended (a signal derived from a timed-out run is the timeout itself, F-4); E-c an exception name of the
    `run_evidence` rows as a whole word in the run's error lines. On a refuted run E-c reads ONLY the `failed[].why` row
    of this instance when a timeout did not end it: a hard kill dumps captured output and source lines between its
    banners, and a retry helper's `except <connection error>` source line there is not the stand (B-3)."""
    summary = facts["summary"]
    if facts["status"] == "env_blocked":
        return True
    if not facts["refuted"] and summary.get("stand_signal"):
        return True
    failed = [f for f in summary.get("failed") or [] if isinstance(f, dict)]
    if facts["refuted"]:
        lines = [] if facts["own"] else [str(f.get("why") or "") for f in failed
                                         if f.get("test") == result.get("test_id") and f.get("test") not in facts["timed"]]
    else:
        lines = [str(x) for x in (summary.get("error_head") or [])] + [str(f.get("why") or "") for f in failed] \
            + [str(x) for x in (summary.get("log_tail") or [])]
    return any(re.search(rf"\b{re.escape(name)}\b", line) for name in names for line in lines)


def _no_run_note(case: str, version: str) -> str:
    return (f"{case or 'a case'}: {BLOCKED_BY_ENV} with no recorded run (story started on {version or 'unknown'}) - not refused "
            f"for a story started before {ENV_EVIDENCE_SINCE}; run it to show the stand")


def check_env_evidence(task_root: Path, manifest: dict, owned: list, findings: list, notes: list) -> None:
    """A `blocked_by_env` row stands only on a run that shows the stand (RH2-9; run 14857: a test killed by the project's
    own pytest timeout was parked as "the stand never indexed", 28 minutes of a person's time).

    Per instance of the row (`_row_instances`) its NEWEST run block is read (a receipt measured on other bytes never counts), and
    the row stands only if EVERY named instance's newest run shows the stand (`_stand_shown`). A run that shows none is a
    finding in family `environment` (the person's word still passes it, `PASSABLE`). An instance with NO run: a finding when
    the story started on `ENV_EVIDENCE_SINCE` or later, a NOTE when it started earlier or the version is unknown (the lenient
    direction, FR-59: `pipeline.json` carries the story's start version, not the row's). A row of a case this dispatch does
    not own is a note in every branch (the window that wrote it is closed)."""
    import story_version
    rows = [r for r in C.manifest_unresolved(manifest) if isinstance(r, dict) and str(r.get("reason") or "") == BLOCKED_BY_ENV]
    if not rows:
        return
    blocks = [item["data"] for item in read_run_blocks(Path(task_root))[0]]
    project, cfg, names = _project_of(task_root), C.case_config(task_root), _evidence_names()
    version = story_version.plugin_version_of(_load(Path(task_root) / "pipeline.json"))
    since = not story_version.is_older(version, ENV_EVIDENCE_SINCE)
    for row in rows:
        case = str(row.get("case") or "")
        mine = any(C.case_matches(case, other, cfg=cfg) for other in owned) if case else False
        instances, refused, unrun = _row_instances(row, case, manifest, blocks, cfg), [], []
        for label, spellings in instances:
            block, result = _newest_run(blocks, spellings)
            if block is None:
                unrun.append(label)
                continue
            facts = _run_facts(block, result, project)
            if not _stand_shown(facts, result, names):
                refused.append((label, facts["seen"] + ("" if facts["read"] else " (its run summary could not be read)")))
        if instances and not refused and not unrun:
            continue
        if not refused and not since:
            notes.append(_no_run_note(case, version))
            continue
        if refused:
            inst, seen = ", ".join(label for label, _ in refused), "; ".join(why for _, why in refused)
            if unrun and since:     # a mixed row: say the un-run instances too, or the next refusal is a second round trip
                seen += f"; no recorded run: {', '.join(unrun)}"
        else:
            inst, seen = ", ".join(unrun) or (case or "this row"), "no recorded run"
        message = f"`{BLOCKED_BY_ENV}` with no environment evidence - the newest run of {inst} shows no stand fault: {seen}"
        if not mine:
            notes.append(f"{case or 'a case'}: {message} - a row this dispatch does not own, so it is a note here, not a repair")
            continue
        fix = ("A stand block stands only on a run that shows the stand: execution_status env_blocked, a STAND SIGNAL on a run no "
               f"timeout killed, or a connection refusal ({', '.join(names)}) in its error lines. Otherwise the red is your test's: "
               "fit it under the project's per-test timeout (your brief's Per-test timeout line) or give it the project's own "
               f"timeout marker, run it again with run_suite.py --mine {case}, and record the result; if you still hold it is the "
               "stand, say so in your digest with the control you ran - the conductor can lift this line with the person's "
               'words (waiver.py --stage S5 --block "no environment evidence").')
        findings.append(_finding("environment", case, message, fix, "env-evidence-missing"))


def case_plan_row(task_root: Path, case: str, text: str, entries: list) -> str:
    """The plan row this case discharges: its own file first (`Plan row:` / `plan_row:`), then
    whatever the manifest rows that prove it recorded. '' when nothing says."""
    match = PLAN_ROW_RE.search(text or "")
    if match:
        return match.group(1)
    path = find_case_file(task_root, case) if not text else None
    if path:
        match = PLAN_ROW_RE.search(path.read_text(encoding="utf-8", errors="replace"))
        if match:
            return match.group(1)
    for entry in entries or []:
        row = str(entry.get("plan_row") or "").strip()
        if row:
            return row
    return ""


ROW_FIELDS_TAG = "row-fields-missing"


def _row_fields_text(gaps: list, task_name: str) -> tuple:
    """(message, fix) of the one row-fields finding. `gaps` is `[(instance id, [(field, problem), ...]), ...]`."""
    import window_record as WR
    pairs = sum(len(fields) for _iid, fields in gaps)
    parts = []
    for iid, fields in gaps:
        groups: dict = {}
        for field, problem in fields:
            groups.setdefault(problem, []).append(field)
        parts.append(f"{iid}: " + ", ".join(f"{', '.join(names)} ({problem})" for problem, names in groups.items()))
    named = list(dict.fromkeys(field for _iid, fields in gaps for field, _problem in fields))
    by_hand = [f for f in named if WR.REQUIRED_ROW_FIELDS[f].filled_by == "automator"]
    by_marker = [f for f in named if WR.REQUIRED_ROW_FIELDS[f].filled_by != "automator"]
    legend = "; ".join(f"`{f}`: {WR.REQUIRED_ROW_FIELDS[f].what}" for f in named)
    fix = ""
    if by_hand:
        fix += ("fill " + ", ".join(f"`{f}`" for f in by_hand) + " now, in one fragment: the row form "
                "`manifest_from_tests.py` prints for this window, or "
                '{"tests": [{"instance_id": "<id>", "<field>": <value>}]} through '
                f"`manifest_put.py --task {task_name} --fragment <file>`; ")
    if by_marker:
        fix += (", ".join(f"`{f}`" for f in by_marker) + " is written by the marker, not by hand (a hand-written value "
                "would not carry the hash the plan's obligation has): put "
                '`qa(obligations=["<plan obligation id>"])` on the test and run `manifest_from_tests.py` again; ')
    fix += f"what each field holds - {legend}; a field present but empty counts as missing"
    message = (f"{len(gaps)} tests[] row(s) of this window miss {pairs} field(s) the S5 window record or the test run "
               "will refuse: " + "; ".join(parts))
    return message, fix


def check_row_fields(task_root: Path, manifest: dict, cases: list, findings: list, notes: list,
                     dispatch_id: str | None, cfg: dict | None = None, plan: list | None = None) -> None:
    """The fields every `tests[]` row of this dispatch's cases owes (`window_record.REQUIRED_ROW_FIELDS`), named
    BEFORE the window or the run refuses them one at a time (HF2-12, EP1-18 (a): the role learned `profile_id` and the
    window fields from the critic and the conductor, two extra dispatches). ONE finding for the whole run, every
    (row, field) pair in it, no truncation: the repair is one fragment, so the list is read once.

    `cfg` is the project's config.json (`hooklib.load_config()`), `plan` the plan's obligations (`contract.
    plan_obligations`): without them `profile_id` and `obligation_refs` are NOT demanded (the error direction is
    "not demanded": the gates behind this one stay as they are). A case handed to the person owes no obligation
    binding here, as in `check_obligations`. Rows speak only inside the dispatch's scope; an unscoped run
    (`dispatch_scope` is None - no dispatch, an unknown id, or two running) refuses nothing and says so in a note,
    because it would speak about rows of windows that closed before this rule existed.

    Family `manifest`, outside PASSABLE: no recorded word, `*` included, and no judge pass lifts it - it is a repair the
    author makes with one command (FR-4)."""
    scope = dispatch_scope(task_root, dispatch_id)
    if scope is None:
        # said only when there are rows it would have looked at: a story with no test row has nothing unchecked, and
        # its printed result stays the line it always was (`test_s5_precheck.py` K-C4 E-C8)
        if any(instances_of_case(manifest, case) for case in cases):
            notes.append("row fields not checked: no single dispatch scope")
        return
    import window_record as WR
    handed = {row["case"] for row in C.handed_tests(manifest)}
    owed: dict = {}  # id(row) -> the plan obligations of the cases it serves (a row may prove several cases)
    for case in cases:
        if case not in scope:
            continue
        entries = instances_of_case(manifest, case)
        plan_row = case_plan_row(task_root, case, "", entries) if plan and case not in handed else ""
        for entry in entries:
            owed.setdefault(id(entry), []).extend(ob for row, ob in plan or [] if plan_row and row == plan_row)
    gaps = []
    for entry in C.manifest_tests(manifest):
        if id(entry) not in owed:
            continue
        fields = WR.row_field_gaps(entry, cfg, owed[id(entry)])
        if fields:
            gaps.append((C.test_instance_id(entry) or "(a row with no instance_id)", fields))
    if gaps:
        message, fix = _row_fields_text(gaps, Path(task_root).name)
        findings.append(_finding("manifest", "", message, fix, ROW_FIELDS_TAG))


def check_obligations(task_root: Path, manifest: dict, cases: list, texts: dict,
                      handed: set, findings: list) -> None:
    """Every coverage obligation of the plan row a scoped case belongs to is bound, under the
    plan's own id, to an instance that proves that case.

    TP2-2553: the plan named `TS-1-O1`, every fragment the automator wrote named `OB-1`,
    and `coverage_contract.coverage_projection` joins by exact equality — so twelve green
    instances reported `unique_instances: 0` and nine coverage gaps, and window 2 spent two
    repair rounds on bindings that had never existed. Nothing before delivery said so. The
    window that can still fix it is this one, so the author is told here, by id and by case.

    A legacy plan (no schema-2 obligations) names none and is asked for none; a case handed to
    the person owes no binding, and a `manual-*` obligation is discharged by evidence the
    runner records, not by an automated instance."""
    plan = C.plan_obligations(task_root)
    if not plan:
        return
    bindings = [b for b in manifest.get("obligation_bindings") or [] if isinstance(b, dict)]
    unknown = C.unknown_obligation_ids(
        [str(b.get("obligation_id") or "") for b in bindings], task_root)
    known = C.plan_obligation_ids(task_root)
    named = ""
    if unknown:
        named = (f"; the manifest binds {', '.join(unknown)}, which the plan does not name — "
                 f"it names {', '.join(known)}")
    for case in cases:
        if case in handed:
            continue
        entries = instances_of_case(manifest, case)
        row = case_plan_row(task_root, case, texts.get(case, ""), entries)
        if not row:
            continue
        aliases = _covering_ids(manifest, case)
        for plan_row, obligation in plan:
            oid = str(obligation.get("obligation_id") or "")
            if plan_row != row or not oid:
                continue
            if str(obligation.get("decision") or "").startswith("manual-"):
                continue
            if any(str(b.get("obligation_id") or "") == oid
                   and aliases & {str(i) for i in b.get("instance_ids") or []} for b in bindings):
                continue
            findings.append(_finding(
                "obligations", case,
                f"{oid} ({case}) has no obligation binding — the projection will count it as "
                "a gap" + named,
                f"add obligation_bindings[] with instance_ids through manifest_put.py, "
                f"spelling the id exactly as the plan's `coverage_obligations[].obligation_id` "
                f"({oid}); manifest_put.py refuses any other spelling",
                # the tag carries the block word `manifest_put.py` names in its own refusal,
                # so ONE `waiver.py --stage S5 --block "obligation-id"` passes both.
                f"obligation-id-{oid}"))


def _words_for_pair(pipeline: dict, pair_at) -> tuple:
    """`(pipeline with the words that may pass a pair that came to exist at `pair_at`, the `at` of each
    stage-wide word left out)`. A STAGE-WIDE word (`match` exactly `changed-after-red`) covers only the
    pairs whose green run existed when it was given: it is compared with the word's `at`. A word naming
    a pair or a function, and `*`, is not compared. When either clock cannot be read the word is
    honoured, as before: a person's word is not thrown away over a missing timestamp."""
    from run_history import _parse_time
    moment = _parse_time(pair_at)
    kept, left_out = [], []
    for word in pipeline.get("stage_overrides") or []:
        said = _parse_time(word.get("at")) if isinstance(word, dict) else None
        broad = isinstance(word, dict) and str(word.get("match") or "").strip().lower() == CHANGED_AFTER_RED
        # A revoked broad word is no word: it is not reported as "left out" (it acts nowhere, `split_overridden` skips it); it stays in `kept`.
        if broad and not word.get("revoked_at") and moment is not None and said is not None and moment > said:
            left_out.append(str(word.get("at")))
        else:
            kept.append(word)
    return {**pipeline, "stage_overrides": kept}, left_out


def finding_line(finding: dict) -> str:
    """The ONE line a finding is printed as (after the `- `): `[<check> <id>] <message> — fix: <fix>`. The label
    carries the finding id, which is how the `WORDS_REFUSED_AT_SOURCE` line is tied to its finding, and the line is
    one physical line (the contract of `detector_verdict`). `passed_by_word` judges a word against this same text,
    so a word taken from the printed line matches here exactly when it matches the gate's record."""
    return DV.one_line(f"[{finding['check']} {DV.id_token(finding['id'])}] {finding['message']} "
                       f"— fix: {finding['fix']}")


def _by_tag(finding: dict) -> bool:
    return _finding_tag(finding).startswith(WORD_PASSABLE_TAGS)


def _passable(finding: dict) -> bool:
    """Can ANY recorded word pass this finding here? Only the families of `PASSABLE` and the tags of
    `WORD_PASSABLE_TAGS`; every other finding is a repair of the role and no word passes it, `*` included."""
    return finding["check"] in PASSABLE or _by_tag(finding)


def refusal_cause(finding: dict) -> str:
    """Why the source refused every recorded word for this finding, or `""` when it did not: `family` (not
    passable), or `predating` (a stage-wide word given before this pair's green run, marked by `passed_by_word`).
    Decided by `_passable`, not by what `passed_by_word` reached, so an early return or a failed `waiver`
    import cannot leave a refused finding without its line.

    One finding is not refused to a word, it WAITS for one (GW1-14): `then-remainder-unrecorded-<n>` is satisfied by
    the person's `then handed:` word for that Then (read by identifier in `check_then_remainders`), so it carries no
    refusal line; every other `then-remainder-*` finding is a repair and keeps the `family` line."""
    if _finding_tag(finding).startswith(THEN_REMAINDER_WAITS):
        return ""
    if not _passable(finding):
        return "family"
    return "predating" if finding.get("refused") == "predating" else ""


def passed_by_word(task_root: Path, findings: list, notes: list) -> list:
    """Drop the environment and obligation findings a person has already answered with
    `waiver.py --stage S5 --block ...`, and say in a note which words passed which.

    A check stops a silent pass, never an informed one. The exit gate does not judge a word over this
    output again: every finding is printed with its line, the header says the words were judged here
    (`detector_verdict.WORDS_AT_SOURCE`), and a finding refused to every word carries a
    `WORDS_REFUSED_AT_SOURCE` line (see `report`). `manifest_put.py` reads the same overrides for the
    same reason: one recorded word about an obligation id passes both the writer and this check, not
    one of them.

    The `changed-after-red` findings are passable by TAG (`WORD_PASSABLE_TAGS`) although their
    family, `oracle`, is not: until B-194 `waiver.py --block "changed-after-red"` matched nothing,
    because this function skipped the family. Each finding is judged alone, so a word for this tag
    leaves every other finding of the run — other oracle findings included — standing.

    `split_overridden` matches a word by WHOLE WORDS (`contract.names_whole`) over the finding's id, message and fix, and this
    finding's id carries the case id: a word given for ANOTHER finding of the case (`--block
    "TP1-13797_TC_002"`) passed it in silence (t-108, critic). So a finding passable by tag is
    passed only by a word whose `match` names the tag (`changed-after-red`, or the whole finding
    id, which contains it) or is `*` — every other word is not shown to `split_overridden` for it."""
    by_tag, passable = _by_tag, _passable
    if not any(passable(f) for f in findings):
        return findings
    try:
        from waiver import split_overridden
    except Exception:
        return findings
    pipeline = _load(task_root / "pipeline.json")
    # The words that name the tag (or are `*`); the rest of `stage_overrides[]` is unchanged for
    # every other finding.
    tag_words = {**pipeline, "stage_overrides": [
        word for word in pipeline.get("stage_overrides") or []
        if isinstance(word, dict) and (str(word.get("match") or "").strip() == "*"
                                       or any(tag in str(word.get("match") or "").lower()
                                              for tag in WORD_PASSABLE_TAGS))]}
    out = []
    for finding in findings:
        if not passable(finding):
            out.append(finding)
            continue
        # the old text stays in front so a word recorded against it keeps matching (FR-7); the printed line
        # is added so a word copied from what the role was shown matches too
        text = f"{finding['id']} {finding['message']} {finding['fix']} {finding_line(finding)}"
        words, predating = tag_words, []
        if by_tag(finding):
            words, predating = _words_for_pair(tag_words, finding.get("pair_at"))
        blocking, passed = split_overridden([text], words if by_tag(finding) else pipeline, "S5")
        if blocking and predating:
            # an informed pass covers what the person saw: the stage-wide word was given before this
            # pair's green run existed, so it stops again - and says why, instead of looking ignored
            # `refused` is read by `report`, which prints the `WORDS_REFUSED_AT_SOURCE ... predating` line;
            # the text names the word as it was recorded (its `match`), not the constant
            given = next((str(w.get("match")).strip() for w in tag_words["stage_overrides"]
                          if str(w.get("at")) == predating[0]), CHANGED_AFTER_RED)
            out.append(dict(finding, refused="predating", message=finding["message"] + (
                f"; the stage-wide word `{given}` (given {predating[0]}) predates this run, so it "
                "does not pass this pair - a person sees it now")))
        elif blocking:
            out.append(finding)
        else:
            notes.append(f"{finding['case'] or 'a case'}: {finding['message']} — passed by "
                         f"the person's word: {passed[0]['decision']}")
    return out


def _flag_word_passed(pairs: list, standing_ids: set) -> None:
    """`passed_by_word` on every pair: true when it had a finding and a person's word removed it.
    A pair with a record never had one (the record answered it), so it is never marked."""
    for pair in pairs:
        pair["passed_by_word"] = bool(pair.get("finding_id")) and pair["finding_id"] not in standing_ids
        pair.pop("finding_id", None)


def word_passed_pairs(task_root, changes: dict, cases: list) -> list:
    """The pairs of `changes` (what `expectation_changes` returned) that a person's word passed,
    each marked `passed_by_word: true` in place; every other pair is marked false. One helper for
    every reader that has to treat such a pair apart - the window record, the critic's brief - so
    that none of them re-asks what a person already answered (P13, builder-rules 8).

    It is the S5 exit's own logic, not a second reading: the finding of each owed pair without a
    record is written (`check_expectation_changes`) and `passed_by_word` decides which of them a
    recorded word (`waiver.py --stage S5`, the pair's own tag or the stage-wide one) removes. Reads
    `pipeline.json`, writes nothing (FR-45). The error direction is the safe one: when it cannot
    tell, no pair is marked (it stays owed) and the reason is added to `changes["unmeasured"]`,
    where the window and the brief print it (FR-41). Returns the marked pairs."""
    pairs = [p for p in (changes.get("pairs") or []) if isinstance(p, dict)]
    try:
        root = Path(task_root)
        findings: list = []
        check_expectation_changes(root, changes, list(cases or []), findings, [])
        _flag_word_passed(pairs, {f["id"] for f in passed_by_word(root, findings, [])})
    except Exception as exc:
        for pair in pairs:
            pair["passed_by_word"] = False
            pair.pop("finding_id", None)
        if isinstance(changes.get("unmeasured"), list):
            changes["unmeasured"].append(
                f"whether a person's word passed a test changed after its red run could not be read "
                f"({type(exc).__name__}: {exc}); every such pair is left to judge")
    return [p for p in pairs if p.get("passed_by_word")]


# The finding families a judge may downgrade, and the question that does it. Each row is
# (check, tag prefix, judgment, refusal id). After X7-2 the one family is a Then contradiction (`bindings contradicted-`): the smell
# and relative-oracle findings are ADVICE for the code critic now, and `case-is-oracle` / `dispute-unstated` are shape refusals a
# judge has nothing to decide on. A downgrade is never silence: the finding becomes a HINT the author still reads, and
# `judged_refusal` journals the row so the gate brief shows the person every block the judge let through.
JUDGED_FINDINGS = (
    ("bindings", "contradicted-", "code_assert_matches_then", "s5_then_contradiction"),
)
FINDING_AT_RE = re.compile(r"([\w.\-]+\.py):(\d+)")
FINDING_FN_RE = re.compile(r"([\w.\-]+\.py): `([A-Za-z_]\w*)`")
FINDING_THEN_RE = re.compile(r"Then (\d+) of (\S+)")


def _finding_tag(finding: dict) -> str:
    """The tag `_finding` appended. Split on the left twice: a tag carries `file.py:79`."""
    parts = str(finding.get("id") or "").split(":", 2)
    return parts[2] if len(parts) > 2 else ""


def _pyfiles(parsed: dict, case: str = "") -> dict:
    """This case's parsed files, by base name. Scoped to the case on purpose: a state built
    from every file of the window is the "id inside a large state" the judge answers worst."""
    groups = [(parsed or {}).get(case) or []] if case in (parsed or {}) else list((parsed or {}).values())
    out = {}
    for files in groups:
        for pyfile in files or []:
            out.setdefault(pyfile.path.name, pyfile)
    return out


def _enclosing(pyfile, lineno: int) -> tuple:
    """The function that contains this line, else a window around it."""
    best = None
    for node in ast.walk(pyfile.tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.lineno <= lineno <= getattr(node, "end_lineno", node.lineno):
            if best is None or node.lineno > best.lineno:
                best = node
    if best is not None:
        return best.name, pyfile.source(best)
    window = pyfile.lines[max(lineno - 4, 0):lineno + 8]
    return "", "\n".join(window)


def _judge_plan(finding: dict, task_root: Path, parsed: dict, texts: dict):
    """(state, judgment, refusal) for a finding a judge may downgrade, else None.

    One finding is one small state: the code the rule was raised against and the Then it is
    measured by. A finding whose code cannot be found is never put to the judge - the model
    would then answer about the message, which is the rule's own words."""
    tag = _finding_tag(finding)
    if tag.startswith(NEVER_JUDGED_TAGS):
        return None  # never put to a judge: `changed-after-red` is a fact about two runs (R9)
    row = next((r for r in JUDGED_FINDINGS
                if r[0] == finding.get("check") and tag.startswith(r[1])), None)
    if row is None:
        return None
    _check, _prefix, judgment, refusal = row
    case = str(finding.get("case") or "")
    files = _pyfiles(parsed, case)
    name, code = "", ""
    at = FINDING_AT_RE.search(finding.get("message") or "")
    named = FINDING_FN_RE.search(finding.get("message") or "")
    if at and at.group(1) in files:
        name, code = _enclosing(files[at.group(1)], int(at.group(2)))
    elif named and named.group(1) in files:
        pyfile = files[named.group(1)]
        node = pyfile.functions.get(named.group(2)) or pyfile.fixtures.get(named.group(2))
        if node is not None:
            name, code = named.group(2), pyfile.source(node)
    clauses = then_clauses(texts.get(case) or "")
    wanted = FINDING_THEN_RE.search(finding.get("message") or "")
    if wanted:
        number = int(wanted.group(1))
        clauses = [c for c in clauses if c[0] == number] or clauses
    if not code:  # the oracle checks speak about the case's tests as a whole
        code = "\n\n".join(pyfile.source(node) for pyfile in files.values()
                           for node in pyfile.functions.values())[:7000]
    if not code:
        return None
    then = "\n".join(f"{case} Then {n}: {t}" for n, t in clauses)[:2400]
    state = {"test": {"file": (at or named).group(1) if (at or named) else "",
                      "function": name, "code": code[:7000]},
             "case": {"ids": [case] if case else [], "then": then},
             "code": code[:7000],
             "finding": {"message": finding.get("message"), "fix": finding.get("fix")}}
    return state, judgment, refusal


def passed_by_judge(task_root: Path, findings: list, hints: list, notes: list,
                    parsed: dict | None = None, texts: dict | None = None) -> list:
    """Downgrade to a hint the smell / Then-contradiction / oracle findings the judge says do
    not apply to THIS code — `judge.mode: on` only, and only for the families above.

    The same seam as `passed_by_word` one function up, and for the same reason: a check stops
    a silent pass, not an informed one. Here the informed party is a registered question whose
    `true` means "the failure mode this rule describes cannot happen in this code"; it is
    asked per finding over that finding's own code, it never fires under `provider: none` or
    in `shadow`, and what it passes stays visible as a hint and as a `judge.passes()` row.
    A judged refusal of FORM or DIAGNOSIS only: nothing here lifts a gate or a safety rule."""
    if not findings:
        return findings
    try:
        import judge
    except Exception:
        return findings  # a judge that cannot be imported is not a reason to fail a check
    cfg = judge.settings(task_root)
    if not judge.active(cfg):
        return findings
    kept = []
    for finding in findings:
        plan = _judge_plan(finding, task_root, parsed or {}, texts or {})
        if plan is None:
            kept.append(finding)
            continue
        state, judgment, refusal = plan
        verdict = judge.judged_refusal(refusal, judgment, state, ticket=Path(task_root).name,
                                       stage="S5", project_root=task_root, cfg=cfg)
        if not verdict["passed"]:
            if verdict.get("note"):  # shadow: what it WOULD have passed, for the calibration
                notes.append(f"{verdict['note']}: {str(finding.get('message'))[:140]}")
            kept.append(finding)
            continue
        hints.append(dict(finding, level="hint", judge=verdict["note"]))
        notes.append(f"{finding['case'] or 'a case'}: {finding['message']} — downgraded to a "
                     f"hint by the judge ({verdict['note']}); it is still yours to read, and "
                     "the gate brief lists every block the judge let through")
    return kept


# --- a window against its plan (SC1-14 B2) -----------------------------------------------------

# The `deviations[].from` kinds (vocabulary `plan_deviation_kinds`) that DECLARE each difference the code can see. A difference with
# no declaring row is the finding "undeclared deviation"; with one it is the author's decision, which the critic of the window reads.
DECLARES = {"identity": ("file", "function"), "missing": ("file", "function", "remainder"), "shape": ("shape",),
            "count": ("count",), "remainder": ("remainder",)}


def _plan_finding(case: str, message: str, fix: str, tag: str) -> dict:
    return _finding("plan", case, message, fix, tag)


def _state_view(task_root: Path) -> dict:
    """The controller's state view as `s5_plan.mode` reads it: `{"dispatches": {id: record}}`. A 0.7.4 view carried a LIST of
    records; it is keyed here so an old story is read as before and is never refused for its shape."""
    raw = _load(task_root / "state" / "controller.json").get("dispatches")
    rows = list(raw.values()) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    return {"dispatches": {str(d.get("id") or d.get("dispatch_id") or index): d for index, d in enumerate(rows) if isinstance(d, dict)}}


def dispatch_record(task_root: Path, dispatch_id: str | None):
    """The state-view record of one dispatch, or None (no id, or no such record)."""
    if not dispatch_id:
        return None
    for record in _state_view(task_root)["dispatches"].values():
        if str(dispatch_id) in {str(record.get("id")), str(record.get("dispatch_id"))}:
            return record
    return None


# R7 (t-1508, AR-13): the reason an S7 repair round registers its dispatch with. The writer (`story_run.s7_round`) and this
# reader share this word - the literal `S7 fix` once lived in both files. A reorder round's reasons (`S7 reorder: ...`, `S7 reorder
# review: ...`, the carrier is `s7_reorder.AUTHOR_REASON` / `REVIEW_REASON`, read by nobody else) never start with `S7 fix`; nor does
# the critic's `S7 repair review: ...` (`s7_reorder.REPAIR_REVIEW_REASON`): the
# reorder round is where the order of the asserts behind a test's own red is the work, so its dispatch hears those words as
# findings (K-R5-10); `is_s7_fix_round` is False for all three.
S7_FIX_PREFIX = "S7 fix"


def is_s7_fix_round(task_root: Path, dispatch_id: str | None) -> bool:
    """Is this dispatch an S7 repair round of the driver (`rework` reason `S7 fix: <test> - verdict ...`)? False for no
    record, no reason, any other reason (the `reorder` round and its review, `S7 reorder: ...` / `S7 reorder review: ...`, a
    window, a plan): the earlier, stricter path."""
    record = dispatch_record(task_root, dispatch_id)
    if record is None:
        return False
    pattern = r"^\s*" + re.escape(S7_FIX_PREFIX) + r"\b"          # built per call: the constant is the one carrier of the words
    return bool(re.match(pattern, str(record.get("reason") or record.get("rework_reason") or ""), re.IGNORECASE))


def is_plan_dispatch(task_root: Path, dispatch_id: str | None) -> bool:
    """Is this dispatch of the plan kind (`controller.s5_part_of`, the one reader of the kind)? False for no record: the earlier
    path is the one an unknown dispatch always took."""
    record = dispatch_record(task_root, dispatch_id)
    if record is None:
        return False
    import controller as CT
    return CT.s5_part_of(record) == "plan"


def plan_result(task_root: Path, dispatch_id: str | None = None) -> dict:
    """The result of a PLAN dispatch, in the shape of `run`: the findings of `s5_plan.check_report`, all at once (the one
    survivor of "the plan has no gap", AR-15), each as a finding of the `plan` family; no manifest is read. A plan that cannot be
    read is a finding naming its door, never a pass (AR-28)."""
    import s5_plan as SP
    door_text = (f"repair the rows named in {SP.PLAN_REL}, then run `python scripts/s5_plan.py --task {Path(task_root).name} --check` "
                 "again")
    try:
        import controller as CT
        texts, notes = SP.check_report(task_root, CT.Controller(task_root))
    except SP.PlanUnreadable as exc:
        texts, notes = [f"plan: {exc}"], []
    findings = []
    for text in texts:
        message, _sep, fix = str(text).partition(" — fix: ")
        findings.append(_plan_finding("", message, fix or door_text, "plan-" + hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:8]))
    # The grouping hint: advice about the shape the author chose, so it never moves `ok` or the findings (FR-4). The plan is read
    # for it by the one helper (`hint_rows`); a plan that is absent or unreadable has its finding already, any other failure is a
    # note that says the hints were not checked (AR-28), not a crash and not a pass.
    rows, why = SP.hint_rows(task_root)
    notes = [str(n) for n in notes] + ([f"not checked: the grouping hints of the plan ({why})"] if why else [])
    hints = [_hint("plan", row["case"], row["message"], row["fix"], row["tag"]) for row in rows]
    return {"ok": not findings, "findings": findings, "hints": hints, "notes": notes, "cases": [],
            "expectation_changes": {"pairs": [], "unmeasured": []}, "unchecked": [], "plan": True}


def _file_key(text) -> str:
    key = str(text or "").strip().replace("\\", "/")
    while key.startswith("./"):
        key = key[2:]
    return key


def _same_file(task_root: Path, left, right) -> bool:
    if _file_key(left) == _file_key(right):
        return True
    found = (resolve_test_file(task_root, _file_key(left)), resolve_test_file(task_root, _file_key(right)))
    return bool(found[0] and found[1] and found[0] == found[1])


def _function_of(entry: dict) -> str:
    """The test function a manifest row names, without its parameter: the field the id is derived from, else the id itself."""
    named = C.function_name(entry.get("test_function") or entry.get("function") or entry.get("test")
                            or entry.get("selector") or entry.get("marker"))
    return named or C.function_name(C.test_instance_id(entry))


def _test_key(file, function) -> str:
    return f"{_file_key(file)}::{C.function_name(function)}"


def _declared(rows: list, kinds: tuple, *names, planned: bool = False) -> bool:
    """Does a `deviations[]` row of one of `kinds` name THE test the finding is about (`file::function`, or the plan's `T-n`)?
    A name is compared as `file::function` without a parameter, slashes alike. The names are the carrier of ONE finding - never
    the names of other tests (SC1-14 fix Y, B-2: a row excuses exactly the test it names). `planned=True`: the finding is about a
    PLANNED test the manifest lacks, so a rename/move row names it in `planned` (its `test` is the new side), and a remainder or
    removal row names it in `test`. A row naming no test (or none of these) excuses nothing, as before."""
    wanted = {_file_key(str(n).split("[", 1)[0]) for n in names if n}
    fields = ("test", "planned") if planned else ("test",)
    return any(isinstance(row, dict) and row.get("from") in kinds
               and any(_file_key(str(row.get(f) or "").split("[", 1)[0]) in wanted for f in fields) for row in rows)


class _Window:
    """One window's conformance run (SC1-14 B2): the slice, the manifest, the form's rows, and one method per check. Split out of
    `_conform` with no change of behaviour (fix Y, F-13) except the scoping of the C3 `_declared` calls (B-2)."""

    def __init__(self, task_root: Path, manifest: dict, piece: dict, rows: dict, findings: list, notes: list):
        self.task_root, self.manifest, self.rows, self.findings, self.notes = task_root, manifest, rows, findings, notes
        self.cfg = C.case_config()
        self.asked = list(piece.get("asked") or [])
        self.piece = piece
        self.tests = [t for t in piece.get("tests") or [] if isinstance(t, dict)]
        self.deviations = [r for r in rows.get("deviations") or [] if isinstance(r, dict)]
        self.all_instances = C.manifest_tests(manifest)
        self.covering = [e for e in self.all_instances if any(C.entries_for_case([e], case, self.cfg) for case in self.asked)]
        self.planned_keys = {_test_key(t.get("file"), t.get("function")) for t in self.tests}
        self.first = self.asked[0] if self.asked else ""
        self.unmatched_origin: list = []

    def fix_dev(self, kind: str = "") -> str:
        text = ("or declare it: add a row to `deviations` of your form - test: <file::function>, from: <one of "
                "vocabulary.plan_deviation_kinds>, planned: <file::function or T-n of the planned test>, reason: <= 80 characters")
        return text.replace("<one of vocabulary.plan_deviation_kinds>", kind) if kind else text

    def add(self, case: str, message: str, fix: str, tag: str) -> None:
        self.findings.append(_plan_finding(case, message, fix, tag))

    def declared(self, kinds: tuple, key: str, tid: str) -> bool:
        return _declared(self.deviations, kinds, key, tid)

    def check_window(self) -> None:
        for case in self.piece.get("missing") or []:
            self.notes.append(f"{case}: not in the plan, so its conformance is not checked")
        for test in self.tests:
            self.one_test(test)
        if self.unmatched_origin:
            self.notes.append(f"C4: no scope row of the form names an instance of {', '.join(self.unmatched_origin)} with its `origin`: not checked")
        self.c3_unplanned()
        self.c12()

    def one_test(self, test: dict) -> None:
        tid, key = str(test.get("id")), _test_key(test.get("file"), test.get("function"))
        mine = [c for c in (str(x) for x in test.get("cases") or []) if c in self.asked]
        where = f"test {tid} ({key})"
        matched = [e for e in self.all_instances if _function_of(e) == C.function_name(test.get("function"))
                   and _same_file(self.task_root, e.get("file"), test.get("file"))]
        if not matched:
            self.c3_missing(tid, key, mine, where)
            return
        ids = {a for e in matched for a in C.instance_id_aliases(e, self.cfg)}
        self.c1(test, tid, key, mine, where, matched)
        self.c2(test, tid, key, where, ids)
        self.c5(test, tid, key, mine, where, matched)
        self.c7(test, tid, key, mine, where, matched)
        self.c4(test, tid, key, mine, where, ids)

    def c3_missing(self, tid: str, key: str, mine: list, where: str) -> None:
        """C3: the planned test is not in the manifest (or lives under another name). Excused only by a row that names THIS planned test."""
        if _declared(self.deviations, DECLARES["missing"], key, tid, planned=True):
            return
        self.add(mine[0] if mine else self.first,
                 f"undeclared deviation (C3): the plan has {where} for {', '.join(mine)}; the manifest has no test with that file and function",
                 "write the planned test, " + self.fix_dev(), f"c3-missing-{tid}")

    def c1(self, test: dict, tid: str, key: str, mine: list, where: str, matched: list) -> None:
        """C1: an instance of it names the cases it proves."""
        kinds = tuple(DECLARES["identity"] + DECLARES["missing"] + DECLARES["shape"] + DECLARES["count"])
        for case in mine:
            if any(C.entries_for_case([e], case, self.cfg) for e in matched) or self.declared(kinds, key, tid):
                continue
            self.add(case, f"undeclared deviation (C1): {where} is planned for {case}, and no manifest instance of it lists {case} in `covers`",
                     "add the case to the instance's `covers` through manifest_put.py, " + self.fix_dev(), f"c1-{tid}-{case}")

    def c2(self, test: dict, tid: str, key: str, where: str, ids: set) -> None:
        """C2 (and C13 remainder): every planned Then is bound to an assertion in the planned test."""
        for ref in (str(r) for r in test.get("thens") or []):
            case, _hash, number = ref.partition("#")
            if case not in self.asked:
                continue
            bound = [b for b in bindings_of_case(self.manifest, case, self.cfg) if C.then_number(b.get("then")) == C.then_number(number)]
            owned = [b for b in bound if str(b.get("instance_id") or "") in ids]
            if any(str(b.get("status") or "covered") != "unresolved" and b.get("assertion_ref") for b in owned):
                continue
            if owned and all(str(b.get("status") or "") == "unresolved" for b in owned):     # moved to a remainder
                if not self.declared(DECLARES["remainder"], key, tid):
                    self.add(case, f"undeclared deviation (C13): Then {number} of {case} is planned in {where} and recorded as a remainder",
                             "bind it to an assertion of the planned test, " + self.fix_dev("remainder"), f"c13-remainder-{tid}-{case}-{number}")
                continue
            self.add(case, f"Then {number} of {case} is planned in {where} and has no `then_bindings` row naming an instance of it with an `assertion_ref` (C2)",
                     f"bind the Then to the planned test and its assertion line in the fragment ({FRAGMENT_ROAD}), or change the plan through a deviation row",
                     f"c2-{tid}-{case}-{number}")

    def c5(self, test: dict, tid: str, key: str, mine: list, where: str, matched: list) -> None:
        shapes = sorted({str(e.get("shape")) for e in matched if e.get("shape")} - {str(test.get("shape"))})
        if shapes and not self.declared(DECLARES["shape"], key, tid):
            self.add(mine[0] if mine else self.first,
                     f"undeclared deviation (C5): {where} is planned as `{test.get('shape')}` and the manifest says `{', '.join(shapes)}`",
                     "tag the test with the planned shape in its `qa(...)` marker, " + self.fix_dev("shape"), f"c5-{tid}")

    def c7(self, test: dict, tid: str, key: str, mine: list, where: str, matched: list) -> None:
        params = test.get("params")
        if isinstance(params, int) and not isinstance(params, bool):
            if len(matched) != params and not self.declared(DECLARES["count"], key, tid):
                self.add(mine[0] if mine else self.first,
                         f"undeclared deviation (C7): {where} is planned with {params} parameter(s) and the manifest holds {len(matched)} instance(s)",
                         "make the counts agree, " + self.fix_dev("count"), f"c7-{tid}")
        elif len(matched) > 1:
            self.notes.append(f"{where}: {len(matched)} instances and the plan gave no `params`: the count was not checked")

    def c4(self, test: dict, tid: str, key: str, mine: list, where: str, ids: set) -> None:
        expected = {"extend": ("changed", "reused"), "reuse": ("changed", "reused"), "new": ("new",)}.get(str(test.get("shape")))
        found = {self.rows.get("origins", {}).get(a) for a in ids} - {None}
        if expected and not found:
            self.unmatched_origin.append(tid)
        elif expected and not found <= set(expected) and not self.declared(DECLARES["shape"], key, tid):
            self.add(mine[0] if mine else self.first,
                     f"undeclared deviation (C4): {where} is planned as `{test.get('shape')}` (origin {' or '.join(expected)}) and the form says origin {', '.join(sorted(found))}",
                     "correct the `origin` of the scope row, " + self.fix_dev("shape"), f"c4-{tid}")

    def c3_unplanned(self) -> None:
        """C3: a test the plan does not have. Excused only by a row whose `test` names THAT test."""
        for entry in self.covering:
            key = _test_key(entry.get("file"), _function_of(entry))
            if key not in self.planned_keys and not _declared(self.deviations, DECLARES["identity"], key):
                self.add(self.first, f"undeclared deviation (C3): the manifest has test {key}, which the plan does not have for {', '.join(self.asked)}",
                         "plan it or remove it, " + self.fix_dev(), "c3-unplanned-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:8])

    def c12(self) -> None:
        """C12 (presence): a row for every remark."""
        import s5_plan as SP
        for gap in SP.remark_rows_missing(self.piece.get("remarks") or [], self.rows.get("plan_remarks")):
            self.add(self.first, f"plan remark {gap} has no row, or more than one, in `plan_remarks` of the form (C12)",
                     f"write exactly one row for {gap}: id: {gap}, row: <applied or not_applicable>, reason: <= 80 characters", "c12-" + gap)


def _conform(task_root: Path, manifest: dict, piece: dict, rows: dict, findings: list, notes: list) -> None:
    """The checks of a window against ITS slice of the plan (`piece`: `s5_plan.window_slice`), C1-C5, C7, C12, C13. `rows` are the
    window form's words: `plan_remarks`, `deviations`, `origins` ({instance id: origin}). C8-C10 stay where they are (AR-15)."""
    _Window(task_root, manifest, piece, rows, findings, notes).check_window()


def check_plan_conformance(task_root, manifest: dict, cases: list, findings: list, notes: list, dispatch_id: str | None = None) -> None:
    """A window dispatch against its plan (SC1-14 B2). ONLY when the story's S5 is on the plan form (`s5_plan.mode`): `legacy` is a
    note, not a finding (E5, E35); `planned` with a plan that is missing or unreadable is a finding (AR-28). The tests of the window
    are the slice `s5_plan.window_slice(cases=<the dispatch's scope>)` - the controller's cut, never recomputed here. A run with no
    dispatch record has no scope to check against and says so. The window's words (`plan_remarks`, `deviations`, `origin` of its
    scope rows) are read from its form `work/handoffs/<dispatch>.yaml`; one that exists and cannot be read is a finding."""
    import s5_plan as SP
    task_root = Path(task_root)
    if not dispatch_id:
        return      # no window is named: conformance is a window's, and the printed result of such a run stays what it was (K-C4 E-C8)
    if dispatch_record(task_root, dispatch_id) is None or not cases:
        notes.append("no S5 plan conformance: this run names no dispatch record to take the window's cases from, so conformance is not checked")
        return
    state = _state_view(task_root)
    try:
        form, why = SP.mode(task_root, state)
        if form == SP.LEGACY:
            notes.append(f"no S5 plan for this story ({why}): conformance not checked")
            return
        if SP.load(task_root) is None:
            findings.append(_plan_finding("", f"the story's S5 is on the plan form and {SP.PLAN_REL} does not exist ({why}), so the window cannot be checked against it",
                                          "restore the plan (the plan dispatch writes it) or ask the conductor for `plan before windows`", "plan-missing"))
            return
        piece = SP.window_slice(task_root, cases=list(cases), state=state)
    except SP.PlanUnreadable as exc:
        findings.append(_plan_finding("", f"the plan cannot be read for this window: {exc}", "repair what is named, then run the check again", "plan-unreadable"))
        return
    rows = {"plan_remarks": None, "deviations": [], "origins": {}}
    from story_step import FORM_REL
    path = task_root / FORM_REL.format(dispatch_id=dispatch_id)
    if path.exists():
        import handoff_check
        try:
            data = handoff_check.form_view(path).data
        except (OSError, ValueError) as exc:
            findings.append(_plan_finding("", f"the window's form {FORM_REL.format(dispatch_id=dispatch_id)} cannot be read ({exc}), so its remark rows and declared deviations cannot be counted",
                                          "repair the form (handoff_check.py --file <form>), then run the check again", "form-unreadable"))
            return
        for name in ("plan_remarks", "deviations"):
            value = data.get(name) if isinstance(data, dict) else None
            if value is not None and not isinstance(value, list):
                findings.append(_plan_finding("", f"`{name}` of the window's form is not a list", f"write `{name}` as a list of rows (or the empty list)", "form-" + name))
                value = None
            rows[name] = value if name == "plan_remarks" else (value or [])
        scope = data.get("scope") if isinstance(data, dict) else None
        rows["origins"] = {str(r.get("id")): r.get("origin") for r in scope or [] if isinstance(r, dict) and r.get("origin")}
    else:
        notes.append("the window's form is not written yet: no plan_remarks row and no deviation row could be counted")
    _conform(task_root, manifest, piece, rows, findings, notes)


# --- entry points -----------------------------------------------------------------------------

def run(task_root, dispatch_id: str | None = None) -> dict:
    task_root = Path(task_root)
    manifest = _load(C.artifact(task_root, "automation-manifest.json"))
    rows = run_block_rows(task_root)
    cases = scope_cases(task_root, manifest, dispatch_id)
    # What the code saw in the test code and the critic judges (X7-2): smells, relative oracles, parametrisation candidates, copies.
    # `advice` goes out in an `ADVICE` block (`report`), is filed in `work/advice-S5.json` by the exit gate, and never moves `ok`.
    findings, hints, advice, notes, every_target = ([] for _ in range(5))
    texts: dict = {}
    parsed_files: dict = {}

    # the non-Python test files no AST check can read: the code critic reads them whole
    unchecked: list = []
    # The order of the asserts behind a test's own red (`_own_red_order`) is the work of the `reorder` round and of the
    # first window that holds such a test; in an S7 repair round (`TEST_BUG`/`FLAKY`, reason `S7 fix: ...`) it is a hint,
    # so the round's budget is not spent on it.
    s7_round = is_s7_fix_round(task_root, dispatch_id)
    check_manifest(manifest, cases, findings, store_root=task_root, hints=hints if s7_round else None)
    # The sides of the story (t-2181 PC-4, N6): called HERE, after `check_manifest` has returned and not from inside it - a
    # manifest that makes `check_manifest` raise never reaches it - and before the run mapping, whose excuse (`pending` below)
    # it does not judge: C3 holds whether or not an instance is excused from running. The ONE reader of the sides, once.
    sides = C.story_sides(_load(task_root / "pipeline.json"))
    scope_ids = {case: [C.test_instance_id(e) for e in instances_of_case(manifest, case)] for case in cases}
    check_sides(manifest, sides, task_root, findings, scope_ids)
    # Right after the manifest invariants and before `passed_by_word`: the family is `manifest`, outside PASSABLE, so no
    # word and no `*` removes what it finds (HF2-12). The config and the plan are what make `profile_id` and
    # `obligation_refs` demandable; a call without them would demand neither.
    check_row_fields(task_root, manifest, cases, findings, notes, dispatch_id,
                     cfg=hooklib.load_config(), plan=C.plan_obligations(task_root))
    check_case_is_oracle(manifest, cases, findings)
    handed_cases = {row["case"] for row in C.handed_tests(manifest)} \
        if hasattr(C, "handed_tests") else set()
    # The instances of this scope the stand blocked, from the ONE reader, with the run blocks read (t-219): the
    # run mapping does not ask for a reporter row of an instance that never reached a verdict.
    import acceptance as AC
    blocked = set(AC.blocked_instances(
        manifest, [{"instance_id": i} for ids in scope_ids.values() for i in ids if i], scope_ids, task_root))
    # The instances whose side does not exist yet, from the ONE reader (C5), asked with the sides reader's output so all
    # three conditions are checked at this exit; read once, beside `blocked`, and handed to the run mapping as a second excused set.
    pending = set(AC.pending_instances(
        manifest, [{"instance_id": i} for ids in scope_ids.values() for i in ids if i], scope_ids, sides))

    # The question register, read ONCE per window by the one reader (AR-13). The import is not guarded: a failure to
    # import propagates (`detector_main` turns it into UNREADABLE, never OK, FR-59). A register that cannot be read gives
    # `{}`, so every `unknown` Then reads `open` (the firing direction).
    import traceability as T
    questions = T.question_rows(task_root)
    for case in cases:
        entries = instances_of_case(manifest, case)
        case_path = find_case_file(task_root, case)
        text = case_path.read_text(encoding="utf-8", errors="replace") if case_path else ""
        if not text:
            notes.append(f"{case}: no case file found; only the manifest and run blocks were read")
        files, seen = [], set()
        for entry in entries:
            relative = str(entry.get("file") or "")
            resolved = resolve_test_file(task_root, relative)
            if not resolved or resolved in seen:
                continue
            seen.add(resolved)
            if resolved.suffix != ".py":
                notes.append(f"{case}: {resolved.name} is not a Python test file; the code did not check its "
                             "Then assertions, contradictions or smells - the code critic reads them")
                unchecked.append({"case": case, "file": relative, "checks": list(UNCHECKED_CHECKS)})
                continue
            parsed, problem = read_python(resolved)
            if problem:
                notes.append(f"{case}: {problem}")
            if parsed:
                files.append(parsed)
        targets = functions_of_case(files, case_aliases(case, entries), case_functions(entries))
        texts[case], parsed_files[case] = text, files
        every_target += [(case, pyfile, name, node) for pyfile, name, node in targets]
        check_run_mapping(case, entries, targets, rows, findings, case in handed_cases, blocked, pending)
        if text:
            check_bindings(manifest, case, text, files, targets, findings)
            check_open_oracle_asserted(task_root, case, text, manifest, findings, notes, questions)
            check_smells(case, text, files, targets, advice, task_root, notes)
        # A value taken before an action and compared after it (TQ1-18): OUTSIDE `if text` - it reads the test's AST only, and an
        # empty or missing case file must not switch the gate off (FR-59). A test file that is not Python is the note above.
        check_relative_oracle(case, text, targets, advice, task_root, notes, s7_round)

    # A Then left with its owner (GW1-14): after the per-case loop (it needs the case texts) and BEFORE
    # `passed_by_word`, so no stage-override substring (`*`, `partial-green`) can remove what it finds: the family is
    # `bindings`, outside PASSABLE, and only the person's `then handed:` word, joined by identifier, satisfies it.
    check_then_remainders(task_root, manifest, cases, texts, findings, notes)

    # Across the whole window, not per case: the twins that read as one parametrized test
    # usually belong to three different cases — that is the point of the hint.
    check_parameterization(every_target, advice)
    helper_twin_hint(manifest, hints, task_root, notes)
    # A copy of existing code (TQ1-19): the story's whole history, so it is not a per-case check.
    check_copies(task_root, manifest, advice, notes, s7_round)
    # The stand gaps are read from the whole manifest, not from the scope: a row this
    # dispatch does not own is still worth naming, as a note.
    check_environment(task_root, manifest, dispatch_scope(task_root, dispatch_id) or [],
                      texts, parsed_files, findings, notes)
    check_env_evidence(task_root, manifest, dispatch_scope(task_root, dispatch_id) or [], findings, notes)
    # After the per-case loop: the join to the plan is per case, but what it reports on is the
    # one `obligation_bindings[]` map every case shares.
    check_obligations(task_root, manifest, cases, texts, handed_cases, findings)
    # The window against its plan (SC1-14 B2): the family is `plan`, outside PASSABLE, so no word removes what it finds; a story
    # whose S5 is not on the plan form gets one note and nothing else changes.
    check_plan_conformance(task_root, manifest, cases, findings, notes, dispatch_id)
    # The tests that went red and later passed on changed code, or vanished after a red run: from
    # the whole story's run blocks, not from the per-case loop, so no branch of the oracle checks there
    # can end it early. `expectation_changes` never raises (an error is an `unmeasured` entry).
    changes = expectation_changes(task_root, cases, manifest)
    try:
        check_expectation_changes(task_root, changes, cases, findings, notes)
    except Exception as exc:  # the same rule as the measurement: a crash here is not a pass
        changes["unmeasured"].append(f"the expectation-change findings could not be written "
                                     f"({type(exc).__name__}: {exc})")
        notes.append("expectation changes not measured: " + changes["unmeasured"][-1])
    findings = passed_by_word(task_root, findings, notes)
    # a pair whose finding a person's word removed is still a pair: it stays here, on the
    # critic's list and in the report, marked as passed by that word
    _flag_word_passed(changes["pairs"], {f["id"] for f in findings})
    # Under `judge.provider: none` (the default) this returns the same list object untouched.
    findings = passed_by_judge(task_root, findings, hints, notes, parsed_files, texts)

    def unique(rows: list) -> list:
        out, seen_ids = [], set()
        for row in rows:
            if row["id"] not in seen_ids:
                seen_ids.add(row["id"])
                out.append(row)
        return out

    # `ok` counts repairs only. A hint is advice about a choice that was the author's to
    # make; failing the gate on one would be the removed "functions per case" rule again.
    repairs = unique(findings)
    return {"ok": not repairs, "findings": repairs, "hints": unique(hints), "advice": unique(advice),
            "notes": notes, "cases": cases, "expectation_changes": changes, "unchecked": unchecked}


def advice_block(result: dict) -> list:
    """The lines of the `ADVICE — <n>` block of a result (`detector_verdict`'s contract, form 1 (e)): one `- ` line per piece of
    advice, the `[<check> <id>] <message> — fix: <fix>` text of a finding. `[]` when there is none (no header is printed for 0).
    Advice never moves `ok` and is never a refusal: `report` prints it on the author's own stdout and the exit gate files it for the code critic."""
    rows = [row for row in result.get("advice") or [] if isinstance(row, dict)]
    return [f"ADVICE — {len(rows)}"] + ["- " + finding_line(row) for row in rows] if rows else []


def report(result: dict) -> int:
    for note in result.get("notes") or []:
        print("note: " + note)
    import s5_plan as SP
    SP.print_hints(result.get("hints"))
    # The ADVICE block is read by `detector_verdict.parse` at exit 0 and 1 alike and filed for the code critic; it is printed on every
    # road, so a window with a refusal and advice at once files its advice when the refusal is repaired (X7-2).
    for line in advice_block(result):
        print(line)
    if result["ok"] and result.get("plan"):
        print(f"OK: the S5 plan has no gap ({len(result.get('notes') or [])} thing(s) not checked, named above)."
              + (" " + SP.HINT_ADVICE if result.get("hints") else ""))
        return 0
    if result["ok"]:
        files = list(dict.fromkeys(row["file"] for row in result.get("unchecked") or []))
        # A Python-only story prints exactly what it always did. A story with test files the code could not read
        # claims nothing for them: the line names them, and `qa-code-critic` reads them in full.
        left = (f", except {len(files)} test file(s) not checked by code for their Then assertions, "
                f"contradictions or smells (the code critic reads them in full): {', '.join(files)}"
                if files else "")
        print(f"OK: S5 exit checks pass for {len(result.get('cases') or [])} case(s) "
              "(manifest invariants, Then bindings, oracle, run mapping, "
              "obligation bindings)" + left + "."
              + (" The hint above is advice about the shape you chose, not a repair: take it "
                 "or answer it in the manifest's `shape` line." if result.get("hints") else ""))
        return 0
    findings = result["findings"]       # `ok` is false only when a repair is listed; if a result says otherwise, the
    # header below declares 0 findings and the classifier names it a defect (`detector_verdict`, FR-59), not unmigrated
    # One line per finding (`detector_verdict`'s contract), the header carries the label that says the recorded
    # words were judged HERE, and a finding refused to every word has its own line ABOVE the header, so a
    # shortened output cannot lose it. The decision is made from the findings alone: it does not depend on what
    # `passed_by_word` reached (an early return, a failed `waiver` import).
    for finding in findings:
        cause = refusal_cause(finding)
        if cause:
            print(DV.refusal_line(finding["id"], cause))
    print(f"REJECT — {len(findings)} finding(s) for the author before the code critic {DV.WORDS_AT_SOURCE}:")
    for finding in findings:
        print("- " + finding_line(finding))
    # The last line used to hand the reader a command the pre-tool guard blocks for every
    # role (`waiver.py --stage` is the orchestrator's alone): a role that could not repair a
    # finding was pointed at its only exit and refused there. So the line now says who does
    # what — the role returns the item, the orchestrator asks and records. The marker is the one
    # sentence the driver routes on (`story_run.match_known`): cmp2, TP1-15045, 06:19, this
    # refusal ("no run block carries a result row") was the automator's own repair, and without
    # the marker it went to the conductor three times and then to the person. It prints only
    # here, after the findings: the OK path returns above and never carries it. The door is named
    # for the findings a word can pass (built from the two constants that decide it) - not for the
    # others, which no recorded word passes, `*` included.
    families = " or ".join(f"[{family}]" for family in sorted(PASSABLE))
    print("These are repairs, not questions: nothing here goes to the person as it stands. "
          + REPAIR_MARKER + ". "
          "A role that cannot repair one returns it in its digest and stops; it does not "
          "record anybody's word. The orchestrator asks the person and records the answer "
          "with `" + door("waiver.py --task <TICKET> --stage S5 --block "
                          "\"<part of the line>\"") + f"` {WHOLE_PART}, which passes an {families} finding or a "
          f"{' or '.join(WORD_PASSABLE_TAGS)} one"
          + "; no recorded word, `*` included, passes any other "
          "finding here - it is a repair."
          + (" A Then the person takes is the one exception: the orchestrator records their words under "
             f"`{C.THEN_HANDED_MATCH_PREFIX} <case>#<n>` (named in the finding); that block is read by NAME, "
             "so no substring of a line passes it."
             if any(_finding_tag(f).startswith(THEN_REMAINDER_TAG) for f in findings) else ""))
    return 1


def running_dispatch(task_root: Path, role: str = "qa-automator", stage: str = "S5") -> str | None:
    """The one dispatch of `role` on `stage` that is running right now, else None.

    The exit gate re-runs this check with no arguments, and an unscoped run speaks about
    EVERY case in the manifest: on TP1-15045 the automator of window TC-001/TC-002 was
    refused its own handoff over a TC-014 finding that belonged to a window closed a day
    earlier, and halted. The gate judges the handoff in front of it, so the check is scoped
    to the dispatch that is handing off. WHICH dispatch is the finisher's is `dispatch_identity.own` (AR-13, the one reader): a name
    (`QA_FACTORY_DETECTOR_DISPATCH`, else `QA_FACTORY_DRIVER_RUN`) picks its own record, never another window's; with no name the
    count rule: with no running dispatch, or two, it answers None (the caller then does not read None as "every case")."""
    import dispatch_identity
    found = dispatch_identity.own(_state_view(Path(task_root))["dispatches"], role, stage)
    return str(found["id"]) if found and found.get("id") else None


RETURNED_STATUS = "returned_unaccepted"      # `controller.RETURNED`: a stop with no bind receipt (the finisher's window)


def dispatch_ids(task_root: Path, status: str, role: str = "qa-automator", stage: str = "S5") -> list:
    """The ids of the dispatches of `role` on `stage` in `status`, by the one state view (AR-13: the reader every live-dispatch
    lookup of the S5 exit goes through, here and in `branch_accounting`)."""
    ids = [str(d.get("id") or d.get("dispatch_id") or "") for d in _state_view(Path(task_root))["dispatches"].values()
           if d.get("status") == status and str(d.get("role") or "") == role and str(d.get("stage") or "") == stage]
    return [d for d in ids if d]


def window_dispatch(task_root: Path, role: str = "qa-automator", stage: str = "S5") -> str | None:
    """The dispatch whose window the S5 exit judges: (a) the running one; only when there is none, (b) the ONE
    `returned_unaccepted` one (RN1-26: the finisher's own window, a stop with no bind receipt). Two of either kind, or none: None
    (the scope is then not read as "every case" by the caller that cares, `branch_accounting.s5_scope`). INVARIANT: (b) is read
    only after (a) found nothing, so a running window is never judged by a returned one; a repair round on a returned window
    is judged over its own cases, never over a window closed a day earlier (TP1-15045)."""
    import dispatch_identity
    found = running_dispatch(task_root, role, stage)     # (a): a name picks its own running record, never a sibling's
    if found:
        return found
    # (b): a name that is a returned window is picked by `own` the same way; a held name that fits neither is None (never the count rule); an unheld name falls to the count rule in `own`
    returned = dispatch_identity.own(_state_view(Path(task_root))["dispatches"], role, stage, statuses=(RETURNED_STATUS,))
    return str(returned["id"]) if returned and returned.get("id") else None


def detector_main(root=None) -> int:
    """Zero-argument entry point for the S5 exit gate. Nothing to check until a manifest exists (exit 0). A check that
    could not run is NOT a pass (RH1-5, FR-59): it prints `UNREADABLE: <what>` and exits `DV.EXIT_UNREADABLE`, so the
    gate hands it to the conductor instead of counting it as clean. The story is the one the gate NAMED
    (`planning_contract.detector_story`, GW1-10); `0` for "no story" now means "not a factory story" only: nothing
    named and no pipeline anywhere has nothing to judge."""
    step = "finding the running story"
    try:
        from planning_contract import detector_story
        task_root = detector_story(root, stage_id="S5")
        if task_root is None:
            return 0
        step = "reading the running dispatch"
        dispatch = window_dispatch(task_root)
        # Two or more windows run and the gate did not say whose handoff this is: every case of the manifest is NOT the answer
        # (TP1-15045: a window refused over another window's finding). INVARIANT: never `run(root, None)` here (AR-28).
        if dispatch is None and len(dispatch_ids(task_root, "running")) >= 2:
            print(DV.unreadable_line("two or more windows are running and this check was not told whose handoff it judges"))
            return DV.EXIT_UNREADABLE
        # The PLAN dispatch writes no manifest: its detector is the plan's own check (`s5_plan.check`). POSITION: before the
        # manifest is looked for. INVARIANT: a window dispatch (and a run with none) takes every road it took before.
        step = "checking the plan"
        if is_plan_dispatch(task_root, dispatch):
            return report(plan_result(task_root, dispatch))
        if not C.artifact(task_root, "automation-manifest.json").exists():
            print(f"s5_precheck: {task_root.name} has no automation-manifest.json yet — nothing to check")
            return 0
        step = "checking the window"
        return report(run(task_root, dispatch))
    except Exception as exc:
        print(DV.unreadable_line(f"s5_precheck could not complete {step} ({type(exc).__name__}: {exc})"))
        return DV.EXIT_UNREADABLE


def main() -> int:
    C.force_utf8()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--task-root", help="qa-factory/artifacts/<TICKET>")
    ap.add_argument("--dispatch", help="limit the scope to this dispatch's cases")
    ap.add_argument("--json", action="store_true")
    ns = hooklib.exact_options(ap).parse_args()
    if ns.task_root is None:        # no flag: the exit-gate hook's mode, as before
        return detector_main()
    # A GIVEN root names an existing story: an empty value is a refusal, never the hook's mode or the current folder,
    # and a phantom root is never answered "OK ... 0 case(s)" (I4, FR-59).
    story = hooklib.story_cli("s5_precheck.py", root=ns.task_root, key_flag=None)
    # POSITION: before the manifest is read. INVARIANT: a window dispatch passes every check it passed before (spec t-1246 B2).
    result = plan_result(story, ns.dispatch) if is_plan_dispatch(story, ns.dispatch) else run(story, ns.dispatch)
    if ns.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0 if result["ok"] else 1
    return report(result)


if __name__ == "__main__":
    sys.exit(main())
