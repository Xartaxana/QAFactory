#!/usr/bin/env python3
"""ONE changed test command as a sealed proposal, approved by a person, applied by apply_plan (B-220 part 1, t-385).

`apply_plan` can write any sealed, approved `proposed_config`; what did not exist was a MAKER of a one-key proposal
(`migration_plan(answers=)` ignores every pointer but the required ones, both pointer setters walk objects only and `profiles` is
a list, and `migration_plan` would also drag in every template migration due). `config_contract.command_proposal` is that maker:
pure, no new writer. What is proved here (the file that judges the maker, the seal and the approval):

  KO6   exactly one `changes` row; the config differs from the current one at the target only; refused when the config is absent,
        unreadable or the profile is not there; a hand-edited sealed file is refused by its hash
  F4    the sentence the person read is in `listing` (the hash covers it) and is rendered from the sealed file; a file edited after
        it was made is "stale"; the sentence must name the command the proposal writes
  F5    a cure may set `reporter.kind` with the target - one `changes` row, two pointers; a recorded kind is not overwritten
  F6    the onboarding sentence itself obeys human-questions.md - a `manage.py` command and a flag included, on its action line
  F7    the maker leaves conflicts / reasked / added empty; what `apply_plan` still refuses on is `validate`
  F8    a second yes on an applied proposal is "already done", never a stale refusal; an old proposal is stale
  F9    a `cure` / `command` proposal is never approved by a headless ref (record_approval) nor applied headless (onboard_apply)
  K8    no new `config_contract.py` operation: the option set is the old one, and the guard's sanction list is untouched
"""
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import config_contract as C  # noqa: E402
import human_text  # noqa: E402
import onboarding_probe as P  # noqa: E402

ARGV = ["npx", "vitest", "run"]
CURED = ARGV + ["--reporter=junit", "--outputFile={report_path}"]
SENTENCE = ("One existing test ran.\n\nI propose to run the web tests as: `npx vitest run --reporter=junit "
            "--outputFile={report_path}`. Do it? yes / no\n\n---\nAnswer: yes or no.\n")


def project(profiles=None, **top) -> Path:
    root = temp_project("qa-cmd-proposal-")
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["profiles"] = profiles if profiles is not None else [
        {"profile_id": "web", "commands": {"one_test": {"argv": ARGV, "cwd": "."}}},
        {"profile_id": "api", "commands": {"one_test": {"argv": ["pytest"], "cwd": "."}}}]
    cfg["test_command_templates"] = {"one_test": "npx vitest run <test-file>", "suite": "npx vitest run", "quiet": ""}
    cfg.update(top)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    use_project(root)
    return root


def config_of(root: Path) -> dict:
    return json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))


def differences(a, b, path="") -> list:
    """The JSON pointers at which two documents differ (a list is compared whole: it is one value)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            out.extend(differences(a.get(key), b.get(key), f"{path}/{key}") if key in a and key in b else [f"{path}/{key}"])
        return out
    return [] if a == b else [path or "/"]


def refusal_of(func) -> str:
    try:
        func()
    except ValueError as exc:
        return str(exc)
    return ""


def make(root: Path, kind: str = "cure", reporter_kind="junit-xml", question: str = SENTENCE, value=None) -> dict:
    return C.command_proposal(root, {"profile_id": "web"}, value or CURED, reporter_kind=reporter_kind, kind=kind, question=question)


def ko6_the_maker_changes_one_key_and_seals_it() -> None:
    root = project()
    try:
        current = config_of(root)
        proposal = make(root)
        check_eq("KO6: the maker is pure: the config on disk did not move", config_of(root), current)
        check_eq("KO6: exactly one `changes` row", len(proposal["changes"]), 1)
        row = proposal["changes"][0]
        check_eq("KO6: the row names the profile's argv by its place in the list, with from and to",
                 (row["path"], row["from"], row["to"], row["reason"]), ("/profiles/0/commands/one_test/argv", ARGV, CURED, "probe cure"))
        check_eq("F5: and the report kind it sets, as a second pointer of the SAME row",
                 row["also"], [{"path": "/profiles/0/reporter/kind", "from": None, "to": "junit-xml"}])
        check_eq("KO6: the proposed config differs from the current one at the target (and its kind) only",
                 differences(current, proposal["proposed_config"]), ["/profiles"])
        check_eq("KO6: inside the list, only the one profile moved, and only its argv and its kind",
                 ([differences(a, b) for a, b in zip(current["profiles"], proposal["proposed_config"]["profiles"])]),
                 [["/commands/one_test/argv", "/reporter"], []])
        check_eq("KO6: the argv under it is the whole new command", proposal["proposed_config"]["profiles"][0]["commands"]["one_test"]["argv"], CURED)
        check_eq("F7: conflicts, reasked, added and every other list the maker leaves empty",
                 [proposal[k] for k in ("conflicts", "reasked", "added", "removed", "renamed", "kept", "reordered", "answers_legacy")],
                 [[], [], [], [], [], [], [], {}])
        check_eq("KO6: it is sealed: the hash is its own", proposal["proposal_hash"], C.proposal_hash(proposal))
        check_eq("KO6: and bound to the config as it is", proposal["input_hash"], C._json_hash(current))
        # a template key is a command too: the same maker
        template = C.command_proposal(root, {"template_key": "one_test"}, "npx vitest run --reporter=junit <test-file>",
                                      question="I propose to run it as: `npx vitest run --reporter=junit <test-file>`. Do it? yes / no\n\n---\nAnswer: yes\n")
        check_eq("KO6: a template target changes that one template and nothing else",
                 differences(current, template["proposed_config"]), ["/test_command_templates/one_test"])
        check_eq("KO6: its row", (template["changes"][0]["path"], template["changes"][0]["from"]),
                 ("/test_command_templates/one_test", "npx vitest run <test-file>"))
        # refusals, each with its reason in words
        absent = project()
        (absent / "qa-factory" / "config.json").unlink()
        check_in("KO6: the config is absent: refused, naming what comes first", "no qa-factory/config.json yet", refusal_of(lambda: make(absent)))
        (absent / "qa-factory" / "config.json").write_text("{nope", encoding="utf-8")
        check_in("KO6: the config is unreadable: refused with its door", "not valid JSON", refusal_of(lambda: make(absent)))
        cleanup(absent)
        missing = refusal_of(lambda: C.command_proposal(root, {"profile_id": "ghost"}, CURED, question=SENTENCE))
        check_in("KO6: the profile is not there: named, with the ones that are", "`ghost` is not in qa-factory/config.json (it has: web, api)", missing)
        check_in("KO6: a command is a list of words, not a line", "non-empty list of words", refusal_of(lambda: make(root, value="npx vitest")))
        check_in("KO6: an empty command is no command", "non-empty list of words",
                 refusal_of(lambda: C.command_proposal(root, {"profile_id": "web"}, [], question=SENTENCE)))
        check_in("KO6: the target is named", "names its target", refusal_of(lambda: C.command_proposal(root, {}, CURED, question=SENTENCE)))
        check_in("KO6: the kind of proposal is one of two", "is one of: cure, command", refusal_of(lambda: make(root, kind="whim")))
        check_in("KO6: the report kind is junit-xml or trx", "junit-xml, trx", refusal_of(lambda: make(root, reporter_kind="xunit")))
        check_in("KO6: a template has no report kind", "no report kind to set", refusal_of(
            lambda: C.command_proposal(root, {"template_key": "suite"}, "x y", reporter_kind="trx", question="`x y`")))
        # a hand-edited sealed file is refused by its hash
        forged = copy.deepcopy(proposal)
        forged["proposed_config"]["profiles"][0]["commands"]["one_test"]["argv"] = ["sh", "-c", "evil"]
        check_in("KO6: a hand-edited sealed file is refused when the person's yes is recorded", "proposal hash is invalid",
                 refusal_of(lambda: C.record_approval(root, forged, "onboarding-cure:web:x", "t:1")))
        C.record_approval(root, proposal, C.command_approval_ref(proposal), "transcript:yes")
        check_in("KO6: and when it is applied, even after an honest approval of the original", "proposal hash is invalid",
                 refusal_of(lambda: C.apply_plan(root, forged, C.command_approval_ref(proposal))))
        check_eq("KO6: nothing was written by the refused apply", config_of(root), current)
    finally:
        cleanup(root)


def f4_the_yes_is_bound_to_the_sentence_the_person_read() -> None:
    root = project()
    try:
        proposal = make(root)
        check_eq("F4: the sentence is in `listing`, which the hash covers", proposal["listing"]["question"], SENTENCE)
        check_eq("F4: and the question is rendered from the sealed file", C.command_question(proposal), SENTENCE)
        before = C.proposal_hash(proposal)
        edited = copy.deepcopy(proposal)
        edited["listing"]["question"] = SENTENCE.replace("Do it?", "Do it, please?")
        check("F4: a changed sentence changes the hash", C.proposal_hash(edited) != before)
        check_in("F4: a sealed file edited after display is `stale`, not shown with a yes that binds to other bytes", "proposal is stale",
                 refusal_of(lambda: C.command_question(edited)))
        check_in("F4: and a yes is not recordable on it", "proposal hash is invalid",
                 refusal_of(lambda: C.record_approval(root, edited, "onboarding-cure:web:z", "t:1")))
        # a forger who re-seals still cannot show a sentence that names another command than the proposal writes
        liar = copy.deepcopy(proposal)
        liar["listing"]["question"] = SENTENCE.replace("npx vitest run --reporter=junit --outputFile={report_path}", "npx vitest run")
        liar["listing"]["command"] = "npx vitest run"
        liar["proposal_hash"] = C.proposal_hash(liar)
        check_in("F4/E30: a re-sealed sentence that names another command is refused too", "does not name the command this proposal writes",
                 refusal_of(lambda: C.command_question(liar)))
        check_in("F4: the maker refuses a sentence that does not carry the command it would write", "does not carry the command",
                 refusal_of(lambda: make(root, question="I propose something. Do it? yes / no\n\n---\nAnswer: yes\n")))
        check_in("F4: and a proposal with no sentence at all", "give `question`", refusal_of(lambda: make(root, question="  ")))
        check_in("F4: a proposal that is not a command proposal has no sentence to ask", "not a proposal to change a test command",
                 refusal_of(lambda: C.command_question(C.migration_plan(config_of(root)))))
        check_eq("F4: the approval ref carries the kind, the profile and the hash", C.command_approval_ref(proposal),
                 f"onboarding-cure:web:{proposal['proposal_hash'][:12]}")
        check_eq("F4: a person's own command is `onboarding-command:`", C.command_approval_ref(make(root, kind="command")).split(":")[0],
                 "onboarding-command")
        check_eq("display: a word with a space or a shell character is quoted, a placeholder is not",
                 C.display_command(["dotnet", "test", "--logger", "trx;LogFileName={report_path}", "--filter", "<test-id>", "a b"]),
                 'dotnet test --logger "trx;LogFileName={report_path}" --filter <test-id> "a b"')
        check_eq("display: a word that holds a double quote is single-quoted", C.display_command(['say "x"']), "'say \"x\"'")
    finally:
        cleanup(root)


def f5_one_row_two_pointers_and_a_recorded_kind_is_not_overwritten() -> None:
    root = project([{"profile_id": "web", "reporter": {"kind": "trx"}, "commands": {"one_test": {"argv": ARGV, "cwd": "."}}}])
    try:
        check_eq("F5: the same kind is no conflict, and the row says so", make(root, reporter_kind="trx")["changes"][0]["also"][0]["from"], "trx")
        check_in("F5: another kind is refused in words, naming both", "already says its report is `trx`, and this change would make it `junit-xml`",
                 refusal_of(lambda: make(root, reporter_kind="junit-xml")))
        no_kind = make(root, reporter_kind=None)
        check_eq("F5: a change with no report kind sets no pointer but the command", ("also" in no_kind["changes"][0], no_kind["listing"]["pointers"]),
                 (False, ["/profiles/0/commands/one_test/argv"]))
        check_eq("F5: and leaves the recorded kind alone", no_kind["proposed_config"]["profiles"][0]["reporter"], {"kind": "trx"})
    finally:
        cleanup(root)


def f6_the_onboarding_sentence_obeys_the_rules_a_person_reads_by() -> None:
    table = P.cure_table()[0]
    cases = {"the vitest cure": (["npx", "vitest", "run", "--reporter=junit", "--outputFile={report_path}"], "cure"),
             "the dotnet cure": (["dotnet", "test", "--logger", "trx;LogFileName={report_path}"], "cure"),
             "a person's command": (["python", "manage.py", "test", "--reporters", "junit", "--out", "{report_path}"], "command"),
             "a command with no placeholder": (["pytest", "--junitxml=report.xml"], "command")}
    for label, (argv, source) in cases.items():
        text = P.render_question(table, "web", argv, source)
        check_eq(f"F6: {label}: human_text.problems on the sentence a person is asked is empty", human_text.problems(text), [])
        check_in(f"F6: {label}: the offer is the owner's sentence", "I propose to run the web tests as: `", text)
        check_in(f"F6: {label}: and the command itself", C.display_command(argv), text)
    cure = P.render_question(table, "web", cases["the dotnet cure"][0], "cure")
    check_in("F6: a command with `{report_path}` says what that is", "stands for the file the factory reads the report from", cure)
    check_not_in("F6: one without it does not", "stands for the file",
                 P.render_question(table, "web", cases["a command with no placeholder"][0], "command"))
    broken = human_text.problems(cure.replace("I propose to run", "You could run"))
    check("F6 (negative control): the same sentence under another opening is the body, and its flag fires",
          "flag" in {p["rule"] for p in broken}, str(broken))
    check_not_in("F6: nothing in the sentence is a script, a config key or a form field", "config_key",
                 " ".join(p["rule"] for p in human_text.problems(P.render_question(table, "web", cases["a person's command"][0], "command"))))


def f7_apply_plan_refuses_on_validate_and_nothing_is_written() -> None:
    root = project(execution={"parallel": {"mode": "bogus", "min_selected_instances": 2}})
    try:
        before = (root / "qa-factory" / "config.json").read_bytes()
        proposal = make(root)
        check_eq("F7: the maker does not judge the rest of the config: it made the proposal", len(proposal["changes"]), 1)
        ref = C.command_approval_ref(proposal)
        C.record_approval(root, proposal, ref, "transcript:yes")
        message = refusal_of(lambda: C.apply_plan(root, proposal, ref))
        check_in("F7: apply_plan refuses on `validate`, and says which key", "proposed config is invalid: execution.parallel.mode must be auto or serial", message)
        check_in("F7: with what to do", "Nothing was written", message)
        check_eq("F7: the config is byte-identical", (root / "qa-factory" / "config.json").read_bytes(), before)
        check("F7: and no backup was made", not (root / "qa-factory" / "records" / "config-migrations").exists())
    finally:
        cleanup(root)


def f9_a_command_is_approved_by_a_person_and_by_nobody_else() -> None:
    root = project()
    try:
        for kind in ("cure", "command"):
            proposal = make(root, kind=kind)
            for label, ref, evidence in (("a headless ref", "headless:abc123", "transcript:yes"),
                                         ("an upper-case headless ref", "HEADLESS:abc", "transcript:yes"),
                                         ("a headless evidence", f"onboarding-{kind}:web:x", "headless: --apply on the command line")):
                said = refusal_of(lambda: C.record_approval(root, proposal, ref, evidence))
                check_in(f"F9: a {kind} proposal refuses {label}, and says only a person's word approves it", "only a person's word approves that", said)
                check_in(f"F9: {kind}/{label}: with the door", "onboarding_probe.py --question", said)
            check_eq(f"F9: nothing was recorded for a refused {kind}", C.approvals_path(root).exists(), False)
        proposal = make(root)
        C.record_approval(root, proposal, C.command_approval_ref(proposal), "transcript:the person said yes")
        record = json.loads(C.approvals_path(root).read_text(encoding="utf-8").splitlines()[-1])
        check_eq("F9: a person's yes is recorded, with the kind of what was approved", (record["status"], record["kind"]), ("approved", "cure"))
        # the control: every other proposal keeps its headless entry (the documented way for an install, E27 of the node)
        plan = C.migration_plan(config_of(root))
        C.record_approval(root, plan, "headless:control", "headless: --apply on the command line")
        check_eq("F9 (control): a migration proposal is still approved by a headless ref", json.loads(
            C.approvals_path(root).read_text(encoding="utf-8").splitlines()[-1])["approval_ref"], "headless:control")
        # onboard_apply: a cure is refused without an --approval-ref, by name, before anything is recorded
        sealed = root.parent / f"{root.name}-sealed.json"
        sealed.write_text(json.dumps(proposal), encoding="utf-8")
        before = C.approvals_path(root).read_text(encoding="utf-8")
        tree = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
        done = harness.run_script("onboard_apply.py", "--root", root, "--proposal", sealed, "--apply", cwd=root)
        check_eq("F9: onboard_apply --apply with no --approval-ref refuses a cure proposal (exit 1)", done.returncode, 1)
        check_in("F9: by name, saying why and what to do", "one approval changes one key", done.stderr)
        check_in("F9: it names the profile", "(web)", done.stderr)
        check_in("F9: and the approval ref the yes is recorded under", C.command_approval_ref(proposal), done.stderr)
        check_eq("F9: and recorded nothing", C.approvals_path(root).read_text(encoding="utf-8"), before)
        check_eq("F9: nor wrote the config", config_of(root)["profiles"][0]["commands"]["one_test"]["argv"], ARGV)
        # F4: the SAME refusal with a person's recorded yes - the door is config_contract.py --apply, and the full install never runs
        with_ref = harness.run_script("onboard_apply.py", "--root", root, "--proposal", sealed, "--apply", "--approval-ref",
                                      C.command_approval_ref(proposal), cwd=root)
        check_eq("F4: with a person's ref onboard_apply --apply STILL refuses a cure proposal (exit 1)", with_ref.returncode, 1)
        check_in("F4: and names the door that writes one key", "applied by `config_contract.py --root <project> --apply <the sealed file> --approval-ref "
                 + C.command_approval_ref(proposal), with_ref.stderr)
        check_in("F4: and why", "one approval changes one key", with_ref.stderr)
        check_eq("F4: the full install never ran: no new file at all (no install manifest, no readiness, no dashboard)",
                 {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} - tree, set())
        check_eq("F4: and the config is as it was", config_of(root)["profiles"][0]["commands"]["one_test"]["argv"], ARGV)
        listing = harness.run_script("onboard_apply.py", "--root", root, "--proposal", sealed, "--listing", cwd=root)
        check_eq("F9/F4: onboard_apply --listing of a cure proposal prints the sealed sentence", (listing.returncode, listing.stdout.strip()),
                 (0, SENTENCE.strip()))
        sealed.unlink()
    finally:
        cleanup(root)


def f8_a_second_yes_is_already_done_and_an_old_proposal_is_stale() -> None:
    root = project()
    sealed = root.parent / f"{root.name}-sealed.json"
    try:
        proposal = make(root)
        sealed.write_text(json.dumps(proposal), encoding="utf-8")
        ref = C.command_approval_ref(proposal)
        check_eq("F8: before the yes the proposal is pending", C.command_state(root, proposal)["state"], "pending")
        yes = harness.run_script("config_contract.py", "--root", root, "--record-approval", sealed, "--approval-ref", ref,
                                 "--evidence-ref", "transcript:yes", cwd=root)
        check_eq("F8: the yes is recorded through the existing CLI", (yes.returncode, "approval_log" in yes.stdout), (0, True))
        applied = harness.run_script("config_contract.py", "--root", root, "--apply", sealed, "--approval-ref", ref, cwd=root)
        check_eq("F8: and applied through the existing CLI (apply_plan)", (applied.returncode, "backup" in applied.stdout), (0, True))
        check_eq("F8: the config has the cured command", config_of(root)["profiles"][0]["commands"]["one_test"]["argv"], CURED)
        after_first = (root / "qa-factory" / "config.json").read_bytes()
        approvals = C.approvals_path(root).read_text(encoding="utf-8")
        check_eq("F8: after the apply the proposal is `already_done`", C.command_state(root, proposal)["state"], "already_done")
        for label, flag, extra in (("a second yes", "--record-approval", ["--evidence-ref", "transcript:yes again"]), ("a second apply", "--apply", [])):
            again = harness.run_script("config_contract.py", "--root", root, flag, sealed, "--approval-ref", ref, *extra, cwd=root)
            data = json.loads(again.stdout) if again.stdout.strip() else {}
            check_eq(f"F8: {label} is 'already done' (exit 0), never a stale refusal", (again.returncode, data.get("already_done")), (0, True))
            check_in(f"F8: {label}: says what the config already holds", "already done: npx vitest run --reporter=junit", data.get("says", ""))
            check_eq(f"F8: {label}: wrote nothing", ((root / "qa-factory" / "config.json").read_bytes(), C.approvals_path(root).read_text(encoding="utf-8")),
                     (after_first, approvals))
        # an old proposal: the config moved on (the command changed again) - stale, in words
        cfg = config_of(root)
        cfg["profiles"][0]["commands"]["one_test"]["argv"] = ["npx", "vitest", "run", "--other"]
        (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        check_eq("F8: a proposal the config has moved away from is `stale`", C.command_state(root, proposal)["state"], "stale")
        stale = harness.run_script("config_contract.py", "--root", root, "--record-approval", sealed, "--approval-ref", "onboarding-cure:web:again",
                                   "--evidence-ref", "transcript:yes", cwd=root)
        door = ("proposal is stale: the config changed after this proposal was made, so a yes to it would change a command nobody asked about. "
                "Make the proposal again: run `onboarding_probe.py --root <project> --probe-profiles --proposals-dir <a folder outside the project>` "
                "(for a command the person gave: `onboarding_probe.py --root <project> --profile <id> --command \"<their line>\" --proposals-dir "
                "<a folder outside the project>`), show the person the new sentence, and record their yes on the new file.")
        check_eq("F8: its yes is refused (exit 1)", stale.returncode, 1)
        check_eq("F8: with the stale word AND the door - the whole sentence, not a substring", stale.stderr.strip(), "config_contract: refused: " + door)
        stale_apply = harness.run_script("config_contract.py", "--root", root, "--apply", sealed, "--approval-ref", ref, cwd=root)
        check_eq("F8: the apply of the old proposal (its yes was recorded before the config moved) is refused with the SAME sentence",
                 (stale_apply.returncode, stale_apply.stderr.strip()), (1, "config_contract: refused: " + door))
        check_eq("F8: command_state carries the same door", C.command_state(root, proposal)["why"], door)
        check_eq("F8 (twin): a proposal that is not a command proposal keeps its old, bare word", refusal_of(
            lambda: C.record_approval(root, dict(C.migration_plan(config_of(root)), input_hash="x"), "r:1", "t:1")), "proposal is stale")
        check_eq("F8: a proposal that is not sealed is `invalid`", C.command_state(root, dict(proposal, proposal_hash="0"))["state"], "invalid")
    finally:
        sealed.unlink(missing_ok=True)
        cleanup(root)


def b1_a_proposal_that_sets_only_env_is_pending_until_the_env_is_on_disk() -> None:
    """EP1-22 B1: the command is its argv AND its env. A proposal whose argv equals the profile's and that only sets `env` is
    `pending` (not `already_done`), a yes through --record-approval and --apply writes the env, and then it is `already_done`;
    absent / null / `{}` env on both sides is as it always was; an env that moved after sealing is not `already_done`."""
    var = "PLAYWRIGHT_JUNIT_OUTPUT_NAME"
    argv = ["npx", "playwright", "test", "--reporter=junit"]
    shown = "npx playwright test --reporter=junit"
    question = f"One existing test ran.\n\nI propose to run the web tests as: `{shown}`, with `{var}` set. Do it? yes / no\n"
    root = project(profiles=[{"profile_id": "web", "reporter": {"kind": "junit-xml"}, "commands": {"one_test": {"argv": argv, "cwd": "."}}}])
    sealed = root.parent / f"{root.name}-env-sealed.json"
    try:
        proposal = C.command_proposal(root, {"profile_id": "web"}, argv, reporter_kind="junit-xml", question=question, env={var: "{report_path}"})
        sealed.write_text(json.dumps(proposal), encoding="utf-8")
        check_eq("B1: an env-only proposal (same argv, same kind) is pending, not already done", C.command_state(root, proposal)["state"], "pending")
        ref = C.command_approval_ref(proposal)
        yes = harness.run_script("config_contract.py", "--root", root, "--record-approval", sealed, "--approval-ref", ref,
                                 "--evidence-ref", "transcript:yes", cwd=root)
        check_eq("B1: the yes is recorded (not 'already done')", (yes.returncode, "already_done" in yes.stdout), (0, False))
        applied = harness.run_script("config_contract.py", "--root", root, "--apply", sealed, "--approval-ref", ref, cwd=root)
        check_eq("B1: the apply writes (not 'already done')", (applied.returncode, "already_done" in applied.stdout), (0, False))
        check_eq("B1: the env is on disk after the yes", config_of(root)["profiles"][0]["commands"]["one_test"].get("env"), {var: "{report_path}"})
        check_eq("B1: and then the proposal is already done", C.command_state(root, proposal)["state"], "already_done")
        # stale: the env moved after sealing (argv still equal): not already done
        cfg = config_of(root)
        cfg["profiles"][0]["commands"]["one_test"].pop("env")
        (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        check_eq("B1: an env taken out after the apply is not 'already done'", C.command_state(root, proposal)["state"] != "already_done", True)
        # absent / null / {} on both sides: the proposal of a plain argv change is as it always was
        for label, env_on_disk in (("absent", None), ("null", "NULL"), ("empty", {})):
            cfg = config_of(root)
            spec = cfg["profiles"][0]["commands"]["one_test"]
            spec.pop("env", None)
            spec["argv"] = ["npx", "playwright", "test"]
            if env_on_disk is not None:
                spec["env"] = None if env_on_disk == "NULL" else env_on_disk
            (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            plain = C.command_proposal(root, {"profile_id": "web"}, argv, reporter_kind=None, question=question)
            check_eq(f"B1: env {label} on both sides: pending before, already done after (as before)",
                     C.command_state(root, plain)["state"], "pending")
            moved = copy.deepcopy(plain)
            moved["proposed_config"]["profiles"][0]["commands"]["one_test"]["argv"] = ["npx", "playwright", "test"]
            moved["proposal_hash"] = C.proposal_hash(moved)
            check_eq(f"B1: env {label} on both sides, same argv: already done", C.command_state(root, moved)["state"], "already_done")
    finally:
        sealed.unlink(missing_ok=True)
        cleanup(root)


def k8_no_new_writer_of_the_config() -> None:
    """The one place the config is written is `apply_plan`, reached by `--apply`; the maker, the question and the state reader write
    nothing and add no operation to the CLI."""
    done = harness.run_script("config_contract.py", "--help")
    options = sorted(set(re.findall(r"--[a-z][a-z-]+", done.stdout)) - {"--help"})
    check_eq("K8: config_contract.py has the operations it had and no new one", options,
             sorted(["--root", "--migration-plan", "--apply", "--record-approval", "--approval-ref", "--evidence-ref", "--fold", "--validate",
                     "--price-table-answer", "--answers", "--model-id", "--check-environment"]))
    root = project()
    try:
        before = (root / "qa-factory" / "config.json").read_bytes()
        proposal = make(root)
        C.command_question(proposal)
        C.command_state(root, proposal)
        check_eq("K8: the maker, the question and the state reader leave config.json byte-identical",
                 (root / "qa-factory" / "config.json").read_bytes(), before)
    finally:
        cleanup(root)


def b220_the_apply_runs_the_report_probe_itself() -> None:
    """`onboard_apply --apply` runs the probe right after it writes the profiles (P3: code runs the command, the LLM relays): one
    proposal in round 1 with its sentence, the person text per profile, nothing applied; `--no-probe` runs nothing."""
    import shutil
    import test_onboarding_probe as T

    def fresh():
        root = T.project([T.profile("api", [T.PY, "fake_vitest.py", "run", "vitest"]), T.profile("web", [T.PY, "fake_dotnet.py", "test"]),
                          T.profile("ui", [T.PY, "fake_karma.py", "ng", "test"]), T.profile("off", [T.PY, "fake_karma.py"], selected=False),
                          T.profile("py", [T.PY, "-m", "pytest", "-p", "no:junitxml", "-p", "no:cacheprovider", "<test-id>"])],
                         test_command_templates=T.PYTEST_TEMPLATES)
        answers = root.parent / f"{root.name}-answers.json"
        answers.write_text(json.dumps({"/environment/access": {"kind": "none"}}), encoding="utf-8")
        return root, answers

    root, answers = fresh()
    twin, twin_answers = fresh()
    folder = None
    try:
        before, twin_before = T.snapshot(root), T.snapshot(twin)
        done = harness.run_script("onboard_apply.py", "--root", root, "--answers", answers, "--apply", cwd=root)
        root_after = T.snapshot(root)
        data = json.loads(done.stdout)
        probe = data["report_probe"]
        check_eq("apply: exits 0 and prints ONE JSON object with the probe in it", (done.returncode, data["applied"]), (0, True))
        check_eq("apply: round 1 - ONE proposal, the other profile waits its turn, the rest are explained or told",
                 [e["move"] for e in probe["profiles"]], ["do_it", "waits_for_turn", "explain_and_ask", "tell", "explain_and_ask"])
        texts = probe["person_text"]
        check_eq("apply: the person text per profile that needs a word", [t["profile"] for t in texts], ["api", "web", "ui", "off", "py"])
        check_in("apply: the first is the proposal sentence with its question", "I propose to run the api tests as: `", texts[0]["text"])
        check_in("apply: ... and asks", "Do it? yes / no", texts[0]["text"])
        check_in("apply: the second says it waits, for whom", "api", texts[1]["text"])
        # F2 on the REAL carrier: every entry of the apply's JSON - do_it, the waiting one, explain_and_ask, tell - obeys the rules
        for t in texts:
            check_eq(f"F2: person_text of `{t['profile']}` ({t['move']}) passes human_text.problems", human_text.problems(t["text"]), [])
        explained = [t["text"] for t in texts if t["move"] == "explain_and_ask"]
        check("F2: no flag, no option and no raw stderr tail on a body line of an explaining text",
              all("--" not in x.split("\n---\n")[0] and "Executed 1 of 1 SUCCESS" not in x and "1 passed" not in x for x in explained),
              str(explained)[:300])
        check_in("F2: the explaining text of the karma profile says what the cure needs, in words (the cure row's person words)",
                 "JUnit report package", explained[0])
        check_in("F2: and offers the three answers", "(c) leave it for now", explained[0])
        ui = probe["profiles"][2]
        check_in("F2: the raw tail of the run stays a CODE field (`report.detail`)", "Executed 1 of 1 SUCCESS", ui["report"]["detail"])
        check_not_in("F2: and is not in the sentence for the LLM either (`says`)", "Executed 1 of 1 SUCCESS", ui["says"])
        check_eq("F10: the apply's do_it text IS the sentence rendered from the sealed file (one renderer)",
                 texts[0]["text"], C.command_question(json.loads(Path(probe["profiles"][0]["proposal"]["path"]).read_text(encoding="utf-8"))))
        # F10 key: the text is read back from the SEALED FILE. A file edited after the probe makes the person text a refusal
        # (never the maker's own copy of the sentence); the untouched file gives the sentence (the positive control above).
        tampered = Path(probe["profiles"][0]["proposal"]["path"]).with_name("tampered.json")
        data_t = json.loads(Path(probe["profiles"][0]["proposal"]["path"]).read_text(encoding="utf-8"))
        data_t["listing"]["question"] = data_t["listing"]["question"].replace("Do it?", "Do it now?")
        tampered.write_text(json.dumps(data_t), encoding="utf-8")
        entry_t = json.loads(json.dumps(probe["profiles"][0]))
        entry_t["proposal"]["path"] = str(tampered)
        said = P.person_text(entry_t)
        check_in("F10: an edited sealed file is NOT shown as the maker's sentence: the text says it could not be read back", "could not be read back", said)
        check_not_in("F10: and the old sentence is not in it", "Do it? yes / no", said)
        check_eq("F10: that refusal obeys the rules a person reads by", human_text.problems(said), [])
        tampered.unlink()
        check("F4 (positive control): a normal apply DOES write the install manifest (so its absence after a cure apply means something)",
              "qa-factory/install-manifest.json" in set(root_after) - set(before))
        proposal_path = Path(probe["profiles"][0]["proposal"]["path"])
        folder = proposal_path.parent
        check_eq("apply: one sealed file in the folder", len(list(folder.iterdir())), 1)
        check("apply: and that folder is not under the project", root.resolve() not in folder.resolve().parents)
        check_eq("apply: a headless apply only REPORTS the cure - the command is as it was", config_of(root)["profiles"][0]["commands"]["one_test"]["argv"],
                 [T.PY, "fake_vitest.py", "run", "vitest"])
        sealed = json.loads(proposal_path.read_text(encoding="utf-8"))
        ref = probe["profiles"][0]["proposal"]["approval_ref"]
        C.record_approval(root, sealed, ref, "transcript:yes")
        C.apply_plan(root, sealed, ref)
        check_eq("apply: the proposal made by the apply is applied on a yes (made against the config as written)",
                 config_of(root)["profiles"][0]["commands"]["one_test"]["argv"][-2:], ["--reporter=junit", "--outputFile={report_path}"])
        quiet_done = harness.run_script("onboard_apply.py", "--root", twin, "--answers", twin_answers, "--apply", "--no-probe", cwd=twin)
        check_eq("--no-probe: no probe result and nothing run", (quiet_done.returncode, json.loads(quiet_done.stdout)["report_probe"]), (0, None))
        check_eq("--no-probe: the probe writes nothing else: the two applies differ by the collect's pytest cache folder only, whichever files this pytest writes into it",
                 T.outside_the_collect_cache((set(root_after) - set(before)) ^ (set(T.snapshot(twin)) - set(twin_before))), set())
    finally:
        if folder:
            shutil.rmtree(folder, ignore_errors=True)
        cleanup(root)
        cleanup(twin)
        answers.unlink(missing_ok=True)
        twin_answers.unlink(missing_ok=True)


def f2_the_probe_failure_is_one_sentence_the_person_hears() -> None:
    """The failure branch of the apply's probe used to give `person_text: []`: the problem never reached the person."""
    import types
    import onboard_apply as OA
    root = project()
    real = P.probe_profiles
    try:
        args = types.SimpleNamespace(no_probe=False, phase="all")
        P.probe_profiles = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("the stand is on fire"))
        got = OA._report_probe(root, {"applied": True}, args)
        check_eq("F2: a probe that fails is reported, not raised, with no profile result", (got["profiles"], len(got["person_text"])), ([], 1))
        text = got["person_text"][0]["text"]
        check_in("F2: ONE sentence, and it carries the problem", "the stand is on fire", text)
        check_in("F2: and says nothing was changed by it", "Nothing was changed by it", text)
        check_eq("F2: and that sentence obeys the rules a person reads by", human_text.problems(text), [])
        check_eq("F2: the same sentence is the module's own", got["person_text"][0]["text"], P.problem_text(got["problem"]))
        P.probe_profiles = real
        for label, result in (("an apply that did not happen", {"applied": False}), ("a plan with nothing to do", {"applied": True, "nothing_to_do": True})):
            check_eq(f"F2 (twin): {label} runs no probe", OA._report_probe(root, result, args), None)
        check_eq("F2 (twin): --no-probe runs none", OA._report_probe(root, {"applied": True}, types.SimpleNamespace(no_probe=True, phase="all")), None)
        check_eq("F2: a probe that could not start (no profile) is one person entry too",
                 [(t["profile"], human_text.problems(t["text"])) for t in P.person_texts({"problem": "the configuration records no execution profile"})],
                 [("", [])])
    finally:
        P.probe_profiles = real
        cleanup(root)


def b416_f20_a_report_adaptation_is_written_by_the_one_writer_and_nothing_else() -> None:
    """B-416 F20 (b), M7: `apply_adaptation` writes a sealed `command_proposal` that is NOTHING BUT an empty `reporter.kind` -> junit-xml | trx
    with the command unchanged. The authority is the helper's record row (`RA-<n>`): no approval line. The proposal's own `changes` and
    `listing` are never trusted - the check compares `proposed_config` with the current config."""
    sentence = "One existing test ran.\n\nI read the report of the web command (`npx vitest run`) as trx. Do it?\n\n---\nAnswer: yes or no.\n"

    def adaptation(root: Path, reporter_kind="trx", **kw) -> dict:
        return C.command_proposal(root, {"profile_id": "web"}, ARGV, reporter_kind=reporter_kind, kind=kw.pop("kind", "cure"),
                                  reason="report adaptation RA-1", question=sentence)

    def reseal(proposal: dict) -> dict:
        proposal["proposal_hash"] = C.proposal_hash(proposal)
        return proposal

    def refused(root: Path, proposal: dict, why: str, ref: str = "RA-1") -> str:
        before = (root / "qa-factory" / "config.json").read_bytes()
        said = refusal_of(lambda: C.apply_adaptation(root, proposal, ref))
        check_eq(f"F20: {why}: refused, the config is byte-identical, and no approval and no backup was written",
                 (bool(said), (root / "qa-factory" / "config.json").read_bytes() == before, C.approvals_path(root).exists(),
                  (root / "qa-factory" / "records" / "config-migrations").exists()), (True, True, False, False))
        return said
    root = project()
    try:
        before = config_of(root)
        proposal = adaptation(root)
        backup = C.apply_adaptation(root, proposal, "RA-1")
        after = config_of(root)
        check_eq("F20: only the kind of the one profile changed, to the value asked, the command unchanged",
                 (differences(before, after), after["profiles"][0]["reporter"]["kind"], after["profiles"][0]["commands"]["one_test"]["argv"]),
                 (["/profiles"], "trx", ARGV))
        check_eq("F20: through the one writer: the backup carries `RA-1` as its approval_ref (M7 v) and the old config",
                 (json.loads(backup.read_text(encoding="utf-8"))["approval_ref"], json.loads(backup.read_text(encoding="utf-8"))["config"] == before),
                 ("RA-1", True))
        check_eq("F20: and NO approval line was written (the approvals log is a log of people's words)", C.approvals_path(root).exists(), False)
        check_eq("F20: the proposal says `cure` (COMMAND_KINDS) and the reason `report adaptation RA-1` (M7 i)",
                 (proposal["listing"]["kind"], proposal["changes"][0]["reason"]), ("cure", "report adaptation RA-1"))
        check_eq("F20: a second apply of the same proposal is a stale refusal (the config moved on)", "stale" in refusal_of(lambda: C.apply_adaptation(root, proposal, "RA-2")), True)
    finally:
        cleanup(root)
    # every refusal: nothing written, with the door
    root = project()
    try:
        good = adaptation(root)
        # a proposal whose proposed_config ALSO changes another profile's command, with a `changes` row that lies (and a valid seal)
        forged = copy.deepcopy(good)
        forged["proposed_config"]["profiles"][1]["commands"]["one_test"]["argv"] = ["pytest", "-x"]
        said = refused(root, reseal(forged), "a proposal that also changes another profile's command (the `changes` row says only the kind)")
        check_in("F20 (iv): the refusal says what an adaptation may do, and what this one also changes, and the door", "this proposal also changes /profiles/1", said)
        check_in("F20 (iv): ... `report_adapt.py understood` is the door", "report_adapt.py understood", said)
        check_in("F20 (iv): and starts `nothing was written`, naming the profile", "nothing was written: an adaptation may only set an empty report kind of profile web", said)
        forged = copy.deepcopy(good)
        forged["proposed_config"]["profiles"][0]["commands"]["one_test"]["argv"] = ARGV + ["--other"]
        check_in("F20: a changed command of the SAME profile is refused too", "also changes /profiles/0/commands/one_test/argv", refused(root, reseal(forged), "a changed command"))
        forged = copy.deepcopy(good)
        forged["proposed_config"]["environments"] = [{"name": "x"}]
        check_in("F20: a change outside the profiles is refused", "also changes", refused(root, reseal(forged), "a change of another key"))
        forged = copy.deepcopy(good)
        forged["proposed_config"]["profiles"][1]["reporter"] = {"kind": "trx"}
        check_in("F20: the kind of TWO profiles is refused", "also changes /profiles/1", refused(root, reseal(forged), "two profiles' kinds"))
        forged = copy.deepcopy(good)
        forged["proposed_config"]["profiles"][0]["reporter"]["kind"] = "pytest"
        check_in("F20: a kind outside junit-xml | trx (`pytest` is the runner's own)", "not one of junit-xml, trx", refused(root, reseal(forged), "another kind"))
        forged = copy.deepcopy(good)
        forged["proposed_config"]["profiles"][0]["reporter"]["extra"] = 1
        check_in("F20: another key inside `reporter` is refused", "also changes /profiles/0/reporter", refused(root, reseal(forged), "an extra reporter key"))
        tampered = copy.deepcopy(good)
        tampered["proposed_config"]["profiles"][1]["commands"]["one_test"]["argv"] = ["x"]
        check_in("F20: a proposal edited after sealing (no reseal) is refused by its hash", "proposal hash is invalid", refused(root, tampered, "an unsealed edit"))
        check_in("F20: a `command` proposal (a person's own command) is not an adaptation", "not a proposal the report adaptation made",
                 refused(root, C.command_proposal(root, {"profile_id": "web"}, ARGV, reporter_kind="trx", kind="command", question=sentence), "kind `command`"))
        check_in("F20: an empty adaptation ref is refused", "adaptation ref", refused(root, good, "an empty ref", ref=" "))
        # the config moved after the proposal: stale, with the door
        path = root / "qa-factory" / "config.json"
        moved = config_of(root)
        moved["profiles"][1]["commands"]["one_test"]["argv"] = ["pytest", "-q"]
        path.write_text(json.dumps(moved, indent=2), encoding="utf-8")
        check_in("F20: a config that moved after the proposal is stale", "proposal is stale", refused(root, good, "a stale proposal"))
    finally:
        cleanup(root)
    # a recorded kind is never overwritten (P13): a proposal made while the kind was EMPTY, applied after a person recorded another one
    # (the input hash re-made, so only the writer's own rule can refuse it)
    root = project()
    try:
        late = adaptation(root)
        moved = config_of(root)
        moved["profiles"][0]["reporter"] = {"kind": "junit-xml"}
        (root / "qa-factory" / "config.json").write_text(json.dumps(moved, indent=2), encoding="utf-8")
        late["input_hash"] = C._json_hash(config_of(root))
        said = refused(root, reseal(late), "a profile that records a kind of its own (the proposal says another)")
        check_in("F20: the refusal names the kind that is recorded and the door", "already records `junit-xml`", said)
        check_eq("F20: the recorded kind stands", config_of(root)["profiles"][0]["reporter"]["kind"], "junit-xml")
    finally:
        cleanup(root)
    root = project(profiles=[{"profile_id": "web", "reporter": {"kind": "trx"}, "commands": {"one_test": {"argv": ARGV, "cwd": "."}}}])
    try:
        check_in("F20: a profile that already records the very kind: nothing to adapt, refused", "already holds", refused(root, adaptation(root), "the same kind"))
    finally:
        cleanup(root)
    root = project(profiles=[{"profile_id": "web", "reporter": {"kind": ""}, "commands": {"one_test": {"argv": ARGV, "cwd": "."}}}])
    try:
        C.apply_adaptation(root, adaptation(root), "RA-3")
        check_eq("F20: an EMPTY recorded kind (\"\") is not a recorded kind: it is set", config_of(root)["profiles"][0]["reporter"]["kind"], "trx")
    finally:
        cleanup(root)


def main() -> None:
    b416_f20_a_report_adaptation_is_written_by_the_one_writer_and_nothing_else()
    f2_the_probe_failure_is_one_sentence_the_person_hears()
    b220_the_apply_runs_the_report_probe_itself()
    ko6_the_maker_changes_one_key_and_seals_it()
    f4_the_yes_is_bound_to_the_sentence_the_person_read()
    f5_one_row_two_pointers_and_a_recorded_kind_is_not_overwritten()
    f6_the_onboarding_sentence_obeys_the_rules_a_person_reads_by()
    f7_apply_plan_refuses_on_validate_and_nothing_is_written()
    f9_a_command_is_approved_by_a_person_and_by_nobody_else()
    f8_a_second_yes_is_already_done_and_an_old_proposal_is_stale()
    b1_a_proposal_that_sets_only_env_is_pending_until_the_env_is_on_disk()
    k8_no_new_writer_of_the_config()
    finish("test_command_proposal")


if __name__ == "__main__":
    main()
