#!/usr/bin/env python3
"""The handoff form: a header, one line per item in scope, a path — and nothing else.

The shapes here are the real ones. The digests of 2026-09-22 (786-3,401 characters of prose
each) are what the form exists against; the 0.7.x one-line digest is what it must not break.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import role_digest as RD  # noqa: E402

GOOD = "\n".join([
    "qa-automator S5 window 2 (TC-001, TC-002) · concerns",
    "TC-001#1 · green · fresh witness on current bytes",
    "TC-002#1 · red · asserts the Then; the endpoint returns non-null",
    "work/automation-manifest.json",
])


def the_form_parses() -> None:
    parsed = RD.parse(GOOD)
    check_eq("the header names the role", parsed["header"]["role"], "qa-automator")
    check_eq("and the stage", parsed["header"]["stage"], "S5")
    check_eq("and the window it worked", parsed["header"]["scope"], "window 2 (TC-001, TC-002)")
    check_eq("and the verdict the orchestrator branches on", parsed["header"]["verdict"], "concerns")
    check_eq("one row per instance", [r["id"] for r in parsed["rows"]], ["TC-001#1", "TC-002#1"])
    check_eq("the state of each", [r["state"] for r in parsed["rows"]], ["green", "red"])
    check_eq("the artifact path is the last line", parsed["path"], "work/automation-manifest.json")
    check_eq("and the form itself raises nothing", parsed["errors"], [])
    check_eq("the scope roll-call is answered", RD.check(GOOD, ["TC-001", "TC-002"]), [])


def prose_is_refused() -> None:
    """The five real final messages of 2026-09-22 — every one of them is refused."""
    real = ("All test-code-level findings are resolved. Final state after this resume:\n\n"
            "**Tooling blocker lifted and confirmed** via the person's waiver "
            "(`qa-factory/config.json` `execution.verify_node_ids: false`). Reopened the "
            "dispatch as `S5-qa-automator-12`.\n\nqa-automator S5 done · "
            "work/automation-manifest.json · 11 instances green")
    errors = RD.check(real, ["TC-009"])
    check("a page of prose with the digest buried in it is refused", bool(errors))
    check_in("and the refusal says which line was not in the form", "not in the form", errors)
    check_in("the refusal quotes the form exactly once", "one row per",
             RD.refusal("qa-automator", errors))
    check_eq("and quotes it once, not once per finding",
             RD.refusal("qa-automator", errors).count("<task-relative path>"), 1)
    check_in("the item named is the role's own", "test instance of the window",
             RD.refusal("qa-automator", errors))


def the_rules_of_a_row() -> None:
    long_reason = "x" * 81
    errors = RD.check("\n".join([
        "qa-runner S6 TC-005 · ok",
        f"TC-005 · passed · {long_reason}",
        "work/run-report.json"]))
    check_in("a reason over 80 characters is a finding", "81 characters", errors)

    errors = RD.check("\n".join([
        "qa-automator S5 window 1 · ok",
        "TC-001#1 · green · ok",
        "work/automation-manifest.json"]), ["TC-001", "TC-014"])
    check_eq("a scoped id with no line is named, and only it", len(errors), 1)
    check_in("by its own id", "TC-014", errors)

    check_eq("an instance id answers for the case it belongs to",
             RD.check("\n".join(["qa-automator S5 w · ok", "TC-012::valid · green · ok",
                                 "work/automation-manifest.json"]), ["TC-012"]), [])
    check("but a neighbouring case is not covered by a prefix", not RD.covers("TC-01", "TC-012"))

    errors = RD.check("\n".join(["qa-automator S5 w · ok", "TC-001#1 · green · ok"]))
    check_in("a digest with no artifact path is a finding", "no artifact path", errors)
    errors = RD.check("\n".join(["qa-automator S5 w · ok", "TC-001#1 · green · ok",
                                 "D:/ws2/work/automation-manifest.json"]))
    check_in("and an absolute one is refused the way A20 refuses it", "absolute", errors)

    errors = RD.check("\n".join(["I looked at four files and found nothing.",
                                 "work/context-manifest.json"]))
    check_in("a message with no header at all is refused", "not a digest header", errors)
    check_in("a header with no verdict too", "states no verdict",
             RD.check("qa-scout S1 twelve sources · work/context-manifest.json"))


def decoration_is_forgiven() -> None:
    """The rule is about structure. A role that bolds its digest or fences it is not refused
    for typography — that would be a block nobody learns anything from."""
    dressed = "\n".join(["```", "**qa-case-critic S4 TC-001 · ok**", "",
                         "- `TC-001` · approved · the seeded defect was caught",
                         "work/test-cases/critic-findings.md", "```"])
    check_eq("bold, a bullet, a fence and a blank line change nothing",
             RD.check(dressed, ["TC-001"]), [])


def the_form_followed_by_prose_is_the_form() -> None:
    """TP1-15045, cmp2 stop 6 (F-cmp2-9): the S2 role's final message held the whole form
    and then a paragraph of concerns and a file list AFTER the path line. The gate refused it
    three times, and a person had to pass it by word. The form is a header, one row per item
    and a path; what follows the path is not part of it - it is kept, not refused."""
    after = ["", "Concerns: AC3 has no observable state on this stand, so TC-002 stays red.",
             "Files I touched:", "- work/automation-manifest.json", "- tests/api/test_orders.py",
             "D:/ws2/work/scratch.json"]
    message = GOOD + "\n" + "\n".join(after)
    parsed = RD.parse(message)
    check_eq("the form followed by prose raises nothing", parsed["errors"], [])
    check_eq("the path is the form's own last line, not a path from the prose",
             parsed["path"], "work/automation-manifest.json")
    check_eq("the rows are the form's rows", [r["id"] for r in parsed["rows"]], ["TC-001#1", "TC-002#1"])
    check_eq("the prose is kept as a note on the digest, line by line",
             parsed["notes"], ["Concerns: AC3 has no observable state on this stand, so TC-002 stays red.",
                               "Files I touched:", "work/automation-manifest.json",
                               "tests/api/test_orders.py", "D:/ws2/work/scratch.json"])
    check_eq("and the gate's own check passes it, scope roll-call included",
             RD.check(message, ["TC-001", "TC-002"]), [])
    check_eq("a form with nothing after it carries no note", RD.parse(GOOD)["notes"], [])

    # What is still refused, word for word as before.
    check_in("prose BEFORE the form is still not a digest header",
             "not a digest header", RD.check("Here is my summary.\n" + message))
    check_in("a row missing from the scope is still named, prose after the path or not",
             "TC-014", RD.check(message, ["TC-001", "TC-014"]))
    between = "\n".join(["qa-automator S5 window 2 · concerns", "TC-001#1 · green · ok",
                         "I ran out of time before the second one.", "TC-002#1 · red · ok",
                         "work/automation-manifest.json", "Some more prose."])
    check_in("prose BETWEEN the rows and the path is still a line not in the form",
             "not in the form", RD.check(between))
    check_in("no path at all is still a finding, whatever follows", "no artifact path",
             RD.check("qa-automator S5 w · ok\nTC-001#1 · green · ok\nI wrote nothing down."))
    check_in("an empty final message is still the same finding", "is empty", RD.check("  \n\n"))
    check_eq("and a row-shaped line after the path is a note, never a second row",
             [r["id"] for r in RD.parse(GOOD + "\nTC-009#1 · green · afterthought")["rows"]],
             ["TC-001#1", "TC-002#1"])
    check_in("so the item it names still has no line of its own",
             "TC-009", RD.check(GOOD + "\nTC-009#1 · green · afterthought", ["TC-009"]))
    check_in("a header that failed keeps the old reading of what follows it",
             "not in the form",
             RD.check("I looked at four files.\nwork/context-manifest.json\nmore prose here"))


def the_old_digest_still_passes() -> None:
    """A story in flight must not be refused because its role file is still the 0.7.x one."""
    for legacy in ("qa-scout S1 done · work/context-manifest.json · 12 sources",
                   "qa-scout S1 halt · work/source-inventory.json · no diff — give --mr",
                   "qa-requirements-tester S2 impossible · work/x.json · the ticket is gone"):
        check_eq(f"the 0.7.x digest parses clean: {legacy[:24]}", RD.check(legacy), [])
    check("a halt is heard through the old form", RD.is_halting(
        "qa-scout S1 halt · work/source-inventory.json · no diff"))
    check("and through the new one", RD.is_halting("qa-scout S1 twelve sources · halt"))
    check("a halt buried under prose is still heard — the gate owes it the exemption",
          RD.is_halting("I tried three routes.\n\nqa-scout S1 sources · halt"))
    check("prose that merely contains the word is not a halt",
          not RD.is_halting("I will halt if the tracker is unreachable"))
    check("and a finished digest is not one either",
          not RD.is_halting("qa-scout S1 twelve sources · ok"))


def a_halt_is_not_asked_for_the_scope_it_never_reached() -> None:
    halting = "\n".join(["qa-automator S5 window 2 · halt",
                         "TC-001#1 · handed · the stand is down; nothing ran",
                         "work/automation-manifest.json"])
    check_eq("a halt answers for what it reached and is not blocked for the rest",
             RD.check(halting, ["TC-001", "TC-002", "TC-014"]), [])


def a_state_is_a_word_the_artifacts_already_use() -> None:
    """The row's state is read from contract.py, not invented for the digest: the strategist
    says the row's disposition, the analyst its triage verdict, the scribe its ledger state."""
    for digest, scope in (("qa-test-strategist S3 plan · ok\nTS-4 · automate · API, cheap\ntest-plan.md", ["TS-4"]),
                          ("qa-failure-analyst S7 4 failures · ok\nt3 · APP_BUG · null where the AC says a value\nwork/triage.json", ["t3"]),
                          ("qa-doc-scribe S8 ledger · concerns\nTS-9 · failed:APP_BUG · one bug drafted\ntest-report.md", ["TS-9"]),
                          ("qa-code-critic S5 window 1 · concerns\nTC-002#1 · approved_with_fixes · two markers\nwork/automation-manifest.json", ["TC-002"])):
        check_eq(f"the state {digest.splitlines()[1].split(' · ')[1]} is in the form",
                 RD.check(digest, scope), [])
    refused = RD.check("qa-runner S6 TC-005 · ok\nTC-005 · mostly-fine · it ran\nwork/run-report.json")
    check_in("a word from nowhere is not", "is not a state of the form", refused)
    check_in("and the refusal names the closed list", "green", refused)


def every_role_has_an_item() -> None:
    stages = json.loads((PLUGIN_ROOT / "references" / "stages.json").read_text(encoding="utf-8"))
    roles = [role for stage in stages["stages"] for role in (stage.get("roles") or [])]
    missing = [role for role in roles if role not in RD.ROLE_ITEM]
    check_eq("every role in stages.json knows what one row of its digest is", missing, [])
    stale = [role for role in RD.ROLE_ITEM if role not in roles]
    check_eq("and no retired role is left in the table", stale, [])


def the_gate_refuses_a_shapeless_handoff() -> None:
    """The exit gate's own wiring: the scope comes from the controller, the refusal is one
    error carrying the form, and a person's word passes it like every other block."""
    import exit_gate as gate
    root = temp_project("qa-digest-gate-")
    try:
        use_project(root)
        task = root / "qa-factory" / "artifacts" / "QA-D1"
        (task / "state").mkdir(parents=True)
        (task / "work").mkdir(parents=True)
        (task / "state" / "controller.json").write_text(json.dumps({"dispatches": {
            "S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator",
                                  "status": "running", "scope": ["TC-001", "TC-014"]},
            "S5-qa-automator-0": {"id": "S5-qa-automator-0", "stage": "S5", "role": "qa-automator",
                                  "status": "completed", "scope": ["TC-777"]}}}), encoding="utf-8")
        saved = gate.artifact_root
        gate.artifact_root = lambda: root / "qa-factory" / "artifacts"
        try:
            check_eq("the gate reads the running dispatch's scope, not the finished one's",
                     gate.dispatch_scope("qa-automator", "QA-D1"), ["TC-001", "TC-014"])
            errors = gate.digest_errors("qa-automator", "QA-D1", "\n".join([
                "qa-automator S5 window 1 · ok",
                "TC-001#1 · green · ok",
                "work/automation-manifest.json"]))
            check_eq("a digest missing a scoped case is exactly one error", len(errors), 1)
            check_in("and that error carries the form", "<state>", errors[0])
            check_eq("a digest in the form is no error at all",
                     gate.digest_errors("qa-automator", "QA-D1", "\n".join([
                         "qa-automator S5 window 1 · ok",
                         "TC-001#1 · green · ok",
                         "TC-014#1 · red · asserts the Then; the endpoint returns non-null",
                         "work/automation-manifest.json"])), [])
            check_eq("a host that sends no transcript is not a finding",
                     gate.digest_errors("qa-automator", "QA-D1", ""), [])
            check_eq("and a foreign agent owes this gate no form at all",
                     gate.digest_errors("some-other-agent", "QA-D1", "pages of prose\nand more"), [])

            from waiver import split_overridden
            pipeline = {"stage_overrides": [{"stage": "S5", "match": "digest",
                                             "decision": "one report is enough for me"}]}
            blocking, passed = split_overridden(errors, pipeline, "S5")
            check_eq("a person's word passes the refusal like any other block", blocking, [])
            check_eq("and what it passed is recorded", len(passed), 1)
        finally:
            gate.artifact_root = saved
    finally:
        cleanup(root)


def _pairs(text: str) -> list:
    return [(r["id"], r["state"]) for r in RD.parse(text)["rows"]]


def canonical_mends_only_the_closed_list() -> None:
    """SC1-14 B3: `canonical` mends (i) prose before the header, (ii) a missing path from the witness, (iii) a reason over 80,
    (iv) an absolute path under the task root - and nothing else; verdict, ids and states stay byte for byte."""
    check_eq("FIXABLE is the closed list", RD.FIXABLE,
             ("prose_before_header", "path_from_witness", "reason_cut", "path_relative"))
    prose ="Done. Here is what I did, in short.\n\nAll good.\n"
    mended, repairs = RD.canonical(prose + GOOD, ["TC-001", "TC-002"], None, None)
    check_eq("(i) prose before the single header is dropped", mended, GOOD)
    check_eq("and the repair is named", repairs, ["prose_before_header"])
    check_eq("and the mended digest passes", RD.check(mended, ["TC-001", "TC-002"]), [])

    no_path = "\n".join(GOOD.splitlines()[:-1])
    mended, repairs = RD.canonical(no_path, [], "work/automation-manifest.json", None)
    check_eq("(ii) a missing path is the witness path", mended, GOOD)
    check_eq("(ii) is named", repairs, ["path_from_witness"])
    check_eq("(ii) with no witness there is nothing to mend", RD.canonical(no_path, [], None, None), (None, []))

    ok80, over81 = "y" * 80, "y" * 81
    digest80 = f"qa-runner S6 TC-005 · ok\nTC-005 · passed · {ok80}\nwork/run-report.json"
    check_eq("(iii) a reason of exactly 80 is untouched (nothing to mend)", RD.canonical(digest80), (None, []))
    mended, repairs = RD.canonical(digest80.replace(ok80, over81))
    check_eq("(iii) 81 is cut to 79 + the ellipsis", mended.splitlines()[1], "TC-005 · passed · " + "y" * 79 + "…")
    check_eq("the cut reason is 80 characters", len(mended.splitlines()[1].split(" · ")[2]), 80)
    check_eq("(iii) is named, the digest passes", (repairs, RD.check(mended)), (["reason_cut"], []))

    root = Path(temp_project("qa-digest-canon-")).resolve()
    try:
        inside = str(root / "work" / "automation-manifest.json")
        under = "\n".join(GOOD.splitlines()[:-1] + [inside])
        check_in("the absolute path alone is a finding", "absolute", RD.check(under, ["TC-001", "TC-002"]))
        mended, repairs = RD.canonical(under, [], None, root)
        check_eq("(iv) an absolute path under the root is task-relative", mended, GOOD)
        check_eq("(iv) is named", repairs, ["path_relative"])
        for label, path in (("another drive or tree", "C:\\other\\x.md"),
                            ("a `..` that leaves the root", str(root / "work" / ".." / ".." / "x.md")),
                            ("the root itself", str(root))):
            got, _ = RD.canonical("\n".join(GOOD.splitlines()[:-1] + [path]), [], None, root)
            check(f"outside root refused: {label} is not mended", got is None or RD.check(got, []) != [])
        check_eq("outside root refused: no root given means no repair",
                 RD.canonical(under, [], None, None), (None, []))
    finally:
        cleanup(root)

    # INVARIANTS: states, ids and the verdict byte for byte; no row added or deleted
    many = "\n".join(["qa-code-critic S5 window 1 (TC-001) · concerns",
                      "TC-001#1 · approved_with_fixes · two markers", "TC-009 · red · outside the scope",
                      "TC-002#1 · failed:APP_BUG · " + "z" * 90, "work/automation-manifest.json"])
    mended, _ = RD.canonical("noise\n" + many, ["TC-001"], None, None)
    check_eq("states byte for byte: the pairs of the mended digest are the input's", _pairs(mended), _pairs(many))
    check_eq("states byte for byte: a row for an id outside the scope is not deleted",
             "TC-009" in [r["id"] for r in RD.parse(mended)["rows"]], True)
    check_eq("the verdict and the header line are the input's",
             RD.parse(mended)["header"]["raw"], RD.parse(many)["header"]["raw"])
    check_eq("canonical of a canonical digest is nothing", RD.canonical(mended, ["TC-001"]), (None, []))
    check_eq("a digest in the form needs nothing", RD.canonical(GOOD), (None, []))


def canonical_leaves_the_unmendable_refused() -> None:
    """Inputs that must stay refusals (the advisor becomes the gate: the direction of error is "not mended")."""
    halt = "qa-automator S5 window 1 · halt\nthe tooling is down: nothing was written"
    check_eq("a halt under prose keeps its refusal (canonical does not touch a halt)",
             RD.canonical("I tried hard.\n" + halt), (None, []))
    check_eq("a bare halt in the form is not mended either", RD.canonical(halt), (None, []))
    no_verdict = "Sorry about that.\nqa-automator S5 window 1\nTC-001#1 · green · ok\nwork/automation-manifest.json"
    check_eq("a header without a verdict is not mended", RD.canonical(no_verdict), (None, []))
    two = GOOD + "\n" + GOOD.splitlines()[0]
    check_eq("two headers are not mended", RD.canonical("prose\n" + two), (None, []))
    rowfirst = "TC-001#1 · green · ok\n" + GOOD
    check_eq("a row before the header is not dropped as prose", RD.canonical(rowfirst), (None, []))
    badstate = "talk\nqa-automator S5 window 1 · ok\nTC-001#1 · rejected-ish · maybe\nwork/automation-manifest.json"
    mended, _ = RD.canonical(badstate)
    check("`<id> · rejected-ish · ...` stays a refusal after the mending",
          mended is None or RD.check(mended) != [])
    check_eq("an empty text has nothing to mend", RD.canonical(""), (None, []))


def main() -> None:
    canonical_mends_only_the_closed_list()
    canonical_leaves_the_unmendable_refused()
    the_form_parses()
    prose_is_refused()
    the_rules_of_a_row()
    decoration_is_forgiven()
    the_form_followed_by_prose_is_the_form()
    the_old_digest_still_passes()
    a_halt_is_not_asked_for_the_scope_it_never_reached()
    a_state_is_a_word_the_artifacts_already_use()
    every_role_has_an_item()
    the_gate_refuses_a_shapeless_handoff()
    finish("test_role_digest")


if __name__ == "__main__":
    main()
