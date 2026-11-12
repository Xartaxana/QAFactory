#!/usr/bin/env python3
"""The scenario walker (scenario_walk.py) on its hand-assembled fixture `fixtures/synthetic-scenario/` (TD-15.4).

ONE table. The mechanics (NOTE for a facet with no carrier, expected-missing, a missing variant pointer, a world that will not
build, the shared world unchanged, every `op`, `witness_for`) run with a stand-in for the slow `story_step start` (~14 s on a
Windows box) and for the exit gate on the variants; the exit gate and the joint check run for real, once.
The gate doors (question, decision), the delivery assessment and the real `start` are walked by the whole fixture (~30 s here),
which is not in this file.
Run on its own: `python -B scripts/tests/test_scenario_walk.py`.
"""
import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenario_walk as W  # noqa: E402
from harness import FIXTURES, check_eq, check_in, check_not_in, finish, temp_dir  # noqa: E402

SYN = "synthetic-scenario"


def fake_exit_gate(story, entry, copy_root):
    """Stands in for the exit gate over a manifest on disk: refused, naming the key, when one the gate demands is gone."""
    data = json.loads((copy_root / "work" / "context-manifest.json").read_text(encoding="utf-8"))
    return W._outcome([f"required key {k!r} is missing" for k in ("ticket", "acceptance_criteria") if k not in data])


def fake_start(*_args, **_kwargs):
    return subprocess.CompletedProcess([], 0, stdout="dispatched S2-qa-requirements-tester-1 (revision 7)\n", stderr="")


def _raises(call) -> str:
    try:
        call()
    except KeyError as exc:
        return str(exc)
    return ""


def story_dir(base: Path, files: dict) -> Path:
    for name, text in files.items():
        (base / "s" / name).parent.mkdir(parents=True, exist_ok=True)
        (base / "s" / name).write_text(text, encoding="utf-8")
    return base


def package_tree() -> Path:
    base = temp_dir("qa-witness-")
    for name, text in {"scripts/a.py": "import b\n", "scripts/b.py": "from c import x\n", "scripts/c.py": "x = 1\n",
                       "scripts/z.py": "", "scripts/tests/test_scenario_demo.py": "",
                       "scripts/tests/fixtures/stories/demo/story.json":
                           json.dumps({"walk": [{"stage": "S1", "door": {"kind": "exit_gate"}, "facets": ["accepted"]}]})}.items():
        (base / name).parent.mkdir(parents=True, exist_ok=True)
        (base / name).write_text(text, encoding="utf-8")
    return base


def witness(paths, absent=False) -> str:
    keep = {"test_gate.py": {"layer": "gate_named", "covers": ["z.py", "references/r.json"]}}
    return "\n".join(W.witness_for(paths, package_tree(), {"absent": absent, "keep": {} if absent else keep}, {"exit_gate": ["a"]}))


@contextlib.contextmanager
def stand_ins():
    """The slow doors replaced for the block (the harness's run_script is the one `story_step start` goes through)."""
    saved = (W.harness.run_script, W.door_exit_gate)
    W.harness.run_script, W.door_exit_gate = fake_start, fake_exit_gate
    try:
        yield
    finally:
        W.harness.run_script, W.door_exit_gate = saved


def main() -> None:
    story = W.load_story(SYN, FIXTURES)
    fresh = W.load_story(SYN, FIXTURES)       # the entries as the fixture states them (no `final_state`): the not-comparable rows read it
    # the hand-assembled fixture filled its S1 manifest and added impl-diff.txt AFTER the recorded accept, so its hashes no longer
    # match (TD-15 B4): the walk below says `final_state` for S1, as a story's Lead would, and the rows on `fresh` show the other side
    story.walk[0]["final_state"] = True
    world = W.build_world(story)
    before = W.world_hash(world)
    cheap = W.Story(SYN, story.task, story.dir, story.root, story.walk[:2], story.not_walked, story.expected, story.variants)
    with stand_ins():
        stubbed = W.walk(cheap, world)      # handed runs for real over the form, only `start` is a stand-in
        gone = W.copy_world(world)
        (gone / "work" / "impl-diff.txt").unlink()
        handed_gone = W.door_handed(story, story.walk[0], gone, world)
    after = W.world_hash(world)
    kinds = {r.name: r.kind for r in stubbed}

    # item 4: template paths and folders are notes, the recorded dispatch's start arguments reach `start`, the cut is found alone
    seen = []

    def recording_start(*args, **kwargs):
        seen.append(list(args))
        return fake_start()

    tpl = W.copy_world(world)
    form = tpl / "work" / "handoffs" / "S1-qa-scout-1.yaml"
    form.write_text(form.read_text(encoding="utf-8").replace(
        "    required: true\n", "    required: true\n  - path: <cases_root>/<area>/<case>.md\n    what: t\n    required: true\n"
        "  - path: work/evidence/\n    what: f\n    required: true\n", 1), encoding="utf-8")
    events = tpl / "state" / "events.jsonl"
    events.write_text(events.read_text(encoding="utf-8").rstrip("\n") + "\n" + json.dumps(
        {"sequence": 7, "type": "dispatch", "payload": {"id": "S2-qa-requirements-tester-1", "stage": "S2", "execution_kind": "automation",
                                                        "scope": ["TC-1", "TC-2"]}}) + "\n", encoding="utf-8")
    with stand_ins():
        W.harness.run_script = recording_start
        templated = W.door_handed(story, story.walk[0], tpl, tpl)
        start_flags = seen[-1][-4:]
        bare = W.copy_world(world)
        (bare / "work" / "handoffs" / "S1-qa-scout-1.yaml").write_text("inputs:\n  - path: x\n    required: false\n", encoding="utf-8")
        no_inputs = W.door_handed(story, story.walk[0], bare, world)
        no_next = W.door_handed(story, dict(story.walk[0], next=None), bare, world)
    # W1: the recorded project config reaches the project of the world and of every copy; W2: the judged stage and dispatch are held
    import base64
    import exit_gate as EG
    recorded = temp_dir("qa-cfg-")
    (recorded / "state").mkdir()
    config_text = '{"case_id_form": "{ticket}_TC_{nnn}", "cases_root": "test-cases"}'
    (recorded / "state" / "config-at-start.json").write_text(
        json.dumps({"bytes_b64": base64.b64encode(config_text.encode()).decode()}), encoding="utf-8")
    (recorded / "pipeline.json").write_text("{}", encoding="utf-8")
    cfg_world = W.build_world(W.Story("cfg", "T-1", recorded, recorded, [], [], {}, []))
    cfg_copy = W.copy_world(cfg_world)
    asked, real_gate = [], EG.all_errors
    EG.all_errors = lambda role, task, digest, facts: (asked.append((EG.held_stage(), EG.held_dispatch())) or
                                                       (["check_coverage.py: map missing", "other.py: bad"], []))
    try:
        gate_answer = W.door_exit_gate(story, dict(story.walk[0], door={"kind": "exit_gate", "skip_detectors": ["check_coverage.py"]}),
                                       W.copy_world(world))
    finally:
        EG.all_errors = real_gate
    cutworlds: dict = {}
    first, second = W._facet_copy(world, 5, cutworlds), W._facet_copy(world, 5, cutworlds)
    (first / "work" / "written-by-one-facet.txt").write_text("x", encoding="utf-8")
    plain = W.copy_world(world)
    source_file = next(p for p in sorted(world.rglob("*")) if p.is_file())
    copied_file = plain / source_file.relative_to(world)

    broken = story_dir(temp_dir("qa-story-"), {"story.json": "{not json"})
    plain = story_dir(temp_dir("qa-story-"), {"story.json": json.dumps({"id": "x", "task": "T", "walk": []})})
    noroot = story_dir(temp_dir("qa-story-"), {"story.json": json.dumps(
        {"id": "x", "task": "T", "synthetic": True, "root": "nowhere", "walk": [{"stage": "S1", "facets": ["accepted"]}]})})
    try:
        W.load_story("s", broken)
        bad_json = ""
    except W.StoryError as exc:
        bad_json = str(exc)
    try:
        W.load_story("s", plain)
        not_synthetic = ""
    except W.StoryError as exc:
        not_synthetic = str(exc)
    walk_less = W.load_story(SYN, FIXTURES)
    walk_less.walk = [story.walk[0], story.walk[3]]
    walk_less.expected = {"stages": {k: v for k, v in story.expected["stages"].items() if k != "S8"}}
    walk_less.variants = [{"id": "nope", "stage": "S1", "file": "work/context-manifest.json", "op": "del", "pointer": "/no/such"}]
    with stand_ins():
        reds = {r.name: r.kind for r in W.walk(walk_less, world)}
    built = W.results_for("s", noroot)
    ops = temp_dir("qa-ops-")
    (ops / "d.json").write_text(json.dumps({"a": {"b": 1}, "l": [1, 2]}), encoding="utf-8")
    (ops / "w.txt").write_text("old", encoding="utf-8")
    (ops / "with.txt").write_text("new", encoding="utf-8")

    def op(**row):
        failure = W.apply_op(ops, row, ops)
        return failure or json.loads((ops / "d.json").read_text(encoding="utf-8"))

    good = {"stage": "S1", "field": "outcome", "recorded": "accepted", "expected": "refused", "names": ["implementation-only", "R-3"],
            "why": "w", "ref": "find-1", "accepted_by": "Lead"}

    def amended(recorded, rows, errors):
        """The first facet of a one-stage walk judged with `rows` as amendments, the exit door answering with `errors`."""
        exp = {"stages": {"S1": {"outcome": recorded}}, "amendments": rows}
        one = W.Story(SYN, story.task, story.dir, story.root, [dict(story.walk[0], facets=["accepted"])], [], exp, [])
        saved = W.door_exit_gate
        W.door_exit_gate = lambda *_a: W._outcome(errors)
        try:
            return [(r.name.split("/", 1)[1].replace(" (final state)", ""), r.kind, r.detail) for r in W.walk(one, world) if r.kind != "note"]
        finally:
            W.door_exit_gate = saved

    def malformed(**change):
        row = {k: v for k, v in dict(good, **change).items() if v is not None}
        got = W.amendments_of(W.Story(SYN, "T", story.dir, story.root, [], [], {"stages": {"S1": {"outcome": "accepted"}}, "amendments": [row]}, []))
        return got[1][0] if got[1] else ""

    refusal = ["R-3 is implementation-only: derived from the diff"]
    no_amend = amended("accepted", [], [])
    pass_ref = amended("accepted", [good], refusal)
    miss_name = amended("accepted", [good], ["R-3 only"])
    again = amended("accepted", [good], [])
    two = W.amendments_of(W.Story(SYN, "T", story.dir, story.root, [], [], {"stages": {"S1": {"outcome": "accepted"}}, "amendments": [good, good]}, []))[1]

    # TD-15 fix round 3: SCENARIO_FULL, the question facet without recorded options, `names` on a decision facet, today's template
    long_text, saved_full = "x" * 300, os.environ.pop("SCENARIO_FULL", None)
    cut_line = W._compare({"errors": long_text, "a": 1}, {"a": 2}, ("a",))
    os.environ["SCENARIO_FULL"] = "1"
    try:
        full_line = W._compare({"errors": long_text, "a": 1}, {"a": 2}, ("a",))
    finally:
        os.environ.pop("SCENARIO_FULL", None)
        if saved_full is not None:
            os.environ["SCENARIO_FULL"] = saved_full
    real_question, real_decision = W.door_question, W.door_decision
    gate_entry = {"stage": "gateA", "door": {"kind": "gate"}, "facets": ["question", "decision"]}
    W.door_question = lambda *_a: {"question_kind": "gate_a", "options": ["a", "b"], "errors": ""}
    W.door_decision = lambda *_a: {"decision": "refused", "errors": "the critic has not reviewed the cases as they stand", "tokens": []}
    try:
        question_notes, decision_row = [], {"stage": "gateA", "field": "decision", "recorded": "approve", "expected": "refused",
                                            "names": ["has not reviewed"], "why": "w", "ref": "r", "accepted_by": "Lead"}
        question_plain = W._run_facet(story, gate_entry, "question", world, {"question_kind": "gate_a"}, question_notes)
        question_opts = W._run_facet(story, gate_entry, "question", world, {"question_kind": "gate_a", "options": ["a"]}, [])
        decision_named = W._run_facet(story, gate_entry, "decision", world, {"decision": "approve"}, [], {}, {"decision": decision_row})
        decision_wrong = W._run_facet(story, gate_entry, "decision", world, {"decision": "approve"}, [], {},
                                      {"decision": dict(decision_row, names=["has a different word"])})
    finally:
        W.door_question, W.door_decision = real_question, real_decision
    # TD-15 fix round on the critic verdict: B2 (every refusal part named), B3 (the question is what the door rendered), B4 (files that
    # moved after the accept), B6 (red_then), N1 (the set of reason kinds)
    unnamed = amended("accepted", [good], ["R-3 is implementation-only: x", "branch_accounting.py: U-1 has no home"])
    two_kinds = amended("accepted", [good], ["R-3 is implementation-only: x", "R-3 another kind of refusal"])
    no_text = amended("accepted", [good], [""])
    os.environ["SCENARIO_FULL"] = "1"
    try:
        unnamed_full = amended("accepted", [good], ["R-3 is implementation-only: x", "y" * 300])[0][2]
    finally:
        os.environ.pop("SCENARIO_FULL", None)
    unnamed_cut = amended("accepted", [good], ["R-3 is implementation-only: x", "y" * 300])[0][2]

    import gate_brief as GB
    kept_brief = (GB.collect, GB.render)
    healthy_brief = "# Gate A - SYN-1\n\n**Approve: `test-plan.md`** - say `approve` to approve it.\n"
    try:
        GB.collect = lambda *_a, **_k: {}
        probe = {}
        for label, rendered in (("mutated", "gate A"), ("healthy", healthy_brief), ("no-words", "# Gate A - SYN-1\n\nthe plan is shown\n"),
                                ("other-gate", healthy_brief.replace("Gate A", "Gate B")), ("empty", "  \n")):
            GB.render = lambda *_a, _r=rendered, **_k: _r
            probe[label] = W._run_facet(story, gate_entry, "question", world, {"question_kind": "gate_a"}, [])
    finally:
        GB.collect, GB.render = kept_brief

    def with_refs(change):
        """A copy of the world whose recorded accept carries `change(copy, refs)` as its evidence_refs."""
        copy = W.copy_world(world)
        log = copy / "state" / "events.jsonl"
        rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
        for row in rows:
            if row["type"] == "accept":
                row["payload"]["evidence_refs"] = change(copy, row["payload"]["evidence_refs"])
        log.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        return copy

    def current_hashes(copy, refs):
        import hashlib
        return [{"path": r["path"], "sha256": hashlib.sha256((copy / r["path"]).read_bytes()).hexdigest()} for r in refs]

    entry_s1 = story.walk[0]
    matching = with_refs(current_hashes)
    unhashed = with_refs(lambda *_a: [])
    n_unchanged, n_none, n_final = [], [], []
    gate_unchanged = W._drift_gate(matching, dict(entry_s1, final_state=True), "n", n_unchanged)
    gate_unchanged_plain = W._drift_gate(matching, {"stage": "S1"}, "n", [])
    gate_none = W._drift_gate(unhashed, {"stage": "S1"}, "n", n_none)
    gate_moved = W._drift_gate(world, {"stage": "S1"}, "n", [])
    gate_final = W._drift_gate(world, entry_s1, "n", n_final)
    one_s1 = dict(fresh.walk[0], facets=["accepted"], final_state=False)   # the fixture's S1 entry says final_state; this walk is the unmarked case
    solo = W.Story(SYN, story.task, story.dir, story.root, [one_s1], [], story.expected, [])
    with stand_ins():
        not_comparable = [(r.name.split("/", 1)[1], r.kind, r.detail) for r in W.walk(solo, world)]
        final_state = [(r.name.split("/", 1)[1], r.kind) for r in W.walk(
            W.Story(SYN, story.task, story.dir, story.root, [dict(one_s1, final_state=True)], [], story.expected, []), world)
                       if r.kind != "note"]

    nc_line = next(d for n, k, d in not_comparable if n == "S1/accepted")
    red_dir = temp_dir("qa-red-then-")
    for rel, rows in (("work/triage.json", [{"test": "t1", "verdict": "APP_BUG"}, {"test": "t2", "verdict": "TEST_BUG"}, {"test": "t3", "verdict": "APP_BUG"}]),
                      ("work/triage-green.json", [{"test": "t1", "verdict": "TEST_BUG"}, {"test": "t2", "verdict": "FLAKY"}])):
        (red_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (red_dir / rel).write_text(json.dumps({"triage": rows}), encoding="utf-8")
    (red_dir / "work" / "plain.json").write_text(json.dumps({"results": []}), encoding="utf-8")

    def red_walk(red, walked=("S1", "accepted"), not_walked=()):
        entry = dict(fresh.walk[0], facets=[walked[1]], final_state=True, stage=walked[0])
        expected = dict(story.expected, stages=dict(story.expected["stages"], **{walked[0]: story.expected["stages"]["S1"]}))
        one = W.Story(SYN, story.task, red_dir, story.root, [entry], list(not_walked), expected, [], red)
        with stand_ins():
            return [(r.name.split("/", 1)[1], r.kind, r.detail) for r in W.walk(one, world) if r.name.split("/", 1)[1] not in ("S1/accepted/world-changed", "world/config")]

    on_s1 = {"stage": "S1", "facet": "accepted"}
    red_ok = red_walk(dict(on_s1, evidence="work/triage.json"))
    red_none = red_walk(dict(on_s1, evidence="work/triage-green.json"))
    red_absent = red_walk(dict(on_s1, evidence="work/gone.json"))
    red_plain = red_walk(dict(on_s1, evidence="work/plain.json"))
    red_elsewhere = red_walk(dict(on_s1, facet="handed", evidence="work/triage.json"))
    red_listed = red_walk(dict(on_s1, evidence="work/triage.json"), not_walked=[{"stage": "S1", "facet": "accepted", "why": "w"}])
    red_malformed = red_walk({"stage": "S1"})
    red_outside = red_walk(dict(on_s1, evidence="../outside.json"))
    no_red = red_walk(None)

    real_delivery = W.door_delivery
    delivery_entry = {"stage": "S8", "door": {"kind": "delivery"}, "facets": ["delivery"]}
    W.door_delivery = lambda *_a: {"delivery": "no", "reasons": ["red", "coverage_gap"], "errors": ""}
    try:
        reasons_same = W._run_facet(story, delivery_entry, "delivery", world, {"delivery": "no", "reasons": ["coverage_gap", "red"]}, [])
        reasons_other = W._run_facet(story, delivery_entry, "delivery", world, {"delivery": "no", "reasons": ["red"]}, [])
        reasons_absent = W._run_facet(story, delivery_entry, "delivery", world, {"delivery": "no"}, [])
    finally:
        W.door_delivery = real_delivery
    today_form = "contract: s1-scout-to-tester\n"
    still, retired, _why = W.required_today(today_form, ["work/handoffs/S1-qa-scout-1.yaml", "work/impl-diff.txt", "work/gone-from-template.json"])
    _s, _r, no_template = W.required_today("contract: no-such-contract\n", ["work/x.json"])

    table = [
        ("SCENARIO_FULL unset: a refusal is cut at 200 characters in the FAIL line", len(cut_line) < 300 and "x" * 200 in cut_line, True),
        ("SCENARIO_FULL=1: the FULL refusal text is in the FAIL line", long_text in full_line, True),
        ("question facet: recorded kind and no options compares the kind only and NOTEs `options not recorded`",
         (question_plain, question_notes), ((True, ""), ["options not recorded"])),
        ("question facet: recorded options are still compared", question_opts[0], False),
        ("decision facet: an amendment's names are checked there too (present: pass; another word: fail naming it)",
         (decision_named[0], decision_wrong[0], "'has a different word'" in decision_wrong[1]), (True, False, True)),
        ("B2: a refusal part that carries none of the names fails the facet, naming the part",
         (unnamed[0][1], unnamed[0][2].startswith("unnamed refusal part: branch_accounting.py: U-1 has no home")), ("fail", True)),
        ("B2: one name per KIND of refusal: every part carries one of the names -> pass",
         [(n, k) for n, k, _d in two_kinds], [("S1/accepted (amended: find-1)", "pass")]),
        ("B2: a refusal of no text under an amendment with names: `refused with no text`", no_text, [("S1/accepted", "fail", "refused with no text")]),
        ("B2: the unnamed part is cut at 160 characters, and whole with SCENARIO_FULL=1",
         (unnamed_cut.endswith("y" * 160), "y" * 161 in unnamed_cut, unnamed_full.endswith("y" * 300)), (True, False, True)),
        ("B3: the kind is read from the rendered heading (gate A, gate B, none)",
         (W.rendered_kind("# Gate A - T\nx"), W.rendered_kind("\n# Gate B - T\nx"), W.rendered_kind("gate A")), ("gate_a", "gate_b", "")),
        ("B3: a brief that renders just `gate A` FAILS the question facet (the mutation of the verdict's probe)", probe["mutated"][0], False),
        ("B3: a brief with the heading, a body and an approval word passes", probe["healthy"][0], True),
        ("B3: a brief that names none of the gate's approval words fails, naming it",
         (probe["no-words"][0], "approval words" in probe["no-words"][1]), (False, True)),
        ("B3: a brief that says it is another gate fails on the kind, though the story's entry says gate A",
         (probe["other-gate"][0], "question_kind" in probe["other-gate"][1]), (False, True)),
        ("B3: a brief that renders empty fails", (probe["empty"][0], "empty" in probe["empty"][1]), (False, True)),
        ("B4: an accept whose files moved: the facet is a NOTE naming them and gives no verdict",
         ([(n, k) for n, k, _d in not_comparable if n == "S1/accepted"], nc_line.startswith("not comparable: work/context-manifest.json")
          and "work/impl-diff.txt" in nc_line and nc_line.endswith("changed after the recorded accept")),
         ([("S1/accepted", "note")], True)),
        ("B4: `final_state: true` runs the facet and the PASS line says so", final_state, [("S1/accepted (final state)", "pass")]),
        ("B4: files that did not change: no mark and no note, `final_state` or not",
         (gate_unchanged, gate_unchanged_plain, n_unchanged), (("", None), ("", None), [])),
        ("B4: an accept with no recorded hashes runs as today plus one NOTE `no recorded hashes`", (gate_none, n_none), (("", None), ["no recorded hashes"])),
        ("B4: moved files with no `final_state` give the NOTE result, with it the mark", (gate_moved[1].kind, gate_final), ("note", (" (final state)", None))),
        ("B4: the drift is read from the recorded accept (3 hashes, 2 files moved)", W.accept_drift(world, "S1"),
         (["work/context-manifest.json", "work/impl-diff.txt"], 3)),
        ("B6: red_then on a walked facet whose evidence holds red rows: the PASS line counts them",
         [(n, k) for n, k, _d in red_ok], [("S1/accepted (final state) (red then: 2 rows)", "pass")]),
        ("B6: evidence with no row of the red verdict fails the facet", [(n, k) for n, k, _d in red_none if k != "pass" or "red then" in n],
         [("S1/accepted", "fail")]),
        ("B6: evidence absent fails the facet naming the file", ("gone.json" in red_absent[0][2], red_absent[0][1]), (True, "fail")),
        ("B6: evidence that is not a triage file passes and says so", red_plain[0][0], "S1/accepted (final state) (red then: evidence is not a triage file)"),
        ("B6: red_then naming a facet the walk does not hold: a FAIL line of the story",
         [(n, k, d) for n, k, d in red_elsewhere if n == "red_then"], [("red_then", "fail", "red_then names S1/handed, which is not walked")]),
        ("B6: red_then naming a facet the story lists as not walked: the same FAIL line",
         [(n, k, d) for n, k, d in red_listed if n == "red_then"], [("red_then", "fail", "red_then names S1/accepted, which is not walked")]),
        ("B6: a malformed red_then and an evidence path outside the story are FAIL lines of the story",
         ([n for n, k, _d in red_malformed if n == "red_then"], [n for n, k, _d in red_outside if n == "red_then"]), (["red_then"], ["red_then"])),
        ("B6: a story with no red_then is walked as before", [(n, k) for n, k, _d in no_red], [("S1/accepted (final state)", "pass")]),
        ("N1: the set of reason kinds is compared when expected.json records `reasons` (same set pass, other set fails, absent as before)",
         (reasons_same[0], reasons_other[0], "reasons" in reasons_other[1], reasons_absent[0]), (True, False, True, True)),
        ("handed: a recorded required path that today's template does not require is retired (a NOTE), the template rows stay",
         (still, retired), (["work/handoffs/S1-qa-scout-1.yaml", "work/impl-diff.txt"], ["work/gone-from-template.json"])),
        ("handed: no template of today's package for the contract: the recorded form judges, and says so",
         (_s, _r, bool(no_template)), (["work/x.json"], [], True)),
        ("amendments absent: the facet is judged as recorded", no_amend, [("S1/accepted", "pass", "")]),
        ("amendment: the expected value replaces the recorded one, the PASS line says so",
         pass_ref, [("S1/accepted (amended: find-1)", "pass", "")]),
        ("amendment: a name missing from the refusal fails naming it, the other name alone does not pass it",
         (miss_name[0][1], "'implementation-only'" in miss_name[0][2]), ("fail", True)),
        ("amendment: the door behaves as recorded again -> `amendment no longer needed: S1/outcome`",
         again, [("S1/accepted", "fail", "amendment no longer needed: S1/outcome")]),
        ("amendment malformed: no stage", "required" in malformed(stage=None), True),
        ("amendment malformed: a stage not in stages", "not in expected.json stages" in malformed(stage="S7"), True),
        ("amendment malformed: a field outside the closed set", "must be one of" in malformed(field="verdict"), True),
        ("amendment malformed: recorded is not what stages holds", "another record" in malformed(recorded="refused"), True),
        ("amendment malformed: no why", "`why`" in malformed(why=None), True),
        ("amendment malformed: no accepted_by", "`accepted_by`" in malformed(accepted_by=None), True),
        ("amendment malformed: names with an expected other than refused", "names" in malformed(expected="accepted"), True),
        ("amendment malformed: two rows for one stage and field", ["same stage and field" in two[0]], [True]),
        ("amendment malformed: the walk gives ONE fail line of the story and amends nothing",
         [(n, k) for n, k, _d in amended("accepted", [dict(good, why=None)], [])], [("amendments", "fail"), ("S1/accepted", "pass")]),
        ("load_story: broken JSON names the file", "story.json" in bad_json and "JSON" in bad_json, True),
        ("load_story: a story without synthetic: true is refused as such", "not synthetic" in not_synthetic, True),
        ("world build failure: ONE fail, no stage check", [(r.name, r.kind) for r in built], [("x/world-build", "fail")]),
        ("a facet with no carrier is a NOTE, never a PASS", kinds.get(f"{SYN}/S1manifest/question"), "note"),
        ("a not_walked row is a NOTE", kinds.get(f"{SYN}/S2/accepted"), "note"),
        ("the stand-in doors walk the fixture green (every line a pass or a note)",
         sorted(set(kinds.values())), ["note", "pass"]),
        ("the shared world is the same bytes after every walk above", before == after, True),
        ("variants del and replace_file ride the door and are refused by name",
         (kinds[f"{SYN}/variant/criteria-missing"], kinds[f"{SYN}/variant/manifest-emptied"]), ("pass", "pass")),
        ("a stage with no expected entry: FAIL <story>/<stage>/expected-missing", reds.get(f"{SYN}/S8/expected-missing"), "fail"),
        ("and no check of that stage runs", f"{SYN}/S8/delivery" in reds, False),
        ("a missing variant pointer: FAIL variant-pointer-absent", reds.get(f"{SYN}/variant/nope/variant-pointer-absent"), "fail"),
        ("handed does not change the shared world (hash before and after the walks)", before == after, True),
        ("handed: the form is read, the start is a stand-in, nothing is named wrongly", kinds.get(f"{SYN}/S1/handed"), "pass"),
        ("handed: a file the form names that is absent is refused by name", "impl-diff.txt" in handed_gone["errors"], True),
        ("vocabulary: a recorded controller action reaches the door's token, the status decides refused",
         (W.decision_of("approve_plan_and_cases", "approved"), W.decision_of("approve_delivery", "approved"),
          W.decision_of("approve", "approved"), W.decision_of("approve", "rejected")), ("approve", "approve", "approve", "refused")),
        ("vocabulary: an action no row of GATE_ACTIONS knows is a KeyError naming it, not a guess",
         _raises(lambda: W.decision_of("reopen_everything", "approved")), "'reopen_everything'"),
        ("vocabulary: a question kind in any case is written the way the door returns it",
         (W.question_kind_of("gate_A"), W.question_kind_of("GATE_B"), W.question_kind_of("other")), ("gate_a", "gate_b", None)),
        ("handed: a template path and a folder are NOTES not failures, the real file rows still count",
         (templated["errors"], sorted(n.split(" -- ")[0] for n in templated["notes"])), ("", ["<cases_root>/<area>/<case>.md", "work/evidence/"])),
        ("handed: a template path stays in the named list (the expected list may hold it)",
         "<cases_root>/<area>/<case>.md" in templated["handed"], True),
        ("handed: the start gets the recorded dispatch's execution kind and scope",
         start_flags, ["--execution-kind", "automation", "--scope", "TC-1,TC-2"]),
        ("handed: the cut is the first recorded dispatch of the next stage when the story names none",
         (W._cut_of(story.walk[0], "handed", tpl), W._cut_of(story.walk[0], "handed", world), W._cut_of(story.walk[0], "accepted", tpl)),
         (7, None, None)),
        ("handed: a recorded dispatch with no start arguments starts with none",
         (W.start_args(None), W.start_args({"payload": {"id": "S2-x"}}), W.start_args({"payload": {"scope": [], "purpose": ""}})), ([], [], [])),
        ("handed: the recorded purpose is passed as --purpose, like the execution kind",
         W.start_args({"payload": {"purpose": "manual", "execution_kind": "manual"}}), ["--execution-kind", "manual", "--purpose", "manual"]),
        ("cut_before_seq per facet: a map gives each facet its own seq, an omitted facet is uncut, a number holds for all",
         (W.story_cut({"door": {"cut_before_seq": {"decision": 34, "question": 30}}}, "decision"),
          W.story_cut({"door": {"cut_before_seq": {"decision": 34}}}, "question"), W.story_cut({"door": {"cut_before_seq": 5}}, "handed")),
         (34, None, 5)),
        ("W1: the recorded project config is the config of the world and of a copy of it",
         ((cfg_world.parents[2] / "qa-factory" / "config.json").read_text(encoding="utf-8"),
          (cfg_copy.parents[2] / "qa-factory" / "config.json").read_text(encoding="utf-8")), (config_text, config_text)),
        ("W1: a story with no recorded config walks on the template config and says so in a NOTE",
         (W.recorded_config(world), kinds.get(f"{SYN}/world/config")), (None, "note")),
        ("W2: the exit door holds the judged stage and its accepted dispatch", asked, [("S1", "S1-qa-scout-1")]),
        ("W3: a detector the story declares not walked is out of the refusal, the rest of the refusal stays",
         (gate_answer["outcome"], gate_answer["errors"]), ("refused", "other.py: bad")),
        ("handed: a form with no required inputs passes with a NOTE and an empty list",
         (no_inputs["errors"], no_inputs["handed"], "no required inputs" in no_inputs["notes"][0]), ("", [], True)),
        ("handed: no next stage is no carrier", (no_next["carrier"], "no `next`" in no_next["errors"]), (False, True)),
        ("facets of one cut: the cut world is built once, each facet gets its own copy and never sees another's write",
         (len(cutworlds), (second / "work" / "written-by-one-facet.txt").exists(), (cutworlds[5] / "work" / "written-by-one-facet.txt").exists()),
         (1, False, False)),
        ("the copy keeps the recording's file ages (a door that compares ages sees the same ages)",
         copied_file.stat().st_mtime_ns == source_file.stat().st_mtime_ns and copied_file.read_bytes() == source_file.read_bytes(), True),
        ("op del removes the key", op(file="d.json", op="del", pointer="/a/b"), {"a": {}, "l": [1, 2]}),
        ("op set puts the value (a list index too)", op(file="d.json", op="set", pointer="/l/0", value=9), {"a": {}, "l": [9, 2]}),
        ("op set on a missing pointer", op(file="d.json", op="set", pointer="/zz", value=1), "variant-pointer-absent"),
        ("op on a missing file", op(file="none.json", op="del", pointer="/a"), "variant-file-absent"),
        ("op nobody defined", op(file="d.json", op="drop", pointer="/a"), "op-unknown"),
        ("op words replaces the text", (op(file="w.txt", op="words", value="say"), (ops / "w.txt").read_text())[1], "say"),
        ("op replace_file copies the named file in", (op(file="w.txt", op="replace_file", **{"with": "with.txt"}),
                                                      (ops / "w.txt").read_text())[1], "new"),
    ]
    for name, got, expected in table:
        check_eq(name, got, expected)

    # the doors that are cheap enough to run for real: a joint, the exit gate, the delivery word, on ONE shared world
    real = W.Story(SYN, story.task, story.dir, story.root,
                   [dict(story.walk[0], facets=["accepted"]), story.walk[1]], [], story.expected, [])
    live = {r.name: r.kind for r in W.walk(real, world) if r.kind == "pass"}
    check_eq("real exit gate and joint check agree with the record",
             sorted(live.items()), [(f"{SYN}/S1/accepted (final state)", "pass"), (f"{SYN}/S1manifest/accepted", "pass")])

    witness_rows = [
        ("witness_for: a module in the import closure of a door names the scenario", witness(["scripts/c.py"]), "test_scenario_demo.py"),
        ("witness_for: a keep row that covers the path names the row", witness(["scripts/z.py"]), "keep test_gate.py"),
        ("witness_for: a data file is matched by covers", witness(["references/r.json"]), "keep test_gate.py"),
        ("witness_for: a data file is said to be one", witness(["references/r.json"]), "not a script of scripts/"),
        ("witness_for: no match runs the whole layer", witness(["scripts/other.py"]), "no scenario or keep row covers scripts/other.py"),
        ("witness_for: a deleted path counts as changed", witness(["scripts/gone.py"]), "deleted or absent on disk"),
        ("witness_for: no test-layers.json is stated", witness(["scripts/c.py"], absent=True), "test-layers.json is absent"),
    ]
    for name, text, needle in witness_rows:
        check_in(name, needle, text)
    check_not_in("witness_for: a keep row that does not cover the path is not named", witness(["scripts/c.py"]), "keep test_gate.py")
    finish("test_scenario_walk")


if __name__ == "__main__":
    main()
