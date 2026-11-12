"""HF7-2 (t-1518 DP-2): a role's gap is shown on the rows it belongs to, and once.

`group` used to put every role named in a session's `incomplete_agents` on EVERY label of that session, so a
false gap (or a true one) showed on "Unclassified", on "Doctor" and on the story alike. Now a role lands on
the label its own rows have; a gap with no request rows lands on the label of the activity it ran in; and
when one document is cut into parts (a price's rows and the rest) that second kind is attached once per
document, not once per part. The fixture is SYNTHETIC (see its README.txt).
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import factory_dashboard as D
from dashboard_cost_groups import group, gap_places, attach_rowless_gaps
from harness import cleanup
from test_cost_capture_role_gaps import money_findings

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "synthetic-gap-rows"
STORY = "SYN-1"


def doc(name):
    return json.loads((FIXTURE / name).read_text(encoding="utf-8"))


def names_by_label(tasks):
    return {label: sorted(v["incomplete_agents"]) for label, v in tasks.items()}


def where(by_task, name):
    return sorted(label for label, v in by_task.items() if name in v["incomplete_agents"])


def priced(sid, task=STORY):
    """A stand-in price answer: its sessions, no figure (the money is not under test)."""
    return {task: {"sessions": [{"session": sid}], "price_low_usd": None, "price_high_usd": None}}


def test_fixture_has_no_money():
    assert money_findings(FIXTURE) == [], money_findings(FIXTURE)
    work = Path(tempfile.mkdtemp(prefix="qa-gap-rows-control-"))
    try:
        data = doc("doc-before.json")
        data["requests"][0]["valuation"]["subtotal_usd"] = "1"
        (work / "doc.json").write_text(json.dumps(data), encoding="utf-8")
        assert money_findings(work), "a non-zero money field must be found"
    finally:
        cleanup(work)


def test_k1_world_before_names_land_on_their_own_rows():
    tasks, _days = group([doc("doc-before.json")])
    got = names_by_label(tasks)
    assert got[STORY] == ["qa-case-designer", "qa-critic", "qa-scout"], got
    assert got["Unclassified"] == [], got              # the rows of no activity carry no role's work
    assert set(got) == {STORY, "Unclassified"}, got


def test_k2_priced_path_each_name_on_exactly_one_row():
    d = doc("doc-before.json")
    driver = {d["session_id"]: {"task": STORY, "rows": []}}
    out = D.task_groups([d], [], priced(d["session_id"]), {}, driver)
    for name in d["incomplete_agents"]:
        assert where(out["by_task"], name) == [STORY], (name, where(out["by_task"], name))


def test_k3_doctor_session():
    tasks, _ = group([doc("doc-doctor.json")])
    got = names_by_label(tasks)
    assert got["Doctor"] == ["qa-doctor"] and got["Unclassified"] == [], got


def test_k4_journal_gap_places():
    base = doc("doc-journal-gap.json")
    # its place is the activity of the history, which has rows
    got = names_by_label(group([base])[0])
    assert got[STORY] == ["qa-ghost"] and got["Doctor"] == [] and got["Unclassified"] == [], got
    # the same through the priced path
    out = D.task_groups([base], [], priced(base["session_id"]), {}, {base["session_id"]: {"task": STORY, "rows": []}})
    assert where(out["by_task"], "qa-ghost") == [STORY], where(out["by_task"], "qa-ghost")
    # an activity that is nowhere among by_activity: Unclassified
    odd = copy.deepcopy(base)
    odd["incomplete_where"] = [{"agent": "qa-ghost", "activities": ["act-nowhere"], "missing": 1}]
    assert where(group([odd])[0], "qa-ghost") == ["Unclassified"]
    assert where(D.task_groups([odd], [], priced(odd["session_id"]), {}, {})["by_task"], "qa-ghost") == ["Unclassified"]
    # two candidate activities (a count-based gap): each candidate's label has the name, once
    two = copy.deepcopy(base)
    two["incomplete_where"] = [{"agent": "qa-ghost", "activities": ["act-story", "act-doctor", "act-story"], "missing": 1}]
    assert where(group([two])[0], "qa-ghost") == ["Doctor", STORY]
    # a gap with no activity of the history and no row anywhere near it, priced story: the story's price row
    held = copy.deepcopy(base)
    held["by_activity"]["act-empty"] = {"type": "story", "task": STORY}
    held["incomplete_where"] = [{"agent": "qa-ghost", "activities": ["act-empty"], "missing": 1}]
    out = D.task_groups([held], [], priced(held["session_id"]), {}, {})
    assert where(out["by_task"], "qa-ghost") == [STORY], where(out["by_task"], "qa-ghost")


def test_k5_rowless_gap_once_when_the_history_is_cut_in_two():
    base = doc("doc-journal-gap.json")
    base["requests"].append({"request_key": "gap-c-5", "stream": "orchestrator", "activity_id": "act-story", "task": STORY,
                             "timestamp": "2026-09-22T09:05:00Z", "usage": {"input": 10, "output": 1},
                             "valuation": {"pricing_coverage": "none"}})
    # a chat binding of another task takes the last row from the price: it is nobody's, stays in the rest
    base["chat_bindings"] = [{"task": "SYN-9", "requests": ["gap-c-5"]}]
    out = D.task_groups([base], [], priced(base["session_id"]), {}, {})
    labels = sorted(out["by_task"])
    assert any(l.startswith(STORY + " - tagged only") for l in labels), labels      # both parts hold rows of the story activity
    assert where(out["by_task"], "qa-ghost") == [STORY], where(out["by_task"], "qa-ghost")
    # the same data cut into parts and attached without the once-per-document rule would double it:
    parts, _ = group([base], rowless_gaps=True)
    assert where(parts, "qa-ghost") == [STORY]


def test_k6_awkward_inputs():
    base = doc("doc-journal-gap.json")
    for bad in ("not a list", {"agent": "qa-ghost"}, [None, 3, {"activities": ["act-story"]}, {"agent": 7}]):
        d = copy.deepcopy(base)
        d["incomplete_where"] = bad
        place = gap_places(d)
        # the field is read as absent for this document: the name has no file, so the older-document rule applies:
        # the one story activity of the session
        assert place == {"qa-ghost": {"streams": [], "activities": ["act-story"]}}, (bad, place)
        assert where(group([d])[0], "qa-ghost") == [STORY], bad
    d = copy.deepcopy(base)
    d["incomplete_where"] = [{"agent": "qa-ghost", "activities": "act-story", "missing": 1}]    # activities not a list
    assert gap_places(d)["qa-ghost"]["activities"] == ["unclassified"]
    assert where(group([d])[0], "qa-ghost") == ["Unclassified"]
    # no field, no file, several activities and no story: all of them; none at all: Unclassified (never dropped)
    d = copy.deepcopy(base)
    del d["incomplete_where"]
    d["by_activity"]["act-story"]["type"] = "doctor"
    assert gap_places(d)["qa-ghost"]["activities"] == ["act-story", "act-doctor", "unclassified"]
    d["by_activity"] = {}
    assert gap_places(d)["qa-ghost"] == {"streams": [], "activities": ["unclassified"]}
    assert where(group([d])[0], "qa-ghost") == ["Unclassified"]
    # incomplete_agents not a list: no places, no failure
    d["incomplete_agents"] = "qa-ghost"
    assert gap_places(d) == {}
    # nothing to place: an empty outcome in the same shape
    assert gap_places({"incomplete_agents": []}) == {} and gap_places({}) == {}
    # a file whose rows are folded away (a ledger folded to `carry:` rows): the file's activity is the place
    carried = doc("doc-before.json")
    for row in carried["requests"]:
        row["stream"] = "carry:" + str(row["stream"])
    assert gap_places(carried)["qa-scout"] == {"streams": [], "activities": ["act-story"]}
    # attach with nothing to attach changes nothing
    by_task = {}
    attach_rowless_gaps(by_task, [{"session_id": "x"}, {"requests": []}, {}], {}, set(), None)
    assert by_task == {}


def test_legacy_document_without_a_request_ledger():
    legacy = {"session_id": "synthetic-gaps-legacy", "usage_completeness": "provisional",
              "by_task": {"SYN-1": {"tokens": 10, "cost": None}, "SYN-2": {"tokens": 20, "cost": None}},
              "by_model": {}, "agents": [{"agent": "qa-factory:qa-scout", "file": "agent-l1.jsonl", "tokens": 5, "task": "SYN-2"}],
              "incomplete_agents": ["qa-scout", "qa-ghost"]}
    tasks, _ = group([legacy])
    got = names_by_label(tasks)
    assert got["SYN-2"] == ["qa-ghost", "qa-scout"], got        # the file's own task for the role, no file: every label
    assert got["SYN-1"] == ["qa-ghost"], got


def test_gap_places_rules():
    d = doc("doc-before.json")
    place = gap_places(d)
    assert place["qa-scout"] == {"streams": ["agent-s1.jsonl"], "activities": []}, place
    # a file of the role with no rows: the activity it ran in
    d["requests"] = [r for r in d["requests"] if r["stream"] != "agent-s1.jsonl"]
    assert gap_places(d)["qa-scout"] == {"streams": [], "activities": ["act-story"]}
    # a journal gap named in the field wins over a file of the same role
    d["incomplete_where"] = [{"agent": "qa-scout", "activities": ["unclassified"], "missing": 1}]
    assert gap_places(d)["qa-scout"] == {"streams": [], "activities": ["unclassified"]}


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print("PASS test_dashboard_cost_gap_rows (%d tests)" % len(tests))
    print("=== test_dashboard_cost_gap_rows: %d/%d ok ===" % (len(tests), len(tests)))


if __name__ == "__main__":
    main()
