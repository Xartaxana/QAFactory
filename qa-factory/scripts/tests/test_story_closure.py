"""S8/S9 closure: where the ledger lives, the report fragment, "keep it local", the
code-written retro and the estimation record it must leave behind.

Every case here is a finding of the 0.7.7 consistency review of S8–S9. The ledger was
read at a path nothing writes, so a green story could not open its MR; the report fragment
had no named producer or section; "keep them local" was recorded under a block text nothing
matched, so the factory attempted the write the person had declined; and a `numbers` retro
left no estimation record, which the next `qa-doctor` reported as audit A15 red on a story
that had done nothing wrong.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import (  # noqa: E402
    SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_dir,
    temp_project, use_project,
)

sys.path.insert(0, str(SCRIPTS))

import check_delivery  # noqa: E402
import contract as C  # noqa: E402
import delivery_summary  # noqa: E402
import estimate_record  # noqa: E402
import external_writes  # noqa: E402
import ledger as L  # noqa: E402
import retro_numbers  # noqa: E402
import story_budget  # noqa: E402


def test_ledger_is_written_where_its_readers_look() -> None:
    """D-F1: one path for the writer and the reader, and it is the registry's."""
    root = temp_dir("qa-ledger-path-")
    try:
        artifacts = root / "TP1-15045"
        artifacts.mkdir(parents=True)
        for name in ("automation-manifest.json", "run-report.json", "triage.json"):
            (artifacts / name).write_text("{}", encoding="utf-8")
        doc = L.build(artifacts)
        L.write(artifacts, doc)
        canonical = artifacts / "work" / "ledger.json"
        check("ledger.py writes work/ledger.json", canonical.is_file())
        check_eq("and contract.artifact resolves to exactly that file",
                 C.artifact(artifacts, "ledger.json").resolve(), canonical.resolve())
        check_eq("as does the writer's own helper",
                 C.artifact_write_path(artifacts, "ledger.json").resolve(), canonical.resolve())
        check_not_in("nothing is left at the flat legacy path",
                     "ledger.json", [p.name for p in artifacts.glob("*.json")])
        check_eq("and ledger.md keeps it company",
                 C.artifact(artifacts, "ledger.md").resolve(),
                 (artifacts / "work" / "ledger.md").resolve())

        verdict = check_delivery.assess(artifacts)
        reread = C.load_json(C.artifact(artifacts, "ledger.json"))
        check_eq("check_delivery writes delivery_ready into the same file",
                 reread.get("delivery_ready"), verdict["delivery_ready"])
        check("and its reasons travel with it", "reasons" in reread)
    finally:
        cleanup(root)


def test_report_fragment_has_a_producer_and_a_section() -> None:
    """D-F9: the command that prints the fragment, and the section that hosts it."""
    root = temp_dir("qa-report-fragment-")
    try:
        artifacts = root / "TP1-15045"
        artifacts.mkdir(parents=True)
        (artifacts / "work").mkdir()
        summary = delivery_summary.write(artifacts)
        fragment = delivery_summary.render(summary)
        check("delivery_summary writes the shared projection",
              (artifacts / "work" / "delivery-summary.json").is_file())
        check_in("the fragment is the validated block", "<!-- factory-summary:start -->",
                 fragment)

        report = ("# T — test report\n\n## Verdict\n\nno\n\n## Run this yourself\n\nnone\n\n"
                  "## Product problems\n\nnone\n\n## Check coverage\n\n"
                  "| Ref | Kind | State |\n|---|---|---|\n| TS-1 | plan_row | `passed_green` |\n\n"
                  + fragment +
                  "\n## Readiness within what was verified\n\nnone\n\n"
                  "## Our tests and the factory\n\nnone\n")
        path = artifacts / "test-report.md"
        path.write_text(report, encoding="utf-8")
        import validate_artifacts as V
        errors: list = []
        V.check_report_coverage(path, errors)
        V.check_report_sections(path, errors)
        check_eq("the fragment at the end of Check coverage breaks neither the "
                 "coverage scan nor the section order", errors, [])
        done = run_script("delivery_summary.py", "--task-root", str(artifacts),
                          "--check-report", str(path))
        check("and --check-report accepts that report", done.returncode == 0,
              (done.stdout + done.stderr)[:200])
        path.write_text(report.replace("Recorded verification", "Retyped verification"),
                        encoding="utf-8")
        retyped = run_script("delivery_summary.py", "--task-root", str(artifacts),
                             "--check-report", str(path))
        check("a retyped fragment is refused by name",
              retyped.returncode != 0 and "STALE_REPORT_SUMMARY" in retyped.stdout)
    finally:
        cleanup(root)


def test_keep_it_local_is_recognised_however_it_was_recorded() -> None:
    """D-F8: the phase records the block as "keep it local"; the old block text still reads."""
    check("the words a person uses are recognised",
          bool(external_writes.LOCAL_ONLY_RE.search("just leave them in the repo, keep it local")))
    check("and so is the block text older stories were recorded under",
          bool(external_writes.LOCAL_ONLY_RE.search("external write")))
    check("an unrelated decision is not read as keep-local",
          not external_writes.LOCAL_ONLY_RE.search("file them all in jira please"))

    root = temp_project("qa-keep-local-")
    try:
        use_project(root)
        artifacts = root / "qa-factory" / "artifacts" / "TP1-15045"
        artifacts.mkdir(parents=True)
        (artifacts / "pipeline.json").write_text(json.dumps(
            {"ticket": "TP1-15045", "gates": {"B": {"decision": "approved"}},
             "stage_overrides": [{"stage": "S8", "match": "external write",
                                  "decision": "just leave them in the repo for now",
                                  "by": "human"}]}), encoding="utf-8")
        decision = external_writes.local_only_decision("TP1-15045")
        check_eq("the person's own words come back verbatim", decision.get("words"),
                 "just leave them in the repo for now")
    finally:
        cleanup(root)


def test_unknown_channel_is_a_refusal_not_a_no_op() -> None:
    """A channel with no adapter: named, non-zero, with both ways out."""
    root = temp_project("qa-no-adapter-")
    try:
        use_project(root)
        artifacts = root / "qa-factory" / "artifacts" / "TP1-15045"
        artifacts.mkdir(parents=True)
        (artifacts / "pipeline.json").write_text(json.dumps(
            {"ticket": "TP1-15045", "gates": {"B": {"decision": "approved"}}}),
            encoding="utf-8")
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = external_writes.run("TP1-15045",
                                       {"external_writes": {"bugs": "azure-boards",
                                                            "cases": "markdown"}},
                                       yes=False, preview=False)
        out = buf.getvalue()
        check_eq("exit 5, never a quiet 0", code, external_writes.EXIT_NO_ADAPTER)
        check_in("the channel is named", "azure-boards", out)
        check_in("and so is the way back to local files", "markdown", out)
        check_in("and the way to configure it", "channels.azure-boards", out)
    finally:
        cleanup(root)


def retro_project(prefix: str) -> tuple:
    root = temp_project(prefix)
    base = root / "qa-factory"
    artifacts = base / "artifacts" / "TP1-15045"
    (artifacts / "work").mkdir(parents=True)
    (artifacts / "state").mkdir(parents=True)
    (base / "state" / "cost").mkdir(parents=True)
    (artifacts / "state" / "controller.json").write_text(
        json.dumps({"source_revision": "rev-1"}), encoding="utf-8")
    (artifacts / "pipeline.json").write_text(json.dumps(
        {"ticket": "TP1-15045", "retro_mode": "numbers",
         "stages": {"S9": {"status": "done", "digest": "retro"}},
         "gates": {"B": {"decision": "approved", "words": "ship it, file 1 and 3"}}}),
        encoding="utf-8")
    (base / "state" / "cost" / "s-1.json").write_text(json.dumps(
        {"session_id": "s-1", "by_task": {"TP1-15045": {"tokens": 1000, "cost": 2.5}},
         "agents": []}), encoding="utf-8")
    return root, base, artifacts


def test_numbers_retro_is_written_by_code_and_leaves_its_precedent() -> None:
    """D-F5 + D-F6: nobody authors prose, and audit A15 stays green."""
    root, base, artifacts = retro_project("qa-retro-numbers-")
    try:
        use_project(root)
        written = retro_numbers.write_retro("TP1-15045", base, artifacts,
                                            feedback="the gates were slow")
        retro = artifacts / "retro.md"
        check("retro.md exists where audit A15 reads it", retro.is_file())
        text = retro.read_text(encoding="utf-8")
        check_in("it says who wrote it", "retro_numbers.py --write-retro", text)
        check_in("it carries the computed table", "Retro numbers", text)
        check_in("the person's gate words are in it", "ship it, file 1 and 3", text)
        check_in("and their closing answer, verbatim", "> the gates were slow", text)

        facts = json.loads(written["estimate"].read_text(encoding="utf-8"))
        action, record = estimate_record.append_record(root, "TP1-15045", facts)
        check_eq("the estimation record is appended", action, "appended")
        check_eq("bound to the retro this run wrote", record["retro_sha256"],
                 __import__("hashlib").sha256(retro.read_bytes()).hexdigest())

        import audit_factory
        errors, count = audit_factory.a15_findings(base / "artifacts", base / "state")
        check_eq("audit A15 sees one completed S9", count, 1)
        check_eq("and finds nothing to report", errors, [])
    finally:
        cleanup(root)


def test_open_items_block_is_optional_and_verbatim() -> None:
    """The MR carries what was open when the person said "open it anyway"."""
    root, base, artifacts = retro_project("qa-open-items-")
    try:
        use_project(root)
        import gate_brief
        original = getattr(gate_brief, "open_before_mr", None)
        try:
            gate_brief.open_before_mr = lambda task_root: [
                "R-4 — nobody answered whether trial users see the banner",
                "TS-7 — env_blocked, no decision recorded"]
            block = delivery_summary.open_items(artifacts)
            check_in("the block is headed for the MR description", "## Open items", block)
            check_in("and quotes the line as the gate message had it",
                     "nobody answered whether trial users see the banner", block)
            gate_brief.open_before_mr = lambda task_root: []
            check_eq("nothing open, nothing printed", delivery_summary.open_items(artifacts), "")

            def absent(task_root):
                raise AttributeError("this build has no open_before_mr")
            gate_brief.open_before_mr = absent
            check_eq("and a build without it loses no MR",
                     delivery_summary.open_items(artifacts), "")
        finally:
            if original is None:
                delattr(gate_brief, "open_before_mr")
            else:
                gate_brief.open_before_mr = original
    finally:
        cleanup(root)


def test_story_budget_stop_is_an_exit_code() -> None:
    """D-F12: a ceiling nobody can act on is not a ceiling."""
    root, base, artifacts = retro_project("qa-budget-stop-")
    try:
        use_project(root)
        # The spend the ceiling polices is the sessions the price NAMES by evidence (FR-24, t-170): the
        # cost file's `by_task` tag binds none, so the driver's journal names `s-1` (one role row whose
        # running total is the $2.5 the tag used to carry). Only this test counts money; the retro
        # tests that share `retro_project` assert no figure and stay on the fixture as it was.
        (artifacts / "state" / "driver-runs.jsonl").write_text(json.dumps(
            {"kind": "role", "role": "qa-scout", "dispatch": "S1-qa-scout-1", "stage": "S1",
             "session_id": "s-1", "num_turns": 3, "total_cost_usd": 2.5,
             "ts": "2026-09-30T10:00:00+00:00"}) + "\n", encoding="utf-8")
        (base / "config.json").write_text(json.dumps(
            {"budget": {"story_usd": 1.0, "warn_at": [0.5]}}), encoding="utf-8")
        check_eq("at the ceiling the caller is told to stop",
                 story_budget.enforce("TP1-15045", base, artifacts), story_budget.STOP_EXIT)
        (artifacts / "pipeline.json").write_text(json.dumps(
            {"ticket": "TP1-15045", "stage_overrides": [
                {"stage": "S8", "match": "story budget", "decision": "go on, it is worth it"}]}),
            encoding="utf-8")
        story_budget.marker_path("TP1-15045", base).unlink(missing_ok=True)
        check_eq("a person's word passes it",
                 story_budget.enforce("TP1-15045", base, artifacts), 0)
        (base / "config.json").write_text("{}", encoding="utf-8")
        story_budget.marker_path("TP1-15045", base).unlink(missing_ok=True)
        check_eq("a project with no ceiling is never stopped",
                 story_budget.enforce("TP1-15045", base, artifacts), 0)
    finally:
        cleanup(root)


def main() -> None:
    test_ledger_is_written_where_its_readers_look()
    test_report_fragment_has_a_producer_and_a_section()
    test_keep_it_local_is_recognised_however_it_was_recorded()
    test_unknown_channel_is_a_refusal_not_a_no_op()
    test_numbers_retro_is_written_by_code_and_leaves_its_precedent()
    test_open_items_block_is_optional_and_verbatim()
    test_story_budget_stop_is_an_exit_code()
    finish("story closure (S8/S9): ledger path, report fragment, keep-it-local, "
           "no-adapter refusal, code-written retro, open items, story budget")


if __name__ == "__main__":
    main()
