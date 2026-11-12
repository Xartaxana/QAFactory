"""external_writes.py — the deterministic post-gate-B executor. Its own --selftest already
covers the four mandatory scenarios (markdown no-op, refusal before gate B, idempotent
skip, write-scope refusal) end to end with an in-process fake tool; this file runs it as a
subprocess (the way run-py.cmd actually invokes it) and adds the cases channel's
preview/--yes split and the CLI usage errors, which --selftest does not touch."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import check, check_eq, check_in, cleanup, finish, run_script, temp_project  # noqa: E402


def run_ew(root: Path, *args):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    return run_script("external_writes.py", *args, env=env)


def write_config(root: Path, external_writes: dict) -> None:
    cfg_path = root / "qa-factory" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["external_writes"] = external_writes
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")


def make_ticket(root: Path, ticket: str, gate_b: bool) -> Path:
    art = root / "qa-factory" / "artifacts" / ticket
    (art / "proposals").mkdir(parents=True)
    pipeline = {"ticket": ticket, "gates": ({"B": {"decision": "approve"}} if gate_b else {})}
    (art / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    return art


def main() -> None:
    # --- the script's own --selftest, run as a subprocess -----------------------------------
    p = run_script("external_writes.py", "--selftest")
    check_eq("--selftest: exit 0", p.returncode, 0)
    check_in("--selftest: reports PASSED", "PASSED", p.stdout)

    # --- CLI usage: no ticket, no --selftest -> a clean usage error, not a crash ------------
    p = run_script("external_writes.py")
    check_eq("no ticket, no --selftest: exit 2", p.returncode, 2)
    check_in("no ticket: says a ticket id is required", "ticket id is required", p.stderr)

    # --- cases channel: preview by default, --yes required to execute ------------------------
    root = temp_project("qa-factory-external-writes-cases-")
    try:
        (root / "qa-factory" / "test-cases" / "tags").mkdir(parents=True)
        make_ticket(root, "QA-1", gate_b=True)
        stub_dir = root / "ew-stub"
        stub_dir.mkdir(exist_ok=True)
        calls_log = stub_dir / "calls.log"
        stub = stub_dir / "stub_tms.py"
        stub.write_text(
            "import sys, json\n"
            f"open({json.dumps(str(calls_log))}, 'a', encoding='utf-8').write(sys.argv[1] + chr(10))\n"
            "print(json.dumps({'external_id': 'XRAY-1', 'url': 'http://tms.example/XRAY-1'}))\n",
            encoding="utf-8",
        )
        write_config(root, {
            "bugs": "markdown", "cases": "xray",
            "write_scopes": ["create_case", "update_case"],
            "commands": {"xray": [sys.executable, str(stub)]},
        })
        case_file = root / "qa-factory" / "test-cases" / "tags" / "TC-001.md"
        case_file.write_text("# TC-001\n\nTags round-trip.\n", encoding="utf-8")
        proposal_path = root / "qa-factory" / "artifacts" / "QA-1" / "proposals" / "case-1.json"
        proposal_path.write_text(json.dumps({
            "kind": "case", "case_file": "test-cases/tags/TC-001.md", "action": "create",
            "fields": {"title": "Tags round-trip"}, "witness": {"note": "from test-plan row TS-1"},
        }), encoding="utf-8")

        # default (no --preview, no --yes): preview only, nothing executed
        p = run_ew(root, "QA-1")
        check_eq("cases default: exit 0", p.returncode, 0)
        check_in("cases default: previewed, not executed", "PREVIEW", p.stdout)
        check_in("cases default: tells the caller to pass --yes", "--yes", p.stdout)
        check("cases default: the stub was not invoked", not calls_log.exists())

        # --preview explicitly: same as default
        p = run_ew(root, "QA-1", "--preview")
        check_in("cases --preview: still just a preview", "PREVIEW", p.stdout)
        check("cases --preview: the stub was not invoked", not calls_log.exists())

        # --yes: actually executes, records external_id into the case file and the proposal
        p = run_ew(root, "QA-1", "--yes")
        check_eq("cases --yes: exit 0", p.returncode, 0)
        check_in("cases --yes: performed", "OK", p.stdout)
        check("cases --yes: the stub was invoked", calls_log.exists())
        case_text = case_file.read_text(encoding="utf-8")
        check_in("cases --yes: case file got external_id", "XRAY-1", case_text)
        proposal_after = json.loads(proposal_path.read_text(encoding="utf-8"))
        check_eq("cases --yes: proposal recorded a result",
                 proposal_after.get("result", {}).get("external_id"), "XRAY-1")

        # re-run with --yes: idempotent, the stub is not called again
        calls_before = calls_log.read_text(encoding="utf-8").splitlines()
        p = run_ew(root, "QA-1", "--yes")
        check_eq("cases re-run --yes: exit 0", p.returncode, 0)
        check_in("cases re-run --yes: skipped", "SKIP", p.stdout)
        calls_after = calls_log.read_text(encoding="utf-8").splitlines()
        check_eq("cases re-run --yes: the stub was not invoked again", len(calls_after), len(calls_before))
    finally:
        cleanup(root)

    # --- cases channel with no command configured: NOT_CONFIGURED, never a crash -----------
    root = temp_project("qa-factory-external-writes-notconfigured-")
    try:
        make_ticket(root, "QA-1", gate_b=True)
        write_config(root, {"bugs": "markdown", "cases": "testrail",
                            "write_scopes": ["create_case", "update_case"]})
        proposal_path = root / "qa-factory" / "artifacts" / "QA-1" / "proposals" / "case-1.json"
        proposal_path.write_text(json.dumps({
            "kind": "case", "case_file": "test-cases/x/TC-002.md", "action": "create",
            "fields": {}, "witness": {},
        }), encoding="utf-8")
        p = run_ew(root, "QA-1", "--yes")
        check_eq("no command configured: exit 0 (NOT_CONFIGURED is not a failure)", p.returncode, 0)
        check_in("no command configured: says so by name", "NOT_CONFIGURED", p.stdout)
    finally:
        cleanup(root)

    # --- an agent-delivered bugs channel: exit 4, a payload, and --record --------------------
    root = temp_project("qa-factory-external-writes-agent-")
    try:
        (root / "qa-factory" / "bugs").mkdir(parents=True, exist_ok=True)
        art = make_ticket(root, "QA-7", gate_b=True)
        write_config(root, {"bugs": "jira", "cases": "markdown",
                            "write_scopes": ["create_issue", "add_comment"],
                            "channels": {"jira": {"method": "agent", "invoke": "jira-assistant"}}})
        bug = root / "qa-factory" / "bugs" / "BUG-9.md"
        bug.write_text("# BUG-9" + chr(10) * 2 + "Sixth tag accepted." + chr(10), encoding="utf-8")
        proposal = art / "proposals" / "bug-1.json"
        proposal.write_text(json.dumps({
            "kind": "bug", "bug_file": "bugs/BUG-9.md", "action": "create",
            "fields": {"summary": "sixth tag accepted"}, "witness": {},
        }), encoding="utf-8")

        p = run_ew(root, "QA-7")
        check_eq("agent-delivered bugs: exit 4, not 0 and not a failure", p.returncode, 4)
        check_in("agent-delivered bugs: names the agent to dispatch", "jira-assistant", p.stdout)
        check_in("agent-delivered bugs: prints the payload to hand over", "PAYLOAD", p.stdout)
        check_in("agent-delivered bugs: prints how to record the result", "--record", p.stdout)
        staged = json.loads(proposal.read_text(encoding="utf-8"))
        check("agent-delivered bugs: a pending marker exists before any dispatch",
              bool(staged.get("pending")))
        check("agent-delivered bugs: no result was invented", not staged.get("result"))

        p = run_ew(root, "QA-7")
        check_in("a second run warns that an attempt is already pending", "pending", p.stdout)

        p = run_ew(root, "--record", str(proposal), "--external-id", "TP1-4242",
                   "--url", "http://tracker.example/TP1-4242")
        check_eq("--record: exit 0", p.returncode, 0)
        recorded = json.loads(proposal.read_text(encoding="utf-8"))
        check_eq("--record: the id is on the proposal",
                 recorded.get("result", {}).get("external_id"), "TP1-4242")
        check("--record: the pending marker is cleared", "pending" not in recorded)
        check_in("--record: the bug file was stamped", "TP1-4242",
                 bug.read_text(encoding="utf-8"))

        p = run_ew(root, "QA-7")
        check_eq("after --record the ticket is complete: exit 0", p.returncode, 0)
        check_in("and the run says what now exists in the tracker", "CREATED", p.stdout)
        check_in("with the link the person can open",
                 "http://tracker.example/TP1-4242", p.stdout)

        p = run_ew(root, "--record", str(proposal))
        check_eq("--record on an already-recorded proposal: exit 0, skipped", p.returncode, 0)
        check_in("--record twice: says it is already recorded", "already recorded", p.stdout)
    finally:
        cleanup(root)

    # --- "keep it local": a decision, not a NOT_CONFIGURED failure ---------------------------
    # The third answer of the gate B question . On TP2-2534 a channel
    # that could not deliver read as a broken factory; when a person has chosen to keep the
    # bugs in the repository, saying `NOT_CONFIGURED` describes their decision as a defect.
    root = temp_project("qa-factory-external-writes-local-")
    try:
        (root / "qa-factory" / "bugs").mkdir(parents=True, exist_ok=True)
        art = make_ticket(root, "QA-11", gate_b=True)
        write_config(root, {"bugs": "jira", "cases": "markdown",
                            "write_scopes": ["create_issue", "add_comment"]})
        pipeline = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["stage_overrides"] = [{
            "stage": "S8", "match": "external_writes bugs channel jira has no delivery",
            "decision": "keep it local for now, I will file them by hand next week",
            "by": "human"}]
        (art / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        (root / "qa-factory" / "bugs" / "BUG-1.md").write_text("# BUG-1\n", encoding="utf-8")
        (art / "proposals" / "bug-1.json").write_text(json.dumps({
            "kind": "bug", "bug_file": "bugs/BUG-1.md", "action": "create",
            "fields": {"summary": "a sixth tag is accepted"}, "witness": {}}), encoding="utf-8")
        p = run_ew(root, "QA-11")
        check_eq("keep-it-local: exit 0, the run did not fail", p.returncode, 0)
        check_in("keep-it-local: reported as a decision", "deferred by decision", p.stdout)
        check_in("keep-it-local: in the person's own words", "file them by hand", p.stdout)
        check("keep-it-local: never as an unconfigured factory",
              "NOT_CONFIGURED" not in p.stdout)
        check_in("keep-it-local: the unsent write becomes an obligation row",
                 "external-writes", p.stdout)
        check_in("keep-it-local: with a trigger that can actually arrive",
                 "a tracker channel that can write is configured", p.stdout)
        check_in("keep-it-local: and the local file named as the record",
                 "bugs/BUG-1.md", p.stdout)
    finally:
        cleanup(root)

    # --- an experiment (t-017 D3, B-003): every channel approved and configured, nothing is sent --
    # The same bugs channel that answers exit 4 above and the same cases command that runs under
    # `--yes` above, on a story whose pipeline says `no_trace`: exit 0, the closed line, no stub
    # call, and the proposals byte for byte as they were (no pending marker, no result).
    root = temp_project("qa-factory-external-writes-experiment-")
    try:
        (root / "qa-factory" / "bugs").mkdir(parents=True, exist_ok=True)
        (root / "qa-factory" / "test-cases" / "tags").mkdir(parents=True)
        art = make_ticket(root, "QA-12", gate_b=True)
        stub_dir = root / "ew-stub"
        stub_dir.mkdir(exist_ok=True)
        calls_log = stub_dir / "calls.log"
        stub = stub_dir / "stub_tms.py"
        stub.write_text(
            "import sys, json\n"
            f"open({json.dumps(str(calls_log))}, 'a', encoding='utf-8').write(sys.argv[1] + chr(10))\n"
            "print(json.dumps({'external_id': 'XRAY-1', 'url': 'http://tms.example/XRAY-1'}))\n",
            encoding="utf-8")
        write_config(root, {"bugs": "jira", "cases": "xray",
                            "write_scopes": ["create_issue", "add_comment", "create_case", "update_case"],
                            "channels": {"jira": {"method": "agent", "invoke": "jira-assistant"}},
                            "commands": {"xray": [sys.executable, str(stub)]}})
        (root / "qa-factory" / "bugs" / "BUG-1.md").write_text("# BUG-1\n", encoding="utf-8")
        (root / "qa-factory" / "test-cases" / "tags" / "TC-001.md").write_text("# TC-001\n", encoding="utf-8")
        bug_proposal = art / "proposals" / "bug-1.json"
        bug_proposal.write_text(json.dumps({"kind": "bug", "bug_file": "bugs/BUG-1.md", "action": "create",
                                            "fields": {"summary": "x"}, "witness": {}}), encoding="utf-8")
        case_proposal = art / "proposals" / "case-1.json"
        case_proposal.write_text(json.dumps({"kind": "case", "case_file": "test-cases/tags/TC-001.md",
                                             "action": "create", "fields": {"title": "t"}, "witness": {}}),
                                 encoding="utf-8")
        before = (bug_proposal.read_bytes(), case_proposal.read_bytes())
        p = run_ew(root, "QA-12", "--yes")
        check_eq("control: without the flag the agent channel wants its dispatch (exit 4)", p.returncode, 4)
        bug_proposal.write_bytes(before[0])   # the control staged a pending marker; put the proposal back
        case_proposal.write_bytes(before[1])
        calls_log.unlink(missing_ok=True)
        pipeline = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
        pipeline["no_trace"] = True
        (art / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        journal = root / "qa-factory" / "records" / "journal.jsonl"
        journal_before = journal.read_bytes() if journal.exists() else b""
        p = run_ew(root, "QA-12", "--yes")
        check_eq("experiment: exit 0", p.returncode, 0)
        check_in("experiment: says it is closed for this run", "closed for this run (experiment)", p.stdout)
        check("experiment: the cases command was not invoked", not calls_log.exists())
        check_eq("experiment: the proposals are untouched",
                 (bug_proposal.read_bytes(), case_proposal.read_bytes()), before)
        check("experiment: no journal line about a write",
              (journal.read_bytes() if journal.exists() else b"") == journal_before)
    finally:
        cleanup(root)

    # --- --record refuses what it cannot account for -----------------------------------------
    root = temp_project("qa-factory-external-writes-record-guards-")
    try:
        art = make_ticket(root, "QA-8", gate_b=False)
        proposal = art / "proposals" / "bug-1.json"
        proposal.write_text(json.dumps({"kind": "bug", "bug_file": "bugs/BUG-1.md",
                                        "action": "create", "fields": {}, "witness": {}}),
                            encoding="utf-8")
        p = run_ew(root, "--record", str(proposal), "--external-id", "X-1")
        check_eq("--record before gate B: exit 2, same rule as the executor", p.returncode, 2)

        art2 = make_ticket(root, "QA-9", gate_b=True)
        proposal2 = art2 / "proposals" / "bug-1.json"
        proposal2.write_text(json.dumps({"kind": "bug", "bug_file": "bugs/BUG-1.md",
                                         "action": "create", "fields": {}, "witness": {}}),
                             encoding="utf-8")
        p = run_ew(root, "--record", str(proposal2))
        check_eq("--record with no --external-id: refused", p.returncode, 1)
        check_in("--record with no id: says why", "external-id", p.stderr)
    finally:
        cleanup(root)

    finish("test_external_writes")


if __name__ == "__main__":
    main()
