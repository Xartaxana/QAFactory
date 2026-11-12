"""S9 estimate writer and A15 current-retro binding acceptance."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_factory import a15_findings  # noqa: E402
from estimate_record import append_record  # noqa: E402


def write_task(root: Path, done: bool = True) -> Path:
    task = root / "qa-factory" / "artifacts" / "T-1"
    (task / "state").mkdir(parents=True)
    task.joinpath("pipeline.json").write_text(json.dumps({"stages": {"S9": {
        "status": "done" if done else "pending"}}}), encoding="utf-8")
    task.joinpath("state/controller.json").write_text(json.dumps({
        "revision": 17, "source_revision": "source-current"}), encoding="utf-8")
    task.joinpath("retro.md").write_text("# current retro\n", encoding="utf-8")
    return task


def test_held_ledger_lock_is_refused_not_hung():
    """TR4-2 C: a ledger lock held past the wait does not hang the CLI: it prints one `invalid_estimate` object whose
    error is the helper's sentence (the lock file, the holder), exit 2, and the ledger is untouched."""
    import estimate_record as ER
    import event_store as ES
    from event_store import take_file_lock
    import io
    import os
    from contextlib import redirect_stdout
    with tempfile.TemporaryDirectory(prefix="qa-estimate-held-") as td:
        root = Path(td)
        write_task(root)
        facts = root / "facts.json"
        facts.write_text(json.dumps({"forecast": {"size_initial": "S"}, "actual": {"n": 1}}), encoding="utf-8")
        import runtime_paths as RP
        holder = take_file_lock(RP.state_file(root, "estimation-ledger.lock"), 0, purpose="test holder", record_holder=True)
        saved, argv = ES.SHORT_RMW_LOCK_WAIT_S, sys.argv
        ES.SHORT_RMW_LOCK_WAIT_S = 0.2
        sys.argv = ["estimate_record.py", "--project-root", str(root), "--task", "T-1", "--facts", str(facts)]
        out = io.StringIO()
        try:
            try:
                with redirect_stdout(out):
                    ER.main()
                code = 0
            except SystemExit as stop:
                code = stop.code
        finally:
            ES.SHORT_RMW_LOCK_WAIT_S, sys.argv = saved, argv
            holder.release()
        printed = json.loads(out.getvalue())
        assert code == 2 and printed["status"] == "invalid_estimate", (code, printed)
        assert "held by process %d" % os.getpid() in printed["error"].lower(), printed
        assert "estimation-ledger.lock" in printed["error"], printed
        assert not (root / "qa-factory" / "records" / "estimation-ledger.jsonl").exists()


def main() -> int:
    failures = 0
    total = 0
    def check(name, condition):
        nonlocal failures, total
        print(("PASS " if condition else "FAIL ") + name)
        failures += not condition
        total += 1
    facts = {"forecast": {"size_initial": "S", "size_final": "M"},
             "actual": {"scenario_count": 4}, "drivers": ["dependency"]}
    with tempfile.TemporaryDirectory(prefix="qa-estimate-") as td:
        root = Path(td); task = write_task(root, done=False)
        errors, count = a15_findings(root / "qa-factory/artifacts", root / "qa-factory/state")
        check("S9 pending does not require future estimate evidence", not errors and count == 0)
        task.joinpath("pipeline.json").write_text(json.dumps({"stages": {"S9": {"status": "done"}}}), encoding="utf-8")
        legacy = root / "qa-factory/records/estimation-ledger.jsonl"; legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps({"task": "T-1", "forecast": {"size": "S"}}) + "\n", encoding="utf-8")
        errors, _ = a15_findings(root / "qa-factory/artifacts", root / "qa-factory/state")
        check("legacy task-only row does not prove current S9", any("exactly one active" in e for e in errors))
        action, first = append_record(root, "T-1", facts)
        again, same = append_record(root, "T-1", facts)
        errors, _ = a15_findings(root / "qa-factory/artifacts", root / "qa-factory/state")
        check("current bound record satisfies A15", action == "appended" and not errors)
        check("transport retry is idempotent", again == "reused" and first["record_id"] == same["record_id"]
              and len(legacy.read_text(encoding="utf-8").splitlines()) == 2)
        task.joinpath("retro.md").write_text("# changed retro\n", encoding="utf-8")
        errors, _ = a15_findings(root / "qa-factory/artifacts", root / "qa-factory/state")
        check("changed retro invalidates old active record", any("not bound" in e for e in errors))
        _, second = append_record(root, "T-1", facts)
        errors, _ = a15_findings(root / "qa-factory/artifacts", root / "qa-factory/state")
        check("new retro record supersedes old append-only", first["record_id"] in second["supersedes"] and not errors)
        duplicate = dict(second, record_id="fork", supersedes=[])
        with legacy.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(duplicate) + "\n")
        errors, _ = a15_findings(root / "qa-factory/artifacts", root / "qa-factory/state")
        check("duplicate active records fail A15", any("found 2" in e for e in errors))
    # --- t-1355 N2: one refusal lists every wrong key, before anything is written ---------------------
    import friction
    import subprocess
    from detector_verdict import split_items
    from estimate_record import FACTS_KEYS, facts_problems
    check("N2-E: FACTS_KEYS is the carrier of the three keys", FACTS_KEYS == ("forecast", "actual", "drivers"))
    check("E-N2-7 an object with no keys: forecast and actual, drivers legal when absent",
          facts_problems({}) == ["estimate facts forecast must be an object", "estimate facts actual must be an object"])
    check("a non-object is told alone", facts_problems([]) == ["estimate facts must be an object"])
    check("a good file has no problem, drivers included or not",
          facts_problems(facts) == [] and facts_problems({"forecast": {}, "actual": {}}) == [])
    with tempfile.TemporaryDirectory(prefix="qa-estimate-n2-") as td:
        root = Path(td)         # NO retro.md, no controller state, no ledger directory: nothing is there to be read or made
        try:
            append_record(root, "T-1", {"forecast": [], "actual": "x", "drivers": 5})
            text = "accepted"
        except ValueError as exc:
            text = str(exc)
        items = split_items(text)
        check("N2-E: bad forecast and bad actual are both named (and drivers)",
              len(items) == 3 and "forecast must be an object" in items[0] and "actual must be an object" in items[1]
              and "drivers must be an array" in items[2])
        check("N2-E: invalid facts without retro.md report the facts, touch no ledger",
              "retro.md" not in text and not (root / "qa-factory").exists() and not any(root.iterdir()))
        check("N2: every multi-problem refusal is validator friction",
              friction.classify("estimate_record.py: " + text) == "validator")
        bad = root / "facts.json"
        bad.write_text(json.dumps({"forecast": [], "actual": "x"}), encoding="utf-8")
        ran = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve().parents[1] / "estimate_record.py"),
                              "--project-root", str(root), "--task", "T-1", "--facts", str(bad)],
                             capture_output=True, text=True, encoding="utf-8")
        out = json.loads(ran.stdout)         # ONE JSON object (FR-14)
        check("N2-E: the CLI prints one JSON object whose error is the compound",
              ran.returncode == 2 and out["status"] == "invalid_estimate" and len(split_items(out["error"])) == 2
              and len(ran.stdout.splitlines()) == 1)
    test_held_ledger_lock_is_refused_not_hung()
    check("TR4-2 C: a held ledger lock is refused as invalid_estimate naming the holder, not hung", True)
    print(f"\n=== test_estimate_record: {total - failures}/{total} ok ===")   # the tally the selftest reads as "ran"
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
