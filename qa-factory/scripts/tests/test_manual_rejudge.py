#!/usr/bin/env python3
"""HF8-19 (N1a): the verdict of a manual check stands on a quote of the text it captured, and a written attempt can be
judged again without running the check again.

Keys of spec r0107-s5b (fixed before the run, quoted from its section 5):
  Q1  `prepare` writes `thens` into request.json, and `then_quotes` into the fields the record must carry.
  Q2  the edge table of N1: every refusal names the Then or the file and a door; one id per input.
  Q3  a quote that IS in the text and contradicts the Then is written: code checks that the words are there, it does
      not read what they mean (FR-12, FR-47).
  Q4  rejudge: `record.json` byte for byte, the finalizer makes the new record current with no
      `ambiguous_attempt_order`, the code sentence and `completion_named_at_rejudge` are in the new record.
  Q7  `--with-attempt` (FB-12): a ui and an api attempt in ONE record, each profile with its own probes; the edges.
  Q8  the quote limit: 300 characters accepted, 301 refused.
(Q5, Q6, Q9 are N1b's: the triage word and the driver.)
The browser and the HTTP client are the fakes of `fixtures/manual-evidence/scaffold.py`.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
import test_manual_capture as TMC  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

import manual_evidence as M  # noqa: E402

MC = S.MC
TMC.AUTO_THEN_FLAGS = False    # the quote rule is what this file tests: no helper adds a quote for it (HF8-19 N1a tests)
CASE = S.CASES["ui"]
OBS = ["OB-7"]
TEXT = "Zoom scale(1.2) applied; the toast says Access denied for this user"
ZOOM = "scale(1.2) applied"
LONG = "".join(chr(97 + i % 26) for i in range(400))        # 400 characters, no whitespace
DOOR = "inconclusive"                                         # every quote refusal names this door beside --then-quote
CYR = "".join(chr(c) for c in (0x41d, 0x435, 0x442))          # three Cyrillic letters, built here: the package source carries none


def quotes(*numbers, words=ZOOM):
    out = []
    for number in numbers:
        out += ["--then-quote", f"{number}={words}"]
    return out


def say(t, *args, command="manual_evidence.py rejudge"):
    with t.patched():
        return S.run(list(args), main=M.main, command=command)


def rejudge(t, *args):
    return say(t, "rejudge", "--task-root", str(t.task), "--case", CASE, *args)


def captured(t, reads=None, attempt=None, steps=None):
    browser = S.FakeBrowser(reads=reads if reads is not None else {TMC.VIEWPORT: TEXT})
    code, out, err, _ = TMC.ui_run(t, steps=steps or TMC.UI_STEPS, browser=browser,
                                   extra=("--attempt", attempt) if attempt else ())
    assert code == 0, err
    return browser


def fresh(**kwargs):
    t = S.make_task(**kwargs)
    TMC.seed_runtime_records(t)
    return t


def built(t, *args, attempt=None):
    return TMC.build(t, CASE, *args, *(("--attempt", attempt) if attempt else ()))


def record_of(t, attempt="a1", name="record.json"):
    return json.loads((t.attempt_dir(CASE, attempt) / name).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def refuses(label, result, *needles):
    code, out, err = result
    check_eq(f"{label}: refused (exit 2)", code, 2)
    for needle in needles:
        check_in(f"{label}: says {needle!r}", needle, err)


# ---------------------------------------------------------------------------------------------------------------------
def q1_prepare_writes_thens():
    t = fresh()
    try:
        with t.patched():
            request = M.prepare_to_file(t.task, CASE, OBS)
        check_eq("Q1: thens are the case's Then clauses by number", sorted(request["thens"]), ["1", "2", "3"])
        check("Q1: ... each with its text", request["thens"]["1"].startswith("P-zoom:") and request["thens"]["3"].startswith("P-pan:"))
        check_in("Q1: the field the record must carry is named before the work", "then_quotes", request["required_actual_fields"])
        check_eq("Q1: request.json holds it", json.loads(M.request_path(t.task, CASE).read_text(encoding="utf-8"))["thens"], request["thens"])
        # a case with no Then: the declared empty outcome, and no quote is asked for
        pinned = next((t.task / "state" / "case-versions" / CASE).glob("*.md"))
        pinned.write_text(pinned.read_text(encoding="utf-8").replace("## Then", "## Notes"), encoding="utf-8")
        with t.patched():
            bare = M.prepare_request(t.task, CASE, OBS)
        check_eq("Q1: a case with no Then has `thens: {}`", bare["thens"], {})
        check_not_in("Q1: ... and is not told to fill `then_quotes`", "then_quotes", bare["required_actual_fields"])
        # a case file that cannot be read is not that outcome: refused, with the door every prepare refusal has
        try:
            M._case_thens(CASE, {"path": str(t.task / "no-such-case.md")})
            check("Q1: an unreadable case file is refused, never `thens: {}`", False)
        except M.Refused as exc:
            check_in("Q1: an unreadable case file is refused with its door", "approved again at gate A", exc.door)
        check_eq("Q1: a case fact with no path at all has no Thens to quote", M._case_thens(CASE, {}), {})
        pinned.write_text("", encoding="utf-8")
        try:
            with t.patched():
                M.prepare_request(t.task, CASE, OBS)
            check("Q1: an emptied case file is refused by prepare, never prepared", False)
        except M.Refused as exc:
            check("Q1: ... with a door", bool(exc.door))
    finally:
        S.cleanup(t)


def q2_edges():
    t = fresh()
    try:
        captured(t)
        pass_args = ["--result", "pass", "--actual", "scale grew", "--masked"]
        # one input per row; the id is the label (spec Q2: every refusal names the Then or the file, and a door)
        rows = (
            ("a pass with no quote at all", pass_args, ["none for Then 1, 2, 3"]),
            ("a pass with a quote for one Then of three", pass_args + quotes(2), ["none for Then 1, 3"]),
            ("a quote of only spaces", pass_args + quotes(1, 2) + ["--then-quote", "3=    "], ["the quote for Then 3 is empty"]),
            ("a number outside the case's Thens", pass_args + quotes(1, 2, 3) + quotes(9), ["Then 9 is not a Then of this case"]),
            ("a Then given twice", pass_args + quotes(1, 1, 2, 3), ["Then 1 is given twice"]),
            ("words the capture does not hold", pass_args + quotes(1, 2) + quotes(3, words="scale(9.9) applied"),
             ["the quote for Then 3 is not in the text this attempt captured", ".txt"]),
            ("the case-sensitive twin of a quote", pass_args + quotes(1, 2) + quotes(3, words="ZOOM SCALE(1.2) APPLIED"),
             ["the quote for Then 3 is not in the text"]),
            ("a flag with no equals sign", pass_args + ["--then-quote", "1"], ["is not <n>=<words>"]),
            ("a number that is not ASCII digits", pass_args + ["--then-quote", "١=x"], ["is not <n>=<words>"]),
            ("a pass that leaves a Then unreached", pass_args + quotes(1, 2) + ["--then-unreached", "3"],
             ["cannot leave a Then unreached"]),
            ("a fail with no quote", ["--result", "fail", "--actual", "x", "--masked"], ["a fail stands on a quote"]),
            ("--then-unreached with words", ["--result", "fail", "--actual", "x", "--masked", "--then-unreached", "1=x"],
             ["not just the number"]),
        )
        for label, args, needles in rows:
            code, out, err = built(t, *args)
            refuses("Q2 " + label, (code, out, err), *needles)
            check_in(f"Q2 {label}: and names a door", DOOR, err)
        check("Q2: every refusal left the attempt unbuilt (nothing written)", not (t.attempt_dir(CASE) / "record.json").exists()
              and not (t.task / "work" / "manual-blocks").exists())
        # an inconclusive asks for no quote (FR-23)
        code, out, err = built(t, "--result", "inconclusive", "--actual", "x", "--masked", "--limitation", "the page never loaded")
        check_eq("Q2: inconclusive needs no quote", code, 0)
        check_not_in("Q2: ... and writes none", "then_quotes", json.dumps(record_of(t)))
    finally:
        S.cleanup(t)
    # a fail: one quote on the Then it failed on, another Then never reached; the rest silent
    t = fresh()
    try:
        captured(t)
        code, out, err = built(t, "--result", "fail", "--actual", "the toast stayed", "--masked", *quotes(1), "--then-unreached", "3")
        check_eq("Q2: a fail with one quote and one unreached Then is written", code, 0)
        entries = record_of(t)["then_quotes"]
        check_eq("Q2: ... the record carries both, by number", [(e["then"], e.get("reached", True)) for e in entries], [(1, True), (3, False)])
        check_eq("Q2: ... the quote names the capture it stands in", (entries[0]["kind"], entries[0]["source"].endswith(".txt")), ("text", True))
        check_eq("Q2: ... and the record validates (the quote is re-read from the file)", M.validate_record(record_of(t), t.task), [])
        # I1 at the validator: a record whose quote is not in its source, or whose source is another file, holds no verdict
        forged = json.loads(json.dumps(record_of(t)))
        forged["then_quotes"][0]["quote"] = "scale(0.1) applied"
        check_in("Q2: a forged quote is refused by validate", "the quote is not in", M.validate_record(forged, t.task))
        forged = json.loads(json.dumps(record_of(t)))
        forged["then_quotes"][0]["source"] = "work/evidence/elsewhere.txt"
        check_in("Q2: a quote whose source is no capture of the record is refused by validate", "its source is not a text capture",
                 M.validate_record(forged, t.task))
        old = json.loads(json.dumps(record_of(t)))
        old.pop("then_quotes")
        check_eq("Q2: a record with no then_quotes (made before HF8-19) is not refused", M.validate_record(old, t.task), [])
    finally:
        S.cleanup(t)
    # a quote of ANOTHER attempt holds nothing (I1)
    t = fresh()
    try:
        captured(t, reads={TMC.VIEWPORT: "alpha-unique words"}, attempt="a1")
        captured(t, reads={TMC.VIEWPORT: "beta words"}, attempt="a2")
        refuses("Q2 a quote that stands only in attempt a1, built as a2",
                built(t, "--result", "pass", "--actual", "x", "--masked", *quotes(1, 2, 3, words="alpha-unique words"), attempt="a2"),
                "the quote for Then 1 is not in the text this attempt captured")
        code, out, err = built(t, "--result", "pass", "--actual", "x", "--masked", *quotes(1, 2, 3, words="beta words"), attempt="a2")
        check_eq("Q2 control: the same flags with a2's own words are written", code, 0)
    finally:
        S.cleanup(t)
    # --then-seen: only a picture
    t = fresh()
    try:
        captured(t)
        code, out, err = built(t, "--result", "pass", "--actual", "x", "--masked", *quotes(1, 2), "--then-seen", "3=the pane shows the new offset")
        check_eq("Q2: --then-seen takes a Then only the picture shows", code, 0)
        entry = [e for e in record_of(t)["then_quotes"] if e["then"] == 3][0]
        image = [r["path"] for r in record_of(t)["evidence_refs"] if r["kind"] == "image" and r["phase"] == "post_action"][-1]
        check_eq("Q2: ... naming a picture of the attempt, kind seen", (entry["kind"], entry["seen_on"]), ("seen", image))
        check_eq("Q2: ... and the record validates", M.validate_record(record_of(t), t.task), [])
    finally:
        S.cleanup(t)
    # old request (no `thens`): the quote rule is silent, the record is written, one line says why
    t = fresh()
    try:
        captured(t)
        with t.patched():
            M.prepare_to_file(t.task, CASE, OBS)
        path = M.request_path(t.task, CASE)
        request = json.loads(path.read_text(encoding="utf-8"))
        request.pop("thens")
        path.write_text(json.dumps(request), encoding="utf-8")
        code, out, err = built(t, "--result", "pass", "--actual", "x", "--masked")
        check_eq("Q2: a request with no `thens` (made before the rule) asks for no quote", code, 0)
        check_in("Q2: ... and the output says so", "no quote was asked for", out)
        check_not_in("Q2: ... limitations are not touched", "quote", json.dumps(record_of(t)["limitations"]))
    finally:
        S.cleanup(t)
    # `thens: {}`: no quote is asked, `--actual` as before; a quote that names a Then of nothing is refused
    t = fresh()
    try:
        captured(t)
        with t.patched():
            M.prepare_to_file(t.task, CASE, OBS)
        path = M.request_path(t.task, CASE)
        request = json.loads(path.read_text(encoding="utf-8"))
        request["thens"] = {}
        path.write_text(json.dumps(request), encoding="utf-8")
        refuses("Q2 a quote for a case that lists no Then", built(t, "--result", "pass", "--actual", "x", "--masked", *quotes(1)),
                "Then 1 is not a Then of this case")
        code, out, err = built(t, "--result", "pass", "--actual", "x", "--masked")
        check_eq("Q2: `thens: {}` asks for no quote", code, 0)
    finally:
        S.cleanup(t)
    quote_units()


def quote_units():
    """The inputs a fake browser cannot make: a file that is not UTF-8, escaped JSON, Unicode spaces, no picture."""
    t = fresh()
    try:
        folder = t.task / "work" / "evidence" / "manual" / "unit"
        folder.mkdir(parents=True)

        def ref(name, data, kind="log", phase="post_action"):
            (folder / name).write_bytes(data)
            return {"path": (folder / name).relative_to(t.task).as_posix(), "kind": kind, "phase": phase}
        request = {"thens": {"1": "a", "2": "b"}}
        latin = ref("latin.txt", b"caf\xe9 is open; the line reads Access denied")
        got, problems = M._then_quote_problems(t.task, request, "pass", [("text", "1=Access denied"), ("text", "2=the line reads")], [latin])
        check_eq("Q2: a file that is not UTF-8 is read with replacement: a quote beside the bad byte is found", problems, [])
        got, problems = M._then_quote_problems(t.task, request, "pass", [("text", "1=café is open"), ("text", "2=Access denied")], [latin])
        check_in("Q2: ... a quote across the bad byte is NOT found (the error goes toward refusing), naming the file",
                 "latin.txt", problems)
        spaced = ref("spaced.txt", b"the   page\n says\tOK now")
        got, problems = M._then_quote_problems(t.task, request, "pass", [("text", "1=the page says OK"), ("text", "2=OK now")], [spaced])
        check_eq("Q2: Unicode spaces and line breaks are one space on both sides", problems, [])
        wrapped = M._then_quote_problems(t.task, request, "inconclusive", [("text", "1=**the page** says")], [spaced])[1]
        check_eq("Q2: a markdown wrapper is part of the words, so it is not found", len(wrapped), 1)
        escaped = ref("escaped.json", json.dumps({"detail": CYR + " access", "n": [1, {"deep": "toast says no"}]}).encode("utf-8"), kind="request_response")
        check_in("Q2 setup: the file really holds the \\u escapes", "\\u041d", escaped and (folder / "escaped.json").read_text(encoding="utf-8"))
        got, problems = M._then_quote_problems(t.task, request, "pass", [("text", f"1={CYR} access"), ("text", "2=toast says no")], [escaped])
        check_eq("Q2: a JSON capture is also read by its parsed string values (\\uXXXX)", problems, [])
        deep = ref("deep.json", ("[" * 3000 + "]" * 3000).encode("utf-8"), kind="request_response")
        got, problems = M._then_quote_problems(t.task, request, "inconclusive", [("text", "1=anything")], [deep])
        check_eq("Q2: a very deep JSON capture is a not-found quote, never a crash", len(problems), 1)
        picture = ref("a.png", b"\x89PNG", kind="image", phase="pre_action")
        got, problems = M._then_quote_problems(t.task, request, "fail", [("seen", "1=the pane moved")], [picture])
        check_in("Q2: --then-seen with no picture after the action refuses", "no picture of the page after the action", problems)
        # the observe/ copy is no capture: it is not in the refs, so it holds nothing
        observe = folder / "observe"
        observe.mkdir()
        (observe / "001-read.txt").write_text("only in observe", encoding="utf-8")
        got, problems = M._then_quote_problems(t.task, request, "inconclusive", [("text", "1=only in observe")], [spaced])
        check_eq("Q2: a words that stand only in an observe/ file is not found", len(problems), 1)
    finally:
        S.cleanup(t)


def q3_code_does_not_judge():
    t = fresh()
    try:
        captured(t)
        # the quote says Access denied; the Thens say the viewport scale changes: the quote is THERE, so it is written
        code, out, err = built(t, "--result", "pass", "--actual", "all as expected", "--masked", *quotes(1, 2, 3, words="the toast says Access denied"))
        check_eq("Q3: a quote that is in the text and contradicts the Then is written (code does not read meaning)", code, 0)
        check_eq("Q3: ... the result is the runner's, unchanged", record_of(t)["result"], "pass")
    finally:
        S.cleanup(t)
    # the answer of the function does not depend on what a Then says, only on the numbers
    t = fresh()
    try:
        folder = t.task / "work" / "evidence"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "x.txt").write_text(TEXT, encoding="utf-8")
        refs = [{"path": "work/evidence/x.txt", "kind": "log", "phase": "post_action"}]
        one = M._then_quote_problems(t.task, {"thens": {"1": "the scale increases"}}, "pass", [("text", "1=Access denied")], refs)
        two = M._then_quote_problems(t.task, {"thens": {"1": "access is denied"}}, "pass", [("text", "1=Access denied")], refs)
        check_eq("Q3: the same quote against opposite Thens gives the same answer", one, two)
    finally:
        S.cleanup(t)


def q8_limit():
    t = fresh()
    try:
        captured(t, reads={TMC.VIEWPORT: LONG})
        args = ["--result", "pass", "--actual", "x", "--masked"]
        refuses("Q8 a quote of 301 characters", built(t, *args, *quotes(1, 2, 3, words=LONG[:301])),
                "is 301 characters: quote at most 300 characters, the shortest part that decides")
        code, out, err = built(t, *args, *quotes(1, 2, 3, words=LONG[:300]))
        check_eq("Q8: a quote of exactly 300 characters is written", code, 0)
        check_eq("Q8: ... the limit is the module's own", M.THEN_QUOTE_MAX, 300)
        forged = json.loads(json.dumps(record_of(t)))
        forged["then_quotes"][0]["quote"] = LONG[:301]
        check_in("Q8: validate holds the same limit", "quote at most 300 characters", M.validate_record(forged, t.task))
    finally:
        S.cleanup(t)


def q4_rejudge():
    import finalize_task as FT
    t = fresh()
    try:
        captured(t)
        code, out, err = built(t, "--result", "fail", "--actual", "refused move shows only a toast", "--masked", *quotes(1), "--then-unreached", "2",
                               "--then-unreached", "3")
        check_eq("Q4 setup: the first verdict, a fail, is written", code, 0)
        first = t.attempt_dir(CASE) / "record.json"
        before_bytes, before_hash = first.read_bytes(), sha(first)
        base = record_of(t)
        code, out, err = rejudge(t, "--of-attempt", "a1", "--result", "pass", "--actual", "the viewport scale grew", "--masked", *quotes(1, 2, 3),
                                 "--reason", "the captured text says the zoom applied")
        check_eq("Q4: rejudge of a written attempt is written", code, 0)
        done = json.loads(out)
        check_eq("Q4: ... as a1-r1 of a1", (done["attempt"], done["of_attempt"], done["rejudged"]), ("a1-r1", "a1", True))
        check_eq("Q4: record.json is byte for byte what it was", (first.read_bytes() == before_bytes, sha(first) == before_hash), (True, True))
        new = record_of(t, name="rejudge-1.json")
        for key in ("evidence_refs", "runtime_before", "runtime_after", "steps_actual", "expected", "obligation_hashes", "runtime_identity",
                    "case_version", "approved_policy_hash"):
            check_eq(f"Q4: {key} is copied unchanged", new[key], base[key])
        check_eq("Q4: the result, the actual and the quotes are the new reading", (new["result"], new["actual"], [e["then"] for e in new["then_quotes"]]),
                 ("pass", "the viewport scale grew", [1, 2, 3]))
        check_eq("Q4: it says what it re-judges and why", (new["rejudge_of"], new["rejudge_reason"], new["attempt_id"]),
                 ("a1", "the captured text says the zoom applied", "a1-r1"))
        sentence = M.rejudge_sentence("a1", "the captured text says the zoom applied")
        check_in("Q4: the code sentence is in limitations", sentence, new["limitations"])
        check("Q4: ... and it says the check was not run again", "the check was not run again" in sentence and sentence.startswith("re-judged from the captures of attempt a1"))
        check("Q4: it starts now, strictly after the original attempt (the reducer orders by it)", new["attempt_started_at"] > base["attempt_ended_at"]
              and new["attempt_started_at"] == new["attempt_ended_at"])
        check_eq("Q4: the new record validates as any record does", M.validate_record(new, t.task), [])
        with t.patched():
            report, _triage = FT.reduce(t.task)
        current = report["current_manual_checks"]
        check_eq("Q4: the finalizer reduces two records to ONE current: the re-judged one", [(r["attempt_id"], r["result"]) for r in current], [("a1-r1", "pass")])
        check_eq("Q4: ... with the order known, not `ambiguous_attempt_order`", (report["attempt_order"], [f["code"] for f in report["factory_findings"]]),
                 ("ordered_by_attempt_started_at", []))
        check_eq("Q4: ... and both records stay in the history", len(report["manual_checks"]), 2)
        # a re-judge of a re-judge: a1-r2, still of a1; the same result is legal
        code, out, err = rejudge(t, "--of-attempt", "a1", "--result", "pass", "--actual", "same again", "--masked", *quotes(1, 2, 3), "--reason", "a second look")
        check_eq("Q4: a second re-judge of the same attempt, with the same result, is written", (code, json.loads(out)["attempt"]), (0, "a1-r2"))
        check_eq("Q4: ... and is of a1 too", record_of(t, name="rejudge-2.json")["rejudge_of"], "a1")
        with t.patched():
            report, _triage = FT.reduce(t.task)
        check_eq("Q4: the latest re-judge is the current one", [r["attempt_id"] for r in report["current_manual_checks"]], ["a1-r2"])
        check_eq("Q4: ... and record.json is still unchanged", sha(first), before_hash)
    finally:
        S.cleanup(t)
    rejudge_edges()
    rejudge_completion()


def rejudge_edges():
    t = fresh()
    try:
        captured(t)
        built(t, "--result", "fail", "--actual", "x", "--masked", *quotes(1))
        ok = ["--result", "pass", "--actual", "y", "--masked", *quotes(1, 2, 3), "--reason", "r"]
        refuses("Q4 edge: --reason missing", rejudge(t, "--of-attempt", "a1", "--result", "pass", "--actual", "y", "--masked"), "--reason missing")
        refuses("Q4 edge: an attempt that was never captured", rejudge(t, "--of-attempt", "a7", *ok), "attempt a7", "nothing to judge again")
        refuses("Q4 edge: a path as the attempt", rejudge(t, "--of-attempt", "../a1", *ok), "is not an attempt name")
        captured(t, attempt="a2")
        refuses("Q4 edge: an attempt that is still open", rejudge(t, "--of-attempt", "a2", *ok), "no record yet", "build")
        blocked = MC.case_root(t.task, CASE) / "a3"
        blocked.mkdir()
        (blocked / "env_blocked.json").write_text(json.dumps({"probe_line": "stand unknown", "remedy": "x"}), encoding="utf-8")
        refuses("Q4 edge: an env_blocked attempt", rejudge(t, "--of-attempt", "a3", *ok), "no record (the stand could not be verified)", "new attempt")
        refuses("Q4 edge: a quote the capture does not hold", rejudge(t, "--of-attempt", "a1", *ok[:5], "--then-quote", "3=not there", "--reason", "r"),
                "the quote for Then 3 is not in the text")
        refuses("Q4 edge: a pass with a Then unquoted", rejudge(t, "--of-attempt", "a1", "--result", "pass", "--actual", "y", "--masked", *quotes(1),
                                                                 "--reason", "r"), "none for Then 2, 3")
        # no S6 dispatch running: nothing to bind a record to (AR-25: the refusal names who opens it)
        t.state(dispatch_status="accepted")
        refuses("Q4 edge: no open S6 dispatch", rejudge(t, "--of-attempt", "a1", *ok), "no S6 dispatch is running")
        # a stale revision: validate_manual_current refuses, the door is a new attempt
        t.state()
        S.FakeController.STATE["source_revision"] = "src-2"
        refuses("Q4 edge: the source revision moved", rejudge(t, "--of-attempt", "a1", *ok), "source revision unknown or stale", "new attempt")
        t.state()
        check("Q4 edge: none of the refusals wrote a record", not list(t.attempt_dir(CASE).glob("rejudge-*.json")))
        # I1/I6: a file changed since the build holds no verdict, and nothing is written
        image = next(r["path"] for r in record_of(t)["evidence_refs"] if r["kind"] == "image")
        (t.task / image).write_bytes(b"tampered")
        refuses("Q4 edge: a changed evidence file", rejudge(t, "--of-attempt", "a1", *ok), "evidence hash mismatch")
        check("Q4 edge: ... no new record", not list(t.attempt_dir(CASE).glob("rejudge-*.json")))
    finally:
        S.cleanup(t)


def rejudge_completion():
    t = fresh()
    try:
        steps = f"goto {TMC.UI}\ncapture pre_action initial\nread {TMC.VIEWPORT} style=transform\ncapture post_action final\n"
        captured(t, steps=steps)
        code, out, err = built(t, "--result", "fail", "--actual", "x", "--masked", *quotes(1))
        check_eq("Q4 setup: an attempt that never proved the completion is built as a fail", code, 0)
        base = record_of(t)
        ok = ["--result", "pass", "--actual", "y", "--masked", *quotes(1, 2, 3), "--reason", "the page did load"]
        refuses("Q4 edge: a pass whose attempt proved no completion", rejudge(t, "--of-attempt", "a1", *ok),
                "pass requires post_action evidence proving completion", "--completion")
        post = next(r["path"] for r in base["evidence_refs"] if r["phase"] == "post_action" and r["kind"] == "image")
        supporting = next(r["path"] for r in base["evidence_refs"] if r["phase"] == "supporting")
        refuses("Q4 edge: --completion on a supporting capture", rejudge(t, "--of-attempt", "a1", *ok, "--completion", supporting), "supporting")
        refuses("Q4 edge: --completion on a path that is no evidence of the attempt", rejudge(t, "--of-attempt", "a1", *ok, "--completion", "work/evidence/x.png"),
                "is no evidence file of that attempt")
        code, out, err = rejudge(t, "--of-attempt", "a1", *ok, "--completion", post)
        check_eq("Q4: --completion names the post_action capture, and the pass is written", code, 0)
        new = record_of(t, name="rejudge-1.json")
        named = [r for r in new["evidence_refs"] if r.get("completion_named_at_rejudge")]
        check_eq("Q4: exactly one ref carries `completion_named_at_rejudge`, and it is the one named", [r["path"] for r in named], [post])
        check_in("Q4: ... with completion in its proves", "completion", named[0]["proves"])
        check_eq("Q4: the original record.json is untouched by it", [r.get("proves") for r in record_of(t)["evidence_refs"] if r["path"] == post],
                 [r["proves"] for r in base["evidence_refs"] if r["path"] == post])
    finally:
        S.cleanup(t)


def q7_with_attempt():
    url = f"{TMC.LOCAL}/v1/workflows/w1"
    routes = {("GET", url): S.ok_json({"id": "w1", "name": "flow"}),
              ("POST", f"{TMC.LOCAL}/v1/local-auth/login"): S.ok_json({"access_token": S.TOKEN})}
    t = fresh()
    try:
        captured(t)
        code, out, err = TMC.http_run(t, S.FakeHttp(routes), "--method", "GET", "--url", url, "--state-url", url, "--phase", "post_action", case=CASE)
        check_eq("Q7 setup: the api call opens its own attempt (one attempt, one profile)", code, 0)
        check_eq("Q7 setup: two attempts", MC.attempts_of(MC.case_root(t.task, CASE)), ["a1", "a2"])
        refuses("Q7 edge: the attempt named is the main one", built(t, "--result", "pass", "--actual", "x", "--masked", *quotes(1, 2, 3), "--with-attempt", "a1", attempt="a1"),
                "is the attempt")
        refuses("Q7 edge: an attempt that has no files", built(t, "--result", "pass", "--actual", "x", "--masked", *quotes(1, 2, 3), "--with-attempt", "a8", attempt="a1"),
                "has no captured files")
        code, out, err = built(t, "--result", "pass", "--actual", "the page and the read agree", "--masked", *quotes(1, 2, 3), "--with-attempt", "a2", attempt="a1")
        check_eq("Q7: a ui attempt and an api attempt are ONE record", code, 0)
        record = record_of(t, "a1")
        check_eq("Q7: ... the record names the other profile's attempt, with its own probes and steps",
                 [(p["attempt"], p["runtime_before"]["profile_id"], p["runtime_after"]["profile_id"], bool(p["steps_actual"])) for p in record["other_profiles"]],
                 [("a2", "api", "api", True)])
        check_eq("Q7: ... the main stand stays the ui one", record["runtime_before"]["profile_id"], "e2e-ui")
        paths = [r["path"] for r in record["evidence_refs"]]
        check("Q7: ... the evidence is the union of both attempts", any("/a1/" in p for p in paths) and any("/a2/" in p for p in paths))
        check_eq("Q7: the joined attempt is written, as a part of the main one", record_of(t, "a2"), {"part_of": "a1"})
        check_eq("Q7: ... so attempt_state reads it as written", MC.attempt_state(t.attempt_dir(CASE, "a2")), "written")
        check_eq("Q7: the record validates", M.validate_record(record, t.task), [])
        with t.patched():
            from coverage_contract import validate_manual_current
            check_eq("Q7: ... and the controller-side check accepts it", validate_manual_current(t.task, record), [])
        refuses("Q7 edge: a joined attempt that is already written", built(t, "--result", "pass", "--actual", "x", "--masked", *quotes(1, 2, 3), "--with-attempt", "a2", attempt="a1"),
                "already written")
        # the provenance rules of the record's own pair hold for each joined pair (the validator, one function)
        for label, mutate, needle in (
                ("a joined pair whose probe is not matched", lambda r: r["other_profiles"][0]["runtime_after"].update(result="mismatched", observed_runtime_identity="build-1"),
                 "other_profiles[0]"),
                ("a joined pair whose identity moved between its probes", lambda r: r["other_profiles"][0]["runtime_after"].update(observed_runtime_identity="build-2"),
                 "runtime provenance changed during the attempt"),
                ("a joined pair on another expected revision", lambda r: [r["other_profiles"][0][k].update(expected_source_revision="deadbeef") for k in ("runtime_before", "runtime_after")],
                 "another expected_source_revision"),
                ("a joined pair of the main profile again", lambda r: [r["other_profiles"][0][k].update(profile_id="e2e-ui") for k in ("runtime_before", "runtime_after")],
                 "one attempt per profile"),
                ("a joined pair with no steps", lambda r: r["other_profiles"][0].update(steps_actual=[]), "steps_actual must be a nonempty")):
            changed = json.loads(json.dumps(record))
            mutate(changed)
            check_in(f"Q7 validate: {label} is refused", needle, M.validate_record(changed, t.task))
        check_in("Q7 validate: other_profiles that is not a list is refused", "other_profiles must be a nonempty array",
                 M.validate_record(dict(record, other_profiles="x"), t.task))
    finally:
        S.cleanup(t)
    # the profile rule stays: a second attempt of the SAME profile cannot join, and another revision is refused
    t = fresh()
    try:
        captured(t, attempt="a1")
        captured(t, attempt="a2")
        refuses("Q7 edge: a second attempt of the same profile", built(t, "--result", "pass", "--actual", "x", "--masked", *quotes(1, 2, 3), "--with-attempt", "a2", attempt="a1"),
                "holds the stand profile e2e-ui", "ANOTHER profile")
    finally:
        S.cleanup(t)
    t = fresh()
    try:
        captured(t)
        moved = lambda spec: dict(S.probe("api" if spec["argv"] == ["probe-api"] else "e2e-ui"), expected_source_revision="0" * 40,
                                  provenance={"technical_verification": True, "source_linkage": "exact", "deployed_source_revision": "0" * 40})
        TMC.patch_backends(http=S.FakeHttp(routes), probes=moved)
        code, out, err = S.run(["http", "--task-root", str(t.task), "--case", CASE, "--method", "GET", "--url", url])
        check_eq("Q7 setup: the api attempt was probed on another checkout", code, 0)
        refuses("Q7 edge: another expected source revision", built(t, "--result", "pass", "--actual", "x", "--masked", *quotes(1, 2, 3), "--with-attempt", "a2", attempt="a1"),
                "another expected source revision")
        check("Q7 edge: ... nothing was written, the joined attempt is still open", MC.attempt_state(t.attempt_dir(CASE, "a2")) == "open"
              and not (t.attempt_dir(CASE, "a1") / "record.json").exists())
    finally:
        S.cleanup(t)


def fix_round_inconclusive():
    """F3: `rejudge --result inconclusive` keeps the role's `--limitation`; without one it is refused, naming the flag."""
    t = fresh()
    try:
        captured(t)
        built(t, "--result", "fail", "--actual", "x", "--masked", *quotes(1))
        base = ["--of-attempt", "a1", "--result", "inconclusive", "--actual", "x", "--reason", "r1"]
        refuses("F3: an inconclusive re-judge with no --limitation", rejudge(t, *base), "--limitation")
        check("F3: ... nothing was written", not list(t.attempt_dir(CASE).glob("rejudge-*.json")))
        words = "THE-ROLE-WORDS the stand died"
        code, out, err = rejudge(t, *base, "--limitation", words)
        check_eq("F3: an inconclusive re-judge that says what stopped the check is written", code, 0)
        kept = record_of(t, name="rejudge-1.json")["limitations"]
        check_in("F3: the role's words are in limitations, whole", words, kept)
        check_in("F3: ... beside the code sentence, which is not them", M.rejudge_sentence("a1", "r1"), kept)
    finally:
        S.cleanup(t)


def fix_round_older_attempt():
    """F4: a re-judge of an OLDER attempt never takes the place of a newer run."""
    t = fresh()
    try:
        captured(t)
        built(t, "--result", "fail", "--actual", "x", "--masked", *quotes(1))
        captured(t, attempt="a2")
        built(t, "--result", "fail", "--actual", "newer", "--masked", *quotes(1), attempt="a2")
        ok = ["--result", "pass", "--actual", "y", "--masked", *quotes(1, 2, 3), "--reason", "r"]
        refuses("F4: re-judging a1 while a2 has its own record", rejudge(t, "--of-attempt", "a1", *ok), "attempt a2", "later run",
                "--of-attempt a2")
        check("F4: ... nothing was written", not list(t.attempt_dir(CASE).glob("rejudge-*.json")))
        code, out, err = rejudge(t, "--of-attempt", "a2", *ok)
        check_eq("F4: the newer attempt itself is re-judged", (code, json.loads(out)["attempt"]), (0, "a2-r1"))
    finally:
        S.cleanup(t)


def fix_round_write_block():
    """F5: `write-block` applies the same Then coverage rule as `build` when the case's request lists Thens."""
    t = fresh()
    try:
        captured(t)
        code, out, err = built(t, "--result", "pass", "--actual", "x", "--masked", *quotes(1, 2, 3))
        check_eq("F5 setup: a built pass is written", code, 0)
        record = record_of(t)

        def block(rec):
            path = t.task / "hand-record.json"
            path.write_text(json.dumps([rec]), encoding="utf-8")
            return say(t, "write-block", "--task-root", str(t.task), "--input", str(path), command="manual_evidence.py write-block")

        code, out, err = block(record)
        check_eq("F5: the record with its quotes is written by hand", code, 0)
        bare = {k: v for k, v in record.items() if k != "then_quotes"}
        refuses("F5: the same record with no then_quotes", block(bare), "none for Then 1, 2, 3", "--then-quote")
        partial = dict(record, then_quotes=record["then_quotes"][:1])
        refuses("F5: ... with a quote for one Then of three", block(partial), "none for Then 2, 3")
        inconclusive = dict(bare, result="inconclusive", limitations=["the stand died"])
        code, out, err = block(inconclusive)
        check_eq("F5: an inconclusive needs no quote", code, 0)
    finally:
        S.cleanup(t)


def fix_round_rejudge_observations():
    """t-1747 F6: `rejudge --observations-file` uses the file (replaces the base's list, validated) and a command that does not read
    it refuses it - the flag is never dropped without a word."""
    t = fresh()
    try:
        captured(t)
        code, out, err = built(t, "--result", "pass", "--actual", "x", "--masked", *quotes(1, 2, 3))
        check_eq("F6 setup: the first verdict is written, no observation", (code, record_of(t).get("observations")), (0, []))
        refs = [r["path"] for r in record_of(t)["evidence_refs"] if Path(r["path"]).suffix.lower() in M.QUOTE_SUFFIXES]
        path = t.task / "obs.json"
        entry = {"step": 1, "expected": "the zoom applies", "seen": "the toast says Access denied", "evidence": refs[0],
                 "quote": "Access denied"}
        path.write_text(json.dumps([entry]), encoding="utf-8")
        args = ("--of-attempt", "a1", "--result", "pass", "--actual", "again", "--masked", *quotes(1, 2, 3),
                "--reason", "a doubt found while re-judging")
        code, out, err = rejudge(t, *args, "--observations-file", str(path))
        check_eq("F6: a re-judge with an observations file is written", code, 0)
        check_eq("F6: and the new record CARRIES the runner's observation (it was dropped before)",
                 record_of(t, name="rejudge-1.json").get("observations"), [entry])
        path.write_text(json.dumps([dict(entry, quote="not on the page at all")]), encoding="utf-8")
        refuses("F6 BEYOND: a quote that is not in the capture is refused by the same rule as build", rejudge(t, *args, "--observations-file", str(path)),
                "the quote of observations[0] is not in")
        check("F6: ... and nothing was written for it", not (t.attempt_dir(CASE, "a1") / "rejudge-2.json").exists())
        path.write_text("[]", encoding="utf-8")
        code, out, err = rejudge(t, *args, "--observations-file", str(path))
        check_eq("F6 AT: `[]` given is a list too and replaces", (code, record_of(t, name="rejudge-2.json").get("observations")), (0, []))
        code, out, err = say(t, "validate", "--task-root", str(t.task), "--input", str(path), "--observations-file", str(path),
                             command="manual_evidence.py validate")
        check_eq("F6: a command that does not read the flag refuses it (exit 2)", code, 2)
        check_in("F6: and says which commands do", "build, rejudge, write-block", out + err)
    finally:
        S.cleanup(t)


def main():
    fix_round_rejudge_observations()
    fix_round_inconclusive()
    fix_round_older_attempt()
    fix_round_write_block()
    q1_prepare_writes_thens()
    q2_edges()
    q3_code_does_not_judge()
    q8_limit()
    q4_rejudge()
    q7_with_attempt()
    finish("test_manual_rejudge")


if __name__ == "__main__":
    main()
