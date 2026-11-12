"""X2-2 / X2-3 (spec t-1765, K13): stage advice by stage and role, detector records flagged as advice, the advice file.

  (1) an adviser declared on S2 does not block S2 and is a blocking detector on S3, where it stands in `detectors` with no `advice`
  (2) a record flagged as advice (`ADVICE - n` block) does not block; a `REJECT` record of the same run does
  (3) the advice lands in `work/advice-<stage>.json`; a stage that declares a detector and no adviser writes `records: []`; a stage
      that declares nothing for the role writes no file (E-X2-2b); a script in `detectors` AND `advice` runs ONCE (E-X2-2c)
  (4) an adviser that did not run is ONE signal to the person; one that ran is none, whatever it printed
  (5) the held stage decides which stage's detectors judge a role of two stages (E-X2-2d)
  (6) X2-3: a digest word outside the form's list is advice in the file, a missing path is still a refusal
Negative controls: an `ADVICE` block with no `- ` line is a defect of `parse`, never silence (7).

Mutants (one killing test each): `detector_errors` returns advice records -> (2); `advice_detectors` ignores `stage` -> (1);
`run_advisers` writes before the verdict's absence of blocks / for a refused stop -> (3) via `all_errors`; the person signal carries
the adviser's content -> (4); `_stage_detectors` merges all stages -> (5); `_digest_word_split` returns everything refused -> (6).
"""
import json
import subprocess
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import detector_verdict as DV  # noqa: E402
import exit_gate as gate  # noqa: E402
import hooklib  # noqa: E402

ROLE, TASK = "qa-requirements-tester", "QA-T"
ADVICE_ONLY = (0, "ADVICE — 1\n- the story looks large for one pass\n", "")
REJECT_ONLY = (1, "REJECT — 1 problem(s):\n- boom\n", "")
BOTH = (1, "REJECT — 1 problem(s):\n- boom\nADVICE — 1\n- consider splitting\n", "")


def model(**stages):
    """A synthetic stages.json: `stages` maps a stage id to {"detectors": [...], "advice": [...] | None}."""
    out = []
    for sid, spec in stages.items():
        row = {"id": sid, "roles": [ROLE], "detectors": {ROLE: spec["detectors"]} if spec.get("detectors") else {}}
        if spec.get("advice") is not None:
            row["advice"] = spec["advice"]
        out.append(row)
    return {"stages": out}


class Env:
    def __init__(self, monkeypatch, tmp_path, stage_model, stage, outputs):
        self.signals, self.calls = [], []
        self.root = tmp_path / "artifacts"
        (self.root / TASK).mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(gate.SG, "stage_model", lambda: stage_model)
        monkeypatch.setattr(gate, "_stage_id", lambda agent, task="": stage)
        monkeypatch.setattr(gate, "artifact_root", lambda: self.root)
        monkeypatch.setattr(gate, "project_root", lambda *a, **k: tmp_path)
        monkeypatch.setattr(gate, "_detector_env", lambda task: {})
        monkeypatch.setattr(hooklib, "person_signal", lambda event, kind, text, **kw: self.signals.append(text))
        gate._STASH.clear()

        def run(command, **kw):
            script = Path(command[-1]).name
            self.calls.append(script)
            got = outputs[script]
            if isinstance(got, BaseException):
                raise got
            return subprocess.CompletedProcess(command, got[0], got[1], got[2])
        monkeypatch.setattr(gate.subprocess, "run", run)

    def advice_file(self, stage):
        path = self.root / TASK / "work" / f"advice-{stage}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def test_1_an_s2_adviser_does_not_block_s2_and_blocks_s3(monkeypatch, tmp_path):
    both_stages = model(S2={"detectors": ["sizing.py"], "advice": ["sizing.py"]}, S3={"detectors": ["sizing.py"]})
    assert gate.advice_detectors(ROLE, "S2") == {"sizing.py"}
    assert gate.advice_detectors(ROLE, "S3") == set()          # declared on S2 only: not an adviser on S3
    env = Env(monkeypatch, tmp_path, both_stages, "S2", {"sizing.py": (3, "UNREADABLE: crashed\n", "")})
    assert gate.detector_errors(ROLE, TASK) == [] and env.calls == []     # S2: not run among the blockers, a crash blocks nothing
    assert gate.run_advisers(ROLE, TASK) == []
    env = Env(monkeypatch, tmp_path, both_stages, "S3", {"sizing.py": REJECT_ONLY})
    records = gate.detector_errors(ROLE, TASK)
    assert [r.kind for r in records] == ["finding", "summary"] and "boom" in records[0]     # S3: a refusal blocks
    env = Env(monkeypatch, tmp_path, both_stages, "S3", {"sizing.py": (3, "UNREADABLE: crashed\n", "")})
    assert [r.kind for r in gate.detector_errors(ROLE, TASK)] == ["unreadable"]             # S3: a crash is the third state
    env = Env(monkeypatch, tmp_path, model(S2={"detectors": ["sizing.py"]}), "S2", {"sizing.py": REJECT_ONLY})
    assert gate.advice_detectors(ROLE, "S2") == set()          # E-X2-2a: no `advice` key is not "everything is advice"
    assert [r.kind for r in gate.detector_errors(ROLE, TASK)] == ["finding", "summary"]


def test_2_a_flagged_record_does_not_block_an_unflagged_one_does(monkeypatch, tmp_path):
    Env(monkeypatch, tmp_path, model(S3={"detectors": ["planning_contract.py"]}), "S3", {"planning_contract.py": BOTH})
    records = gate.detector_errors(ROLE, TASK)
    assert [r.kind for r in records] == ["finding", "summary"]
    assert not [r for r in records if r.kind == DV.ADVICE_KIND] and "consider" not in records[0]   # [1] is the summary, shown to no one
    assert [str(r) for r in gate._STASH[(ROLE, TASK, "detector")]] == ["consider splitting"]
    only = DV.parse(0, ADVICE_ONLY[1], "")
    assert only["advice"] == ["the story looks large for one pass"] and only["findings"] == [] and only["defects"] == []
    both = DV.parse(1, BOTH[1], "")
    assert both["findings"] == ["boom"] and both["advice"] == ["consider splitting"]


def test_3_advice_lands_in_the_file_and_a_script_in_both_lists_runs_once(monkeypatch, tmp_path):
    m = model(S2={"detectors": ["sizing.py", "other.py"], "advice": ["sizing.py"]})
    env = Env(monkeypatch, tmp_path, m, "S2", {"sizing.py": BOTH, "other.py": ADVICE_ONLY})
    assert [r.kind for r in gate.detector_errors(ROLE, TASK)] == []          # other.py: advice only; sizing.py waits for the verdict
    late = gate.run_advisers(ROLE, TASK)
    assert env.calls.count("sizing.py") == 1                                  # E-X2-2c: once
    assert late == []                                                         # t-1815 F5: an adviser that fails (exit 1) never blocks
    filed = env.advice_file("S2")
    assert filed["stage"] == "S2" and filed["role"] == ROLE and [u["script"] for u in filed["unread"]] == ["sizing.py"]   # ...its failure is a line + one signal
    texts = {(r["script"], r["text"]) for r in filed["records"]}
    assert {("other.py", "the story looks large for one pass"), ("sizing.py", "consider splitting")} <= texts
    assert any(script == "sizing.py" and "boom" in text for script, text in texts)   # what it printed is filed as advice
    env = Env(monkeypatch, tmp_path, model(S3={"detectors": ["planning_contract.py"]}), "S3", {"planning_contract.py": (0, "", "")})
    gate.detector_errors(ROLE, TASK)
    assert gate.run_advisers(ROLE, TASK) == []
    assert env.advice_file("S3")["records"] == []                              # a stage with no adviser writes an empty list
    env = Env(monkeypatch, tmp_path, model(S6={}), "S6", {})
    gate.detector_errors(ROLE, TASK)
    gate.run_advisers(ROLE, TASK)
    assert env.advice_file("S6") is None                                      # E-X2-2b: nothing declared, nothing to say, no file


def test_3b_a_refused_stop_writes_no_file(monkeypatch, tmp_path):
    m = model(S3={"detectors": ["planning_contract.py"]})
    env = Env(monkeypatch, tmp_path, m, "S3", {"planning_contract.py": BOTH})
    blocking, _passed = gate.all_errors(ROLE, TASK, "")
    assert blocking and env.advice_file("S3") is None


def test_4_a_failed_adviser_is_one_signal_a_finished_one_none(monkeypatch, tmp_path):
    m = model(S2={"detectors": ["sizing.py"], "advice": ["sizing.py"]})
    env = Env(monkeypatch, tmp_path, m, "S2", {"sizing.py": (2, "", "usage: argparse error\n")})
    assert gate.run_advisers(ROLE, TASK) == []
    assert len(env.signals) == 1 and "sizing.py: unreadable (advice)" in env.signals[0]
    assert [u["script"] for u in env.advice_file("S2")["unread"]] == ["sizing.py"]
    for outcome in (ADVICE_ONLY, (0, "sizing: size=XL\n", ""), (0, "", "")):
        env = Env(monkeypatch, tmp_path, m, "S2", {"sizing.py": outcome})
        gate.run_advisers(ROLE, TASK)
        assert env.signals == []                                              # content never goes to the person
    env = Env(monkeypatch, tmp_path, m, "S2", {"sizing.py": subprocess.TimeoutExpired("sizing.py", 1)})
    gate.run_advisers(ROLE, TASK)
    assert len(env.signals) == 1
    env = Env(monkeypatch, tmp_path, m, "S2", {"sizing.py": ADVICE_ONLY})
    gate.run_advisers(ROLE, TASK)
    assert "unreadable (advice)" not in json.dumps(env.advice_file("S2")["records"])


def test_5_the_held_stage_decides_which_detectors_judge(monkeypatch, tmp_path):
    two = {"stages": [{"id": "S2", "roles": [ROLE], "detectors": {ROLE: ["a.py"]}},
                      {"id": "S4", "roles": [ROLE], "detectors": {ROLE: ["critic_rollcall.py"]}}]}
    env = Env(monkeypatch, tmp_path, two, "", {"a.py": REJECT_ONLY, "critic_rollcall.py": REJECT_ONLY})
    monkeypatch.undo()                                      # the real `_stage_id` below, with only the model and the I/O patched
    monkeypatch.setattr(gate.SG, "stage_model", lambda: two)
    monkeypatch.setattr(gate, "artifact_root", lambda: env.root)
    monkeypatch.setattr(gate, "project_root", lambda *a, **k: tmp_path)
    monkeypatch.setattr(gate, "_detector_env", lambda task: {})

    def run(command, **kw):
        env.calls.append(Path(command[-1]).name)
        return subprocess.CompletedProcess(command, 1, REJECT_ONLY[1], "")
    monkeypatch.setattr(gate.subprocess, "run", run)
    with gate.holding_stage("S2"):
        gate.detector_errors(ROLE, TASK)
    assert env.calls == ["a.py"]                              # the detectors of S4 do not judge the work of S2
    env.calls.clear()
    gate.detector_errors(ROLE, "")                            # two stages, none held, none running: not established, nothing runs
    assert env.calls == []


def test_6_a_digest_word_outside_the_list_is_advice_a_missing_path_is_refused(monkeypatch, tmp_path):
    Env(monkeypatch, tmp_path, model(S5={"detectors": []}), "S5", {})
    monkeypatch.setattr(gate, "_live_dispatch", lambda agent, task: None)
    role = "qa-automator"
    ok_but_word = f"{role} S5 window 1 · rejected\nwork/automation-manifest.json"
    assert gate.digest_errors(role, TASK, ok_but_word) == []
    advice = gate._STASH[(role, TASK, "digest")]
    assert advice and all(r.kind == DV.ADVICE_KIND and r.script == "role_digest" for r in advice) and "rejected" in advice[0]
    refused = gate.digest_errors(role, TASK, f"{role} S5 window 1 · rejected")
    assert len(refused) == 1 and "names no artifact path" in refused[0]
    assert gate._digest_word_split(ok_but_word, [], []) == ([], [])


def s5_output(extra_findings=()) -> tuple:
    """`(exit code, stdout)` of the REAL `s5_precheck.report` over a result whose advice is what `check_smells` finds in a test that
    sleeps (the unit moved to ADVICE in X7-2); `extra_findings` are findings of the same run (e.g. an xref one)."""
    import contextlib
    import io
    import s5_precheck as S5
    pyfile = S5.PyFile(Path("test_x.py"), "def test_wait():\n    sleep(2)\n    assert True\n")
    advice = []
    S5.check_smells("TC-1", "", [pyfile], [(pyfile, "test_wait", pyfile.functions["test_wait"])], advice, None, [])
    assert [a["id"] for a in advice] == ["smell:TC-1:sleep-test_x.py-test_wait"]       # the real unit produced it
    result = {"ok": not extra_findings, "findings": list(extra_findings), "hints": [], "advice": advice, "notes": [],
              "cases": ["TC-1"], "unchecked": []}
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = S5.report(result)
    return code, out.getvalue()


def test_8_s5_sleep_is_advice_in_the_file_and_an_xref_refusal_of_the_same_run_still_blocks(monkeypatch, tmp_path):
    import s5_precheck as S5
    m = model(S5={"detectors": ["s5_precheck.py"]})
    code, text = s5_output()
    assert code == 0 and text.startswith("ADVICE — 1\n- [smell smell:TC-1:sleep-test_x.py-test_wait]")
    env = Env(monkeypatch, tmp_path, m, "S5", {"s5_precheck.py": (code, text, "")})
    blocking, _passed = gate.all_errors(ROLE, TASK, "")
    assert blocking == []                                            # the stage closes: advice is not an error
    filed = env.advice_file("S5")
    assert [(r["script"], "waits with sleep()" in r["text"]) for r in filed["records"]] == [("s5_precheck.py", True)]
    # the same run with an xref refusal (a Then bound to a test whose expectation nobody confirmed): it blocks, the advice waits
    xref = S5._finding("oracle", "TC-1", "Then 2 of TC-1 is open and a test asserts it", "settle the question", "open-oracle-asserted-2")
    code, text = s5_output([xref])
    assert code == 1 and "ADVICE — 1" in text and "REJECT — 1 finding(s)" in text
    (env.root / TASK / "work" / "advice-S5.json").unlink()           # the file of the first run must not stand in for the second
    env = Env(monkeypatch, tmp_path, m, "S5", {"s5_precheck.py": (code, text, "")})
    blocking, _passed = gate.all_errors(ROLE, TASK, "")
    assert any("open-oracle-asserted-2" in str(e) for e in blocking) and not any("sleep" in str(e) for e in blocking)
    assert env.advice_file("S5") is None                             # a refused stop writes no file (AR-14) ...
    assert [str(r) for r in gate._STASH[(ROLE, TASK, "detector")]][0].startswith("[smell smell:TC-1:sleep-")   # ... the advice waits
    # negative control: without the ADVICE block nothing is filed (the file is the block's work, not the gate's guess)
    env = Env(monkeypatch, tmp_path, m, "S5", {"s5_precheck.py": (0, "", "")})
    gate.all_errors(ROLE, TASK, "")
    assert env.advice_file("S5")["records"] == []                    # (rewritten whole at each accepted stop)


def test_7_an_advice_block_that_breaks_its_shape_is_never_silence(monkeypatch, tmp_path):
    for text in ("ADVICE — 1\n", "ADVICE — 0\n", "ADVICE — 2\n- only one\n", "ADVICE — 1\n- a\n- b\n", "ADVICE — x\n"):
        assert DV.parse(0, text, "")["defects"], text
    env = Env(monkeypatch, tmp_path, model(S2={"detectors": ["sizing.py"], "advice": ["sizing.py"]}), "S2",
              {"sizing.py": (0, "ADVICE — 1\n", "")})
    gate.run_advisers(ROLE, TASK)
    assert len(env.signals) == 1 and "breaks the contract" in env.advice_file("S2")["unread"][0]["reason"]
    assert DV.parse(3, "UNREADABLE: x\nADVICE — 1\n- a\n", "")["advice"] == []     # an unreadable run reads no advice


if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
