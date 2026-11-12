"""gate_preflight._rehearse_reporter: the report format rehearsed is the one the run reads (FB-22, CX1-12).

`profile_contract` makes `commands.one_test.reporter.format` the command's contract and `execution_request` runs a
`--request` by it, so the rehearsal proves that format first. The legacy `profile.reporter.kind` is read only when the
command names no format (or names a value outside `profile_contract.REPORT_FORMATS`), exactly as before; an explicit
`none` of the COMMAND stays `none` and is never guessed from the command's shape, while an OLD `kind: none` on a pytest
command stays `pytest` (the rule of `main`, pinned here). Only the rehearsal changed: the stage that runs the tests
still reads the old setting, and the rehearsal says so when the two differ."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import gate_preflight  # noqa: E402

DOTNET = ["dotnet", "test", "--logger", "trx;LogFileName={report_path}"]
PYTEST = ["python", "-m", "pytest", "{test}"]


def rehearse(reporter, legacy=None, argv=None, outcome=None):
    """`(format _probe_reporter was asked to read, report suffix, the rehearsal)` for one profile's one-test command."""
    root = temp_dir("qa-reporter-format-")
    try:
        rehearsal = gate_preflight.Rehearsal(root, "A")
        spec = {"argv": argv or DOTNET}
        if reporter is not ...:
            spec["reporter"] = reporter
        profile = {"commands": {"one_test": spec}}
        if legacy is not None:
            profile["reporter"] = {"kind": legacy}
        with patch.object(rehearsal, "_probe_test_of", return_value="ExistingTest"), \
                patch.object(rehearsal, "_probe_reporter", return_value=outcome or {"tests": 1}) as probe, \
                patch.object(rehearsal, "_record_rehearsal", return_value=None), \
                patch.object(rehearsal, "_keep_unread", return_value=""), \
                patch.object(rehearsal, "_adaptation_state", return_value={"state": "none", "rows": [], "note": ""}), \
                patch.dict(gate_preflight._REPORTER_PROBES, {}, clear=True):
            rehearsal._rehearse_reporter("reporter", "backend", {"cases": []}, profile, root, root, 10, {})
            return probe.call_args.args[-1], probe.call_args.args[-2].suffix, rehearsal
    finally:
        cleanup(root)


def the_command_format_wins() -> None:
    check_eq("R1: a v2 `trx` contract is rehearsed with the trx parser and extension",
             rehearse({"format": "trx"})[:2], ("trx", ".trx"))
    check_eq("the command's own format wins over the legacy profile kind",
             rehearse({"format": "junit-xml"}, "trx")[0], "junit-xml")
    check_eq("an explicit `none` of the command stays `none`, never guessed from the legacy kind",
             rehearse({"format": "none"}, "trx")[0], "none")
    check_eq("an explicit `none` on a pytest command is `none` too, not pytest",
             rehearse({"format": "none"}, argv=PYTEST)[:2], ("none", ".xml"))
    check_eq("an explicit `pytest` on a command that does not look like pytest is `pytest`",
             rehearse({"format": "pytest"})[0], "pytest")


def a_command_that_names_nothing_leaves_the_rule_as_it_was() -> None:
    check_eq("R2: a command naming no format falls back to the legacy kind", rehearse({}, "trx")[0], "trx")
    check_eq("no reporter key at all: the same", rehearse(..., "trx")[0], "trx")
    check_eq("a reporter that is not a dict: the same", rehearse("trx", "trx")[0], "trx")
    check_eq("and with neither, the command's shape decides (not pytest-shaped: none)", rehearse({})[0], "none")
    check_eq("(pytest-shaped: pytest)", rehearse({}, argv=PYTEST)[0], "pytest")
    check_eq("legacy `kind: mocha` is not a format the factory reads: the shape decides", rehearse({}, "mocha")[0], "none")
    for name, value in (("null", None), ("empty", ""), ("upper case", "TRX"), ("unknown", "mocha"), ("a number", 7)):
        check_eq(f"R3: a command format that is {name} falls back to the legacy kind (not to the shape)",
                 rehearse({"format": value}, "trx")[0], "trx")
    check_eq("R3: and to the shape when there is no legacy kind either", rehearse({"format": "mocha"}, argv=PYTEST)[0],
             "pytest")
    check_eq("M-6 pin: the OLD `kind: none` on a pytest command stays pytest (main's rule, not the command's `none`)",
             rehearse({}, "none", argv=PYTEST)[:2], ("pytest", ".xml"))
    check_eq("(and on a command that does not look like pytest it is `none`)", rehearse({}, "none")[0], "none")


def the_unreadable_explicit_none_is_a_finding_without_a_heal() -> None:
    unread = {"why": "no report written", "fit": "junit-xml", "tried": []}
    *_, rehearsal = rehearse({"format": "none"}, argv=PYTEST, outcome=unread)
    found = [f for f in rehearsal.findings if f["check"] == "reporter"]
    check("R4: the explicit `none` leaves a finding for the conductor", len(found) == 1, str(rehearsal.findings))
    check_eq("it names the declared kind", found[0].get("declared_kind") if found else None, "none")
    check("and carries NO helper command: `none` is not an empty kind, and the heal would write a key this step "
          "does not read", found and "argv" not in found[0], str(found))
    *_, control = rehearse({}, argv=PYTEST, outcome=unread)
    found = [f for f in control.findings if f["check"] == "reporter"]
    check("control, the same shape without a declared format: the finding does carry the helper's command",
          len(found) == 1 and "argv" in found[0], str(control.findings))


def a_different_format_is_a_different_proof() -> None:
    root = temp_dir("qa-reporter-format-keys-")
    try:
        rehearsal = gate_preflight.Rehearsal(root, "A")
        with patch.object(rehearsal, "_probe_test_of", return_value="ExistingTest"), \
                patch.object(rehearsal, "_probe_reporter", return_value={"tests": 1}) as probe, \
                patch.object(rehearsal, "_record_rehearsal", return_value=None), \
                patch.dict(gate_preflight._REPORTER_PROBES, {}, clear=True):
            for fmt in ("trx", "junit-xml", "trx"):
                profile = {"commands": {"one_test": {"argv": DOTNET, "reporter": {"format": fmt}}}}
                rehearsal._rehearse_reporter("reporter", "backend", {"cases": []}, profile, root, root, 10, {})
            keys = sorted(key[-1] for key in gate_preflight._REPORTER_PROBES)
            asked = [call.args[-1] for call in probe.call_args_list]
        check_eq("R6: two different formats of one command are two keys of the cache", keys, ["junit-xml", "trx"])
        check_eq("and the third call (trx again) reuses the first proof instead of running", asked, ["trx", "junit-xml"])
    finally:
        cleanup(root)


def the_older_setting_is_named_when_it_disagrees() -> None:
    def said(*args, **kwargs):
        return [line["message"] for line in rehearse(*args, **kwargs)[2].info if "older report setting" in line["message"]]

    check("R5: the command says trx, the older setting says junit-xml: the rehearsal says both",
          len(said({"format": "trx"}, "junit-xml")) == 1 and "trx" in said({"format": "trx"}, "junit-xml")[0]
          and "junit-xml" in said({"format": "trx"}, "junit-xml")[0], str(said({"format": "trx"}, "junit-xml")))
    check("M-6: the OLD `kind: none` on a pytest command: the proof is pytest, the run reads `none` - said",
          len(said({}, "none", argv=PYTEST)) == 1, str(said({}, "none", argv=PYTEST)))
    check_eq("the two agree: nothing to say", said({"format": "trx"}, "trx"), [])
    check_eq("no older setting: nothing to say", said({"format": "trx"}), [])
    check_eq("an older setting the factory does not read is the old rule's business, not a disagreement",
             said({}, "mocha"), [])


def the_format_rule_alone() -> None:
    rule = gate_preflight.Rehearsal._report_format
    check_eq("spec omitted: exactly main's rule (legacy kind first)", rule({"reporter": {"kind": "trx"}}, PYTEST),
             (True, "trx", "trx"))
    check_eq("spec omitted, nothing declared: the shape", rule({}, PYTEST), (True, "", "pytest"))
    check_eq("spec naming a format: it is both the declared kind and the format",
             rule({"reporter": {"kind": "trx"}}, DOTNET, {"reporter": {"format": "junit-xml"}}),
             (False, "junit-xml", "junit-xml"))
    check_eq("spec with a value outside the list: main's rule", rule({}, DOTNET, {"reporter": {"format": "TRX"}}),
             (False, "", "none"))


def main() -> None:
    the_command_format_wins()
    a_command_that_names_nothing_leaves_the_rule_as_it_was()
    the_unreadable_explicit_none_is_a_finding_without_a_heal()
    a_different_format_is_a_different_proof()
    the_older_setting_is_named_when_it_disagrees()
    the_format_rule_alone()
    finish("test_reporter_contract_format")


if __name__ == "__main__":
    main()
