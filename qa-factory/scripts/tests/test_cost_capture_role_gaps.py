"""HF7-1 / HF7-2 (t-1518 DP-1): a role's gap is found by ROLE and by COUNT, not by the spelling of its name.

The journal's `subagent_stop` line names a role by the bare name (`qa-scout`); the cost file's `agents[]`
names it as the host does (`qa-factory:qa-scout`). The old comparison read the two as different roles and
named every role of every session as a gap. `cost_capture.incomplete_roles` compares through
`hooklib.role_name` and counts dispatches against files, so one role in two spellings is one role and a lost
one of several dispatches is still seen. The fixture is SYNTHETIC (see its README.txt).
"""
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_capture as C
import runtime_paths as RP
from harness import temp_project, cleanup, run_capture

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "synthetic-role-gaps"
MONEY_KEYS = {"cost", "subtotal_usd", "total_cost_usd", "priced_subtotal_usd", "priced_subtotal_exact_usd",
              "price_low_usd", "price_high_usd"}
DOLLAR_DIGIT = re.compile(r"\$\s?\d")
PERSONAL_PATH = re.compile(r"C:\\Users\\|/Users/|/home/", re.IGNORECASE)


def load_fixture():
    sessions = {s["session_id"]: s for s in json.loads((FIXTURE / "sessions.json").read_text(encoding="utf-8"))["sessions"]}
    journal = [json.loads(line) for line in (FIXTURE / "journal.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    return sessions, journal


def raw_gap(agents, journal, session):
    """The comparison the fix replaces (the mutant): the journal's name against the files' names, as written."""
    seen = {a["agent"] for a in agents}
    out = []
    for rec in journal:
        if rec.get("event") == "subagent_stop" and rec.get("session") == session and rec.get("agent") and rec["agent"] not in seen:
            out.append(rec["agent"])
            seen.add(rec["agent"])
    return out


def stop(role, session, dispatch=None, ts="2026-09-20T19:24:00+00:00"):
    rec = {"ts": ts, "event": "subagent_stop", "agent": role, "session": session}
    if dispatch is not None:
        rec["dispatch"] = dispatch
    return rec


def file_of(role, tokens=100, n=0):
    return {"agent": role, "file": f"agent-{n}.jsonl", "tokens": tokens}


def money_findings(root: Path):
    """What a fixture directory carries that it must not: a money field with a non-zero value, `$` + digit,
    a personal path. (`$env:` and `$(` are not money and are not looked for.)"""
    found = []

    def walk(value, where):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in MONEY_KEYS and item not in (None, 0, "0", 0.0):
                    found.append(f"{where}: {key}={item!r}")
                walk(item, where)
        elif isinstance(value, list):
            for item in value:
                walk(item, where)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if DOLLAR_DIGIT.search(text):
            found.append(f"{path.name}: dollar + digit")
        if PERSONAL_PATH.search(text):
            found.append(f"{path.name}: personal path")
        if path.suffix == ".json":
            walk(json.loads(text), path.name)
    return found


def test_fixture_clean_and_control():
    assert money_findings(FIXTURE) == [], money_findings(FIXTURE)
    # negative control: the same check on a copy with one non-zero money field, a `$1.00`, a personal path
    work = Path(tempfile.mkdtemp(prefix="qa-gaps-control-"))
    try:
        for name in ("sessions.json", "journal.jsonl", "README.txt"):
            (work / name).write_text((FIXTURE / name).read_text(encoding="utf-8"), encoding="utf-8")
        assert money_findings(work) == []
        data = json.loads((work / "sessions.json").read_text(encoding="utf-8"))
        data["sessions"][0]["agents"][0]["subtotal_usd"] = "1"
        (work / "sessions.json").write_text(json.dumps(data), encoding="utf-8")
        assert any("subtotal_usd" in f for f in money_findings(work)), money_findings(work)
        (work / "README.txt").write_text("it cost $1.00 in " + "C:" + chr(92) + "Users" + chr(92) + "someone", encoding="utf-8")
        found = money_findings(work)
        assert any("dollar" in f for f in found) and any("personal" in f for f in found), found
    finally:
        cleanup(work)


def test_k1_k2_one_role_two_spellings_is_one_role():
    sessions, journal = load_fixture()
    for sid, session in sessions.items():
        assert C.incomplete_roles(session["agents"], journal, sid) == [], (sid, C.incomplete_roles(session["agents"], journal, sid))
    # the mutant (raw comparison) must name something on the same data, or the fixture proves nothing
    mutant = raw_gap(sessions["synthetic-session-a"]["agents"], journal, "synthetic-session-a")
    assert len(mutant) == 3, mutant
    for sid in ("synthetic-session-b", "synthetic-session-c", "synthetic-session-d"):
        assert len(raw_gap(sessions[sid]["agents"], journal, sid)) == 1, sid


def test_k3_a_lost_one_of_four_dispatches_is_seen():
    sessions, journal = load_fixture()
    agents = [a for a in sessions["synthetic-session-a"]["agents"] if a["file"] != "agent-a6.jsonl"]
    roles = C.incomplete_roles(agents, journal, "synthetic-session-a")
    assert [(r["agent"], r["missing"]) for r in roles] == [("qa-case-designer", 1)], roles   # the journal's own spelling
    assert len(roles[0]["seen_at"]) == 4, roles
    names = list(dict.fromkeys(r["agent"] for r in roles))
    assert names == ["qa-case-designer"], names


def test_k4_edges():
    sess = "s1"
    one_file = [file_of("qa-factory:qa-scout")]
    # no journal records: nothing to check against the files, no gap
    assert C.incomplete_roles(one_file, [], sess) == []
    # a role in the journal with no file at all: its dispatches are the gap (a dispatch with no transcript is never free)
    roles = C.incomplete_roles([], [stop("qa-scout", sess, "d1"), stop("qa-scout", sess, "d2")], sess)
    assert [(r["agent"], r["missing"]) for r in roles] == [("qa-scout", 2)], roles
    # not an object / not a string agent / empty tail / another session's line / nameless: skipped one by one
    junk = [None, 7, "text", [], {"event": "subagent_stop", "session": sess, "agent": 5},
            stop("qa-factory:", sess, "x"), stop("qa-ghost", "other-session", "y"),
            {"event": "subagent_stop", "session": sess, "agent": ""}, {"event": "stage_gate", "session": sess, "agent": "qa-ghost"}]
    assert C.incomplete_roles(one_file, junk + [stop("qa-scout", sess, "d1")], sess) == []
    # a repeated dispatch id (a retry after a refusal) is one dispatch
    assert C.incomplete_roles(one_file, [stop("qa-scout", sess, "d1"), stop("qa-scout", sess, "d1")], sess) == []
    # a file with no usage is a gap as before and is not a cover for the journal's dispatch of its role
    zero = [file_of("qa-factory:qa-scout", tokens=0)]
    roles = C.incomplete_roles(zero, [stop("qa-scout", sess, "d1")], sess)
    assert [(r["agent"], r["missing"]) for r in roles] == [("qa-factory:qa-scout", 1), ("qa-scout", 1)], roles
    assert C.incomplete_roles(zero, [], sess) == [{"agent": "qa-factory:qa-scout", "missing": 1, "seen_at": []}]
    # journal lines that are not a list at all
    assert C.incomplete_roles(one_file, None, sess) == []
    assert C.incomplete_roles(None, [stop("qa-scout", sess, "d1")], sess)[0]["missing"] == 1


def test_k5_awkward_inputs():
    sess = "s1"
    # two namespaces of one bare name merge by name; the count still catches 2 dispatches on 1 file
    roles = C.incomplete_roles([file_of("a:qa-scout")], [stop("a:qa-scout", sess, "d1"), stop("b:qa-scout", sess, "d2")], sess)
    assert [(r["agent"], r["missing"]) for r in roles] == [("a:qa-scout", 1)], roles
    # dispatch "" / null: each such line is its own dispatch (more dispatches, the safe side)
    lines = [stop("qa-scout", sess), {**stop("qa-scout", sess), "dispatch": ""}, {**stop("qa-scout", sess), "dispatch": None}]
    roles = C.incomplete_roles([file_of("qa-factory:qa-scout")], lines, sess)
    assert [r["missing"] for r in roles] == [2], roles
    # an agents[] entry without an agentType carries the file stem as its name: it matches no role, a gap is named
    stem = [file_of("agent-abc123")]
    roles = C.incomplete_roles(stem, [stop("qa-scout", sess, "d1")], sess)
    assert [(r["agent"], r["missing"]) for r in roles] == [("qa-scout", 1)], roles
    # entries that are not objects, or have no name, are not files
    assert C.incomplete_roles(["x", None, {"tokens": 5}], [], sess) == []


def test_gap_places_of_journal_gaps_only():
    roles = [{"agent": "qa-factory:qa-scout", "missing": 1, "seen_at": []},
             {"agent": "qa-ghost", "missing": 2, "seen_at": ["2026-09-20T19:24:00+00:00", "not a time", "2026-09-20T19:25:00+00:00"]}]
    activities = [{"activity_id": "act1", "type": "story", "task": "SYN-1",
                   "segments": [{"segment_id": "s", "start_time": "2026-09-20T19:20:00+00:00", "end_time": None}]}]
    where = C._gap_places(roles, activities)
    assert where == [{"agent": "qa-ghost", "activities": ["act1", "unclassified"], "missing": 2}], where
    assert C._gap_places([], activities) == []        # an empty outcome is the empty list, not a missing field
    assert C._gap_places(roles, []) == [{"agent": "qa-ghost", "activities": ["unclassified"], "missing": 2}]


# --- the whole capture on a temp project (the join of the journal, the files and the document) ---------------

SESSION = "synthetic-capture-session"
USAGE = {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 0,
         "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0}}


def _line(**kw):
    return json.dumps(kw, ensure_ascii=False)


def build_capture(root: Path, files, journal_lines):
    transcripts = root / "transcripts"
    sub_dir = transcripts / SESSION / "subagents"
    sub_dir.mkdir(parents=True)
    main_path = transcripts / f"{SESSION}.jsonl"
    main_path.write_text("\n".join([
        _line(type="user", isSidechain=False, promptId="p1", uuid="u0", timestamp="2026-09-20T19:22:00Z",
              message={"role": "user", "content": "synthetic prompt"}),
        _line(type="assistant", isSidechain=False, requestId="req-main", uuid="u1", timestamp="2026-09-20T19:22:05Z",
              message={"model": "claude-sonnet-5", "usage": USAGE, "content": [
                  {"type": "tool_use", "id": "t1", "name": "Write",
                   "input": {"file_path": "qa-factory/artifacts/SYN-1/understanding.md"}}]}),
    ]) + "\n", encoding="utf-8")
    for n, (role, with_usage) in enumerate(files):
        rows = [_line(type="user", isSidechain=True, uuid=f"u{n}", timestamp="2026-09-20T19:22:10Z",
                      message={"role": "user", "content": "synthetic role prompt"})]
        if with_usage:
            rows.append(_line(type="assistant", isSidechain=True, requestId=f"req-{n}", uuid=f"a{n}",
                              timestamp="2026-09-20T19:22:20Z", message={"model": "claude-sonnet-5", "usage": USAGE, "content": []}))
        (sub_dir / f"agent-{n}.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
        (sub_dir / f"agent-{n}.meta.json").write_text(json.dumps({"agentType": role, "description": "synthetic"}), encoding="utf-8")
    activities = root / "qa-factory" / "state" / "activities"
    activities.mkdir(parents=True)
    (activities / f"{SESSION}.json").write_text(json.dumps({
        "schema_version": 1, "session_id": SESSION,
        "activities": [{"activity_id": "act1", "type": "story", "task": "SYN-1", "start_event_id": "e1",
                        "start_time": "2026-09-20T19:21:00Z", "end_event_id": None, "end_time": None, "evidence_ref": None,
                        "status": "open", "segments": [{"segment_id": "seg1", "start_event_id": "e1",
                                                        "start_time": "2026-09-20T19:21:00Z", "end_event_id": None, "end_time": None}]}],
        "active_stack": ["act1"], "processed_events": {}, "usage_completeness": "unknown"}), encoding="utf-8")
    if journal_lines is not None:
        journal = RP.record(root, "journal.jsonl")
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("\n".join(journal_lines) + "\n", encoding="utf-8")
    return main_path


def capture(files, journal_lines, journal_dir=False):
    root = temp_project()
    try:
        main_path = build_capture(root, files, journal_lines)
        if journal_dir:
            journal = RP.record(root, "journal.jsonl")
            journal.parent.mkdir(parents=True, exist_ok=True)
            journal.mkdir()
        result = run_capture(root, SESSION, main_path)
        assert result.returncode == 0, result.stderr
        doc = json.loads((root / "qa-factory" / "state" / "cost" / f"{SESSION}.json").read_text(encoding="utf-8"))
        return doc, result.stderr
    finally:
        cleanup(root)


def test_capture_join_names_gaps_by_role_and_count():
    when = "2026-09-20T19:24:00+00:00"
    files = [("qa-factory:qa-scout", True), ("qa-factory:qa-case-designer", True)]
    journal = [_line(**stop("qa-scout", SESSION, "d1", when)),
               _line(**stop("qa-case-designer", SESSION, "d2", when)),
               _line(**stop("qa-case-designer", SESSION, "d3", when)),
               "this line is not json {",                            # one bad line alone is skipped
               _line(**stop("qa-ghost", SESSION, "d4", when)),       # read AFTER the bad line (the old read stopped there)
               _line(**stop("qa-scout", "another-session", "d9", when))]
    doc, stderr = capture(files, journal)
    assert doc["incomplete_agents"] == ["qa-case-designer", "qa-ghost"], doc["incomplete_agents"]
    assert doc["incomplete_where"] == [{"agent": "qa-case-designer", "activities": ["act1"], "missing": 1},
                                       {"agent": "qa-ghost", "activities": ["act1"], "missing": 1}], doc["incomplete_where"]
    assert "journal could not be read" not in stderr, stderr
    # the whole journal is covered by the files: an empty outcome, the field is present and empty
    clean = [_line(**stop("qa-scout", SESSION, "d1", when)), _line(**stop("qa-case-designer", SESSION, "d2", when))]
    doc, _ = capture(files, clean)
    assert doc["incomplete_agents"] == [] and doc["incomplete_where"] == [], (doc["incomplete_agents"], doc["incomplete_where"])
    # a zero-usage file is a gap as before: named as the file spells it, its place stays in agents[] (not in the field)
    doc, _ = capture([("qa-factory:qa-scout", False)], None)
    assert doc["incomplete_agents"] == ["qa-factory:qa-scout"] and doc["incomplete_where"] == [], doc["incomplete_agents"]


def test_capture_journal_missing_is_silent_and_unreadable_is_one_line():
    files = [("qa-factory:qa-scout", True)]
    doc, stderr = capture(files, None)                         # no journal file: not a factory session's record, no word
    assert doc["incomplete_agents"] == [] and doc["incomplete_where"] == []
    assert "journal could not be read" not in stderr, stderr
    doc, stderr = capture(files, None, journal_dir=True)       # the journal exists and cannot be opened
    assert doc["incomplete_agents"] == [] and doc["incomplete_where"] == []
    assert stderr.count("the journal could not be read; roles with no transcript were not checked") == 1, stderr


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print("PASS test_cost_capture_role_gaps (%d tests)" % len(tests))
    print("=== test_cost_capture_role_gaps: %d/%d ok ===" % (len(tests), len(tests)))


if __name__ == "__main__":
    main()
