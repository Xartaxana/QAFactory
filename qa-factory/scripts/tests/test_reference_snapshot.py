#!/usr/bin/env python3
"""t-2181 PC-9a: `reference_snapshot.py put/show` over a real recorder walk (fake backend, no browser, no network).

The reference walk is a `survey` walk on the reference stand; `put` takes its id from the newest S1 dispatch whose purpose is `reference_walk`
(`state/controller.json`) and cites each capture through `walk_session.capture_cited` with that stand. The snapshot is then the reader's data
for `contract.then_oracle_errors` (C7). Run: `python -B test_reference_snapshot.py` (exit code = failures).
"""
import contextlib
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import test_walk_survey_place as S  # noqa: E402
from harness import finish  # noqa: E402

import contract as C  # noqa: E402
import reference_snapshot as RS  # noqa: E402

must, must_eq, must_in = S.must, S.must_eq, S.must_in
QUOTE = "button: Pay"


def dispatches(rig, *rows) -> None:
    """`state/controller.json` with S1 dispatches in order: (walk id, purpose)."""
    state = {"dispatches": {i: {"id": i, "stage": "S1", "role": "qa-runner", "request_binding": {"purpose": p}} for i, p in rows}}
    target = rig.t.task / "state" / "controller.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(state), encoding="utf-8")


def call(rig, items, gaps=(), reference=S.SAMPLE, replace=False, command="put"):
    """(exit code, stdout, stderr) of one CLI call; `items` is written as the items file."""
    argv = [command, "--task-root", str(rig.t.task)]
    if command == "put":
        file = rig.t.task.parent / "items.json"
        file.write_text(json.dumps({"items": items, "gaps": list(gaps)}), encoding="utf-8")
        argv += ["--reference", reference, "--items-file", str(file)] + (["--replace"] if replace else [])
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = RS.main(argv)
    return code, out.getvalue(), err.getvalue()


def item(path, quote=QUOTE, ident=S.ITEM, **over):      # the id of a walked item is the walk's item (`survey-<id>/aN`)
    return {"id": ident, "area": "cart", "user_path": "open the cart", "observed": "a Pay button is shown",
            "evidence": [{"path": path, "quote": quote}], "locators_portable": "unknown", **over}


def written(rig):
    return RS.snapshot_path(rig.t.task).exists()


def test_put_cites_captures_and_the_contract_reads_the_items():
    with S.survey(env=S.SAMPLE) as rig:
        path = S.looked(rig)
        dispatches(rig, ("S1-first-look", "initial"), (S.WALK, "reference_walk"))
        code, out, err = call(rig, [item(path, ident="R-1"), {"id": "old-only", "area": "cart", "user_path": "p", "observed": "o",
                                                              "old_test": "tests/cart.spec.ts:12", "locators_portable": "yes"}])
        must_eq("a capture of the reference walk and an old test are both accepted", (code, err), (0, ""))
        data = RS.read(rig.t.task)
        must_eq("the stand and the cited capture PATHS are kept", (data["reference_env"], data["items"][0]["evidence"]), (S.SAMPLE, [path]))
        must_eq("an old-test-only item keeps its ref", data["items"][1]["old_test"], "tests/cart.spec.ts:12")
        must_eq("a cited path is stored with forward slashes", "\\" in data["items"][0]["evidence"][0], False)
        must_eq("the reader gives the ids", RS.item_ids(rig.t.task), {"R-1", "old-only"})
        must_in("show prints the file", "reference_env", call(rig, [], command="show")[1])
        raw = json.dumps([{"then": 1, "source": "precedent", "ref": "reference:old-only"}])
        must_eq("C7 accepts a Then citing an item through the reader's ids", C.then_oracle_errors(
            "TC.md", raw, None, [1], snapshot_items=RS.item_ids(rig.t.task), parity={"R-9"}, basis="requirement:R-9"), [])
        code, _, err = call(rig, [item(path.replace("/", "\\"), ident="R-1")], replace=True)
        stored = RS.read(rig.t.task)["items"][0]["evidence"][0] if code == 0 else path
        must("a backslash-typed path is stored with forward slashes (or refused)", "\\" not in stored, err)


def test_refusals_name_a_door_and_write_nothing():
    with S.survey(env=S.SAMPLE) as rig:
        path = S.looked(rig)
        dispatches(rig, (S.WALK, "reference_walk"))
        no_cite = {"id": "bare", "area": "a", "user_path": "p", "observed": "o", "locators_portable": "no"}
        for label, items, gaps, want in (
                ("no evidence and no old test", [no_cite], [], "no capture"),
                ("words that are not in the capture", [item(path, quote="a button nobody drew")], [], "Door:"),
                ("a capture cited by name alone", [item(path, ident="x") | {"evidence": [path]}], [], "{path, quote}"),
                ("an old test with no line", [no_cite | {"old_test": "tests/cart.spec.ts"}], [], "old_test"),
                ("a portable word outside the list", [item(path, locators_portable="maybe")], [], "locators_portable"),
                ("an empty area", [item(path, area=" ")], [], "`area` is empty"),
                ("an id that is no plain id", [item(path, ident="a b")], [], "plain id"),
                ("a repeated id", [item(path), item(path)], [], "unique"),
                ("an empty snapshot with no gap line", [], [], "gap line")):
            code, _, err = call(rig, items, gaps)
            must(f"{label} is refused, naming what to do, and nothing is written", code == 2 and want in err and not written(rig), err)
        code, _, err = call(rig, [], ["the old version at preview could not be reached: no route"])
        must_eq("`items: []` with a gap line is the empty outcome", (code, RS.read(rig.t.task)["items"]), (0, []))
        must("a second put needs --replace", call(rig, [item(path)])[0] == 2 and RS.read(rig.t.task)["items"] == [])
        must_eq("and with it the snapshot is replaced", (call(rig, [item(path)], replace=True)[0], len(RS.read(rig.t.task)["items"])), (0, 1))


def test_absent_snapshot_world():
    with S.survey(env=S.SAMPLE) as rig:
        must_eq("no snapshot: no ids", RS.item_ids(rig.t.task), None)
        code, out, _ = call(rig, [], command="show")
        must("show says there is none and exits 0", code == 0 and "no reference snapshot" in out, out)
        must_eq("no controller state: no reference walk", RS.reference_walk(rig.t.task), "")


def test_reference_put_refuses_first_look_capture():
    """A first look walks the stand under test; its captures are no evidence of the reference (J-C2)."""
    with S.survey(env=S.LOCAL) as rig:
        path = S.looked(rig)
        for label, rows, want in (
                ("a story with only first-look dispatches", [(S.WALK, "initial")], "no S1 dispatch with purpose `reference_walk`"),
                ("a walk of the stand under test taken for the reference", [(S.WALK, "reference_walk")], f"`{S.LOCAL}`, not `{S.SAMPLE}`"),
                ("a newer reference dispatch that is not the walk the capture came from",
                 [(S.WALK, "reference_walk"), ("S1-newer", "reference_walk")], "no record")):
            dispatches(rig, *rows)
            code, _, err = call(rig, [item(path)])
            must(f"{label}: refused, nothing written", code == 2 and want in err and not written(rig), err)


if __name__ == "__main__":
    test_put_cites_captures_and_the_contract_reads_the_items()
    test_refusals_name_a_door_and_write_nothing()
    test_absent_snapshot_world()
    test_reference_put_refuses_first_look_capture()
    finish("reference snapshot")
