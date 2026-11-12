#!/usr/bin/env python3
"""The handoff contracts: the contract is the schema, and code fills what code can derive.

Every shape here is real. The stale case version, the missing `run_witness` and the word a
role reached for outside the list are the three refusals that cost TP1-13797 twenty-three
resumed role sessions and nineteen conductor sessions at S5 alone.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (FIXTURES, PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_dir, temp_project)

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import handoff  # noqa: E402

import tempfile  # noqa: E402

CONTRACTS = PLUGIN_ROOT / "handoffs"


def the_folder_and_the_index_agree() -> None:
    index = handoff.index()
    named = {str(row.get("contract")) for row in index.get("handoffs", [])}
    named.add(str((index.get("escalation") or {}).get("contract")))
    on_disk = {p.stem for p in CONTRACTS.glob("*.yaml")} - {"index", "vocabulary"}
    check_eq("every contract the index names has a file", sorted(named - on_disk), [])
    check_eq("every file is named by the index", sorted(on_disk - named), [])
    check("the index covers every handover of a story", len(index.get("handoffs", [])) >= 20,
          f"{len(index.get('handoffs', []))} handovers")
    for row in index.get("handoffs", []):
        where = str(row.get("stage") or row.get("gate") or "")
        got = handoff.contract_of(where, str(row.get("from")), str(row.get("to")), str(row.get("purpose") or ""))
        if got != str(row.get("contract")):
            check(f"lookup resolves {where} {row.get('from')} -> {row.get('to')}", False, got)
            return
    check("every row resolves by stage and role, never by file name", True)
    # Three roles hand over twice. Without a named receiver the lookup must return the
    # DISPATCH-TIME contract - the form `story_step start` writes is the one the role fills now.
    for stage, role, expected in (("S4", "qa-case-designer", "s4-designer-to-case-critic"),
                                  ("S5", "qa-automator", "s5-automator-to-critic"),
                                  ("S7", "qa-failure-analyst", "s7-analyst-to-automator")):
        got = handoff.contract_of(stage, role)
        if got != expected:
            check(f"{stage} {role} with no receiver picks its dispatch-time contract", False, got)
            return
    check("a role that hands over twice gets the form it is about to fill", True)
    check_eq("and the second contract is reachable by naming the receiver",
             handoff.contract_of("S5", "qa-automator", "qa-runner"), "s5-automator-to-runner")


def every_contract_parses_and_carries_the_shape() -> None:
    kinds = {str(row.get("contract")): str(row.get("kind")) for row in handoff.index()["handoffs"]}
    kinds[str(handoff.index()["escalation"]["contract"])] = "help"
    for path in sorted(CONTRACTS.glob("*.yaml")):
        if path.stem in ("index", "vocabulary"):
            continue
        doc = handoff.parse(path.read_text(encoding="utf-8"))
        missing = [key for key in ("schema_version", "contract") if key not in doc.data]
        if missing:
            check(f"{path.name} carries the shared skeleton", False, f"missing {missing}")
            return
        if doc.data.get("contract") != path.stem:
            check(f"{path.name} names itself", False, str(doc.data.get("contract")))
            return
        # an item handover carries `scope`; a gate, the story's setup and the conductor's own
        # form have no item list, and the index says which is which
        wants_scope = kinds.get(path.stem) in ("produce", "review", "ledger")
        if wants_scope != ("scope" in doc.data):
            check(f"{path.name}: `scope` matches its kind ({kinds.get(path.stem)})", False,
                  f"scope={'scope' in doc.data}")
            return
    check("every contract parses, names itself and matches its kind", True)


def the_vocabulary_is_the_single_list() -> None:
    """P1: a word the Python literals accept must exist in the vocabulary file, or the two
    lists have started to drift again - which is what cost four handoffs."""
    import role_digest as RD
    states = set(handoff.allowed("row_states"))
    literal = set(RD.BASE_STATES) | set(RD.ITEM_STATES)
    check_eq("every word role_digest knows is in the vocabulary", sorted(literal - states), [])
    check_eq("the header verdicts are the same four",
             sorted(handoff.allowed("header_verdicts")), sorted(RD.HEADER_VERDICTS))
    import contract as C
    for name, literals in (("unresolved_reasons", C.UNRESOLVED_REASONS),
                           ("execution_status", C.EXECUTION_STATUS),
                           ("result_status", C.RESULT_STATUS),
                           ("critic_verdicts", C.CRITIC_VERDICTS)):
        missing = sorted(set(literals) - set(handoff.allowed(name)))
        if missing:
            check(f"vocabulary.{name} covers contract.py", False, f"missing {missing}")
            return
    check("vocabulary.yaml covers every closed list contract.py holds", True)
    import critic_rollcall
    check_eq("every case-critic verdict word is a row state of the vocabulary",
             sorted(set(critic_rollcall.CASE_CRITIC_VERDICTS) - states), [])
    # FR-35 / D-0013: a critic can say "could not verify" as a word of its own, and the ledger
    # words it emits (`review_rejected`, `review_unverified`, `review_unrecognised`, and the three
    # the list lacked) are states a digest row may carry - in both lists, exactly.
    check_eq("the critic's verdicts are the same list in the contract and the vocabulary",
             sorted(handoff.allowed("critic_verdicts")), sorted(C.CRITIC_VERDICTS))
    check_in("unverified is a critic verdict", "unverified", handoff.allowed("critic_verdicts"))
    for word in ("review_rejected", "review_unverified", "review_unrecognised", "not_verified", "partial", "error"):
        check_in(f"{word} is a state a digest row may carry", word, RD.ROW_STATES)


def the_grounding_vocabulary_line_is_one_builder_and_never_blank() -> None:
    """OH3-14: the line that hands a role the labels and the requirement states is built here, once, from `allowed`; a missing or
    empty list is declared, never blank, and the helper never raises."""
    line = handoff.grounding_vocabulary_line()
    labels, states = handoff.allowed("grounding_labels"), handoff.allowed("requirement_grounding_states")
    check_eq("grounding line: exactly the driver's old shape, labels then requirement states",
             line, f"labels: {', '.join(labels)}; requirement states: {', '.join(states)}.")
    check("grounding line: both lists are non-empty in the shipped vocabulary (the control for the empty cases below)", bool(labels and states))
    real_vocabulary, real_allowed = handoff.vocabulary, handoff.allowed
    try:
        def gone():
            raise FileNotFoundError("vocabulary.yaml")

        handoff.vocabulary = gone
        check_eq("grounding line: no vocabulary file -> both lists declared, no raise", handoff.grounding_vocabulary_line(),
                 "labels: NONE READABLE (the vocabulary holds no `grounding_labels` words); "
                 "requirement states: NONE READABLE (the vocabulary holds no `requirement_grounding_states` words).")
        handoff.vocabulary = real_vocabulary
        handoff.allowed = lambda name: [] if name == "grounding_labels" else real_allowed(name)
        check_eq("grounding line: only the labels empty -> declared there, the states stay whole",
                 handoff.grounding_vocabulary_line(),
                 f"labels: NONE READABLE (the vocabulary holds no `grounding_labels` words); requirement states: {', '.join(states)}.")
    finally:
        handoff.vocabulary, handoff.allowed = real_vocabulary, real_allowed


def the_schema_comes_from_the_contract() -> None:
    spec = handoff.spec("s5-automator-to-critic")
    check_in("a vocabulary reference resolves to the list", "green", spec["scope[].state"].options)
    check_eq("a two-value placeholder is a boolean", spec["claims.every_instance_ran"].kind, "boolean")
    check_eq("a length limit is read off the placeholder", spec["scope[].reason"].max_len, 80)
    check("an optional field is not required",
          handoff.spec("s5-critic-to-automator")["probes.records[].note"].optional)
    check("what the contract writes itself is never refused",
          handoff.owned_by_contract("inputs[0].path") and handoff.owned_by_contract("to_role"))


def a_refusal_names_the_roles_own_words() -> None:
    field = handoff.spec("s5-automator-to-critic")["scope[].state"]
    author = handoff.options_for_role(field, "qa-automator")
    analyst = handoff.options_for_role(field, "qa-failure-analyst")
    check("the whole vocabulary is not put in front of one role", len(author) < len(field.options),
          f"{len(author)} of {len(field.options)}")
    check_in("the author gets its own words", "green", author)
    check("a triage verdict is not offered to the author", "APP_BUG" not in author)
    check_in("and the analyst does get it", "APP_BUG", analyst)


def a_form_is_written_and_then_repaired_by_code() -> None:
    """The whole point: a role is not woken to copy a value that is already on disk."""
    root = Path(tempfile.mkdtemp(prefix="qa-handoff-"))
    try:
        art = root / "artifacts" / "QA-1"
        (art / "work").mkdir(parents=True)
        (art / "state").mkdir()
        (art / "evidence").mkdir()
        (art / "work" / "probes").mkdir()
        (art / "work" / "test-code").mkdir()
        (art / "work" / "automation-manifest.json").write_text(json.dumps({
            "tests": [{"instance_id": "test_one", "case": "TC-001", "status": "green",
                       "file": "tests/test_one.py", "shape": "new",
                       "case_version_links": [{"case_id": "TC-001", "version": "cv_old"}]}],
            "runs": [{"summary_path": "evidence/runs/abc/initial-abc.json"}],
        }), encoding="utf-8")
        (art / "state" / "story-case-links.json").write_text(json.dumps({
            "links": [{"case_id": "TC-001", "version": "cv_new"}]}), encoding="utf-8")
        (art / "work" / "probes" / "test_one.json").write_text("{}", encoding="utf-8")
        (art / "work" / "test-code" / "critic-findings.md").write_text("#", encoding="utf-8")
        (art / "evidence" / "runtime-provenance-api-20260101T000000Z.json").write_text(
            json.dumps({"profile_id": "api", "observed_runtime_identity": "verified_content:abc"}),
            encoding="utf-8")

        form = art / "work" / "handoffs" / "S5-qa-automator-1.yaml"
        done = run_script("handoff_init.py", "--task", "QA-1", "--stage", "S5",
                          "--role", "qa-automator", "--to", "qa-code-critic",
                          "--dispatch", "S5-qa-automator-1", "--task-root", str(art))
        check_eq("the form is written from the contract", done.returncode, 0)
        check("and it exists where the brief says", form.is_file(), done.stdout + done.stderr)
        doc = handoff.parse(form.read_text(encoding="utf-8"))
        check_eq("the header is already filled", doc.get("header.role"), "qa-automator")
        check_eq("and the ticket replaced", doc.get("header.window"), "QA-1")

        done = run_script("handoff_check.py", "--file", str(form), "--task-root", str(art),
                          "--json", "--no-judge")
        report = json.loads(done.stdout)
        check("an untouched form reads as untouched", report["untouched"], done.stdout[:120])

        # the role fills its own part, and claims something the artifacts contradict
        lines = form.read_text(encoding="utf-8").splitlines()
        doc = handoff.parse("\n".join(lines))
        start = doc.nodes["scope[0].id"].line
        end = max(n.end_line for p, n in doc.nodes.items() if p.startswith("scope[0]"))
        rows = ["  - id: test_one", "    state: green", "    reason: written in this window",
                "    origin: new", "    case_version: <the pinned cv_ id this instance was written against>",
                "    obligations: []", "    case: TC-001"]
        doc.lines = doc.lines[:start] + rows + doc.lines[end + 1:]
        doc = handoff.parse(doc.text())
        for path, value in (("header.verdict", "ok"),
                            ("claims.every_case_in_scope_has_an_instance", True),
                            ("claims.every_instance_names_its_current_case_version", True),
                            ("claims.every_instance_ran", True),
                            ("claims.every_expectation_change_after_red_is_recorded", True),
                            ("claims.manifest_matches_the_tests", True),
                            ("tried_note", "fixture: nothing was tried beyond the shared run"),
                            ("for_the_reviewer[0]", "the shared helper holds the oracle")):
            handoff.set_value(doc, path, value)
            doc = handoff.parse(doc.text())
        form.write_text(doc.text(), encoding="utf-8")

        done = run_script("handoff_check.py", "--file", str(form), "--task-root", str(art),
                          "--fix", "--json", "--no-judge")
        report = json.loads(done.stdout)
        fixed = " ".join(report["fixed"])
        check_in("the run witness is taken from the manifest's own runs[]",
                 "evidence/runs/abc/initial-abc.json", fixed)
        check_in("the pinned case version is taken from the links", "cv_new", fixed)
        check_in("the test files are taken from the manifest", "artifacts.tests", fixed)
        check_in("the probes on disk are listed", "artifacts.probes", fixed)
        check_in("and the stand the evidence was taken on", "runtime-provenance", fixed)
        problems = {p["path"]: p["problem"] for p in report["problems"]}
        check_in("a false claim is refused with the count behind it",
                 "claims.every_instance_names_its_current_case_version", problems)
        check_in("and the refusal says what the artifacts say", "carry a version other than the pin",
                 problems.get("claims.every_instance_names_its_current_case_version", ""))

        done = run_script("handoff_check.py", "--file", str(form), "--task-root", str(art),
                          "--set", "claims.every_instance_names_its_current_case_version=false",
                          "--no-judge")
        check_eq("answered honestly, the form is accepted", done.returncode, 0)
        check_in("and it says so", "is complete", done.stdout)
        text = form.read_text(encoding="utf-8")
        check_in("the comments of the contract survive every write", "# The head of the handoff", text)
    finally:
        cleanup(root)


def a_word_outside_the_list_is_refused_with_the_list() -> None:
    root = Path(tempfile.mkdtemp(prefix="qa-handoff-"))
    try:
        art = root / "artifacts" / "QA-2"
        (art / "work").mkdir(parents=True)
        form = art / "work" / "handoffs" / "S5-qa-code-critic-1.yaml"
        run_script("handoff_init.py", "--task", "QA-2", "--stage", "S5", "--role", "qa-code-critic",
                   "--to", "qa-automator", "--dispatch", "S5-qa-code-critic-1", "--task-root", str(art))
        run_script("handoff_check.py", "--file", str(form), "--task-root", str(art),
                   "--set", "review.outcome=send-it-back", "--no-judge")
        done = run_script("handoff_check.py", "--file", str(form), "--task-root", str(art),
                          "--json", "--no-judge")
        problems = {p["path"]: p["problem"] for p in json.loads(done.stdout)["problems"]}
        check_in("the wrong word is named", "review.outcome", problems)
        check_in("and the allowed ones are printed", "approved_with_fixes",
                 problems.get("review.outcome", ""))
    finally:
        cleanup(root)


def what_cannot_be_filled_goes_to_the_conductor() -> None:
    root = Path(tempfile.mkdtemp(prefix="qa-handoff-"))
    try:
        art = root / "artifacts" / "QA-3"
        (art / "work").mkdir(parents=True)
        form = art / "work" / "handoffs" / "S5-qa-automator-1.yaml"
        run_script("handoff_init.py", "--task", "QA-3", "--stage", "S5", "--role", "qa-automator",
                   "--to", "qa-code-critic", "--dispatch", "S5-qa-automator-1", "--task-root", str(art))
        done = run_script("handoff_help.py", "--file", str(form), "--task", "QA-3",
                          "--field", "scope[0].state", "--problem", "the probe tool refused",
                          "--candidate", "unverified", "--json")
        report = json.loads(done.stdout)
        check_eq("the request names the contract", report["request"]["contract"],
                 "s5-automator-to-critic")
        check_eq("and the field", report["request"]["field"], "scope[0].state")
        check_eq("and the word the role would have written", report["request"]["candidate"],
                 "unverified")
        check("the conductor's file is written", Path(report["file"]).is_file())
        text = Path(report["file"]).read_text(encoding="utf-8")
        check_in("with an answer block for the conductor", "resolution:", text)
        done = run_script("handoff_help.py", "--file", str(form), "--task", "QA-3")
        check_eq("an empty `blocked` and no arguments is refused, with what to do",
                 done.returncode, 2)
        check_in("and the refusal is an instruction", "that IS the question", done.stdout)
    finally:
        cleanup(root)


def a_blocked_row_says_what_blocks_it() -> None:
    """GW1-8 (N4, F-10 b; K8). A row in state `blocked` beside an empty `blocked.problem` is refused with the two honest
    shapes and the author's marker; the same row beside a filled `blocked.problem`, and the stand's own word, pass. The
    trigger is the VALUE `blocked` and the PRESENCE of the contract's section (FR-12, FR-38). KILLS M6 (the rule dropped)."""
    import handoff_check
    from role_cli import REPAIR_MARKER
    root = Path(tempfile.mkdtemp(prefix="qa-handoff-blocked-"))
    try:
        art = root / "artifacts" / "QA-3"
        (art / "work").mkdir(parents=True)
        form = art / "work" / "handoffs" / "S5-qa-automator-1.yaml"
        run_script("handoff_init.py", "--task", "QA-3", "--stage", "S5", "--role", "qa-automator",
                   "--to", "qa-code-critic", "--dispatch", "S5-qa-automator-1", "--task-root", str(art))

        def about_blocked(*sets):
            done = run_script("handoff_check.py", "--file", str(form), "--task", "QA-3", "--task-root", str(art),
                              "--json", *[arg for one in sets for arg in ("--set", one)])
            return [p for p in json.loads(done.stdout)["problems"]
                    if p["path"] == "scope[0].state" and "`blocked` says" in p["problem"]]
        found = about_blocked("scope[0].state=blocked")
        check_eq("K8: `blocked` with an empty `blocked.problem` is one problem, on the row's state", len(found), 1)
        for label, needle in (("the stand's word", "blocked_by_env"), ("its remedy", "remedy"),
                              ("the halt road", "header.verdict: halt"), ("the author's marker", REPAIR_MARKER)):
            check_in(f"K8: the refusal names {label}", needle, found[0]["problem"])
        check_eq("K8: with `blocked.problem` filled the row passes (the vocabulary's own meaning)",
                 about_blocked("scope[0].state=blocked", "blocked.problem=the verify tool refused the run"), [])
        # F3 (fix round): the legal shapes, in order - the one that keeps the row first, the stand's word only to a role
        # that may write it (`options_for_role`), the halt road last
        text = found[0]["problem"]
        check("F3: the first shape is filling `blocked.problem`, before the stand's word",
              0 <= text.index("(1) keep `blocked`") < text.index("(2) the stand blocks it") < text.index("blocked_by_env")
              < text.index("(3) a factory command"), text)
        check_in("F3: and the count says three for the automator", "one of three things", text)
        check_eq("K8: the stand's own word is not this rule's", about_blocked("scope[0].state=blocked_by_env"), [])
        check_eq("K8: another state is not this rule's", about_blocked("scope[0].state=green"), [])
        # a contract with no `blocked` section offered the role nothing to fill: never refused for it
        doc = handoff.parse(form.read_text(encoding="utf-8"))
        handoff.set_value(doc, "scope[0].state", "blocked")
        handoff.set_value(doc, "blocked.problem", "<what the role tried and what refused it>")   # the CLI cases above filled it
        doc = handoff.parse(doc.text())
        spec = dict(handoff.spec("s5-automator-to-critic"))
        check_eq("K8: the rule fires on this contract", len(handoff_check._blocked_row_problems(doc, spec)), 1)
        del spec["blocked.problem"]
        check_eq("K8: and not on a contract with no `blocked.problem` field", handoff_check._blocked_row_problems(doc, spec), [])
        # F3: the stand's word is named only to a role `options_for_role` gives it to (a scout, a tester, a designer
        # may not write it); the contract and the row are the same, only the ROLE differs
        spec = dict(handoff.spec("s5-automator-to-critic"))
        for role, offered in (("qa-automator", True), ("qa-runner", True), ("", True), ("qa-scout", False),
                              ("qa-requirements-tester", False)):
            shown = handoff_check._blocked_row_problems(doc, spec, role)
            check_eq(f"F3[{role or 'no role'}]: one problem", len(shown), 1)
            both = shown[0].text + " " + str(shown[0].fix)
            check_eq(f"F3[{role or 'no role'}]: `blocked_by_env` is named exactly when the role is offered it",
                     "blocked_by_env" in both, offered)
            check_in(f"F3[{role or 'no role'}]: filling `blocked.problem` is always a shape", "(1) keep `blocked`", both)
            check_in(f"F3[{role or 'no role'}]: so is the halt road", "header.verdict: halt", both)
            check_in(f"F3[{role or 'no role'}]: and the hint leads with `blocked.problem`",
                     '--set blocked.problem="<what stops the row>"', both)
    finally:
        cleanup(root)


def the_judged_values_are_recorded_in_the_form() -> None:
    """With a judge on, a mapped word is written in and what the role wrote is kept beside it."""
    import handoff_check
    doc = handoff.parse("contract: s5-automator-to-critic\nscope:\n  - id: a\n    state: green\n")
    doc = handoff_check.record_judged(doc, [{"field": "scope[0].state", "value": "unverified",
                                             "as_written": "unverified-by-tooling",
                                             "confidence": 0.94, "judgment": "handoff_field_value"}])
    rows = doc.data.get("judged")
    check_eq("the repair is a row of the form itself", len(rows or []), 1)
    check_eq("with the word the role wrote", rows[0]["as_written"], "unverified-by-tooling")
    check_eq("and the value the judge chose", rows[0]["value"], "unverified")


def a_row_the_judge_can_answer_from_its_own_contents() -> None:
    """J5: the runner's manual observation against the Then the case quoted.

    `result_observation_matches_then` was in the registry, calibrated, and asked ZERO times: it had
    no call site anywhere, and without it `inconclusive` was invented in the middle of
    TP1-13797. The judge answers `true` or `false` from the row itself; it cannot answer
    `inconclusive` and does not try - an undecided answer leaves the field to the role.
    """
    import handoff_check

    form = ("contract: s6-runner-to-analyst\n"
            "stage: S6\n"
            "manual_observations:\n"
            "  - case: TC-4\n"
            "    then: \"the canvas position equals the baseline (x=800, y=300)\"\n"
            "    observed: \"x=1082.0, y=175.0\"\n"
            "    result: <passed|failed|inconclusive|manual_skipped>\n")

    class FakeJudge:
        def __init__(self, answer):
            self.answer, self.asked = answer, []

        def active(self, *a, **k):
            return True

        def ask(self, state, questions, **kw):
            self.asked.append((state, questions))
            return {"status": "ok", "advisory": False, "answers": {"q": self.answer}}

    saved = handoff_check.judge
    try:
        fake = FakeJudge({"value": False, "decided": True, "confidence": 0.98})
        handoff_check.judge = fake
        doc = handoff.parse(form)
        got = handoff_check._ask_judge_row("manual_observations[].result",
                                          "manual_observations[0].result", doc, "QA-1")
        check_eq("a Then the observation does not satisfy is `failed`", (got or {}).get("value"),
                 "failed")
        check_eq("and the question asked is the registered one", (got or {}).get("judgment"),
                 "result_observation_matches_then")
        state = fake.asked[0][0]
        check_eq("the judge is given the row's own two fields", sorted(state), ["observed", "then"])
        check_in("as the role wrote them", "1082.0", state["observed"])

        handoff_check.judge = FakeJudge({"value": True, "decided": True, "confidence": 0.99})
        got = handoff_check._ask_judge_row("manual_observations[].result",
                                           "manual_observations[0].result",
                                           handoff.parse(form), "QA-1")
        check_eq("an observation that satisfies its Then is `passed`", (got or {}).get("value"),
                 "passed")

        handoff_check.judge = FakeJudge({"value": None, "decided": False, "confidence": 0.5})
        check_eq("an undecided answer fills nothing - inconclusive stays the role's word",
                 handoff_check._ask_judge_row("manual_observations[].result",
                                              "manual_observations[0].result",
                                              handoff.parse(form), "QA-1"), None)

        handoff_check.judge = FakeJudge({"value": True, "decided": True, "confidence": 0.99})
        half = form.replace('    observed: "x=1082.0, y=175.0"', "    observed: <what was seen>")
        check_eq("and a row whose own input the role has not written is never asked about",
                 handoff_check._ask_judge_row("manual_observations[].result",
                                              "manual_observations[0].result",
                                              handoff.parse(half), "QA-1"), None)
    finally:
        handoff_check.judge = saved


def a_tooling_finding_is_not_a_round_for_the_author() -> None:
    """Nine of twelve findings on TP1-13797 said `cause: tooling` and went back anyway."""
    import handoff_check
    form = ("contract: s5-critic-to-automator\n"
            "findings:\n"
            "  - id: F-7\n"
            "    cause: tooling\n"
            "    problem: the probe tool refuses this shape\n")
    doc = handoff.parse(form)
    problems, _ = handoff_check.check_findings(doc, "s5-critic-to-automator", "QA-9", False)
    check_eq("a tooling finding with no tooling_findings row is refused", len(problems), 1)
    check_in("and the refusal says what to do with it instead", "tooling_findings", problems[0].text)
    check_in("and where the instance goes", "unverified", problems[0].text)
    doc = handoff.parse(form + "tooling_findings:\n  - id: F-7\n    tool: probe_by_code.py\n")
    problems, _ = handoff_check.check_findings(doc, "s5-critic-to-automator", "QA-9", False)
    check_eq("named as the factory's own, it passes", problems, [])
    doc = handoff.parse("contract: s7-analyst-to-automator\nfindings:\n"
                        "  - id: F-1\n    cause: test_defect\n")
    problems, _ = handoff_check.check_findings(doc, "s7-analyst-to-automator", "QA-9", False)
    check_eq("a cause the author can act on is left alone", problems, [])


def the_diff_counts_read_the_production_rule() -> None:
    """The S1 count `implementation.diff.production_files` is the production rule over the paths of the diff (K-A4). The S2
    per-file rows that used to show those files left with grounding/1 G1-16: the account of the hunks is the S3 table."""
    root = Path(tempfile.mkdtemp(prefix="qa-handoff-"))
    try:
        art = root / "artifacts" / "QA-4"
        (art / "work").mkdir(parents=True)
        # B-407 A (K-A4): the extended fixture. `contest_service.py` and `latest_report.py` carry `test_` INSIDE a word: the
        # old filter dropped them from the count; `backend/Tests/XTests.cs` (fixture shape of test_red_sandbox_reports) and
        # `test-harness/` are tests; `.md` is not production, and CODE under `Docs/` is (G1-1, L-2 F-1: `Docs/guide.py` was lost).
        (art / "work" / "impl-diff.txt").write_text(
            "diff --git a/src/app/webhook.py b/src/app/webhook.py\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/tests/test_webhook.py b/tests/test_webhook.py\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/src/app/filters.py b/src/app/filters.py\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/src/app/contest_service.py b/src/app/contest_service.py\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/src/app/latest_report.py b/src/app/latest_report.py\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/backend/Tests/XTests.cs b/backend/Tests/XTests.cs\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/test-harness/conftest.py b/test-harness/conftest.py\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/Docs/guide.py b/Docs/guide.py\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/README.md b/README.md\n@@ -1 +1 @@\n-a\n+b\n"
            # F2 (critic t-557): names the widened recognizers must NOT drop - they were rows before - and a classic one
            "diff --git a/src/main/java/UserSpecs.java b/src/main/java/UserSpecs.java\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/src/ABTest.java b/src/ABTest.java\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/api/spec/openapi.py b/api/spec/openapi.py\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/__tests__/a.test.tsx b/__tests__/a.test.tsx\n@@ -1 +1 @@\n-a\n+b\n",
            encoding="utf-8")
        # K-A4: exactly these production files, in the diff's order - a name that merely CONTAINS `test_` is a production
        # file. The recogniser is called on the 13 paths directly (G1-7, t-990 T7): under test is the production rule, not the
        # reader of the diff.
        import handoff_check as H
        import hooklib
        with hooklib.selftest_root_restored():
            hooklib.pin_project_root(root)
            art_view = H.Artifacts(art)
            rows = H._production_files(
                ["src/app/webhook.py", "tests/test_webhook.py", "src/app/filters.py", "src/app/contest_service.py",
                 "src/app/latest_report.py", "backend/Tests/XTests.cs", "test-harness/conftest.py", "Docs/guide.py", "README.md",
                 "src/main/java/UserSpecs.java", "src/ABTest.java", "api/spec/openapi.py", "__tests__/a.test.tsx"],
                art_view.config, art_view)
            check_eq("K-A4 / F2 / G1-1: the production files are webhook, filters, contest_service, latest_report, Docs/guide.py (CODE "
                     "under a docs folder is production: L-2 F-1, it was a lost row) and the three names a widened recognizer must "
                     "not drop (UserSpecs.java, ABTest.java, api/spec/openapi.py); the mutation 'drop the agree rule' turns the "
                     "last three into lost rows: killed here",
                     rows, ["src/app/webhook.py", "src/app/filters.py", "src/app/contest_service.py", "src/app/latest_report.py",
                            "Docs/guide.py", "src/main/java/UserSpecs.java", "src/ABTest.java", "api/spec/openapi.py"])
            check_eq("K-A4: and the count the contract derives is the same eight of thirteen files",
                     (H.DERIVERS["implementation.diff.production_files"](art_view, None)[0],
                      H.DERIVERS["implementation.diff.files"](art_view, None)[0]), (8, 13))
    finally:
        cleanup(root)


S2_FORM = "s2-tester-to-strategist"
S2_COUNT = "inputs_read[0].production_files_accounted_for"
S2_CLAIM = "claims.every_production_file_reaches_a_requirement_or_is_named_not_requirement_bearing"


def an_exited_s2_key_is_read_in_any_shape() -> None:
    """E5, E12 (G1-16): the family `diff_accounting` (the section, its count, its claim) is no field of the S2 form any more,
    so a key of it in ANY shape is read, never refused and never rewritten by `--fix` (the rule 'not in the template is no
    refusal' is now the only guarantee a saved form still passes). Every call really fixes something OUTSIDE the family (the
    bundle's version is blank in every shape and `work/context-bundle.json` exists), so the comparison runs after a rewrite
    of the form, never a text against itself."""
    import handoff_check as H
    import hooklib
    untouched = (FIXTURES / "s2-handoff-13877" / "work" / "handoffs" / "S2-qa-requirements-tester-1.yaml").read_text(encoding="utf-8")
    check_eq("T-a the fixture holds the one bundle version the pin blanks (the edit hits)", untouched.count("    version: ba3519394db5d85e\n"), 1)
    saved = untouched.replace("    version: ba3519394db5d85e\n", "    version: <the bundle revision or hash>\n")
    section = re.search(r"^diff_accounting:.*?(?=^\S)", saved, re.M | re.S)
    check("T-a the fixture holds the saved section (the pin edits what is there)", bool(section), saved[:80])
    old = section.group(0)
    count_line = re.search(r"^ +production_files_accounted_for:.*$", saved, re.M).group(0)
    claim_line = re.search(r"^ +every_production_file_reaches_a_requirement_or_is_named_not_requirement_bearing:.*$", saved, re.M).group(0)
    forms = {
        "the saved form": saved,
        "a CRLF copy": saved.replace("\n", "\r\n"),
        "a scalar section": saved.replace(old, "diff_accounting: none\n"),
        "an empty list": saved.replace(old, "diff_accounting: []\n"),
        "a map": saved.replace(old, "diff_accounting:\n  file: src/a.py\n  requirements: R-1\n"),
        "a row with an extra nested key": saved.replace(old, "diff_accounting:\n  - file: src/a.py\n    requirements: R-1\n"
                                                               "    why:\n      deeper: 1\n"),
        "a blank count": saved.replace(count_line, count_line.split(":")[0] + ": <n of m>"),
        "a claim that is not a boolean": saved.replace(claim_line, claim_line.split(":")[0] + ": maybe"),
    }

    def family(text: str) -> list:
        lines, inside = [], False
        for line in text.splitlines():
            inside = line.startswith("diff_accounting") or (inside and line[:1].isspace())
            if inside or "production_files_accounted_for" in line or "every_production_file_" in line:
                lines.append(line)
        return lines

    root = Path(tempfile.mkdtemp(prefix="qa-handoff-exit-"))
    try:
        art = root / "artifacts" / "QA-4"
        (art / "work").mkdir(parents=True)
        (art / "work" / "context-bundle.json").write_text('{"revision": "r1"}', encoding="utf-8")
        with hooklib.selftest_root_restored():
            hooklib.pin_project_root(root)
            view = H.Artifacts(art)
            for label, text in forms.items():
                doc, fixed, problems, _judged, derived = H.check(handoff.parse(text), S2_FORM, view, fix=True, use_judge=False)
                paths = [p.path for p in problems]
                check_in(f"T-a {label} (same call): --fix did fix a field outside the family, so the line comparison below follows "
                         "a rewrite of the form", "inputs_read[1].version", " ".join(fixed))
                check_not_in(f"T-a {label}: and the blank version is no longer a blank in the rewritten form",
                             "<the bundle revision or hash>", doc.text())
                check_eq(f"T-a {label}: no refusal on the family's paths", [p for p in paths if p.startswith("diff_accounting") or p in (S2_COUNT, S2_CLAIM)], [])
                check_eq(f"T-a {label}: --fix leaves the line content of the family as it was (a CRLF copy is compared by lines, "
                         "not by bytes: the writer normalises line ends)", family(doc.text()), family(text))
                check_not_in(f"T-a {label}: and says nothing of rows", "diff_accounting", " ".join(fixed) + " ".join(d["field"] for d in derived))
            doc, fixed, problems, _judged, derived = H.check(handoff.parse(untouched), S2_FORM, view, fix=True, use_judge=False)
            check_eq("T-a negative control: a saved form with nothing to fix gets no fix and the same text under --fix",
                     (fixed, doc.text() == untouched), ([], True))
            blank = saved.replace("  verdict: ok", "  verdict: <one of vocabulary.header_verdicts>")
            check_in("T-a control (same call): a blank OUTSIDE the family is refused, so the calls above do see refusals", "header.verdict",
                     [p.path for p in H.check(handoff.parse(blank), S2_FORM, view, fix=True, use_judge=False)[2]])
    finally:
        cleanup(root)


def a_section_owed_only_under_a_header_value_has_an_empty_outcome_otherwise() -> None:
    """t-1765 G2/G3 (AR-23, AR-28, AR-19): the three critic forms (S4, S2, S3) owe `stage_acceptance` and `questions` only when
    `header.verdict` is `concerns` (each form's own `required_when:`). An `ok` review leaves both as the form has them and is not
    refused for it; a `concerns` review, or a form whose verdict is missing, is refused for them; a filled block is still checked."""
    import handoff_check as H
    import hooklib
    forms = ("s4-case-critic-to-designer", "s2-stage-critic-to-tester", "s3-stage-critic-to-strategist")
    owed = ("stage_acceptance", "questions")

    def owed_problems(contract: str, text: str, view) -> list:
        got = H.check(handoff.parse(text), contract, view, fix=False, use_judge=False)[2]
        return sorted({p.path.split("[")[0].split(".")[0] for p in got} & set(owed))

    root = Path(tempfile.mkdtemp(prefix="qa-handoff-when-"))
    try:
        art = root / "artifacts" / "QA-4"
        (art / "work").mkdir(parents=True)
        with hooklib.selftest_root_restored():
            hooklib.pin_project_root(root)
            view = H.Artifacts(art)
            for contract in forms:
                template = (CONTRACTS / f"{contract}.yaml").read_text(encoding="utf-8")

                def with_verdict(word: str) -> str:
                    return template.replace("verdict: <one of vocabulary.header_verdicts>", f"verdict: {word}", 1)

                check_in(f"G2 {contract} control: the edit hit, the verdict is written", "verdict: ok", with_verdict("ok"))
                check_eq(f"G2 {contract} ok: the two blocks left as the form has them are not refused",
                         owed_problems(contract, with_verdict("ok"), view), [])
                check_eq(f"G2 {contract} concerns: the same blocks left blank ARE refused (same call, same form)",
                         owed_problems(contract, with_verdict("concerns"), view), sorted(owed))
                check_eq(f"G2 {contract} verdict missing: required as before (AR-28)", owed_problems(contract, template, view), sorted(owed))
                check_eq(f"G2 {contract} halt: not a concern, so not owed", owed_problems(contract, with_verdict("halt"), view), [])
                filled = with_verdict("ok").replace("failure_class: <spec|capability|data|tooling>", "failure_class: bogus", 1)
                check_in(f"G2 {contract} ok with a block FILLED: it is checked as before (a word outside the list is refused)",
                         "stage_acceptance.failure_class",
                         [p.path for p in H.check(handoff.parse(filled), contract, view, fix=False, use_judge=False)[2]])
                check_in(f"G2 {contract} control: the other blanks are refused on ok too",
                         "review.outcome" if contract == forms[0] else "header.window",
                         [p.path for p in H.check(handoff.parse(with_verdict("ok")), contract, view, fix=False, use_judge=False)[2]])
        check_eq("G2 pure reader: a contract with no block relaxes nothing",
                 handoff.relaxed_sections("s1-scout-to-tester", "ok"), set())
    finally:
        cleanup(root)


def the_s2_field_and_the_s3_gate_never_live_together() -> None:
    """J4 (G1-16, t-1018 F-5 (a)): the account of the hunks has one carrier at a time. Once the S3 form carries the grounding
    table, the S2 form carries neither the section nor its count (a field coming back beside a live gate is the window
    G1-16 exists to close)."""
    s2, s3 = handoff.sections(S2_FORM), handoff.sections("s3-strategist-to-designer")
    raw = (CONTRACTS / f"{S2_FORM}.yaml").read_text(encoding="utf-8")
    check("T-b control: both forms are read (S2 still holds its register, S3 holds sections)", "scope" in s2 and bool(s3), str(sorted(s3)[:3]))
    together = "grounding" in s3 and ("diff_accounting" in s2 or "production_files_accounted_for" in raw)
    check_eq("T-b the S3 grounding section and the S2 accounting field are never both in the contracts", together, False)


def no_form_text_claims_a_count_check_that_does_not_run() -> None:
    """FR-37 (G1-16): the words about a gate that no longer runs left with the field. S2: 'the exit gate checks the sum' (this
    node's: the sentence lived in the S2 block it deletes). S1: 'the S2 exit gate compares the numbers' - nothing compares
    `<read> of <handed>`, the role writes it and nobody reads it back. The S1 half is pinned here, with the S1 form it reads
    (G1-10, t-992 site 7: the pin stays in this file)."""
    raw = (CONTRACTS / f"{S2_FORM}.yaml").read_text(encoding="utf-8")
    s1_raw = (CONTRACTS / "s1-scout-to-tester.yaml").read_text(encoding="utf-8")
    check("phrases control: both forms are read (the S2 form holds its register, the S1 form its duties)",
          "scope:" in raw and "expected_of_the_receiver:" in s1_raw, raw[:60])
    check_eq("T-b2 no form text claims a count check that does not run",
             [(name, said) for name, text, said in (("S2", raw, "exit gate checks the sum"), ("S1", s1_raw, "exit gate compares the numbers"))
              if said in text], [])


def the_diff_counts_read_every_recorded_diff() -> None:
    """G1-1 (E8, spec 3.5): `implementation.diff.files|hunks|production_files` read ALL `work/impl-diff*.txt` through the one
    index. A diff nobody could read, or a combined diff, leaves the field to the role (None) instead of a smaller number."""
    import handoff_check as H
    import hooklib

    def counts(files: dict, folders: tuple = ()) -> dict:
        root = Path(tempfile.mkdtemp(prefix="qa-handoff-counts-"))
        try:
            work = root / "artifacts" / "QA-5" / "work"
            work.mkdir(parents=True)
            for name, text in files.items():
                (work / name).write_text(text, encoding="utf-8")
            for name in folders:
                (work / name).mkdir()
            with hooklib.selftest_root_restored():
                hooklib.pin_project_root(root)
                view = H.Artifacts(root / "artifacts" / "QA-5")
                return {key: H.DERIVERS[f"implementation.diff.{key}"](view, None) for key in ("files", "hunks", "production_files")}
        finally:
            cleanup(root)

    def section(path: str, hunks: int = 1) -> str:
        return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n" + "@@ -1 +1 @@\n-a\n+b\n" * hunks

    got = counts({"impl-diff-api.txt": section("src/a.py", 2) + section("tests/test_a.py"),
                  "impl-diff-ui.txt": section("ui/Page.tsx") + "diff --git a/logo.png b/logo.png\nBinary files a/logo.png and b/logo.png differ\n"})
    check_eq("two diffs: files are the sections of both (the binary one included), production the rows of both",
             (got["files"], got["production_files"]), ((4, "impl-diff-api.txt, impl-diff-ui.txt"), (3, "impl-diff-api.txt, impl-diff-ui.txt")))
    check_eq("... and hunks are the REAL hunks (a pseudo-hunk is not one)", got["hunks"], (4, "impl-diff-api.txt, impl-diff-ui.txt"))
    check_eq("no diff, an empty diff, a diff of blanks: the field stays the role's (None)",
             [counts(f)["files"] for f in ({}, {"impl-diff.txt": ""}, {"impl-diff.txt": "\n \n"})], [None, None, None])
    merged = counts({"impl-diff.txt": section("src/a.py") + "diff --cc f.py\n@@@ -1 -1 +1 @@@\n+x\n"})
    check_eq("a combined diff in the set: the files are counted, the hunks are None (never a smaller number)",
             (merged["files"][0], merged["hunks"][0]), (2, None))
    broken = counts({"impl-diff.txt": section("src/a.py")}, folders=("impl-diff-bad.txt",))
    check_eq("an unreadable diff in the set: nothing is counted from the rest as if it were all (None everywhere)",
             [broken[key][0] for key in ("files", "hunks", "production_files")], [None, None, None])
    check_eq("a lone diff.txt reads as before", counts({"impl-diff.txt": section("src/a.py")})["files"], (1, "impl-diff.txt"))


def reference_shaped_story(prefix: str, config_extra: dict, manifest: dict):
    """The shape of the reference project: the project `ws/th` sits beside the application checkout `ws/testproject1`, `app_root`
    points up to it, and the story's context manifest names the implementation repository. Returns (ws, task root).
    No diff is written: the production rule is asked over a list of paths, and nothing here reads `work/impl-diff.txt`."""
    ws = Path(tempfile.mkdtemp(prefix=prefix)).resolve()
    for folder in ("th/qa-factory/artifacts/QA-9/work", "testproject1/src", "testproject1/tests/x", "testproject1/legacy_checks", "other/tests"):
        (ws / folder).mkdir(parents=True)
    config = {"schema_version": 1, "app_root": "..", "tests_root": ".", "protected_app_paths": ["testproject1"]}
    config.update(config_extra)
    (ws / "th/qa-factory/config.json").write_text(json.dumps(config), encoding="utf-8")
    task = ws / "th/qa-factory/artifacts/QA-9"
    (task / "work" / "context-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return ws, task


def the_production_rule_reads_the_projects_word_from_the_implementation_checkout() -> None:
    """B-407 A5 (K-A4b, E-A6, E-A7, amendments 1 and 2): the diff's paths are relative to the implementation repository, so
    the project's word is matched against the CHECKOUT they came from; a carrier that names a folder (`run.levels`) hides
    the usual names in the verdict and excludes a file only when the file's own name or folder says test as well; with no
    checkout the config is not consulted at all."""
    import handoff_check as H
    import hooklib
    mut = ["tests/x/test_a.py", "legacy_checks/a.py", "src/contest_service.py", "src/latest_report.py", "src/attestation/x.py",
           "src/testing/helpers.py", "src/AUDIT.java", "src/Contest.cs", "src/protest_utils.py", "src/pytest_plugin.py"]
    levels = {"run": {"levels": {"unit": ["../testproject1/tests/**"], "legacy": ["../testproject1/legacy_checks/**"]}}}
    adversarial = ["src/contest_service.py", "src/latest_report.py", "src/attestation/x.py", "src/testing/helpers.py",
                   "src/AUDIT.java", "src/Contest.cs", "src/protest_utils.py", "src/pytest_plugin.py"]

    def rows(prefix: str, config_extra: dict, manifest: dict, files=mut) -> list:
        ws, task = reference_shaped_story(prefix, config_extra, manifest)
        try:
            with hooklib.selftest_root_restored():
                hooklib.pin_project_root(ws / "th")
                view = H.Artifacts(task)
                return H._production_files(files, view.config, view)
        finally:
            cleanup(ws)

    one = {"implementation": {"repo_id": "testproject1", "local_path": "C:/somewhere/else/testproject1", "source_sha": "abc"}}
    impl = {"implementation_repos": [{"repo_id": "testproject1", "local_path": "../testproject1"}]}
    # K-A4b: the reference project's shape - run.levels over <impl>/tests/**, base resolved: `tests/x/test_a.py` is excluded,
    # and the files only `run.levels` names (legacy_checks/a.py, no usual name) stay rows
    got = rows("qa-ho-ref-", dict(levels, **impl), one)
    check_eq("K-A4b: the impl repo under app_root, a run.levels glob over <impl>/tests/**, base resolved: tests/x/test_a.py is "
             "excluded (the mutation 'handoff accepts run.levels only through the verdict' turns it into a row: killed here)",
             "tests/x/test_a.py" in got, False)
    check_eq("K-A4 / E-A7: a file matched ONLY by run.levels (legacy_checks/a.py) stays a row, and so does every adversarial name",
             [f for f in ["legacy_checks/a.py"] + adversarial if f not in got], [])
    # amendment 2: the checkout comes from the manifest's repo_id through the PROJECT's config; the manifest's own absolute
    # local_path (some other machine) is a hint and never the base
    check_eq("amendment 2: `implementations[]` with one entry reads the same as the single `implementation`",
             rows("qa-ho-list-", dict(levels, **impl), {"implementations": [one["implementation"]]}), got)
    check_eq("amendment 2: `code_repos[].name -> path` is the second door (relative to the project root)",
             rows("qa-ho-code-", dict(levels, code_repos=[{"name": "testproject1", "path": "../testproject1"}]), one), got)
    check_eq("F3: a manifest that carries `repo` only (the 13797 shape) reaches the checkout: a test_locations word that only "
             "the base can match excludes the file",
             "legacy_checks/a.py" in rows("qa-ho-repo2-", dict({"test_locations": ["testproject1/legacy_checks/"]}, **impl),
                                          {"implementation": {"repo": "testproject1"}}), False)
    # E-A6: a base the code could not establish gives only the usual names: an extra row, never a lost one
    place = {"test_locations": ["testproject1/legacy_checks/"]}
    resolved = rows("qa-ho-word-", dict(place, **impl), one)
    check_eq("the project's test_locations word excludes legacy_checks/a.py once the checkout is known; with the project's word "
             "given, only that word answers inside application code (step 3), so a usual name outside it is a row, not a loss",
             ("legacy_checks/a.py" in resolved, "tests/x/test_a.py" in resolved), (False, True))
    for label, config_extra, manifest in (
            ("no entry in the manifest", dict(place, **impl), {}),
            ("two entries (ambiguous)", dict(place, **impl),
             {"implementations": [one["implementation"], {"repo_id": "other", "source_sha": "x"}]}),
            ("a repo_id the config does not name", dict(place, **impl), {"implementation": {"repo_id": "unknown"}}),
            ("no repo_id (only the manifest's own local_path)", dict(place, **impl),
             {"implementation": {"local_path": str(Path(tempfile.gettempdir()))}}),
            ("a checkout that is not on this machine", dict(place, implementation_repos=[{"repo_id": "testproject1", "local_path": "../missing"}]), one)):
        got_blind = rows("qa-ho-blind-", config_extra, manifest)
        check_eq(f"E-A6 ({label}): the config is not consulted: legacy_checks/a.py is a row again, tests/x/test_a.py is still "
                 "excluded by its usual name", ("legacy_checks/a.py" in got_blind, "tests/x/test_a.py" in got_blind), (True, False))
    # amendment 1 (the stated edge): `roots.test` / `tests_root` may name a folder that is not wholly tests
    for key, value in (("tests_root", "../testproject1/legacy_checks"), ("profiles", [{"profile_id": "p", "roots": {"test": "../testproject1/legacy_checks"}}])):
        got_root = rows("qa-ho-roots-", dict({key: value}, **impl), one)
        check_eq(f"amendment 1: {key} naming a folder: its files are rows unless their own name says test",
                 ("legacy_checks/a.py" in got_root, "tests/x/test_a.py" in got_root), (True, False))
    # E-A7 without any config at all (the world of the old fixture)
    check_eq("E-A7: with no config every adversarial name is a row and the plain test file is not",
             [f for f in adversarial if f not in rows("qa-ho-none-", {}, {})] + [f for f in ["tests/x/test_a.py"]
                                                                              if f in rows("qa-ho-none2-", {}, {})], [])
    # the one reader of the manifest's implementation shape
    check_eq("implementation_entries: the list, else the single object, else nothing",
             [H.implementation_entries(m) for m in ({}, None, {"implementations": []}, {"implementations": [{"a": 1}, {"b": 2}]},
                                                    {"implementations": [], "implementation": {"c": 3}}, {"implementation": [1]},
                                                    {"implementation": {"c": 3}})],
             [[], [], [], [{"a": 1}, {"b": 2}], [{"c": 3}], [], [{"c": 3}]])


def a_value_written_into_a_row_keeps_the_row() -> None:
    """The conductor's `fill` answer writes into a row - and a row is a `- ` line.

    Writing `  id: x` over `  - id: <fill>` dissolves the item: every field under it lands
    somewhere else and the next check says the row's own fields do not exist.
    """
    doc = handoff.parse("contract: c\nscope:\n  - id: <the id>\n    state: <a|b>\n")
    handoff.set_value(doc, "scope[0].id", "test_one")
    doc = handoff.parse(doc.text())
    check_eq("the id is written", doc.get("scope[0].id"), "test_one")
    check_eq("and the row still carries its other fields", doc.get("scope[0].state"), "<a|b>")
    check_in("the item marker survives", "- id: test_one", doc.text())
    handoff.set_value(doc, "scope[0].state", "a")
    doc = handoff.parse(doc.text())
    check_eq("which is what lets the next field be written at all", doc.get("scope[0].state"), "a")


def the_same_fact_derives_under_the_same_name():
    """A fact keeps its name wherever a contract puts it, and code fills it there.

    TP1-13797, 26.09: a form carried 1,422 fields and code filled six. The designer typed
    `case_version: "pending case_versions.py --all (no Bash available to this role)"` into a field
    that `story-case-links.json` answers — the role has no Bash and could not run the script its
    own field names, so it wrote prose into a record. `id`, `path`, `case_version`, `requirements`,
    `plan_row` are facts; `reason`, `state`, `what` are the role's and stay the role's.
    """
    import handoff_check as H
    root = temp_dir("qa-handoff-leaf-")
    try:
        cases = root / "work" / "test-cases" / "area"
        cases.mkdir(parents=True, exist_ok=True)
        (cases / "TC-003.md").write_text(
            "\n".join(["---", "id: TC-003", "covers: [R-3, R-9]", "plan_row: TS-3", "---",
                       "", "Given x", ""]),
            encoding="utf-8")

        class Art:
            def __init__(self, root):
                self.root = root

            def text(self, rel):
                path = self.root / rel
                return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""

        art = Art(root)
        check_eq("the requirements come from the case's own `covers`",
                 H._requirements_of(art, None, {"case": "TC-003"})[0], "R-3, R-9")
        # B-405: `covers:` holds REQUIREMENT ids, whose one reader is contract.REQ_ID_RE (`R-n`); the old `[A-Z]+-\d+` read
        # an `AC-1` as one too (a third key variant that was never a ticket key)
        (cases / "TC-004.md").write_text("\n".join(["---", "id: TC-004", "covers: AC-1, R-2", "---", "", "Given x", ""]),
                                         encoding="utf-8")
        (cases / "TC-005.md").write_text("\n".join(["---", "id: TC-005", "covers: [AC-1, TP1-9]", "---", "", "Given x", ""]),
                                         encoding="utf-8")
        check_eq("B-405: `covers: AC-1, R-2` gives R-2 (AC-1 is no requirement id)",
                 H._requirements_of(art, None, {"case": "TC-004"})[0], "R-2")
        check_eq("B-405: a case that covers no R-id derives nothing (the field stays the role's to fill)",
                 H._requirements_of(art, None, {"case": "TC-005"}), None)
        check_eq("the plan row comes from the case's own front matter",
                 H._plan_row_of(art, None, {"case": "TC-003"})[0], "TS-3")
        check_eq("a row that is not a case derives nothing",
                 H._plan_row_of(art, None, {"id": "SRC-1"}), None)
        check("judgement fields have no deriver, on purpose",
              not ({"reason", "state", "what", "origin"} & set(H.BY_LEAF)))
        check_in("and the identity fields do", "case_version", H.BY_LEAF)
    finally:
        cleanup(root)


# --- B-194 piece D: `every_expectation_change_after_red_is_recorded` is a claim code verifies --------
#
# The story below is synthetic: one test that went red (its own junit says so) in attempt r1 and
# passed in attempt g1 on a different code sha - the shape the S5 exit check calls an owed pair.

NEW_CLAIM = "every_expectation_change_after_red_is_recorded"
OLD_CLAIM = "no_test_adjusted_to_the_code"
CLAIM_PATH = f"claims.{NEW_CLAIM}"
VERSION_CLAIM_PATH = "claims.every_instance_names_its_current_case_version"
DISPATCH = "S5-qa-automator-1"
TEST_FN = "test_invalid_filter_is_rejected"
TEST_KEY = "test_filter_mod.TestFilters." + TEST_FN
TEST_CLASS = "tests.test_filter_mod.TestFilters"
FILTER_SOURCE = ('class TestFilters:\n    def test_invalid_filter_is_rejected(self, client):\n'
                 '        """@case TC-500."""\n        assert_that(client.put("bad").status_code, equal_to(400))\n')
CASE_TEXT = "---\nid: TC-500\nstatus: Draft\n---\n## Given\nA filter.\n\n## When\nPut it.\n\n## Then\n1. It is rejected.\n"


def _junit(task: Path, attempt: str, outcome: str) -> dict:
    inner = '<failure message="assert 200 == 400"/>' if outcome == "failed" else ""
    xml = (f'<testsuites><testsuite name="s" tests="1"><testcase classname="{TEST_CLASS}" '
           f'name="{TEST_FN}[P]">{inner}</testcase></testsuite></testsuites>').encode("utf-8")
    relative = f"evidence/runs/{attempt}/report.junit.xml"
    (task / relative).parent.mkdir(parents=True, exist_ok=True)
    (task / relative).write_bytes(xml)
    return {"summary": "", "reporter": "junit-xml", "report_path": relative,
            "report_sha256": hashlib.sha256(xml).hexdigest()}


def _block(task: Path, attempt: str, minute: int, outcome: str, code_sha: str) -> None:
    row = {"instance_id": f"{TEST_FN}[P]", "test_id": f"tests.test_filter_mod.TestFilters::{TEST_FN}[P]",
           "status": outcome, "reason": "", "report_matched": True, "instance_code_sha": code_sha,
           "case_version_links": [{"case_id": "TC-500", "version": "cv_old"}]}
    data = {"schema_version": 2, "block_id": attempt, "attempt_id": attempt,
            "attempt_started_at": f"2026-09-30T05:{minute:02d}:00+00:00", "dispatch_id": DISPATCH,
            "purpose": "repair_verify", "source_fingerprint": {"test_content_sha": "F"},
            "execution_status": "passed" if outcome == "passed" else "failed",
            "results": [row], "evidence": [_junit(task, attempt, outcome)]}
    (task / "work" / "run-blocks" / f"20260930T05{minute:02d}00000000Z-{attempt}.json").write_text(
        json.dumps(data), encoding="utf-8")


def _story(root: Path, ticket: str = "QA-600", runs: bool = True) -> Path:
    """A story with (runs=True) one red-then-green pair on a changed code sha, or with no run
    block at all."""
    task = root / "qa-factory" / "artifacts" / ticket
    for folder in ("work/test-cases", "work/run-blocks", "work/handoffs", "state", "evidence/runs"):
        (task / folder).mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "test_filter_mod.py").write_text(FILTER_SOURCE, encoding="utf-8")
    (task / "work" / "test-cases" / "TC-500.md").write_text(CASE_TEXT, encoding="utf-8")
    manifest = {"tests": [{"case": "TC-500", "file": "tests/test_filter_mod.py",
                           "instance_id": f"{TEST_FN}[P]", "test_function": TEST_FN,
                           "covers": ["TC-500"], "status": "green",
                           "case_version_links": [{"case_id": "TC-500", "version": "cv_old"}]}]}
    (task / "work" / "automation-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (task / "state" / "story-case-links.json").write_text(
        json.dumps({"links": [{"case_id": "TC-500", "version": "cv_old"}]}), encoding="utf-8")
    if runs:
        _block(task, "r1", 0, "failed", "code-before")
        _block(task, "g1", 10, "passed", "code-after")
    return task


def _form(task: Path, claims: dict, legacy: bool = False) -> Path:
    """The S5 handover form, written by `handoff_init.py` from the shipped contract, with the
    claims filled. `legacy` rewrites the new claim's line into the OLD key, the way a form
    initialised before this change looks."""
    done = run_script("handoff_init.py", "--task", task.name, "--stage", "S5", "--role", "qa-automator",
                      "--to", "qa-code-critic", "--dispatch", DISPATCH, "--task-root", str(task))
    form = task / "work" / "handoffs" / f"{DISPATCH}.yaml"
    if not form.is_file():
        check("the form was written", False, done.stdout + done.stderr)
    text = form.read_text(encoding="utf-8")
    if legacy:
        text = re.sub(rf"(?m)^  {NEW_CLAIM}: .*$", f"  {OLD_CLAIM}: <true|false>          # a failure by "
                      "requirement is handed over RED", text)
    doc = handoff.parse(text)
    # a claim the test does not name is answered honestly `false`, which code never verifies, so
    # only the claims under test can produce a problem
    for name in list(doc.data.get("claims") or {}):
        handoff.set_value(doc, f"claims.{name}", claims.get(name, False))
        doc = handoff.parse(doc.text())
    form.write_text(doc.text(), encoding="utf-8")
    return form


def _claim_problems(task: Path, claims: dict, legacy: bool = False, art=None) -> tuple:
    """`(problems of claims.*, the Artifacts object)` from an in-process check of a filled form."""
    import handoff_check as H
    form = _form(task, claims, legacy)
    art = art or H.Artifacts(task, dispatch=DISPATCH)
    doc = handoff.parse(form.read_text(encoding="utf-8"))
    _doc, _fixed, problems, _judged, _derived = H.check(doc, "s5-automator-to-critic", art,
                                                        fix=False, task=task.name, use_judge=False)
    return [p for p in problems if p.path.startswith("claims.")], art


def _tree(task: Path, skip: str = "") -> dict:
    return {p.relative_to(task).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(task.rglob("*")) if p.is_file()
            and not (skip and p.relative_to(task).as_posix().startswith(skip))}


def the_claim_is_replaced_and_the_comment_is_true() -> None:
    import handoff_check as H
    text = (CONTRACTS / "s5-automator-to-critic.yaml").read_text(encoding="utf-8")
    spec = handoff.spec("s5-automator-to-critic")
    check("edge 1: the new key is in the form and the old key is gone",
          NEW_CLAIM in text and OLD_CLAIM not in text)
    check_eq("edge 1: the new key is a boolean the role fills", spec[CLAIM_PATH].kind, "boolean")
    line = next(l for l in text.splitlines() if l.strip().startswith(NEW_CLAIM))
    check_in("edge 1: its trailing comment says in plain words what it means",
             "expectation_changes[]", line.split("#", 1)[1] if "#" in line else "")
    check_not_in("edge 1: the header no longer says every key is checked by code",
                 "Each key is checked by code", text)
    header = text.split("claims:")[0].rsplit("# What the automator asserts", 1)[1]
    check_in("edge 1: the header names the keys code verifies today",
             "every_instance_names_its_current_case_version", header)
    check_in("edge 1: and the new one", NEW_CLAIM, header)
    check_in("edge 1: and says the others are the role's own statement", "the role's own statement", header)
    check_in("edge 2: the verifier is registered in CLAIMS", NEW_CLAIM, list(H.CLAIMS))
    for key in ("every_case_in_scope_has_an_instance", "every_instance_ran", "manifest_matches_the_tests"):
        check_not_in(f"non-goal: {key} still has no verifier", key, list(H.CLAIMS))


def an_owed_pair_without_a_record_makes_the_claim_false() -> None:
    import handoff_check as H
    import s5_precheck as S5
    root = temp_project("qa-handoff-owed-")
    try:
        task = _story(root)
        pairs = S5.expectation_changes(task, ["TC-500"], json.loads(
            (task / "work" / "automation-manifest.json").read_text(encoding="utf-8")))["pairs"]
        check_eq("the fixture really holds one owed, unrecorded pair (the detector's own answer)",
                 [(p["function"], p["owed"], p["record"]) for p in pairs], [(TEST_KEY, True, None)])
        before = _tree(task, skip="work/handoffs/")
        problems, art = _claim_problems(task, {NEW_CLAIM: True})
        check_eq("edge 5: a claim of `true` the detector contradicts is one problem of that claim",
                 [p.path for p in problems], [CLAIM_PATH])
        text = problems[0].text if problems else ""
        check_in("edge 2: it says the form claims this is true and it is not (the existing mismatch text)",
                 "the form claims this is true, and it is not:", text)
        check_in("edge 2: it names the function", TEST_KEY, text)
        check_in("edge 2: and its red attempt", "r1", text)
        check_in("edge 2: and its green attempt", "g1", text)
        check_in("edge 2: the first door is the exact manifest_put.py --fragment row",
                 "manifest_put.py --task QA-600 --fragment '", text)
        check_in("edge 2: with the attempts filled in", '"red_attempt": "r1", "green_attempt": "g1"', text)
        check_in("edge 2: the second door is restoring the value and handing the test RED",
                 "restore that value and hand the test over RED with `contradicts_requirement`", text)
        check_not_in("edge 2: no door names triage.json, which the automator cannot write", "triage.json", text)
        check_eq("edge 2: the fix line of the problem is the form's existing one",
                 problems[0].fix if problems else "", "repair the work, or write false and name it in `unresolved`")
        check_eq("edge 7: the verifier writes nothing into the story (FR-45; the form is the only new file)",
                 _tree(task, skip="work/handoffs/"), before)
        check_eq("edge 3: a verdict was given, so nothing is printed as `no verdict`", art.no_verdict, [])

        # edge 5: an honest `false` is not verified (the existing behaviour), so it is accepted
        problems, _art = _claim_problems(task, {NEW_CLAIM: False})
        check_eq("edge 5: the role wrote `false`: no problem, as for every other claim", problems, [])

        # position invariant: another claim's result and the order of the messages are unchanged
        problems, _art = _claim_problems(task, {"every_instance_names_its_current_case_version": True,
                                                NEW_CLAIM: True})
        check_eq("position: the other claim, holding, adds no message and moves none",
                 [p.path for p in problems], [CLAIM_PATH])
        (task / "state" / "story-case-links.json").write_text(
            json.dumps({"links": [{"case_id": "TC-500", "version": "cv_new"}]}), encoding="utf-8")
        problems, art = _claim_problems(task, {"every_instance_names_its_current_case_version": True,
                                               NEW_CLAIM: True})
        check_eq("position: two false claims come back in the order of the form, the old one first",
                 [p.path for p in problems], [VERSION_CLAIM_PATH, CLAIM_PATH])
        check_eq("position: and the old claim's message is exactly what its own verifier says",
                 problems[0].text if problems else "",
                 "the form claims this is true, and it is not: " + H._claim_instance_versions(art)[1])
    finally:
        cleanup(root)


def a_record_or_a_persons_word_makes_it_hold() -> None:
    import waiver as W
    root = temp_project("qa-handoff-record-")
    try:
        task = _story(root)
        manifest_path = task / "work" / "automation-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["expectation_changes"] = [{"function": TEST_KEY, "red_attempt": "r1", "green_attempt": "g1",
                                            "then_refs": [{"case": "TC-500", "then": 1}],
                                            "what_changed": "400 -> 422", "reason": "the case leaves it open"}]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        problems, art = _claim_problems(task, {NEW_CLAIM: True})
        check_eq("edge 2: a pair with its record in the manifest: the claim holds", problems, [])
        check_eq("and nothing is printed as `no verdict`", art.no_verdict, [])
        # a record for another pair of runs answers nothing
        manifest["expectation_changes"][0]["green_attempt"] = "g9"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        problems, _art = _claim_problems(task, {NEW_CLAIM: True})
        check_eq("a record naming other attempts does not answer the pair", [p.path for p in problems],
                 [CLAIM_PATH])
        # the person's word
        del manifest["expectation_changes"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        pipeline = {"task": "QA-600"}
        W.apply_stage_override(pipeline, "S5", "changed-after-red", "the person accepts the change",
                               W.now_iso())
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        problems, _art = _claim_problems(task, {NEW_CLAIM: True})
        check_eq("edge 2: a pair passed by a person's word: the claim holds", problems, [])
        pipeline["stage_overrides"] = []
        (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        problems, _art = _claim_problems(task, {NEW_CLAIM: True})
        check_eq("and without the word it does not", [p.path for p in problems], [CLAIM_PATH])
    finally:
        cleanup(root)


def an_unmeasured_detector_gives_no_verdict() -> None:
    import handoff_check as H
    import s5_precheck as S5
    root = temp_project("qa-handoff-unmeasured-")
    try:
        task = _story(root, runs=False)
        (task / "work" / "run-blocks" / "broken.json").write_text("{not json", encoding="utf-8")
        art = H.Artifacts(task, dispatch=DISPATCH)
        got = H.CLAIMS[NEW_CLAIM](art)
        check_eq("edge 3: an unreadable run block: the verifier's verdict is None, never True", got[0], None)
        check_in("edge 3: and it gives the detector's reason", "broken.json", got[1])
        problems, art = _claim_problems(task, {NEW_CLAIM: True})
        check_eq("edge 3: the form is not refused for it", problems, [])
        check_eq("edge 3: the reason is recorded as `no verdict` for that claim",
                 [(r["claim"], "broken.json" in r["reason"]) for r in art.no_verdict], [(CLAIM_PATH, True)])
        form = task / "work" / "handoffs" / f"{DISPATCH}.yaml"
        done = run_script("handoff_check.py", "--file", str(form), "--task-root", str(task), "--no-judge")
        check_in("edge 3: the reason is printed by the command", f"no verdict on {CLAIM_PATH}:", done.stdout)
        check_in("edge 3: with the detector's words", "broken.json", done.stdout)
        as_json = json.loads(run_script("handoff_check.py", "--file", str(form), "--task-root", str(task),
                                        "--no-judge", "--json").stdout)
        check_eq("edge 3: and in --json", [r["claim"] for r in as_json["no_verdict"]], [CLAIM_PATH])
        check_eq("edge 3: the claim is not among the problems", [p["path"] for p in as_json["problems"]
                                                              if p["path"] == CLAIM_PATH], [])

        # the call itself fails: no verdict either, with the failure named
        clean = _story(root, ticket="QA-601", runs=False)
        saved = S5.check_expectation_changes

        def boom(*args, **kwargs):
            raise RuntimeError("boom")
        S5.check_expectation_changes = boom
        try:
            got = H.CLAIMS[NEW_CLAIM](H.Artifacts(clean, dispatch=DISPATCH))
        finally:
            S5.check_expectation_changes = saved
        check_eq("edge 3: the detector raises: no verdict", got[0], None)
        check_in("edge 3: and the reason names the failure", "RuntimeError: boom", got[1])
    finally:
        cleanup(root)


def an_owed_pair_beats_an_unmeasured_corner() -> None:
    """D-fork: a pair the detector DID find makes the claim false even when something else could
    not be measured; `no verdict` is for the case where nothing is owed."""
    import handoff_check as H
    root = temp_project("qa-handoff-fork-")
    try:
        task = _story(root, ticket="QA-610")
        (task / "work" / "run-blocks" / "broken.json").write_text("{not json", encoding="utf-8")
        art = H.Artifacts(task, dispatch=DISPATCH)
        got = H.CLAIMS[NEW_CLAIM](art)
        check_eq("D-fork: an owed unrecorded pair AND an unreadable block: the claim is FALSE, not no verdict",
                 got[0], False)
        check_in("D-fork: the pair is named", TEST_KEY, got[1])
        check_in("D-fork: with its way on", "manifest_put.py --task QA-610 --fragment '", got[1])
        check_in("D-fork: and the unmeasured note is added, with the detector's words", "broken.json", got[1])
        check_in("D-fork: saying it is an addition, not the verdict", "could not measure everything either", got[1])
        problems, art = _claim_problems(task, {NEW_CLAIM: True})
        check_eq("D-fork: a form that claims `true` is refused for it, as for any false claim",
                 [p.path for p in problems], [CLAIM_PATH])
        check_eq("D-fork: and no `no verdict` line is recorded for it", art.no_verdict, [])

        # the same story with the pair recorded: nothing is owed, something is unmeasured -> no verdict
        manifest_path = task / "work" / "automation-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["expectation_changes"] = [{"function": TEST_KEY, "red_attempt": "r1", "green_attempt": "g1",
                                            "then_refs": [{"case": "TC-500", "then": 1}],
                                            "what_changed": "400 -> 422", "reason": "the case leaves it open"}]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        got = H.CLAIMS[NEW_CLAIM](H.Artifacts(task, dispatch=DISPATCH))
        check_eq("D-fork: nothing owed (the pair is recorded) and something unmeasured: NO VERDICT",
                 got[0], None)
        check_in("D-fork: with the detector's reason", "broken.json", got[1])
        (task / "work" / "run-blocks" / "broken.json").unlink()
        check_eq("D-fork: and once nothing is unmeasured it holds",
                 H.CLAIMS[NEW_CLAIM](H.Artifacts(task, dispatch=DISPATCH))[0], True)
    finally:
        cleanup(root)


def nothing_to_measure_holds_and_is_never_refused() -> None:
    import handoff_check as H
    root = temp_project("qa-handoff-empty-")
    try:
        empty = _story(root, ticket="QA-602", runs=False)
        got = H.CLAIMS[NEW_CLAIM](H.Artifacts(empty, dispatch=DISPATCH))
        check_eq("edge 4: no run block at all: the claim holds", got[0], True)
        (empty / "work" / "automation-manifest.json").write_text("{}", encoding="utf-8")
        check_eq("edge 4: an empty manifest: it holds", H.CLAIMS[NEW_CLAIM](H.Artifacts(empty))[0], True)
        (empty / "work" / "automation-manifest.json").unlink()
        check_eq("edge 4: no manifest file at all: it holds", H.CLAIMS[NEW_CLAIM](H.Artifacts(empty))[0], True)
        bare = root / "qa-factory" / "artifacts" / "QA-603"
        bare.mkdir(parents=True)
        check_eq("edge 4: a story folder with nothing in it: it holds", H.CLAIMS[NEW_CLAIM](H.Artifacts(bare))[0],
                 True)
        keyless = _story(root, ticket="QA-604", runs=False)
        _block(keyless, "g1", 10, "passed", "code-after")
        got = H.CLAIMS[NEW_CLAIM](H.Artifacts(keyless, dispatch=DISPATCH))
        check("edge 4: a manifest with no expectation_changes key and only a green: it holds, nothing refused",
              got[0] is True and "expectation_changes" not in json.loads(
                  (keyless / "work" / "automation-manifest.json").read_text(encoding="utf-8")), str(got))
        problems, _art = _claim_problems(keyless, {NEW_CLAIM: True})
        check_eq("edge 4: and the form is not refused over the missing key", problems, [])
    finally:
        cleanup(root)


def a_form_initialised_before_this_change_is_not_refused() -> None:
    import handoff_check as H
    root = temp_project("qa-handoff-legacy-")
    try:
        task = _story(root)
        problems, art = _claim_problems(task, {OLD_CLAIM: True}, legacy=True)
        form_text = (task / "work" / "handoffs" / f"{DISPATCH}.yaml").read_text(encoding="utf-8")
        legacy_claims = handoff.parse(form_text).data.get("claims") or {}
        check_eq("edge 6: the legacy form carries the old key, set to true, and not the new one",
                 (legacy_claims.get(OLD_CLAIM), NEW_CLAIM in legacy_claims), (True, False))
        check_eq("edge 6: the old key is never refused, even on a story with an owed pair",
                 [p.path for p in problems], [])
        check_eq("edge 6: and never verified: no verdict is recorded either", art.no_verdict, [])
        check_not_in("edge 6: no verifier is registered under the old key", OLD_CLAIM, list(H.CLAIMS))
        as_json = json.loads(run_script("handoff_check.py", "--file", str(task / "work" / "handoffs"
                                        / f"{DISPATCH}.yaml"), "--task-root", str(task), "--no-judge",
                                        "--json").stdout)
        check_eq("edge 6: the command says nothing about the old key", [p["path"] for p in as_json["problems"]
                                                                        if "claims." in p["path"]], [])
    finally:
        cleanup(root)


def the_detector_runs_once_per_check() -> None:
    import handoff_check as H
    import s5_precheck as S5
    root = temp_project("qa-handoff-once-")
    try:
        task = _story(root)
        calls = []
        saved = S5.expectation_changes

        def counting(*args, **kwargs):
            calls.append(1)
            return saved(*args, **kwargs)
        S5.expectation_changes = counting
        try:
            # two claims of the form and many rows: the detector is still called once
            _claim_problems(task, {"every_instance_names_its_current_case_version": True, NEW_CLAIM: True})
            check_eq("edge 7: one check run calls the detector once", len(calls), 1)
            art = H.Artifacts(task, dispatch=DISPATCH)
            H.CLAIMS[NEW_CLAIM](art)
            H.CLAIMS[NEW_CLAIM](art)
            check_eq("edge 7: and asking twice within one run does not measure twice", len(calls), 2)
            calls.clear()
            _claim_problems(task, {NEW_CLAIM: False})
            check_eq("edge 5: an honest `false` is not verified, so the detector is not called", len(calls), 0)
        finally:
            S5.expectation_changes = saved
    finally:
        cleanup(root)


def _critic_form(root: Path, dispatch: str = "S5-qa-code-critic-1", reason: str = "short and honest",
                 verdict: str = "ok") -> tuple:
    """A critic form filled except for what the test varies: (task root, form path)."""
    art = root / "artifacts" / "QA-9"
    (art / "work").mkdir(parents=True)
    run_script("handoff_init.py", "--task", "QA-9", "--stage", "S5", "--role", "qa-code-critic",
               "--to", "qa-automator", "--dispatch", dispatch, "--task-root", str(art))
    form = art / "work" / "handoffs" / f"{dispatch}.yaml"
    doc = handoff.parse(form.read_text(encoding="utf-8"))
    start = doc.nodes["scope[0].id"].line
    end = max(n.end_line for p, n in doc.nodes.items() if p.startswith("scope[0]"))
    doc.lines = doc.lines[:start] + ["  - id: test_one", "    state: approved",
                                     f"    reason: {json.dumps(reason, ensure_ascii=False)}"] + doc.lines[end + 1:]
    doc = handoff.parse(doc.text())
    for path, value in (("header.verdict", verdict), ("review.outcome", "approved"),
                        ("review.receipt_ref", "work/windows/x.json"), ("review.rounds_used", 0),
                        ("probes.runtime_provenance", "evidence/runtime-provenance-api.json"),
                        ("probes.records[0].instance", "test_one"),
                        ("probes.records[0].verdict", "intended_failure")):
        handoff.set_value(doc, path, value)
        doc = handoff.parse(doc.text())
    form.write_text(doc.text(), encoding="utf-8")
    return art, form


def _hc(art: Path, form: Path, *flags: str) -> tuple:
    done = run_script("handoff_check.py", "--file", str(form), "--task-root", str(art), "--json",
                      "--no-judge", *flags)
    return done.returncode, (json.loads(done.stdout) if done.stdout.lstrip().startswith("{") else done.stdout)


def a_field_over_its_limit_is_cut_by_code_with_the_whole_text_kept() -> None:
    """C2-4 T13/T13b/T14: --shorten cuts a TAIL, keeps the role's words and says where, and cuts only
    when length is the form's sole problem."""
    root = Path(tempfile.mkdtemp(prefix="qa-handoff-"))
    try:
        said = "the assertion compares the response with itself, so it cannot fail for the right reason ok"
        art, form = _critic_form(root, reason=said)
        check_eq("the reason is 90 characters", len(said), 90)
        code, report = _hc(art, form, "--fix")
        lengths = [p for p in report["problems"] if p.get("limit")]
        check_eq("without --shorten the length problem stays, and carries its limit as data",
                 [(p["path"], p["limit"]) for p in lengths], [("scope[0].reason", 80)])
        check_eq("and nothing is cut", report["shortened"], [])
        before = form.read_text(encoding="utf-8")
        code, report = _hc(art, form, "--shorten")
        check_eq("--shorten without --fix is refused", code, 2)
        check_eq("and writes nothing", form.read_text(encoding="utf-8"), before)

        code, report = _hc(art, form, "--fix", "--shorten")
        check_eq("with both, the form is complete", (code, report["problems"]), (0, []))
        check_eq("one field was cut, by name and size",
                 report["shortened"], [{"field": "scope[0].reason", "kept_len": 80, "written_len": 90}])
        doc = handoff.parse(form.read_text(encoding="utf-8"))
        kept = doc.get("scope[0].reason")
        mark = " [cut: work/handoffs/S5-qa-code-critic-1.yaml]"
        check("the kept value fits the limit it was cut for", len(kept) <= 80, kept)
        check("it ends with the mark that names the file the code writes", kept.endswith(mark), kept)
        check("and starts with the role's own words", said.startswith(kept[:-len(mark)]), kept)
        check_eq("the role's whole text is in the form", doc.get("shortened[0].as_written"), said)
        check_eq("with the value that replaced it", doc.get("shortened[0].kept"), kept)
        check_eq("one row for the field", doc.get("shortened[0].field"), "scope[0].reason")
        code, report = _hc(art, form)
        check_eq("T13b: a form with the section passes the check on its own", (code, report["problems"]), (0, []))

        # edge 1/3: the very limit is not cut; a later longer word of the role replaces the row
        handoff.set_value(doc, "scope[0].reason", "x" * 80)
        form.write_text(doc.text(), encoding="utf-8")
        code, report = _hc(art, form, "--fix", "--shorten")
        check_eq("a value of exactly the limit is not cut", report["shortened"], [])
        run_script("handoff_check.py", "--file", str(form), "--task-root", str(art), "--no-judge",
                   "--set", "scope[0].reason=" + "y" * 90)
        code, report = _hc(art, form, "--fix", "--shorten")
        doc = handoff.parse(form.read_text(encoding="utf-8"))
        check_eq("cut again: still exactly one row for the field", doc.rows("shortened"), [0])
        check_eq("and it holds the role's LAST word", doc.get("shortened[0].as_written"), "y" * 90)
    finally:
        cleanup(root)


def length_is_cut_only_when_it_is_the_forms_only_problem() -> None:
    """F-1 (t-909): the guard lives in HC. A form that also has a judgement problem is not cut - the
    role is woken for that one anyway and can say it shorter itself (P1); the same for a limit with no
    room beside the mark (T14); text is counted in characters, not bytes."""
    root = Path(tempfile.mkdtemp(prefix="qa-handoff-"))
    try:
        art, form = _critic_form(root, reason="r" * 95, verdict="banana")
        code, report = _hc(art, form, "--fix", "--shorten")
        paths = sorted(p["path"] for p in report["problems"])
        check_eq("length + a word outside the closed list (`banana`): both stay", paths, ["header.verdict", "scope[0].reason"])
        check_eq("nothing is cut", report["shortened"], [])
        check_eq("the role's text is untouched", handoff.parse(form.read_text(encoding="utf-8")).get(
            "scope[0].reason"), "r" * 95)
        check_not_in("and no section appears", "shortened:", form.read_text(encoding="utf-8"))
    finally:
        cleanup(root)
    root = Path(tempfile.mkdtemp(prefix="qa-handoff-"))
    try:
        stem = "S5-qa-code-critic-" + "z" * 28          # 46 characters: 80 - 27 - 46 = 7 < 8 left for the role's words
        check_eq("the stem is one over the room", len(stem), 46)
        art, form = _critic_form(root, dispatch=stem, reason="r" * 90)
        code, report = _hc(art, form, "--fix", "--shorten")
        check_eq("T14: no room beside the mark - the role keeps its problem", [p["path"] for p in report["problems"]],
                 ["scope[0].reason"])
        check_eq("nothing is cut", report["shortened"], [])
    finally:
        cleanup(root)
    root = Path(tempfile.mkdtemp(prefix="qa-handoff-"))
    try:
        stem = "S5-qa-code-critic-" + "z" * 27          # 45: exactly 8 characters of the role's words stay
        art, form = _critic_form(root, dispatch=stem, reason="é" * 90)
        code, report = _hc(art, form, "--fix", "--shorten")
        check_eq("at 45 the cut happens", (code, len(report["shortened"])), (0, 1))
        kept = handoff.parse(form.read_text(encoding="utf-8")).get("scope[0].reason")
        check_eq("characters are counted, not bytes: 8 of them stay and the mark follows",
                 (len(kept), kept.startswith("é" * 8)), (80, True))
    finally:
        cleanup(root)


def two_fields_cut_at_once_and_a_later_cut_of_another_field_keeps_the_first_row() -> None:
    """t-919 F-5: `record_shortened` with two fields cut in one call (two rows, both fields within the limit), and a LATER cut of a
    third field inserted into the existing section (three rows, the section still parses, the first rows unchanged)."""
    root = Path(tempfile.mkdtemp(prefix="qa-handoff-"))
    try:
        art, form = _critic_form(root, reason="a" * 90)
        doc = handoff.parse(form.read_text(encoding="utf-8"))
        start = doc.nodes["scope[0].id"].line
        end = max(n.end_line for p, n in doc.nodes.items() if p.startswith("scope[0]"))
        rows = ["  - id: test_one", "    state: approved", f"    reason: {json.dumps('a' * 90)}",
                "  - id: test_two", "    state: approved", f"    reason: {json.dumps('b' * 91)}",
                "  - id: test_three", "    state: approved", "    reason: fine"]
        doc.lines = doc.lines[:start] + rows + doc.lines[end + 1:]
        form.write_text(doc.text(), encoding="utf-8")
        code, report = _hc(art, form, "--fix", "--shorten")
        check_eq("two fields over their limit: both are cut in one call",
                 (code, [r["field"] for r in report["shortened"]]), (0, ["scope[0].reason", "scope[1].reason"]))
        doc = handoff.parse(form.read_text(encoding="utf-8"))
        check_eq("two rows in the section", doc.rows("shortened"), [0, 1])
        check_eq("each keeps its own whole text",
                 [doc.get("shortened[0].as_written"), doc.get("shortened[1].as_written")], ["a" * 90, "b" * 91])
        check("and both fields are within 80", all(len(doc.get(f"scope[{i}].reason")) <= 80 for i in (0, 1)))
        first = doc.get("shortened[0].kept")
        # a third field goes over its limit later: its row goes INTO the existing section, the first two stay
        run_script("handoff_check.py", "--file", str(form), "--task-root", str(art), "--no-judge",
                   "--set", "scope[2].reason=" + "c" * 90)
        code, report = _hc(art, form, "--fix", "--shorten")
        doc = handoff.parse(form.read_text(encoding="utf-8"))
        check_eq("the later cut of another field: three rows, the section still parses",
                 (code, doc.rows("shortened"), doc.get("shortened[2].field")), (0, [0, 1, 2], "scope[2].reason"))
        check_eq("the first row is as it was", (doc.get("shortened[0].kept"), doc.get("shortened[0].as_written")), (first, "a" * 90))
        check_eq("and the form passes on its own", _hc(art, form)[1]["problems"], [])
        # t-919 F-4: the row of a field cut AGAIN is rewritten by the one scalar writer: a wrapped value loses its continuation lines
        node = doc.nodes["shortened[0].as_written"]
        doc.lines[node.line:node.line + 1] = ["    as_written: wrapped first part", "      and its continuation line"]
        form.write_text(doc.text(), encoding="utf-8")
        wrapped = handoff.parse(form.read_text(encoding="utf-8"))
        check("the wrapped row parses (the premise of the pin)", "continuation" in str(wrapped.get("shortened[0].as_written")))
        run_script("handoff_check.py", "--file", str(form), "--task-root", str(art), "--no-judge",
                   "--set", "scope[0].reason=" + "z" * 90)
        code, report = _hc(art, form, "--fix", "--shorten")
        text = form.read_text(encoding="utf-8")
        doc = handoff.parse(text)
        check_eq("a field cut again: its wrapped row is replaced whole, no continuation line left",
                 (code, doc.get("shortened[0].as_written"), "continuation" in text, doc.rows("shortened")), (0, "z" * 90, False, [0, 1, 2]))
    finally:
        cleanup(root)


BUG_CLAIM = "no_bug_reaches_the_gate_without_a_draft_and_a_triage_row"


def the_bug_draft_claim_reads_the_manifestations() -> None:
    """t-2187 N2 (5.2, F-2 (a)): the S7 claim covers an APP_BUG row through a draft's manifestations, refuses a manifestation that names no row or
    a row that is not APP_BUG, and refuses a merge whose cause the factory cannot re-read - each with its door. Mutation (named, not run):
    drop the `BR.merged_unconfirmed` loop -> the 'cannot confirm' keys; drop the `manifestation_*` loops -> the two door keys."""
    import handoff_check as H
    claim = H.CLAIMS[BUG_CLAIM]
    rows = [{"instance_id": f"t_{n}", "attempt_id": "a1", "case": f"TC-{n}", "verdict": "APP_BUG"} for n in (1, 2, 3)]
    rows.append({"instance_id": "t_9", "attempt_id": "a1", "verdict": "ENV_ISSUE"})
    ref = lambda n: {"instance_id": f"t_{n}", "attempt_id": "a1"}   # noqa: E731

    def man(n, **over):
        return {"action": f"a{n}", "start_state": "s", "seen": "x", "triage_ref": None, "triage_row": ref(n), "evidence": "e", "red_test_none": "m", **over}
    line = "const q = f(1);"
    good = {"statement": "s", "status": "confirmed", "basis": [{"id": "b1", "kind": "code_line", "path": "src/P.tsx", "line": 2, "quote": line}]}

    def merged(mech=None, mans=None, **over):
        body = {"title": "t", "triage_ref": ref(1), "case": "TC-1", "manifestations": mans or [man(1), man(2), man(3)], **over}
        if mech is not None:
            body["mechanism"] = mech
        return body
    root = temp_project("qa-handoff-n2-")
    try:
        (root / "src").mkdir(exist_ok=True)
        (root / "src" / "P.tsx").write_text("a\n" + line + "\n", encoding="utf-8")   # the project root holds the code the basis cites

        def verdict(name, drafts):
            task = root / "qa-factory" / "artifacts" / name
            (task / "work" / "bug-drafts").mkdir(parents=True)
            (task / "work" / "triage.json").write_text(json.dumps({"triage": rows}), encoding="utf-8")
            for fname, body in drafts.items():
                (task / "work" / "bug-drafts" / fname).write_text(json.dumps(body), encoding="utf-8")
            return claim(H.Artifacts(task))
        import bug_records as BR
        got = verdict("n2-three", {"m.json": merged(good)})
        check_eq("N2 5.2: three APP_BUG rows, one merged draft whose basis stands: the claim holds", got[0], True)
        check_in("N2 5.2: ... and says what it paired", "every draft rests on an APP_BUG row and every APP_BUG row has its draft", got[1])
        got = verdict("n2-nr", {"m.json": merged(good, mans=[man(1), man(2, triage_row={"instance_id": "t_77", "attempt_id": "a1"}), man(3)])})
        check_eq("N2 5.2: a manifestation naming no row: refused", got[0], False)
        check_in("N2 5.2: ... with its door", "names the row t_77@a1, which is no row of work/triage.json - add the row the manifestation names, or remove the manifestation", got[1])
        got = verdict("n2-env", {"m.json": merged(good, mans=[man(1), man(9), man(2), man(3)])})
        check_in("N2 5.2: a manifestation naming a row that is not APP_BUG: refused, naming the verdict and the door",
                 "names the row t_9@a1, whose verdict is ENV_ISSUE, not APP_BUG - the verdict is corrected, or the manifestation is removed", got[1])
        got = verdict("n2-uncovered", {"m.json": merged(good, mans=[man(1), man(2)])})
        check_in("N2 5.2: the row no manifestation names is still owed a draft", "no draft for the APP_BUG row t_3@a1", got[1])
        broken = dict(good, basis=[{"id": "b1", "kind": "code_line", "path": "src/Nope.tsx", "line": 1, "quote": "x"}])
        for label, mech in (("a basis that does not stand", broken), ("no mechanism at all", None), ("status unknown", {"status": "unknown", "why": "w"})):
            got = verdict("n2-" + label.split()[0] + str(len(label)), {"m.json": merged(mech)})
            check_eq(f"N2 F-2: {label}, three manifestations: refused", got[0], False)
            check("N2 F-2: ... naming the draft, its first problem and the two doors (fix the basis / split with possibly_same_cause)",
                  "the draft m.json puts several manifestations under one cause the factory cannot confirm" in got[1]
                  and "fix the basis (a shared `defect_location` line can be cited as a `code_line`), or split the draft and link the parts with `possibly_same_cause`" in got[1], got[1])
        got = verdict("n2-one", {"m.json": merged(broken, mans=[man(1)])})
        check_not_in("N2 F-2: a draft with ONE manifestation and a broken mechanism is no merge: no 'cannot confirm' line", "cannot confirm", got[1])
        check_eq("N2 old draft: no manifestations, no new line", BR.merged_unconfirmed(root, [("o.json", {"title": "t"})]), [])
    finally:
        cleanup(root)


def the_bug_draft_claim_reads_the_json_drafts() -> None:
    """G1-9 (t-1078): `no_bug_reaches_the_gate_without_a_draft_and_a_triage_row` counted `work/bug-drafts/*.md` while the
    writer produces `*.json`, so it refused every story with APP_BUG rows and passed a draft with no row. It now pairs
    (`bug_records.pair_drafts`): each draft on an APP_BUG row, each APP_BUG row with a draft. The error goes one way (a
    refusal). Edges 1-7, 12 and the old home of the spec, through `H.CLAIMS` and `_check_claims`; the expectations are the
    requirement ("a bug at the gate needs a draft and a triage row"), the saved stories are the shapes."""
    import types
    import handoff_check as H
    claim = H.CLAIMS[BUG_CLAIM]
    app = {"instance_id": "t_a", "attempt_id": "a1", "verdict": "APP_BUG"}
    env = {"instance_id": "t_b", "attempt_id": "a1", "verdict": "ENV_ISSUE"}
    on_app = {"triage_ref": {"instance_id": "t_a", "attempt_id": "a1"}}

    def story(root: Path, name: str, drafts: dict | None = None, triage=None, md: dict | None = None,
              old: dict | None = None, raw_triage: str | None = None) -> Path:
        task = root / name
        task.mkdir()
        for home, files in (("work/bug-drafts", drafts), ("work/bug-drafts", md), ("bug-drafts", old)):
            if files is not None:
                (task / home).mkdir(parents=True, exist_ok=True)
                for fname, body in files.items():
                    (task / home / fname).write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
        if raw_triage is not None:
            (task / "work").mkdir(exist_ok=True)
            (task / "work" / "triage.json").write_text(raw_triage, encoding="utf-8")
        elif triage is not None:
            (task / "work").mkdir(exist_ok=True)
            (task / "work" / "triage.json").write_text(json.dumps({"triage": triage}), encoding="utf-8")
        return task

    root = Path(tempfile.mkdtemp(prefix="qa-handoff-g19-"))
    try:
        def verdict(task: Path) -> tuple:
            return claim(H.Artifacts(task))

        check_in("the claim is registered under its key", BUG_CLAIM, list(H.CLAIMS))
        got = verdict(story(root, "e1", drafts={}, triage=[]))
        check_eq("edge 1: an empty folder, no rows: it holds (I3)", got[0], True)
        check_in("edge 1: and says nothing claims a bug", "nothing claims a bug", got[1])
        check_eq("edge 3: no folder, no triage.json: it holds (I3)", verdict(story(root, "e3"))[0], True)
        got = verdict(story(root, "e2", triage=[app]))
        check_eq("edge 2: no folder but an APP_BUG row: it refuses (I2)", got[0], False)
        check_in("edge 2: the text counts both sides and names the folder it looked in and the row with no draft",
                 "0 draft(s) in work/bug-drafts/*.json (or the old bug-drafts/*.json) and 1 APP_BUG triage row(s) in "
                 "work/triage.json", got[1])
        check_in("edge 2: and names the APP_BUG row that has no draft, with its door", "no draft for the APP_BUG row t_a@a1 - the draft is written",
                 got[1])
        got = verdict(story(root, "e4", md={"BD-1.md": "# a hand-laid draft"}, triage=[app]))
        check_eq("edge 4: only a `.md` and an APP_BUG row: it refuses, the `.md` is not a draft (I1)", got[0], False)
        check_in("edge 4: it says the .md was not counted (the legacy world is named, never silent)",
                 "1 *.md file(s) in the draft folder were not counted, a draft is a *.json file (BD-1.md)", got[1])
        got = verdict(story(root, "e5", drafts={"BD-1.json": on_app}, md={"BD-2.md": "x"}, triage=[app]))
        check_eq("edge 5: a `.md` beside a `.json` on its row: the count is the `.json`, it holds", got[0], True)
        check_in("edge 5: and says what it paired", "1 draft(s) in work/bug-drafts/*.json", got[1])
        got = verdict(story(root, "e6", drafts={"r2-github.json": on_app}, triage=[]))
        check_eq("edge 6: a draft and no row (judge-off/13797, the class the claim exists for): it refuses (I2)", got[0], False)
        check_in("edge 6: it names the draft and the door (back to triage)", "no triage row for r2-github.json - the draft goes back to triage", got[1])
        got = verdict(story(root, "e7", triage=[env, {"instance_id": "t_c", "verdict": "FLAKY"}]))
        check_eq("edge 7: rows that are all ENV_ISSUE/FLAKY and no drafts (cmp3/13797): it holds (I3 over I2)", got[0], True)
        got = verdict(story(root, "e7b", drafts={"BD-9.json": {"triage_ref": {"instance_id": "t_b", "attempt_id": "a1"}}}, triage=[env]))
        check_eq("edge 7b: a draft on a row that is ENV_ISSUE: it refuses", got[0], False)
        check_in("edge 7b: and says the row is not APP_BUG, with the verdict and the door", "the row is not APP_BUG for BD-9.json (ENV_ISSUE) - the verdict is corrected or the draft is withdrawn", got[1])
        check_eq("edge 8: a draft in the OLD home counts like any other (F-2 (a))",
                 verdict(story(root, "e8", old={"old.json": on_app}, triage=[app]))[0], True)
        story(root, "e9", triage=[app])
        (root / "e9" / "work" / "bug-drafts" / "x.json").mkdir(parents=True)
        check_eq("edge 9: a folder called x.json is no draft: the APP_BUG row has none", verdict(root / "e9")[0], False)
        check_eq("edge 10: `BD-1.JSON` is a draft on every OS", verdict(story(root, "e10", drafts={"BD-1.JSON": on_app}, triage=[app]))[0], True)
        # the saved stories of the stand (the shapes the measurement of §2.4 read; B-1 of the plan review is the first)
        sdk = verdict(story(root, "sdk15045", triage=[
            {"instance_id": "t1", "verdict": "ENV_ISSUE"}, {"instance_id": "t2", "verdict": "ENV_ISSUE"},
            {"instance_id": "t3", "attempt_id": "a1", "verdict": "APP_BUG"}],
            drafts={f"d{n}.json": {"title": f"d{n}"} for n in range(4)}))
        check_eq("testproject1-sdk/15045 (4 drafts without triage_ref, 3 rows, 1 APP_BUG): it refuses - three drafts rest on no APP_BUG row",
                 sdk[0], False)
        check_in("... and says so for the drafts and for the APP_BUG row alike", "no triage row for d0.json, d1.json, d2.json, d3.json", sdk[1])
        check_in("... and the APP_BUG row has none", "no draft for the APP_BUG row t3@a1", sdk[1])
        cmp2r = verdict(story(root, "cmp2r", triage=[app, dict(app, instance_id="t_d")], drafts={
            "a.json": on_app, "b.json": {"triage_ref": "t_d@a1"}}))
        check_eq("cmp2r/15045 (two drafts, two APP_BUG rows, each draft names its row): it holds", cmp2r[0], True)
        check_in("... and says every draft rests on an APP_BUG row", "every draft rests on an APP_BUG row and every APP_BUG row has its draft", cmp2r[1])
        check_eq("an unreadable draft rests on no row: it refuses, by name",
                 (verdict(story(root, "bad", drafts={"broken.json": "{not json"}, triage=[app]))[0]), False)
        check_eq("two drafts for one row: both rest on it, it holds",
                 verdict(story(root, "two", drafts={"a.json": on_app, "b.json": on_app}, triage=[app]))[0], True)

        # edge 12 / F-8 (b) / M-1: a triage.json that is there and cannot be read is NO VERDICT, never `0 rows`
        for label, raw in (("not JSON", "{not json"), ("a JSON list (it crashed the old line)", '[{"verdict": "APP_BUG"}]'),
                           ("an object with no `triage` list", "{}"), ("`triage: null`", '{"triage": null}'),
                           ("a row that is not an object", '{"triage": ["junk"]}')):
            task = story(root, "bad-triage-" + str(len(list(root.iterdir()))), drafts={"BD-1.json": on_app}, raw_triage=raw)
            art = H.Artifacts(task)
            got = claim(art)
            check_eq(f"edge 12: triage.json is {label}: no verdict (None), no exception", got[0], None)
            check_in(f"edge 12: {label}: the reason is _triage_view's own", "work/triage.json", got[1])
            doc = types.SimpleNamespace(data={"claims": {BUG_CLAIM: True}})
            check_eq(f"edge 12: {label}: not a problem of the form, printed as `no verdict`",
                     (H._check_claims(doc, art), [n["claim"] for n in art.no_verdict]), ([], [f"claims.{BUG_CLAIM}"]))

        # the form's check: the existing mismatch text and the form's door; `false` and an absent claim are not verified
        task = story(root, "form", drafts={"BD-1.json": on_app}, triage=[])
        art = H.Artifacts(task)
        problems = H._check_claims(types.SimpleNamespace(data={"claims": {BUG_CLAIM: True}}), art)
        check_eq("the refusal is one problem of that claim, in the form's own words and with its door",
                 [(p.path, p.text.startswith("the form claims this is true, and it is not: "), p.fix) for p in problems],
                 [(f"claims.{BUG_CLAIM}", True, "repair the work, or write false and name it in `unresolved`")])
        check_eq("an honest `false` is not verified", H._check_claims(types.SimpleNamespace(data={"claims": {BUG_CLAIM: False}}), art), [])
        form_text = (CONTRACTS / "s7-analyst-to-scribe.yaml").read_text(encoding="utf-8")
        check("FR-37: the form tells the role the path the code reads (`work/bug-drafts/<file>.json`, never `.md`)",
              "path: work/bug-drafts/<file>.json" in form_text and "bug-drafts/<file>.md" not in form_text)
        before = {p.relative_to(task).as_posix(): p.read_bytes() for p in sorted(task.rglob("*")) if p.is_file()}
        claim(H.Artifacts(task))
        check_eq("FR-45: the verifier writes nothing into the story",
                 {p.relative_to(task).as_posix(): p.read_bytes() for p in sorted(task.rglob("*")) if p.is_file()}, before)
        # --- C3 (t-1676): a code-reading draft rests on an oracle and an S1 fact, never on a triage row ---
        import question_register as QR
        q7 = {"id": "Q7", "question": "What should the cart keep?", "severity": "blocker", "source_says": [],
              "readings": [{"reading": "the price shown when added is kept", "from": "person", "if_chosen": "x"}, {"reading": "refreshed", "from": "person", "if_chosen": "y"}]}
        fact = {"id": "XPANBFLFA-167 price sync / subtotal", "path": "MyBooks/src/lib/services/cartService.ts", "line": 103}
        cr = {"title": "The cart total uses the current price", "impact": "money", "violates": "requirement:R-24", "evidence": "code-reading",
              "oracle": {"question": "Q7", "quote": "the price shown when added is kept"}, "fact": fact, "check_state": "not_executed",
              "manual_steps": ["add a book at 6, change its price to 8, open the cart"], "confirmation": "unconfirmed",
              "red_test_none": "no run spoke: the defect is read from the code"}

        def cr_story(name, answered):
            task = story(root, name, drafts={"BD-1.json": cr})
            (task / "work" / "context-bundle.json").write_text(json.dumps({"facts": [fact]}), encoding="utf-8")
            (task / "work" / "requirements-readiness.json").write_text(json.dumps({"open_questions": [q7]}), encoding="utf-8")
            if answered:
                (task / "work" / "question-answers.jsonl").write_text(json.dumps({"id": "Q7", "status": "answered", "reading": "a", "words": "a", "where": "gate_a",
                                                                                 "at": "2026-11-01T12:00:00", "row_hash": QR._hash(q7)}) + "\n", encoding="utf-8")
            return task
        got = verdict(cr_story("c3a", True))
        check_eq("C3 S7 claim: a valid code-reading draft passes with no triage row (no `no row` refusal)", got[0], True)
        check_in("C3 ... and the pass names it as standing on its oracle", "code-reading draft(s) stand on their oracle", got[1])
        got = verdict(cr_story("c3b", False))
        check_eq("C3 S7 claim: a draft whose question is not settled is refused", got[0], False)
        check_in("C3 ... by name, with the way out", "the code-reading draft BD-1.json: question Q7 is not settled by the person", got[1])
        check_in("C3 ... and says fix it or withdraw it", "fix it or withdraw it", got[1])
    finally:
        cleanup(root)


def the_bug_draft_claim_gives_no_verdict_on_a_folder_it_cannot_list() -> None:
    """F-1 (t-1100): a draft folder that exists and cannot be listed is NOT 'no drafts'. The claim answers `None` ('drafts
    unreadable: <home>: <reason>', printed as `no verdict`), never the pass 'nothing claims a bug' (FR-59, FR-41; the
    error goes one way, into a refusal or no verdict). The critic's probe: one draft, no row, `{"triage": []}`, and the
    listing refused. An EMPTY listable folder keeps its pass (edge 1)."""
    import pathlib
    import types
    import handoff_check as H
    claim = H.CLAIMS[BUG_CLAIM]
    root = Path(tempfile.mkdtemp(prefix="qa-handoff-g19-unreadable-"))
    real = pathlib.Path.iterdir
    try:
        def build(name: str, drafts: dict, homes=("work/bug-drafts",), triage=None) -> Path:
            task = root / name
            (task / "work").mkdir(parents=True)
            for home in homes:
                (task / home).mkdir(parents=True, exist_ok=True)
                for fname, body in drafts.items():
                    (task / home / fname).write_text(json.dumps(body), encoding="utf-8")
            (task / "work" / "triage.json").write_text(json.dumps({"triage": [] if triage is None else triage}), encoding="utf-8")
            return task

        def refusing(task: Path, *homes: str):
            blocked = {task / home for home in homes}

            def iterdir(self):
                if self in blocked:
                    raise PermissionError("denied")
                return real(self)
            return iterdir

        task = build("probe", {"BD-1.json": {"triage_ref": {"instance_id": "t_a", "attempt_id": "a1"}}})
        check_eq("probe, listable: one draft and no row - it refuses (False)", claim(H.Artifacts(task))[0], False)
        pathlib.Path.iterdir = refusing(task, "work/bug-drafts")
        try:
            got = claim(H.Artifacts(task))
            check_eq("probe, the same story with the listing refused: no verdict (None), NOT the pass 'nothing claims a bug'",
                     got[0], None)
            check_in("... the reason names the home and the cause", "drafts unreadable: work/bug-drafts: cannot list: denied", got[1])
            check_in("... and the door: say so under `blocked`, so the conductor can make it listable", "under `blocked`", got[1])
            art = H.Artifacts(task)
            doc = types.SimpleNamespace(data={"claims": {BUG_CLAIM: True}})
            check_eq("through `_check_claims`: not a problem of the form, printed as `no verdict`",
                     (H._check_claims(doc, art), [n["claim"] for n in art.no_verdict]), ([], [f"claims.{BUG_CLAIM}"]))
        finally:
            pathlib.Path.iterdir = real
        check_eq("and once it can be listed the claim answers again (False)", claim(H.Artifacts(task))[0], False)

        # an APP_BUG row and a folder nobody could list: also no verdict, not 'the row has no draft' and not a pass
        row = {"instance_id": "t_a", "attempt_id": "a1", "verdict": "APP_BUG"}
        task = build("with-row", {}, triage=[row])
        pathlib.Path.iterdir = refusing(task, "work/bug-drafts")
        try:
            check_eq("an APP_BUG row and an unlistable folder: no verdict", claim(H.Artifacts(task))[0], None)
        finally:
            pathlib.Path.iterdir = real
        # only the OLD home fails: still no verdict - a draft may lie in the home nobody could read
        task = build("old-home", {"BD-1.json": {"triage_ref": {"instance_id": "t_a", "attempt_id": "a1"}}},
                     homes=("work/bug-drafts", "bug-drafts"), triage=[row])
        check_eq("(control) both homes listable, a draft on its APP_BUG row in each: it holds", claim(H.Artifacts(task))[0], True)
        pathlib.Path.iterdir = refusing(task, "bug-drafts")
        try:
            got = claim(H.Artifacts(task))
            check_eq("the old home refused, the work/ home fine: still no verdict", got[0], None)
            check_in("... and the reason names the old home by its own label", "drafts unreadable: bug-drafts: cannot list: denied", got[1])
        finally:
            pathlib.Path.iterdir = real
        # an EMPTY folder that CAN be listed is not unreadable (edge 1 keeps its pass)
        task = build("empty", {})
        got = claim(H.Artifacts(task))
        check_eq("(control) an empty, listable folder and no rows: it holds, as before", got[0], True)
        check_in("(control) and says nothing claims a bug", "nothing claims a bug", got[1])
    finally:
        pathlib.Path.iterdir = real
        cleanup(root)


def the_implementation_checkout_has_one_survivor_and_never_asks_for_an_empty_id() -> None:
    """G1-2 (M14, axis 10): `implementation_checkout(entry, cfg, project, diff_name)` is the one «entry -> checkout» survivor: an
    empty id never reaches `_checkout_path` (it would match a config entry that names no repository)."""
    import handoff_check as H
    root = Path(tempfile.mkdtemp(prefix="qa-impl-checkout-")).resolve()       # the long form: a Windows temp path may be an 8.3 name
    folder = root / "co"
    folder.mkdir()
    (root / "afile").write_bytes(b"x")
    cfg = {"implementation_repos": [{"repo_id": "", "local_path": str(folder)}, {"repo_id": "be", "local_path": str(folder)},
                                    {"repo_id": "gone", "local_path": str(root / "afile")}]}
    asked, real = [], H._checkout_path
    H._checkout_path = lambda *args: (asked.append(args[0]), real(*args))[1]
    try:
        check_eq("impl checkout: repo_id '' with `repo` set -> the repo's folder", H.implementation_checkout({"repo_id": "", "repo": "be"}, cfg, root, "impl-diff.txt"), (folder, ""))
        check_eq("impl checkout: whitespace around the id is stripped", H.implementation_checkout({"repo_id": " be "}, cfg, root, "impl-diff.txt"), (folder, ""))
        asked.clear()
        check_eq("impl checkout: both empty -> the reason by diff name, and `_checkout_path` was NOT asked",
                 (H.implementation_checkout({"repo_id": "", "repo": " "}, cfg, root, "impl-diff.txt"), asked), ((None, "no repository id for impl-diff.txt"), []))
        check_eq("impl checkout: a config path that is a file -> `no checkout of <id> on this machine`",
                 H.implementation_checkout({"repo": "gone"}, cfg, root, "d.txt"), (None, "no checkout of gone on this machine"))
        check_eq("impl checkout: an id the config does not name -> the same words", H.implementation_checkout({"repo": "zz"}, cfg, root, "d.txt"), (None, "no checkout of zz on this machine"))
        check_eq("impl checkout: no entry (None / a string) -> `no manifest entry for <diff>`",
                 [H.implementation_checkout(x, cfg, root, "impl-diff.txt") for x in (None, "be")], [(None, "no manifest entry for impl-diff.txt")] * 2)
    finally:
        H._checkout_path = real
        cleanup(root)


PLAN_AUTHOR, PLAN_CRITIC ="s5-automator-plan-to-critic", "s5-critic-plan-to-automator"
WINDOW_AUTHOR, WINDOW_CRITIC = "s5-automator-to-critic", "s5-critic-to-automator"


def a_row_may_name_the_purpose_it_serves_and_the_window_contract_stays_what_it_was() -> None:
    """SC1-14 A2: the two plan handovers are index rows with `purpose: s5_plan`. `contract_of` matches such a row only for a
    lookup that asks for that purpose. KILLS M10 (a row with a purpose taken by a lookup without one: the window contract of
    S5 changes under every `story_step start`)."""
    check_eq("window contract unchanged: the author's lookup with no purpose", handoff.contract_of("S5", "qa-automator"), WINDOW_AUTHOR)
    check_eq("window contract unchanged: the author -> critic lookup with no purpose",
             handoff.contract_of("S5", "qa-automator", "qa-code-critic"), WINDOW_AUTHOR)
    check_eq("window contract unchanged: the critic's lookup with no purpose", handoff.contract_of("S5", "qa-code-critic"), WINDOW_CRITIC)
    check_eq("window contract unchanged: the critic -> author lookup with no purpose",
             handoff.contract_of("S5", "qa-code-critic", "qa-automator"), WINDOW_CRITIC)
    check_eq("the plan: the author's contract for purpose s5_plan", handoff.contract_of("S5", "qa-automator", purpose="s5_plan"), PLAN_AUTHOR)
    check_eq("the plan: the author -> critic lookup for purpose s5_plan",
             handoff.contract_of("S5", "qa-automator", "qa-code-critic", "s5_plan"), PLAN_AUTHOR)
    check_eq("the plan: the critic's contract for purpose s5_plan", handoff.contract_of("S5", "qa-code-critic", purpose="s5_plan"), PLAN_CRITIC)
    check_eq("the plan: the critic -> author lookup for purpose s5_plan",
             handoff.contract_of("S5", "qa-code-critic", "qa-automator", "s5_plan"), PLAN_CRITIC)
    check_eq("an unknown purpose resolves to no contract, never to the stage's usual one",
             [handoff.contract_of("S5", "qa-automator", purpose="nobody_registered_this"),
              handoff.contract_of("S5", "qa-code-critic", purpose="repair_verify")], ["", ""])
    check_eq("a purpose on a stage that names none: no contract", handoff.contract_of("S4", "qa-case-designer", purpose="s5_plan"), "")
    check_eq("a purpose with a receiver the row does not name: no contract",
             handoff.contract_of("S5", "qa-automator", "qa-runner", "s5_plan"), "")
    check_eq("the secondary handover is still reached by naming its receiver, with no purpose",
             handoff.contract_of("S5", "qa-automator", "qa-runner"), "s5-automator-to-runner")
    # position is not what protects the window contract: put the plan rows FIRST and ask again
    real = handoff.index
    rows = [r for r in real()["handoffs"]]
    plan_rows = [r for r in rows if r.get("purpose")]
    check_eq("control: the real index holds exactly the two plan rows with a purpose",
             sorted(r["contract"] for r in plan_rows), sorted([PLAN_AUTHOR, PLAN_CRITIC]))
    handoff.index = lambda: {"handoffs": plan_rows + [r for r in rows if not r.get("purpose")]}
    try:
        check_eq("with the plan rows first, the author's lookup with no purpose is still the window contract",
                 [handoff.contract_of("S5", "qa-automator"), handoff.contract_of("S5", "qa-automator", "qa-code-critic")],
                 [WINDOW_AUTHOR, WINDOW_AUTHOR])
        check_eq("with the plan rows first, the critic's lookup with no purpose is still the window contract",
                 [handoff.contract_of("S5", "qa-code-critic"), handoff.contract_of("S5", "qa-code-critic", "qa-automator")],
                 [WINDOW_CRITIC, WINDOW_CRITIC])
    finally:
        handoff.index = real


def the_plan_handovers_carry_what_the_readers_read() -> None:
    """The review is read by `s5_plan.reviews` as `review.outcome` plus a TOP-LEVEL `remarks` list (A1b decision 6); the plan
    handover points at `work/s5-plan.json`. Neither contract has a claim (the facts are `s5_plan.check`'s) nor a plan hash
    (the stamp is code's)."""
    author, critic = handoff.spec(PLAN_AUTHOR), handoff.spec(PLAN_CRITIC)
    check_eq("the plan handover is a produce handover whose artifact is the plan file",
             (handoff.template(PLAN_AUTHOR).get("artifacts.plan"), [k for k in author if k.startswith("claims")]), ("work/s5-plan.json", []))
    check_eq("the review's outcome is one of the plan verdicts", critic["review.outcome"].options,
             handoff.allowed("plan_verdicts"))
    check_eq("the review's remark kind is one of the plan remark kinds", critic["remarks[].kind"].options, handoff.allowed("plan_remark_kinds"))
    for leaf in ("id", "case", "test", "then", "kind", "check", "problem", "expected", "fix"):
        check_in(f"the review's remark row carries `{leaf}` (the reader `s5_plan._remark` reads it)", f"remarks[].{leaf}", critic)
    check("a remark's `expected` is required (a remark that does not say what the critic expects is a riddle)", not critic["remarks[].expected"].optional)
    check_eq("`case`, `test`, `then` take a dash, and the empty `remarks` list is the answer to an approved plan",
             [critic[f"remarks[].{leaf}"].optional for leaf in ("case", "test", "then", "id")], [True] * 4)
    check_eq("the review has no plan hash and no claims (the stamp is code's, the facts are the detector's)",
             [k for k in critic if "sha" in k or "hash" in k or k.startswith("claims") or k.startswith("plan_sha256")], [])
    raw = (CONTRACTS / f"{PLAN_CRITIC}.yaml").read_text(encoding="utf-8")
    check_not_in("and the contract's own text names no plan_sha256 field", "plan_sha256:", raw)


def the_window_form_gains_two_optional_sections_and_the_0102_form_still_passes() -> None:
    """SC1-14 A2, N2/E5: `plan_remarks` and `deviations` are optional (the contract says `or the empty list`), so a window form
    written on 0.10.2 - without them - passes `handoff_check` on 0.10.3 with no problem at their paths. KILLS M11 (a new section
    without the optional words: every row field of it is then required, and an untouched skeleton row is a refusal)."""
    spec = handoff.spec(WINDOW_AUTHOR)
    for section, first in (("plan_remarks", "id"), ("deviations", "test")):
        check(f"{section}[].{first} is optional (`or the empty list`)", spec[f"{section}[].{first}"].optional)
    check_eq("plan_remarks: the row word is one of the plan remark rows, the reason is at most 80 characters",
             (spec["plan_remarks[].row"].options, spec["plan_remarks[].reason"].max_len), (handoff.allowed("plan_remark_rows"), 80))
    check_eq("deviations: the kind is one of the plan deviation kinds, the reason is at most 80 characters",
             (spec["deviations[].from"].options, spec["deviations[].reason"].max_len), (handoff.allowed("plan_deviation_kinds"), 80))
    check_eq("no new claim in the window contract (C12 and the plan's facts are held by the detectors)",
             sorted(k for k in spec if k.startswith("claims.")),
             ["claims.every_case_in_scope_has_an_instance", "claims.every_expectation_change_after_red_is_recorded",
              "claims.every_instance_names_its_current_case_version", "claims.every_instance_ran", "claims.manifest_matches_the_tests"])
    form_0102 = FIXTURES / "s5-window-form-0102" / "work" / "handoffs" / "S5-qa-automator-1.yaml"
    text = form_0102.read_text(encoding="utf-8")
    check("control: the 0.10.2 fixture holds neither new section (the form predates them)",
          "plan_remarks" not in text and "deviations" not in text and "for_the_reviewer:" in text)
    root = Path(tempfile.mkdtemp(prefix="qa-handoff-0102-"))

    def problems_at_new_paths(form_text: str) -> tuple:
        art = root / "artifacts" / "QA-7"
        (art / "work" / "handoffs").mkdir(parents=True, exist_ok=True)
        form = art / "work" / "handoffs" / "S5-qa-automator-1.yaml"
        form.write_text(form_text, encoding="utf-8")
        done = run_script("handoff_check.py", "--file", str(form), "--task", "QA-7", "--task-root", str(art),
                          "--fix", "--json", "--no-judge")
        report = json.loads(done.stdout)
        paths = [p["path"] for p in report["problems"]]
        return [p for p in paths if p.startswith(("plan_remarks", "deviations"))], paths, form.read_text(encoding="utf-8")
    try:
        new, every, after = problems_at_new_paths(text)
        check_eq("N2: the 0.10.2 window form has no problem at `plan_remarks` or `deviations`", new, [])
        check("N2 control: the same call does read the form (it is not a silent pass: its own paths are checked)",
              isinstance(every, list), str(every)[:120])
        check("N2: and --fix adds no section to the saved form", "plan_remarks" not in after and "deviations" not in after)
        untouched = text.rstrip("\n") + (
            "\nplan_remarks:\n  - id: <PR-n, or the empty list>\n    row: <one of vocabulary.plan_remark_rows>\n    reason: <= 80 characters>\n"
            "deviations:\n  - test: <file::function of the test that differs, or the empty list>\n    from: <one of vocabulary.plan_deviation_kinds>\n"
            "    planned: <file::function or T-n of the planned test>\n    reason: <= 80 characters>\n")
        new, _every, _after = problems_at_new_paths(untouched)
        check_eq("an untouched skeleton of the new sections is an empty section, not a refusal", new, [])
        bad = text.rstrip("\n") + (
            "\nplan_remarks:\n  - id: PR-1\n    row: maybe\n    reason: the helper already does it\n"
            "deviations:\n  - test: tests/test_one.py::test_one\n    from: file\n    planned: tests/test_two.py\n    reason: x\n")
        new, _every, _after = problems_at_new_paths(bad)
        check_in("control: a plan_remarks row with a word outside the list IS refused, at its path", "plan_remarks[0].row", new)
        good = bad.replace("row: maybe", "row: applied")
        new, _every, _after = problems_at_new_paths(good)
        check_eq("and the same rows with the word from the list pass", new, [])
    finally:
        cleanup(root)


# --- SC1-2 part C: every claim on a form is checked or gone -----------------------------------------------------
#
# Three claims have a verifier that is silent on what it cannot measure; `--fix` writes `true` into an empty claim only
# where that verifier PROVES it; five claims nothing read are removed from their contracts.

S2C, S4C, S5R, S6A = "s2-tester-to-strategist", "s4-case-critic-to-designer", "s5-automator-to-runner", "s6-runner-to-analyst"
SIZE_CLAIM = "size_computed_by_sizing_py_not_quoted"
ROLLCALL_CLAIM = "the_verdict_was_computed_by_rollcall_not_typed"
FINGERPRINT_CLAIM = "every_instance_carries_a_fingerprint_or_says_never_run"
REMOVED_CLAIMS = {
    "s1-scout-to-tester": "every_retrieved_attachment_has_an_inspection_receipt",
    S2C: "every_requirement_names_its_source_and_revision",
    "s3-strategist-to-designer": "every_row_carries_a_coverage_contract_revision",
    S6A: "every_rerun_names_the_fingerprint_that_moved",
    "s9-retro-to-project": "the_numbers_were_computed_by_code_and_not_recomputed_by_the_role",
}


def _filled(contract: str, values: dict):
    """The shipped contract read as a form, with each `path: value` written in (a path the form lacks fails the test)."""
    doc = handoff.parse(handoff.template(contract).text())
    for path, value in values.items():
        check(f"fixture: the form has a line for {path}", handoff.set_value(doc, path, value), path)
        doc = handoff.parse(doc.text())
    return doc


def _c_story(root: Path, sizing=None, findings=None) -> Path:
    task = root / "qa-factory" / "artifacts" / "QA-700"
    (task / "work" / "test-cases").mkdir(parents=True, exist_ok=True)
    if sizing is not None:
        (task / "work" / "sizing.json").write_text(json.dumps(sizing), encoding="utf-8")
    if findings is not None:
        (task / "work" / "test-cases" / "critic-findings.md").write_text(findings, encoding="utf-8")
    return task


def _c_check(doc, contract: str, task: Path, fix: bool = True, judge: bool = False) -> tuple:
    """`(doc, fixed, problems, judged, derived, art)` of one in-process `check`, with the project pinned to the story's."""
    import handoff_check as H
    import hooklib
    with hooklib.selftest_root_restored():
        hooklib.pin_project_root(task.parents[2])
        art = H.Artifacts(task, dispatch="S0-qa-x-1")
        return H.check(doc, contract, art, fix=fix, task="QA-700", use_judge=judge) + (art,)


def _verify(claim: str, doc, task: Path) -> tuple:
    """The verifier of `claim`, called the way `_check_claims` calls it: with the form on `art.form_doc`."""
    import handoff_check as H
    art = H.Artifacts(task, dispatch="S0-qa-x-1")
    art.form_doc = doc
    return H.CLAIMS[claim](art)


def _rollcall_md(*rows) -> str:
    lines = ["# Critic findings", "", "Verdict: approve_with_concerns", "", "## Roll-call", "",
             "| plan row | case | reviewed | note |", "|---|---|---|---|"]
    return "\n".join(lines + [f"| TS-{n} | {case} | {reviewed} | n |" for n, (case, reviewed) in enumerate(rows, 1)]) + "\n"


def a_claim_code_proves_is_filled_true_and_recorded_in_derived() -> None:
    """K-C1: an empty claim whose verifier proves it is written `true` by `--fix`, and the run says who proved it."""
    root = temp_project("qa-claims-c1-")
    try:
        task = _c_story(root, sizing={"size": "M"})
        path = f"claims.{SIZE_CLAIM}"
        doc = _filled(S2C, {"size.computed": "M"})
        check("K-C1 control: the claim is blank before the run", handoff.is_placeholder(doc.get(path)))
        out, fixed, problems, _judged, derived, _art = _c_check(doc, S2C, task)
        check_eq("K-C1: the claim is `true` in the form", out.get(path), True)
        check_eq("K-C1: and `derived` says it was verified by the claims table",
                 [d["source"] for d in derived if d["field"] == path], ["verified by handoff_check.CLAIMS"])
        check_in("K-C1: and the printed line says so", f"{path} = true", " | ".join(fixed))
        check_eq("K-C1: and the claim is no problem", [p.path for p in problems if p.path == path], [])
        other = "claims.contradiction_matrix_walked_in_full"
        check("K-C1: a claim with no verifier is not filled by code", handoff.is_placeholder(out.get(other)))
        check_in("K-C1: and is refused as not filled, as before", other, [p.path for p in problems])
    finally:
        cleanup(root)


def the_null_outcome_audit_is_green_over_the_index_with_the_purpose_rows() -> None:
    """N9: the audit walks the real index, now with two rows that carry a `purpose`; no new problem, and the two plan
    handovers each have exactly one home (a never_empty row)."""
    import null_outcomes as NO
    report = NO.audit()
    check_eq("null_outcomes.audit over the real index (purpose rows included): no problem", report.problems, [])
    homes = [r for r in json.loads(NO.DATA.read_text(encoding="utf-8"))["never_empty"] if r["kind"] == "scope"
             and r["carrier"] in (f"{PLAN_AUTHOR}:scope", f"{PLAN_CRITIC}:scope")]
    check_eq("each plan handover's item list has one never_empty home", sorted(r["carrier"] for r in homes),
             sorted([f"{PLAN_AUTHOR}:scope", f"{PLAN_CRITIC}:scope"]))
    check_eq("the index counts twenty-three handovers", len(handoff.index()["handoffs"]), 23)


def a_claim_code_measures_false_stays_open_with_the_door() -> None:
    """K-C2: the form says XL and `work/sizing.json` says M: the claim is not written, and the refusal says what was measured."""
    root = temp_project("qa-claims-c2-")
    try:
        task = _c_story(root, sizing={"size": "M"})
        path = f"claims.{SIZE_CLAIM}"
        out, fixed, problems, _judged, derived, _art = _c_check(_filled(S2C, {"size.computed": "XL"}), S2C, task)
        check("K-C2: the claim is still blank", handoff.is_placeholder(out.get(path)))
        check_eq("K-C2: nothing was recorded as derived for it", [d for d in derived if d["field"] == path], [])
        said = [p for p in problems if p.path == path]
        check_eq("K-C2: one problem names it", len(said), 1)
        text = said[0].text if said else ""
        check_in("K-C2: it says code measured false, and the two sizes", "code measured this as false: the form says XL, work/sizing.json says M", text)
        check_in("K-C2: and names the door", "write false and name it in `unresolved`, or repair the work", text)
        check_eq("K-C2: it is not the `blank` kind (the guard does not excuse it)", said[0].kind if said else "x", "")
    finally:
        cleanup(root)


def a_claim_code_cannot_measure_stays_open_with_the_reason() -> None:
    """K-C3: no sizing file, an exception inside the verifier, or a verifier with no answer: the claim stays open with the
    reason and is never `true` (FR-59). The problem is the `blank` kind, so a role that cannot produce the word is excused
    by the guard and refused by `finish`."""
    import handoff_check as H
    root = temp_project("qa-claims-c3-")
    try:
        task = _c_story(root)
        path = f"claims.{SIZE_CLAIM}"
        doc = _filled(S2C, {"size.computed": "M"})
        out, _fixed, problems, _judged, derived, _art = _c_check(doc, S2C, task)
        said = [p for p in problems if p.path == path]
        check("K-C3: no sizing.json - the claim is still blank", handoff.is_placeholder(out.get(path)))
        check_eq("K-C3: and has no derived row", [d for d in derived if d["field"] == path], [])
        check_eq("K-C3: the problem is `blank` and says why code could not measure",
                 [(p.kind, p.text) for p in said],
                 [("blank", "not filled. code could not measure it: work/sizing.json holds no size; write your own word")])
        task = _c_story(root, sizing={"size": "M"})
        real = H.CLAIMS[SIZE_CLAIM]

        def raising(art):
            raise RuntimeError("the sizing file is on fire")

        for label, stub, reason in (("an exception", raising, "RuntimeError"), ("no answer", lambda art: None, "the verifier gave no answer")):
            H.CLAIMS[SIZE_CLAIM] = stub
            try:
                out, _fixed, problems, _judged, derived, _art = _c_check(doc, S2C, task)
            finally:
                H.CLAIMS[SIZE_CLAIM] = real
            said = [p for p in problems if p.path == path]
            check(f"K-C3 {label}: the claim is still blank (never `true`)", handoff.is_placeholder(out.get(path)))
            check_eq(f"K-C3 {label}: one `blank` problem names the reason",
                     [(p.kind, reason in p.text) for p in said], [("blank", True)])
            check_eq(f"K-C3 {label}: and nothing is derived for it", [d for d in derived if d["field"] == path], [])
        check_eq("K-C3 control: the real verifier is back and proves the claim",
                 _c_check(doc, S2C, task)[0].get(path), True)
    finally:
        cleanup(root)


def a_roles_own_false_is_never_overwritten() -> None:
    """K-C4: a claim the role answered `false` is not a placeholder - `--fix` does not ask the verifier and does not write."""
    root = temp_project("qa-claims-c4-")
    try:
        task = _c_story(root, sizing={"size": "M"})
        path = f"claims.{SIZE_CLAIM}"
        doc = _filled(S2C, {"size.computed": "M", path: False})
        out, fixed, problems, _judged, derived, _art = _c_check(doc, S2C, task)
        check_eq("K-C4: the role's `false` is still `false` after --fix", out.get(path), False)
        check_eq("K-C4: no derived row and no printed line for it",
                 ([d for d in derived if d["field"] == path], [f for f in fixed if path in f]), ([], []))
        check_eq("K-C4: and no problem (a `false` is an honest answer)", [p.path for p in problems if p.path == path], [])
    finally:
        cleanup(root)


def a_removed_claim_in_a_form_in_flight_is_accepted() -> None:
    """K-C5: five claims left their contracts. A form begun before still holds the line: `check` neither refuses it nor
    rewrites it (the rule 'not in the template is no refusal'), with and without --fix."""
    for contract, name in REMOVED_CLAIMS.items():
        check(f"K-C5: {contract} no longer holds {name}", f"claims.{name}" not in handoff.spec(contract))
        check("K-C5: and its text no longer names it", name not in (CONTRACTS / f"{contract}.yaml").read_text(encoding="utf-8"))
    root = temp_project("qa-claims-c5-")
    try:
        task = _c_story(root)
        saved = (FIXTURES / "s2-handoff-13877" / "work" / "handoffs" / "S2-qa-requirements-tester-1.yaml").read_text(encoding="utf-8")
        gone = f"claims.{REMOVED_CLAIMS[S2C]}"
        check("K-C5 control: the saved S2 form (13877) holds the removed key set to true", f"  {REMOVED_CLAIMS[S2C]}: true" in saved)
        for fix in (False, True):
            out, _fixed, problems, _judged, _derived, art = _c_check(handoff.parse(saved), S2C, task, fix=fix)
            paths = [p.path for p in problems]
            check_eq(f"K-C5 (fix={fix}): no problem names the removed key", [p for p in paths if p == gone], [])
            check_eq(f"K-C5 (fix={fix}): the key is still in the form, as the role wrote it", out.get(gone), True)
            check_eq(f"K-C5 (fix={fix}): the kept sizing claim (no work/sizing.json) is no problem, it is 'no verdict'",
                     ([p for p in paths if p == f"claims.{SIZE_CLAIM}"],
                      [(r["claim"], r["reason"]) for r in art.no_verdict if SIZE_CLAIM in r["claim"]]),
                     ([], [(f"claims.{SIZE_CLAIM}", "work/sizing.json holds no size")]))
        s6_removed = REMOVED_CLAIMS[S6A]
        text = handoff.template(S6A).text()
        anchor = "  every_row_carries_an_evidence_path: <true|false>\n"
        check("K-C5 control: the S6 template holds the anchor line", anchor in text)
        doc = handoff.parse(text.replace(anchor, anchor + f"  {s6_removed}: true\n"))
        for fix in (False, True):
            _out, _fixed, problems, _judged, _derived, _art = _c_check(doc, S6A, task, fix=fix)
            paths = [p.path for p in problems]
            check_eq(f"K-C5 S6 (fix={fix}): the removed key in a form in flight is no problem", [p for p in paths if s6_removed in p], [])
            check_in(f"K-C5 S6 (fix={fix}) control: a blank claim beside it is still refused", "claims.every_row_carries_an_evidence_path", paths)
    finally:
        cleanup(root)


def rollcall_the_claim_checks_the_ceiling_and_the_forms_n_of_m() -> None:
    """K-C6: `the_verdict_was_computed_by_rollcall_not_typed` against `critic_rollcall.derive` over the findings file."""
    root = temp_project("qa-claims-c6-")
    try:
        both = _rollcall_md(("TC-001", "yes"), ("TC-002", "yes"))
        one = _rollcall_md(("TC-001", "yes"), ("TC-002", "no"))
        task = _c_story(root, findings=one)
        form = {"review.outcome": "approved", "review.rollcall": "1 of 2 reviewed"}
        got = _verify(ROLLCALL_CLAIM, _filled(S4C, form), task)
        check_eq("K-C6 ceiling: approved over a case without a review is false", got[0], False)
        check_in("K-C6 ceiling: and says so, naming the case",
                 "the form says approved, and the roll-call leaves TC-002 without a review: the ceiling is partial", got[1])
        check_eq("K-C6 ceiling: the same digest does not save it (the digest is right: 1 of 2)", got[0], False)
        got = _verify(ROLLCALL_CLAIM, _filled(S4C, {"review.outcome": "approved"}), task)
        check_eq("K-C6 ceiling: and it is false before the digest is even read", got[0], False)
        task = _c_story(root, findings=both)
        got = _verify(ROLLCALL_CLAIM, _filled(S4C, {"review.outcome": "approved", "review.rollcall": "2 of 2 reviewed"}), task)
        check_eq("K-C6 match: the digest is what critic_rollcall computes - true", got[0], True)
        got = _verify(ROLLCALL_CLAIM, _filled(S4C, {"review.outcome": "approved", "review.rollcall": "1 of 2 reviewed"}), task)
        check_eq("K-C6 other digest: false, and both are named",
                 got, (False, "the form says 1 of 2 reviewed, critic_rollcall computes 2 of 2 reviewed"))
        got = _verify(ROLLCALL_CLAIM, _filled(S4C, {"review.outcome": "approved"}), task)
        check_eq("K-C6 digest not filled: no verdict (not a pass)", got, (None, "review.rollcall is not filled"))
        task = _c_story(root)
        (task / "work" / "test-cases" / "critic-findings.md").unlink(missing_ok=True)
        got = _verify(ROLLCALL_CLAIM, _filled(S4C, form), task)
        check_eq("K-C6 no file: no verdict, with the file named",
                 got, (None, "no roll-call rows in work/test-cases/critic-findings.md"))
        # the findings file the form names must stay inside the story, whatever it holds
        outside = root / "outside.md"
        outside.write_text(both, encoding="utf-8")
        for label, named in (("an absolute path", str(outside)), ("a `..` path", "../../../outside.md")):
            got = _verify(ROLLCALL_CLAIM, _filled(S4C, {**form, "review.findings_file": named}), task)
            check_eq(f"K-C6 {label} to a real roll-call outside the story: no verdict", got[0], None)
        # --fix: the digest is derived, then the claim is proved on it
        task = _c_story(root, findings=both)
        out, fixed, problems, _judged, derived, _art = _c_check(_filled(S4C, {"review.outcome": "approved"}), S4C, task)
        check_eq("K-C6 --fix: review.rollcall is written by code", out.get("review.rollcall"), "2 of 2 reviewed")
        check_eq("K-C6 --fix: and the claim is proved on it", out.get(f"claims.{ROLLCALL_CLAIM}"), True)
        check_in("K-C6 --fix: both are in derived", "review.rollcall",
                 [d["field"] for d in derived if d["source"] == "critic_rollcall.derive"])
    finally:
        cleanup(root)


def no_rollcall_rows_no_digest_written() -> None:
    """K-C6b: a findings file with no roll-call rows writes nothing: `0 of 0 reviewed` must never come out of an empty file."""
    import handoff_check as H
    root = temp_project("qa-claims-c6b-")
    try:
        for label, findings in (("no heading", "# Critic findings\n\nVerdict: approve\n"),
                                ("a heading and a table with no rows", "## Roll-call\n\n| plan row | case | reviewed |\n|---|---|---|\n")):
            task = _c_story(root, findings=findings)
            doc = _filled(S4C, {"review.outcome": "approved"})
            out, _fixed, problems, _judged, derived, art = _c_check(doc, S4C, task)
            check(f"K-C6b {label}: review.rollcall stays blank", handoff.is_placeholder(out.get("review.rollcall")))
            check_not_in(f"K-C6b {label}: `0 of 0` is nowhere in the form", "0 of 0", out.text())
            check_eq(f"K-C6b {label}: nothing is derived for it", [d for d in derived if d["field"] == "review.rollcall"], [])
            check_eq(f"K-C6b {label}: the deriver itself answers None", H._rollcall_digest(art, doc), None)
            said = [p for p in problems if p.path == f"claims.{ROLLCALL_CLAIM}"]
            check_eq(f"K-C6b {label}: the claim stays open, `blank`, with the reason",
                     [(p.kind, "no roll-call rows in work/test-cases/critic-findings.md" in p.text) for p in said], [("blank", True)])
    finally:
        cleanup(root)


def sizing_one_fix_fills_size_computed_and_then_proves_the_claim() -> None:
    """K-C7: both blank, `work/sizing.json` there: one --fix fills `size.computed` and then proves the claim on the filled
    field - in either order of the two sections (the claim is proved AFTER the field loop, on the form as it stands)."""
    root = temp_project("qa-claims-c7-")
    try:
        task = _c_story(root, sizing={"size": "L"})
        path = f"claims.{SIZE_CLAIM}"
        text = handoff.template(S2C).text()
        lines = text.splitlines()
        start = lines.index("claims:")
        end = next(i for i in range(start, len(lines)) if not lines[i].strip())
        block = lines[start:end]
        size_at = lines.index("size:")
        check("K-C7 control: in the contract the claims come after `size:`", start > size_at)
        above = lines[:size_at] + block + [""] + lines[size_at:start] + lines[end:]
        for label, form in (("claims below size", text), ("claims ABOVE size", "\n".join(above) + "\n")):
            doc = handoff.parse(form)
            check(f"K-C7 {label}: both are blank before",
                  handoff.is_placeholder(doc.get("size.computed")) and handoff.is_placeholder(doc.get(path)))
            if label.endswith("ABOVE size"):
                check("K-C7 control: the claims block really sits above size", doc.nodes[path].line < doc.nodes["size.computed"].line)
            out, _fixed, problems, _judged, derived, _art = _c_check(doc, S2C, task)
            check_eq(f"K-C7 {label}: size.computed and the claim are both filled",
                     (out.get("size.computed"), out.get(path)), ("L", True))
            check_eq(f"K-C7 {label}: both are recorded as derived",
                     sorted(d["field"] for d in derived if d["field"] in (path, "size.computed")), sorted([path, "size.computed"]))
            check_eq(f"K-C7 {label}: and neither is a problem", [p.path for p in problems if p.path in (path, "size.computed")], [])
    finally:
        cleanup(root)


def fingerprints_what_a_row_says_it_ran_must_be_on_disk() -> None:
    """K-C8: a row that states it ran needs a receipt that is a relative path inside the story and a file there."""
    root = temp_project("qa-claims-c8-")
    try:
        task = _c_story(root)
        (task / "evidence").mkdir()
        (task / "evidence" / "run1.txt").write_text("receipt", encoding="utf-8")
        outside = root / "outside.txt"
        outside.write_text("not in the story", encoding="utf-8")

        def rows(*items):
            out = ["scope:"]
            for item in items:
                for n, (key, value) in enumerate(item.items()):
                    out.append(("  - " if n == 0 else "    ") + f"{key}: {value}")
            return handoff.parse("\n".join(out) + "\n")

        placeholder = "<the run witness path, or a dash when it never ran>"
        got = _verify(FINGERPRINT_CLAIM, handoff.parse(handoff.template(S5R).text()), task)
        check_eq("K-C8 template row (placeholders): no verdict", got, (None, "no instance row states its freshness"))
        for label, receipt in (("a placeholder receipt", placeholder), ("a missing file", "evidence/gone.txt"), ("a dash", "-"),
                               ("an absolute path to a file that exists", str(task / "evidence" / "run1.txt")),
                               ("a `..` path to a file that exists", "../../../outside.txt")):
            got = _verify(FINGERPRINT_CLAIM, rows({"id": "T-1", "freshness": "fresh", "last_receipt": receipt}), task)
            check_eq(f"K-C8 fresh + {label}: false, and the instance is named",
                     got, (False, "1 instance(s) say they ran and carry no receipt on disk: T-1"))
        got = _verify(FINGERPRINT_CLAIM, rows({"id": "T-2", "freshness": "stale", "last_receipt": "evidence/gone.txt"}), task)
        check_eq("K-C8 stale + a missing file: false too (stale also ran)", got[0], False)
        got = _verify(FINGERPRINT_CLAIM, rows({"id": "T-3", "freshness": "maybe", "last_receipt": "-"}), task)
        check_eq("K-C8 a word outside the list needs a receipt too: false", got[0], False)
        got = _verify(FINGERPRINT_CLAIM, rows({"id": "T-4", "freshness": "fresh", "last_receipt": "evidence/run1.txt"},
                                              {"id": "T-5", "freshness": "never_run", "last_receipt": "-"}), task)
        check_eq("K-C8 fresh + an existing relative file, and never_run + a dash: true", got[0], True)
        got = _verify(FINGERPRINT_CLAIM, rows({"id": "T-4", "freshness": "fresh", "last_receipt": "evidence/run1.txt"},
                                              {"id": "T-6", "freshness": "fresh", "last_receipt": "evidence/gone.txt"},
                                              {"id": "T-5", "freshness": "never_run", "last_receipt": "-"}), task)
        check_eq("K-C8 one bad row among good ones: false, naming only the bad row",
                 got, (False, "1 instance(s) say they ran and carry no receipt on disk: T-6"))
        got = _verify(FINGERPRINT_CLAIM, rows({"id": "T-4", "freshness": "fresh", "last_receipt": "evidence/run1.txt"},
                                              {"id": "T-7", "freshness": "<one of vocabulary.freshness_states>",
                                               "last_receipt": placeholder}), task)
        check_eq("K-C8 a row that states nothing is skipped; the stated one holds: true", got[0], True)
        doc = _filled(S5R, {"scope[0].id": "T-8", "scope[0].freshness": "never_run", "scope[0].last_receipt": "-"})
        out, fixed, _problems, _judged, derived, _art = _c_check(doc, S5R, task)
        check_eq("K-C8 --fix: the claim is proved on the form's own row and written", out.get(f"claims.{FINGERPRINT_CLAIM}"), True)
    finally:
        cleanup(root)


def the_judge_is_never_asked_for_a_claim() -> None:
    """K-C9: with a judge configured and answering yes to anything, a blank claim is still filled by its verifier or left open;
    the stub is never called for it. The control shows the stub IS reachable by the same call (a state word outside its list)."""
    import handoff_check as H
    calls = []

    class Judge:
        @staticmethod
        def active():
            return True

        @staticmethod
        def ask(state, questions, **kwargs):
            calls.append(state)
            return {"status": "ok", "answers": {"q": {"value": True, "decided": True, "confidence": 1.0}}}

    root = temp_project("qa-claims-c9-")
    saved = H.judge
    H.judge = Judge
    try:
        task = _c_story(root)
        out, _fixed, problems, judged, _derived, _art = _c_check(_filled(S2C, {"size.computed": "M"}), S2C, task, judge=True)
        path = f"claims.{SIZE_CLAIM}"
        check_eq("K-C9: the judge was not asked at all for the form with blank claims", calls, [])
        check_eq("K-C9: and nothing was recorded as judged", judged, [])
        check("K-C9: the claim code cannot measure stays blank", handoff.is_placeholder(out.get(path)))
        check_in("K-C9: and is refused with the reason", path, [p.path for p in problems])
        weird = _filled(S5R, {"scope[0].state": "weirdword"})
        _c_check(weird, S5R, task, judge=True)
        check("K-C9 control: the same stub IS asked for a state word outside its list", len(calls) >= 1, str(calls))
    finally:
        H.judge = saved
        cleanup(root)


S3_FORM = "s3-strategist-to-designer"
S3_GROUNDING_CLAIMS = ("every_hunk_of_the_diff_has_a_grounding_row", "every_register_requirement_has_a_grounding_line",
                       "every_risk_and_uncovered_area_reaches_a_row_or_not_planned", "every_area_that_matters_has_regression_or_a_gap",
                       "refactoring_share_computed_by_code")


def the_s3_form_carries_the_grounding_and_its_claims_are_the_gates() -> None:
    """G1-5: the S3 form names the table as an input, `not_planned[].ref`, the code-filled `grounding` / `blast_radius`, and five claims.
    Each verifier is ONE call into `grounding_table` (no logic of its own, FR-10): a stand-in for that call decides the claim, and `None`
    (no verdict) is carried as it is."""
    import handoff_check as H
    import grounding_table as GT
    raw = (CONTRACTS / f"{S3_FORM}.yaml").read_text(encoding="utf-8")
    spec = handoff.spec(S3_FORM)
    check_in("G1-5 the table is an input of the form", "path: work/grounding.yaml", raw)
    check("G1-5 `not_planned` holds `ref`, and `requirement` is gone from it", "not_planned[].ref" in spec and "not_planned[].requirement" not in spec, str(sorted(spec))[:200])
    check("G1-5 `grounding` and `blast_radius` are sections of the form, code's and optional (a role may leave them out)",
          all(spec[p].optional for p in ("grounding.hunks", "grounding.road", "blast_radius[]")), "")
    check("G1-5 the form has no `grounding.decision`: the stop's word is G2-2's", "grounding.decision" not in spec, "")
    for name in S3_GROUNDING_CLAIMS:
        check(f"G1-5 claim {name} is on the form and has a verifier", f"claims.{name}" in spec and name in H.CLAIMS, name)
    check("G1-5 code fills `grounding.*` and `blast_radius` (AR-22: a producer for each field of the form)",
          all(f"grounding.{n}" in H.DERIVERS for n in ("hunks", "rows_cover", "requirements_cover", "refactoring_percent", "road"))
          and "blast_radius" in H.LIST_DERIVERS, "")
    real = GT.claim_view
    seen = []
    try:
        for verdict in ((True, "yes"), (False, "no"), (None, "unknown")):
            GT.claim_view = lambda root, *a, **k: seen.append((a, k)) or verdict
            with tempfile.TemporaryDirectory() as tmp:
                art = H.Artifacts(Path(tmp))
                got = [H.CLAIMS[n](art) for n in S3_GROUNDING_CLAIMS[:2] + S3_GROUNDING_CLAIMS[3:4]]
            check_eq(f"G1-5 the claims of the table return what grounding_table.claim_view says: {verdict}", got, [verdict] * 3)
        with tempfile.TemporaryDirectory() as tmp:
            art = H.Artifacts(Path(tmp))
            check_eq("G1-5 the reach claim has no verdict (None) while there is no plan", H.CLAIMS[S3_GROUNDING_CLAIMS[2]](art)[0], None)
            plan = Path(tmp) / "work" / "test-plan.json"
            plan.parent.mkdir()
            plan.write_text(json.dumps({"rows": [{"id": "TS-1"}]}), encoding="utf-8")
            GT.claim_view = lambda root, rules=(), **k: (k.get("plan_rows") == [{"id": "TS-1"}], "with the plan")
            check_eq("G1-5 ...and with the plan it asks the gate's function with the plan rows",
                     H.CLAIMS[S3_GROUNDING_CLAIMS[2]](H.Artifacts(Path(tmp)))[0], True)
    finally:
        GT.claim_view = real
    with tempfile.TemporaryDirectory() as tmp:
        art = H.Artifacts(Path(tmp))
        check_eq("G1-5 refactoring_share claim: no table -> no verdict (None)", H.CLAIMS[S3_GROUNDING_CLAIMS[4]](art)[0], None)
        check_eq("G1-5 the code-filled fields give nothing off a diff (no invented value)",
                 (H.DERIVERS["grounding.hunks"](art, None), H.LIST_DERIVERS["blast_radius"](art, None)), (None, None))
    # the real path (no stand-in): the stored key is compared WHOLE with what the code computes now (G1-5 fix round, F-5)
    import planning_contract as PC
    policy, _why = PC.grounding_policy()
    label = policy["numerator_labels"][0]
    with tempfile.TemporaryDirectory() as tmp:
        art = H.Artifacts(Path(tmp))
        claim = H.CLAIMS[S3_GROUNDING_CLAIMS[4]]
        data = {"schema_version": 1, "implementation_source": "diff", "hunks": [{"id": "h0", "file": "src/a.py", "added": 3, "removed": 0, "pseudo": ""}],
                "rows": [{"id": "G-0", "hunks": "h0", "label": label, "reason": "ok"}]}
        GT.write_yaml(GT.table_path(Path(tmp)), data)
        check_eq("G1-5 refactoring_share claim: a table with no `refactoring_share` -> None", claim(art)[0], None)
        stored = GT.share(data, policy, GT.check(Path(tmp)))
        for name, key, want in (("what the code computes -> True", stored, True),
                                ("an edited percent -> False", dict(stored, percent="1.0"), False),
                                ("an empty mapping -> False, not a pass on nothing to compare", {}, False),
                                ("a key the code does not compute, the rest equal -> False", dict(stored, note="typed"), False)):
            GT.write_yaml(GT.table_path(Path(tmp)), dict(data, refactoring_share=key))
            check_eq(f"G1-5 refactoring_share claim, the real path: {name}", claim(H.Artifacts(Path(tmp)))[0], want)


def main() -> None:
    a_row_may_name_the_purpose_it_serves_and_the_window_contract_stays_what_it_was()
    the_plan_handovers_carry_what_the_readers_read()
    the_window_form_gains_two_optional_sections_and_the_0102_form_still_passes()
    the_null_outcome_audit_is_green_over_the_index_with_the_purpose_rows()
    a_claim_code_proves_is_filled_true_and_recorded_in_derived()
    a_claim_code_measures_false_stays_open_with_the_door()
    a_claim_code_cannot_measure_stays_open_with_the_reason()
    a_roles_own_false_is_never_overwritten()
    a_removed_claim_in_a_form_in_flight_is_accepted()
    rollcall_the_claim_checks_the_ceiling_and_the_forms_n_of_m()
    no_rollcall_rows_no_digest_written()
    sizing_one_fix_fills_size_computed_and_then_proves_the_claim()
    fingerprints_what_a_row_says_it_ran_must_be_on_disk()
    the_judge_is_never_asked_for_a_claim()
    the_implementation_checkout_has_one_survivor_and_never_asks_for_an_empty_id()
    the_bug_draft_claim_gives_no_verdict_on_a_folder_it_cannot_list()
    the_bug_draft_claim_reads_the_json_drafts()
    the_bug_draft_claim_reads_the_manifestations()
    two_fields_cut_at_once_and_a_later_cut_of_another_field_keeps_the_first_row()
    a_field_over_its_limit_is_cut_by_code_with_the_whole_text_kept()
    length_is_cut_only_when_it_is_the_forms_only_problem()
    the_claim_is_replaced_and_the_comment_is_true()
    an_owed_pair_without_a_record_makes_the_claim_false()
    a_record_or_a_persons_word_makes_it_hold()
    an_unmeasured_detector_gives_no_verdict()
    an_owed_pair_beats_an_unmeasured_corner()
    nothing_to_measure_holds_and_is_never_refused()
    a_form_initialised_before_this_change_is_not_refused()
    the_detector_runs_once_per_check()
    the_same_fact_derives_under_the_same_name()
    the_folder_and_the_index_agree()
    every_contract_parses_and_carries_the_shape()
    the_vocabulary_is_the_single_list()
    the_grounding_vocabulary_line_is_one_builder_and_never_blank()
    the_schema_comes_from_the_contract()
    a_refusal_names_the_roles_own_words()
    a_form_is_written_and_then_repaired_by_code()
    a_word_outside_the_list_is_refused_with_the_list()
    what_cannot_be_filled_goes_to_the_conductor()
    a_blocked_row_says_what_blocks_it()
    the_judged_values_are_recorded_in_the_form()
    a_row_the_judge_can_answer_from_its_own_contents()
    a_value_written_into_a_row_keeps_the_row()
    a_tooling_finding_is_not_a_round_for_the_author()
    the_diff_counts_read_the_production_rule()
    an_exited_s2_key_is_read_in_any_shape()
    a_section_owed_only_under_a_header_value_has_an_empty_outcome_otherwise()
    the_s2_field_and_the_s3_gate_never_live_together()
    the_s3_form_carries_the_grounding_and_its_claims_are_the_gates()
    no_form_text_claims_a_count_check_that_does_not_run()
    the_diff_counts_read_every_recorded_diff()
    the_production_rule_reads_the_projects_word_from_the_implementation_checkout()
    finish("test_handoff")


if __name__ == "__main__":
    main()
