#!/usr/bin/env python3
"""question_stop.py: the threshold for "stop and ask the whole batch" and the batch text
(t-113 piece B1, B-216 R15 / R16, owner decision 30.09).

The class of defect held here: a stop that hides its own limit (a default shown as the project's
number), a share compared in floats (2 of 6 requirements over "a third"), a register with no total
that crashes or reads as 0, and a batch that drops a question or asks an answered one again. One
named check per override and per edge; the real gate card is called once, at the very end, and
asserts only that every open id is there (gate_brief is changed by another piece).
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import question_stop as QS  # noqa: E402
import human_text  # noqa: E402

NAN = float("nan")
INF = float("inf")
TIME = "2026-09-30T18:05"


def q(qid, reqs=None, n=2, text=None):
    row = {"id": qid, "question": text or f"what should happen for {qid}?", "severity": "major",
           "readings": [{"reading": f"reading {i}", "from": "code", "if_chosen": "x"} for i in range(n)]}
    if reqs is not None:
        row["requirements"] = reqs
    return row


def story(root: Path, questions, total=24, answers=None, pipeline=None, register=True):
    """A task root with the files the register reads. `answers` are record dicts (one line each)."""
    (root / "work").mkdir(parents=True, exist_ok=True)
    if register:
        data = {"verdict": "blocked", "open_questions": questions}
        if total is not None:
            data["register"] = {"total": total}
        (root / "work" / "requirements-readiness.json").write_text(json.dumps(data), encoding="utf-8")
    if answers:
        (root / "work" / "question-answers.jsonl").write_text(
            "\n".join(json.dumps(a) for a in answers) + "\n", encoding="utf-8")
    if pipeline is not None:
        (root / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")


def rec(qid, status):
    return {"kind": "question", "id": qid, "status": status, "words": f"{qid}: a", "by": "person",
            "where": "gate A", "at": "2026-09-30T17:00:00+00:00"}


def many(n, reqs_each=None):
    """n questions; question i names requirements R-{i*k+1}..R-{i*k+k} (disjoint) when reqs_each is set."""
    out = []
    for i in range(n):
        reqs = None if reqs_each is None else [f"R-{i * reqs_each + j + 1}" for j in range(reqs_each)]
        out.append(q(f"Q{i + 1}", reqs))
    return out


def run(root, questions, total=24, config=None, **kw):
    story(root, questions, total=total, **kw)
    return QS.over_threshold(root, config)


def stub_card(calls=None):
    def card(question, index):
        if calls is not None:
            calls.append((question["id"], index))
        return [f"- **{question['id']}** {question['question']}",
                "  - a) the first reading", "  - b) the second reading"]
    return card


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def safe(fn, *args, **kw):
    """(value, error text): a crash is a failed check, not the end of the file."""
    try:
        return fn(*args, **kw), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


tmp = temp_dir("qa-stop-")
counter = [0]


def fresh() -> Path:
    counter[0] += 1
    return tmp / f"story{counter[0]}"


try:
    # ---- the data file ---------------------------------------------------------------------
    raw = json.loads(QS.THRESHOLDS_PATH.read_text(encoding="utf-8"))
    check_eq("O1 data file: the default count is 6", raw["count"], 6)
    check_eq("O1 data file: the default share is the STRING \"1/3\" (exact, never a float)", raw["share"], "1/3")
    base = QS.defaults()
    check("O1 defaults() reads the exact fraction 1/3", str(base["share"]) == "1/3" and base["count"] == 6)
    check("O1 the stop-reason words cover every closed reason of the vocabulary",
          set(base["reason_words"]) == set(QS.QR.vocabulary()["stop_reasons"]))

    # ---- O1: count, strictly greater -----------------------------------------------------------
    r = run(fresh(), many(6), config={})
    check("O1 count = limit (6 of 6): NOT over", r["over"] is False and r["count"] == 6 and r["count_limit"] == 6)
    r = run(fresh(), many(7), config={})
    check("O1 count = limit + 1 (7): over", r["over"] is True and r["count"] == 7)
    check_in("O1 the count reason says it is more than the limit", "That is more than the limit", r["reasons"])
    r = run(fresh(), many(0), config={})
    check("O1 no question at all: not over, count 0", r["over"] is False and r["count"] == 0)
    r = run(fresh(), many(1), config={"questions": {"stop_at": {"count": 0}}})
    check("O1 a project limit of 0 is valid: one open question is over", r["over"] is True and r["count_limit"] == 0)
    r = run(fresh(), many(3), config={"questions": {"stop_at": {"count": 3}}})
    check("O1 project count 3: 3 open not over", r["over"] is False and r["count_limit"] == 3)
    r = run(fresh(), many(4), config={"questions": {"stop_at": {"count": 3.0}}})
    check("O1 project count 3.0 (a whole float) is a number: 4 open over", r["over"] is True and r["count_limit"] == 3)

    # ---- O1: share, exact arithmetic -----------------------------------------------------------
    r = run(fresh(), [q("Q1", ["R-1", "R-2"])], total=6, config={})
    check("O1 share 2 of 6 requirements is NOT over a third (exact, not float)", r["over"] is False)
    check_eq("O1 share printed for 2 of 6", (r["requirements_open"], r["requirements_total"]), (2, 6))
    r = run(fresh(), [q("Q1", ["R-1", "R-2", "R-3"])], total=6, config={})
    check("O1 share 3 of 6 is over a third", r["over"] is True and r["count"] == 1)
    check_in("O1 the share reason says it is more than the limit", "rest on an open question", r["reasons"])
    r = run(fresh(), [q("Q1", [f"R-{i}" for i in range(100)])], total=300, config={})
    check("O1 share exactly at the limit (100 of 300): not over", r["over"] is False)
    r = run(fresh(), [q("Q1", [f"R-{i}" for i in range(101)])], total=300, config={})
    check("O1 share just above the limit (101 of 300): over", r["over"] is True)
    r = run(fresh(), [q("Q1", [f"R-{i}" for i in range(99)])], total=300, config={})
    check("O1 share just below the limit (99 of 300): not over", r["over"] is False)
    r = run(fresh(), [q("Q1", ["R-1", "R-2"]), q("Q2", ["R-2", "R-3"])], total=9, config={})
    check("O1 the share counts the UNION: R-2 named twice is one requirement (3 of 9 = a third, not over)",
          r["over"] is False and r["requirements_open"] == 3)
    r = run(fresh(), [q("Q1", ["R-1", "R-2"])], total=10, config={"questions": {"stop_at": {"share": 0.2}}})
    check("O1 project share 0.2 as a number: 2 of 10 not over", r["over"] is False)
    r = run(fresh(), [q("Q1", ["R-1", "R-2", "R-3"])], total=10, config={"questions": {"stop_at": {"share": 0.2}}})
    check("O1 project share 0.2: 3 of 10 over", r["over"] is True)
    r = run(fresh(), [q("Q1", ["R-1", "R-2", "R-3"])], total=10, config={"questions": {"stop_at": {"share": 0.3}}})
    check("O1 project share 0.3 (a decimal is read as 3/10, not its binary neighbour): 3 of 10 NOT over",
          r["over"] is False)
    r = run(fresh(), [q("Q1", ["R-1", "R-2", "R-3", "R-4"])], total=10, config={"questions": {"stop_at": {"share": 0.3}}})
    check("O1 project share 0.3: 4 of 10 over", r["over"] is True)
    r = run(fresh(), [q("Q1", ["R-1", "R-2", "R-3"])], total=10, config={"questions": {"stop_at": {"share": " 3 / 10 "}}})
    check("O1 project share written n/d with spaces, \"3 / 10\": 3 of 10 not over; text is 3/10",
          r["over"] is False and r["share_limit_text"] == "3/10")
    r = run(fresh(), [q("Q1", ["R-1"])], total=10, config={"questions": {"stop_at": {"share": 0}}})
    check("O1 project share 0 is valid: any requirement on an open question is over", r["over"] is True)
    r = run(fresh(), [q("Q1", [f"R-{i}" for i in range(10)])], total=10, config={"questions": {"stop_at": {"share": 1}}})
    check("O1 project share 1 is valid: every requirement open is not MORE than all of them", r["over"] is False)
    r = run(fresh(), many(7, 1), total=24, config={})
    check("O1 either condition stops: 7 questions over by count although the share is 7/24",
          r["over"] is True and r["share"] is not None and r["share"] < 1 / 3)

    # ---- O1 / O2: source and the words a person reads -------------------------------------------
    r = run(fresh(), many(2, 1), config={})
    check_eq("O2 no config: source is 'factory default'", r["source"], "factory default")
    check_eq("O2 no config: both fields say default", r["sources"], {"count": "factory default", "share": "factory default"})
    text = "\n".join(r["reasons"])
    check_in("O2 a default is labelled \"the factory's default threshold\"", "the factory's default threshold", text)
    check_not_in("O2 a default is never presented as the project's number", "this project's threshold", text)
    r = run(fresh(), many(2, 1), config={"questions": {"stop_at": {"count": 5, "share": "1/2"}}})
    text = "\n".join(r["reasons"])
    check_eq("O2 a project config: source is 'project'", r["source"], "project")
    check_in("O2 a project number is labelled \"this project's threshold\"", "this project's threshold", text)
    check_not_in("O2 a project number is never labelled as the factory's default", "default", text)
    check_eq("O2 no warning when the project values are valid", r["warnings"], [])
    r = run(fresh(), many(2, 1), config={"questions": {"stop_at": {"count": 5}}})
    text = "\n".join(r["reasons"])
    check_eq("O2 only the count set: each field has its own source", r["sources"], {"count": "project", "share": "factory default"})
    count_line = next(x for x in r["reasons"] if "open." in x)
    share_line = next(x for x in r["reasons"] if "rest on" in x)
    check("O2 mixed: the count line says the project's, the share line says the default",
          "this project's threshold" in count_line and "default threshold" in share_line
          and "default" not in count_line and "project" not in share_line)
    r = run(fresh(), many(2, 1), config={"questions": {"stop_at": {"count": 3, "share": "abc"}}})
    check_eq("O2 a project field replaced by the default is labelled as the default",
             r["sources"], {"count": "project", "share": "factory default"})

    # ---- project value discovery ---------------------------------------------------------------
    project = temp_project("qa-stop-proj-")
    try:
        troot = project / "qa-factory" / "artifacts" / "T-1"
        cfg_path = project / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["questions"] = {"stop_at": {"count": 2}}
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        story(troot, many(3))
        r = QS.over_threshold(troot)
        check("E-8 config=None: the project's qa-factory/config.json is found from the task root",
              r["source"] == "project" and r["count_limit"] == 2 and r["over"] is True)
        r = QS.over_threshold(troot, {})
        check("E-8 config={} given explicitly beats the file on disk: the defaults",
              r["source"] == "factory default" and r["count_limit"] == 6 and r["over"] is False)
        cfg_path.write_text("{ not json", encoding="utf-8")
        r, err = safe(QS.over_threshold, troot)
        check("E-8 a project config that is not JSON: defaults and a warning, no exception",
              not err and r["count_limit"] == 6 and r["source"] == "factory default" and len(r["warnings"]) == 1, err)
        cfg.pop("questions")
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        r = QS.over_threshold(troot)
        check("E-8 the `questions` key absent from the project config: defaults, no warning",
              r["source"] == "factory default" and r["warnings"] == [])
    finally:
        cleanup(project)
    alone = fresh()
    story(alone, many(2))
    r = QS.over_threshold(alone)
    check("E-8 no project config anywhere above the task root: defaults", r["source"] == "factory default" and r["count_limit"] == 6)

    # ---- edge: invalid project values -----------------------------------------------------------
    bad_counts = {"text": "abc", "negative": -1, "bool": True, "fraction": 2.5, "null": None, "list": [3],
                  "nan": NAN, "inf": INF, "numeric text": "3"}
    for label, value in bad_counts.items():
        r, err = safe(run, fresh(), many(7), config={"questions": {"stop_at": {"count": value, "share": "1/2"}}})
        ok = (not err and r["count_limit"] == 6 and r["sources"]["count"] == "factory default"
              and r["sources"]["share"] == "project" and len(r["warnings"]) == 1 and r["over"] is True)
        check(f"edge invalid project count ({label}): default 6 for THAT field, the share stays the project's, one warning", ok, err)
    bad_shares = {"text": "abc", "negative": -0.1, "above 1": 1.5, "zero denominator": "1/0", "above 1 as n/d": "4/3",
                  "bool": True, "decimal text": "0.5", "negative n/d": "-1/3", "nan": NAN, "inf": INF, "null": None,
                  "list": [0.5], "empty": ""}
    for label, value in bad_shares.items():
        r, err = safe(run, fresh(), [q("Q1", ["R-1", "R-2"])], total=6,
                      config={"questions": {"stop_at": {"count": 4, "share": value}}})
        ok = (not err and r["share_limit_text"] == "1/3" and r["sources"]["share"] == "factory default"
              and r["sources"]["count"] == "project" and len(r["warnings"]) == 1 and r["over"] is False)
        check(f"edge invalid project share ({label}): default 1/3 for THAT field, the count stays the project's, one warning", ok, err)
    r = run(fresh(), many(2), config={"questions": {"stop_at": {"count": "abc"}}})
    check_in("edge the warning is plain words and names the value and the replacement",
             "the factory's default, 6, is used instead", r["warnings"])
    for label, cfg_value in {"stop_at is a list": {"questions": {"stop_at": [1]}},
                             "questions is a string": {"questions": "x"},
                             "config is a list": [1, 2],
                             "stop_at empty": {"questions": {"stop_at": {}}}}.items():
        r, err = safe(run, fresh(), many(2), config=cfg_value)
        check(f"edge odd project shape ({label}): defaults, no exception", not err and r["source"] == "factory default"
              and r["count_limit"] == 6, err)

    # ---- edge: share unknown ----------------------------------------------------------------
    r, err = safe(run, fresh(), [q("Q1", ["R-1"])], total=0, config={})
    check("edge register total 0: no exception, the share is unknown (None), never 0",
          not err and r["share"] is None and r["over"] is False, err)
    check_in("edge total 0: the text says the share could not be computed", "could not be computed", (r or {"reasons": []})["reasons"])
    r, err = safe(run, fresh(), many(7, 1), total=0, config={})
    check("edge total 0: the count alone decides (7 questions over)", not err and r["over"] is True and r["share"] is None, err)
    r, err = safe(run, fresh(), many(3, 1), total=None, config={})
    check("edge register with no total at all: share None, count decides (3 not over)",
          not err and r["share"] is None and r["over"] is False, err)
    for label, total in {"negative": -5, "text": "24", "bool": True, "float": 24.0}.items():
        r, err = safe(run, fresh(), many(3, 1), total=total, config={})
        check(f"edge register total that is not a positive whole number ({label}): share None", not err and r["share"] is None, err)
    r, err = safe(run, fresh(), many(3), total=24, config={})
    check("edge no question carries `requirements`: share None (not 0), text says so",
          not err and r["share"] is None and any("no question says which requirements" in x for x in r["reasons"]), err)
    r, err = safe(run, fresh(), many(9), total=24, config={})
    check("edge no `requirements` anywhere: 9 questions still over by count alone", not err and r["over"] is True, err)
    r = run(fresh(), [q("Q1", []), q("Q2", None)], total=24, config={})
    check("edge some questions carry an (empty) list: the share is known and is 0",
          r["share"] == 0.0 and any("name no requirements" in w for w in r["warnings"]))
    r = run(fresh(), [q("Q1", ["R-1", "R-1", "", 7, None, " R-2 "])], total=24, config={})
    check("edge requirement entries: blanks and non-texts are not counted, names are trimmed, a warning says so",
          r["requirements_open"] == 2 and any("not texts" in w for w in r["warnings"]))
    r = run(fresh(), [q("Q1", [f"R-{i}" for i in range(9)])], total=6, config={})
    check("edge more requirements named than the register total: over, and a warning says the data is wrong",
          r["over"] is True and any("more than the register's total" in w for w in r["warnings"]))
    r = run(fresh(), [q("Q1", ["R-1"])], total=6, answers=[rec("Q1", "answered")], config={})
    check("edge all answered: count 0, share 0 and not unknown (the register carries requirements)",
          r["count"] == 0 and r["share"] == 0.0 and r["over"] is False)

    # ---- edge: register absent / broken / load raising ---------------------------------------------
    r, err = safe(QS.over_threshold, fresh(), {})
    check("edge no register (no task folder at all): defaults, over False, no exception",
          not err and r["over"] is False and r["count"] == 0 and r["count_limit"] == 6, err)
    check_in("edge no register: the reason says no question register was found", "No question register was found", r["reasons"])
    blank = fresh()
    blank.mkdir(parents=True)
    r = QS.over_threshold(blank, {})
    check("edge task folder with no readiness file: over False, reason says no register was found",
          r["over"] is False and "No question register was found" in r["reasons"][0])
    broken = fresh()
    (broken / "work").mkdir(parents=True)
    (broken / "work" / "requirements-readiness.json").write_text("{ broken", encoding="utf-8")
    r, err = safe(QS.over_threshold, broken, {})
    check("edge register that is not JSON: over False and the reason says it could not be read, never a crash",
          not err and r["over"] is False and "could not be read" in r["reasons"][0], err)
    original_load = QS.QR.load

    def boom(_root):
        raise KeyError("load exploded")
    QS.QR.load = boom
    try:
        r, err = safe(QS.over_threshold, fresh(), {"questions": {"stop_at": {"count": 2}}})
        check("edge `load` raising: over False, the project's limits still read, the reason says it could not be read",
              not err and r["over"] is False and r["count_limit"] == 2 and "could not be read" in r["reasons"][0], err)
        text, err = safe(QS.batch_text, fresh(), "x", stub_card())
        check("edge `load` raising: batch_text returns \"\" (nothing it can ask), no exception", not err and text == "", err)
    finally:
        QS.QR.load = original_load

    # ---- edge: statuses: what counts, what is in the batch ---------------------------------------
    st = fresh()
    story(st, [q("Q1", ["R-1"]), q("Q2", ["R-2"]), q("Q3", ["R-3"]), q("Q4", ["R-4"]), q("Q5", ["R-5"]), q("Q6", ["R-6"])],
          answers=[rec("Q1", "answered"), rec("Q2", "not_needed"), rec("Q3", "with_designer")],
          pipeline={"gates": {"A": {"decision": "approved", "authorization_source": "Q5 is a hard one, I will think"}}})
    view = QS.QR.load(st)
    status = {x["id"]: x["status"] for x in view["questions"]}
    check_eq("edge fixture statuses as the register reads them", status,
             {"Q1": "answered", "Q2": "not_needed", "Q3": "with_designer", "Q4": "open", "Q5": "named", "Q6": "open"})
    r = QS.over_threshold(st, {})
    check("edge `named` counts as open for the COUNT (it has no recorded answer); answered, not_needed and with_designer do not: 3",
          r["count"] == 3 and r["requirements_open"] == 3)
    text = QS.batch_text(st, "x", stub_card())
    check("edge `named` IS in the batch (same rule as the count)", "**Q5**" in text)
    check_in("edge a named question says the person named it but no answer was recorded",
             "no answer for it", text)
    check("edge open questions Q4 and Q6 are in the batch", "**Q4**" in text and "**Q6**" in text)
    for gone in ("Q1", "Q2", "Q3"):
        check_not_in(f"O3/E an {status[gone]} question ({gone}) is never in the batch", f"**{gone}**", text)

    # ---- O3: the batch text -----------------------------------------------------------------------
    b3 = fresh()
    story(b3, [q("Q1", ["R-1"], text="should a disallowed event type get 200 or 400?"),
               q("Q2", ["R-2"], text="is the 25 MB limit a failure or a bypass?"),
               q("Q3", ["R-7", "R-9"], text="is the UI field in scope?")])
    calls: list = []
    text = QS.batch_text(b3, "the factory is not confident enough in its reading of the story to go on without you",
                         stub_card(calls))
    print("---- batch text, three open questions, stub renderer ----")
    print(text)
    print("---- end ----")
    check_eq("O3 the renderer is called once per open question, in register order, with a 1-based index",
             calls, [("Q1", 1), ("Q2", 2), ("Q3", 3)])
    check("O3 all three cards are in the text, in order",
          0 <= text.find("**Q1**") < text.find("**Q2**") < text.find("**Q3**"))
    check_in("O3 the header says what the factory decided by itself", "has not guessed an answer", text)
    check_in("O3 the header gives the reason in plain words", "Why it stops: the factory is not confident enough", text)
    check_in("O3 the header says how many questions and that it is one batch", "3 questions to decide - one batch", text)
    check("O3 the how-to-answer block is last, in its own block, with the three forms",
          text.rfind("## How to answer") > text.rfind("**Q3**")
          and "<question id>: <the letter of the answer you choose>" in text
          and "<question id>: not needed" in text and "in your own words" in text)
    check_in("O3 an example line uses ids that are in the batch", "`Q1: a` and `Q2: not needed`", text)
    check_not_in("O3 a first stop does not carry the re-stop line", "still open after your answer", text)
    check_eq("O3 human_text finds nothing wrong with the header and the block (FR-6)", human_text.problems(text), [])
    check_eq("O3 batch_text writes nothing (FR-45): a second call is the same text", QS.batch_text(
        b3, "the factory is not confident enough in its reading of the story to go on without you", stub_card()), text)
    before = tree_hash(b3)
    QS.batch_text(b3, "over_threshold", stub_card())
    QS.over_threshold(b3, {})
    check_eq("O4 neither function writes anything into the task folder (tree hash before = after)", tree_hash(b3), before)

    code_text = QS.batch_text(b3, "over_threshold", stub_card(), None)
    check_not_in("O3 a closed reason code never reaches a person", "over_threshold", code_text)
    check_in("O3 the code is turned into its plain words", "too much of the story rests on questions nobody has answered", code_text)
    check_in("O2/O3 the threshold stop text says whose number the limit is", "the factory's default threshold", code_text)
    check_eq("O3 human_text finds nothing wrong with a threshold stop either", human_text.problems(code_text), [])
    proj_text = QS.batch_text(b3, "over_threshold", stub_card())
    check_eq("O3 the same register gives the same text twice", proj_text, code_text)
    blank_reason = QS.batch_text(b3, "  ", stub_card())
    check_in("O3 a blank reason gets a plain fallback, never an empty 'Why it stops'", "needs an answer to the questions below", blank_reason)
    spaced = QS.batch_text(b3, "  a   reason\nin words ", stub_card())
    check_in("O3 a reason in words is shown as given (whitespace collapsed)", "Why it stops: a reason in words", spaced)

    # the re-stop after a partial answer
    (b3 / "work" / "question-answers.jsonl").write_text(json.dumps(rec("Q2", "answered")) + "\n", encoding="utf-8")
    second = QS.batch_text(b3, "the factory is not confident enough in its reading of the story to go on without you",
                           stub_card(), TIME)
    check_in("O3 a re-stop carries the line \"still open after your answer of <time>\"",
             f"still open after your answer of {TIME}", second)
    check("O3 a re-stop lists only the still-open questions: Q1 and Q3, not the answered Q2",
          "**Q1**" in second and "**Q3**" in second and "**Q2**" not in second)
    check_in("O3 a re-stop says what the answer settled", "Your answer settled 1 question, and they are not asked again", second)
    check("FR-7 the re-stop is changed text, not the first text again", second != text and "1 questions to decide" not in second)
    check_in("O3 a re-stop counts the questions left", "2 questions to decide", second)
    check_eq("O3 human_text finds nothing wrong with the re-stop", human_text.problems(second), [])
    blank_time = QS.batch_text(b3, "x", stub_card(), "")
    check("O3 a re-stop with no time known is still a re-stop (FR-7), not the first text",
          "still open after your answer of earlier" in blank_time and "**Q2**" not in blank_time)
    (b3 / "work" / "question-answers.jsonl").write_text(
        "\n".join(json.dumps(rec(i, "answered")) for i in ("Q1", "Q2", "Q3")) + "\n", encoding="utf-8")
    check_eq("edge every question answered: the batch is an empty string, not a header with no cards",
             QS.batch_text(b3, "x", stub_card(), TIME), "")
    check_eq("edge every question answered: a first-stop call is also empty", QS.batch_text(b3, "x", stub_card()), "")
    none = fresh()
    story(none, [], total=10)
    check_eq("edge a register with no questions: \"\"", QS.batch_text(none, "x", stub_card()), "")
    check_eq("edge no register at all: \"\"", QS.batch_text(fresh(), "x", stub_card()), "")
    mixed = fresh()
    story(mixed, [q("Q1", ["R-1"], n=0), q("Q2", ["R-2"], n=2)])
    check_in("O3 the example letter goes only with a question that has readings (Q1 has none, Q2 has two)",
             "`Q2: a` and `Q1: not needed`", QS.batch_text(mixed, "x", stub_card()))
    nocard = fresh()
    story(nocard, [q("Q1", ["R-1"])])

    # the invariant: a card that fails or forgets the id never drops the question
    def raising(question, index):
        raise RuntimeError("renderer broke")
    text = QS.batch_text(nocard, "x", raising)
    check_in("edge a renderer that raises: the question is still printed (id and its words)", "**Q1** what should happen for Q1?", text)
    text = QS.batch_text(nocard, "x", lambda question, index: ["some card without the id"])
    check("edge a card that does not carry the id gets one (no open question is missing)",
          "**Q1**" in text and "some card without the id" in text)
    text = QS.batch_text(nocard, "x", lambda question, index: "- **Q1** a card returned as one string\n  - a) x")
    check_in("edge a renderer that returns one string is accepted", "a card returned as one string", text)

    # ---- edge: 200 questions, no cap --------------------------------------------------------------
    big = fresh()
    story(big, many(200, 1), total=400)
    r = QS.over_threshold(big, {})
    check("edge 200 questions: counted in full and over", r["count"] == 200 and r["over"] is True)
    text = QS.batch_text(big, "over_threshold", stub_card())
    missing = [f"Q{i}" for i in range(1, 201) if f"**Q{i}** " not in text]
    check("edge 200 questions: every one printed, no cap", not missing and text.count("- **Q") == 200, str(missing[:5]))
    check_not_in("edge 200 questions: no 'more in a file' line cutting the list", " more ", text.split("200 questions to decide")[1])
    check_in("edge 200 questions: the batch says how many", "200 questions to decide", text)
    st200 = fresh()
    story(st200, many(200), answers=[rec(f"Q{i}", "answered") for i in range(1, 197)])
    text = QS.batch_text(st200, "x", stub_card(), TIME)
    check("edge 200 questions with 196 answered: exactly the four left, in order",
          text.count("- **Q") == 4 and all(f"**Q{i}** " in text for i in range(197, 201)))

    # ---- last: the real gate card, once ------------------------------------------------------------
    real = fresh()
    story(real, [q("Q1", ["R-1"]), q("Q2", ["R-2"]), q("Q3", ["R-3"])])
    text, err = safe(QS.batch_text, real, "x")
    check("real renderer (gate_brief.question_card, loaded at call time): every open question id appears",
          not err and all(f"Q{i}" in text for i in (1, 2, 3)), err)

    # ---- C1-3 node A: the priced batch (the section arrives rendered, above the answer block) -------------------------
    priced_in = "## What each answer costs and does\n\n(a) answer the questions above\nthe factory: x\nyou: y\nthe story: z\n"
    text = QS.batch_text(real, "x", stub_card(), priced=priced_in)
    check("P1 the priced section is in the batch, ABOVE `## How to answer`",
          text.index("## What each answer costs and does") < text.index("## How to answer"))
    check_in("P1 the answer block says a whole `go on` / `stop` is read as that word", "only `go on`, or only `stop`", text)
    check_eq("P1 every option line of the batch is priced (the check reads the body above the answer block)",
             human_text.price_problems(text, None), [])
    check_not_in("P1 with no section handed in the batch is as it was (no section, no sentence)",
                 "## What each answer costs and does", QS.batch_text(real, "x", stub_card()))
    check_not_in("P1 question_stop reads no price data itself (the lines arrive rendered)", "question-prices",
                 Path(QS.__file__).read_text(encoding="utf-8"))
    check_not_in("P1 ...nor conductor-actions", "conductor-actions", Path(QS.__file__).read_text(encoding="utf-8"))

    # ---- C1-3 node A: the answers `go on` / `stop` at the threshold and `stop` at a halt, THROUGH take_answer ---------
    import story_run  # noqa: E402
    from story_run_common import driver_for, seed  # noqa: E402

    r2, task_root2, env2 = seed("QA-9")
    driver = driver_for(r2, env2, "QA-9")
    seen = {"waiver": [], "conductor": [], "unread": [], "review": []}
    waiver_exit = [0]
    real_py = driver.py

    def spy_py(script, *a, **k):
        if script == "waiver.py":
            seen["waiver"].append(a)
            return waiver_exit[0], "refused" if waiver_exit[0] else ""
        return real_py(script, *a, **k)
    driver.py = spy_py
    driver.conductor = lambda *a, **k: seen["conductor"].append(a) or {"action": "continue", "did": "d"}
    real_unread = driver.unread
    driver.unread = lambda *a, **k: seen["unread"].append(a) or "continue"
    driver.judged_reply = lambda *a, **k: ""
    driver.record_review = lambda words: seen["review"].append(words) or True
    DISPATCH = "S2-qa-requirements-tester-1"

    def say(words, name="answer.txt"):
        path = task_root2 / name
        path.write_bytes(words.encode("utf-8"))
        try:
            driver.take_answer(path)
            return None
        except story_run.Person as person:
            return person

    def open_question(kind, text, **kw):
        driver.state["pending_words"] = {}
        driver.ask(story_run.Person(kind, text, "S2", DISPATCH, **kw))

    section = driver.priced_section("questions", [{"answer": "answers", "says": "answer the questions above"},
                                                  {"answer": "go on", "token": "go on", "says": "go on with them open"},
                                                  {"answer": "stop", "token": "stop", "says": "stop the story here"}])
    shown = story_run.Priced(QS.batch_text(real, "x", stub_card(), priced=section), section.priced)
    open_question("questions", shown)
    check("T1 a priced threshold question carries `priced` and NOT `offered` in `asked` (the position invariant of take_answer)",
          "offered" not in driver.state["asked"] and tuple(shown.priced) == ("go on", "stop"))
    held = say("go on")
    check("T2 `go on` is the pass: waiver.py by code, block `question threshold`, the words file named",
          held is None and len(seen["waiver"]) == 1 and "question threshold" in seen["waiver"][0] and "--words-file" in seen["waiver"][0],
          str(seen["waiver"]))
    check_eq("T2 and the words are NOT filed for the role (pending_words empty)", driver.state["pending_words"], {})
    check("T2 the answer is the informed pass: `question_stop.answered` is kept",
          isinstance(driver.state.get("question_stop", {}).get("answered"), dict))
    open_question("questions", shown)
    waiver_exit[0] = 1
    held = say("go on")
    check("T3 a pass that could not be recorded: the question comes back, nothing passed",
          held is not None and held.kind == "questions" and "could not be recorded" in held.text, repr(held))
    waiver_exit[0] = 0
    seen["waiver"].clear()
    open_question("questions", shown)
    held = say("stop")
    check("T4 `stop` holds the question (exit 3), with the changed first line and the batch again",
          held is not None and held.code == 3 and held.text.startswith("You said to stop. Nothing runs and nothing is spent.")
          and "## What each answer costs and does" in held.text, repr(held))
    check("T4 ...and the waiver is not called and no words are filed", not seen["waiver"] and driver.state["pending_words"] == {})
    # F7 (critic t-684): a SECOND `stop` at the same question (the held one is on disk) does not stack the held lead
    driver.ask(held)
    held2 = say("stop")
    check_eq("F7 a second `stop` at the threshold: the held line is there ONCE and the batch under it is the same",
             (held2.text.count("You said to stop."), held2.text == held.text), (1, True))
    driver.ask(held2)
    held3 = say("stop")
    check_eq("F7 ...and a third", (held3.text.count("You said to stop."), held3.text == held.text), (1, True))
    open_question("questions", shown)
    held = say("I would say go on here\nQ1: a")
    check("T5 `go on` INSIDE other words is the choices road (FR-12): no waiver, the words go to the role",
          held is None and not seen["waiver"] and driver.state["pending_words"].get(DISPATCH, "").startswith("I would say go on"),
          str(driver.state["pending_words"]))

    # N22 (G6): at a halt question
    digest = "qa-requirements-tester S2 all · halt\nR-1 · blocked · the size limit is in neither the ticket nor the code\n"
    halt = driver.halt_text("S2", "qa-requirements-tester", digest)
    open_question("halt", halt, details=digest)
    check("N22 a priced halt question has NO `offered` in `asked` (G5: priced is never written there)",
          "offered" not in driver.state["asked"] and tuple(halt.priced) == ("stop",))
    held = say("stop")
    check("N22 `stop` at a halt: exit 3, the changed first line, the priced section again",
          held is not None and held.code == 3 and held.text.startswith("You said to stop.") and "(b) `stop`" in held.text, repr(held))
    check("N22 ...no conductor call, nothing unread, and `pending_words` absent for the dispatch",
          not seen["conductor"] and not seen["unread"] and DISPATCH not in driver.state["pending_words"])
    check_in("N22 ...and the role's own words stay in the details file", "the size limit is in neither the ticket nor the code",
             (driver.state_dir / "driver-question-details.md").read_text(encoding="utf-8"))
    driver.ask(held)
    held2 = say("stop")
    check_eq("F7 a second `stop` at a halt: the held line ONCE, the details file kept, the same text",
             (held2.text.count("You said to stop."), held2.text == held.text, held2.details == held.details), (1, True, True))
    open_question("halt", halt, details=digest)
    held = say("stop please")
    check_eq("N22 `stop please` is other words: today's unread road (the seam, once), not a stop",
             (len(seen["unread"]), held is None), (1, True))
    check("N22 ...and the words are filed for the role as they were", driver.state["pending_words"].get(DISPATCH) == "stop please")
    seen["unread"].clear()
    open_question("s1_review", "These are the sources I found.\n\n" + driver.priced_section("s1.review", [
        {"answer": "agree", "says": "agree"}, {"answer": "flip", "says": "flip"}, {"answer": "unavailable", "says": "access"}]))
    held = say("stop")
    check_eq("N22 at `s1_review` `stop` is the review's words: `record_review` as today, no stop, no unread",
             (seen["review"], held, seen["unread"]), (["stop"], None, []))

    # F1 (critic t-684): the S1 no-diff halt keeps what the scout reported and says `again`, like every other halt kind
    (task_root2 / "work").mkdir(parents=True, exist_ok=True)
    (task_root2 / "work" / "context-manifest.json").write_text(json.dumps({"implementation": {"source": "none"}}), encoding="utf-8")
    scout_digest = "qa-scout S1 all · halt\nR-7 · blocked · the capability the scout needs is unavailable\n"
    nodiff = driver.halt_text("S1", "qa-scout", scout_digest)
    check_in("F1 the no-diff lead is still the scout's question", "No implementation was found for QA-9.", nodiff)
    check_in("F1 the no-diff halt keeps `What it reported:` and the row's own reason",
             "What it reported:\n- R-7 — the capability the scout needs is unavailable", nodiff)
    # the lead (above the priced answers) is what says `again`; the `not built yet` answer's own words (PC-2) end on "start the same story again"
    check_not_in("F1 a first no-diff halt does not say `again` in its lead", "again", str(nodiff).split("## What each answer")[0])
    check_in("F1 the no-diff lead still ends on the decision, above the prices",
             "Testing without grounding is a decision, so pick one:\n\n## What each answer costs and does", nodiff)
    check_eq("F1 the no-diff options keep their priced tokens exactly (only `stop` carries a token)", tuple(nodiff.priced), ("stop",))
    check("F1 the answers are still offered (change, lives, ungrounded, not built yet), in the PC-2 words",
          all(w in str(nodiff) for w in ("give me the change", "name where it already lives", "go on with the requirements only",
                                         "the code for this story is not written yet")), str(nodiff))
    again_text = driver.halt_text("S1", "qa-scout", scout_digest, again=True)
    check_in("F1 a second no-diff halt says the scout stopped on it again", "The scout stopped on it again.", again_text)
    check_in("F1 ...and keeps the rows", "- R-7 — the capability the scout needs is unavailable", again_text)
    bare = driver.halt_text("S1", "qa-scout", "qa-scout S1 all · halt\n")
    check_in("F1 no rows: the no-reason sentence of the other kinds, no `What it reported:` block",
             "It gave no reason in its report; its own words are in the file named below.", bare)
    check_not_in("F1 no rows: no `What it reported:` block", "What it reported:", bare)

    # ---- HF2-7 part 2 (GW1-21): one open blocker stops; the cards and the answer block have one builder each ----------
    import ast  # noqa: E402
    import re  # noqa: E402
    import test_question_register as TQR  # noqa: E402  (the F-12586 fixture of part 1: reused, not copied)

    src = Path(QS.__file__).read_text(encoding="utf-8")
    T1 = ("some of these questions are marked as blocking: the plan or the cases written next depend on their answers, "
          "so that work waits for them")
    T2 = "  - it is not said whether the work can go on without this answer, so the factory treats it as blocking."
    T9 = ("A question marked as blocking is settled only by a line with its id, or passed with `go on`; "
          "words alone go to the role, and the question is asked again.")
    ASKED_AGAIN = "its text changed after your answer, so it is asked again"
    ONLY_BOTH = "An answer that is only `go on`, or only `stop`, is read as that word."
    ONLY_STOP = "An answer that is only `stop` is read as that word."

    def f12586_root(**kw) -> Path:
        root = fresh()
        TQR.f12586_story(root, **kw)
        return root

    def edit_row(root: Path, qid: str, **changes) -> None:
        path = root / "work" / "requirements-readiness.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data["open_questions"]:
            if row["id"] == qid:
                row.update(changes)
        path.write_text(json.dumps(data), encoding="utf-8")

    def card_count(text: str) -> int:
        return len(re.findall(r"^- \*\*Q\d+\*\*", text, re.M))

    # K1 (H8, H15, H22): who blocks
    root = f12586_root()
    got = QS.blocking_stop(root)
    check_eq("K1 hf2-7: F-12586 with no answers stops: the blockers Q3 and Q5 and the unmarked Q4 (no severity), not the major/minor ones",
             (got["stop"], got["ids"], got["unmarked"], got["reasons"]), (True, ["Q3", "Q4", "Q5"], ["Q4"], []))
    before_hash = tree_hash(root)
    QS.blocking_stop(root)
    QS.open_cards(root)
    QS.answer_block(root, ("stop",))
    check_eq("K1 hf2-7: the three readers write nothing into the task folder (FR-45)", tree_hash(root), before_hash)
    done =QS.QR.record_answers(root, TQR.WORDS_1, "S2 stop", "person")
    after = QS.blocking_stop(root)
    check_eq("K1 hf2-7: after words 1 (Q3 kept open until the report, the rest answered) nothing blocks - a held deferral is not an open blocker (H15)",
             (len(done["recorded"]), done["deferred"], after["stop"], after["ids"], after["unmarked"]), (4, ["Q3"], False, [], []))
    edit_row(root, "Q5", question="what should happen for Q5 when the payload is empty?")
    again = QS.blocking_stop(root)
    check_eq("K1 hf2-7: Q5's text changes after its answer: the answer no longer holds, the stop is back for Q5 alone",
             (again["stop"], again["ids"], again["unmarked"]), (True, ["Q5"], []))
    edit_row(root, "Q3", question="what should happen for Q3 when the payload is empty?")
    check_eq("K1 hf2-7 H15/H43: a deferred blocker whose text changed is open again (it is asked, and it blocks)",
             QS.blocking_stop(root)["ids"], ["Q3", "Q5"])
    odd = f12586_root()
    edit_row(odd, "Q2", severity="Blocker")
    edit_row(odd, "Q1", severity=7)
    check_eq("K1 hf2-7 H8: `Blocker` (wrong case) and a number are not marked: they block, and are said to be unmarked",
             (QS.blocking_stop(odd)["ids"], QS.blocking_stop(odd)["unmarked"]), (["Q1", "Q2", "Q3", "Q4", "Q5"], ["Q1", "Q2", "Q4"]))
    nothing = fresh()
    got = QS.blocking_stop(nothing)
    check("K1 hf2-7 H22: no register: no stop, and a line says why", got["stop"] is False and got["ids"] == [] and len(got["reasons"]) == 1
          and "no blocking question to stop on" in got["reasons"][0], str(got))
    story(nothing, [])
    check_eq("K1 hf2-7: a register with no question: no stop", QS.blocking_stop(nothing)["stop"], False)
    broken = fresh()
    (broken / "work").mkdir(parents=True)
    (broken / "work" / "requirements-readiness.json").write_text("{not json", encoding="utf-8")
    got = QS.blocking_stop(broken)
    check("K1 hf2-7 H2: a register that cannot be read stops nothing and says so (no crash)",
          got["stop"] is False and "could not be read" in " ".join(got["reasons"]), str(got))
    unreadable = f12586_root()
    (unreadable / "work" / "question-answers.jsonl").mkdir()
    check_eq("K1 hf2-7 H2: an answers file that cannot be read leaves every question open: the blockers stop",
             (QS.blocking_stop(unreadable)["stop"], QS.blocking_stop(unreadable)["ids"]), (True, ["Q3", "Q4", "Q5"]))
    original_load = QS.QR.load
    QS.QR.load = lambda *a, **k: (_ for _ in ()).throw(KeyError("load exploded"))
    try:
        got, err = safe(QS.blocking_stop, fresh())
        check("K1 hf2-7: `load` raising: no stop, a reason, no exception", not err and got["stop"] is False and got["reasons"], err)
        cards, err = safe(QS.open_cards, fresh())
        block, err2 = safe(QS.answer_block, fresh(), ("stop",))
        check_eq("K1 hf2-7: `load` raising: no cards and no block", (cards, block, err, err2), ([], "", "", ""))
    finally:
        QS.QR.load = original_load

    # K2 (H8, H15, H26, H43): the blocking batch
    root = f12586_root()
    text = QS.batch_text(root, "blocking", stub_card())
    check_in("K2 hf2-7: T1 is the first line of `Why it stops:`, and no reason code reaches the person", "Why it stops: " + T1 + ".", text)
    check_not_in("K2 hf2-7: ...the code `blocking` as a bare word never stands in the text", "Why it stops: blocking", text)
    check("K2 hf2-7: T2 stands once, under Q4 and above Q5 - the one question with no severity",
          text.count(T2) == 1 and text.index("**Q4**") < text.index(T2) < text.index("**Q5**"))
    check("K2 hf2-7: the blocking note T9 stands under the answer block",
          text.count(T9) == 1 and text.index(T9) > text.index("## How to answer") > text.rindex("**Q5**"))
    check_in("K2 hf2-7: the batch counts all five, blockers and others in one packet", "5 questions to decide - one batch", text)
    check_not_in("K2 hf2-7: another reason has no T9 line", "marked as blocking is settled only", QS.batch_text(root, "over_threshold", stub_card()))
    QS.QR.record_answers(root, TQR.WORDS_1, "S2 stop", "person")
    check_eq("K2 hf2-7: every question answered or kept open and holding: no batch at all", QS.batch_text(root, "blocking", stub_card()), "")
    edit_row(root, "Q5", question="what should happen for Q5 when the payload is empty?")
    edit_row(root, "Q3", question="what should happen for Q3 when the payload is empty?")
    text = QS.batch_text(root, "blocking", None, TIME)
    check("K2 hf2-7 H43: the changed Q5 and the changed deferred Q3 are in the batch, no held answer is",
          "**Q5**" in text and "**Q3**" in text and not any(f"**{gone}**" in text for gone in ("Q1", "Q2", "Q4")))
    check_eq("K2 hf2-7: ...and each says why it is asked again", text.count(ASKED_AGAIN), 2)
    check_in("K2 hf2-7 H45: `Your answer settled N` counts what still holds - Q1, Q2, Q4 and none of the two changed ones",
             "Your answer settled 3 questions, and they are not asked again.", text)
    check_in("K2 hf2-7: the re-stop is the re-stop", f"still open after your answer of {TIME}", text)
    check_in("K2 hf2-7 H26: a re-stop for a blocker carries the blocking note again", T9, text)
    root = f12586_root()
    QS.QR.record_answers(root, "Q3: a\nQ5: a\n", "S2 stop", "person")
    text = QS.batch_text(root, "blocking", stub_card(), TIME)
    check("K2 hf2-7 H26: a blocker the person left out (Q4) is asked again: Q1, Q2 and Q4 stay, with the blocking note",
          card_count(text) == 3 and "**Q4**" in text and T9 in text and "Your answer settled 2 questions" in text, text)
    answered = f12586_root()
    QS.QR.record_answers(answered, "Q1: not needed\nQ2: a\nQ3: until the report\n", "S2 stop", "person")
    text = QS.batch_text(answered, "blocking", stub_card())
    check("K2 hf2-7: answered, not-needed and held-deferred questions are not in the batch; Q4 and Q5 are",
          all(f"**{gone}**" not in text for gone in ("Q1", "Q2", "Q3")) and "**Q4**" in text and "**Q5**" in text)

    # K3 (FR-6): the texts a person reads pass the machine check
    root = f12586_root()
    real_text = QS.batch_text(root, "blocking")
    check_eq("K3 hf2-7: human_text finds nothing wrong with the blocking batch (stub cards, no price section)",
             human_text.problems(QS.batch_text(root, "blocking", stub_card())), [])
    check_eq("K3 hf2-7: ...nor with the blocking batch of the real gate cards", human_text.problems(real_text), [])
    check_eq("K3 hf2-7: ...nor with the cards and the halt's answer block (`stop` only) taken apart and put together",
             human_text.problems("\n".join(QS.open_cards(root)) + "\n\n" + QS.answer_block(root, ("stop",))), [])
    check_eq("K3 hf2-7: ...nor with the re-stop of a changed answer",
             human_text.problems(QS.batch_text(answered, "blocking", None, TIME)), [])

    # K4 (H23): the boundary of the count is NOT the boundary of the blocker
    flat = fresh()
    story(flat, many(8))
    check_eq("K4 hf2-7: 0 blockers among 8 major questions: no blocking stop (the count threshold is another question)",
             QS.blocking_stop(flat)["stop"], False)
    one = fresh()
    story(one, [dict(row, severity="blocker") if row["id"] == "Q1" else row for row in many(8)])
    got = QS.blocking_stop(one)
    check_eq("K4 hf2-7: exactly 1 blocker among 8: it stops, and it is the one", (got["stop"], got["ids"], got["unmarked"]), (True, ["Q1"], []))
    text = QS.batch_text(one, "blocking", stub_card())
    check("K4 hf2-7: 1 blocker + 7 others: ONE packet of 8 cards, one answer block",
          card_count(text) == 8 and "8 questions to decide - one batch" in text and text.count("## How to answer") == 1)
    lone = fresh()
    story(lone, [dict(many(1)[0], severity="blocker")])
    check_eq("K4 hf2-7: a lone blocker is a packet of one", (QS.blocking_stop(lone)["ids"], card_count(QS.batch_text(lone, "blocking", stub_card()))),
             (["Q1"], 1))
    long = fresh()
    story(long, [dict(row, severity="blocker") if row["id"] == "Q1" else row for row in many(201)], total=400)
    text = QS.batch_text(long, "blocking", stub_card())
    check("K4 hf2-7 H23: 1 blocker + 200 others: all 201 cards, no cap", card_count(text) == 201 and "201 questions to decide" in text)

    # K5: the answer block, one builder
    root = f12586_root()
    both = QS.answer_block(root, ("go on", "stop"))
    check_in("K5 hf2-7: at the stop of the questions the whole `go on` / `stop` is read as that word", ONLY_BOTH, both)
    stop_only = QS.answer_block(root, ("stop",))
    check("K5 hf2-7: at a halt only `stop` is; `go on` is not offered there",
          ONLY_STOP in stop_only and "go on" not in stop_only, stop_only)
    plain = QS.answer_block(root)
    check("K5 hf2-7: with nothing offered there is no such sentence", "An answer that is" not in plain and plain.startswith("## How to answer\n"), plain)
    check_in("K5 hf2-7: the block offers `until the report` and says what it does", "  <question id>: until the report", both)
    check_in("K5 hf2-7: ...and explains it", "keeps the question open without asking it again; the report lists it for you", both)
    check_in("K5 hf2-7: the example is made of open ids", "For example: `Q1: a` and `Q2: not needed`.", both)
    answered_all = fresh()
    story(answered_all, [q("Q1")], answers=[rec("Q1", "answered")])
    check_eq("K5 hf2-7: every question answered: an empty block", QS.answer_block(answered_all, ("stop",)), "")
    check_eq("K5 hf2-7 H22: no register: an empty block", QS.answer_block(fresh(), ("go on", "stop")), "")
    check_eq("K5 hf2-7: the batch's block is the builder's block (priced: both words; the block text is the builder's, byte for byte)",
             QS.batch_text(root, "blocking", stub_card(), priced=priced_in).split("\n## How to answer\n")[1].split(T9)[0].rstrip("\n"),
             QS.answer_block(root, ("go on", "stop")).split("## How to answer\n")[1].rstrip("\n"))
    check_not_in("K5 hf2-7: the batch without a price section offers no whole word",
                 "An answer that is", QS.batch_text(root, "blocking", stub_card()))
    check_eq("K5 hf2-7: the block is written once in question_stop.py", src.count("## How to answer"), 1)

    # K6 (AR-15): one renderer of the cards
    tree = ast.parse(src)
    callers = [fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
               for call in ast.walk(fn) if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "_card_lines"]
    check_eq("K6 hf2-7: `_card_lines` is called once, inside open_cards", callers, ["open_cards"])
    original_cards = QS.open_cards
    QS.open_cards = lambda *a, **k: ["- **Q1** the card open_cards made", "  - SENTINEL"]
    try:
        check_in("K6 hf2-7: the batch's cards ARE open_cards' (a replaced open_cards shows in the batch)", "SENTINEL",
                 QS.batch_text(root, "blocking", stub_card()))
    finally:
        QS.open_cards = original_cards
    named = fresh()
    story(named, [q("Q1"), q("Q2")], pipeline={"gates": {"A": {"decision": "approved", "authorization_source": "Q2 is a hard one"}}})
    check("K6 hf2-7: the `named` line is in open_cards and in the batch alike",
          any("no answer for it" in line for line in QS.open_cards(named, stub_card())) and "no answer for it" in QS.batch_text(named, "x", stub_card()))
    calls = []
    check_eq("K6 hf2-7: open_cards numbers the cards 1.. in register order, only the open ones (a held answer is skipped)",
             (QS.open_cards(answered, stub_card(calls)) and calls), [("Q4", 1), ("Q5", 2)])
    check_eq("K6 hf2-7: open_cards of a story with nothing open, and of no register, is []",
             (QS.open_cards(answered_all), QS.open_cards(fresh())), ([], []))
    check_in("K6 hf2-7: the real gate card shows the T2 line for the unmarked one", T2, "\n".join(QS.open_cards(f12586_root())))
    check_eq("K6 hf2-7 AR-13: question_stop holds no second definition of `settled` / `open` and reads severity once (for the mark)",
             (src.count("SETTLED_STATUSES"), src.count('("open", "named")'), src.count('"severity"')), (0, 0, 1))
    check_eq("K6 hf2-7: OPEN_STATUSES here is the register's own tuple (a reference, not a copy)", QS.OPEN_STATUSES is QS.QR.OPEN_STATUSES, True)

    # K7 (H45): the count reads the one definition of "open"
    changed = fresh()
    story(changed, [q(f"Q{i}", [f"R-{i}"]) for i in range(1, 6)], answers=[dict(rec("Q5", "answered"), row_hash="a" * 64)])
    found = QS.over_threshold(changed, {})
    check("K7 hf2-7 H45: 4 open + 1 answered on a changed row: the count is 5, and the 5 requirements are counted",
          found["count"] == 5 and found["requirements_open"] == 5, str(found))
    text = QS.batch_text(changed, "over_threshold", stub_card())
    check("K7 hf2-7: the packet says 5 questions to decide and shows 5 cards", "5 questions to decide" in text and card_count(text) == 5)
    check_in("K7 hf2-7: ...and the threshold's own line counts 5", "5 questions are open.", text)
    held = fresh()
    story(held, [q(f"Q{i}", [f"R-{i}"]) for i in range(1, 6)], answers=[dict(rec("Q5", "answered"), row_hash=QS.QR.load(changed)["questions"][4]["row_hash"])])
    check_eq("K7 hf2-7: the same answer on the bytes it was given holds: the count is 4", QS.over_threshold(held, {})["count"], 4)

    # the temporal edge: a `before_value_needed` answer is an open blocker before part 3 gives it a note; its card is shown all the same
    before = fresh()
    story(before, [dict(q("Q1"), severity="blocker", before={"value": "unknown", "where": "x"}), q("Q2")])
    fresh_hash = QS.QR.load(before)["questions"][0]["row_hash"]
    story(before, [dict(q("Q1"), severity="blocker", before={"value": "unknown", "where": "x"}), q("Q2")],
          answers=[dict(rec("Q1", "answered"), reading="b", row_hash=fresh_hash)])
    check_eq("temporal: an answer `b` while `before` is unknown is an open blocker (the card is never hidden), with or without a note on it",
             (QS.blocking_stop(before)["ids"], any("**Q1**" in line for line in QS.open_cards(before, stub_card()))), (["Q1"], True))
finally:
    cleanup(tmp)

finish("question_stop")
