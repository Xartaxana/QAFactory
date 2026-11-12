#!/usr/bin/env python3
"""TR3-10 E: the S3 plan row's optional `walk_data` / `walk_global` - checked by SHAPE only, carried whole into request.json, and the
strategist is told they exist (FR-38, AR-10; AR-29: nothing here judges whether what the strategist wrote is RIGHT).
KEYS: walk_data_shape_each_bad_refused, walk_global_blank_refused, absent_field_no_constraint, prepare_request_carries_both_whole,
strategist_line_present, role_load_raise_named, unprepared_request_carries_walk_fields, walk_line_in_s3_head_once,
shape_check_any_disposition.
Mutations (each killed by THIS file): `exclusive` accepted as text -> walk_data_shape_each_bad_refused; a blank `walk_global`
accepted -> walk_global_blank_refused; an absent field refused -> absent_field_no_constraint; the request built without the fields or
with reworded text -> prepare_request_carries_both_whole; the brief line dropped -> strategist_line_present; the ratchet row moved
back or another row changed -> role_load_raise_named; `_unprepared_document` without `_walk_fields` ->
unprepared_request_carries_walk_fields; the line back inside `request_lines` or dropped from the S3 head ->
walk_line_in_s3_head_once; the shape check back on `manual-agent` rows only -> shape_check_any_disposition."""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import harness  # noqa: E402
from harness import SCRIPTS, check, check_eq, check_in, finish  # noqa: E402
import scaffold as S  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import brief_pack as BP  # noqa: E402
import manual_evidence as M  # noqa: E402
import planning_contract as PC  # noqa: E402

PACKAGE = SCRIPTS.parent
GOOD_ENTRY = {"kind": "book", "exclusive": True, "changes": "deletes one book"}


def manual_row(**fields):
    """The plan's manual-agent row of the api case (TS-12) with `fields` added, and the plan the check reads."""
    t = S.make_task(manual=("api",))
    try:
        row = copy.deepcopy(t.row("TS-12"))
    finally:
        S.cleanup(t)
    row.update(fields)
    return row


def problems(row) -> list:
    """The walk-field problems of the plan check on this one row (the shape check lives inside `validate_plan`)."""
    return [e for e in PC.validate_plan([row]) if "walk_data" in e or "walk_global" in e]


def walk_data_shape_each_bad_refused():
    check_eq("good walk_data: no problem", problems(manual_row(walk_data=[GOOD_ENTRY])), [])
    check_eq("good walk_data with `exclusive: false` and an empty `changes`: no problem",
             problems(manual_row(walk_data=[{"kind": "x", "exclusive": False, "changes": ""}])), [])
    bad = {
        "a non-list walk_data (object)": ({"walk_data": GOOD_ENTRY}, "walk_data must be a list"),
        "a non-list walk_data (text)": ({"walk_data": "book"}, "walk_data must be a list"),
        "a null walk_data": ({"walk_data": None}, "walk_data must be a list"),
        "an entry that is not an object": ({"walk_data": ["book"]}, "walk_data[0] must be an object"),
        "a blank kind": ({"walk_data": [dict(GOOD_ENTRY, kind="  ")]}, "walk_data[0].kind"),
        "a missing kind": ({"walk_data": [{"exclusive": True, "changes": "x"}]}, "walk_data[0].kind"),
        "a kind that is not text": ({"walk_data": [dict(GOOD_ENTRY, kind=3)]}, "walk_data[0].kind"),
        "an exclusive given as text": ({"walk_data": [dict(GOOD_ENTRY, exclusive="true")]}, "walk_data[0].exclusive"),
        "an exclusive given as a number": ({"walk_data": [dict(GOOD_ENTRY, exclusive=1)]}, "walk_data[0].exclusive"),
        "a missing exclusive": ({"walk_data": [{"kind": "book", "changes": "x"}]}, "walk_data[0].exclusive"),
        "a changes that is not text": ({"walk_data": [dict(GOOD_ENTRY, changes=["x"])]}, "walk_data[0].changes"),
        "a missing changes": ({"walk_data": [{"kind": "book", "exclusive": True}]}, "walk_data[0].changes"),
        "the second entry bad": ({"walk_data": [GOOD_ENTRY, dict(GOOD_ENTRY, exclusive="yes")]}, "walk_data[1].exclusive"),
    }
    for label, (fields, needle) in bad.items():
        row = manual_row(**fields)
        found = problems(row)
        check(f"{label}: refused", bool(found), str(found))
        check_in(f"{label}: names the field", needle, " ".join(found))
        check_in(f"{label}: names the row", row["id"] + ":", " ".join(found))
        check(f"{label}: gives the right shape (an example)", "e.g." in " ".join(found), str(found))
        check_in(f"{label}: refused by the plan check as a whole", needle, " ".join(PC.validate_plan([row])))
    # E.4: a kind of 200+ characters, with `/` or quotes, is kept as given: the shape check does not touch it
    for kind in ("k" * 250, "a/b", 'say "hi"', "it's"):
        check_eq(f"E.4 kind {kind[:12]!r}: well-formed, no problem", problems(manual_row(walk_data=[dict(GOOD_ENTRY, kind=kind)])), [])


def shape_check_any_disposition():
    """F12: the carrier takes the fields from every row that owns the case's obligations, so the shape check runs on every row that
    carries them, whatever its disposition."""
    other = manual_row(disposition="automate", walk_data="nonsense")
    found = problems(other)
    check("a non-manual-agent row with a malformed walk_data is refused", bool(found), str(found))
    check_in("... naming the row and the field", other["id"] + ": walk_data must be a list", " ".join(found))
    blank = problems(manual_row(disposition="automate", walk_global=""))
    check("`walk_global: \"\"` on a non-manual-agent row is refused by shape", bool(blank), str(blank))
    check_eq("a good field on a non-manual-agent row: no problem",
             problems(manual_row(disposition="automate", walk_data=[GOOD_ENTRY], walk_global="x")), [])
    check_eq("absent fields on a non-manual-agent row: no constraint", problems(manual_row(disposition="automate")), [])


def walk_global_blank_refused():
    check_eq("a reason: no problem", problems(manual_row(walk_global="the Then counts every book")), [])
    for label, value in (("empty", ""), ("blanks", "   "), ("null", None), ("a number", 3), ("a list", ["x"])):
        row = manual_row(walk_global=value)
        found = problems(row)
        check(f"walk_global {label}: refused", bool(found), str(found))
        check_in(f"walk_global {label}: names the field", "walk_global must be non-blank text", " ".join(found))
        check(f"walk_global {label}: gives an example", "e.g." in " ".join(found), str(found))
        check_in(f"walk_global {label}: refused by the plan check as a whole", "walk_global", " ".join(PC.validate_plan([row])))


def absent_field_no_constraint():
    row = manual_row()
    check("the scaffold row names neither field", "walk_data" not in row and "walk_global" not in row)
    check_eq("E.1 absent fields: no problem", problems(row), [])
    check_eq("E.3 `walk_data: []` is not said: no problem", problems(manual_row(walk_data=[])), [])
    check("absent fields add nothing to the plan check", not any("walk_" in e for e in PC.validate_plan([row])))
    t = S.make_task(manual=("api",))
    try:
        with t.patched():
            request = M.prepare_request(t.task, S.CASES["api"], ["OB-12"])
        check("the request of a plan with no field carries neither key (no constraint)", "walk_data" not in request and "walk_global" not in request,
              str(sorted(request)))
        t.row("TS-12")["walk_data"] = []
        t.write_plan()
        with t.patched():
            request = M.prepare_request(t.task, S.CASES["api"], ["OB-12"])
        check("E.3 `walk_data: []` carries no key either", "walk_data" not in request)
    finally:
        S.cleanup(t)


def prepare_request_carries_both_whole():
    data = [dict(GOOD_ENTRY, kind="Book / \"odd\" " + "k" * 250, changes="removes it; the count drops"),
            {"kind": "cart", "exclusive": False, "changes": "adds a line"}]
    reason = "the Then counts every book, in every lane"
    t = S.make_task(manual=("api",))
    try:
        row = t.row("TS-12")
        row["walk_data"], row["walk_global"] = copy.deepcopy(data), reason
        t.write_plan()
        with t.patched():
            request = M.prepare_request(t.task, S.CASES["api"], ["OB-12"])
        check_eq("walk_data travels whole (no rewording, no cut, no reorder)", request.get("walk_data"), data)
        check_eq("walk_global travels whole", request.get("walk_global"), reason)
        row["walk_data"] = [{"kind": "x", "exclusive": "yes", "changes": "y"}]
        t.write_plan()
        try:
            with t.patched():
                M.prepare_request(t.task, S.CASES["api"], ["OB-12"])
            check("a malformed field is refused with the plan's own check, never carried", False)
        except M.Refused as exc:
            check_in("a malformed field: the refusal names the field and the shape", "walk_data[0].exclusive", exc.args[2] if len(exc.args) > 2 else str(exc))
    finally:
        S.cleanup(t)


def unprepared_request_carries_walk_fields():
    """F10 (AR-21, FR-49, AR-28): a case through the unprepared (walkable) door carries walk_data / walk_global whole, so it is never
    walked with 'no constraint' when its row said `exclusive: true`."""
    data = [dict(GOOD_ENTRY, kind="Book / \"odd\"", changes="removes it; the count drops")]
    reason = "the Then counts every book"
    t = S.make_task(manual=("ui",))
    try:
        row = t.row("TS-7")
        policy = {"not": "one word"}
        row["evidence_policy"] = policy
        for ob in row["coverage_obligations"]:
            ob["evidence_policy"] = policy
        row["walk_data"], row["walk_global"] = copy.deepcopy(data), reason
        t.write_plan()
        case = S.CASES["ui"]
        with t.patched():
            try:
                M.prepare_to_file(t.task, case, ["OB-7"])
                check("the dict policy leaves the case unprepared (the walkable door)", False)
            except M.Refused as exc:
                check("the refusal is the walkable one", exc.walkable is True)
        doc = json.loads(M.request_path(t.task, case).read_text(encoding="utf-8"))
        check("the document is the unprepared one", "unprepared" in doc and "refused" not in doc, str(sorted(doc)))
        check_eq("unprepared: walk_data kept whole (with `exclusive: true`)", doc.get("walk_data"), data)
        check_eq("unprepared: walk_global kept whole", doc.get("walk_global"), reason)
        row.pop("walk_data"), row.pop("walk_global")
        t.write_plan()
        with t.patched():
            try:
                M.prepare_to_file(t.task, case, ["OB-7"])
            except M.Refused:
                pass
        doc = json.loads(M.request_path(t.task, case).read_text(encoding="utf-8"))
        check("unprepared with no field said: neither key (no constraint)", "walk_data" not in doc and "walk_global" not in doc, str(sorted(doc)))
    finally:
        S.cleanup(t)


def s3_head(flow_raises: bool) -> list:
    """The S3 brief of the strategist as `brief_pack.build` makes it, with the flow requests working or raising."""
    import judge
    from unittest.mock import patch
    import user_path_failures as UPF
    root = harness.temp_project("walk-line-")
    try:
        harness.use_project(root)
        task = root / "qa-factory" / "artifacts" / "QA-9"
        (task / "work").mkdir(parents=True)
        (task / "pipeline.json").write_text(json.dumps(
            {"ticket": "QA-9", "size": "S", "environment": "local", "implementation_source": "diff",
             "stages": {"S0": {"status": "pending"}}, "gates": {}, "halts": []}), encoding="utf-8")
        with patch.object(judge, "active", return_value=False):
            if flow_raises:
                with patch.object(UPF, "flow_requests", side_effect=RuntimeError("boom")):
                    built = BP.build("QA-9", "S3", "qa-test-strategist", "S3-qa-test-strategist-1", write=False)
            else:
                built = BP.build("QA-9", "S3", "qa-test-strategist", "S3-qa-test-strategist-1", write=False)
        return built["markdown"].splitlines()
    finally:
        harness.cleanup(root)


def walk_line_in_s3_head_once():
    """F11: the strategist line is emitted ONCE in the S3 head (so it shows when the flow requests fail), and is no part of
    `request_lines` (so `user_path_failures` does not print it)."""
    for flow_raises in (False, True):
        lines = s3_head(flow_raises)
        mine = [x for x in lines if x.startswith("Walk data: ")]
        label = "flow requests failing" if flow_raises else "flow requests working"
        check_eq(f"{label}: the S3 brief carries the line exactly once", len(mine), 1)
        check_eq(f"{label}: and it is the constant", mine[:1], [BP.WALK_DATA_LINE])
        if flow_raises:
            check("flow requests failing: their own `not measured` line is there too",
                  any(x.startswith("Flow requests: not measured") for x in lines))
    req = {"key": "GET /api/r1", "method": "GET", "url_template": "/api/r1", "path": "App/src/a.ts", "line": 1}
    for found in ({"requests": [], "unmeasured": []}, {"requests": [req], "unmeasured": []}):
        check("request_lines carries no walk line", not any(x.startswith("Walk data: ") for x in BP.request_lines(found, "QA-9")))
    src = (SCRIPTS / "user_path_failures.py").read_text(encoding="utf-8")
    check("user_path_failures carries no walk line of its own", "Walk data" not in src)


def strategist_line_present():
    check("the line names both fields and the shape",
          all(s in BP.WALK_DATA_LINE for s in ("`walk_data`", "`walk_global`", "kind", "exclusive", "changes")), BP.WALK_DATA_LINE)
    req = {"key": "GET /api/r1", "method": "GET", "url_template": "/api/r1", "path": "App/src/a.ts", "line": 1}
    with_requests = BP.request_lines({"requests": [req], "unmeasured": []}, "QA-9")
    check("the closing line of the flow requests stays last", "each one gets a plan row" in with_requests[-1], with_requests[-1][:60])
    charter = (PACKAGE / "agents" / "qa-test-strategist.md").read_text(encoding="utf-8")
    check_in("the charter carries the experience sentence, exactly",
             "a manual check that changes a record other checks read says which kind and whether it must be its own.", charter)


def role_load_raise_named():
    """AR-20: the strategist's rows rise by what the sentence cost and by nothing else; every other row is the old number."""
    doc = json.loads((PACKAGE / "references" / "role-load.json").read_text(encoding="utf-8"))
    # TR3-10 part E set 16747 / 15286; the approved J-15 raises since then (AR-20, named in the commits): f571cdf10 PK0-3 fix round re-measured
    # the strategist rows to 16804 / 15346; 8f21582c7 (t-2385, merged by 307a8f258) raised qa-automator to 19754 / 18467 and qa-code-critic
    # to 18909 / 17431 after PC-3 contract text. t-2391 (J-15 (a)) raised the strategist to 16854 / 15396 for the regenerated key page.
    # c1f65a401 (PC-6) raised qa-runner 15641 -> 15697 and 4ca13f671 (PK0-8) its process row 14433 -> 14434 (AR-20, named in those commits).
    # The merged experiment branch raised qa-requirements-tester 12496 -> 12590, qa-automator 19754 -> 19859 and qa-code-critic 18909 -> 19101
    # (their J-15 raises, AR-20); the process ceilings of the automator and the code critic only shrank by one token (allowed).
    # Joint plan t-2277 (AR-20, named in the merge commits): FL-3 raised qa-runner to 16124; FL-7 raised qa-automator to 20149 / 18607
    # and qa-code-critic to 19373 / 17571; the FL-7 merge set six rows to the measured +4/+5 drift of the experiment branch
    # (tester 12594 / 11244, designer 13269 / 12072, case critic process 15942, bug reporter 14811 / 13931, scribe (the t-2277 batch 2a +15, the `real_or_mock` form line, is re-stated below),
    # retro 14086 / 13217) and lowered the runner's process row to 14433. FL-4 (t-2277, fix round t-2506, J-15, AR-20): the first-look craft
    # paragraphs raised the strategist to 16925, the case designer to 13331 / 12094 and the case critic to 18308 (its process row stays 15941,
    # below the frozen 15942). PC-9b (t-2524) names the reference snapshot as an S1 output and an S2 input in stages.json: the scout
    # 15425 -> 15441 / 13963 -> 13979, the requirements tester 12594 -> 12609 / 11244 -> 11259. PC-9c fix round (t-2551, B1): one charter sentence
    # (claims cite `reference:<item>`) is counted in the row set below. The pins below follow role-load.json.
    check_eq("strategist ratchet: 16718 -> 16747 (TR3-10 e) -> 16804 (f571cdf10, J-15) -> 16854 (t-2391, J-15 (a): the regenerated key page, 3 product_roles lines) -> 16925 (FL-4: one craft sentence)", doc["ratchet_tokens"]["qa-test-strategist"], 16925)
    check_eq("strategist process ratchet: 15287 -> 15286 (TR3-10 e) -> 15346 (f571cdf10, J-15) -> 15396 (t-2391, same)",
             doc["process_ratchet_tokens"]["qa-test-strategist"], 15396)
    # t-2554 (J-15, AR-20): the name `reference-snapshot.yaml` in the artifact tree of artifact-contract.md (test_stages needs it there; every
    # slice of that file carries the tree) raised six roles by 6-7 tokens: tester 12609 -> 12616 / 11259 -> 11266, designer 13331 -> 13338 /
    # 12094 -> 12101, case critic 18308 -> 18315 / 15941 -> 15948, bug reporter 14811 -> 14817 / 13931 -> 13937, scribe 17944 -> 17950 /
    # 16954 -> 16960, retro 14086 -> 14092 / 13217 -> 13223.
    # PC-9c fix round (t-2551, B1; on top of the t-2554 rows): one charter sentence takes the tester 12616 -> 12649 / 11266 -> 11299.
    # Merge of the probe chain (t-2064 TR2-14, AR-20): the joined wording, by measurement - qa-automator 20149 -> 20181 / 18607 -> 18614,
    # qa-code-critic 19373 -> 19389 / 17571 -> 17566.
    # t-2277 batch 2a (AR-20, named in the commit): the scribe's `real_or_mock` form line is +15, re-measured on the merged tree with
    # `role_load.py --all`: scribe 17950 -> 17965 / 16960 -> 16975.
    # The first canon after the merge into main (FG7-9, AR-20: rows lowered, none raised): the s5-plan sentence of artifact-contract.md
    # is back under the qa-automator marker, so the six slice holders stopped carrying it, and the shorter tracker key of the moved
    # repository took a few bytes off four forms. Re-measured with `role_load.py --all`: scout 15441 -> 15437, tester 12649 -> 12630,
    # designer 13338 -> 13320, case critic 18315 -> 18296, bug reporter 14817 -> 14799, scribe 17965 -> 17944, retro 14092 -> 14075.
    old = {"qa-scout": 15437, "qa-requirements-tester": 12630, "qa-case-designer": 13320, "qa-case-critic": 18296, "qa-automator": 20181,
           "qa-code-critic": 19389, "qa-runner": 16124, "qa-failure-analyst": 18361, "qa-bug-reporter": 14799, "qa-doc-scribe": 17944,
           "qa-retro-analyst": 14075}
    old_process = {"qa-scout": 13979, "qa-requirements-tester": 11299, "qa-case-designer": 12101, "qa-case-critic": 15948,
                   "qa-automator": 18614, "qa-code-critic": 17566, "qa-runner": 14434, "qa-failure-analyst": 16336,
                   "qa-bug-reporter": 13937, "qa-doc-scribe": 16975, "qa-retro-analyst": 13223}
    check_eq("every other role's ratchet is unchanged", {k: v for k, v in doc["ratchet_tokens"].items() if k != "qa-test-strategist"}, old)
    others = {k: v for k, v in doc["process_ratchet_tokens"].items() if k != "qa-test-strategist"}

    def raised(current):
        return sorted(k for k, v in current.items() if k not in old_process or v > old_process[k]) + sorted(set(old_process) - set(current))

    check_eq("every other role's process ratchet is at or below its frozen ceiling (a shrink is allowed, a raise is not)", raised(others), [])
    check_eq("negative control: a raised process ratchet of one other role is reported",
             raised(dict(others, **{"qa-scout": old_process["qa-scout"] + 1})), ["qa-scout"])
    fragment = (PACKAGE / "changelog.d" / "tr3-10e-walk-data-field.md").read_text(encoding="utf-8")
    check_in("the changelog fragment names the raise old -> new", "16718 -> 16747", fragment)


def main():
    walk_data_shape_each_bad_refused()
    walk_global_blank_refused()
    absent_field_no_constraint()
    shape_check_any_disposition()
    prepare_request_carries_both_whole()
    unprepared_request_carries_walk_fields()
    walk_line_in_s3_head_once()
    strategist_line_present()
    role_load_raise_named()
    finish("test_walk_plan_fields")


if __name__ == "__main__":
    main()
