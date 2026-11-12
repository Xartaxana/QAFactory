#!/usr/bin/env python3
"""question_register.py: the one reader of a story's question status, the answers file, the strict
answer parser and the CLI (t-113 piece A1, B-216 / B-181).

The class of defect held here: an id found by substring or alias, a status guessed from a mention,
and a parser that errs toward APPLYING an answer the person did not write. On cmp1 the person
answered Q1..Q5 by name at gate A and gate B still called all five unanswered; the same words, read
by a lenient grammar, would have applied readings ("Q1: a question for later" reads Q1=a).
One named check per edge of the piece, then the adversarial battery, then the real cmp1 words.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import (check, check_eq, check_in, cleanup, finish,  # noqa: E402
                     temp_dir, temp_project, use_project)

sys.path.insert(0, str(harness.SCRIPTS))
import question_register as QR  # noqa: E402

# Every non-ASCII character is BUILT with chr(): the package holds no Cyrillic (FR-30) and a literal
# BOM or no-break space in a source file is invisible.
CYR_A = chr(0x430)        # Cyrillic small a: looks like the Latin one
FULL_COLON = chr(0xFF1A)  # full-width colon
FULL_A = chr(0xFF41)      # full-width Latin a
NBSP = chr(0xA0)
BULLET = chr(0x2022)      # a bullet character
BOM = chr(0xFEFF)
ACUTE = chr(0x301)        # a combining accent
E_ACUTE = chr(0xE9)
CYR_TS = chr(0x422) + chr(0x421)                    # look-alikes of the Latin T and C
HELLO = "".join(chr(c) for c in (0x43F, 0x440, 0x438, 0x432, 0x435, 0x442))            # a Russian word
THEN = "".join(chr(c) for c in (0x43F, 0x43E, 0x442, 0x43E, 0x43C))                    # another
ALPHABET = "".join(chr(c) for c in (0x43A, 0x438, 0x440, 0x438, 0x43B, 0x43B, 0x438, 0x446, 0x430))  # a third
CASES = [f"TP1-13797_TC_{n:03d}" for n in range(1, 13)]

# The person's gate A answer of the cmp1 run, verbatim (experiments/measurers/answers/cmp1-gate-a.md).
CMP1_GATE_A = """Gate A: **approved.** The plan (14 rows) and the 12 pinned cases go to S5 as they stand - no edits, no re-dispatch. Size XXL, budget 47 against a cap of 28: **test it as one story, do not decompose.** The critic's `approve_with_fixes` verdict stands; its two exact replacements (TC_005 When step 1, TC_008 Given bullet 1) are applied by code - `critic_rollcall.py --apply-fixes` - and the cases re-pinned, no designer dispatch.

The items under "After your approval", by name:

1. **vcs-1, dirty working tree (26 uncommitted changes on `HEAD`, 97a6de8331f9)** - go on, on this branch as it is. Nothing is committed or stashed on my behalf.
2. **case_environment-1, TS-14's declared gap (no observable)** - accept the gap: the row stays in the plan as unverifiable, nothing is invented for it.
3. **s5_toolchain-1, the tests cannot be collected** - install what is missing, on my word, then re-collect and go on. The worktree already has `poetry install` done; if the collection still dies, it is the interpreter the check uses (system python instead of the poetry environment) - run the collection through poetry and record what you changed. S5 does not write code nothing can run, and "not executed" for a dependency of our own making is not accepted.
4. **s5_reporter-1, stand gap RP-api** - **apply**: the card's own diagnosis says the runner passes `--junitxml` itself, so the missing report has the same cause as item 3 (collection dies in conftest). After item 3, re-probe the card; only if a run still leaves no readable report change `qa-factory/config.json:profiles[api].commands.one_test`, and record what you changed.
5. **s5_environment-1, credentials and accounts** - accept the gap. `AWS_ACCESS_KEY`, `AWS_SECRET_KEY`, `AWS_PROFILE` are not set and the `auditor`, `default_scoped_user`, `project_scoped_user` accounts are not provisioned. The cases that need them are reported as not executed, by name, never as passed; nothing writes a value anywhere.

The open questions, by name (the register's Q-R ids are the same questions):

- **Q1 / Q-R14 / R-9 (event-type mismatch: 400 or 200 ACK)** - reading **(a)**: the 200 ACK with no dispatch is intended - AC-9 means valid deliveries keep working, and a 200 keeps GitHub from disabling the webhook. R-14 is asserted as 200/no dispatch; TS-5 keeps its disposition with the register's own reading of R-9; the old 400 is not tested and no bug is filed for it.
- **Q2 / Q-R15 (payload over 25,000,000 bytes)** - reading **(a)**: the size guard fails open by design; R-15 is asserted as dispatched with the bypass metric recorded. If S5 finds the metric is not emitted, that is a local bug proposal, not a test oracle change.
- **Q3 / Q-R7 (UI field for the JSON path filter)** - this is **missed scope, not a deferral**: the ticket's AC-7 stands, and nothing ships the UI half (`settingsUIConfig.ts` has no `github_json_path_filter`). AC-7 is unmet as shipped and is reported as a discrepancy against the acceptance criteria: a **local bug proposal under `qa-factory/bugs`, nothing to Jira or any tracker**. No UI or e2e row this cycle - there is nothing to observe yet; TC_011 stays manual-human and is reported as not executed with this reason.
- **Q4 / Q-R21 (`$.pull_request[?(@.draft==false)]` never matches)** - reading **(a)**: a documented limitation; only syntax errors are invalid. R-21 is asserted as "saves and never matches"; TC_009 keeps its disposition.
- **Q5 / Q-R22 (filter without a webhook secret)** - reading **(a)**: test with and without a secret; the unfiltered no-secret case is recorded as a gap in the report, not asserted either way, and not a bug.

The warnings:

- **ticket_adapter: unknown** - run the read-only probe; it is the factory's own receipt.
- **config_schema: not_configured** - leave it. This is an experiment copy; no migration decision tonight. Carry it as a warning to the end.

**Sources found after the S1 review** - TP1-13289 stays left out, the reason given is right.

Standing for the rest of the run, unchanged: bugs stay **local proposal files under `qa-factory/bugs`** and are not submitted anywhere; a merge request, if the pipeline reaches one, is **Draft only** on a branch with the suffix -c; the remote branches `TP1-13797_github-webhook-json-path-filter` and `-b` are ignored entirely - not a source, not existing coverage, not a precedent.
"""


def q(qid, n=2, text=None):
    return {"id": qid, "question": text or f"question {qid}?", "severity": "major",
            "readings": [{"reading": f"reading {i}", "from": "code", "if_chosen": "x"} for i in range(n)]}


def write_story(root: Path, questions=None, answers=None, pipeline=None, readiness_raw=None):
    """A task root with the files the register reads. `answers` are RAW lines (a test may break one)."""
    (root / "work").mkdir(parents=True, exist_ok=True)
    if readiness_raw is not None:
        (root / "work" / "requirements-readiness.json").write_text(readiness_raw, encoding="utf-8")
    elif questions is not None:
        (root / "work" / "requirements-readiness.json").write_text(
            json.dumps({"verdict": "blocked", "open_questions": questions}), encoding="utf-8")
    if answers is not None:
        (root / "work" / "question-answers.jsonl").write_bytes("\n".join(answers).encode("utf-8"))
    if pipeline is not None:
        (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    return root


HASH = "a" * 64  # a well-formed row hash that is no row's hash today


def rec(qid, status="answered", **extra):
    base = {"id": qid, "status": status, "words": f"words for {qid}", "by": "person", "where": "gate A",
            "at": "2026-09-30T10:00:00+00:00", "row_hash": HASH}
    base.update(extra)
    return json.dumps(base)


def case_rec(case, decision="manual", **extra):
    base = {"kind": "case", "case": case, "decision": decision, "words": f"{case}: {decision}", "where": "gate A",
            "by": "person", "at": "2026-09-30T10:00:00+00:00"}
    base.update(extra)
    return json.dumps(base)


def row_hash_of(root, qid):
    return next(x["row_hash"] for x in QR.load(root)["questions"] if x["id"] == qid)


def put(root, qid, status, words, hash_from="row", reading="", where="gate A", by="person"):
    """QR.record() with the hash the card would pass back: the row's own hash today, unless given."""
    shown = row_hash_of(root, qid) if hash_from == "row" else hash_from
    return QR.record(root, qid, status, words, where, by, shown, reading=reading)


def status_of(view, qid):
    return next(x["status"] for x in view["questions"] if x["id"] == qid)


def row_of(view, qid):
    return next(x for x in view["questions"] if x["id"] == qid)


def safe(fn, *args):
    try:
        return fn(*args), None
    except Exception as exc:  # the register must never raise on a story's own data
        return None, exc


def snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def parse(words, questions=("Q1", "Q2"), cases=CASES, readings=2):
    return QR.parse_choices(words, [q(x, readings) for x in questions], list(cases))


# ------------------------------------------------------------------------------------------------
# E1 - ONE id, exact
# ------------------------------------------------------------------------------------------------

def test_e1_exact_id(tmp):
    root = write_story(tmp / "e1", [q("Q1"), q("Q10", 3), q("Q3")],
                       answers=[rec("Q10"), rec("q1"), rec("Q-1"), rec("Q-R14"), rec(" Q3 ")])
    view = QR.load(root)
    check_eq("E1 an answer for Q10 does not answer Q1 (no prefix or substring match)",
             (status_of(view, "Q1"), status_of(view, "Q10")), ("open", "answered"))
    check_eq("E1 lower-case q1 and the aliases Q-1 / Q-R14 resolve to nothing: three records skipped as unknown ids",
             view["skipped"]["unknown_id"], 3)
    check_eq("E1 the id in a record is trimmed and then exact: ' Q3 ' answers Q3", status_of(view, "Q3"), "answered")

    words = {"gate A": "we settled Q10 as a group, reading a", "alias": "Q-R14 and Q-1 are the same as R-9",
             "glued": "see Q1-x and R-Q1 and Q1_a and Q1a"}
    for name, text in words.items():
        pipe = {"gates": {"A": {"decision": "approved", "authorization_source": text}}}
        v = QR.load(write_story(tmp / ("e1n-" + name.replace(" ", "")), [q("Q1"), q("Q10")], pipeline=pipe))
        check_eq(f"E1 the id inside other text is not named ({name}): Q1 stays open", status_of(v, "Q1"), "open")
    check_eq("E1 ... while the exact token Q10 in the same words is named",
             status_of(QR.load(write_story(tmp / "e1n-q10", [q("Q1"), q("Q10")],
                                           pipeline={"gates": {"A": {"authorization_source": words["gate A"]}}})), "Q10"),
             "named")

    got = parse("Q10: a\nQ1: b", questions=("Q1", "Q10"))
    check_eq("E1 parser: Q10 and Q1 are different questions", got["choices"], {"Q1": "b", "Q10": "a"})
    got = parse("Q10: a", questions=("Q1",))
    check_eq("E1 parser: Q10 is not Q1 (unknown, Q1 untokened)", (got["choices"], got["unknown_ids"], got["untokened_questions"]),
             ({}, ["Q10"], ["Q1"]))
    for alias in ("Q-1", "Q-R14", "R-14", "q1", "Q 1", "Q01", "TS-6"):
        got = parse(f"{alias}: a", questions=("Q1", "Q2"))
        ok = got["choices"] == {} and got["untokened_questions"] == ["Q1", "Q2"]
        check(f"E1 parser: the alias {alias!r} chooses nothing", ok, str(got))
    for alias in ("Q-1", "Q-R14", "q1"):
        check_eq(f"E1 parser: {alias!r} is reported as an unknown id", parse(f"{alias}: b")["unknown_ids"], [alias])
    check_eq("E1 parser: an id with surrounding spaces in the REGISTER is trimmed, exact after that",
             QR.parse_choices("Q1: a", [{"id": " Q1 ", "readings": [1, 2]}], [])["choices"], {"Q1": "a"})


# ------------------------------------------------------------------------------------------------
# E2 - load(): statuses and fields
# ------------------------------------------------------------------------------------------------

def test_e2_load(tmp):
    vocab = QR.vocabulary()
    check_eq("E2 the statuses are the closed list of the data file",
             vocab["statuses"], ["open", "answered", "not_needed", "with_designer", "named", "deferred_to_report"])
    check("E2 `named` is never a recordable status", "named" not in vocab["recorded_statuses"])
    # HF2-7 P5a (t-108, accepted): `S4 stop` joined the closed list (and `where_words`) - the S4 stop is a place a person answers
    check_eq("E2 the where-values are the owner's closed list",
             vocab["where"], ["gate A", "gate B", "S2 stop", "S3 stop", "S4 stop", "waiver", "remark", "conductor", "stage ran"])
    check_eq("E2 the stop reasons are in the data file (Q5)", vocab["stop_reasons"],
             ["scope_or_structure", "no_readings", "dependent", "over_threshold", "low_confidence", "blocking"])
    check_eq("E2 who-recorded is a closed list of the data file (edge 4)", vocab["by"],
             ["person", "conductor", "driver", "orchestrator"])
    check_eq("E2 the case decisions are a closed list of the data file", vocab["case_decisions"], ["manual", "automate"])
    check("E2 the data file has no default `where` (a write must say where)", "default_where" not in vocab)

    answers = [rec("Q2", reading="b", words="Q2: b - because", where="S2 stop"),
               rec("Q3", "not_needed", words="not needed: out of scope Q3"),
               rec("Q4", "with_designer", words="the designer will reword Q4"),
               rec("Q5"), rec("Q5", "open", words="reopened Q5", where="conductor")]
    root = write_story(tmp / "e2", [q("Q1"), q("Q2"), q("Q3"), q("Q4"), q("Q5")], answers=answers)
    view = QR.load(root)
    check_eq("E2 statuses: no record open, answered, not_needed, with_designer, reopened open",
             [status_of(view, x) for x in ("Q1", "Q2", "Q3", "Q4", "Q5")],
             ["open", "answered", "not_needed", "with_designer", "open"])
    q2 = row_of(view, "Q2")
    check_eq("E2 an answered question carries reading, words, where, at and the line with its id",
             (q2["reading"], q2["words"], q2["where"], q2["at"], q2["line"]),
             ("b", "Q2: b - because", "S2 stop", "2026-09-30T10:00:00+00:00", "Q2: b - because"))
    check_eq("E2 not_needed carries no reading", (row_of(view, "Q3")["reading"], row_of(view, "Q3")["line"]),
             ("", "not needed: out of scope Q3"))
    q1 = row_of(view, "Q1")
    check_eq("E2 an open question with no record has empty words/where/at/line/reading",
             (q1["reading"], q1["words"], q1["where"], q1["at"], q1["line"]), ("", "", "", "", ""))
    check_eq("E2 a reopen keeps the reopening words and place, and the status is open",
             (row_of(view, "Q5")["status"], row_of(view, "Q5")["words"], row_of(view, "Q5")["where"]),
             ("open", "reopened Q5", "conductor"))
    check("E2 every returned status is in the closed list", all(x["status"] in vocab["statuses"] for x in view["questions"]))
    check_eq("E2 the record's line is empty when the words do not carry the id",
             row_of(QR.load(write_story(tmp / "e2b", [q("Q1")], answers=[rec("Q1", words="a plain reading")])), "Q1")["line"], "")
    check_eq("E2 the register row keeps its own keys (readings, severity)", (q1["severity"], len(q1["readings"]), q1["readings_count"], q1["letters"]),
             ("major", 2, 2, "ab"))

    # named: a story with NO answers file, the exact id in the person's recorded gate words
    pipe = {"gates": {"A": {"id": "g1", "decision": "approved", "authorization_source": CMP1_GATE_A},
                      "B": {"decision": "approved", "authorization_source": ""}}}
    cmp_q = [q(f"Q{i}") for i in range(1, 6)]
    named = QR.load(write_story(tmp / "e2n", cmp_q, pipeline=pipe))
    check_eq("E2 no answers file + the id in authorization_source: all five are `named`, none `answered`",
             [status_of(named, f"Q{i}") for i in range(1, 6)], ["named"] * 5)
    n1 = row_of(named, "Q1")
    check("E2 `named` carries the line of the words that has the id, the words whole and where=gate A",
          n1["line"].startswith("- **Q1 / Q-R14 / R-9") and n1["words"] == CMP1_GATE_A and n1["where"] == "gate A"
          and n1["reading"] == "" and n1["at"] == "")
    check_eq("E2 the answers file is reported absent", named["answers_present"], False)
    check_eq("E2 a question with no record has changed_since_answer False and no stored hash",
             (n1["changed_since_answer"], n1["record_row_hash"]), (False, ""))
    for key, text in (("words", "Q2: a"), ("decision", "answered Q2 as a")):
        v = QR.load(write_story(tmp / f"e2-{key}", [q("Q2")], pipeline={"gates": {"A": {key: text}}}))
        check_eq(f"E2 the recorded words are also read from `{key}`", status_of(v, "Q2"), "named")
    v = QR.load(write_story(tmp / "e2-order", [q("Q2"), q("Q3")],
                            pipeline={"gates": {"A": {"authorization_source": "about Q3", "words": "about Q2", "decision": "Q2"}}}))
    check_eq("E2 authorization_source first, then words, then decision (the first non-empty one is the words)",
             (status_of(v, "Q2"), status_of(v, "Q3")), ("open", "named"))
    v = QR.load(write_story(tmp / "e2-gb", [q("Q2")], pipeline={"gates": {"B": {"authorization_source": "settled Q2"}}}))
    check_eq("E2 gate B words name it too, and say so", (status_of(v, "Q2"), row_of(v, "Q2")["where"]), ("named", "gate B"))
    v = QR.load(write_story(tmp / "e2-other", [q("Q2")], pipeline={"gates": {"C": {"authorization_source": "Q2"}},
                                                                    "gate_waivers": [{"requirement": "Q2", "decision": "Q2"}],
                                                                    "remarks": [{"text": "Q2"}]}))
    check_eq("E2 only gate words name a question (a waiver or a remark does not)", status_of(v, "Q2"), "open")
    v = QR.load(write_story(tmp / "e2-file", [q("Q2"), q("Q3")], answers=[rec("Q3")],
                            pipeline={"gates": {"A": {"authorization_source": "Q2 reading a"}}}))
    check_eq("E2 edge 8: with an answers file, `named` is still computed for the question with NO record: Q2 named, Q3 answered",
             (status_of(v, "Q2"), status_of(v, "Q3")), ("named", "answered"))
    v = QR.load(write_story(tmp / "e2-one", cmp_q, answers=[rec("Q3")], pipeline=pipe))
    check_eq("E2 edge 8: one recorded answer (Q3) does not turn the other four named questions into plain open",
             [status_of(v, f"Q{i}") for i in range(1, 6)], ["named", "named", "answered", "named", "named"])
    v = QR.load(write_story(tmp / "e2-empty-file", [q("Q2")], answers=[""],
                            pipeline={"gates": {"A": {"authorization_source": "Q2 reading a"}}}))
    check_eq("E2 edge 8: an EMPTY answers file is a file with no record: the named question stays named",
             (status_of(v, "Q2"), v["answers_present"]), ("named", True))
    v = QR.load(write_story(tmp / "e2-reopen", [q("Q2")], answers=[rec("Q2", "open", words="reopened")],
                            pipeline={"gates": {"A": {"authorization_source": "Q2 reading a"}}}))
    check_eq("E2 a reopened question HAS a record: open, never named again", status_of(v, "Q2"), "open")
    check("E2 a mention never yields `answered` (the error direction of the reader is toward open)",
          all(x["status"] != "answered" for x in named["questions"]))


# ------------------------------------------------------------------------------------------------
# E3 - the answers file
# ------------------------------------------------------------------------------------------------

def test_e3_answers_file(tmp):
    root = write_story(tmp / "e3", [q("Q1"), q("Q2")], answers=[
        rec("Q1", reading="a"), rec("Q1", reading="b", words="second"), rec("Q2")])
    check_eq("E3 the LAST record per id wins", (row_of(QR.load(root), "Q1")["reading"], row_of(QR.load(root), "Q1")["words"]),
             ("b", "second"))
    root = write_story(tmp / "e3b", [q("Q1")], answers=[rec("Q1"), "{not json", "[1, 2]", "\"text\"", "5", "null", "",
                                                        rec("Q99"), json.dumps({"id": "Q1"}), json.dumps({"status": "answered"}),
                                                        json.dumps({"id": 5, "status": "answered"}),
                                                        json.dumps({"id": "Q1", "status": "invented"}),
                                                        "\x00\x01 garbage", "{" * 5000])
    view, exc = safe(QR.load, root)
    check("E3 broken, non-object, unknown-id and malformed lines never raise", exc is None, repr(exc))
    check_eq("E3 they are counted: 3 broken, 4 non-object ([1,2], string, 5, null), 1 unknown id, 4 invalid",
             view["skipped"], {"broken_lines": 3, "non_object_lines": 4, "unknown_id": 1, "invalid": 4, "unreadable_file": 0})
    check_eq("E3 the good record before them still stands", status_of(view, "Q1"), "answered")
    check_eq("E3 a broken line after the good one does not hide it (last VALID record wins)",
             status_of(QR.load(write_story(tmp / "e3c", [q("Q1")], answers=[rec("Q1"), "{oops"])), "Q1"), "answered")
    bom = write_story(tmp / "e3d", [q("Q1")])
    (bom / "work" / "question-answers.jsonl").write_bytes(b"\xef\xbb\xbf" + (rec("Q1") + "\r\n" + rec("Q1", "not_needed") + "\r\n").encode())
    check_eq("E3 a BOM and CRLF line ends in the answers file are read", status_of(QR.load(bom), "Q1"), "not_needed")
    raw = write_story(tmp / "e3e", [q("Q1")])
    (raw / "work" / "question-answers.jsonl").write_bytes(b"\xff\xfe\xfa\n" + rec("Q1").encode() + b"\n")
    view, exc = safe(QR.load, raw)
    check("E3 invalid UTF-8 in a line is skipped, the rest is read", exc is None and status_of(view, "Q1") == "answered", repr(exc))

    # what the writer puts in a record, and a file whose last line has no newline
    tail = write_story(tmp / "e3f", [q("Q1"), q("Q2")], answers=[rec("Q1")])  # no trailing newline, as after a crash
    written = put(tail, "Q2", "answered", "Q2: a", reading="a", by="conductor")
    lines = (tail / "work" / "question-answers.jsonl").read_text(encoding="utf-8").split("\n")
    check_eq("E3 an append after a line with no newline starts a new line (two records, then the final newline)",
             (len(lines), lines[-1], json.loads(lines[1])["id"]), (3, "", "Q2"))
    check_eq("E3 a record carries kind, id, status, reading, words, by, where, at and row_hash",
             sorted(written), sorted(["kind", "id", "status", "reading", "words", "by", "where", "at", "row_hash"]))
    check_eq("E3 the record's kind is `question`", written["kind"], "question")
    check_eq("E3 the row_hash of the record is the hash of the row it was shown (64 hex)",
             (written["row_hash"], len(written["row_hash"])), (row_hash_of(tail, "Q2"), 64))
    check_eq("E3 with no reading the key is absent", "reading" in put(tail, "Q1", "not_needed", "no"), False)


# ------------------------------------------------------------------------------------------------
# E4 - the register file
# ------------------------------------------------------------------------------------------------

def test_e4_register(tmp):
    view = QR.load(tmp / "nothing-here")
    check_eq("E4 a story with no readiness file: no questions, register_present false, no exception",
             (view["questions"], view["register_present"], view["answers_present"]), ([], False, False))
    for name, raw in (("empty", ""), ("blank", "  \n"), ("not json", "{oops"), ("a list", "[1, 2]"),
                      ("a string", "\"x\""), ("deep", "[" * 100000), ("null", "null")):
        view, exc = safe(QR.load, write_story(tmp / ("e4-" + name.replace(" ", "")), readiness_raw=raw))
        check(f"E4 a readiness file that is {name}: no exception, no questions, one problem stated",
              exc is None and view["questions"] == [] and len(view["problems"]) == 1, f"{exc!r} {view}")
    bom = write_story(tmp / "e4-bom", readiness_raw=BOM + json.dumps({"open_questions": [q("Q1")]}))
    check_eq("E4 a BOM on the readiness file is read", [x["id"] for x in QR.load(bom)["questions"]], ["Q1"])
    for name, value in (("missing", None), ("null", None), ("a dict", {"a": 1}), ("a string", "Q1"), ("a number", 3)):
        body = {"verdict": "blocked"} if name in ("missing",) else {"open_questions": value}
        view, exc = safe(QR.load, write_story(tmp / ("e4o-" + name.replace(" ", "")), readiness_raw=json.dumps(body)))
        expected_problems = 1 if name in ("a dict", "a string", "a number") else 0
        check(f"E4 open_questions {name}: no exception, no questions, {expected_problems} problem(s)",
              exc is None and view["questions"] == [] and len(view["problems"]) == expected_problems, f"{exc!r} {view}")
    rows = [q("Q1"), "text", None, 5, {"question": "no id"}, {"id": ""}, {"id": "   "}, {"id": 7}, {"id": ["Q"]}, q("Q2"),
            {"id": "Q1", "question": "the duplicate"}, {"id": " Q2 ", "question": "another duplicate, trimmed"}, q("Q3", 0)]
    view, exc = safe(QR.load, write_story(tmp / "e4-rows", readiness_raw=json.dumps({"open_questions": rows})))
    check("E4 rows that are not objects or carry no usable id: no exception", exc is None, repr(exc))
    check_eq("E4 only the rows with an id are questions; duplicates are not merged (the first is kept)",
             [x["id"] for x in view["questions"]], ["Q1", "Q2", "Q3"])
    check_eq("E4 the kept Q1 is the FIRST one", row_of(view, "Q1")["question"], "question Q1?")
    check_eq("E4 duplicates are reported by id", view["duplicates"], ["Q1", "Q2"])
    check("E4 every skipped row and duplicate is stated in problems (2 duplicates + 8 unusable rows)", len(view["problems"]) == 10,
          "\n".join(view["problems"]))
    check_eq("E4 a question with no readings has readings_count 0 and no letters", (row_of(view, "Q3")["readings_count"], row_of(view, "Q3")["letters"]), (0, ""))
    check_eq("E4 readings that are not a list count as none",
             row_of(QR.load(write_story(tmp / "e4-rd", [{"id": "Q1", "readings": "ab"}])), "Q1")["readings_count"], 0)
    check_eq("E4 an answer for a register with no questions: the record is skipped as unknown",
             QR.load(write_story(tmp / "e4-none", [], answers=[rec("Q1")]))["skipped"]["unknown_id"], 1)
    check_eq("E4 load() takes a str as well as a Path", len(QR.load(str(write_story(tmp / "e4-str", [q("Q1")])))["questions"]), 1)


# ------------------------------------------------------------------------------------------------
# E5 - the strict parser
# ------------------------------------------------------------------------------------------------

def test_e5_parser(tmp):
    # edge 1: a strict token is the WHOLE line - after the value only spaces, at most one of . , ;
    positive = {
        "Q1: a": "a", "Q1: a.": "a", "Q1: a;": "a", "Q1: a,": "a", "Q1:a": "a", "Q1 : a": "a", "Q1 = a": "a",
        "Q1 = b": "b", "Q1=b": "b", "- Q1: a": "a", "* Q1: a": "a", "1. Q1: a": "a", "12. Q1: a": "a",
        "1) Q1: a": "a", "2) Q1: b": "b", "- 3) Q1: a": "a",
        "**Q1: a**": "a", "**Q1**: a": "a", "`Q1`: a": "a", "`Q1: a`": "a", "- **Q1: a**": "a", "  - `Q1: b`": "b",
        "- **Q1**: a.": "a", "Q1: a .": "a", "Q1: a  ;  ": "a",
        "Q1:\ta": "a", "Q1: a   ": "a", "Q1: a\r": "a", "- - Q1: a": "a", BOM + "Q1: a": "a",
        BULLET + " Q1: a": "a", BULLET + BULLET + "Q1: a": "a",
        "Q1:" + NBSP + "a": "a", "Q1" + NBSP + ": a": "a", NBSP + "Q1: a": "a", "Q1: a" + NBSP: "a",
        "Q1: a" + NBSP + ".": "a", NBSP + "- Q1: a": "a", "-" + NBSP + "Q1: a": "a", "1." + NBSP + "Q1: a": "a",
    }
    for text, letter in positive.items():
        got = parse(text)
        check_eq(f"E5 edge 1: {text!r} IS a choice Q1={letter}", got["choices"], {"Q1": letter})
    for text in ("Q1: not needed", "- Q1: not needed.", "**Q1: not needed**", "Q1: not needed;", "Q1 = not needed ,",
                 "Q1:" + NBSP + "not needed", "Q1: not needed" + NBSP):
        got = parse(text)
        check_eq(f"E5 edge 1: {text!r} IS `not needed`", (got["not_needed"], got["choices"]), (["Q1"], {}))

    negative = [
        # edge 1: text after the value makes the line prose, not a token
        "Q1: a, b or not needed", "Q1: a, but only if the API allows it", "Q1: a.k.a. the old flow", "Q1: a, b",
        "Q1: not needed. Actually it is needed", "Q1: a; Q2: b", "Q1: a, no wait, b", "Q1: a. The rest is prose",
        "Q1: a, because the ticket says so", "Q1: a.,", "Q1: a..", "Q1: a,;", "Q1: not needed, out of scope",
        "Q1 = not needed, out of scope", "Q1: a. b", "Q1: a; b",
        "Q1 a", "Q3 a scope question for the owner", "Q1 - reading (a)", "Q1: a question for later", "Q1: a b",
        "Q1: (a)", "Q1: a)", "reading (a) for Q1", "I think Q1: a", "not Q1: a", "Q1 not a", "(a) Q1", "a) Q1",
        "Q1: A", "Q1: ab", "Q1: ", "Q1:", "Q1: 1", "Q1: -a", "Q1: not needed at all", "Q1: not neededness", "Q1: notneeded",
        "Q1: Not needed", "> Q1: a", "     - a) the first reading is intended", "Q1 :: a", "Q1:: a",
        "Q1: " + CYR_A, "Q1" + FULL_COLON + "a", "Q1" + FULL_COLON + " a", "Q1: " + FULL_A, "Q1: a" + ACUTE + "x", "Q1 / Q-R14: a",
        "Q1: a a", "Q1: a -", "Q1: a and Q2: b", "Q1: a" + NBSP + "b", "Q1: a" + FULL_COLON,
    ]
    for text in negative:
        got = parse(text)
        check(f"E5 edge 1: {text!r} is NOT a token: nothing chosen, nothing reported", got["choices"] == {} and got["not_needed"] == []
              and got["conflicts"] == [] and got["out_of_range"] == [], str(got))
    got = parse("Q1: a; Q2: b")
    check_eq("E5 edge 1: `Q1: a; Q2: b` (two tokens on one line) takes neither, and both ids are reported untokened",
             (got["choices"], got["untokened_questions"]), ({}, ["Q1", "Q2"]))
    got = parse("Q1: a, b or not needed")
    check_eq("E5 edge 1: `Q1: a, b or not needed` chooses nothing and Q1 is untokened",
             (got["choices"], got["not_needed"], got["untokened_questions"]), ({}, [], ["Q1", "Q2"]))
    got = parse("Q1: a, but only if the API allows it")
    check_eq("E5 edge 1: `Q1: a, but only if the API allows it` chooses nothing (the text after the value)",
             got["choices"], {})
    for text in (f"{CASES[8]}: automate, not manual", f"{CASES[8]}: manual because it is slow", f"{CASES[8]}: manual, automate",
                 f"{CASES[8]}: automate. Then again no"):
        check_eq(f"E5 edge 1: case line {text!r} is NOT a case token", parse(text)["case_tokens"], [])
    for text, decision in ((f"{CASES[8]}: automate", "automate"), (f"{CASES[8]}: manual.", "manual"),
                           (f"- **{CASES[8]}**: manual;", "manual"), (f"{CASES[8]}" + NBSP + ": automate", "automate")):
        got = parse(text)
        check_eq(f"E5 edge 1: case line {text!r} IS a case token", [(t["case"], t["decision"]) for t in got["case_tokens"]],
                 [(CASES[8], decision)])
    check_eq("E5 a Cyrillic look-alike letter is not the Latin one", parse("Q1: " + CYR_A)["untokened_questions"], ["Q1", "Q2"])
    check_eq("E5 a full-width colon is not the separator", parse("Q1" + FULL_COLON + "a")["choices"], {})
    check_eq("E5 the same letter twice is one choice, not a conflict",
             (parse("Q1: a\nQ1: a")["choices"], parse("Q1: a\nQ1: a")["conflicts"]), ({"Q1": "a"}, []))
    got = parse("Q1: a\nQ1: b")
    check_eq("E5 two different letters for one id: a conflict, nothing chosen, the question stays untokened",
             (got["choices"], got["conflicts"], got["untokened_questions"]),
             ({}, [{"id": "Q1", "values": ["a", "b"]}], ["Q1", "Q2"]))
    got = parse("Q1: a\nQ1: not needed")
    check_eq("E5 a letter and `not needed` for one id conflict", (got["conflicts"], got["not_needed"], got["choices"]),
             ([{"id": "Q1", "values": ["a", "not needed"]}], [], {}))
    got = parse("Q1: c\nQ2: b")
    check_eq("E5 a letter beyond the readings is out_of_range and chooses nothing",
             (got["choices"], got["out_of_range"], got["untokened_questions"]),
             ({"Q2": "b"}, [{"id": "Q1", "letter": "c", "readings": 2}], ["Q1"]))
    check_eq("E5 the boundary: the last letter of 8 readings is in range, the ninth is not",
             (parse("Q1: h", readings=8)["choices"], parse("Q1: i", readings=8)["out_of_range"]),
             ({"Q1": "h"}, [{"id": "Q1", "letter": "i", "readings": 8}]))
    check_eq("E5 nine readings give the letter i; 26 give z; the 27th letter does not exist",
             (parse("Q1: i", readings=9)["choices"], parse("Q1: z", readings=26)["choices"], parse("Q1: z", readings=25)["out_of_range"] != []),
             ({"Q1": "i"}, {"Q1": "z"}, True))
    check_eq("E5 a question with no readings takes no letter", parse("Q1: a", readings=0)["out_of_range"],
             [{"id": "Q1", "letter": "a", "readings": 0}])
    check_eq("E5 a question with 'not needed' needs no readings", parse("Q1: not needed", readings=0)["not_needed"], ["Q1"])
    got = parse("Q1: a\nQ2: b\nQ7: a", questions=("Q1", "Q2", "Q3"))
    check_eq("E5 untokened lists the register questions nobody spoke of (Q3), unknown ids are reported (Q7)",
             (got["untokened_questions"], got["unknown_ids"]), (["Q3"], ["Q7"]))
    check_eq("E5 an id-less 'Note: a' is not reported as an unknown id (no digit in it)", parse("Note: a")["unknown_ids"], [])

    # case tokens
    full = CASES[8]  # TP1-13797_TC_009
    got = parse(f"{full}: manual\n{CASES[5]}: automate")
    check_eq("E5 `<full case id>: manual|automate` are case tokens",
             got["case_tokens"], [{"case": full, "decision": "manual", "written": full},
                                  {"case": CASES[5], "decision": "automate", "written": CASES[5]}])
    got = parse("- **TC_009: manual**\n1. TC_010: automate.")
    check_eq("E5 a short case id resolves when exactly one given case id ends with _<it>",
             [(t["case"], t["decision"], t["written"]) for t in got["case_tokens"]],
             [(full, "manual", "TC_009"), (CASES[9], "automate", "TC_010")])
    got = parse("TC_009: manual", cases=[full, "OTHER-1_TC_009"])
    check_eq("E5 a short id that two case ids end with is unresolved, with its candidates",
             (got["case_tokens"], got["unresolved_short_ids"]),
             ([], [{"id": "TC_009", "candidates": [full, "OTHER-1_TC_009"]}]))
    got = parse("TC_099: manual\nTC_099: automate")
    check_eq("E5 a short id no case ends with is unresolved (once), not guessed",
             (got["case_tokens"], got["unresolved_short_ids"]), ([], [{"id": "TC_099", "candidates": []}]))
    check_eq("E5 a short id is matched after the underscore only: TC_9 is not TC_009",
             parse("TC_9: manual")["case_tokens"], [])
    check_eq("E5 a Cyrillic look-alike in a case id resolves nothing",
             parse(CYR_TS + "_009: manual")["case_tokens"], [])
    got = parse(f"{full}: manual\n{full}: automate")
    check_eq("E5 manual and automate for one case conflict; no case token", (got["case_tokens"], got["conflicts"]),
             ([], [{"id": full, "values": ["manual", "automate"]}]))
    got = parse(f"{full}: manual\nTC_009: manual")
    check_eq("E5 the full and the short form of one case, same decision: one token", len(got["case_tokens"]), 1)
    check_eq("E5 a case token needs the strict tail: 'manual because' and '(manual)' are not tokens",
             (parse(f"{full}: manual because it is slow")["case_tokens"], parse(f"{full}: (manual)")["case_tokens"]), ([], []))
    check_eq("E5 'Q1: manual' is no case token and no choice",
             (parse("Q1: manual")["case_tokens"], parse("Q1: manual")["choices"], parse("Q1: manual")["unresolved_short_ids"]), ([], {}, []))
    check_eq("E5 a letter after a case id is no token, and the id is reported unknown",
             (parse(f"{full}: a")["case_tokens"], parse(f"{full}: a")["unknown_ids"]), ([], [full]))
    check_eq("E5 the parser handles no case ids at all", parse("TC_009: manual", cases=[])["unresolved_short_ids"],
             [{"id": "TC_009", "candidates": []}])

    # never alters the words; tolerates any input
    words = "  - Q1: a\r\n" + BOM + E_ACUTE + " " + HELLO + "\n"
    kept = str(words)
    parse(words)
    check_eq("E5 the words are not altered (a str is immutable; the parser returns no copy of them)", words, kept)
    for odd in (None, "", "   ", 5, b"Q1: a"):
        got, exc = safe(parse, odd)
        check(f"E5 input {odd!r}: no exception, nothing chosen", exc is None and got["choices"] == {}, repr(exc))
    got, exc = safe(QR.parse_choices, "Q1: a", None, None)
    check("E5 no questions and no case ids: an empty result", exc is None and got["untokened_questions"] == [], repr(exc))
    got, exc = safe(QR.parse_choices, "Q1: a", [None, "Q1", {"id": None}, {"id": ""}, {"readings": [1]}, q("Q1")], [None, "", 5])
    check("E5 malformed question rows and case ids are ignored", exc is None and got["choices"] == {"Q1": "a"}, repr(exc))


# ------------------------------------------------------------------------------------------------
# E6 - the CLI
# ------------------------------------------------------------------------------------------------

def cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = QR.main(list(args))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def test_e6_cli(tmp):
    proj = temp_project("qa-question-register-")
    try:
        use_project(proj)
        task = proj / "qa-factory" / "artifacts" / "QA-9"
        write_story(task, [q("Q1"), q("Q10", 3), q("Q3")])
        answers = task / "work" / "question-answers.jsonl"

        before = snapshot(proj)
        code, out, err = cli("--task", "QA-9", "--show")
        shown = json.loads(out)
        check_eq("E6 --show exits 0 and prints ONE JSON document on stdout (stderr empty)", (code, err), (0, ""))
        check_eq("E6 --show lists the questions with their status", [(x["id"], x["status"]) for x in shown["questions"]],
                 [("Q1", "open"), ("Q10", "open"), ("Q3", "open")])
        check_eq("E6 --show writes nothing (every byte of the project is as it was, no answers file)",
                 (snapshot(proj) == before, answers.exists()), (True, False))

        def hash_args(qid):
            return ["--register-hash", next(x["row_hash"] for x in shown["questions"] if x["id"] == qid)]

        base = ["--where", "gate A", "--by", "conductor"]
        check_eq("E6 edge 3: --show prints each row's own hash (64 hex, distinct per row)",
                 (all(len(x["row_hash"]) == 64 for x in shown["questions"]), len({x["row_hash"] for x in shown["questions"]})),
                 (True, 3))
        code, out, err = cli("--task", "QA-9", "--answer", "Q1", "--reading", "a", "--words", "Q1: a - the ACK is intended",
                             *base, *hash_args("Q1"))
        got = json.loads(out)
        check_eq("E6 --answer with a reading records an answered question", (code, got["question"]["status"], got["question"]["reading"]),
                 (0, "answered", "a"))
        check_eq("E6 the record carries where and by as given, kind `question`, and the hash passed back (--register-hash)",
                 (got["recorded"]["where"], got["recorded"]["by"], got["recorded"]["kind"], got["recorded"]["row_hash"]),
                 ("gate A", "conductor", "question", hash_args("Q1")[1]))
        check_eq("E6 edge 3: the row is as it was shown, so changed_since_answer is False",
                 got["question"]["changed_since_answer"], False)
        code, out, _ = cli("--task", "QA-9", "--answer", "Q10", "--words", "the designer's new Then", "--where", "S2 stop",
                           "--by", "driver", *hash_args("Q10"))
        got = json.loads(out)
        check_eq("E6 --answer with no --reading is legal (the designer road): answered, empty reading, where as given",
                 (code, got["question"]["status"], got["question"]["reading"], got["question"]["where"]), (0, "answered", "", "S2 stop"))
        code, out, _ = cli("--task", "QA-9", "--not-needed", "Q3", "--words", "not needed, the ticket drops it", "--where", "gate A",
                           "--by", "person", *hash_args("Q3"))
        check_eq("E6 --not-needed records not_needed", (code, json.loads(out)["question"]["status"]), (0, "not_needed"))
        code, out, _ = cli("--task", "QA-9", "--reopen", "Q1", "--words", "the person changed their mind", *base)
        got = json.loads(out)
        check_eq("E6 --reopen puts it back to open and keeps the reopening words; the hash is optional for it",
                 (code, got["question"]["status"], got["question"]["words"], got["question"]["changed_since_answer"]),
                 (0, "open", "the person changed their mind", None))
        code, out, _ = cli("--task", "QA-9", "--answer", "Q1", "--reading", "b", "--words", "- Q1: b", *base, *hash_args("Q1"))
        got = json.loads(out)
        check_eq("E6 an answer after a reopen wins; words that START WITH A HYPHEN are taken whole, not read as an option",
                 (code, got["question"]["status"], got["question"]["reading"], got["question"]["words"]), (0, "answered", "b", "- Q1: b"))
        # HF2-7: Q1 is settled (b), so another answer needs the door first (`--reopen`); this key is about the words
        cli("--task", "QA-9", "--reopen", "Q1", "--words", "the person changed their mind again", *base)
        code, out, _ = cli("--task", "QA-9", "--answer", "Q1", "--reading", "a", "--words", "-x", *base, *hash_args("Q1"))
        check_eq("E6 a bare '-x' as the words is a value too", (code, json.loads(out)["recorded"]["words"]), (0, "-x"))

        file_before = answers.read_bytes()
        ok_hash = hash_args("Q1")
        refusals = [
            ("a letter out of range", ["--answer", "Q1", "--reading", "c", "--words", "w"], ["beyond the 2 readings of Q1", "Valid: a, b"]),
            ("a letter for a question with more readings still bounded", ["--answer", "Q10", "--reading", "d", "--words", "w"], ["Valid: a, b, c"]),
            ("an uppercase letter", ["--answer", "Q1", "--reading", "A", "--words", "w"], ["one Latin letter a-z"]),
            ("a Cyrillic letter", ["--answer", "Q1", "--reading", CYR_A, "--words", "w"], ["one Latin letter a-z"]),
            ("two letters", ["--answer", "Q1", "--reading", "ab", "--words", "w"], ["one Latin letter a-z"]),
            ("an unknown id", ["--answer", "Q9", "--words", "w"], ["no question with id 'Q9'", "Q1, Q10, Q3", "exact, case-sensitive"]),
            ("a lower-case id", ["--answer", "q1", "--words", "w"], ["no question with id 'q1'"]),
            ("an alias id", ["--answer", "Q-R14", "--words", "w"], ["no question with id 'Q-R14'", "aliases"]),
            ("a prefix of an id", ["--answer", "Q", "--words", "w"], ["no question with id 'Q'"]),
            ("a longer id", ["--answer", "Q1x", "--words", "w"], ["no question with id 'Q1x'"]),
            ("blank words", ["--answer", "Q1", "--words", "   "], ["the words are blank", "--words"]),
            ("empty words", ["--answer", "Q1", "--words", ""], ["the words are blank"]),
            ("newline-only words", ["--not-needed", "Q1", "--words", "\n\t\r\n"], ["the words are blank"]),
            ("no words at all", ["--answer", "Q1"], ["the words are blank"]),
            ("an unknown --where", ["--answer", "Q1", "--words", "w", "--where", "gate_A"],
             ["where 'gate_A' is not a known value", "gate A, gate B, S2 stop, S3 stop, S4 stop, waiver, remark, conductor, stage ran"]),
            ("edge 4: a missing --where (no default)", ["--answer", "Q1", "--words", "w"],
             ["--where is missing", "no default", "gate A, gate B, S2 stop, S3 stop, S4 stop, waiver, remark, conductor, stage ran"], ("--where",)),
            ("edge 4: a missing --where on --reopen", ["--reopen", "Q1", "--words", "w"], ["--where is missing", "no default"], ("--where",)),
            ("edge 4: a missing --by", ["--answer", "Q1", "--words", "w"],
             ["--by is missing", "no default", "person, conductor, driver, orchestrator"], ("--by",)),
            ("edge 4: an unknown --by", ["--answer", "Q1", "--words", "w", "--by", "the intern"],
             ["by 'the intern' is not a known value", "person, conductor, driver, orchestrator"]),
            ("edge 4: an empty --by", ["--answer", "Q1", "--words", "w", "--by", ""], ["--by is missing", "person, conductor"]),
            ("edge 3: --answer with no --register-hash", ["--answer", "Q1", "--words", "w"],
             ["register hash is missing", "row_hash", "--register-hash"], ("--register-hash",)),
            ("edge 3: --not-needed with no --register-hash", ["--not-needed", "Q1", "--words", "w"],
             ["register hash is missing"], ("--register-hash",)),
            ("edge 3: a register hash that is not a sha256", ["--answer", "Q1", "--words", "w", "--register-hash", "h"],
             ["is not a sha256", "row_hash"]),
            ("edge 3: a reopen with a malformed hash", ["--reopen", "Q1", "--words", "w", "--register-hash", "xyz"],
             ["is not a sha256"]),
            ("edge 6: both --words and --words-file", ["--answer", "Q1", "--words", "w", "--words-file", "whatever.txt"],
             ["exactly one of --words and --words-file"]),
            ("edge 6: neither --words nor --words-file", ["--answer", "Q1"], ["exactly one of --words and --words-file"]),
            ("edge 6: a --words-file that does not exist", ["--answer", "Q1", "--words-file", "no-such-file-here.txt"],
             ["could not be read", "UTF-8"]),
            ("edge 5: --keep-manual with a reading", ["--keep-manual", "TP1-13797_TC_009", "--words", "w", "--reading", "a"],
             ["only with an answer"]),
            ("edge 5: --keep-manual with no words", ["--keep-manual", "TP1-13797_TC_009"], ["the words are blank"]),
            ("edge 5: --keep-manual with no --where", ["--keep-manual", "TP1-13797_TC_009", "--words", "w"],
             ["--where is missing"], ("--where",)),
            ("edge 5: --automate with no --by", ["--automate", "TP1-13797_TC_009", "--words", "w"],
             ["--by is missing"], ("--by",)),
            ("edge 5: --case-ids-file with a question operation", ["--answer", "Q1", "--words", "w", "--case-ids-file", "x.txt"],
             ["--case-ids-file has no meaning"]),
            ("edge 5: --keep-manual and --automate together", ["--keep-manual", "A_TC_1", "--automate", "A_TC_2", "--words", "w"],
             ["exactly one operation", "got 2"]),
            ("a reading with --not-needed", ["--not-needed", "Q1", "--reading", "a", "--words", "w"], ["only with an answer"]),
            ("a reading with --reopen", ["--reopen", "Q1", "--reading", "a", "--words", "w"], ["only with an answer"]),
            ("no operation", ["--words", "w"], ["exactly one operation", "got 0"]),
            ("two operations", ["--answer", "Q1", "--reopen", "Q3", "--words", "w"], ["exactly one operation", "got 2"]),
            ("--show with words", ["--show", "--words", "w"], ["--show writes nothing", "--words"]),
            ("a task id that is a path", ["--answer", "Q1", "--words", "w", "--task", "../QA-9"], ["(got '../QA-9')"]),
        ]
        defaults = {"--where": "gate A", "--by": "person", "--register-hash": ok_hash[1]}
        for name, argv, needles, *omit in refusals:
            argv = list(argv)
            if "--task" not in argv:
                argv = ["--task", "QA-9"] + argv
            if "--show" not in argv:  # every refusal above is about ONE thing: the rest of the call is well-formed
                for flag, value in defaults.items():
                    if flag not in argv and flag not in (omit[0] if omit else ()):
                        if flag == "--register-hash" and any(op in argv for op in ("--reopen", "--keep-manual", "--automate")):
                            continue
                        argv += [flag, value]
            code, out, err = cli(*argv)
            check(f"E6 refused: {name} -> exit 2, stdout empty, the message says what is wrong and what is valid",
                  code == 2 and out == "" and all(n in err for n in needles), f"{code} out={out!r} err={err!r}")
        check_eq("E6 no refusal wrote anything", answers.read_bytes(), file_before)

        (proj / "qa-factory" / "artifacts" / "QA-NEW").mkdir()      # the story exists (S0 made it) and has no register yet
        code, out, err = cli("--task", "QA-NEW", "--answer", "Q1", "--words", "w", *base, *ok_hash)
        check("E6 a story with no register: refused, and the message says there are no register ids yet",
              code == 2 and "no register ids yet" in err, err)
        check_eq("E6 ... and nothing was created in it", list((proj / "qa-factory" / "artifacts" / "QA-NEW").iterdir()), [])
        code, out, err = cli("--task", "QA-9", "--answer", "Q1", "--words", "w", *base, *ok_hash, "--nonsense")
        check_eq("E6 an unknown option is argparse's own refusal (exit 2)", code, 2)
        code, out, err = cli("--answer", "Q1", "--words", "w")
        check_eq("E6 --task is required (exit 2)", code, 2)
        code, out, err = cli("--task", "QA-9", "--sho")
        check_eq("E6 an abbreviated option is refused, never guessed", code, 2)
    finally:
        cleanup(proj)


def test_e6_cli_subprocess(tmp):
    proj = temp_project("qa-question-register-sub-")
    try:
        task = proj / "qa-factory" / "artifacts" / "QA-9"
        write_story(task, [q("Q1"), q("Q2")])
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj), PYTHONDONTWRITEBYTECODE="1")
        script = str(harness.SCRIPTS / "question_register.py")

        def run(*args):
            return subprocess.run([sys.executable, "-B", script, *args], capture_output=True, encoding="utf-8",
                                  errors="replace", cwd=str(proj), env=env, timeout=120)

        proc = run("--task", "QA-9", "--show")
        check_eq("E6 subprocess: --show exits 0 and stdout is exactly one JSON document",
                 (proc.returncode, [x["id"] for x in json.loads(proc.stdout)["questions"]]), (0, ["Q1", "Q2"]))
        shown = {x["id"]: x["row_hash"] for x in json.loads(proc.stdout)["questions"]}
        tail = ["--where", "gate A", "--by", "conductor", "--register-hash", shown["Q1"]]
        words = BOM + "- Q1: a\r\n- Q2: not needed " + HELLO + " " + E_ACUTE + "\r\n"
        proc = run("--task", "QA-9", "--answer", "Q1", "--reading", "a", "--words", words, *tail)
        line = (task / "work" / "question-answers.jsonl").read_bytes().decode("utf-8").split("\n")[0]
        check_eq("E6 subprocess: BOM, CRLF and non-ASCII words are stored whole, byte for byte",
                 (proc.returncode, json.loads(line)["words"]), (0, words))
        proc = run("--task", "QA-9", "--answer", "Q1", "--reading", "z", "--words", "w", *tail)
        check("E6 subprocess: a refusal is exit 2 with an empty stdout and the message on stderr",
              proc.returncode == 2 and proc.stdout == "" and "beyond the 2 readings" in proc.stderr, proc.stderr)
        proc = run("--task", "QA-9", "--answer", "Q1", "--words", "w", "--by", "person", "--register-hash", shown["Q1"])
        check("E6 edge 4 subprocess: no --where is exit 2, the valid values are named, stdout is empty",
              proc.returncode == 2 and proc.stdout == "" and "--where is missing" in proc.stderr and "gate A, gate B" in proc.stderr,
              proc.stderr)
        long_file = tmp / "words-from-file.txt"
        long_words = BOM + ("- Q2: not needed " + HELLO + " " + E_ACUTE + "\r\n" + "x" * 100 + "\r\n") * 600
        long_file.write_bytes(long_words.encode("utf-8"))
        check("E6 edge 6: the words file is longer than a Windows command line (about 32 KB)", len(long_words.encode("utf-8")) > 60000)
        proc = run("--task", "QA-9", "--answer", "Q2", "--words-file", str(long_file), "--where", "gate B", "--by", "person",
                   "--register-hash", shown["Q2"])
        last = (task / "work" / "question-answers.jsonl").read_bytes().decode("utf-8").split("\n")
        check_eq("E6 edge 6 subprocess: --words-file words are stored whole, BOM and CRLF and non-ASCII kept",
                 (proc.returncode, json.loads(last[-2])["words"] == long_words, last[-1]), (0, True, ""))
        listed = tmp / "case-ids.txt"
        listed.write_bytes(("TP1-9_TC_001\n\nTP1-9_TC_002\n").encode("utf-8"))
        proc = run("--task", "QA-9", "--keep-manual", "TP1-9_TC_001", "--words", "w", "--where", "gate A", "--by", "person",
                   "--case-ids-file", str(listed))
        got = json.loads(proc.stdout) if proc.stdout else {}
        check_eq("E6 edge 5 subprocess: --keep-manual with a case ids file records the decision and says what it checked against",
                 (proc.returncode, got.get("recorded", {}).get("kind"), got.get("case_ids_checked_against")),
                 (0, "case", "--case-ids-file"))
        empty = temp_dir("qa-question-register-none-")  # outside any project: no marker on the way up
        try:
            proc = subprocess.run([sys.executable, "-B", script, "--task", "QA-9", "--show"], capture_output=True,
                                  encoding="utf-8", errors="replace", cwd=str(empty),
                                  env={k: v for k, v in env.items() if k != "CLAUDE_PROJECT_DIR"}, timeout=120)
        finally:
            cleanup(empty)
        check("E6 subprocess: outside a project the refusal is the project-marker one (exit 3), nothing on stdout",
              proc.returncode == 3 and proc.stdout == "", f"{proc.returncode} {proc.stderr}")
    finally:
        cleanup(proj)


# ------------------------------------------------------------------------------------------------
# E7 - the adversarial battery (parser and CLI)
# ------------------------------------------------------------------------------------------------

def timed(fn):
    start = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - start


def test_e7_battery(tmp):
    got = parse("")
    check_eq("E7 empty words: nothing chosen, every question untokened", (got["choices"], got["untokened_questions"]), ({}, ["Q1", "Q2"]))
    check_eq("E7 CRLF line ends: each token is on its own line", parse("Q1: a\r\nQ2: b\r\n")["choices"], {"Q1": "a", "Q2": "b"})
    check_eq("E7 old-Mac CR line ends work too", parse("Q1: a\rQ2: b")["choices"], {"Q1": "a", "Q2": "b"})
    check_eq("E7 a BOM at the start of the words", parse(BOM + "Q1: a\nQ2: b")["choices"], {"Q1": "a", "Q2": "b"})
    check_eq("E7 non-ASCII prose around a token: the token line is read, the prose is not",
             parse(HELLO + " " + E_ACUTE + "\nQ1: a\n" + THEN + " " + ALPHABET + "\n")["choices"], {"Q1": "a"})
    check_eq("E7 non-ASCII text AFTER the value on the token line makes it prose",
             parse("Q1: a, " + THEN + " " + ALPHABET + "\n")["choices"], {})

    echoed = ("## Open questions (2)\n\n- **Q1** Is the mismatch intended?\n"
              "  - a) intended: 200 ACK\n  - b) unintended: stays 400\n    - a) nested echo\n"
              "  - a) TC_006 is automated at api and asserts 200\n     - b) keeps it manual\n\n"
              "Answer each question as `Q1: a` or `Q1: not needed`, or in your own words.")
    got = parse(echoed)
    check("E7 the gate text echoed back: '  - a)' lines and the question line are no choice",
          got["choices"] == {} and got["not_needed"] == [] and got["case_tokens"] == [], str(got))
    check_eq("E7 (the echo of the grammar hint alone, mid-sentence, is no token either)", parse("write `Q1: a` for reading a")["choices"], {})

    big = ("- Q1: a.  \n" + HELLO + " " + E_ACUTE + " a line of prose, then a second sentence\n") * 6000
    check("E7 the 200 KB body is at least 200000 characters", len(big) >= 200000)
    got, seconds = timed(lambda: parse(big))
    check("E7 200 KB of token lines parse in linear time (well under 10 s) and read Q1=a once", seconds < 10 and got["choices"] == {"Q1": "a"}, f"{seconds:.2f}s")
    shapes = {"markers": "- " * 100000 + "Q1: a", "asterisks": "*" * 200000, "one word": "x" * 200000,
              "spaces before colon": "Q1" + " " * 200000 + ": a", "numbered": "1. " * 70000 + "Q1: a",
              "backticks tail": "Q1: a" + "`" * 200000, "colons": ":" * 200000, "equals": "Q1" + "=" * 200000,
              "long id": "Q" * 200000 + ": a", "many short lines": "\n".join(["q"] * 100000), "only newlines": "\n" * 200000,
              "fence lines": "\n".join(["```"] * 70000), "quote marks": ">" * 200000, "no-break spaces": NBSP * 200000 + "Q1: a",
              "spaces after value": "Q1: a" + " " * 200000 + ".", "unclosed fence": "```\n" + "Q1: a\n" * 50000}
    for name, text in shapes.items():
        got, seconds = timed(lambda text=text: parse(text))
        check(f"E7 hostile shape '{name}' (200 KB) parses in linear time, no exception", seconds < 10, f"{seconds:.2f}s")
    check_eq("E7 the marker prefix of 100000 dashes still reads the token behind it", parse(shapes["markers"])["choices"], {"Q1": "a"})
    check_eq("E7 the numbered prefix ('1. ' repeated) is stripped in one pass", parse(shapes["numbered"])["choices"], {"Q1": "a"})
    check_eq("E7 a 200 KB id is no id", parse(shapes["long id"])["unknown_ids"], [])

    # the CLI with 200 KB words: in-process, because a Windows command line holds 32 KB
    proj = temp_project("qa-question-register-big-")
    try:
        use_project(proj)
        task = proj / "qa-factory" / "artifacts" / "QA-9"
        write_story(task, [q("Q1"), q("Q2")])
        def wh(qid):
            return ["--where", "gate A", "--by", "conductor", "--register-hash", row_hash_of(task, qid)]

        (code, out, err), seconds = timed(lambda: cli("--task", "QA-9", "--answer", "Q1", "--reading", "a", "--words", big, *wh("Q1")))
        stored = QR.load(task)
        check("E7 CLI: 200 KB of words is recorded in linear time and kept WHOLE (compared to the last character)",
              code == 0 and seconds < 10 and row_of(stored, "Q1")["words"] == big, f"{code} {seconds:.2f}s {err[:200]}")
        line = (task / "work" / "question-answers.jsonl").read_bytes().split(b"\n")
        check_eq("E7 CLI: the 200 KB answer is ONE line of the answers file", (len(line), line[1]), (2, b""))
        crlf = "\r\n".join(["- Q2: not needed", "", "and " + ALPHABET + " " + E_ACUTE, ""])
        code, out, _ = cli("--task", "QA-9", "--not-needed", "Q2", "--words", crlf, *wh("Q2"))
        got = row_of(QR.load(task), "Q2")["words"]
        check("E7 CLI: CRLF and non-ASCII words are stored whole", code == 0 and got == crlf, f"{code} {got[:80]!r}")
        bom = BOM + "- Q1: a"
        # HF2-7: Q1 is settled with reading `a`; the keys below are about the WORDS, so they repeat the same answer (`--reading a`),
        # which is appended as it always was - a different answer would need `--reopen` first
        code, out, _ = cli("--task", "QA-9", "--answer", "Q1", "--reading", "a", "--words", bom, *wh("Q1"))
        got = row_of(QR.load(task), "Q1")["words"]
        check("E7 CLI: a BOM in the words is stored, not eaten", code == 0 and got == bom, f"{code} {got[:80]!r}")
        echo = "  - a) intended: 200 ACK\n  - b) unintended\n"
        code, out, _ = cli("--task", "QA-9", "--answer", "Q1", "--reading", "a", "--words", echo, *wh("Q1"))
        got = row_of(QR.load(task), "Q1")["words"]
        check("E7 CLI: the gate text echoed inside the words is kept whole, and it is no choice for the parser",
              code == 0 and got == echo and parse(echo)["choices"] == {}, f"{code} {got[:80]!r}")
        code, out, err = cli("--task", "QA-9", "--answer", "Q1", "--reading", "a", "--words", chr(0xD800) + " lone surrogate", *wh("Q1"))
        check_eq("E7 CLI: a lone surrogate in the words does not lose the answer (escaped, exit 0)", code, 0)
        view, exc = safe(QR.load, task)
        check("E7 ... and the file still reads after it", exc is None and view["skipped"]["broken_lines"] == 0, repr(exc))
        words_file = tmp / "big-words.txt"
        words_file.write_bytes(big.encode("utf-8"))
        (code, out, err), seconds = timed(lambda: cli("--task", "QA-9", "--not-needed", "Q2", "--words-file", str(words_file), *wh("Q2")))
        check("E7 edge 6 CLI: 200 KB of words through --words-file are recorded and kept WHOLE",
              code == 0 and seconds < 10 and row_of(QR.load(task), "Q2")["words"] == big, f"{code} {seconds:.2f}s {err[:200]}")
    finally:
        cleanup(proj)


# ------------------------------------------------------------------------------------------------
# edge 2 - fences and quotes are never tokens
# ------------------------------------------------------------------------------------------------

def test_edge2_fence_and_quote(tmp):
    cases = {
        "a token inside a fence": ("```\nQ1: a\n```", {}),
        "a fence with a language tag": ("```text\nQ1: a\n```\nQ2: b", {"Q2": "b"}),
        "tokens before and after a fence, none inside": ("Q1: a\n```\nQ2: b\n```", {"Q1": "a"}),
        "an indented fence": ("  ```\nQ1: a\n  ```", {}),
        "an unclosed fence hides the rest": ("```\nQ1: a\nQ2: b", {}),
        "two fences, the token between them is read": ("```\nQ1: a\n```\nQ2: b\n```\nQ1: b\n```", {"Q2": "b"}),
        "a fence with CRLF line ends": ("```\r\nQ1: a\r\n```\r\nQ2: b\r\n", {"Q2": "b"}),
        "a one-line fence": ("```Q1: a```", {}),
        "a quote": ("> Q1: a", {}),
        "an indented quote": ("   > Q1: a", {}),
        "a nested quote": ("> > Q1: a", {}),
        "a quote after a list marker": ("- > Q1: a", {}),
        "a quote with no space": (">Q1: a", {}),
        "a quote among tokens": ("> Q1: a\nQ2: b\n> Q2: a", {"Q2": "b"}),
    }
    for name, (text, expected) in cases.items():
        got = parse(text)
        check_eq(f"E2b edge 2: {name}", got["choices"], expected)
        check(f"E2b edge 2: {name} - nothing else is read from it (no unknown id, not needed, conflict)",
              got["unknown_ids"] == [] and got["not_needed"] == [] and got["conflicts"] == [], str(got))
    got = parse("```\nQ1: not needed\n" + CASES[8] + ": manual\nQ7: a\n```\n> Q2: not needed\n> " + CASES[8] + ": automate")
    check_eq("E2b edge 2: `not needed`, case tokens and unknown ids inside a fence or a quote are not read either",
             (got["not_needed"], got["case_tokens"], got["unknown_ids"], got["untokened_questions"]), ([], [], [], ["Q1", "Q2"]))
    check_eq("E2b edge 2: a single-backtick line is not a fence: `Q1: a` is still a choice",
             parse("`Q1: a`")["choices"], {"Q1": "a"})


# ------------------------------------------------------------------------------------------------
# edge 3 - each row has its own hash; a record stores the hash of the row AS SHOWN
# ------------------------------------------------------------------------------------------------

def test_edge3_row_hash(tmp):
    import inspect
    check("E3h edge 3: record() has a REQUIRED shown_hash argument (no default)",
          inspect.signature(QR.record).parameters["shown_hash"].default is inspect.Parameter.empty)
    root = write_story(tmp / "e3h", [q("Q1"), q("Q2")])
    view = QR.load(root)
    h1, h2 = row_of(view, "Q1")["row_hash"], row_of(view, "Q2")["row_hash"]
    check_eq("E3h each row has its OWN hash: 64 hex, different rows differ", (len(h1), len(h2), h1 != h2), (64, 64, True))
    same = QR.load(write_story(tmp / "e3h-same", [q("Q1")]))
    reordered = {"readings": q("Q1")["readings"], "severity": "major", "question": "question Q1?", "id": "Q1"}
    other = QR.load(write_story(tmp / "e3h-order", [reordered]))
    check_eq("E3h the hash is the row's content: the same row in another story, or with its keys in another order, is the same hash",
             (row_of(same, "Q1")["row_hash"], row_of(other, "Q1")["row_hash"]), (h1, h1))

    # the person is shown Q1 (hash h1); the register changes Q1 before the answer is recorded
    write_story(root, [q("Q1", 3), q("Q2")])
    now = row_hash_of(root, "Q1")
    check("E3h the changed row has a different hash today", now != h1)
    written = QR.record(root, "Q1", "answered", "Q1: a", "gate A", "person", h1, reading="a")
    check_eq("E3h record() stores the hash of the row AS SHOWN, not the current one", written["row_hash"], h1)
    row = row_of(QR.load(root), "Q1")
    check_eq("E3h the changed row: status as recorded (answered) PLUS changed_since_answer true; the stored hash is exposed",
             (row["status"], row["changed_since_answer"], row["record_row_hash"], row["row_hash"]), ("answered", True, h1, now))
    written = put(root, "Q2", "answered", "Q2: b", reading="b")
    check_eq("E3h a row shown and not changed: changed_since_answer is False", row_of(QR.load(root), "Q2")["changed_since_answer"], False)
    write_story(root, [q("Q1", 4), q("Q2")])
    v = QR.load(root)
    check_eq("E3h changing ANOTHER row does not flag this one (per-row hash, not one hash for the register)",
             (row_of(v, "Q2")["changed_since_answer"], row_of(v, "Q2")["status"]), (False, "answered"))
    write_story(root, [q("Q1", 4), q("Q2", 3)])
    check_eq("E3h ... and a change to its own row does", row_of(QR.load(root), "Q2")["changed_since_answer"], True)
    fresh = put(root, "Q2", "answered", "Q2: b again", reading="b")
    check_eq("E3h answering again with the hash of the row as shown NOW clears the flag",
             (row_of(QR.load(root), "Q2")["changed_since_answer"], fresh["row_hash"]), (False, row_hash_of(root, "Q2")))

    # a record with no stored hash
    old = write_story(tmp / "e3h-old", [q("Q1"), q("Q2"), q("Q3")], answers=[
        json.dumps({"id": "Q1", "status": "answered", "words": "w", "by": "t", "where": "gate A",
                    "at": "2026-09-30T10:00:00+00:00", "register_hash": "h"})])
    QR.record(old, "Q2", "open", "reopened", "conductor", "person", "")
    v = QR.load(old)
    check_eq("E3h a record written before this change (no row_hash) reads changed_since_answer null",
             row_of(v, "Q1")["changed_since_answer"], None)
    check_eq("E3h a reopen recorded with no hash reads null, and its record carries no row_hash key",
             (row_of(v, "Q2")["changed_since_answer"], "row_hash" in json.loads(
                 (old / "work" / "question-answers.jsonl").read_text(encoding="utf-8").split("\n")[-2])), (None, False))
    check_eq("E3h a question with no record reads False, not null", row_of(v, "Q3")["changed_since_answer"], False)

    # refusals
    clean = write_story(tmp / "e3h-refuse", [q("Q1")])
    good = row_hash_of(clean, "Q1")
    for name, status, shown in (("answered", "answered", ""), ("not_needed", "not_needed", ""),
                                ("with_designer", "with_designer", ""), ("answered", "answered", None),
                                ("a short hash", "answered", "abc"), ("an upper-case hash", "answered", good.upper()),
                                ("a hash with a stray space", "answered", good + " "), ("a reopen with a malformed hash", "open", "xyz")):
        try:
            QR.record(clean, "Q1", status, "w", "gate A", "person", shown)
            problem = None
        except QR.Refused as exc:
            problem = str(exc)
        check(f"E3h refused: {name} with hash {shown!r}: nothing written, the text names the register hash",
              problem is not None and "register hash" in problem and not (clean / "work" / "question-answers.jsonl").exists(),
              str(problem))
    QR.record(clean, "Q1", "open", "reopened without a hash", "conductor", "person", "")
    check("E3h a reopen needs no hash: it is recorded", (clean / "work" / "question-answers.jsonl").exists())


# ------------------------------------------------------------------------------------------------
# edge 4 - where and by are required, closed lists
# ------------------------------------------------------------------------------------------------

def test_edge4_where_by(tmp):
    root = write_story(tmp / "e4wb", [q("Q1")])
    good = row_hash_of(root, "Q1")
    answers = root / "work" / "question-answers.jsonl"
    for label, where, by, needles in (
            ("no where", "", "person", ["--where is missing", "no default", "gate A, gate B"]),
            ("no by", "gate A", "", ["--by is missing", "person, conductor, driver, orchestrator"]),
            ("an unknown where", "gate C", "person", ["where 'gate C' is not a known value", "gate A, gate B"]),
            ("an unknown by", "gate A", "somebody", ["by 'somebody' is not a known value", "person, conductor"]),
            ("neither", None, None, ["--where is missing", "--by is missing"])):
        try:
            QR.record(root, "Q1", "answered", "w", where or "", by or "", good)
            text = ""
        except QR.Refused as exc:
            text = str(exc)
        check(f"E4wb edge 4: {label} is refused naming the valid values, and nothing is written",
              text != "" and all(n in text for n in needles) and not answers.exists(), text)
    for by in QR.vocabulary()["by"]:
        got = QR.record(root, "Q1", "answered", "w", "gate A", by, good)
        check_eq(f"E4wb edge 4: by={by!r} is a valid value and is recorded as given", got["by"], by)
    for where in QR.vocabulary()["where"]:
        got = QR.record(root, "Q1", "answered", "w", where, "person", good)
        check_eq(f"E4wb edge 4: where={where!r} is a valid value and is recorded as given", got["where"], where)


# ------------------------------------------------------------------------------------------------
# edge 5 - case decisions: --keep-manual / --automate
# ------------------------------------------------------------------------------------------------

def test_edge5_case_decisions(tmp):
    full = CASES[8]
    root = write_story(tmp / "e5", [q("Q1")], answers=[rec("Q1"), json.dumps({"kind": "question", **json.loads(rec("Q1", "not_needed"))})])
    check_eq("E5c a record with kind `question` and a record with no kind are both question records: the last wins",
             status_of(QR.load(root), "Q1"), "not_needed")
    first = QR.record_case(root, full, "manual", full + ": manual", "gate A", "person")
    check_eq("E5c a case record is {kind, case, decision, words, where, by, at}",
             (sorted(first), first["kind"], first["case"], first["decision"], first["where"], first["by"]),
             (sorted(["kind", "case", "decision", "words", "where", "by", "at"]), "case", full, "manual", "gate A", "person"))
    view = QR.load(root)
    check_eq("E5c load() returns case_decisions {case id: {decision, words, where, by, at}}",
             view["case_decisions"], {full: {"decision": "manual", "words": full + ": manual", "where": "gate A", "by": "person",
                                             "at": first["at"]}})
    check_eq("E5c a case record is NOT counted under skipped (all four counters stay 0)",
             view["skipped"], {"broken_lines": 0, "non_object_lines": 0, "unknown_id": 0, "invalid": 0, "unreadable_file": 0})
    check_eq("E5c a case record makes no question: the register's questions are as before", [x["id"] for x in view["questions"]], ["Q1"])
    QR.record_case(root, full, "automate", "on my word, automate " + full, "gate B", "driver")
    QR.record_case(root, CASES[5], "manual", "the other one", "conductor", "conductor")
    view = QR.load(root)
    check_eq("E5c the LAST case record per case wins; another case is its own entry",
             ({k: (v["decision"], v["where"], v["by"]) for k, v in view["case_decisions"].items()}),
             {full: ("automate", "gate B", "driver"), CASES[5]: ("manual", "conductor", "conductor")})
    check_eq("E5c still nothing skipped after three case records", sum(view["skipped"].values()), 0)
    raw = write_story(tmp / "e5-raw", [q("Q1")], answers=[
        json.dumps({"kind": "case", "decision": "manual", "words": "w"}), json.dumps({"kind": "case", "case": full, "decision": "maybe"}),
        json.dumps({"kind": "case", "case": 5, "decision": "manual"}), json.dumps({"kind": "weird", "id": "Q1", "status": "answered"}),
        case_rec(full, "manual")])
    v = QR.load(raw)
    check_eq("E5c malformed case records and an unknown kind are counted as invalid (4), the good one is read",
             (v["skipped"]["invalid"], list(v["case_decisions"])), (4, [full]))
    check_eq("E5c a case record does not answer a question of the same name",
             status_of(QR.load(write_story(tmp / "e5-same", [q("Q1")], answers=[case_rec("Q1", "manual")])), "Q1"), "open")

    # the ids the caller gives
    file_before = (root / "work" / "question-answers.jsonl").read_bytes()
    for label, ids, case in (("an id that is not one of the story's", CASES, "TP1-13797_TC_099"),
                             ("a short id (only full ids are recorded)", CASES, "TC_009"),
                             ("any id when the story has NO case ids", [], full), ("a blank id", CASES, "   ")):
        try:
            QR.record_case(root, case, "manual", "w", "gate A", "person", case_ids=ids)
            text = ""
        except QR.Refused as exc:
            text = str(exc)
        check(f"E5c refused: {label} -> nothing written", text != "" and (root / "work" / "question-answers.jsonl").read_bytes() == file_before, text)
    try:
        QR.record_case(root, "TP1-13797_TC_099", "manual", "w", "gate A", "person", case_ids=CASES)
    except QR.Refused as exc:
        check("E5c the refusal names the valid full case ids", CASES[0] in str(exc) and "no case with id" in str(exc), str(exc))
    QR.record_case(root, "ANY_1", "manual", "w", "gate A", "person", case_ids=None)
    check("E5c with no case ids given (None) any non-empty id is accepted", "ANY_1" in QR.load(root)["case_decisions"])
    file_mid = (root / "work" / "question-answers.jsonl").read_bytes()
    for label, kwargs in (("a decision that is not manual/automate", {"decision": "skip"}), ("blank words", {"words": " "}),
                          ("no where", {"where": ""}), ("no by", {"by": ""}), ("a bad hash", {"shown_hash": "nope"})):
        args = {"decision": "manual", "words": "w", "where": "gate A", "by": "person"}
        args.update(kwargs)
        try:
            QR.record_case(root, full, args.pop("decision"), args.pop("words"), args.pop("where"), args.pop("by"), **args)
            text = ""
        except QR.Refused as exc:
            text = str(exc)
        check(f"E5c refused: {label} -> nothing written", text != "" and (root / "work" / "question-answers.jsonl").read_bytes() == file_mid, text)
    stored = QR.record_case(root, CASES[1], "manual", "w", "gate A", "person", shown_hash=HASH)
    check_eq("E5c an optional shown hash is stored as row_hash when given, and absent when not",
             ("row_hash" in stored, stored.get("row_hash"), "row_hash" in first), (True, HASH, False))


def test_edge5_case_cli(tmp):
    proj = temp_project("qa-question-register-case-")
    try:
        use_project(proj)
        task = proj / "qa-factory" / "artifacts" / "QA-9"
        write_story(task, [q("Q1")])
        answers = task / "work" / "question-answers.jsonl"
        full = "TP1-9_TC_009"
        common = ["--where", "gate A", "--by", "person"]
        code, out, err = cli("--task", "QA-9", "--keep-manual", full, "--words", full + ": manual", *common)
        got = json.loads(out) if out else {}
        check_eq("E5c CLI: with no case store and no --case-ids-file any non-empty id is accepted, and the output SAYS the ids were not checked",
                 (code, got.get("recorded", {}).get("decision"), got.get("case_ids_checked_against", "")[:5]), (0, "manual", "none:"))
        check_eq("E5c CLI: the record and the read-back agree", (got["recorded"]["case"], got["case_decision"]["decision"]), (full, "manual"))
        code, out, err = cli("--task", "QA-9", "--automate", full, "--words", "on my word", *common)
        got = json.loads(out)
        check_eq("E5c CLI: --automate is the twin: the last decision wins", (code, got["recorded"]["decision"], got["case_decision"]["decision"]),
                 (0, "automate", "automate"))
        (task / "state").mkdir(parents=True, exist_ok=True)
        (task / "state" / "story-case-links.json").write_text(json.dumps(
            {"links": [{"case_id": "TP1-9_TC_001", "version": "v1"}, {"case_id": full, "version": "v1"}, "junk", {"case_id": 5}]}),
            encoding="utf-8")
        before = answers.read_bytes()
        code, out, err = cli("--task", "QA-9", "--keep-manual", "TP1-9_TC_777", "--words", "w", *common)
        check("E5c CLI: the story's case links are read: an id that is not one of the story's is refused (exit 2), nothing written",
              code == 2 and out == "" and "no case with id" in err and "TP1-9_TC_001" in err and answers.read_bytes() == before, err)
        code, out, err = cli("--task", "QA-9", "--keep-manual", "TC_009", "--words", "w", *common)
        check("E5c CLI: a short case id is refused too (only full ids are recorded)", code == 2 and answers.read_bytes() == before, err)
        code, out, err = cli("--task", "QA-9", "--keep-manual", "TP1-9_TC_001", "--words", "w", *common)
        got = json.loads(out)
        check_eq("E5c CLI: a case id of the story is recorded, and the output names what it was checked against",
                 (code, got["case_ids_checked_against"]), (0, "state/story-case-links.json"))
        ids = tmp / "e5-case-ids.txt"
        ids.write_bytes(("TP1-9_TC_500\r\n\r\n  TP1-9_TC_501  \r\n").encode("utf-8"))
        code, out, err = cli("--task", "QA-9", "--automate", "TP1-9_TC_001", "--words", "w", *common, "--case-ids-file", str(ids))
        check("E5c CLI: --case-ids-file wins over the story's links: TC_001 is not in it, refused", code == 2 and "TP1-9_TC_500" in err, err)
        code, out, err = cli("--task", "QA-9", "--automate", "TP1-9_TC_501", "--words", "w", *common, "--case-ids-file", str(ids))
        check_eq("E5c CLI: an id of the file (trimmed) is recorded", (code, json.loads(out)["case_ids_checked_against"]), (0, "--case-ids-file"))
        empty = tmp / "e5-empty-ids.txt"
        empty.write_bytes(b"\n\n")
        code, out, err = cli("--task", "QA-9", "--automate", "TP1-9_TC_501", "--words", "w", *common, "--case-ids-file", str(empty))
        check("E5c CLI: an EMPTY case ids file refuses every id (it says the story has none), nothing is guessed",
              code == 2 and "no case ids" in err or "none - the story has no case ids" in err, err)
        view = QR.load(task)
        check_eq("E5c CLI: the decisions read back, none of them a skipped line",
                 (sorted(view["case_decisions"]), sum(view["skipped"].values())),
                 (sorted([full, "TP1-9_TC_001", "TP1-9_TC_501"]), 0))
        code, out, err = cli("--task", "QA-9", "--show")
        check("E5c CLI: --show prints case_decisions", code == 0 and full in json.loads(out)["case_decisions"], err)
    finally:
        cleanup(proj)


# ------------------------------------------------------------------------------------------------
# edge 6 - words from a file
# ------------------------------------------------------------------------------------------------

def test_edge6_words_file(tmp):
    proj = temp_project("qa-question-register-wf-")
    try:
        use_project(proj)
        task = proj / "qa-factory" / "artifacts" / "QA-9"
        write_story(task, [q("Q1")])
        answers = task / "work" / "question-answers.jsonl"
        tail = ["--where", "gate A", "--by", "person", "--register-hash", row_hash_of(task, "Q1")]
        text = BOM + "- Q1: a\r\n" + HELLO + " " + E_ACUTE + "\r\n" + "y" * 70000
        target = tmp / "wf-words.txt"
        target.write_bytes(text.encode("utf-8"))
        code, out, err = cli("--task", "QA-9", "--answer", "Q1", "--reading", "a", "--words-file", str(target), *tail)
        check_eq("E6w edge 6: --words-file words (BOM, CRLF, non-ASCII, longer than 32 KB) are stored whole",
                 (code, row_of(QR.load(task), "Q1")["words"] == text), (0, True))
        before = answers.read_bytes()
        bad = tmp / "wf-bad.txt"
        bad.write_bytes(b"Q1: a\xff\xfe broken")
        code, out, err = cli("--task", "QA-9", "--answer", "Q1", "--words-file", str(bad), *tail)
        check("E6w edge 6: a words file that is not UTF-8 is refused, the message says what is expected, nothing written",
              code == 2 and "not UTF-8" in err and answers.read_bytes() == before, err)
        utf16 = tmp / "wf-utf16.txt"
        utf16.write_bytes("Q1: a".encode("utf-16"))
        code, out, err = cli("--task", "QA-9", "--answer", "Q1", "--words-file", str(utf16), *tail)
        check("E6w edge 6: a UTF-16 words file (what a Windows shell redirect writes) is refused, not misread",
              code == 2 and answers.read_bytes() == before, err)
        blank = tmp / "wf-blank.txt"
        blank.write_bytes(b" \r\n\t\r\n")
        code, out, err = cli("--task", "QA-9", "--answer", "Q1", "--words-file", str(blank), *tail)
        check("E6w edge 6: a blank words file is a blank-words refusal", code == 2 and "the words are blank" in err and answers.read_bytes() == before, err)
        code, out, err = cli("--task", "QA-9", "--answer", "Q1", "--words", "w", "--words-file", str(target), *tail)
        check("E6w edge 6: both --words and --words-file -> exit 2", code == 2 and answers.read_bytes() == before, err)
        code, out, err = cli("--task", "QA-9", "--show", "--words-file", str(target))
        check("E6w edge 6: --words-file with --show is meaningless and refused", code == 2 and "--words-file" in err, err)
    finally:
        cleanup(proj)


# ------------------------------------------------------------------------------------------------
# edge 7 - appends are serialised
# ------------------------------------------------------------------------------------------------

WRITER = '''
import sys
sys.path.insert(0, sys.argv[1])
import question_register as QR
root, tag, count, size = sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
for n in range(count):
    QR.record(root, "Q1", "answered", tag + ":" + str(n) + ":" + "z" * size, "gate A", "person", "a" * 64, reading="a")
'''


def test_edge7_lock(tmp):
    root = write_story(tmp / "e7", [q("Q1"), q("Q2")])
    answers = root / "work" / "question-answers.jsonl"
    problems = []

    def writer():
        try:
            QR.record(root, "Q2", "answered", "held back", "gate A", "person", HASH)
        except Exception as exc:  # reported through the check below
            problems.append(repr(exc))

    with QR.answers_lock(root):
        thread = threading.Thread(target=writer)
        thread.start()
        time.sleep(0.5)
        check("E7l edge 7: a second writer WAITS while the lock is held: nothing is written, the writer has not returned",
              thread.is_alive() and not answers.exists(), f"alive={thread.is_alive()} file={answers.exists()}")
        check("E7l ... and a reader is not blocked by the writer lock", len(QR.load(root)["questions"]) == 2)
        try:
            with QR.answers_lock(root, wait=0.2):
                waited = False
        except QR.Refused as exc:
            waited = "another writer" in str(exc)
        check("E7l a writer that cannot get the lock in time says so (Refused) and writes nothing", waited and not answers.exists())
    thread.join(20)
    check("E7l after the lock is released the waiting writer writes its record",
          not thread.is_alive() and not problems and status_of(QR.load(root), "Q2") == "answered", str(problems))

    script = tmp / "e7-writer.py"
    script.write_text(WRITER, encoding="utf-8")
    count, size, procs = 12, 60000, 4
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    running = [subprocess.Popen([sys.executable, "-B", str(script), str(harness.SCRIPTS), str(root), f"w{i}", str(count), str(size)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) for i in range(procs)]
    codes = []
    for proc in running:
        _, err = proc.communicate(timeout=300)
        codes.append((proc.returncode, err.decode("utf-8", errors="replace")[-300:] if proc.returncode else ""))
    check_eq("E7l edge 7: four concurrent writer processes all finish cleanly", codes, [(0, "")] * procs)
    lines = [ln for ln in answers.read_bytes().decode("utf-8").split("\n") if ln]
    parsed, broken = [], 0
    for ln in lines:
        try:
            parsed.append(json.loads(ln))
        except ValueError:
            broken += 1
    check_eq("E7l two concurrent writers never interleave a line: every line is one whole JSON record, none broken",
             (broken, len(parsed)), (0, 1 + procs * count))
    mine = [r for r in parsed if str(r.get("words", "")).startswith("w")]
    check("E7l every concurrent record arrived whole (its words end with the full run of z)",
          len(mine) == procs * count and all(r["words"].endswith("z" * size) and len(r["words"]) > size for r in mine))
    per_writer = {}
    for r in mine:
        tag, n, _ = r["words"].split(":", 2)
        per_writer.setdefault(tag, []).append(int(n))
    check_eq("E7l each writer's own records are all there, in its own order",
             {k: v for k, v in sorted(per_writer.items())}, {f"w{i}": list(range(count)) for i in range(procs)})
    check_eq("E7l the file reads back with nothing skipped", sum(QR.load(root)["skipped"].values()), 0)


# ------------------------------------------------------------------------------------------------
# edge 8 - `named`: the id is a word, not a piece of a URL, a path or a file name
# ------------------------------------------------------------------------------------------------

def test_edge8_named(tmp):
    def named_of(name, text, qid):
        pipe = {"gates": {"A": {"decision": "approved", "authorization_source": text}}}
        root = write_story(tmp / ("e8-" + name), [q("Q1"), q("Q3"), q("Q4"), q("Q5")], pipeline=pipe)
        return status_of(QR.load(root), qid)

    not_named = {
        "url": ("see http://x/browse/Q1 for the ticket", "Q1"), "https url": ("https://tracker.example/issue/Q1?x=1", "Q1"),
        "file name": ("the details are in Q3.md", "Q3"), "path": ("docs/Q3/notes.txt and Q3/other", "Q3"),
        "hash sign": ("see #Q4", "Q4"), "path continues": ("Q5/other", "Q5"), "path before": ("x/Q5", "Q5"),
        "dot before": ("a.Q1", "Q1"), "dot after with a digit": ("Q1.5 is the release", "Q1"), "hyphen before": ("R-Q1", "Q1"),
        "hyphen after": ("Q1-x", "Q1"), "underscore": ("Q1_a and Q1a", "Q1"),
        "a longer id": ("Q10 is settled", "Q1"), "an id inside a word": ("aQ1", "Q1"),
    }
    for name, (text, qid) in not_named.items():
        check_eq(f"E8n edge 8: an id inside {name} ({text!r}) is NOT named", named_of(name, text, qid), "open")
    named = {
        "bare": ("Q1", "Q1"), "in brackets": ("(Q1) is settled", "Q1"), "before a comma": ("Q1, Q3 and Q4", "Q3"),
        "bold": ("**Q1** - reading a", "Q1"), "before a colon": ("Q1: a", "Q1"), "list dash and spaces": ("- Q1 - reading (a)", "Q1"),
        "slash-separated ids with spaces": ("Q1 / Q-R14 / R-9 (event-type mismatch)", "Q1"),
        "in quotes": ("\"Q4\" is fine", "Q4"), "in backticks": ("`Q5` is fine", "Q5"), "first word": ("Q3 stays", "Q3"),
        "after a colon": ("answers:Q4", "Q4"),
    }
    for name, (text, qid) in named.items():
        check_eq(f"E8n edge 8: an id standing as a word ({name}: {text!r}) IS named", named_of("p-" + name, text, qid), "named")
    # A backslash right before an id is a boundary, not a word character: a chat client or an editor
    # escapes markdown (`\Q1`), and the person named the question all the same. Built from chr(92), never typed (FR-29).
    bs = chr(92)
    for name, text in (("a markdown escape", bs + "Q1 is settled"), ("an escaped backslash", bs * 2 + "Q1 is settled"),
                       ("after a space and a backslash", "see " + bs + "Q1"), ("a backslash on both sides", bs + "Q1" + bs)):
        check_eq(f"E8n edge 8: a backslash before an id is a boundary ({name}: {text!r}) - the id is found",
                 named_of("bs-" + name, text, "Q1"), "named")
        check_eq(f"E8n edge 8: the line finder reads the same ({name})", QR._line_with(text, "Q1"), text)
    check_eq("E8n edge 8: negative control - a letter before the id is still no boundary (`aQ1`)",
             QR._line_with("aQ1", "Q1"), "")
    check_eq("E8n edge 8: ... nor is a backslash before an id that goes on (`" + bs + "Q10`)",
             QR._line_with(bs + "Q10", "Q1"), "")
    root = write_story(tmp / "e8-mix", [q("Q1"), q("Q3")], answers=[rec("Q3")],
                       pipeline={"gates": {"A": {"authorization_source": "Q1 is fine; also http://x/browse/Q3"}}})
    check_eq("E8n edge 8: with an answers file the question with no record is named, the recorded one is answered",
             (status_of(QR.load(root), "Q1"), status_of(QR.load(root), "Q3")), ("named", "answered"))
    check_eq("E8n the line of the words carries only the real mention", row_of(QR.load(root), "Q1")["line"], "Q1 is fine; also http://x/browse/Q3")


# ------------------------------------------------------------------------------------------------
# the real cmp1 gate A words
# ------------------------------------------------------------------------------------------------

def test_cmp1(tmp):
    questions = [q(f"Q{i}") for i in range(1, 6)]
    got = QR.parse_choices(CMP1_GATE_A, questions, CASES)
    print("cmp1 gate A words ->", json.dumps(got, sort_keys=True))
    check_eq("cmp1 the strict grammar reads NO choice from the person's gate A words", got["choices"], {})
    check_eq("cmp1 ... no `not needed`, no case token, no conflict, no unknown id, no out-of-range letter, nothing unresolved",
             (got["not_needed"], got["case_tokens"], got["conflicts"], got["unknown_ids"], got["out_of_range"], got["unresolved_short_ids"]),
             ([], [], [], [], [], []))
    check_eq("cmp1 ... and all five questions are untokened (they go to the conductor, a role that reads meaning)",
             got["untokened_questions"], ["Q1", "Q2", "Q3", "Q4", "Q5"])
    check("cmp1 the fixture is the words verbatim: 4360 characters, no Cyrillic", len(CMP1_GATE_A) == 4360 and all(ord(c) < 128 for c in CMP1_GATE_A))
    pipe = {"gates": {"A": {"decision": "approved", "authorization_source": CMP1_GATE_A}}}
    view = QR.load(write_story(tmp / "cmp1", questions, pipeline=pipe))
    check_eq("cmp1 the reader: the five questions are `named` (the ids stand in authorization_source), never answered",
             [status_of(view, f"Q{i}") for i in range(1, 6)], ["named"] * 5)
    check_eq("cmp1 the line of the words that carries Q3", row_of(view, "Q3")["line"][:60], "- **Q3 / Q-R7 (UI field for the JSON path filter)** - this i")


# ------------------------------------------------------------------------------------------------
# t-256 O6: `<case id>: accept as blocked` is a whole-line token of the parser
# ------------------------------------------------------------------------------------------------

def test_t256_o6_accept_as_blocked_is_a_whole_line_case_token(tmp):
    got = parse("TC_003: accept as blocked\nTP1-13797_TC_004: accept as blocked.\n- **TC_005**: manual\n")
    check_eq("O6: the register's parser reads the token, a short id resolved, with the id as typed",
             [(t["case"], t["decision"], t["written"]) for t in got["case_tokens"]],
             [("TP1-13797_TC_003", "accept as blocked", "TC_003"), ("TP1-13797_TC_004", "accept as blocked", "TP1-13797_TC_004"),
              ("TP1-13797_TC_005", "manual", "TC_005")])
    for label, words in (("a negation", "TC_003: do not accept as blocked"), ("a second case on the line", "TC_003: accept as blocked; TC_004 runs"),
                         ("the card's old words", "TC_003: accept them as blocked"), ("prose around it", "I think TC_003: accept as blocked")):
        check_eq(f"O6: {label} is no token", parse(words)["case_tokens"], [])
    got = parse("TC_003: accept as blocked\nTC_003: manual")
    check_eq("O6: two different words for one case: a conflict, no token", (got["case_tokens"], [c["values"] for c in got["conflicts"]]),
             ([], [["accept as blocked", "manual"]]))
    check_eq("O6: a register id takes only question tokens - `Q1: accept as blocked` is no case token",
             parse("Q1: accept as blocked")["case_tokens"], [])
    check_eq("O6: an unknown short id is `unresolved`, not guessed", parse("TC_099: accept as blocked")["unresolved_short_ids"],
             [{"id": "TC_099", "candidates": []}])
    check_eq("the register's recorded case decisions are still only manual | automate (record_case writes what a card applies)",
             json.loads((QR.VOCAB_PATH).read_text(encoding="utf-8"))["case_decisions"], ["manual", "automate"])


# ------------------------------------------------------------------------------------------------
# t-256 O4: the S4-exit half of `--raise` - keyed by (case, Then), idempotent
# ------------------------------------------------------------------------------------------------

def test_t256_o4_raise_for_case_is_keyed_by_case_and_then(tmp):
    import contract as C
    fixtures = Path(__file__).resolve().parent / "fixtures" / "oracle-provenance"
    readiness = (fixtures / "requirements-readiness.json").read_text(encoding="utf-8")
    tc015 = (fixtures / "TP1-15045_TC_015.md").read_text(encoding="utf-8").replace("updated: 2026-10-01", "updated: 2026-10-02")
    spec = {"then": 4, "question": "Which status code must PUT return for a body that breaks two checks at once?",
            "source_says": [{"quote": "returns the same results and error codes as before", "where": "register R-19"}],
            "severity": "major", "owner_role": "po_ba", "before": {"value": "unknown", "where": "the base revision is not in the hunk"},
            "now": {"value": "400", "where": "observed by the S5 run"}}
    oracles = [{"then": 1, "source": "ac", "ref": "R-13"}, {"then": 2, "source": "ac", "ref": "R-13"},
               {"then": 3, "source": "ac", "ref": "R-13"}, {"then": 4, "source": "unknown", "ref": "raise"}]
    qthens = [{"question": "raise", "then": 4, "readings": {"a": "HTTP 400, the behaviour now", "b": ""}, "not_needed": ""}]

    def case_with(oracles=oracles, qthens=qthens, raise_questions=(spec,)):
        extra = f"then_oracles: {json.dumps(oracles)}\nquestion_thens: {json.dumps(qthens)}\n"
        if raise_questions:
            extra += f"raise_questions: {json.dumps(list(raise_questions))}\n"
        return tc015.replace("plan_row: TS-15\n", extra + "plan_row: TS-15\n", 1)

    story = tmp / "t256-raise"
    (story / "work").mkdir(parents=True)
    ready = story / "work" / "requirements-readiness.json"
    ready.write_text(readiness, encoding="utf-8")
    text = case_with()
    done = QR.raise_for_case(story, text, "TP1-15045_TC_015")
    check_eq("O4: one question raised for the Then that said `raise`", done["raised"],
             [{"case": "TP1-15045_TC_015", "then": 4, "question": "Q8"}])
    check_eq("...and nothing was refused", done["problems"], [])
    new = done["text"]
    check_eq("the then_oracles line now names the new id", C.then_oracles_from_text(new)[0][3], {"then": 4, "source": "unknown", "ref": "Q8"})
    check_eq("the question_thens entry that said `raise` names it too", C.question_thens_from_text(new)[0][0]["question"], "Q8")
    check_eq("the raise_questions line is gone", C.front_line(new, "raise_questions"), None)
    check_eq("every other line of the case is byte for byte as it was",
             [ln for ln in new.splitlines() if not ln.startswith(("then_oracles:", "question_thens:"))],
             [ln for ln in text.splitlines() if not ln.startswith(("then_oracles:", "question_thens:", "raise_questions:"))])
    rows = json.loads(ready.read_text(encoding="utf-8"))["open_questions"]
    check_eq("the readiness file holds it after the old ones, keyed by (case, Then)",
             [(r["id"], r.get("raised_for")) for r in rows], [("Q1", None), ("Q7", None), ("Q8", {"case": "TP1-15045_TC_015", "then": 4})])
    check_eq("it passes the shape check and shows before/now", (C.question_errors(rows[2]), rows[2]["before"]["value"]), ([], "unknown"))
    # idempotent: the case rewrite was lost (a crash between the raise and the write); the SAME text raises nothing twice
    again = QR.raise_for_case(story, text, "TP1-15045_TC_015")
    check_eq("O4: the same (case, Then) again returns the question it raised", again["raised"],
             [{"case": "TP1-15045_TC_015", "then": 4, "question": "Q8"}])
    check_eq("...and the readiness file is untouched: no duplicate", len(json.loads(ready.read_text(encoding="utf-8"))["open_questions"]), 3)
    check_eq("the rewritten case has nothing left to raise (text None, nothing raised)",
             {k: v for k, v in QR.raise_for_case(story, new, "TP1-15045_TC_015").items() if k != "problems"},
             {"text": None, "raised": []})
    other = QR.raise_for_case(story, text, "TP1-15045_TC_016")
    check_eq("another case with the same Then number is another question (Q9)", [r["question"] for r in other["raised"]], ["Q9"])
    # what it refuses: the Then stays `raise` and one sentence says why
    no_entry = QR.raise_for_case(story, case_with(raise_questions=()), "TP1-15045_TC_017")
    check_eq("a `raise` with no raise_questions entry: nothing raised, no text, one problem", (no_entry["raised"], no_entry["text"], len(no_entry["problems"])),
             ([], None, 1))
    check_in("...naming the Then", "Then 4 is `unknown` with the ref `raise` but the case has no `raise_questions` entry for it", no_entry["problems"][0])
    bad = QR.raise_for_case(story, case_with(raise_questions=({k: v for k, v in spec.items() if k != "now"},)), "TP1-15045_TC_018")
    check_eq("an entry the register would refuse: nothing raised", (bad["raised"], bad["text"]), ([], None))
    check_in("...with the register's own sentence", "needs `now` as an object", bad["problems"][0])
    check_eq("...and the readiness file holds the four questions it should (Q1, Q7, Q8, Q9)",
             [r["id"] for r in json.loads(ready.read_text(encoding="utf-8"))["open_questions"]], ["Q1", "Q7", "Q8", "Q9"])
    # a Then that already has a settled oracle is never asked about
    settled = case_with(oracles=oracles[:3] + [{"then": 4, "source": "ac", "ref": "R-13"}], qthens=[])
    check_eq("no `raise` ref: nothing to do", QR.raise_for_case(story, settled, "TP1-15045_TC_019")["raised"], [])
    # set_front_line: the one line only, line endings kept, a body line never touched
    crlf = "---\r\nid: x\r\nraise_questions: [1]\r\nthen_oracles: [2]\r\n---\r\nraise_questions: [body]\r\n"
    check_eq("set_front_line removes one front-matter line and keeps the CRLF of the others",
             C.set_front_line(crlf, "raise_questions", None), "---\r\nid: x\r\nthen_oracles: [2]\r\n---\r\nraise_questions: [body]\r\n")
    check_eq("...and rewrites one in place", C.set_front_line(crlf, "then_oracles", "[3]").splitlines()[3], "then_oracles: [3]")
    check_eq("...removing the LAST front-matter line leaves no blank line", C.set_front_line("---\nid: x\nraise_questions: [1]\n---\nbody\n", "raise_questions", None),
             "---\nid: x\n---\nbody\n")
    check_eq("a text with no such line is returned unchanged", C.set_front_line("---\nid: x\n---\n", "nothing", None), "---\nid: x\n---\n")


def test_g1_13_question_row_keys_never_meet_and_the_readiness_writer_keeps_its_bytes(tmp):
    """G1-13: `_question_row` is the one row step of `_raise` and of the S3 claim projector. A claim key and a case key with the same
    numbers never meet; `taken` hands out contiguous ids; `_write_readiness` writes the bytes `_raise` always wrote."""
    question = {key: f"v-{key}" for key in QR.QUESTION_KEYS}
    rows = [{"id": "Q1", "raised_for": {"case": "R-28", "then": 1}}, {"id": "Q7"}]
    row, earlier = QR._question_row(rows, question, {"claim": "R-28", "origin": "S3-grounding"})
    check_eq("a claim key is not the case key of the same numbers: a new row, Q8, the keys in order",
             (earlier, row["id"], list(row)), (None, "Q8", ["id", *QR.QUESTION_KEYS, "raised_for"]))
    again, found = QR._question_row(rows + [row], question, {"claim": "R-28", "origin": "S3-grounding"})
    check_eq("the same claim key finds its row and makes no second one", (again, found is row), (None, True))
    case_row, case_found = QR._question_row(rows, question, {"case": "R-28", "then": 1})
    check_eq("the case key still finds the case row", (case_row, case_found), (None, rows[0]))
    check_eq("`taken` makes a batch contiguous without rescanning its own rows",
             [QR._question_row(rows, question, {"claim": f"R-{n}", "origin": "x"}, taken=top)[0]["id"] for n, top in ((1, 0), (2, 8), (3, 9))],
             ["Q8", "Q9", "Q10"])
    path = tmp / "g1-13-readiness.json"
    data = {"verdict": "ready", "open_questions": [{"id": "Q1", "text": "é"}]}
    QR._write_readiness(path, data)
    check_eq("_write_readiness: the file is the indent-2 JSON with ensure_ascii False and a final newline, no staged file left",
             (path.read_bytes().decode("utf-8").replace("\r\n", "\n"), path.with_name(path.name + ".tmp").exists()),
             (json.dumps(data, ensure_ascii=False, indent=2) + "\n", False))


# ------------------------------------------------------------------------------------------------
# HF2-7 part 1 (GW1-21): the store keeps what a person said and says it with ONE vocabulary
# ------------------------------------------------------------------------------------------------

OWN_WORDS = "".join(chr(c) for c in (0x43e, 0x441, 0x442, 0x430, 0x432, 0x44c, 0x20, 0x43e, 0x442, 0x43a, 0x440, 0x44b, 0x442, 0x44b,
                                      0x43c, 0x20, 0x434, 0x43e, 0x20, 0x43e, 0x442, 0x447, 0x451, 0x442, 0x430))   # "leave it open until the report"
WORDS_1 = "Q1: b\nQ2: a\nQ3: until the report\nQ4: a\nQ5: a\n"
WORDS_2 = "Q1 b, Q3 " + OWN_WORDS
SPEC_ROOT = Path(__file__).resolve().parents[2]


def f12586_rows(q4_severity=None) -> list:
    """The F-12586 register: Q1 major, Q2 minor, Q3 blocker, Q4 with no severity (or `q4_severity`), Q5 blocker; two readings each."""
    def row(qid, severity):
        out = q(qid)
        out.pop("severity")
        out.update({"owner_role": "qa"})
        if severity:
            out["severity"] = severity
        return out
    return [row("Q1", "major"), row("Q2", "minor"), row("Q3", "blocker"), row("Q4", q4_severity), row("Q5", "blocker")]


def f12586(q4_severity=None, verdict="blocked") -> dict:
    return {"verdict": verdict, "goal_summary": "Check the filter of the webhook payload end to end, by its paths",
            "aspects": {"functional": {"status": "ready"}}, "register": {"total": 3, "by_source": {"story": 2, "ac": 1}},
            "open_questions": f12586_rows(q4_severity)}


def f12586_story(path: Path, q4_severity=None, answers=None) -> Path:
    return write_story(path, readiness_raw=json.dumps(f12586(q4_severity)), answers=answers)


def test_hf2_7_p1_vocabulary_and_parser(tmp):
    vocab = QR.vocabulary()
    check("K1 hf2-7: deferred_to_report is in statuses and in recorded_statuses; blocking is a stop reason",
          "deferred_to_report" in vocab["statuses"] and "deferred_to_report" in vocab["recorded_statuses"]
          and "blocking" in vocab["stop_reasons"], str(vocab["statuses"]))
    # P1 pinned `S4 stop` as absent "until P5a adds it with the S4 code"; P5a (t-108, accepted) added it to `where` and `where_words`
    check("K1 hf2-7: `S4 stop` is in where and in where_words (P5a, t-108)",
          "S4 stop" in vocab["where"] and bool(vocab["where_words"].get("S4 stop")), str(vocab["where"]))
    check_eq("K1 hf2-7: every value of `where` has its words", [w for w in vocab["where"] if not vocab["where_words"].get(w)], [])
    check_eq("K12 where_words: S2 stop, gate A (the pinned form), an unknown value and a value that is no text",
             [QR.where_words("S2 stop"), QR.where_words("gate A"), QR.where_words("zzz"), QR.where_words(None), QR.where_words("note")],
             ["when the requirements were checked", "at gate A", "earlier", "earlier", "earlier"])
    rows = f12586_rows()
    got = QR.parse_choices(WORDS_1, rows, [])
    check_eq("K2 hf2-7: words 1 -> four choices, Q3 deferred, and Q3 is neither a choice nor untokened",
             (got["choices"], got["deferred"], "Q3" in got["untokened_questions"], got["unknown_ids"]),
             ({"Q1": "b", "Q2": "a", "Q4": "a", "Q5": "a"}, ["Q3"], False, []))
    fenced = QR.parse_choices("```\nQ3: until the report\n```\n", rows, [])
    check_eq("K2 hf2-7: the token inside a code block is said (fenced), not read", (fenced["deferred"], fenced["fenced"]),
             ([], ["Q3: until the report"]))
    quoted = QR.parse_choices("> Q3: until the report\n", rows, [])
    check_eq("K2 hf2-7: a quoted token is not read", (quoted["deferred"], "Q3" in quoted["untokened_questions"]), ([], True))
    check_eq("K2 hf2-7: `Q50: until the report` is an unknown id", QR.parse_choices("Q50: until the report", rows, [])["unknown_ids"], ["Q50"])
    check_eq("K2 hf2-7: a trailing full stop and a list dash keep the token whole", QR.parse_choices("- Q3: until the report.", rows, [])["deferred"], ["Q3"])
    check_eq("K2 hf2-7: prose after the words is no token (`until the report, please`)", QR.parse_choices("Q3: until the report, please", rows, [])["deferred"], [])
    check_eq("K2 hf2-7: two different answers for Q3 write neither (a conflict, still untokened)",
             (QR.parse_choices("Q3: a\nQ3: until the report", rows, [])["conflicts"][0]["id"],
              QR.parse_choices("Q3: a\nQ3: until the report", rows, [])["deferred"]), ("Q3", []))
    crlf = QR.parse_choices(BOM + WORDS_1.replace("\n", "\r\n"), rows, [])
    check_eq("K2 battery: CRLF and a BOM read the same five tokens", (crlf["choices"], crlf["deferred"]), (got["choices"], got["deferred"]))
    for label, text in (("a full-width colon", f"Q1{FULL_COLON}a"), ("a Cyrillic a", f"Q1: {CYR_A}"), ("a lower-case id", "q1: a"),
                        ("nothing", ""), ("spaces only", "   \n \t \n"), ("a colon with no value", "Q1:")):
        read = QR.parse_choices(text, rows, [])
        check_eq(f"K2 battery: {label} is no token", (read["choices"], read["not_needed"], read["deferred"]), ({}, [], []))
    many = QR.parse_choices("\n".join(f"Q{n}: a" for n in range(1, 61)), [q(f"Q{n}") for n in range(1, 61)], [])
    check_eq("K2 battery: 60 lines are all read (no limit)", len(many["choices"]), 60)


def test_hf2_7_p1_record_answers(tmp):
    root = f12586_story(tmp / "k3")
    answers = root / "work" / "question-answers.jsonl"
    got = QR.record_answers(root, WORDS_1, "S2 stop", "person")
    stored = [json.loads(x) for x in answers.read_text(encoding="utf-8").splitlines()]
    check_eq("K3 hf2-7: words 1 -> four answers recorded, Q3 deferred, all tokens, nothing unread",
             (got["recorded"], got["deferred"], got["all_tokens"], got["unread"], got["unknown_ids"], got["fenced"]),
             (["Q1: b", "Q2: a", "Q4: a", "Q5: a"], ["Q3"], True, [], [], []))
    check_eq("K3 hf2-7: five records in the file; Q3 is `deferred_to_report` with no reading; each keeps the words whole",
             ([(r["id"], r["status"], r.get("reading", "")) for r in stored], {r["words"] for r in stored}, {r["where"] for r in stored}),
             ([("Q1", "answered", "b"), ("Q2", "answered", "a"), ("Q4", "answered", "a"), ("Q5", "answered", "a"),
               ("Q3", "deferred_to_report", "")], {WORDS_1}, {"S2 stop"}))
    view = QR.load(root)
    check_eq("K4 hf2-7: load reads Q3 back as deferred_to_report", status_of(view, "Q3"), "deferred_to_report")
    again = QR.record_answers(root, WORDS_1, "S2 stop", "person")
    check_eq("K3 hf2-7: the same words again write nothing (H6b), and are still all tokens",
             (len(answers.read_text(encoding="utf-8").splitlines()), again["recorded"], again["deferred"], again["all_tokens"]), (5, [], [], True))
    root2 = f12586_story(tmp / "k3b")
    two = QR.record_answers(root2, WORDS_2, "S2 stop", "person")
    check_eq("K3 hf2-7: words 2 (no token on a line of its own) write nothing and are not all tokens",
             (two["recorded"], two["deferred"], two["all_tokens"], (root2 / "work" / "question-answers.jsonl").exists()), ([], [], False, False))
    for label, text in (("empty", ""), ("spaces", "  \n  "), ("a lone colon", "Q1:")):
        r3 = QR.record_answers(root2, text, "S2 stop", "person")
        check_eq(f"K3 hf2-7: {label} words write nothing and are not all tokens (C14)",
                 (r3["recorded"], r3["all_tokens"], (root2 / "work" / "question-answers.jsonl").exists()), ([], False, False))
    mixed = QR.record_answers(root2, "Q1: a\nplease also look at the logs\n", "S2 stop", "person")
    check_eq("K3 hf2-7: a token with prose on another line is recorded, but not all tokens (the role reads the rest)",
             (mixed["recorded"], mixed["all_tokens"]), (["Q1: a"], False))
    unknown = QR.record_answers(root2, "Q50: a\nQ2: b", "S2 stop", "person")
    check_eq("H4 hf2-7: an id not in the register is an unknown id, nothing is recorded for it; the other token is",
             (unknown["unknown_ids"], unknown["recorded"], unknown["all_tokens"]), (["Q50"], ["Q2: b"], False))
    conflict = QR.record_answers(f12586_story(tmp / "h5"), "Q1: a\nQ1: b\nQ2: a", "S2 stop", "person")
    check_eq("H5 hf2-7: two different answers for one id write neither and are said", (conflict["recorded"], conflict["all_tokens"],
             [u for u in conflict["unread"] if u.startswith("Q1")]), (["Q2: a"], False, ["Q1 (two different answers: a, b)"]))
    beyond = QR.record_answers(f12586_story(tmp / "range"), "Q1: z", "S2 stop", "person")
    check_eq("H4 hf2-7: a letter beyond the readings is said, not recorded", (beyond["recorded"], beyond["unread"]),
             ([], ["Q1 (the letter z is beyond its 2 readings)"]))
    fenced = QR.record_answers(f12586_story(tmp / "fence"), "```\nQ1: a\n```\n", "S2 stop", "person")
    check_eq("H25 hf2-7: a token in a code block is `fenced`, nothing recorded, not all tokens",
             (fenced["recorded"], fenced["fenced"], fenced["all_tokens"]), ([], ["Q1: a"], False))
    shown = QR.record_answers(f12586_story(tmp / "bad-hash"), "Q1: a", "S2 stop", "person", shown={"Q1": "not-a-hash"})
    check_eq("H18 hf2-7: a refusal of one record is a line in unread (the question stays open), not an exception",
             (shown["recorded"], len(shown["unread"]), "sha256" in shown["unread"][0]), ([], 1, True))
    root3 = write_story(tmp / "c13", [q("Q7")], answers=[rec("Q7", "with_designer")])
    check_eq("C13 hf2-7: a token for a question that is with the designer is recorded (the exact id is the person's word)",
             QR.record_answers(root3, "Q7: a", "S2 stop", "person")["recorded"], ["Q7: a"])


def test_hf2_7_p1_record_rules(tmp):
    root = f12586_story(tmp / "k4b")
    answers = root / "work" / "question-answers.jsonl"
    put(root, "Q5", "answered", "Q5: a", reading="a")
    before = answers.read_bytes()
    try:
        put(root, "Q5", "answered", "Q5: b", reading="b")
        refused = ""
    except QR.Refused as exc:
        refused = str(exc)
    check("K4b hf2-7: a DIFFERENT answer on a settled question is refused with the door (reopen, words by file) and the reason",
          "Q5 is already settled (reading a, at gate A" in refused and "--reopen Q5 --words-file <file>" in refused
          and "the plan rows that followed the first answer are reworked" in refused, refused)
    check("K4b hf2-7: ...and nothing was written", answers.read_bytes() == before)
    try:
        put(root, "Q5", "not_needed", "Q5: not needed")
        other = ""
    except QR.Refused as exc:
        other = str(exc)
    check("K4b hf2-7: `not needed` over a letter is a different answer too", "already settled" in other, other)
    put(root, "Q5", "open", "back to open", hash_from="")
    put(root, "Q5", "answered", "Q5: b", reading="b")
    check_eq("K4b hf2-7: after --reopen (status open) the new answer is written", row_of(QR.load(root), "Q5")["reading"], "b")
    count = len(answers.read_text(encoding="utf-8").splitlines())
    put(root, "Q5", "answered", "Q5: b again, other words", hash_from="c" * 64, reading="b")
    check_eq("K4b hf2-7: the SAME answer with another hash and other words is appended (H6b; the old pins stay)",
             len(answers.read_text(encoding="utf-8").splitlines()), count + 1)
    put(root, "Q3", "deferred_to_report", "later", reading="")
    put(root, "Q3", "answered", "Q3: a", reading="a")
    check_eq("K4b hf2-7: an answer over deferred_to_report is written (H6c: a deferred question is not settled)", row_of(QR.load(root), "Q3")["reading"], "a")
    try:
        put(root, "Q3", "deferred_to_report", "later", reading="")
        late = ""
    except QR.Refused as exc:
        late = str(exc)
    check("K4b hf2-7: `until the report` over a settled answer is a different answer: refused", "already settled" in late, late)
    # the row moved after the answer: the answer was given on other bytes, so the question is asked again and answers freely (H6d)
    root2 = write_story(tmp / "h6d", [q("Q1")], answers=[rec("Q1", "answered", reading="a")])
    check_eq("H6d hf2-7: the record carries a hash that is not the row's -> changed_since_answer", row_of(QR.load(root2), "Q1")["changed_since_answer"], True)
    put(root2, "Q1", "answered", "Q1: b", reading="b")
    check_eq("H6d hf2-7: a new answer on a changed row is written without --reopen", row_of(QR.load(root2), "Q1")["reading"], "b")
    row = dict(q("Q6"), before={"value": "unknown", "where": "x"}, now={"value": "403", "where": "y"})
    root3 = write_story(tmp / "bvn", [row])
    put(root3, "Q6", "answered", "Q6: b", reading="b")
    put(root3, "Q6", "answered", "Q6: a", reading="a")
    check_eq("H6d hf2-7: an answer `b` while the before value is missing does not settle: another answer is written",
             row_of(QR.load(root3), "Q6")["reading"], "a")
    try:
        QR.record(root, "Q1", "deferred_to_report", "later", "gate A", "person", row_hash_of(root, "Q1"), reading="a")
        letter = ""
    except QR.Refused as exc:
        letter = str(exc)
    check("K4 hf2-7: a reading with `until the report` is refused; without a reading it is written (above)", "reading letter goes only with an answer" in letter, letter)


def test_hf2_7_p1_predicates(tmp):
    def mk(status="open", severity="blocker", **extra):
        out = {"id": "Q", "status": status, "reading": "", "changed_since_answer": False}
        if severity is not None:
            out["severity"] = severity
        out.update(extra)
        return out
    table = [
        ("Q3 open", mk(), (False, True, True, None)),
        ("Q3 named", mk("named"), (False, True, True, None)),
        ("Q3 deferred", mk("deferred_to_report"), (False, False, False, None)),
        ("Q3 deferred + changed", mk("deferred_to_report", changed_since_answer=True), (False, True, True, None)),
        ("Q5 answered a", mk("answered", reading="a"), (True, False, False, "a")),
        ("Q5 answered a + changed", mk("answered", reading="a", changed_since_answer=True), (False, True, True, None)),
        ("Q5 answered a, hash not stored (None)", mk("answered", reading="a", changed_since_answer=None), (True, False, False, "a")),
        ("Q6 answered b, before unknown", mk("answered", reading="b", before={"value": "unknown"}), (False, True, True, None)),
        ("Q6 answered b, before empty", mk("answered", reading="b", before={"value": ""}), (False, True, True, None)),
        ("Q6 answered b, before known", mk("answered", reading="b", before={"value": "400"}), (True, False, False, "b")),
        ("Q2 not_needed", mk("not_needed"), (True, False, False, "not_needed")),
        ("answered with no letter", mk("answered"), (True, False, False, None)),
        ("with_designer", mk("with_designer"), (False, False, False, None)),
        ("an unknown status", mk("invented"), (False, True, True, None)),
        ("no status at all", {"id": "Q", "severity": "blocker"}, (False, True, True, None)),
    ]
    for label, question, want in table:
        got = (QR.settled(question), QR.is_open(question), QR.open_blocker(question), QR.answer_key(question))
        check_eq(f"K9 hf2-7: {label} -> settled/is_open/open_blocker/answer_key", got, want)
    for label, severity in (("no severity (Q4)", None), ("`Blocker`", "Blocker"), ("`critical`", "critical"), ("a list", ["major"])):
        check(f"K9 hf2-7: an open question with {label} is a blocker (the error goes toward asking)", QR.open_blocker(mk(severity=severity)))
    check("K9 hf2-7: an open question marked major or minor is not a blocker",
          not QR.open_blocker(mk(severity="major")) and not QR.open_blocker(mk(severity="minor")))
    check_eq("K9 hf2-7: a row that is no object: not settled, open, a blocker", (QR.settled(None), QR.is_open("Q1"), QR.open_blocker(7)), (False, True, True))
    # K9b: a publish reads rows that are not on disk; the hash is the data's, and load gets the same answer through _merge
    root = f12586_story(tmp / "k9b")
    QR.record_answers(root, WORDS_1, "S2 stop", "person")
    data = f12586_rows()
    same = QR.statuses_for(root, data)
    check_eq("K9b hf2-7: unchanged data rows read as load reads them", same, QR.load(root)["questions"])
    data[4] = dict(data[4], question="Q5 with other words?")
    moved = QR.statuses_for(root, data)
    check_eq("K9b hf2-7: Q5 with another text in the DATA is changed_since_answer (the hash is the data's, not the disk's)",
             (moved[4]["changed_since_answer"], moved[4]["status"], QR.settled(moved[4]), QR.open_blocker(moved[4])), (True, "answered", False, True))
    f12586_story(tmp / "k9b-disk")
    (tmp / "k9b-disk" / "work" / "question-answers.jsonl").write_bytes((root / "work" / "question-answers.jsonl").read_bytes())
    (tmp / "k9b-disk" / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": data}), encoding="utf-8")
    check_eq("K9b hf2-7: ...and load on a disk register holding those rows says the same (one _merge)",
             QR.load(tmp / "k9b-disk")["questions"], moved)
    odd = QR.statuses_for(root, ["x", {"question": "no id?"}])
    check_eq("K9b hf2-7: a row that is no object gives None, a row with no id has no record and is open", (odd[0], odd[1]["status"]), (None, "open"))
    nothing = QR.statuses_for(tmp / "no-such-story", data)
    check("H1 hf2-7: with no answers file every row is open", all(x["status"] == "open" for x in nothing))
    unreadable = write_story(tmp / "h2-dir", f12586_rows())
    (unreadable / "work" / "question-answers.jsonl").mkdir()
    check("H2 hf2-7: an answers file that cannot be read (a folder): every row open, no exception",
          all(x["status"] == "open" for x in QR.statuses_for(unreadable, f12586_rows())))


def test_hf2_7_p1_brief_and_drift(tmp):
    root = write_story(tmp / "k5", f12586_rows() + [q("Q6")])    # Q6 is the question nobody answers: it stays open
    check_eq("K5 hf2-7: no answers file -> no answers, not unreadable (H1)", QR.answers_for_brief(root), {"answers": [], "unreadable": False})
    QR.record_answers(root, WORDS_1 + "Q60: a\n", "S2 stop", "person")
    brief = QR.answers_for_brief(root)
    check_eq("K5 hf2-7: the settled and the deferred are listed, in register order, nothing open",
             [(a["id"], a["status"], a["reading"], a["reading_text"]) for a in brief["answers"]],
             [("Q1", "answered", "b", "reading 1"), ("Q2", "answered", "a", "reading 0"), ("Q3", "deferred_to_report", "", ""),
              ("Q4", "answered", "a", "reading 0"), ("Q5", "answered", "a", "reading 0")])
    check_eq("K5 hf2-7: an entry carries id, question, status, reading, reading_text, where, at, words (whole)",
             sorted(brief["answers"][0]), sorted(["id", "question", "status", "reading", "reading_text", "where", "at", "words"]))
    check_eq("K5 hf2-7: the words are the whole text", brief["answers"][0]["words"], WORDS_1 + "Q60: a\n")
    check_eq("K5 hf2-7: Q6 is open (nobody answered it) and has no entry; Q60 is no register id and has none either",
             [a["id"] for a in brief["answers"] if a["id"] in ("Q6", "Q60")], [])
    sick = f12586_story(tmp / "k5-broken")
    good = rec("Q1", "answered", reading="a", row_hash=row_hash_of(sick, "Q1"))   # the hash the row has today: the answer holds
    (sick / "work" / "question-answers.jsonl").write_text(good + "\n{ not json", encoding="utf-8")
    check_eq("K5 hf2-7: one broken line -> unreadable, the good record is kept (H2)",
             (QR.answers_for_brief(sick)["unreadable"], [a["id"] for a in QR.answers_for_brief(sick)["answers"]]), (True, ["Q1"]))
    applied = f12586_story(tmp / "k5-applied")
    (applied / "work" / "question-answers.jsonl").write_text(
        rec("Q1", "answered", reading="a", row_hash=row_hash_of(applied, "Q1")) + "\n"
        + json.dumps({"kind": "answers_applied", "id": "Q1", "at": "2026-10-26T10:00:00+00:00"}), encoding="utf-8")
    check_eq("K5 hf2-7: an `answers_applied` line is no breakage (N7): unreadable False",
             QR.answers_for_brief(applied)["unreadable"], False)
    folder = f12586_story(tmp / "k5-dir")
    (folder / "work" / "question-answers.jsonl").mkdir()
    check_eq("K5 hf2-7: an answers file that is a folder -> unreadable and skipped.unreadable_file == 1",
             (QR.answers_for_brief(folder)["unreadable"], QR.load(folder)["skipped"]["unreadable_file"]), (True, 1))
    changed = f12586_story(tmp / "k5-changed", answers=[rec("Q1", "answered", reading="a")])
    check_eq("K5 hf2-7: an answer given on other bytes (the row changed) is asked again, so it is not listed", QR.answers_for_brief(changed)["answers"], [])
    # K6: an answered question stays in the register
    drift_root = f12586_story(tmp / "k6")
    QR.record_answers(drift_root, WORDS_1, "S2 stop", "person")
    check_eq("K6 hf2-7: every row present -> no drift", QR.readiness_drift(drift_root), [])
    kept = [r for r in f12586_rows() if r["id"] != "Q5"]
    (drift_root / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": kept}), encoding="utf-8")
    check_eq("K6 hf2-7: Q5 answered a but gone from open_questions -> ONE problem, in the T6 words",
             QR.readiness_drift(drift_root),
             ["Q5 has an answer recorded at S2 stop (a) but is missing from open_questions: an answered question stays in the register with "
              "its id. Expected: restore the row as it was; the factory reads its status from the answers file."])
    kept = [r for r in f12586_rows() if r["id"] not in ("Q3",)]
    (drift_root / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": kept}), encoding="utf-8")
    check("K6 hf2-7: a deferred question gone from the register is named with `until the report`",
          any(p.startswith("Q3 has an answer recorded at S2 stop (until the report)") for p in QR.readiness_drift(drift_root)))
    (drift_root / "work" / "requirements-readiness.json").write_text("{ not json", encoding="utf-8")
    check_eq("K6 hf2-7: a register that cannot be read -> [] (its own finding)", QR.readiness_drift(drift_root), [])
    check_eq("K6 hf2-7: no register file at all -> []", QR.readiness_drift(tmp / "nowhere"), [])
    check_eq("K6 hf2-7: an empty answers file or none -> []", QR.readiness_drift(f12586_story(tmp / "k6-none")), [])


def test_hf2_7_p1_cli_defer(tmp):
    proj = temp_project("qa-question-register-")
    try:
        use_project(proj)
        task = proj / "qa-factory" / "artifacts" / "QA-9"
        write_story(task, f12586_rows())
        shown = json.loads(cli("--task", "QA-9", "--show")[1])
        digest = next(x["row_hash"] for x in shown["questions"] if x["id"] == "Q3")
        words = proj / "words.txt"
        words.write_bytes((BOM + "Q3: until the report\r\nI will come back to it").encode("utf-8"))
        code, out, err = cli("--task", "QA-9", "--defer", "Q3", "--words-file", str(words), "--where", "S2 stop", "--by", "person",
                             "--register-hash", digest)
        written = json.loads(out)["recorded"] if code == 0 else {}
        check_eq("K7 hf2-7: --defer writes a deferred_to_report record; the words are read by person_words (BOM off, CRLF kept)",
                 (code, written.get("status"), written.get("words"), written.get("reading")),
                 (0, "deferred_to_report", "Q3: until the report\r\nI will come back to it", None))
        check_eq("K7 hf2-7: ...and --show reads it back", next(x["status"] for x in json.loads(cli("--task", "QA-9", "--show")[1])["questions"] if x["id"] == "Q3"),
                 "deferred_to_report")
        empty = proj / "empty.txt"
        empty.write_bytes(b"")
        code, out, err = cli("--task", "QA-9", "--defer", "Q3", "--words-file", str(empty), "--where", "S2 stop", "--by", "person", "--register-hash", digest)
        check("K7 hf2-7: an empty words file is person_words' refusal (named option, nothing recorded)", code == 2 and "--words-file" in err and "is empty" in err, err)
        code, out, err = cli("--task", "QA-9", "--defer", "Q3", "--words", "w", "--words-file", str(words), "--where", "S2 stop", "--by", "person",
                             "--register-hash", digest)
        check("K7 hf2-7: both --words and --words-file are refused", code == 2 and "exactly one" in err, err)
        code, out, err = cli("--task", "QA-9", "--defer", "Q3", "--words-file", str(words), "--where", "S2 stop", "--by", "person")
        check("K7 hf2-7: --defer without the register hash is the register's refusal", code == 2 and "register hash is missing" in err, err)
        code, out, err = cli("--task", "QA-9", "--defer", "Q3", "--answer", "Q1", "--words", "w")
        check("K7 hf2-7: two operations are refused", code == 2 and "exactly one operation" in err and "--defer" in err, err)
        h1 = next(x["row_hash"] for x in shown["questions"] if x["id"] == "Q1")
        base = ["--where", "gate A", "--by", "person"]
        code, out, err = cli("--task", "QA-9", "--answer", "Q1", "--reading", "a", "--words", "Q1: a", *base, "--register-hash", h1)
        code2, out2, err2 = cli("--task", "QA-9", "--answer", "Q1", "--reading", "b", "--words", "Q1: b", *base, "--register-hash", h1)
        check("H6 hf2-7: the CLI refuses a different answer on a settled question and prints the reopen door with the words by file",
              code == 0 and code2 == 2 and "already settled" in err2 and "--reopen Q1 --words-file <file>" in err2, err2)
        code, out, err = cli("--task", "QA-9", "--reopen", "Q3", "--words", "asked now", *base)
        check_eq("K8 hf2-7: --reopen puts a deferred question back to open",
                 (code, next(x["status"] for x in json.loads(cli("--task", "QA-9", "--show")[1])["questions"] if x["id"] == "Q3")), (0, "open"))
    finally:
        cleanup(proj)


def test_hf2_7_p1_state_exit_row(tmp):
    walk = (SPEC_ROOT / "design" / "state-exits.md").read_text(encoding="utf-8")
    line = next((x for x in walk.splitlines() if x.startswith("| `deferred_to_report`")), "")
    check("K8 hf2-7: design/state-exits.md has a row for deferred_to_report whose exit is `question_register.py ... --reopen <id>`",
          "question_register.py --task <T> --reopen <id>" in line, line[:200])


def test_hf2_7_p1_readiness_rules(tmp):
    import check_witness as CW
    import human_text
    root = f12586_story(tmp / "k10")
    blocked, ready = f12586(verdict="blocked"), f12586(verdict="ready")
    t12b = ("open blocker questions (Q3, Q4, Q5) or blocked aspects with verdict 'ready' - contradiction. "
            "Expected: verdict 'blocked' while a blocker question is still open")
    check_eq("K10 hf2-7: before any answer, `ready` is T12b and `blocked` passes",
             (CW.readiness_rules(ready, root), CW.readiness_rules(blocked, root)), ([t12b], []))
    QR.record_answers(root, WORDS_1, "S2 stop", "person")
    t12a = ("verdict 'blocked' with no open blocker question and no blocked aspect - contradiction: Q3, Q4, Q5 are answered, not needed or "
            "kept open by the person. Expected: verdict 'ready', or a blocked aspect named")
    check_eq("K10 hf2-7: after words 1 (Q3 deferred, Q4 and Q5 answered) `blocked` is T12a and `ready` passes",
             (CW.readiness_rules(blocked, root), CW.readiness_rules(ready, root)), ([t12a], []))
    check_eq("K10 hf2-7: a blocked ASPECT keeps `blocked` legitimate and makes `ready` wrong, answers or not",
             (CW.readiness_rules(dict(blocked, aspects={"a": {"status": "blocked"}}), root),
              CW.readiness_rules(dict(ready, aspects={"a": {"status": "blocked"}}), root)),
             ([], ["open blocker questions (none) or blocked aspects with verdict 'ready' - contradiction. Expected: verdict 'blocked' "
                   "while a blocker question is still open"]))
    moved = dict(ready, open_questions=[dict(r, question="Q5 changed?") if r["id"] == "Q5" else r for r in ready["open_questions"]])
    check_eq("K10b hf2-7: Q5's text changed since its answer -> Q5 is an open blocker again: `ready` is T12b (Q5), `blocked` passes",
             (CW.readiness_rules(moved, root), CW.readiness_rules(dict(moved, verdict="blocked"), root)),
             (["open blocker questions (Q5) or blocked aspects with verdict 'ready' - contradiction. Expected: verdict 'blocked' while a "
               "blocker question is still open"], []))
    full = CW.readiness_check(blocked, root)
    check("K10c hf2-7: readiness_check on F-12586 -> the FORM error of Q4 (no severity) plus the consistency error",
          any(e.startswith("open_questions[3]: needs question, severity") for e in full["errors"]) and t12a in full["errors"]
          and full["not_checked"] == [], str(full))
    sev_root = f12586_story(tmp / "k10c-sev", q4_severity="minor")
    QR.record_answers(sev_root, WORDS_1, "S2 stop", "person")
    only = CW.readiness_check(f12586(q4_severity="minor"), sev_root)
    check_eq("K10c hf2-7: on F-12586-sev only the consistency error remains (T12a names Q3 and Q5)",
             only["errors"], ["verdict 'blocked' with no open blocker question and no blocked aspect - contradiction: Q3, Q5 are answered, "
                              "not needed or kept open by the person. Expected: verdict 'ready', or a blocked aspect named"])
    # main derives the root from the artifact path: work/ -> its parent
    script = str(harness.SCRIPTS / "check_witness.py")
    for verdict, code in (("blocked", 1), ("ready", 0)):
        artifact = sev_root / "work" / "requirements-readiness.json"
        artifact.write_text(json.dumps(f12586(q4_severity="minor", verdict=verdict)), encoding="utf-8")
        run = subprocess.run([sys.executable, "-B", script, str(artifact)], capture_output=True, text=True, encoding="utf-8", cwd=str(tmp))
        check(f"K10c hf2-7: check_witness main on the artifact: verdict {verdict} -> exit {code}",
              run.returncode == code and (("contradiction" in run.stdout) == (code == 1)), run.stdout + run.stderr)
    check_eq("K10 hf2-7: RULES[...] with no root errs only on what needs no answers file (H32)",
             [e for e in CW.RULES["requirements-readiness.json"](f12586(q4_severity="minor")) if "contradiction" in e], [])
    # FR-6: the phrases a person reads from where_words, inside the sentences that carry them (T4, T5, the card suffix)
    sentences = []
    for where in QR.vocabulary()["where"]:
        words = QR.where_words(where)
        sentences += [f"Q3 is kept open until the report, on your word {words}; it is not asked again here.",
                      f"Q3 (kept open on your word {words}; the factory did not guess an answer)",
                      f"Q3 (answered {words})"]
    broke = [(s, [x["rule"] for x in human_text.problems(s, kind="report")]) for s in sentences]
    check_eq("FR-6 hf2-7: human_text.problems(kind=report) finds nothing in the sentences the where_words phrases go into",
             [b for b in broke if b[1]], [])


def test_x2_6_role_questions(tmp):
    """X2-6 (t-1765): a question a role of S1-S4 raises goes into THE register (`open_questions`), idempotent by (dispatch, entry); the
    driver's `--answer ... --by driver --where "stage ran"` closes it from disk; the S4 `--raise --case-file --then` form is untouched."""
    import person_owned
    proj = temp_project("qa-question-register-x26-")
    try:
        use_project(proj)
        task = proj / "qa-factory" / "artifacts" / "QA-9"
        write_story(task, [q("Q1")])
        forms = task / "work" / "handoffs"
        forms.mkdir(parents=True)

        def entry(text="Is the import limit 100 or 1000?", **over):
            base = {"question": text, "read": ["work/requirements-register.md#R-7"], "recommendation": "plan on 100",
                    "options": [{"reading": "100", "if_chosen": "the plan checks 100"}, {"reading": "1000", "if_chosen": "the plan checks 1000"}],
                    "severity": "blocker", "owner_role": "po_ba", "why_person": "requirement_intent"}
            base.update(over)
            return base

        def form(name, *entries):
            """The role's handoff form with its questions[] (flow maps, one per line: the YAML subset of handoff.py)."""
            lines = ["header: {role: qa-requirements-tester, stage: S2, window_or_scope: S2, verdict: concerns}", "questions:"]
            for e in entries:
                lines.append("  - " + json.dumps(e, ensure_ascii=False))
            path = forms / (name + ".yaml")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return path

        classes = person_owned.class_ids()
        check("X2-6 the classes come from person-owned.json `classes[].id`", "requirement_intent" in classes and "access" in classes)
        # the form check: one named edge each
        errors = lambda spec, **kw: QR.role_question_errors(spec, **dict({"stage": "S2", "asked_by": "qa-requirements-tester"}, **kw))
        check_eq("X2-6 a good entry has no problem", errors(entry()), [])
        check_eq("X2-6 why_person null is legal (the conductor settles it)", errors(entry(why_person=None)), [])
        check_in("X2-6 why_person `opinion` -> refused with the classes", "requirement_intent", " ".join(errors(entry(why_person="opinion"))))
        check_in("X2-6 one option -> refused", "options must be 2-5", " ".join(errors(entry(options=[{"reading": "a", "if_chosen": "b"}]))))
        check_eq("X2-6 five options pass, six do not", (errors(entry(options=[{"reading": str(i), "if_chosen": "x"} for i in range(5)])) == [],
                                                       bool(errors(entry(options=[{"reading": str(i), "if_chosen": "x"} for i in range(6)])))), (True, True))
        check_in("X2-6 an empty question -> refused", "question is empty", " ".join(errors(entry(question="  "))))
        check_in("X2-6 a stage outside S1-S4 -> refused", "stage 'S5'", " ".join(errors(entry(), stage="S5")))
        check_in("X2-6 a name that is no role file -> refused", "not a role of the package", " ".join(errors(entry(), asked_by="nobody")))
        check_in("X2-6 an option without if_chosen -> refused", "options[0].if_chosen", " ".join(errors(entry(options=[{"reading": "a"}, {"reading": "b", "if_chosen": "x"}]))))
        check_eq("X2-6 an empty `read` is legal in the form", errors(entry(read=[])), [])

        # raising
        path = form("S2-qa-requirements-tester-1", entry())
        code, out, err = cli("--task", "QA-9", "--raise", "--stage", "S2", "--asked-by", "qa-requirements-tester", "--from-handoff", str(path))
        check_eq("X2-6 --raise --from-handoff exits 0", (code, err), (0, ""))
        view = QR.load(task)
        row = row_of(view, "Q2")
        check_eq("X2-6 one new row after the old one, with asked_by, stage, read, raised_from",
                 (len(view["questions"]), row["asked_by"], row["stage"], row["read"], row["raised_from"], row["why_person"]),
                 (2, "qa-requirements-tester", "S2", ["work/requirements-register.md#R-7"],
                  {"dispatch": "S2-qa-requirements-tester-1", "row": "questions[0]"}, "requirement_intent"))
        check_eq("X2-6 the readings are the options, lettered by position", [r["reading"] for r in row["readings"]], ["100", "1000"])
        check("X2-6 the new row is open and blocking (severity is the role's, not `major`/`minor`)", QR.is_open(row) and QR.open_blocker(row))
        before = snapshot(proj)
        code, out, err = cli("--task", "QA-9", "--raise", "--stage", "S2", "--asked-by", "qa-requirements-tester", "--from-handoff", str(path))
        check_eq("X2-6 the same form again writes nothing (FR-7)", (code, snapshot(proj) == before, len(json.loads(out)["already"])), (0, True, 1))
        form("S2-qa-requirements-tester-1", entry("Is the import limit 50?"))
        before = snapshot(proj)
        code, out, err = cli("--task", "QA-9", "--raise", "--stage", "S2", "--asked-by", "qa-requirements-tester", "--from-handoff", str(path))
        check_eq("X2-6 the same (dispatch, entry) with another text -> refused, nothing written", (code, snapshot(proj) == before), (2, True))
        check_in("X2-6 ... naming both texts", "import limit 100", err)
        check_in("X2-6 ... and the new one", "import limit 50", err)
        bad = form("S2-bad", entry(), entry(why_person="opinion"))
        before = snapshot(proj)
        code, out, err = cli("--task", "QA-9", "--raise", "--stage", "S2", "--asked-by", "qa-requirements-tester", "--from-handoff", str(bad))
        check_eq("X2-6 one bad entry refuses the whole form, nothing written", (code, snapshot(proj) == before), (2, True))
        check_in("X2-6 ... naming the entry", "questions[1]", err)
        empty = form("S2-none")
        before = snapshot(proj)
        code, out, err = cli("--task", "QA-9", "--raise", "--stage", "S2", "--asked-by", "qa-requirements-tester", "--from-handoff", str(empty))
        check_eq("X2-6 a form with no questions raises nothing (declared empty outcome)", (code, json.loads(out)["raised"], snapshot(proj) == before), (0, [], True))
        # a read-less entry is raised with read_missing; two roles asking the same thing are two rows (dedup is the conductor's)
        none_read = form("S3-qa-test-strategist-1", entry("Same words?", read=[]))
        code, out, err = cli("--task", "QA-9", "--raise", "--stage", "S3", "--asked-by", "qa-test-strategist", "--from-handoff", str(none_read))
        row = row_of(QR.load(task), json.loads(out)["raised"][0]["id"])
        check_eq("X2-6 an empty `read` -> the row is raised with read_missing", (code, row.get("read_missing"), row["read"]), (0, True, []))
        twin = form("S3-qa-case-critic-1", entry("Same words?", read=[]))
        code, out, err = cli("--task", "QA-9", "--raise", "--stage", "S3", "--asked-by", "qa-case-critic", "--from-handoff", str(twin))
        check_eq("X2-6 the same question from two roles -> two rows", len([x for x in QR.load(task)["questions"] if x.get("question") == "Same words?"]), 2)
        # S1 is a stage a role may ask in
        s1 = form("S1-qa-scout-1", entry("Which source is meant?"))
        code, out, err = cli("--task", "QA-9", "--raise", "--stage", "S1", "--asked-by", "qa-scout", "--from-handoff", str(s1))
        check_eq("X2-6 a raise from S1 is accepted", code, 0)

        # the driver's form: the path the role sees, relative to the story folder, with the process cwd somewhere else (g10)
        elsewhere = Path(tempfile.mkdtemp(prefix="qa-question-register-g10-cwd-"))
        try:
            rel_env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj), PYTHONDONTWRITEBYTECODE="1")

            def rel_run(handoff):
                return subprocess.run([sys.executable, "-B", str(harness.SCRIPTS / "question_register.py"), "--task", "QA-9", "--raise",
                                       "--stage", "S2", "--asked-by", "qa-case-critic", "--from-handoff", handoff],
                                      capture_output=True, encoding="utf-8", errors="replace", cwd=str(elsewhere), env=rel_env, timeout=120)
            form("S2-qa-case-critic-g10", entry("Is the export limit 10 or 20?"))
            proc = rel_run("work/handoffs/S2-qa-case-critic-g10.yaml")
            check_eq("g10 a task-relative --from-handoff, cwd not the story folder -> exit 0, one question raised",
                     (proc.returncode, len(json.loads(proc.stdout)["raised"]) if proc.returncode == 0 else proc.stderr), (0, 1))
            proc = rel_run("work/handoffs/S2-qa-case-critic-9.yaml")
            check_eq("g10 the same relative path with no such form -> exit 2", proc.returncode, 2)
            check_in("g10 ... the refusal quotes the path as given", "'work/handoffs/S2-qa-case-critic-9.yaml' could not be read", proc.stderr)
            proc = rel_run("  ")
            check_eq("g10 a blank --from-handoff is refused, never read as the cwd", proc.returncode, 2)
        finally:
            shutil.rmtree(elsewhere, ignore_errors=True)

        # the driver closes from disk: --by driver, the source in the words; the closed row is not open
        qid = "Q2"
        shown = row_hash_of(task, qid)
        code, out, err = cli("--task", "QA-9", "--answer", qid, "--reading", "a", "--by", "driver", "--where", "stage ran", "--register-hash", shown,
                             "--words", "work/requirements-register.md#R-7: the limit is 100")
        closed = row_of(QR.load(task), qid)
        check_eq("X2-6 the driver's answer is recorded (by driver, where `stage ran`)", (code, closed["status"], closed["where"], closed["reading"]), (0, "answered", "stage ran", "a"))
        check("X2-6 ... the row is no longer open and its words name the source", not QR.is_open(closed) and "requirements-register.md#R-7" in closed["words"])
        check_eq("X2-6 `stage ran` reads as `while the stage ran` to a person", QR.where_words("stage ran"), "while the stage ran")
        raw = [json.loads(line) for line in (task / "work" / "question-answers.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        check_eq("X2-6 ... the answers file holds by=driver", raw[-1]["by"], "driver")

        # t-1815 F2: the questions come from the CRITIC's form; its contract template is what role_question_errors accepts; a classless question
        # is the conductor's and is never listed to a person at gate A
        import handoff
        import gate_brief
        contracts = Path(QR.__file__).resolve().parent.parent / "handoffs"
        for name in ("s2-stage-critic-to-tester", "s3-stage-critic-to-strategist", "s4-case-critic-to-designer"):
            template = handoff.parse((contracts / f"{name}.yaml").read_text(encoding="utf-8")).data["questions"][0]
            check_eq(f"F2 {name}: the template's severity words are blocker|major|minor, `read` is a list, every option has if_chosen",
                     (template["severity"], isinstance(template["read"], list), all("if_chosen" in o for o in template["options"])),
                     ("<blocker|major|minor>", True, True))
            filled = dict(template, why_person=None, severity="blocker", question="Is it 100?", owner_role="po_ba")
            check_eq(f"F2 {name}: the template, filled in, is raised without a refusal", QR.role_question_errors(
                filled, stage=name[:2].upper(), asked_by="qa-case-critic"), [])
        check_eq("F2: `major` and `minor` do not block, `blocker` does (the words the template offers)",
                 [QR.open_blocker({"severity": s}) for s in ("blocker", "major", "minor")], [True, False, False])
        critic_form = form("S2-qa-case-critic-1", entry("Is the cap per file or per run?", why_person=None, severity="major"),
                           entry("Who owns the import limit?"))
        code, out, err = cli("--task", "QA-9", "--raise", "--stage", "S2", "--asked-by", "qa-case-critic", "--from-handoff", str(critic_form))
        raised = json.loads(out)["raised"]
        check_eq("F2: the critic's form raises its two questions, asked_by the critic", (code, [r["asked_by"] for r in raised]), (0, ["qa-case-critic"] * 2))
        classless, classed = raised[0], raised[1]
        view = QR.load(task)
        check_eq("F2: the classless row is driver-owned, the classed one is not", (QR.driver_owned(row_of(view, classless["id"])),
                                                                                   QR.driver_owned(row_of(view, classed["id"]))), (True, False))
        listed = [str(x.get("id")) for x in gate_brief.unanswered_questions(task, {})]
        check_eq("F2: gate A lists the classed role question and NOT the classless one", (classed["id"] in listed, classless["id"] in listed), (True, False))
        check("F2: ...while the classless row stays in the register, open, for the conductor", QR.is_open(row_of(QR.load(task), classless["id"])))
        check_eq("F2: a readiness question (no asked_by) is never driver-owned; a non-object is not either", (QR.driver_owned(q("Q9")), QR.driver_owned("x")),
                 (False, False))
        empty_critic = form("S2-qa-case-critic-2")
        before = snapshot(proj)
        code, out, err = cli("--task", "QA-9", "--raise", "--stage", "S2", "--asked-by", "qa-case-critic", "--from-handoff", str(empty_critic))
        check_eq("F2: a critic form with an empty questions[] raises nothing and is no error", (code, json.loads(out)["raised"], snapshot(proj) == before), (0, [], True))
        no_text = form("S2-qa-case-critic-3", entry(question="", why_person="requirement_intent"))
        code, out, err = cli("--task", "QA-9", "--raise", "--stage", "S2", "--asked-by", "qa-case-critic", "--from-handoff", str(no_text))
        check_eq("F2: a question with a class and no text -> shape refusal naming the entry", (code, "questions[0]" in err and "question is empty" in err), (2, True))

        # regression: the S4 form is refused with the new flags, and the old form's own refusal text is unchanged
        code, out, err = cli("--task", "QA-9", "--raise", "--case-file", "x.md", "--then", "1", "--question-file", "q.json", "--stage", "S4")
        check_eq("X2-6 --raise --case-file with --stage is refused", code, 2)
        code, out, err = cli("--task", "QA-9", "--raise")
        check_eq("X2-6 the old `--raise` alone keeps its refusal text byte for byte",
                 err, "question_register.py: refused.\n- --raise needs --case-file, --then, --question-file\n")
        code, out, err = cli("--task", "QA-9", "--stage", "S2", "--show")
        check_eq("X2-6 --stage without --raise is refused", code, 2)
    finally:
        cleanup(proj)


def test_placeholder_question_row_dropped(tmp):
    """t-1936 F1 (B-11): a `questions[]` row whose `question` is still the contract's placeholder is the sample, not a question: it is
    not raised and not refused; a real row beside it keeps its own form index in `raised_from`."""
    proj = temp_project("qa-question-register-b11-")
    try:
        use_project(proj)
        task = proj / "qa-factory" / "artifacts" / "QA-9"
        write_story(task, [q("Q1")])
        forms = task / "work" / "handoffs"
        forms.mkdir(parents=True)
        sample = {"question": "<the question, in plain words>", "read": ["<path#anchor the critic read before asking>"],
                  "recommendation": "<what the work goes on with meanwhile>", "options": [], "severity": "<blocker|major|minor>"}
        real = {"question": "Is the import limit 100 or 1000?", "read": ["work/requirements-register.md#R-7"], "recommendation": "plan on 100",
                "options": [{"reading": "100", "if_chosen": "the plan checks 100"}, {"reading": "1000", "if_chosen": "the plan checks 1000"}],
                "severity": "blocker", "owner_role": "po_ba", "why_person": "requirement_intent"}

        def form(name, *entries):
            lines = ["header: {role: qa-case-critic, stage: S2, window_or_scope: S2, verdict: ok}", "questions:"]
            lines += ["  - " + json.dumps(e, ensure_ascii=False) for e in entries]
            path = forms / (name + ".yaml")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return path

        only_sample = form("S2-qa-case-critic-1", sample)
        before = (task / "work" / "requirements-readiness.json").read_bytes()
        result = QR.raise_from_handoff(task, only_sample, stage="S2", asked_by="qa-case-critic")
        check_eq("F1 a form holding only the template row raises nothing and is no refusal",
                 (result["raised"], result["already"], (task / "work" / "requirements-readiness.json").read_bytes() == before), ([], [], True))
        both = form("S2-qa-case-critic-2", sample, real)
        result = QR.raise_from_handoff(task, both, stage="S2", asked_by="qa-case-critic")
        check_eq("F1 beside a real row the template row is dropped and the real one keeps its form index",
                 (len(result["raised"]), result["raised"][0]["raised_from"]), (1, {"dispatch": "S2-qa-case-critic-2", "row": "questions[1]"}))
    finally:
        cleanup(proj)


def test_answers_lock_busy_names_the_holder(tmp=None):
    """TR4-2 part B: the answers lock is the package's one file lock. Busy = the old head + the holder clause (the file is in
    the story's tracked work folder: none recorded); broken = Refused with the LockBroken sentence and the writable door,
    never the busy head."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="qa-answers-lock-") as td:
        root = Path(td) / "story"
        with QR.answers_lock(root):
            try:
                with QR.answers_lock(root, wait=0.1):
                    raise AssertionError("a second writer got the answers lock")
            except QR.Refused as exc:
                text = str(exc)
        assert text.startswith("- another writer has held "), text
        assert "nothing was written. Expected: try again in a moment; no holder recorded - released when that process ends: wait and repeat" in text, text
        assert (root / "work" / QR.LOCK_NAME).read_bytes() == b"0", "no holder is written into the story's work folder"
        folder_root = Path(td) / "other"
        (folder_root / "work" / QR.LOCK_NAME).mkdir(parents=True)
        try:
            with QR.answers_lock(folder_root, wait=0.1):
                raise AssertionError("a folder at the lock path was taken as a lock")
        except QR.Refused as exc:
            text = str(exc)
        assert text.startswith("- ") and "cannot be locked" in text and text.endswith("Expected: the file must be writable"), text
        assert "has held" not in text and "try again in a moment" not in text and "holder" not in text, text


TESTS = [test_answers_lock_busy_names_the_holder, test_placeholder_question_row_dropped, test_x2_6_role_questions,test_g1_13_question_row_keys_never_meet_and_the_readiness_writer_keeps_its_bytes, test_e1_exact_id, test_e2_load, test_e3_answers_file, test_e4_register, test_e5_parser, test_e6_cli,
         test_e6_cli_subprocess, test_e7_battery, test_edge2_fence_and_quote, test_edge3_row_hash, test_edge4_where_by,
         test_edge5_case_decisions, test_edge5_case_cli, test_edge6_words_file, test_edge7_lock, test_edge8_named,
         test_cmp1, test_t256_o6_accept_as_blocked_is_a_whole_line_case_token, test_t256_o4_raise_for_case_is_keyed_by_case_and_then,
         test_hf2_7_p1_vocabulary_and_parser, test_hf2_7_p1_record_answers, test_hf2_7_p1_record_rules,
         test_hf2_7_p1_predicates, test_hf2_7_p1_brief_and_drift, test_hf2_7_p1_cli_defer, test_hf2_7_p1_state_exit_row,
         test_hf2_7_p1_readiness_rules]


def main() -> None:
    tmp = temp_dir("qa-question-register-test-")
    try:
        for test in TESTS:
            test(tmp)
    finally:
        cleanup(tmp)
    finish("question_register")


if __name__ == "__main__":
    main()
