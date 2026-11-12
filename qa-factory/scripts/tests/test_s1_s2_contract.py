#!/usr/bin/env python3
"""What S0-S2 order a Sonnet orchestrator to do, and what the code actually answers.

0.7.7 review, findings A-F3, A-F4, A-F6, A-F7, A-F10, A-F12, and the owner's decision on tracker reads. Each of
these was a phase file naming a thing no command produced, or a script demanding a thing the
phase file never wrote:

- A-F3 s1.md's ONE planned stop said "checkpoint the dispatch (blocked, ...)" and the only
  route was a hand-written JSON file that s0.md forbids.
- A-F4 the scout's three charter halts all fire BEFORE the step that writes the manifest, and
  the exit gate blocked the handoff for a missing manifest — while telling the role to "hand
  the orchestrator a halt instead".
- A-F6 `sizing.py` caps a defect ticket at one regression case from `issue_type`, a key no
  contract mentioned and nobody wrote: every bug was sized as a feature.
- A-F7 `understanding.md` quotes `work/sizing.json` and nothing had written it yet.
- A-F10 with no stand configured, s1.md asked "which stand: <names>?" with an empty list.
- A-F12 a bad `--source-ref` reached the orchestrator as a Python traceback.
- reading a tracker through a session agent returns no attachments and no related
  tickets; the read route is `direct_api` and the refusal says so.
"""
import hashlib
import io
import json
import sys
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, run_script, temp_dir, temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import exit_gate  # noqa: E402
import sizing  # noqa: E402
import ticket_adapter  # noqa: E402
from controller import Controller  # noqa: E402
from environment_selection import select_environment  # noqa: E402


# --- A-F3: the S1 stop has a runnable command --------------------------------------------

def the_s1_stop_is_checkpointed_by_flags():
    root = temp_project("qa-s1-checkpoint-")
    try:
        controller = Controller(root)
        controller.apply("initialize", {"scope": [], "source_revision": "src-1",
                                        "known_paths": {"root": str(root)},
                                        "idempotency_key": "init"})
        evidence = root / "preflight.txt"
        evidence.write_text("preflight green", encoding="utf-8")
        controller.apply("code_only", {
            "id": "s0", "stage": "S0", "reason": "no role runs preflight",
            "evidence_refs": [{"path": "preflight.txt",
                               "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
            "idempotency_key": "code-only-S0"})
        controller.apply("dispatch", {"id": "dS1", "stage": "S1", "role": "qa-scout",
                                      "scope": [], "input_hash": "S1", "budget": {},
                                      "known_paths": {}, "idempotency_key": "dispatch-S1"})
        request = controller.build_checkpoint_request(
            None, "blocked", "source review awaiting the person",
            "record the answer; collect the kept sources")
        check_eq("the one running dispatch is found without an id",
                 request["id"], "dS1")
        check_eq("the status is the person-facing one", request["status"], "blocked")
        check_eq("remaining work is split on ';'", request["checkpoint"]["remaining"],
                 ["record the answer", "collect the kept sources"])
        controller.apply("checkpoint", dict(request))
        after = controller.state()["dispatches"]["dS1"]
        check_eq("and the controller records it", after["status"], "blocked")
        check_eq("with the reason the person will read back",
                 after["reason"], "source review awaiting the person")
        check_eq("`next` then offers to resume that checkpoint",
                 controller.next_action()["action"], "resume_checkpoint")
        for status, why in (("accepted", "--operation accept"), ("finished", "must be one of")):
            err = ""
            try:
                controller.build_checkpoint_request("dS1", status, "x")
            except ValueError as exc:
                err = str(exc)
            check_in(f"`--status {status}` is refused with the route that fits", why, err)
    finally:
        cleanup(root)


# --- A-F4: a halt is a handoff, not an incomplete one ------------------------------------

def a_halt_digest_is_exempt_from_required_outputs():
    check("a scout halt is recognised as a halt",
          exit_gate.is_halting_handoff(
              "qa-scout S1 halt · work/source-inventory.json · no diff — give --mr"))
    check("so is an impossible digest",
          exit_gate.is_halting_handoff("qa-requirements-tester S2 impossible · x · y"))
    check("a done digest is not",
          not exit_gate.is_halting_handoff("qa-scout S1 done · work/manifest.json · 12 sources"))
    check("and neither is prose that merely contains the word",
          not exit_gate.is_halting_handoff("I will halt if the tracker is unreachable"))

    root = temp_project("qa-halt-exempt-")
    try:
        use_project(root)
        art = root / "qa-factory" / "artifacts" / "QA-1"
        (art / "work").mkdir(parents=True, exist_ok=True)
        (art / "pipeline.json").write_text(json.dumps({
            "ticket": "QA-1", "stages": {"S0": {"status": "done"},
                                         "S1": {"status": "running"}}, "gates": {}}),
            encoding="utf-8")
        old_root = exit_gate.artifact_root
        exit_gate.artifact_root = lambda: root / "qa-factory" / "artifacts"
        try:
            missing = exit_gate.required_outputs_errors("qa-scout", "QA-1")
            check("without a digest the missing manifest is still an error", bool(missing))
            blocking, _ = exit_gate.all_errors("qa-scout", "QA-1")
            check("and it blocks the handoff", bool(blocking))
            blocking, _ = exit_gate.all_errors(
                "qa-scout", "QA-1",
                "qa-scout S1 halt · work/source-inventory.json · AC/code conflict: \"a\" vs \"b\"")
            check_eq("a halt hands the decision back instead of being refused", blocking, [])
            blocking, _ = exit_gate.all_errors(
                "qa-scout", "QA-1",
                "qa-scout S1 halt · work/source-inventory.json · requirement/code conflict: \"a\" vs \"b\"")
            check_eq("G1-0: the same halt under its new token (any requirement against the code) is a halt too - the token is not read, "
                     "the word `halt` is", blocking, [])
        finally:
            exit_gate.artifact_root = old_root
    finally:
        cleanup(root)


def the_digest_is_read_from_the_transcript():
    root = temp_dir("qa-halt-transcript-")
    try:
        transcript = root / "agent-x.jsonl"
        transcript.write_text("\n".join(json.dumps(record) for record in [
            {"type": "user", "message": {"content": "You are qa-scout. Ticket: QA-1."}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "working"}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "qa-scout S1 halt · work/x.json · no diff"}]}},
        ]), encoding="utf-8")
        digest = exit_gate.handoff_digest({"transcript_path": str(transcript)})
        check_in("the role's LAST word is the digest", "halt", digest)
        check("which the gate then reads as a halt", exit_gate.is_halting_handoff(digest))
        check_eq("a host that sends no transcript changes nothing",
                 exit_gate.handoff_digest({}), "")
        check_eq("nor does an unreadable one",
                 exit_gate.handoff_digest({"transcript_path": str(root / "gone.jsonl")}), "")
    finally:
        cleanup(root)


# --- A-F6 / A-F7: the size is computed from the ticket's own type, by the role ------------

REGISTER = ("# Requirements\n\n| ID | Requirement | Source | Observable in code | Impact |\n"
            "|---|---|---|---|---|\n"
            "| R-1 | the field rejects an empty value | ac | src/a.py:10 | blocked-flow |\n"
            "| R-2 | the error names the field | ac | src/a.py:14 | degraded |\n")


def a_bug_ticket_is_sized_as_a_bug():
    root = temp_project("qa-sizing-issue-type-")
    try:
        work = root / "work"
        work.mkdir(parents=True, exist_ok=True)
        (work / "requirements-register.md").write_text(REGISTER, encoding="utf-8")
        (work / "context-manifest.json").write_text(json.dumps({
            "ticket": root.name, "acceptance_criteria": [], "implementation": {"source": "diff"},
        }), encoding="utf-8")
        feature = sizing.run(root)
        check_in("with no issue_type the cap is not even evaluated",
                 "the defect-ticket cap was not evaluated", feature["reasoning"])

        manifest = json.loads((work / "context-manifest.json").read_text(encoding="utf-8"))
        manifest["issue_type"] = "Bug"
        (work / "context-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        defect = sizing.run(root)
        check_eq("the scout's issue_type caps a defect at one regression case",
                 defect["computed_budget"], 1)
        check_in("and the arithmetic says why", "defect ticket — capped",
                 defect["reasoning"])
    finally:
        cleanup(root)


def the_roles_size_override_survives_the_detector_rerun():
    root = temp_project("qa-sizing-override-")
    try:
        work = root / "work"
        work.mkdir(parents=True, exist_ok=True)
        (work / "requirements-register.md").write_text(REGISTER, encoding="utf-8")
        written = sizing.run(root, size_override="XL", size_override_reason="two teams")
        check_eq("the role records its objection in the documented field",
                 written["size_override"], "XL")
        again = sizing.run(root)
        check_eq("the S2 exit detector re-verifies and does not erase it",
                 (again["size_override"], again["size_override_reason"]), ("XL", "two teams"))
        on_disk = json.loads((work / "sizing.json").read_text(encoding="utf-8"))
        check_eq("and gate A reads it off disk", on_disk["size_override"], "XL")
    finally:
        cleanup(root)


# --- A-F10: an empty environments[] is not a question --------------------------------------

def an_empty_stand_list_is_not_an_empty_question():
    answer = select_environment({"environments": []})
    check_eq("it is still a question_required", answer["status"], "question_required")
    check("but the phase file can tell the two apart",
          answer["no_environments_configured"] is True)
    check_eq("with nothing to offer", answer["choices"], [])
    two = select_environment({"environments": [{"name": "dev"}, {"name": "stage"}]})
    check("a real choice is not flagged as none configured",
          two["no_environments_configured"] is False)
    check_eq("and it does carry the names", two["choices"], ["dev", "stage"])


# --- t-017 D2: the stand is a warning at S0 and a question before S5/S6 ---------------------
# The phase files and the contract say what story_run.py does. The keys below are the DoD's own words,
# fixed BEFORE the run; the negative control proves the check can fail.

# --- A-F12: a bad source ref is a refusal, not a traceback --------------------------------

def a_bad_source_ref_is_refused_in_words():
    result = run_script("source_preflight.py", "--repo", str(SCRIPTS / "nowhere"),
                        "--source-ref", "deadbeef", "--task", "QA-1")
    check_eq("the command exits with a refusal code", result.returncode, 2)
    check_not_in("no traceback reaches the orchestrator", "Traceback", result.stderr)
    check_in("the error says what was wrong", "repository", result.stderr)
    check_in("and where a real source ref comes from", "--source-ref", result.stderr)


# --- reading a tracker is direct_api, and nothing else -------------------------------

def an_agent_read_route_is_refused_with_the_one_that_works():
    for method in ("agent", "skill"):
        err = io.StringIO()
        code = None
        try:
            with redirect_stderr(err):
                ticket_adapter.get_ticket("QA-1", {"adapters": {"ticket": {
                    "name": "jira", "method": method, "invoke": "jira-assistant"}}})
        except SystemExit as exc:
            code = exc.code
        message = err.getvalue()
        check_eq(f"a {method} read route exits 3", code, ticket_adapter.EXIT_NOT_CONFIGURED)
        check_in("naming the route that works", "direct_api", message)
        check_in("and the command that records it", "qa-onboarding", message)
        check_in("and saying why, in facts", "attachment", message)
        check_in("while keeping the write channel", "external_writes", message)
        check_not_in("and never sending anyone to relay the ticket by hand",
                     "ticket-snapshot.md", message)


# --- D-F1 neighbour: a configured case store is where the cases are ----------------------

def a_configured_cases_root_is_where_s4s_output_lives():
    """`config.cases_root` moves the store out of the story tree; S4's declared
    `work/test-cases/` is then missing forever and no handoff after it can close."""
    root = temp_project("qa-cases-root-")
    try:
        use_project(root)
        config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        config["cases_root"] = "tests/cases"
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        art = root / "qa-factory" / "artifacts" / "QA-1"
        (art / "work").mkdir(parents=True, exist_ok=True)
        (art / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "stages": {}}),
                                           encoding="utf-8")
        store = root / "tests" / "cases"
        store.mkdir(parents=True, exist_ok=True)
        (store / "TC-1.md").write_text("# TC-1\n", encoding="utf-8")
        check("the project's own store answers for work/test-cases/",
              exit_gate._output_present(art, "work/test-cases/"))
        check_eq("and it is the configured path, not the story's",
                 exit_gate._output_path(art, "work/test-cases/").resolve(), store.resolve())
    finally:
        cleanup(root)


def the_no_diff_source_is_one_reader_of_three_shapes():
    """C1-3 (G11): `handoff_check.manifest_impl_source` reads the summary `implementation.source`, the list
    `implementations[].source` and the top-level `implementation_source` - ONE reader, so `none` is visible to the handover
    form check and to the driver's no-diff question. AT each shape, and the shapes that must read as nothing."""
    import handoff_check
    read = handoff_check.manifest_impl_source
    check_eq("A summary `implementation.source: none` is read", read({"implementation": {"source": "none"}}), "none")
    check_eq("the first entry of `implementations[]` is read", read({"implementations": [{"repo": "a", "source": "none"}]}), "none")
    check_eq("the older top-level `implementation_source` is read", read({"implementation_source": "none"}), "none")
    check_eq("the summary wins over the list and the list over the top level",
             read({"implementation": {"source": "diff"}, "implementations": [{"source": "none"}], "implementation_source": "none"}), "diff")
    check_eq("a manifest that names none reads as '' (not 'none')", read({"implementation": {}}), "")
    for label, bad in (("a list", []), ("None", None), ("a string", "none"), ("an `implementation` that is a string", {"implementation": "none"}),
                       ("an `implementations` that is a dict", {"implementations": {"source": "none"}}),
                       ("a first entry that is not an object", {"implementations": ["none"]})):
        check_eq(f"NEGATIVE: {label} reads as ''", read(bad), "")


# --- G1-10 (grounding/1): the role text says what the code does, one verdict per place ------
# The role texts of K1-K15 (spec t-1211 section 3) are rows of design/role-rules.json; the couplings to code data stay here.

def fr21_row_mismatch(row: str, doc: dict) -> list:
    """Does the FR-21 debt row claim what the kinds file says? The row claims the `pending_implementation` half when it holds
    `**narrowed` and `pending_implementation`; the file says it when that state's kind has the verdict `no`. A claim without the
    data, or the data without the claim, is a mismatch. A verdict the file cannot give (None) is an unknown: FR-59 - it fails."""
    import delivery_verdict as DV
    verdict = DV.verdict_of_kind(DV.kind_of_state("pending_implementation", doc), doc)
    if verdict is None:
        return ["the kinds file gives no verdict for pending_implementation (an unknown is not a pass)"]
    claims = "**narrowed" in row and "pending_implementation" in row
    if claims != (verdict == "no"):
        return [f"the row {'claims' if claims else 'does not claim'} pending_implementation blocks; the file says `{verdict}`"]
    return []


def role_text_says_what_the_code_does():
    import copy
    import contract as C
    import delivery_verdict as DV
    import stage_done
    plugin = SCRIPTS.parent
    # coupling (a): the FR-21 row against the kinds file (a constant read, not a phrase; hygiene 7 (d): a COPY is corrupted)
    doc, problem = DV.load_kinds()
    check_eq("G1-10: the kinds file is readable", problem, "")
    rows = [line for line in (plugin / "design/factory-rules-debt.md").read_text(encoding="utf-8").splitlines()
            if line.startswith("| FR-21 |")]
    check_eq("G1-10: the debt file holds exactly one FR-21 row", len(rows), 1)
    check_eq("G1-10: the FR-21 row says what the kinds file says", fr21_row_mismatch(rows[0], doc), [])
    flipped = copy.deepcopy(doc)
    flipped["kinds"]["pending_implementation"]["verdict"] = "none"
    check("G1-10: the coupling reports a mismatch when the file says `none` (control)", fr21_row_mismatch(rows[0], flipped) != [])
    gone = copy.deepcopy(doc)
    del gone["kinds"]["pending_implementation"]
    check("G1-10: a verdict the file cannot give fails the coupling (FR-59)", fr21_row_mismatch(rows[0], gone) != [])
    # coupling (b): the two words the scout and the tester now use are the words the pipeline accepts
    check_in("G1-10: `ungrounded` is a settable pipeline value", "ungrounded", stage_done.SETTABLE["implementation_source"])
    check_in("G1-10: `none` is a manifest implementation source", "none", C.IMPLEMENTATION_SOURCES)


def main():
    the_s1_stop_is_checkpointed_by_flags()
    a_configured_cases_root_is_where_s4s_output_lives()
    a_halt_digest_is_exempt_from_required_outputs()
    the_digest_is_read_from_the_transcript()
    a_bug_ticket_is_sized_as_a_bug()
    the_roles_size_override_survives_the_detector_rerun()
    an_empty_stand_list_is_not_an_empty_question()
    a_bad_source_ref_is_refused_in_words()
    an_agent_read_route_is_refused_with_the_one_that_works()
    the_no_diff_source_is_one_reader_of_three_shapes()
    role_text_says_what_the_code_does()
    finish("S1-S2 contract")


if __name__ == "__main__":
    main()
