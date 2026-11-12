#!/usr/bin/env python3
"""t-1765 X8-3: a `surprise` line of the recorder reaches the analyst - the record carries it, the triage lists it as a target, and
code judges only shape and citation (AR-22, AR-27, AR-29); whether a surprise is a bug is the analyst's call.

Keys (fixed before the run, quoted from the DoD of node X8-3):
  C1 the record carries every surprise line (no project rule hides one) and `surprise_detection`, and no retired `surprises_ignored`
  C2 `<case>#sur-<id>` is in `observations`; a surprise CITED by an observation (`"surprise": "<id>"`) is not a target of its own
  C3 `NO_DEFECT` on a `#sur` target with a quote from THAT line passes; a word from another line of the same file is refused, naming the line
  C4 an unanswered `#sur` target holds delivery (`triage_failures` lists it as a failure of the kind `observation`)
  C5 an attempt without `surprises.jsonl` -> `surprise_detection: absent`, no targets, no refusal
  C6 `--with-attempt` and `rejudge` carry the fields through (a line an older recorder marked `ignored` is listed; a base's `surprises_ignored` is dropped); an id of an attempt the record does not hold is refused with the door
  C7 30 is the cap of TARGETS: exactly 30 uncited -> 30 targets, no overflow; 31 -> 30 + `#sur-overflow`
  C8 the row of `current_manual_checks` carries `surprises` through the reduce (read by the contract reader `triage_failures`)
Kill map (builder-rules 7a): dropping `**carried` from the record kills C1; counting a cited line as a target kills C2; reading the
evidence file for a `#sur` quote kills C3; a cap of 31 or 29 kills C7; `rejudge` recounting kills C6; a write-block that trusts the
role's own `surprises` kills the write-block case.
"""
import copy
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
from harness import GOOD, check, check_eq, check_in, check_not_in, finish  # noqa: E402
import test_manual_capture as TMC  # noqa: E402
import test_manual_surprise as TS  # noqa: E402

import contract as C  # noqa: E402
import manual_evidence as M  # noqa: E402

MC = S.MC
CASE = S.CASES["ui"]
STEPS = f'goto {TS.PAGE}\ncapture pre_action initial\nclick "#a"\ncapture post_action completion\n'
PASS = ("--result", "pass", "--actual", "x", "--masked")


def fresh():
    t = S.make_task()
    TMC.seed_runtime_records(t)
    return t


def boom(*numbers):
    return [TS.ev("pageerror", text=f"boom {n}") for n in numbers]


def go(t, born=None, extra=()):
    code, out, err, _ = TMC.ui_run(t, STEPS, TS.EventBrowser(born={("click", "#a"): born or []}), extra=extra)
    assert code == 0, err
    return json.loads(out)


def folder(t, attempt="a1"):
    return t.attempt_dir(CASE, attempt)


def lines_of(t, attempt="a1"):
    return [r for r in TMC.jsonl(folder(t, attempt) / "surprises.jsonl") if r["line"] == "surprise"]


def evidence_of(t, attempt="a1"):
    return next(c["path"] for c in TMC.jsonl(folder(t, attempt) / "captures.jsonl") if "surprises" in c["proves"])


def record_of(t, attempt="a1", name="record.json"):
    return json.loads((folder(t, attempt) / name).read_text(encoding="utf-8"))


def cite(t, number, *, ident=None, **over):
    """An observation that cites the surprise line `number` of attempt a1 (its evidence is the surprises capture)."""
    row = lines_of(t)[number - 1]
    entry = {"step": row["step"], "expected": "no page error", "seen": row["fact"], "evidence": evidence_of(t),
             "quote": row["fact"], "surprise": ident or row["id"]}
    entry.update(over)
    return entry


def build(t, observations=None, *args, attempt=None):
    extra = list(args) + (["--attempt", attempt] if attempt else [])
    if observations is not None:
        path = t.task / "obs.json"
        path.write_text(json.dumps(observations), encoding="utf-8")
        extra += ["--observations-file", str(path)]
    return TMC.build(t, CASE, *PASS, *extra)


def report_of(record):
    return {"current_manual_checks": [record]}


def targets(record):
    return C.triage_targets(report_of(record))["observations"]


def sur(n):
    return f"{CASE}#sur-a1-ui-S{n}"


# ---------------------------------------------------------------------------------------------------------------------
def c1_c2_c3_c4_one_recorded_attempt():
    t = fresh()
    try:
        go(t, boom(1, 2, 3))
        check_eq("setup: the recorder wrote three lines", [r["id"] for r in lines_of(t)], ["a1-ui-S1", "a1-ui-S2", "a1-ui-S3"])
        # the citation edges first: nothing is written by a refused build
        for label, bad, needle in (("an id no line holds", cite(t, 1, ident="a1-ui-S9"), "is no surprise line of a1"),
                                   ("an id of an attempt the record does not hold", cite(t, 1, ident="a2-ui-S1"), "--with-attempt a2"),
                                   ("an empty id", cite(t, 1, ident=" "), "must be the id of a surprise line"),
                                   ("a number for an id", cite(t, 1, ident=2), "must be the id of a surprise line")):
            code, out, err = build(t, [bad])
            check_eq(f"C2 edge: {label} is refused (exit 2)", code, 2)
            check_in(f"C2 edge: ... saying {needle!r}", needle, err)
        check("C2 edge: ... and nothing was written", not (folder(t) / "record.json").exists())
        code, out, err = build(t, [cite(t, 2)])
        check_eq("C2: a cited line passes", code, 0)
        record = record_of(t)
        check_eq("C1: the record carries every line", [s["id"] for s in record["surprises"]],
                 ["a1-ui-S1", "a1-ui-S2", "a1-ui-S3"])
        check_eq("C1: ... each with step, kind, fact and the capture that holds the line",
                 [(s["step"], s["kind"], s["fact"], s["evidence"]) for s in record["surprises"]],
                 [(r["step"], r["kind"], r["fact"], evidence_of(t)) for r in lines_of(t)])
        check_eq("C1: ... no retired count, and the detection", ("surprises_ignored" in record, record["surprise_detection"]), (False, "on"))
        check_eq("C1: the record validates", M.validate_record(record, t.task), [])
        got = targets(record)
        check_eq("C2: the uncited lines are targets, the cited one is not (its observation is)", got,
                 {f"{CASE}#obs1", sur(1), sur(3)})
        check_not_in("C2: ... the cited line has no target of its own", "S2", "\n".join(sorted(got)))
        check_eq("C2 control: the same record with no citation lists all three",
                 targets(dict(record, observations=[])), {sur(1), sur(2), sur(3)})
        check_eq("C2 BEYOND: citing an id the record does not hold cites nothing",
                 targets(dict(record, observations=[dict(record["observations"][0], surprise="zz")])), {f"{CASE}#obs1", sur(1), sur(2), sur(3)})
        check_eq("C2: target_parts reads each name", [C.target_parts(n) for n in (sur(1), f"{CASE}#obs12", f"{CASE}#sur-overflow")],
                 [(CASE, "sur", "a1-ui-S1"), (CASE, "obs", 12), (CASE, "sur-overflow", "")])
        check_eq("C2 control: a name that is no target", [C.target_parts(n) for n in (f"{CASE}#obs0", f"{CASE}#sur-x", CASE, None, 5)],
                 [None] * 5)
        # C3
        report = report_of(record)
        line1, line3 = lines_of(t)[0]["fact"], lines_of(t)[2]["fact"]

        def verdict(name, reason, rep=report):
            return C.triage_no_defect_problems({"instance_id": name, "verdict": "NO_DEFECT", "reason": reason}, rep)
        check_eq("C3: a quote from THAT line passes", verdict(sur(1), f'the page threw "{line1}" on purpose'), [])
        bad = verdict(sur(1), f'the page threw "{line3}"')
        check_eq("C3: a word from another line of the same file is refused", len(bad), 1)
        check_in("C3: ... naming the target and its line", sur(1), bad)
        check_in("C3: ... and the line", "surprise: a1-ui-S1 step", bad)
        check_eq("C3 BEYOND: a word of the SAME file's capture that is not in the line is refused too",
                 len(verdict(sur(1), 'it says "' + MC_FILE_WORD(t) + '"')), 1)
        check_eq("C3: the form rules of the verdict hold on a #sur target (no quote)", len(verdict(sur(1), "looks fine")), 1)
        check_eq("C3: a Then verdict is not judged here", C.triage_no_defect_problems({"instance_id": sur(1), "verdict": "APP_BUG"}, report), [])
        mixed = C.triage_no_defect_problems({"instance_id": sur(1), "test": "a.ts::red", "verdict": "NO_DEFECT",
                                             "reason": f'"{line1}"'}, report)
        check_in("C3: a row that also names a red test is refused", "and nothing else", mixed)
        # C4
        failures, notes = C.triage_failures(report)
        check_eq("C4: each target is a failure of the kind `observation`, in the order the recorder wrote them",
                 [k for k in failures], [("observation", f"{CASE}#obs1"), ("observation", sur(1)), ("observation", sur(3))])
        bound = C.bind_triage(failures, [{"instance_id": sur(1), "verdict": "NO_DEFECT"}])["matched"]
        check_eq("C4: unanswered ones have no row, the answered one has", [len(bound[k]) for k in failures], [0, 1, 0])
        check_eq("C4 control: a record with no surprise lists no #sur failure",
                 [k for k in C.triage_failures(report_of(dict(record, surprises=[])))[0]], [("observation", f"{CASE}#obs1")])
        # the observation entry the quote is judged against
        entry = C.observation_entry(report, sur(3))
        check_eq("C3: the entry of a #sur target has the fact as `seen`, no evidence, the line as the quote",
                 (entry["expected"], entry["seen"], entry["evidence"], entry["quote"]),
                 ("", line3, "", C.surprise_line(record["surprises"][2])))
        check_eq("C3 control: the cited line has no entry as a target", C.observation_entry(report, sur(2)), None)
        check_eq("word: the entry carries the recorder's word and its quote is the recorder's line verbatim",
                 (record["surprises"][2]["word"], entry["quote"]), (lines_of(t)[2]["word"], MC._surprise_line(lines_of(t)[2])))
        full = MC._surprise_line(lines_of(t)[0])
        check_eq("word: a quote of the whole line (with the word) passes", verdict(sur(1), f'the line "{full}"'), [])
        old = copy.deepcopy(record)
        for one in old["surprises"]:
            del one["word"]
        check_eq("word: a record built before `word` still quotes the line without it",
                 C.triage_no_defect_problems({"instance_id": sur(1), "verdict": "NO_DEFECT",
                                              "reason": f'"surprise: a1-ui-S1 step {lines_of(t)[0]["step"]}"'}, report_of(old)), [])
        # C4 at the delivery check: an unanswered #sur holds it, the answer opens it, a wrong quote does not
        import check_delivery as D
        art = t.task.parent / "good-art"
        shutil.copytree(GOOD, art)
        rp, tp = art / "work" / "run-report.json", art / "work" / "triage.json"
        rep = json.loads(rp.read_text(encoding="utf-8"))
        check_eq("C4 setup: the good set has no reason", D.triage_reasons(art), [])
        rep["manual_checks"][0]["surprises"] = [{"id": "a1-ui-S1", "step": 1, "kind": "console", "fact": "pageerror: boom 1", "evidence": ""}]
        rp.write_text(json.dumps(rep), encoding="utf-8")
        name = f"{rep['manual_checks'][0]['case']}#sur-a1-ui-S1"
        check_in("C4: the delivery check names the unanswered surprise", f"the observation {name} of a manual check has no verdict",
                 "\n".join(D.triage_reasons(art)))

        def judge(reason):
            tp.write_text(json.dumps({"triage": [{"instance_id": name, "verdict": "NO_DEFECT", "reason": reason}]}), encoding="utf-8")
            return "\n".join(D.triage_reasons(art))
        check_eq("C4: a NO_DEFECT that quotes the line answers it", judge('the page says "pageerror: boom 1"'), "")
        check_in("C4: ... one that quotes other words is refused", "stands in the line of " + name, judge('the page says "pageerror: boom 2"'))
        # C8: the reducer copies the row whole (`dict(latest, ...)`): the contract reader sees the same targets after it
        after = dict(record, current_obligation_ids=["OB-7"], evidence_validated=True)
        check_eq("C8: the row after the reduce lists the same targets", targets(after), got)
        from coverage_contract import validate_manual_current
        with t.patched():
            check_eq("C8: the controller-side check accepts a record with surprises", validate_manual_current(t.task, record), [])
    finally:
        S.cleanup(t)


def MC_FILE_WORD(t):
    """A word the surprises capture holds in a line that is not S1's: the id of the third line."""
    return "a1-ui-S3"


def c5_no_file_is_absent_never_on():
    t = fresh()
    try:
        code, out, err, _ = TMC.ui_run(t, STEPS, S.FakeBrowser())
        check_eq("C5 setup: a backend with no detector writes no file", (code, (folder(t) / "surprises.jsonl").exists()), (0, False))
        code, out, err = build(t)
        check_eq("C5: the build is not refused", code, 0)
        record = record_of(t)
        check_eq("C5: no surprise", (record["surprises"], "surprises_ignored" in record), ([], False))
        check("C5: ... and the detection says `absent`, never `on`", record["surprise_detection"].startswith("absent:"), record["surprise_detection"])
        check_eq("C5: ... no target", targets(record), set())
    finally:
        S.cleanup(t)
    t = fresh()
    try:
        go(t, boom(1))
        (folder(t) / "surprises.jsonl").write_text("", encoding="utf-8")
        code, out, err = build(t)
        record = record_of(t)
        check_eq("C5 BEYOND: an empty file is absent too", (code, record["surprise_detection"].split(":")[0], record["surprises"]), (0, "absent", []))
    finally:
        S.cleanup(t)
    t = fresh()
    try:
        go(t, boom(1, 2))
        path = folder(t) / "surprises.jsonl"
        rows = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(rows[:1] + ["{not json"] + rows[1:]) + "\n", encoding="utf-8")
        code, out, err = build(t)
        record = record_of(t)
        check_eq("C5 BEYOND: a torn line does not stop the build or hide the others", (code, len(record["surprises"])), (0, 2))
        check("C5 BEYOND: ... and the detection is `partial`, with the number of unreadable lines (M-2)",
              record["surprise_detection"].startswith("partial:") and "1 unreadable line(s)" in record["surprise_detection"],
              record["surprise_detection"])
    finally:
        S.cleanup(t)
    t = fresh()
    try:
        go(t, boom(1))
        path = folder(t) / "surprises.jsonl"
        path.write_text("{not json\n", encoding="utf-8")                       # the torn line is the FIRST line: the detector line itself
        code, out, err = build(t)
        record = record_of(t)
        check_eq("C5 BEYOND: a torn first line leaves no detector line -> `absent`, not partial",
                 (code, record["surprise_detection"].split(":")[0]), (0, "absent"))
    finally:
        S.cleanup(t)
    t = fresh()
    try:
        go(t, boom(1))
        path = folder(t) / "surprises.jsonl"
        with path.open("a", encoding="utf-8") as out:
            out.write('{"line": "surprise", "id": "a1-ui-S9", "st')                 # a call killed mid-append: no newline
        code2, out2, err2, _ = TMC.ui_run(t, STEPS, TS.EventBrowser(born={("click", "#a"): boom(2)}), extra=["--attempt", "a1"])
        check_eq("C5 BEYOND: a second `ui` call after a torn line is not refused (M-2)", code2, 0)
        rows, torn = MC._surprise_rows(folder(t))
        check_eq("C5 BEYOND: ... the new lines do not glue onto the torn one: it stays the only unreadable line", torn, 1)
        check("C5 BEYOND: ... and the surprise ids run on past the lines that were readable",
              [r["id"] for r in rows if r.get("line") == "surprise"] == ["a1-ui-S1", "a1-ui-S2"],
              [r.get("id") for r in rows if r.get("line") == "surprise"])
    finally:
        S.cleanup(t)


def c6_with_attempt_and_rejudge():
    url = f"{TMC.LOCAL}/v1/workflows/w1"
    routes = {("GET", url): S.ok_json({"id": "w1", "name": "flow"}),
              ("POST", f"{TMC.LOCAL}/v1/local-auth/login"): S.ok_json({"access_token": S.TOKEN})}

    def two(watched):
        """a1: the page with two lines; a2: an api attempt of ANOTHER profile. Its surprises file is written by hand - the stand-in
        for a second watched surface (the api client logs none of its own)."""
        t = fresh()
        go(t, boom(1, 2))
        code, out, err = TMC.http_run(t, S.FakeHttp(routes), "--method", "GET", "--url", url, "--state-url", url, "--phase", "post_action", case=CASE)
        assert code == 0, err
        steps = len(TMC.jsonl(folder(t, "a2") / "steps.jsonl"))
        rows = [{"line": "surprise", "id": "a2-http-S1", "step": 1, "word": "get", "kind": "status", "fact": "GET /v1/x -> 500",
                 "at": "t", "ignored": None},
                {"line": "surprise", "id": "a2-http-S2", "step": 1, "word": "get", "kind": "status", "fact": "GET /v1/y -> 404",
                 "at": "t", "ignored": 0}]
        if watched:
            rows += [{"line": "detector", "step": n, "listeners": "ok", "kinds_checked": [], "at": "t"} for n in range(1, steps + 1)]
            (folder(t, "a2") / "surprises.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        return t

    t = two(watched=True)
    try:
        code, out, err = build(t, [cite(t, 1, ident="a2-http-S1")], attempt="a1")
        check_eq("C6 edge: citing the line of an attempt the record does not join is refused", code, 2)
        check_in("C6 edge: ... the door is `--with-attempt a2`", "--with-attempt a2", err)
        check("C6 edge: ... nothing was written, the joined attempt is still open", not (folder(t) / "record.json").exists()
              and MC.attempt_state(folder(t, "a2")) == "open")
        code, out, err = build(t, [cite(t, 1, ident="a2-http-S1")], "--with-attempt", "a2", attempt="a1")
        check_eq("C6: the same build with the attempt joined is written", code, 0)
        record = record_of(t)
        check_eq("C6: the record carries the lines of BOTH attempts; a line an older recorder marked `ignored` is listed like any other",
                 [s["id"] for s in record["surprises"]], ["a1-ui-S1", "a1-ui-S2", "a2-http-S1", "a2-http-S2"])
        check("C6: ... and no entry carries `ignored`", all("ignored" not in s for s in record["surprises"]), str(record["surprises"]))
        check_eq("C6: ... a line no capture holds has an empty evidence, never a made-up one",
                 [s["evidence"] for s in record["surprises"]][2], "")
        check_eq("C6: ... both attempts were watched whole: `on`", record["surprise_detection"], "on")
        check_eq("C6: the line the observation cites (a2-http-S1) is not a target, the uncited lines are",
                 targets(record), {f"{CASE}#obs1", sur(1), sur(2), f"{CASE}#sur-a2-http-S2"})
        # rejudge: the two fields travel, nothing is recounted
        base = {k: record[k] for k in ("surprises", "surprise_detection")}
        (folder(t) / "surprises.jsonl").write_text("", encoding="utf-8")          # a recount would now find nothing
        args = ("--of-attempt", "a1", "--result", "inconclusive", "--actual", "again", "--reason", "r", "--limitation", "stopped")
        with t.patched():
            code, out, err = S.run(["rejudge", "--task-root", str(t.task), "--case", CASE, *args], main=M.main, command="manual_evidence.py rejudge")
        check_eq("C6: a re-judge is written", code, 0)
        again = record_of(t, name="rejudge-1.json")
        check_eq("C6: ... and carries the base's two fields unchanged (no recount)",
                 {k: again[k] for k in base}, base)
        # F-4 (a): a base written before X9 carries the retired count; the re-judge drops it (nothing reads it)
        base_path = folder(t) / "record.json"
        old_base = base_path.read_text(encoding="utf-8")
        base_path.write_text(json.dumps(dict(json.loads(old_base), surprises_ignored=1)), encoding="utf-8")
        with t.patched():
            code, out, err = S.run(["rejudge", "--task-root", str(t.task), "--case", CASE, *args], main=M.main, command="manual_evidence.py rejudge")
        check_eq("C6 F-4: a re-judge of a base that carries `surprises_ignored` is written", code, 0)
        check("C6 F-4: ... without the retired count", "surprises_ignored" not in record_of(t, name="rejudge-2.json"),
              str(sorted(record_of(t, name="rejudge-2.json"))))
        base_path.write_text(old_base, encoding="utf-8")
        path = t.task / "obs2.json"
        entry = {"step": 3, "expected": "no page error", "seen": "boom 1", "evidence": evidence_of(t), "quote": "boom 1",
                 "surprise": "a2-http-S1"}
        for label, ident, ok in (("a line of the joined attempt", "a2-http-S1", True), ("an attempt the base does not hold", "a3-ui-S1", False)):
            path.write_text(json.dumps([dict(entry, surprise=ident)]), encoding="utf-8")
            with t.patched():
                code, out, err = S.run(["rejudge", "--task-root", str(t.task), "--case", CASE, *args, "--observations-file", str(path)],
                                       main=M.main, command="manual_evidence.py rejudge")
            check_eq(f"C6: a re-judge citing {label} is {'written' if ok else 'refused'}", code, 0 if ok else 2)
            if not ok:
                check_in("C6: ... with the door", "--with-attempt a3", err)
    finally:
        S.cleanup(t)
    t = two(watched=False)
    try:
        code, out, err = build(t, None, "--with-attempt", "a2", attempt="a1")
        record = record_of(t)
        check_eq("C6: a joined attempt with no detector line is not `on`", (code, record["surprise_detection"].startswith("partial: attempt a2: absent")), (0, True))
        check_eq("C6: ... the main attempt's lines are still carried", [s["id"] for s in record["surprises"]], ["a1-ui-S1", "a1-ui-S2"])
    finally:
        S.cleanup(t)


def write_block_case():
    t = fresh()
    try:
        go(t, boom(1, 2))
        code, out, err = build(t, [cite(t, 1)])
        check_eq("write-block setup: the record is built", code, 0)
        record = record_of(t)
        fields = ("surprises", "surprise_detection")
        dropped = {k: v for k, v in record.items() if k not in fields}
        forged = dict(record, surprises=[], surprise_detection="on")
        legacy = dict(record, surprises_ignored=7)                                  # F-4 (a): a hand record that carries the retired count
        with t.patched():
            for label, rec in (("a record that dropped the fields", dropped), ("a record that forged them", forged), ("a record with the retired count", legacy)):
                path = M.write_block(t.task, [rec], declared=True)
                got = json.loads(path.read_text(encoding="utf-8"))["manual_checks"][0]
                check_eq(f"write-block: {label} is written with the lines of the attempt's files", {k: got[k] for k in fields}, {k: record[k] for k in fields})
                check(f"write-block: {label} is written without `surprises_ignored`", "surprises_ignored" not in got, str(sorted(got)))
            try:
                M.write_block(t.task, [dict(record, observations=[cite(t, 1, ident="a1-ui-S9")])], declared=True)
                refused = ""
            except ValueError as exc:
                refused = str(exc)
            check_in("write-block: a citation no line holds is refused", "is no surprise line of a1", refused)
            try:
                M.write_block(t.task, [dict(record, observations=[cite(t, 1, ident="a2-ui-S1")])], declared=True)
                refused = ""
            except ValueError as exc:
                refused = str(exc)
            check_in("write-block: ... an attempt it does not hold gets the door", "--with-attempt a2", refused)
            # a record whose files are not here: nothing is added, its own lines are all there is to cite
            alone = dict(dropped, case=record["case"], attempt_id="a7", surprises=[{"id": "a7-ui-S1", "step": 1, "kind": "console", "fact": "f", "evidence": ""}])
            alone["observations"] = [cite(t, 1, ident="a7-ui-S1")]
            check_eq("write-block: a record with no attempt folder cites its own lines", C_cite(alone), [])
            # M-2: the retired count is dropped on the no-folder branch too; a record without the key is unchanged
            nofolder = dict(record, attempt_id="a7", rejudge_of=None, surprises_ignored=7)
            check_eq("write-block no-folder setup: the attempt has no folder (no fields to add)", M._hand_surprises(t.task, nofolder)[2], None)
            check("write-block no-folder negative control: the record handed in DOES carry `surprises_ignored`", "surprises_ignored" in nofolder)
            try:
                path = M.write_block(t.task, [nofolder], declared=True)
                got = json.loads(path.read_text(encoding="utf-8"))["manual_checks"][0]
                check("write-block: a record with no attempt folder is written without `surprises_ignored`", "surprises_ignored" not in got, str(sorted(got)))
                check_eq("write-block: ... and nothing else of it changes",
                         {k: v for k, v in got.items()}, {k: v for k, v in nofolder.items() if k != "surprises_ignored"})
                plain = {k: v for k, v in nofolder.items() if k != "surprises_ignored"}
                path = M.write_block(t.task, [plain], declared=True)
                check_eq("write-block: a record with no `surprises_ignored` key is unchanged",
                         json.loads(path.read_text(encoding="utf-8"))["manual_checks"][0], plain)
            except ValueError as exc:
                check("write-block: a record with no attempt folder is accepted by the write-block", False, str(exc)[:200])
    finally:
        S.cleanup(t)


def C_cite(record):
    attempts, known, fields = M._hand_surprises(Path("."), dict(record, case="nowhere"))
    return M._surprise_cite_errors(record["observations"], known, attempts, "door")


def c7_the_cap_is_on_targets():
    cap = C._surprise_cap()
    check_eq("C7: the cap is the data file's number", cap, MC.spec()["surprise"]["max_per_attempt"])
    check_eq("C7: ... and the fallback in code is the same number (pinned)", C.SURPRISE_CAP_FALLBACK, cap)
    check_eq("C7: ... 30", cap, 30)

    def row(count, cited=()):
        return {"case": "TC-1", "result": "pass", "attempt_id": "a1",
                "surprises": [{"id": f"a1-ui-S{k}", "step": 2, "kind": "console", "fact": f"pageerror: boom {k}", "evidence": ""}
                              for k in range(1, count + 1)],
                "observations": [{"step": 2, "surprise": f"a1-ui-S{k}"} for k in cited]}

    def shape(record):
        got = C.triage_targets(report_of(record))["observations"]
        return len([n for n in got if "#sur-a" in n]), "TC-1#sur-overflow" in got
    check_eq("C7 below: 29 uncited -> 29 targets, no overflow", shape(row(29)), (29, False))
    check_eq("C7 AT: exactly 30 -> 30 targets, no overflow target", shape(row(30)), (30, False))
    check_eq("C7 BEYOND: 31 -> 30 targets + one overflow", shape(row(31)), (30, True))
    check_eq("C7 BEYOND: 100 -> still ONE overflow target", shape(row(100)), (30, True))
    check_eq("C7: a cited line does not count toward the cap (31 lines, 1 cited -> 30, no overflow)", shape(row(31, cited=[7])), (30, False))
    check_eq("C7: ... 32 lines, 1 cited -> 30 + overflow", shape(row(32, cited=[7])), (30, True))
    got = C.triage_targets(report_of(row(31)))["observations"]
    check("C7: the targets are the FIRST 30 in the record's order, the last line is the overflow's", "TC-1#sur-a1-ui-S30" in got and "TC-1#sur-a1-ui-S31" not in got)
    failures, _ = C.triage_failures(report_of(row(12)))
    check_eq("C7: the order of the failures is the recorder's (S2 before S10)", [n.rpartition("-")[2] for _, n in failures][:4], ["S1", "S2", "S3", "S4"])
    check_eq("C7: ... S10 after S9", [n.rpartition("-")[2] for _, n in failures][-3:], ["S10", "S11", "S12"])
    entry = C.observation_entry(report_of(row(33)), "TC-1#sur-overflow")
    check_eq("C7: the overflow target has an entry that counts the lines (`seen`) and quotes the lines themselves (M-1)",
             (entry["evidence"], entry["seen"], len(entry["quote"].splitlines())),
             ("", "3 more surprises: a1-ui-S31, a1-ui-S32, a1-ui-S33", 3))
    entry = C.observation_entry(report_of(row(37)), "TC-1#sur-overflow")
    check_eq("C7 BEYOND: seven lines past the cap -> the count names the first five ids and `...`, the quote holds all seven lines",
             (entry["seen"], len(entry["quote"].splitlines())),
             ("7 more surprises: a1-ui-S31, a1-ui-S32, a1-ui-S33, a1-ui-S34, a1-ui-S35, ...", 7))
    check_eq("C7: no overflow, no overflow entry", C.observation_entry(report_of(row(30)), "TC-1#sur-overflow"), None)
    check_eq("C7: a line past the cap is no target and has no entry", C.observation_entry(report_of(row(31)), "TC-1#sur-a1-ui-S31"), None)
    def overflow(words, rows=33):
        return C.triage_no_defect_problems({"instance_id": "TC-1#sur-overflow", "verdict": "NO_DEFECT", "reason": f'said "{words}"'},
                                           report_of(row(rows)))
    check_eq("C7: a NO_DEFECT on the overflow target quoting a fact of a hidden line passes (M-1)", overflow("boom 31"), [])
    check_eq("C7: ... a fact of ANY hidden line, the last one too", overflow("boom 33"), [])
    check_eq("C7: ... the count words alone are no evidence and are refused", len(overflow("3 more surprises")), 1)
    check_eq("C7: ... nor an id taken from the count", len(overflow("a1-ui-S32")), 1)
    check_eq("C7: ... a quote that is not there is refused", len(overflow("boom 99")), 1)
    check_eq("C7 BEYOND: ... a fact of a line that is NOT hidden (the line 30 is shown) is refused", len(overflow("boom 30")), 1)
    # E2E: the real recorder, 31 distinct page errors in one click, through build
    t = fresh()
    try:
        go(t, boom(*range(1, 32)))
        check_eq("C7 e2e: the recorder wrote 31 lines (the summary shows 5 of them per step, the file holds all)", len(lines_of(t)), 31)
        code, out, err = build(t)
        record = record_of(t)
        check_eq("C7 e2e: the record carries all 31", len(record["surprises"]), 31)
        check_eq("C7 e2e: 30 targets and one overflow", shape(dict(record, case="TC-1")), (30, True))
    finally:
        S.cleanup(t)
    # nameless and legacy rows
    check_eq("C7 control: a legacy row with no `surprises` yields what it did before",
             C.triage_targets(report_of({"case": "TC-1", "result": "pass"}))["observations"], set())
    for junk in ("x", {"a": 1}, [None, 5, {"id": ""}, {"id": "a1-ui-S1"}, {"id": "a1-ui-S1"}]):
        got = C.triage_targets(report_of({"case": "TC-1", "result": "pass", "surprises": junk}))["observations"]
        check_eq(f"C7 BEYOND: `surprises` = {str(junk)[:30]!r} gives only the real, once-listed ids", got,
                 {"TC-1#sur-a1-ui-S1"} if isinstance(junk, list) else set())
    nameless = C.triage_targets({"current_manual_checks": [{"result": "pass", "surprises": [{"id": "a1-ui-S1"}]}]})
    check_eq("C7: a surprise on a check with no name is a note, never dropped", (len(nameless["unnamed_manual"]), nameless["observations"]), (1, set()))


def main():
    c1_c2_c3_c4_one_recorded_attempt()
    c5_no_file_is_absent_never_on()
    c6_with_attempt_and_rejudge()
    write_block_case()
    c7_the_cap_is_on_targets()
    finish("test_manual_surprise_triage")


if __name__ == "__main__":
    main()
