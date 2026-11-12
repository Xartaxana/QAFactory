#!/usr/bin/env python3
"""F7 (t-087 rev 9, K-M3-25): `handoff_check.check` accepts the S7 analyst form of an INVESTIGATION dispatch with an empty
`scope` and an empty / placeholder `not_for_repair`, whatever `work/triage.json` holds; every other dispatch keeps today's check.

The dispatch id is the form's FILE STEM (the S7 header carries no dispatch field); the record is read through
`s5_precheck.dispatch_record`. Keys: K-M3-25a, b, b2, c, c2, n1, n2, n3, d.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check_eq, check_in, check_not_in, cleanup, finish, run_script  # noqa: E402
import test_s7_null_outcome as T  # noqa: E402  (its fixtures: the real template, a triage task root)

HC, handoff = T.HC, T.handoff
DISPATCH = T.DISPATCH


def with_record(task: Path, purpose) -> None:
    """`state/controller.json` holding the dispatch record: an S7 analyst dispatch of the given purpose word."""
    record = {"id": DISPATCH, "stage": "S7", "role": "qa-failure-analyst", "request_binding": {"purpose": purpose}}
    T.write_json(task / "state" / "controller.json", {"dispatches": {DISPATCH: record}})


def verdict(form: str, task: Path, *, fix=False):
    art = HC.Artifacts(task, dispatch=DISPATCH)
    doc, fixed, problems, _j, _d = HC.check(handoff.parse(form), T.CONTRACT, art, fix=fix, use_judge=False)
    return doc, fixed, problems


def paths(problems) -> list:
    return [p.path for p in problems]


TEST_BUG_ROW = T.instance_row("test_late[1]", "TEST_BUG", fix_result="fixed")


def keys() -> None:
    rows = T.cmp2r_rows()
    # K-M3-25a: an investigation record, NO work/triage.json -> accepted (today: "scope: no rows" or the untriaged report)
    task = T.a_task(None, report=None)
    try:
        with_record(task, "investigation")
        _d, _f, problems = verdict(T.a_form(nfr=[]), task)
        check_eq("K-M3-25a: investigation record, no triage.json: accepted", paths(problems), [])
    finally:
        cleanup(task)
    # K-M3-25b: a TEST_BUG row `fix_result: fixed` in the triage -> accepted; K-M3-25n2 the same under a TRIAGE record -> refused
    task = T.a_task(rows + [TEST_BUG_ROW])
    try:
        with_record(task, "investigation")
        _d, _f, problems = verdict(T.a_form(nfr=[]), task)
        check_eq("K-M3-25b: triage with a TEST_BUG row fixed: accepted", paths(problems), [])
        # K-M3-25b2: `not_for_repair` holding only the template's placeholder row -> accepted
        _d, _f, problems = verdict(T.a_form(nfr=None), task)
        check_eq("K-M3-25b2: not_for_repair = the placeholder row only: accepted", paths(problems), [])
        # K-M3-25c: --fix opens no row
        doc, fixed, problems = verdict(T.a_form(nfr=[]), task, fix=True)
        check_eq("K-M3-25c: --fix under the investigation view opens no row",
                 ([f for f in fixed if "not_for_repair" in f], doc.data.get("not_for_repair")), ([], []))
        # K-M3-25n2 (negative control): the SAME form under a triage record -> today's refusal
        with_record(task, "triage")
        _d, _f, problems = verdict(T.a_form(nfr=[]), task)
        check_in("K-M3-25n2: the same form under a TRIAGE record: today's refusal", "TEST_BUG", T.text_of(problems))
        check_eq("K-M3-25n2: ...and it names scope", "scope" in paths(problems), True)
        # K-M3-25n3: unreadable state/controller.json -> today's refusals (error direction)
        (task / "state" / "controller.json").write_text("{not json", encoding="utf-8")
        _d, _f, problems = verdict(T.a_form(nfr=[]), task)
        check_in("K-M3-25n3: corrupt controller.json: today's refusal", "TEST_BUG", T.text_of(problems))
        (task / "state" / "controller.json").unlink()
        _d, _f, problems = verdict(T.a_form(nfr=[]), task)
        check_in("K-M3-25n3: absent controller.json: today's refusal", "TEST_BUG", T.text_of(problems))
    finally:
        cleanup(task)
    # K-M3-25c2: a non-list scope / not_for_repair under the investigation record -> "must be a list"
    task = T.a_task(None, report=None)
    try:
        with_record(task, "investigation")
        for label, form in (("scope: {}", T.replace_section(T.a_form(nfr=[]), "scope", "scope: {}")),
                            ('scope: "x"', T.replace_section(T.a_form(nfr=[]), "scope", 'scope: "x"')),
                            ("not_for_repair: {}", T.replace_section(T.a_form(nfr=[]), "not_for_repair", "not_for_repair: {}"))):
            _d, _f, problems = verdict(form, task)
            check_in(f"K-M3-25c2: {label} refused 'must be a list'", "must be a list", T.text_of(problems))
        # K-M3-25n1: a non-empty scope / a non-empty not_for_repair -> the F7 text
        _d, _f, problems = verdict(T.a_form(scope=[("test_late[1]", "TEST_BUG")], nfr=[]), task)
        check_in("K-M3-25n1: non-empty scope refused with the F7 text",
                 "an investigation hands nothing for repair and relists no triage row: `scope` is not empty; the triage is not yours to change",
                 T.text_of(problems))
        _d, _f, problems = verdict(T.a_form(nfr=[("a1", "ENV_ISSUE")]), task)
        check_in("K-M3-25n1: non-empty not_for_repair refused with the F7 text",
                 "`not_for_repair` is not empty; the triage is not yours to change", T.text_of(problems))
    finally:
        cleanup(task)


def minimal_form(*, filled: bool) -> str:
    """Header + `scope: []` (+ the `inputs_read` row with `version` and `failures` when `filled`); the rest as the template."""
    doc = handoff.parse(T.untouched_form())
    if filled:
        for path, value in (("inputs_read[0].version", "cfa50cc02493c8b8"), ("inputs_read[0].failures", 7)):
            handoff.set_value(doc, path, value)
            doc = handoff.parse(doc.text())
    return T.replace_section(doc.text(), "scope", "scope: []")


def cli_untouched() -> None:
    """K-M3-25d: through the CLI, the minimal investigation form is not `untouched`; header + `scope: []` only is."""
    task = T.a_task(None, report=None)
    try:
        with_record(task, "investigation")
        form = task / "work" / "handoffs" / f"{DISPATCH}.yaml"
        form.parent.mkdir(parents=True, exist_ok=True)
        # DIVERGENCE from the spec (reported): the real template pre-fills `inputs_read[0].path`, a leaf `filled_share` counts
        # (generic `inputs_read[].path` is blank in row 1), so even the header-only form reads `filled == 1`, `untouched` False.
        # The negative control is therefore the filled COUNT (1 without the row, 3 with it), not `untouched` True.
        for filled, expected_untouched, expected_filled in ((True, False, 3), (False, False, 1)):
            form.write_text(minimal_form(filled=filled), encoding="utf-8")
            done = run_script("handoff_check.py", "--file", form, "--task-root", task, "--no-judge", "--fix", "--json")
            report = json.loads(done.stdout)
            check_eq(f"K-M3-25d: CLI --fix --json, inputs_read row filled={filled}: untouched is {expected_untouched}",
                     report["untouched"], expected_untouched)
            check_eq(f"K-M3-25d: filled={filled}: the filled count is {expected_filled}", report["filled"], expected_filled)
            check_not_in(f"K-M3-25d: filled={filled}: no scope refusal", "scope: no rows",
                         "\n".join(p["path"] + ": " + p["problem"] for p in report["problems"]))
    finally:
        cleanup(task)


def main() -> None:
    keys()
    cli_untouched()
    finish("test_handoff_check_investigation")


if __name__ == "__main__":
    main()
