"""t-2064 P4a, items 3 and 4: `author_green_of` (the author's own run, green on these bytes) and the per-check records
(`work/probes/checks/<iid>--L<line>.json`). Fast: temp task folders and pure functions; no probe is run, no tool is launched.

`author_green_of` ERRS TO `None` (a fact that became a proof's condition): nothing here reads `True` by default.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import probe_by_code as PBC  # noqa: E402
import probe_debt as PD  # noqa: E402
import proof_level as PL  # noqa: E402

FN_SHA = "f" * 64          # the function's instance_content_sha
FP = "a" * 64              # test_content_sha over the author's bytes


def put_block(task: Path, name: str, rows: list, **extra) -> Path:
    """One run block under `work/run-blocks/`, the way `run_history.read_run_blocks` reads it."""
    path = task / "work" / "run-blocks" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict({"attempt_id": name[:-5], "attempt_started_at": "2026-11-10T10:00:00+00:00",
                                     "dispatch_id": "d1", "results": rows}, **extra)), encoding="utf-8")
    return path


def row(status="passed", iid="i1", sha=FP, fn_sha="") -> dict:
    return {"instance_id": iid, "status": status, "instance_content_sha": fn_sha,
            "source_fingerprint": {"test_content_sha": sha}}


# --- author_green_of --------------------------------------------------------------------------------------------

def test_author_green_by_fingerprint_on_ts(tmp_path):
    """Arm B's TS record: `instance_content_sha` is empty, so `author_binding` binds nothing; the run block's
    `source_fingerprint.test_content_sha` equal to the fingerprint of the author's bytes is the green."""
    put_block(tmp_path, "20261110T100000-a.json", [row("passed")])
    assert PBC.author_binding(tmp_path, "i1", "") is None
    assert PBC.author_green_of(tmp_path, "i1", "", FP) is True
    put_block(tmp_path, "20261110T110000-b.json", [row("failed")], attempt_started_at="2026-11-10T11:00:00+00:00")
    assert PBC.author_green_of(tmp_path, "i1", "", FP) is False       # the latest row of these bytes is red


def test_author_unknown_critic(tmp_path):
    """No fact, no `True`: the return is `None`, which the walk reads as the critic's (the role), never as a green."""
    assert PBC.author_green_of(tmp_path, "i1", "", FP) is None                    # no binding and no run block at all
    assert PBC.author_green_of(tmp_path, "i1", FN_SHA, FP) is None
    put_block(tmp_path, "20261110T100000-a.json", [row("passed")])
    for iid, identity, fingerprint in (("i1", "", ""), ("", "", FP), ("i1", "", None), ("i1", "", 7)):
        assert PBC.author_green_of(tmp_path, iid, identity, fingerprint) is None, (iid, identity, fingerprint)


def test_author_binding_first_read_as_run_alternative_reads_it(tmp_path):
    """Route 1: the function-bound block row decides, exactly `None if bound is None else status == "passed"`."""
    put_block(tmp_path, "20261110T100000-a.json", [row("passed", fn_sha=FN_SHA, sha="b" * 64)])
    assert PBC.author_green_of(tmp_path, "i1", FN_SHA, "") is True
    put_block(tmp_path, "20261110T110000-b.json", [row("error", fn_sha=FN_SHA, sha="b" * 64)],
              attempt_started_at="2026-11-10T11:00:00+00:00")
    assert PBC.author_green_of(tmp_path, "i1", FN_SHA, "") is False
    assert PBC.author_green_of(tmp_path, "i1", "e" * 64, "") is None                 # another function: nothing binds


def test_author_green_other_instance_is_none(tmp_path):
    put_block(tmp_path, "20261110T100000-a.json", [row("passed", iid="i2")])
    assert PBC.author_green_of(tmp_path, "i1", "", FP) is None
    assert PBC.author_green_of(tmp_path, "i2", "", FP) is True                       # the control: the same rows answer for i2


def test_author_green_helper_changed_since_is_none(tmp_path):
    """The fingerprint covers the test files and helpers: any edit gives another fingerprint, which matches no row."""
    put_block(tmp_path, "20261110T100000-a.json", [row("passed")])
    assert PBC.author_green_of(tmp_path, "i1", "", "9" * 64) is None
    assert PBC.author_green_of(tmp_path, "i1", "", FP) is True


@pytest.mark.parametrize("status", ["failed", "error", "not_run", "skipped", ""])
def test_author_green_status_other_than_passed_is_false(tmp_path, status):
    put_block(tmp_path, "20261110T100000-a.json", [row(status)])
    assert PBC.author_green_of(tmp_path, "i1", "", FP) is False


def test_author_green_reparse_block_is_none(tmp_path):
    """A reparse block supersedes the block it follows; a green read only there is not the author's own run."""
    put_block(tmp_path, "20261110T100000-a.json", [row("failed")])
    put_block(tmp_path, "20261110T100000-a-reparse-1234.json", [row("passed")], reparse_of="20261110T100000-a.json")
    assert PBC.author_green_of(tmp_path, "i1", "", FP) is None
    only = tmp_path / "other"
    put_block(only, "20261110T100000-a-reparse-1234.json", [row("passed")])
    assert PBC.author_green_of(only, "i1", "", FP) is None


def test_author_green_retried_green_latest_row_decides(tmp_path):
    """No row field tells a retry from a first run, so the LATEST row of the bytes decides (inside one block the last row too)."""
    put_block(tmp_path, "20261110T100000-a.json", [row("failed"), row("passed")])
    assert PBC.author_green_of(tmp_path, "i1", "", FP) is True
    put_block(tmp_path, "20261110T110000-b.json", [row("passed"), row("failed")], attempt_started_at="2026-11-10T11:00:00+00:00")
    assert PBC.author_green_of(tmp_path, "i1", "", FP) is False


def test_author_green_unreadable_block_is_none(tmp_path):
    put_block(tmp_path, "20261110T100000-a.json", [row("passed")])
    assert PBC.author_green_of(tmp_path, "i1", "", FP) is True
    (tmp_path / "work" / "run-blocks" / "20261110T120000-broken.json").write_text("{not json", encoding="utf-8")
    assert PBC.author_green_of(tmp_path, "i1", "", FP) is None                       # the broken file may hold the newer row


def test_author_green_malformed_rows_are_none(tmp_path):
    put_block(tmp_path, "20261110T100000-a.json", ["x", {"instance_id": "i1", "source_fingerprint": "nope"}, {"instance_id": "i1"}])
    put_block(tmp_path, "20261110T110000-b.json", None)
    assert PBC.author_green_of(tmp_path, "i1", "", FP) is None


# --- the per-check records ----------------------------------------------------------------------------------------

def rec(verdict="intended_failure", **over) -> dict:
    body = {"schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": "i1", "verdict": verdict,
            "recorded_at": "2026-11-10T10:00:00+00:00", "notes": ["a note"]}
    body.update(over)
    return body


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_check_records_under_checks_dir(tmp_path):
    """`<iid>--L<line>.json` in `work/probes/checks/`; the second check on the line `-2` (EP-O); no `target_line`: today's path."""
    probes = tmp_path / "work" / "probes"
    assert PL.probe_record_path(tmp_path, "i1") == probes / "i1.json"                           # byte for byte, as before
    assert PL.probe_record_path(tmp_path, "i1", "product") == probes / "product" / "i1.json"
    assert PL.probe_record_path(tmp_path, "i1", "alternative") == probes / "alternative" / "i1.json"
    for odd in (None, True, "46", 4.0):
        assert PL.probe_record_path(tmp_path, "i1", target_line=odd) == probes / "i1.json", odd
        assert PL.probe_record_path(tmp_path, "i1", target_line=odd, ordinal=2) == probes / "i1.json", odd
    assert PL.probe_record_path(tmp_path, "i1", "product", target_line=46) == probes / "product" / "i1.json"   # the default kind only
    assert PL.probe_record_path(tmp_path, "i1", target_line=46) == probes / "checks" / "i1--L46.json"
    assert PL.probe_record_path(tmp_path, "i1", target_line=46, ordinal=2) == probes / "checks" / "i1--L46-2.json"
    for one in (None, 0, 1, True, "2"):
        assert PL.probe_record_path(tmp_path, "i1", target_line=46, ordinal=one).name == "i1--L46.json", one
    first = PBC._check_record(tmp_path, "i1", 46, rec(target={"line": 46}))
    second = PBC._check_record(tmp_path, "i1", 46, rec("no_failure"), ordinal=2)
    assert first == probes / "checks" / "i1--L46.json" and second == probes / "checks" / "i1--L46-2.json"
    assert read(first)["verdict"] == "intended_failure" and read(second)["verdict"] == "no_failure"
    assert sorted(p.name for p in (probes / "checks").iterdir()) == ["i1--L46-2.json", "i1--L46.json"], "no temp file is left"
    assert not (probes / "i1.json").exists(), "the standing record is not touched"


def test_check_record_name_uses_the_existing_sanitising(tmp_path):
    odd = "tests/cart spec.ts::in stock?*"
    stem = PL.probe_record_path(tmp_path, odd).stem
    assert PL.probe_record_path(tmp_path, odd, target_line=7).name == f"{stem}--L7.json"
    assert not set('\\/:*?"<>| ') & set(PL.probe_record_path(tmp_path, odd, target_line=7).name)
    long_id = "x" * 300
    assert PL.probe_record_path(tmp_path, long_id, target_line=7).name.endswith("--L7.json")
    assert PL.probe_record_path(tmp_path, long_id, target_line=7, ordinal=2).name.endswith("--L7-2.json")
    assert PL.probe_record_path(tmp_path, long_id + "y", target_line=7) != PL.probe_record_path(tmp_path, long_id, target_line=7)
    written = PBC._check_record(tmp_path, odd, 7, rec())
    assert written.is_file() and written.parent.name == "checks"


def test_helper_called_by_two_two_records(tmp_path):
    """EP-D: a check in a helper called by two instances: each instance has its OWN record, never shared."""
    one = PBC._check_record(tmp_path, "i1", 176, rec(instance_id="i1"))
    two = PBC._check_record(tmp_path, "i2", 176, rec("no_failure", instance_id="i2"))
    assert one != two and one.is_file() and two.is_file()
    assert read(one)["instance_id"] == "i1" and read(one)["verdict"] == "intended_failure"
    assert read(two)["instance_id"] == "i2" and read(two)["verdict"] == "no_failure"


def test_check_record_never_overwrites_proved_by_a_weaker_outcome(tmp_path):
    """`keep_standing_record`'s rule, the same code: a run that judged nothing leaves the proved key as it was, with `last_attempt`."""
    path = PBC._check_record(tmp_path, "i1", 46, rec(test_file_sha256="s1"))
    for weaker in ("not_executed", "incomplete"):
        PBC._check_record(tmp_path, "i1", 46, rec(weaker, notes=[f"{weaker} run"]))
        stored = read(path)
        assert stored["verdict"] == "intended_failure" and stored["test_file_sha256"] == "s1", weaker
        assert stored["last_attempt"]["verdict"] == weaker and f"{weaker} run" in stored["last_attempt"]["why"]
    # the controls: a judged verdict replaces, and a weaker outcome over a record that proved nothing is stored
    PBC._check_record(tmp_path, "i1", 46, rec("no_failure"))
    assert read(path)["verdict"] == "no_failure" and "last_attempt" not in read(path)
    PBC._check_record(tmp_path, "i1", 46, rec("not_executed"))
    assert read(path)["verdict"] == "not_executed"
    # the second check on the line is another file: the first stays
    PBC._check_record(tmp_path, "i1", 46, rec("intended_failure"))
    PBC._check_record(tmp_path, "i1", 46, rec("no_failure"), ordinal=2)
    assert read(path)["verdict"] == "intended_failure"


def test_two_files_one_line_one_ordinal_two_records(tmp_path):
    """Measured before the fix: without `file` the two files' checks shared one path. With it each has its own record file."""
    assert PL.probe_record_path(tmp_path, "i1", target_line=10) == PL.probe_record_path(tmp_path, "i1", target_line=10, file=None)
    one = PBC._check_record(tmp_path, "i1", 10, rec(target={"file": "tests/test_a.py", "line": 10}), file="tests/test_a.py")
    two = PBC._check_record(tmp_path, "i1", 10, rec("no_failure", target={"file": "tests/helper.py", "line": 10}), file="tests/helper.py")
    assert one != two and one.parent == two.parent and one.is_file() and two.is_file()
    assert read(one)["verdict"] == "intended_failure" and read(two)["verdict"] == "no_failure"
    assert one.name.startswith("i1--L10-") and len(one.stem.rsplit("-", 1)[1]) == 8
    assert PL.probe_record_path(tmp_path, "i1", target_line=10, ordinal=2, file="tests/test_a.py").name.startswith("i1--L10-2-")
    assert PL.probe_record_path(tmp_path, "i1", target_line=10, file="") == PL.probe_record_path(tmp_path, "i1", target_line=10)
    assert PBC._check_proved(tmp_path, "i1", 10, 1, "E", "B", file="tests/helper.py") is False       # no entry_sha in these records
    for path, name in ((one, "tests/test_a.py"), (two, "tests/helper.py")):
        body = read(path)
        body.update(entry_sha="E", mutated_file={"path": name, "sha256": "B"}, verdict="intended_failure")
        path.write_text(json.dumps(body), encoding="utf-8")
    assert PBC._check_proved(tmp_path, "i1", 10, 1, "E", "B", file="tests/helper.py") is True
    two.unlink()
    assert PBC._check_proved(tmp_path, "i1", 10, 1, "E", "B", file="tests/helper.py") is False, "the other file's record is not read"


def test_backslash_and_slash_name_one_record(tmp_path):
    a = PL.probe_record_path(tmp_path, "i1", target_line=3, file="tests\\sub\\test_a.py")
    assert a == PL.probe_record_path(tmp_path, "i1", target_line=3, file="tests/sub/test_a.py")
    assert a != PL.probe_record_path(tmp_path, "i1", target_line=3, file="tests/sub/test_b.py")


def test_old_unhashed_record_is_read_only_for_the_file_it_names(tmp_path):
    old = PL.probe_record_path(tmp_path, "i1", target_line=10)                      # the pre-fix name
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps(rec(entry_sha="E", mutated_file={"path": "tests/test_a.py", "sha256": "B"},
                                  target={"file": "tests/test_a.py", "line": 10})), encoding="utf-8")
    assert PL.record_read_path(tmp_path, "i1", 10, file="tests/test_a.py") == old
    assert PBC._check_proved(tmp_path, "i1", 10, 1, "E", "B", file="tests/test_a.py") is True       # same file: still read
    assert PL.record_read_path(tmp_path, "i1", 10, file="tests\\test_a.py") == old
    assert PL.record_read_path(tmp_path, "i1", 10, file="tests/helper.py") != old
    assert PBC._check_proved(tmp_path, "i1", 10, 1, "E", "B", file="tests/helper.py") is False       # ANOTHER file: absent
    nameless = PL.probe_record_path(tmp_path, "i1", target_line=11)
    nameless.write_text(json.dumps(rec(entry_sha="E")), encoding="utf-8")
    assert PL.record_read_path(tmp_path, "i1", 11, file="tests/test_a.py") != nameless          # names no file: absent
    assert PL.record_read_path(tmp_path, "i1", 10) == old                                      # no file asked: today's path


def test_check_record_refuses_a_line_that_is_not_an_int(tmp_path):
    """INV: a per-check record never lands on the instance's STANDING record path."""
    standing = PL.probe_record_path(tmp_path, "i1")
    standing.parent.mkdir(parents=True)
    standing.write_text(json.dumps(rec()), encoding="utf-8")
    before = standing.read_bytes()
    for odd in (None, True, "46", 4.5):
        with pytest.raises(PBC.Refusal):
            PBC._check_record(tmp_path, "i1", odd, rec("no_failure"))
    assert standing.read_bytes() == before and not (standing.parent / "checks").exists()


class Repeat:
    """A task folder with a per-check record and the entry/identity `already_probed` asks about; no probe is run."""
    SHA, TEST = "a" * 64, "tests/test_calc.py"

    def __init__(self, tmp_path):
        self.task = tmp_path / "task"
        self.task.mkdir()
        self.entry = {"instance_id": "i1", "file": self.TEST}
        self.now = {"input_hash": self.SHA, "test_code_sha": "c" * 64, "instance_identity": {}}

    def write(self, line=46, **over):
        body = rec("no_failure", test_file_sha256=self.SHA, test_code_sha="c" * 64,
                   mutated_file={"path": self.TEST, "sha256": "d" * 64, "code_sha": "e" * 64},
                   target={"line": line, "end_line": line, "assertion_id": f"{self.TEST}:{line}", "is_assertion_id": False,
                           "source": "at"}, entry_sha="E1")
        body.update(over)
        path = PL.probe_record_path(self.task, "i1", target_line=line)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body), encoding="utf-8")
        return path

    def asked(self, line=46, **kwargs):
        return PL.already_probed(self.entry, {}, self.task, now=self.now, project=self.task.parent,
                                 target={"file": self.TEST, "line": line, "source": "at"}, **kwargs)


def test_already_probed_reads_checks_record_by_key_and_entry_sha(tmp_path):
    r = Repeat(tmp_path)
    assert r.asked(entry_sha="E1")["probed"] is False                       # no record
    r.write()
    got = r.asked(entry_sha="E1")
    assert got["probed"] is True and got["record"] == "work/probes/checks/i1--L46.json", got     # same key, same sha
    assert r.asked(entry_sha="E2")["probed"] is False                       # same key, another entry sha: runs
    assert r.asked(45, entry_sha="E1")["probed"] is False                   # another key
    assert r.asked(entry_sha="")["probed"] is True                          # the sha not asked: today's reading
    assert r.asked()["probed"] is True


def test_already_probed_checks_record_without_entry_sha_runs(tmp_path):
    r = Repeat(tmp_path)
    path = r.write()
    body = read(path)
    del body["entry_sha"]
    path.write_text(json.dumps(body), encoding="utf-8")
    assert r.asked(entry_sha="E1")["probed"] is False


def test_already_probed_unreadable_checks_record_is_not_probed(tmp_path):
    r = Repeat(tmp_path)
    r.write().write_text("{broken", encoding="utf-8")
    got = r.asked(entry_sha="E1")
    assert got["probed"] is False and any("cannot be read" in n for n in got["notes"]), got
    r.write().write_text("[]", encoding="utf-8")                            # a JSON that is not an object
    assert r.asked(entry_sha="E1")["probed"] is False


def test_already_probed_other_sha_of_the_bytes_runs(tmp_path):
    """The bytes' own identity still counts: the same key and entry sha over other test bytes runs the probe."""
    r = Repeat(tmp_path)
    r.write(test_file_sha256="b" * 64, test_code_sha="9" * 64)
    assert r.asked(entry_sha="E1")["probed"] is False
    r.write()                                                               # the control: the same bytes, the same key and sha
    assert r.asked(entry_sha="E1")["probed"] is True


def test_debt_scan_ignores_checks_dir(tmp_path):
    """`probe_debt._scan` and the handoff glob read `work/probes/*.json` non-recursively: a per-check record is not seen."""
    import handoff_check
    from types import SimpleNamespace
    task = tmp_path / "T-1"
    task.mkdir()
    check = PBC._check_record(task, "i1", 46, rec(test_node="tests/test_calc.py::test_calc"))
    assert check.parent.name == "checks"
    seen = PD._scan(task, {})
    assert seen == {"items": [], "info": []}, seen                          # nothing: the record is not listed, read or called unreadable
    assert handoff_check._probe_list(SimpleNamespace(root=task), {}) is None
    # the control: the same record one directory up IS seen by both
    standing = PL.probe_record_path(task, "i2")
    standing.write_text(json.dumps(rec(test_node="tests/test_calc.py::test_calc")), encoding="utf-8")
    assert any("work/probes/i2.json" in item["record"] for item in PD._scan(task, {})["info"])
    assert handoff_check._probe_list(SimpleNamespace(root=task), {})[0] == ["work/probes/i2.json"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
