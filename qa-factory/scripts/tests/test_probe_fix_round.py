"""probe_by_code.py: fix round A of t-2064 P4 (the critic's blockers B1, B2, B3), on the stub runner of `test_probe_walk.World`.

The flip of `_probe` left three guards of the old road on dead code. Each test names the mutation of the code that kills it. The World,
the `flip` wiring and its helpers are the ones of `test_probe_every_check.py` (imported, not copied). Fast; no sleeps, no real runner.
Runnable alone (`python -B test_probe_fix_round.py`) and collected by pytest."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import probe_by_code as PBC  # noqa: E402
import test_probe_walk as TW  # noqa: E402
from test_probe_every_check import flip, flip_call, flip_models, flip_actual, flip_snapshot, flip_refusal, real_receipt  # noqa: E402
from test_probe_walk import World, fire, row, verdicts  # noqa: E402


# --- B1: the request refusals (R6) come before the first byte -----------------------------------------------------------------------

def table_world(tmp_path, monkeypatch, kinds="sss", stage="S6"):
    """A flip world whose test the call reads as a TABLE test (`ctx.detector`): R6 is on the road only there."""
    world = flip(tmp_path, monkeypatch, kinds, stage=stage)
    real = PBC._probe_plan       # the World's test is Python (the AST reader): only the flag that puts R6 on the road is turned on
    monkeypatch.setattr(PBC, "_probe_plan", lambda ctx, *a, **k: real(ctx._replace(detector=True), *a, **k))
    return world


def test_b1_request_refusal_is_exit_2_nothing_written(tmp_path, monkeypatch):
    """The REAL `run_shape_checks` on a profile that does not say its selectors are verified (R6 a): the call is refused with its own text
    and door, and NOTHING moved - the tree and the story folder byte for byte, no record, no run. Killed by: removing the `_shape_refusals`
    call from `_probe_plan`, or calling it after `_walk_plan` (the walk writes, the refusal is then a note and the rows `not_executed`)."""
    world = table_world(tmp_path, monkeypatch)
    before = flip_snapshot(world.root, world.task_root)
    text = flip_refusal(world)
    assert "selector contract" in text and "Nothing was changed" in text, text
    assert flip_snapshot(world.root, world.task_root) == before, "not a byte written: no record, no copy, no lock file"
    assert world.runs == [] and not (world.task_root / "work" / "probes").exists(), "no run, no record"


def test_b1_owed_model_is_refused_before_the_request(tmp_path, monkeypatch):
    """A role with no model for the checks: the MODEL refusal comes first, and the request check is not even asked. Killed by: calling
    `_shape_refusals` before `_entries_for` / the owed refusal."""
    world = table_world(tmp_path, monkeypatch, stage="S5")
    monkeypatch.setattr(PBC, "run_shape_checks", lambda *a, **k: pytest.fail("an owed model is refused first"))
    assert "no model is stored" in flip_refusal(world), "the model refusal"
    assert world.runs == []


def test_b1_once_per_call_before_the_first_write(tmp_path, monkeypatch):
    """Three checks, one call: `run_shape_checks` is called ONCE (not per row), with the author's bytes on disk and no record written yet.
    Killed by: calling it per row / per run, or from inside `_walk_attempt` (after `begin_copy` and the first write)."""
    world = table_world(tmp_path, monkeypatch)
    seen = []

    def spy(cfg, manifest, case, entry_row, spec, instance_id, context, text, root=None):
        seen.append({"bytes": world.path.read_bytes(), "records": (world.task_root / "work" / "probes").exists(), "text": text, "context": context})

    monkeypatch.setattr(PBC, "run_shape_checks", spy)
    record = flip_call(world)
    assert len(seen) == 1, f"once per call: {len(seen)}"
    assert seen[0]["bytes"] == world.original and not seen[0]["records"] and seen[0]["text"] == world.text, seen[0]
    assert record["verdict"] == "intended_failure" and len(world.runs) == 1, "the check passes, the walk goes on"


def test_b1_a_selection_asks_only_when_a_selected_row_runs(tmp_path, monkeypatch):
    """`--at` of one row runs that row: the request check is asked once. A plan whose every entry is `not_here` runs nothing and builds no
    request: it is not asked. Killed by: asking for a plan with no row to run (a refusal of a request nobody builds), or never asking
    under a selection."""
    world = table_world(tmp_path, monkeypatch)
    asked = []
    monkeypatch.setattr(PBC, "run_shape_checks", lambda *a, **k: asked.append(1))
    flip_call(world, at=int(world.keys[0].rsplit(":", 1)[1]))
    assert asked == [1], "one selected row runs: asked once"
    asked.clear()
    flip_models(world, [{"check": key, "instance": "i1", "not_here": "this instance never reaches it"} for key in world.keys], dispatch="D")
    world.stage = "S5"
    flip_call(world)
    assert asked == [], "no row will run: no request is built, none is judged"


# --- B2: a pass that cannot say which body ran is `incomplete`, never `no_failure` -----------------------------------------------------

NOTE_E5 = "a pass does not say which body ran"


def test_b2_joint_judge_among_per_key():
    """The joint judge's `facts["among"]` is read PER KEY: a passed run gives `incomplete` / `tooling` with the old road's note for a key
    flagged `among`, `no_failure` for a key that is not flagged, and `no_failure` for every key when the caller says nothing (the pure
    function keeps its old shape). Killed by: `among=False` hard-coded in `_judge_joint_rows` (the first assertion fails)."""
    spec = PBC.parse_node(TW.NODE)      # no disk needed: the plan and the details are built by hand below
    keys = [f"{TW.FILE}:3", f"{TW.FILE}:4"]
    plan = {"checks": [{"key": k, "line": int(k.rsplit(":", 1)[1]), "file": TW.FILE} for k in keys], "runs": [{"keys": keys}]}
    details = [{"key": k, "probe_kind": "actual", "file": TW.FILE, "line": int(k.rsplit(":", 1)[1])} for k in keys]
    base = {"entry": spec["entry"], "site": {}, "author_green": {}, "argv": ["runner"], "language_label": "python"}
    passed = [TW.row("passed")]
    out, move = PBC._judge_joint_rows(passed, {}, keys, plan, details, dict(base, among={keys[0]: True, keys[1]: False}))
    assert out[keys[0]]["verdict"] == "incomplete" and out[keys[0]]["cause"] == "tooling" and NOTE_E5 in out[keys[0]]["note"], out[keys[0]]
    assert out[keys[1]]["verdict"] == "no_failure", out[keys[1]]
    assert move == "go on"
    silent, _move = PBC._judge_joint_rows(passed, {}, keys, plan, details, base)
    assert {one["verdict"] for one in silent.values()} == {"no_failure"}, "a caller that says nothing keeps today's answer"


def test_b2_unlocated_body_a_pass_is_incomplete(tmp_path, monkeypatch):
    """The run cannot say WHICH body ran (the body of the test is not located: two declarations of its name) and `--at` names a check: the
    PASS of that row is `incomplete`, `cause: tooling`, the note says so (E5), the aggregate is not a survivor and no receipt exists, never
    `no_failure`. The body is measured ONCE per walk (not per row or per run). Killed by: `_walk_attempt` not passing `among` (the row reads
    `no_failure`), or `among` taken from `target_source` (a walk has none)."""
    world = flip(tmp_path, monkeypatch, "sss", stage="S6")
    world.scenario = lambda w, run: [TW.row("passed")]
    callers = []

    def unlocated(*a, **k):
        callers.append(sys._getframe(1).f_code.co_name)
        return None

    monkeypatch.setattr(PBC, "test_body_span", unlocated)
    record = flip_call(world, at=int(world.keys[1].rsplit(":", 1)[1]))
    chosen = next(row for row in record["checks"] if row["key"] == world.keys[1])
    assert chosen["verdict"] == "incomplete" and record["verdict"] != "no_failure" and not record.get("receipt"), (chosen, record["verdict"])
    per_check = json.loads(PBC.proof_level.probe_record_path(world.task_root, "i1", target_line=int(world.keys[1].rsplit(":", 1)[1]),
                                                             file=TW.FILE).read_text())
    assert per_check["cause"] == "tooling" and NOTE_E5 in " ".join(per_check["notes"]), per_check
    assert [c for c in callers if c in ("_walk_plan", "_walk_attempt")].count("_walk_plan") == 1 and "_walk_attempt" not in callers,         f"the body is measured once per walk, by the walk: {callers}"


def test_b2_located_body_a_pass_is_no_failure(tmp_path, monkeypatch):
    """One declaration, the body located, an in-body check passes: `no_failure`, as before (EP-H keeps its survivor). Killed by: `among`
    true for every key whatever the body (an over-broad fix: the survivor would be hidden as a gap)."""
    world = flip(tmp_path, monkeypatch, "sss", stage="S6")
    world.scenario = lambda w, run: [TW.row("passed")]
    record = flip_call(world)
    assert [row["verdict"] for row in record["checks"]] == ["no_failure"] * 3 and record["verdict"] == "no_failure", record["checks"]


# --- B3: a repeat on the same bytes is `already_probed` (the old road's answer), an old record stands, a changed entry reruns -------------

def with_row(world, monkeypatch, **more) -> dict:
    """The manifest row the call reads: the instance, its test file (so `already_probed` can measure the bytes) and what `more` adds (the
    receipt the first call wrote). One dict, edited in place between calls."""
    row = {"case": "TC-1", "instance_id": "i1", "file": TW.FILE, **more}
    monkeypatch.setattr(PBC, "manifest_entry", lambda task_root, iid: row)
    return row


def aggregate_bytes(world) -> bytes:
    return (world.task_root / "work" / "probes" / "i1.json").read_bytes()


def test_b3_old_record_on_the_same_bytes_stands(tmp_path, monkeypatch):
    """An OLD single-probe record (`no_failure`, no `checks`) on these very bytes answers `already_probed` under a role with NO model: it is
    not read as "every model owed" (EP-I), nothing runs, the record on disk is not touched, and the answer carries the old road's keys
    (`by`, `prior_verdict`, `block`, the info line). Killed by: dropping the `_repeat_is_new` branch of `_probe_plan` (the refusal "no model
    is stored" comes instead)."""
    world = flip(tmp_path, monkeypatch, "sss", stage="S5")
    with_row(world, monkeypatch)
    sha = PBC.sha256(world.original)
    old = world.task_root / "work" / "probes" / "i1.json"
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"verdict": "no_failure", "test_file_sha256": sha, "recorded_at": "2026-10-01T10:00:00",
                               "mutated_file": {"path": TW.FILE, "sha256": sha}}), encoding="utf-8")
    before = flip_snapshot(world.root, world.task_root)
    answer = flip_call(world)
    assert answer["verdict"] == "already_probed" and answer["by"] == "probe_record" and answer["prior_verdict"] == "no_failure", answer
    assert answer["block"] and answer["words"] and any("proves one check" in n for n in answer["notes"]), answer
    assert world.runs == [] and flip_snapshot(world.root, world.task_root) == before, "nothing launched, not a byte written"


def test_b3_repeat_of_a_complete_walk_is_already_probed(tmp_path, monkeypatch):
    """A complete walk (every check `intended_failure`, the receipt on the row), then the same call on the same bytes and entries: the answer
    is `already_probed` (by the receipt), no run, the aggregate and the receipt file are byte for byte as the first call left them. A
    CHANGED model entry on the same bytes is not a repeat: the check runs again. Killed by: not calling `already_probed` in `_probe_plan`
    (the second call re-publishes the aggregate), or answering without comparing `entry_sha` (the changed entry reads as a repeat)."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5")
    row = with_row(world, monkeypatch)
    monkeypatch.setattr(PBC.proof_level, "binding_facts", lambda task_root, iid: {      # a content-addressed case version: the receipt is valid
        "case_version": "cv_1", "test_content_hash": PBC.sha256(world.original), "source_revision": "rev1", "build_id": "b1"})
    flip_models(world, flip_actual(world))
    first = flip_call(world)
    assert first["verdict"] == "intended_failure" and first["receipt"], (first["verdict"], first.get("receipt_missing"), first["notes"])
    row["sensitivity_proof"] = {"receipt_ref": first["receipt"]}
    runs, aggregate = len(world.runs), aggregate_bytes(world)
    receipt = (world.task_root / first["receipt"]["path"]).read_bytes()
    again = flip_call(world)
    assert again["verdict"] == "already_probed" and again["by"] == "receipt" and again["prior_verdict"] == "intended_failure", again
    assert len(world.runs) == runs, "no new run"
    assert aggregate_bytes(world) == aggregate and (world.task_root / first["receipt"]["path"]).read_bytes() == receipt, "nothing re-published"
    flip_models(world, [dict(m, actual="3") for m in flip_actual(world)])
    changed = flip_call(world)
    assert changed["verdict"] != "already_probed" and len(world.runs) > runs, "a changed entry is a rerun"
    # E5 of t-041 (B1 of its plan critic): a walked row plus a `product` row, both proved, repeated on the same bytes and entries: answered by
    # the receipt, no run. The product row has no per-check record by construction; reading one for it would walk every repeat forever.
    # Killed by: dropping the `kind == "product"` skip in `_repeat_same_entries`.
    product_world = flip(tmp_path / "with-product", monkeypatch, "ss", stage="S5")
    good, _receipt = real_receipt(product_world, monkeypatch, product_world.keys[0])
    product_row = with_row(product_world, monkeypatch)        # after real_receipt: its manifest_entry patch is replaced by this row
    monkeypatch.setattr(PBC.proof_level, "binding_facts", lambda task_root, iid: {
        "case_version": "cv_1", "test_content_hash": PBC.sha256(product_world.original), "source_revision": "rev1", "build_id": "b1"})
    flip_models(product_world, [{"check": product_world.keys[0], "instance": "i1", "product": good}] + flip_actual(product_world, product_world.keys[1:]))
    proved = flip_call(product_world)
    assert [(r["probe_kind"], r["verdict"]) for r in proved["checks"]] == [("product", "intended_failure"), ("actual", "intended_failure")] and proved["receipt"], proved["checks"]
    product_row["sensitivity_proof"] = {"receipt_ref": proved["receipt"]}
    runs = len(product_world.runs)
    repeat = flip_call(product_world)
    assert repeat["verdict"] == "already_probed" and repeat["by"] == "receipt" and len(product_world.runs) == runs, (repeat.get("verdict"), repeat.get("notes"))


def test_b3_a_survivor_of_a_walk_is_not_a_repeat(tmp_path, monkeypatch):
    """A walk that ended `no_failure` (a new aggregate, with `checks`) is WALKED again - never answered `already_probed` - but since the Lead's
    F3 decision (§14 amended 11.11.2026) its survivors are carried as they stand: the same entry on the same bytes launches nothing, the
    aggregate is still `no_failure`, no receipt. (Repinned: before F3 the survivor was run again, `runs + 1`.) Killed by: reading every standing
    probe record as a repeat, whatever its shape."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5")
    with_row(world, monkeypatch)
    flip_models(world, flip_actual(world))
    world.scenario = lambda w, run: [TW.row("passed")]
    assert flip_call(world)["verdict"] == "no_failure"
    runs = len(world.runs)
    again = flip_call(world)
    assert again["verdict"] == "no_failure" and again["receipt"] is None and len(world.runs) == runs, "the survivor is carried, not run again"


# --- F1: ONE numbering of the checks on a line (`checks_of` writes it, `_located` reads it) -----------------------------------------------

def one_line_assert_all(first="assertEquals(1, a);", second="assertEquals(1, a);"):
    """`(data, spec, listed)` of a JUnit test whose body holds ONE line `assertAll(() -> { first }, () -> { second });`."""
    from test_probe_every_check import SCOPES
    java = SCOPES["java-junit"]
    text = java["head"] + f"        assertAll(() -> {{ {first} }}, () -> {{ {second} }});\n" + java["tail"]
    spec = PBC.parse_node(java["node"])
    return text.encode(), spec, PBC.checks_of(text.encode(), spec, PBC._reader_entry(spec), [], [], [])


def test_f1_one_line_assert_all_numbers_and_locates_by_one_ordinal():
    """The critic's counter-example: a one-line JUnit `assertAll` with two IDENTICAL checks. `checks_of` numbers the two members 1 and 2 (the
    `assertAll(` opener is a dropped scope head and takes no number), and `_located` resolves `#1` to the first statement and `#2` to the
    SECOND (by the offset the row carries), neither refused - before the fix `#1` was refused and `#2` landed on the first. Killed by:
    `_located` listing the line with no soft scopes (the opener counts again: `#1` is refused, `#2` is the first statement)."""
    data, spec, listed = one_line_assert_all()
    assert [c["ordinal"] for c in listed] == [1, 2] and not listed[0]["key"].endswith("#1") and listed[1]["key"] == listed[0]["key"] + "#2", listed
    assert listed[0]["offset"] < listed[1]["offset"], "the second statement stands later in the file"
    found = [PBC._located(data, spec, check) for check in listed]
    assert [f["start"] for f in found] == [c["offset"] for c in listed], "each key resolves to the statement it was numbered at"
    assert found[0]["start"] != found[1]["start"], "`#2` is not the first statement again"
    assert "assertAll" not in [f["text"][f["start"]:f["end"]] for f in found][0]


def test_f1_one_line_assert_all_with_different_texts_resolves_each():
    """The same line with two DIFFERENT checks: each key resolves to its own text (before the fix both were refused), and the `find` door
    opens for both (a located check is never a refusal of the call). Killed by: `_located` listing with no soft scopes."""
    data, spec, listed = one_line_assert_all("assertEquals(1, a);", "assertEquals(2, a);")
    assert len(listed) == 2
    texts = []
    for check in listed:
        got = PBC._located(data, spec, check)
        texts.append(got["text"][got["start"]:got["end"]])
        assert "find" in PBC._check_doors(data, spec, check), (check["key"], PBC._check_doors(data, spec, check))
    assert texts == ["assertEquals(1, a);", "assertEquals(2, a);"], texts


def test_f1_ordinal_beyond_the_count_is_refused_with_the_count_and_the_keys():
    """`#3` of two members: a Refusal with the true count (2, not the three heads the line holds with its opener) and the keys that DO
    exist on the line - a door the role can use. A key with no `#` is ordinal 1. Killed by: counting the opener (the count reads 3 and `#3`
    resolves) or dropping the keys from the refusal."""
    data, spec, listed = one_line_assert_all()
    ghost = dict(listed[1], key=listed[0]["key"] + "#3")
    with pytest.raises(PBC.Refusal) as caught:
        PBC._located(data, spec, ghost)
    text = str(caught.value)
    assert "only 2 stand there" in text and listed[0]["key"] in text and listed[1]["key"] in text, text
    assert PBC._ordinal_of(listed[0]["key"]) == 1 and PBC._ordinal_of(listed[1]["key"]) == 2


# --- F2: `plan_unfinished` is a walk the WALL cut, never a selection that ran its own rows ----------------------------------------------

def test_f2_at_over_other_unproved_rows_is_incomplete_with_the_door_not_plan_unfinished(tmp_path, monkeypatch):
    """`--at` runs ITS row of three and the others stay unproved: the record is `incomplete`, NOT `plan_unfinished` (the same `--at` again
    would never finish the plan), the unsettled keys are named in its last note (the line `probe_record_state` shows) together with the door
    that does finish it (a call with no `--at`), and the state a reader sees is `incomplete`. Killed by: `_aggregate_verdict` reading every
    `not_reached` row of an `ended == ""` walk as unfinished (the old line `ended in ("", "time")`)."""
    from test_probe_every_check import FIRE_ALL
    world = flip(tmp_path, monkeypatch, "sss", stage="S5")
    world.scenario = FIRE_ALL
    flip_models(world, flip_actual(world))
    record = flip_call(world, at=3)
    assert record["verdict"] == "incomplete" and record["plan_unfinished"] is False and record["receipt"] is None, record["checks"]
    assert [r["verdict"] for r in record["checks"]] == ["intended_failure", "not_reached", "not_reached"], record["checks"]
    last = record["notes"][-1]
    assert world.keys[1] in last and world.keys[2] in last and world.keys[0] not in last and "no `--at`" in last, last
    state = PBC.proof_level.probe_record_state(world.task_root, "i1", record["test_file_sha256"])
    assert state["state"] == "incomplete" and "no `--at`" in state["why"], state
    done = flip_call(world)       # the door it names finishes the plan
    assert done["verdict"] == "intended_failure" and done["plan_unfinished"] is False and done["receipt"], done["checks"]


def test_f2_a_wall_cut_walk_is_still_plan_unfinished(tmp_path, monkeypatch):
    """The control: the wall cuts a plain walk after the first row - `plan_unfinished: true`, whose door ("the same call again") DOES continue
    it, and a note about `--at` is not written. Killed by: `unfinished` false whenever the call had no unsettled row of its own that is
    pending (the wall's rows would then read as a selection's)."""
    world = flip(tmp_path, monkeypatch, "hhh", stage="S6")
    world.scenario = lambda w, run: [TW.row("failed", TW.thrown(w, run, *run["tokens"]))]
    world.step = 60.0
    cut = flip_call(world, timeout=100)
    assert cut["plan_unfinished"] is True and cut["verdict"] == "incomplete" and not any("no `--at`" in n for n in cut["notes"]), cut["notes"]


def test_f2_a_selected_row_the_wall_cut_is_still_plan_unfinished(tmp_path, monkeypatch):
    """`--oracle` of two checks whose wall is spent after the first: the second SELECTED row is not reached, so the same call again does
    continue it - `plan_unfinished: true`. Killed by: narrowing `unfinished` to nothing under a selection."""
    from test_probe_every_check import FIRE_ALL, HELPER_TWO
    world = flip(tmp_path, monkeypatch, "ss", stage="S5", extra=HELPER_TWO)
    world.scenario = FIRE_ALL
    keys = [c["key"] for c in PBC._plan_of_test(world.ctx, world.root, [(TW.FILE, world.path, "5-7")])[0]]
    flip_models(world, flip_actual(world, keys))
    world.step = 120.0
    cut = flip_call(world, oracle="expect", timeout=100)
    pending = [r["key"] for r in cut["checks"] if r["verdict"] == "not_reached" and r["key"] in keys[2:]]
    assert pending and cut["plan_unfinished"] is True, [(r["key"], r["verdict"]) for r in cut["checks"]]


def test_f2_cause_a_selection_over_unproved_rows_is_judgment_not_the_tools_failure(tmp_path, monkeypatch):
    """Lead decision on the cause (critic t-2411): an `--at` call that ran its own rows while OTHER rows stay unproved is `incomplete` with
    `cause: judgment` (models owed to the critic); `proof_level.probe_could_not_run` - the one reader of "the tool could not run", the
    person's class-word door - is False for it, and the state is `incomplete` with cause `judgment`, never `plan_unfinished`. Control: the
    same reader is True for an `incomplete` record of cause `tooling`. Killed by: `_aggregate_verdict` returning cause `tooling` for the
    selection (the old line), which makes `probe_could_not_run` True."""
    from test_probe_every_check import FIRE_ALL
    world = flip(tmp_path, monkeypatch, "sss", stage="S5")
    world.scenario = FIRE_ALL
    flip_models(world, flip_actual(world))
    record = flip_call(world, at=3)
    assert record["verdict"] == "incomplete" and record["cause"] == "judgment" and record["plan_unfinished"] is False, record["checks"]
    sha = record["test_file_sha256"]
    state = PBC.proof_level.probe_record_state(world.task_root, "i1", sha)
    assert state["state"] == "incomplete" and state["cause"] == "judgment", state
    assert PBC.proof_level.probe_could_not_run(world.task_root, "i1", sha) is False
    path = world.task_root / "work" / "probes" / "i1.json"
    on_disk = json.loads(path.read_text())
    path.write_text(json.dumps(dict(on_disk, cause="tooling")), encoding="utf-8")      # the control: the reader does say True for the tool's failure
    assert PBC.proof_level.probe_could_not_run(world.task_root, "i1", sha) is True


# --- F8: a check `--at` ADDED to the plan survives an incomplete call, and the older proved aggregate no longer stands for the bigger plan --

def test_f8_added_check_stays_on_the_plan_and_the_old_aggregate_does_not_stand(tmp_path, monkeypatch):
    """A complete walk (two checks, receipt on the manifest row), then `--at` of a helper's line whose run ends `incomplete`: the aggregate
    on disk is the NEW one (three rows, the added key among them, no receipt, `intended_failure` gone), `_stored_plan_refs` still reads the
    added line, the next PLAIN call is refused for the helper's missing model instead of answering `already_probed` by the old receipt.
    Killed by: `keep_standing_record` ignoring `_plan_grew` (the old aggregate stays, the helper falls off
    the plan and the plain call is answered `already_probed`)."""
    world = flip(tmp_path, monkeypatch, "ss", stage="S5", extra='def helper(a):\n    assert a == 1, "h"\n')
    row = {"case": "TC-1", "instance_id": "i1", "file": TW.FILE}
    monkeypatch.setattr(PBC, "manifest_entry", lambda task_root, iid: row)
    monkeypatch.setattr(PBC.proof_level, "binding_facts", lambda task_root, iid: {
        "case_version": "cv_1", "test_content_hash": PBC.sha256(world.original), "source_revision": "rev1", "build_id": "b1"})
    helper = f"{TW.FILE}:6"
    flip_models(world, flip_actual(world))
    first = flip_call(world)
    assert first["verdict"] == "intended_failure" and first["receipt"] and [r["key"] for r in first["checks"]] == world.keys, first["notes"]
    row["sensitivity_proof"] = {"receipt_ref": first["receipt"]}
    flip_models(world, flip_actual(world) + flip_actual(world, [helper]))
    world.scenario = lambda w, run: [TW.row("failed", "boom: nothing marked")]       # a failure with no marker: owed a judgment, `incomplete`
    added = flip_call(world, at=f"{TW.FILE}:6")
    assert added["verdict"] == "incomplete" and [r["key"] for r in added["checks"]] == world.keys + [helper], added["checks"]
    on_disk = json.loads((world.task_root / "work" / "probes" / "i1.json").read_text())
    assert on_disk["verdict"] == "incomplete" and on_disk["receipt"] is None and [r["key"] for r in on_disk["checks"]] == world.keys + [helper], \
        (on_disk["verdict"], [r["key"] for r in on_disk["checks"]])
    spec = PBC.parse_node(TW.NODE)
    assert (TW.FILE, 6) in PBC._stored_plan_refs(world.task_root, "i1", spec, world.original, PBC._reader_entry(spec)), "the added line is owed"
    again = flip_call(world)        # the next PLAIN call walks the grown plan; the old receipt is not read as its answer
    assert again["verdict"] != "already_probed" and [r["key"] for r in again["checks"]] == world.keys + [helper], again.get("verdict")
    assert again["checks"][-1]["verdict"] != "not_owed" and any(r["key"] == helper for r in again["checks"]), "the added key is owed"


def test_f8_a_call_that_added_no_key_keeps_the_standing_aggregate(tmp_path):
    """The rule of `keep_standing_record` for a call with no added key is unchanged: an `incomplete` record over a stored `intended_failure`
    of the SAME plan keeps the stored record and adds `last_attempt`; one whose plan holds a key the stored one lacks does not, and
    `_plan_grew` names it (a removed key, or a record with no plan list, is not growth). Killed by: `_plan_grew` answering for a removed key
    or for an old record with no `checks`, or `keep_standing_record` never asking it."""
    stored = {"verdict": "intended_failure", "mutation_detail": {"checks": ["f:3", "f:4"]}, "receipt": {"path": "r"}}
    same = {"verdict": "incomplete", "notes": ["why"], "recorded_at": "t", "mutation_detail": {"checks": ["f:3", "f:4"]}}
    path = tmp_path / "i1.json"
    path.write_text(json.dumps(stored), encoding="utf-8")
    assert PBC.keep_standing_record(path, same) is True and json.loads(path.read_text())["verdict"] == "intended_failure"
    assert json.loads(path.read_text())["last_attempt"]["verdict"] == "incomplete"
    bigger = {"verdict": "incomplete", "notes": ["why"], "recorded_at": "t", "mutation_detail": {"checks": ["f:3", "f:4", "g:6"]}}
    path.write_text(json.dumps(stored), encoding="utf-8")
    assert PBC.keep_standing_record(path, bigger) is False and json.loads(path.read_text()) == stored, "nothing written by the refusal to keep"
    assert PBC._plan_grew(stored, bigger) == ["g:6"] and PBC._plan_grew(stored, dict(same, mutation_detail={"checks": ["f:3"]})) == []
    assert PBC._plan_grew({"verdict": "intended_failure"}, bigger) == [] and PBC._plan_grew(stored, {"verdict": "incomplete"}) == []


# --- round C: F3 (a survivor is carried), F4 (the bytes key), F5 (the edited file), F6 (the code-written marker), F7 (one reader, one ordinal) --

def fake_instance_identity(world, monkeypatch, function="test_run"):
    """`proof_level.instance_identity` as the job-based measure would answer it, made from the file: the instance's code sha is the sha of the TEXT
    of `function` alone (up to the next top-level `def`), so an edit of another function or a trailing comment moves the file's sha and not this
    one. A stand-in for the measure (which needs a mined job); what is under test is the use the walk makes of the number."""
    def fake(entry, task_root, project=None):
        data = world.path.read_bytes()
        body = data.decode().split(f"def {function}():", 1)[1].split("\ndef ", 1)[0]
        sha = PBC.sha256(body.encode())
        return {"input_hash": PBC.sha256(data), "test_code_sha": "", "why": "",
                "instance_identity": {"instance_content_sha": "c" + sha, "instance_code_sha": "k" + sha, "job_id": "j"}}
    monkeypatch.setattr(PBC.proof_level, "instance_identity", fake)


def edit_file(path, world, data: bytes):
    path.write_bytes(data)
    if path == world.path:
        world.original = data


def test_f3_a_survivor_on_the_same_entry_and_bytes_is_carried_no_run(tmp_path, monkeypatch):
    """A check that ended `no_failure` is carried on the next walk as it stands: the SAME entry on the SAME bytes launches nothing, the row
    keeps `no_failure` in the aggregate (a survivor is not a proof: no receipt, the verdict stays), a CHANGED entry runs again, and a stored
    `incomplete` runs again too. Killed by: the `standing in _CARRIED_VERDICTS` branch of `_walk_plan` made `False` (the survivor is run)."""
    world = World(tmp_path, "ss").install(monkeypatch)
    world.scenario = lambda w, run: [row("passed")]
    first = world.walk()
    assert set(verdicts(first).values()) == {"no_failure"}, first["outcomes"]
    runs = len(world.runs)
    again = world.walk()
    assert len(world.runs) == runs and sorted(again["carried"]) == sorted(world.keys) and again["outcomes"] == {}, "no run for a survivor"
    record = again["record"]
    assert record["verdict"] == "no_failure" and record["receipt"] is None and [r["verdict"] for r in record["checks"]] == ["no_failure"] * 2, record["checks"]
    assert all("carried as it stands" in r["note"] for r in record["checks"]), "the row says why it did not run"
    world.walk([dict(e, actual="3") for e in world.entries()])
    assert len(world.runs) == runs + 1, "a changed entry is a rerun"
    other = World(tmp_path / "o", "ss").install(monkeypatch)
    other.scenario = lambda w, run: [row("failed", "boom: nothing marked")]       # a failure with no marker: `incomplete`, owed a judgment
    assert set(verdicts(other.walk()).values()) == {"incomplete"}
    spent = len(other.runs)
    other.walk()
    assert len(other.runs) > spent, "any other stored verdict reruns as before"


def test_f3_standing_reads_entry_bytes_and_flags(tmp_path):
    """`_check_standing` gives the stored verdict only for the same entry, bytes and flags; the walk carries exactly `no_failure` and
    `wrong_location`. Killed by: `_check_standing` ignoring the flags, or `_CARRIED_VERDICTS` holding another word."""
    from test_probe_walk import stored
    stored(tmp_path, verdict="wrong_location", no_retry_flags=["--retries=0"])
    assert PBC._check_standing(tmp_path, "i1", 3, 1, "E", "B", ["--retries=0"]) == "wrong_location"
    assert PBC._check_standing(tmp_path, "i1", 3, 1, "E", "B", []) == "" and PBC._check_standing(tmp_path, "i1", 3, 1, "E2", "B", ["--retries=0"]) == ""
    assert PBC._check_standing(tmp_path, "i1", 3, 1, "E", "B2", ["--retries=0"]) == ""
    assert PBC._CARRIED_VERDICTS == ("no_failure", "wrong_location")


def test_f4_a_comment_or_another_tests_edit_reruns_nothing_this_tests_edit_does(tmp_path, monkeypatch):
    """The bytes key of a check in the test's own body is the INSTANCE's code sha: a comment at the end of the file and an edit of ANOTHER test in
    it leave the proved checks standing (no run); an edit of this test's own body reruns them; the record says it used `code_sha`. Without the
    instance's code sha (nothing measured) the key falls back to the file's sha and the record says `file_sha`. Killed by: the walk passing
    the file's sha as the key of a check in the test file (the first two edits rerun)."""
    world = World(tmp_path, "ss", extra="def test_other():\n    b = 2\n").install(monkeypatch)
    fake_instance_identity(world, monkeypatch)
    world.scenario = fire(0, 1)
    base = world.original
    first = world.walk()
    assert set(verdicts(first).values()) == {"intended_failure"} and len(world.runs) == 1
    assert all(world.record(key)["bytes_key"]["kind"] == "code_sha" and world.record(key)["bytes_key"]["sha"].startswith("k") for key in world.keys)
    edit_file(world.path, world, base + b"# a comment at the end of the file\n")
    again = world.walk()
    assert len(world.runs) == 1 and sorted(again["proved"]) == sorted(world.keys), "a comment elsewhere reruns nothing"
    edit_file(world.path, world, base.replace(b"b = 2", b"b = 3"))
    world.walk()
    assert len(world.runs) == 1, "another test's edit reruns nothing"
    edit_file(world.path, world, base.replace(b"    a = 1\n", b"    a = 1 + 0\n", 1))
    world.walk()
    assert len(world.runs) == 2, "an edit of this test's own body reruns"
    plain = World(tmp_path / "p", "ss").install(monkeypatch)       # nothing measured: the file's sha is the key, and the record says so
    monkeypatch.setattr(PBC.proof_level, "instance_identity", lambda *a, **k: {"input_hash": "", "test_code_sha": "", "instance_identity": {}, "why": "x"})
    plain.scenario = fire(0, 1)
    plain.walk()
    got = plain.record(plain.keys[0])
    assert got["bytes_key"] == {"kind": "file_sha", "sha": got["mutated_file"]["sha256"]}, got["bytes_key"]


def test_f4_a_helper_files_edit_reruns_the_helpers_check_only(tmp_path, monkeypatch):
    """A check in a HELPER file is keyed by that file's sha: an edit of the helper reruns the helper's check and carries the test's; a check of the
    test file that lies outside the test's own body (a helper function of the same file) is keyed by the file's sha too. Killed by: the helper
    check keyed by the test instance's code sha (the helper's edit reruns nothing)."""
    from test_probe_walk_edges import HelperWorld
    world = HelperWorld(tmp_path).install(monkeypatch)
    fake_instance_identity(world, monkeypatch)

    def scenario(w, run):
        marks = w.helper_tokens() or run["tokens"]
        return [row("failed", "\n".join(f"AssertionError: qa-probe-{token} {key}" for key, token in marks.items()))]
    world.scenario = scenario
    assert set(verdicts(world.walk()).values()) == {"intended_failure"} and len(world.runs) == 2
    kinds = {key: world.record(key)["bytes_key"]["kind"] for key in world.keys}
    assert kinds == {world.keys[0]: "code_sha", world.keys[1]: "file_sha"}, kinds
    edit_file(world.helper_path, world, world.helper_original + b"# a note in the helper\n")
    again = world.walk()
    assert len(world.runs) == 3 and again["proved"] == [world.keys[0]], "only the helper's check runs"
    from test_probe_every_check import flip_call, flip_models, flip_actual, HELPER_TWO, FIRE_ALL, edited_lines, flip
    same = flip(tmp_path / "s", monkeypatch, "ss", stage="S5", extra=HELPER_TWO)
    fake_instance_identity(same, monkeypatch)
    same.scenario = FIRE_ALL
    keys = [c["key"] for c in PBC._plan_of_test(same.ctx, same.root, [(FILE_OF_TEST, same.path, "5-7")])[0]]
    flip_models(same, flip_actual(same, keys))
    flip_call(same, oracle="expect")
    flip_call(same)
    assert [edited_lines(r) for r in same.runs] == [[6], [7], [3, 4]]
    edit_file(same.path, same, same.original + b"    # a note in the helper function\n")
    flip_call(same)
    assert [edited_lines(r) for r in same.runs][3:] == [[6], [7]], "the helper function's checks rerun; the body's stand"


def test_f4_an_old_record_with_only_the_file_sha_is_read_by_its_old_rule(tmp_path):
    """The rule of `_same_bytes`: a record with no `bytes_key` stands on its `mutated_file.sha256` equal to the file's sha now, whatever instance
    code sha is given, and is NOT a stand on a different file sha (never a silent pass, never a silent drop); a `file_sha` key is read against
    the file's sha even when an instance code sha is now available; a `code_sha` key needs the same code sha and never stands with none; an
    unknown kind or an empty sha never stands. Killed by: reading an old record's missing key as a mismatch (it reruns) or a match."""
    from test_probe_walk import stored
    stored(tmp_path, bytes_key=None)
    assert PBC._check_standing(tmp_path, "i1", 3, 1, "E", "B", None, None, "K") == "intended_failure", "old record: same file sha stands"
    assert PBC._check_standing(tmp_path, "i1", 3, 1, "E", "B2", None, None, "K") == "", "old record: another file sha does not"
    for key, file_sha, code, expected in [({"kind": "file_sha", "sha": "B"}, "B", "K", True), ({"kind": "file_sha", "sha": "B"}, "B2", "K", False),
                                          ({"kind": "code_sha", "sha": "K"}, "B2", "K", True), ({"kind": "code_sha", "sha": "K"}, "B", "K2", False),
                                          ({"kind": "code_sha", "sha": "K"}, "B", "", False), ({"kind": "other", "sha": "K"}, "B", "K", False),
                                          ({"kind": "code_sha", "sha": ""}, "B", "", False)]:
        stored(tmp_path, bytes_key=key)
        got = PBC._check_standing(tmp_path, "i1", 3, 1, "E", file_sha, None, None, code)
        assert (got == "intended_failure") is expected, (key, file_sha, code)


def test_f5_the_aggregate_names_the_edited_helper_and_the_replay_builds_its_oracle(tmp_path, monkeypatch):
    """`--oracle` over a helper file's function while the plan also holds the test's check: `mutated_file` is the HELPER (first of `mutated_files`,
    each file once), `mutation_detail.file` and its line are the helper's, `oracle_function` and `oracle_note` are carried, and
    `proof_level._replay` (which reads `mutated_file.path` and `oracle_function`) builds `<helper>::<function>`. A plain call lists each edited file
    once in plan order. Killed by: `mutated_files` listing the plan's files in plan order whatever the selection (the replay names the test file)."""
    from test_probe_walk_edges import HelperWorld, HELPER
    world = HelperWorld(tmp_path).install(monkeypatch)

    def scenario(w, run):
        marks = w.helper_tokens() or run["tokens"]
        return [row("failed", "\n".join(f"AssertionError: qa-probe-{token} {key}" for key, token in marks.items()))]
    world.scenario = scenario
    plain = world.walk()["record"]
    assert [f["path"] for f in plain["mutated_files"]] == [FILE_OF_TEST, HELPER] and plain["mutated_file"]["path"] == FILE_OF_TEST, plain["mutated_files"]
    world.plan.update(only=[world.keys[1]], oracle_function="expect_cart", oracle_file=HELPER, oracle_note="the check lives in `expect_cart`")
    record = world.walk()["record"]
    assert [f["path"] for f in record["mutated_files"]] == [HELPER, FILE_OF_TEST] and record["mutated_file"]["path"] == HELPER, record["mutated_files"]
    detail = record["mutation_detail"]
    assert detail["file"] == HELPER and detail["line"] == 2 and detail["oracle_function"] == "expect_cart" and detail["oracle_note"], detail
    replay = PBC.proof_level._replay({"instance_id": "i1", "case": "TC-1", "file": FILE_OF_TEST}, world.task_root)
    assert replay and replay["oracle"] == f"{HELPER}::expect_cart", replay


FILE_OF_TEST = "tests/test_t.py"


def test_f6_a_code_written_inversion_is_marked_by_a_field_never_by_its_sentence(tmp_path, monkeypatch):
    """The marker is a FIELD (`entry_by` on the stored row, `by` on the entry code wrote), and `_standing_entry` / `replay_owed` / `_entries_for`
    read it: a row marked `code` is owed to a role whatever its reason says; a row marked `role` that carries the very sentence of the code-written
    reason STANDS; a role cannot type the field (`load_models` refuses an unknown key); an OLD row with only the sentence is read by the old rule
    (the migration edge). End to end: a no-role call stores `code`, and the role's call is refused for the model it still owes. Killed by:
    `_code_written` reading the reason's wording first (the `role` row loses its entry), or ignoring the field (the `code` row stands)."""
    from test_probe_replay import python_world, stored_of
    from test_probe_every_check import flip, flip_call, flip_models, flip_refusal
    data, spec, listed = python_world()
    keys = [c["key"] for c in listed]
    assert PBC.replay_owed(stored_of(listed, "any wording at all", entry_by="code"), data, spec, None, []) == keys, "marked code: owed to a role"
    assert PBC.replay_owed(stored_of(listed, PBC.NO_ROLE_REASON, entry_by="role"), data, spec, None, []) == [], "marked role: the sentence is its own"
    assert PBC.replay_owed(stored_of(listed, PBC.NO_ROLE_REASON), data, spec, None, []) == keys, "old row, sentence only: the old rule (migration edge)"
    assert PBC.replay_owed(stored_of(listed, "R"), data, spec, None, []) == [], "old row, a reason of its own: stands"
    assert "by" not in PBC.MODEL_ENTRY_KEYS and "entry_by" not in PBC.MODEL_ENTRY_KEYS, "a role cannot type the marker"
    world = flip(tmp_path, monkeypatch, "ss", stage="S6")
    closed = flip_call(world)       # no role: the inversion is written by code
    assert [r["entry_by"] for r in closed["checks"]] == ["code"] * 2 and {r["entry"]["by"] for r in closed["checks"]} == {"code"}, closed["checks"]
    world.stage = "S5"
    assert "work/probe-models/D.json" in flip_refusal(world), "what code wrote for no role is owed to the role"
    flip_models(world, [{"check": key, "invert": PBC.NO_ROLE_REASON} for key in world.keys])        # a role that writes the same sentence as ITS reason
    mine = flip_call(world)
    assert [r["entry_by"] for r in mine["checks"]] == ["role"] * 2, mine["checks"]
    (world.task_root / "work" / "probe-models" / "D.json").unlink()
    again = flip_call(world)        # S5, no model file: the role's stored entries stand, however they are worded
    assert [r["probe_kind"] for r in again["checks"]] == ["invert"] * 2 and [r["entry_by"] for r in again["checks"]] == ["role"] * 2


def test_f7_one_ordinal_one_reader(tmp_path):
    """`_ordinal_of` reads a row's own `ordinal` field (else the key's `#n`, else 1), and `_selected_keys` and `_per_check_read` use it: a row whose
    FIELD says 2 is the second check whatever its key looks like. Killed by: `_ordinal_of` or `_selected_keys` parsing the key only."""
    assert PBC._ordinal_of("f:3#2") == 2 and PBC._ordinal_of("f:3") == 1 and PBC._ordinal_of({"key": "f:3#4"}) == 4
    assert PBC._ordinal_of({"key": "f:3", "ordinal": 2}) == 2 and PBC._ordinal_of({"key": "f:3#4", "ordinal": 0}) == 4 and PBC._ordinal_of({"key": "f:3", "ordinal": True}) == 1
    rows = [{"key": "f:3", "file": "f", "line": 3, "end_line": 3, "ordinal": 1}, {"key": "f:3b", "file": "f", "line": 3, "end_line": 3, "ordinal": 2}]
    assert PBC._selected_keys(rows, {"shown": "f", "line": 3, "ordinal": 2, "spans": None}) == ["f:3b"]
    world = World(tmp_path, "s")
    PBC._check_record(world.task_root, "i1", 3, {"verdict": "no_failure", "entry_sha": "E"}, 2, file=FILE_OF_TEST)
    assert PBC._per_check_read(world.ctx, {"key": "tests/test_t.py:3", "line": 3, "file": FILE_OF_TEST, "ordinal": 2})["entry_sha"] == "E"
    assert PBC._per_check_read(world.ctx, {"key": "tests/test_t.py:3", "line": 3, "file": FILE_OF_TEST}) is None, "the first on the line has its own file"


# --- round I1: what the old road refused or recorded BEFORE / AROUND the write (q11, q13, q14, q15, q16) --------------------------------------

def csharp_if_world(tmp_path):
    """`(ctx, entries, checks)` of a C# test whose two checks stand under `#if DEBUG / #else`: the real `checks_of` lists both branches, the
    ctx is the five fields `_locating_refusals` reads, the file is on disk under `tmp_path`. Pure setup."""
    import types
    from test_probe_every_check import SCOPES
    cs = SCOPES["csharp-nunit"]
    text = (cs["head"] + "#if DEBUG\n        Assert.That(a, Is.EqualTo(1));\n#else\n        Assert.That(a, Is.EqualTo(2));\n#endif\n" + cs["tail"])
    root = tmp_path / "proj"
    (root / "tests").mkdir(parents=True)
    (root / cs["file"]).write_text(text, encoding="utf-8")
    spec = PBC.parse_node(cs["node"])
    checks = PBC.checks_of(text.encode(), spec, PBC._reader_entry(spec), [], [], [])
    ctx = types.SimpleNamespace(spec=spec, path=root / cs["file"], root=root, instance_id="i1", entry={"instance_id": "i1"})
    entries = [{"check": c["key"], "kind": "invert", "instance": ""} for c in checks]
    return ctx, entries, checks


def test_q11_a_check_under_conditional_compilation_is_refused_before_the_walk(tmp_path):
    """Two rows of a C# test under `#if/#else`: the located pre-pass raises the old road's ToolRefusal (the directive, its line, "Nothing was
    changed", the product-level door) - for the whole plan and for a selection of one of them - and a plan with NO row to run (`only` empty, or
    every entry `not_here`) is not asked; a file with no directive is not refused. Killed by: `_locating_refusals` not raising (the walk then
    makes two tooling rows AFTER the write), or asking for rows that do not run."""
    ctx, entries, checks = csharp_if_world(tmp_path)
    assert len(checks) == 2, "the planner lists both branches"
    with pytest.raises(PBC.ToolRefusal) as caught:
        PBC._locating_refusals(ctx, entries, checks)
    assert "conditional-compilation directive `#if DEBUG`" in str(caught.value) and "Nothing was changed" in str(caught.value), caught.value
    with pytest.raises(PBC.ToolRefusal):
        PBC._locating_refusals(ctx, entries, checks, only=[checks[1]["key"]])
    PBC._locating_refusals(ctx, entries, checks, only=[])
    PBC._locating_refusals(ctx, [dict(e, kind="not_here") for e in entries], checks)
    ctx.path.write_text(ctx.path.read_text(encoding="utf-8").replace("#if DEBUG\n", "").replace("#else\n", "").replace("#endif\n", ""), encoding="utf-8")
    PBC._locating_refusals(ctx, entries, checks)


def test_q11_the_refusal_aborts_the_call_with_nothing_written_and_the_walk_still_locates(tmp_path, monkeypatch):
    """Through the real call: the second row's locating is a ToolRefusal -> `probe` raises it with the tree, the story folder and the lock
    file byte for byte as before, no run, no record, no aggregate. Each row was located ONCE by the pre-pass (by the one function `_located`);
    with a clean file the same walk then goes on and the walk's own `plan_model` locating finds nothing the pre-pass did not. Killed by:
    calling `_locating_refusals` after `_walk_plan`, or locating from `_walk_attempt` only (the first row is run before the second is
    refused)."""
    world = flip(tmp_path, monkeypatch, "sss", stage="S6")
    real, seen = PBC._located, []

    def located(data, spec, check):
        seen.append((sys._getframe(1).f_code.co_name, check["key"]))
        if check["key"] == world.keys[1] and sys._getframe(1).f_code.co_name == "_locating_refusals":
            raise PBC.ToolRefusal("probe_by_code: tests/test_t.py holds the conditional-compilation directive `#if X` at line 3. Nothing was changed.")
        return real(data, spec, check)

    monkeypatch.setattr(PBC, "_located", located)
    before = flip_snapshot(world.root, world.task_root)
    with pytest.raises(PBC.ToolRefusal) as caught:
        flip_call(world)
    assert "conditional-compilation directive" in str(caught.value) and "Nothing was changed" in str(caught.value)
    assert flip_snapshot(world.root, world.task_root) == before, "not a byte written: no record, no aggregate, no copy, no lock file"
    assert world.runs == [] and not (world.task_root / "work" / "probes").exists()
    assert [k for who, k in seen if who == "_locating_refusals"] == world.keys[:2], "located in plan order, once per row, up to the refused one"
    seen.clear()
    monkeypatch.setattr(PBC, "_located", lambda data, spec, check: (seen.append(check["key"]), real(data, spec, check))[1])
    record = flip_call(world)
    assert record["verdict"] == "intended_failure" and len(world.runs) == 1 and seen.count(world.keys[0]) >= 2, "the walk locates again, never refused after the pre-pass"


def test_q16_a_copy_that_cannot_be_taken_refuses_the_call_before_any_mutation(tmp_path, monkeypatch):
    """The FIRST `begin_copy` of the walk fails: `probe` raises the old road's Refusal (the text of `begin_copy`, "not mutated without one",
    "Nothing was changed"), the project tree and the story folder are byte for byte as before, no run, no record, no aggregate. Control: a
    LATER row's failing copy is that row's tooling outcome (the earlier row stands with its records), as before. Killed by: `_walk_attempt`
    settling the first refusal as a row (the aggregate and the check's record are written), or raising for a later row too (the first row's
    record would be lost)."""
    world = flip(tmp_path, monkeypatch, "sss", stage="S6")

    def no_copy(root, path, original, original_sha, stat, mutated_sha, detail, timeout):
        raise PBC.Refusal("probe_by_code: the byte copy of tests/test_t.py could not be written and verified under X (OSError: no) - the file is not mutated "
                          "without one. Nothing was changed.")

    monkeypatch.setattr(PBC, "begin_copy", no_copy)
    def unlocked(*roots):       # the lock FILE is opened and never deleted by design (`try_lock`); a lock still HELD is checked below
        return {k: v for k, v in flip_snapshot(*roots).items() if not k.endswith(".lock")}

    before = unlocked(world.root, world.task_root)
    text = flip_refusal(world)
    assert "not mutated without one" in text and "Nothing was changed" in text, text
    assert unlocked(world.root, world.task_root) == before and world.runs == [], "the tree and the story folder untouched, nothing run"
    key, _shown = PBC.copy_key(world.path, world.root)
    state, handle = PBC.try_lock(PBC.copy_dir(world.root), key)
    assert state == "locked", "the refused call released its lock"
    handle.release()
    from test_probe_walk_edges import HelperWorld
    monkeypatch.undo()      # the real `begin_copy` again, for the control
    two = HelperWorld(tmp_path / "two").install(monkeypatch)
    real, calls = PBC.begin_copy, []

    def second_fails(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            raise PBC.Refusal("probe_by_code: the byte copy could not be written. Nothing was changed.")
        return real(*a, **k)

    monkeypatch.setattr(PBC, "begin_copy", second_fails)
    two.scenario = lambda w, run: [row("failed", "\n".join(f"AssertionError: qa-probe-{token} {key}" for key, token in (w.helper_tokens() or run["tokens"]).items()))]
    got = two.walk()
    assert len(calls) == 2 and len(two.runs) == 1 and got["record"] is not None, "the first row ran and stands; the second is its own outcome"
    assert verdicts(got)[two.keys[0]] == "intended_failure" and verdicts(got)[two.keys[1]] == "incomplete", verdicts(got)


def tool_args(world, test=None):
    import argparse
    return argparse.Namespace(test=test or TW.NODE, instance="i1", task="T", alternative="")


def read_tool_record(world, monkeypatch, exc):
    """What `main` does with a ToolRefusal: `_record_tool_refusal`, read back from the instance's record path (the manifest row names the file)."""
    monkeypatch.setattr(PBC, "manifest_entry", lambda task_root, iid: {"case": "TC-1", "instance_id": "i1", "file": TW.FILE})
    PBC._record_tool_refusal(tool_args(world), world.task_root, exc)
    path = PBC.record_path(world.task_root, "i1")
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def test_q13_every_tool_refusal_of_the_walk_road_leaves_the_record_the_old_road_left(tmp_path, monkeypatch):
    """The walk road's refusals that are the TOOL's - R6 (`run_shape_checks`), the locating of q11, the empty plan - are `ToolRefusal`s, and the
    record `refused: tool` is written for each by the ONE writer `_record_tool_refusal` (the story's work folder, `probe_could_not_run` reads it as
    the old road's: True for these bytes, `cause: tooling`, the refusal's text in its notes), while the PROJECT's files stay byte for byte. A plain
    `Refusal` (an owed model) leaves none; so does the refusal of a copy (`begin_copy`, the old road's plain Refusal, q16). Killed by:
    `_empty_plan_refusal` returning a plain Refusal (no record), or `_locating_refusals` re-raising as a plain Refusal."""
    def recorded(label, world, exc):
        """Called right after the refusal, while the world's patches are installed: the record the one writer leaves, the project untouched."""
        project = {p: p.read_bytes() for p in sorted(world.root.rglob("*")) if p.is_file()}
        got = read_tool_record(world, monkeypatch, exc)
        assert (got.get("verdict"), got.get("refused"), got.get("cause"), got.get("notes")) == ("not_executed", "tool", "tooling", [str(exc)]), (label, got)
        assert {p: p.read_bytes() for p in sorted(world.root.rglob("*")) if p.is_file()} == project, f"{label}: the project's files are not touched by the record"
        assert got["test_file_sha256"] == PBC.sha256(world.original), label
        assert PBC.proof_level.probe_could_not_run(world.task_root, "i1", got["test_file_sha256"]) is True, label

    world = table_world(tmp_path / "r6", monkeypatch)
    with pytest.raises(PBC.ToolRefusal) as caught:
        flip_call(world)
    recorded("R6", world, caught.value)
    monkeypatch.undo()
    world = flip(tmp_path / "q11", monkeypatch, "sss", stage="S6")
    monkeypatch.setattr(PBC, "_located", lambda *a: (_ for _ in ()).throw(PBC.ToolRefusal(
        "probe_by_code: tests/test_t.py holds the conditional-compilation directive `#if X` at line 3. Nothing was changed.")))
    with pytest.raises(PBC.ToolRefusal) as caught:
        flip_call(world)
    recorded("q11", world, caught.value)
    monkeypatch.undo()
    world = flip(tmp_path / "empty", monkeypatch, "sss", stage="S6")
    monkeypatch.setattr(PBC, "_plan_of_test", lambda ctx, cwd, extra=(): ([], [], []))
    with pytest.raises(PBC.ToolRefusal) as caught:
        flip_call(world)
    assert caught.value.name_unproved is False, "the AST reader proves its name"
    recorded("empty plan", world, caught.value)
    monkeypatch.undo()
    plain = flip(tmp_path / "plain", monkeypatch, "sss", stage="S5")        # a plain Refusal (the call's, or the copy's) is no record of the tool
    assert read_tool_record(plain, monkeypatch, PBC.Refusal("a plain refusal")) == {}, "an owed model / a copy that cannot be taken: no record"


def test_q14_the_copy_meta_keeps_the_statement_before_the_edit(tmp_path, monkeypatch):
    """`begin_copy` is handed the statement's text BEFORE the edit (the author's own), for an `actual`/`find` entry (the located statement's span)
    and for an `invert` entry (the planner's `statement_before`), and the copy's `.meta` on disk holds it - the text the recovery message says to put
    back. Killed by: `_statement_before` returning None (the meta holds null and the recovery says "put back `None`")."""
    for kind in ("actual", "invert"):
        world = World(tmp_path / kind, "ss").install(monkeypatch)
        world.scenario = fire(0, 1)
        real, seen = PBC.begin_copy, []

        def spy(root, path, original, original_sha, stat, mutated_sha, detail, timeout):
            made = real(root, path, original, original_sha, stat, mutated_sha, detail, timeout)
            seen.append((detail.get("statement_before"), json.loads(made["meta"].read_text(encoding="utf-8"))))
            return made

        monkeypatch.setattr(PBC, "begin_copy", spy)
        world.walk(world.entries(kind))
        lines = world.original.decode().splitlines()
        wanted = lines[world.checks[0]["line"] - 1].strip()
        assert seen and seen[0][0] is not None and seen[0][0].strip() == wanted, (kind, seen)
        assert seen[0][1]["statement_before"] == seen[0][0] and seen[0][1]["statement_after"] != seen[0][1]["statement_before"], (kind, seen[0][1])
        monkeypatch.setattr(PBC, "begin_copy", real)


def test_q15_an_unverified_restore_names_the_move_and_the_sha(tmp_path, monkeypatch, capsys):
    """A walk whose restore is NOT verified: its aggregate's `restore` carries the kept copy, the file and the author's sha, and
    `_unrestored_exit` prints the old road's line - `copy <orig> over <file>` and the sha of the bytes it could not put back - with exit 1. A
    VERIFIED restore carries none of these (nothing new is printed; `_unrestored_exit` is not reached). Killed by: dropping the `restore_fact.update(...)`
    of the aggregate (the line says `restore <file> by hand` and `sha256 None`)."""
    world = World(tmp_path, "ss").install(monkeypatch)
    world.scenario = fire(0, 1)
    good = world.walk()["record"]
    assert good["restore"]["verified"] is True and not {"copy", "file", "author_sha256"} & set(good["restore"]), good["restore"]
    bad_world = World(tmp_path / "bad", "ss").install(monkeypatch)
    bad_world.scenario = fire(0, 1)
    monkeypatch.setattr(PBC, "restore", lambda target, original, sha, stat, copy=None: {"verified": False, "sha256": "x", "error": "boom"})
    record = bad_world.walk()["record"]
    sha = PBC.sha256(bad_world.original)
    assert record["restore"]["verified"] is False and record["restore"]["author_sha256"] == sha and record["restore"]["file"] == TW.FILE, record["restore"]
    monkeypatch.setattr(PBC, "project_root", lambda: bad_world.root)
    with pytest.raises(SystemExit) as stopped:
        PBC._unrestored_exit(record)
    assert stopped.value.code == 1
    err = capsys.readouterr().err
    orig = bad_world.root.resolve() / record["restore"]["copy"]
    assert f"copy {orig} over {bad_world.root.resolve() / TW.FILE}" in err and f"sha256 {sha}" in err and "None" not in err, err

# --- fix round I2: what the old road told its reader about a run's rows (open product questions 7-10 of t-2064 P4b) --------------------

def with_contract(monkeypatch, **more):
    """The World's request carries the instance's contract (a hand-written id of the test's file): `selection_rows` reads it, as on the old road."""
    real = PBC.build_request

    def build(*args, **kw):
        request, notes = real(*args, **kw)
        contract = dict({"file": TW.FILE, "report_test_id": f"{TW.FILE}::test_run"}, **more)
        return dict(request, instance_contracts={"i1": contract}), notes

    monkeypatch.setattr(PBC, "build_request", build)


def test_i2_q7_judge_without_check_proves_the_one_unsettled_check(tmp_path, monkeypatch):
    """q7: a ONE-check plan whose run the tool cannot judge (a failure with no marker) leaves the check `incomplete` / `judgment` WITH its
    `judgment_facts`; `--judge <instance>` with no `--check` and the critic's `fires` proves THAT check, the aggregate re-folds to
    `intended_failure` and the receipt appears. With TWO unsettled checks and no `--check` the refusal stays and lists the keys. Killed by:
    `_walk_attempt` not attaching `judgment_facts` to the outcome (the walk's record then owes nothing: the refusal 'no check of this probe owes a
    judgment now'), `_judge_walk` reading an omitted `--check` as a refusal for one unsettled check, or a re-fold that leaves the receipt out."""
    from test_probe_every_check import judged_world, judge_check, judge_refusal
    world, walked = judged_world(tmp_path, monkeypatch, "h", scenario=lambda w, run: [TW.row("failed", "boom: the badge was empty")])
    assert [r["verdict"] for r in walked["checks"]] == ["incomplete"] and walked["receipt"] is None, walked["checks"]
    stored = world.record(world.keys[0])
    assert stored["cause"] == "judgment" and stored["judgment_facts"]["check_key"] == world.keys[0], stored
    record = judge_check(world)       # no --check: exactly one check is unsettled
    assert record["verdict"] == "intended_failure" and record["checks"][0]["proved_by"] == "critic" and record["receipt"], record
    assert world.record(world.keys[0])["judgment"]["verdict"] == "fires"
    other = tmp_path / "two"
    other.mkdir()
    world2, walked2 = judged_world(other, monkeypatch, "hh", scenario=lambda w, run: [TW.row("failed", "boom: the badge was empty")])
    text = judge_refusal(world2)
    assert all(key in text for key in world2.keys) and "--check" in text, text


def test_i2_q8_a_run_with_no_row_of_the_test_says_the_old_roads_note(tmp_path, monkeypatch):
    """q8: the report holds rows, none is the test: the check row is `not_executed`, `cause: tooling` (the tool could not bind), and its note
    is the old road's - 'no row of the junit-xml report ...' with what was looked for and what the report held - not 'report status None'.
    Both bindings (a contract with a file; none). A report with NO row at all: the same text, no cause (a stand that ran nothing). Killed by:
    `_walk_run_once` not asking `_bind_report_rows` (the note is the joint judge's 'report status None')."""
    world = flip(tmp_path, monkeypatch, "h", stage="S6")
    world.scenario = lambda w, run: [TW.row("failed", "x", test_id="tests/test_other.py::test_run")]
    with_contract(monkeypatch)
    record = flip_call(world)
    one = record["checks"][0]
    assert one["verdict"] == "not_executed" and record["verdict"] == "not_executed" and "report status" not in one["note"], one
    assert one["note"].startswith("no row of the junit-xml report is the test the request selected for i1") and "tests/test_other.py::test_run" in one["note"], one["note"]
    assert world.record(world.keys[0])["cause"] == "tooling"
    other = tmp_path / "plain"
    other.mkdir()
    world2 = flip(other, monkeypatch, "h", stage="S6")
    world2.scenario = lambda w, run: []
    record2 = flip_call(world2)
    note = record2["checks"][0]["note"]
    assert record2["checks"][0]["verdict"] == "not_executed" and "no row of the junit-xml report is named 'test_run'" in note and "no rows" in note, note
    assert world2.record(world2.keys[0]).get("cause") is None, "a report that held nothing says nothing about the tool"


def test_i2_q9_two_rows_of_a_hand_written_id_are_ambiguous_never_a_verdict(tmp_path, monkeypatch):
    """q9: a report with TWO rows of the test's hand-written id, both carrying the check's marker: the row is `not_executed`, the note says
    'ambiguous' (the tool cannot tell which row is the test's) - not `intended_failure` and not a verdict on the author; the author's bytes are
    back. A pattern contract (`report_match`: a parametrised test) keeps several rows as one test: both are judged. Killed by:
    `_walk_run_once` taking the selection's rows without the binding's ambiguity rule (the two marked rows prove the check)."""
    world = flip(tmp_path, monkeypatch, "h", stage="S6")
    world.scenario = lambda w, run: [TW.row("failed", TW.thrown(w, run, *run["tokens"])) for _ in range(2)]
    with_contract(monkeypatch)
    record = flip_call(world)
    one = record["checks"][0]
    assert one["verdict"] == "not_executed" and record["verdict"] != "intended_failure" and "ambiguous" in one["note"] and not record["receipt"], one
    assert world.path.read_bytes() == world.original
    other = tmp_path / "param"
    other.mkdir()
    world2 = flip(other, monkeypatch, "h", stage="S6")
    world2.scenario = lambda w, run: [TW.row("failed", TW.thrown(w, run, *run["tokens"])) for _ in range(2)]
    with_contract(monkeypatch, report_match={"pattern": "test_run"})
    assert flip_call(world2)["checks"][0]["verdict"] == "intended_failure", "a pattern's rows are one test: every row proves"


def test_i2_q10_last_attempt_why_is_the_reason_of_the_row_that_did_not_prove(tmp_path):
    """q10: a kept standing `intended_failure` records `last_attempt.why` = the first row that did not prove (its own note), plus the count when
    several did not; a row with no note, or a record with no rows (an old single record), keeps the last note as before; `proved` and `not_owed`
    rows are not 'unproved'. The standing verdict stays. Killed by: `_attempt_why` reading `notes[-1]` for a walk's aggregate (the command line,
    not the reason), or counting the proved row."""
    path = tmp_path / "i1.json"
    standing = {"verdict": "intended_failure", "test_file_sha256": "a" * 64}

    def attempt(rows, notes):
        path.write_text(json.dumps(standing), encoding="utf-8")
        record = {"verdict": "incomplete", "recorded_at": "2026-11-11T00:00:00+00:00", "notes": notes, "checks": rows}
        assert PBC.keep_standing_record(path, record) is True
        kept = json.loads(path.read_text(encoding="utf-8"))
        assert kept["verdict"] == "intended_failure" and kept["last_attempt"]["verdict"] == "incomplete", kept
        return kept["last_attempt"]["why"]

    proved = {"key": "f:1", "verdict": "intended_failure", "note": "proved by marker"}
    skipped = {"key": "f:2", "verdict": "not_owed", "note": "not owed"}
    bad = {"key": "f:3", "verdict": "incomplete", "note": "the run failed and the marker is not in its text; the code critic judges it"}
    assert attempt([proved, skipped, bad], ["the command note"]) == bad["note"]
    assert attempt([proved, bad, dict(bad, key="f:4", note="second")], ["the command note"]) == bad["note"] + " (2 checks did not prove)"
    assert len(attempt([dict(bad, note="x" * 400), dict(bad, key="f:4")], ["n"])) == 300 and attempt([dict(bad, note="x" * 400), bad], ["n"]).endswith("(2 checks did not prove)")
    assert attempt([dict(bad, note="")], ["first", "last note"]) == "last note", "no reason on the row: the aggregate's line, as today"
    assert attempt([], ["only note"]) == "only note" and attempt([], []) == "nothing ran", "an old record with no rows: unchanged"


def test_nv1_a_row_whose_request_was_refused_on_scope_carries_the_refusals_words(tmp_path, monkeypatch):
    """NV-1: the walk builds the request for a row, and the builder refuses it (a check outside the dispatch's scope): the row never ran, so its
    note is the REFUSAL's own words - not 'report status None' - with the verdict `not_executed` and no cause, as the old road wrote; the
    aggregate's `last_attempt.why` (`_attempt_why`, which reads the row note) says them; the author's bytes are back and nothing ran. An empty
    refusal text keeps the old road's note. Killed by: `_walk_attempt` leaving the caught refusal in the notes only (the row note is then
    'report status None' and the why says that)."""
    import execution_request as ER
    words = "TC-100 is outside its scope: dispatch D-9 was given TC-200"

    def refuse(text):
        def build(*args, **kw):
            raise ER.MineRefusal(text)
        monkeypatch.setattr(PBC, "build_request", build)

    world = flip(tmp_path, monkeypatch, "h", stage="S6")
    refuse(words)
    record = flip_call(world)
    one = record["checks"][0]
    assert one["verdict"] == "not_executed" and record["verdict"] == "not_executed" and one["note"] == words, one
    assert world.record(world.keys[0]).get("cause") is None and world.runs == [] and world.path.read_bytes() == world.original
    assert "outside its scope" in PBC._attempt_why(record) and "report status" not in PBC._attempt_why(record), PBC._attempt_why(record)
    other = tmp_path / "empty"
    other.mkdir()
    world2 = flip(other, monkeypatch, "h", stage="S6")
    refuse("")
    note = flip_call(world2)["checks"][0]["note"]
    assert "report status None" in note, note


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
