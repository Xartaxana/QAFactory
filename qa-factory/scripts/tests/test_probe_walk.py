"""probe_by_code.py: the walk over the plan of one test's checks (t-2064 P4a item 1), on a STUB runner.

No real test runner starts: `run_request` is replaced by a function that reads the bytes the author's file holds AT THE MOMENT OF THE RUN
(the edit with its markers) and answers the report rows a scenario builds from them; `build_request` is replaced where the request is not
the point. The tests use the Python test of `tests/test_t.py` (the AST reader), whose `assert` is a soft form here and `assert_that` a
stopping one. A red names the branch (the test and its message). Runnable alone and collected by pytest; fast, no sleeps."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import execution_request as ER  # noqa: E402
import probe_by_code as PBC  # noqa: E402

NODE = "tests/test_t.py::test_run"
FILE = "tests/test_t.py"
SOFT = '    assert a == 1, "{n}"\n'
HARD = '    assert_that(a, equal_to(1), "{n}")\n'
TOKEN = re.compile(r"'qa-probe', '([0-9a-f]{12})'")


def entry_for(check: dict, kind: str = "actual", **more) -> dict:
    base = {"index": 1, "check": check["key"], "instance": "", "alternative": "", "kind": kind, "supposes": "s"}
    if kind == "actual":
        base["actual"] = "2"
    return dict(base, **more)


class World:
    """One test on disk, its plan, a stub runner and the log of every run: `runs` = [{bytes, tokens (line -> token), flags, left}]."""

    def __init__(self, tmp_path: Path, kinds: str = "sss", extra: str = "", flags=(), cut: str = "Test timeout of 9ms exceeded"):
        self.root, self.task_root = tmp_path / "proj", tmp_path / "task"
        (self.root / "tests").mkdir(parents=True)
        self.task_root.mkdir()
        body = "".join((SOFT if kind == "s" else HARD).format(n=f"c{number}") for number, kind in enumerate(kinds, 1))
        self.text = "def test_run():\n    a = 1\n" + body + extra
        self.path = self.root / FILE
        self.path.write_bytes(self.text.encode())
        self.original = self.text.encode()
        spec = PBC.parse_node(NODE)
        entry = dict(spec["entry"], soft_assert_patterns=[r"assert\s"], interruption_texts=[cut], marker_read=["message", "text"])
        if flags:
            entry["probe_no_retry"] = [{"source": "def test_run", "flags": list(flags)}]
        self.spec = dict(spec, entry=entry)
        self.checks = PBC.checks_of(self.original, self.spec, None, [], [], [])
        self.plan = {"checks": self.checks, "runs": PBC.run_plan(self.checks)}
        self.keys = [c["key"] for c in self.checks]
        self.ctx = PBC.ProbeCtx("T", "D", "i1", "TC-1", self.spec, {}, self.root, {}, self.task_root, False, "model",
                                self.task_root / "m.json", self.path, "")
        self.runs: list = []
        self.scenario = lambda world, run: []
        self.clock, self.step, self.green = [0.0], 0.0, True

    def entries(self, kind: str = "actual", keys=None) -> list:
        return [entry_for(c, kind) for c in self.checks if keys is None or c["key"] in keys]

    def tokens_in(self, data: bytes) -> dict:
        """{key: token} of the markers the edit put in: the check on a line owns the marker on that line."""
        out = {}
        for number, line in enumerate(data.decode().splitlines(), 1):
            hit = TOKEN.search(line)
            if hit:
                out[f"{FILE}:{number}"] = hit.group(1)
        return out

    def install(self, monkeypatch):
        world = self

        def fake_build(root, cfg, task, dispatch, case, spec, iid, mutation, reason, profile_id="", s6_close=False,
                       mutation_kind="assertion", extra_argv=()):
            return {"command": {"argv": ["runner"] + list(extra_argv)}, "instance_contracts": {}}, []

        def fake_run(root, request_path, timeout):
            run = {"bytes": world.path.read_bytes(), "flags": json.loads(Path(request_path).read_text())["command"]["argv"][1:],
                   "left": timeout}
            run["tokens"] = world.tokens_in(run["bytes"])
            world.runs.append(run)
            run["checks_seen"] = sorted(p.name for p in (world.task_root / "work" / "probes" / "checks").glob("*.json")) \
                if (world.task_root / "work" / "probes" / "checks").is_dir() else []
            rows = world.scenario(world, run)
            world.clock[0] += world.step
            report = world.task_root / "work" / f"r{len(world.runs)}.xml"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("x")
            run["rows"] = rows
            return None, {"report_evidence": {"path": report.relative_to(world.task_root).as_posix()}, "reporter": "junit-xml"}

        monkeypatch.setattr(PBC, "build_request", fake_build)
        monkeypatch.setattr(PBC, "run_request", fake_run)
        monkeypatch.setattr(PBC, "report_rows", lambda path, reporter, raw=False: world.runs[-1]["rows"])
        monkeypatch.setattr(PBC.reporters, "assertion_site", lambda row, *a, **k: dict(row.get("_site") or {}))
        monkeypatch.setattr(PBC, "_walk_clock", lambda: world.clock[0])
        monkeypatch.setattr(ER, "entry_profile_id", lambda entry: "")
        monkeypatch.setattr(PBC, "author_green_of", lambda *a: world.green)
        return self

    def walk(self, entries=None, timeout=100):
        locks: list = []
        try:
            return PBC._walk_plan(self.ctx, self.plan, self.entries() if entries is None else entries, locks, timeout)
        finally:
            PBC.release_locks(locks)

    def record(self, key: str) -> dict:
        check = next(c for c in self.checks if c["key"] == key)
        return json.loads(PBC.proof_level.probe_record_path(self.task_root, "i1", target_line=check["line"],
                                                                            file=check["file"]).read_text())


def row(status="failed", *texts, site=None, test_id="tests/test_t.py::test_run") -> dict:
    problems = [{"kind": "failure" if status == "failed" else "error", "message": text, "text": ""} for text in texts]
    return {"test_id": test_id, "status": status, "problems": problems, "_site": site or {}}


def thrown(world, run, *keys) -> str:
    """The failure text of the checks `keys` that fired in this run: their own markers."""
    return "\n".join(f"AssertionError: qa-probe-{run['tokens'][key]} {key}" for key in keys if key in run["tokens"])


# --- step 1: `_entry_sha`, `_check_proved`, the flags in `build_request` --------------------------------------------------------------

def test_entry_sha_is_stable_and_covers_the_entry():
    a = {"check": "k", "instance": "", "alternative": "", "kind": "actual", "actual": "2", "supposes": "s", "index": 1}
    assert PBC._entry_sha(a) == PBC._entry_sha(dict(a, index=7)), "the position in the file is not the entry"
    assert PBC._entry_sha(a) != PBC._entry_sha(dict(a, actual="3")) != PBC._entry_sha(dict(a, supposes="t")), "value and supposes count"
    assert PBC._entry_sha(a) != PBC._entry_sha(dict(a, instance="i1")), "the instance counts"
    find = {"check": "k", "kind": "find", "find": "x", "replace": "y", "supposes": "s"}
    assert PBC._entry_sha(find) != PBC._entry_sha(dict(find, replace="z")), "a find's replace counts"
    assert re.fullmatch(r"[0-9a-f]{64}", PBC._entry_sha(a))


def stored(tmp_path, line=3, ordinal=1, **fields):
    record = dict({"verdict": "intended_failure", "entry_sha": "E", "mutated_file": {"path": "t.py", "sha256": "B"}}, **fields)
    return record, PBC._check_record(tmp_path, "i1", line, record, ordinal)


@pytest.mark.parametrize("change,expected", [
    ({}, True),
    ({"verdict": "no_failure"}, False), ({"verdict": "not_reached"}, False), ({"verdict": "incomplete"}, False),
    ({"entry_sha": "other"}, False), ({"entry_sha": None}, False),
    ({"mutated_file": {"sha256": "other bytes"}}, False), ({"mutated_file": None}, False), ({"mutated_file": "x"}, False),
])
def test_check_proved_only_on_the_same_entry_and_bytes(tmp_path, change, expected):
    stored(tmp_path, **change)
    assert PBC._check_proved(tmp_path, "i1", 3, 1, "E", "B") is expected, change


def test_check_proved_edges(tmp_path):
    assert PBC._check_proved(tmp_path, "i1", 3, 1, "E", "B") is False, "no record: not proved"
    record, path = stored(tmp_path)
    assert PBC._check_proved(tmp_path, "i1", 3, 1, "", "B") is False and PBC._check_proved(tmp_path, "i1", 3, 1, "E", "") is False
    assert PBC._check_proved(tmp_path, "i1", 3, 1, "E") is False, "bytes not shown: not proved"
    assert PBC._check_proved(tmp_path, "i1", 4, 1, "E", "B") is False and PBC._check_proved(tmp_path, "i2", 3, 1, "E", "B") is False
    assert PBC._check_proved(tmp_path, "i1", 3, 2, "E", "B") is False, "the second check on the line has its own file"
    for line in (None, True, "3", 3.0):
        assert PBC._check_proved(tmp_path, "i1", line, 1, "E", "B") is False, line
    for junk in ("{not json", "[]", "null", "﻿" + json.dumps(record)[:-3], "[" * 100000):
        path.write_text(junk, encoding="utf-8")
        assert PBC._check_proved(tmp_path, "i1", 3, 1, "E", "B") is False, junk[:20]
    path.write_bytes(b"\xff\xfe\x00bad")
    assert PBC._check_proved(tmp_path, "i1", 3, 1, "E", "B") is False, "an unreadable record is not proved"
    path.write_text("﻿" + json.dumps(record), encoding="utf-8")
    assert PBC._check_proved(tmp_path, "i1", 3, 1, "E", "B") is True, "a BOM is tolerated"
    stored(tmp_path, ordinal=2)
    assert PBC._check_proved(tmp_path, "i1", 3, 2, "E", "B") is True


def build_world(tmp_path, monkeypatch, argv):
    """`build_request` over a stub of the one builder it calls: (spec, the request the stub returns)."""
    request = {"command": {"argv": list(argv)}, "selected_instance_ids": ["i1"], "input_fingerprint": "f" * 64}

    class Jobs:
        def __init__(self, *_a):
            pass

        def jobs(self):
            return []

    monkeypatch.setattr(ER, "build_mine_request", lambda *a, **k: (request, ["built"], True, True))
    monkeypatch.setattr(ER, "JobStore", Jobs)
    monkeypatch.setattr(PBC, "artifacts_dir", lambda task: tmp_path)
    monkeypatch.setattr(PBC, "_profile_cwd", lambda *a, **k: ".")
    return PBC.parse_node(NODE), request


def test_no_retry_flag_reaches_request(tmp_path, monkeypatch):
    """The flags are appended to `command.argv`, once, in order, with a note; the fingerprint and the key are not touched; the request
    still passes the validator's argv rule (a non-empty string array)."""
    spec, request = build_world(tmp_path, monkeypatch, ["node", "run.mjs"])
    got, notes = PBC.build_request(tmp_path, {}, "T", "D", "TC-1", spec, "i1", "model", "r", extra_argv=("--retries=0", "--x"))
    assert got["command"]["argv"] == ["node", "run.mjs", "--retries=0", "--x"], got["command"]
    assert got["input_fingerprint"] == "f" * 64, "the fingerprint is built from files, config and provenance, never from the argv"
    assert any("--retries=0 --x" in note for note in notes) and notes[0] == "built", notes
    assert all(isinstance(x, str) and x for x in got["command"]["argv"])


def test_no_retry_flags_default_leaves_the_argv(tmp_path, monkeypatch):
    spec, _request = build_world(tmp_path, monkeypatch, ["node", "run.mjs"])
    for extra in ((), None, ("", None, 3)):
        got, notes = PBC.build_request(tmp_path, {}, "T", "D", "TC-1", spec, "i1", "model", "r", extra_argv=extra)
        assert got["command"]["argv"] == ["node", "run.mjs"] and notes == ["built"], extra


# --- steps 2 and 3: the walk --------------------------------------------------------------------------------------------------------

def verdicts(result: dict) -> dict:
    return {key: outcome["verdict"] for key, outcome in result["outcomes"].items()}


def fire(*which):
    """A scenario: every run fails with the markers of the keys `which` (indexes into `world.keys`) that stand in that run."""
    return lambda world, run: [row("failed", thrown(world, run, *[world.keys[i] for i in which]))]


def test_three_soft_one_run_three_proved(tmp_path, monkeypatch):
    world = World(tmp_path, "sss").install(monkeypatch)
    world.scenario = fire(0, 1, 2)
    result = world.walk()
    assert verdicts(result) == {key: "intended_failure" for key in world.keys}, result["outcomes"]
    assert len(world.runs) == 1 and result["ended"] == "" and result["plan_remaining"] == []
    assert all(world.record(key)["verdict"] == "intended_failure" and world.record(key)["entry_sha"] for key in world.keys)
    assert world.path.read_bytes() == world.original, "the author's bytes are back"


def absent_scenario(alone):
    """Run 1 shows the markers of keys 0 and 1 only; later runs are `alone(world, run)`."""
    return lambda world, run: fire(0, 1)(world, run) if len(world.runs) == 1 else alone(world, run)


def test_absent_alone_passes_is_no_failure(tmp_path, monkeypatch):
    world = World(tmp_path, "sss").install(monkeypatch)
    world.scenario = absent_scenario(lambda w, run: [row("passed")])
    result = world.walk()
    assert len(world.runs) == 3, "the joint run, then key 1 (demoted: a key was absent) and key 2 alone, once each"
    assert verdicts(result)[world.keys[0]] == "intended_failure"
    last = result["outcomes"][world.keys[2]]
    assert last["verdict"] == "no_failure" and last["rerun_alone"] is False and last["reran_alone"] is True and last["read_in_joint"] is False


def test_absent_alone_marker_proves_with_note(tmp_path, monkeypatch):
    world = World(tmp_path, "sss").install(monkeypatch)
    world.scenario = absent_scenario(lambda w, run: [row("failed", thrown(w, run, *run["tokens"]))])
    result = world.walk()
    assert set(verdicts(result).values()) == {"intended_failure"}, result["outcomes"]
    assert "not read jointly" in result["outcomes"][world.keys[2]]["note"]
    assert result["outcomes"][world.keys[2]]["rerun_alone"] is False, "an alone outcome is final: no further rerun"
    assert len(world.runs) == 3, "no run beyond the one alone rerun each"


def test_rerun_new_token(tmp_path, monkeypatch):
    world = World(tmp_path, "sss").install(monkeypatch)
    world.scenario = absent_scenario(lambda w, run: [row("passed")])
    world.walk()
    joint, key = world.runs[0]["tokens"], world.keys[2]
    assert world.runs[2]["tokens"][key] != joint[key], "an alone rerun carries a token of its own (started_at per run)"
    assert world.runs[1]["tokens"][world.keys[1]] != joint[world.keys[1]]


def test_chain_three_runs_earlier_untouched(tmp_path, monkeypatch):
    world = World(tmp_path, "hhh").install(monkeypatch)
    world.scenario = lambda w, run: [row("failed", thrown(w, run, *run["tokens"]))]
    result = world.walk()
    assert len(world.runs) == 3 and set(verdicts(result).values()) == {"intended_failure"}, "n links, n runs"
    lines = world.text.splitlines()
    for number, run in enumerate(world.runs):
        seen = run["bytes"].decode().splitlines()
        changed = [i for i, (a, b) in enumerate(zip(lines, seen), 1) if a != b]
        assert changed == [3 + number], f"run {number + 1} saw the earlier checks as the author wrote them and edited only its own: {changed}"


def test_mutation_restored_after_each_row(tmp_path, monkeypatch):
    world = World(tmp_path, "hh").install(monkeypatch)
    world.scenario = lambda w, run: [row("failed", thrown(w, run, *run["tokens"]))]
    world.walk()
    assert [sorted(run["tokens"]) for run in world.runs] == [[world.keys[0]], [world.keys[1]]], "row 2 ran on the author's bytes + its edit"
    assert world.runs[1]["checks_seen"] == [PBC.proof_level.probe_record_path(world.task_root, "i1", target_line=world.checks[0]["line"],
                                                                      file=world.checks[0]["file"]).name], "row 1's record was written before row 2 ran"
    assert world.path.read_bytes() == world.original
    assert not list((world.root / "state" / "probe-copies").glob("*")) if (world.root / "state" / "probe-copies").is_dir() else True


def test_failed_restore_ends_walk(tmp_path, monkeypatch):
    world = World(tmp_path, "hhh").install(monkeypatch)
    world.scenario = lambda w, run: [row("failed", thrown(w, run, *run["tokens"]))]
    monkeypatch.setattr(PBC, "restore", lambda *a, **k: {"verified": False, "sha256": "x"})
    result = world.walk()
    assert len(world.runs) == 1 and result["ended"] == "restore_failed", "nothing else runs after a restore that is not verified"
    assert verdicts(result)[world.keys[0]] == "incomplete" and result["outcomes"][world.keys[0]]["cause"] == "tooling"
    assert result["plan_remaining"] == world.keys[1:] and verdicts(result)[world.keys[2]] == "not_reached"
    assert list(PBC.copy_dir(world.root).glob("*.orig")), "the copy stays"


def test_no_retry_flag_reaches_request_in_the_walk(tmp_path, monkeypatch):
    world = World(tmp_path, "s", flags=("--retries=0",)).install(monkeypatch)
    world.scenario = fire(0)
    world.walk()
    assert world.runs[0]["flags"] == ["--retries=0"]


def test_no_retry_dropped_when_no_rows(tmp_path, monkeypatch):
    world = World(tmp_path, "hh", flags=("--retries=0",)).install(monkeypatch)
    world.scenario = lambda w, run: [] if run["flags"] else [row("failed", thrown(w, run, *run["tokens"]))]
    result = world.walk()
    assert [run["flags"] for run in world.runs] == [["--retries=0"], [], []], "row 1 once more without them; row 2 never gets them"
    assert result["flags_dropped"] is True and sum("no-retry flags" in n for n in result["notes"]) == 1, result["notes"]
    assert set(verdicts(result).values()) == {"intended_failure"}


def test_no_retry_kept_when_rows_come(tmp_path, monkeypatch):
    world = World(tmp_path, "hh", flags=("--retries=0",)).install(monkeypatch)
    world.scenario = lambda w, run: [row("failed", thrown(w, run, *run["tokens"]))]
    result = world.walk()
    assert [run["flags"] for run in world.runs] == [["--retries=0"]] * 2 and result["flags_dropped"] is False


def test_param_rows_every_row(tmp_path, monkeypatch):
    world = World(tmp_path, "s").install(monkeypatch)
    ids = ("tests/test_t.py::test_run[a]", "tests/test_t.py::test_run[b]")
    world.scenario = lambda w, run: [row("failed", thrown(w, run, w.keys[0]), test_id=ids[0]), row("failed", "no marker", test_id=ids[1])]
    result = world.walk()
    outcome = result["outcomes"][world.keys[0]]
    assert outcome["verdict"] != "intended_failure" and [p["test_id"] for p in outcome["param_rows"]] == list(ids), "a proof never covers a row that failed elsewhere"
    world = World(tmp_path / "again", "s").install(monkeypatch)
    world.scenario = lambda w, run: [row("failed", thrown(w, run, w.keys[0]), test_id=i) for i in ids]
    assert world.walk()["outcomes"][world.keys[0]]["verdict"] == "intended_failure"


def test_chain_red_link_stops_walk(tmp_path, monkeypatch):
    world = World(tmp_path, "hhh").install(monkeypatch)
    world.scenario = lambda w, run: [row("failed", thrown(w, run, *run["tokens"]))] if len(w.runs) == 1 else \
        [row("failed", "boom in a", site={"location": f"{FILE}:{w.checks[0]['line']}"})]
    result = world.walk()
    assert len(world.runs) == 2 and result["ended"] == "stop", "no third run"
    assert verdicts(result) == {world.keys[0]: "intended_failure", world.keys[1]: "not_reached", world.keys[2]: "not_reached"}
    assert result["plan_remaining"] == world.keys[1:] and result["outcomes"][world.keys[1]]["plan_remaining"] == world.keys[1:]
    assert world.record(world.keys[1])["plan_remaining"] == world.keys[1:], "the not_reached key is recorded with the walk's final list"


def test_chain_no_location_walk_goes_on(tmp_path, monkeypatch):
    world = World(tmp_path, "hhh").install(monkeypatch)
    world.scenario = lambda w, run: [row("failed", thrown(w, run, *run["tokens"]))] if len(w.runs) != 2 else [row("failed", "throw")]
    result = world.walk()
    assert len(world.runs) == 3 and result["ended"] == ""
    assert verdicts(result) == {world.keys[0]: "intended_failure", world.keys[1]: "incomplete", world.keys[2]: "intended_failure"}


def test_time_is_checked_before_each_row(tmp_path, monkeypatch):
    world = World(tmp_path, "hhh").install(monkeypatch)
    world.step = 60.0
    world.scenario = lambda w, run: [row("failed", thrown(w, run, *run["tokens"]))]
    result = world.walk(timeout=100)
    assert len(world.runs) == 2 and result["ended"] == "time" and world.runs[1]["left"] <= 41
    assert result["plan_remaining"] == [world.keys[2]] and "--timeout" in result["outcomes"][world.keys[2]]["note"]
    assert world.record(world.keys[2])["verdict"] == "not_reached", "never a silent stop"
    again = World(tmp_path / "zero", "hh").install(monkeypatch)
    assert again.walk(timeout=0)["plan_remaining"] == again.keys and again.runs == [], "no time at all: nothing runs, everything is named"


def test_empty_plan_and_all_proved_run_nothing(tmp_path, monkeypatch):
    world = World(tmp_path, "ss").install(monkeypatch)
    world.scenario = fire(0, 1)
    assert world.walk(entries=[])["unmodelled"] == world.keys and world.runs == [], "no entry: nothing runs"
    assert PBC._walk_plan(world.ctx, {"checks": [], "runs": []}, [], [], 10)["outcomes"] == {} and world.runs == []
    world.walk()
    assert len(world.runs) == 1
    stamp = sorted((world.task_root / "work" / "probes" / "checks").glob("*.json"))
    second = world.walk()
    assert len(world.runs) == 1 and second["proved"] == world.keys and second["outcomes"] == {}, "proved on these bytes with this entry: skipped"
    assert stamp == sorted((world.task_root / "work" / "probes" / "checks").glob("*.json"))
    other = [dict(e, supposes="another supposition") for e in world.entries()]
    world.walk(entries=other)
    assert len(world.runs) == 2, "another entry sha runs again"


def test_not_here_and_product_are_dropped(tmp_path, monkeypatch):
    world = World(tmp_path, "sss").install(monkeypatch)
    world.scenario = fire(0, 2)
    entries = [entry_for(world.checks[0]), entry_for(world.checks[1], "not_here", instance="i1", not_here="w"),
               entry_for(world.checks[2])]
    result = world.walk(entries=entries)
    assert result["dropped"] == [world.keys[1]] and set(result["outcomes"]) == {world.keys[0], world.keys[2]}
    assert sorted(world.runs[0]["tokens"]) == [world.keys[0], world.keys[2]], "the dropped key is never edited"


def test_plan_refusal_is_that_rows_outcome(tmp_path, monkeypatch):
    world = World(tmp_path, "hh").install(monkeypatch)
    world.scenario = lambda w, run: [row("failed", thrown(w, run, *run["tokens"]))]
    entries = [entry_for(world.checks[0], "find", find="no such code", replace="x"), entry_for(world.checks[1])]
    result = world.walk(entries=entries)
    assert verdicts(result) == {world.keys[0]: "incomplete", world.keys[1]: "intended_failure"} and len(world.runs) == 1
    assert result["outcomes"][world.keys[0]]["cause"] == "tooling" and world.path.read_bytes() == world.original


def test_joint_row_settled_by_nothing_is_incomplete(tmp_path, monkeypatch):
    world = World(tmp_path, "ss").install(monkeypatch)
    world.scenario = fire(0, 1)
    monkeypatch.setattr(PBC, "_judge_joint_rows", lambda *a, **k: ({}, "go on"))
    result = world.walk()
    assert set(verdicts(result).values()) == {"incomplete"} and {o["cause"] for o in result["outcomes"].values()} == {"judgment"}


def test_runner_timeout_is_not_a_verdict(tmp_path, monkeypatch):
    world = World(tmp_path, "hh", flags=("--retries=0",)).install(monkeypatch)

    def cut(root, request_path, timeout):
        raise subprocess.TimeoutExpired("run", timeout)
    monkeypatch.setattr(PBC, "run_request", cut)
    result = world.walk()
    assert result["ended"] == "time" and result["flags_dropped"] is False, "a cut run is not the flags' trouble"
    assert "intended_failure" not in verdicts(result).values() and world.path.read_bytes() == world.original


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
