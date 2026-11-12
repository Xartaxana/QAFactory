"""RH2-9: a `blocked_by_env` row stands only on a run that shows the stand (K-E, K-AR10 keys).

`s5_precheck.check_env_evidence` reads, per instance of the row, its NEWEST run block and that run's summary. Evidence: `env_blocked`, a
STAND SIGNAL on a run no project timeout ended, or a `run_evidence` exception name of `stand-answers.json` in the run's error lines. A
project-timeout run is never evidence (its dump holds captured output and source lines), a missing run is a finding from 0.10.9 and a
note before it, and a row of a case the dispatch does not own is only ever a note.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, cleanup, finish, temp_project, use_project  # noqa: E402

import s5_precheck as S5  # noqa: E402

PKG = Path(__file__).resolve().parents[2]
TICKET = "ET-1"
CASE = "TC-1"
INST = "test_reindex_last_indexed"
OTHER = "test_other"
SENTENCE = "test_reindex_last_indexed was killed by the project's per-test timeout (300 s, pyproject.toml): it ran longer than the project allows."
PROJECT = None


def put(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return path


def story(version="0.10.9", pipeline=True) -> Path:
    task = PROJECT / "qa-factory" / "artifacts" / TICKET
    if task.exists():
        shutil.rmtree(task)
    task.mkdir(parents=True)
    if pipeline:
        put(task / "pipeline.json", {"ticket": TICKET, "run_mode": {"plugin_version": version}})
    return task


def run(task: Path, n: int, rows: list, summary=None, status="failed") -> None:
    """One run block (attempt `n`, oldest first by its clock) with `rows` [(instance, reason_code)] and its summary file."""
    ref = f"qa-factory/artifacts/{TICKET}/evidence/runs/s{n}.json"
    if summary is not None:
        put(PROJECT / ref, summary)
    results = [{"instance_id": i, "test_id": f"tests.test_reindex::{i}", "status": "failed", "reason": "x",
                "case_version_links": [{"case_id": CASE}], **({"reason_code": c} if c else {})} for i, c in rows]
    put(task / "work" / "run-blocks" / f"2026110{n}T000000Z-att{n}.json",
        {"schema_version": 2, "block_id": f"att{n}", "attempt_id": f"att{n}", "attempt_started_at": f"2026-11-0{n}T00:00:00+00:00",
         "execution_status": status, "results": results,
         "evidence": [{"summary": ref if summary is not None else "", "reporter": "pytest"}]})


def manifest(instance_ids=None, instance_id=None, tests=(INST,)) -> dict:
    row = {"case": CASE, "reason": "blocked_by_env", "detail": "d", "remedy": {"kind": "service", "where": "x", "change": "y", "restart": "z"}}
    if instance_ids:
        row["instance_ids"] = list(instance_ids)
    if instance_id:
        row["instance_id"] = instance_id
    return {"tests": [{"instance_id": t, "covers": [CASE], "status": "red"} for t in tests], "unresolved": [row]}


def check_row(task: Path, mf: dict, owned=(CASE,)) -> tuple:
    findings, notes = [], []
    S5.check_env_evidence(task, mf, list(owned), findings, notes)
    return [f for f in findings if f["id"].endswith("env-evidence-missing")], notes


def refused(label: str, task, mf=None, owned=(CASE,)):
    found, _notes = check_row(task, mf or manifest(), owned)
    check(f"{label}: one finding, family environment, tag env-evidence-missing", len(found) == 1 and found[0]["check"] == "environment", str(found))
    return found[0] if found else {"message": "", "fix": ""}


def accepted(label: str, task, mf=None, owned=(CASE,)):
    found, notes = check_row(task, mf or manifest(), owned)
    check_eq(f"{label}: no finding, no note", (found, notes), ([], []))


def failed_row(test, why, kind="failure") -> dict:
    return {"test": f"tests.test_reindex::{test}", "kind": kind, "why": why}


PLAIN = {"execution_status": "failed", "exit_code": 1, "failed": [failed_row(INST, "AssertionError: 0 == 1")]}
HARD = {"execution_status": "timeout", "exit_code": 1, "error_head": ["x"], "log_tail": ["    except ConnectionResetError:"],
        "timeout": {"how": "hard_kill", "source": "project", "tests": [f"tests.test_reindex::{INST}"], "sentence": SENTENCE}}


def k_e_refusals():
    task = story()
    run(task, 1, [(INST, None)], PLAIN)
    found = refused("K-E1 a plain red run is no stand evidence", task)
    check_in("K-E1 the message names the instance", INST, found["message"])
    check_in("K-E1 ... and the run's first line", "AssertionError", found["message"])
    check_in("K-E1 the fix names the door (--stage S5 --block)", 'waiver.py --stage S5 --block "no environment evidence"', found["fix"])
    check_in("K-E1 the exception names in the fix come from the data rows", "ConnectionRefusedError", found["fix"])
    check_in("K-E1 `--mine` names the case", f"--mine {CASE}", found["fix"])
    check("K-E2 the family is one a person's word passes", "environment" in S5.PASSABLE)
    run(task, 2, [(INST, "project_timeout")], dict(HARD, stand_signal={"reason": "same_failure", "sentence": "three runs fail alike"}),
        status="timeout")
    found = refused("K-E3 / M4 a stand signal derived from a timed-out run is not evidence", task)
    check_in("K-E3 the message carries the timeout's own sentence", "per-test timeout", found["message"])
    run(task, 3, [(INST, None)], dict(PLAIN, failed=[failed_row(INST, "TimeoutError: waited 30 s for the index")]))
    refused("K-E7 / M6 a test's own TimeoutError is not the stand", task)
    run(task, 4, [(INST, None)], dict(PLAIN, failed=[failed_row(INST, "ConnectionRefusedError: [Errno 111]")]))
    run(task, 5, [(INST, None)], PLAIN)
    refused("K-E8 / M5 an older run's refusal never counts: the NEWEST run of the instance is read", task)
    run(task, 6, [(INST, None)], dict(HARD, error_head=["    except ConnectionResetError:"]), status="timeout")
    refused("K-E11 / B-3 a hard-kill dump that shows `except ConnectionResetError:` is not the stand", task)
    run(task, 7, [(INST, "project_timeout"), (OTHER, None)],
        dict(HARD, failed=[failed_row(OTHER, "ConnectionRefusedError: other")],
             timeout={"how": "failed_in_report", "source": "project", "tests": [f"tests.test_reindex::{INST}"], "sentence": SENTENCE}))
    refused("K-E11 the timed-out instance never takes evidence from a sibling's refusal", task)
    refused("K-E12 / B-4 every named instance must show the stand: A timed out, B refused the connection", task,
            manifest(instance_ids=[INST, OTHER], tests=(INST, OTHER)))
    found, _ = check_row(task, manifest(instance_ids=[OTHER], tests=(INST, OTHER)))
    check_eq("K-E12 control: the row naming only B (its own failed row has the refusal) stands", found, [])
    third = "test_third"
    found = refused("K-E13 / m-4 a mixed row (A refused, C never ran)", task, manifest(instance_ids=[INST, third], tests=(INST, third)))
    check_in("K-E13 the message names the refused instance", INST, found["message"])
    check_in("K-E13 ... and says the un-run one has no recorded run", f"no recorded run: {third}", found["message"])


def k_e_evidence():
    task = story()
    run(task, 1, [(INST, None)], dict(PLAIN, execution_status="env_blocked"), status="env_blocked")
    accepted("K-E4 an env_blocked run", task)
    run(task, 2, [(INST, None)], dict(PLAIN, stand_signal={"reason": "slow_run", "sentence": "slow"}))
    accepted("K-E5 a stand signal on a run no timeout killed", task)
    run(task, 3, [(INST, None)], dict(PLAIN, error_head=["E   ConnectionRefusedError: [Errno 111]"]))
    accepted("K-E6 a connection refusal in the error head", task)
    run(task, 4, [(INST, None)], dict(PLAIN, failed=[failed_row(INST, "socket.gaierror: x", "error")]))
    accepted("K-E6 gaierror in the failed row", task)
    run(task, 5, [(INST, None)], dict(PLAIN, log_tail=["urllib3.exceptions.ProtocolError: ConnectionResetError(10054)"]))
    accepted("K-E6 a reset in the log tail of a run no timeout ended", task)
    run(task, 6, [(INST, None)], dict(PLAIN, error_head=["E   MyConnectionRefusedErrorHandler failed"]))
    refused("K-E6 control: the name is matched as a whole word", task)


def k_e_owned_and_versions():
    task = story()
    run(task, 1, [(INST, None)], PLAIN)
    found, notes = check_row(task, manifest(), owned=("TC-9",))
    check_eq("K-E9 a row of a case this dispatch does not own is a note, not a finding", (found, len(notes)), ([], 1))
    check_in("K-E9 ... that says it is not a repair", "does not own", notes[0] if notes else "")
    mf = manifest()
    refused("K-E10a 0.10.9 and no run at all: a finding", story("0.10.9"), mf)
    found, notes = check_row(story("0.10.5"), mf)
    check_eq("K-E10b 0.10.5 and no run: a note, no finding", (found, len(notes)), ([], 1))
    check_in("K-E10b ... the note names the story's start version", "story started on 0.10.5", notes[0] if notes else "")
    found, notes = check_row(story(pipeline=False), mf)
    check_eq("K-E10c no pipeline.json: unknown version is the lenient side, a note", (found, len(notes)), ([], 1))
    check_in("K-E10c ... it says `unknown`", "unknown", notes[0] if notes else "")
    task = story("0.10.5")
    run(task, 1, [(INST, None)], PLAIN)
    refused("K-E10d 0.10.5 but a run exists that shows no stand: a finding (the version only softens a missing run)", task, mf)
    refused("K-E10 a later version (0.10.10) is not older than 0.10.9", story("0.10.10"), mf)
    task = story("0.10.9")
    run(task, 1, [(INST, None)], PLAIN)
    refused("B-4 the singular `instance_id` row whose test left tests[] still finds its run in the block", task,
            manifest(instance_id=INST, tests=()))
    refused("B-4 a row naming no instance falls back to the instances the run blocks cover for the case", task, manifest(tests=()))


def k_ar_carriers():
    texts = {"qa-automator.md": (PKG / "agents" / "qa-automator.md").read_text(encoding="utf-8"),
             "ahead-cards.json": (PKG / "references" / "ahead-cards.json").read_text(encoding="utf-8"),
             "s5-automator-to-critic.yaml": (PKG / "handoffs" / "s5-automator-to-critic.yaml").read_text(encoding="utf-8")}
    for name, text in texts.items():
        check(f"K-AR10 {name} names the timeout rule", any(p in text for p in ("per-test", "project's timeout killed")), name)
        check(f"K-AR10 {name} mentions blocked_by_env", "blocked_by_env" in text, name)
    import env_probe
    flagged = {r["id"] for r in env_probe.stand_answers()["no_answer"] if r.get("run_evidence") is True}
    check_eq("K-AR22 the run_evidence flag stands on N1, N2, N4, N7 and NOT on N3 (a test's TimeoutError)", flagged, {"N1", "N2", "N4", "N7"})


def main() -> None:
    global PROJECT
    PROJECT = temp_project("qa-env-evidence-")
    use_project(PROJECT)
    try:
        for step in (k_e_refusals, k_e_evidence, k_e_owned_and_versions, k_ar_carriers):
            step()
    finally:
        cleanup(PROJECT)
    finish("env evidence")


if __name__ == "__main__":
    main()
