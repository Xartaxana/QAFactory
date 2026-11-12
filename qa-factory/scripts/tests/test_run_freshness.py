"""HF2-11a: did the latest run of a test run the code the test holds now?

TP2-12586: after the fixtures of a story were edited, the factory reported the old green runs as the tests'
results. The run row already carries the producer's per-test shas (`instance_content_sha`, `instance_code_sha`);
`proof_level.instance_identity` measures the same two over the bytes on disk; `proof_level.run_freshness` compares
them with `same_test`'s rule and says `fresh`, `stale` or `unknown`. `probe_freshness` and `staleness` ask the same of a
test's live check; the window (`acceptance.validate_window`) turns a stale run into the gap `stale_run:<iid>`.

Every key runs on `test_probe_binding.Fixture`: a real project, real `build_mine_request` jobs, real `function_sha`.
Nothing launches pytest or a model.
"""
import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, finish, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import acceptance as AC  # noqa: E402
import controller as CONTROLLER  # noqa: E402
import proof_level as PL  # noqa: E402
import window_record as WR  # noqa: E402

import test_probe_binding as PB  # noqa: E402  (the Fixture: a project, a config, a dispatch, the author's jobs)
import test_window_record as WT  # noqa: E402  (the stand-in controller and detector of the pure `build`)

FILES = {"tests/conftest.py": PB.CONFTEST, "tests/plugins.py": PB.PLUGINS, "tests/test_a.py": PB.TEST_A,
         "tests/test_other.py": "def test_a():\n    assert 1 == 1\n"}
CONFTEST_BODY_EDIT = PB.CONFTEST.replace("return Db()", "return Db() if True else None")
TEST_CODE_EDIT = PB.TEST_A.replace('["alice"]', '["bob"]')
FRESH = ("fresh", "")


class Story:
    """The Fixture, the author's job and the run row that job's contract gives (what `run_suite.build_run_block` writes)."""

    def __init__(self, row_extra=None, *, job: bool = True):
        self.fix = PB.Fixture(FILES, [PB.row("test_a", "TC-1", "tests/test_a.py", **(row_extra or {}))],
                              scope=("TC-1",))
        self.root, self.task = self.fix.root, self.fix.task
        self.job = None
        if job:
            def declare(request):
                path = str((self.root / "tests" / "plugins.py").resolve())
                request["fingerprint_files"].append({"path": path, "sha256": PB.digest(path), "kind": "helper_files"})
            self.fix.job(["TC-1"], completed=False, edit=declare)   # the author declared the helper that gives `client`
            self.job = self.fix.job(["TC-1"])
        manifest = json.loads((self.task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        self.entry = manifest["tests"][0]
        contract = (self.job or {"request": {"instance_contracts": {"test_a": {}}}})["request"]["instance_contracts"]["test_a"]
        self.row = {"instance_id": "test_a", "status": "passed", "attempt_id": (self.job or {}).get("job_id", ""),
                    "instance_content_sha": contract.get("instance_content_sha", ""),
                    "instance_code_sha": contract.get("instance_code_sha", "")}

    def state(self, row=None, **kw) -> tuple:
        return PL.run_freshness(self.entry, self.row if row is None else row, self.task, **kw)

    def put(self, rel: str, text) -> None:
        PB.write(self.root / rel, text)

    def restore(self) -> None:
        for rel, text in FILES.items():
            self.put(rel, text)

    def close(self) -> None:
        self.fix.close()


def the_run_is_fresh_or_stale_by_the_code_it_ran():
    s = Story()
    try:
        check("the fixture's job carries both per-test shas (the control of every key below)",
              bool(s.row["instance_content_sha"] and s.row["instance_code_sha"]), str(s.row))
        # (a) the same bytes
        check_eq("K1 (a): equal instance shas - fresh", s.state(), FRESH)
        # (b) a comment, a docstring, a blank line in the test: D-0017's classifier, the code sha
        s.put("tests/test_a.py", PB.TEST_A.replace("    names = db.names()", "    # the names\n    names = db.names()"))
        check_eq("K1 (b): a comment in the test - fresh", s.state(), FRESH)
        s.put("tests/test_a.py", PB.TEST_A.replace("(db, client):\n", '(db, client):\n    """the first test"""\n', 1))
        check_eq("K1 (b): a docstring in the test - fresh", s.state(), FRESH)
        s.put("tests/test_a.py", PB.TEST_A.replace("    names = db.names()", "\n\n    names = db.names()\n"))
        check_eq("K1 (b): blank lines in the test - fresh", s.state(), FRESH)
        s.restore()
        # (c) a comment in conftest
        s.put("tests/conftest.py", "# the database fixture\n" + PB.CONFTEST)
        check_eq("K1 (c): a comment in conftest - fresh", s.state(), FRESH)
        s.restore()
        # (d) the body of a fixture in conftest: the test file is the same bytes, the identity is not
        s.put("tests/conftest.py", CONFTEST_BODY_EDIT)
        got = s.state()
        check_eq("K1 (d): a fixture body edited in conftest - stale", got[0], "stale")
        check_in("K1 (d): ...and the sentence names the run", f"changed since run {s.job['job_id']}", got[1])
        check_eq("K1 (d) control: the test file itself is byte-for-byte the same",
                 (s.root / "tests" / "test_a.py").read_text(encoding="utf-8"), PB.TEST_A)
        s.restore()
        # (e) a helper the test uses by name (the declared module that gives the fixture `client`)
        s.put("tests/plugins.py", PB.PLUGINS.replace("client-v1", "client-v2"))
        check_eq("K1 (e): a named helper edited - stale", s.state()[0], "stale")
        s.restore()
        # (f) a variable renamed: the code differs, a rename is not cosmetic
        s.put("tests/test_a.py", PB.TEST_A.replace("names", "rows"))
        check_eq("K1 (f): a variable renamed in the test - stale", s.state()[0], "stale")
        s.restore()
        # (g) the function renamed while the row is the old one: the fallback sha has scope `file`, never the function's
        s.put("tests/test_a.py", PB.TEST_A.replace("def test_a(", "def test_a_renamed("))
        check_eq("K1 (g): the function renamed, the run's row is the old one - stale", s.state()[0], "stale")
        s.restore()
        check_eq("K1: back to the original bytes - fresh again", s.state(), FRESH)
    finally:
        s.close()


def the_run_that_recorded_no_identity_is_unknown_and_never_fresh():
    s = Story()
    try:
        # (h) empty shas
        empty = dict(s.row, instance_content_sha="", instance_code_sha="")
        check_eq("K1 (h): the row's shas are empty - unknown, said so", s.state(empty), ("unknown", PL.WHY_RUN_NO_IDENTITY))
        # (i) only the raw one: "both or nothing" - a code-only or content-only row is no identity
        check_eq("K1 (i): only the content sha - unknown", s.state(dict(s.row, instance_code_sha="")),
                 ("unknown", PL.WHY_RUN_NO_IDENTITY))
        check_eq("K1 (i): only the code sha - unknown", s.state(dict(s.row, instance_content_sha="")),
                 ("unknown", PL.WHY_RUN_NO_IDENTITY))
        check_eq("K1: no row at all, a row that is no object - unknown, never a raise",
                 (s.state({}), PL.run_freshness(s.entry, None, s.task), PL.run_freshness(s.entry, "x", s.task)),
                 (("unknown", PL.WHY_RUN_NO_IDENTITY),) * 3)
        check_eq("run_identity: both shas or nothing, the attempt only when the row names it",
                 (PL.run_identity(s.row), PL.run_identity(empty), PL.run_identity(dict(s.row, attempt_id="")),
                  PL.run_identity(None)),
                 ({"instance_content_sha": s.row["instance_content_sha"], "instance_code_sha": s.row["instance_code_sha"],
                   "attempt_id": s.job["job_id"]}, {},
                  {"instance_content_sha": s.row["instance_content_sha"], "instance_code_sha": s.row["instance_code_sha"]},
                  {}))
        # the row of another file is never this test's: the job selected tests/test_a.py::test_a, not this row's file
        other = dict(s.entry, file="tests/test_other.py", selector="tests/test_other.py::test_a")
        other.pop("trace_binding", None)
        got = PL.run_freshness(other, s.row, s.task)
        check_eq("K1: a manifest row whose file is not the job's node - no identity of its own, unknown (not fresh)",
                 got[0], "unknown")
        # (l) the test has no identity because nothing selected it yet: FALL_THROUGH is unknown, whatever the row says
        for why in sorted(PL.FALL_THROUGH):
            now = {"input_hash": "r" * 64, "test_code_sha": "c", "instance_identity": {}, "why": why}
            check_eq(f"K1 (l): now has no identity because of `{why[:28]}...` - unknown, with its own sentence",
                     s.state(now=now), ("unknown", why))
        # (o) ...but a MEASUREMENT cause with the row's shas is a change, not an absence of news (P1)
        for why in sorted(PL.MEASUREMENT - {PL.WHY_NO_FILE}):
            now = {"input_hash": "r" * 64, "test_code_sha": "c", "instance_identity": {}, "why": why}
            check_eq(f"K1 (o): now has no identity because of `{why[:28]}...` - stale",
                     s.state(now=now), ("stale", PL.WHY_RUN_UNMEASURABLE))
        check_eq("...and the same cause with a row that recorded nothing is still unknown (rule 2 comes first)",
                 s.state(empty, now={"input_hash": "r" * 64, "instance_identity": {}, "why": PL.WHY_NO_CODE}),
                 ("unknown", PL.WHY_RUN_NO_IDENTITY))
        # a story whose jobs never selected the test: the real FALL_THROUGH
        bare = Story(job=False)
        try:
            check_eq("K1 (l): no run of the story selected the test - unknown, the cause printed",
                     bare.state(s.row), ("unknown", PL.WHY_NO_REQUEST))
        finally:
            bare.close()
            use_project(s.root)       # the Fixture points the process at ITS project; this story's is the one in use
            PL._reset()
        # an exception inside the measurement is `unknown`, said so
        real = PL.same_test
        PL.same_test = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            check_eq("K1: a measurement that raises is unknown, never an exception",
                     s.state(), ("unknown", "run freshness could not be measured (RuntimeError)"))
        finally:
            PL.same_test = real
    finally:
        s.close()


def a_pass_belongs_only_to_bytes_on_disk_and_to_a_helper_that_can_be_measured():
    s = Story()
    try:
        # (k) the file deleted
        test = s.root / "tests" / "test_a.py"
        moved = test.with_suffix(".gone")
        test.rename(moved)
        check_eq("K1 (k): the test file is gone - stale, with the file's own sentence", s.state(), ("stale", PL.WHY_NO_FILE))
        check_eq("K1 (k): ...even when the row recorded no identity (a pass belongs to bytes on disk)",
                 s.state(dict(s.row, instance_content_sha="", instance_code_sha="")), ("stale", PL.WHY_NO_FILE))
        moved.rename(test)
        # (o) a helper deleted: function_sha gives "" for it, and "" must never read fresh
        helper = s.root / "tests" / "plugins.py"
        text = helper.read_bytes()
        helper.unlink()
        check_eq("K1 (o): the helper the run declared is deleted - stale, not unknown, not fresh",
                 s.state(), ("stale", PL.WHY_RUN_UNMEASURABLE))
        helper.write_bytes(text)
        # ...nor a helper that is not UTF-8
        helper.write_bytes(text + b"# \xff\n")
        check_eq("K1 (o): the helper is not UTF-8 - stale", s.state(), ("stale", PL.WHY_RUN_UNMEASURABLE))
        helper.write_bytes(text)
        check_eq("K1: the helper back as it was - fresh", s.state(), FRESH)
    finally:
        s.close()


def the_last_edit_decides_and_time_decides_nothing():
    s = Story()
    try:
        test = s.root / "tests" / "test_a.py"
        # (m) an edit, then the revert
        s.put("tests/test_a.py", TEST_CODE_EDIT)
        check_eq("K1 (m): the edit changed the code - stale", s.state()[0], "stale")
        s.put("tests/test_a.py", PB.TEST_A)
        check_eq("K1 (m): reverted to the bytes that ran - fresh", s.state(), FRESH)
        # (n) two edits between the run and now: the last one decides
        s.put("tests/test_a.py", TEST_CODE_EDIT)
        s.put("tests/test_a.py", PB.TEST_A + "\n# only a comment after the code was put back\n")
        check_eq("K1 (n): a code edit, then the code restored and a comment added - fresh", s.state(), FRESH)
        s.put("tests/test_a.py", PB.TEST_A + "\n# a comment\n")
        s.put("tests/test_a.py", TEST_CODE_EDIT + "\n# a comment\n")
        check_eq("K1 (n): a comment, then a code edit - stale", s.state()[0], "stale")
        s.restore()
        # time: the test file is touched into the future, and into the past; neither moves the answer
        import os
        before = test.stat().st_mtime
        os.utime(test, (before + 86400, before + 86400))
        check_eq("K1: a file touched a day ahead, same bytes - fresh (mtime decides nothing)", s.state(), FRESH)
        s.put("tests/test_a.py", TEST_CODE_EDIT)
        os.utime(test, (before - 86400, before - 86400))
        check_eq("K1: a file with a code edit and an OLD mtime - stale (a run newer than the edit proves nothing)",
                 s.state()[0], "stale")
    finally:
        s.close()


def a_green_run_of_other_code_is_not_a_pass_for_the_blocked_context():
    """K6: `_passed_on_current_bytes` is a refactor - it keeps its direction (the blocked context reads "cannot tell" as
    passed) while asking the one predicate; the witness of every input is `test_blocked_by_env_window.py` C9."""
    s = Story()
    try:
        asked = lambda: AC._passed_on_current_bytes(s.entry, s.row, s.task)  # noqa: E731
        check_eq("K6: the same code - passed", asked(), True)
        s.put("tests/conftest.py", CONFTEST_BODY_EDIT)
        check_eq("K6: a fixture changed after the pass - a measured difference, NOT passed", asked(), False)
        s.restore()
        s.put("tests/test_a.py", PB.TEST_A + "\n# a comment\n")
        check_eq("K6: a comment only - passed", asked(), True)
        s.restore()
        (s.root / "tests" / "plugins.py").unlink()
        check_eq("K6: a helper deleted - run_freshness says stale, this context keeps passed (its own direction)",
                 (s.state()[0], asked()), ("stale", True))
        s.restore()
        test = s.root / "tests" / "test_a.py"
        test.rename(test.with_suffix(".gone"))
        check_eq("K6: the test file gone - run_freshness says stale, this context keeps passed",
                 (s.state()[0], asked()), ("stale", True))
        test.with_suffix(".gone").rename(test)
        check_eq("K6: a row with no shas - passed", AC._passed_on_current_bytes(s.entry, {"status": "passed"}, s.task), True)
        check_eq("K6: a failed run is never 'passed on the current bytes'",
                 AC._passed_on_current_bytes(s.entry, dict(s.row, status="failed"), s.task), False)
    finally:
        s.close()


# --- the live check ------------------------------------------------------------------------------------------

def receipt_story(**record_over):
    """A story whose row demands a live check, holds a receipt measured on the current bytes and a record of that probe."""
    s = Story({"change_disposition": "new_or_changed"})
    now = PL.instance_identity(s.entry, s.task, s.root)
    body = {"instance_id": "test_a", "case_version": "cv_1", "test_content_hash": now["input_hash"],
            "source_revision": "src", "build_id": "b", "mutation": "invert", "expected_assertion_failure": "x",
            "actual_failure": "x", "assertion_location": "t.py:1", "restoration_evidence": "r", "failure_kind": "assertion",
            "proof_level": "live", "probe_tool": "probe_by_code.py", "mutation_kind": "assertion", "immutable": True,
            "receipt_hash": "h-1", "test_code_sha": now["test_code_sha"], "instance_identity": now["instance_identity"],
            "probe_record": "work/probes/test_a.json"}
    path = PB.write(s.task / "work" / "sensitivity-receipts" / "test_a-live-1.json", body)
    s.entry = dict(s.entry, sensitivity_proof={"receipt_ref": {"path": path.relative_to(s.task).as_posix(),
                                                              "sha256": PB.digest(path)}})
    record = {"schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": "test_a", "verdict": "intended_failure",
              "recorded_at": "2026-09-20T10:00:00+00:00", "test_node": "tests/test_a.py::test_a", "mutation": "invert",
              "mutated_file": {"path": "tests/test_a.py", "sha256": now["input_hash"], "code_sha": now["test_code_sha"]},
              "mutation_detail": {"line": 3, "mutation": "invert"}}
    record.update(record_over)
    PB.write(PL.probe_record_path(s.task, "test_a"), {k: v for k, v in record.items() if v is not None})
    return s


def the_live_check_is_fresh_stale_missing_or_not_required():
    s = receipt_story()
    try:
        got = PL.probe_freshness(s.entry, {}, s.task)
        check_eq("K2: a receipt measured on these bytes - fresh, nothing to replay", (got["state"], got["replay"]), ("fresh", None))
        s.put("tests/test_a.py", PB.TEST_A + "\n# a comment\n")
        check_eq("K2: a comment-only edit - still fresh (D-0017)", PL.probe_freshness(s.entry, {}, s.task)["state"], "fresh")
        s.restore()
        s.put("tests/conftest.py", CONFTEST_BODY_EDIT)
        got = PL.probe_freshness(s.entry, {}, s.task)
        check_eq("K2: a fixture edited after the probe - stale, with what a re-probe by code needs",
                 (got["state"], got["replay"]),
                 ("stale", {"test": "tests/test_a.py::test_a", "instance": "test_a", "mutation": "invert", "oracle": ""}))
        check_eq("K2: ...and the sentence is the probe's", got["why"], PL.WHY_PROBE_CHANGED)
        # the oracle the probe followed out of the test is carried as `--oracle <file>::<function>`
        PB.write(PL.probe_record_path(s.task, "test_a"), {
            "probe_tool": "probe_by_code.py", "instance_id": "test_a", "verdict": "intended_failure",
            "test_node": "tests/test_a.py::test_a", "mutation": "invert",   # t-2113: `expected` is a removed kind, replayed as `invert` (PL.replay_mutation); this key is about the oracle
            "mutated_file": {"path": "tests/plugins.py", "sha256": "x", "code_sha": "y"},
            "mutation_detail": {"oracle_function": "client", "oracle_note": "followed"}})
        check_eq("K2: a probe of a helper's oracle replays with `oracle = <mutated file>::<function>`",
                 PL.probe_freshness(s.entry, {}, s.task)["replay"],
                 {"test": "tests/test_a.py::test_a", "instance": "test_a", "mutation": "invert",
                  "oracle": "tests/plugins.py::client"})
        # a record made with `--at`: the line anchor does not survive the edit - nothing to replay by code
        PB.write(PL.probe_record_path(s.task, "test_a"), {
            "probe_tool": "probe_by_code.py", "instance_id": "test_a", "test_node": "tests/test_a.py::test_a",
            "mutation": "invert", "mutation_detail": {"at": 7, "style": "detector"}})
        got = PL.probe_freshness(s.entry, {}, s.task)
        check_eq("K2: a record with `mutation_detail.at` - stale, replay None", (got["state"], got["replay"]), ("stale", None))
        # a record that names no test, or no mutation, or does not exist: stale, nothing to replay with
        PB.write(PL.probe_record_path(s.task, "test_a"), {"probe_tool": "probe_by_code.py", "instance_id": "test_a",
                                                         "mutation": "invert", "mutation_detail": {}})
        got = PL.probe_freshness(s.entry, {}, s.task)
        check_eq("K2: a record without `test_node` - stale, replay None", (got["state"], got["replay"]), ("stale", None))
        PB.write(PL.probe_record_path(s.task, "test_a"), {"test_node": "tests/test_a.py::test_a", "mutation_detail": {}})
        check_eq("K2: a record without a mutation - stale, replay None",
                 PL.probe_freshness(s.entry, {}, s.task)["replay"], None)
        PL.probe_record_path(s.task, "test_a").unlink()
        got = PL.probe_freshness(s.entry, {}, s.task)
        check_eq("K2: no record at all - stale, replay None", (got["state"], got["replay"]), ("stale", None))
        s.restore()
        # not required: the row is not new or changed
        check_eq("K2: no live check demanded - not_required",
                 PL.probe_freshness(dict(s.entry, change_disposition="unchanged"), {}, s.task)["state"], "not_required")
        check_eq("K2: a row that is no object - not_required, no raise", PL.probe_freshness(None, {}, s.task)["state"],
                 "not_required")
        # missing: demanded, and no receipt at all
        bare = dict(s.entry)
        bare.pop("sensitivity_proof")
        check_eq("K2: demanded and no receipt - missing (a gap of S5, not of the edit)",
                 PL.probe_freshness(bare, {}, s.task)["state"], "missing")
        # unknown: the file is gone / the vocabulary is unreadable
        test = s.root / "tests" / "test_a.py"
        test.rename(test.with_suffix(".gone"))
        check_eq("K2: the test file gone - unknown, said so", PL.probe_freshness(s.entry, {}, s.task)["state"], "unknown")
        test.with_suffix(".gone").rename(test)
        real = PL.reached
        PL.reached = lambda *a, **k: (_ for _ in ()).throw(PL.LevelsUnavailable("levels are gone"))
        try:
            got = PL.probe_freshness(s.entry, {}, s.task)
        finally:
            PL.reached = real
        check_eq("K2: the vocabulary of levels unreadable - unknown, with the door", got["state"], "unknown")
        check_in("K2: ...and the sentence carries the message", "levels are gone", got["why"])
    finally:
        s.close()


def tree_of(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def staleness_measures_once_per_instance_and_writes_nothing():
    s = receipt_story()
    try:
        name = "20260924T090000000000Z-run.json"
        PB.write(s.task / "work" / "run-blocks" / name, {
            "schema_version": 2, "block_id": name, "attempt_id": s.job["job_id"], "input_fingerprint": "fp",
            "execution_status": "passed", "results": [dict(s.row, input_fingerprint="fp")], "evidence": []})
        manifest = {"tests": [s.entry]}
        real, calls = PL.instance_identity, []

        def counted(*args, **kw):
            calls.append(1)
            return real(*args, **kw)
        PL.instance_identity = counted
        before = tree_of(s.root)
        try:
            got = PL.staleness(s.task, manifest, ["test_a", "nobody"])
            check_eq("K2: ONE instance_identity per instance that the manifest holds", len(calls), 1)
            check_eq("K2: a fresh run and a fresh live check", (got["test_a"]["run"], got["test_a"]["probe"]["state"]),
                     (FRESH, "fresh"))
            check_eq("K2: an id the manifest has no row for - unknown, said so",
                     (got["nobody"]["run"], got["nobody"]["probe"]["state"]), (("unknown", PL.NO_MANIFEST_ROW), "unknown"))
            check_eq("K2: staleness wrote nothing (FR-45)", tree_of(s.root), before)
            s.put("tests/conftest.py", CONFTEST_BODY_EDIT)
            calls.clear()
            after = PL.staleness(s.task, manifest, ["test_a"])
        finally:
            PL.instance_identity = real
        check_eq("K2: after a fixture edit both are stale, and the replay is carried",
                 (after["test_a"]["run"][0], after["test_a"]["probe"]["state"], bool(after["test_a"]["probe"]["replay"])),
                 ("stale", "stale", True))
        check_eq("K2: ...still ONE measurement", len(calls), 1)
        (s.task / "work" / "run-blocks" / name).unlink()
        check_eq("K2: an instance with no run - the run is unknown (WHY_NO_RUN), the live check still answers",
                 (PL.staleness(s.task, manifest, ["test_a"])["test_a"]["run"], ), (("unknown", PL.WHY_NO_RUN),))
    finally:
        s.close()


# --- the window ----------------------------------------------------------------------------------------------

class WindowStory(Story):
    """A story whose one instance is complete for the window except what the run says: approved, unchanged, with its
    obligation, assertion and defect location, and a run block that carries the run row's per-test shas."""

    def __init__(self, status="passed"):
        super().__init__({"critic_verdict": "approved", "change_disposition": "unchanged", "change_basis_ref": "manifest:TC-1",
                          "assertion_id": "tests/test_a.py:3", "defect_location": "src/a.py:1",
                          "obligation_refs": [{"obligation_id": "OB-1", "obligation_hash": "oh-1"}]})
        self.block_name = "20260924T090000000000Z-run.json"
        row = dict(self.row, status=status, input_fingerprint="fp")
        PB.write(self.task / "work" / "run-blocks" / self.block_name, {
            "schema_version": 2, "block_id": self.block_name, "attempt_id": self.job["job_id"], "dispatch_id": PB.DISPATCH,
            "input_fingerprint": "fp", "execution_status": status, "purpose": "initial", "results": [row],
            "evidence": [{"summary": "", "reporter": "none", "report_path": "", "report_sha256": ""}]})

    def built(self) -> tuple:
        real, CONTROLLER.Controller = CONTROLLER.Controller, WT.StandInController
        try:
            with WT.Detector({"pairs": [], "unmeasured": []}):
                window, notes = WR.build(self.task, WT.CRITIC)
        finally:
            CONTROLLER.Controller = real
        return window, notes

    def cli(self) -> tuple:
        out = io.StringIO()
        real_argv, real = sys.argv, CONTROLLER.Controller
        sys.argv = ["window_record.py", "--task", PB.TASK, "--dispatch", WT.CRITIC]
        CONTROLLER.Controller = WT.StandInController
        try:
            with WT.Detector({"pairs": [], "unmeasured": []}), contextlib.redirect_stdout(out):
                code = WR.main()
        finally:
            sys.argv, CONTROLLER.Controller = real_argv, real
        return code, out.getvalue()


def the_window_names_a_run_of_other_code_and_is_not_acceptable_by_code():
    s = WindowStory()
    try:
        window, _notes = s.built()
        item = window["instances"][0]
        check_eq("K3: the item carries the run's identity, copied", item.get("run_identity"),
                 {"instance_content_sha": s.row["instance_content_sha"], "instance_code_sha": s.row["instance_code_sha"],
                  "attempt_id": s.job["job_id"]})
        check_eq("K4 control: the same code ran - the window has no gap of any kind", AC.validate_window(window, s.task), [])
        code, out = s.cli()
        check_eq("K4 control: the CLI says the window is acceptable", (code, "the window is acceptable" in out), (0, True))
        # a comment in conftest: still the same code, still acceptable, and no 'not measured' line either
        s.put("tests/conftest.py", "# the database fixture\n" + PB.CONFTEST)
        code, out = s.cli()
        check_eq("K4: a comment-only edit of conftest - no gap, acceptable", (code, "stale_run" in out), (0, False))
        check_not_in("K4: ...and nothing is said about an unmeasured run", "run freshness not measured", out)
        # the fixture body changed after the run: the gap, its sentence, its door - and exit 1, NOT 'acceptable as unresolved'
        s.put("tests/conftest.py", CONFTEST_BODY_EDIT)
        window, notes = s.built()
        info: list = []
        lines = WR.verdict(s.task, window, notes, info)
        check_eq("K4: a green stale instance - the gap `stale_run:<iid>` and nothing else",
                 AC.validate_window(window, s.task), ["stale_run:test_a"])
        text = "\n".join(lines)
        check_in("K4: the printed line names the cause with the run's id", f"changed since run {s.job['job_id']}", text)
        check_in("K4: ...and the door", "run it again with `run_suite.py --mine <case>`", text)
        check_not_in("K4: ...with no placeholder left in it", "{why}", text)
        code, out = s.cli()
        check_eq("K4: the CLI refuses the window (derivable refuses `stale_run:`)",
                 (code, "stale_run:test_a" in out, "acceptable as unresolved" in out), (1, True, False))
        origin = WR.GAP_ORIGIN["stale_run"]
        check_eq("K4: GAP_ORIGIN carries the sentence and the door",
                 origin, ("the latest run of this instance ran other code than it holds now: {why}",
                          "run it again with `run_suite.py --mine <case>`"))
        check_eq("K4: `_explain_parts` explains the kind and does not crash", WR._explain_parts("stale_run:test_a", [])[1],
                 origin[1])
        check_not_in("K4: no recorded word is read for it", "stale_run", WR.WORD_READ_KINDS)
        # MEASUREMENT mirror: a helper deleted after the run - the item records why it has no identity
        s.restore()
        (s.root / "tests" / "plugins.py").unlink()
        window, _notes = s.built()
        item = window["instances"][0]
        check_eq("K4: a deleted helper - the item has no identity now and says why",
                 ("instance_identity" in item, item.get("instance_identity_why")), (False, PL.WHY_NO_CODE))
        check_eq("K4: ...and the gap is raised (a run that had an identity is not kept by a measurement that has none)",
                 AC.validate_window(window, s.task), ["stale_run:test_a"])
    finally:
        s.close()


def a_run_that_recorded_no_identity_is_printed_not_passed():
    s = WindowStory()
    try:
        name = s.task / "work" / "run-blocks" / s.block_name
        block = json.loads(name.read_text(encoding="utf-8"))
        block["results"][0].pop("instance_content_sha")
        block["results"][0].pop("instance_code_sha")
        PB.write(name, block)
        s.put("tests/conftest.py", CONFTEST_BODY_EDIT)
        window, notes = s.built()
        check_eq("K3: a row with no shas - the item has no `run_identity` key", "run_identity" in window["instances"][0], False)
        info: list = []
        lines = WR.verdict(s.task, window, notes, info)
        check_eq("K4: ...no gap (today's reading stays)", [l for l in lines if l.startswith("stale_run")], [])
        check_in("K4: ...and the info line says the freshness was not measured, and why",
                 f"run freshness not measured: {PL.WHY_RUN_NO_IDENTITY} (test_a)", info)
        code, out = s.cli()
        check_eq("K4: ...the CLI prints it as a note and the window is acceptable as before",
                 (code, f"note: run freshness not measured: {PL.WHY_RUN_NO_IDENTITY} (test_a)" in out), (0, True))
    finally:
        s.close()


def a_red_run_of_other_code_carries_both_gaps():
    s = WindowStory(status="failed")
    real_wr, real_ac = WR.red_by_requirement, AC.red_by_requirement
    try:
        s.put("tests/conftest.py", CONFTEST_BODY_EDIT)
        window, _notes = s.built()
        check_eq("K4: a plain red of other code - `product:` and `stale_run:`", AC.validate_window(window, s.task),
                 ["product:test_a", "stale_run:test_a"])
        stand_in = lambda *a, **k: {"test_a": [{"case": "TC-1", "reason": "contradicts_requirement"}]}  # noqa: E731
        WR.red_by_requirement = AC.red_by_requirement = stand_in
        window, _notes = s.built()
        check_eq("K4: a red its manifest row explains, of other code - both gaps",
                 AC.validate_window(window, s.task), ["contradicts_requirement:test_a", "stale_run:test_a"])
        code, out = s.cli()
        check_eq("K4 (m4): the window is NOT acceptable by code - exit 1, no 'acceptable as unresolved'",
                 (code, "stale_run:test_a" in out, "acceptable as unresolved" in out), (1, True, False))
        s.restore()
        code, out = s.cli()
        check_eq("K4 control: the same explained red on the same code - acceptable as unresolved, exit 0", code, 0)
    finally:
        WR.red_by_requirement, AC.red_by_requirement = real_wr, real_ac
        s.close()


# --- K5: the one carrier of the dispositions, read lazily -----------------------------------------------------

def the_dispositions_come_from_the_carrier_and_the_import_is_lazy():
    scripts = Path(SCRIPTS)
    literal = '"new_or_changed", "unchanged"'
    for name, expected in (("acceptance.py", 0), ("window_record.py", None)):
        count = (scripts / name).read_text(encoding="utf-8").count(literal)
        if expected is None:
            check(f"K5 control: the carrier line is in {name} (the same search finds it)", count >= 1, str(count))
        else:
            check_eq(f"K5: no literal set of the two dispositions left in {name}", count, expected)
    result = subprocess.run([sys.executable, "-B", "-c", "import sys, acceptance; print('window_record' in sys.modules)"],
                            cwd=str(scripts), capture_output=True, text=True, timeout=120)
    check_eq("K5: `import acceptance` from scripts/ loads no `window_record` (the import inside validate_window is lazy)",
             (result.returncode, result.stdout.strip()), (0, "False"))
    result = subprocess.run([sys.executable, "-B", "-c",
                             "import sys, acceptance; acceptance.validate_window("
                             "{'required_quality_checks': [], 'instances': [], 'not_applicable_reason': 'x'}, '.');"
                             "print('window_record' in sys.modules)"],
                            cwd=str(scripts), capture_output=True, text=True, timeout=120)
    check_eq("K5 control: the same process after a call to validate_window DOES hold it (the probe can say True)",
             (result.returncode, result.stdout.strip()), (0, "True"))
    # the values are the carrier's: a disposition the carrier lists is accepted, one it does not is the gap
    values = WR.REQUIRED_ROW_FIELDS["change_disposition"].values
    check_eq("K5: the carrier lists exactly the two dispositions", tuple(sorted(values)), ("new_or_changed", "unchanged"))
    window = {"schema_version": 2, "input_hash": "h", "required_quality_checks": [], "quality_receipts": [],
              "instances": [{"instance_id": "i1", "input_hash": "x", "outcome": "passed", "schema_version": 1,
                             "review": {"verdict": "approved", "input_hash": "x"}, "change_disposition": "sometimes",
                             "evidence_refs": []}]}
    check_in("K5: a disposition the carrier does not list is `change_disposition:` as ever",
             "change_disposition:i1", AC.validate_window(window, "."))


def main():
    the_run_is_fresh_or_stale_by_the_code_it_ran()
    the_run_that_recorded_no_identity_is_unknown_and_never_fresh()
    a_pass_belongs_only_to_bytes_on_disk_and_to_a_helper_that_can_be_measured()
    the_last_edit_decides_and_time_decides_nothing()
    a_green_run_of_other_code_is_not_a_pass_for_the_blocked_context()
    the_live_check_is_fresh_stale_missing_or_not_required()
    staleness_measures_once_per_instance_and_writes_nothing()
    the_window_names_a_run_of_other_code_and_is_not_acceptable_by_code()
    a_run_that_recorded_no_identity_is_printed_not_passed()
    a_red_run_of_other_code_carries_both_gaps()
    the_dispositions_come_from_the_carrier_and_the_import_is_lazy()
    finish("run freshness")


if __name__ == "__main__":
    main()
