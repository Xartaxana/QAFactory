"""probe_by_code.py: the walk's owed edge cases (t-2064 P4a part 3b), on the stub runner of `test_probe_walk.py`.

One behaviour per test; each docstring names the ONE mutation of the product that turns it red. No real runner starts; no sleeps
(the walk's clock is a function the world sets). Fast: temp folders only. A red names the branch (the test and its message).
Runnable alone and collected by pytest."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import probe_by_code as PBC  # noqa: E402
from test_probe_walk import FILE, TOKEN, World, absent_scenario, entry_for, fire, row, thrown, verdicts  # noqa: E402

HELPER = "tests/helpers.py"


class HelperWorld(World):
    """A body of one soft check that calls `expect_cart`, whose one check lives in `tests/helpers.py` line 2 and runs ALONE."""

    def __init__(self, tmp_path: Path):
        super().__init__(tmp_path, "s", extra="    expect_cart(a)\n")
        self.helper_path = self.root / HELPER
        self.helper_original = b"def expect_cart(n):\n    assert n == 1\n"
        self.helper_path.write_bytes(self.helper_original)
        helpers = [{"file": HELPER, "data": self.helper_original, "hop": True, "chain": False}]
        bindings = [{"then": 3, "assertion_ref": f"{HELPER}:2"}]
        self.checks = PBC.checks_of(self.original, self.spec, None, bindings, helpers, [])
        self.plan = {"checks": self.checks, "runs": PBC.run_plan(self.checks)}
        self.keys = [c["key"] for c in self.checks]

    def helper_tokens(self) -> dict:
        return {f"{HELPER}:{number}": hit.group(1) for number, line in enumerate(self.helper_path.read_bytes().decode().splitlines(), 1)
                for hit in [TOKEN.search(line)] if hit}


def test_check_in_a_helper_file_runs_alone_and_is_recorded(tmp_path, monkeypatch):
    """A check that lives in a helper file: its own run edits THAT file (not the test), the test file is untouched in that run, both
    files are the author's after it, and its record names the helper as the mutated file. Killing mutation: `_walk_target` returns
    `ctx.path` for every file (the helper's edit would land in the test)."""
    world = HelperWorld(tmp_path).install(monkeypatch)
    assert world.keys == [f"{FILE}:3", f"{HELPER}:2"], world.keys
    seen = []

    def scenario(w, run):
        seen.append({"test_bytes": run["bytes"], "helper": w.helper_tokens(), "own": run["tokens"]})
        marks = w.helper_tokens() or run["tokens"]
        return [row("failed", "\n".join(f"AssertionError: qa-probe-{token} {key}" for key, token in marks.items()))]
    world.scenario = scenario
    result = world.walk()
    assert verdicts(result) == {key: "intended_failure" for key in world.keys}, result["outcomes"]
    assert len(world.runs) == 2 and result["ended"] == ""
    assert sorted(seen[0]["own"]) == [world.keys[0]] and seen[0]["helper"] == {}, "run 1 edits the test only"
    assert seen[1]["helper"].keys() == {world.keys[1]} and seen[1]["own"] == {}, "run 2 edits the helper only"
    assert world.path.read_bytes() == world.original and world.helper_path.read_bytes() == world.helper_original
    record = json.loads(PBC.proof_level.probe_record_path(world.task_root, "i1", target_line=2, file=HELPER).read_text())
    assert record["mutated_file"]["path"] == HELPER and record["verdict"] == "intended_failure", record


class TwoOnALine(World):
    """One statement line holding two checks: keys `tests/test_t.py:3` and `tests/test_t.py:3#2`."""

    def __init__(self, tmp_path: Path):
        super().__init__(tmp_path, "", extra="    assert a == 1; assert a == 1\n")     # equal texts: `_located` reads `#n` as the n-th EQUAL statement

    def tokens_in(self, data: bytes) -> dict:
        found = {}
        for number, line in enumerate(data.decode().splitlines(), 1):
            for index, hit in enumerate(TOKEN.finditer(line), 1):
                found[f"{FILE}:{number}" + ("" if index == 1 else f"#{index}")] = hit.group(1)
        return found


def test_second_check_on_a_line_has_its_own_record_and_the_first_is_untouched(tmp_path, monkeypatch):
    """A `#2` ordinal end to end: two checks on one line give two record files (`--L3.json`, `--L3-2.json`); a second walk whose
    entry for `#2` changed runs only `#2` and leaves the first record byte for byte. Killing mutation: `ordinal(key)` in `_walk_plan`
    returns 1 (the second check's record would overwrite the first's)."""
    world = TwoOnALine(tmp_path).install(monkeypatch)
    assert world.keys == [f"{FILE}:3", f"{FILE}:3#2"], world.keys
    world.scenario = lambda w, run: [row("failed", thrown(w, run, *run["tokens"]))]
    first_walk = world.walk()
    assert set(verdicts(first_walk).values()) == {"intended_failure"}, [o["note"] for o in first_walk["outcomes"].values()]
    checks_dir = world.task_root / "work" / "probes" / "checks"
    name1 = PBC.proof_level.probe_record_path(world.task_root, "i1", target_line=3, file=FILE).name
    name2 = PBC.proof_level.probe_record_path(world.task_root, "i1", target_line=3, ordinal=2, file=FILE).name
    assert sorted(p.name for p in checks_dir.glob("*.json")) == sorted([name2, name1])
    first = (checks_dir / name1).read_bytes()
    assert json.loads((checks_dir / name2).read_text())["check_key"] == world.keys[1]
    changed = [world.entries()[0], dict(world.entries()[1], supposes="another supposition")]
    result = world.walk(entries=changed)
    assert result["proved"] == [world.keys[0]] and list(result["outcomes"]) == [world.keys[1]], "only #2 runs again"
    assert len(world.runs) == 2 and len(TOKEN.findall(world.runs[-1]["bytes"].decode())) == 1, "one marker: only #2 was edited"
    assert (checks_dir / name1).read_bytes() == first, "the first record is untouched"
    assert json.loads((checks_dir / name2).read_text())["supposes"] == "another supposition"


class DifferingOnALine(TwoOnALine):
    """One line, two checks of DIFFERENT text: `assert a == 1; assert a == 2`, keys `:3` and `:3#2`."""

    def __init__(self, tmp_path: Path, line: str = "    assert a == 1; assert a == 2\n"):
        World.__init__(self, tmp_path, "", extra=line)


def _located_texts(world):
    found = [PBC._located(world.original, world.spec, c) for c in world.checks]
    return [f["text"][f["start"]:f["end"]] for f in found]


def test_differing_text_second_check_resolves_plans_and_walks(tmp_path, monkeypatch):
    """`assert a == 1; assert a == 2`: `#2` is the SECOND statement (not 'the 2nd of equal text'), a model on `#2` plans an edit of
    `a == 2` only, and the walk records both checks. Killing mutation: `_located` filters its candidates by the key's `statement_sha`
    again (the old rule: `#2` refused with 'only 1 stand there')."""
    world = DifferingOnALine(tmp_path).install(monkeypatch)
    assert world.keys == [f"{FILE}:3", f"{FILE}:3#2"], world.keys
    assert _located_texts(world) == ["assert a == 1", "assert a == 2"]
    after = PBC.plan_model(world.original, world.spec, [entry_for(world.checks[1])], world.checks)[0]
    assert after.decode() == world.text.replace("assert a == 2", "assert 2 == 2"), after.decode()
    world.scenario = lambda w, run: [row("failed", thrown(w, run, *run["tokens"]))]
    result = world.walk()
    assert set(verdicts(result).values()) == {"intended_failure"} and set(verdicts(result)) == set(world.keys), result["outcomes"]


def test_middle_check_equal_to_the_first_keeps_head_order(tmp_path, monkeypatch):
    """Three checks `a == 1; a == 1; a == 2` (the middle one equal to the first): `#2` is the SECOND, `#3` the third;
    no key resolves to another's statement. Killing mutation: `_located` takes the n-th among EQUAL-text statements (`#3` would be refused
    and `#2` would stay right by luck) or the n-th by text only (`#2` would land on the first)."""
    world = DifferingOnALine(tmp_path, "    assert a == 1; assert a == 1; assert a == 2\n").install(monkeypatch)
    assert world.keys == [f"{FILE}:3", f"{FILE}:3#2", f"{FILE}:3#3"], world.keys
    located = [PBC._located(world.original, world.spec, c) for c in world.checks]
    starts = [c["start"] for c in located]
    assert starts == sorted(set(starts)) and len(set(starts)) == 3, starts
    assert [c["text"][c["start"]:c["end"]] for c in located] == ["assert a == 1", "assert a == 1", "assert a == 2"]


def test_ordinal_beyond_the_count_is_refused_with_the_true_count(tmp_path, monkeypatch):
    """`#3` on a line of two checks: the refusal names the count (2). Killing mutation: the count in the refusal is the number of equal-text
    hits (1) or the bound check is dropped (IndexError instead of a Refusal)."""
    world = DifferingOnALine(tmp_path).install(monkeypatch)
    ghost = dict(world.checks[1], key=f"{FILE}:3#3")
    with pytest.raises(PBC.Refusal) as caught:
        PBC._located(world.original, world.spec, ghost)
    assert "3th check on line 3" in str(caught.value) and "only 2 stand there" in str(caught.value), str(caught.value)


def test_check_replaced_on_its_line_is_refused_not_misplaced(tmp_path, monkeypatch):
    """The invariant: a key never resolves to a statement other than the one `checks_of` gave it. After the second statement's text changes
    the `#2` key is refused. Killing mutation: the sha comparison in `_located` is dropped."""
    world = DifferingOnALine(tmp_path).install(monkeypatch)
    changed = world.original.replace(b"assert a == 2", b"assert a == 3")
    with pytest.raises(PBC.Refusal, match="not in these bytes"):
        PBC._located(changed, world.spec, world.checks[1])


def alone_scenario(world, run):
    """Joint run: keys 0 and 1 fire, key 2 is absent (key 1, the last read, is demoted): keys 1 and 2 are owed an alone rerun."""
    return fire(0, 1)(world, run)


def test_alone_rerun_that_stops_ends_the_walk_and_names_the_rest(tmp_path, monkeypatch):
    """An alone rerun whose failure lies on an EARLIER check's span ends the walk: no third run, the rerun key is `not_reached` and
    marked `reran_alone`, the key whose rerun was still owed says so, both are named in `plan_remaining`. Killing mutation: the
    `if again["move"] == "stop": ... break` of the alone loop removed (the next alone rerun would still run)."""
    world = World(tmp_path, "sss").install(monkeypatch)
    world.scenario = absent_scenario(lambda w, run: [row("failed", "boom", site={"location": f"{FILE}:{w.checks[0]['line']}"})])
    result = world.walk()
    assert len(world.runs) == 2 and result["ended"] == "stop", "joint run + ONE alone rerun, then nothing"
    k0, k1, k2 = world.keys
    assert verdicts(result) == {k0: "intended_failure", k1: "not_reached", k2: "not_reached"}, result["outcomes"]
    assert result["outcomes"][k1]["reran_alone"] is True
    assert "before its alone rerun" in result["outcomes"][k2]["note"] and result["outcomes"][k2]["rerun_alone"] is False
    assert result["plan_remaining"] == [k1, k2] and world.path.read_bytes() == world.original
    assert world.record(k2)["verdict"] == "not_reached", "never a silent stop"


def test_alone_rerun_whose_restore_fails_ends_the_walk_and_names_the_file(tmp_path, monkeypatch):
    """The restore after an ALONE rerun is not verified: the walk ends `restore_failed`, the outcome names the file and the release
    command, the copy of the author's bytes stays on disk, and no further run starts. Killing mutation: the `restore_failed` check of
    the alone loop removed (the next alone rerun would run on a tree nobody restored)."""
    world = World(tmp_path, "sss").install(monkeypatch)
    world.scenario = absent_scenario(lambda w, run: [row("passed")])
    real, calls = PBC.restore, []

    def restore(target, original, original_sha, stat, copy=None):
        calls.append(1)
        return {"verified": False, "error": "disk"} if len(calls) == 2 else real(target, original, original_sha, stat, copy=copy)
    monkeypatch.setattr(PBC, "restore", restore)
    result = world.walk()
    assert len(world.runs) == 2 and result["ended"] == "restore_failed" and result["restore"]["verified"] is False
    note = result["outcomes"][world.keys[1]]["note"]
    assert FILE in note and "--release-copy" in note, note
    assert [p.read_bytes() for p in PBC.copy_dir(world.root).glob("*.orig")] == [world.original], "the author's bytes are kept"
    assert result["plan_remaining"] == [world.keys[2]]


def test_time_running_out_inside_the_alone_loop(tmp_path, monkeypatch):
    """The budget is spent after the first alone rerun: the second alone rerun is NOT started, the key is `not_reached` naming the
    timeout, `ended` is `time`, and it is recorded. Killing mutation: the `_walk_clock() >= deadline` test of the alone loop removed."""
    world = World(tmp_path, "sss").install(monkeypatch)
    world.step = 60.0
    world.scenario = absent_scenario(lambda w, run: [row("failed", thrown(w, run, *run["tokens"]))])
    result = world.walk(timeout=100)
    assert len(world.runs) == 2 and result["ended"] == "time", "joint run (60 s) + one alone rerun, then the budget is spent"
    last = result["outcomes"][world.keys[2]]
    assert last["verdict"] == "not_reached" and "--timeout" in last["note"] and result["plan_remaining"] == [world.keys[2]]
    assert world.record(world.keys[2])["verdict"] == "not_reached"
    assert result["outcomes"][world.keys[1]]["verdict"] == "intended_failure", "the rerun that did run keeps its proof"


def throw_scenario(location):
    """Chain: runs 1 and 3 fire their own marker; run 2 fails with no marker, at `location`."""
    return lambda w, run: [row("failed", "throw", site={"location": location(w)})] if len(w.runs) == 2 else \
        [row("failed", thrown(w, run, *run["tokens"]))]


def test_helper_throw_does_not_stop_the_walk(tmp_path, monkeypatch):
    """A failure in a helper file at a line number that equals an earlier check's line is not that check's span: the walk goes on,
    the third check is proved by its own run. Killing mutation: `_location_hits` compares the line and not the file."""
    world = World(tmp_path, "hhh").install(monkeypatch)
    world.scenario = throw_scenario(lambda w: f"{HELPER}:{w.checks[0]['line']}")
    result = world.walk()
    assert len(world.runs) == 3 and result["ended"] == "", "no stop on a helper's throw"
    assert verdicts(result) == {world.keys[0]: "intended_failure", world.keys[1]: "incomplete", world.keys[2]: "intended_failure"}


def test_own_argument_throw_does_not_stop_the_walk(tmp_path, monkeypatch):
    """A failure on the edited check's OWN line (its argument expression threw before the check ran) is not an earlier check: the walk
    goes on and the next check is proved by its own run. Killing mutation: `_earlier_check_at` iterates `order` (the run's own key
    included) and drops the `key in edited` skip."""
    world = World(tmp_path, "hhh").install(monkeypatch)
    world.scenario = throw_scenario(lambda w: f"{FILE}:{w.checks[1]['line']}")
    result = world.walk()
    assert len(world.runs) == 3 and result["ended"] == ""
    assert verdicts(result)[world.keys[1]] == "incomplete" and verdicts(result)[world.keys[2]] == "intended_failure"


@pytest.mark.parametrize("which,find,why", [(0, "no such code", "no match"),
                                            (1, "1", "two matches in the region before the check (`a = 1`, `equal_to(1)`, `c1`)")])
def test_find_whose_target_breaks_is_that_rows_outcome_only(tmp_path, monkeypatch, which, find, why):
    """A `find` that matches nothing, or matches twice, in its check's statement: that row is `incomplete` / `tooling`, no run is made
    for it, the file is untouched, its record is written, and the walk goes on with the rest. Killing mutation: `settle` in
    `_walk_attempt` also sets `move` to `stop`, or `plan_model` takes the first of two matches."""
    world = World(tmp_path, "hhh").install(monkeypatch)
    world.scenario = lambda w, run: [row("failed", thrown(w, run, *run["tokens"]))]
    entries = world.entries()
    entries[which] = entry_for(world.checks[which], "find", find=find, replace="x")
    result = world.walk(entries=entries)
    broken = result["outcomes"][world.keys[which]]
    assert broken["verdict"] == "incomplete" and broken["cause"] == "tooling", f"{why}: {broken}"
    assert len(world.runs) == 2 and result["ended"] == "", f"{why}: the other two rows run"
    assert all(v == "intended_failure" for k, v in verdicts(result).items() if k != world.keys[which])
    assert world.path.read_bytes() == world.original and world.record(world.keys[which])["verdict"] == "incomplete"


def test_run_of_one_absent_is_not_rerun(tmp_path, monkeypatch):
    """A run of ONE check whose marker is absent is judged as it stands: no rerun alone (it already was alone), `reran_alone` stays
    off. Killing mutation: the `len(keys) >= 2` rule of the joint judge becomes `>= 1` (a pointless second run)."""
    world = World(tmp_path, "h").install(monkeypatch)
    world.scenario = lambda w, run: [row("failed", "no marker here")]
    result = world.walk()
    outcome = result["outcomes"][world.keys[0]]
    assert len(world.runs) == 1 and outcome["verdict"] != "intended_failure", outcome
    assert not outcome.get("reran_alone") and outcome["rerun_alone"] is False


def test_cut_last_token_is_rerun_alone_and_the_others_stand(tmp_path, monkeypatch):
    """The runner cut the test and all three markers are in the text: only the LAST read key is demoted and rerun alone (it may not
    have decided); the other two are proved from the joint run. Killing mutation: `demoted = [read[-1]]` becomes `[]` (a cut would
    prove) or `list(read)` (everything is rerun)."""
    world = World(tmp_path, "sss").install(monkeypatch)
    cut = "Test timeout of 9ms exceeded"
    world.scenario = lambda w, run: [row("failed", thrown(w, run, *run["tokens"]) + "\n" + cut)] if len(w.runs) == 1 else \
        [row("failed", thrown(w, run, *run["tokens"]))]
    result = world.walk()
    k0, k1, k2 = world.keys
    assert len(world.runs) == 2 and sorted(world.runs[1]["tokens"]) == [k2], "the last token is rerun alone, nothing else"
    assert set(verdicts(result).values()) == {"intended_failure"}
    assert result["outcomes"][k2]["reran_alone"] is True and result["outcomes"][k0]["read_in_joint"] is True
    assert not result["outcomes"][k1].get("reran_alone")


# --- Lead decision 2: a reused result is read with the flags it was made under ----------------------------------------------------------

def test_check_proved_reads_the_flags_the_record_was_made_under(tmp_path):
    """`_check_proved` with `flags`: the same list reuses; another list, the empty list against flags, flags against the empty list,
    and a record with NO flag field (an old one) do not; `flags=None` is today's rule. Killing mutation: the `no_retry_flags` test
    removed from `_check_proved`."""
    for stored_flags, asked, expected in [(["--r=0"], ["--r=0"], True), ([], [], True), ([], ["--r=0"], False), (["--r=0"], [], False),
                                          (["--a"], ["--b"], False), (None, [], False), (None, ["--r=0"], False)]:
        record = {"verdict": "intended_failure", "entry_sha": "E", "mutated_file": {"sha256": "B"}}
        if stored_flags is not None:
            record["no_retry_flags"] = stored_flags
        PBC._check_record(tmp_path, "i1", 3, record)
        assert PBC._check_proved(tmp_path, "i1", 3, 1, "E", "B", asked) is expected, (stored_flags, asked)
        assert PBC._check_proved(tmp_path, "i1", 3, 1, "E", "B") is True, "flags not asked: the old rule"


@pytest.mark.parametrize("first,second", [((), ("--retries=0",)), (("--retries=0",), ())])
def test_result_made_under_other_flags_is_not_reused(tmp_path, monkeypatch, first, second):
    """A result recorded by a walk WITHOUT the no-retry flags is not served to a walk that runs WITH them, and the reverse; the same
    flags reuse it. Killing mutation: `_walk_plan` calls `_check_proved` without `flags_on`."""
    world = World(tmp_path, "ss", flags=first).install(monkeypatch)
    world.scenario = fire(0, 1)
    world.walk()
    assert len(world.runs) == 1 and world.record(world.keys[0])["no_retry_flags"] == list(first)
    assert world.walk()["proved"] == world.keys and len(world.runs) == 1, "the same flags: reused"
    entry = world.ctx.spec["entry"]
    if second:
        entry["probe_no_retry"] = [{"source": "def test_run", "flags": list(second)}]
    else:
        entry.pop("probe_no_retry", None)
    got = world.walk()
    assert got["proved"] == [] and len(world.runs) == 2, f"flags {first} -> {second}: the walk runs again"
    assert world.runs[1]["flags"] == list(second) and world.record(world.keys[0])["no_retry_flags"] == list(second)


def test_old_record_without_flag_field_is_rerun(tmp_path, monkeypatch):
    """A record written before the field existed is not reused by a walk (rerun, never a pass). Killing mutation: a missing field read
    as an empty list."""
    world = World(tmp_path, "ss").install(monkeypatch)
    world.scenario = fire(0, 1)
    world.walk()
    for key in world.keys:
        path = PBC.proof_level.probe_record_path(world.task_root, "i1", target_line=next(c["line"] for c in world.checks if c["key"] == key),
                                                   file=FILE)
        data = json.loads(path.read_text())
        del data["no_retry_flags"]
        path.write_text(json.dumps(data))
    assert world.walk()["proved"] == [] and len(world.runs) == 2


def test_flags_dropped_run_records_empty_flags(tmp_path, monkeypatch):
    """A row made again WITHOUT the flags (the runner gave no rows) is recorded with `[]`, the flags its result was made under.
    Killing mutation: `used = []` of the fallback branch removed (the record would claim flags it never ran with)."""
    world = World(tmp_path, "h", flags=("--retries=0",)).install(monkeypatch)
    world.scenario = lambda w, run: [] if run["flags"] else [row("failed", thrown(w, run, *run["tokens"]))]
    result = world.walk()
    assert result["flags_dropped"] is True and world.record(world.keys[0])["no_retry_flags"] == []


# --- t-2064 P4b step 2a: the walk feeds the aggregate -----------------------------------------------------------------------------

def aggregate_on_disk(world) -> dict:
    return json.loads(PBC.record_path(world.task_root, "i1").read_text())


def hard_world(tmp_path, monkeypatch, kinds="hh"):
    world = World(tmp_path, kinds).install(monkeypatch)
    world.scenario = lambda w, run: [row("failed", thrown(w, run, *run["tokens"]))]
    return world


def test_walk_carries_evidence_and_input_hash_to_the_aggregate(tmp_path, monkeypatch):
    """A real walk of two checks: the result holds the evidence of BOTH runs (in run order) and the one `input_hash` (the fingerprint
    over the author's bytes: the stub request names no fingerprint files, so it is the author's sha), and the aggregate carries the first
    evidence as `evidence_ref` and the same `input_hash`; a walk in which no row ran has neither (absent, never invented).
    Kills: `_walk_plan` not returning `evidence_refs` / `input_hash` (the aggregate would read None), or collecting only the last run."""
    world = hard_world(tmp_path, monkeypatch)
    result = world.walk()
    assert [e["path"] for e in result["evidence_refs"]] == ["work/r1.xml", "work/r2.xml"] and all(e["sha256"] for e in result["evidence_refs"])
    assert result["input_hash"] == PBC.sha256(world.original)
    record = aggregate_on_disk(world)
    assert record["evidence_ref"] == "work/r1.xml" and record["evidence_refs"] == result["evidence_refs"]
    assert record["input_hash"] == result["input_hash"] and record["input_hash_source"]
    idle = World(tmp_path / "idle", "hh").install(monkeypatch)
    nothing = idle.walk(timeout=0)
    assert nothing["evidence_refs"] == [] and nothing["input_hash"] is None and idle.runs == []
    bare = aggregate_on_disk(idle)
    assert bare["evidence_ref"] is None and bare["input_hash"] is None and bare["verdict"] == "incomplete"


def test_aggregate_is_written_after_every_row_with_the_authors_bytes_back(tmp_path, monkeypatch):
    """Two rows: the aggregate is called after every row that has a follower, and once at the end (2 calls for two rows), is ALREADY on
    disk when row 2 runs (unfinished, row 1 proved, row 2 named in `plan_remaining`), and every call sees the author's bytes (never the
    mutated copy).
    Kills: no aggregate call inside the row loop (the count is 1 and row 2 sees no file), a call from inside the attempt (the bytes
    are the mutated ones at the call), or a second publish of the last row (3 calls: the regression PC2-4 removed)."""
    world = hard_world(tmp_path, monkeypatch)
    calls, at_run = [], []
    real_aggregate, real_run = PBC._aggregate_record, PBC.run_request

    def spy_aggregate(*args, **kwargs):
        calls.append(world.path.read_bytes() == world.original)
        return real_aggregate(*args, **kwargs)

    def spy_run(root, request_path, timeout):
        at_run.append(aggregate_on_disk(world) if PBC.record_path(world.task_root, "i1").is_file() else None)
        return real_run(root, request_path, timeout)
    monkeypatch.setattr(PBC, "_aggregate_record", spy_aggregate)
    monkeypatch.setattr(PBC, "run_request", spy_run)
    world.walk()
    assert calls == [True, True], calls
    assert at_run[0] is None, "before row 1 nothing is written"
    between = at_run[1]
    assert between and between["plan_unfinished"] is True and between["plan_remaining"] == [world.keys[1]]
    assert [c["verdict"] for c in between["checks"]] == ["intended_failure", "not_reached"]
    done = aggregate_on_disk(world)
    assert done["verdict"] == "intended_failure" and done["plan_unfinished"] is False and done["plan_remaining"] == []


def test_killed_walk_keeps_rows(tmp_path, monkeypatch):
    """The walk interrupted inside row 2's run (a kill, not an exception the walk catches): row 1's per-check record stands and so
    does an aggregate with `plan_unfinished: true` naming row 2 in `plan_remaining`; the author's bytes are back (the `finally`).
    Kills: writing the aggregate only at the end of the walk, or only after the last row."""
    world = hard_world(tmp_path, monkeypatch)
    real_run = PBC.run_request

    def kill_second(root, request_path, timeout):
        if len(world.runs) == 1:
            raise KeyboardInterrupt
        return real_run(root, request_path, timeout)
    monkeypatch.setattr(PBC, "run_request", kill_second)
    with pytest.raises(KeyboardInterrupt):
        world.walk()
    assert world.record(world.keys[0])["verdict"] == "intended_failure"
    record = aggregate_on_disk(world)
    assert record["plan_unfinished"] is True and record["plan_remaining"] == [world.keys[1]] and record["verdict"] == "incomplete"
    assert record["cause"] == "tooling" and [c["verdict"] for c in record["checks"]] == ["intended_failure", "not_reached"]
    assert world.path.read_bytes() == world.original


def test_a_failed_aggregate_write_loses_no_per_check_record(tmp_path, monkeypatch):
    """The aggregate write raising does not end the walk and loses nothing: both per-check records are on disk, the outcomes are
    returned, and a note names it. Kills: letting the aggregate's exception out of `_walk_plan`."""
    world = hard_world(tmp_path, monkeypatch)

    def broken(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(PBC, "_aggregate_record", broken)
    result = world.walk()
    assert verdicts(result) == {key: "intended_failure" for key in world.keys}
    assert all(world.record(key)["verdict"] == "intended_failure" for key in world.keys)
    assert any("aggregate record" in note and "disk full" in note for note in result["notes"])


def test_failed_restore_is_recorded_in_the_aggregate(tmp_path, monkeypatch):
    """A restore that is not verified: the aggregate IS written (after the row, recording the failure), `restore.verified` is false and
    the verdict is `incomplete`, `tooling`, never `intended_failure`. Kills: skipping the aggregate on `restore_failed`, or a
    `restore.verified: true` written beside an unverified restore."""
    world = hard_world(tmp_path, monkeypatch, "hhh")
    monkeypatch.setattr(PBC, "restore", lambda *a, **k: {"verified": False, "sha256": "x"})
    world.walk()
    record = aggregate_on_disk(world)
    assert record["restore"]["verified"] is False and record["verdict"] == "incomplete" and record["cause"] == "tooling"
    assert record["plan_remaining"] == world.keys[1:]


def test_one_helper_picks_the_entry():
    """The pick of the model entry for a check is ONE function both the walk and the aggregate call: the comparison that prefers an
    instance's own entry over a general one stands once in the module. Kills: an inline copy of the loop coming back into
    `_walk_plan` or `_aggregate_rows`."""
    import inspect
    source = Path(PBC.__file__).read_text(encoding="utf-8")
    assert source.count('not picked[one["check"]].get("instance")') == 1, "the entry pick stands in one place"
    for name in ("_walk_plan", "_aggregate_rows"):
        assert "_pick_entries(" in inspect.getsource(getattr(PBC, name)), name
        assert "picked[one[" not in inspect.getsource(getattr(PBC, name)), name


def test_pick_prefers_an_instances_own_entry_in_either_order(tmp_path):
    """An entry named for this instance beats a general one, whichever comes first; another instance's entry is never picked.
    Kills: taking the first entry only, or ignoring `instance`."""
    world = World(tmp_path, "s")
    key = world.keys[0]
    general, own = entry_for(world.checks[0], supposes="general"), entry_for(world.checks[0], instance="i1", supposes="own")
    other = entry_for(world.checks[0], instance="zz", supposes="other")
    for order in ([general, own, other], [other, own, general], [own, general]):
        assert PBC._pick_entries(world.ctx, order)[key]["supposes"] == "own"
    assert PBC._pick_entries(world.ctx, [other]) == {}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
