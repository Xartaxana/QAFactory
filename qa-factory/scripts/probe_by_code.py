"""probe_by_code.py — the critic's red probe done by code, one instance per call.

The critic used to write a mutation request by hand, prepare two sandboxes, run both, read
tracebacks with `--detail` and retype what it saw into a `probe` record (S5-122; on
TP1-13797 every attempt ended `probe_defect` before a test ran). Here the whole probe is
one command and nothing in the record is typed by a role:

  1. the test function is located by AST (`<file>::[Class::]<func>[<param>]`, class methods too);
  2. its FIRST check is mutated — `invert`: `assert not (<expr>)` (hamcrest `assert_that(actual,
     matcher)` gets `is_not(matcher)`; every form is a row of `assertion_probes_ast.python.forms`). When the form takes a message, the mutated check carries the
     factory's marker `qa-probe-<token>` (joined at run time) so the failure that fires is attributable, and the statement keeps its line
     count; the human text `probe-<IID> invert: ...` is the record's `expected_reason`, not the proof;
  3. exactly that node runs through `run_suite.py --request` with a typed `red_probe` request
     this script writes under `work/probe-requests/probe-<IID>.json` (built by the same code
     `--mine` uses; `red_probe` writes no run block, so the mutated red never reaches the
     ledger as a product result);
  4. the original bytes are restored in a `finally` FROM A BYTE COPY ON DISK (see below) — verified
     by sha256, mtime put back, the module's `__pycache__` entries dropped so no rewritten
     bytecode of the mutated source outlives it — and `work/probes/<IID>.json` is written in the
     `probe` shape `acceptance.validate_window` checks.

  0. BEFORE anything is mutated a test that was already probed over the same bytes is ANSWERED, not
     probed again (`proof_level.already_probed`, D-0018: one probe call per instance, every check; a
     check proved on the same bytes AND entries is not run again, only a person's word repeats it): exit 0, `{"verdict": "already_probed", ...}`, and nothing is mutated, launched
     or written. "The same bytes" is the per-test identity `--mine` writes into the run's
     `instance_contracts` (`proof_level.same_test`), so an edit of ANOTHER test of the file, or a
     comment, keeps the answer; a code edit of this test, or of a fixture or helper it uses, does not.
  5. an `intended_failure` with a verified restore also writes the IMMUTABLE live receipt
     `work/sensitivity-receipts/<stem>-live-<hash>.json` (level `live`: "the check is live") and
     publishes it in `tests[]` and the obligation bindings through one `manifest_put.py` fragment;
     a receipt of a higher level (`red_sandbox.py --probe`) already there is never replaced.

  probe_by_code.py --task T --dispatch ID --test "<file>::<func>[<param>]" --instance IID
                   [--mutation invert] [--oracle [<file>::]<func>] [--at <line>[#n]] [--json] [--timeout S]
  probe_by_code.py --task T --s6-close --test "<file>::<func>[<param>]" --instance IID  [same options]
  probe_by_code.py --release-copy <file> [--json]
  probe_by_code.py --task T --dispatch ID --test "<file>::<func>" --instance IID
                   --alternative <case>:ALT-n [--model work/probe-models/<name>.json]   (TQ1-25; t-2064 P5: the one road)
  probe_by_code.py --task T --alternatives [--instance IID] [--json]     (the report: what is owed, stale, proven)

  `--alternative` walks the reading B a case declares for a Then (`alternatives`) on the ONE road, on every language: the entries of the
  model file (`work/probe-models/<dispatch id>.json`, or `--model`) that carry `alternative: <case>:ALT-n` are the plan, each an
  `actual` or `find` entry on a check of that Then; a `{"alternative": ..., "gap": ...}` entry says B cannot be modelled. Its record
  lives under `work/probes/alternative/` and is never a live receipt; `proven` means every check of that Then proved under the entry.
  (`--mutation alternative` was removed; it is refused with this door.)

  The `--s6-close` form is the DRIVER's, in the code close of S6 when no dispatch is open (HF3-6): `--s6-close` takes
  the place of `--dispatch`, and the context is allowed exactly when the controller would take the S6 code-only
  receipt (`execution_request.s6_close_dispatch`, one predicate with `controller.code_close_conflicts`). It is
  asked before anything is read or mutated, and refused (exit 2, nothing changed) while any dispatch is running,
  before S6 has started, after S6 closed, for a case outside the story's scope, or when the state cannot be read.
  The record then carries `dispatch_id` `S6-close-r<revision>`, and a repeat is looked up under the stage S6.

A test in ANY other language gets the same probe (B-373, D-0028: the proof that the check is live is an
assertion change, and it does not depend on the language of the test). `references/detectors.json`
`assertion_probes` says, per language (read ONLY through `assertion_detectors.py`), how to find the test, its
first assertion and the one inverted form of it, and which failure that inverted form must show. The source is
read by the language's lexer (comments and strings never hold a head), the test is found by its declaration
(exactly one match, or `--at <line>` picks), the first head of its body is inverted by one `find -> replace`
pair at one position (`--mutation invert` only), and the run's own report decides: the inverted statement
failed and the factory's own marker, the exact token, is read in a failed row's failure or error text is `intended_failure`
(`proved_by: marker`); one rule for every language. Neither the place, the line nor the library's wording (`fires_as`) proves.
A failure with text and no token is `incomplete`, `cause: judgment` (exit 1, no receipt): the place, the frame and the library
wording are facts in `judgment_facts` for the code critic. `cause: tooling` stays only for what the tool cannot read at all - a
row with no text, a pass whose body is unknown (`--at` among two candidates, or the manifest's id), a compiled launcher that may not rebuild, a
row that is not bound to the test: a factory gap is never a verdict on the test (FR-59). A language with no entry, or a table that cannot be read, is a
refusal that says it is a gap of the factory's data and names the row to add (exit 2, nothing changed in the
author's tree). A refusal of the TOOL (`ToolRefusal`) leaves one record, `refused: tool`, when the manifest proves the test is
the instance's (`_record_tool_refusal`); a refusal of the CALL leaves none. A record that says `incomplete`, or that no row of
the report could be bound to the test, also says `language` and `cause: tooling` (`proof_level.tooling_gap_key` reads it); the one
exception is a failed or error row with text and no marker (E15, t-1968): `cause: judgment`
with `judgment_facts` (the statement, the frame, the whole message and the failure text, cut). That record is the code critic's to judge:

  probe_by_code.py --task T --dispatch ID --judge "<instance>" --verdict fires|other_failure|cannot_judge
                   --quote "<a line of its failure text>" [--why "<one sentence>"]        (`JUDGE_DOOR`, `judge_record`)

`fires` makes it an `intended_failure` (`proved_by: critic`, a live receipt carrying the quote), `other_failure` a
`wrong_location`, `cannot_judge` leaves it `incomplete` with the judgment written. The tool checks only that the record is of
these bytes, owes the judgment and that the quote is a substring of the stored text; whether the quote proves the firing is the
critic's word and the acceptor's to read (AR-29). Never a question to a person, never a gap.

The author's file is never mutated without a verified byte copy on disk, and the copy is the only
way back that survives the process. `RUN_TIMEOUT_S` is 31 minutes and a role's shell call is killed
long before it: a killed process never runs its `finally`, and the original bytes lived only in its
memory, so the author's file stayed mutated for good. So, per file (keyed by a hash of its
project-relative path, in the project's `qa-factory/state/probe-copies/`, one folder for every
story of the project):

  * `<k>.lock` - an OS lock (the convention of `event_store.lock`), taken BEFORE the file is first
    read and held to the end of the probe; process death releases it. `OSError` EACCES / EAGAIN /
    EWOULDBLOCK / EDEADLK means HELD; any other errno or an ImportError means the primitive itself
    failed, and only then does the fallback deadline `started_at + timeout_s + 120 s` stand in for
    it. Liveness is never tested by a pid;
  * `<k>.orig` - the original bytes; `<k>.meta` - JSON with a non-`.json` suffix (the json scans of
    the story folders skip it): path, original and mutated sha256, original mtime, start, timeout,
    the statement before and after, its line.
  The order: write `.orig` and `.meta`, re-read `.orig` and check its sha, mutate, restore FROM
  `.orig`, check the sha, put the mtime back (a `.py` keeps its own and loses its bytecode; any other
  file gets "now", so the next incremental build rebuilds), and only then delete the copy. A restore
  that cannot be verified keeps both files and says `copy <.orig> over <file>`.

  When a probe starts it first restores what a dead probe left: every copy whose lock is free is
  restored if the file still holds the probe's mutated bytes, dropped if it already holds the
  original, and otherwise left alone (the author's newer edit wins): a copy of another file is a
  note, a copy of THIS probe's own test or oracle is a refusal that goes back to the test's author
  as a tooling finding. `--release-copy <file>` drops such a copy once the author has dealt with it.

The oracle is not always in the test. A suite whose expectations live in shared helpers - the
common idiom - left this script with nothing to mutate, and it refused: nine of the twelve
critic findings of TP1-13797 were that one tooling defect. So the expectation is followed
ONE hop out of the test, into the helpers and fixtures it calls, looked for in the test file,
the conftest chain and the modules it imports; the mutation then lives in that file for the
length of the probe and is restored with it, and the record says where it went. Deeper than one
hop is named by hand with `--oracle`.

Verdicts: `intended_failure` (the probe's marker was read in the failure, `proved_by: marker`, or the code critic
judged `fires`, `proved_by: critic`), `no_failure` (the mutated test passed — the assert never fired), `wrong_location`
(it failed elsewhere, or for another reason; `actual_location`/`actual_reason` say where),
`not_executed` (nothing ran; `notes` say why), `incomplete` (the run happened but the tool could not read
it well enough to judge the test: `notes` say what it could not read; a tooling finding). Exit 0 for the
first three, 1 for `not_executed`, `incomplete` or a restore that could not be verified, 2 for a refusal
before any file was touched (no such test, no assert, an instance the manifest does not name, a language
with no `assertion_probes` entry: that one names the row to add and `red_sandbox.py --probe`, the probe
that breaks the product in a throwaway copy and works for any language).

The run directory is the profile's own, passed to the request builder as `--cwd` on the first
call (this probe mutates the author's tree in place, so it has no clone to pass as
`--sandbox-root`). The run's report is read by `reporters.read_rows` with the reporter the run's
summary names (JUnit when it names none).

The run itself is `run_suite.py`; `PROBE_RUN_SUITE=<script>` replaces it (tests), and the
script never launches pytest by itself.
"""
import argparse
import ast
import bisect
import hashlib
import json
import os
import pathlib
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import assertion_detectors as AD  # noqa: E402
import contract as C  # noqa: E402
import proof_level  # noqa: E402
import reporters  # noqa: E402
from red_sandbox import held_ids, matching_rows  # noqa: E402,F401  (the one matcher, HF4-12; red_sandbox never imports this module)
import runtime_paths  # noqa: E402
import test_source  # noqa: E402  (the one reader of a non-Python test file, EP1-37; it imports this module only inside its functions)
from event_store import (LockBroken, LockBusy, atomic_json, content_hash, os_try_lock,  # noqa: E402,F401
                         take_file_lock)
from hooklib import artifacts_dir, load_config, project_root, story_root  # noqa: E402
from hooklib import read_json, sorted_paths  # noqa: E402

MUTATIONS = ("invert",)
# t-2045 N7: `expected` (a distinct literal in place of the expected one) was removed. The parser still lists it, so argparse does not
# answer first; `_refuse_flags` refuses it with the door `--mutation invert`; `proof_level.replay_mutation` replays a stored one as `invert`.
REMOVED_MUTATION = proof_level.REMOVED_MUTATION
# This tool mutates the ASSERTION of a test and never the product, so what it proves is that the
# check is live (level `live`), not that it catches a broken product. It used to claim
# "real_behavior", a product mutation it never makes, and the window then accepted an assertion
# probe as if the product had been broken (D-0010, D-0012).
MUTATION_KIND = "assertion"
# TQ1-25: the probe kind `alternative` models a case's declared reading B and is NOT in MUTATIONS (`probe_debt` replays only
# the invert kind: a second there would make it try to replay a kind it cannot).
ALTERNATIVE = "alternative"
ALTERNATIVE_KIND = "alternative_model"
MODEL_TEXT_MAX = 2000       # characters of a model's `find` / `replace`
MODEL_FILE_MAX = 65536      # bytes of a model file (t-2064 P3: a window holds one entry per check, about 90-150 bytes each: an ESTIMATE)
MODEL_KINDS = ("actual", "find", "invert", "not_here", "product")     # the kinds of one entry of `work/probe-models/<dispatch>.json`
MODEL_ENTRY_KEYS = ("check", "instance", "alternative", "supposes", "replace", "gap") + MODEL_KINDS    # `gap` (t-2064 P5): a reading's, with no check
ALTERNATIVE_KINDS = ("actual", "find")      # the kinds a READING (an entry with `alternative`) may carry: a supposition about the product's value
MODEL_SUPPOSES_MAX = 300    # characters of an entry's `supposes` (presence only; its content is never read)
MODEL_GAP_MAX = 300         # characters of a model's `gap`
SUPERSEDE_REASON_MAX = 300  # characters of `--supersede "<reason>"`
MANIFEST_FIELDS = ("obligation_ids", "obligation_hash", "defect_location", "assertion_id")
RUN_TIMEOUT_S = 1860
# t-1968 N2: the ONE text of the code critic's door for a record `incomplete` with `cause: judgment` (AR-13): the E15 note, the
# window note (`window_record.build`), the refusals of `judge_record` and the charter's pin all carry this constant.
JUDGE_DOOR = ('probe_by_code.py --task <T> --dispatch <D> --judge "<instance>" --verdict fires|other_failure|cannot_judge '
              '--quote "<a line of its failure text>" [--why "<one sentence>"]')
JUDGE_VERDICTS = ("fires", "other_failure", "cannot_judge")
FAILURE_TEXT_MAX = 16384    # characters of ONE failure text stored in `judgment_facts` (a longer one keeps its head and its tail around one `…`, which counts)
FACTS_ROWS_MAX = 12         # unsettled rows `judgment_facts.rows` holds (the rest is counted in `rows_cut`; `fires` is refused then)
JUDGE_QUOTE_MAX = 300       # characters of `--quote`
JUDGE_WHY_MAX = 300         # characters of `--why`
_TRACE_TAIL = re.compile(r"^(?P<loc>\S.*:\d+):\s*(?P<exc>\S+)\s*$")
_FRAME = re.compile(r"^(?P<path>[^\s:]+?\.py):(?P<line>\d+)(?::|\s|$)")


class Refusal(ValueError):
    """A problem with what was asked — answered before any file is touched."""


class ToolRefusal(Refusal):
    """A refusal whose cause is the factory's tool, not the call: the language has no entry, the data is broken, the lexer cannot
    read the file, no declaration or assertion form of the entry fits, or the run cannot be selected on this profile. `main` prints
    it as any refusal (one JSON, exit 2) and also leaves the record `refused: tool` (`_record_tool_refusal`), so that "the tool
    cannot read this" is a fact on disk and not only a line in a chat. `name_unproved` says the refusal does not prove the
    `--test` name is the instance's (no declaration was found for it): the record is then written only when the manifest row
    proves the name. A refusal of the CALL (a wrong --test, an unknown instance, a lock) stays a plain `Refusal`: the role does not
    write itself a gap by a wrong call (AR-22)."""

    def __init__(self, message: str = "", name_unproved: bool = False):
        super().__init__(message)
        self.name_unproved = name_unproved


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fold(text: str, limit: int = 160) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


# --- the test ----------------------------------------------------------------------------------

def parse_node(spec: str, root=None) -> dict:
    """`tests/t.py::TestX::test_y[p]` -> file, class chain, function, param. `root` (the project
    root) only lets a refusal call a directory a directory."""
    text = str(spec or "").strip().replace("\\", "/")
    if "::" not in text:
        raise Refusal(f"--test wants <file>::<function>[<param>], got {spec!r}")
    file, tail = text.split("::", 1)
    parts = tail.split("::")
    last = parts[-1]
    function, _, param = last.partition("[")
    if not file.endswith(".py"):
        return parse_detector_node(text, file, tail, root)
    if not function.isidentifier():
        raise Refusal(f"--test wants a .py file and a function name, got {spec!r}")
    # `reader` (t-2045 N2, B1): which reader judges this test - "ast" (this one) or "table" (`parse_detector_node`). The ONE
    # key the sites that branch on it read. N3b: a Python spec carries what a table spec carries - `language`, `entry` (the
    # `assertion_probes_ast` row) and `tail` (the chain and the function, no parameter) - so the road after the plan asks no
    # language question: it reads the entry.
    language, entry = _python_entry()
    return {"file": file, "chain": parts[:-1], "function": function,
            "param": param[:-1] if param.endswith("]") else param, "node": text, "reader": "ast",
            "language": language, "entry": entry, "tail": "::".join(parts[:-1] + [function])}


def _is_table(spec: dict) -> bool:
    """True when the table reader (`assertion_probes`) judges this test, False for the AST reader. Strict: both producers
    (`parse_node`, `parse_detector_node`) write `reader`, so a spec with none is a named KeyError, not a guess (AR-23)."""
    return spec["reader"] == "table"


def _reader_entry(spec: dict):
    """The `assertion_probes` entry the TABLE reader reads this test's source with, None for the AST reader (whose `entry` is the
    `assertion_probes_ast` row, which has no lexer: `test_body_span` and `check_on_line` take None for it). The reader's own
    selection, not a language question: both readers' specs carry `entry` since N3b."""
    return spec["entry"] if _is_table(spec) else None


def _defs(body, chain: list, at: list):
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield list(at), node
        elif isinstance(node, ast.ClassDef):
            yield from _defs(node.body, chain, at + [node.name])
        elif isinstance(node, (ast.If, ast.Try)):  # a def under a guard is still a def
            for sub in ("body", "orelse", "finalbody"):
                yield from _defs(getattr(node, sub, []) or [], chain, at)


def locate(tree: ast.Module, chain: list, function: str):
    """The one FunctionDef named — the class chain decides when a name repeats."""
    found = [(at, node) for at, node in _defs(tree.body, chain, []) if node.name == function]
    if chain:
        found = [(at, node) for at, node in found if at == chain]
    if not found:
        raise Refusal(f"no test function {'::'.join(chain + [function])} in this file")
    if len(found) > 1:
        names = ", ".join("::".join(at + [function]) for at, _ in found)
        raise Refusal(f"{function} is defined more than once ({names}); name the class in --test")
    return found[0][1]


def _statements(body):
    """Every statement of a body in source order, into compound statements, never into a
    nested def/class (that is another function's assert)."""
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield node
        for field in ("body", "orelse", "finalbody", "handlers"):
            children = getattr(node, field, None)
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, ast.ExceptHandler):
                        yield from _statements(child.body)
                    elif isinstance(child, ast.stmt):
                        yield from _statements([child])


def _python_entry() -> tuple:
    """(language id, entry) of the `assertion_probes_ast` key for `.py` - the ONE place the Python reader loads its data (the
    shared contract and the `forms` rows). A gap of the data is a `ToolRefusal`, never a guess (t-2045 N2, N2b)."""
    try:
        language, entry = AD.ast_entry(".py")       # this reader plans a Python file only (`parse_node` sends the rest to the table)
    except AD.DetectorsError as exc:
        raise ToolRefusal(f"probe_by_code: factory data gap - {exc}. Return it as a tooling finding (the table is the "
                          "factory's). Nothing was changed.") from exc
    if entry is None:
        raise ToolRefusal("probe_by_code: factory data gap - references/detectors.json `assertion_probes_ast` has no entry for "
                          ".py, so the marker of a Python probe cannot be built. Return it as a tooling finding. "
                          "Nothing was changed.")
    return language, entry


def _form_label(form: dict) -> str:
    """How a refusal names a row's check: its first name as a call, else its shape (`assert`)."""
    return f"{form['names'][0]}()" if form.get("names") else form["shape"]


def _call_name(func) -> str:
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


def _call_of(stmt):
    """The `ast.Call` of an expression statement (under an `await` too), None when the statement is not a call."""
    value = stmt.value if isinstance(stmt, ast.Expr) else None
    value = value.value if isinstance(value, ast.Await) else value
    return value if isinstance(value, ast.Call) else None


def _row_name(stmt, form: dict):
    """The name of the check `stmt` is by the row `form` (its `shape`), None when the statement is not one of the row."""
    shape = form["shape"]
    if shape == "assert":
        return shape if isinstance(stmt, ast.Assert) else None
    if shape == "with":      # `with <receiver>.<name>(...):` - any item of the header
        if not isinstance(stmt, (ast.With, ast.AsyncWith)):
            return None
        for item in stmt.items:
            ctx = item.context_expr
            head = ctx.func if isinstance(ctx, ast.Call) else None
            if isinstance(head, ast.Attribute) and isinstance(head.value, ast.Name) and head.value.id in form["receivers"] \
                    and head.attr in form["names"]:
                return head.attr
        return None
    call = _call_of(stmt)
    if call is None:
        return None
    func = call.func
    if shape in ("call", "method") and call is not stmt.value:        # only a `chain` is read under an `await`
        return None
    if shape == "call":
        name = _call_name(func)
        ok = name in form["names"]
    elif shape == "method":
        name = func.attr if isinstance(func, ast.Attribute) else ""
        names = form.get("names") or list(form["invert"]["names"])
        ok = isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in form["receivers"] \
            and name in names
    else:
        head = func.value if isinstance(func, ast.Attribute) else None
        name = _call_name(head.func) if isinstance(head, ast.Call) else ""
        ok = name in form["names"]
    return name if ok and len(call.args) >= form.get("min_args", 0) else None


def _form_of(stmt, forms: list, file_text: str):
    """(row, name) of the first row of `forms` that `stmt` is a check of, None when no row matches (it is not a check). The
    shapes are code; the names, receivers, argument counts and the `source` regex (which must match the whole file: an import
    decides which library is meant) are the rows'."""
    for form in forms:
        name = _row_name(stmt, form)
        if name is not None and (not form.get("source") or re.search(form["source"], file_text)):
            return form, name
    return None


def _first_check(function_node, forms: list, file_text: str):
    """(statement, row, name) of the first check statement of a function, None when it has none. A row with `invert: null` is a
    check too, and is returned: the caller refuses it, it is never skipped for a later one."""
    for node in _statements(function_node.body):
        got = _form_of(node, forms, file_text)
        if got is not None:
            return (node,) + got
    return None


def _check_end(node) -> int:
    """The last line a check statement spans: its own end, except a `with`, whose check is its HEADER (the last context
    expression), so a line inside the block is its own check or none - never the with's."""
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return max(item.context_expr.end_lineno for item in node.items)
    return node.end_lineno


def _skipped_calls(function_node, target) -> list:
    """The lines of the call statements before `target` in a function that no row reads (data for a note, never a verdict): the
    first check a row reads is `target`, and the author may have meant one of these (a check of a form the rows do not know)."""
    out = []
    for node in _statements(function_node.body):
        if node is target:
            break
        if _call_of(node) is not None or (isinstance(node, (ast.With, ast.AsyncWith))
                                          and any(isinstance(item.context_expr, ast.Call) for item in node.items)):
            out.append(node.lineno)
    return out


def _python_checks(tree: ast.Module, forms: list, file_text: str) -> list:
    """[(line, end_line, row id, node, column, row, name)] of every check statement of a Python file - a statement one of the
    `forms` rows reads, in any function or class of it - in source order. The reader of `check_on_line` and of the `at` target of
    `plan_mutation` (t-2045 N1): one list, so the line a door prints is a line the plan can invert."""
    out = []
    for node in ast.walk(tree):
        got = _form_of(node, forms, file_text) if isinstance(node, ast.stmt) else None
        if got is not None:
            out.append((node.lineno, _check_end(node), got[0]["id"], node, node.col_offset, got[0], got[1]))
    return sorted(out, key=lambda c: (c[0], c[4]))


def _python_call_name(tree: ast.Module, line: int):
    """The name of the outermost call that starts on `line` (`helper(...)` or `obj.method(...)`), None when none does."""
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and n.lineno == line]
    if not calls:
        return None
    func = min(calls, key=lambda n: (n.col_offset, -(n.end_lineno * 100000 + n.end_col_offset))).func
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None


def _line_facts(checks: list, line: int, helper) -> dict:
    """The facts `check_on_line` returns, from `[(line, end_line, form)]` in source order. `found`: the first check whose
    statement starts on or spans `line`, with `starts_here` (how many checks start on its first line); `nearest_below`: the
    first check that starts after `line`; `calls_helper`: what the caller read on the line."""
    found = next(({"line": a, "end_line": b, "form": f} for a, b, f in checks if a <= line <= b), None)
    if found is not None:
        found["starts_here"] = sum(1 for a, _b, _f in checks if a == found["line"])
    below = next(({"line": a, "end_line": b, "form": f} for a, b, f in checks if a > line), None)
    return {"found": found, "nearest_below": below, "calls_helper": helper}


def _no_check_refusal(shown: str, line: int, facts: dict) -> Refusal:
    """The refusal of a target line with no check (t-2045 N1, E-A): a FACT and two doors, nothing chosen. A plain `Refusal`
    (the call's, or the author's id), so it leaves no record; the critic carries its text into a `mechanical` finding, or
    reports `unverified` when he reads a real check of a form the factory does not know."""
    below, helper = facts["nearest_below"], facts["calls_helper"]
    parts = [f"probe_by_code: line {line} of {shown} holds no check of a form the factory reads (none starts or spans there), "
             "so nothing there can be inverted."]
    parts.append(f"The nearest check below it starts at line {below['line']}: `--at {below['line']}` probes that one, when it is "
                 "the Then's check." if below else "No check of a form the factory reads follows it in the file.")
    if helper:
        parts.append(f"The line calls `{helper}(`: when the Then's check stands inside it, name that line itself, "
                     "`--at <file>:<line>`.")
    parts.append("When the id is the author's mistake, the row's assertion_id is corrected (`manifest_put.py --task <T> --fragment "
                 "<file>`); a real check of a form the factory does not read is reported `unverified` with the reason, never "
                 "blamed on the author. Nothing was changed.")
    return Refusal(" ".join(parts))


# --- where the oracle lives ----------------------------------------------------------------------
# A probe mutates the ORACLE, and this script only ever looked in the test function's own body.
# A suite whose expectations live in shared helpers - the common idiom, and the one TP1-13797's
# suite used - therefore had no oracle to mutate, and the probe refused: nine of the critic's
# twelve findings that run were this one tooling defect returned to the author in four windows,
# plus seven registry rows that went to the person. The critic of runs 1 and 2 did the red probe by
# hand and never met it, which is the shape of the rule in plan section 2: code that replaces a
# role must name the class of cases where it steps back, and this was not one - it was a gap.
#
# So the oracle is followed one hop out of the test: into the helpers and fixtures the test body
# calls, looked for in the test's own file, then its conftest chain, then the project modules it
# imports from. One hop, and in call order, because the FIRST expectation the test asserts is the
# one the probe is about; anything deeper is a chain the reader cannot follow either, and gets the
# refusal with `--oracle` named in it.

def _called_names(unit, reader_entry=None) -> list:
    """The names a test body calls, in SOURCE order, unique (t-2045 N5). The AST reader (`reader_entry` None): `unit` is the
    FunctionDef; its parameters come first - a fixture that asserts is as much this test's oracle as a helper it calls - then the
    calls by position. The table reader: `unit` is `(Source, opener, closer)`, the names before an opening parenthesis in the
    skeleton between the braces, where a string and a comment are blank: a name inside either is no call. No call graph, no type:
    a method is its bare name (`this.page.x()` is `x`)."""
    names, seen = [], set()
    if reader_entry is not None:
        src, opener, closer = unit
        for name in _CALL_NAME.findall(src.skeleton[opener + 1:closer]):
            if name not in seen:
                seen.add(name)
                names.append(name)
        return names
    for arg in unit.args.args:
        if arg.arg not in seen and arg.arg not in ("self", "cls"):
            seen.add(arg.arg)
            names.append(arg.arg)
    calls = sorted((n for n in ast.walk(unit) if isinstance(n, ast.Call)), key=lambda n: (n.lineno, n.col_offset))
    for node in calls:
        func = node.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _any_declaration(entry: dict):
    """The compiled `helper_declaration` of an entry with the name left open (a named group `name`): every declaration of a helper
    in a file, whatever it is called. The data keeps its guards against a call or a keyword in the row itself."""
    return re.compile(entry["helper_declaration"].replace(AD.NAME, r"(?P<name>[A-Za-z_$][\w$]*)"))


class _Hop:
    """One file the hop reads, through the reader of its language: the declarations of a name in it, each with the line of its first
    check and the names it calls. `entry` is the `assertion_probes` entry (the table reader: its lexer and `helper_declaration`
    read the file) or None (the AST reader). A file the parser or the lexer cannot read has no declaration and says why in
    `unread`: it is never mutated and never guessed at."""

    def __init__(self, path: Path, text: str, entry, shown: str, language: str = ""):
        self.path, self.text, self.entry, self.shown, self.language = path, text, entry, shown, language
        self.unread, self.src, self.tree, self._checks = "", None, None, None
        try:
            if entry is None:
                self.tree = ast.parse(text)
            else:
                self.src = Source(text, entry["lexer"], shown)
        except (SyntaxError, ValueError, ToolRefusal) as exc:
            self.unread = f"{shown} is not read ({fold(str(exc), 120)})"

    def checks(self) -> list:
        if self._checks is None:
            self._checks = _source_checks(self.src, self.entry, self.shown)
        return self._checks

    def _first_in(self, opener: int, closer: int):
        inside = [c for c in self.checks() if opener < c[3] < closer]
        return inside[0][0] if inside else None

    def test_unit(self, spec: dict):
        """{first, last, check, calls} of the test `spec` names in this file: the line of its first check (None: it holds none)
        and the names its body calls. None when the test is not located here (no declaration, more than one, a body not read):
        the plan's own refusal then says it."""
        if self.entry is None:
            function = locate(self.tree, spec["chain"], spec["function"])
            found = _first_check(function, _python_entry()[1]["forms"], self.text)
            return {"first": function.lineno, "last": function.end_lineno,
                    "check": found[0].lineno if found else None, "calls": _called_names(function)}
        matches = declaration_candidates(self.src, self.entry, spec["function"], False, self.shown)
        if len(matches) != 1:
            return None
        try:
            opener, closer = body_span(self.src, self.entry, matches[0], False, self.shown)
        except Refusal:
            return None
        return {"first": self.src.line(matches[0].start()), "last": self.src.line(closer), "check": self._first_in(opener, closer),
                "calls": _called_names((self.src, opener, closer), self.entry)}

    def units(self, name: str) -> list:
        """Every declaration of the helper `name` in this file: {name, first, last, check, calls, unread}. The AST reader: the
        functions and methods of the module; the table: the entry's `helper_declaration` with the name in."""
        out = []
        if self.entry is None:
            forms = _python_entry()[1]["forms"]
            for _at, node in _defs(self.tree.body, [], []):
                if node.name == name:
                    found = _first_check(node, forms, self.text)
                    out.append({"name": name, "first": node.lineno, "last": node.end_lineno, "unread": False,
                                "check": found[0].lineno if found else None, "calls": _called_names(node)})
            return out
        for match in declaration_candidates(self.src, self.entry, name, True, self.shown):
            first = self.src.line(match.start())
            try:
                opener, closer = body_span(self.src, self.entry, match, True, self.shown)
            except Refusal:
                out.append({"name": name, "first": first, "last": first, "check": None, "calls": [], "unread": True})
                continue
            out.append({"name": name, "first": first, "last": self.src.line(closer), "unread": False,
                        "check": self._first_in(opener, closer), "calls": _called_names((self.src, opener, closer), self.entry)})
        return out


def _resolve_import(row: dict, raw: str, directory: Path, root: Path):
    """The file an import names, or None: `relative` joins the path to the importing file's folder and tries it as written (when it
    already ends in a suffix of the row), with each suffix added, and as a folder's `index`; `dotted` tries the dotted name from
    its full length down to its first segment (a trailing segment may be a member or a nested class), as a path under the importing
    file's folder and every folder above it up to the project root (a source root)."""
    suffixes = row["suffixes"]
    if row["resolve"] == "relative":
        base = os.path.normpath(os.path.join(str(directory), raw))
        names = ([base] if base.lower().endswith(tuple(suffixes)) else []) + [base + s for s in suffixes] \
            + [os.path.join(base, "index" + s) for s in suffixes]
    else:
        parts, folders, current = raw.split("."), [], directory.resolve()
        while current == root.resolve() or current.is_relative_to(root.resolve()):
            folders.append(current)
            if current == root.resolve():
                break
            current = current.parent
        names = [os.path.join(str(folder), *parts[:count]) + s for count in range(len(parts), 0, -1)
                 for folder in folders for s in suffixes]
    return next((Path(n) for n in names if os.path.isfile(n)), None)


def _in_code(src, pos: int) -> bool:
    """True when the match starting at `pos` starts in CODE: not inside a string or a comment (the skeleton keeps the character) and
    not on whitespace the declaration pattern's lead-in swallowed."""
    return src.skeleton[pos] == src.code[pos] and not src.code[pos].isspace()


def _imported_modules(hop: "_Hop", root: Path, cfg) -> tuple:
    """([files], [notes]) this file imports from, by its reader. The AST reader: the project modules its `import` statements name.
    The table reader: the files its entry's `import_forms` name, matched in code (a comment hides one), each only when it lies under
    a test root and no protected product path - the guard of N1: a product module is never hopped into; with no config to judge by
    none is. An entry with no form follows nothing (this file only), and the note says so; an import that names no file, or a file
    outside the test tree, is skipped and counted in a note."""
    if hop.entry is None:
        out, outside = [], []
        for node in ast.walk(hop.tree):
            parts = []
            if isinstance(node, ast.ImportFrom) and node.module and not node.level:
                parts = node.module.split(".")
            elif isinstance(node, ast.Import):
                parts = (node.names[0].name.split(".") if node.names else [])
            if not parts:
                continue
            for base in (hop.path.parent, root):
                for file in (base.joinpath(*parts).with_suffix(".py"), base.joinpath(*parts) / "__init__.py"):
                    if not file.is_file() or file in out:
                        continue
                    if cfg is None or not _in_test_root(cfg, _rel_project(file, root)):   # B1: the same guard as the table reader
                        if ".".join(parts) not in outside:
                            outside.append(".".join(parts))
                    else:
                        out.append(file)
        return out, ([f"{len(outside)} import(s) name a file outside the test tree and were not hopped into "
                      f"({_capped(outside, 3)})"] if outside else [])
    rows = AD.import_forms(hop.entry)
    if not rows:
        return [], [f"the {hop.language} entry has no `import_forms` row, so only this file was searched"]
    files, unresolved, outside = [], [], []
    for row in rows:
        for found in row["pattern"].finditer(hop.src.code):
            if not _in_code(hop.src, found.start()):
                continue
            raw = found.group(AD.IMPORT_GROUP)
            file = _resolve_import(row, raw, hop.path.parent, root)
            if file is None:
                unresolved.append(raw)
            elif cfg is None or not _in_test_root(cfg, _rel_project(file, root)):
                outside.append(raw)
            elif file.resolve() != hop.path.resolve() and file not in files:
                files.append(file)
    notes = []
    if unresolved:
        notes.append(f"{len(unresolved)} import(s) named no file of the project and were skipped ({_capped(unresolved, 3)})")
    if outside:
        notes.append(f"{len(outside)} import(s) name a file outside the test tree and were not hopped into ({_capped(outside, 3)})")
    return files, notes


def _hop_file(file: Path, root: Path, entry, language: str):
    try:
        text = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return _Hop(file, text, entry, _rel_project(file, root), language)


def _declared_twice(name: str, hop: "_Hop", units: list, root: Path) -> Refusal:
    """A name declared more than once in one file, one of them holding a check: which is the helper the test calls is not told by
    a name (no type is resolved), so no body is chosen. The checks' lines are the door."""
    shown = _rel_project(hop.path, root)
    checks = [u["check"] for u in units if u["check"] is not None]
    return Refusal(f"probe_by_code: `{name}` is declared {len(units)} times in {shown} (lines "
                   f"{_capped([str(u['first']) for u in units], CANDIDATE_CAP)}) and a check stands in "
                   f"{'one of them' if len(checks) == 1 else 'more than one'}; which one the test calls is not told by the name "
                   f"(no type is resolved), so no body is mutated. Door: `--at {shown}:<line>` with the line of the check you mean "
                   f"({_capped([str(n) for n in checks], CANDIDATE_CAP)}). Nothing was changed.")


def _declared_in_files(name: str, found: list, root: Path) -> ToolRefusal:
    """A name holding a check in more than one hop file: a method is read by its bare name and no type is resolved, so which file the
    test calls is not told. A ToolRefusal: the reader's gap is the factory's, so the record reaches the seam. Every file:line of a
    check is named and is the door."""
    where = [f"{_rel_project(h.path, root)}:{held[0]['check']}" for h, held in found]
    return ToolRefusal(f"probe_by_code: `{name}` is declared in {' and '.join(_rel_project(h.path, root) + ':' + str(held[0]['first']) for h, held in found)} "
                       f"with a check in more than one; which one the test calls is not told by the name (no type is resolved), "
                       f"so no body is mutated. Door: `--at <file>:<line>` of the check you mean ({_capped(where, CANDIDATE_CAP)}). "
                       "Nothing was changed.")


def _second_hop(spec: dict, declared: list, hops: list, root: Path, cfg, entry, language: str, chain=frozenset()):
    """A ToolRefusal when a helper the test calls (and which holds no check) calls one that does: the check is two hops away. One
    hop is followed and a chain is never guessed; the door is the check's own line. None when there is no such helper."""
    pool, seen = list(hops), {h.path.resolve() for h in hops}
    for hop, _name, _unit in declared:
        if hop is hops[0]:
            continue
        for file in _imported_modules(hop, root, cfg)[0]:
            made = None if file.resolve() in seen else _hop_file(file, root, entry, language)
            if made is not None and not made.unread:
                seen.add(file.resolve())
                pool.append(made)
    for hop, name, unit in declared:
        for second in unit["calls"]:
            found_in = [(other, [u for u in other.units(second) if u["check"] is not None]) for other in pool
                        if not other.unread and other.path.resolve() not in chain]
            found_in = [(o, held) for o, held in found_in if held]
            if len(found_in) > 1:      # the same rule as B2: a bare name with a check in two files is not told by the name
                return _declared_in_files(second, found_in, root)
            for other in pool:
                holding = [u for u in (other.units(second) if not other.unread else []) if u["check"] is not None]
                if holding:
                    shown, line = _rel_project(other.path, root), holding[0]["check"]
                    return ToolRefusal(
                        f"probe_by_code: the body of {spec['node']} holds no check of a form the factory reads, and neither does "
                        f"`{name}` (line {unit['first']} of {_rel_project(hop.path, root)}), the helper it calls: the check stands "
                        f"one hop further, in `{second}` (line {line} of {shown}). One hop is followed and a chain is never guessed. "
                        f"Doors: `--at {shown}:{line}` (the check, when it is the Then's), or `--oracle {shown}::{second}`. "
                        "Nothing was changed.")
    return None


def pick_hop(test: dict, hops: list, in_chain) -> tuple:
    """The ONE hop rule (AR-13), pure over already-read `_Hop`s: which helper the test's body calls holds the check. `test` is the
    test's unit (`calls` in source order), `hops` the files searched (the test's own first), `in_chain(hop)` tells a conftest (test
    plumbing, never counted for a cross-file ambiguity). Returns one of: `("found", hop, name, holding_units)` - the first helper in
    call order that holds a check; `("twice", name, hop, units)` - a name declared more than once in one file with a check in one;
    `("files", name, [(hop, held)])` - a name with a check in two non-chain files; `("none", [(hop, name, first_unit)])` - the
    helpers declared with no check. Callers: `find_oracle` (reads the files, raises on the ambiguities) and `checks_of` (reads
    nothing, notes them)."""
    declared = []
    for name in test["calls"]:
        for hop in hops:
            units = [] if hop.unread else hop.units(name)
            if not units:
                continue
            holding = [u for u in units if u["check"] is not None]
            if len(units) > 1 and holding:
                return ("twice", name, hop, units)
            if holding:
                if not in_chain(hop):         # B2: the same name with a check in a second file is not told by the name
                    found_in = [(hop, holding)] + [(h, [u for u in h.units(name) if u["check"] is not None]) for h in hops
                                                   if h is not hop and not h.unread and not in_chain(h)]
                    found_in = [(h, held) for h, held in found_in if held]
                    if len(found_in) > 1:
                        return ("files", name, found_in)
                return ("found", hop, name, holding)
            declared.append((hop, name, units[0]))
    return ("none", declared)


def find_oracle(text: str, spec: dict, path: Path, root: Path, helpers: list, reader_entry=None, cfg=None) -> tuple:
    """((file, function name, its unit, the line of its check), note) for the check this probe must mutate; (None, "") when the
    test's own body is not read here (the plan then refuses in its own words). Reached only when the target is the test's FIRST
    check (`_target_of`); `reader_entry` is the table entry, None for the AST reader (`_reader_entry`).

    The test's own body first. Then ONE hop out, the helpers its body calls by name, in source order, searched in the test's file,
    then (the AST reader) its conftest chain, then the files it imports: the first declaration that holds a check. A name
    declared twice in one file with a check in one of them is a refusal that names the lines; a check two hops away is a ToolRefusal
    whose door is its line; with nothing found the table reader refuses (door `--at <file>:<line>`) and the AST reader returns
    (None, "") for `plan_mutation`'s refusal. `note` is empty when the oracle is the test's own; otherwise it says where it went
    and that the file is shared, because a mutation there is visible to every test using that helper for the length of one probe."""
    language = str(spec.get("language") or "")
    own = _Hop(path, text, reader_entry, spec["file"], language)
    if own.unread:
        return (None, "")
    test = own.test_unit(spec)
    if test is None:
        return (None, "")
    if test["check"] is not None:
        return (path, spec["function"], None, test["check"]), ""
    hops, notes = [own], []
    files = [Path(h) for h in helpers] if reader_entry is None else []
    chain = {f.resolve() for f in files}      # the conftest chain: test plumbing, nearest first (pytest's own resolution order), never counted by B2
    imported, import_notes = _imported_modules(own, root, cfg)
    notes += import_notes
    for file in files + imported:
        if all(file.resolve() != h.path.resolve() for h in hops):
            made = _hop_file(file, root, reader_entry, language)
            if made is not None:
                hops.append(made)
    picked = pick_hop(test, hops, lambda h: h.path.resolve() in chain)
    if picked[0] == "twice":
        raise _declared_twice(picked[1], picked[2], picked[3], root)
    if picked[0] == "files":
        raise _declared_in_files(picked[1], picked[2], root)
    if picked[0] == "found":
        _kind, hop, name, holding = picked
        line, where = holding[0]["check"], (hop.path.name if hop.path.resolve() != path.resolve() else "this file")
        extra = f" ({'; '.join(notes)})" if notes else ""
        return ((hop.path, name, holding[0], line),
                f"the test body asserts nothing; its oracle is `{name}` in {where} "
                f"(line {line}), which other tests share — the mutation lives "
                f"there for the length of this probe and is restored with it{extra}")
    declared = picked[1]
    looked = [f"`{name}` ({_rel_project(hop.path, root)}:{unit['first']}, no check)" for hop, name, unit in declared]
    deeper = _second_hop(spec, declared, hops, root, cfg, reader_entry, language, chain)
    if deeper is not None:
        raise deeper
    if reader_entry is None:
        return (None, "; ".join(notes))
    seen = f"it calls {_capped(looked, 4)}" if looked else "it calls no helper declared in this file or in a file it imports"
    raise ToolRefusal(
        f"probe_by_code: no recognised assertion in the body of {spec['node']!r} (lines {test['first']}-{test['last']} of "
        f"{spec['file']}), and none in what it calls: {seen}. {('; '.join(notes) + '. ') if notes else ''}A fixture a framework hands "
        "in (`test.extend`) is not followed, and neither is a call two hops out. Doors: `--at <file>:<line>` (the line of the check "
        "the Then is, in this file or in a helper under a test root), `--oracle [<file>::]<helper>` when the expectation lives in a "
        "helper, or add the assertion's head as a form of references/detectors.json "
        f"assertion_probes.{language} (the factory's data). Nothing was changed.")


def enclosing_declaration(data: bytes, reader_entry, line: int):
    """{name, first, last} of the innermost function or helper declaration of a file that holds `line`, None when none does (pure; for
    a reader of a helper's span, N5b). The AST reader (`reader_entry` None): the innermost FunctionDef or AsyncFunctionDef. The
    table: the declarations the entry's `helper_declaration` finds with the name open, whose body (or head) spans the line, the one
    that starts last. `first`/`last` are the declaration's first line and its body's last line. A file the reader cannot read is None."""
    raw = data[len(_BOM):] if data.startswith(_BOM) else data
    try:
        text = raw.decode("utf-8")
        if reader_entry is None:
            held = [n for n in ast.walk(ast.parse(text)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.lineno <= line <= n.end_lineno]
            best = max(held, key=lambda n: (n.lineno, -n.end_lineno), default=None)
            return None if best is None else {"name": best.name, "first": best.lineno, "last": best.end_lineno}
        src = Source(text, reader_entry["lexer"], "")
        best = None
        for match in _any_declaration(reader_entry).finditer(src.code):
            if not _in_code(src, match.start()):
                continue
            try:
                _opener, closer = body_span(src, reader_entry, match, True, "")
            except Refusal:
                continue
            first, last = src.line(match.start()), src.line(closer)
            if first <= line <= last and (best is None or first >= best["first"]):
                best = {"name": match.group("name"), "first": first, "last": last}
        return best
    except (Refusal, SyntaxError, UnicodeDecodeError, ValueError, RecursionError):
        return None


def declared_once(data: bytes, suffix: str, function: str) -> str:
    """"" when `function` is declared exactly once in this file by the reader of `suffix`, else the reason it is not: the AST's
    `locate` for a suffix `assertion_probes_ast` claims, the entry's `helper_declaration` for a suffix of `assertion_probes`. A
    suffix no entry claims is a reason that names the data gap, never a pass (pure; `probe_debt` replays by it, so code never
    replays a helper the probe would refuse)."""
    raw = data[len(_BOM):] if data.startswith(_BOM) else data
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return f"the file is not UTF-8 ({exc.reason} at byte {exc.start})"
    try:
        language, ast_row = AD.ast_entry(suffix)
        entry = None
        if ast_row is None:
            language, entry = AD.entry_for_suffix(AD.assertion_detectors(), suffix)
    except AD.DetectorsError as exc:
        return f"factory data gap: {exc}"
    if ast_row is None and entry is None:
        return (f"{suffix or 'a file with no suffix'} has no entry in references/detectors.json (assertion_probes, "
                f"assertion_probes_ast): a factory data gap, so code cannot tell whether {function} is declared once")
    if entry is None:
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError) as exc:
            return f"it does not parse ({type(exc).__name__})"
        try:
            locate(tree, [], function)
        except Refusal as exc:
            return str(exc)
        return ""
    hop = _Hop(Path(""), text, entry, "", language)
    if hop.unread:
        return hop.unread
    units = hop.units(function)
    if not units:
        return (f"no declaration of {function} matches the {language} entry's `helper_declaration` "
                "(references/detectors.json), so it cannot be replayed by name")
    if len(units) > 1:
        return f"{function} is declared {len(units)} times (lines {_capped([str(u['first']) for u in units], CANDIDATE_CAP)})"
    if units[0]["unread"]:
        return f"the body of {function} (line {units[0]['first']}) is not certainly read"
    return ""


# --- the mutation --------------------------------------------------------------------------------

def _line_starts(data: bytes) -> list:
    starts, pos = [0], 0
    while True:
        pos = data.find(b"\n", pos)
        if pos < 0:
            return starts
        pos += 1
        starts.append(pos)


def _span(starts: list, node) -> tuple:
    return (starts[node.lineno - 1] + node.col_offset,
            starts[node.end_lineno - 1] + node.end_col_offset)


def _padded(text: bytes, wanted_newlines: int) -> bytes:
    """`text` with newlines added inside its last parenthesis so a statement keeps its line
    count — every line after the mutated assert stays where the author's run reported it."""
    missing = wanted_newlines - text.count(b"\n")
    return text if missing <= 0 else text + b"\n" * missing


class Replacement(NamedTuple):
    """What `plan_mutation` has fixed about the one statement it replaces, handed to the builder of the
    replacement text: the statement's node, the source (BOM stripped) with its line starts, `seg` (the
    source of a node of it) and the statement's newline count, which the replacement must keep."""
    target: ast.AST
    text: bytes
    starts: list
    seg: Callable
    newlines: int


def _shown(message: str, marker: str) -> bytes:
    """The message a mutated check carries: the marker expression when one was given, else the human marker as a literal."""
    return message.encode("utf-8") if message else json.dumps(marker).encode("utf-8")


def _assert_replacement(rep: Replacement, instance_id: str, message: str = "") -> tuple:
    """(the replacement of an `assert` statement, the human marker, the plain inversion): `assert not (<expr>), <message>`.
    `message` is the factory's marker EXPRESSION, joined at run time (`AD.marker_expression`, t-2045 N2); "" keeps the literal
    text of the human marker as the message. Every line the statement spanned is still there (`_padded`). `--mutation
    expected` is gone (t-2045 N7): one inversion."""
    target, _text, _starts, seg, newlines = rep
    marker = f"probe-{instance_id} invert: {fold(seg(target.test).decode('utf-8', 'replace'))}"
    body = _padded(b"assert not (" + seg(target.test), newlines) + b")"
    return body + b", " + _shown(message, marker), marker, body


def _not_invertible(unit: str, where: str, shown: str, name: str, line: int, asked, reason: str, next_line) -> "ToolRefusal":
    """THE refusal of a check that is read but not inverted (E7, both readers: the python rows and the table), one text so the
    two roads cannot drift (t-2122 F1). `unit` is "check" or "assertion"; `asked` is the line the role's target named (`--at`
    or the id), None when the plan took the first one - the text says which, so a check the role chose is never called "first";
    `reason` says which row and why; `next_line` is the line of the next check the reader knows, so the door `--at` prints
    a line that opens (FR-2), not a placeholder. Never a guess and never a skip to a later check. A `ToolRefusal` (t-2045 N4, E-F: the
    row's `invert: null` is a gap of the factory's data, never a verdict on the test), so it leaves the record `refused: tool` that
    reaches the seam; the refusal's text and the exit are unchanged."""
    lead = (f"the {unit} `{name}` at line {line} of {shown} (the line {asked} asked for)" if asked is not None
            else f"the first {unit} of {where}, `{name}` at line {line} of {shown}")
    door = (f"`--at {next_line}` probes the next {unit} of the file" if next_line is not None
            else f"no other {unit} of a form the factory reads follows it in the file, `--at <file>:<line>` names one elsewhere")
    return ToolRefusal(f"probe_by_code: {lead}, {reason}: not invertible by code - the role's model or the critic's red probe carries "
                   f"it. It never skips to a later {unit}, because what is mutated must be what the record says. Doors: {door}, "
                   "`--oracle [<file>::]<helper>` another place; the product-breaking probe does not read it: "
                   f"{RED_SANDBOX_DOOR}. Nothing was changed.")


class _NoInversion(Refusal):
    """A row read the check but has no inversion for it (a method the rename map or the patterns do not cover); `plan_mutation`
    turns it into `_not_invertible` with the context only it has (the asked line, the next check)."""

    def __init__(self, form: dict, name: str):
        super().__init__(f"row {form['id']} has no inversion for `{name}`")
        self.form, self.name = form, name


def _no_inversion(form: dict, name: str, line: int) -> Refusal:
    return _NoInversion(form, name)


def _kept(positional: list, keywords: list, slot, count: int) -> list:
    """The argument texts of a rebuilt call: with a message slot the first `count` positionals and every keyword but the
    message's own (an author's message is replaced); with none, every argument as the author wrote it."""
    if slot is None:
        return positional + [text for _name, text in keywords]
    return positional[:count] + [text for name, text in keywords if name != slot["kw"]]


def _call_replacement(rep: Replacement, instance_id: str, form: dict, name: str, message: str = "") -> tuple:
    """(the replacement of a `call`, `method` or `chain` statement, the human marker, the plain inversion), by the row `form`
    (t-2045 N2b; the row's data names every wrap, rename and message slot). `call`: the argument `invert.arg` wrapped by the row's
    text, the message put at the positional `message.arg` (the arguments from there on are the message's); `method`: the method
    renamed by the row's map, the arguments up to the map's count kept, the message the keyword `message.kw` (an author's keyword
    or a positional beyond the count is replaced); `chain`: the method name of the outer call changed by the first pattern that
    matches, the message the keyword `message.kw` of the head call (positionals beyond `message.args` replaced), the text between
    the head and the name, and after it, kept as written (an `await` stays). A row with no `message` adds none. `message` as in
    `_assert_replacement`. Every line the statement spanned is still there (`_padded`)."""
    target, text, starts, seg, _newlines = rep
    call = _call_of(target)
    invert, slot = form["invert"], form.get("message")
    stmt_start, stmt_end = _span(starts, target)
    call_start, call_end = _span(starts, call)
    lead, trail = text[stmt_start:call_start], text[call_end:stmt_end]
    positional = [seg(a) for a in call.args]
    keywords = [(k.arg, seg(k)) for k in call.keywords]
    kind = invert["kind"]
    marker = f"probe-{instance_id} invert: {fold(seg(call).decode('utf-8', 'replace'))}"
    if kind == "method_pattern":
        return _chain_replacement(rep, instance_id, form, message, marker)
    if kind == "wrap_arg":
        index = invert["arg"]
        subject = positional[index]
        marker = f"probe-{instance_id} invert: {fold(subject.decode('utf-8', 'replace'))}"
        positional[index] = invert["wrap"].encode("utf-8").replace(AD.ARG.encode(), subject)
        kept = positional[:slot["arg"]] if slot else positional + [text_ for _n, text_ in keywords]
        core = seg(call.func) + b"(" + b", ".join(kept)
        label = b""
    else:
        old = call.func.attr
        rename = invert["names"].get(old)
        if rename is None:
            raise _no_inversion(form, name, target.lineno)
        func = seg(call.func)
        kept = _kept(positional, keywords, slot, rename["args"])
        core = func[:len(func) - len(old.encode("utf-8"))] + rename["to"].encode("utf-8") + b"(" + b", ".join(kept)
        label = slot["kw"].encode("utf-8") + b"=" if slot else b""
    core = _padded(core, seg(call).count(b"\n"))
    inverted = lead + core + b")" + trail
    if not slot:
        return inverted, marker, inverted
    sep = b", " if kept else b""
    return lead + core + sep + label + _shown(message, marker) + b")" + trail, marker, inverted


def _chain_replacement(rep: Replacement, instance_id: str, form: dict, message: str, marker: str) -> tuple:
    """`_call_replacement` of a `chain` statement `<head>(...).<method>(...)`: the head call carries the message, the method
    name is inverted by the row's patterns, everything between and after is kept byte for byte."""
    target, text, starts, seg, _newlines = rep
    call = _call_of(target)
    slot, pairs = form.get("message"), form["invert"]["pairs"]
    stmt_start, stmt_end = _span(starts, target)
    call_start, call_end = _span(starts, call)
    head = call.func.value
    head_start, head_end = _span(starts, head)
    attr = call.func.attr
    func_end = _span(starts, call.func)[1]
    name_start = func_end - len(attr.encode("utf-8"))
    for pair in pairs:
        if re.search(pair["find"], attr):
            new_name = re.sub(pair["find"], pair["replace"], attr, count=1)
            break
    else:
        raise _no_inversion(form, attr, target.lineno)
    keywords = [(k.arg, seg(k)) for k in head.keywords]
    kept = _kept([seg(a) for a in head.args], keywords, slot, slot["args"] if slot else 0)
    core = _padded(seg(head.func) + b"(" + b", ".join(kept), seg(head).count(b"\n"))
    after = text[head_end:name_start] + new_name.encode("utf-8") + text[func_end:call_end]
    lead, trail = text[stmt_start:head_start], text[call_end:stmt_end]
    inverted = lead + core + b")" + after + trail
    if not slot:
        return inverted, marker, inverted
    sep = b", " if kept else b""
    shown = slot["kw"].encode("utf-8") + b"=" + _shown(message, marker)
    return lead + core + sep + shown + b")" + after + trail, marker, inverted


def _assert_with_marker(rep: Replacement, message: str) -> bytes:
    """The un-inverted `_assert_replacement` (t-2064 P3): the `assert` statement AS WRITTEN with the factory's marker EXPRESSION `message`
    (joined at run time) as its message - `assert (<test>), <message>`. An author's message is REPLACED, as N2's rule has it for the
    inversion (the check's own failure then reads the marker, not the author's words). Every line the statement spanned is still there."""
    target, _text, _starts, seg, newlines = rep
    return _padded(b"assert (" + seg(target.test), newlines) + b"), " + message.encode("utf-8")


def _assert_that_with_marker(rep: Replacement, form: dict, message: str):
    """The un-inverted `_call_replacement` (t-2064 P3): the statement of a `call`, `method` or `chain` form AS WRITTEN, the factory's
    marker EXPRESSION `message` at the form's message slot - a positional message at its place BEFORE the keywords, the keywords
    kept, an author's message (a positional beyond the slot, or the slot's own keyword) replaced. None when the form has no message
    slot or no way to tell where the message goes (a method the row's map does not name, a chain whose head is not a call, a call with
    fewer positionals than the slot): the caller then puts no marker in and says so, never a guess. Every line is still there."""
    target, text, starts, seg, _newlines = rep
    slot, invert, call = form.get("message"), form.get("invert"), _call_of(target)
    if not slot or call is None or not isinstance(invert, dict):
        return None
    stmt_start, stmt_end = _span(starts, target)
    call_start, call_end = _span(starts, call)
    trail = text[call_end:stmt_end]
    shown = message.encode("utf-8")
    kind = invert["kind"]
    if kind == "method_pattern":
        head = call.func.value if isinstance(call.func, ast.Attribute) else None
        if not isinstance(head, ast.Call):
            return None
        head_start, head_end = _span(starts, head)
        kept = _kept([seg(a) for a in head.args], [(k.arg, seg(k)) for k in head.keywords], slot, slot["args"])
        core = _padded(seg(head.func) + b"(" + b", ".join(kept) + (b", " if kept else b"") + slot["kw"].encode("utf-8") + b"=" + shown,
                       seg(head).count(b"\n"))
        return text[stmt_start:head_start] + core + b")" + text[head_end:call_end] + trail
    positional, keywords = [seg(a) for a in call.args], [(k.arg, seg(k)) for k in call.keywords]
    if kind == "wrap_arg":
        if len(positional) < slot["arg"]:
            return None
        parts = positional[:slot["arg"]] + [shown] + [part for _name, part in keywords]
        core = seg(call.func) + b"(" + b", ".join(parts)
    elif kind == "rename":
        rename = invert["names"].get(call.func.attr)
        if rename is None:
            return None
        kept = _kept(positional, keywords, slot, rename["args"])
        core = seg(call.func) + b"(" + b", ".join(kept) + (b", " if kept else b"") + slot["kw"].encode("utf-8") + b"=" + shown
    else:
        return None
    return text[stmt_start:call_start] + _padded(core, seg(call).count(b"\n")) + b")" + trail


def plan_mutation(data: bytes, spec: dict, mutation: str, instance_id: str,
                  oracle_function: str = "", oracle_note: str = "", at=None, marker_token: str = "") -> tuple:
    """(mutated bytes, detail) — nothing is written here.

    `oracle_function` names a function in THESE bytes instead of the test itself: the helper or
    fixture `find_oracle` followed the expectation into. `at` (t-2045 N1; a line number) names the check to mutate: the
    check (a statement one of the `assertion_probes_ast.python.forms` rows reads) whose statement starts or spans that line, ANYWHERE in these bytes (a helper, a page-object
    method), so no function is looked up; a line with no check is a refusal that names the nearest one (`check_on_line`).

    `marker_token` (t-2045 N2; "" = none, which is how a direct caller plans): the factory's marker `qa-probe-<token>` travels as
    the check's MESSAGE, an expression joined at run time (the `assertion_probes_ast` entry's `marker_expr`), so a traceback's
    echo of the source line never holds the contiguous token. The detail has the keys `plan_detector_mutation`'s has
    (`language` is "python" here only; `form` and `message_form` are the check's row id; `pair`, `pair_id` are None; `fires_as` and
    `matcher_at` are the row's, `style` and `head` the matched name), `message_marker` is "qa-probe-<token>" or "" with no token
    (or when the row has no message slot, which `message_note` says), and `statement_inverted` is the plain
    inversion, with no message. With no token the message stays the human marker's text, as before. `detail["file"]` is the test's `spec["file"]` (the
    oracle case: `_probe` overwrites it, as before)."""
    if mutation not in MUTATIONS:
        raise Refusal(f"--mutation is one of {', '.join(MUTATIONS)}")
    bom = data.startswith(b"\xef\xbb\xbf")
    text = data[3:] if bom else data
    try:
        tree = ast.parse(text.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise Refusal(f"{spec['file']} does not parse: {exc}") from exc
    language, entry = _python_entry()
    forms, file_text = entry["forms"], text.decode("utf-8")
    note = ""
    declaration_line = None
    if at is not None:
        checks = _python_checks(tree, forms, file_text)
        hit = [c for c in checks if c[0] <= at <= c[1]]
        if not hit:
            raise _no_check_refusal(spec["file"], at, _line_facts([(c[0], c[1], c[2]) for c in checks], at,
                                                                   _python_call_name(tree, at)))
        target, form, name = hit[0][3], hit[0][5], hit[0][6]
        if len({c[4] for c in checks if c[0] == target.lineno}) > 1:
            note = f"two checks start on line {target.lineno}; the first is the one inverted"
    else:
        function = (locate(tree, [], oracle_function) if oracle_function
                    else locate(tree, spec["chain"], spec["function"]))
        first = _first_check(function, forms, file_text)
        declaration_line = function.lineno
        if first is None:       # N4: nothing the table's rows read - the factory's gap (the rows' data), never a verdict: a record for the seam
            raise ToolRefusal(f"{spec['node']}: the function body has no {_form_label(forms[0])} and no other check of a form the "
                          f"factory reads (rows {', '.join(f['id'] for f in forms)} of assertion_probes_ast.python.forms), and "
                          "neither has any helper or fixture it calls — nothing to mutate. "
                          "If the expectation lives further out than one hop, name it: "
                          "`--oracle [<file>::]<function>`"
                          + (f". {oracle_note}; a check that lives in product code is probed by {RED_SANDBOX_DOOR}"
                             if oracle_note and not oracle_function else ""))
        target, form, name = first
        skipped = _skipped_calls(function, target)
        if skipped:      # a call no row reads stands before the check the plan takes: named, never decided (INV of N2b)
            shown = ", ".join(str(n) for n in skipped[:CANDIDATE_CAP]) + (f" and {len(skipped) - CANDIDATE_CAP} more" if len(skipped) > CANDIDATE_CAP else "")
            note = (f"{len(skipped)} call statement(s) before line {target.lineno} matched no row of assertion_probes_ast.python.forms "
                    f"({', '.join(f['id'] for f in forms)}): line {shown}; the first check a row reads is `{name}` at line "
                    f"{target.lineno}, and that is the one inverted. When one of those calls is the Then's check, `--at <line>` probes it")
    def gap(reason: str) -> Refusal:
        later = [c[0] for c in _python_checks(tree, forms, file_text) if c[0] > target.lineno]
        return _not_invertible("check", spec["node"], spec["file"], name, target.lineno, at, reason, later[0] if later else None)
    if form["invert"] is None:
        raise gap(f"a form the python rows do not invert (assertion_probes_ast.python.forms row {form['id']} has invert null)")
    starts = _line_starts(text)
    seg = lambda node: text[slice(*_span(starts, node))]  # noqa: E731
    stmt_start, stmt_end = _span(starts, target)
    original = text[stmt_start:stmt_end]
    newlines = original.count(b"\n")
    detail = {"line": target.lineno, "end_line": target.end_lineno, "mutation": mutation, "style": name,
              "language": language, "head": name, "form": form["id"], "pair": None, "pair_id": None, "at": at,
              "candidates": [], "statement_before": original.decode("utf-8", "replace")}
    if note:
        detail["target_note"] = note
    if oracle_function:
        # The reader must see that the mutated line is not in the test: a probe of a shared
        # oracle proves the expectation fires, and says where that expectation lives.
        detail["oracle_function"] = oracle_function
        detail["oracle_note"] = oracle_note

    rep = Replacement(target, text, starts, seg, newlines)
    expression = AD.marker_expression(entry, marker_token) if marker_token else ""
    if form["shape"] == "assert":
        replaced, marker, inverted = _assert_replacement(rep, instance_id, expression)
    else:
        try:
            replaced, marker, inverted = _call_replacement(rep, instance_id, form, name, expression)
        except _NoInversion as missing:
            raise gap(f"read by row {missing.form['id']} of assertion_probes_ast.python.forms, but that row has no inversion "
                          "for it (add one to the row: the factory's data)") from None
    slot = form.get("message") is not None
    # The message is the joined expression when a token was given; else the human marker's text, and the detail says no factory
    # marker is in the statement (AR-23: "" falls through, never an error). `message_note` is always "" here: `ast_entry`
    # validates `marker_expr` as required, so a token always yields an expression (the key stays for the detector's key set).
    detail.update({"statement_after": replaced.decode("utf-8", "replace"),
                   "statement_inverted": inverted.decode("utf-8", "replace"), "marker": marker,
                   "message_marker": MARKER_PREFIX + marker_token if expression and slot else "",
                   "message_form": form["id"] if expression and slot else "",
                   "message_note": (f"row {form['id']} has no message slot, so the check carries no factory marker"
                                    if expression and not slot else ""),
                   "fires_as": form.get("fires_as"), "matcher_at": form.get("matcher_at"),
                   "declaration_line": declaration_line, "file": spec["file"],
                   "target_source": None, "target_outside_body": None})
    if replaced.count(b"\n") != newlines:
        raise Refusal("internal: the mutated statement would change the file's line count")
    mutated = text[:stmt_start] + replaced + text[stmt_end:]
    try:
        ast.parse(mutated.decode("utf-8"))
    except SyntaxError as exc:
        raise Refusal(f"the mutated statement does not parse ({exc}); report it as tooling") from exc
    return (b"\xef\xbb\xbf" + mutated if bom else mutated), detail


# --- a test in another language: the detector path (B-373 c) ---------------------------------------------
# The Python path above mutates one `assert` found by the AST. For any other language the same proof - "the
# check is live" - needs a way to find the test, its first assertion and the one inverted form of it, and
# that is DATA (`references/detectors.json` `assertion_probes`, FR-13, read only by `assertion_detectors`).
# What is code here is what no table can say: reading the source with the entry's lexer, matching brackets,
# and deciding from the run's report. Every function on this path errs one way: toward a refusal before a
# byte is written, or toward `incomplete` after the run - never toward a verdict on the author's test that
# the tool did not actually read (FR-59, E26).

RED_SANDBOX_DOOR = ("red_sandbox.py --probe --repo <project root> --request <mutations.json> "
                    "--task-root <task root>")
OPEN_BRACKETS, CLOSE_BRACKETS = "([{", ")]}"
BRACKET = re.compile(r"[()\[\]{}]")
LINE_BREAK = re.compile(r"\r\n|\r|\n")
IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")
# A line break inside a statement that may end at one (`semicolon_or_newline`): the statement goes on when the
# last code character before the break, or the first one after it, only a continuation can have.
CONTINUES_BEFORE = ".,+-*/%|&=?:<>!"
CONTINUES_AFTER = ".?:,+-*/%|&=<>([`"
OPERAND = "<operand>"  # what the lexer remembers after a string or a regex literal: a `/` after it divides
CANDIDATE_CAP = 5   # candidate declarations a refusal lists, then "and N more"
OFFENDER_CAP = 5    # manifest rows a refusal lists, then "and N more"
NAME_BOUNDARY = ".  /:"   # what may stand right before the tail inside a report id (or nothing: its start)


def _blank(chunk: str) -> str:
    """The chunk with every character but a line break turned into a space: offsets and lines survive."""
    return re.sub(r"[^\r\n]", " ", chunk)


def _string_end(text: str, pos: int, spec: dict) -> int:
    """The index after the closing delimiter of the string whose body starts at `pos`, or -1."""
    close, escape = spec["close"], spec["escape"]
    if escape == "backslash":
        scan = re.compile(r"\\.|" + re.escape(close), re.S)
        while True:
            hit = scan.search(text, pos)
            if hit is None:
                return -1
            if hit.group(0) == close:
                return hit.end()
            pos = hit.end()
    while True:
        found = text.find(close, pos)
        if found < 0:
            return -1
        if escape == "double" and text.startswith(close, found + len(close)):
            pos = found + 2 * len(close)  # a doubled delimiter is one escaped character
            continue
        return found + len(close)


def _line_end(text: str, pos: int) -> int:
    """The index of the line break that ends the line `pos` is on (the end of the text when there is none)."""
    return re.compile(r"[^\r\n]*").match(text, pos).end()


def _regex_opens(text: str, pos: int, spec: dict, prev_char: str, prev_word: str) -> bool:
    """Does the `/` at `pos` open a regular-expression literal rather than divide? By the entry's `after` data: the
    last code character before it is one of `after.chars`, or the word it ends is one of `after.words`, or the
    `/` is the first thing on its line or in the file. After an operand - an identifier, a number, `)`, `]`, a
    string, another literal - it divides (`a / b`, `x = y /g/ 2`)."""
    start = max(text.rfind("\n", 0, pos), text.rfind("\r", 0, pos)) + 1
    after = spec["after"]
    return (not text[start:pos].strip() or (bool(prev_char) and prev_char in after["chars"])
            or prev_word in after["words"] or not prev_char)


def _regex_end(text: str, pos: int, spec: dict) -> int:
    """The index after the closing `/` of the regex literal whose body starts at `pos`, or -1. A backslash escapes
    one character; inside a class `[...]` a `/` does not close; a line break before the close is -1 (unless the
    spec allows lines to be crossed)."""
    escape, close, class_open, class_close = spec["escape"], spec["close"], spec["class_open"], spec["class_close"]
    in_class, index = False, pos
    while index < len(text):
        char = text[index]
        if char == escape:
            index += 2
            continue
        if char in "\r\n" and not spec.get("multiline", False):
            return -1
        if in_class:
            in_class = char != class_close
        elif char == class_open:
            in_class = True
        elif char == close:
            return index + 1
        index += 1
    return -1


def lex(text: str, lexer: dict) -> tuple:
    """(code, skeleton, state). `code` is the text with comments blanked and strings kept (a declaration and
    its title are matched there); `skeleton` is the same with strings blanked too (brackets, heads and
    statement ends are read there: a head inside a string or a comment is never the first assertion, E8).
    Both keep every offset and every line break. `state` is `code`, or what the text ends inside."""
    line_comments = list(lexer.get("line_comments") or [])
    blocks = {opener: closer for opener, closer in lexer.get("block_comments") or []}
    strings = {spec["open"]: spec for spec in lexer["strings"]}
    openers = sorted(set(line_comments) | set(blocks) | set(strings), key=len, reverse=True)
    finder = re.compile("|".join(re.escape(o) for o in openers))
    regex = lexer.get("regex_literal")
    if regex:
        openers = sorted(set(openers) | {regex["open"]}, key=len, reverse=True)
        finder = re.compile("|".join(re.escape(o) for o in openers))
    code, skeleton, at, state = [], [], 0, "code"
    prev_char, prev_word = "", ""  # the last code character before a `/`, and the word it ends (a regex is told from a division by them)
    while at < len(text):
        hit = finder.search(text, at)
        stop = len(text) if hit is None else hit.start()
        code.append(text[at:stop])
        skeleton.append(text[at:stop])
        if hit is None:
            break
        seen = text[at:stop].rstrip()
        if seen:
            prev_char = seen[-1]
            word = re.search(r"[A-Za-z_$][\w$]*$", seen)
            prev_word = word.group(0) if word else ""
        opener = hit.group(0)
        if regex and opener == regex["open"] and not _regex_opens(text, stop, regex, prev_char, prev_word):
            code.append(opener)  # a division sign: code
            skeleton.append(opener)
            prev_char, prev_word, at = opener, "", stop + len(opener)
            continue
        if regex and opener == regex["open"]:
            end = _regex_end(text, stop + 1, regex)
            comment = False
            if end < 0:
                end = _line_end(text, stop)
                state = (f"a regex literal that opens at line {1 + len(LINE_BREAK.findall(text[:stop]))} "
                         "and does not close on its line")
            prev_char, prev_word = OPERAND, ""
        elif opener in line_comments:
            end = re.compile(r"[^\r\n]*").match(text, stop).end()
            comment = True
        elif opener in blocks:
            closed = text.find(blocks[opener], stop + len(opener))
            end, comment = (len(text), True) if closed < 0 else (closed + len(blocks[opener]), True)
            if closed < 0:
                state = "a block comment"
        else:
            end, comment = _string_end(text, stop + len(opener), strings[opener]), False
            prev_char, prev_word = OPERAND, ""  # after a string a `/` is a division
            if end < 0:
                end, state = len(text), "a string literal"
            elif strings[opener].get("multiline", True) is False and LINE_BREAK.search(
                    re.sub(r"\\(?:\r\n|.)", "", text[stop:end], flags=re.S)):
                # A string the language ends at the line break, read across one: the lexer took a quote that
                # is not one (a regex literal `/can't/`, an apostrophe in text it does not know) for an
                # opener, so everything up to the next quote is misread - a head can sit "in code" that is
                # really a string. Only a backslash-newline continuation may cross a line.
                state = ("a single-line string that crosses a line break (it opens at line "
                         f"{1 + len(LINE_BREAK.findall(text[:stop]))})")
        piece = text[stop:end]
        code.append(_blank(piece) if comment else piece)
        skeleton.append(_blank(piece))
        at = end
    return "".join(code), "".join(skeleton), state


def _text_line_starts(text: str) -> list:
    """Where each line of `text` starts, a line ending at `\\r\\n`, `\\r` or `\\n` (axis 7). The Python path
    slices BYTES by `\\n` (`_line_starts`); this reads the decoded text of another language."""
    return [0] + [m.end() for m in LINE_BREAK.finditer(text)]


def lexical_shape(text: str, lexer: dict) -> tuple:
    """What a one-statement edit must leave alone: the count of each bracket outside strings and comments,
    and where the lexer ends."""
    _code, skeleton, state = lex(text, lexer)
    return {char: skeleton.count(char) for char in OPEN_BRACKETS + CLOSE_BRACKETS}, state


class Source:
    """One file as an entry's lexer reads it (see `lex`), with the matching bracket of every opener and
    where each line starts. A file the lexer cannot read to its end, or whose brackets do not balance, is
    refused: a regex literal, an interpolated string with quotes in it or a preprocessor branch can do both,
    and a body found in text that is not certainly read could be the wrong one (E4: never a guess)."""

    def __init__(self, text: str, lexer: dict, file: str = ""):
        self.text = text
        self.code, self.skeleton, state = lex(text, lexer)
        self.starts = _text_line_starts(text)
        if state != "code":
            raise ToolRefusal(f"probe_by_code: the lexer reads {file or 'the file'} to its end inside {state}; a "
                          "construct it does not know (a regex literal, an apostrophe, an interpolated string with "
                          "quotes in it) is in the way, so what is code and what is a string cannot be told with "
                          "certainty, and a mutation could land inside a string. Nothing was changed.")
        self.pairs: dict = {}
        stack = []
        for hit in BRACKET.finditer(self.skeleton):
            index, char = hit.start(), hit.group(0)
            if char in OPEN_BRACKETS:
                stack.append(index)
            elif not stack or OPEN_BRACKETS.index(self.skeleton[stack[-1]]) != CLOSE_BRACKETS.index(char):
                raise self._unbalanced(index, file)
            else:
                self.pairs[stack.pop()] = index
        if stack:
            raise self._unbalanced(stack[-1], file)

    def line(self, index: int) -> int:
        return bisect.bisect_right(self.starts, index)

    def _unbalanced(self, index: int, file: str) -> Refusal:
        return ToolRefusal(f"probe_by_code: the brackets of {file or 'the file'} do not balance at line {self.line(index)} "
                       "as the lexer reads it (a regex literal or a preprocessor branch can do that), so no body "
                       "can be told with certainty. Nothing was changed.")


def _strip_call(value: str) -> str:
    """`Adds(a: 1)` -> `Adds`: a trailing balanced `(...)` is the report's way of showing parameters."""
    value = value.rstrip()
    depth = 0
    for index in range(len(value) - 1, -1, -1):
        if value[index] == ")":
            depth += 1
        elif value[index] == "(":
            depth -= 1
            if depth == 0:
                return value[:index].rstrip()
    return value


def _no_entry(file: str, suffix: str, root, doc: dict) -> Refusal:
    known = "; ".join(f"{language}: {' '.join(entry['suffixes'])}" for language, entry in doc.items())
    directory = root is not None and (Path(root) / file).is_dir()
    what = (f"{file} is a directory, not a test file" if directory
            else f"no assertion probe for {suffix or 'a file with no suffix'} ({file})")
    return (Refusal if directory else ToolRefusal)(     # a directory is the call's fault, a missing row the tool's
        f"probe_by_code: {what} - factory data gap: references/detectors.json `assertion_probes` has entries for "
        f"({known}) and none for this suffix, so this probe reads no test of it (it never guesses a grammar). The "
        f"row to add is one entry in that file, the factory's data and not the author's test: {AD.ENTRY_SHAPE}. "
        f"Return it as a tooling finding. Until the row exists the probe that breaks the product in a throwaway "
        f"copy works for any language: {RED_SANDBOX_DOOR}. Nothing was changed.")


def parse_detector_node(text: str, file: str, tail: str, root=None) -> dict:
    """`tests/CalcTests.cs::CalcTests.Adds` -> the spec of a test in a language with an `assertion_probes`
    entry (E1: the grammar is the one declared for the suffix, never another). The tail is everything after
    the first `::`, split on the entry's `name_separators`; the name is the last segment, the tail is the
    segments joined with the entry's `tail_join` (the form the report id is compared with, R6 c)."""
    try:
        doc = AD.assertion_detectors()
    except AD.DetectorsError as exc:
        raise ToolRefusal(f"probe_by_code: factory data gap - {exc}. Return it as a tooling finding (the table is the "
                      f"factory's); the product-breaking probe does not read it: {RED_SANDBOX_DOOR}. "
                      "Nothing was changed.") from exc
    suffix = Path(file).suffix.lower()
    language, entry = AD.entry_for_suffix(doc, suffix)
    if entry is None:
        raise _no_entry(file, suffix, root, doc)
    method = entry["declaration_style"] == "method"
    separators = sorted(entry["name_separators"], key=len, reverse=True)
    body = _strip_call(tail) if method else tail
    parts = re.split("|".join(re.escape(s) for s in separators), body) if separators else [body]
    segments = [" ".join(part.split()) for part in parts if part.strip()]
    if not segments:
        raise Refusal(f"probe_by_code: --test wants <file>::<test name>, got {text!r} (nothing follows `::`)")
    name = segments[-1]
    if method and not IDENTIFIER.fullmatch(name):
        raise Refusal(f"probe_by_code: the test name {name!r} of --test is not an identifier, and a {language} test is "
                      "found by the name of its method: give the method name (after the class, separated by "
                      f"{' '.join(repr(s) for s in entry['name_separators'])}); parameters belong to the report id. "
                      "Nothing was changed.")
    spec = {"file": file, "chain": segments[:-1], "function": name, "param": "", "node": text,
            "language": language, "entry": entry, "tail": entry["tail_join"].join(segments), "reader": "table"}
    template = entry.get("title_template")
    if "${" in name and not template:
        raise Refusal(f"probe_by_code: the title {name!r} holds a template substitution `${{`; a title the runner "
                      "builds at run time cannot be matched against the source, so no test is guessed. Name a test "
                      "with a literal title. Nothing was changed.")
    if template and str(template.get("open") or "") in name:
        # the entry reads templated titles (`title_template`): the title is a pattern, the declaration is found by it. Only a
        # title that keeps too few literal characters binds any row to it, and that is refused (EP1-36).
        literal = "".join(p for kind, p in test_source._template_parts(name, template) if kind == "lit")
        tag = re.compile(entry["title_tag"]) if entry.get("title_tag") else None
        kept = len("".join((tag.sub("", literal) if tag else literal).split()))
        if kept < test_source.MIN_LITERAL:
            raise Refusal(f"probe_by_code: the title {name!r} keeps {kept} literal character(s) around its template "
                          f"substitution (fewer than {test_source.MIN_LITERAL}): a pattern that loose would bind any report "
                          "row to it, so no test is guessed. Name the test by a title with more literal text. "
                          "Nothing was changed.")
        spec["template"] = True
    return spec


# --- locating the body and the first assertion ---------------------------------------------------------

def _titled_declarations(src: Source, entry: dict, name: str, file: str, taken: set) -> list:
    """The declarations of a call-style entry that read their titles as DATA (`title_tag`, `title_template`) and are the test
    `name` names, though the entry's regex with the name escaped in did not match them: a title with a tag the name leaves out,
    a templated title whose pattern fits the name (EP1-36). Each is a match-like (`test_source._Call`: start, end, group) of the
    call, found by the ONE reader of the file (`test_source.matches`, the same predicate a report row is tied by). An `each`
    declaration is not one: its first parenthesis is the table's. Never raises: a file the reader cannot read gives none."""
    try:
        state = {"entry": entry, "src": src, "text": src.text}
        test_source._declarations(state, file)
        decls = state["declarations"]
    except Exception:
        return []
    bare = _untagged(name, entry)
    each = re.compile(entry["each_declaration"]) if entry.get("each_declaration") else None
    out = []
    for decl in decls:
        start = decl["span"][0]
        if start in taken or (each and each.match(src.code, start)):
            continue
        if not (test_source.matches(decl, name) or (decl.get("tags") and decl.get("bare_title") == bare)):
            continue
        opener = src.code.find("(", start)
        if opener < 0 or opener not in src.pairs:
            continue
        out.append(test_source._Call(src.text, start, opener + 1))
    return out


def declaration_candidates(src: Source, entry: dict, name: str, helper: bool = False, file: str = "") -> list:
    """Every match of the declaration pattern that starts in CODE (not inside a string or a comment). For a call-style entry
    that reads titles as data (`title_tag`, `title_template`) the declarations `test_source.matches` ties to the name are
    candidates too (a templated declaration is one), so a tagged or templated test is found by the title the report shows."""
    pattern = AD.declaration_regex(entry, name, helper=helper)
    found = [m for m in pattern.finditer(src.code) if _in_code(src, m.start())]
    if helper or entry["declaration_style"] != "call" or not (entry.get("title_tag") or entry.get("title_template")):
        return found
    extra = _titled_declarations(src, entry, name, file, {m.start() for m in found})
    return sorted(found + extra, key=lambda m: m.start())


def _direct_children(src: Source, opener: int) -> list:
    """(open, close) of every bracket group standing directly inside the one that opens at `opener`."""
    out, index = [], opener + 1
    while index < src.pairs[opener]:
        close = src.pairs.get(index)
        if close is None:
            index += 1
        else:
            out.append((index, close))
            index = close + 1
    return out


def body_span(src: Source, entry: dict, match, helper: bool = False, file: str = "") -> tuple:
    """(index of `{`, index of its `}`) of the body the declaration `match` opens, or a refusal that names the
    shape (A4). `method`: right after the balanced parameter list `body_open` must match, anchored there, and
    its last `{` opens the body. `call`: inside the call's own argument list, after the title, the first
    `body_open` match that stands directly in that list opens it - not one nested deeper. Invariant: a body
    that is not certainly the named test's is never mutated."""
    style = "method" if helper else entry["declaration_style"]
    line = src.line(match.start())
    shape = ("a concise arrow `() => expr`, a C# `=>` expression body, a declaration with no block (abstract, "
             "interface), or a parameter list with no block after it")
    refusal = Refusal(f"probe_by_code: no block opens where the body of the test declared at line {line} of "
                      f"{file or 'the file'} should ({shape}); a body that is not certainly the named test's is "
                      "never mutated. Nothing was changed.")
    if style == "method":
        opener = match.end() - 1
        if src.skeleton[opener] != "(":
            raise ToolRefusal("probe_by_code: the declaration pattern of the entry must end at the opening parenthesis "
                          "of the parameter list (factory data gap: references/detectors.json). Nothing was changed.")
        pattern = re.compile((helper and entry.get("helper_body_open")) or entry["body_open"])
        found = pattern.match(src.skeleton, src.pairs[opener] + 1)
        if found is None or "{" not in found.group(0):
            raise refusal
        brace = found.start() + found.group(0).rindex("{")
        return brace, src.pairs[brace]
    if "(" not in match.group(0):
        raise ToolRefusal("probe_by_code: the declaration pattern of a call-style entry must contain the opening "
                      "parenthesis of the call (factory data gap: references/detectors.json). Nothing was changed.")
    opener = match.start() + match.group(0).index("(")
    nested = _direct_children(src, opener)
    for found in re.compile(entry["body_open"]).finditer(src.skeleton, match.end(), src.pairs[opener]):
        if "{" in found.group(0) and not any(o <= found.start() <= c for o, c in nested):
            brace = found.start() + found.group(0).rindex("{")
            return brace, src.pairs[brace]
    raise refusal


def _lines_of(src: Source, matches: list) -> list:
    return [src.line(m.start()) for m in matches]


def locate_target(src: Source, entry: dict, name: str, at, helper: bool = False, file: str = "",
                  language: str = "") -> dict:
    """The declaration, its body and the first head in it. Exactly one declaration must match; two or more are
    refused with the candidate lines and the door `--at <line>`, which picks the candidate whose body holds
    that line (and, among the body's heads, the one whose statement starts there). No head, or the first one
    not invertible, is a refusal too (E6, E7): this never skips to a later assertion."""
    matches = declaration_candidates(src, entry, name, helper, file)
    where = f"{file or 'the file'}"
    if not matches:
        raise ToolRefusal(f"probe_by_code: no declaration of {name!r} in {where} matches the {language} entry's "
                          f"`{'helper_declaration' if helper else 'test_declaration'}`. The name is the last segment of "
                          "--test; if the test is declared in a shape the entry does not know, the shape is a row of "
                          f"references/detectors.json assertion_probes.{language} (the factory's data). Nothing was changed.",
                          name_unproved=True)
    lines = _lines_of(src, matches)
    if len(matches) > 1 and at is None:
        raise Refusal(f"probe_by_code: {name!r} is declared {len(matches)} times in {where} "
                      f"({_capped([f'line {n}' for n in lines], CANDIDATE_CAP)}); "
                      "which one is the test is not told by the name. Door: --at <line> (a line inside the body "
                      "you mean). Nothing was changed.")
    chosen = matches[0]
    if len(matches) > 1:
        holding = []
        for match in matches:
            try:
                opener, closer = body_span(src, entry, match, helper, file)
            except Refusal:
                continue
            if src.line(opener) <= at <= src.line(closer):
                holding.append(match)
        if len(holding) != 1:
            raise Refusal(f"probe_by_code: --at {at} lies in {len(holding)} of the {len(matches)} bodies of "
                          f"{name!r} in {where} ({_capped([f'line {n}' for n in lines], CANDIDATE_CAP)}); "
                          "it must lie in exactly one. Nothing was changed.")
        chosen = holding[0]
    opener, closer = body_span(src, entry, chosen, helper, file)
    forms = [re.compile(form["head"]) for form in entry["assertions"]]
    heads = sorted(((m.start(), index, m) for index, rx in enumerate(forms)
                    for m in rx.finditer(src.skeleton, opener + 1, closer)), key=lambda h: (h[0], h[1]))
    if at is not None:      # t-2045 N1: the head whose STATEMENT starts or spans the line (the rule `check_on_line` prints doors by)
        spans = {h[0]: _head_lines(src, entry, h[0], closer, file) for h in heads}
        heads = [h for h in heads if spans[h[0]][0] <= at <= spans[h[0]][1]]
    if not heads:
        # the tool's gap only when the role did not point at a line: a wrong `--at` is the call's fault (no record for it)
        raise (Refusal if at is not None else ToolRefusal)(
            f"probe_by_code: no recognised assertion {'starts on line ' + str(at) + ' of' if at else 'in'} "
            f"the body of {name!r} (lines {src.line(opener)}-{src.line(closer)} of {where}); this probe "
            "inverts the first assertion form its table knows. Doors: `--oracle [<file>::]<helper>` when "
            "the expectation lives in a helper, or add the assertion's head as a form of "
            f"references/detectors.json assertion_probes.{language} (the factory's data). Nothing was changed.")
    start, index, head = heads[0]
    return {"declaration": chosen, "candidates": lines, "body": (opener, closer), "head_start": start,
            "form": index, "head": head}


def _statement_span(src: Source, start: int, mode: str, limit: int, file: str) -> tuple:
    """(start, end) of the statement that begins at `start`: through the first `;` outside any bracket, or - for
    `semicolon_or_newline` - at a line break outside any bracket that no continuation covers (the next
    non-blank character, or the last one before the break, is an operator that only a continuation can
    carry). A statement not certainly delimited is refused."""
    index = start
    while index < limit:
        char = src.skeleton[index]
        if char in OPEN_BRACKETS:
            index = src.pairs[index] + 1
            continue
        if char in CLOSE_BRACKETS:
            break
        if char == ";":
            return start, index + 1
        if mode == "semicolon_or_newline" and char in "\r\n" and not _continues(src, index, start, limit):
            return start, _trimmed(src, start, index)
        index += 1
    if mode == "semicolon_or_newline":
        return start, _trimmed(src, start, min(index, limit))
    raise Refusal(f"probe_by_code: the statement at line {src.line(start)} of {file or 'the file'} is not ended by "
                  "`;` before its block closes, so its extent is not certain. Nothing was changed.")


def _trimmed(src: Source, start: int, end: int) -> int:
    while end > start and src.code[end - 1].isspace():
        end -= 1
    return end


def _continues(src: Source, brk: int, start: int, limit: int) -> bool:
    before = _trimmed(src, start, brk)
    if before > start and src.code[before - 1] in CONTINUES_BEFORE:
        return True
    after = brk
    while after < limit and src.code[after].isspace():
        after += 1
    return after < limit and src.code[after] in CONTINUES_AFTER


def _matcher_position(src: Source, kind: str, head, stmt_end: int, file: str) -> int:
    """Where the pair's `find` is matched: `head` the start of the head, `after_args` the end of the head's
    balanced `(...)`, `second_arg` the start of the second top-level argument (A3). One position, nowhere
    else in the statement."""
    line = src.line(head.start())
    if kind == "head":
        return head.start()
    shown = f"the assertion at line {line} of {file or 'the file'}"
    if kind == "after_args":
        opener = head.end() - 1
        if src.skeleton[opener] != "(" or src.pairs[opener] >= stmt_end:
            raise ToolRefusal(f"probe_by_code: {shown} is matched by a head that does not end at the opening parenthesis "
                          "of its arguments, so `after_args` has no position (factory data gap). Nothing was changed.")
        return src.pairs[opener] + 1
    opener = head.end()
    while opener < stmt_end and src.skeleton[opener].isspace():
        opener += 1
    if opener >= stmt_end or src.skeleton[opener] != "(":
        raise ToolRefusal(f"probe_by_code: {shown} has no parenthesised argument list right after its head, so its "
                      "second argument cannot be found. Nothing was changed.")
    close, index = src.pairs[opener], opener + 1
    while index < close:
        if src.pairs.get(index) is not None:
            index = src.pairs[index] + 1
        elif src.skeleton[index] == ",":
            index += 1
            while index < close and src.code[index].isspace():
                index += 1
            if index >= close:
                break
            return index
        else:
            index += 1
    raise ToolRefusal(f"probe_by_code: {shown} has no second argument. Nothing was changed.")


def _refuse_conditional_compilation(src: Source, entry: dict, shown: str, language: str) -> None:
    """A file that holds a conditional-compilation directive (the entry's `conditional_directive`, a regex matched
    per line: C# `#if` / `#elif` / `#else` / `#endif`) is refused: the lexer reads every branch as code, but only
    one is compiled, and which one is not knowable here - a mutation could land in the inactive branch, the run
    would pass, and the author's live check would be called dead. `--at` is no door (the inactive branch stays
    unknowable); the doors are a row for that file's shape and the product-level probe."""
    pattern = entry.get("conditional_directive")
    hit = re.compile(pattern, re.M).search(src.skeleton) if pattern else None
    if hit:
        line = src.line(hit.start())
        directive = fold(LINE_BREAK.split(src.text[src.starts[line - 1]:], 1)[0].strip(), 60)
        raise ToolRefusal(f"probe_by_code: {shown} holds the conditional-compilation directive `{directive}` at "
                      f"line {line}: which branch is compiled is not knowable here, so a mutation "
                      "could land in the inactive one and the run would pass for it. This is not a verdict on the "
                      f"test (a gap of the factory's: references/detectors.json assertion_probes.{language}); the "
                      f"probe that breaks the product in a throwaway copy does not read the source: {RED_SANDBOX_DOOR}. "
                      "Nothing was changed.")


def _inverted(src: Source, text: str, entry: dict, language: str, form: dict, head, start: int, end: int,
              shown: str) -> tuple:
    """(pair index, pair, the statement after, the whole mutated text). The first pair of the form whose `find`
    matches AT the form's one position (`re.match`, never a search over the statement) is applied once. Every
    guard of the plan lives here, and each is a refusal with nothing written: no pair matches (the form is known,
    this shape is not), `fires_as` matches the mutated statement itself (a failure text that merely echoes it
    could pass for the intended one - A2), a line break would change (count AND kind, so CRLF stays CRLF), the
    brackets' balance or the lexer's end state would change, a byte outside the statement would change (E7, E9)."""
    line = src.line(start)
    position = _matcher_position(src, form["matcher_at"], head, end, shown)
    chosen = next(((index, pair, hit) for index, pair in enumerate(form["invert"])
                   for hit in [re.match(pair["find"], text[position:end])] if hit and hit.end() > 0), None)
    if chosen is None:
        raise ToolRefusal(f"probe_by_code: no inversion pair of the {language} table matches at the {form['matcher_at']} "
                      f"position of the assertion at line {line} of {shown} (`{fold(text[position:end], 80)}`); the "
                      "form is recognised but this shape of it is not (Hamcrest `assertThat(x, is(y))`, Chai "
                      "`.to.equal`, a chain on the next line): nothing is skipped to a later assertion. Doors: "
                      "`--at <line>` or a row for this shape in references/detectors.json. Nothing was changed.")
    index, pair, hit = chosen
    which = pair.get("id") or index
    try:
        replacement = hit.expand(pair["replace"])
    except (re.error, IndexError) as exc:
        raise ToolRefusal(f"probe_by_code: the `replace` of pair {which} of assertion_probes.{language} "
                      f"cannot be expanded ({exc}) - factory data gap. Nothing was changed.") from exc
    before = text[start:end]
    after = text[start:position + hit.start()] + replacement + text[position + hit.end():end]
    if AD.fires_in(pair["fires_as"], after):
        raise ToolRefusal(f"probe_by_code: the failure this inverted form must show (pair {which}) would "
                      f"also match the mutated statement's own text (`{fold(after, 100)}`), so a failure text that "
                      "merely echoes the statement could pass for the intended one. Nothing was changed.")
    if LINE_BREAK.findall(before) != LINE_BREAK.findall(after):
        raise ToolRefusal(f"probe_by_code: the inversion (pair {which} of assertion_probes.{language}) would "
                      f"change the line breaks of the statement at line {line} of {shown}: an edit may not move a "
                      "line or turn CRLF into LF, and a `find` that matches the whitespace of a chain split over "
                      "lines consumes its break. Nothing was changed. The assertion can be inverted by a pair whose "
                      "`find` captures that whitespace (a row of references/detectors.json, the factory's data).")
    mutated = text[:start] + after + text[end:]
    if lexical_shape(mutated, entry["lexer"]) != lexical_shape(text, entry["lexer"]):
        raise ToolRefusal(f"probe_by_code: the inversion would change the bracket balance or the lexical state of "
                      f"{shown}. Nothing was changed.")
    # `mutated` is built from `text[:start]` and `text[end:]` verbatim, so no byte outside the statement can
    # change; the assertion states that invariant (it cannot fire unless this function is edited wrongly).
    assert mutated.startswith(text[:start]) and mutated.endswith(text[end:])
    return index, pair, after, mutated


# --- the factory's own marker in the message of the broken check (t-1968 N1) ------------------------------
# A failure text the library words in a way the table does not know used to leave the probe `incomplete`. The factory
# can know the failure is the broken check's own by a fact it controls: the inverted statement carries a message that
# holds a token only this probe knows, and a failed run whose failure text holds that token was thrown by that check.
# The marker only ADDS a proof the factory wrote (E1.1): where no variant applies the statement is the plain inversion
# and the table (`fires_as`) judges as before. Closed variety - how a message attaches to a form - is data (FR-13, AR-1).

MARKER_PREFIX = AD.MARKER_PREFIX         # the one spelling: the detectors validator checks every `marker_expr` against it
MARKER_INSERT_CAP = 64                   # E1.10: characters the marker adds to the statement
MARKER_FORBIDDEN = "%{}"                 # format-string characters (NUnit message, AssertJ `as`): none may enter the message
CALL_PREFIX = re.compile(r"[\w.$\s]*(?:<[\w.,\s<>?\[\]]*>)?\s*")   # what may stand between the statement start and its `(`


def marker_token(instance_id: str, original_sha: str, started_at: str, key: str) -> str:
    """The 12 hex characters that make one probe's marker its own: the instance, the author's bytes, the moment of this run and the
    CHECK's key (t-2064 P3: one token per check, so the failures of several checks of one joint run are told apart), so a marker left in
    another run's report never matches this one (E1.4). Always 12 hex, so no token is a prefix of another one; `started_at` is the
    caller's per RUN, never per walk, so an alone rerun does not share the joint run's token."""
    return hashlib.sha256(f"{instance_id}\0{original_sha}\0{started_at}\0{key}".encode("utf-8")).hexdigest()[:12]


def _call_arguments(src: "Source", start: int, end: int):
    """(opener, closer, [(start, end) of each top-level argument, trimmed]) of the first call of the statement
    `[start, end)`, or None when the statement does not open with a plain call (only a name, dots and generics may stand
    before its `(`). Read in the skeleton: a comma or a bracket inside a string or a comment is not one. An empty
    argument next to others (`f(a,)`) is None: its place is not certain."""
    opener = next((i for i in range(start, end) if src.skeleton[i] == "("), None)
    if opener is None or not CALL_PREFIX.fullmatch(src.skeleton[start:opener]):
        return None
    closer = src.pairs.get(opener)
    if closer is None or closer >= end:
        return None
    spans, first, index = [], opener + 1, opener + 1
    while index < closer:
        char = src.skeleton[index]
        if char in OPEN_BRACKETS:
            index = src.pairs[index] + 1
            continue
        if char == ",":
            spans.append((first, index))
            first = index + 1
        index += 1
    spans.append((first, closer))
    trimmed = []
    for a, b in spans:
        while a < b and src.code[a].isspace():      # `code` has comments blanked: a trailing comment is not an argument's end
            a += 1
        while b > a and src.code[b - 1].isspace():
            b -= 1
        trimmed.append((a, b))
    if len(trimmed) == 1 and trimmed[0][0] == trimmed[0][1]:
        return opener, closer, []
    if any(a == b for a, b in trimmed):
        return None
    return opener, closer, trimmed


def _variant_misses(variant: dict, original: str, mutated: str, src: "Source", entry: dict, call: tuple, end: int) -> str:
    """Why `variant` does not apply to this statement, or "" when every condition holds (the conditions of the row:
    `source`, `not_source`, `args`, `string_arg`, `not_after`). Reads the row; judges nothing about the test."""
    opener, closer, args = call
    if "source" in variant and not re.search(variant["source"], original):
        return "the file does not match its `source`"
    if "not_source" in variant and re.search(variant["not_source"], original):
        return "the file matches its `not_source`"
    if len(args) != variant["args"]:
        return f"the call has {len(args)} argument(s), the row wants {variant['args']}"
    if variant["at"].startswith("arg_start:") and int(variant["at"].split(":", 1)[1]) > len(args):
        return "the row names an argument the call does not have"
    if variant["at"] == "args_close" and not args:
        return "the call has no argument to follow"
    if "string_arg" in variant:
        number = variant["string_arg"]
        opens = "|".join(re.escape(s["open"]) for s in entry["lexer"]["strings"])
        if number > len(args) or not re.match(r"\$?(?:" + opens + ")", src.code[args[number - 1][0]:args[number - 1][1]]):
            return f"argument {number} does not begin with a string literal"
    if "not_after" in variant and re.match(variant["not_after"], mutated[closer + 1:end]):
        return "the call is already followed by a description (`not_after`)"
    return ""


def _with_marker(mutated: str, start: int, after: str, original: str, entry: dict, form: dict, fires_as: str,
                 token: str) -> tuple:
    """(the statement with the marker put in, the id of the variant that applied, the note). The first variant of the
    form's `message` whose conditions hold is applied to the statement `after` (which stands at `start` of `mutated`): the
    INVERTED statement of a plain inversion, or - since t-2064 P3 - the check AS WRITTEN after a model's value edit, in which case
    `fires_as` is None and the echo guard below is skipped (nothing was inverted, so there is no failure this statement must
    show). Every guard fails toward the plain statement - the same text back, id "", a note - never a refusal (E1.1), and the plain
    statement carries no marker, so the row goes to the role: the error direction is toward "the role decides", never toward
    `intended_failure` (§11.0): the inserted text holds no line break, at most MARKER_INSERT_CAP characters and no format character;
    the brackets of the new file are those of the edited file plus the inserted ones and the lexer still ends in code; the
    contiguous marker occurs nowhere in the new file (it is joined at run time, so a code frame or a transpiled copy never holds it);
    and the pair's `fires_as`, when there is one, does not match the new statement (the echo guard of `_inverted`). Variant `id` ""
    means none applied. No token (a caller that plans without a marker) is no marker and no note."""
    if not token:
        return after, "", ""
    variants = AD.message_forms(form)
    if not variants:
        return after, "", ""         # AR-23: the form takes no message - a legal row, nothing to say
    expression = AD.marker_expression(entry, token)
    if not expression:
        return after, "", "the entry declares no marker_expr, so no marker was put in"
    try:
        src = Source(mutated, entry["lexer"])
    except Refusal as exc:
        return after, "", f"the mutated file could not be read again for the marker ({str(exc)[:120]})"
    end = start + len(after)
    call = _call_arguments(src, start, end)
    if call is None:
        return after, "", "the statement does not open with a plain call whose arguments can be told, so no marker was put in"
    opener, closer, args = call
    misses = []
    for variant in variants:
        why = _variant_misses(variant, original, mutated, src, entry, call, end)
        if why:
            misses.append(f"{variant['id']}: {why}")
            continue
        at = variant["at"]
        position = closer + 1 if at == "after_args" else args[-1][1] if at == "args_close" else args[int(at.split(":", 1)[1]) - 1][0]
        inserted = variant["insert"].replace(AD.MARKER, expression)
        marker = MARKER_PREFIX + token
        new_after = after[:position - start] + inserted + after[position - start:]
        new_text = mutated[:start] + new_after + mutated[end:]
        added, added_state = lexical_shape(inserted, entry["lexer"])
        base, base_state = lexical_shape(mutated, entry["lexer"])
        if LINE_BREAK.search(inserted) or len(inserted) > MARKER_INSERT_CAP:
            return after, "", f"{variant['id']}: the text to insert has a line break or is longer than {MARKER_INSERT_CAP} characters"
        if any(char in inserted for char in MARKER_FORBIDDEN):
            return after, "", f"{variant['id']}: the text to insert holds a format character ({MARKER_FORBIDDEN})"
        if added_state != "code" or any(added[o] != added[c] for o, c in zip(OPEN_BRACKETS, CLOSE_BRACKETS)) \
                or lexical_shape(new_text, entry["lexer"]) != (
                {char: base[char] + added[char] for char in base}, base_state):
            return after, "", f"{variant['id']}: the inserted text would change the lexical state or the brackets other than by its own"
        if marker in new_text:
            return after, "", f"{variant['id']}: the contiguous marker would stand in the source (it must be joined at run time)"
        if fires_as is not None and AD.fires_in(fires_as, new_after):
            return after, "", f"{variant['id']}: the failure this inverted form must show would match the statement with the marker"
        return new_after, variant["id"], ""
    return after, "", "no message variant applies (" + "; ".join(misses) + ")"


def plan_detector_mutation(data: bytes, spec: dict, instance_id: str, at=None, oracle_function: str = "",
                           oracle_note: str = "", file: str = "", marker_token: str = "", target: dict = None) -> tuple:
    """(mutated bytes, detail, context) - nothing is written here; `context` is the code between the end of the
    previous statement or block and the declaration (where an annotation such as a display name stands). The
    first head of the body is the target - unless `target` (`_target_of`; built from `at` when only `at` is given) names a
    LINE: then it is the check whose statement starts or spans that line, in the test's body when it stands there, else
    anywhere in these bytes (a helper, a page-object method: `declaration_line` None, `candidates` [], `context` ""), and a
    line with no check is a refusal that names the nearest one (t-2045 N1). A form with `invert: null` is a refusal (it
    never skips to a later assertion, E7), any other form is inverted by `_inverted`, whose guards are refusals too. A BOM
    and CRLF line ends are kept; a file that is not UTF-8 is refused (E21).

    `marker_token` (t-1968 N1; "" = none: the plain inversion, which is how the language tests call it; the one production caller passes the story's token): when the form has a message variant that applies, the
    inverted statement also carries the factory's marker `qa-probe-<token>` in the message of the broken check. The detail
    then holds `message_marker` / `message_form` (both "" when none applied) and `message_note` (why, when the form had
    rows and none applied); `statement_after` is the statement as WRITTEN, `statement_inverted` the plain inversion."""
    entry, language, shown = spec["entry"], spec["language"], file or spec["file"]
    bom = data.startswith(b"\xef\xbb\xbf")
    try:
        text = (data[3:] if bom else data).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Refusal(f"probe_by_code: {shown} is not UTF-8 ({exc.reason} at byte {exc.start}); a file read in the "
                      "wrong encoding is never mutated. Nothing was changed.") from exc
    src = Source(text, entry["lexer"], shown)
    _refuse_conditional_compilation(src, entry, shown, language)
    name = oracle_function or spec["function"]
    target = target if target is not None else _bare_target(data, spec, at)
    if target["line"] is None:
        found = locate_target(src, entry, name, None, bool(oracle_function), shown, language)
    else:
        found, prior = None, None
        if target.get("same_file", True) and not oracle_function:     # the test's own body holds the line: the declaration is known
            try:
                found = locate_target(src, entry, name, target["line"], False, shown, language)
            except Refusal as exc:
                prior = exc
        if found is None:
            found = _target_at_line(src, entry, shown, target["line"], prior)
    head, form = found["head"], entry["assertions"][found["form"]]
    start, end = _statement_span(src, found["head_start"], entry["statement_end"], found["body"][1], shown)
    line, end_line = src.line(start), src.line(max(start, end - 1))
    if form["invert"] is None:
        later = [c[0] for c in _source_checks(src, entry, shown) if c[0] > line]
        raise _not_invertible("assertion", repr(name), shown, fold(head.group(0)), line, target["line"],
                              f"a form the {language} table does not invert (assertion_probes.{language}.assertions"
                              f"[{found['form']}].invert is null)", later[0] if later else None)
    index, pair, after, mutated = _inverted(src, text, entry, language, form, head, start, end, shown)
    before = text[start:end]
    marker = f"probe-{instance_id} invert: {fold(before)} fires as /{pair['fires_as']}/"
    inverted = after
    after, variant, note = _with_marker(mutated, start, inverted, text, entry, form, pair["fires_as"], marker_token)
    if variant:
        mutated = text[:start] + after + text[end:]
    detail = {"line": line, "end_line": end_line, "mutation": "invert", "style": "detector", "language": language,
              "head": head.group(0), "form": found["form"], "pair": index, "pair_id": pair.get("id"),
              "at": target["given"], "candidates": found["candidates"],
              "statement_before": before, "statement_after": after, "statement_inverted": inverted,
              "message_marker": MARKER_PREFIX + marker_token if variant else "", "message_form": variant, "message_note": note,
              "fires_as": pair["fires_as"], "marker": marker, "matcher_at": form["matcher_at"],
              "declaration_line": src.line(found["declaration"].start()) if found["declaration"] is not None else None,
              "file": shown}
    _stamp_target(detail, target)
    if target["line"] is not None and len({c[3] for c in _source_checks(src, entry, shown) if c[0] == line}) > 1:
        detail["target_note"] = f"two checks start on line {line}; the first is the one inverted"     # E-K, a named residual
    if oracle_function:
        detail["oracle_function"], detail["oracle_note"] = oracle_function, oracle_note
    return ((b"\xef\xbb\xbf" if bom else b"") + mutated.encode("utf-8"), detail,
            _context(src, found["declaration"]) if found["declaration"] is not None else "")


def _stamp_target(detail: dict, target: dict) -> None:
    """What the plan says of its target, beside `line`: where the choice came from (`target_source`) and whether the check
    stands outside the located body of the test (`target_outside_body`: True / False / None when the body is not located).
    The producer of both; their readers are `target_fact` and the verdict of the run (N3b)."""
    detail["target_source"], detail["target_outside_body"] = target["source"], target["outside_body"]


def _context(src: Source, declaration) -> str:
    """The code just before a declaration: from the last `;`, `{` or `}` before it."""
    index = declaration.start()
    while index > 0 and src.skeleton[index - 1] not in ";{}":
        index -= 1
    return src.code[index:declaration.start()]


# --- the target: which check is inverted, read by ONE order for every language (t-2045 N1) ---------------------
# `--at` (a line, or `<file>:<line>`), then `--oracle`, then the manifest row's `assertion_id`, then the first check of the
# test. Nothing here asks what language the test is in: the only per-language things are the reader of the source (the
# `ast` for Python, the entry's lexer and heads for the others) and the rows of the table. A line is looked up in the WHOLE
# file, so a check in a local helper or a page-object method needs no declaration. The tool never picks "the nearest" check
# by itself (AR-7): a line with no check is a refusal that names the nearest one, and the role chooses.

_BOM = b"\xef\xbb\xbf"
_CALL_NAME = re.compile(r"([A-Za-z_$][\w$]*)\s*\(")


def _head_lines(src: Source, entry: dict, start: int, limit: int, file: str) -> tuple:
    """(first line, last line) of the statement that begins at `start`; a statement whose extent is not certain counts as its
    first line alone (a pure read: the plan itself refuses such a statement, `_statement_span`)."""
    try:
        first, end = _statement_span(src, start, entry["statement_end"], limit, file)
    except Refusal:
        return src.line(start), src.line(start)
    return src.line(first), src.line(max(first, end - 1))


def _source_checks(src: Source, entry: dict, file: str) -> list:
    """[(line, end_line, form index, start, match)] of every head of every assertion form of the entry in the WHOLE file, in
    source order. The same heads `locate_target` reads inside one body."""
    forms = [re.compile(form["head"]) for form in entry["assertions"]]
    heads = sorted(((m.start(), index, m) for index, rx in enumerate(forms) for m in rx.finditer(src.skeleton)),
                   key=lambda h: (h[0], h[1]))
    out = []
    for start, index, match in heads:
        first, last = _head_lines(src, entry, start, len(src.skeleton), file)
        out.append((first, last, index, start, match))
    return out


def _skeleton_call_name(src: Source, line: int):
    """The last name before an opening parenthesis on `line` of the skeleton (strings and comments blanked), None when there is
    none. One rule for every language: a fact for the reader of a refusal, never a target (S13)."""
    if not 1 <= line <= len(src.starts):
        return None
    end = src.starts[line] if line < len(src.starts) else len(src.skeleton)
    names = _CALL_NAME.findall(src.skeleton[src.starts[line - 1]:end])
    return names[-1] if names else None


def check_on_line(data: bytes, name: str, reader_entry, line: int) -> dict:
    """What check stands on `line` of a file: `{"found": {line, end_line, form, starts_here} | None, "nearest_below": {line,
    end_line, form} | None, "calls_helper": <name> | None}`. Pure: it reads only its arguments, so the same call serves the
    probe's refusal and a writer of `assertion_id` (TR2-1).

    A check counts when it starts on the line OR its statement spans it (the rule `target_fact` compares by, so a printed
    `--at` door always opens). `reader_entry` is the `assertion_probes` entry of the file's language, or None for Python
    (`ast`: a statement one of the `assertion_probes_ast.python.forms` rows reads); `form` is the index of the entry's form, or
    the Python row's id.
    `calls_helper` is the last name before `(` on the line (Python: the outermost call that starts there) - a fact, not a
    target. A file that cannot be read is a refusal, never `found: None`."""
    raw = data[len(_BOM):] if data.startswith(_BOM) else data
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Refusal(f"probe_by_code: {name} is not UTF-8 ({exc.reason} at byte {exc.start}); a file read in the wrong "
                      "encoding is never mutated. Nothing was changed.") from exc
    if reader_entry is None:
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            raise Refusal(f"{name} does not parse: {exc}") from exc
        checks = _python_checks(tree, _python_entry()[1]["forms"], text)
        return _line_facts([(c[0], c[1], c[2]) for c in checks], line, _python_call_name(tree, line))
    src = Source(text, reader_entry["lexer"], name)
    return _line_facts([(c[0], c[1], c[2]) for c in _source_checks(src, reader_entry, name)], line,
                       _skeleton_call_name(src, line))


def test_body_span(test_bytes: bytes, spec: dict, reader_entry):
    """(first line, last line) of the body of the test `spec` names in these bytes, or None when it is not located: no such
    function or declaration, more than one, a file the reader cannot read. Pure. None is read as "outside" (E-O)."""
    raw = test_bytes[len(_BOM):] if test_bytes.startswith(_BOM) else test_bytes
    try:
        text = raw.decode("utf-8")
        if reader_entry is None:
            node = locate(ast.parse(text), spec["chain"], spec["function"])
            return node.lineno, node.end_lineno
        src = Source(text, reader_entry["lexer"], spec["file"])
        matches = declaration_candidates(src, reader_entry, spec["function"], False, spec["file"])
        if len(matches) != 1:
            return None
        opener, closer = body_span(src, reader_entry, matches[0], False, spec["file"])
        return src.line(opener), src.line(closer)
    except (Refusal, SyntaxError, UnicodeDecodeError, RecursionError):
        return None


def _scoped_rows(src: Source, rows: list, name: str, scope_rows: list, notes: list) -> list:
    """`rows` of one table-read file with its soft SCOPES applied (t-2064 P1b): a row of `soft_scopes` names a bracketed region
    (`opens` ends on its opening bracket, the scope runs to the balanced closing); every check inside it - or, when the row has a
    `head`, every check that head matches - reads as non-stopping, and the row of the scope's own opening head (`assertAll(`) is
    not a check and leaves the list. The OUTERMOST scope decides (a nested one adds nothing: one group). Every rule that is not a
    check reads as before: a scope whose closing cannot be found, or that holds no check of a known form, is no scope (a note
    names the line; its checks stop as written - the safe side), and a check outside the scope is untouched. Reads rows, never a name."""
    real, by_call = [], []
    for scope_row in scope_rows:
        if scope_row["closes"]:
            by_call.extend(_called_scopes(src, rows, scope_row, name, notes))
            continue
        head_rx = re.compile(scope_row["head"]) if scope_row["head"] else None
        for hit in re.finditer(scope_row["opens"], src.skeleton):
            where, opener = f"line {src.line(hit.start())} of {name}", hit.end() - 1
            close = src.pairs.get(opener) if hit.end() > hit.start() and src.skeleton[opener] in OPEN_BRACKETS else None
            if close is None:
                notes.append(f"the scope that opens at {where} does not end on an opening bracket, or its closing cannot be found: "
                             "no scope from it, its checks read by the plain rule (stopping)")
                continue
            inside = [r for r in rows if opener < r["start"] < close]
            soft = [r for r in inside if head_rx is None or head_rx.match(src.skeleton, r["start"])]
            if not soft:
                notes.append(f"the scope that opens at {where} holds no check of a form the factory reads: read as a head of an "
                             "unknown form, never as a soft group")
                continue
            real.append((hit.start(), opener, close, inside, soft))
    real.sort(key=lambda s: (s[0], -s[2]))
    on_line, dropped = {}, set()
    for begin, opener, close, inside, soft in real:
        dropped |= {id(r) for r in rows if begin <= r["start"] <= opener}
        if any(o < begin < c for _b, o, c, _i, _s in real):
            continue                                    # nested: the outer scope decides
        line = src.line(begin)
        on_line[line] = on_line.get(line, 0) + 1
        scope_id = f"{name}:{line}" + (f"#{on_line[line]}" if on_line[line] > 1 else "")
        for row in inside:
            row["scope"] = scope_id
        for row in soft:
            row["soft"] = True
    members = []
    for begin, inside, soft, shut in sorted(by_call, key=lambda s: s[0]):      # scopes that end at a CALL (t-2273): never merged
        dropped |= shut
        line = src.line(begin)
        on_line[line] = on_line.get(line, 0) + 1
        scope_id = f"{name}:{line}" + (f"#{on_line[line]}" if on_line[line] > 1 else "")
        for row in soft:
            if row["scope"] is None:                    # a bracketed scope that holds it already decides
                row["scope"], row["soft"] = scope_id, True
        members.append((scope_id, inside))
    for scope_id, inside in members:                    # a stopping check between the opening and the closing is the scope's too
        for row in inside:
            if row["scope"] is None:
                row["scope"] = scope_id
    return [r for r in rows if id(r) not in dropped]

def _called_scopes(src: Source, rows: list, scope_row: dict, name: str, notes: list) -> list:
    """The scopes of one row WITH `closes` (t-2273): `[(begin, inside, soft, shut)]`. A scope opens at each match of `opens` and ends at
    the first later `closes` match in the same body - the innermost bracket pair that holds the opening, at that same depth, so a
    closing call inside a conditional or a lambda does not count. `{name}` of a group `opens` captured is put into `closes` and
    `head`. Not a scope, with a note naming the line, its checks read by the plain rule (stopping - the safe side): no closing call
    (returned, passed on, closed in another function), a regex that does not compile once the name is put in, or no check of the
    row's `head` between the two. The closing call is no check: its rows (`shut`) leave the list. Reads rows, never a name."""
    def around(position: int):
        return max(((o, c) for o, c in src.pairs.items() if o < position < c), default=None)

    found = []
    for hit in re.finditer(scope_row["opens"], src.skeleton):
        where = f"line {src.line(hit.start())} of {name}"
        values = hit.groupdict()
        try:
            closes_rx = re.compile(AD.fill_scope_regex(scope_row["closes"], values))
            head_rx = re.compile(AD.fill_scope_regex(scope_row["head"], values)) if scope_row["head"] else None
        except re.error as exc:
            notes.append(f"the scope that opens at {where} has a `closes` or `head` that does not compile once its name is put in "
                         f"({str(exc)[:60]}): no scope from it, its checks read by the plain rule (stopping)")
            continue
        level = around(hit.start())
        limit = level[1] if level else len(src.skeleton)
        shut = next((m for m in closes_rx.finditer(src.skeleton, hit.end(), limit) if around(m.start()) == level), None)
        if shut is None:
            notes.append(f"the scope that opens at {where} has no closing call in its body (returned, passed on, or closed elsewhere): "
                         "no scope from it, its checks read by the plain rule (stopping)")
            continue
        inside = [r for r in rows if hit.end() <= r["start"] < shut.start()]
        soft = [r for r in inside if head_rx is None or head_rx.match(src.skeleton, r["start"])]
        if not soft:
            notes.append(f"the scope that opens at {where} holds no check of a form the factory reads: read as a head of an "
                         "unknown form, never as a soft group")
            continue
        found.append((hit.start(), inside, soft, {id(r) for r in rows if shut.start() <= r["start"] < shut.end()}))
    return found


def _number_rows(rows: list, name: str) -> list:
    """Number the rows of one file's listing, in the order given: the ONE numbering of the checks on a line (t-2064 fix round B, F1; AR-13).
    Each row gets `ordinal` (1-based among the rows left on its line), `key` (`<file>:<line>`, `#n` from the second) and `file`. `checks_of`
    writes the numbers on the checks it lists and `_located` reads them off the same rows: no other function counts a line's statements."""
    seen_on_line: dict = {}
    for row in rows:
        seen_on_line[row["line"]] = seen_on_line.get(row["line"], 0) + 1
        row["ordinal"] = seen_on_line[row["line"]]
        row["key"] = f"{name}:{row['line']}" + (f"#{row['ordinal']}" if row["ordinal"] > 1 else "")
        row["file"] = name
    return rows


def _table_rows(src: Source, reader_entry: dict, name: str, soft_rx: list, scope_rows: list, notes: list) -> list:
    """The numbered check rows of one file the TABLE reader reads (the table branch of `checks_of`'s listing, and the only reader of "which
    check is `#n`" for `_located`, AR-13): every head `_source_checks` finds with its statement span (`begin`, `end`; `refusal` holds the
    Refusal when the extent is not certain, and the span then falls back to the head's line), the soft SCOPES applied (a scope's own opening
    head and a closing call leave the rows and take no number), then numbered by `_number_rows`. Pure: it reads its arguments."""
    rows = []
    for first, last, index, start, _match in _source_checks(src, reader_entry, name):
        form = reader_entry["assertions"][index]
        refusal = None
        try:
            begin, end = _statement_span(src, start, reader_entry["statement_end"], len(src.skeleton), name)
        except Refusal as exc:    # an extent that is not certain: the first line of the head, never a guess of more
            refusal = exc
            begin, end = start, (src.starts[first] if first < len(src.starts) else len(src.text))
        rows.append({"line": first, "end_line": last, "form": index, "text": src.text[begin:end], "start": start, "scope": None,
                     "begin": begin, "end": end, "refusal": refusal,
                     "soft": any(rx.match(src.skeleton, start) for rx in soft_rx), "invertible": form["invert"] is not None,
                     "has_message": bool(AD.message_forms(form))})
    return _number_rows(_scoped_rows(src, rows, name, scope_rows, notes), name)


def checks_of(data: bytes, spec: dict, reader_entry, bindings: list, helpers: list, notes=None) -> list:
    """The checks of one test, in source order, as data (t-2064 P2; pure: it reads its arguments and nothing else).

    `data` is the test file's bytes, `spec` the parsed `--test`, `reader_entry` the table entry (None: the AST reader), `bindings` the
    `then_bindings` rows of THIS instance as `{"then": n, "assertion_ref": "<file>:<a>[-<b>]"}`, `helpers` the other files the caller
    read: `[{"file": <spelling>, "data": bytes, "hop": bool, "chain": bool}]` - a file a binding names is looked up by `file`; a
    `hop` file is searched, in order, for the helpers the body calls (`chain`: a conftest, nearest first, never counted for a
    cross-file ambiguity - the order of `find_oracle`). `notes` (a list) receives the facts the list leaves out.

    One dict per check: `{key, file, line, end_line, form, soft, invertible, has_message, in_body, then, statement_sha, scope, ordinal,
    offset}`. `key` is `<file>:<line>` (`#2` for a second head on the line, by head order); `ordinal` is that number (1-based, counted
    over the rows left after the soft scopes dropped their openers and closing calls: `_number_rows`, the ONE numbering, which `_located`
    reads through the same function) and `offset` the character offset of the statement in the file's text (None for the AST reader); `soft` is a row of the entry's
    `soft_assert_patterns` (data: a framework with no soft form states `[]`, and every check of it stops) or a check inside a soft
    SCOPE of its `soft_scopes` (t-2064 P1b); `scope` is the id (`<file>:<line>` of its opening) of the outermost scope a check stands
    in, None outside one - the scope's own end stops the test when a check in it failed, so `run_plan` never reads past it; `then` is the Then of
    the first binding whose lines hold the check, None when none does; `statement_sha` is the sha256 of the statement with its
    whitespace folded (the join a stored edit finds its check by).

    Listed (F-P1 A): every head of a known form inside the test's body, setup included, through the two readers `check_on_line`
    reads (`_source_checks`, `_python_checks`: no third walker); every check a binding names outside the body; when the body holds
    none, the checks of the one helper N5's hop finds. NOT listed, and a note says so: a binding on a line with no check; the
    checks of the helpers the body calls that no binding names (counted); a binding or a helper that was not supplied. A file that
    does not lex or parse is the refusal `Source` / `check_on_line` already give. The code lists and never ranks."""
    import s5_precheck as S5
    notes = notes if isinstance(notes, list) else []
    soft_entry = reader_entry if reader_entry is not None else spec.get("entry")
    patterns, soft_note = AD.soft_stated(soft_entry)
    if soft_note:
        notes.append(soft_note)
    soft_rx = [re.compile(p) for p in patterns]
    scope_rows = AD.soft_scopes_of(reader_entry, notes) if reader_entry is not None else []   # the table's soft SCOPES (t-2064 P1b)

    def text_of(raw: bytes, name: str) -> str:
        raw = raw[len(_BOM):] if raw.startswith(_BOM) else raw
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Refusal(f"{name} is not UTF-8 ({exc.reason} at byte {exc.start}); a file read in the wrong encoding is "
                          "never listed. Nothing was changed.") from exc

    def statement_of(node, text: str) -> str:
        if isinstance(node, (ast.With, ast.AsyncWith)):
            return "with " + ", ".join(ast.get_source_segment(text, item.context_expr) or "" for item in node.items)
        return ast.get_source_segment(text, node) or ""

    def listing(text: str, name: str) -> list:
        """The checks of one file, in source order, each with its key: through `_python_checks` or `_source_checks`."""
        rows = []
        if reader_entry is None:
            try:
                tree = ast.parse(text)
            except SyntaxError as exc:
                raise Refusal(f"{name} does not parse: {exc}") from exc
            for first, last, form_id, node, _col, row, _name in _python_checks(tree, _python_entry()[1]["forms"], text):
                statement = statement_of(node, text)
                rows.append({"line": first, "end_line": last, "form": form_id, "text": statement,
                             "soft": any(rx.match(statement) for rx in soft_rx), "invertible": row.get("invert") is not None,
                             "has_message": isinstance(row.get("message"), dict)})
            return _number_rows(rows, name)
        return _table_rows(Source(text, reader_entry["lexer"], name), reader_entry, name, soft_rx, scope_rows, notes)

    spans = []
    for row in bindings or []:
        got = S5._ref_span(row.get("assertion_ref")) if isinstance(row, dict) else None
        if got is None:
            notes.append(f"binding {str((row or {}).get('assertion_ref') if isinstance(row, dict) else row)!r} is not a "
                         "<file>:<line> or <file>:<a>-<b>, so it labels no check")
            continue
        spans.append((got[0], got[1], got[2], row.get("then")))

    def make(row: dict, in_body: bool) -> dict:
        then = next((t for f, a, b, t in spans if _same_file(f, row["file"]) and row["line"] <= b and a <= row["end_line"]), None)
        return {"key": row["key"], "file": row["file"], "line": row["line"], "end_line": row["end_line"], "form": row["form"],
                "soft": row["soft"], "invertible": row["invertible"], "has_message": row["has_message"], "in_body": in_body,
                "then": then, "statement_sha": sha256(" ".join(row["text"].split()).encode("utf-8")), "scope": row.get("scope"),
                "ordinal": row["ordinal"], "offset": row.get("begin")}

    own_text = text_of(data, spec["file"])
    own_rows = listing(own_text, spec["file"])
    span = test_body_span(data, spec, reader_entry)
    if span is None:
        notes.append(f"the body of {spec['function']} is not located in {spec['file']} (no such declaration, or more than one): "
                     "only the checks a binding names are listed")
    in_body = [r for r in own_rows if span is not None and span[0] <= r["line"] <= span[1]]
    out = [make(r, True) for r in in_body]
    listed = {c["key"] for c in out}
    cache = {spec["file"]: own_rows}

    def rows_of(name: str):
        """The rows of a supplied file by the spelling it was given under, None when it was not supplied."""
        if name not in cache:
            held = next((h for h in helpers or [] if h.get("file") == name), None)
            if held is None:
                return None
            cache[name] = listing(text_of(held["data"], name), name)
        return cache[name]

    for file, first, last, _then in spans:
        name = spec["file"] if _same_file(file, spec["file"]) else next(
            (h["file"] for h in helpers or [] if _same_file(file, h["file"])), None)
        label = f"{'' if name == spec['file'] else file}:{first}" + (f"-{last}" if last != first else "")
        rows = rows_of(name) if name is not None else None
        if rows is None:
            notes.append(f"binding `{label}` names a file that was not read here (absent, or not under a test root): "
                         "its check is not listed")
            continue
        hits = [r for r in rows if r["line"] <= last and first <= r["end_line"]]
        if not hits:
            notes.append(f"binding `{label}` holds no check")
        for row in hits:
            if row["key"] not in listed:
                listed.add(row["key"])
                out.append(make(row, False))

    candidates = [h for h in helpers or [] if h.get("hop")]
    own_hop = _Hop(Path(spec["file"]), own_text, reader_entry, spec["file"], "")
    hops = [own_hop] + [_Hop(Path(h["file"]), h["data"].decode("utf-8-sig", "replace"), reader_entry, h["file"], "") for h in candidates]
    chain = {h["file"] for h in candidates if h.get("chain")}
    try:
        test = None if own_hop.unread else own_hop.test_unit(spec)
    except Refusal:
        test = None
    if test is not None and not in_body:
        picked = pick_hop(test, hops, lambda h: h.shown in chain)      # the ONE hop rule, shared with find_oracle (AR-13)
        found_unit = None
        if picked[0] in ("twice", "files"):
            notes.append(f"`{picked[1]}` holds a check in more than one declaration or file: which one the test calls is not told "
                         "by the name (no type is resolved), so none of its checks is listed")
            found_unit = False
        elif picked[0] == "found":
            found_unit = (picked[1], picked[3][0], picked[2])
        if found_unit:
            hop, unit, name = found_unit
            rows = own_rows if hop is own_hop else rows_of(hop.shown)
            inside = [r for r in rows or [] if unit["first"] <= r["line"] <= unit["last"]]
            notes.append(f"the body of {spec['function']} holds no check; the checks of `{name}` ({hop.shown}) are listed, one hop out")
            for row in inside:
                if row["key"] not in listed:
                    listed.add(row["key"])
                    out.append(make(row, False))
        elif found_unit is None:
            notes.append(f"the body of {spec['function']} holds no check and none of the helpers it calls, one hop out, holds one")
    elif test is not None:
        unnamed, where = set(), []
        for name in test["calls"]:
            for hop in hops:
                for unit in ([] if hop.unread else hop.units(name)):
                    if unit["check"] is None:
                        continue
                    rows = own_rows if hop is own_hop else rows_of(hop.shown)
                    keys = {r["key"] for r in rows or [] if unit["first"] <= r["line"] <= unit["last"]} - listed
                    if keys and name not in where:
                        where.append(name)
                    unnamed |= keys
        if unnamed:
            notes.append(f"{len(unnamed)} check(s) in helpers the body calls ({_capped(where, 4)}) are not listed: no binding "
                         "names them")
    return out


def run_plan(checks: list) -> list:
    """`[{run, keys, why}]`: the runs of one test's checks (t-2064 P2; pure). Checks outside the body each run alone, after the
    body's runs. In the body, in source order: non-stopping (`soft`) checks are collected into one run; a stopping check after a
    collected group joins it as its LAST check and closes it; a stopping check with no open group runs alone and opens none.

    POSITION INVARIANT: a check behind a stopping check in the same run is unreachable, so no run holds a stopping check before
    another check - at most one, and last (EP-B; P0 s2 and s3 measured both sides). A run's list is never reordered. The plan reads
    the form the author wrote; whether the checks really are independent is the role's (AR-29).

    A SCOPE (`scope` of a check, t-2064 P1b) is a stop of its own: the failures its checks recorded are thrown where it closes (measured:
    JUnit `assertAll`, AssertJ `assertSoftly`, NUnit `Assert.Multiple` - a check after it never ran), so a group never runs past the
    end of a scope - the next check starts a new run - and a stopping check INSIDE a scope throws out of it at once, losing the failures
    recorded before it (measured with a static `assertThat` in `assertSoftly`), so it never joins a group: it runs alone."""
    runs, group, last_scope = [], [], None

    def close(keys: list, why: str) -> None:
        runs.append({"run": len(runs) + 1, "keys": keys, "why": why})

    for check in (c for c in checks if c["in_body"]):
        scope = check.get("scope")
        if group and last_scope is not None and scope != last_scope:
            close(group, "non-stopping checks of a scope, which ends the test where it closes")
            group = []
        last_scope = scope
        if check["soft"]:
            group.append(check["key"])
        elif scope is not None:
            if group:
                close(group, "non-stopping checks before a stopping check inside a scope")
                group = []
            close([check["key"]], "a stopping check inside a scope runs alone")
        elif group:
            close(group + [check["key"]], "non-stopping checks, and the stopping check that closes them")
            group = []
        else:
            close([check["key"]], "a stopping check runs alone")
    if group:
        close(group, "non-stopping checks together")
    for check in (c for c in checks if not c["in_body"]):
        close([check["key"]], "outside the test body, alone")
    return runs


def _no_check_for_line(shown: str, line: int, facts: dict, prior) -> Refusal:
    """`_no_check_refusal`, and - when reading the test's own body had refused first for a reason of its own that is
    the CALL's (several declarations, a line in none, a line in the body that starts no head) - that reason ahead of
    it, whole: nothing the body reading said is lost. A tool refusal (no declaration) is not repeated: the line is what
    is wrong."""
    ours = _no_check_refusal(shown, line, facts)
    if isinstance(prior, Refusal) and not isinstance(prior, ToolRefusal):
        return Refusal(f"{str(prior).rstrip()} {str(ours).removeprefix('probe_by_code: ')}")
    return ours


def _target_at_line(src: Source, entry: dict, shown: str, line: int, prior=None) -> dict:
    """The `locate_target` answer for a check found by LINE in the whole file - the bypass: no declaration is read
    (`declaration` None, `candidates` []), the statement may end only where the file does. No check on the line is a
    refusal that names the nearest one."""
    checks = _source_checks(src, entry, shown)
    for first, last, index, start, match in checks:
        if first <= line <= last:
            return {"declaration": None, "candidates": [], "body": (0, len(src.skeleton)), "head_start": start,
                    "form": index, "head": match}
    raise _no_check_for_line(shown, line, _line_facts([(c[0], c[1], c[2]) for c in checks], line,
                                                      _skeleton_call_name(src, line)), prior)


def _parse_at(at):
    """(file hint, line) of `--at`: an int, `<line>` or `<file>:<line>` (the spelling of `assertion_id`), or None when it was
    not given. Any other spelling is the call's mistake and a refusal."""
    if at is None:
        return None
    if isinstance(at, int) and not isinstance(at, bool):
        return "", at
    text = str(at).strip()
    if text.isascii() and text.isdigit():
        return "", int(text)
    parsed = _ASSERTION_ID.match(text)
    if parsed:
        return parsed.group("file"), int(parsed.group("line"))
    raise Refusal(f"probe_by_code: --at wants <line> or <file>:<line> (the spelling of assertion_id), got {at!r}. "
                  "Nothing was changed.")


def _parse_at_row(at) -> tuple:
    """(file hint, line, ordinal) of `--at` as the walk reads it (t-2064 P4b item 3, EP-O): `_parse_at`'s spellings, each with an optional
    `#n` after the line (`12#2`, `tests/helpers.py:12#2`: the n-th check that STARTS on that line, by head order; no `#n` is the first).
    A line below 1 or an ordinal below 1 is the call's mistake and a refusal. Pure."""
    text, ordinal = (str(at).strip() if not isinstance(at, int) else at), 1
    if isinstance(text, str):
        tail = re.match(r"^(?P<head>.*?)#(?P<n>\d+)$", text)
        if tail:
            text, ordinal = tail.group("head"), int(tail.group("n"))
    hint, line = _parse_at(text)
    if line < 1 or ordinal < 1:
        raise Refusal(f"probe_by_code: --at {at!r} names line {line} and check number {ordinal}: both count from 1 (`--at <line>`, "
                      "`--at <file>:<line>`, and `#2` after the line for the second check on it). Nothing was changed.")
    return hint, line, ordinal


def _bare_target(data: bytes, spec: dict, at) -> dict:
    """The target of a caller that gives only `at` (the plan functions called on bytes, without `_target_of`): a line of the
    given bytes, or the first check. Never reads another file."""
    given = _parse_at(at)
    if given is None:
        return {"line": None, "source": "first", "given": None, "outside_body": False, "same_file": True, "note": ""}
    span = test_body_span(data, spec, _reader_entry(spec))
    return {"line": given[1], "source": "at", "given": at, "same_file": True, "note": "",
            "outside_body": None if span is None else not span[0] <= given[1] <= span[1]}


def _target_file(ctx, run_cwd: Path, hint: str, what: str) -> Path:
    """The file a target names, through the ONE guard of every language (E10, E-J, #18): it exists under the project root or the
    run directory (absent is a refusal, never a fall back to the test), has the test's language by suffix, and - unless it IS
    the test - lies under a test root and under no protected product path. The product tree is never touched knowingly."""
    spec = ctx.spec
    found = next((p for p in (ctx.root / hint, run_cwd / hint) if p.is_file()), None)
    if found is None:
        raise Refusal(f"probe_by_code: {what} names the file {hint!r}, and no such file is under the project root. "
                      "Nothing was changed.")
    suffixes = spec["entry"]["suffixes"]
    if found.suffix.lower() not in suffixes:
        raise Refusal(f"probe_by_code: the {'oracle' if what == '--oracle' else 'target'} file {hint} is not a "
                      f"{spec['language']} file ({' '.join(suffixes)}): a helper is read with the grammar of "
                      "the test's own language. Nothing was changed.")
    if found.resolve() != ctx.path.resolve() and not _in_test_root(ctx.cfg, _rel_project(found, ctx.root)):
        raise Refusal(f"probe_by_code: the {'oracle' if what == '--oracle' else 'target'} file {_rel_project(found, ctx.root)} "
                      "is not under a test root (roots.test of a profile), or lies under a protected_app_paths entry: this "
                      "probe never touches the product tree knowingly. Name a helper inside the test tree, or use the probe "
                      f"that breaks the product in a throwaway copy: {RED_SANDBOX_DOOR}. Nothing was changed.")
    return found


def _target_of(ctx, at, oracle: str, test_bytes: bytes) -> dict:
    """`{file, line | None, source, outside_body, ...}`: the ONE reader order of the target (t-2045 N1, AR-13, AR-15) -
    `--at` (it wins), `--oracle`, the manifest row's `assertion_id` when it is `<file>:<line>`, else the first check
    (`source` ∈ at | oracle | assertion_id | first).

    POSITION: after the test's lock and before `_resolve_oracle`; the target file's lock is claimed after this call and BEFORE its
    bytes are read, so this reads no byte but the test's own (R9) - `outside_body` for another file is True without reading it.
    `file` is the path the mutation lands in; `--oracle` wins the file, then the file of `--at`, then of the id, then the test.
    `outside_body`: True when the check is in another file or function, None when the test's body is not located (read as
    outside), else whether the line lies outside the body (E-O: a pass on a body the run may not have touched is `incomplete`,
    never a verdict on the author). `given` is `--at` as spelled (a replay aims at the same file), `note` the one line a
    missing or malformed id leaves (F10: `first`, never a guess).

    t-2064 P4b item 3: `_probe` no longer calls this (`--at` / `--oracle` select rows on the plan road: `_row_selection`). The `assertion_id`
    and `first` branches stay, because the `source` values are still read: `proof_level._same_target` (:1315-1319) reads `target.source`
    (`oracle`, `first`) of a STORED old-road record against the one it is asked about, and `_judge_rows` (:`detail.get("target_source")`
    in `at`, `assertion_id`) judges old-road details; both serve records written before the flip and the old-road helpers
    (`_repeat_check`, `_run_and_judge`) that tests still call. Their removal is the item that retires those readers (not this one)."""
    spec = ctx.spec
    given = _parse_at(at)
    hint, line, source, note = "", None, "first", ""
    if given is not None:
        (hint, line), source = given, "at"
    elif oracle:
        source = "oracle"
    else:
        raw = obligation_fields(ctx.entry)[0].get("assertion_id")
        text = raw.strip() if isinstance(raw, str) else ""
        parsed = _ASSERTION_ID.match(text) if text else None
        if parsed and int(parsed.group("line")) >= 1:
            hint, line, source = parsed.group("file"), int(parsed.group("line")), "assertion_id"
        else:
            note = (f"the manifest row's assertion_id {text!r} is not a <file>:<line>, so the first check of the test is "
                    "probed (fill the id as <file>:<line> to aim the probe)" if text else
                    "the manifest row has no assertion_id, so the first check of the test is probed")
    import execution_request as ER
    run_cwd = (ctx.root / _profile_cwd(ctx.cfg, spec["file"], ER.entry_profile_id(ctx.entry))).resolve()
    if oracle:
        file_hint = str(oracle).rpartition("::")[0]
        path = _target_file(ctx, run_cwd, file_hint, "--oracle") if file_hint else ctx.path
    elif hint and not _same_file(hint, spec["file"]):
        path = _target_file(ctx, run_cwd, hint, "--at" if source == "at" else "the manifest row's assertion_id")
    else:
        path = ctx.path
    same = path.resolve() == ctx.path.resolve()
    if not same or source == "oracle":
        outside = True
    elif line is None:
        outside = False
    else:
        span = test_body_span(test_bytes, spec, _reader_entry(spec))
        outside = None if span is None else not span[0] <= line <= span[1]
    return {"file": path, "rel": _rel_project(path, ctx.root), "line": line, "source": source, "outside_body": outside,
            "given": at if source == "at" else None, "same_file": same, "note": note}


# --- the checks that stand before the first write (R6, E10) ----------------------------------------------

def _in_test_root(cfg: dict, rel: str) -> bool:
    """E10, the interim rule: `rel` (project-relative, POSIX) lies under a profile's `roots.test` (or the
    config's `tests_root`) and under no `protected_app_paths` entry (those are relative to `app_root`). The
    seam B-415 widens: `test_locations.is_test_path(rel, cfg).by == "config"` will also pass; `markers` alone
    never does. Invariant: the product tree is never touched knowingly.

    EP1-12 (AR-13, AR-15): every path here is spelled by `execution_request._path_key` and compared by
    `execution_request.path_under` - the pair `profiles_owning` uses - so `./tests`, `tests\\x` and `tests/a/../x`
    are one spelling. The direction of error is only toward False (the edit is refused): an empty path, an absolute
    path (`/x`, `\\x`, `C:...`: `_path_key` would cut the outer slash and read `/tests/x.py` as `tests/x.py`) and a
    path that climbs out of the project (`..`) are False before any compare; the protected paths are checked after
    the roots and win over them."""
    import execution_request as ER
    text = str(rel or "").replace("\\", "/").strip()     # stripped ONCE, before every absolute check: ` /x` is `/x`, as `_path_key` reads it
    if not text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        return False
    key = ER._path_key(text)
    if not key or key == ".." or key.startswith("../"):
        return False
    roots = [ER._path_key((p.get("roots") or {}).get("test")) for p in cfg.get("profiles") or [] if isinstance(p, dict)]
    roots.append(ER._path_key(cfg.get("tests_root")))
    if not any(r and not (r == ".." or r.startswith("../")) and ER.path_under(key, r) for r in roots):
        return False
    app = str(cfg.get("app_root") or ".").replace("\\", "/")
    for protected in cfg.get("protected_app_paths") or []:
        base = ER._path_key(posixpath.join(app, str(protected).replace("\\", "/")))
        if not base or ER.path_under(key, base):
            return False
    return True


def _capped(items: list, cap: int = OFFENDER_CAP) -> str:
    return ", ".join(items[:cap]) + (f" and {len(items) - cap} more" if len(items) > cap else "")


def _normalised_id(report_id: str, entry: dict) -> list:
    """The report id as it is compared with the --test tail: a trailing `(...)` stripped (parameters), `::` and
    the entry's `report_separators` turned into `tail_join`, whitespace folded. Both spellings (with and
    without the parentheses) come back: a title that really ends in `)` must not be lost to the strip."""
    out = []
    for raw in (_strip_call(report_id), report_id):
        text = raw.replace("::", entry["tail_join"])
        for separator in entry.get("report_separators") or []:
            text = text.replace(separator, entry["tail_join"])
        out.append(_untagged(text, entry))
    return out


def _untagged(text: str, entry: dict) -> str:
    """`text` with the entry's own tags (`title_tag`: a `@smoke` in a title) taken out and the whitespace folded; both sides of
    every title comparison go through here, so a tag the report keeps and the --test leaves out (or the reverse) is no mismatch.
    An entry without `title_tag` gets the whitespace fold alone, as before."""
    if entry.get("title_tag"):
        text = re.sub(entry["title_tag"], "", text)
    return " ".join(text.split())


def _tail_matches(report_id: str, tail: str, entry: dict) -> bool:
    folded = _untagged(tail, entry)
    for candidate in _normalised_id(report_id, entry):
        if candidate.endswith(folded) and (len(candidate) == len(folded) or candidate[-len(folded) - 1] in NAME_BOUNDARY):
            return True
    return False


def _profile_of(cfg: dict, rows: list, case: str) -> dict:
    """The profile `build_mine_request` will pick for these rows (its own selector, `_profile_for`: one reading
    of "which profile runs this", FR-17), or a refusal."""
    import execution_request as ER
    files = sorted({str(r["node"]).split("::")[0] for r in rows})
    try:
        # This tool takes no `--profile`: the refusal names only the manifest-row door (FR-2).
        wanted = ER._profile_for(cfg, files, "", [r["entry"] for r in rows], [], [case], profile_door=False)
    except ER.MineRefusal as exc:
        raise Refusal(f"probe_by_code: {str(exc).rstrip('. ')}. Nothing was changed.") from exc
    return next((p for p in cfg.get("profiles") or [] if isinstance(p, dict) and p.get("profile_id") == wanted), {})


def _longer_title(text: str, entry: dict, tail: str, report_id: str) -> tuple:
    """(title, line) of ANOTHER test of the file whose title ends with `tail` at a boundary and that the report
    id ends with too, else ("", 0). For a call-style entry the join and the boundary are both a space, so the
    id of the test titled `calc does not adds` also "ends with" `adds`: `--test x.ts::adds` against that row
    would pass R6(c), and the pass of the OTHER test would be read as a dead check for this one."""
    try:
        src = Source(text, entry["lexer"])
        pattern = re.compile(entry["test_declaration"].replace(AD.NAME, "(?P<_title>[^\r\n]+?)"))
    except (Refusal, re.error) as exc:
        raise Refusal("probe_by_code: the titles of the other tests of the file cannot be listed to tell them from "
                      f"this one ({str(exc)[:120]}), and a report id that ends with several titles is ambiguous. "
                      "Nothing was changed.") from exc
    for found in pattern.finditer(src.code):
        if src.skeleton[found.start()] != src.code[found.start()]:
            continue
        # the other test's title as written (a templated one with its `${...}`; tags out on BOTH sides, so the same test with
        # a tag the --test leaves out is not "another test")
        title = _untagged(found.group("_title"), entry)
        if title != _untagged(tail, entry) and _tail_matches(title, tail, entry) and _tail_matches(report_id, title, entry):
            return title, src.line(found.start())
    return "", 0


def _pattern_ends(pattern: str, report_id: str, entry: dict) -> bool:
    """Does the report id END with a title the `pattern` (a templated title's, `test_source` shape) fits, at a name boundary?
    A pattern that does not compile fits nothing."""
    for candidate in _normalised_id(report_id, entry):
        try:
            if re.search("(?:^|[" + re.escape(NAME_BOUNDARY) + "])(?:" + pattern + ")$", candidate):
                return True
        except re.error:
            return False
    return False


def _report_id_fits(report_id: str, spec: dict, entry: dict) -> bool:
    """R6 (c): the row's report id ends with the --test tail. A templated --test title also fits a report id that is the title
    RENDERED (a role wrote what the runner printed): the id then ends with a string the title's own pattern fits."""
    if _tail_matches(report_id, spec["tail"], entry):
        return True
    if not spec.get("template"):
        return False
    pattern = test_source._shape(spec["function"], entry, False)[1]
    return bool(pattern) and _pattern_ends(pattern, report_id, entry)


def _code_built(cfg: dict, row_entry: dict, argv, root):
    """The selector and report identity the CODE builds for a manifest row that carries none of its own
    (`execution_request.code_selection`, the ONE builder: `--mine` calls it for the same row, EP1-37), or None. The row's profile
    directory is `_profile_cwd`'s; with no project `root` nothing is built (a caller that has none keeps the hand-written rule)."""
    if root is None:
        return None
    import execution_request as ER
    run_cwd = Path(root) / _profile_cwd(cfg, str(row_entry.get("file") or ""), ER.entry_profile_id(row_entry))
    return ER.code_selection(row_entry, argv, run_cwd, Path(root))


def run_shape_checks(cfg: dict, manifest: dict, case: str, entry_row: dict, spec: dict, instance_id: str,
                     context: str, text: str, root=None) -> None:
    """R6: what must hold before one byte is written, because the whole CASE runs (a non-pytest runner
    selects by the manifest's own arguments, not by a node id) and only the row whose report id equals the
    instance's is read. Exit 2, "Nothing was changed". (a) every row of the case has `selector_args` and a
    `report_test_id` - its own, or the ones the code builds for it (`_code_built`; the role's own win, as in `--mine`) - no file
    of it is bare, and the profile's selectors are verified (`profile_contract.selectors_verified`); (b) --test names the
    manifest row's file; (c) the row's report id ends with the --test tail; (d) a compiled entry's launch does
    not forbid a rebuild. Invariant: the mutated test is the test the run selects, and a mutation that never
    reached the build never yields `no_failure` (E11, E12, E14). A row nothing selects on a profile whose command is the
    project's own script is refused BY NAME (`no_direct_form`) and never passes (FR-41, AR-28); `root` is the project, not a clone."""
    import execution_request as ER
    import launch_check
    import profile_contract as PC   # the ONE reader of the `commands` shape (OH3-27, AR-13)
    entry = spec["entry"]
    rows, bare = ER.manifest_rows(manifest, case)
    profile = _profile_of(cfg, rows, case) if rows else {}
    argv = PC.one_test_argv(profile)[0]
    offenders = []
    for row in rows:
        lacks = [name for name, ok in (("selector_args", isinstance(row["entry"].get("selector_args"), list)
                                        and bool(row["entry"]["selector_args"])),
                                       ("report_test_id", bool(str(row["entry"].get("report_test_id") or "").strip())))
                 if not ok]
        if lacks and _code_built(cfg, row["entry"], argv, root) is None:
            offenders += [f"{row['instance_id']} (no `{name}`)" for name in lacks]
    offenders += [f"{file} (names no test)" for file in bare]
    verified = PC.selectors_verified(profile, root)
    if offenders or not verified:
        no_form = str(launch_check.runner_identity(argv)["no_direct_form"] or "") if offenders else ""
        if no_form:
            raise ToolRefusal(f"probe_by_code: {no_form}; the probe is not run on this profile; onboarding offers the "
                              f"direct form. {len(offenders)} instance(s) of {case} that the run would select have no selector "
                              f"of their own: {_capped(offenders)}. Nothing was changed.")
        problems = []
        if offenders:
            problems.append(f"{len(offenders)} instance(s) of {case} that the run would select have no selector of "
                            f"their own: {_capped(offenders)}")
        if not verified:
            problems.append(f"profile {profile.get('profile_id') or '(none found)'} does not say its selector contract "
                            "is verified (selectors.verified in qa-factory/config.json: the onboarding's gap)")
        raise ToolRefusal("probe_by_code: " + "; ".join(problems) + ". A non-pytest runner runs the whole case, and the "
                          "factory binds one report row by the report id the manifest records; the automator records "
                          "them once through `manifest_put.py --task <TICKET> --fragment <file>` "
                          '(`{"tests": [{"instance_id": "<id>", "selector_args": ["<the framework\'s own arguments>"], '
                          '"report_test_id": "<the runner\'s name>"}]}`), then probe again. Nothing was changed.')
    row_file = str(entry_row.get("file") or "").replace("\\", "/")
    if not _same_file(row_file, spec["file"]):
        raise Refusal(f"probe_by_code: --test names {spec['file']}, but the manifest row of {instance_id!r} names "
                      f"{row_file or 'no file'}: the mutated file must be the one the run selects. Nothing was changed.")
    report_id = str(entry_row.get("report_test_id") or "").strip()
    if not report_id:       # the row carries none: the id the code builds for it is the one the run reports under
        report_id = str((_code_built(cfg, entry_row, argv, root) or {}).get("report_test_id") or "")
    if not _report_id_fits(report_id, spec, entry):
        shown = (f"the report id of {instance_id!r} is {report_id!r}; it does not end with {spec['tail']!r} (the --test "
                 f"tail, segments joined by {entry['tail_join']!r}, after the same normalisation), so the test named "
                 "here is not certainly the test the run reports under that id.")
        if entry.get("display_name") and re.search(entry["display_name"], context):
            shown += (" The declaration carries a display name, and the report may name this test by it: the "
                      "manifest's `report_test_id` must be the runner's id for the method.")
        raise Refusal(f"probe_by_code: {shown} Fix --test or the row's `report_test_id` (manifest_put.py --fragment). "
                      "Nothing was changed.")
    longer, where = _longer_title(text, entry, spec["tail"], report_id) if entry["declaration_style"] == "call" else ("", 0)
    if longer:
        raise Refusal(f"probe_by_code: the report id of {instance_id!r} ({report_id!r}) ends with {spec['tail']!r}, but it "
                      f"also ends with the longer title {longer!r} of another test declared at line {where} of "
                      f"{spec['file']}: the row may belong to that test, and its pass would be read as a dead check of "
                      f"{spec['tail']!r}. Give --test the full title, or fix the row's `report_test_id` "
                      "(manifest_put.py --fragment). Nothing was changed.")
    if entry["compiled"]:
        argv, problem = PC.one_test_argv(profile)
        if problem:
            # no words, no proof that the build is the one that rebuilds: reading "no flag found" here would let a dead
            # check pass as a live one - the very thing this refusal guards
            raise Refusal(f"probe_by_code: profile {profile.get('profile_id') or '(none found)'}: {problem}. Nothing was changed.")
        stop = [a for a in argv if a in entry["no_rebuild_flags"]]
        if stop:
            raise Refusal(f"probe_by_code: the profile's one-test command carries {', '.join(stop)}, which stops the "
                          f"{spec['language']} build from picking up the mutated source, so the run would execute the "
                          "author's compiled test and report a pass for a check that never ran. Run the probe on a "
                          "profile whose command builds (the onboarding's `commands.one_test`). Nothing was changed.")


def manifest_entry(task_root: Path, instance_id: str) -> dict:
    path = task_root / "work" / "automation-manifest.json"
    manifest = C.load_json(path) if path.is_file() else {}
    for entry in C.manifest_tests(manifest):
        if not isinstance(entry, dict):
            continue
        ids = {str(entry.get("instance_id") or "")} | set(C.instance_id_aliases(entry))
        if instance_id in ids:
            return entry
    raise Refusal(f"the manifest names no instance {instance_id!r} (work/automation-manifest.json) — "
                  "the automator records it through manifest_put.py first")


def obligation_fields(entry: dict) -> tuple:
    """The four fields the window's `probe` must repeat from its instance, and what is missing."""
    refs = entry.get("obligation_refs") if isinstance(entry.get("obligation_refs"), list) else []
    ids = entry.get("obligation_ids") if isinstance(entry.get("obligation_ids"), list) else None
    if ids is None and refs:
        ids = [str(r.get("obligation_id")) for r in refs if isinstance(r, dict) and r.get("obligation_id")]
    if ids is None and entry.get("obligation_id"):
        ids = [str(entry["obligation_id"])]
    fields = {"obligation_ids": ids or [],
              "obligation_hash": entry.get("obligation_hash") or (content_hash(refs) if refs else None),
              "defect_location": entry.get("defect_location") or None,
              "assertion_id": entry.get("assertion_id") or None}
    if refs:
        fields["obligation_refs"] = refs
    missing = [k for k in MANIFEST_FIELDS if not fields.get(k)]
    return fields, missing


# --- the run ---------------------------------------------------------------------------------------

def probe_runtime(spec: dict) -> dict:
    """The read-only runtime probe `--mine` runs before a first typed run of a profile - `run_suite.probe_runtime`, the
    ONE strict reader (t-300 N2 S8, FR-17). This function used to hold a copy of it that took `matched` only: a person's
    word reached the role's own `--mine` and not the critic's red probe, and a probe that compared nothing
    (`no_changed_file`) was refused here and taken there (B-255 a). One function, one exception class
    (`ProvenanceRefused`), one message; the delegate is imported on use (run_suite imports this package's modules)."""
    import run_suite
    return run_suite.probe_runtime(spec)


def _profile_cwd(cfg: dict, file: str, profile_id: str = "") -> str:
    """The run directory of the profile that owns this file ('.' when none does). The owners are asked of the one
    predicate `_profile_for` asks (`execution_request.profiles_owning`); `profile_id` is the profile the manifest
    row NAMES (`execution_request.entry_profile_id`), which settles a shared root. Invariant: a root several
    profiles share never gives the first profile's directory: when they run in one directory that directory is
    the answer (no guess is made), when they run in different ones the tie is refused with its door. A profile the
    row names that the config does not hold is refused too (EP1-16, A-E4): it is not read as a path, which would run
    the test under whichever profile owns the file - the same predicate and words as `_profile_for`
    (`execution_request.known_profile`, AR-13)."""
    import execution_request as ER
    profiles = {str(p.get("profile_id")): p for p in cfg.get("profiles") or [] if isinstance(p, dict)}
    if profile_id and not ER.known_profile(cfg, profile_id):
        raise Refusal("probe_by_code: " + ER.unknown_profile_refusal(cfg, profile_id, ER.NAMED_BY_ROW)
                      + ". Nothing was changed.")
    owners = [profile_id] if profile_id else ER.profiles_owning(cfg, file)
    import profile_contract as PC     # the ONE reader of the `commands` shape (OH3-27, AR-13)
    # a profile whose commands cannot be read names no directory (as one with no `cwd`): the run is refused earlier, where the
    # command is built from it, with the shape problem
    cwds = {str(PC.profile_command(profiles[o], "one_test")[0].get("cwd") or ".")
            for o in owners if o in profiles}
    if len(cwds) > 1:
        raise Refusal(f"probe_by_code: profiles {', '.join(owners)} share the test root of {file} and run in "
                      "different directories, so the path cannot tell where this test runs; name the profile on "
                      "the manifest row of the instance (`profile_id`). Nothing was changed.")
    return cwds.pop() if cwds else "."


def build_request(root: Path, cfg: dict, task: str, dispatch: str, case: str, spec: dict,
                  instance_id: str, mutation: str, reason: str, profile_id: str = "", s6_close: bool = False,
                  mutation_kind: str = MUTATION_KIND, extra_argv=()) -> tuple:
    """The typed red_probe request of this one node, built by the code `--mine` uses. `extra_argv` (t-2064 P4a, F-P10; the walk's
    `AD.no_retry_flags`, the ONE reader of the data row) is appended to `command.argv` after the build and named in the notes: the
    request validator reads `command.argv` only as a non-empty string array, and `input_fingerprint` is built from files, config
    projection and runtime provenance, not from the argv, so the flags change neither the validity nor the fingerprint (they never
    become a verdict on the test). With `s6_close` the dispatch
    is the S6 close context (`execution_request.s6_close_dispatch`, read afresh): `dispatch` is then only the
    name the idempotency key starts with, and no dispatch id goes to the builder. A test the table reads
    (`spec["reader"]`) is selected the way L9 of the sandbox probe selects one: the request is built
    for the whole case (a non-pytest runner takes the manifest's own `selector_args`, never a node id built
    here), and the instance must be one of the instances it selects (R7)."""
    from execution_request import JobStore, build_mine_request
    by_table = _is_table(spec)      # the runner's selection by node id (t-2045 §3 #10): the ONE read of the reader in this builder
    # A red probe is always told where to run (the request builder refuses one that is not). This
    # probe mutates the author's tree in place - there is no clone - so the directory is passed
    # as `--cwd`, and it is the profile's own: the one the call used to be retried with after a
    # refusal whose WORDING it matched on. The profile the row names goes to the builder too (EP1-16): it used to
    # settle only the directory, and the builder then refused a root two profiles share for want of the name it had
    # been given one line above. This tool has no `--profile`: the builder's refusal names the row door only.
    cwd = (root / _profile_cwd(cfg, spec["file"], profile_id)).resolve()
    request, notes, _reusable, _verified = build_mine_request(
        root, [case], cfg=cfg, task=task, dispatch_id="" if s6_close else dispatch, purpose="red_probe",
        node_ids=None if by_table else [spec["node"]], again=True, reason=reason, probe=probe_runtime,
        cwd=str(cwd), profile_id=profile_id, profile_door=False, s6_close=s6_close)
    flags = [flag for flag in extra_argv or () if isinstance(flag, str) and flag]
    if flags:
        request["command"]["argv"] = list(request["command"]["argv"]) + flags
        notes = list(notes) + [f"the no-retry flags {' '.join(flags)} were added to the run's command (the runner would otherwise run "
                               "a failed test twice)"]
    selected = list(request.get("selected_instance_ids") or [])
    if by_table:
        if instance_id not in selected:
            raise Refusal(f"the request for {case} selects {selected}, which does not include {instance_id!r}")
    elif selected != [instance_id]:
        raise Refusal(f"--test {spec['node']} names instance {selected}, not {instance_id!r}")
    jobs = JobStore(artifacts_dir(task) / "state" / "execution-jobs").jobs()
    taken = {str(j.get("idempotency_key")) for j in jobs}
    base = f"{dispatch}:red_probe:probe-{instance_id}:{mutation}:{request['input_fingerprint'][:12]}"
    key, attempt = base, 1
    while key in taken:
        attempt += 1
        key = f"{base}:again-{attempt}"
    request["idempotency_key"] = key
    request["reason"] = reason
    request["built_by"] = {"tool": "probe_by_code.py", "cases": [case], "instance_id": instance_id,
                           "mutation": mutation, "mutation_kind": mutation_kind}
    return request, notes


def run_request(root: Path, request_path: Path, timeout: int) -> tuple:
    """`run_suite.py --request <file>` as a subprocess (or `PROBE_RUN_SUITE`); (proc, summary)."""
    runner = os.environ.get("PROBE_RUN_SUITE") or str(Path(__file__).resolve().parent / "run_suite.py")
    argv = [sys.executable, "-B", runner, "--request", str(request_path)]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", QA_FACTORY_SKIP_DASHBOARD_REFRESH="1")
    proc = subprocess.run(argv, cwd=str(root), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env=env)
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip().startswith("{")]
    try:
        summary = json.loads(lines[-1]) if lines else {}
    except ValueError:
        summary = {}
    return proc, summary if isinstance(summary, dict) else {}


# --- reading the result ------------------------------------------------------------------------

DEFAULT_REPORTER = "junit-xml"


def report_rows(path: Path, reporter: str, raw: bool = False) -> list:
    """`raw`: the shared reader's own rows (`{test_id, status, problems}`), for the road that binds a row
    by the runner's report id and reads its frames (`_judge_rows`: every language, N3b). Otherwise (the alternative
    probe's injected row judge, until P5):

    The run's report as `{test_id, status, message, text}` rows, read by the shared reader
    (`reporters.read_rows`, dispatched on the TYPED `reporter` of the run's summary).

    `observe` below wants one status and one message/stack per row, as this script's private
    JUnit reader gave them: the FAILURE's own message and stack when the testcase has one, else
    the ERROR's, and then the status is `failed` / `error` — even beside a `<skipped>` child. The
    shared reader keeps every problem of the row in document order and lets a skip outrank a
    failure in `status`; this picks from `problems` what the private reader picked. A row with
    neither keeps the shared reader's status (`passed`, `skipped`, TRX `not_run`)."""
    if raw:
        return reporters.read_rows(path, reporter)
    rows = []
    for row in reporters.read_rows(path, reporter):
        problems = row.get("problems") or []
        chosen = next((p for p in problems if p.get("kind") == "failure"),
                      next((p for p in problems if p.get("kind") == "error"), None))
        status = row.get("status")
        if chosen is not None:
            status = "failed" if chosen["kind"] == "failure" else "error"
        rows.append({"test_id": row["test_id"], "status": status,
                     "message": (chosen or {}).get("message", ""), "text": (chosen or {}).get("text", "")})
    return rows


def _tail(node_id: str) -> str:
    return str(node_id or "").replace("\\", "/").rsplit("::", 1)[-1]


def _same_file(observed: str, expected_file: str) -> bool:
    observed = observed.replace("\\", "/")
    expected_file = expected_file.replace("\\", "/")
    return observed == expected_file or observed.endswith("/" + expected_file) or \
        expected_file.endswith("/" + observed)


def observe(row: dict, spec: dict, detail: dict) -> dict:
    """What the report says: the last traceback line (pytest's own `path:line: Exception`),
    and, when that line is inside a helper (hamcrest, a page object), the deepest frame of the
    test file itself."""
    out = {"status": row.get("status"), "message_head": fold((row.get("message") or "").splitlines()[0]
                                                            if row.get("message") else "", 300)}
    lines = [ln.strip() for ln in (row.get("text") or "").splitlines() if ln.strip()]
    last = _TRACE_TAIL.match(lines[-1]) if lines else None
    if last:
        exc = last.group("exc").split(".")[-1]
        out["location"] = last.group("loc")
        out["failure_kind"] = ("assertion" if exc == "AssertionError" else
                               "error" if row.get("status") == "error" else "exception")
    elif row.get("status") in {"failed", "error"}:
        out["failure_kind"] = "error" if row.get("status") == "error" else "exception"
        head = (row.get("message") or "").split(":", 1)[0].strip()
        if head == "AssertionError":
            out["failure_kind"] = "assertion"
    frames = []
    for line in lines:
        match = _FRAME.match(line)
        if match and _same_file(match.group("path"), spec["file"]):
            frames.append((match.group("path"), int(match.group("line"))))
    if frames:
        out["test_file_frame"] = f"{frames[-1][0]}:{frames[-1][1]}"
    return out


def _location_hits(location: str, spec: dict, detail: dict) -> bool:
    if not location:
        return False
    path, _, line = location.replace("\\", "/").rpartition(":")
    return line.isdigit() and _same_file(path, detail.get("file") or spec["file"]) and \
        detail["line"] <= int(line) <= detail["end_line"]


# --- reading the run of a test: ONE row judge for every language (R8, t-2064 N3b) -----------------------------------
# The site comes from `reporters.assertion_site` with the entry's frame grammar, and the row judge is the one place that
# decides what the tool may say about the AUTHOR's test. "Only our text proves without a role" (the owner's word): the tool
# proves a failure by ONE thing, the probe's own marker read in the failure's text; a failure without it is not proved by
# its place or by the library's wording (a throw inside the statement's arguments is at the same line, a foreign
# `AssertionError` from a helper has the same type) - it is the code critic's, with the facts. Anything the tool did not read
# well enough (a row with no text, a pass whose body is unknown, a launcher that may not rebuild) is `incomplete`, `cause: tooling`,
# never a verdict on the test (FR-59, E15, E26); an error row or an unresolvable frame, with its text, goes to the critic.
# The alternative reading (t-2064 P5) walks the same road and is judged by the same row judge.

def text_head(text: str, entry: dict) -> str:
    """The failure's text above its first stack frame or skipped line."""
    frames, skip, _path = AD.grammar_of(entry)
    stops = [re.compile(pattern) for pattern in frames + skip]
    lines = []
    for line in str(text or "").splitlines():
        if any(stop.search(line) for stop in stops):
            break
        lines.append(line)
    return "\n".join(lines)


def failure_problem(row: dict) -> dict:
    problems = row.get("problems") or []
    return next((p for p in problems if p.get("kind") == "failure"),
                next((p for p in problems if p.get("kind") == "error"), {}))


def fires_on(row: dict, entry: dict, fires_as: str) -> bool:
    """Does the failure show the message the inverted form must? The `message` first; the text above the first
    frame when the message is empty OR does not match (a Playwright junit message may be `file:line title`).

    RN1-8: the runner's failure body (`text_head`) is read through `AD.fires_in`: the whole text and EACH LINE of it, leading
    whitespace cut, so a `^` in the row's sample binds to the start of a line and not of the whole text (a Playwright report
    opens with a header and its own `Error: <msg>` line; the library's `expect(received)...` line comes after, indented). The
    `message` attribute stays matched WHOLE, as before (`by_line=False`). What this does NOT bound: a line of the failure body
    that is the author's own assertion message can fire a row, as it could when it opened the body; the caller's location
    check bounds WHERE the failure is, not WHOSE words it shows. A blank line is skipped."""
    problem = failure_problem(row)
    message = str(problem.get("message") or "")
    head = text_head(problem.get("text"), entry)
    return AD.fires_in(fires_as, message, by_line=False) or AD.fires_in(fires_as, head)


def launcher_words(argv) -> str:
    """The launch as argv basenames joined by spaces, `.exe` / `.cmd` / `.bat` stripped."""
    words = []
    for token in argv or []:
        name = posixpath.basename(str(token).strip("\"'").replace("\\", "/"))
        for suffix in (".exe", ".cmd", ".bat"):
            if name.lower().endswith(suffix):
                name = name[:-len(suffix)]
        words.append(name)
    return " ".join(words)


def builds_by_default(argv, entry: dict) -> str:
    """The `builds_by_default` prefix this launch starts with (at a token boundary), or ""."""
    words = launcher_words(argv)
    return next((prefix for prefix in entry["builds_by_default"] if words == prefix or words.startswith(prefix + " ")), "")


def _row_status(row: dict) -> str:
    """The status of a RAW report row as the road reads it (t-2045 E-P): the shared reader lets a `<skipped>` child outrank a
    failure in `status`, so a row that holds a failure or an error problem is `failed` / `error` (the failure first, as
    `failure_problem` picks), else the row's own status. Pure; a failed row is never read as not executed."""
    return {"failure": "failed", "error": "error"}.get(failure_problem(row).get("kind"), row.get("status"))


def _row_answer(observed: dict, verdict: str, note="", location=None, reason=None, mismatches=(), cause=None, proved_by=None) -> dict:
    """The one shape every step of `judge_probe_row` answers in. `cause` is written only by the step that owes a judgment
    (RN1-8, E15): every other `incomplete` answer is the tool's gap, and the caller writes that. `proved_by` is how an
    `intended_failure` was established: only `marker` is written here (`critic` is `judge_record`'s)."""
    got = {"verdict": verdict, "actual_location": location, "actual_reason": reason,
           "mismatches": list(mismatches), "observed": observed, "note": note}
    if cause:
        got["cause"] = cause
    if proved_by:
        got["proved_by"] = proved_by
    return got


def _problem_texts(row: dict, fields=AD.MARKER_READ_FIELDS) -> list:
    """The texts a probe's token may be read from in ONE report row (t-2064 P4a): the `message` and the `text` (the `fields` asked
    for; the caller passes the entry's `marker_read`) of EVERY problem of kind `failure` or `error`, in document order - not only
    the first one `failure_problem` picks (a Playwright body is one problem, another reporter may hold several, and the token may
    stand only in the second). Never the system-out, an attachment or a step title: the row carries only problems. Pure; `[]` for a
    row with none; an empty or non-text field is skipped."""
    texts = []
    for problem in (row.get("problems") or []) if isinstance(row, dict) else []:
        if not isinstance(problem, dict) or problem.get("kind") not in ("failure", "error"):
            continue
        for field in ("message", "text"):
            value = problem.get(field)
            if field in fields and isinstance(value, str) and value:
                texts.append(value)
    return texts


def _cut_by_runner(texts: list, entry: dict) -> bool:
    """Do the `texts` of a failed row say the runner CUT the test (its timeout ended it mid-way)? The entry's own words
    (`interruption_texts`, DATA: regexes, `[]` where the entry states none - nothing is ever demoted on that language, EP-V's named
    residual). It only DEMOTES a marker read (a check the timeout cut prints its marker undecided, P0 s4 / P0b s4b) and never proves
    anything; the error direction is toward the role. A regex that does not compile reads as no cut here (the loader refuses it
    earlier)."""
    for pattern in AD.interruption_texts(entry):
        try:
            rx = re.compile(pattern)
        except re.error:
            continue
        if any(rx.search(text) for text in texts):
            return True
    return False


def _row_by_marker(row: dict, token: str, detail: dict, entry: dict, observed: dict):
    """Step 1: a `failed` row whose failure or error problems (the fields the entry's `marker_read` names - the message, and the text
    for a runner whose text echoes no values; every problem of kind `failure` or `error`, `_problem_texts`; never the system-out, an
    attachment or a step title) hold the EXACT `token` was thrown by the check the probe broke - the token exists
    in no other place (joined at run time, E1.3), so whatever site the frame names (a soft collector reports at its end, R9) and
    whatever wording the library chose, it is that check's own failure: `intended_failure`, `proved_by: marker`. The ONE thing that
    proves in code, and the ONE reader of a marker in a row (AR-13). None when it does not settle the row: an empty token (a probe
    planned without one), a row that is not `failed`
    (a `passed` row is never looked at, an `error` row is not decided here), a token not in the text. The `missed` note of a
    `fires_as` the library's wording did not match stays only a note (the row is the factory's to correct); a null `fires_as`
    writes none."""
    if not token or _row_status(row) != "failed":
        return None
    # B1 (t-2064): WHERE the token may be read is the runner's data (`marker_read`): a runner that prints argument values in its
    # failure text (pytest) echoes the joined token there when a callee throws, so it reads the message only
    # the token counts only as its EXACT self: 12 hex characters, so a hex run around it makes it part of another word
    exact = re.compile(r"(?<![0-9A-Fa-f])" + re.escape(token) + r"(?![0-9A-Fa-f])")
    if not any(exact.search(text) for text in _problem_texts(row, AD.marker_read(entry))):
        return None
    fires_as = detail.get("fires_as")
    missed = "" if not fires_as or fires_on(row, entry, fires_as) else (
        f"proved by the factory's marker; the library's wording did not match the row (the `{detail['language']}` entry of "
        f"references/detectors.json, pair {detail.get('pair_id') or detail.get('pair')}, `{observed['message_head'][:120]}`): the row "
        "is the factory's to correct")
    return _row_answer(observed, "intended_failure", missed, proved_by="marker")


def _row_passed(row: dict, entry: dict, detail: dict, observed: dict, *, among: bool, argv):
    """Step 2: a `passed` row is NEVER proved. `among` (the caller's: the target was chosen by `--at` or the manifest's id and the
    body that ran is not shown to be the one mutated) -> `incomplete`, no text, no cause set here (the caller writes `cause:
    tooling`), never `no_failure`; a compiled entry whose launcher may not rebuild -> `incomplete`; else `no_failure`. None when the
    row is not `passed`."""
    if _row_status(row) != "passed":
        return None
    language = detail["language"]
    prefix = builds_by_default(argv, entry)
    if among:
        return _row_answer(observed, "incomplete",
                           f"the inverted run passed and the check at {detail.get('file')}:{detail.get('line')} was chosen by "
                           f"{detail.get('target_source')} - not shown to stand in the body of the test that ran "
                           f"({row.get('test_id')}): a pass does not say which body ran, so the check is not called dead (E5)")
    if entry["compiled"] and not prefix:
        return _row_answer(observed, "incomplete",
                           f"the {language} entry is compiled and the launcher `{launcher_words(argv)[:80]}` is not one that "
                           f"rebuilds by default ({', '.join(entry['builds_by_default']) or 'none listed'}): the inverted source may "
                           "never have reached the build, and a pass then proves nothing (E14)")
    if entry["compiled"]:
        return _row_answer(observed, "no_failure", f"the launcher builds by default (`{prefix}`)",
                           mismatches=["the mutated assert never fired"])
    residual = entry.get("passed_residual")      # DATA of the entry (t-2064 par.12 d): no language branch, no key = no residual
    if residual:
        observed["residual"] = residual
    return _row_answer(observed, "no_failure", mismatches=["the mutated assert never fired"])


def _row_unsettled(observed: dict):
    """Step 4: a `failed` or `error` row with text and no token - whatever its type, whatever `fires_as` says, whether the form takes a
    marker or not, whether the location hits or not, whether the place was read or not. The place and the wording are FACTS for the
    critic (`judgment_facts`), never a proof and never `wrong_location`: `incomplete`, `cause: judgment`. The error direction of the
    judge. A row with NO text never comes here (`judge_probe_row` answers it first: `cause: tooling`)."""
    if observed.get("status") == "error":
        return _row_answer(observed, "incomplete",
                           "the run's row is an error (an exception outside an assertion, a timeout or a setup failure) and the "
                           "factory's marker is not in its text; whether the inverted check ran is the code critic's to read: "
                           + JUDGE_DOOR, cause="judgment")
    return _row_answer(observed, "incomplete",
                       "the run failed and the factory's marker is not in its text; the code critic judges it: " + JUDGE_DOOR,
                       cause="judgment")


def judge_probe_row(row: dict, site: dict, entry: dict, detail: dict, *, among: bool, argv) -> dict:
    """The R8 table, ONE judge for every language. {verdict, actual_location, actual_reason, mismatches, observed, note}; `note` is the
    one sentence a reader needs when the verdict is not `intended_failure`. A short sequence of steps; a step runs only when no earlier
    step settled the row, a `passed` row is never read as proved, no step reads the failure's wording or place to prove.

      1 failed, the probe's own marker in its failure text -> intended_failure  (`proved_by: marker`)
      2 passed + `among`                                    -> incomplete  (a pass says nothing about WHICH body ran)
        passed + compiled, launcher may not rebuild         -> incomplete  (the mutation may never have been built)
        passed otherwise                                    -> no_failure
      3 no row / any status but passed, failed, error       -> not_executed
        failed or error, no text at all                     -> incomplete  (no cause: the tool's gap; the caller writes `tooling`)
      4 failed or error, text, no marker                    -> incomplete, `cause: judgment`  (the code critic judges it; the place
                                                               may be unread: it is a fact he reads, not a gap of the tool)"""
    status = _row_status(row)
    problem = failure_problem(row)
    shown = (str(problem.get("message") or "").strip() or text_head(problem.get("text"), entry)).strip()
    observed = {"status": status, "message_head": fold(shown.splitlines()[0] if shown else "", 300)}
    for key in ("frame", "location", "failure_kind", "site_unread"):
        if site.get(key):
            observed[key] = site[key]
    settled = _row_by_marker(row, str(detail.get("message_marker") or ""), detail, entry, observed) \
        or _row_passed(row, entry, detail, observed, among=among, argv=argv)
    if settled is not None:
        return settled
    if status not in ("failed", "error"):
        return _row_answer(observed, "not_executed", f"report status {status!r}", mismatches=[f"report status {status!r}"])
    if not shown and not str(problem.get("text") or "").strip():
        # item 2 (N4): no text at all - nothing for the critic to read - is the tool's gap (the caller writes `cause: tooling`)
        return _row_answer(observed, "incomplete",
                           ("the run's row is an error and holds no message or text, so there is nothing to read: a tooling gap "
                            "(the runner's report carries none), not a verdict on the test") if status == "error" else
                           ("the failing row holds no failure text, so there is nothing to read: a tooling gap (the runner's report "
                            "carries no message), not a verdict on the test"))
    # items 1 and 3 (N4): a row with text goes to the critic whatever else is unread - the place (`site_unread`, no location) is a
    # fact he reads himself (the owner: the critic can look at the failing line on his own), never a reason to stop at a tooling gap
    return _row_unsettled(observed)


def _judge_joint_rows(rows: list, tokens: dict, group: list, plan: dict, details: list, facts: dict) -> tuple:
    """`({check key: outcome}, move)` for ONE run of the checks `group` (t-2064 P4a item 2; pure: it reads its arguments, runs nothing,
    writes nothing, and RETURNS which keys must be rerun alone). ONE judge for one check or many (EP-A): a loop over
    `_row_by_marker`, the one reader of a marker in a row. POSITION INVARIANT: a token read outranks everything but step C, and only a
    PASSED row settles a not-fire without another run. The error direction is toward `cause: judgment`, never `intended_failure`.

    Arguments. `rows`: the run's report rows for this test (the judge reads the first failed one, else the first error, else the
    first passed, else the first); `tokens`: `{check key: marker_token}` (a key with none - the check has no message slot - is never
    read); `group`: the run's keys in SOURCE order; `plan`: `{"checks": [checks_of rows], "runs": [run_plan rows]}`; `details`: the
    list `plan_model` returned for this run (a key's kinds are its `probe_kind`s); `facts`: `{"entry": the runner's table entry,
    "site": {"location": ...} the failing site as the row judge reads it, "author_green": {key: True|False|None} (computed by the
    caller, never here), "argv": the launch, "language_label": text for the passed rule's notes, "among": {key: True} for a key whose pass
    cannot say which body ran (absent or False: it can)}`; a pass of such a key is `incomplete`, `cause: tooling`, never `no_failure` (E5).

    Steps. A status: passed -> every key `no_failure` (a `find` model: `incomplete`, `cause: judgment`, EP-H); `error`, no row or any
    other status -> `judge_probe_row`'s rule for each key (no marker is read there), move `go on`. B read: the keys whose exact token
    stands in the message or text of any `failure` / `error` problem. C demote (EP-V): a key absent, or `_cut_by_runner`: the LAST
    read key in source order is demoted (a cut never proves). D a read key that stands: `invert` -> proved; a value kind -> proved
    only with `author_green` True, else `_row_unsettled` carrying `author_green` (F-P4). E the stop (EP-G): a key absent AND
    `_earlier_check_at` names a check -> the absent and demoted keys and every key of a LATER run are `not_reached` (each carries
    `plan_remaining`: those keys, and `earlier_check`), move `"stop"`, and the returned dict then also holds the later keys; keys
    still unsettled in this run's own run are the caller's to list. F: a group of 2 or more -> each absent or
    demoted key is `not_reached` with `rerun_alone: True` (the caller reruns it ALONE, once; its outcome is this same function over
    that run, with no further rerun); a run of one -> `_row_unsettled` (`interrupted` when the runner cut it), `rerun_alone: False`.

    Outcome: a `_row_answer` (`verdict`, `note`, `observed`, `cause`, `proved_by`) plus `check_key`, `read_in_joint`, `rerun_alone`,
    and, where it applies, `author_green`, `interrupted`, `demoted`. `move` is `"go on"` or `"stop"`."""
    keys = list(group or [])
    if not keys:
        return {}, "go on"
    entry, site = facts.get("entry") or {}, facts.get("site") or {}
    greens, argv = facts.get("author_green") or {}, facts.get("argv")
    by_key = {}
    for one in details or []:
        by_key.setdefault(one.get("key"), []).append(one)
    rank = {"failed": 0, "error": 1, "passed": 2}
    row = min((r for r in rows or [] if isinstance(r, dict)), key=lambda r: rank.get(_row_status(r), 3), default=None)
    status = _row_status(row) if row else None

    def detail_of(key: str) -> dict:
        one = dict((by_key.get(key) or [{"key": key}])[0], language=str(facts.get("language_label") or ""))
        one.setdefault("target_source", "the plan")      # the note of an unknown body names where the check came from
        return one

    def passed(key: str, whole: bool = False) -> dict:
        """`_row_passed` (or, `whole`, the full row judge) for one key with `facts["among"][key]` (E5, EP-O; fix round A, B2): the run cannot
        say WHICH body ran (the test's body is not located: two declarations of its name), so a pass is `incomplete`, `cause: tooling` - an
        unknown never becomes a verdict on the author (AR-28). Absent from `facts["among"]` = False (the caller did not ask)."""
        asked = bool((facts.get("among") or {}).get(key))
        answer = judge_probe_row(row or {}, site, entry, dict(detail_of(key), message_marker=""), among=asked, argv=argv) if whole else \
            _row_passed(row, entry, detail_of(key), observed_of(), among=asked, argv=argv)
        if asked and answer is not None and answer["verdict"] == "incomplete" and not answer.get("cause"):
            answer["cause"] = "tooling"
        return answer

    def observed_of() -> dict:
        problem = failure_problem(row or {})
        shown = (str(problem.get("message") or "").strip() or text_head(problem.get("text"), entry)).strip()
        out = {"status": status, "message_head": fold(shown.splitlines()[0] if shown else "", 300)}
        for field in ("frame", "location", "failure_kind", "site_unread"):
            if site.get(field):
                out[field] = site[field]
        return out

    def stamp(answer: dict, key: str, read: bool, rerun: bool = False, **more) -> dict:
        return _walk_stamp(answer, key, read_in_joint=read, rerun_alone=rerun, **more)      # the one stamp (F7)

    if status != "failed":
        out = {}
        for key in keys:
            if status == "passed" and any(one.get("probe_kind") == "find" for one in by_key.get(key, [])):
                answer = _row_answer(observed_of(), "incomplete",
                                     "the run passed with a `find` model standing: the read may not reach the check, and code cannot show "
                                     "it on every reader, so the check is not called dead (EP-H); the code critic judges it: " + JUDGE_DOOR,
                                     cause="judgment")
            elif status == "passed":
                answer = passed(key)
            else:
                answer = passed(key, whole=True)
            out[key] = stamp(answer, key, False)
        return out, "go on"

    marked = {}
    for key in keys:
        got = _row_by_marker(row, str(tokens.get(key) or ""), detail_of(key), entry, observed_of())
        if got is not None:
            marked[key] = got
    read = [key for key in keys if key in marked]
    absent = [key for key in keys if key not in marked]
    cut = _cut_by_runner(_problem_texts(row), entry)
    demoted = [read[-1]] if read and (absent or cut) else []             # C: the last read key in source order; a cut never proves
    stop = _earlier_check_at(str(site.get("location") or ""), plan or {}, {"keys": keys}, details or []) if absent else None
    out = {}
    for key in read:
        if key in demoted:
            continue
        kinds = [one.get("probe_kind") for one in by_key.get(key, [])]
        if kinds and all(kind == "invert" for kind in kinds):
            out[key] = stamp(marked[key], key, True)
        elif greens.get(key) is True:
            out[key] = stamp(marked[key], key, True, author_green=True)
        else:
            answer = _row_unsettled(observed_of())
            answer["note"] = ("the check's marker was read, but the author's run is not known to be green on these bytes (`author_green`): a "
                              "model's marker does not prove alone (F-P4); the code critic judges it: " + JUDGE_DOOR)
            out[key] = stamp(answer, key, True, author_green=greens.get(key))
    if stop:      # E (EP-G): the failure lies on an EARLIER check this run did not edit: a link is read only behind green earlier ones
        runs = (plan or {}).get("runs") or []
        mine = next((i for i, one in enumerate(runs) if keys[0] in (one.get("keys") or [])), len(runs))
        later = [key for one in runs[mine + 1:] for key in (one.get("keys") or []) if key not in keys]
        lost = [key for key in keys if key not in out]
        remaining = lost + later
        why = (f"the run failed on the span of the earlier check {stop}, which this run did not edit (a fact that orders the walk, never a "
               "proof): this check and the rest of the plan are not reached, and the code critic reads the failure: " + JUDGE_DOOR)
        for key in lost + later:
            answer = _row_answer(observed_of() if key in lost else {}, "not_reached", why)
            out[key] = stamp(answer, key, False, plan_remaining=list(remaining), earlier_check=stop, interrupted=cut)
        return {key: out[key] for key in keys + later}, "stop"
    for key in keys:
        if key in out:
            continue
        if len(keys) >= 2:
            answer = _row_answer(observed_of(), "not_reached",
                                 ("its marker was read but the runner cut the test, so the check may not have decided; " if key in demoted
                                  else "its marker is not in the failure text of this run; ")
                                 + "it is rerun alone, once (a joint run proves firing, never non-firing)")
            out[key] = stamp(answer, key, False, rerun=True, demoted=key in demoted, interrupted=cut)
        else:
            answer = _row_unsettled(observed_of())
            if key in demoted:
                answer["note"] = ("the check's marker was read, but the runner cut the test, so the check may not have decided and a cut never "
                                  "proves; the code critic judges it: " + JUDGE_DOOR)
            out[key] = stamp(answer, key, False, interrupted=cut, demoted=key in demoted)
    return {key: out[key] for key in keys}, "go on"


def _earlier_check_at(location: str, plan: dict, row: dict, edits: list):
    """The key of the EARLIER check of the plan the failing `location` lies on, or None (t-2064 P4a, EP-G; pure). Earlier = before
    `row`'s first key in the walk's order (`plan["runs"]` in order, each run's keys in order), a check this run did not edit
    (`edits` = the `plan_model` details of the run), and no edit of this run STANDS before it: a `find` may begin anywhere between the
    body's start and its statement, so any `find` of the run (and an edit on a line at or above the check, in its file) is read as
    possibly standing before it - then the walk goes on (a helper's throw, the check's own argument, no location, a stand hiccup all
    return None too). The location orders the walk; it is a fact, never a proof of anything. `row` is `{"keys": [...]}`; `location`
    is `<path>:<line>` as the row judge reads it, `""` for none."""
    runs = (plan or {}).get("runs") or []
    order = [key for one in runs for key in (one.get("keys") or [])]
    spots = [order.index(key) for key in (row or {}).get("keys") or [] if key in order]
    if not location or not spots:
        return None
    edited = {one.get("key") for one in edits or []}
    checks = {check.get("key"): check for check in (plan or {}).get("checks") or []}
    for key in order[:min(spots)]:
        check = checks.get(key)
        if check is None or key in edited or not _location_hits(location, {"file": ""}, check):
            continue
        for one in edits or []:
            if one.get("probe_kind") == "find" or (one.get("file") == check.get("file") and int(one.get("line") or 0) <= int(check["line"])):
                return None
        return key
    return None


_COLUMN = re.compile(r":(\d+):(\d+)\)?\s*$")


def _frames_of(text: str, entry) -> list:
    """The lines of `text` the entry's frame grammar reads as a stack frame and does not skip (a library or runner frame), in the
    order they stand (`reporters.frame_lines`, the walk the site reader takes its first frame from). A fact for the critic, never a
    proof; `[]` with no entry or no grammar. Bounded by the text, which the caller has cut at `FAILURE_TEXT_MAX`."""
    if not isinstance(entry, dict) or "frames" not in entry:
        return []
    frames, skip, _path = AD.grammar_of(entry)
    return reporters.frame_lines(text, frames, skip)      # the site reader's own walk and acceptance rule (F4)


def cut_text(text: str) -> str:
    """`text` as `judgment_facts` stores it: whole up to `FAILURE_TEXT_MAX` characters; a longer one keeps its HEAD and its TAIL around
    ONE `…` (half each; the mark counts, so the result is exactly `FAILURE_TEXT_MAX` long). INV: the tail survives - a runner's last
    line is the raising line (pytest's `E   ...` / `path:line: Exc`), and the head is the message; a middle of repeated frames is
    what is dropped. Pure; `""` for an empty text."""
    text = str(text or "")
    if len(text) <= FAILURE_TEXT_MAX:
        return text
    tail = (FAILURE_TEXT_MAX - 1) // 2
    return text[:FAILURE_TEXT_MAX - 1 - tail] + "…" + text[len(text) - tail:]


def _fact_row(row: dict) -> dict:
    """One unsettled row as `judgment_facts.rows` holds it: `{test_id, status, message, failure_text}`, the texts cut by `cut_text`."""
    problem = failure_problem(row)
    return {"test_id": row.get("test_id"), "status": _row_status(row), "message": cut_text(problem.get("message")),
            "failure_text": cut_text(problem.get("text"))}


def judgment_facts(record: dict, row: dict, site: dict, detail: dict, entry=None, rows=None) -> dict:
    """The facts a record `cause: judgment` hands to the code critic (t-1968 N2): pure, reads only its arguments. DATA only - what was
    mutated, where the run failed and the text it printed; no field says whether the broken check fired (that is the critic's
    word, AR-29). `column` is read from the frame line (`:<line>:<col>` at its end), else null. `failure_text` is cut by `cut_text`
    (head and tail around one `…`, the mark counts): a quote beyond the cut is refused by `judge_record` (E2.4).
    t-2064 N3b: `location_hit` is `_location_hits`' answer - whether the failing site lies inside the mutated statement (a FACT; the
    judge decides nothing by it) - and `frames` the stack frames of the cut text, read with the entry's grammar.

    t-2045 N4: `rows` is EVERY unsettled row of the run, `[{test_id, status, message, failure_text}]` (B7: a parametrised test shows
    each parameter, not the first), at most `FACTS_ROWS_MAX`, then `rows_cut` counts the rest (`rows_cut` is always written: 0 when nothing was cut) and
    `judge_record` refuses `fires` (a verdict on rows the critic could not read all of). `rows` is the caller's list of the rows
    whose answer was `cause: judgment` (`row` is the first of them, the one the flat keys describe: `proof_level` and
    `window_record` read those); None -> this row alone. `check_key`, `model` and `author_green` are NULL here: their producer is
    P4a (t-2064 par.11.3, the per-check walk); the keys exist now so the shape is written once. A text is never empty by itself:
    a row with no text is `cause: tooling` and carries no facts."""
    problem = failure_problem(row)
    text = cut_text(problem.get("text"))
    shown_rows = [row] if rows is None else list(rows)
    frame = str(site.get("frame") or "")
    found = _COLUMN.search(frame)
    return {"file": detail.get("file"), "line": detail.get("line"), "end_line": detail.get("end_line"),
            "statement_before": detail.get("statement_before"), "statement_after": detail.get("statement_after"),
            "statement_inverted": detail.get("statement_inverted"),      # the plain inversion, no marker: what the PERSON reads (F5)
            "frame": frame or None, "location": site.get("location") or None, "column": int(found.group(2)) if found else None,
            "location_hit": bool(detail.get("line") and detail.get("end_line")
                                 and _location_hits(str(site.get("location") or ""), {"file": ""}, detail)),
            "frames": _frames_of(text, entry),
            "status": _row_status(row), "message": str(problem.get("message") or ""), "failure_text": text,
            "message_marker": detail.get("message_marker") or "",
            "fires_as_pair": {"pair_id": detail.get("pair_id") or detail.get("pair"), "fires_as": detail.get("fires_as")},
            "evidence_ref": record.get("evidence_ref"),
            "rows": [_fact_row(r) for r in shown_rows[:FACTS_ROWS_MAX]], "rows_cut": max(0, len(shown_rows) - FACTS_ROWS_MAX),
            "check_key": None, "model": None, "author_green": None}      # the last three: P4a writes them (t-2064 par.11.3)


def facts_sha(facts: dict) -> str:
    """The sha256 of the canonical JSON of `judgment_facts`: what the critic's judgment says it was made on."""
    return sha256(json.dumps(facts, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


# --- restore -----------------------------------------------------------------------------------

def put_back(path: Path, data: bytes, sha: str, atime_ns, mtime_ns) -> dict:
    """Write the author's bytes into `path` and prove it: the ONE restore, used by the probe's own
    `finally` and by the recovery of a dead probe's copy, so the two cannot drift.

    mtime (E20): a `.py` gets the mtime it had, and its module's bytecode caches are dropped so no
    rewritten bytecode of the mutated source outlives it; any other file gets "now" - an
    incremental build (MSBuild, Maven) that saw the old mtime on a file whose build output was made
    from the MUTATED bytes would call that output up to date, and the author's next ordinary run
    would then execute the mutation."""
    result = {"verified": False}
    try:
        path.write_bytes(data)
        if path.suffix == ".py" and mtime_ns is not None:
            os.utime(path, ns=(mtime_ns if atime_ns is None else atime_ns, mtime_ns))
        else:
            os.utime(path, None)
        result["verified"] = sha256(path.read_bytes()) == sha
        if path.suffix == ".py":
            dropped = []
            for cached in sorted_paths((path.parent / "__pycache__").glob(path.stem + ".*.pyc")):
                try:
                    cached.unlink()
                    dropped.append(cached.name)
                except OSError:
                    pass
            result["bytecode_dropped"] = dropped
    except OSError as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def restore(path: Path, original: bytes, original_sha: str, stat, copy=None) -> dict:
    """Put the author's bytes back FROM THE COPY ON DISK when there is one, and prove it by sha256.

    The copy is the bytes a killed probe could still be put back from; `original` (the same bytes in
    this process's memory) is only the way back when the copy cannot be read or no longer matches the
    sha256 it was made with (writing a damaged copy over the author's file would lose what the probe
    still holds), and the result says which one it used (`restored_from`) - a restore that silently
    used memory would make the copy decoration."""
    data, source, why = original, "memory", ""
    if copy is not None:
        try:
            data, source = Path(copy).read_bytes(), "copy"
            if sha256(data) != original_sha:
                data, source, why = original, "memory", "the copy's sha256 differs from the original's"
        except OSError as exc:
            why = f"{type(exc).__name__}: {exc}"
    result = put_back(path, data, original_sha, stat.st_atime_ns, stat.st_mtime_ns)
    result["sha256"] = original_sha
    if copy is not None:
        result["restored_from"] = source
        if why:
            result["copy_unreadable"] = why
    return result


# --- the durable copy, the lock and the recovery (R9) ----------------------------------------------
# The shape of the failure: the probe holds the author's original bytes in memory, mutates the file,
# and runs for up to RUN_TIMEOUT_S (31 minutes). A role's shell call is killed long before that, and a
# killed process never reaches its `finally`: the author's file stayed mutated and the only copy of the
# original died with the process. So the bytes go to disk BEFORE the mutation, keyed per file (a
# `conftest.py` exists in many folders, so a name is no key), under one lock per file that process
# death releases, and the next probe restores what a dead one left BEFORE it reads a single byte as
# "the author's".

COPY_DIR = "probe-copies"
FALLBACK_GRACE_S = 120
META_FIELDS = ("path", "original_sha", "mutated_sha", "original_mtime_ns", "started_at", "timeout_s",
               "statement_before", "statement_after", "line")
_KEY = re.compile(r"^[0-9a-f]{16}$")


def copy_dir(root: Path) -> Path:
    """The project's `state/probe-copies/`: one folder for every story, because a probe killed in
    story A must be visible to the probe of story B. Resolved through `runtime_paths` (FR-37), never
    spelled by hand."""
    return runtime_paths.state_file(root, COPY_DIR)


def copy_key(path: Path, root: Path) -> tuple:
    """(key, project-relative POSIX path): the key is the first 16 hex of sha256 of that path, case-
    folded on Windows where `Tests/A.py` and `tests/a.py` are one file."""
    shown = _rel_project(Path(path), Path(root))
    folded = shown.casefold() if os.name == "nt" else shown
    return sha256(folded.encode("utf-8"))[:16], shown


def copy_files(directory: Path, key: str) -> tuple:
    """(`<k>.orig`, `<k>.meta`). `.meta` is JSON content under a name that is deliberately not
    `.json`: the story folders' json scans (exit_gate, finalize_task, handoff_check, probe_debt) must
    not read it as one of theirs."""
    return directory / f"{key}.orig", directory / f"{key}.meta"


# The module-level SEAM of the lock call: the helper's one primitive, looked up by `try_lock` at call time so a
# test that injects `PBC._os_lock` (a one-argument callable that raises OSError / ImportError) keeps working.
_os_lock = os_try_lock


def try_lock(directory: Path, key: str) -> tuple:
    """("locked", handle) | ("held", None) | ("broken", None); the handle is the helper's `FileLock`.

    "held" is ONLY the helper's `LockBusy` (an OSError whose errno says the lock is taken, `HELD_ERRNOS`);
    any other errno, an ImportError, or a lock file that cannot be made is `LockBroken`: the PRIMITIVE
    failed ("broken"), and only then does the fallback deadline apply (a lock reported as broken when it
    was merely held would let a second probe take a live probe's mutated bytes for the original). The
    lock file is only ever opened, never deleted or truncated (event_store.take_file_lock)."""
    try:
        held = take_file_lock(directory / f"{key}.lock", 0, purpose="probe copy", record_holder=True,
                              lock_call=lambda fd: _os_lock(fd))
    except LockBusy:
        return "held", None
    except LockBroken:
        return "broken", None
    return "locked", held


def release_locks(locks: list) -> None:
    while locks:
        locks.pop().release()


def read_meta(meta_path: Path) -> tuple:
    """(meta dict, "") or (None, why). Never raises: a copy record that cannot be read is a state to
    report, not a crash (P1)."""
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"its record {meta_path.name} cannot be read ({type(exc).__name__})"
    if not isinstance(data, dict):
        return None, f"its record {meta_path.name} is not a JSON object"
    missing = [k for k in META_FIELDS if k not in data]
    if missing:
        return None, f"its record {meta_path.name} lacks {', '.join(missing)}"
    return data, ""


def copy_deadline(meta) -> "datetime | None":
    """`started_at + timeout_s + FALLBACK_GRACE_S`: when a probe that holds no OS lock must be dead."""
    try:
        started = datetime.fromisoformat(str(meta["started_at"]))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return started + timedelta(seconds=float(meta["timeout_s"]) + FALLBACK_GRACE_S)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _meta_target(root: Path, meta: dict) -> Path:
    path = Path(str(meta["path"]))
    return path if path.is_absolute() else Path(root) / path


def _door(shown: str) -> str:
    return f"probe_by_code.py --release-copy {shown}"


def _unresolved_text(shown: str, why: str, meta, current_sha, orig: Path) -> str:
    """What a copy that cannot be applied says (E19): the file, the shas, the copy, the line, the
    door. The addressee is the test's AUTHOR through a tooling finding - the critic never edits test
    code (FR-2) - and the author's newer edit always wins."""
    parts = [f"a probe that was killed left a byte copy of {shown} ({orig}) that cannot be applied: {why}."]
    if meta:
        parts.append(f"The file holds sha256 {current_sha or 'unreadable'}; the probe's mutated version was "
                     f"{meta['mutated_sha']}, the original {meta['original_sha']}.")
        parts.append(f"If line {meta['line']} still reads `{meta['statement_after']}`, the probe's mutation is "
                     f"still in the file: put back `{meta['statement_before']}`, or copy {orig} over the file "
                     "if nothing else changed there.")
    parts.append(f"Once that is settled, `{_door(shown)}` drops the copy. Nothing was overwritten.")
    return " ".join(parts)


def settle(root: Path, key: str, *, fallback_deadline_needed: bool = False, shown_hint: str = "") -> tuple:
    """Deal with the copy of a probe that is NOT running. -> (state, text), state one of `none` (no
    copy), `dropped` (the file already holds the original: only the copy goes), `recovered` (the file
    held the mutated bytes and the original is back, verified; `text` is the note) or `unresolved`
    (`text` says why; nothing was overwritten).

    Anything the copy does not explain - the author edited the file after the crash, deleted it, or
    the copy itself no longer matches its own sha - is left alone: the author's newer edit wins and
    the way out is `--release-copy` (FR-57)."""
    directory = copy_dir(root)
    orig, meta_path = copy_files(directory, key)
    if not meta_path.is_file():
        return "none", ""  # an orphan `.orig`: the probe died before its record, and nothing was mutated yet
    meta, why = read_meta(meta_path)
    if meta is None:
        # The record is unreadable, so the file it was about is unknown unless the caller knows it (its
        # own test or oracle): the door then takes the 16-hex key, which is the copy's own name.
        return "unresolved", _unresolved_text(shown_hint or key, why, None, None, orig)
    shown = str(meta["path"])
    if fallback_deadline_needed and copy_deadline(meta) is None:
        return "unresolved", _unresolved_text(shown, "the OS lock cannot say whether that probe is alive and its "
                                              "record has no readable started_at / timeout_s", meta, None, orig)
    target = _meta_target(root, meta)
    try:
        current = target.read_bytes()
    except OSError as exc:
        return "unresolved", _unresolved_text(shown, f"the file cannot be read now ({type(exc).__name__})",
                                              meta, None, orig)
    current_sha = sha256(current)
    if current_sha == meta["original_sha"]:
        for stale in (meta_path, orig):
            stale.unlink(missing_ok=True)
        return "dropped", ""
    if current_sha != meta["mutated_sha"]:
        return "unresolved", _unresolved_text(shown, "the file was changed after the probe's mutation (its "
                                              "sha256 is neither the mutated nor the original one)",
                                              meta, current_sha, orig)
    try:
        data = orig.read_bytes()
    except OSError as exc:
        return "unresolved", _unresolved_text(shown, f"the copy cannot be read ({type(exc).__name__})",
                                              meta, current_sha, orig)
    if sha256(data) != meta["original_sha"]:
        return "unresolved", _unresolved_text(shown, "the copy's own bytes no longer match the sha256 its record "
                                              "gives, so it is not written over the file", meta, current_sha, orig)
    mtime = meta.get("original_mtime_ns")
    done = put_back(target, data, meta["original_sha"], None, mtime if isinstance(mtime, int) else None)
    if not done["verified"]:
        return "unresolved", _unresolved_text(shown, "the recovery was written but could not be verified"
                                              + (f" ({done['error']})" if done.get("error") else ""),
                                              meta, current_sha, orig)
    for stale in (meta_path, orig):
        stale.unlink(missing_ok=True)
    return "recovered", (f"recovered {shown}: a probe that was killed before it restored left line {meta['line']} "
                         f"reading `{meta['statement_after']}`; its byte copy put the author's bytes back "
                         f"(sha256 {meta['original_sha']}, verified) and was deleted")


def claim_key(root: Path, key: str, shown: str, *, own: bool, notes: list, now=None):
    """Take the lock of one file, settling the copy a dead probe left there first. -> the lock handle
    (None when the primitive failed: the fallback deadline then stands in for it).

    `own` = this probe's own test or oracle: a probe running there, or a copy that cannot be applied,
    is a refusal (exit 2, nothing changed). For any OTHER file it is a note and the probe goes on - a
    stale copy of file X left in story A must not stop story B's probe of file Y (P1: code reports,
    it does not stop the factory)."""
    now = now or datetime.now(timezone.utc)
    directory = copy_dir(root)
    meta_path = copy_files(directory, key)[1]
    state, handle = try_lock(directory, key)

    def blocked(until):
        if handle is not None:
            release_locks([handle])
        if not own:
            return None
        raise Refusal(f"probe_by_code: a probe of {shown} is running"
                      + (f" until {until.isoformat(timespec='seconds')}" if until else "")
                      + " - it holds the copy of that file, and the lock ends with the probe (a killed one "
                        "releases it). Probe again when it has ended. Nothing was changed.")

    if state == "held":
        return blocked(None)
    broken = state == "broken"
    if broken and meta_path.is_file():
        meta, _why = read_meta(meta_path)
        until = copy_deadline(meta) if meta else None
        if until is not None and until >= now:
            return blocked(until)
    try:
        outcome, text = settle(root, key, fallback_deadline_needed=broken, shown_hint=shown if own else "")
    except Exception as exc:  # the copy is examined, never trusted to be well formed
        outcome, text = "unresolved", _unresolved_text(
            shown, f"it could not be examined ({type(exc).__name__}: {str(exc)[:160]})", None, None,
            copy_files(directory, key)[0])
    if outcome == "unresolved" and own:
        if handle is not None:
            release_locks([handle])
        raise Refusal("probe_by_code: " + text + " This is a tooling finding to return to the test's author, "
                      "not an edit for the critic to make. Nothing was changed.")
    if outcome in ("recovered", "unresolved"):
        notes.append(text)
    if not own and handle is not None:
        release_locks([handle])
        return None
    return handle


def scan_copies(root: Path, *, skip_keys, notes: list, now=None) -> None:
    """R9 step 1: every copy in the folder whose probe is not running is settled - the OTHER files'
    first; this probe's own file goes through `claim_key`. Reads no byte of any project file that
    does not have a copy; makes nothing when there is no folder."""
    directory = copy_dir(root)
    if not directory.is_dir():
        return
    for meta_path in sorted_paths(directory.glob("*.meta")):
        key = meta_path.stem
        if key in skip_keys or not _KEY.match(key):
            continue
        claim_key(root, key, key, own=False, notes=notes, now=now)


def begin_copy(root: Path, path: Path, original: bytes, original_sha: str, stat, mutated_sha: str,
               detail: dict, timeout: int) -> dict:
    """R9 write order 1-2: `.orig`, then `.meta`, then the copy read back and its sha checked. The file
    is NOT mutated yet, so a copy that cannot be written and verified is a refusal with nothing
    changed (invariant: never a mutation without a verified copy on disk)."""
    key, shown = copy_key(path, root)
    directory = copy_dir(root)
    orig, meta = copy_files(directory, key)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        orig.write_bytes(original)  # `.orig` first: a record always has its copy behind it
        atomic_json(meta, {
            "path": shown, "original_sha": original_sha, "mutated_sha": mutated_sha,
            "original_mtime_ns": stat.st_mtime_ns,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "timeout_s": timeout,
            "statement_before": detail.get("statement_before"), "statement_after": detail.get("statement_after"),
            "line": detail.get("line")})
        if sha256(orig.read_bytes()) != original_sha:
            raise OSError("the copy read back does not match the original's sha256")
    except OSError as exc:
        for stale in (meta, orig):
            try:
                stale.unlink(missing_ok=True)
            except OSError:  # the folder is a file or unwritable: `missing_ok` swallows only ENOENT, and Linux
                pass  # answers ENOTDIR under a file (Windows: ENOENT); nothing of ours is there to remove
        raise Refusal(f"probe_by_code: the byte copy of {shown} could not be written and verified under {directory} "
                      f"({type(exc).__name__}: {exc}) - the file is not mutated without one. Fix the folder "
                      "(space, permissions) and probe again. Nothing was changed.") from exc
    return {"orig": orig, "meta": meta, "key": key, "path": shown}


def finish_copy(copy: dict, result: dict, root: Path) -> None:
    """R9 write order 6-7: the copy goes only after the restore is VERIFIED; otherwise both files stay
    (the recovery and the stderr line need them)."""
    result["copy"] = _rel_project(copy["orig"], root)
    if result.get("verified"):
        for stale in (copy["meta"], copy["orig"]):
            stale.unlink(missing_ok=True)
        result["copy_kept"] = False
    else:
        result["copy_kept"] = True


def release_copy(root: Path, file: str, now=None) -> dict:
    """`--release-copy <file>`: take the file's lock, print the copy's record, delete `.orig` and
    `.meta`. Nothing else runs. A held lock (a probe running there) refuses - the author's edit is the
    reason for a release, never a probe's live copy."""
    now = now or datetime.now(timezone.utc)
    if _KEY.match(str(file)):  # a copy whose record is unreadable names no file: its own name is the door
        key, shown = str(file), str(file)
    else:
        target = Path(file)
        target = target if target.is_absolute() else Path(root) / target
        key, shown = copy_key(target, root)
    directory = copy_dir(root)
    orig, meta_path = copy_files(directory, key)
    if not (orig.exists() or meta_path.exists()):
        return {"status": "no_copy", "file": shown,
                "message": f"no byte copy of {shown} is held under {directory}: nothing to release"}
    state, handle = try_lock(directory, key)
    try:
        meta, why = read_meta(meta_path) if meta_path.exists() else (None, "it has no record file")
        until = copy_deadline(meta) if meta else None
        if state == "held" or (state == "broken" and until is not None and until >= now):
            raise Refusal(f"probe_by_code: a probe of {shown} is running"
                          + (f" until {until.isoformat(timespec='seconds')}" if until else "")
                          + " - its copy is not released while it runs. Release it again once that probe has "
                            "ended (a killed probe frees the lock). Nothing was changed.")
        for stale in (meta_path, orig):
            stale.unlink(missing_ok=True)
    finally:
        release_locks([handle] if handle is not None else [])
    return {"status": "released", "file": shown, "copy": _rel_project(orig, root),
            "record": meta if meta else {"unreadable": why}}


# --- binding to the author's bytes -----------------------------------------------------------

def _rel_root(path: Path, root: Path, run_cwd: Path) -> str:
    """The mutated file as the report will name it: relative to the run directory when it
    lies under it, else to the project root."""
    for base in (run_cwd, root):
        try:
            return path.resolve().relative_to(base.resolve()).as_posix()
        except ValueError:
            continue
    return path.as_posix()


def _rel_project(path: Path, root: Path) -> str:
    """The mutated file relative to the project root, POSIX - the one spelling `already_probed`
    resolves it from later, whatever directory the run itself was made in."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _rel_task(path: str, root: Path, task_root: Path) -> str:
    candidate = Path(path)
    candidate = candidate if candidate.is_absolute() else root / candidate
    try:
        return candidate.resolve().relative_to(task_root.resolve()).as_posix()
    except ValueError:
        return str(path).replace("\\", "/")


def original_input_hash(request: dict, mutated_path: Path, mutated_sha: str, original_sha: str) -> str:
    """`test_content_sha` as `execution_fingerprint.build` computes it — the same records in
    the same order, with this file's mutated sha replaced by the author's."""
    records = request.get("fingerprint_files") or []
    groups = {}
    for record in records:
        if not isinstance(record, dict) or record.get("kind") not in ("test_files", "helper_files"):
            continue
        row = dict(record)
        if row.get("sha256") == mutated_sha and Path(str(row.get("path"))).resolve() == mutated_path.resolve():
            row["sha256"] = original_sha
        groups.setdefault(record["kind"], []).append(row)
    ordered = (sorted(groups.get("test_files", []), key=lambda x: x["path"])
               + sorted(groups.get("helper_files", []), key=lambda x: x["path"]))
    return content_hash(ordered) if ordered else original_sha


def _helper_chain(path: Path, run_cwd: Path) -> list:
    """The conftest chain of a test file, nearest first, up to the run directory: where `find_oracle`
    looks for a helper or fixture that asserts. It is NOT the test's identity: that list is the run's
    own (the other test files and the helpers earlier runs declared), and the identity is measured
    by `proof_level.instance_identity`, from the author's request."""
    helpers, directory = [], path.resolve().parent
    while directory == run_cwd or directory.is_relative_to(run_cwd):
        candidate = directory / "conftest.py"
        if candidate.is_file():
            helpers.append(str(candidate))
        if directory == run_cwd:
            break
        directory = directory.parent
    return helpers


def author_binding(task_root: Path, instance_id: str, function_sha: str) -> dict | None:
    """The latest author run block whose row for this instance ran exactly this function
    (`instance_content_sha` equal): its `test_content_sha` is the hash the window carries.
    An empty sha binds nothing: two unmeasured tests are not "the same function".

    "Latest" is the story's ONE block order (`run_history.read_run_blocks`: the block's own clock, a
    reparse right after the block it supersedes), not file-name order, which puts a reparse of an
    attempt whose id starts with a low digit before every `2026...` block (t-149, F-order)."""
    if not function_sha:
        return None
    import run_history
    blocks, _unreadable = run_history.read_run_blocks(task_root)
    for item in reversed(blocks):
        block = item["data"]
        for row in block.get("results") or []:
            if (isinstance(row, dict) and row.get("instance_id") == instance_id
                    and row.get("instance_content_sha") == function_sha
                    and (row.get("source_fingerprint") or {}).get("test_content_sha")):
                return {"run_block": "work/run-blocks/" + item["name"],
                        "test_content_sha": row["source_fingerprint"]["test_content_sha"],
                        "dispatch_id": block.get("dispatch_id"), "status": row.get("status")}
    return None


def author_green_of(task_root: Path, iid: str, identity: str, fingerprint: str) -> bool | None:
    """Was the author's own run of instance `iid` green on THESE bytes? `True` / `False` / `None` (unknown). t-2064 P4a, F-P4: the
    marker of a value model proves only with `True`. `identity` is the function's `instance_content_sha` (what `author_binding` keys
    on); `fingerprint` is `test_content_sha` over the author's bytes (`original_input_hash`'s value for the run's request).

    In this order: (1) `author_binding`, read exactly as `_run_alternative` reads it (a block row of this function: its status is
    the answer); (2) when that binds nothing (an empty `instance_content_sha`, arm B's TS record): the LATEST row of `iid` in a run
    block whose `source_fingerprint.test_content_sha` equals `fingerprint` - its status `passed` is `True`, any other status
    `False`. A fact turned into a proof's condition ERRS TO `None`: an empty `fingerprint` or `iid`, no row of this instance and
    fingerprint (another instance, a helper or a test file changed since: the fingerprint differs), a row of a reparse block, no
    run block at all, and a run-block file that cannot be read (it may hold the newer row) are all `None`, never a default `True`."""
    bound = author_binding(Path(task_root), iid, identity)
    if bound is not None:
        return bound.get("status") == "passed"
    if not iid or not isinstance(fingerprint, str) or not fingerprint:
        return None
    import run_history
    blocks, unreadable = run_history.read_run_blocks(Path(task_root))
    if unreadable:
        return None
    for item in reversed(blocks):
        results = item["data"].get("results")
        for row in reversed(results if isinstance(results, list) else []):
            fp = row.get("source_fingerprint") if isinstance(row, dict) else None
            if (isinstance(fp, dict) and row.get("instance_id") == iid and fp.get("test_content_sha") == fingerprint):
                return None if item.get("depth") else row.get("status") == "passed"
    return None


# --- main ----------------------------------------------------------------------------------------

WINDOW_PROBE_FIELDS = ("verdict", "input_hash", "expected_location", "actual_location", "expected_reason",
                       "actual_reason", "failure_kind", "mutation_kind", "proof_level", "obligation_ids",
                       "obligation_hash", "defect_location", "assertion_id", "target", "proved_by", "evidence_ref")


def window_probe(record: dict) -> dict:
    """The `probe` object of the window instance, exactly as `acceptance.validate_window`
    reads it — the critic copies this, never retypes it."""
    return {key: record.get(key) for key in WINDOW_PROBE_FIELDS}


def record_path(task_root: Path, instance_id: str) -> Path:
    """The probe's own record. The naming lives in `proof_level.probe_record_path`, where
    `already_probed` (which reads it back) and `red_sandbox.py` (which writes the product record beside
    it) find it too: one naming, three users."""
    return proof_level.probe_record_path(task_root, instance_id)


# --- the live receipt ----------------------------------------------------------------------------

RECEIPT_DIR = "work/sensitivity-receipts"
FACT_KEYS = ("case_version", "test_content_hash", "source_revision", "build_id")


def _receipt_core(record: dict, iid: str, facts: dict, restoration: str) -> dict:
    """Everything a live receipt says except the run evidence and its own hash."""
    core = {
        "instance_id": iid, **{key: facts[key] for key in FACT_KEYS},
        "mutation": record["mutation"], "expected_assertion_failure": record["expected_reason"],
        "actual_failure": record["actual_reason"], "assertion_location": record["expected_location"],
        "restoration_evidence": restoration, "failure_kind": record["failure_kind"],
        "proof_level": proof_level.LIVE, "probe_tool": "probe_by_code.py",
        "mutation_kind": MUTATION_KIND, "probe_record": record["record"],
        "obligation_ids": list(record.get("obligation_ids") or []),
        "obligation_hash": record.get("obligation_hash"),
        "defect_location": record.get("defect_location"), "assertion_id": record.get("assertion_id"),
        "immutable": True}
    if record.get("obligation_refs"):
        core["obligation_refs"] = record["obligation_refs"]
    if isinstance(record.get("checks"), list) and record["checks"]:
        # t-2064 P4b item 4: a receipt of a walk names what it stands on, per check: the statement, the model entry's sha (`_entry_sha`,
        # the one the per-check record carries as `entry_sha`) and the verdict. A reader that holds another entry set for the same checks
        # compares `checks[].entry_sha` and finds this receipt is not for it (a changed model never reads an old receipt as live).
        core["checks"] = [{"key": row.get("key"), "statement_sha": row.get("statement_sha"),
                           "entry_sha": _entry_sha(row["entry"]) if isinstance(row.get("entry"), dict) else "", "verdict": row.get("verdict")}
                          for row in record["checks"] if isinstance(row, dict)]
    if isinstance(record.get("target"), dict):
        # which statement was mutated, and whether it is the obligation's check (`target_fact`); a probe of
        # another line never proves the obligation (`proof_level.receipt_off_target`, the one reader)
        core["target"] = record["target"]
    if record.get("proved_by") and record.get("verdict") == "intended_failure":
        core["proved_by"] = record["proved_by"]     # t-1968 N1: `marker` | `critic` (a stored `fires_as` from an older package still reads, t-2064 Q5); the window block carries it (window_record)
        judgment = record.get("judgment")
        if record["proved_by"] == "critic" and isinstance(judgment, dict) and judgment.get("quote"):
            core["judgment_quote"] = judgment["quote"]      # t-1968 N2: the line of the stored text the critic quoted as the firing
    if record.get("test_code_sha"):
        # What can execute in the measured bytes (diff_scope.executable_sha): the receipt still
        # counts after a comment-only edit of its test. Absent for bytes that are not UTF-8 - then
        # only raw equality holds (D-0017, the safe direction).
        core["test_code_sha"] = record["test_code_sha"]
    if record.get("mutated_file"):
        # What this probe mutated travels with the receipt, not only with the record that the next probe
        # overwrites: a repeat is answered by the receipt only while that file still holds these bytes.
        core["mutated_file"] = record["mutated_file"]
    if record.get("instance_identity"):
        # The per-test identity measured BEFORE the mutation, over the same bytes as the raw sha above
        # (the receipt is written only when that raw sha equals what the manifest binds): a neighbour's
        # edit, or a comment, keeps this receipt (D5). Absent when the test had no measurable identity.
        core["instance_identity"] = record["instance_identity"]
    return core


def _hash_of(receipt: dict) -> str:
    """The receipt's identity: everything but itself and the run evidence. The evidence (a job
    summary, a junit file with its timings) differs on EVERY run, so a hash that covered it would
    make a rerun on the same bytes a new receipt each time; what the receipt proves is the same."""
    return content_hash({k: v for k, v in receipt.items() if k not in ("receipt_hash", "evidence_refs")})


def write_receipt(task_root: Path, receipt: dict, instance_id: str) -> tuple:
    """(`{path, sha256}` or None, note). The receipt is IMMUTABLE: written once, never over
    another. Same facts again -> the file already there (same path, same bytes); a different file
    under this very name -> nothing is overwritten and the note says so."""
    receipt = dict(receipt)
    receipt["receipt_hash"] = _hash_of(receipt)
    directory = Path(task_root) / RECEIPT_DIR
    path = directory / f"{C.instance_file_stem(instance_id)}-live-{receipt['receipt_hash'][:16]}.json"
    rel = path.relative_to(task_root).as_posix()
    try:
        if path.exists():
            try:
                found = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                found = None
            if not (isinstance(found, dict) and found.get("receipt_hash") == receipt["receipt_hash"]
                    and _hash_of(found) == receipt["receipt_hash"]):
                return None, (f"{rel} already exists with different content; an immutable receipt is "
                              "never overwritten, so no live receipt was written")
            return {"path": rel, "sha256": sha256(path.read_bytes())}, f"{rel} already holds this proof"
        # `atomic_json` names its scratch file `<name>.<32 hex>.tmp`, 37 characters on top of a
        # name that is already 156 for the longest stem `contract.instance_file_stem` allows: on a
        # Windows path limited to 260 that one file failed for a long id while the receipt itself
        # would have fitted. The scratch file here has a short name of its own; the receipt is put
        # in place by one rename, so nobody ever reads it half written.
        directory.mkdir(parents=True, exist_ok=True)
        scratch = directory / (uuid.uuid4().hex[:8] + ".tmp")
        try:
            scratch.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(scratch, path)
        finally:
            scratch.unlink(missing_ok=True)
        return {"path": rel, "sha256": sha256(path.read_bytes())}, ""
    except OSError as exc:
        return None, f"the live receipt could not be written ({type(exc).__name__}: {exc})"


def attach_receipt(record: dict, entry: dict, task_root: Path) -> None:
    """Write the live receipt of an `intended_failure` whose restore was verified, and say in the
    record what happened — the receipt, or every fact that was missing for it."""
    record["receipt"], record["receipt_missing"] = None, []
    iid = C.test_instance_id(entry) or record["instance_id"]
    try:
        facts = proof_level.binding_facts(task_root, iid)
    except Exception as exc:  # the record says why there is no receipt; it never crashes the probe
        facts = {}
        record["notes"].append(f"no live receipt: the binding facts could not be read "
                               f"({type(exc).__name__}: {exc})")
    missing = [key for key in FACT_KEYS if not facts.get(key)]
    # The receipt claims the bytes the manifest binds; this probe MEASURED the test file it ran,
    # before mutating anything (`test_file_sha256`, the raw sha256 of the file). A claim nobody
    # compared with the measurement makes the window's byte check circular (the window reads the
    # hash from the receipt), so a receipt is written only when the two agree. Both sides are the
    # raw file hash: `input_hash` is the run's fingerprint over the test AND helper files, a
    # different quantity, and comparing it refused every row of TP1-13797 (driver3) whose
    # binding was right (critic t-035). The door: the manifest's trace_binding is stale.
    measured = str(record.get("test_file_sha256") or "")
    stale = bool(facts.get("test_content_hash")) and bool(measured) and measured != facts["test_content_hash"]
    if stale:
        missing.append("test_content_hash")
        record["notes"].append(
            f"no live receipt: the test file this probe measured (sha256 {measured}) is not the bytes the "
            f"manifest binds (trace_binding.test_content_sha {facts['test_content_hash']}) - the "
            "manifest's trace_binding is stale. It is the author's to rebind, through `manifest_put.py` "
            "(no run needed): trace_binding.test_content_sha is the sha256 of the file's bytes, as "
            "manifest_from_tests.py writes it - never a run block's source_fingerprint.test_content_sha, "
            "which is a fingerprint over several files; then the critic probes again")
        record["receipt_missing"] = missing
        return
    if missing:
        record["receipt_missing"] = missing
        record["notes"].append(
            "no live receipt: the manifest and run blocks carry no " + ", ".join(missing)
            + " for this instance — the author's record, not yours to type: the case version and "
              "test bytes belong in the instance's tests[] row (case_version_links, "
              "trace_binding.test_content_sha), the source and build identity in the run block "
              "that executed it")
        return
    shown = (record.get("mutation_detail") or {}).get("file") or record["test_node"].split("::")[0]
    restoration = f"probe_by_code: {shown} sha256 {record['restore']['sha256']} verified restored"
    receipt = _receipt_core(record, iid, facts, restoration)
    receipt["evidence_refs"] = list(record.get("evidence_refs") or [])
    ref, note = write_receipt(task_root, receipt, iid)
    if note:
        record["notes"].append(note)
    record["receipt"] = ref


def _run_evidence(summary: dict, root: Path, task_root: Path) -> list:
    """The run evidence of one run's summary: `[{path (task-relative), sha256}]` for the summary file and the report file that exist
    on disk, in that order, each once. The ONE derivation (AR-15): `_judge_run` (the single probe) and the walk both call it. A path
    that is not a file is left out, never invented. Reads files; writes nothing."""
    evidence: list = []
    for candidate in (summary.get("summary_path"), (summary.get("report_evidence") or {}).get("path")):
        if not candidate:
            continue
        for base in (root, task_root):
            file = (base / str(candidate))
            if file.is_file():
                rel = _rel_task(str(file), root, task_root)
                if rel not in [e["path"] for e in evidence]:
                    evidence.append({"path": rel, "sha256": sha256(file.read_bytes())})
                break
    return evidence


def _judge_run(root: Path, task_root: Path, record: dict, summary: dict, spec: dict, detail: dict, request: dict,
               oracle_path: Path, keys: list, *, judge_row: Callable = None) -> None:
    """What the run's summary and its report say, written into the record: the evidence, then the verdict
    (every language: the R8 table over the bound row and the entry's frame grammar, `_judge_rows`). The alternative probe injects its
    own row judge (`judge_row`, TQ1-25, until P5 merges the two probes): that branch reads the non-raw rows, unchanged."""
    notes = record["notes"]
    record["run"] = {k: summary.get(k) for k in ("label", "exit_code", "execution_status",
                                                 "error_head", "stand_signal") if k in summary}
    evidence = _run_evidence(summary, root, task_root)
    record["evidence_refs"] = evidence
    record["evidence_ref"] = evidence[0]["path"] if evidence else None
    report = (summary.get("report_evidence") or {}).get("path")
    # The run says which reporter wrote the report; a summary that names none is
    # what every summary was before it did, and was always read as JUnit.
    reporter = str(summary.get("reporter") or "").strip() or DEFAULT_REPORTER
    rows = []
    report_read = False     # a report that was read: only then is "no row of it is this test" a fact about the tool, not the stand
    if report and (task_root / report).is_file():
        try:
            rows = report_rows(task_root / report, reporter, raw=judge_row is None)
            report_read = True
        except ET.ParseError as exc:
            notes.append(f"the report is not valid XML: {exc}")
        except ValueError as exc:  # a reporter the reader does not know: no rows, said why
            notes.append(f"the run's report was not read (its summary names the reporter): {exc}")
    else:
        notes.append("no report evidence: " + str(summary.get("error_head") or
                                                   summary.get("no_junitxml") or
                                                   summary.get("execution_status") or "unknown cause"))
    if judge_row is None:
        _judge_rows(root, record, rows, reporter, spec, detail, request, oracle_path, keys, report_read)
        return
    matches = matching_rows(rows, spec["node"])
    if len(matches) == 1:
        judge_row(record, matches[0], spec, detail)
        if _tail(matches[0]["test_id"]) != _tail(spec["node"]):
            record["matched_report_id"] = matches[0]["test_id"]
    elif matches:
        _judge_param_rows(record, matches, spec, detail, judge_row=judge_row)
    elif rows:
        notes.append(f"no report row is named {_tail(spec['node'])!r}; the report held {held_ids(rows)}")


# Which verdict speaks for a node whose several parametrised rows disagree: the one that says the most
# about a test that did NOT kill the mutation. A mutated assert that never fired outranks a failure at the
# wrong place, and BOTH are judged verdicts that outrank a row that did not run: `not_executed` as the
# headline would let `keep_standing_record` keep an old `intended_failure` over a row that was judged and
# survived (B1, t-1482).
_SURVIVOR_ORDER = ("no_failure", "wrong_location", "not_executed")


def _judge_param_rows(record: dict, rows: list, spec: dict, detail: dict, *, judge_row: Callable) -> None:
    """Several rows `func[p1]`, `func[p2]` stand for one requested node: every row is judged by `judge_row` (required: the road's
    own judge is `judge_probe_row` through `_judge_rows`; this is the injected judge's branch), the verdict is
    `intended_failure` only if EVERY row is, otherwise the surviving rows are named in the record and in a
    note (a row never picked silently: the mutated assert must fire for each parameter)."""
    judged = []
    for row in rows:
        probe: dict = {}
        judge_row(probe, row, spec, detail)
        judged.append((row, probe))
    _worst_of_rows(judged, spec, record)


def _worst_of_rows(judged: list, spec: dict, record: dict) -> dict:
    """The ONE aggregator of several judged report rows of one requested test (AR-15; a parametrised Python node and a
    templated or looped test of another language both come here). `judged` is [(report row, its judged fields)], never empty
    (a caller with no row has nothing to judge and says so before it comes here). The verdict is `intended_failure` only if
    EVERY row is; otherwise the survivors are named in `param_rows` and in a note, and the survivor that says the most speaks
    (`_SURVIVOR_ORDER`). The error is allowed only toward NOT `intended_failure` (a row never picked silently: the mutated
    assert must fire for each). Returns the fields that were copied into the record."""
    survivors = [(row, probe) for row, probe in judged if probe["verdict"] != "intended_failure"]
    if len(judged) > 1:     # one row is the plain case: no `param_rows`, no note (as every single-row record always was)
        record["param_rows"] = [{"test_id": row["test_id"], "verdict": probe["verdict"]} for row, probe in judged]
    if len(judged) == 1 or not survivors:
        first = judged[0][1]
    else:
        first = next((p for v in _SURVIVOR_ORDER for _r, p in survivors if p["verdict"] == v), survivors[0][1])
        names = ", ".join(repr(row["test_id"]) for row, _p in survivors)
        record["notes"].append(f"{len(judged)} report rows are named {_tail(spec['node'])!r}[...]; the mutation "
                               f"survived in {len(survivors)}: {names}")
    for key in ("observed", "verdict", "actual_location", "actual_reason", "failure_kind", "mismatches"):
        if key in first:
            record[key] = first[key]
    if not survivors and all(probe.get("proved_by") == "marker" for _row, probe in judged):
        record["proved_by"] = "marker"      # every row is `intended_failure` and every one read the token: the only proof the code writes
    return first


def _tooling_gap(record: dict, detail: dict) -> None:
    """The record says the TOOL could not judge: the language and `cause: tooling` (the module docstring's `incomplete` and
    an unbound report row). The reader is `proof_level.tooling_gap_key`, which takes the class word only from a record that says
    this and nothing else (a stand that did not run writes no cause)."""
    record["language"], record["cause"] = detail["language"], "tooling"


def _bind_report_rows(rows: list, own, spec: dict, key: str, reporter: str, task: str, pytest_command: bool, report_read: bool = True) -> tuple:
    """`(matched rows, note, tooling)` - the ONE binding of a run's report rows to the test (fix round I2, t-2064 q8/q9: the old road's
    `_judge_rows` and the walk's `_walk_run_once` both read it, AR-15). `own` is the request's contract of the instance (`None` for none).
    A contract with a `file` is read by `red_sandbox.selection_rows`, any other by `matching_rows(rows, spec["node"])`; every row of the
    answer is judged, none is picked. A refusal is `([], note, tooling)`: no row of the test ("no row of the ... report", with what was
    looked for and what the report held), SEVERAL rows of a hand-written id (`bind_row`'s text, else "...; ambiguous": the tool cannot tell
    which row is the test's), or rows of different files or classes. `tooling` is True when the report was read and the tool could not
    bind (the caller writes `cause: tooling`); False for a report that held no rows at all (a stand that ran nothing: no cause). An
    unknown is never a verdict on the author (AR-28). Pure; reads and writes nothing."""
    import red_sandbox
    if isinstance(own, dict) and own.get("file"):
        matched = red_sandbox.selection_rows(rows, own)
        if not matched:
            return [], (f"no row of the {reporter} report is the test the request selected for {key} "
                        f"({own.get('report_test_id')!r} in {own.get('file')}); the report held {held_ids(rows)}"), bool(report_read and rows)
        if len(matched) > 1 and not (own.get("report_match") or own.get("classname_match")):
            # a hand-written id names ONE row: several are ambiguous (`bind_row`'s text). Only a selection the CODE built
            # (a pattern, or the file-suffix rule of the run form) can be several rows of one test
            _row, why = red_sandbox.bind_row({"instance_id": key}, {key: own} if key else {}, rows, reporter, task, pytest_command=pytest_command)
            return [], why or f"{len(matched)} rows of the {reporter} report are named {own.get('report_test_id')!r}; ambiguous", True
        if red_sandbox.classnames_differ(matched):
            return [], (f"{len(matched)} rows of the {reporter} report are named like {own.get('report_test_id')!r} but belong "
                        "to different files, so which test ran cannot be told; nothing is said about the test"), True
        return matched, "", False
    matched = matching_rows(rows, spec["node"])      # every matching row is judged, none is picked
    if not matched:
        return [], (f"no row of the {reporter} report is named {_tail(spec['node'])!r} (no file-bound contract for {key or 'this instance'}); "
                    f"the report held {held_ids(rows) if rows else 'no rows'}"), bool(report_read and rows)
    if red_sandbox.classnames_differ(matched):     # one tail in two classes or files: which test ran cannot be told (never a verdict)
        return [], (f"{len(matched)} rows of the {reporter} report are named {_tail(spec['node'])!r} but belong to different "
                    "files or classes, so which test ran cannot be told; nothing is said about the test"), True
    return matched, "", False


def _judge_rows(root: Path, record: dict, rows: list, reporter: str, spec: dict, detail: dict,
                request: dict, oracle_path: Path, keys: list, report_read: bool = True) -> None:
    """R7, R8: the rows of THIS instance are the ones the request's `report_test_id` names for it. ONE binding, keyed by the
    contract's shape (t-2045 N3a, B2): a contract with a `file` (the code built the selection, or the role's own id is judged by
    the same table, EP1-37) is read by `red_sandbox.selection_rows`: one row, or several of ONE file (a templated or looped test,
    or a run of several projects), each judged and the worst speaks (`_worst_of_rows`); a contract with NO `file` (a pytest
    contract) or no contract is read by `matching_rows(rows, spec["node"])`, the one matcher: every row that matches
    is judged, none is picked (`func[webkit]` never matches `func[firefox]`).
    No row, rows of different files, or no binding leaves the record `not_executed` with the reason BEFORE any aggregate (a
    verdict of "nothing" is none), and says it is the tool that could not bind (`cause: tooling`) - only when the report HELD
    rows (`rows` empty: a stand that wrote an empty report, or none, did not run the suite, and nothing is said about the tool;
    `report_read` is a parameter of the caller's, the rows are the fact, F-1 of t-596). Then the frame of each failed row is
    read with the entry's grammar. `among` is true only for a `--at` that chose among several candidates (E5, M-4)."""
    import execution_request as ER
    entry, notes = spec["entry"], record["notes"]
    contracts = request.get("instance_contracts") or {}
    key = next((k for k in keys if k in contracts), keys[0] if keys else "")
    own = contracts.get(key)
    argv = (request.get("command") or {}).get("argv")
    pytest_command = ER.is_pytest_command(argv)     # once: the ambiguity text below and the frame reader both read it (B2)
    matched, why, tooling = _bind_report_rows(rows, own, spec, key, reporter, record["task"], pytest_command, report_read)
    if why:
        if tooling:
            _tooling_gap(record, detail)
        notes.append(why)
        return
    if not (isinstance(own, dict) and own.get("file")) and len(matched) == 1 and _tail(matched[0]["test_id"]) != _tail(spec["node"]):
        record["matched_report_id"] = matched[0]["test_id"]      # K2: the one row matched by another tail (a plugin parameter)
    frames, skip, frame_path = AD.grammar_of(entry)
    # E5, E-O: a pass of a check chosen by `--at` or the manifest's id does not say which body ran when the declaration is one of
    # several, or when the check stands outside the located body of the test (or the body is not located: `None` reads as outside)
    among = detail.get("target_source") in ("at", "assertion_id") and (
        len(detail.get("candidates") or []) > 1 or detail.get("target_outside_body") is not False)
    judged, row_notes, owed = [], {}, []
    for row in matched:
        if reporter in reporters.READERS:
            site = reporters.assertion_site(row, reporter, root, oracle_path, pytest_command=pytest_command,
                                            runtime=detail["language"], frames=frames, skip_frames=skip,
                                            frame_path=frame_path)
        else:
            site = {"site_unread": f"{reporter}/{detail['language']}",
                    "reason": f"the run's reporter is {reporter!r}; stack frames are read only from the readers {', '.join(reporters.READERS)}"}
        result = judge_probe_row(row, site, entry, detail, among=among, argv=argv)
        fields = {"observed": result["observed"], "verdict": result["verdict"],
                  "actual_location": result["actual_location"], "actual_reason": result["actual_reason"],
                  "failure_kind": site.get("failure_kind")}
        if result.get("cause"):
            fields["cause"] = result["cause"]
        if result.get("proved_by"):
            fields["proved_by"] = result["proved_by"]
        if result["verdict"] == "intended_failure":
            fields.update(actual_location=record["expected_location"], actual_reason=record["expected_reason"],
                          failure_kind="assertion")
        if result["mismatches"]:
            fields["mismatches"] = result["mismatches"]
        judged.append((row, fields))
        row_notes[id(fields)] = result["note"]
        if result.get("cause") == "judgment":     # t-1968 N2: the facts travel with the rows that are owed a judgment (N4: ALL of them)
            owed.append((row, site))
    first = _worst_of_rows(judged, spec, record)
    if record.get("verdict") == "incomplete":   # the module docstring's gap of the factory (a frame it cannot resolve, a launcher that may not rebuild): the tool's
        incomplete = [f for _r, f in judged if f["verdict"] == "incomplete"]   # ALL of them decide: one tooling gap among data rows is still a gap
        if incomplete and owed and all(f.get("cause") == "judgment" for f in incomplete):
            # E15 (t-1968 N2): the run was read and failed; its text is the code critic's to judge. `cause: judgment` always travels
            # with `judgment_facts` (one move, E2.5) - never `tooling`, so no `probe gap` question. N4 (B7): the facts hold EVERY
            # owed row (`rows`); the flat keys describe the first of them, for the readers that predate `rows`
            facts = judgment_facts(record, owed[0][0], owed[0][1], detail, entry, rows=[r for r, _s in owed])
            record["language"], record["cause"], record["judgment_facts"] = detail["language"], "judgment", facts
        else:
            _tooling_gap(record, detail)
    if row_notes.get(id(first)):
        notes.append(row_notes[id(first)])


def probe(task: str, dispatch: str, test: str, instance_id: str, mutation: str,
          timeout: int = RUN_TIMEOUT_S, oracle: str = "", at=None, *, s6_close: bool = False,
          alternative: str = "", model: str = "", supersede=None) -> dict:
    """One probe. The per-file locks it takes live exactly as long as this call: released on every
    way out (an answer, a refusal, a crash), and by the OS if the process is killed.

    `s6_close` (keyword only) is the `--s6-close` form of the call (HF3-6): the probe of the code close of S6, with no
    dispatch open (`dispatch` is then ""; the context's own id is taken from the story's state)."""
    locks: list = []
    try:
        return _probe(task, dispatch, test, instance_id, mutation, timeout, oracle, locks, at, s6_close=s6_close,
                      alternative=alternative, model=model, supersede=supersede)
    finally:
        release_locks(locks)


def _alternative_spelling_refusal() -> Refusal:
    """`--mutation alternative` was removed (t-2064 P5, S11): a reading is called by `--alternative <case>:ALT-n` alone, whatever the
    language. ONE text for `main`'s flag check and `_refuse_flags` (the API call), the door the caller can use named (FR-2)."""
    return Refusal("--mutation alternative was removed: a case's declared reading B is probed by `--alternative <case>:ALT-n` alone (the call "
                   "`probe_by_code.py --task <T> --dispatch <D> --test <node> --instance <I> --alternative TC-001:ALT-1`; "
                   "`--alternatives` prints the token of every declared reading). The reading's model is an entry that carries "
                   "`alternative` in work/probe-models/<dispatch id>.json (or the file `--model` names). Nothing was changed.")


def _refuse_flags(spec: dict, mutation: str) -> None:
    """Refuse a flag that means something only for the other kind of test, before anything is read. `--mutation alternative` is refused
    for every language with the door `--alternative` (t-2064 P5: the alternative is a call form of the one road, not a mutation).
    `--at` is read by every language (t-2045 N1), so it is no flag of either kind.

    `--mutation expected` stays among the parser's `choices` (so argparse does not answer first, with a list that omits it) and is
    refused HERE, for every language, before anything is read (t-2045 N7): the door is the `invert` ENTRY of the model file, not the flag
    `--mutation invert` (a flag selects nothing and is no bypass of a model; t-2064 P4b item 3, FR-2)."""
    if mutation == REMOVED_MUTATION:
        raise Refusal("--mutation expected was removed: code never chooses another expected value (what a broken product "
                      "would answer is for the role to suppose); write an `invert` entry for the check in the model file of the call, "
                      '{"check": "<key>", "invert": "<why no other value is known>"} in work/probe-models/<dispatch id>.json '
                      "(`--plan` prints the keys). Nothing was changed.")
    if mutation == ALTERNATIVE:
        raise _alternative_spelling_refusal()


def _test_path(root: Path, cfg: dict, spec: dict, entry: dict | None = None) -> tuple:
    """(the test file, the directory its profile runs in); a refusal when no such file is under the root.
    `entry` is the instance's manifest row: the profile it names settles a test root several profiles share.
    Reads no byte of the file: what is read, and when, is the caller's (R9)."""
    import execution_request as ER
    cwd = root / _profile_cwd(cfg, spec["file"], ER.entry_profile_id(entry))
    path = next((p for p in (root / spec["file"], cwd / spec["file"]) if p.is_file()), None)
    if path is None:
        raise Refusal(f"no file {spec['file']} under the project root")
    return path, cwd.resolve()


def _resolve_oracle(root: Path, run_cwd: Path, cfg: dict, spec: dict, oracle: str,
                    path: Path, test_text: bytes, target: dict = None) -> tuple:
    """(the file the mutation lands in, the function whose assert is mutated, the note saying how it was
    found). Which FILE the mutation lands in is decided here: the test's own, or the one holding the
    helper or fixture its expectation lives in. Everything after it - the restore, the sha in the
    fingerprint - follows that file, while the test file stays the probe's identity. The test's bytes
    are the caller's argument, read after the test's lock (R9): this function reads none of them.

    The file and the line come from `target` (`_target_of`, already through the one guard of every language): `--oracle` names
    the function (`[<file>::]<name>`), a target with a LINE names no function at all - the check is found by its line - and
    only a target with neither (the first check) follows ONE hop out of a test body that holds no check, into a helper it calls
    (`find_oracle`, by the spec's reader, for every language; t-2045 N5)."""
    target = target or {"file": path, "line": None}
    if oracle:
        _hint, _, name = str(oracle).rpartition("::")
        return target["file"], name or str(oracle), f"the oracle was named by hand: {oracle}"
    if target["line"] is not None:
        return target["file"], "", ""
    found, oracle_note = find_oracle(test_text.decode("utf-8", "replace"), spec, path, root,
                                     _helper_chain(path, run_cwd), _reader_entry(spec), cfg)
    if found is None:
        return path, "", oracle_note       # plan_mutation refuses with the shape
    return found[0], (found[1] if oracle_note else ""), oracle_note


class ProbeCtx(NamedTuple):
    """What one probe launch has fixed BEFORE it reads a byte of the test (R9): the arguments of `probe()`
    that are values, and what `_test_path` and the manifest give without opening the file. Immutable, and
    it holds nothing a helper changes and no bytes (E11): `record`, `notes`, `locks`, the bytes, their shas
    and the oracle stay arguments, so the lock still comes before the first read of each file and no helper
    can read the test or the oracle from here. `path` is the test file's PATH."""
    task: str
    dispatch: str
    instance_id: str
    case: str
    spec: dict
    entry: dict
    root: Path
    cfg: dict
    task_root: Path
    detector: bool
    mutation: str
    manifest_path: Path
    path: Path
    # The stage the probe belongs to when it has no dispatch to name it ("S6" in the close context, HF3-6); "" = the
    # stage of the dispatch, read by `proof_level` as before. Last and defaulted: a positional build stays valid.
    stage: str = ""
    # The reading (`<case>:ALT-n`) an alternative call walks (t-2064 P5); "" on every other call. Last and defaulted. It redirects the walk's
    # WRITES only (`_records_id`: the per-check records, `_aggregate_record`: the one record under work/probes/alternative/), never what it
    # reads or runs: an alternative's walk is the plain walk with its own file names.
    alt: str = ""


def _repeat_check(ctx: ProbeCtx, now: dict, test_sha: str, copy_notes: list, target: dict = None,
                  oracle_function: str = "") -> tuple:
    """(the answer to give, or None; the notes the new record starts with). The identity of the test is
    measured by the caller BEFORE the mutation is written: a mutated file is never measured as the
    author's bytes. The same measure answers a repeat (D-0018): a test already probed over these very
    bytes is reported and nothing runs after it - no mutation, no request file, no job, no record
    overwritten. It errs only toward running: a check that fails says so in a note and the probe goes
    on (P1: code tells, never stops).

    `target` is `_target_of`'s answer (t-2045 N1b, B10): the repeat is answered by the bytes AND the target, so a probe of
    another line - the retarget a `no_failure` note prints - is not the repeat of the first. None = the bytes alone."""
    pre_notes: list = list(copy_notes)
    asked = ({"file": target["rel"], "line": target["line"], "source": target["source"],
              "oracle_function": oracle_function}
             if isinstance(target, dict) else None)
    if now["input_hash"] != test_sha:
        pre_notes.append(f"--test names {ctx.spec['file']}, which is not the file the manifest row of "
                         f"{ctx.instance_id!r} names ({proof_level.test_file_of(ctx.entry) or 'none'}), or that "
                         "file cannot be read: the repeat check is not made, and the record binds the "
                         "bytes measured here")
        return None, pre_notes
    try:
        answer = proof_level.already_probed(ctx.entry,
                                            C.load_json(ctx.manifest_path) if ctx.manifest_path.is_file() else {},
                                            ctx.task_root, now=now, project=ctx.root, dispatch=ctx.dispatch,
                                            stage=ctx.stage, target=asked)
    except Exception as exc:
        answer = {"probed": False, "notes": [f"the repeat check failed ({type(exc).__name__}: "
                                             f"{str(exc)[:160]}); the probe runs"]}
    if answer.get("probed"):
        return {"verdict": "already_probed", "instance_id": ctx.instance_id, "by": answer["by"],
                "level": answer["level"], "receipt_ref": answer["receipt_ref"],
                "record": answer["record"], "prior_verdict": answer["prior_verdict"],
                "recorded_at": answer["recorded_at"], "holds": answer["holds"],
                "words": answer["words"], "block": answer["block"],
                "notes": copy_notes + list(answer["notes"] or [])}, pre_notes
    pre_notes.extend(answer.get("notes") or [])
    return None, pre_notes


def _reader_plan(ctx: ProbeCtx, target: dict, original: bytes, oracle_path: Path, oracle_function: str, oracle_note: str,
                 token: str) -> tuple:
    """(the mutated bytes, the detail, the context) by the reader the spec names (`spec["reader"]`, t-2045 N2): ONE call shape
    for both. The detail has the same keys either way; `context` is the code before the declaration (the table reader's, "" for
    the AST reader, which has no annotation to read). `ctx.detector` means "the table reads it" (built from `spec["reader"]`)."""
    if ctx.detector:
        return plan_detector_mutation(original, ctx.spec, ctx.instance_id, target["given"], oracle_function, oracle_note,
                                      _rel_project(oracle_path, ctx.root), marker_token=token, target=target)
    mutated, detail = plan_mutation(original, ctx.spec, ctx.mutation, ctx.instance_id, oracle_function, oracle_note,
                                    at=target["line"], marker_token=token)
    detail["at"] = target["given"]
    _stamp_target(detail, target)
    return mutated, detail, ""


def _plan(ctx: ProbeCtx, target: dict, original: bytes, oracle_path: Path, oracle_function: str, oracle_note: str) -> tuple:
    """(the mutated bytes, the detail of the mutation). `target` is `_target_of`'s answer: its line (None = the first check) is
    what both readers' plans aim at, and its source and place are stamped into the detail. The token is this probe's own
    (instance, the author's bytes, this moment; t-1968 N1), computed once here for every language and handed to `_reader_plan`.
    For a test the table reads, everything the run needs is checked BEFORE the first write (R6): the whole case runs, and one
    row of its report is read."""
    token = marker_token(ctx.instance_id, sha256(original), datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                         f"{_rel_project(oracle_path, ctx.root)}:{target['line'] if target['line'] is not None else 'first'}")
    mutated, detail, context = _reader_plan(ctx, target, original, oracle_path, oracle_function, oracle_note, token)
    if ctx.detector:
        run_shape_checks(ctx.cfg, C.load_json(ctx.manifest_path) if ctx.manifest_path.is_file() else {}, ctx.case,
                         ctx.entry, ctx.spec, ctx.instance_id, context, original.decode("utf-8-sig", "replace"), ctx.root)
    return mutated, detail


_ASSERTION_ID = re.compile(r"^(?P<file>.+):(?P<line>\d+)$")


def target_fact(detail: dict, spec: dict, assertion_id) -> dict:
    """The fact `target` of a probe: which statement was mutated, and whether that is the obligation's check.
    `is_assertion_id`: True when `assertion_id` (`<file>:<n>`) names the probed file and `line <= n <= end_line`
    (a multi-line statement holds its inner lines); False when it names another line or another file; None when it
    is absent or not `<path>:<digits>` - an unknown is never written as False (FR-41, FR-59). Computed from the PLAN
    (`detail`): it describes what was MUTATED, never what failed. Data only: no default target is chosen here."""
    line = detail.get("line")
    end_line = detail.get("end_line") or line
    shown = assertion_id if isinstance(assertion_id, str) and assertion_id.strip() else None
    verdict = None
    parsed = _ASSERTION_ID.match(shown.strip()) if shown else None
    if parsed and isinstance(line, int):
        probed = str(detail.get("file") or spec.get("file") or "")
        n = int(parsed.group("line"))
        verdict = bool(_same_file(parsed.group("file"), probed) and line <= n <= end_line)
    fact = {"line": line, "end_line": end_line, "assertion_id": shown, "is_assertion_id": verdict}
    if detail.get("target_source"):      # t-2045 N1: at | oracle | assertion_id | first - where the choice came from; absent on a record written before
        fact["source"] = detail["target_source"]
    return fact


def _off_target_note(target: dict, probed_file: str = "") -> str:
    """The one note of a probe that mutated a line other than the obligation's check, with its one door, the same for every
    language (`--at` is read by all): the Then's line - written `<file>:<line>` when the id names another file than the one
    probed (`probed_file`), the id's own spelling, so the printed door opens."""
    parsed = _ASSERTION_ID.match(target["assertion_id"])
    where = parsed.group("line") if parsed and (not probed_file or _same_file(parsed.group("file"), probed_file)) \
        else target["assertion_id"]
    door = (f"probe the Then's line with `--at {where}`; or, when no check of the Then can be inverted here, report the "
            "item `unverified` with the reason")
    return (f"this probe broke line {target['line']}, not the obligation's check at {target['assertion_id']}: it does "
            f"not prove that check; {door}")


def _new_record(ctx: ProbeCtx, detail: dict, identity: dict, test_bytes: bytes, original: bytes,
                oracle_path: Path) -> dict:
    """The record of a probe that has not run yet: verdict `not_executed`, every field the run fills in
    later empty. `notes` is a fresh list the caller extends."""
    spec, path = ctx.spec, ctx.path
    fields, missing = obligation_fields(ctx.entry)
    expected_location = f"{detail.get('file') or spec['file']}:{detail['line']}"
    return {
        "schema_version": 1, "probe_tool": "probe_by_code.py", "task": ctx.task, "dispatch_id": ctx.dispatch,
        "instance_id": ctx.instance_id, "case": ctx.case, "test_node": spec["node"],
        "verdict": "not_executed", "mutation": ctx.mutation, "mutation_kind": MUTATION_KIND,
        "proof_level": proof_level.LIVE, "failure_kind": None, "expected_location": expected_location, "actual_location": None,
        "expected_reason": detail["marker"], "actual_reason": None, "observed": {},
        "input_hash": None, "input_hash_source": None, "test_file_sha256": sha256(test_bytes),
        # the same measured bytes without comments, docstring lines and blank lines: a later
        # comment-only edit of the test keeps this probe's receipt (D-0017, proof_level)
        "test_code_sha": proof_level.code_sha(test_bytes, path.name),
        # The per-test identity (`--mine`'s `instance_contracts` shas, re-measured by their producer) and
        # the flat sha beside it that says the same thing under the name the run blocks use: ONE
        # derivation per field name. "" when the test has no measurable identity (never a stand-in).
        "instance_identity": identity, "instance_content_sha": identity.get("instance_content_sha", ""),
        # What this probe mutated, so a later repeat is answered only while that file still holds
        # these bytes: the oracle may be a helper or the product, not the test (`already_probed`).
        "mutated_file": {"path": _rel_project(oracle_path, ctx.root), "sha256": sha256(original),
                         "code_sha": proof_level.code_sha(original, oracle_path.name)},
        **fields, "manifest_fields_missing": missing,
        "target": target_fact(detail, spec, fields.get("assertion_id")),
        "evidence_ref": None, "evidence_refs": [], "request": None,
        "mutation_detail": detail, "restore": None, "notes": [],
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


_READ_BOUND = object()   # `_run_and_judge`: the caller did not read the author's binding, read it here


def _run_and_judge(ctx: ProbeCtx, record: dict, oracle_path: Path, mutated_sha: str, original_sha: str,
                   timeout: int, *, judge_row: Callable = None, request_stem: str = None, reason: str = None,
                   mutation_kind: str = MUTATION_KIND, bound=_READ_BOUND) -> None:
    """Build the request, run it, judge the run - filling `record` and its `notes` in place (it is the
    contract of `_judge_run` too). Nothing in here may stop the caller: the record says what happened,
    and the author's bytes go back regardless (the caller's `finally`). The task, dispatch, case,
    instance and mutation are read from `ctx`; the detail and the expected location from the record
    they were written into.

    The keywords are the alternative probe's (TQ1-25): its row judge, its own request file stem (`probe-alt-...`, never the
    invert probe's), its reason, the `mutation_kind` the request names, and the author's binding it already read (one read,
    one id). Their defaults are the invert probe's, unchanged."""
    root, task_root, spec, entry = ctx.root, ctx.task_root, ctx.spec, ctx.entry
    notes, instance_id = record["notes"], ctx.instance_id
    reason = reason or (f"probe-{instance_id}: {ctx.mutation} of the first assert at {record['expected_location']} "
                        f"({ctx.dispatch})")
    try:
        import execution_request as ER
        request, build_notes = build_request(root, ctx.cfg, ctx.task, ctx.dispatch, ctx.case, spec, instance_id,
                                             ctx.mutation, reason, ER.entry_profile_id(entry),
                                             s6_close=ctx.stage == "S6",   # only the close context sets `stage`
                                             mutation_kind=mutation_kind)
        notes.extend(build_notes)
        request_path = (task_root / "work" / "probe-requests"
                        / f"{request_stem or 'probe-' + record_path(task_root, instance_id).stem}.json")
        atomic_json(request_path, request)
        record["request"] = request_path.relative_to(task_root).as_posix()
        record["input_hash"] = original_input_hash(request, oracle_path, mutated_sha, original_sha)
        record["input_hash_source"] = "fingerprint:test_content_sha over the author's bytes"
        if bound is _READ_BOUND:
            bound = author_binding(task_root, instance_id, record["instance_content_sha"])
        if bound:
            record["input_hash"] = bound["test_content_sha"]
            record["input_hash_source"] = f"run_block:{bound['run_block']} ({bound['dispatch_id']})"
            record["author_run_block"] = bound["run_block"]
        proc, summary = run_request(root, request_path, timeout)
        if not summary:
            notes.append(f"run_suite printed no summary (exit {proc.returncode}): "
                         + fold((proc.stderr or proc.stdout or "").strip()[-600:], 600))
        else:
            _judge_run(root, task_root, record, summary, spec, record["mutation_detail"], request, oracle_path,
                       [instance_id, C.test_instance_id(entry) or instance_id], judge_row=judge_row)
    except Exception as exc:  # the record says what happened; the bytes go back regardless
        notes.append(f"{type(exc).__name__}: {exc}")


def _proved_standing(path: Path, record: dict):
    """The stored record at `path` when `record` must not overwrite it, else None (t-2045 N1b, B10). That is: the stored one is
    an `intended_failure` ON the obligation's check (`target.is_assertion_id` true) over the same measured test bytes, and `record`
    is a judged verdict of another target that is not itself on the check, or an `incomplete` record `cause: judgment` (it exists
    so the code critic can judge it: t-2096 F3, it is kept beside, never dropped). A `not_executed` or any other `incomplete`
    record judged nothing and is `keep_standing_record`'s; an unreadable or unmeasured stored record is no proof to protect. ERROR DIRECTION: toward the
    old overwrite only where the stored proof cannot be shown to be the check's."""
    target = record.get("target") if isinstance(record.get("target"), dict) else {}
    unjudged = record.get("verdict") == "not_executed" or (record.get("verdict") == "incomplete"
                                                           and record.get("cause") != "judgment")
    if unjudged or target.get("is_assertion_id") is True:
        return None
    line = target.get("line")
    if not isinstance(line, int) or isinstance(line, bool):
        return None
    try:
        stored = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    fact = stored.get("target") if isinstance(stored, dict) else None
    if (not isinstance(fact, dict) or stored.get("verdict") != "intended_failure" or fact.get("is_assertion_id") is not True
            or not stored.get("test_file_sha256") or stored["test_file_sha256"] != record.get("test_file_sha256")):
        return None
    return stored


def _finish_record(record: dict, entry: dict, task_root: Path, instance_id: str) -> None:
    """Window probe, receipt and the write of the record - after the author's bytes are back."""
    record["window_probe"] = window_probe(record)
    out = record_path(task_root, instance_id)
    record["record"] = out.relative_to(task_root).as_posix()
    record["receipt"], record["receipt_missing"] = None, []
    standing = _proved_standing(out, record)
    if standing is not None:
        # t-2045 N1b: a probe of another line never overwrites the proof of the obligation's check - it is kept BESIDE it, and
        # no receipt is published from it (the standing one is the receipt's record)
        beside = proof_level.probe_record_path(task_root, instance_id, target_line=record["target"]["line"],
                                               file=(record.get("mutation_detail") or {}).get("file"))
        record["record"] = beside.relative_to(task_root).as_posix()
        record["notes"].append(f"the proved probe of line {standing['target'].get('line')} stands in {out.relative_to(task_root).as_posix()}; "
                               f"this probe of line {record['target']['line']} is kept beside it and publishes no receipt")
        atomic_json(beside, record)
        return
    # Only a probe that showed the intended failure AND put the author's bytes back proves
    # anything: an unverified restore is the tool's own failure, and a receipt would vouch for it.
    if record["verdict"] == "intended_failure" and (record.get("restore") or {}).get("verified"):
        attach_receipt(record, entry, task_root)
    if not keep_standing_record(out, record):
        atomic_json(out, record)


def _dispatch_context(root: Path, task: str, task_root: Path, dispatch: str, case: str, s6_close: bool) -> tuple:
    """(dispatch, stage) of the context this probe runs under, asked BEFORE `_test_path`, `scan_copies`, any lock or
    any read of the test (HF3-6 for `--s6-close`, RH1-8 B3 for `--dispatch`). Invariant: a refused context restores
    nobody's copy, takes no lock, reads and mutates no byte, and writes no request, job or record.

    `--s6-close`: the S6 close context, `(id, "S6")`. `--dispatch`: the answer of `find_active_dispatch` is only
    "there is one / refusal"; the PASSED id is kept unchanged (a `parent_retry` ancestor id stays the id the request
    and its `idempotency_key` carry), with no stage. The late question in `build_mine_request` stays (a race)."""
    import execution_request as ER
    if s6_close:
        try:
            got = ER.s6_close_dispatch(task_root, [case])
        except ER.MineRefusal as exc:
            raise Refusal(f"probe_by_code: {exc}") from exc
        return got["id"], "S6"
    from hooklib import artifact_root
    try:
        ER.find_active_dispatch(artifact_root(root=root), task, dispatch, [case], None)
    except ER.MineRefusal as exc:
        detail = str(exc)
        # keep the REASON only: the doors `find_active_dispatch` appends (`--dispatch ID`, `controller.py --operation prepare`,
        # `--task/--label`) belong to the `--mine` caller, not to the critic who reads this refusal (FR-2, RH1-8 F5)
        reason = detail
        for door in (". Inside a story", "; say which one is yours"):
            reason = reason.split(door)[0]
        head =(f"several dispatches are open in story {task}; " if detail.startswith("several dispatches are open")
                else f"no open dispatch {dispatch} in story {task}: ")
        raise Refusal(
            f"probe_by_code: {head}the probe runs only under the dispatch your brief names. Nothing was read or "
            f"changed. Check the id in your brief; if it is that one, report the probe as cause: tooling "
            f"(dispatch not open), repeated under tooling_findings; the instance stays unverified. "
            f"Detail: {reason}.") from exc
    return dispatch, ""


def _lock_test(ctx: ProbeCtx, locks: list) -> tuple:
    """(the test file's copy key, the notes of what a dead probe left). POSITION (R9): everything before this call read no
    byte of the test. Before the FIRST read of it - and so before any byte can be taken as "the author's original", as
    `test_file_sha256` or as the identity - (1) what a dead probe left is restored, (2) this file's lock is taken.
    Invariant: no byte is read as the author's until every dead probe's copy has been put back, and none is read while another
    probe may be mutating the file. The ONE copy of this order: `_probe` and `_probe_alternative` both call it."""
    copy_notes: list = []
    test_key, test_shown = copy_key(ctx.path, ctx.root)
    scan_copies(ctx.root, skip_keys={test_key}, notes=copy_notes)
    held = claim_key(ctx.root, test_key, test_shown, own=True, notes=copy_notes)
    if held is not None:
        locks.append(held)
    return test_key, copy_notes


def _require_cover(task_root: Path, manifest_path: Path, entry: dict, instance_id: str, case: str) -> None:
    """The instance must prove the case the alternative token names (`instances_of_case`, the one reader): else the CALL is
    wrong (exit 2, FR-46). Invariant: a record is only ever keyed by a (case, ALT) the instance proves. Reads the manifest only."""
    import s5_precheck as S5
    cfg = C.case_config()
    manifest = C.load_json(manifest_path) if manifest_path.is_file() else {}
    aliases = {a for row in S5.instances_of_case(manifest, case, cfg) for a in C.instance_id_aliases(row, cfg)}
    if instance_id not in aliases and (C.test_instance_id(entry) or instance_id) not in aliases:
        raise Refusal(f"instance {instance_id!r} does not cover case {case}: an alternative is probed on an instance that "
                      "proves its case (`probe_by_code.py --task <TICKET> --alternatives` lists each instance with its "
                      "cases). Nothing was changed.")


def _probe(task: str, dispatch: str, test: str, instance_id: str, mutation: str, timeout: int,
           oracle: str, locks: list, at=None, *, s6_close: bool = False, alternative: str = "", model: str = "",
           supersede=None) -> dict:
    root = project_root().resolve()
    task_root = artifacts_dir(task).resolve()
    cfg = load_config()
    spec = parse_node(test, root)
    _refuse_flags(spec, mutation)
    alt_case = parse_alternative_token(alternative)[0] if alternative else ""
    entry = manifest_entry(task_root, instance_id)
    if alt_case:
        # The case of an alternative probe is the TOKEN's, not the instance's first: the dispatch scope and the request name it
        # (an instance covering TC-001 and TC-002 is probed for TC-002 under the window that holds TC-002).
        _require_cover(task_root, task_root / "work" / "automation-manifest.json", entry, instance_id, alt_case)
    case = alt_case or str(entry.get("case") or next(iter(entry.get("covers") or []), "") or "")
    if not case:
        raise Refusal(f"the manifest entry of {instance_id!r} names no case")
    dispatch, stage = _dispatch_context(root, task, task_root, dispatch, case, s6_close)
    path, run_cwd = _test_path(root, cfg, spec, entry)
    ctx = ProbeCtx(task, dispatch, instance_id, case, spec, entry, root, cfg, task_root, _is_table(spec), mutation,
                   task_root / "work" / "automation-manifest.json", path, stage)
    if alternative:
        return _probe_alternative(ctx._replace(mutation="model"), run_cwd, locks, alternative, model, timeout)
    # t-2064 P4b items 2 and 3: every call that is not an alternative probe walks the plan. No `--at` and no `--oracle`: the whole plan;
    # `--at` / `--oracle`: the plan with the selected rows to run (`_probe_plan`'s docstring: the selection, its position invariant). POSITION:
    # here, after every refusal that preceded a probe (flags, the manifest row, the dispatch, the test file, the alternative's branch):
    # nothing refused before is reachable now, and no byte is written before `_probe_plan`'s own refusals.
    return _probe_plan(ctx._replace(mutation="model"), run_cwd, locks, timeout, at=at, oracle=oracle or "")


# --- the alternative reading: the red probe models reading B (TQ1-25) -------------------------------------------------
# A Then its case lists in `alternatives` must FAIL when the product behaves per reading B. The critic writes ENTRIES (a file
# under `work/probe-models/`: `{"models": [...]}`, each entry on a check of that Then carrying `alternative: <case>:ALT-n`);
# since t-2064 P5 the reading walks the ONE road (`_probe_plan`, any language) and this section only names the reading, reads
# its records and writes the gap. The verdict is `intended_failure` (every check of the Then failed under B, and the test was
# green under A), `no_failure` (it passed under B: the Then separates nothing), or `incomplete` / `gap` / `unknown`. Every
# function here errs one way: toward NOT `intended_failure` and never toward blaming the author for the critic's model.
# The record is keyed `<IID>--<CASE>--<ALT>` under `work/probes/alternative/`; it is never a live receipt, never published.

def parse_alternative_token(value) -> tuple:
    """`<case>:ALT-<n>` -> (case, alt). One form only: the case is part of the identity (a bare `ALT-1` of an instance that
    covers two cases would answer for both). `rpartition`: an ALT id never holds a colon."""
    case, _, alt = str(value or "").strip().rpartition(":")
    case = case.strip()
    if not case or not C.ALTERNATIVE_ID.fullmatch(alt):
        raise Refusal(f"--alternative wants <case>:ALT-<n> (for example TC-001:ALT-1), got {value!r}; `probe_by_code.py "
                      "--task <TICKET> --alternatives` prints the token of every declared reading. Nothing was changed.")
    return case, alt


def _read_model_file(task_root: Path, path, refuse: Callable) -> tuple:
    """(the JSON object, its bytes, the resolved path) of a critic's model file, under the guards of `load_models` (t-2064 P3; the
    one loader, since the old alternative loader went in P5): under `<task>/work/probe-models/` after `resolve()` (a symlink out is
    refused), a file, <= MODEL_FILE_MAX bytes, UTF-8 (a BOM is tolerated), one JSON object. `refuse(path, what)` builds the loader's own Refusal, so each
    names its own shape; nothing is mutated or written."""
    base = (Path(task_root) / "work" / "probe-models").resolve()
    raw = Path(str(path))
    target = raw if raw.is_absolute() else Path(task_root) / raw
    try:
        resolved = target.resolve()
        resolved.relative_to(base)
    except (ValueError, OSError):
        raise refuse(path, f"the file is not under {base.as_posix()} (a link out of it counts as out)") from None
    if not resolved.is_file():
        raise refuse(path, "no such file")
    size = resolved.stat().st_size
    if size > MODEL_FILE_MAX:
        raise refuse(path, f"the file is {size} bytes, at most {MODEL_FILE_MAX} are read")
    data = resolved.read_bytes()
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise refuse(path, "the file is not UTF-8") from None
    except (ValueError, RecursionError):
        raise refuse(path, "the file is empty or not valid JSON") from None
    if not isinstance(doc, dict):
        raise refuse(path, "the JSON is not one object")
    return doc, data, resolved


MODELS_SHAPE = ('{"models": [{"check": "<file>:<line>", "supposes": "<what the product would do>", "actual": "<the value the check '
                'would read>"}, ...]}')


def _models_shape_refusal(path, what: str) -> Refusal:
    """The refusal of a model file whose SHAPE is wrong (the new one: `models` is a list of entries, ONE kind each)."""
    return Refusal(f"--model {path}: {what}. A model file is ONE JSON object {MODELS_SHAPE}; every entry carries `check` (a key of the "
                   "plan) and EXACTLY ONE kind: `actual` or `find` + `replace` (each with `supposes`, 1 to "
                   f"{MODEL_SUPPOSES_MAX} characters), `invert` (the reason no other value is known), `not_here` (with `instance`: why "
                   "this instance does not reach the check) or `product` (a receipt path); `instance` is optional, and so is `alternative` "
                   "(`<case>:ALT-n`: the entry is a case's declared reading B, walked only by `--alternative`, with kind `actual` or `find`); "
                   "`{\"alternative\": \"<case>:ALT-n\", \"gap\": \"<why B cannot be modelled>\"}` is a reading's gap. Nothing was changed.")


def _model_door_lines(doors: dict) -> list:
    """The example entry of every kind that opens for at least one listed check: the refusal prints the doors that open and no other."""
    example = {"actual": '{"check": "<key>", "supposes": "<what the product would do>", "actual": "<the value the check would read>"}',
               "find": '{"check": "<key>", "supposes": "<...>", "find": "<code before the check>", "replace": "<that code under the supposition>"}',
               "invert": '{"check": "<key>", "invert": "<why no other value is known>"}',
               "not_here": '{"check": "<key>", "instance": "<instance>", "not_here": "<why this instance does not reach it>"}',
               "product": '{"check": "<key>", "product": "<work/sensitivity-receipts/<file>.json>"}'}
    opened = [kind for kind in MODEL_KINDS if any(kind in kinds for kinds in doors.values())]
    return [f"  {kind}: {example[kind]}" for kind in opened]


def _models_refusal(path, items: list, why: str = "no model is stored for these checks") -> Refusal:
    """THE refusal of a probe that needs a model for a check and has none (F-P8, t-2064 P3): no file, an empty `models`, or a check no
    entry names. `items` is `[{key, line, doors: [kind, ...]}]` - the checks, each with ONLY the doors that open for it (`actual` when its
    form names the argument that holds the value, `find` when code stands before its statement, `invert` when its form has an inversion,
    `not_here` always, `product` while the language has the product probe) - and the text prints those doors and no other, then the exit:
    when none fits, the check is reported `unverified`. A plain Refusal (the call's: the role writes the file and calls again). FR-2: the
    only door named is the one the plain call has - the file at `path` (the real `work/probe-models/<dispatch id>.json`, no placeholder),
    which this call reads by the dispatch id; `--model` belongs to `--alternative` alone and is not named here."""
    lines = [f"  {item['key']} (line {item['line']}): {', '.join(item['doors'])}" for item in items]
    doors = {item["key"]: item["doors"] for item in items}
    return Refusal(f"probe_by_code: the model file {path}: {why}. A probe of a check needs a value the product could return instead of the one the "
                   "check reads (a model), written by you as the critic. Checks, with the doors that open for each:\n" + "\n".join(lines)
                   + f"\nWrite {path} as {MODELS_SHAPE} with one entry per check, then make the same call again (it reads that file by the dispatch id "
                   "and takes no other argument for it); the kinds that open here:\n"
                   + "\n".join(_model_door_lines(doors))
                   + "\nIf none fits a check, report `unverified` for that check. Nothing was changed.")


def load_models(task_root: Path, path, items: list = None) -> list:
    """The critic's model file of ONE dispatch, validated (t-2064 P3, F-P8; reads SHAPE and presence, never meaning - AR-29):
    `{"models": [entry, ...]}` under the guards of `_read_model_file`. One entry: `check` (a non-empty string), and
    EXACTLY ONE kind of MODEL_KINDS - `actual` (a string), `find` + `replace` (strings; `find` 1 to MODEL_TEXT_MAX characters, `replace`
    at most that), `invert` (a non-empty reason), `not_here` (a non-empty why, and `instance` required) or `product` (a non-empty receipt
    path); `supposes` is REQUIRED on `actual` and `find` (1 to MODEL_SUPPOSES_MAX characters once stripped) and read by nobody;
    `instance` and `alternative` are optional strings. Two entries with the same (`check`, `instance`, `alternative`) are refused naming
    both; an unknown key (so an unknown kind) too. The old one-object shape (`find`/`replace`/`gap`/`function` at the top level), a file
    with no `models` key and `models` that is not a list are refused naming the new shape. With `items` (the plan's checks, see
    `_models_refusal`): an absent file or an empty `models` is the F-P8 refusal naming each check and its doors, and a `check` that is
    not a key of `items` is refused listing the plan's keys. Returns `[{index, check, instance, alternative, kind, supposes, ...}]`."""
    def refuse(path_, what):
        return _models_refusal(path_, items, what) if items is not None and what in ("no such file", "no model is stored here") \
            else _models_shape_refusal(path_, what)

    doc, _data, _resolved = _read_model_file(task_root, path, refuse)
    models = doc.get("models")
    if "models" not in doc:
        old = [k for k in ("find", "replace", "gap", "function", "alternative") if k in doc]
        raise _models_shape_refusal(path, "it has no `models` key" + (f" (the old one-object shape: {', '.join('`' + k + '`' for k in old)} "
                                                                        "at its top level is the alternative probe's model of the past; a reading is now an entry "
                                                                        "of `models` that carries `alternative`: `{\"models\": [{\"check\": \"<key>\", "
                                                                        "\"alternative\": \"<case>:ALT-n\", \"supposes\": \"...\", \"actual\": \"<value under B>\"}]}`, "
                                                                        "or `{\"models\": [{\"alternative\": \"<case>:ALT-n\", \"gap\": \"<why B cannot be "
                                                                        "modelled>\"}]}`)" if old else ""))
    if not isinstance(models, list):
        raise _models_shape_refusal(path, "`models` is not a list")
    if not models:
        raise refuse(path, "no model is stored here")
    out, seen = [], {}
    for index, raw in enumerate(models, 1):
        label = f"models[{index}]"
        if not isinstance(raw, dict):
            raise _models_shape_refusal(path, f"{label} is not an object")
        label += f" (check {raw.get('check')!r})"
        unknown = [k for k in raw if k not in MODEL_ENTRY_KEYS]
        if unknown:
            raise _models_shape_refusal(path, f"{label} has the unknown key(s) {', '.join(repr(k) for k in unknown)}, so no kind of its own")
        if "gap" in raw:        # t-2064 P5 item 4: a reading B cannot model - `{"alternative": "<case>:ALT-n", "gap": "<why>"}`, presence only
            stray = [k for k in raw if k not in ("alternative", "gap")]
            gap, token = raw["gap"], raw.get("alternative")
            if stray or not isinstance(token, str) or not token.strip() or not isinstance(gap, str) or not 1 <= len(gap.strip()) <= MODEL_GAP_MAX:
                raise _models_shape_refusal(path, f"{label.split(' (')[0]} is a `gap` entry: it carries ONLY `alternative` (a non-empty string) and `gap` "
                                                  f"(why the reading cannot be modelled, 1 to {MODEL_GAP_MAX} characters)" + (
                                                      f"; it has also {', '.join(repr(k) for k in stray)}" if stray else ""))
            entry = {"index": index, "check": "", "instance": "", "alternative": token.strip(), "kind": "gap", "supposes": "", "gap": gap.strip()}
            if ("", "", entry["alternative"]) in seen:
                raise _models_shape_refusal(path, f"models[{seen[('', '', entry['alternative'])]}] and models[{index}] are both the `gap` of {entry['alternative']!r}")
            seen[("", "", entry["alternative"])] = index
            out.append(entry)
            continue
        check = raw.get("check")
        if not isinstance(check, str) or not check.strip():
            raise _models_shape_refusal(path, f"{label}: `check` must be a non-empty string")
        has_pair = "find" in raw or "replace" in raw
        kinds = [k for k in MODEL_KINDS if k in raw and k != "find"] + (["find"] if has_pair else [])
        if len(kinds) != 1:
            raise _models_shape_refusal(path, f"{label} carries {'no kind' if not kinds else 'two kinds: ' + ', '.join(kinds)}; it must carry exactly one")
        kind = kinds[0]
        entry = {"index": index, "check": check.strip(), "instance": "", "alternative": "", "kind": kind, "supposes": ""}
        for key in ("instance", "alternative"):
            if key in raw:
                if not isinstance(raw[key], str) or not raw[key].strip():
                    raise _models_shape_refusal(path, f"{label}: `{key}` must be a non-empty string when present")
                entry[key] = raw[key].strip()
        if kind in ("actual", "find"):
            supposes = raw.get("supposes")
            if not isinstance(supposes, str) or not 1 <= len(supposes.strip()) <= MODEL_SUPPOSES_MAX:
                raise _models_shape_refusal(path, f"{label}: `supposes` is required on `{kind}`, a string of 1 to {MODEL_SUPPOSES_MAX} characters")
            entry["supposes"] = supposes.strip()
        if kind == "actual":
            if not isinstance(raw["actual"], str) or not raw["actual"].strip() or len(raw["actual"]) > MODEL_TEXT_MAX:
                raise _models_shape_refusal(path, f"{label}: `actual` must be a non-empty string of at most {MODEL_TEXT_MAX} characters")
            entry["actual"] = raw["actual"]
        elif kind == "find":
            find, replace = raw.get("find"), raw.get("replace")
            if not isinstance(find, str) or not 1 <= len(find) <= MODEL_TEXT_MAX or not find.strip():
                raise _models_shape_refusal(path, f"{label}: `find` must be a string of 1 to {MODEL_TEXT_MAX} characters, and `replace` goes with it")
            if not isinstance(replace, str) or len(replace) > MODEL_TEXT_MAX:
                raise _models_shape_refusal(path, f"{label}: `replace` must be a string of at most {MODEL_TEXT_MAX} characters, and `find` goes with it")
            entry["find"], entry["replace"] = find, replace
        else:
            value = raw[kind]
            if not isinstance(value, str) or not value.strip():
                raise _models_shape_refusal(path, f"{label}: `{kind}` must be a non-empty string"
                                            + (" (the reason no other value is known)" if kind == "invert" else ""))
            entry[kind] = value.strip()
            if kind == "not_here" and not entry["instance"]:
                raise _models_shape_refusal(path, f"{label}: `not_here` needs `instance` (the one that does not reach the check) and a why")
        identity = (entry["check"], entry["instance"], entry["alternative"])
        if identity in seen:
            raise _models_shape_refusal(path, f"models[{seen[identity]}] and models[{index}] name the same check {entry['check']!r} "
                                              f"(instance {entry['instance']!r}, alternative {entry['alternative']!r}): one entry per check")
        seen[identity] = index
        out.append(entry)
    if items is not None:
        keys = [item["key"] for item in items]
        for entry in out:
            if entry["kind"] != "gap" and entry["check"] not in keys:
                raise _models_shape_refusal(path, f"models[{entry['index']}] names the check {entry['check']!r}, which is not a key of "
                                                  f"this plan; the plan's keys are {', '.join(keys) or '(none)'}")
    return out


# --- t-2064 P3: a model on ANY reader - the value a check reads is replaced, the check is never edited -----------------------------------
# A check proves it can fail when the value it reads is made one the product could return instead (the critic writes it: `actual`, or a
# `find` / `replace` of the code that reads it). Code only places the edit: where the value stands, where the code before the check
# stands, whether the edit keeps the brackets and the line count - never whether the model is a realistic bug (AR-29). Every function here
# errs toward a REFUSAL before a byte is written, never toward a guessed value (FR-59). Position invariant (EP-N): the matcher, the
# expected value, `.not` and the message of a check are never edited by a model; an inversion is the only edit of a matcher.

_MODEL_BOM = b"\xef\xbb\xbf"


def _paired(skeleton: str) -> str:
    """"" when every bracket of `skeleton` closes the one that opened last, else what is wrong (a half-bracket text such as `foo(`, or one
    that closes what it did not open such as `x).toBe(1`: equal COUNTS of `(` and `)` do not make a text balanced)."""
    stack = []
    for hit in BRACKET.finditer(skeleton):
        char = hit.group(0)
        if char in OPEN_BRACKETS:
            stack.append(char)
        elif not stack or OPEN_BRACKETS.index(stack[-1]) != CLOSE_BRACKETS.index(char):
            return f"`{char}` closes a bracket the text did not open"
        else:
            stack.pop()
    return f"`{stack[-1]}` is never closed" if stack else ""


def _edit_shape(base_text: str, start: int, end: int, added: str, lexer) -> str:
    """"" when replacing `base_text[start:end]` (the removed text) by `added` is a well-shaped edit, else the reason, one sentence (a
    refusal is built from it by the caller; nothing is written here). Both texts must have the SAME line breaks (count and kind, so CRLF
    stays CRLF) and differ once their ends are stripped. With a `lexer` (the table reader): each of the two has every bracket paired in
    order and ends in code (a text that opens a bracket it does not close, closes one it did not open, or ends inside a string is refused),
    and the whole new text's bracket counts are the base's minus the removed text's plus the added text's with the same end state - the
    arithmetic `_with_marker` uses, so `expect(r.status(), m)` with `actual: "500"` holds (one pair removed, none added) and a balanced
    edit is never refused for its brackets. `lexer` None (the AST reader) checks the line breaks and the difference only: the caller
    parses the new text. Never a judgment of what the edit means."""
    removed = base_text[start:end]
    if LINE_BREAK.findall(removed) != LINE_BREAK.findall(added):
        return "the edit would change the line breaks (count or kind): an edit may not move a line or turn CRLF into LF"
    if removed.strip() == added.strip():
        return "the new text equals the old once its ends are stripped: nothing would change"
    if lexer is None:
        return ""
    parts = {}
    for label, part in (("removed", removed), ("added", added)):
        code, skeleton, state = lex(part, lexer)
        if state != "code":
            return f"the {label} text ends inside {state}, not in code"
        broken = _paired(skeleton)
        if broken:
            return f"the {label} text's brackets are not balanced ({broken})"
        parts[label] = {char: skeleton.count(char) for char in OPEN_BRACKETS + CLOSE_BRACKETS}
    base, base_state = lexical_shape(base_text, lexer)
    new_text = base_text[:start] + added + base_text[end:]
    if lexical_shape(new_text, lexer) != ({char: base[char] - parts["removed"][char] + parts["added"][char] for char in base}, base_state):
        return "the edit would change the lexical state or the brackets other than by its own"
    return ""


def _statement_text_py(node, text: str) -> str:
    """The statement of a Python check as `checks_of` hashes it (a `with` is its header): the join key of a stored model."""
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return "with " + ", ".join(ast.get_source_segment(text, item.context_expr) or "" for item in node.items)
    return ast.get_source_segment(text, node) or ""


def _located(data: bytes, spec: dict, check: dict) -> dict:
    """Where ONE check of `checks_of`'s list stands in `data` (the bytes of its file): `{reader, text, bom, shown, start, end, form, ...}`
    with the statement's span `[start, end)` in characters of `text` (the BOM cut). The check is found by the readers `checks_of` lists it
    through (`_table_rows` for the table reader: the very function `checks_of` lists with, so a scope's opening head and a closing call take no
    number here either; `_python_checks` for the AST reader): the `#n` of its key is the n-th row of its LINE as numbered there (any text,
    F1: one ordinal, AR-13), a `#n` beyond the count is refused with the true count and the keys that stand, and that check must still have the key's form and `statement_sha`: a statement that is no longer there is a refusal,
    never a nearby one. The table reader reads a file with the
    entry's lexer, the AST reader parses it; a file neither can read is the refusal they already give."""
    shown, key = check.get("file") or spec["file"], check["key"]
    bom = data.startswith(_MODEL_BOM)
    raw = data[len(_MODEL_BOM):] if bom else data
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Refusal(f"probe_by_code: {shown} is not UTF-8 ({exc.reason} at byte {exc.start}); a file read in the wrong encoding is "
                      "never edited. Nothing was changed.") from exc
    tail = key.rsplit(":", 1)[-1]
    occurrence = int(tail.split("#", 1)[1]) if "#" in tail and tail.split("#", 1)[1].isdigit() else 1
    reader, hits, refused = _reader_entry(spec), [], None
    ctx = {"reader": reader, "text": text, "bom": bom, "shown": shown, "key": key, "line": check["line"], "end_line": check["end_line"]}
    if reader is not None:
        src = Source(text, reader["lexer"], shown)
        _refuse_conditional_compilation(src, reader, shown, spec["language"])
        # the rows of the line are the rows `checks_of` numbered, through the same function (F1: one numbering, AR-13): a scope's opening
        # head and a closing call took no number there and take none here, so `#n` is the n-th row of the line by the `ordinal` it carries
        listed = _table_rows(src, reader, shown, [], AD.soft_scopes_of(reader, []), [])
        for row in sorted((r for r in listed if r["line"] == check["line"]), key=lambda r: r["ordinal"]):
            if row["refusal"] is not None:
                refused = refused or row["refusal"]
                hits.append(None)                       # it still holds its ordinal on the line
                continue
            hits.append({"start": row["begin"], "end": row["end"], "form": reader["assertions"][row["form"]], "index": row["form"],
                         "sha": sha256(" ".join(row["text"].split()).encode("utf-8")), "node": None})
        ctx["src"] = src
    else:
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            raise Refusal(f"{shown} does not parse: {exc}") from exc
        starts = _line_starts(raw)
        chars = lambda offset: len(raw[:offset].decode("utf-8"))  # noqa: E731  (ast columns are UTF-8 bytes)
        for first, _last, form_id, node, _col, row, _name in _python_checks(tree, _python_entry()[1]["forms"], text):
            if first == check["line"]:
                begin, end = _span(starts, node)
                hits.append({"start": chars(begin), "end": chars(end), "form": row, "index": form_id, "node": node,
                             "sha": sha256(" ".join(_statement_text_py(node, text).split()).encode("utf-8"))})
        ctx["tree"], ctx["chars"] = tree, chars
    if occurrence > len(hits):
        stand = ", ".join(f"{shown}:{check['line']}" + (f"#{n}" if n > 1 else "") for n in range(1, len(hits) + 1))
        raise Refusal(f"probe_by_code: the check {key} is the {occurrence}th check on line {check['line']} of {shown}, "
                      f"and only {len(hits)} stand there" + (f" (the keys that do: {stand})" if hits else "") + ". Nothing was changed.")
    # `#n` is the n-th check of the line in head order, whatever its text: the order `checks_of` numbers them (one ordinal, AR-13).
    hit = hits[occurrence - 1]
    if hit is None and refused is not None:
        raise refused
    if hit is None or hit["index"] != check["form"] or hit["sha"] != check["statement_sha"]:
        raise Refusal(f"probe_by_code: the check {key} (line {check['line']} of {shown}) is not in these bytes as `checks_of` listed it: "
                      "the check that stands in its place on that line is of another form or text any more, so a model written for it "
                      "is never applied to another check. Nothing was changed.")
    ctx.update({k: v for k, v in hit.items() if k not in ("index", "sha")})
    return ctx


def _py_actual_node(node, form: dict, number):
    """The AST node of a Python check that holds the value it reads, None when the form does not say or the statement has no such
    node: an `assert` reads the LEFT of its comparison (`number` "compare_left"), a call form the `number`th positional argument
    (the head call's, for a chain). Pure."""
    if isinstance(node, ast.Assert):
        return node.test.left if number == "compare_left" and isinstance(node.test, ast.Compare) else None
    call = _call_of(node)
    if call is None or not isinstance(number, int) or isinstance(number, bool):
        return None
    if form.get("shape") == "chain":
        call = call.func.value if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Call) else None
    return call.args[number - 1] if call is not None and 1 <= number <= len(call.args) else None


def _py_comment_and_string_spans(text: str) -> tuple:
    """([comment spans], [string spans]) of a Python text, in characters; empty when it cannot be tokenized (the caller then refuses)."""
    import io
    import tokenize
    starts = [0] + [m.end() for m in re.finditer(r"\n", text)]
    comments, strings = [], []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            span = (starts[token.start[0] - 1] + token.start[1], starts[token.end[0] - 1] + token.end[1])
            if token.type == tokenize.COMMENT:
                comments.append(span)
            elif token.type == tokenize.STRING:
                strings.append(span)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return [], []
    return comments, strings


def _body_of(ctx: dict, spec: dict) -> tuple:
    """(begin, end) in characters of the body that HOLDS the check: the table reader's test declaration (by the test's name) when its
    body holds the statement, else the helper declaration that does, the innermost; a refusal when none is told (a check outside any
    function the entry's rows read, e.g. a binding in another test of a file). The AST reader: the innermost function that holds the line."""
    start, shown = ctx["start"], ctx["shown"]
    if ctx["reader"] is None:
        funcs = [n for n in ast.walk(ctx["tree"]) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.lineno <= ctx["line"] <= n.end_lineno]
        if not funcs:
            raise Refusal(f"the check {ctx['key']} stands in no function of {shown}, so the body that holds it is not told")
        inner = max(funcs, key=lambda n: n.lineno)
        raw = ctx["text"].encode("utf-8")
        first = inner.body[0]
        return ctx["chars"](_line_starts(raw)[first.lineno - 1]), start
    src, entry, found = ctx["src"], ctx["reader"], []
    for helper in (False, True):
        matches = declaration_candidates(src, entry, spec["function"], False, shown) if not helper else \
            [m for m in _any_declaration(entry).finditer(src.code) if _in_code(src, m.start())]
        for match in matches:
            try:
                opener, closer = body_span(src, entry, match, helper, shown)
            except Refusal:
                continue
            if opener < start < closer:
                found.append((opener + 1, start))
    if not found:
        raise Refusal(f"the body that holds the check {ctx['key']} is not told (it stands in no declaration of the test or of a helper "
                      f"the {spec['language']} entry reads): code before it cannot be bounded")
    return max(found)


def _region_of(ctx: dict, spec: dict, kind: str) -> tuple:
    """(begin, end) in characters of what a model of `kind` may edit for the located check, or a Refusal that says why not. `actual`: the
    argument of the check's call that holds the value (`AD.actual_arg_of`; `_call_arguments` splits the call, and a call it cannot split
    is a refusal, never a guess) or the left of a Python comparison. `find`: from the start of the body that holds the check to the
    start of its statement - never the statement."""
    if kind == "actual":
        number = AD.actual_arg_of(ctx["form"])
        label = ctx["form"].get("id") or ctx["form"].get("head") or ctx["form"].get("shape")
        if number is None:
            raise Refusal(f"the form of the check {ctx['key']} (`{label}`) names no argument that holds the value it reads (no verified "
                          "`actual_arg` row: a form in doubt has no key), so `actual` cannot place the edit")
        if ctx["reader"] is None:
            node = _py_actual_node(ctx["node"], ctx["form"], number)
            if node is None:
                raise Refusal(f"the check {ctx['key']} has no {'comparison to read the left of' if number == 'compare_left' else 'argument ' + str(number)} "
                              "in its statement, so `actual` cannot place the edit")
            raw = ctx["text"].encode("utf-8")
            begin, end = _span(_line_starts(raw), node)
            return ctx["chars"](begin), ctx["chars"](end)
        if not isinstance(number, int):
            raise Refusal(f"the form of the check {ctx['key']} reads its value as `{number}`, which the table reader cannot place")
        call = _call_arguments(ctx["src"], ctx["start"], ctx["end"])
        if call is None:
            raise Refusal(f"the statement of the check {ctx['key']} does not open with a plain call whose arguments can be told, so "
                          "the argument that holds the value is not found: never a guess")
        if number > len(call[2]):
            raise Refusal(f"the call of the check {ctx['key']} has {len(call[2])} argument(s) and its form reads the value in argument {number}")
        return call[2][number - 1]
    begin, end = _body_of(ctx, spec)
    text = ctx["src"].code if ctx["reader"] is not None else ctx["text"]
    if not text[begin:end].strip():
        raise Refusal(f"no line of the body stands before the statement of the check {ctx['key']}, so `find` has nowhere to look")
    return begin, end


def _check_doors(data: bytes, spec: dict, check: dict) -> list:
    """The kinds of model that OPEN for one check (the doors `_models_refusal` prints): `actual` when its form names the argument that
    holds the value and the call splits, `find` when code stands before its statement, `invert` when its form has an inversion,
    `not_here` always, `product` always (the product-breaking probe reads no table: a plan only exists for a language with an entry).
    A file that cannot be read opens only the last two."""
    doors = []
    try:
        ctx = _located(data, spec, check)
    except Refusal:
        return ["not_here", "product"]
    for kind in ("actual", "find"):
        try:
            _region_of(ctx, spec, kind)
            doors.append(kind)
        except Refusal:
            pass
    return doors + (["invert"] if check.get("invertible") else []) + ["not_here", "product"]


def _model_region(data: bytes, spec: dict, check: dict, kind: str) -> dict:
    """The located check with the region a model of `kind` ("actual" or "find") may edit: `_located`'s dict plus `region` (begin, end;
    characters of `ctx["text"]`) - or a Refusal naming the check and the doors that DO open for it. Errs to refusal. POSITION INVARIANT: the
    region of `actual` is the value alone and the region of `find` ends where the statement begins, so the matcher, the expected value,
    `.not` and the message of any check are outside every region a model can have."""
    ctx = _located(data, spec, check)
    try:
        ctx["region"] = _region_of(ctx, spec, kind)
    except Refusal as exc:
        doors = [d for d in _check_doors(data, spec, check) if d != kind]
        raise Refusal(f"probe_by_code: {exc}. Doors that open for it: {', '.join(doors)}; or report `unverified` for this check. "
                      "Nothing was changed.") from None
    return ctx


def _model_edit(entry: dict, ctx: dict, spec: dict) -> dict:
    """The edit ONE `actual` or `find` entry makes, from its located check: `{spans: [(begin, end)], edits: [(begin, end, new)],
    statement_after, removed, added}` in characters of the file's text, all in the ORIGINAL coordinates (so edits of several entries
    apply bottom-up). Every refusal names the check and what failed; nothing is written."""
    key, text, reader = entry["check"], ctx["text"], ctx["reader"]
    lexer = reader["lexer"] if reader is not None else None
    start, end = ctx["start"], ctx["end"]
    begin, stop = ctx["region"]
    if entry["kind"] == "actual":
        added = entry["actual"].strip()
        if reader is None:
            try:
                ast.parse(added, mode="eval")
            except SyntaxError as exc:
                raise Refusal(f"probe_by_code: the `actual` of {key} is not one expression ({exc.msg}), so it cannot replace the value the "
                              "check reads. Nothing was changed.") from None
    else:
        added = entry["replace"]
        find = entry["find"]
        hay = ctx["src"].code[begin:stop] if reader is not None else text[begin:stop]
        comments, strings = ([], []) if reader is not None else _py_comment_and_string_spans(text)
        spots = []
        for hit in re.finditer(re.escape(find), hay):
            at = begin + hit.start()
            first = at + (len(find) - len(find.lstrip()))
            if reader is not None and ctx["src"].skeleton[first] != ctx["src"].code[first]:
                continue                                    # starts inside a string or a comment
            if any(a <= first < b for a, b in comments) or any(a < first < b for a, b in strings) \
                    or any(a < at + len(find) and at < b for a, b in comments):
                continue
            spots.append(at)
        if len(spots) != 1:
            inside = find in text[start:end]
            raise Refusal(f"probe_by_code: the `find` of {key} stands {len(spots)} times between the start of the body that holds the check and "
                          f"its statement, not once" + (" - it lies inside the check's statement, which a model never edits (the matcher, the "
                                                          "expected value and the message stay as written; `actual` replaces the value) -" if inside else "")
                          + ". Nothing was changed.")
        begin, stop = spots[0], spots[0] + len(find)
    reason = _edit_shape(text, begin, stop, added, lexer)
    if reason:
        raise Refusal(f"probe_by_code: the model of {key} was not applied: {reason}. Nothing was changed.")
    new_text = text[:begin] + added + text[stop:]
    shift = len(added) - (stop - begin)
    if reader is not None:
        try:
            fresh = Source(new_text, lexer, ctx["shown"])
        except Refusal as exc:
            raise Refusal(f"probe_by_code: the model of {key} leaves a file the reader cannot read ({fold(str(exc), 140)}). Nothing was changed.") from None
        new_start = start + (shift if stop <= start else 0)
        new_end = end + shift
        if entry["kind"] == "actual":
            call = _call_arguments(fresh, new_start, new_end)
            old = _call_arguments(ctx["src"], start, end)
            if call is None or len(call[2]) != len(old[2]) or any(
                    new_text[a:b] != text[c:d] for i, ((a, b), (c, d)) in enumerate(zip(call[2], old[2])) if i != AD.actual_arg_of(ctx["form"]) - 1):
                raise Refusal(f"probe_by_code: the `actual` of {key} would change the call's other arguments or their number (it reaches the "
                              "matcher, the expected value or the message): a model edits the value alone. Nothing was changed.")
        try:
            span = _statement_span(fresh, new_start, reader["statement_end"], len(fresh.skeleton), ctx["shown"])
        except Refusal:
            span = None
        if span != (new_start, new_end):
            raise Refusal(f"probe_by_code: the model of {key} would change where the check's statement ends (a `;` or a line break inside "
                          "the new text). Nothing was changed.")
    else:
        try:
            tree = ast.parse(new_text)
        except SyntaxError as exc:
            raise Refusal(f"probe_by_code: the model of {key} does not parse ({exc.msg} at line {exc.lineno}), so it was not applied. "
                          "Nothing was changed.") from None
        if entry["kind"] == "actual":
            number = AD.actual_arg_of(ctx["form"])
            fresh = next((s for s in ast.walk(tree) if isinstance(s, ast.stmt) and type(s) is type(ctx["node"])
                          and (s.lineno, s.col_offset) == (ctx["node"].lineno, ctx["node"].col_offset)), None)
            new_node = _py_actual_node(fresh, ctx["form"], number) if fresh is not None else None
            old_node = _py_actual_node(ctx["node"], ctx["form"], number)

            def rest(statement, actual):
                return ast.dump(statement).replace(ast.dump(actual), "ACTUAL", 1)

            if new_node is None or rest(fresh, new_node) != rest(ctx["node"], old_node):
                raise Refusal(f"probe_by_code: the `actual` of {key} would change more than the value the check reads (it reaches the matcher, "
                              "the expected value or the message): a model edits the value alone. Nothing was changed.")
    statement = new_text[start + (shift if stop <= start else 0):end + shift]
    return {"spans": [(begin, stop)], "edits": [(begin, stop, added)], "statement_after": statement, "removed": text[begin:stop],
            "added": added}


def _refuse_overlap(spans: list) -> None:
    """A Refusal naming BOTH entries when two of `spans` ([((begin, end), entry)]) edit the same bytes (identical edits included);
    nothing otherwise."""
    ordered = sorted(spans, key=lambda s: (s[0][0], s[0][1]))
    for (a, first), (b, second) in zip(ordered, ordered[1:]):
        if a[1] > b[0] or a == b:
            raise Refusal(f"probe_by_code: the model of {first['check']} (models[{first['index']}]) and the model of {second['check']} "
                          f"(models[{second['index']}]) edit the same bytes: regions never overlap, so write one entry or move one `find`. "
                          "Nothing was changed.")


def _marked_statement(ctx: dict, edit, token: str) -> dict:
    """The check's statement WITH the factory's marker put in, after the value edit `edit` ((begin, stop, added) inside the statement,
    or None): `{applied, after, marker, form, note}` (t-2064 P3; `ctx` is `_located`'s). The table reader goes through `_with_marker` with
    no `fires_as` (nothing was inverted), the AST reader through `_assert_with_marker` / `_assert_that_with_marker`. EVERY way the
    marker cannot go in - a form that takes no message, a shape with no place for one, a guard of `_with_marker`, an edit that no longer
    parses - answers `applied` False, `after` the statement as edited, `marker` and `form` "" and a note that says why: the edit is
    still planned and the row goes to the role. The error direction is toward "the role decides", never toward `intended_failure`."""
    text, start, end, reader, form = ctx["text"], ctx["start"], ctx["end"], ctx["reader"], ctx["form"]
    mutated, shift = text, 0
    if edit is not None:
        mutated, shift = text[:edit[0]] + edit[2] + text[edit[1]:], len(edit[2]) - (edit[1] - edit[0])
    after = mutated[start:end + shift]

    def plain(note: str) -> dict:
        return {"applied": False, "after": after, "marker": "", "form": "", "note": note}

    if reader is not None:
        if not AD.message_forms(form):
            return plain("the form takes no message, so the check carries no factory marker: the row goes to the role")
        marked, variant, note = _with_marker(mutated, start, after, text, reader, form, None, token)
        if not variant:
            return plain(note or "no marker was put in: the row goes to the role")
        return {"applied": True, "after": marked, "marker": MARKER_PREFIX + token, "form": variant, "note": ""}
    if not form.get("message"):
        return plain(f"the form {form['id']} takes no message, so the check carries no factory marker: the row goes to the role")
    expression = AD.marker_expression(_python_entry()[1], token)
    if not expression:
        return plain("the entry declares no marker_expr, so no marker was put in: the row goes to the role")
    raw = mutated.encode("utf-8")
    try:
        tree = ast.parse(mutated)
    except SyntaxError:
        return plain("the edited file could not be read again for the marker: the row goes to the role")
    node = ctx["node"]
    fresh = next((s for s in ast.walk(tree) if type(s) is type(node) and (s.lineno, s.col_offset) == (node.lineno, node.col_offset)), None)
    if fresh is None:
        return plain("the edited statement could not be found again for the marker: the row goes to the role")
    starts = _line_starts(raw)
    first, last = _span(starts, fresh)
    rep = Replacement(fresh, raw, starts, lambda n: raw[slice(*_span(starts, n))], raw[first:last].count(b"\n"))
    replaced = _assert_with_marker(rep, expression) if form["shape"] == "assert" else _assert_that_with_marker(rep, form, expression)
    if replaced is None:
        return plain(f"the statement of the form {form['id']} has no place the marker can be put (the row's message slot does not fit it): "
                     "the row goes to the role")
    marked = replaced.decode("utf-8")
    try:
        ast.parse(mutated[:start] + marked + mutated[end + shift:])
    except SyntaxError:
        return plain("the statement with the marker does not parse: the row goes to the role")
    if marked.count("\n") != after.count("\n"):
        return plain("the statement with the marker would change the line count: the row goes to the role")
    return {"applied": True, "after": marked, "marker": MARKER_PREFIX + token, "form": form["id"], "note": ""}


def plan_model(data: bytes, spec: dict, entries: list, checks: list, tokens: dict = None, instance_id: str = "") -> tuple:
    """(the mutated bytes, [one detail per entry]) for ONE plan row, which is ONE file (t-2064 P3; nothing is written, run or judged).

    `entries` are entries `load_models` returned for this row's checks - kinds `actual`, `find` and `invert`; `not_here` and `product`
    make no edit and are filtered before this call (one reaching it is a refusal). `checks` is `checks_of`'s list (each entry's `check`
    is a key of it: an unknown key is a refusal listing the plan's keys). `actual` replaces the argument that holds the value the check
    reads, `find` replaces code that stands once between the start of the body that holds the check and its statement, `invert` is the
    inversion `plan_detector_mutation` / `plan_mutation` plan for that line; each `_model_region` / `_edit_shape` guard is a refusal naming
    the check. REGIONS MUST NOT OVERLAP (two entries editing the same bytes: a refusal naming both, identical edits included), and the
    edits apply BOTTOM-UP (highest offset first) so earlier offsets hold. The file keeps its BOM, its line ends and its line count. A
    `find` may break several checks; each is read by its own entry's marker, and then `supposes` is not what failed for the second.

    `tokens` ({check key: `marker_token`}; absent, or a key with none, = no marker for that check): after the value edit the check AS
    WRITTEN gets ONE marker, `_marked_statement` (the statement's edit, so it joins the overlap list; an `invert` entry gets the
    planner's own). A check whose form takes no message, or where a guard of the marker fails, is planned all the same, with no marker and a
    `message_note` that says why: the row goes to the role. `instance_id` names an `invert`'s plan."""
    by_key = {check["key"]: check for check in checks}
    if not entries:
        raise Refusal("probe_by_code: plan_model got no entry: nothing to edit. Nothing was changed.")
    shown = {by_key[e["check"]].get("file") for e in entries if e["check"] in by_key}
    planned, edits, details = [], [], []
    bom = data.startswith(_MODEL_BOM)
    for entry in entries:
        key = entry["check"]
        if key not in by_key:
            raise Refusal(f"probe_by_code: the check {key!r} is not a key of this plan; the plan's keys are {', '.join(by_key) or '(none)'}. "
                          "Nothing was changed.")
        if entry["kind"] not in ("actual", "find", "invert"):
            raise Refusal(f"probe_by_code: the entry for {key} is of kind `{entry['kind']}`, which makes no edit; it is filtered before the plan. "
                          "Nothing was changed.")
    if len(shown) != 1:
        raise Refusal("probe_by_code: the entries of one plan row name checks in more than one file; a row is one file. Nothing was changed.")
    for entry in entries:
        check = by_key[entry["check"]]
        if entry["kind"] == "invert":
            planned.append(_invert_edit(data, spec, entry, check, tokens, instance_id))
        else:
            ctx = _model_region(data, spec, check, entry["kind"])
            planned.append(dict(_model_edit(entry, ctx, spec), ctx=ctx))
    text = (data[len(_MODEL_BOM):] if bom else data).decode("utf-8")
    _refuse_overlap([(span, entry) for entry, one in zip(entries, planned) for span in one["spans"]])
    marks = {}          # check key -> `_marked_statement`'s answer: ONE marker per check, whatever the number of entries on it
    for entry, one in zip(entries, planned):
        key, token = entry["check"], (tokens or {}).get(entry["check"], "")
        if entry["kind"] != "invert" and token and key not in marks:
            own = next((e for en, pl in zip(entries, planned) if en["check"] == key and en["kind"] == "actual" for e in pl["edits"]), None)
            marks[key] = _marked_statement(one["ctx"], own, token)
    # the marker edit is the check's STATEMENT: it joins the overlap list, and the `actual` edit it contains is part of it
    carried = [(span, entry) for entry, one in zip(entries, planned) for span in one["spans"]
               if not (entry["kind"] == "actual" and marks.get(entry["check"], {}).get("applied"))]
    for key, mark in marks.items():
        if mark["applied"]:
            first = next(entry for entry in entries if entry["check"] == key)
            ctx = next(one["ctx"] for entry, one in zip(entries, planned) if entry["check"] == key and entry["kind"] != "invert")
            carried.append(((ctx["start"], ctx["end"]), first))
            edits.append((ctx["start"], ctx["end"], mark["after"]))
    _refuse_overlap(carried)
    for entry, one in zip(entries, planned):
        key, mark = entry["check"], marks.get(entry["check"])
        if not (entry["kind"] == "actual" and mark and mark["applied"]):
            edits.extend(one["edits"])
        check = by_key[key]
        if mark:
            message = {"message_marker": mark["marker"], "message_form": mark["form"], "message_note": mark["note"]}
        else:
            message = one.get("message") or {"message_marker": "", "message_form": "", "message_note": "no marker is put in by this call"}
        details.append({"key": key, "probe_kind": entry["kind"], "instance": entry["instance"], "line": check["line"],
                        "end_line": check["end_line"], "file": check["file"], "supposes": entry["supposes"],
                        "reason": entry.get("invert", ""), "removed": one["removed"], "added": one["added"],
                        "statement_before": _statement_before(one),     # q14: the copy record's `statement_before`, as the old road wrote it
                        "statement_after": mark["after"] if mark else one["statement_after"], **message})
    new_text = text
    for begin, stop, added in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):      # bottom-up: an earlier offset still holds
        new_text = new_text[:begin] + added + new_text[stop:]
    if LINE_BREAK.findall(new_text) != LINE_BREAK.findall(text):
        raise Refusal("probe_by_code: the models would change the file's line breaks (internal: every edit keeps them). Nothing was changed.")
    return (_MODEL_BOM if bom else b"") + new_text.encode("utf-8"), details


def _statement_before(one: dict):
    """The text of the statement a planned entry edits, BEFORE the edit (the author's own): an `invert` carries the planner's
    `statement_before`; an `actual` / `find` entry's is the located statement's span of the original text. None when neither is known."""
    if one.get("statement_before") is not None:
        return one["statement_before"]
    ctx = one.get("ctx")
    if isinstance(ctx, dict) and isinstance(ctx.get("text"), str) and "start" in ctx and "end" in ctx:
        return ctx["text"][ctx["start"]:ctx["end"]]
    return None


def _invert_edit(data: bytes, spec: dict, entry: dict, check: dict, tokens, instance_id: str) -> dict:
    """The edit of an `invert` entry: the inversion the existing planner makes for the check's LINE, as a span (the bytes that differ)
    so it composes with the other entries. Refused when the planner's target is not the check (the second check on a line is
    `--at <line>#2`, P4b; a line that starts another check): what is mutated must be what the record says."""
    key = entry["check"]
    if "#" in key.rsplit(":", 1)[-1]:
        raise Refusal(f"probe_by_code: {key} is the second check on its line, which the inversion cannot name by line yet: write a model "
                      "(`actual` or `find`) for it. Nothing was changed.")
    token = (tokens or {}).get(key, "")
    reader = _reader_entry(spec)
    if reader is None:
        mutated, detail = plan_mutation(data, spec, "invert", instance_id or "model", at=check["line"], marker_token=token)
    else:
        mutated, detail, _context = plan_detector_mutation(data, spec, instance_id or "model", at=check["line"], file=check["file"],
                                                           marker_token=token)
    if detail["line"] != check["line"] or detail["form"] != check["form"]:
        raise Refusal(f"probe_by_code: the inversion planned for line {check['line']} is the check at line {detail['line']}, not {key}: "
                      "what is mutated must be what the record says. Nothing was changed.")
    old = (data[len(_MODEL_BOM):] if data.startswith(_MODEL_BOM) else data).decode("utf-8")
    new = (mutated[len(_MODEL_BOM):] if mutated.startswith(_MODEL_BOM) else mutated).decode("utf-8")
    head = 0
    while head < min(len(old), len(new)) and old[head] == new[head]:
        head += 1
    tail = 0
    while tail < min(len(old), len(new)) - head and old[len(old) - 1 - tail] == new[len(new) - 1 - tail]:
        tail += 1
    return {"spans": [(head, len(old) - tail)], "edits": [(head, len(old) - tail, new[head:len(new) - tail])],
            "statement_before": detail.get("statement_before"),
            "statement_after": detail["statement_after"], "removed": old[head:len(old) - tail], "added": new[head:len(new) - tail],
            "message": {key: detail[key] for key in ("message_marker", "message_form", "message_note")}}


def declared_alternative(task_root: Path, case: str, alt: str, cfg) -> tuple:
    """(the declared item | None, why not). The case file is the contract's (`s5_precheck._case_file_of`: a qualified key is that
    area's file), the key is read by `contract.alternatives_from_text`, and the Then must be one of the case's."""
    import s5_precheck as S5
    file = S5._case_file_of(task_root, case, cfg)
    if file is None:
        return None, f"case file of {case} not found"
    try:
        text = Path(file).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, f"case file of {case} cannot be read ({type(exc).__name__})"
    entries, problem = C.alternatives_from_text(text)
    if entries is None:
        return None, (f"the key is malformed: {problem}" if problem else "the `alternatives` key is absent")
    errors = C.alternatives_errors(case, entries, [n for n, _ in S5.then_clauses(text)])     # ONE validity rule, the report's too
    if errors:
        return None, f"the key is malformed: {errors[0]}"
    item = next((e for e in entries if e.get("id") == alt), None)
    if item is None:
        return None, f"{alt} is not declared in {case}"
    return item, ""


def then_assertions(manifest: dict, case: str, then, entry: dict, cfg) -> list:
    """[(file, line)] of the covered `then_bindings` rows of THIS instance for this Then, read through `bindings_of_case` (the one
    reader: area-qualified and instance-only rows included). [] = no covered binding."""
    import s5_precheck as S5
    aliases = set(C.instance_id_aliases(entry, cfg))
    out: list = []
    for row in S5.bindings_of_case(manifest, case, cfg):
        number = row.get("then")
        if row.get("status") != "covered" or isinstance(number, bool) or str(number).strip() != str(then):
            continue
        if str(row.get("instance_id") or "") not in aliases:
            continue
        file, _, line = str(row.get("assertion_ref") or "").rpartition(":")
        if file and line.isdigit() and int(line) > 0 and (file, int(line)) not in out:
            out.append((file, int(line)))
    return out


# --- identity, freshness, naming -----------------------------------------------------------------------------

def alternative_record_path(task_root: Path, iid: str, case: str, alt: str) -> Path:
    """`work/probes/alternative/<IID>--<CASE>--<ALT>.json`: one naming (`proof_level.probe_record_path`), the CANONICAL instance id
    (an alias at probe time and the canonical id in the report find one file), the case in the key (an instance that covers two
    cases, both with an ALT-1, keeps two records)."""
    return proof_level.probe_record_path(task_root, f"{iid}--{case}--{alt}", kind="alternative")


def _reading_sha(item: dict) -> str:
    """The ONE formula of an alternative's reading hash (the run, the gap record and `alternative_now` all read it here)."""
    return sha256(json.dumps({"then": item.get("then"), "reading": str(item.get("reading") or "").strip()},
                             sort_keys=True).encode("utf-8"))


def alternative_now(entry: dict, task_root: Path, root: Path, item: dict, refs, target_rels=()) -> dict:
    """What the world says NOW, for `alternative_fresh`: the reading's hash, the test's raw sha and per-test identity (ONE read,
    `proof_level.instance_identity`), the Then's bound assertions (None when not asked) and the raw sha of EVERY file the model edited
    (`target_rels`: one path or a list; `target_shas[path]` is "" for a file that cannot be read now)."""
    ident = proof_level.instance_identity(entry, task_root, root)
    rels = [target_rels] if isinstance(target_rels, str) else list(target_rels or ())
    target_shas: dict = {}
    for target_rel in rels:
        if not target_rel:
            continue
        try:
            target_shas[str(target_rel)] = sha256((Path(root) / target_rel).read_bytes())
        except OSError:
            target_shas[str(target_rel)] = ""
    identity = ident.get("instance_identity") or {}
    return {"reading_sha": _reading_sha(item), "test_file_sha256": ident.get("input_hash") or "",
            "instance_content_sha": identity.get("instance_content_sha") or "", "instance_identity": identity,
            "assertion_refs": None if refs is None else [[f, n] for f, n in refs],
            "test_file": proof_level.test_file_of(entry), "target_shas": target_shas}


def _recorded_edits(record: dict) -> list:
    """The files a record's run edited: `mutated_files` (every one), else the old record's lone `mutated_file`."""
    many = record.get("mutated_files")
    rows = many if isinstance(many, list) and many else [record.get("mutated_file")]
    return [r for r in rows if isinstance(r, dict) and r.get("path") and r.get("sha256")]


def alternative_fresh(record: dict, now: dict) -> tuple:
    """(True, "") or (False, "stale: <which>"). ONE predicate for the repeat check AND the report. Fresh iff the reading and its
    Then are the same, the test is (the raw sha, or a non-empty equal per-test identity: a neighbour's comment edit keeps it),
    the model's target file (when it is not the test) holds the bytes the model ran on, and the Then is bound to the same
    assertions. A record that never read the test (a tooling gap) is held to the reading alone. Any miss is stale: an old proof
    never stands for new bytes or a new reading."""
    if not isinstance(record, dict):
        return False, "stale: the record is unreadable"
    if record.get("reading_sha") != now.get("reading_sha"):
        return False, "stale: the case's reading of this Then changed"
    rec_raw, rec_id = record.get("test_file_sha256") or "", record.get("instance_content_sha") or ""
    if rec_raw or rec_id:
        cur_raw, cur_id = now.get("test_file_sha256") or "", now.get("instance_content_sha") or ""
        if not ((rec_raw and cur_raw and rec_raw == cur_raw) or (rec_id and cur_id and rec_id == cur_id)):
            return False, "stale: the test's bytes changed since this record"
    for target in _recorded_edits(record):      # EVERY edited file that is not the test (a helper's edit never leaves `proven` standing)
        if _same_file(str(target["path"]), now.get("test_file") or ""):
            continue
        current = (now.get("target_shas") or {}).get(str(target["path"]))
        if current is None or current == "":
            return False, f"stale: the file the model ran on ({target['path']}) cannot be read now, so its bytes are not known to be the proved ones"
        if target["sha256"] != current:
            return False, "stale: the file the model ran on changed since this record"
    if record.get("assertion_refs") is not None and now.get("assertion_refs") is not None \
            and [list(r) for r in record["assertion_refs"]] != now["assertion_refs"]:
        return False, "stale: the Then is bound to another assertion now"
    return True, ""


def _read_alt_record(path: Path) -> tuple:
    """(the record | None, why none). Missing is (None, ""): an unreadable file is said, never read as a proof."""
    if not path.is_file():
        return None, ""
    data = read_json(path, kind=dict)       # the package's one JSON reader (dup ratchet: no private copy)
    return (data, "") if data is not None else (None, "the record file cannot be read as one JSON object")


def _alt_answer(verdict: str, iid: str, token: str, why: str, notes=()) -> dict:
    """An ANSWER, not a record: nothing was mutated, launched or written (exit 1 for `unknown`, 0 for `already_probed`)."""
    return {"verdict": verdict, "instance_id": iid, "alternative": token, "why": why, "words": why, "notes": list(notes)}


def _store_alternative(out: Path, record: dict, old, reason: str) -> None:
    """Write the record atomically; the record it replaces (any verdict) is folded into `superseded[]` with its reason, so the
    old verdict stays visible (no model shopping)."""
    if isinstance(old, dict):
        record["superseded"] = list(old.get("superseded") or []) + [
            {"verdict": old.get("verdict"), "recorded_at": old.get("recorded_at"), "model_sha": old.get("model_sha"),
             "reason": reason}]
    atomic_json(out, record)


def _alt_base(ctx: ProbeCtx, iid: str, token: str, item: dict, out: Path, now: dict) -> dict:
    """The fields every alternative record carries (a gap or a run), under the names the exit and print paths of `main` read."""
    return {"schema_version": 1, "probe_tool": "probe_by_code.py", "task": ctx.task, "dispatch_id": ctx.dispatch,
            "instance_id": iid, "case": ctx.case, "alternative": token, "then": item["then"], "reading": item["reading"],
            "reading_sha": now["reading_sha"], "test_node": ctx.spec["node"], "verdict": "gap", "mutation": ALTERNATIVE,
            "mutation_kind": ALTERNATIVE_KIND, "proof_level": None, "expected_location": None,
            "expected_reason": f"alternative {token}", "actual_location": None, "actual_reason": None, "failure_kind": None,
            "observed": {}, "test_file_sha256": None, "instance_content_sha": "", "mutated_file": None,
            "assertion_refs": None, "evidence_ref": None, "evidence_refs": [], "request": None, "restore": None,
            "superseded": [], "notes": [], "record": out.relative_to(ctx.task_root).as_posix(),
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def _alternative_gap_record(ctx: ProbeCtx, iid: str, token: str, item: dict, out: Path, old, *, cause: str, why: str,
                            now: dict, door: str = "", model: dict = None, copy_notes=()) -> dict:
    """The record `gap`: the probe could not model B, and says who owns that (`cause: model` the critic's own gap, the one a `gap` entry of
    the model file writes; `tooling` the factory's). It is the critic's citable word and never a verdict on the test."""
    record = _alt_base(ctx, iid, token, item, out, now)
    record.update(cause=cause, why=why, door=door, notes=list(copy_notes))
    if now.get("test_file_sha256") and cause == "model":
        record.update(test_file_sha256=now["test_file_sha256"], instance_content_sha=now["instance_content_sha"])
    if model:
        record.update(model=model["content"], model_sha=model["sha256"])
    _store_alternative(out, record, old, f"rerun after {old.get('verdict')}" if isinstance(old, dict) else "")
    return record


def _alternative_refusal(ctx: ProbeCtx, token: str, item: dict, what: str) -> Refusal:
    """A refusal of an alternative call, in the call's own terms: the reading, its Then, what is wrong and the door (FR-1, FR-2)."""
    return Refusal(f"probe_by_code: {token} (Then {item['then']} of {ctx.case}) on {ctx.spec['file']} ({ctx.spec['node']}): {what}. `probe_by_code.py "
                   f"--task <T> --instance <I> --test <node> --plan` lists the checks and the Then each one belongs to. Nothing was changed.")


def _probe_alternative(ctx: ProbeCtx, run_cwd: Path, locks: list, token: str, model_path: str, timeout: float) -> dict:
    """One alternative call (`--alternative <case>:ALT-n`, t-2064 P5): the entries of the reading are walked on the ONE road (`_walk_plan`),
    on every language, with the marker and the author's green run (`author_green_of`) in the joint judge. SELECTION: the entries of the
    model file (`--model`, else `work/probe-models/<dispatch>.json`) that carry exactly this `alternative`; a plain entry (no `alternative`) is
    never read here and an alternative's entry never by a plain walk (`_entries_for`), so the two never meet on one check. Its PLAN is those
    keys, which must be checks of the reading's Then (an entry on another check: refusal; an unknown key: `load_models`' refusal naming
    the plan's keys); a check of the Then with no entry of the reading stays unproved and is named in the record (`unmodelled`): the
    record's verdict is then `incomplete`, never `intended_failure` (no refusal). An entry of a kind that does not suppose a value
    (`invert`, `not_here`, `product`) is a refusal: only `actual` and `find` model a reading. A `gap` entry with no other entry of the
    reading writes `_alternative_gap_record` and runs nothing; a gap beside entries is a refusal (a reading is modelled or it is a gap).
    WRITES: the per-check records and the ONE record go to `work/probes/checks/<IID>--<CASE>--<ALT>--L..` and
    `work/probes/alternative/<IID>--<CASE>--<ALT>.json` (`ctx.alt`: `_records_id`, `_aggregate_record`), never to the plain aggregate and
    never a live receipt. POSITION of the refusals: after the declaration is read (an undeclared ALT is an ANSWER, never a record) and the
    plan is read off the author's bytes, before any lock or byte is written."""
    case, alt = parse_alternative_token(token)
    ctx = ctx._replace(alt=token)
    task_root, root, case_cfg = ctx.task_root, ctx.root, C.case_config()
    iid = C.test_instance_id(ctx.entry) or ctx.instance_id
    item, why = declared_alternative(task_root, case, alt, case_cfg)
    if item is None:
        return _alt_answer("unknown", iid, token, why)
    out = alternative_record_path(task_root, iid, case, alt)
    old, _problem = _read_alt_record(out)
    settled = _settle_dead_copy(ctx, locks)
    checks, _runs, _plan_notes = _plan_of_test(ctx, run_cwd)
    if not checks:
        raise _empty_plan_refusal(ctx)
    then_checks = [c for c in checks if c.get("then") is not None and str(c["then"]).strip() == str(item["then"])]
    then_keys = [c["key"] for c in then_checks]
    items = _door_items(ctx, checks)
    shown = str(model_path or "").strip() or f"work/probe-models/{ctx.dispatch}.json"
    given = Path(shown)
    items_of_then = [{**i, "doors": [d for d in i["doors"] if d in ALTERNATIVE_KINDS]} for i in items if i["key"] in then_keys]

    def need(why_text: str) -> Refusal:
        if not then_checks:
            return _alternative_refusal(ctx, token, item, f"no check of the test is labelled with Then {item['then']} by a covered binding of {iid}, so "
                                                          "there is nothing to walk for the reading")
        return _models_refusal(shown, items_of_then, why_text)

    if not (given if given.is_absolute() else task_root / given).is_file():
        raise need(f"no model file; a reading is walked from the entries of it that carry `alternative: {token}`")
    mine = [m for m in load_models(task_root, shown, items) if m["alternative"] == token]
    gaps, values = [m for m in mine if m["kind"] == "gap"], [m for m in mine if m["kind"] != "gap"]
    if gaps and values:
        raise _alternative_refusal(ctx, token, item, f"the model file holds a `gap` for the reading AND entries for it (models[{gaps[0]['index']}] and "
                                                     f"models[{values[0]['index']}]): a reading is modelled or it is a gap, not both")
    if gaps:        # the critic says B cannot be modelled: presence only, a record, no run (item 4)
        _key, copy_notes = _lock_test(ctx, locks)
        manifest_gap = {"content": {"alternative": token, "gap": gaps[0]["gap"]}, "sha256": _entry_sha(gaps[0])}
        return _alternative_gap_record(ctx, iid, token, item, out, old, cause="model", why=gaps[0]["gap"], model=manifest_gap, copy_notes=copy_notes + settled,
                                       now=alternative_now(ctx.entry, task_root, root, item, None))
    if not mine:
        raise need(f"the file holds no entry that carries `alternative: {token}` (a plain entry is not read by this call)")
    if not then_checks:
        raise need("")
    others = sorted({str(m.get("instance") or "") for m in values} - {""} - {"", ctx.instance_id, iid})
    values = list(_pick_entries(ctx, values).values())      # the ONE pick (as `_walk_plan` and the report): an entry of another instance is not this call's
    if not values:
        raise need(f"every entry of the reading `{token}` in the model file names another instance ({', '.join(others)}), and none is for {iid} (or has an "
                   f"empty `instance`): add entries with `\"instance\": \"{iid}\"` or without `instance`")
    wrong = [m for m in values if m["kind"] not in ALTERNATIVE_KINDS]
    if wrong:
        raise _alternative_refusal(ctx, token, item, f"models[{wrong[0]['index']}] is a `{wrong[0]['kind']}` entry, and a reading is modelled by `actual` or "
                                                     "`find` only (a value the product would return under B); `gap` says B cannot be modelled")
    foreign = [m for m in values if m["check"] not in then_keys]
    if foreign:
        raise _alternative_refusal(ctx, token, item, f"models[{foreign[0]['index']}] names the check {foreign[0]['check']!r}, which is not a check of that "
                                                     f"Then; its checks are {', '.join(then_keys)}")
    keys = {m["check"] for m in values}
    chosen = [c for c in checks if c["key"] in keys]
    manifest = C.load_json(ctx.manifest_path) if ctx.manifest_path.is_file() else {}
    refs = then_assertions(manifest, case, item["then"], ctx.entry, case_cfg)
    unmodelled = [key for key in then_keys if key not in keys]
    plan = {"checks": chosen, "runs": run_plan(chosen), "notes": list(settled), "unmodellable": {}, "only": [],
            "alternative": {"item": item, "then_checks": then_keys, "unmodelled": unmodelled, "assertion_refs": [[f, n] for f, n in refs]}}
    _shape_refusals(ctx, values, chosen)        # R6 (fix round A) on the alternative's walk too: a request the builder refuses is refused before a byte
    _locating_refusals(ctx, values, chosen)     # q11 on the alternative's walk too: a check under `#if` is refused before a byte
    walk = _walk_plan(ctx, plan, values, locks, timeout)
    record = walk.get("record")
    if record is None:
        raise Refusal("probe_by_code: the record of the reading could not be written (" + "; ".join(str(n) for n in walk.get("notes") or [])[:300]
                      + "). The per-check records stand under work/probes/checks/; the same call again continues.")
    return record


# --- the report: what is owed, stale or proven ---------------------------------------------------------------------

def alternatives_report(task_root: Path, root: Path, instance=None) -> list:
    """[row]: one per declared alternative of every (instance, case) of the manifest, read-only. `state` is `proven`,
    `not_separated`, `wrong_location`, `gap`, `stale` (a fresher bytes/reading/binding than the record: never `proven`), `unknown`
    (no record, an unreadable one, one that names another case, instance or alternative, or an unjudged run), or `case_unreadable`
    (the case file is missing or its key is malformed: never read as "nothing owed", AR-28). A case with no key or `[]` has no row."""
    import s5_precheck as S5
    case_cfg = C.case_config()
    manifest_path = Path(task_root) / "work" / "automation-manifest.json"
    if not manifest_path.is_file():
        return [{"instance": "-", "case": "-", "then": None, "alternative": "-", "reading": "", "state": "case_unreadable",
                 "why": "the automation manifest is missing: no instance is listed", "record": None, "model_find": None,
                 "model_replace": None, "superseded": [], "flags": ""}]
    manifest = C.load_json(manifest_path)
    rows: list = []
    for entry in C.manifest_tests(manifest):
        aliases = C.instance_id_aliases(entry, case_cfg)
        if instance and instance not in aliases:
            continue
        iid = C.test_instance_id(entry) or (aliases[0] if aliases else "")
        for case in C.manifest_test_keys(entry, case_cfg):
            rows.extend(_case_rows(task_root, root, manifest, entry, iid, case, case_cfg, S5))
    return rows


def _case_rows(task_root: Path, root: Path, manifest: dict, entry: dict, iid: str, case: str, case_cfg, S5) -> list:
    def unreadable(why: str) -> list:
        return [{"instance": iid, "case": case, "then": None, "alternative": "-", "reading": "", "state": "case_unreadable",
                 "why": why, "record": None, "model_find": None, "model_replace": None, "superseded": [], "flags": ""}]
    file = S5._case_file_of(task_root, case, case_cfg)
    if file is None:
        return unreadable(f"case file of {case} not found")
    try:
        text = Path(file).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return unreadable(f"case file of {case} cannot be read ({type(exc).__name__})")
    entries, problem = C.alternatives_from_text(text)
    if entries is None:
        return unreadable(f"the `alternatives` key of {case} is malformed: {problem}") if problem else []
    shape = C.alternatives_errors(case, entries and json.dumps(entries), [n for n, _ in S5.then_clauses(text)])
    if shape:
        return unreadable(f"the `alternatives` key of {case} is malformed: {shape[0]}")
    return [_alt_row(task_root, root, manifest, entry, iid, case, item, case_cfg) for item in entries]


def _alt_row(task_root: Path, root: Path, manifest: dict, entry: dict, iid: str, case: str, item: dict, case_cfg) -> dict:
    token = f"{case}:{item['id']}"
    out = alternative_record_path(task_root, iid, case, item["id"])
    row = {"instance": iid, "case": case, "then": item["then"], "alternative": token, "reading": item["reading"],
           "state": "unknown", "verdict": None, "why": "", "record": None, "model_find": None, "model_replace": None,
           "superseded": [], "flags": ""}
    record, problem = _read_alt_record(out)
    if record is None:
        row["why"] = problem or "never probed"
    elif (record.get("instance_id"), record.get("case"), record.get("alternative")) != (iid, case, token):
        row["why"] = (f"the record names another case, instance or alternative ({record.get('case')}, "
                      f"{record.get('instance_id')}, {record.get('alternative')}), not this one")
    else:
        _judge_alt_row(row, record, task_root, root, manifest, entry, item, case, case_cfg, out)
    if row["state"] in ("unknown", "stale"):
        # the call form of the one road (t-2064 P5), the same for every language: the entries of the model file that carry the token
        row["flags"] = f"--alternative {token} [--model work/probe-models/<any name>.json]"
        row["skeleton"] = json.dumps({"models": [{"check": "<file>:<line of a check of that Then, `--plan` lists them>", "alternative": token,
                                                  "supposes": "<what the product would do under reading B>",
                                                  "actual": "<the value that check would read under reading B>"}]}, ensure_ascii=False)
        row["skeleton_gap"] = json.dumps({"models": [{"alternative": token, "gap": "<why B cannot be modelled in the test>"}]},
                                         ensure_ascii=False)
    return row


def _judge_alt_row(row: dict, record: dict, task_root: Path, root: Path, manifest: dict, entry: dict, item: dict, case: str,
                   case_cfg, out: Path) -> None:
    verdict = record.get("verdict")
    row.update(verdict=verdict, record=out.relative_to(task_root).as_posix(), model_find=record.get("model_find"),
               model_replace=record.get("model_replace"),
               superseded=[s.get("verdict") for s in record.get("superseded") or [] if isinstance(s, dict)])
    if verdict in ("not_executed", "incomplete"):
        row["why"] = f"the last probe was {verdict}: " + str(record.get("why") or (record.get("notes") or ["no reason recorded"])[0])
        return
    refs = then_assertions(manifest, case, item["then"], entry, case_cfg)
    fresh, why = alternative_fresh(record, alternative_now(entry, task_root, root, item, refs,
                                                           [str(m["path"]) for m in _recorded_edits(record)]))
    if not fresh:
        row.update(state="stale", why=why)
    elif verdict == "intended_failure":
        row.update(state="proven", why="every check of that Then proved under the entries of reading B")
    elif verdict == "no_failure":
        row.update(state="not_separated", why="the Then passed under reading B: its assert does not separate A from B")
    elif verdict == "wrong_location":
        row.update(state="wrong_location", why=f"it failed elsewhere: {record.get('actual_location')}")
    elif verdict == "gap":
        row.update(state="gap", why=f"{record.get('cause')}: {record.get('why')}")
    else:
        row["why"] = f"the record's verdict {verdict!r} is not one this report knows"


def _print_alternatives(rows: list, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return
    if not rows:
        print("no case of this story declares `alternatives`: nothing is owed")
    for row in rows:
        print(f"{row['instance']} {row['alternative'] if row['alternative'] != '-' else row['case']}"
              f"{' Then ' + str(row['then']) if row.get('then') is not None else ''}: {row['state']} - {row['why']}")
        if row["state"] in ("proven", "not_separated") and row.get("model_find") is not None:
            print(f"  model: {row['model_find']} -> {row['model_replace']}")
        if row.get("superseded"):
            print(f"  superseded: {len(row['superseded'])} (prior: {', '.join(str(v) for v in row['superseded'])})")
        if row.get("flags"):
            print(f"  add to the probe command: {row['flags']}")
        if row.get("skeleton"):
            print(f"  model file: {row['skeleton']}  or, when B cannot be modelled: {row['skeleton_gap']}")


def _plan_grew(stored: dict, record: dict) -> list:
    """The keys of `record`'s plan (`mutation_detail.checks`) that the `stored` aggregate's plan does not hold, in plan order; [] when
    either has no plan list (an old single-probe record: the rule of `keep_standing_record` is then as it was) or nothing was added.
    Pure; a removed key is not growth."""
    def plan_of(one) -> "list | None":
        detail = one.get("mutation_detail") if isinstance(one, dict) else None
        keys = detail.get("checks") if isinstance(detail, dict) else None
        return [str(k) for k in keys] if isinstance(keys, list) else None
    before, after = plan_of(stored), plan_of(record)
    return [k for k in after if k not in before] if before is not None and after is not None else []


def keep_standing_record(path: Path, record: dict) -> bool:
    """True when `record` is a run that judged NOTHING about the test (`not_executed`, or `incomplete`: the
    tool could not read the run well enough) and `path` holds an `intended_failure`: that stored record is
    kept, and only `last_attempt {at, verdict, why}` is added to it - `verdict` and `test_file_sha256` stay as
    they were. Invariant: an `intended_failure` record is replaced only by the record of a run that judged
    the test. A probe that never ran (a refused request, a stand that was down) used to overwrite it with
    `not_executed`, and the evidence that a probe had passed - the very thing `probe_debt.py` settles -
    vanished (t-177); an `incomplete` answer is a gap of the factory's, and costs the same. Any judged verdict
    (`no_failure`, `wrong_location`, `intended_failure`) replaces the record as before (E23) - except a judged verdict of
    ANOTHER target over a proved record of the obligation's check, which `_finish_record` keeps beside it (`_proved_standing`,
    t-2045 N1b); this function never sees that record."""
    if record.get("verdict") not in ("not_executed", "incomplete"):
        return False
    try:
        stored = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    if not isinstance(stored, dict) or stored.get("verdict") != "intended_failure":
        return False
    if proof_level.receipt_off_target(stored):
        # a probe of another line proved nothing about the obligation: it does not stand over a re-probe
        # that ends `incomplete` (a judgment record must be stored to be judged)
        return False
    grown = _plan_grew(stored, record)
    if grown:
        # t-2064 fix round B, F8: the call ADDED a check to the plan (`--at` of a helper's line, owed from then on) and ended `incomplete`.
        # The older proved aggregate speaks for the smaller plan only: kept, it would drop the added key (`_stored_plan_refs` reads it
        # from `checks[]`) and leave its receipt standing for a plan one check bigger. The new record replaces it; nothing proved is lost
        # (each proved check keeps its own per-check record, and the next call carries it as proved). The one rule of this function stays
        # as it was for a call that added no key. (No note is written: the walk rewrites the aggregate after every row, and the next write
        # finds no proved record to keep, so a note made here would not outlive the call.)
        return False
    stored["last_attempt"] = {"at": record.get("recorded_at"), "verdict": record["verdict"], "why": _attempt_why(record)}
    atomic_json(path, stored)
    return True


def _attempt_why(record: dict) -> str:
    """The `last_attempt.why` of a kept standing record (fix round I2, t-2064 q10). RULE: a walk's aggregate (it holds `checks` rows) says
    the REASON OF THE ROW THAT DID NOT PROVE - that row's own note - not the aggregate's own note (a command line is not why the attempt
    stopped); with several rows that did not prove (neither `intended_failure` nor `not_owed`), the FIRST one's reason and the count
    (`(N checks did not prove)`). A first such row with no note, a record with no rows or an old single record: the last note of the
    record, as before, else `nothing ran`. Pure; at most 300 characters (the count survives the cut)."""
    rows = [r for r in record.get("checks") or [] if isinstance(r, dict) and r.get("verdict") not in ("intended_failure", "not_owed")]
    note = str(rows[0].get("note") or "").strip() if rows else ""
    if note:
        tail = f" ({len(rows)} checks did not prove)" if len(rows) > 1 else ""
        return fold(note, 300 - len(tail)) + tail
    notes = [str(n) for n in record.get("notes") or []]
    return fold(notes[-1] if notes else "nothing ran", 300)


def _records_id(ctx: ProbeCtx) -> str:
    """The id every per-check record and request file of this call is NAMED by (t-2064 P5): the instance's own id on a plain call, and
    `<IID>--<CASE>--<ALT>` (the stem of the alternative's record) on an alternative call - so a reading's per-check record never lies on
    the file of the plain walk's check (`_check_proved` would read another entry's sha there, but the write would still replace it).
    INVARIANT: a plain call (`ctx.alt` empty) gets `ctx.instance_id` byte for byte. Only a NAME: what the run is built for stays the
    instance's (`build_request` reads `ctx.instance_id`)."""
    if not ctx.alt:
        return ctx.instance_id
    case, alt = parse_alternative_token(ctx.alt)
    return f"{C.test_instance_id(ctx.entry) or ctx.instance_id}--{case}--{alt}"


def _check_record(task_root: Path, iid: str, line: int, record: dict, ordinal: int = 1, file=None) -> Path:
    """Store ONE check's record (t-2064 P4a) at `proof_level.probe_record_path(task_root, iid, target_line=line, ordinal=ordinal)`:
    `work/probes/checks/<iid>--L<line>.json`, `...-2.json` for the second check on the same line (EP-O). Returns the path written (or
    kept). Written atomically; the standing-record rule is `keep_standing_record`'s, the one function (AR-15): a run that judged
    nothing (`not_executed`, `incomplete`) never replaces an `intended_failure` of this key, it only adds `last_attempt`. The record
    is never a receipt's and no receipt is made from it. `line` must be an int: anything else would be the instance's STANDING
    record path (`probe_record_path` answers today's path for it), which this function must never write: a Refusal, nothing written."""
    if not isinstance(line, int) or isinstance(line, bool):
        raise Refusal(f"probe_by_code: a check record needs the line of its check as an int, got {line!r}: the instance's standing "
                      "record is not written by a per-check record. Nothing was written.")
    path = proof_level.probe_record_path(task_root, iid, target_line=line, ordinal=ordinal, file=file)
    if not keep_standing_record(path, record):
        atomic_json(path, record)
    return path


def _entry_sha(entry: dict) -> str:
    """The sha256 of a model entry's canonical JSON (spec section 14): sorted keys, the fields `check`, `instance`, `alternative`, the
    entry's ONE kind with its value (`find` with its `replace`) and `supposes`. Pure data; the same entry always gives the same sha
    and a changed value, kind or supposition gives another, so a record written for one model is never read as proof of another."""
    kind = entry.get("kind")
    body = {"check": entry.get("check"), "instance": entry.get("instance") or "", "alternative": entry.get("alternative") or "",
            "kind": kind, "supposes": entry.get("supposes") or ""}
    if kind == "find":
        body["find"], body["replace"] = entry.get("find"), entry.get("replace")
    elif isinstance(kind, str) and kind in entry:
        body[kind] = entry[kind]
    return sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _check_proved(task_root: Path, iid: str, line: int, ordinal: int, entry_sha: str, target_sha: str = "", flags=None, file=None,
                  code_sha: str = "") -> bool:
    """Is the check at `line` (the `ordinal`-th on it) PROVED already, so the walk skips it (t-2064 P4a, section 14)? True only when its
    per-check record exists under `work/probes/checks/`, is readable, carries this `entry_sha`, was made on the same target bytes
    (`_same_bytes`: the record's own `bytes_key` - the file's `target_sha` or the instance's `code_sha` - and, for an old record with
    none, `mutated_file.sha256` equal to `target_sha`) and its verdict is `intended_failure`. Anything else - no record, an unreadable or malformed one, another entry, other bytes, a `not_reached` or
    `incomplete` verdict, an empty `entry_sha` or `target_sha` - is not proved, and the check runs: the error goes toward running
    (AR-28). `target_sha` is keyword-optional only for the signature of the Lead's decision; empty, it cannot show the same bytes
    and answers False. `flags` (a list, or None = not asked): the no-retry flags the walk runs WITH now; when given, the record must carry
    the SAME list as `no_retry_flags` (the flags its run was made under): a result made without them is never served to a walk that
    runs with them, and the reverse; a record with no such field (an old one) or an unreadable one is not proved (rerun, never a
    pass; AR-28). Reads one file; writes nothing."""
    return _check_standing(task_root, iid, line, ordinal, entry_sha, target_sha, flags, file, code_sha) == "intended_failure"


_CARRIED_VERDICTS = ("no_failure", "wrong_location")        # a survivor of a deterministic rerun is carried as it stands (§14 amended 11.11.2026, F3)


def _read_check_record(task_root: Path, iid: str, line, ordinal: int, file=None):
    """The per-check record of the check at `line` (the `ordinal`-th on it, in `file`) as a dict, or None when it is absent, unreadable or not
    an object: the ONE reader of `work/probes/checks/` for this module (`_check_standing`, `_per_check_read`), through
    `proof_level.record_read_path` (the record of THIS check's file, never a name built here). Reads one file."""
    try:
        stored = json.loads(Path(proof_level.record_read_path(task_root, iid, line, ordinal, file=file)).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError, TypeError):
        return None
    return stored if isinstance(stored, dict) else None


def _bytes_key(is_test: bool, file_sha: str, code_sha: str = "") -> dict:
    """The key a per-check record is bound to, `{"kind", "sha"}` (§14 amended 11.11.2026, F4): for a check that lives in the TEST file the
    instance's own code sha (`proof_level`'s `instance_code_sha`: the test function's code, so a comment or another test's edit in the
    file changes nothing here); for a check in a helper file, or when the instance's code sha cannot be computed (no job to measure it by,
    a file no reader tokenizes), the sha of the whole file - the record says which kind it used. Pure."""
    if is_test and code_sha:
        return {"kind": "code_sha", "sha": code_sha}
    return {"kind": "file_sha", "sha": file_sha}


def _same_bytes(stored: dict, target_sha: str, code_sha: str = "") -> bool:
    """Is the record `stored` made on the bytes as they stand now? Read by the record's OWN kind of key (`bytes_key`): `file_sha` - equal to
    `target_sha`, the sha of the file the check lives in (a file that is the same is the same instance too); `code_sha` - equal to `code_sha`,
    the instance's code sha now, and only when one is given (none: the key cannot be compared, so it does not stand); an unknown kind or
    an empty sha does not stand. An OLD record with no `bytes_key` is read by the old rule alone: its `mutated_file.sha256` equals
    `target_sha` (never a silent pass and never a silent drop). Error direction: not the same (the check runs). Pure."""
    key = stored.get("bytes_key")
    if isinstance(key, dict):
        sha = key.get("sha")
        if not isinstance(sha, str) or not sha:
            return False
        if key.get("kind") == "file_sha":
            return sha == target_sha
        return key.get("kind") == "code_sha" and bool(code_sha) and sha == code_sha
    moved = stored.get("mutated_file")
    return isinstance(moved, dict) and moved.get("sha256") == target_sha


def _check_standing(task_root: Path, iid: str, line: int, ordinal: int, entry_sha: str, target_sha: str = "", flags=None, file=None,
                    code_sha: str = "") -> str:
    """The verdict of the per-check record that STANDS for this check now, else "": it exists, is readable, carries this `entry_sha`, the
    same bytes (`_same_bytes`: `target_sha` the file's sha now, `code_sha` the instance's code sha now, "" when not measured) and, when
    `flags` is given, the same no-retry flags. The one reading `_check_proved` (proved) and the walk's carry of a survivor (`no_failure`,
    `wrong_location`: `_CARRIED_VERDICTS`) share. An empty `entry_sha` or `target_sha` never stands (AR-28). Reads one file; writes nothing."""
    if not entry_sha or not target_sha or isinstance(line, bool) or not isinstance(line, int):
        return ""
    stored = _read_check_record(task_root, iid, line, ordinal, file)
    if stored is None or stored.get("entry_sha") != entry_sha or not _same_bytes(stored, target_sha, code_sha):
        return ""
    if flags is not None and stored.get("no_retry_flags") != [str(f) for f in flags]:
        return ""
    verdict = stored.get("verdict")
    return verdict if isinstance(verdict, str) else ""


# --- the walk over the plan (t-2064 P4a item 1): a function, not yet on `_probe` (P4b wires it) -------------------------------------

def _walk_clock() -> float:
    """The walk's clock: `time.monotonic`, one function so that a test sets the time without sleeping."""
    return time.monotonic()


def _walk_stamp(answer: dict, key: str, **more) -> dict:
    """A walk-made outcome in the judge's shape: the answer plus `check_key`, `read_in_joint`, `rerun_alone` (and what `more` adds)."""
    answer.update({"check_key": key, "read_in_joint": False, "rerun_alone": False, **more})
    return answer


def _walk_target(ctx: ProbeCtx, shown: str, locks: list, state: dict) -> Path:
    """The path of the file a check lives in. The test's own file is the one `_lock_test` locked; any other file is locked
    (`claim_key`, once per walk) BEFORE its first read, as `_probe` does: no byte is read as the author's under another probe."""
    if _same_file(shown, ctx.spec["file"]):
        return ctx.path
    candidate = Path(shown)
    candidate = candidate if candidate.is_absolute() else ctx.root / candidate
    key, display = copy_key(candidate, ctx.root)
    if key not in state["claimed"]:
        held = claim_key(ctx.root, key, display, own=True, notes=state["notes"])
        if held is not None:
            locks.append(held)
        state["claimed"].add(key)
    return candidate


def _walk_run_once(ctx: ProbeCtx, target: Path, left: float, flags: list, number: int) -> dict:
    """ONE run of the file as it now stands, read into raw rows (the joint judge reads every problem of a row, which `_run_and_judge`'s
    non-raw rows do not carry): `{request, rows (the rows this test's report holds), sites (one per row), notes, ran, timed_out}`.
    The no-retry `flags` go through `build_request`. A run the walk's own timeout ends is `timed_out`, never a verdict."""
    import execution_request as ER
    import red_sandbox
    spec, notes = ctx.spec, []
    out = {"request": None, "rows": [], "sites": [], "notes": notes, "ran": False, "timed_out": False, "evidence": []}
    more = {"mutation_kind": ALTERNATIVE_KIND} if ctx.alt else {}       # the request says what kind of probe asked for it
    request, built = build_request(ctx.root, ctx.cfg, ctx.task, ctx.dispatch, ctx.case, spec, ctx.instance_id, ctx.mutation or "model",
                                   f"probe-{ctx.instance_id}: model walk{' of ' + ctx.alt if ctx.alt else ''}, run {number} of {spec['file']} "
                                   f"({ctx.dispatch})", ER.entry_profile_id(ctx.entry), s6_close=ctx.stage == "S6", extra_argv=tuple(flags),
                                   **more)
    notes.extend(built)
    out["request"] = request
    request_path = ctx.task_root / "work" / "probe-requests" / f"probe-walk-{record_path(ctx.task_root, _records_id(ctx)).stem}-{number}.json"
    atomic_json(request_path, request)
    try:
        _proc, summary = run_request(ctx.root, request_path, int(left) + 1)
    except subprocess.TimeoutExpired:
        out["timed_out"] = True
        notes.append("the run was ended by the walk's --timeout")
        return out
    out["ran"] = True
    try:
        out["evidence"] = _run_evidence(summary, ctx.root, ctx.task_root)
    except OSError as exc:      # no evidence is absent, never invented
        notes.append(f"the run's evidence files were not read ({type(exc).__name__}: {exc})")
    report = (summary.get("report_evidence") or {}).get("path")
    reporter = str(summary.get("reporter") or "").strip() or DEFAULT_REPORTER
    rows: list = []
    report_read = False     # only a report that was READ makes "no row of it is this test" a fact about the tool, not the stand (as `_judge_run`)
    if report and (ctx.task_root / report).is_file():
        try:
            rows = report_rows(ctx.task_root / report, reporter, raw=True)
            report_read = True
        except ET.ParseError as exc:
            notes.append(f"the report is not valid XML: {exc}")
        except ValueError as exc:
            notes.append(f"the run's report was not read (its summary names the reporter): {exc}")
    else:
        notes.append("no report evidence: " + str(summary.get("error_head") or summary.get("no_junitxml")
                                                   or summary.get("execution_status") or "unknown cause"))
    contracts = request.get("instance_contracts") or {}
    own = next((contracts[i] for i in (ctx.instance_id, C.test_instance_id(ctx.entry) or ctx.instance_id)
                if isinstance(contracts.get(i), dict)), None)
    argv = (request.get("command") or {}).get("argv")
    own_key = next((i for i in (ctx.instance_id, C.test_instance_id(ctx.entry) or ctx.instance_id) if isinstance(contracts.get(i), dict)), "")
    matched, why, tooling = _bind_report_rows(rows, own, spec, own_key, reporter, ctx.task, ER.is_pytest_command(argv), report_read)
    if why:     # q8/q9 (fix round I2): the old road's binding refused - no row of the test, or several of a hand-written id: nothing is judged
        out["refused"] = {"note": why, "tooling": tooling}
        out["rows"] = red_sandbox.selection_rows(rows, own) if own and own.get("file") else matching_rows(rows, spec["node"])    # what the run held (flag rule)
        return out
    frames, skip, frame_path = AD.grammar_of(spec["entry"])
    for one in matched:
        if reporter in reporters.READERS:
            site = reporters.assertion_site(one, reporter, ctx.root, target, pytest_command=ER.is_pytest_command(argv),
                                            runtime=spec["language"], frames=frames, skip_frames=skip, frame_path=frame_path)
        else:
            site = {"site_unread": f"{reporter}/{spec['language']}",
                    "reason": f"the run's reporter is {reporter!r}; stack frames are read only from the readers {', '.join(reporters.READERS)}"}
        out["sites"].append(site)
    out["rows"] = matched
    return out


def _walk_attempt(ctx: ProbeCtx, plan: dict, group: list, picked: list, flags: list, left: float, state: dict, locks: list) -> dict:
    """ONE edited run of the checks `group` of one file, judged: `{outcomes: {key: outcome}, move, restore, restore_failed, flag_trouble,
    timed_out, notes}`. Order and the invariant of each position: the file is read under its lock, the model is planned (a refusal
    is the row's outcome and NOTHING was written), the byte copy is on disk and verified BEFORE the first write, and the author's bytes
    are put back FROM the copy and verified in a `finally` - a restore that is not verified keeps the copy and returns
    `restore_failed` (the walk ends there). Judged by `_judge_joint_rows`; every row the report holds for the test is judged, and a key
    is proved only if EVERY row proves it (a parametrised instance: a proof never covers a row that passed)."""
    iid, by_key = ctx.instance_id, {c["key"]: c for c in plan["checks"]}
    if state.get("located") is None:        # measured once per walk (`_walk_plan`); a caller that did not: once here, on the author's bytes
        state["located"] = test_body_span(ctx.path.read_bytes(), ctx.spec, _reader_entry(ctx.spec)) is not None
    got = {"outcomes": {}, "move": "go on", "restore": None, "restore_failed": False, "flag_trouble": False, "timed_out": False, "notes": [],
           "evidence": [], "fingerprint": None}

    def settle(why: str) -> dict:
        got["outcomes"] = {key: _walk_stamp(_row_answer({}, "incomplete", why, cause="tooling"), key) for key in group}
        return got

    try:
        target = _walk_target(ctx, by_key[group[0]]["file"], locks, state)
        original = target.read_bytes()
        stat = target.stat()
    except (OSError, KeyError) as exc:
        return settle(f"the file of the check could not be read ({type(exc).__name__}: {exc}); nothing was changed")
    original_sha = sha256(original)
    started = datetime.now(timezone.utc).isoformat(timespec="microseconds")        # per RUN: an alone rerun never shares a joint run's token
    tokens = {key: marker_token(iid, original_sha, started, key) for key in group}
    try:
        mutated, details = plan_model(original, ctx.spec, picked, plan["checks"], tokens, iid)
    except Refusal as exc:
        return settle(str(exc))
    mutated_sha = sha256(mutated)
    try:
        copy = begin_copy(ctx.root, target, original, original_sha, stat, mutated_sha, details[0], int(left) + 1)
    except Refusal as exc:
        if state.get("fresh"):      # q16: the FIRST copy of the walk cannot be taken - nothing was run or written: the CALL is refused (exit 2), not a row
            raise
        return settle(str(exc))     # a later row: the earlier rows stand with their records, this one is its own tooling outcome
    ran = {"request": None, "rows": [], "sites": [], "notes": [], "ran": False, "timed_out": False, "evidence": []}
    try:
        target.write_bytes(mutated)
        state["runs"] += 1
        ran = _walk_run_once(ctx, target, left, flags, state["runs"])
    except Exception as exc:        # the outcome says what happened; the author's bytes go back regardless
        ran["notes"].append(f"{type(exc).__name__}: {exc}")
        import execution_request as ER
        if isinstance(exc, ER.MineRefusal):     # NV-1: the request was refused (a check outside its scope): the row never ran, and says why
            ran["request_refused"] = str(exc).strip()
    finally:
        try:
            got["restore"] = restore(target, original, original_sha, stat, copy=copy["orig"])
        except OSError as exc:
            got["restore"] = {"verified": False, "error": f"{type(exc).__name__}: {exc}"}
        finish_copy(copy, got["restore"], ctx.root)
        got["restore"].update(file=_rel_project(target, ctx.root), author_sha256=original_sha)     # q15: what `_unrestored_exit` names
    got["notes"] = ran["notes"]
    if not got["restore"].get("verified"):
        got["restore_failed"] = True
        return settle("the author's bytes were not put back verified after this run, so the copy stays and the walk ends (nothing else "
                      f"runs): `probe_by_code.py --release-copy {_rel_project(target, ctx.root)}` shows it and releases it; this "
                      "run's result is not used")
    rows, sites = ran["rows"], ran["sites"]
    got["timed_out"] = ran["timed_out"]
    got["evidence"] = ran["evidence"]
    fingerprint = None
    if ran["request"]:      # `test_content_sha` over the author's bytes: what the single probe records as `input_hash`
        try:
            fingerprint = original_input_hash(ran["request"], target, mutated_sha, original_sha)
        except Exception:       # no fingerprint is absent, never invented
            fingerprint = None
    got["fingerprint"] = fingerprint
    got["flag_trouble"] = bool(flags) and ran["ran"] and (not rows or all(_row_status(one) == "error" for one in rows))
    if ran.get("refused"):      # q8/q9: the report holds no row of the test, or several of a hand-written id - the old road's note, and no verdict
        why, cause = ran["refused"]["note"], ("tooling" if ran["refused"]["tooling"] else None)
        got["outcomes"] = {key: _walk_stamp(_row_answer({}, "not_executed", why, cause=cause), key) for key in group}
        return got
    if ran.get("request_refused"):      # NV-1: a refused request (no row, nothing ran): the refusal's own words are the row's note, never "report status None"
        words = ran["request_refused"]      # an empty refusal text never reaches here: the old road's note stands for it
        got["outcomes"] = {key: _walk_stamp(_row_answer({"status": None, "message_head": ""}, "not_executed", words, mismatches=[words]), key)
                           for key in group}
        return got
    kinds ={key: [one.get("probe_kind") for one in details if one.get("key") == key] for key in group}
    valued = [key for key in group if any(kind != "invert" for kind in kinds[key])]
    green = None
    if valued and ran["request"]:
        try:
            green = author_green_of(ctx.task_root, iid, state["identity"],
                                    fingerprint if fingerprint is not None else original_input_hash(ran["request"], target, mutated_sha, original_sha))
        except Exception:       # a fact turned into a proof's condition errs to unknown
            green = None
    facts = {"entry": ctx.spec["entry"], "author_green": {key: green for key in valued}, "language_label": ctx.spec["language"],
             "argv": ((ran["request"] or {}).get("command") or {}).get("argv"),
             # E5 / EP-O (fix round A, B2): a pass says nothing about WHICH body ran when the test's body is not located (two declarations of
             # its name, a file the reader cannot read) - the old road's `among`, once per walk (`state["located"]`), the same for every key
             "among": {key: not state["located"] for key in group}}
    pairs = list(zip(rows, sites)) or [(None, {})]
    site_of = {id(one): site for one, site in pairs if one is not None}
    results = [(one, *_judge_joint_rows([one] if one else [], tokens, group, plan, details, dict(facts, site=site)))
               for one, site in pairs]
    if len(results) == 1:
        outs, move = results[0][1], results[0][2]
    else:
        outs, move = {}, "stop" if any(m == "stop" for _o, _x, m in results) else "go on"
        for key in dict.fromkeys(k for _o, per, _m in results for k in per):
            per = [(one, o[key]) for one, o, _m in results if key in o]
            outs[key] = dict(next((a for _o, a in per if a.get("verdict") != "intended_failure"), per[0][1]),
                             param_rows=[{"test_id": (one or {}).get("test_id"), "verdict": a.get("verdict")} for one, a in per])
    for key in group:
        if key not in outs:     # a joint row settled by nothing leaves `incomplete`, never a pass (AR-28)
            outs[key] = _walk_stamp(_row_answer({}, "incomplete", "the joint judge settled nothing for this check; the code critic "
                                                "judges it: " + JUDGE_DOOR, cause="judgment"), key)
    for key, outcome in outs.items():       # t-2064 P4b item 5: the facts of a check owed a judgment travel with ITS outcome (AR-21, AR-22)
        if outcome.get("verdict") == "incomplete" and outcome.get("cause") == "judgment":
            owed = [(one, site_of.get(id(one), {})) for one, o, _m in results
                    if one is not None and (o.get(key) or {}).get("cause") == "judgment"] or [({"status": "", "problems": []}, {})]
            detail = next((one for one in details if one.get("key") == key), {"file": None, "line": None, "end_line": None})
            mine = next((one for one in picked if one.get("check") == key), None)
            outcome["judgment_facts"] = dict(judgment_facts({"evidence_ref": None}, owed[0][0], owed[0][1], detail, ctx.spec["entry"],
                                                            rows=[r for r, _s in owed]),
                                             check_key=key, model=mine, author_green=(facts.get("author_green") or {}).get(key))
    got["outcomes"], got["move"] = outs, move
    return got


def _walk_record(ctx: ProbeCtx, check: dict, outcome: dict, one: dict, sha: str, shown: str, bytes_sha: str, test_sha: str,
                 unfinished: bool, bytes_key=None) -> dict:
    """The per-check record of one outcome (written through `_check_record`, the ONE writer of `work/probes/checks/`). It carries
    the model entry's sha and the bytes of the file it was made on, which is what `_check_proved` reads; no receipt is made from it.
    `bytes_key` (`_bytes_key`: `{kind: code_sha | file_sha, sha}`) is the key the record is carried by; absent, it is the file sha."""
    facts = {"judgment_facts": outcome["judgment_facts"]} if isinstance(outcome.get("judgment_facts"), dict) else {}    # item 5: what `--judge --check` reads
    return {**facts, "schema_version": 1, "probe_tool": "probe_by_code.py", "record_kind": "check", "task": ctx.task, "dispatch_id": ctx.dispatch,
            "instance_id": ctx.instance_id, "case": ctx.case, "check_key": check["key"], "verdict": outcome["verdict"],
            "cause": outcome.get("cause"), "proved_by": outcome.get("proved_by"), "read_in_joint": outcome.get("read_in_joint"),
            "reran_alone": bool(outcome.get("reran_alone")), "no_retry_flags": outcome.get("no_retry_flags_used"), "observed": outcome.get("observed") or {}, "entry_sha": sha,
            "probe_kind": one["kind"], "supposes": one.get("supposes", ""),
            "mutated_file": {"path": shown, "sha256": bytes_sha}, "bytes_key": bytes_key or _bytes_key(False, bytes_sha), "test_file_sha256": test_sha,
            "target": {"file": check.get("file"), "line": check["line"], "end_line": check.get("end_line")},
            "notes": [str(outcome.get("note") or "")], "plan_remaining": outcome.get("plan_remaining") or [],
            "plan_unfinished": unfinished, "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def _pick_entries(ctx: ProbeCtx, entries: list) -> dict:
    """`{check key: the model entry that stands for it}`, the ONE pick (`_walk_plan` and `_aggregate_rows` both call it, AR-15): an entry
    of this instance (its own id or the test's) or a general one (`instance` empty); an instance's own entry wins over a general one,
    otherwise the first. Pure."""
    mine = {"", ctx.instance_id, C.test_instance_id(ctx.entry) or ctx.instance_id}
    picked: dict = {}
    for one in entries or []:
        if one.get("instance", "") in mine and (one["check"] not in picked or (not picked[one["check"]].get("instance") and one.get("instance"))):
            picked[one["check"]] = one
    return picked


def _word_reruns(plan: dict, key: str, only: set) -> bool:
    """Does the person's word (`plan["rerun"]`, set by `_probe_plan` from `_repeat_look`) re-run the PROVED check `key`? Every proved check of a
    plain call, and under a selection (`only`) the selected ones (the old road probed the asked check). The word never lowers a proof: what the
    re-run gives is written as any later attempt on a standing `intended_failure` is. Pure."""
    return bool((plan or {}).get("rerun")) and (not only or key in only)


def _walk_plan(ctx: ProbeCtx, plan: dict, entries: list, locks: list, timeout: float) -> dict:
    """Walk the plan of ONE test (t-2064 P4a item 1; nothing on the live road calls it yet, P4b wires it). `plan["rerun"]`, set by `_probe_plan` from a person's word that passed the repeat (`_repeat_look`), makes the proved checks run again (`_word_reruns`). `plan` is
    `{"checks": checks_of rows, "runs": run_plan rows}`, `entries` are `load_models`' entries, `locks` is the caller's list of locks
    (released by the caller), `timeout` the seconds the WHOLE walk may take. Returns
    `{outcomes: {key: outcome}, plan_remaining: [keys], ended: "" | "stop" | "restore_failed" | "time", notes, restore, flags_dropped,
    unmodelled: [keys with no entry], dropped: [not_here / product keys, P4b reads them], proved: [keys skipped as proved], runs,
    evidence_refs: [{path, sha256}] (the summary and report files of every attempt that ran; [] when none ran), input_hash (the one
    value the single probe records: the author's run-block binding, else the fingerprint over the author's bytes; None when no run
    built a request)}`. After every row but the last, and once at the end (the walk's one receipt-capable call), `_aggregate_record` writes `work/probes/<iid>.json` (the one writer), after that
    row's per-check records and with the author's bytes back (or the restore recorded as failed); a failed aggregate write is a note
    in `notes`, the per-check records stand. A walk with no key left to run because all are proved also writes it (read back from the
    records); a plan with no live key (all unmodelled or dropped: no lock was taken) or no check writes nothing: the caller reads
    `unmodelled`, `dropped` and refuses or calls `_aggregate_record` itself.
    An outcome is the joint judge's (`verdict`, `note`, `cause`, `proved_by`, `observed`, `check_key`, `read_in_joint`, `rerun_alone`,
    and where it applies `reran_alone`, `plan_remaining`, `earlier_check`, `param_rows`, `author_green`).

    For each plan row in order: `not_here` and `product` keys are dropped; a key `_check_proved` shows proved on these bytes with the
    same entry sha is skipped; then `begin_copy`, `plan_model`'s bytes, one run, the restore VERIFIED, the judge, the alone reruns the
    judge asks for (once each, a new token per run), and one `_check_record` per key - after EACH row, so a killed walk keeps what it
    proved. INVARIANT: the author's bytes are back after every run, or the copy stays and the walk ENDS (the rest is named in
    `plan_remaining`, nothing else runs). The judge's `stop` ends the walk; time is checked before every run (`<= 0` left: the rest is
    `not_reached` with the reason, EP-J); a run WITH the no-retry flags that gives no rows or only errors is made once more without
    them, one note, and no flags for the rest of the walk (F-P10). An empty plan, or one whose keys are all proved or dropped, runs and
    writes nothing. `plan["only"]` (a list of keys; absent or empty = the whole plan, `--at` / `--oracle` of t-2064 P4b item 3) restricts
    what RUNS: a key outside it is still checked for proof (so the aggregate carries it as proved) and is otherwise left unreached - no run, no
    per-check record - while its entry stays in the aggregate's reading."""
    result = {"outcomes": {}, "plan_remaining": [], "ended": "", "notes": [], "restore": None, "flags_dropped": False,
              "unmodelled": [], "dropped": [], "proved": [], "carried": [], "runs": 0, "evidence_refs": [], "input_hash": None}
    runs = (plan or {}).get("runs") or []
    checks = {one["key"]: one for one in (plan or {}).get("checks") or []}
    picked = _pick_entries(ctx, entries)
    only = set((plan or {}).get("only") or [])      # a selection (t-2064 P4b item 3): only these keys may run; the others are carried (proved) or left
    live: dict = {}
    for one in runs:
        for key in one.get("keys") or []:
            if picked.get(key) is None or key not in checks:
                result["unmodelled"].append(key)
            elif picked[key]["kind"] in ("not_here", "product"):
                result["dropped"].append(key)
            else:
                live[key] = picked[key]
    if not live:
        return result
    state = {"claimed": set(), "runs": 0, "identity": "", "notes": result["notes"], "fresh": True}      # `fresh`: no attempt has run yet (q16)
    test_key, copy_notes = _lock_test(ctx, locks)
    state["claimed"].add(test_key)
    result["notes"].extend(copy_notes)
    test_bytes = ctx.path.read_bytes()
    test_sha = sha256(test_bytes)
    test_code = ""      # the instance's own code sha (F4): the bytes key of a check in the test file; "" = not measured, the file's sha is the key
    try:
        now = proof_level.instance_identity(ctx.entry, ctx.task_root, ctx.root)
        same = now["input_hash"] == test_sha
        state["identity"] = str((now["instance_identity"] or {}).get("instance_content_sha") or "") if same else ""
        test_code = str((now["instance_identity"] or {}).get("instance_code_sha") or "") if same else ""
    except Exception:       # no identity: the binding binds nothing, the fingerprint route stays
        state["identity"] = ""
    span = test_body_span(test_bytes, ctx.spec, _reader_entry(ctx.spec))        # once, on the author's bytes: the road's own measure
    body = (ctx.spec["file"], span[0], span[1]) if span else None
    state["located"] = span is not None      # B2: the one measure of "which body ran", read by `_walk_attempt` for every row

    def publish() -> None:
        """The aggregate (`work/probes/<iid>.json`), the ONE writer; the per-check records are already on disk. A failed write is a
        note and never loses them. Called only with the author's bytes back (after a row's restore is verified or recorded as failed)."""
        result["runs"] = state["runs"]
        try:
            result["record"] = _aggregate_record(ctx, plan, entries, result, body)      # the record THIS call built: the caller's answer
        except Exception as exc:
            result["notes"].append(f"the aggregate record of the plan was not written ({type(exc).__name__}: {exc}); the per-check "
                                   "records stand")

    def collect(got: dict) -> None:
        """Carry what only the walk knows to what the aggregate reads: the run evidence of every attempt, and `input_hash` ONCE
        (the author's binding when the run blocks hold one, else the fingerprint over the author's bytes: `_run_and_judge`'s order)."""
        for one in got["evidence"]:
            if one["path"] not in [seen["path"] for seen in result["evidence_refs"]]:
                result["evidence_refs"].append(one)
        if result["input_hash"] is None and got["fingerprint"] is not None:
            try:
                bound = author_binding(ctx.task_root, ctx.instance_id, state["identity"])
            except Exception:       # no binding is absent: the fingerprint stays
                bound = None
            result["input_hash"] = bound["test_content_sha"] if bound else got["fingerprint"]
    sha_of, shown_of, sha_entry, key_of = {}, {}, {key: _entry_sha(one) for key, one in live.items()}, {}

    def ordinal(key: str) -> int:
        return _ordinal_of(checks[key])         # the one ordinal (F7): the row's field, else the key's `#n`

    flags_on = AD.no_retry_flags(ctx.spec["entry"], test_bytes.decode("utf-8", "replace"), result["notes"])
    for key in list(live):
        try:
            target = _walk_target(ctx, checks[key]["file"], locks, state)
            sha_of[key], shown_of[key] = sha256(target.read_bytes()), _rel_project(target, ctx.root)
        except OSError:
            sha_of[key], shown_of[key] = "", str(checks[key]["file"])       # unreadable: it runs, and the run says so
        # the instance's code sha speaks only for the test's OWN code: a check in the test file but outside the test's body (a helper function
        # of the same file) is keyed by the file's sha, or an edit of that function would leave the carried proof standing
        in_test = (_same_file(str(checks[key]["file"]), ctx.spec["file"]) and span is not None
                   and span[0] <= checks[key]["line"] <= span[1])
        key_of[key] = _bytes_key(in_test, sha_of[key], test_code)
        standing = _check_standing(ctx.task_root, _records_id(ctx), checks[key]["line"], ordinal(key), sha_entry[key], sha_of[key], flags_on,
                                   file=checks[key].get("file"), code_sha=test_code if in_test else "")
        if standing == "intended_failure" and not _word_reruns(plan, key, only):
            result["proved"].append(key)
            del live[key]
        elif standing == "intended_failure":
            pass        # a person's word re-runs a proved check (`plan["rerun"]`): it stays live, goes through `_walk_attempt` like a first run
        elif standing in _CARRIED_VERDICTS:
            result["carried"].append(key)       # F3: a survivor of the same entry, bytes and flags is deterministic: carried as it stands, no run
            del live[key]
        elif only and key not in only:
            del live[key]       # a row the selection does not name (`--at` / `--oracle`): it keeps what its record says, never runs here
    groups = [g for g in ([k for k in one.get("keys") or [] if k in live] for one in runs) if g]
    if not groups:
        publish()       # every key proved on these bytes: the aggregate is read back from the per-check records
        return result
    deadline = _walk_clock() + timeout
    outcomes, written = result["outcomes"], set()

    def attempt(keys: list) -> dict:
        nonlocal flags_on
        used = list(flags_on)
        got = _walk_attempt(ctx, plan, keys, [live[k] for k in keys], flags_on, deadline - _walk_clock(), state, locks)
        state["fresh"] = False
        collect(got)
        if flags_on and got["flag_trouble"] and not got["restore_failed"]:
            result["notes"].append(f"a run with the no-retry flags {' '.join(flags_on)} gave no rows or only errors: the run is made once more "
                                   "without them, and the rest of the walk runs without them (the runner may not forward them)")
            flags_on, result["flags_dropped"] = [], True
            if deadline - _walk_clock() > 0:
                used = []
                got = _walk_attempt(ctx, plan, keys, [live[k] for k in keys], flags_on, deadline - _walk_clock(), state, locks)
                collect(got)
        for outcome in got["outcomes"].values():
            outcome["no_retry_flags_used"] = list(used)      # the flags this result was made under: `_check_proved` reads them back
        result["notes"].extend(got["notes"])
        return got

    def absorb(outs: dict, keys: list) -> None:
        for key, outcome in outs.items():
            if key in keys or (key in live and key not in outcomes):
                outcomes[key] = outcome

    def write(keys: list, unfinished: bool, final: bool = False) -> None:
        for key in keys:
            if key in written or key not in outcomes or (result["ended"] and not final and outcomes[key]["verdict"] == "not_reached"):
                continue        # a not_reached key of an ended walk is written once, with the walk's final `plan_remaining`
            written.add(key)
            try:
                _check_record(ctx.task_root, _records_id(ctx), checks[key]["line"],
                              _walk_record(ctx, checks[key], outcomes[key], live[key], sha_entry[key], shown_of[key], sha_of[key], test_sha,
                                           unfinished, key_of.get(key)), ordinal(key), file=checks[key].get("file"))
            except Refusal as exc:
                result["notes"].append(str(exc))

    for index, group in enumerate(groups):
        if _walk_clock() >= deadline:
            result["ended"] = "time"
            break
        got = attempt(group)
        absorb(got["outcomes"], group)
        if got["restore_failed"]:
            result["ended"], result["restore"] = "restore_failed", got["restore"]
        elif got["move"] == "stop":
            result["ended"] = "stop"
        elif got["timed_out"]:
            result["ended"] = "time"
        else:
            for key in [k for k in group if outcomes[k].get("rerun_alone")]:
                if _walk_clock() >= deadline:
                    result["ended"] = "time"
                    break
                again = attempt([key])
                absorb(again["outcomes"], [key])
                if again["restore_failed"]:
                    result["ended"], result["restore"] = "restore_failed", again["restore"]
                    break
                outcomes[key].update(read_in_joint=False, rerun_alone=False, reran_alone=True)
                outcomes[key]["note"] = ((outcomes[key].get("note") or "") + "; " if outcomes[key].get("note") else "") + \
                    "run alone after the joint run did not show it (not read jointly)"
                if again["move"] == "stop":
                    result["ended"] = "stop"
                    break
                if again["timed_out"]:
                    result["ended"] = "time"
                    break
        write(group, index < len(groups) - 1 and not result["ended"])
        if result["ended"]:
            break
        if index < len(groups) - 1:
            # intermediate aggregates after every row but the last, after the row's restore is verified and its per-check records are
            # written (a killed walk keeps both); the last row's aggregate is the final one at the end of the walk, so a walk attaches
            # its receipt once
            publish()
    remaining = [k for k in live if k not in outcomes or outcomes[k]["verdict"] == "not_reached"]
    why = {"time": f"the walk's --timeout ({timeout} s) is spent before this check ran; the same call again continues (checks proved on "
                   "these bytes are skipped)",
           "restore_failed": "an earlier run did not put the author's bytes back verified, so the walk ended: `probe_by_code.py "
                             "--release-copy <file>` releases the copy, then the same call again continues",
           "stop": "the failure of an earlier run lies on the span of an earlier check of the plan (the code critic reads it): the "
                   "rest of the plan is not reached"}.get(result["ended"], "the walk ended before this check ran")
    for key in remaining:
        outcomes.setdefault(key, _walk_stamp(_row_answer({}, "not_reached", why), key))
        outcomes[key]["plan_remaining"] = list(remaining)
    for outcome in outcomes.values():
        if outcome.get("rerun_alone"):       # the walk ended before the alone rerun this key was owed
            outcome["rerun_alone"] = False
            outcome["note"] = (outcome.get("note") or "") + "; the walk ended before its alone rerun: " + why
    result["plan_remaining"], result["runs"] = remaining, state["runs"]
    write(remaining, bool(remaining), final=True)
    publish()
    return result


# --- the aggregate of a walk (t-2064 P4b item 1): the ONE writer of `work/probes/<iid>.json` for a walk -----------------------------

_AGG_KNOWN = ("intended_failure", "no_failure", "wrong_location", "not_executed", "incomplete", "not_reached")
_NOT_SELECTED = ("this call ran only the rows `--at` / `--oracle` named, so this check is not proved yet: a call with no `--at` and no "
                 "`--oracle` walks the rest (it needs a model entry for each check that has none)")


def _product_entry_holds(ctx: ProbeCtx, entry: dict, check: dict) -> str:
    """`""` when the product receipt a `product` entry names stands for `check`, else ONE sentence naming what failed (EP-W; t-2064 P4b
    item 6). DATA only (AR-29): the critic names the receipt and the check; this joins them - (1) the file `entry["product"]` exists under the
    story folder (a path out of it is refused: a role cannot point the tool elsewhere), is a JSON object; (2) it is of the product level
    (`proof_level.PRODUCT`); (3) it speaks for the test as it stands (`proof_level.product_receipt_holds`, the one reader: the same bytes or
    the same test, no issues of its own, scope absent - an old receipt - or `one_check`, never `whole_unlisted`; NOT `valid_level`, which is
    None for a `one_check` receipt by design); (3b) a `one_check` receipt's `checks` name `check` (`_location_hits`); (4) its `assertion_location` lies on the span of `check` (`_location_hits`). A receipt with no location
    read is not on any span: the entry is refused, never taken. Reads; writes nothing. Error direction: any doubt is a reason."""
    shown = str(entry.get("product") or "").strip()
    if not shown:
        return "the entry names no receipt path"
    base = Path(ctx.task_root).resolve()
    given = Path(shown)
    try:
        path = (given if given.is_absolute() else base / given).resolve()
        path.relative_to(base)
    except (ValueError, OSError):
        return f"{shown} is not a path under the story folder"
    try:
        data = path.read_bytes()
        receipt = json.loads(data.decode("utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        return f"no readable JSON receipt file at {shown}"
    if not isinstance(receipt, dict):
        return "the receipt is not a JSON object"
    if receipt.get("proof_level") != proof_level.PRODUCT:
        return f"its level is {receipt.get('proof_level')!r}, not the product's ({proof_level.PRODUCT})"
    ref = {"path": path.relative_to(base).as_posix(), "sha256": sha256(data)}
    got = proof_level.product_receipt_holds(ctx.entry, ref, ctx.task_root, ctx.root)      # B1: the receipt's own guards, minus the one-check scope line
    if not got["holds"]:
        return got["why"] or "it does not speak for the test as it stands"
    location = str(receipt.get("assertion_location") or "")
    if not location:
        return "its assertion location is not read, so it is on no check's span (the doors of the check: `actual`, `find`, `invert`)"
    if receipt.get("scope") == proof_level.ONE_CHECK and not any(_location_hits(shown_key, ctx.spec, check) for shown_key in got["keys"]):
        # EP-W: a new receipt claims only what its `checks` hold - the key is joined by the one position reader (the same file form and span)
        named = ", ".join(got["keys"]) or "no check"
        return f"it proves {named}, not {check['key']}: a product receipt stands for the one check it names"
    if not _location_hits(location, ctx.spec, check):
        return f"its location {location} is not on the span of {check['key']} ({check['file']}:{check['line']}-{check['end_line']})"
    return ""


def _ordinal_of(ref) -> int:
    """The ordinal of a check - the n-th on its line - the ONE reading of it (F7): a plan row's own `ordinal` field (`checks_of` wrote it,
    F1) when it is a positive int; else the `n` of its key `<file>:<line>#n` (`ref` is the key itself, or a row with no field), 1 for a key
    with no `#n`. Pure."""
    given = ref.get("ordinal") if isinstance(ref, dict) else None
    if isinstance(given, int) and not isinstance(given, bool) and given >= 1:
        return given
    found = re.search(r"#(\d+)$", str(ref.get("key") if isinstance(ref, dict) else ref))
    return int(found.group(1)) if found else 1


def _per_check_read(ctx: ProbeCtx, check: dict):
    """The per-check record of `check` as a dict (the one reader `_read_check_record`: the record of THIS check's file, under the id the
    call's records live under: `_records_id`, an alternative's own), or None when it is absent, unreadable or not an object. Reads one file."""
    return _read_check_record(ctx.task_root, _records_id(ctx), check["line"], _ordinal_of(check), file=check.get("file"))


def _aggregate_rows(ctx: ProbeCtx, plan: dict, entries: list, walk: dict) -> list:
    """The `checks[]` rows of the aggregate, one per check of the plan in plan order (a private helper of `_aggregate_record`). Each is
    `{key, then, probe_kind, supposes | reason, entry, statement_sha, verdict, cause, proved_by, run, read_in_joint, note, restore}`;
    `entry` is the model entry WHOLE as the critic wrote it (the replay's producer, AR-22), `cause` is set on `incomplete` only. A key
    the walk skipped as proved is read back from its per-check record (an unreadable one is `incomplete`, never proved: AR-28). An outcome
    whose verdict this module does not know is `incomplete`, `cause: tooling`, never a proof. A key with no outcome and no reason to be
    without one is `not_reached` (the walk has not got there). Reads files; writes nothing."""
    picked = _pick_entries(ctx, entries)
    outcomes, skipped, carried = walk.get("outcomes") or {}, set(walk.get("proved") or []), set(walk.get("carried") or [])
    only = set((plan or {}).get("only") or [])       # the rows a selection (`--at` / `--oracle`) names; empty: the whole plan
    run_of = {key: one.get("run") for one in (plan or {}).get("runs") or [] for key in one.get("keys") or []}
    rows = []
    for check in (plan or {}).get("checks") or []:
        key, entry = check["key"], picked.get(check["key"])
        kind = (entry or {}).get("kind")
        row = {"key": key, "then": check.get("then"), "probe_kind": kind, "entry": entry,
               "entry_by": None if entry is None else ENTRY_BY_CODE if entry.get("by") == ENTRY_BY_CODE else ENTRY_BY_ROLE, "statement_sha": check.get("statement_sha"),
               "verdict": "incomplete", "cause": "judgment", "proved_by": None, "run": run_of.get(key), "read_in_joint": False,
               "note": "", "restore": None}
        if kind == "invert":
            row["reason"] = entry.get("invert")
        elif entry is not None:
            row["supposes"] = entry.get("supposes", "")
        if entry is None:
            why = ((plan or {}).get("unmodellable") or {}).get(key)
            if why:     # EP-R: no role at this call and no inversion for this form: this row alone is tooling, the others walk
                row.update(cause="tooling", note=why)
            else:
                row["note"] = "no model entry stands for this check, so nothing was edited for it"
        elif kind == "not_here":
            row.update(verdict="not_owed", cause=None, reason=entry.get("not_here"),
                       note="this instance does not reach the check (the critic's word, EP-T); code does not judge it")
        elif kind == "product":
            held = _product_entry_holds(ctx, entry, check)      # EP-W: the critic names the receipt, code joins it; no run for this row
            if held:
                row.update(note=f"the product receipt {entry.get('product')} does not hold for this check: {held}")
            else:
                row.update(verdict="intended_failure", cause=None, proved_by="critic", reason=None,
                           note=f"proved by the product receipt {entry.get('product')} (the critic's entry, EP-W): no run of this call")
                row["product"] = entry.get("product")
        elif key in outcomes:
            got = outcomes[key] if isinstance(outcomes[key], dict) else {}
            verdict = got.get("verdict")
            if verdict in _AGG_KNOWN:
                row.update(verdict=verdict, cause=got.get("cause") or ("tooling" if verdict == "incomplete" else None),
                           proved_by=got.get("proved_by") if verdict == "intended_failure" else None)
            else:
                row.update(verdict="incomplete", cause="tooling", note=f"the walk gave the verdict {verdict!r}, which this tool does not know")
            if row["verdict"] == "incomplete" and row["cause"] == "judgment" and isinstance(got.get("judgment_facts"), dict):
                row["owes_judgment"] = True      # B2: the walk wrote facts for this check; `--judge --check` has something to judge
            row["read_in_joint"] = bool(got.get("read_in_joint"))
            row["note"] = row["note"] or str(got.get("note") or "")
            row["restore"] = got.get("restore") if isinstance(got.get("restore"), dict) else None
        elif key in skipped or key in carried:
            stored = _per_check_read(ctx, check)      # the walk's own reader: the record of THIS check's file, through the one function (F7)
            want = ("intended_failure",) if key in skipped else _CARRIED_VERDICTS
            if isinstance(stored, dict) and stored.get("verdict") in want:
                row.update(verdict=stored["verdict"], cause=None, proved_by=stored.get("proved_by") if stored["verdict"] == "intended_failure" else None,
                           read_in_joint=bool(stored.get("read_in_joint")),
                           note=("proved on these bytes by an earlier call; the run was skipped" if key in skipped else
                                 f"{stored['verdict']} on these bytes and this entry by an earlier call; carried as it stands, no run (it is not a proof)"))
            else:
                row.update(cause="tooling", note="the walk skipped this check as settled but its per-check record cannot be read now: not proved")
        elif key in set(walk.get("from_records") or []):
            stored = _per_check_read(ctx, check)      # a rebuild after `--judge` (item 5): this row is what its per-check record says now
            if isinstance(stored, dict) and stored.get("verdict") in _AGG_KNOWN:
                row.update(verdict=stored["verdict"], cause=stored.get("cause") or ("tooling" if stored["verdict"] == "incomplete" else None),
                           proved_by=stored.get("proved_by") if stored["verdict"] == "intended_failure" else None,
                           read_in_joint=bool(stored.get("read_in_joint")), note=str((stored.get("notes") or [""])[-1] or ""))
                if isinstance(stored.get("judgment"), dict):
                    row["judgment"] = stored["judgment"]
                    if stored["judgment"].get("verdict") == "cannot_judge" and isinstance(stored.get("judgment_facts"), dict):
                        row["judgment_facts"] = stored["judgment_facts"]      # B2: what the person is shown (only a `cannot_judge` row carries them)
                elif row["verdict"] == "incomplete" and row["cause"] == "judgment" and isinstance(stored.get("judgment_facts"), dict):
                    row["owes_judgment"] = True
            else:
                row.update(cause="tooling", note="this check's per-check record cannot be read now: not proved")
        elif only and key not in only:       # F2: a selection (`--at` / `--oracle`) did not name it: it is unproved and the door says what proves it
            row.update(verdict="not_reached", cause=None, note=_NOT_SELECTED)
        else:
            row.update(verdict="not_reached", cause=None, note="the walk has not reached this check yet")
        if row["verdict"] != "incomplete":
            row["cause"] = None
        if row["verdict"] == "no_failure" and "not_here" not in row["note"]:      # EP-T: the note of a surviving check names its door
            row["note"] = (row["note"] + "; " if row["note"] else "") + NO_FAILURE_DOOR
        rows.append(row)
    return rows


def _aggregate_verdict(rows: list, ended: str, selected=()) -> tuple:
    """`(verdict, cause or None, plan_unfinished)` of the aggregate (a private helper of `_aggregate_record`). In this order, the first
    that applies: (1) a check not reached - `ended` `stop` (EP-G): `incomplete`, `judgment`; `restore_failed`: `incomplete`, `tooling`;
    otherwise (the wall, or a walk between two rows): `incomplete`, `tooling`, unfinished - an unfinished plan is never `intended_failure`
    (EP-J). `selected` (the keys of an `--at` / `--oracle` call; empty: the whole plan) narrows `unfinished` to a SELECTED row not yet run
    (F2): the call's own rows are done and the others are only unproved, so the same call again would never finish the plan - the record is
    `incomplete`, `judgment` (models owed to the critic: `proof_level.probe_could_not_run` is False for it) and NOT unfinished, and its note names the door that finishes it; (2) any `incomplete` row with `cause: tooling`: `incomplete`, `tooling` (a mix with a tooling row is tooling); (3) a survivor:
    the first by `_SURVIVOR_ORDER`; (4) any other row not proved and not `not_owed`: `incomplete` with that row's cause; (5) every owed
    check proved and at least one proved (EP-K): `intended_failure`; (6) nothing proved (all `not_owed`): `incomplete`, `judgment`.
    Pure. The error goes only toward NOT `intended_failure`."""
    verdicts = [row["verdict"] for row in rows]
    if not rows:
        return "incomplete", "judgment", False
    if "not_reached" in verdicts:
        if ended == "stop":
            return "incomplete", "judgment", False
        pending = [row for row in rows if row["verdict"] == "not_reached" and (not selected or row["key"] in selected)]
        if selected and not pending and ended == "":
            return "incomplete", "judgment", False      # the selection ran its own rows: the rest is owed to the critic's models, never "the tool could not run"
        return "incomplete", "tooling", ended in ("", "time") and bool(pending)
    if any(row["verdict"] == "incomplete" and row["cause"] == "tooling" for row in rows):
        return "incomplete", "tooling", False
    for kind in _SURVIVOR_ORDER:
        if kind in verdicts:
            return kind, None, False
    other = next((row for row in rows if row["verdict"] == "incomplete"), None)
    if other is not None:
        return "incomplete", other["cause"] or "judgment", False
    if "intended_failure" in verdicts:
        return "intended_failure", None, False
    return "incomplete", "judgment", False


def _judgment_fold(rows: list, verdict: str, cause) -> dict:
    """The aggregate's own judgment keys, folded from its rows (fix round D, B2: the ONE producer of the top-level `judgment`,
    `judgment_facts` and `judgment_owed` that `proof_level.probe_record_state`, `probe_owes_judgment` and `cannot_judge_facts` read).
    `judgment_owed` is always written: the keys of the rows that owe the critic's `--judge` now (`owes_judgment`). `judgment` and
    `judgment_facts` are written ONLY when the aggregate is `incomplete` with `cause: judgment` and EVERY row of that kind carries a
    `cannot_judge` judgment (the critic has been asked on each and could not tell: the person's door opens); one such row - its judgment
    and facts as they are; several - `why` names each key (`<key>: <why>`), `at` is the latest, the facts are the first row's with `checks`
    naming every key. A row that owes a judgment, or one with no model yet, keeps the aggregate where it was (the critic's, or the plain
    call's). Copies recorded data; weighs nothing (AR-29). Pure."""
    owed = [r["key"] for r in rows if r.get("owes_judgment")]
    out = {"judgment_owed": owed}
    if verdict != "incomplete" or cause != "judgment":
        return out
    kind = [r for r in rows if r.get("verdict") == "incomplete" and r.get("cause") == "judgment"]
    cannot = [r for r in kind if isinstance(r.get("judgment"), dict) and r["judgment"].get("verdict") == "cannot_judge"
              and isinstance(r.get("judgment_facts"), dict)]
    if not kind or len(cannot) != len(kind):
        return out
    if len(cannot) == 1:
        out["judgment"], out["judgment_facts"] = dict(cannot[0]["judgment"]), dict(cannot[0]["judgment_facts"], checks=[cannot[0]["key"]])
        return out
    latest = max(cannot, key=lambda r: str(r["judgment"].get("at") or ""))["judgment"]
    out["judgment"] = {"verdict": "cannot_judge", "quote": "", "by": latest.get("by"), "at": latest.get("at"), "facts_sha": "",
                       "why": " ".join(f"{r['key']}: {' '.join(str(r['judgment'].get('why') or '').split())}" for r in cannot)}
    out["judgment_facts"] = dict(cannot[0]["judgment_facts"], checks=[r["key"] for r in cannot])
    return out


def _aggregate_record(ctx: ProbeCtx, plan: dict, entries: list, walk: dict, body_span=None) -> dict:
    """Write `work/probes/<iid>.json` for a walk, the ONE writer of it (t-2064 P4b item 1; AR-14). Callable after EVERY row and at the
    end: `walk` is `_walk_plan`'s result so far (`outcomes`, and where it has them `plan_remaining`, `ended`, `proved`, `runs`,
    `restore`, `notes`, `evidence_refs`, `input_hash`); `plan` is `{"checks": checks_of rows, "runs": run_plan rows}`; `entries` are
    `load_models`' entries; `body_span` is `(file, first line, last line)` of the test body or None. Returns the record as written.
    It is written by `keep_standing_record` (an `incomplete` answer never replaces a stored `intended_failure`, it adds `last_attempt`)
    and otherwise by `atomic_json`: the very pair `_finish_record` writes with.

    Keys: everything `window_probe` and `_receipt_core` read (`verdict`, `mutation` `"invert"` as a compat spelling - the truth of what
    was edited is `checks[]` -, `failure_kind` `"assertion"` when `intended_failure`, `expected_*`/`actual_*`, `record`, `target`,
    `restore`, `proved_by`, `evidence_ref`, the obligation fields, the identity), the replay readers' (`test_node`, `mutation_detail`
    with NO `at`, `mutated_file(s)`, `test_file_sha256`), `words` (`s6_reprove` prints it), and `checks`, `plan_runs`, `plan_remaining`,
    `plan_unfinished`. `verdict`: `intended_failure` only under EP-K (every owed check proved, at least one proved, `not_owed` ones
    set aside); otherwise by `_aggregate_verdict`. `restore.verified` only when no outcome and no walk reported an unverified restore.

    THE CHECK THIS FUNCTION IS: `acceptance.py`'s `expected_location == actual_location` and `expected_reason == actual_reason` are
    VACUOUS for a walk - both pairs are written equal here (the first proved check's `file:line`; one fixed line naming the count), so
    acceptance checks only their shape. What a person may rely on is the verdict, which this function derives from the recorded per-check
    verdicts alone; no new gate is added. It judges nothing: it folds verdicts the walk and the critic recorded (AR-29).

    No check in the plan: NOTHING is written and `{"written": False, "reason": "no_checks", ...}` is returned (EP-A: an empty list never
    reads as "all proved"; the refusal naming the data row and `--at` is the caller's, t-2045 E-F)."""
    checks = (plan or {}).get("checks") or []
    if not checks:
        return {"written": False, "reason": "no_checks",
                "words": "the plan holds no check: no aggregate is written, and an empty list is never read as all proved"}
    walk = walk if isinstance(walk, dict) else {}
    rows = _aggregate_rows(ctx, plan, entries, walk)
    ended = str(walk.get("ended") or "")
    selected = list((plan or {}).get("only") or [])
    verdict, cause, unfinished = _aggregate_verdict(rows, ended, selected)
    unsettled = [r["key"] for r in rows if r["verdict"] == "not_reached" and selected and r["key"] not in selected]
    door = ([f"this call ran only the selected check(s); not proved yet: {', '.join(unsettled)}. The call that finishes the plan is the same "
             "call with no `--at` and no `--oracle` (it needs a model entry for each check that has none); this call again would not"]
            if selected and unsettled and not unfinished and not ended else [])
    remaining = list(dict.fromkeys(list(walk.get("plan_remaining") or []) + [r["key"] for r in rows if r["verdict"] == "not_reached"]))
    proved = [r for r in rows if r["verdict"] == "intended_failure"]
    owed = [r for r in rows if r["verdict"] != "not_owed"]
    left = [r["key"] for r in owed if r["verdict"] != "intended_failure"]
    by_key = {c["key"]: c for c in checks}
    first = by_key[proved[0]["key"]] if proved else None
    location = f"{first['file']}:{first['line']}" if first else None
    reason = f"{len(proved)} of {len(owed)} checks of the plan proved"
    kinds = {r["proved_by"] for r in proved}
    proved_by = (next(iter(kinds)) if len(kinds) == 1 else "critic" if kinds else None) if verdict == "intended_failure" else None
    # F5: the files EDITED for the rows (a row that has a verdict and an entry that edits: not `product`, `not_here`, a gap or an unreached row), each once,
    # in plan order; for `--oracle` the oracle's file FIRST, because `proof_level._replay` builds `<mutated_file.path>::<oracle_function>` from the first
    oracle_file = str((plan or {}).get("oracle_file") or "") if (plan or {}).get("oracle_function") else ""
    edited = list(dict.fromkeys(str(c["file"]) for c, r in zip(checks, rows)
                                if r["verdict"] not in ("not_reached", "not_owed") and r.get("probe_kind") in ("actual", "find", "invert")))
    if oracle_file:
        edited.sort(key=lambda shown: not _same_file(shown, oracle_file))       # stable: the oracle's file first, the rest in plan order
    bad = [one for one in [walk.get("restore")] + [r["restore"] for r in rows] if isinstance(one, dict) and one.get("verified") is not True]
    measured, test_sha, test_bytes, identity, mutated = not bad, None, b"", {}, []
    if measured:        # the author's bytes are back: only then are they measured as the author's
        try:
            test_bytes = ctx.path.read_bytes()
            test_sha = sha256(test_bytes)
            now = proof_level.instance_identity(ctx.entry, ctx.task_root, ctx.root)
            identity = (now["instance_identity"] or {}) if now["input_hash"] == test_sha else {}
        except Exception:
            test_bytes, test_sha, identity = b"", None, {}
        for shown in edited:
            try:
                path = Path(shown) if Path(shown).is_absolute() else ctx.root / shown
                data = path.read_bytes()
                mutated.append({"path": _rel_project(path, ctx.root), "sha256": sha256(data), "code_sha": proof_level.code_sha(data, path.name)})
            except OSError:
                mutated.append({"path": shown, "sha256": "", "code_sha": ""})
    restore_fact = {"verified": measured and test_sha is not None, "sha256": test_sha, "runs": int(walk.get("runs") or 0)}
    if bad:
        restore_fact["error"] = str(bad[0].get("error") or "an author's file was not put back verified")
        # q15: the move that undoes it and the bytes it could not put back - the file, its copy (kept) and the author's sha, as `_unrestored_exit` reads them
        restore_fact.update({k: bad[0][k] for k in ("copy", "file", "author_sha256") if bad[0].get(k)})
    fields, missing = obligation_fields(ctx.entry)
    assertion_id, line_id = fields.get("assertion_id"), None
    shown_id = assertion_id if isinstance(assertion_id, str) and assertion_id.strip() else None
    parsed = _ASSERTION_ID.match(shown_id.strip()) if shown_id else None
    if parsed:
        n, spot = int(parsed.group("line")), parsed.group("file")
        inside = next((c for c in checks if _same_file(spot, str(c["file"])) and c["line"] <= n <= (c.get("end_line") or c["line"])), None)
        if inside is not None:
            line_id = True if next((r for r in rows if r["key"] == inside["key"]), {}).get("verdict") == "intended_failure" else None
        elif body_span is not None and not (_same_file(spot, str(body_span[0])) and body_span[1] <= n <= body_span[2]):
            line_id = False
    anchor = first or checks[0]
    target = {"line": anchor["line"], "end_line": anchor.get("end_line") or anchor["line"], "assertion_id": shown_id, "is_assertion_id": line_id}
    reading = ((plan or {}).get("alternative") or {}) if ctx.alt else {}
    if ctx.alt:     # t-2064 P5: the REDIRECT - an alternative call writes its own record and never the instance's aggregate (INV: not a receipt)
        a_case, a_alt = parse_alternative_token(ctx.alt)
        out = alternative_record_path(ctx.task_root, C.test_instance_id(ctx.entry) or ctx.instance_id, a_case, a_alt)
        if verdict == "intended_failure" and reading.get("unmodelled"):
            # `proven` is ALL the Then's checks proved under the entry: a check of the Then with no entry of the reading proves nothing, so the
            # rows that did prove are not the Then's proof (no refusal: the critic reads the keys)
            verdict, cause = "incomplete", "judgment"
    else:
        out = record_path(ctx.task_root, ctx.instance_id)
    shown_test = _rel_project(ctx.path, ctx.root)
    # `mutation_detail` names ONE row: for `--oracle` the first check in the oracle's file, else the anchor; its `file` is the file THAT row lives in
    # (the line and the file always belong together). `_replay` reads `mutated_file.path` and `oracle_function`, never this `file`.
    detail_row = next((c for c in checks if oracle_file and _same_file(str(c["file"]), oracle_file)), anchor)
    detail_file = shown_test if _same_file(str(detail_row["file"]), ctx.spec["file"]) else _rel_project(
        Path(str(detail_row["file"])) if Path(str(detail_row["file"])).is_absolute() else ctx.root / str(detail_row["file"]), ctx.root)
    record = {
        "schema_version": 1, "probe_tool": "probe_by_code.py", "task": ctx.task, "dispatch_id": ctx.dispatch,
        "instance_id": ctx.instance_id, "case": ctx.case, "test_node": ctx.spec["node"], "verdict": verdict,
        "mutation": "invert", "mutation_kind": MUTATION_KIND, "proof_level": proof_level.LIVE,
        "failure_kind": "assertion" if verdict == "intended_failure" else None,
        "expected_location": location, "actual_location": location, "expected_reason": reason, "actual_reason": reason,
        "observed": {}, "input_hash": walk.get("input_hash"), "input_hash_source": "the walk's request" if walk.get("input_hash") else None,
        "test_file_sha256": test_sha, "test_code_sha": proof_level.code_sha(test_bytes, ctx.path.name) if test_sha else "",
        "instance_identity": identity, "instance_content_sha": identity.get("instance_content_sha", ""),
        "mutated_file": mutated[0] if mutated else None, "mutated_files": mutated,
        **fields, "manifest_fields_missing": missing, "target": target, "proved_by": proved_by,
        "evidence_ref": ((walk.get("evidence_refs") or [{}])[0] or {}).get("path"), "evidence_refs": list(walk.get("evidence_refs") or []),
        "request": None, "mutation_detail": {"file": detail_file, "line": detail_row["line"], "end_line": detail_row.get("end_line") or detail_row["line"],
                                              "checks": [c["key"] for c in checks],
                                              **({"oracle_function": plan["oracle_function"]} if (plan or {}).get("oracle_function") else {}),
                                              **({"oracle_note": plan["oracle_note"]} if (plan or {}).get("oracle_note") else {})},
        "restore": restore_fact, "checks": rows, "plan_runs": int(walk.get("runs") or 0), "plan_remaining": remaining,
        "plan_unfinished": unfinished, "walk_ended": ended, "words":f"{len(proved)} of {len(owed)} checks proved" + (f"; left: {', '.join(left)}" if left else ""),
        "notes": [str(n) for n in list((plan or {}).get("notes") or []) + list(walk.get("notes") or []) + door], "receipt": None,
        "receipt_missing": [],
        "record": out.relative_to(ctx.task_root).as_posix(),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if cause:
        record["cause"] = cause
    record.update(_judgment_fold(rows, verdict, cause))      # B2: the readers of the aggregate's judgment read what THIS writes
    if ctx.alt:
        item = reading.get("item") or {}
        record.update(alternative=ctx.alt, then=item.get("then"), reading=item.get("reading"), reading_sha=_reading_sha(item) if item else None,
                      mutation=ALTERNATIVE, mutation_kind=ALTERNATIVE_KIND, proof_level=None, proved_by=None if verdict != "intended_failure" else proved_by,
                      assertion_refs=reading.get("assertion_refs"), then_checks=list(reading.get("then_checks") or []),
                      unmodelled=list(reading.get("unmodelled") or []), why=record["words"] + (
                          f"; no entry of {ctx.alt} stands for {', '.join(reading['unmodelled'])} (a check of the same Then), so the Then is not proved"
                          if reading.get("unmodelled") else ""))
        record["words"] = record["why"]
        if not keep_standing_record(out, record):
            atomic_json(out, record)
        return record       # never `attach_receipt`, never `window_probe`: an alternative record is not a receipt and no window reads it
    if verdict == "intended_failure" and not unfinished and restore_fact["verified"]:
        # t-2064 P4b item 4, EP-K: the receipt comes from the AGGREGATE alone and only when the walk is complete (every owed check proved,
        # at least one proved: `_aggregate_verdict`); anything else leaves `receipt: None`, and a standing older record is never touched
        attach_receipt(record, ctx.entry, ctx.task_root)
    record["window_probe"] = window_probe(record)
    if not keep_standing_record(out, record):
        atomic_json(out, record)
    return record


# --- the flip (t-2064 P4b item 2): a call with no `--at` and no `--oracle` walks the plan ------------------------------------------------
# What stands for a check, in this order (`_entries_for`): (1) an entry of this window's model file, by key; (2) an entry stored in the
# instance's aggregate, joined by `statement_sha` (EP-U); (3) with no role at this call, an inversion written by code; (4) otherwise it is
# OWED, and the call is a refusal BEFORE a byte is written. Every function here errs toward the refusal: an unknown stage is a role.

NO_ROLE_REASON = "no role at this call"
ENTRY_BY_CODE, ENTRY_BY_ROLE = "code", "role"       # the `by` field of a stored entry: who wrote the model (F6); never read from a reason's wording


def _dispatch_stage(root: Path, task: str, dispatch: str, case: str) -> str:
    """The stage of the dispatch row `dispatch` names ("S5", "S6", ...), read from the very row `_judge_dispatch_why` reads
    (`find_active_dispatch`, which resolves a `parent_retry` ancestor id the same way); "" when it cannot be read (no row, an unreadable
    controller, a row with no stage). DATA only (AR-29). The error direction belongs to the caller: `_no_role` reads "" as a role."""
    import execution_request as ER
    from hooklib import artifact_root
    try:
        row = ER.find_active_dispatch(artifact_root(root=root), task, dispatch, [case], None)[2]
    except Exception:       # noqa: BLE001 - an unreadable story is "unknown", and unknown is a role
        return ""
    stage = row.get("stage") if isinstance(row, dict) else None
    return stage.strip() if isinstance(stage, str) else ""


def _no_role(ctx: ProbeCtx) -> bool:
    """True when no role can write a model at this call: the S6 close (`ctx.stage == "S6"`, `--s6-close`) or a call under a dispatch whose
    row says stage S6 (`_dispatch_stage`; `_dispatch_context` leaves `ctx.stage` empty on `--dispatch`). Invariant: an UNKNOWN stage (no row,
    no stage, an unreadable controller) is a role - the refusal, never an inversion written for a critic who could have modelled; and a
    `--mutation` value is never read as "no role" (a role cannot type its way out of a model)."""
    if ctx.stage == "S6":
        return True
    return bool(ctx.dispatch) and _dispatch_stage(ctx.root, ctx.task, ctx.dispatch, ctx.case) == "S6"


def _check_bytes(ctx: ProbeCtx, check: dict) -> bytes:
    """The bytes of the file `check` lives in, read for the planner's doors and a stored entry's test; b"" when unreadable."""
    shown = str(check.get("file") or "")
    if not shown or _same_file(shown, ctx.spec["file"]):
        path = ctx.path
    else:
        candidate = Path(shown)
        path = candidate if candidate.is_absolute() else ctx.root / candidate
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _rows_of_record(stored) -> list:
    """The `checks[]` rows of an aggregate (a dict) that carry a whole `entry` and a `statement_sha` (what EP-U joins on); [] for anything
    else (not a dict, no `checks`). Pure: the one filter `_stored_rows` and `replay_owed` both read through (AR-13)."""
    rows = stored.get("checks") if isinstance(stored, dict) else None
    return [r for r in rows if isinstance(r, dict) and r.get("statement_sha") and isinstance(r.get("entry"), dict)
            and isinstance(r["entry"].get("kind"), str)] if isinstance(rows, list) else []


def _stored_rows(ctx: ProbeCtx) -> list:
    """The stored rows (`_rows_of_record`) of the instance's aggregate on disk; [] when there is no aggregate or it cannot be read. Reads one file."""
    try:
        stored = json.loads(record_path(ctx.task_root, ctx.instance_id).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        return []
    return _rows_of_record(stored)


def _join_stored(rows: list, checks: list) -> list:
    """For each of `checks` (in order) the stored row whose `statement_sha` equals the check's - the n-th stored among equal ones for the n-th
    current - or None. EP-U's join, by the statement and never by a line; pure. The one join `_entries_for` and `replay_owed` both use."""
    by_sha: dict = {}
    for row in rows:
        by_sha.setdefault(row["statement_sha"], []).append(row)
    nth: dict = {}
    out = []
    for check in checks:
        sha = check.get("statement_sha")
        ordinal = nth[sha] = nth.get(sha, -1) + 1 if sha else 0
        same = by_sha.get(sha, []) if sha else []
        out.append(same[ordinal] if ordinal < len(same) else None)
    return out


def _standing_entry(stored, mine: set):
    """The entry of a stored row when it may stand for a call at all, else None: not an alternative's, not another instance's (`mine` holds
    the spellings that are this one, "" included) and not a code-written no-role inversion (that one never satisfies a role's call: a role
    cannot be spared its model by what code once wrote). Pure."""
    old = stored["entry"] if stored else None
    if old is not None and (old.get("alternative") or old.get("instance", "") not in mine or _code_written(stored)):
        return None
    return old


def _code_written(stored: dict) -> bool:
    """Is the entry of the stored row `stored` an inversion CODE wrote because no role was at the call (F6, FR-12)? Read by a FIELD, never by
    the reason's wording: the row's `entry_by` (`_aggregate_rows` stamps `"code"` or `"role"` on every row that has an entry), else the
    entry's own `by` (what `_entries_for` stamped on the inversion): `"code"` yes, any other value no. MIGRATION EDGE: a row stored before
    these fields existed carries neither; it is read by the OLD rule (kind `invert` and the reason `NO_ROLE_REASON`) until a walk re-stores it
    with `entry_by`. Pure."""
    entry = stored["entry"]
    if entry.get("kind") != "invert":
        return False
    by = stored.get("entry_by", entry.get("by"))
    return by == ENTRY_BY_CODE if by is not None else entry.get("invert") == NO_ROLE_REASON


def _stands_on(data: bytes, spec: dict, entry: dict, check: dict) -> bool:
    """Does a stored `actual` / `find` entry still apply to `check` on `data`, the bytes of the check's file as they stand now (EP-U: a `find`
    that no longer stands once is not applied)? Asked of the planner itself (`plan_model` on that one entry), writing nothing; any refusal
    or error is "no". Other kinds need no bytes and stand."""
    if entry.get("kind") not in ("actual", "find"):
        return True
    try:
        plan_model(data, spec, [entry], [check])
    except Exception:       # noqa: BLE001 - not applied is the safe answer
        return False
    return True


def _stored_stands(ctx: ProbeCtx, entry: dict, check: dict) -> bool:
    """`_stands_on` for a call's own context: the bytes are those of the file `check` lives in (`_check_bytes`)."""
    if entry.get("kind") not in ("actual", "find"):
        return True
    return _stands_on(_check_bytes(ctx, check), ctx.spec, entry, check)


def replay_owed(record, data: bytes, spec: dict, reader_entry, bindings: list, helpers=()) -> list:
    """The keys of the plan's checks on the CURRENT bytes `data` that have no stored entry in `record` (t-2064 P4c item 1, EP-U): what a
    replay under a role would still owe the critic. PURE: it reads its arguments and nothing else - `record` is an aggregate already read
    (`work/probes/<iid>.json`), `data`, `spec`, `reader_entry`, `bindings` (and the optional `helpers`) are `checks_of`'s own arguments.
    A check is owed unless `_join_stored` finds the row of its statement in `record` AND that row's entry may stand (`_standing_entry`: a
    code-written no-role inversion does not, an alternative's does not) AND an `actual` / `find` still applies to the bytes (`_stands_on`).
    Err toward owed: a record that is not a dict, is unreadable, or has no `checks` owes EVERY key (an old single-probe record proved one
    check of several and wrote no reason); a test with no check owes nothing (`[]`), the one empty answer that is not an accident.
    A `checks_of` refusal (a file that does not parse) is the caller's to read. Judges nothing: a join by statement sha, a shape read (AR-29)."""
    checks = checks_of(data, spec, reader_entry, bindings, list(helpers or ()))
    if not checks:
        return []
    mine = {"", str(record.get("instance_id") or "")} if isinstance(record, dict) else {""}
    owed = []
    for check, stored in zip(checks, _join_stored(_rows_of_record(record), checks)):
        old = _standing_entry(stored, mine)
        if old is not None:
            shown = str(check.get("file") or "")
            here = data if not shown or _same_file(shown, spec["file"]) else next(
                (h["data"] for h in helpers or () if _same_file(str(h.get("file") or ""), shown)), b"")
            if _stands_on(here, spec, {"instance": "", "alternative": "", "supposes": "", **old, "check": check["key"]}, check):
                continue
        owed.append(check["key"])
    return owed


def _door_items(ctx: ProbeCtx, checks: list) -> list:
    """`[{key, line, doors}]` of `checks`: the items `load_models` and `_models_refusal` take, each with ONLY the doors that open for it
    (`_check_doors`; a file the planner cannot read opens the last two). The one builder of them (AR-15): the plain call and the
    alternative's both read it. Reads; writes nothing."""
    out = []
    for check in checks:
        try:
            doors = _check_doors(_check_bytes(ctx, check), ctx.spec, check)
        except Exception:       # noqa: BLE001 - a file the planner cannot read opens only the last two
            doors = ["not_here", "product"]
        out.append({"key": check["key"], "line": check["line"], "doors": doors})
    return out


def _entries_for(ctx: ProbeCtx, checks: list) -> dict:
    """What stands for each check of the plan (item 2, EP-U, EP-R): `{entries, owed, gaps, notes, path}`. `entries` are the model entries
    to walk (`load_models`' shape), `owed` the `_models_refusal` items (`{key, line, doors}`) of the checks that need a model and have none,
    `gaps` `{key: why}` the checks no entry can stand for under no role (an `invert: null` form, or the second check on a line, which the
    inversion cannot name), `notes` what the join did, `path` the window's model file as shown. Per check, in this order: (1) an entry of the
    window's model file `work/probe-models/<dispatch>.json` with no `alternative`, by key (an absent file is no entries; a file of the wrong
    shape is `load_models`' refusal); (2) the entry stored in the instance's aggregate whose `statement_sha` equals the check's, the n-th
    stored among equal ones for the n-th current - its `check` rewritten to the current key, and only when it still stands (`_stored_stands`)
    and is not a code-written no-role inversion (that one never satisfies a role's call: a role cannot be spared its model by what code once
    wrote); (3) `_no_role(ctx)`: an `invert` entry with `by: "code"` (and the reason `NO_ROLE_REASON`), written by code; (4) owed. Reads; writes nothing."""
    shown = f"work/probe-models/{ctx.dispatch}.json"
    items = _door_items(ctx, checks)
    file = ctx.task_root / "work" / "probe-models" / f"{ctx.dispatch}.json"
    models = load_models(ctx.task_root, shown, items) if ctx.dispatch and file.is_file() else []
    picked = _pick_entries(ctx, [m for m in models if not m.get("alternative")])
    joined_rows = _join_stored(_stored_rows(ctx), checks)       # the one join `replay_owed` reads too
    mine = {"", ctx.instance_id, C.test_instance_id(ctx.entry) or ctx.instance_id}
    entries, owed, gaps, notes, role = [], [], {}, [], None
    for check, item, stored in zip(checks, items, joined_rows):
        key = check["key"]
        if key in picked:
            entries.append(picked[key])
            continue
        old = _standing_entry(stored, mine)
        if old is not None:
            joined = {"instance": "", "alternative": "", "supposes": "", **old, "check": key}
            if _stored_stands(ctx, joined, check):
                entries.append(joined)
                if stored["key"] != key:
                    notes.append(f"the stored model of {stored['key']} stands for {key} (the same statement, joined by its sha)")
                continue
            notes.append(f"the stored model of {stored['key']} no longer stands on the bytes as they are, so it is not applied to {key}")
        if role is None:
            role = not _no_role(ctx)
        if role:
            owed.append(item)
        elif "#" in key.rsplit(":", 1)[-1]:
            gaps[key] = (f"{key} is the second check on its line, which the inversion cannot name by line yet, and no role is at this call "
                         "to write a model for it")
        elif not check.get("invertible"):
            gaps[key] = (f"the form of {key} has no inversion (`invert: null`) and no role is at this call to write a model for it")
        else:
            entries.append({"index": 0, "check": key, "instance": "", "alternative": "", "kind": "invert", "supposes": "",
                            "invert": NO_ROLE_REASON, "by": ENTRY_BY_CODE})
            notes.append(f"{key}: no model is stored and {NO_ROLE_REASON}: it is inverted (written by code)")
    return {"entries": entries, "owed": owed, "gaps": gaps, "notes": notes, "path": shown}


def _plan_of_test(ctx: ProbeCtx, run_cwd: Path, extra_refs=()) -> tuple:
    """`(checks, plan, notes)` of the test this call probes, through the one gatherer `--plan` uses (`_plan_inputs`): reads, writes nothing.
    `extra_refs` are a selection's lines (`_row_selection`): a check of a helper outside the plan is ADDED to it."""
    data, bindings, helpers, notes, reader_entry = _plan_inputs(ctx.root, ctx.task_root, ctx.cfg, ctx.spec, ctx.entry, ctx.case, ctx.path, run_cwd,
                                                                instance_id=ctx.instance_id, extra_refs=extra_refs)
    checks = checks_of(data, ctx.spec, reader_entry, bindings, helpers, notes)
    return checks, run_plan(checks), notes


def _row_selection(ctx: ProbeCtx, run_cwd: Path, at, oracle: str) -> dict:
    """What `--at` / `--oracle` select, read off the author's bytes (t-2064 P4b item 3; EP-O, EP-S): `{shown, extra, line, ordinal, spans}`.
    The FILE: `--oracle`'s file hint wins, then `--at`'s, then the test's own (through `_target_file`, the one guard of every language: under
    a test root, never the product tree). `--at <line>` (`<file>:<line>`, `<line>#2`): the line must be a check - the statement starts or spans
    there (`check_on_line`) - or the refusal `_no_check_refusal` names the nearest one; `--at` wins the row over `--oracle` (whose file still
    wins the file). `--oracle [<file>::]<function>` alone: the line spans of the declarations of that name that hold a check (`_Hop.units`; the
    test's own function too); no declaration, or none holding a check, is a refusal and never a pass. `extra` is what `_plan_inputs` adds to the
    plan (a helper's lines are real checks and join it); `_selected_keys` reads the rows off the finished plan. Reads; writes nothing."""
    spec = ctx.spec
    given = _parse_at_row(at) if at is not None else None
    hint, _, name = str(oracle or "").rpartition("::")
    if hint:
        path = _target_file(ctx, run_cwd, hint, "--oracle")
    elif given is not None and given[0] and not _same_file(given[0], spec["file"]):
        path = _target_file(ctx, run_cwd, given[0], "--at")
    else:
        path = ctx.path
    shown = spec["file"] if path.resolve() == ctx.path.resolve() else _rel_project(path, ctx.root)
    data, reader = path.read_bytes(), _reader_entry(spec)
    if given is not None:
        facts = check_on_line(data, shown, reader, given[1])
        if facts["found"] is None:
            raise _no_check_refusal(shown, given[1], facts)
        return {"shown": shown, "extra": [(shown, path, str(given[1]))], "line": given[1], "ordinal": given[2], "spans": None}
    hop = _Hop(path, data.decode("utf-8-sig", "replace"), reader, shown, "")
    units = [] if hop.unread else hop.units(name)
    if not units and name == spec["function"] and not hop.unread:
        try:
            own = hop.test_unit(spec)
        except Refusal:
            own = None
        units = [own] if own else []
    spans = [(u["first"], u["last"]) for u in units if u.get("check") is not None]
    if not spans:
        raise Refusal(f"probe_by_code: --oracle {oracle} selects no check: " + (hop.unread or f"no declaration named `{name}` in {shown} holds "
                      "a check of a form the factory reads") + ". An oracle that selects nothing is never read as a pass: name the function "
                      "that holds the check (`--oracle [<file>::]<function>`), or the line, `--at <file>:<line>`; `--plan` lists the checks of "
                      "the test. Nothing was changed.")
    return {"shown": shown, "extra": [(shown, path, f"{a}-{b}") for a, b in spans], "line": None, "ordinal": 1, "spans": spans}


def _selected_keys(checks: list, selection: dict) -> list:
    """The keys of the plan's rows a selection names (`_row_selection`), in plan order. `--at`: ONE row - on a line with two checks the first
    (head order), `#n` the n-th that starts there; a line inside a longer statement is that statement's first check. `--oracle`: every
    check of the file whose line lies in a span of the function. No row is a refusal (a selection that selects nothing never runs the rest of
    the plan in its place)."""
    mine = [c for c in checks if _same_file(str(c["file"]), selection["shown"])]
    if selection["line"] is not None:
        line, ordinal = selection["line"], selection["ordinal"]
        here = [c for c in mine if c["line"] <= line <= c["end_line"]]
        if ordinal > 1:
            here = [c for c in here if c["line"] == line and _ordinal_of(c) == ordinal]
        if not here:
            raise Refusal(f"probe_by_code: line {line} of {selection['shown']} does not hold check number {ordinal} (`--at {line}#{ordinal}`): "
                          "`--plan` lists the keys of the checks. Nothing was changed.")
        return [here[0]["key"]]
    keys = [c["key"] for c in mine if any(a <= c["line"] <= b for a, b in selection["spans"])]
    if not keys:
        raise Refusal(f"probe_by_code: the function --oracle names holds no check the plan lists in {selection['shown']}: nothing is selected, "
                      "and nothing is read as a pass. `--plan` lists the checks. Nothing was changed.")
    return keys


def _settle_dead_copy(ctx: ProbeCtx, locks: list) -> list:
    """The notes of settling a copy a dead probe left (`_lock_test`, released at once; `[]` when none is left): the plan must be read off the
    author's bytes, not a killed run's. The one place of it (AR-15): a plain call and an alternative's both start here."""
    directory = copy_dir(ctx.root)
    if directory.is_dir() and any(directory.glob("*.meta")):
        _key, settled = _lock_test(ctx, locks)
        release_locks(locks)
        return settled
    return []


def _name_is_declared(ctx: ProbeCtx) -> bool:
    """Is the `--test` name declared in the test's file for the table reader (`declaration_candidates`, the old road's own question inside
    `locate_target`)? The AST reader proves its name by `locate` before a plan exists: True. Any doubt is False (the record then needs the
    manifest row to prove the name, `_tool_refusal_record`). Reads; writes nothing."""
    reader = _reader_entry(ctx.spec)
    if reader is None:
        return True
    try:
        src = Source(ctx.path.read_bytes().decode("utf-8-sig"), reader["lexer"], ctx.spec["file"])
        return bool(declaration_candidates(src, ctx.spec["entry"], ctx.spec["function"], False, ctx.spec["file"]))
    except (Refusal, OSError, UnicodeDecodeError, RecursionError):
        return False


def _empty_plan_refusal(ctx: ProbeCtx) -> ToolRefusal:
    """The refusal of a test with no check of a form the factory reads (EP-A: an empty list is never read as proved). A `ToolRefusal` as on
    the old road (E6 / N4: a gap of the factory's data): `main` leaves the record `refused: tool` for it (`_record_tool_refusal`, t-2143 N4,
    fix round I1 q13); `name_unproved` when no declaration of the name was found, as `locate_target` said it."""
    return ToolRefusal(f"probe_by_code: no check of a form the factory reads was found in {ctx.spec['file']} ({ctx.spec['node']}), so there "
                   "is nothing to probe, and an empty list is never read as proved. A row of references/detectors.json that reads the "
                   "test's form makes it listable (`probe_by_code.py --task <T> --instance <I> --test <node> --plan` prints what is "
                   "read); a check the Then names in a helper is probed by its line, `--at <file>:<line>`; a real check of a form the "
                   "factory does not read is reported `unverified` with the reason, never blamed on the author. Nothing was changed.",
                       name_unproved=not _name_is_declared(ctx))


def _repeat_look(ctx: ProbeCtx, notes: list) -> tuple:
    """`(the answer, the person's word)` - the one reader of the repeat question (D-0018: one probe call per instance, every check; only a
    person's word repeats it). The answer is `proof_level.already_probed`'s when this instance is already probed on these very bytes, else
    None; a person's recorded word that passes the repeat, the run budget or the proof levels unavailable, a record that cannot be read: each
    is None and its note goes into `notes` (the call walks; it errs only toward running, P1). The word is the text of a recorded word that passed THIS repeat (it was said
    after the newest record it repeats, so the record of its own repeat spends it: `word_passes`), else "" - and a blank text is no word.
    With a word the answer is None and the call walks AGAIN, the proved checks too (`_walk_plan`, `plan["rerun"]`): a person's word leads
    the factory through the gate, and the pass stays on the record in `notes`. Reads; writes nothing."""
    try:
        answer = proof_level.already_probed(ctx.entry, C.load_json(ctx.manifest_path) if ctx.manifest_path.is_file() else {}, ctx.task_root,
                                            project=ctx.root, dispatch=ctx.dispatch, stage=ctx.stage)
    except Exception as exc:        # noqa: BLE001 - the repeat check never stops a probe
        notes.append(f"the repeat check failed ({type(exc).__name__}: {str(exc)[:160]}); the probe runs")
        return None, ""
    if answer.get("probed"):
        return answer, ""
    notes.extend(str(n) for n in answer.get("notes") or [])
    return None, str(answer.get("word") or "").strip()


def _repeat_record(ctx: ProbeCtx, answer: dict):
    """The record an `already_probed` answer stands on, as a dict: the receipt (`by: receipt`), the probe record or the product record it
    names; None when it cannot be read. Reads one file."""
    path = (answer.get("receipt_ref") or {}).get("path") if answer.get("by") == "receipt" else answer.get("record")
    try:
        stored = json.loads((ctx.task_root / str(path)).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError, TypeError):
        return None
    return stored if isinstance(stored, dict) else None


def _repeat_is_new(ctx: ProbeCtx, answer: dict) -> bool:
    """Is the standing record the one of a WALK (it holds `checks`), and so judged against the plan's entries? An OLD record (a single probe
    of one check, written before this batch: no `checks`) and a product record stand on the bytes alone (EP-I: they say they prove one check;
    they are never read as "every model owed"). A walk record that cannot be read is new: the safe side, the call walks."""
    if answer.get("by") == "product_record":
        return False
    stored = _repeat_record(ctx, answer)
    return stored is None or isinstance(stored.get("checks"), list)


def _repeat_same_entries(ctx: ProbeCtx, answer: dict, checks: list) -> bool:
    """Does the receipt of a walk (`by: receipt`, `checks[]` with `entry_sha`) still stand for THIS call: the same plan (the same keys with
    the same statements) and no model entry of this window's file that differs from the one the receipt was made for (`_entry_sha`)? A
    probe record of a walk that is not a receipt (a survivor, an unfinished plan) is never a repeat: it walks (§14). A check with no entry in
    the file stands on the one the receipt holds (the stored model): nothing runs on a repeat, so no model is owed. Any doubt is False: the
    changed check runs again. A proved row the walk runs (`actual`, `find`, `invert`; a kind not established is read as walked) whose
    per-check record is absent, unreadable or disagrees with the receipt on verdict or `entry_sha` is not a repeat: the call walks (FR-59,
    error direction: walk); a `product` row has no per-check record and stands on its product receipt. Reads; writes nothing."""
    if answer.get("by") != "receipt":
        return False
    rows = (_repeat_record(ctx, answer) or {}).get("checks")
    if not isinstance(rows, list) or len(rows) != len(checks):
        return False
    file = ctx.task_root / "work" / "probe-models" / f"{ctx.dispatch}.json"
    try:
        models = load_models(ctx.task_root, f"work/probe-models/{ctx.dispatch}.json",
                             [{"key": c["key"], "line": c["line"], "doors": []} for c in checks]) if ctx.dispatch and file.is_file() else []
    except Exception:        # noqa: BLE001 - the shape refusal is `_entries_for`'s, on the walk
        return False
    picked = _pick_entries(ctx, [m for m in models if not m.get("alternative")])
    stored_rows = None      # the standing aggregate's rows, read once and only for a check with no entry in the file
    for check, row in zip(checks, rows):
        if not (isinstance(row, dict) and row.get("key") == check["key"] and row.get("statement_sha") == check.get("statement_sha")
                and row.get("verdict") in ("intended_failure", "not_owed")):
            return False
        if check["key"] in picked and _entry_sha(picked[check["key"]]) != row.get("entry_sha"):
            return False
        if row["verdict"] != "intended_failure":
            continue        # a not_owed row never runs: it has no per-check record
        kind = (picked.get(check["key"]) or {}).get("kind")
        if kind is None:
            if stored_rows is None:
                # `_repeat_record` reads `answer["record"]` for any `by` but "receipt"; for a receipt answer that is the aggregate the receipt names
                stored_rows = (_repeat_record(ctx, {**answer, "by": "probe_record"}) or {}).get("checks")
                stored_rows = stored_rows if isinstance(stored_rows, list) else []
            kind = next(((one.get("entry") or {}).get("kind") for one in stored_rows
                         if isinstance(one, dict) and one.get("key") == check["key"] and isinstance(one.get("entry"), dict)), None)
        if kind == "product":
            continue        # proved by its product receipt, never run: no per-check record
        stored = _per_check_read(ctx, check)        # actual / find / invert, or a kind not established (unknown: read as walked)
        if not (isinstance(stored, dict) and stored.get("verdict") == "intended_failure" and stored.get("entry_sha") == row.get("entry_sha")):
            return False
    return True


def _repeat_answer(ctx: ProbeCtx, answer: dict, notes: list, info: str = "") -> dict:
    """The answer of a repeat: `{"verdict": "already_probed", ...}` in the old road's shape (`_repeat_check`), which `main` prints with exit 0.
    Nothing was mutated, launched or written; `info` is the one line an old record adds."""
    return {"verdict": "already_probed", "instance_id": ctx.instance_id, "by": answer["by"], "level": answer["level"],
            "receipt_ref": answer["receipt_ref"], "record": answer["record"], "prior_verdict": answer["prior_verdict"],
            "recorded_at": answer["recorded_at"], "holds": answer["holds"], "words": answer["words"], "block": answer["block"],
            "notes": list(notes) + list(answer.get("notes") or []) + ([info] if info else [])}


def _shape_context(ctx: ProbeCtx, data: bytes) -> str:
    """The code just before the test's declaration (where a display name stands) - what `run_shape_checks` reads for its hint, read WITHOUT
    planning any mutation: the declaration is the test's, whichever check a row selects. "" for the AST reader, or when the declaration is
    not located (the hint is then left out of a refusal's text; it never decides one). Pure."""
    reader = _reader_entry(ctx.spec)
    if reader is None:
        return ""
    try:
        src = Source(data.decode("utf-8-sig"), reader["lexer"], ctx.spec["file"])
        found = locate_target(src, ctx.spec["entry"], ctx.spec["function"], None, False, ctx.spec["file"], ctx.spec["language"])
        return _context(src, found["declaration"]) if found["declaration"] is not None else ""
    except (Refusal, UnicodeDecodeError, RecursionError):
        return ""


def _shape_refusals(ctx: ProbeCtx, entries: list, checks: list, only=None) -> None:
    """R6 on the walk's road (t-2064 fix round A, B1): `run_shape_checks` - every row of the case has a selector and a report id, `--test`
    names the row's file, the report id ends with the `--test` tail, a compiled launch allows a rebuild - ONCE per call, for a test the table
    reads (`ctx.detector`). Raises its refusal (exit 2, "Nothing was changed"). POSITION: after the entries are resolved and every model
    refusal (an owed model is refused first, as built) and before the first write - `_probe_plan` calls it before `_walk_plan`, and the walk
    is the only thing that writes. INVARIANT it preserves: the mutated test is the test the run selects, and a request the builder would
    refuse is the CALL's fault (FR-46), refused before a byte, never the story's `not_executed`, and a pass of another test or of a binary
    that was not rebuilt is never read as this check's survival (AR-28). It runs only when at least one row WILL run (`only`, a selection's
    keys, narrows it; None = the whole plan): a plan with no live row builds no request, so no request is judged. Reads; writes nothing
    (the test is read unlocked: a copy a dead probe left was settled at the top of `_probe_plan`, and a live probe of this file refused there)."""
    if not ctx.detector:
        return
    picked = _pick_entries(ctx, entries)
    if not any(one["kind"] not in ("not_here", "product") and (only is None or key in only)
               for key, one in picked.items() if key in {c["key"] for c in checks}):
        return
    data = ctx.path.read_bytes()
    run_shape_checks(ctx.cfg, C.load_json(ctx.manifest_path) if ctx.manifest_path.is_file() else {}, ctx.case, ctx.entry, ctx.spec,
                     ctx.instance_id, _shape_context(ctx, data), data.decode("utf-8-sig", "replace"), ctx.root)


def _locating_refusals(ctx: ProbeCtx, entries: list, checks: list, only=None) -> None:
    """Locate every row that WILL run, once, before the first write (t-2064 fix round I1, q11; the same pattern as `_shape_refusals`). The ONE
    function is `_located` (the one that `plan_model` calls for each row and that raises `_refuse_conditional_compilation`): a `ToolRefusal`
    of locating - a file that holds `#if/#else/#endif`, a lexer that cannot read it - is the CALL's refusal (exit 2, the old road's text and
    door, "Nothing was changed"), never a tooling row after a write. POSITION: after the entries are resolved and every model, product and
    R6 refusal, before `_walk_plan` (the one writer). INVARIANT it preserves: a mutation is never planned onto a branch that may be inactive
    and a pass of it never read as the check's survival (AR-28), and the project tree, the story folder and the lock are untouched after the
    refusal. A refusal of another kind (an ordinal beyond the count, a file that is not UTF-8, a statement that moved) stays what it was, the
    row's own outcome in the walk. WHY the walk cannot refuse after this pass: `_located` reads only the bytes of the check's file, and
    the walk reads that same file under its lock, byte for byte the author's (every run is restored from the verified copy before the next
    row); a file that changed in between is a different file and is a row, as before. `only` narrows to a selection's keys (None = all). Reads;
    writes nothing."""
    picked = _pick_entries(ctx, entries)
    for check in checks:
        one = picked.get(check["key"])
        if one is None or one["kind"] not in ("actual", "find", "invert") or (only is not None and check["key"] not in only):
            continue
        shown = str(check.get("file") or ctx.spec["file"])
        path = ctx.path if _same_file(shown, ctx.spec["file"]) else (Path(shown) if Path(shown).is_absolute() else ctx.root / shown)
        try:
            data = path.read_bytes()
        except OSError:
            continue        # an unreadable file is the walk's row ("could not be read"), as before
        try:
            _located(data, ctx.spec, check)
        except ToolRefusal:
            raise
        except Refusal:
            continue


def _probe_plan(ctx: ProbeCtx, run_cwd: Path, locks: list, timeout: float, at=None, oracle: str = "") -> dict:
    """Every call that is not an alternative probe: list the checks, find what stands for each (`_entries_for`), refuse BEFORE a byte is
    written when any is owed, else walk the plan (`_walk_plan`) and answer with the aggregate it wrote (`work/probes/<iid>.json`).
    `--at` and `--oracle` (t-2064 P4b item 3; EP-O, EP-S) are SELECTIONS of rows of that plan, on this one road (`_row_selection`,
    `_selected_keys`): the selected rows only run, each ALWAYS gets its per-check record, the aggregate is rebuilt by its one writer
    (`_aggregate_record`) over the WHOLE plan - the other rows keep what their records say (proved on these bytes with the same entry: carried
    as proved; anything else: `not_reached`, an unsettled row) - and a receipt exists only when the whole plan is complete, so a selection
    NEVER publishes one check of several. A helper's line outside the plan is added to it (a real check) and stays on it, owed (`_plan_inputs`,
    `_stored_plan_refs`). POSITION of the selection: after every refusal that precedes a probe (`_probe`) and after the settling of a dead copy,
    before any lock or byte; INVARIANT it preserves: only the SELECTED rows need an entry to run - their refusal (`_models_refusal`, the same
    text and door as a plain call, which a flag never opens: `--at` is no bypass of a model) comes first; another owed check is not a refusal of
    this call, it stays owed (an unsettled row of the aggregate, so no receipt appears) - and a selection that selects no check is a
    refusal, never a pass and never a run of the rest of the plan in its place.
    POSITION of a plain call: after every refusal that precedes a probe (flags, the manifest row, the dispatch, the test file), so nothing refused before is
    reachable now; a refusal here takes no lock and writes nothing. The REQUEST refusals of the run shape (R6, `_shape_refusals`) come last of them: after
    the entries are resolved and the owed model refused, before `_walk_plan` (the one writer), once per call, for the rows that will run. The one thing done before it is settling a copy a dead probe left
    (`_lock_test`, released at once): the plan must be read off the author's bytes, not a killed run's, and a refusal that read mutated
    bytes would repeat forever. An empty plan is a refusal (EP-A: an empty list never reads as proved); no live key (`not_here`, `product`
    or gaps only) writes the aggregate here, under the lock, with no run - the record states `not_owed` and unsettled rows, never a proof.
    Returns the record THIS call built (`_walk_plan` hands it back), never a re-read of the file: under `keep_standing_record` an older
    proved aggregate may stay on disk after a partial call."""
    settled = _settle_dead_copy(ctx, locks)
    selection = _row_selection(ctx, run_cwd, at, oracle) if at is not None or oracle else None
    checks, runs, plan_notes = _plan_of_test(ctx, run_cwd, selection["extra"] if selection else ())
    if not checks:
        raise _empty_plan_refusal(ctx)
    repeat, word = None, ""
    if selection:       # a selection is never answered `already_probed`; only the person's word is read (it re-runs the SELECTED proved rows)
        word = _repeat_look(ctx, [])[1]
        if word:
            settled.append(f"a person's recorded word passes this repeat of the probe: {word}")
    else:
        repeat, word = _repeat_look(ctx, settled)       # fix round A, B3: the old road's one question, before `_entries_for`
    if repeat is not None and not _repeat_is_new(ctx, repeat):        # an old record on these bytes stands: never "every model owed" (EP-I)
        return _repeat_answer(ctx, repeat, settled, "the record was written before the probe walked every check of a test: it proves one "
                                                    "check, and it stands on these bytes (EP-I)")
    if repeat is not None and _repeat_same_entries(ctx, repeat, checks):
        return _repeat_answer(ctx, repeat, settled)       # a complete aggregate on these bytes and the same entries: answered, nothing runs
    only = _selected_keys(checks, selection) if selection else []
    got = _entries_for(ctx, checks)
    owed = [item for item in got["owed"] if item["key"] in only] if selection else got["owed"]
    if owed:
        raise _models_refusal(got["path"], owed)
    by_key = {c["key"]: c for c in checks}
    failed = [(one["check"], _product_entry_holds(ctx, one, by_key[one["check"]])) for one in got["entries"]
              if one["kind"] == "product" and one["check"] in by_key and (not selection or one["check"] in only)]
    failed = [(key, why) for key, why in failed if why]
    if failed:      # EP-W: a product entry that does not hold is a refusal naming what failed, before a byte is written
        raise Refusal("probe_by_code: the `product` entry of " + "; ".join(f"{key} does not hold: {why}" for key, why in failed) + ". A product "
                      "receipt counts only for the check it names, through the critic's `product` entry (the receipt of "
                      f"`{RED_SANDBOX_DOOR}`, its location on that check's span); the other doors of the check are an `actual`, `find` or "
                      f"`invert` entry in {got['path']} (those are walked). Nothing was changed.")
    _shape_refusals(ctx, got["entries"], checks, only if selection else None)
    _locating_refusals(ctx, got["entries"], checks, only if selection else None)       # q11: located once, before `_walk_plan` writes
    plan = {"checks": checks, "runs": runs, "notes": list(settled) + got["notes"], "unmodellable": got["gaps"], "only": only, "rerun": bool(word)}
    if selection and selection["spans"] is not None:     # `--oracle`: what the old road told its reader stays on the record (AR-21)
        name = str(oracle).rpartition("::")[2]
        plan["oracle_function"], plan["oracle_file"] = name, selection["shown"]        # the file the aggregate names as edited (F5)
        plan["oracle_note"] = (f"the check lives in `{name}` ({selection['shown']}), which other tests may share - the mutation lives there for the "
                               "length of one run and is restored with it" if name != ctx.spec["function"] else "")
        plan["notes"].append(f"the oracle was named by hand: {oracle}" + (f"; {plan['oracle_note']}" if plan["oracle_note"] else ""))
    entries = got["entries"]
    if any(one["kind"] not in ("not_here", "product") for one in entries):
        walk = _walk_plan(ctx, plan, entries, locks, timeout)
    else:
        _lock_test(ctx, locks)
        span = test_body_span(ctx.path.read_bytes(), ctx.spec, _reader_entry(ctx.spec))
        walk = {"outcomes": {}, "plan_remaining": [], "ended": "", "notes": [], "restore": None, "flags_dropped": False, "unmodelled": [],
                "dropped": [], "proved": [], "runs": 0, "evidence_refs": [], "input_hash": None}
        walk["record"] = _aggregate_record(ctx, plan, entries, walk, (ctx.spec["file"], span[0], span[1]) if span else None)
    record = walk.get("record")
    if record is None:
        raise Refusal("probe_by_code: the aggregate record of the plan could not be written (" + "; ".join(str(n) for n in walk.get("notes") or [])[:300]
                      + "). The per-check records stand under work/probes/checks/; the same call again continues.")
    return record


def _row_publish(entry: dict, ref: dict, task_root, iid: str, new_rank: int) -> tuple:
    """(what the row got: `kept: ...`, `replaced` or `added`; the `tests[]` fragment it needs, or None).
    Never a downgrade: a row ref that already resolves to a VALID receipt of a higher level is kept."""
    row_ref = (entry.get("sensitivity_proof") or {}).get("receipt_ref") \
        if isinstance(entry.get("sensitivity_proof"), dict) else None
    row_level = proof_level.valid_level(entry, row_ref, task_root)
    if proof_level.rank(row_level) > new_rank:
        return f"kept: the row already names a valid receipt that {proof_level.words(row_level)}", None
    return "replaced" if row_ref else "added", [{"instance_id": iid, "sensitivity_proof": {"receipt_ref": ref}}]


def _held_action(existing: dict, entry: dict, task_root, new_rank: int) -> str:
    """`set`, or `kept: ...` when the binding's receipt is a VALID one of a higher level (a file that is
    gone, another instance's receipt or bytes that moved hold nothing)."""
    held = str(existing.get("probe_receipt_ref") or "")
    held_file = task_root / held if held and not pathlib.Path(held).is_absolute() else None
    if existing.get("sensitivity") == "proven" and held_file is not None and held_file.is_file():
        held_level = proof_level.valid_level(
            entry, {"path": held, "sha256": sha256(held_file.read_bytes())}, task_root)
        if proof_level.rank(held_level) > new_rank:
            return f"kept: the binding already names a valid receipt that {proof_level.words(held_level)}"
    return "set"


def _binding_items(obligations: list, manifest: dict, entry: dict, task_root, iid: str, ref_path: str,
                   new_rank: int, off_target: str = "") -> tuple:
    """(the `obligation_bindings[]` items for the fragment, the rows `record["publish"]["bindings"]` gets).
    A binding's `instance_ids` is the union of what it lists and this instance, because `manifest_put.py`
    REPLACES that list and a second instance of one obligation would otherwise erase the first.
    `off_target` (`proof_level.receipt_off_target(record)`, t-2007 F3): the probe broke another line than the obligation's check, so the
    binding is NOT published as `proven` (a probe of another line never counts, and `case_stamp` falls through to any `proven`
    binding); the row's `sensitivity_proof` stays, and the window keeps its off-target door."""
    aliases = set(C.instance_id_aliases(entry)) | {iid}
    by_id = {str(b.get("obligation_id")): b for b in manifest.get("obligation_bindings") or []
             if isinstance(b, dict)}
    bindings, rows = [], []
    for oid in obligations:
        existing = by_id.get(oid) or {}
        # what the binding lists minus the rows a retraction took out on purpose
        ids = proof_level.without_retracted(existing.get("instance_ids"), manifest)
        if not aliases & set(ids):
            ids.append(iid)
        item = {"obligation_id": oid, "instance_ids": ids}
        action = _held_action(existing, entry, task_root, new_rank)
        if off_target and action == "set":
            action = "not bound as proven: " + off_target
        if action == "set":
            item.update(sensitivity="proven", proof_kind="executed_red_probe", probe_receipt_ref=ref_path)
        bindings.append(item)
        rows.append({"obligation_id": oid, "instance_ids": ids, "receipt": action})
    return bindings, rows


def _put_fragment(task: str, fragment: dict) -> subprocess.CompletedProcess:
    """Run `manifest_put.py` over `fragment`. The fragment is scratch, not an artifact: it never lands in
    the story's own folder, where a guard and every later reader would treat it as one."""
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="qa-probe-binding-"))
    try:
        path = scratch / "manifest-fragment.json"
        atomic_json(path, fragment)
        return subprocess.run([sys.executable, "-B", str(pathlib.Path(__file__).with_name("manifest_put.py")),
                               "--task", task, "--fragment", str(path)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def publish_binding(task: str, task_root, record: dict) -> str:
    """Publish this probe's live receipt in the two places it is read, through ONE
    `manifest_put.py` fragment: `tests[]` (`sensitivity_proof.receipt_ref`, which delivery and
    the ledger read) and the obligation bindings (`probe_receipt_ref`, which the review receipt and
    the coverage map read).

    `window_record.py` publishes a review receipt only when every instance of the window is
    reached by `obligation_bindings[].probe_receipt_ref`, and `red_sandbox.py --probe` writes that
    row itself. This script did not - it wrote `work/probes/<IID>.json` and stopped - while the
    code critic's brief names it as the ONLY probe the role may run. So a critic that obeyed its
    brief could never receipt its window: live TP1-13797, run 5, seven critic dispatches and
    $13.64 on a receipt that was unreachable by construction, with both probes already on disk and
    both `intended_failure`.

    Never a downgrade: a row ref or a binding ref that already resolves to a VALID receipt of a
    higher level (a `red_sandbox.py --probe` receipt) is kept; the same level is replaced (the new
    bytes' proof). A binding's `instance_ids` is the union of what it lists and this instance,
    because `manifest_put.py` REPLACES that list and a second instance of one obligation would
    otherwise erase the first. Everything the publish did goes into `record["publish"]` (FR-14).
    Only a probe that showed the intended failure and restored the author's bytes has a receipt, so
    nothing is published for any other. Returns what it did, for the caller's own output.
    """
    if record.get("verdict") != "intended_failure":
        return ""
    receipt = record.get("receipt")
    if not isinstance(receipt, dict) or not receipt.get("path"):
        why = ("the restore was not verified" if not (record.get("restore") or {}).get("verified")
               else "the facts a receipt binds are missing: " + ", ".join(record.get("receipt_missing") or [])
               if record.get("receipt_missing") else "the receipt could not be written")
        record["publish"] = {"published": False, "why": why}
        return f"no live receipt, nothing published ({why})"
    task_root = pathlib.Path(task_root)
    manifest_path = task_root / "work" / "automation-manifest.json"
    manifest = C.load_json(manifest_path) if manifest_path.is_file() else {}
    try:
        entry = manifest_entry(task_root, record["instance_id"])
    except Refusal as exc:
        record["publish"] = {"published": False, "why": str(exc)}
        return f"nothing published: {exc}"
    iid = C.test_instance_id(entry) or record["instance_id"]
    new_rank = proof_level.rank(proof_level.LIVE)
    ref = {"path": receipt["path"], "sha256": receipt["sha256"]}
    fragment: dict = {}

    row, tests = _row_publish(entry, ref, task_root, iid, new_rank)
    if tests:
        fragment["tests"] = tests
    obligations = [str(oid) for oid in (record.get("obligation_ids") or []) if oid]
    bindings, rows = _binding_items(obligations, manifest, entry, task_root, iid, ref["path"], new_rank,
                                    proof_level.receipt_off_target(record))
    done: dict = {"published": True, "receipt": ref, "row": row, "bindings": rows}
    if bindings:
        fragment["obligation_bindings"] = bindings
    else:
        done["bindings_note"] = "no obligation_ids on this probe — the row is published, no binding"
    record["publish"] = done
    if not fragment:
        done["manifest_put"] = "nothing to put: a receipt of a higher level is already published"
        return done["manifest_put"]
    put = _put_fragment(task, fragment)
    from manifest_put import outcome
    put_kind, move = outcome(put.returncode, task)
    if put_kind == "stale":     # exit 4: the fragment IS in the journal, only the manifest's projection failed
        done["published"] = False
        done["manifest_put"] = f"committed, projection stale: {(put.stderr or put.stdout).strip()[-300:]}"
        return (f"manifest_put committed the publish but the manifest's projection is stale - run `{move}`; "
                f"the receipt stays at {ref['path']}")
    if put_kind == "refused":
        done["published"] = False
        done["manifest_put"] = f"refused: {(put.stderr or put.stdout).strip()[-300:]}"
        return f"manifest_put refused the publish, the receipt stays at {ref['path']}: {done['manifest_put']}"
    done["manifest_put"] = ((put.stdout or "").strip().splitlines() or ["ok"])[0]
    return (f"published {ref['path']}: row {done['row']}"
            + (f"; bound {', '.join(obligations)}" if obligations else "; no obligation ids to bind"))


PROBE_AGAIN = 'probe_by_code.py --task <T> --dispatch <D> --test "<node>" --instance <IID>'    # the door of a record to be made again


def _judge_refusal(what: str, door: str = "") -> Refusal:
    """A refusal of `judge_record`: what is wrong, what was expected, the door the critic can use (FR-1, FR-2)."""
    return Refusal(f"probe_by_code: --judge refused: {what}. {door + ' ' if door else ''}Nothing was written.")


JUDGE_CHECK_DOOR = ('probe_by_code.py --task <T> --dispatch <D> --judge "<instance>" --check "<key>" --verdict fires|other_failure|cannot_judge '
                    '--quote "<a line of its failure text>" [--why "<one sentence>"]')      # the door of a walk's aggregate: ONE check is judged per call
NO_FAILURE_DOOR = ("a check that survived its inversion (`no_failure`) is not weighed by `--judge`: write `not_here` for it in the model file "
                   "when this instance does not reach it (EP-T), or report a `test_defect` finding")


def _unsettled_checks(ctx: ProbeCtx, checks: list) -> dict:
    """`{key: per-check record}` of the checks of the plan that owe the critic's judgment now: the per-check record reads `incomplete`,
    `cause: judgment`, holds `judgment_facts` and no `judgment`. Reads the records; writes nothing."""
    out = {}
    for check in checks:
        stored = _per_check_read(ctx, check)
        if (stored and stored.get("verdict") == "incomplete" and stored.get("cause") == "judgment" and isinstance(stored.get("judgment_facts"), dict)
                and not isinstance(stored.get("judgment"), dict)):
            out[check["key"]] = stored
    return out


def _judge_walk(task_root: Path, root: Path, instance_id: str, agg: dict, entry: dict, check: str) -> tuple:
    """`(path of the per-check record, the record, entry, parts)` of the check `--judge --check` names in a walk's aggregate `agg`
    (t-2064 P4b item 5). `parts` is what the rebuild needs: `{ctx, run_cwd, checks, runs, agg, key}`. The plan is read off the author's bytes
    through the one gatherer (`_plan_of_test`). Refusals, all naming the door: the plan cannot be read; the key is not the plan's (they are
    listed); no key and not exactly one check owes the judgment (the unsettled ones are listed); the check owes none (a `no_failure` one
    names `NO_FAILURE_DOOR`); its record holds a judgment already. DATA only (AR-29): nothing here weighs a check."""
    try:
        cfg, spec = load_config(), parse_node(str(agg.get("test_node") or ""), root)
        path, run_cwd = _test_path(root, cfg, spec, entry)
        ctx = ProbeCtx(str(agg.get("task") or ""), str(agg.get("dispatch_id") or ""), instance_id, str(agg.get("case") or ""), spec, entry, root, cfg,
                       Path(task_root), _is_table(spec), "model", Path(task_root) / "work" / "automation-manifest.json", path, "")
        checks, runs, _notes = _plan_of_test(ctx, run_cwd)
    except Refusal as exc:
        raise _judge_refusal(f"the plan of this probe cannot be read again ({str(exc)[:240]})", f"Probe again with {PROBE_AGAIN}.") from exc
    keys = [c["key"] for c in checks]
    unsettled = _unsettled_checks(ctx, checks)
    if check and check not in keys:
        raise _judge_refusal(f"--check {check!r} is not a check of the plan of {instance_id!r}; the plan's keys are: {', '.join(keys) or 'none'}",
                             "Door: " + JUDGE_CHECK_DOOR)
    if not check:
        if len(unsettled) != 1:
            raise _judge_refusal("--check names the check to judge, and " + (
                f"{len(unsettled)} checks owe a judgment: {', '.join(unsettled)}" if unsettled else "no check of this probe owes a judgment now"),
                "Door: " + JUDGE_CHECK_DOOR)
        check = next(iter(unsettled))
    row = next(c for c in checks if c["key"] == check)
    stored = _per_check_read(ctx, row)
    if stored is None:
        raise _judge_refusal(f"the check {check!r} has no per-check record: it was not run by this probe", f"Run the probe first: {PROBE_AGAIN}.")
    if isinstance(stored.get("judgment"), dict):
        raise _judge_refusal(f"the check {check!r} already carries a judgment, and a written judgment is never rewritten",
                             f"Probe the test again with {PROBE_AGAIN} (the new record is judged on its own).")
    if check not in unsettled:
        what = f"its verdict is {stored.get('verdict')!r}" + (f" with cause {stored['cause']!r}" if stored.get("cause") else "")
        raise _judge_refusal(f"the check {check!r} owes no judgment: {what}",
                             (NO_FAILURE_DOOR + ". " if stored.get("verdict") == "no_failure" else "Only a check `incomplete` with `cause: judgment` is judged. ")
                             + "Door: " + JUDGE_CHECK_DOOR)
    bound = str(stored.get("test_file_sha256") or "")
    if not bound or bound != str(agg.get("test_file_sha256") or ""):
        raise _judge_refusal(f"the record of {check!r} is of other bytes than the aggregate's", f"Probe the current bytes again with {PROBE_AGAIN}.")
    per_path = proof_level.record_read_path(task_root, instance_id, row["line"], _ordinal_of(row), file=row.get("file"))
    return per_path, stored, entry, {"ctx": ctx, "run_cwd": run_cwd, "checks": checks, "runs": runs, "agg": agg, "key": check, "row": row}


def _judged_record(task_root: Path, root: Path, instance_id: str, check: str = "") -> tuple:
    """`(path, record, manifest entry, parts)` of the record `--judge` may judge; else the `_judge_refusal`s about the RECORD: it
    exists, is of the bytes the test holds now, owes the judgment (`incomplete`, `cause: judgment`, with facts) and has none written.
    A walk's aggregate (it carries `checks`) is judged BY CHECK (`_judge_walk`: the per-check record, `parts` set); a record of the
    old single form (no `checks`) is judged as it was, `parts` None, and `--check` is refused there."""
    path = record_path(task_root, instance_id)
    record = read_json(path, kind=dict)    # absent, unreadable or not an object -> None
    if record is None:
        raise _judge_refusal(f"no probe record of {instance_id!r} (work/probes) - the judgment is of a probe that ran",
                             f"Run the probe first: {PROBE_AGAIN} (nothing is judged before it).")
    entry = manifest_entry(task_root, instance_id)
    current = proof_level.current_test_sha(entry, root)
    bound = str(record.get("test_file_sha256") or "")
    if not (current and bound and current == bound):
        raise _judge_refusal("the probe record is of other bytes than the test holds now (or the test cannot be read); a judgment of "
                             "other bytes counts for nothing", f"Probe the current bytes again with {PROBE_AGAIN}, then judge that record.")
    if isinstance(record.get("checks"), list):
        return _judge_walk(task_root, root, instance_id, record, entry, check)
    if check:
        raise _judge_refusal(f"--check {check!r} names a check, and this record is not a walk's (it holds no checks)",
                             f"Judge it without --check, or probe again with {PROBE_AGAIN}.")
    if record.get("verdict") != "incomplete" or record.get("cause") != "judgment" or not isinstance(record.get("judgment_facts"), dict):
        raise _judge_refusal(f"this probe owes no judgment: its verdict is {record.get('verdict')!r}"
                             + (f" with cause {record['cause']!r}" if record.get("cause") else ""),
                             "Only a record `incomplete` with `cause: judgment` is judged; a `tooling` record goes back as a "
                             f"tooling finding. Door: {JUDGE_DOOR}")
    if isinstance(record.get("judgment"), dict):
        raise _judge_refusal("this record already carries a judgment, and a written judgment is never rewritten",
                             f"Probe the test again with {PROBE_AGAIN} (the new record is judged on its own).")
    return path, record, entry, None


def _judge_input(verdict: str, quote, why, facts: dict) -> tuple:
    """`(quote, why)` stripped, or the `_judge_refusal`s about the INPUT: the verdict word, the quote (present unless `cannot_judge`, at
    most `JUDGE_QUOTE_MAX`, a substring of the stored message or failure text after whitespace folding - of the flat keys or of any
    row of `rows`, N4), the `why`. `fires` is refused when the facts hold no text to quote (E4.1: no proof with no evidence) or
    when `rows_cut` > 0 (rows the critic could not read: he names `cannot_judge`, and the person's word follows). An old record
    (no `rows`, no `rows_cut`) is read by its flat keys, as before (E4.5)."""
    if verdict not in JUDGE_VERDICTS:
        raise _judge_refusal(f"--verdict is {verdict!r}; expected one of {', '.join(JUDGE_VERDICTS)}", "Door: " + JUDGE_DOOR)
    rows = [r for r in (facts.get("rows") or []) if isinstance(r, dict)] if isinstance(facts.get("rows"), list) else []
    stored = [str(source.get(key) or "") for source in [facts, *rows] for key in ("message", "failure_text")]
    if verdict == "fires" and not any(text.strip() for text in stored):
        raise _judge_refusal("`fires` has nothing to stand on: the stored message and failure text of this record are empty",
                             "No proof with no evidence: name `cannot_judge` with --why. Door: " + JUDGE_DOOR)
    cut = facts.get("rows_cut")
    if verdict == "fires" and isinstance(cut, int) and not isinstance(cut, bool) and cut > 0:
        raise _judge_refusal(f"`fires` is refused: the record shows {len(rows)} unsettled rows and {cut} more were cut "
                             f"(at most {FACTS_ROWS_MAX} are stored), so the critic cannot have read them all",
                             "Name `cannot_judge` with --why (the rows he could not read); the person's `probe not proved` word "
                             "follows. Door: " + JUDGE_DOOR)
    quote, why = str(quote or "").strip(), str(why or "").strip()
    if not quote and verdict != "cannot_judge":
        raise _judge_refusal("--quote is empty", "Quote a line of the stored text (probe record, judgment_facts), or name "
                             "`cannot_judge`. Door: " + JUDGE_DOOR)
    if quote:
        if len(quote) > JUDGE_QUOTE_MAX:
            raise _judge_refusal(f"--quote is {len(quote)} characters; at most {JUDGE_QUOTE_MAX}", "Quote one line. Door: " + JUDGE_DOOR)
        folded = " ".join(quote.split())
        if not any(folded in " ".join(text.split()) for text in stored):
            raise _judge_refusal("--quote is not in the stored message or failure text of the record, or of any of its rows "
                                 "(whitespace folded on both sides)",
                                 "Quote a line of the stored text, or name `cannot_judge`. Door: " + JUDGE_DOOR)
    if verdict == "cannot_judge" and not why:
        raise _judge_refusal("`cannot_judge` needs --why (one sentence: what you could not tell)", "Door: " + JUDGE_DOOR)
    if len(why) > JUDGE_WHY_MAX:
        raise _judge_refusal(f"--why is {len(why)} characters; at most {JUDGE_WHY_MAX}", "Door: " + JUDGE_DOOR)
    return quote, why


JUDGE_ROLE, JUDGE_STAGE = "qa-code-critic", "S5"    # whose dispatch may write a judgment, and in which stage (t-1968 N2 item 3)


def _judge_dispatch_why(root: Path, record: dict, dispatch: str) -> str:
    """Why `dispatch` is not the code critic's open S5 dispatch for the record's case, or "" when it is. DATA only (AR-29): the row
    `find_active_dispatch` answers (a `parent_retry` ancestor id resolves to the open dispatch that resumes it, through the same
    reader) must be readable, have role `JUDGE_ROLE`, stage `JUDGE_STAGE`, and the record's case in its `scope`. Error direction: a
    reason (a row that cannot be read, a record with no task or case, a controller that cannot be read refuse)."""
    import execution_request as ER
    from hooklib import artifact_root
    task, case = str(record.get("task") or ""), str(record.get("case") or "")
    if not task or not case:
        return "the probe record names no story or case, so no dispatch can be matched to it"
    try:
        row = ER.find_active_dispatch(artifact_root(root=root), task, dispatch, [case], None)[2]
    except ER.MineRefusal:
        return "is not open"
    except Exception:  # noqa: BLE001 - an unreadable controller or config refuses; it never passes
        return "cannot be read: the controller state of the story is unreadable"
    scope = row.get("scope") if isinstance(row, dict) else None
    if not isinstance(row, dict) or not isinstance(scope, list) or not row.get("role") or not row.get("stage"):
        return "cannot be read: its controller row lacks a role, a stage or a scope"
    if row["role"] != JUDGE_ROLE:
        return f"is a {row['role']} dispatch, not the code critic's"
    if row["stage"] != JUDGE_STAGE:
        return f"is a {row['stage']} dispatch, not the code critic's S5 one"
    if case not in {str(item) for item in scope}:
        return f"does not cover case {case} (its scope is {', '.join(str(item) for item in scope) or 'empty'})"
    return ""


def _demand_critic_dispatch(root: Path, record: dict, dispatch: str, instance_id: str) -> None:
    """Raise the `_judge_refusal` when `dispatch` is not the code critic's open S5 dispatch of the record's case (F2): an author's
    dispatch, an S6 one, or a critic of another window must not write a `fires` of its own test."""
    why = _judge_dispatch_why(root, record, dispatch)
    if why:
        raise _judge_refusal(f"{dispatch!r} is not the open code-critic dispatch of the window of {instance_id!r} (story "
                             f"{record.get('task')}): it {why}" if not why.startswith("the probe record") else why,
                             "Judge under the dispatch id your brief names - the open S5 dispatch of the code critic that covers "
                             "this test's case. Door: " + JUDGE_DOOR)


def _refold(parts: dict, note: str) -> dict:
    """The aggregate of a judged walk, REBUILT by `_aggregate_record` (the one writer) with every row read from its per-check record
    (`walk["from_records"]`): the entries are the stored aggregate's own (`checks[].entry`), the gaps its tooling rows with no entry, the
    notes its notes plus `note`. The receipt follows `_aggregate_record`'s rule alone: only for a complete plan. Returns the record."""
    ctx, agg, checks = parts["ctx"], parts["agg"], parts["checks"]
    rows = [r for r in agg.get("checks") or [] if isinstance(r, dict)]
    entries = [dict(r["entry"], check=r["key"]) for r in rows if isinstance(r.get("entry"), dict)]
    gaps = {r["key"]: str(r.get("note") or "") for r in rows if r.get("entry") is None and r.get("cause") == "tooling"}
    plan = {"checks": checks, "runs": parts["runs"], "notes": [str(n) for n in agg.get("notes") or []] + [note], "unmodellable": gaps, "only": []}
    walk = {"outcomes": {}, "proved": [], "from_records": [c["key"] for c in checks], "plan_remaining": [], "ended": str(agg.get("walk_ended") or ""),
            "runs": int(agg.get("plan_runs") or 0), "restore": None, "notes": [], "evidence_refs": list(agg.get("evidence_refs") or []),
            "input_hash": agg.get("input_hash")}
    span = test_body_span(ctx.path.read_bytes(), ctx.spec, _reader_entry(ctx.spec))
    return _aggregate_record(ctx, plan, entries, walk, (ctx.spec["file"], span[0], span[1]) if span else None)


def judge_record(task_root, root, instance_id: str, dispatch: str, verdict: str, quote: str, why: str = "", check: str = "") -> dict:
    """THE one writer of a record's `judgment` (AR-14): the code critic's verdict on a record `incomplete` with `cause: judgment`
    (t-1968 N2). It checks DATA only - the record exists, is of these bytes, owes the judgment, the verdict is one of
    `JUDGE_VERDICTS`, the quote is a substring of the stored text after whitespace folding (of the message or of the failure text),
    the dispatch is the open critic dispatch of the instance's window. Whether the quote PROVES that the broken check fired is the
    critic's word and the acceptor's to read, never this code's (AR-29, E2.3). Every refusal raises `Refusal` (exit 2, one JSON, nothing
    written) and names what it expected and the door.

    `fires` -> `intended_failure`, `proved_by: critic`, the location and reason of the plan, then the live receipt (carrying the
    quote) when the restore was verified; `other_failure` -> `wrong_location` (the actual location from the facts, the quote as the
    reason, `mismatches: ["reason"]`); `cannot_judge` -> the record stays `incomplete`/`judgment` and the judgment (with `why`) is
    written. A written judgment is never rewritten (E2.8). The quote of `cannot_judge` is optional; when given it is checked the
    same way. Returns the written record.

    A walk's aggregate (t-2064 P4b item 5) is judged BY CHECK: `check` names the key (omitted: allowed with exactly one unsettled check). The
    judgment is written on that check's per-check record (`fires` -> `intended_failure`, `proved_by: critic`; `other_failure` ->
    `wrong_location`; `cannot_judge` -> stays `incomplete`/`judgment`), then the aggregate is REBUILT by `_aggregate_record`, the one
    writer, from every per-check record: the receipt appears only when the plan is now complete (EP-K). Code records the judgment and
    re-folds; it weighs nothing (AR-29)."""
    task_root, root = Path(task_root), Path(root)
    path, record, entry, parts = _judged_record(task_root, root, instance_id, check)
    facts = record["judgment_facts"]
    quote, why = _judge_input(verdict, quote, why, facts)
    _demand_critic_dispatch(root, record, dispatch, instance_id)
    judgment = {"verdict": verdict, "quote": quote, "why": why, "by": dispatch,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "facts_sha": facts_sha(facts)}
    record["judgment"] = judgment
    if parts is not None:
        if verdict == "fires":
            record.update(verdict="intended_failure", cause=None, proved_by="critic", failure_kind="assertion")
        elif verdict == "other_failure":
            record.update(verdict="wrong_location", cause=None, actual_location=facts.get("location"), actual_reason=quote, mismatches=["reason"])
        note = f"judged by the code critic ({dispatch}): {parts['key']}: {verdict}"
        record["notes"] = list(record.get("notes") or []) + [note]
        row = parts["row"]
        _check_record(task_root, instance_id, row["line"], record, _ordinal_of(row), file=row.get("file"))
        return _refold(parts, note)
    if verdict == "fires":
        record.update(verdict="intended_failure", proved_by="critic", actual_location=record["expected_location"],
                      actual_reason=record["expected_reason"], failure_kind="assertion")
    elif verdict == "other_failure":
        record.update(verdict="wrong_location", actual_location=facts.get("location"), actual_reason=quote,
                      mismatches=["reason"])
    record["notes"] = list(record.get("notes") or []) + [f"judged by the code critic ({dispatch}): {verdict}"]
    record["window_probe"] = window_probe(record)
    record["receipt"], record["receipt_missing"] = None, []
    if verdict == "fires" and (record.get("restore") or {}).get("verified"):
        attach_receipt(record, entry, task_root)
    atomic_json(path, record)
    return record


def _judge_cli(args) -> None:
    """`--judge <instance>`: nothing else runs. One JSON refusal and exit 2, or the record printed and exit 0 for a judged verdict
    (`intended_failure`, `wrong_location`), 1 for `cannot_judge` (the record stays `incomplete`, as for any probe)."""
    try:
        if args.s6_close:
            raise _judge_refusal("--s6-close has no judgment: no critic dispatch is open at the close of S6, so a probe that "
                                 "owes one stays not proved", "Door: " + JUDGE_DOOR)
        missing = [name for name in ("task", "dispatch") if not getattr(args, name)]
        if missing:
            raise _judge_refusal("--" + " and --".join(missing) + " are required with --judge", "Door: " + JUDGE_DOOR)
        try:
            root = story_root(args.task, "probe_by_code.py --task")
        except ValueError as exc:
            raise Refusal(str(exc)) from exc
        record = judge_record(root, project_root().resolve(), args.judge, args.dispatch, args.verdict or "", args.quote or "",
                              args.why or "", args.check or "")
    except Refusal as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False))
        sys.exit(2)
    bound = publish_binding(args.task, root, record)
    if bound:
        record["binding"] = bound
    if record.get("publish"):
        try:
            atomic_json(Path(root) / record["record"], record)
        except OSError as exc:
            record["notes"].append(f"the publish could not be written into the record: {exc}")
    _print_record(record, bool((record.get("restore") or {}).get("verified")), args.json)
    if isinstance(record.get("checks"), list):     # a walk's aggregate: the exit speaks of THIS judgment, the aggregate says what else is owed
        sys.exit(1 if args.verdict == "cannot_judge" else 0)
    sys.exit(0 if record["verdict"] in {"intended_failure", "wrong_location"} else 1)


def _tool_refusal_record(args, task_root: Path, exc: "ToolRefusal"):
    """The record `refused: tool` for this refusal, or None when it must not exist. Written only when everything proves the
    refusal is the tool's and the test is the instance's: the manifest names the instance, the `--test` file is the file of
    its row and is under the project, and - when the refusal does not prove the name (`name_unproved`: no declaration was found
    for it) - the row's `report_test_id` ends with the `--test` tail, as `run_shape_checks` reads it. A wrong call (a missing
    file, another instance's file, a name that is not the row's) gives None: the role does not write itself a gap by a wrong
    call (AR-22). Reads, writes nothing."""
    text = str(args.test or "").replace("\\", "/")
    if "::" not in text:
        return None
    file = text.split("::", 1)[0]
    try:
        entry = manifest_entry(task_root, args.instance)
    except Refusal:
        return None
    project = project_root().resolve()
    row_file = str(entry.get("file") or "").replace("\\", "/")
    if not row_file or not _same_file(row_file, file):
        return None
    try:
        path, _cwd = _test_path(project, load_config(), {"file": file}, entry)
    except Refusal:
        return None
    if exc.name_unproved:
        try:
            spec = parse_node(text, project)
        except Refusal:
            return None
        # the AST reader never raises `name_unproved` (its name is proved by `locate`): a spec of that reader, or one that names no tail
        # or no entry, proves no name here - no record (`_tail_matches` reads the table entry's `tail_join`, which the AST entry has not)
        if spec.get("reader") != "table" or not spec.get("tail") or not spec.get("entry"):
            return None
        report_id = str(entry.get("report_test_id") or "").strip()
        if not report_id or not _tail_matches(report_id, spec["tail"], spec["entry"]):
            return None
    record = {"schema_version": 1, "probe_tool": "probe_by_code.py", "task": args.task, "instance_id": args.instance,
              "verdict": "not_executed", "refused": "tool", "test_file_sha256": sha256(path.read_bytes()),
              "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "notes": [str(exc)]}
    try:    # the tool's gap names its language the way `_tooling_gap` does (F-2 of t-596: ONE reader, `tooling_gap_key`); no entry: neither.
        suffix = Path(file).suffix       # N4 (S4): the table's entry first, then the AST reader's (`.py`: never an entry of the table)
        language, _entry = AD.entry_for_suffix(AD.assertion_detectors(), suffix)
        if not language:
            language, _entry = AD.ast_entry(suffix)
    except AD.DetectorsError:
        language = None
    if language:
        record["language"], record["cause"] = language, "tooling"
    return record


def _record_tool_refusal(args, task_root: Path, exc: "ToolRefusal") -> None:
    """Write the record of a tool refusal (`_tool_refusal_record`) at the probe's own path. An `intended_failure` stands
    (`keep_standing_record`). Any failure here is ONE line on stderr: the refusal's answer (one JSON, exit 2) never changes."""
    try:
        record = _tool_refusal_record(args, task_root, exc)
        if record is None:
            return
        out = record_path(task_root, args.instance)
        if not keep_standing_record(out, record):
            atomic_json(out, record)
    except Exception as err:    # noqa: BLE001 - the answer is already printed; the record is a convenience of the next reader
        print(f"probe_by_code: the record of this refusal was not written ({type(err).__name__}: {str(err)[:160]})",
              file=sys.stderr)


def _release_copy_cli(args) -> None:
    """`--release-copy`: nothing else runs. Exits 2 on a refusal (one JSON line), 0 once it printed what it
    released."""
    try:
        released = release_copy(project_root().resolve(), args.release_copy)
    except Refusal as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False))
        sys.exit(2)
    if args.json:
        print(json.dumps(released, ensure_ascii=False, indent=1))
    else:
        print(released.get("message") or f"released the byte copy of {released['file']} ({released['copy']}); "
              f"its record was {json.dumps(released['record'], ensure_ascii=False)}")
    sys.exit(0)


def _print_record(record: dict, restored: bool, json_mode: bool) -> None:
    """What the CLI prints for a probe that ran: the whole record as one object with `--json`, else the
    two lines, the binding and the notes."""
    if json_mode:
        print(json.dumps(record, ensure_ascii=False, indent=1))
        return
    print(f"probe {record['instance_id']}: {record['verdict']} — expected {record['expected_location']} "
          f"/ {record['expected_reason']!r}; actual {record.get('actual_location')} / "
          f"{fold(record.get('actual_reason') or '', 120)!r}")
    print(f"record {record['record']}; evidence {record.get('evidence_ref')}; "
          f"restore {'verified' if restored else 'NOT VERIFIED'}")
    if record.get("binding"):
        print(f"binding: {record['binding']}")
    for note in record.get("notes") or []:
        print(f"note: {note}")


def _unrestored_exit(record: dict) -> None:
    """The author's bytes could not be verified restored: say so on stderr and exit 1, whatever the verdict."""
    # The copy is KEPT when the restore cannot be verified (R9 write order 7), and the line names
    # the one move that undoes the mutation: the file that was mutated is the oracle's when the
    # expectation lives in a helper, not always the test's.
    mutated_file = record.get("mutated_file") or {}
    restore_fact = record.get("restore") or {}
    file_rel = mutated_file.get("path") or restore_fact.get("file") or record["test_node"].split("::")[0]
    copy_rel = restore_fact.get("copy")
    base = project_root().resolve()
    undo = (f"copy {(base / copy_rel)} over {(base / file_rel)}" if copy_rel
            else f"restore {file_rel} by hand")
    print(f"PROBE: the author's bytes of {file_rel} could not be verified restored "
          f"(sha256 {mutated_file.get('sha256') or restore_fact.get('author_sha256') or record['test_file_sha256']}) — stop and {undo}",
          file=sys.stderr)
    sys.exit(1)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="the critic's red probe by code: mutate the first "
                                                 "assert of ONE test, run that node, restore, record")
    parser.add_argument("--task", help="the ticket id")
    parser.add_argument("--dispatch", help="the open qa-code-critic dispatch id")
    parser.add_argument("--s6-close", action="store_true", dest="s6_close",
                        help="driver only: the probe of the code close of S6, when no dispatch is open "
                             "(refused otherwise)")
    parser.add_argument("--test", help='"<file>::[Class::]<func>[<param>]" — the pytest node; for another '
                                       'language "<file>::<test name>" (the method, or the title)')
    parser.add_argument("--instance", help="the manifest instance id (contract.instance_id)")
    parser.add_argument("--release-copy", default="", metavar="FILE",
                        help="drop the byte copy a killed probe left of FILE (after its author settled the "
                             "file); nothing else runs. A copy whose record is unreadable is named by its "
                             "16-hex key instead of a file")
    parser.add_argument("--mutation", choices=MUTATIONS + (REMOVED_MUTATION, ALTERNATIVE), default="invert",
                        help="invert: `assert not (<expr>)` (`expected` and `alternative` are removed and refused with their doors: the "
                             "`invert` entry of the model file, and the flag --alternative)")
    parser.add_argument("--alternative", default=None, metavar="CASE:ALT-n",
                        help="probe a declared reading B of a case on the one road, any language: the entries of the model file that carry "
                             "this token are walked, e.g. TC-001:ALT-1 (`--alternatives` prints the token of every one)")
    parser.add_argument("--model", default=None, metavar="FILE",
                        help="with --alternative: the model file under work/probe-models/ (default: the dispatch's own file)")
    parser.add_argument("--supersede", default=None, metavar="REASON",
                        help="removed (refused): a changed entry runs again by itself")
    parser.add_argument("--alternatives", action="store_true",
                        help="report only (needs --task; optional --instance, --json): every declared alternative with "
                             "its state and the flags to add; reads, writes nothing, exits 0")
    parser.add_argument("--oracle", default="",
                        help="[<file>::]<function> — the helper whose assert is this test's "
                             "expectation, when it lies further out than one hop")
    parser.add_argument("--at", type=_at_arg, default=None, metavar="LINE|FILE:LINE[#N]",
                        help="the line of the check to invert, for a test of any language: the check whose statement "
                             "starts or spans it, in the test's file or - as <file>:<line>, the spelling of assertion_id - "
                             "in a helper under the test tree; `#2` after the line is the second check that starts there; "
                             "it wins over --oracle and the manifest row's assertion_id")
    parser.add_argument("--judge", default="", metavar="INSTANCE",
                        help="the code critic's judgment of a probe record `incomplete` with `cause: judgment` (needs --task, "
                             "--dispatch, --verdict, --quote; --why for cannot_judge); nothing else runs")
    parser.add_argument("--check", default=None, metavar="KEY",
                        help="with --judge: the key of the check to judge (`<file>:<line>`, `--plan` lists them); may be left out when exactly "
                             "one check of the probe owes a judgment")
    parser.add_argument("--verdict", default=None, help="with --judge: " + "|".join(JUDGE_VERDICTS))
    parser.add_argument("--quote", default=None, help="with --judge: a line of the record's stored failure text")
    parser.add_argument("--why", default=None, help="with --judge: one sentence (required for cannot_judge)")
    parser.add_argument("--plan", action="store_true",
                        help="report only (needs --task, --instance, --test; optional --json): the checks of that test and the runs "
                             "that would probe them, one JSON {checks (each with its `doors`), plan, notes, plan_runs, model_file, models_shape}; "
                             "with --dispatch the model file is that dispatch's; reads, writes and runs nothing, exits 0")
    parser.add_argument("--timeout", type=int, default=RUN_TIMEOUT_S, help="seconds for the run")
    parser.add_argument("--json", action="store_true", help="print the probe record as JSON")
    return parser


def _at_arg(value: str):
    """`--at`: a line (int) or `<file>:<line>` (the spelling of `assertion_id`, kept as typed so a replay aims at the same file), each with an
    optional `#<n>` after the line (n >= 1: the n-th check that starts there, EP-O; the string is handed on whole to `_parse_at_row`, which reads
    the ordinal). `#1` is no suffix (dropped here). `#0`, `#x`, a bare `#`, a negative or empty line part are this refusal."""
    text = str(value).strip()
    bad = argparse.ArgumentTypeError(f"--at wants <line>, <file>:<line>, or either with `#<n>` after the line for the n-th check on it "
                                     f"(`12`, `tests/t.py:12`, `12#2`, `tests/t.py:12#2`; n counts from 1), got {value!r}")
    head, mark, tail = text.rpartition("#")
    ordinal = 1
    if mark and tail.isascii() and tail.isdigit():      # any other tail is no ordinal: the whole text must then be a plain spelling (a `#` in a file name)
        if int(tail) < 1:
            raise bad
        text, ordinal = head, int(tail)
    if text.isascii() and text.isdigit():
        return int(text) if ordinal == 1 else f"{int(text)}#{ordinal}"
    if _ASSERTION_ID.match(text):
        return text if ordinal == 1 else f"{text}#{ordinal}"
    raise bad


def _refuse_alternative_args(args) -> None:
    """The flags of the alternative probe, checked in `main` before anything is read (exit 2): they mean something only together."""
    if args.mutation == ALTERNATIVE:
        raise _alternative_spelling_refusal()
    if args.alternative is None:
        for flag, value in (("--model", args.model), ("--supersede", args.supersede)):
            if value is not None:
                raise Refusal(f"{flag} belongs to --alternative <case>:ALT-n: add it, or drop {flag}. Nothing was changed.")
        return
    if args.oracle or args.at is not None:
        raise Refusal("a reading is selected by its token and the entries of the model file that carry it, not by --oracle or --at: drop them. "
                      "Nothing was changed.")
    if args.supersede is not None:
        raise Refusal("--supersede was removed with the alternative's own road: a reading walks the plain road, which runs a check again by itself "
                      "when its entry changed (a proved check of the same entry and bytes is skipped). Change the entry in the model file and make the "
                      "same call again. Nothing was changed.")


def _alternatives_cli(args) -> None:
    """`--alternatives`: the report, read-only, exit 0 (P1: code tells, never stops). A story that does not exist is refused as
    everywhere else (CX1-18)."""
    try:
        task_root = story_root(args.task, "probe_by_code.py --task")
    except ValueError as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False))
        sys.exit(2)
    _print_alternatives(alternatives_report(Path(task_root), project_root().resolve(), args.instance), args.json)
    sys.exit(0)


def _stored_plan_refs(task_root: Path, instance_id: str, spec: dict, data: bytes, reader_entry) -> list:
    """`[(file spelling, line)]` of the checks the instance's stored aggregate lists OUTSIDE the test's body (a helper's line `--at` added,
    t-2064 P4b item 3): they stay on the plan from then on, so an owed one is owed on the next plain call too. Keys are `<file>:<line>[#n]`; a
    key of the test's own file inside its body is the plan's already and is not repeated. Reads one file; [] when there is none."""
    if not instance_id:
        return []
    try:
        stored = json.loads(record_path(task_root, instance_id).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        return []
    rows = stored.get("checks") if isinstance(stored, dict) else None
    span = test_body_span(data, spec, reader_entry)
    out: list = []
    for row in rows if isinstance(rows, list) else []:
        shown, _, tail = str(row.get("key") if isinstance(row, dict) else "").rpartition(":")
        line = tail.split("#", 1)[0]
        if not shown or not line.isdigit() or int(line) < 1:
            continue
        if _same_file(shown, spec["file"]) and span is not None and span[0] <= int(line) <= span[1]:
            continue
        if (shown, int(line)) not in out:
            out.append((shown, int(line)))
    return out


def _plan_inputs(root: Path, task_root: Path, cfg: dict, spec: dict, entry: dict, case: str, path: Path, run_cwd: Path,
                 instance_id: str = "", extra_refs=()) -> tuple:
    """`(data, bindings, helpers, notes, reader_entry)`: everything `checks_of` is given for ONE instance's test, gathered by READING
    (the manifest, the test file, the files a binding names, the one hop's candidates); writes nothing, runs nothing, takes no lock. The ONE
    gatherer: `--plan` (`_plan_cli`) and the walk's `_probe` (`_plan_of_test`) both call it (AR-15), so the list the critic reads is the plan
    the probe walks. Two more sources of checks, both as bindings with no Then (a real check outside the body, never labelled): the
    `extra_refs` `[(file spelling, file, "<a>" | "<a>-<b>")]` of a selection (`--at` / `--oracle`, `_row_selection`: the file is read and
    supplied as a helper when it is not the test), and the lines of the stored aggregate of `instance_id` outside the body (`_stored_plan_refs`:
    a helper's check added by an earlier `--at` stays on the plan, owed). A stored line whose file cannot be read here is skipped."""
    import s5_precheck as S5
    data = path.read_bytes()
    manifest_path = task_root / "work" / "automation-manifest.json"
    manifest = C.load_json(manifest_path) if manifest_path.is_file() else {}
    case_cfg = C.case_config()
    aliases = set(C.instance_id_aliases(entry, case_cfg))
    bindings = [{"then": row.get("then"), "assertion_ref": row.get("assertion_ref")}
                for row in S5.bindings_of_case(manifest, case, case_cfg)
                if row.get("status") == "covered" and str(row.get("instance_id") or "") in aliases]
    reader_entry = _reader_entry(spec)
    own = _Hop(path, data.decode("utf-8-sig", "replace"), reader_entry, spec["file"], "")
    chain = [] if reader_entry is not None else _helper_chain(path, run_cwd)
    imported, import_notes = ([], []) if own.unread else _imported_modules(own, root, cfg)
    found = []          # (spelling, file, hop?, conftest?): what a binding or the hop may need
    for file in [Path(c) for c in chain] + imported:
        found.append((_rel_project(file, root), file, True, file in [Path(c) for c in chain]))
    for row in bindings:
        span = S5._ref_span(row["assertion_ref"])
        if span is None or _same_file(span[0], spec["file"]) or any(_same_file(span[0], f[0]) for f in found):
            continue
        there = next((p for p in (root / span[0], run_cwd / span[0]) if p.is_file()), None)
        if there is not None and there.suffix.lower() in spec["entry"]["suffixes"] \
                and _in_test_root(cfg, _rel_project(there, root)):
            found.append((span[0], there, False, False))
    refs = [(shown, file, str(line)) for shown, line in _stored_plan_refs(task_root, instance_id, spec, data, reader_entry)
            for file in [next((p for p in (root / shown, run_cwd / shown) if p.is_file()), None)]
            if _same_file(shown, spec["file"]) or (file is not None and file.suffix.lower() in spec["entry"]["suffixes"]
                                                   and _in_test_root(cfg, _rel_project(file, root)))]
    for shown, file, span_text in list(refs) + list(extra_refs):
        bindings.append({"then": None, "assertion_ref": f"{shown}:{span_text}"})
        if file is not None and not _same_file(shown, spec["file"]) and not any(_same_file(shown, f[0]) for f in found):
            found.append((shown, file, False, False))
    helpers = []
    for spelling, file, hop, conftest in found:
        try:
            helpers.append({"file": spelling, "data": file.read_bytes(), "hop": hop, "chain": conftest})
        except OSError:
            continue
    return data, bindings, helpers, list(import_notes), reader_entry


def _plan_cli(args) -> None:
    """`--plan --task T --instance I --test N [--json]`: print `{checks, plan, notes}` of one instance's test and exit 0. It READS
    (the manifest, the test file, the files a binding names, the one hop's candidates) and writes nothing, runs nothing and takes no
    lock (t-2064 P2): a probe mutating the file at that moment would show its bytes - the list is data, never a verdict. The
    gathering is `_plan_inputs`; `checks_of` and `run_plan` are pure. A refusal is the same JSON and exit 2 as everywhere."""
    try:
        try:
            story_root(args.task, "probe_by_code.py --task")
        except ValueError as exc:
            raise Refusal(str(exc)) from exc
        root, task_root, cfg = project_root().resolve(), artifacts_dir(args.task).resolve(), load_config()
        spec = parse_node(args.test, root)
        entry = manifest_entry(task_root, args.instance)
        case = str(entry.get("case") or next(iter(entry.get("covers") or []), "") or "")
        if not case:
            raise Refusal(f"the manifest entry of {args.instance!r} names no case")
        path, run_cwd = _test_path(root, cfg, spec, entry)
        data, bindings, helpers, notes, reader_entry = _plan_inputs(root, task_root, cfg, spec, entry, case, path, run_cwd,
                                                                    instance_id=args.instance)
        # a flag is never dropped in silence: the plan is pure, so these are not used - and the report says so, one line each
        given = [flag for flag, value in (("--at", args.at), ("--oracle", args.oracle)) if value]       # `--dispatch` names the model file below: it is used
        if args.at == 0:
            given.insert(0, "--at")
        if args.mutation != "invert" or any(a == "--mutation" or a.startswith("--mutation=") for a in sys.argv[1:]):
            given.append("--mutation")        # its default is `invert`, so a stated value is told by the command line too
        notes += [f"--plan lists and plans only: {flag} was not used" for flag in given]
        checks = checks_of(data, spec, reader_entry, bindings, helpers, notes)
        notes.append("this list holds the heads of the forms the factory reads (references/detectors.json); a check of any other "
                     "form is not on it: compare it with the test")
        if not checks:
            notes.append("no check of a form the factory reads was found: nothing can be probed until a row of references/"
                         "detectors.json reads the test's form, or a line is named with --at <file>:<line>")
        # AR-10 / FR-38: what the role needs BEFORE the work - the model file of this dispatch, the entry shape (`MODELS_SHAPE`, the constant
        # `_models_refusal` prints), the doors open for each check (`_door_items`, the builder the refusal lists them with) and the number of
        # runs the walk will make (`plan_runs`: more than 3 rows is a background call). The ctx is the call's own, built as `probe()` builds it.
        plan = run_plan(checks)
        ctx = ProbeCtx(str(args.task), str(args.dispatch or ""), args.instance, case, spec, entry, root, cfg, task_root, _is_table(spec), "model",
                       task_root / "work" / "automation-manifest.json", path, "")
        doors = {item["key"]: item["doors"] for item in _door_items(ctx, checks)}
        checks = [{**check, "doors": doors.get(check["key"], [])} for check in checks]
        report = {"checks": checks, "plan": plan, "notes": notes, "plan_runs": len(plan),
                  "model_file": f"work/probe-models/{args.dispatch or '<dispatch id>'}.json", "models_shape": MODELS_SHAPE}
    except Refusal as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False))
        sys.exit(2)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print(f"{len(report['checks'])} check(s), {len(report['plan'])} run(s) for {args.instance}")
        print(f"plan_runs: {report['plan_runs']}")
        print(f"model file: {report['model_file']}")
        print(f"entry shape: {report['models_shape']}")
        for check in report["checks"]:
            print(f"doors of {check['key']} (line {check['line']}): {', '.join(check['doors']) or 'none'}")
        for run in report["plan"]:
            print(f"run {run['run']}: {', '.join(run['keys'])} ({run['why']})")
        for note in report["notes"]:
            print(f"note: {note}")
    sys.exit(0)


def _finish_alternative(args, record: dict) -> None:
    """Print what an alternative probe answered and exit. Never `publish_binding` (an alternative record is never a live receipt).
    An unverified restore of the author's file is the loudest alarm and is reported first (`_unrestored_exit`); a `gap` or an
    `unknown` answer ran nothing, has no restore and is not an unrestored file."""
    verdict = record.get("verdict")
    if record.get("restore") is not None:
        restored = bool((record.get("restore") or {}).get("verified"))
        _print_record(record, restored, args.json)
        if not args.json:
            print(f"alternative {record['alternative']}: {record.get('why') or 'see the notes'}")
        if not restored:
            _unrestored_exit(record)
    elif args.json:
        print(json.dumps(record, ensure_ascii=False, indent=1))
    else:
        print(f"probe {record['instance_id']} {record['alternative']}: {verdict} — {record.get('why')}")
        if record.get("record"):
            print(f"record {record['record']}")
        if record.get("door"):
            print(f"door: {record['door']}")
        for note in record.get("notes") or []:
            print(f"note: {note}")
    sys.exit(0 if verdict in {"intended_failure", "no_failure", "wrong_location"} else 1)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.release_copy:
        _release_copy_cli(args)
    if args.alternatives:
        if not args.task:
            parser.error("the following arguments are required: --task")
        _alternatives_cli(args)
    if args.judge:
        _judge_cli(args)       # before the probe branch: it reads a record, runs and mutates nothing
    stray = [flag for flag, value in (("--verdict", args.verdict), ("--quote", args.quote), ("--why", args.why)) if value is not None]
    if stray:
        print(json.dumps({"status": "refused", "error": f"probe_by_code: {', '.join(stray)} belong to --judge: add --judge "
                          f"<instance>, or drop them. Door: {JUDGE_DOOR}. Nothing was written."}, ensure_ascii=False))
        sys.exit(2)
    if args.s6_close and args.dispatch:
        parser.error("use one: --dispatch <id> (an open dispatch) or --s6-close (the code close of S6)")
    # the role's text names `--dispatch` alone: the driver's door (`--s6-close`) is not shown to the critic
    absent = [name for name in ("task", "dispatch", "test", "instance")
              if not getattr(args, name) and not (name == "dispatch" and (args.s6_close or args.plan))]
    if absent:
        parser.error("the following arguments are required: " + ", ".join("--" + name for name in absent))
    if args.plan:
        _plan_cli(args)       # before the probe branch: it reads, runs and writes nothing, takes no lock
    try:
        _refuse_alternative_args(args)     # a misuse of the alternative flags is refused before even the story is looked at
        # FIRST, before the probe reads or mutates anything: the story must EXIST (CX1-18), else the person would be
        # sent to a manifest door of a story that is not there. The same root serves the two writes below.
        try:
            root = story_root(args.task, "probe_by_code.py --task")
        except ValueError as exc:
            raise Refusal(str(exc)) from exc
        # the alternative probe's own values go to `probe()` only for that probe: every other call is the call it always was
        extra = ({"alternative": args.alternative, "model": args.model or ""} if args.alternative else {})
        record = probe(args.task, args.dispatch or "", args.test, args.instance, args.mutation,
                       args.timeout, args.oracle, args.at, s6_close=args.s6_close, **extra)
    except ToolRefusal as exc:
        # BEFORE `Refusal`: the same one JSON and exit 2, and the record `refused: tool` beside them (the producer of the field);
        # an alternative probe leaves none: that record's path is the INVERT probe's
        print(json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False))
        if not args.alternative:
            _record_tool_refusal(args, root, exc)
        sys.exit(2)
    except Refusal as exc:
        print(json.dumps({"status": "refused", "error": str(exc)}, ensure_ascii=False))
        sys.exit(2)
    if record.get("verdict") == "already_probed":
        # Answered, not probed: before `publish_binding` and before the restore check, because nothing
        # was mutated, launched or written - there is nothing to publish and nothing to restore. Exit 0:
        # the test HAS a probe; asking again is not a failure of anyone.
        if args.json:
            print(json.dumps(record, ensure_ascii=False, indent=1))
        else:
            print(f"probe {record['instance_id']}: already_probed — {record['words']}")
            for note in record.get("notes") or []:
                print(f"note: {note}")
        sys.exit(0)
    if args.alternative:
        _finish_alternative(args, record)
    restored = bool((record.get("restore") or {}).get("verified"))
    # Inside the record, never as an extra line: with `--json` the whole of stdout is one
    # object, and a human-readable line after it turned every field of the parsed record
    # into None for the caller (caught by test_probe_by_code the same minute).
    bound = publish_binding(args.task, root, record)
    if bound:
        record["binding"] = bound
    if record.get("publish"):
        try:  # what the publish did belongs in the probe's own record too (FR-14)
            atomic_json(root / record["record"], record)
        except OSError as exc:
            record["notes"].append(f"the publish could not be written into the record: {exc}")
    _print_record(record, restored, args.json)
    if not restored:
        _unrestored_exit(record)
    sys.exit(0 if record["verdict"] in {"intended_failure", "no_failure", "wrong_location"} else 1)


if __name__ == "__main__":
    main()
