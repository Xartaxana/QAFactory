"""t-043 C: a review, a probe and a receipt speak for ONE test, and a repeated probe is answered.

Before this change every carrier of "this test was reviewed / probed" was bound to the raw bytes of the
whole test FILE: fixing test_b after test_a had been reviewed made test_a's review and probe stale, and
the S5 window asked the critic again. The run budget already knew better - `--mine` writes, per test,
`instance_contracts[<iid>].instance_content_sha` / `.instance_code_sha` (`execution_fingerprint.function_sha`:
the function, its class, the fixtures and helpers it uses, the module skeleton). Here that identity is
re-measured by its own producer (`execution_request.instance_shas`), carried by every review, probe and
receipt, and compared by ONE predicate (`proof_level.same_test`); the window (`acceptance.validate_window`)
binds through it.

Every fixture gets its author request from `build_mine_request` on the fixture project, stored as a job;
no sha is typed by hand. Nothing here launches pytest or a model.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     temp_dir, temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import execution_request as ER  # noqa: E402
import proof_level as PL  # noqa: E402
import red_sandbox as RS  # noqa: E402
import window_record as WR  # noqa: E402
from acceptance import validate_window  # noqa: E402
from execution_fingerprint import function_sha  # noqa: E402

import test_window_record as WT  # noqa: E402  (the S5 story fixture: a controller, a manifest, run blocks)

PY = sys.executable
TASK = "BIND-1"
DISPATCH = "S5-qa-automator-1"
PROVENANCE = {"profile_id": "unit", "timestamp": "2026-09-30T10:00:00Z", "environment_id": "local",
              "expected_source_revision": "source-1", "observed_runtime_identity": "build-1",
              "evidence_refs": ["probe"], "result": "matched",
              "provenance": {"technical_verification": True, "source_linkage": "exact",
                             "deployed_source_revision": "source-1"}}


def write(path: Path, value) -> Path:
    """Bytes as given, text and JSON as UTF-8 with LF line endings (`write_text` would write CRLF on Windows,
    and a fixture whose edits look for `\\n` would then find nothing)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_bytes((value if isinstance(value, str) else json.dumps(value, indent=1)).encode("utf-8"))
    return path


def digest(data) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else Path(data).read_bytes()).hexdigest()


# --- a project whose author run is a real job -------------------------------------------------------------

class Fixture:
    """A project with files, a config that names a pytest stand-in, a running dispatch and a manifest; the
    author's runs are `build_mine_request` requests stored in the story's job store."""

    def __init__(self, files: dict, rows: list, *, scope=("TC-1", "TC-2"), git: bool = False):
        self.root = temp_dir("qa-bind-")
        self.task = self.root / "qa-factory" / "artifacts" / TASK
        for rel, text in files.items():
            write(self.root / rel, text)
        self.provenance = dict(PROVENANCE)
        if git:
            self.revision = self._commit()
            self.provenance.update(expected_source_revision=self.revision,
                                   provenance=dict(PROVENANCE["provenance"], deployed_source_revision=self.revision))
        stand = write(self.root.parent / (self.root.name + "-bin") / "pytest", "import sys\nsys.exit(0)\n")
        self.probe_script = write(self.root.parent / (self.root.name + "-probe.py"),
                                  "import json\nprint(json.dumps(" + repr(self.provenance) + "))\n")
        self.cfg = {"tests_root": "tests", "app_root": ".",
                    "profiles": [{"profile_id": "unit", "selected": True, "roots": {"test": "tests"},
                                  "commands": {"one_test": {"argv": [PY, str(stand), "--junitxml", "{report_path}"],
                                                            "cwd": "."}},
                                  "reporter": {"kind": "junit-xml"}, "selectors": {"verified": True}}],
                    "execution": {"runtime_probes": {"unit": {"argv": [PY, str(self.probe_script)], "cwd": ".",
                                                               "timeout_s": 20}}}}
        write(self.root / "qa-factory" / "config.json", self.cfg)
        write(self.task / "pipeline.json", {"stages": {"S5": {"status": "running"}}})
        write(self.task / "state" / "controller.json", {
            "schema_version": "2", "revision": "1", "source_revision": self.provenance["expected_source_revision"],
            "dispatches": {DISPATCH: {"id": DISPATCH, "stage": "S5", "role": "qa-automator", "status": "running",
                                      "scope": list(scope), "budget": {"requests": 50}}}})
        write(self.task / "work" / "automation-manifest.json", {"tests": rows})
        use_project(self.root)
        PL._reset()

    def _commit(self) -> str:
        def git(*args):
            return subprocess.run(["git", "-C", str(self.root), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                                  capture_output=True, text=True, timeout=60)
        git("init", "-q")
        git("add", "-A")
        git("commit", "-q", "-m", "author")
        return git("rev-parse", "HEAD").stdout.strip()

    def job(self, cases, *, completed: bool = True, dispatch: str = DISPATCH, edit=None) -> dict:
        """The author's run of `cases` as a stored job: the request is `build_mine_request`'s, `edit` may
        change it (a helper the author declared) before it is stored."""
        request, _notes, _reuse, _verified = ER.build_mine_request(
            self.root, list(cases), cfg=self.cfg, task=TASK, dispatch_id=dispatch, probe=lambda spec: self.provenance)
        if edit:
            edit(request)
        store = ER.JobStore(self.task / "state" / "execution-jobs")
        _action, job = store.begin(request)
        if completed:
            job = store.update(job, status="completed", execution_status="passed", freshness="fresh")
        PL._reset()
        return job

    def close(self) -> None:
        cleanup(self.root)
        for extra in self.root.parent.glob(self.root.name + "-*"):
            cleanup(extra) if extra.is_dir() else extra.unlink(missing_ok=True)


def row(iid: str, case: str, file: str, selector: str = "", **extra) -> dict:
    return {"instance_id": iid, "case": case, "covers": [case], "file": file, "selector": selector or iid,
            "case_version_links": [{"case_id": case, "version": "cv_1"}], **extra}


CONFTEST = '''\
import pytest


@pytest.fixture
def db():
    return Db()


class Db:
    def names(self):
        return ["alice"]
'''
PLUGINS = '''\
import pytest


@pytest.fixture
def client():
    return "client-v1"
'''
TEST_A = '''\
def test_a(db, client):
    names = db.names()
    assert names == ["alice"], client


def test_c():
    assert 1 == 1
'''
TEST_B = '''\
def test_b():
    assert 2 == 2
'''


# --- AC7: `instance_shas` reproduces `instance_contracts` ---------------------------------------------------

def instance_shas_reproduces_the_contracts():
    fix = Fixture({"tests/conftest.py": CONFTEST, "tests/plugins.py": PLUGINS, "tests/test_a.py": TEST_A,
                   "tests/test_b.py": TEST_B},
                  [row("test_a", "TC-1", "tests/test_a.py"), row("test_b", "TC-2", "tests/test_b.py")])
    try:
        # the author declared a helper beyond the conftest chain (a role's own request, or an earlier run):
        # `plugins.py` provides the fixture `client`, which no conftest does
        def declare_plugins(request):
            path = str((fix.root / "tests" / "plugins.py").resolve())
            request["fingerprint_files"].append({"path": path, "sha256": digest(path), "kind": "helper_files"})
        fix.job(["TC-1"], completed=False, edit=declare_plugins)
        job = fix.job(["TC-1", "TC-2"], completed=False)
        request = job["request"]
        kinds = [(Path(r["path"]).name, r["kind"]) for r in request["fingerprint_files"]]
        check("the request inherited the declared helper and ran two test files",
              ("plugins.py", "helper_files") in kinds and ("test_a.py", "test_files") in kinds
              and ("test_b.py", "test_files") in kinds, str(kinds))
        for iid in ("test_a", "test_b"):
            contract = request["instance_contracts"][iid]
            measured = ER.instance_shas(fix.root, request, iid)
            check_eq(f"{iid}: instance_shas equals the contract's shas and scope",
                     measured, {"instance_content_sha": contract["instance_content_sha"],
                                "instance_code_sha": contract["instance_code_sha"],
                                "scope": contract["instance_content_scope"]})
        # MC11's kill: the inherited helper is part of the derivation - without it the sha is another one
        tests = [str((fix.root / "tests" / n).resolve()) for n in ("test_a.py", "test_b.py")]
        chain = ER._conftest_chain(tests, fix.root.resolve())
        without = function_sha(tests[0], "test_a", (), ER._helper_paths(chain, [], tests))["sha"]
        check("control: the same test measured WITHOUT the inherited helper has another sha",
              without and without != request["instance_contracts"]["test_a"]["instance_content_sha"])
        check_eq("and the helper's own edit moves the identity",
                 (lambda before: (write(fix.root / "tests" / "plugins.py", PLUGINS.replace("v1", "v2")),
                                  ER.instance_shas(fix.root, request, "test_a")["instance_content_sha"] != before)[1])(
                     ER.instance_shas(fix.root, request, "test_a")["instance_content_sha"]), True)
        write(fix.root / "tests" / "plugins.py", PLUGINS)

        # the extracted helpers: one derivation, first occurrence kept, chain first
        check_eq("_helper_paths: chain, sorted inherited, test files - each path once, at its first place",
                 ER._helper_paths(["c", "a"], ["b", "a"], ["t", "c"]), ["c", "a", "b", "t"])
        check_eq("_conftest_chain: nearest first, up to the run directory",
                 [Path(p).relative_to(fix.root.resolve()).as_posix()
                  for p in ER._conftest_chain(tests, fix.root.resolve())], ["tests/conftest.py"])

        # every way it can say nothing says `{}` - never a sha for a missing file
        check_eq("no selector for the instance: {}", ER.instance_shas(fix.root, request, "nobody"), {})
        not_pytest = json.loads(json.dumps(request))
        not_pytest["command"]["argv"] = ["dotnet", "test"]
        check_eq("a command that is not pytest: {}", ER.instance_shas(fix.root, not_pytest, "test_a"), {})
        (fix.root / "tests" / "test_b.py").rename(fix.root / "tests" / "test_b.gone")
        check_eq("no file: {} - not the sha of empty bytes", ER.instance_shas(fix.root, request, "test_b"), {})
        (fix.root / "tests" / "test_b.gone").rename(fix.root / "tests" / "test_b.py")
        import execution_fingerprint as EF
        real = EF.function_sha
        EF.function_sha = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            check_eq("function_sha raises: {}", ER.instance_shas(fix.root, request, "test_a"), {})
        finally:
            EF.function_sha = real
        check_eq("a request that is not a request: {}", ER.instance_shas(fix.root, {}, "test_a"), {})
    finally:
        fix.close()


def an_inherited_helper_that_is_also_a_test_file_is_stale_not_equal():
    """Edge 27: the run's own list puts an inherited helper before the test files; a request's
    `helper_files` leave the test files out, so the reconstruction puts it after. Where the order decides
    which of two same-named fixtures wins, the shas differ: one more run, one more probe - the safe
    direction, and pinned here so it is chosen, not found."""
    fix = Fixture({"tests/test_a.py": "def test_a(dup):\n    assert dup == 1\n",
                   "tests/test_b.py": "import pytest\n\n\n@pytest.fixture\ndef dup():\n    return 1\n",
                   "tests/test_c.py": "import pytest\n\n\n@pytest.fixture\ndef dup():\n    return 2\n"},
                  [row("test_a", "TC-1", "tests/test_a.py"), row("test_b", "TC-2", "tests/test_b.py"),
                   row("test_c", "TC-3", "tests/test_c.py")], scope=("TC-1", "TC-2", "TC-3"))
    try:
        def declare(request):
            path = str((fix.root / "tests" / "test_c.py").resolve())
            request["fingerprint_files"].append({"path": path, "sha256": digest(path), "kind": "helper_files"})
        fix.job(["TC-1"], completed=False, edit=declare)
        job = fix.job(["TC-1", "TC-2", "TC-3"], completed=False)
        request = job["request"]
        contract = request["instance_contracts"]["test_a"]["instance_content_sha"]
        measured = ER.instance_shas(fix.root, request, "test_a")["instance_content_sha"]
        check("the reconstructed order differs from the run's own: the shas are NOT equal (stale, never 'same')",
              measured and contract and measured != contract)
    finally:
        fix.close()


# --- the identity, and the predicate, on a fixture --------------------------------------------------------

def the_identity_is_measured_from_the_authors_job():
    fix = Fixture({"tests/conftest.py": CONFTEST, "tests/plugins.py": PLUGINS, "tests/test_a.py": TEST_A},
                  [row("test_a", "TC-1", "tests/test_a.py")], scope=("TC-1",))
    try:
        entry = json.loads((fix.task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))["tests"][0]
        before = PL.instance_identity(entry, fix.task, fix.root)
        check_eq("no job yet: no identity, and the cause is that no run selected the test",
                 (before["instance_identity"], before["why"]), ({}, PL.WHY_NO_REQUEST))
        check_eq("...and the job directory was not created for it (a reader writes nothing, FR-45)",
                 (fix.task / "state" / "execution-jobs").exists(), False)
        job = fix.job(["TC-1"])
        got = PL.instance_identity(entry, fix.task, fix.root)
        contract = job["request"]["instance_contracts"]["test_a"]
        check_eq("the identity is the job's contract shas, re-measured, with the job it came from",
                 got["instance_identity"], {"instance_content_sha": contract["instance_content_sha"],
                                            "instance_code_sha": contract["instance_code_sha"],
                                            "job_id": job["job_id"]})
        raw = (fix.root / "tests" / "test_a.py").read_bytes()
        check_eq("input_hash and test_code_sha come from the one read of the test file",
                 (got["input_hash"], got["test_code_sha"], got["why"]),
                 (digest(raw), PL.code_sha(raw, "test_a.py"), ""))
        check_eq("no story folder: only the file's own shas, and the cause says so",
                 (PL.instance_identity(entry, None, fix.root)["instance_identity"],
                  PL.instance_identity(entry, None, fix.root)["why"]), ({}, PL.WHY_NO_TASK))
        # the newest job that selected the row decides; a red probe's job is never the author's
        newer = json.loads(json.dumps(job))
        newer.update(job_id="a-red-probe", idempotency_key="probe-key", created_at="2999-01-01T00:00:00+00:00",
                     updated_at="2999-01-01T00:00:00+00:00")
        newer["request"]["purpose"] = "red_probe"
        newer["request"]["instance_contracts"]["test_a"]["instance_content_sha"] = "not-the-authors"
        ER.JobStore(fix.task / "state" / "execution-jobs").write(newer)
        PL._reset()
        check_eq("a red probe's job is not the author's run",
                 PL.instance_identity(entry, fix.task, fix.root)["instance_identity"]["job_id"], job["job_id"])
        # the reread guard: bytes that move between the two reads give no identity
        real = PL.current_test_bytes
        calls = []

        def racing(entry_, project=None):
            calls.append(1)
            data = real(entry_, project)
            if len(calls) == 1 and data is not None:  # the first read is the measured one; the file moves after it
                (fix.root / "tests" / "test_a.py").write_bytes(data + b"\n# moved\n")
            return data
        PL.current_test_bytes = racing
        try:
            PL._reset()
            moved = PL.instance_identity(entry, fix.task, fix.root)
        finally:
            PL.current_test_bytes = real
            write(fix.root / "tests" / "test_a.py", raw)
        check_eq("the file changed while it was measured: no identity, and the first read's shas are kept",
                 (moved["instance_identity"], moved["why"], moved["input_hash"]),
                 ({}, PL.WHY_CHANGED, digest(raw)))
        # undecodable bytes: the code sha is "" -> no identity (function_sha decodes with replacement, so two
        # different undecodable files would otherwise look alike)
        write(fix.root / "tests" / "test_a.py", raw + b"# \xff\xfe\n")
        PL._reset()
        bad = PL.instance_identity(entry, fix.task, fix.root)
        check_eq("undecodable test bytes: no identity, a measurement cause", (bad["instance_identity"], bad["why"]),
                 ({}, PL.WHY_NO_CODE))
        write(fix.root / "tests" / "test_a.py", raw)
        PL._reset()
        # a helper the test uses that is not UTF-8: the same
        write(fix.root / "tests" / "plugins.py", PLUGINS.encode("utf-8") + b"# \xff\n")
        # (plugins.py is not in the run, so the conftest chain is what the run lists: use the conftest)
        write(fix.root / "tests" / "plugins.py", PLUGINS)
        write(fix.root / "tests" / "conftest.py", CONFTEST.encode("utf-8") + b"# \xff\n")
        PL._reset()
        bad = PL.instance_identity(entry, fix.task, fix.root)
        check_eq("an undecodable conftest of the run: no identity either", (bad["instance_identity"], bad["why"]),
                 ({}, PL.WHY_NO_CODE))
        write(fix.root / "tests" / "conftest.py", CONFTEST)
        PL._reset()
        # the instance is not selected by any request: named by an alias, or as a parametrized form, it is
        alias = dict(entry, instance_id="TC-1::test_a")  # its bare spelling `test_a` is an alias of it
        check_eq("a row whose id the job spells by an alias is found",
                 PL.instance_identity(alias, fix.task, fix.root)["instance_identity"].get("job_id"), job["job_id"])
    finally:
        fix.close()


def a_newer_request_with_more_helpers_changes_the_identity():
    """Edge 26: the author's NEWEST request that selected the test decides its identity. A later run that inherited
    one more helper makes the identity another one - the review and the probe of the earlier one are stale: one
    re-review, one re-probe, a named cost. Two derivations never compare equal by accident."""
    fix = Fixture({"tests/conftest.py": CONFTEST, "tests/plugins.py": PLUGINS, "tests/test_a.py": TEST_A},
                  [row("test_a", "TC-1", "tests/test_a.py")], scope=("TC-1",))
    try:
        entry = json.loads((fix.task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))["tests"][0]
        fix.job(["TC-1"], completed=False)
        first = PL.instance_identity(entry, fix.task, fix.root)

        def declare(request):
            path = str((fix.root / "tests" / "plugins.py").resolve())
            request["fingerprint_files"].append({"path": path, "sha256": digest(path), "kind": "helper_files"})
        job = fix.job(["TC-1"], completed=False, edit=declare)
        # (the second job's own contract is what the newest request says; make it the newest by its clock)
        second = PL.instance_identity(entry, fix.task, fix.root)
        check_eq("the newer request's helper list is the identity's", second["instance_identity"]["job_id"], job["job_id"])
        check("...and it is another identity than the earlier request's", first["instance_identity"]
              and second["instance_identity"]["instance_content_sha"] != first["instance_identity"]["instance_content_sha"])
        check_eq("...so one carries the other as different: stale, never same",
                 PL.same_test(first, {"input_hash": second["input_hash"], "test_code_sha": second["test_code_sha"],
                                      "instance_identity": second["instance_identity"]}), "")
    finally:
        fix.close()


def a_helper_edited_under_a_cached_identity_is_seen():
    """Edge 28: the identity is cached for one process (FR-27). The key names the file's raw sha, the job directory
    and - beyond the plan's key - the size and mtime of every file the request's derivation reads, so a helper
    edited while a long-lived reader (the driver, the dashboard) holds a cached identity is seen by its NEXT
    question, not only by the next process: a stale 'same' is the one error this identity may not make."""
    fix = Fixture({"tests/conftest.py": CONFTEST, "tests/plugins.py": PLUGINS, "tests/test_a.py": TEST_A},
                  [row("test_a", "TC-1", "tests/test_a.py")], scope=("TC-1",))
    try:
        entry = json.loads((fix.task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))["tests"][0]
        fix.job(["TC-1"], completed=False)
        first = PL.instance_identity(entry, fix.task, fix.root)["instance_identity"]["instance_content_sha"]
        again = PL.instance_identity(entry, fix.task, fix.root)["instance_identity"]["instance_content_sha"]
        check_eq("asked twice over the same files: the same identity (from the cache)", again, first)
        write(fix.root / "tests" / "conftest.py", CONFTEST.replace('["alice"]', '["bob", "carol"]'))
        seen = PL.instance_identity(entry, fix.task, fix.root)["instance_identity"]["instance_content_sha"]
        check("the conftest edited under the cached identity: the next question sees it, with no reset", seen != first)
        PL._reset()
        check_eq("...and a new process (a reset) sees the same", PL.instance_identity(entry, fix.task, fix.root)
                 ["instance_identity"]["instance_content_sha"], seen)
    finally:
        fix.close()


def a_probe_record_of_one_id_never_answers_for_another():
    """Edge 29: an id is an identity, not a file name. At and beyond the name limit two ids stay two records."""
    root = temp_dir("qa-bind-names-")
    try:
        limit = PL.NAME_LIMIT
        at, beyond = PL.probe_record_path(root, "a" * limit, "product"), PL.probe_record_path(root, "a" * (limit + 1), "product")
        check("100 and 101 characters: two records", at != beyond, f"{at.name} {beyond.name}")
        check_eq("AT the limit the stem is the id itself", at.name, "a" * limit + ".json")
        check("BEYOND it the stem is cut and told apart by a hash of the WHOLE id", len(beyond.stem) < limit + 12
              and beyond.stem.startswith("a" * limit + "-"))
        long_one, long_two = "b" * 299 + "x", "b" * 299 + "y"
        check("two long ids that share their first 299 characters stay two records",
              PL.probe_record_path(root, long_one) != PL.probe_record_path(root, long_two))
        check_eq("the product record sits beside the live one, in its own folder",
                 (PL.probe_record_path(root, "i", "product").parent.name, PL.probe_record_path(root, "i").parent.name),
                 ("product", "probes"))
        check("an id with `::`, `[`, `/` and a space is a file name a file system takes: no separator in it",
              not any(ch in PL.probe_record_path(root, "TC-1::test_x[a/b c]").name for ch in '\\/:*?"<>|'))
    finally:
        cleanup(root)


# (the truth table of `same_test` is in test_proof_level.py, where MC4 is killed)

# --- already_probed: the mutated-file check, and the empty shas -------------------------------------------

def a_probe_answers_only_while_what_it_mutated_holds():
    fix = Fixture({"tests/test_a.py": "def test_a(dup):\n    assert dup == 1\n", "tests/helper.py": "VALUE = 1\n"},
                  [row("test_a", "TC-1", "tests/test_a.py")], scope=("TC-1",))
    try:
        job = fix.job(["TC-1"])
        entry = json.loads((fix.task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))["tests"][0]
        now = PL.instance_identity(entry, fix.task, fix.root)
        helper = fix.root / "tests" / "helper.py"

        def record(**over):
            body = {"schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": "test_a",
                    "verdict": "no_failure", "recorded_at": "2026-09-20T10:00:00+00:00",
                    "test_file_sha256": now["input_hash"], "test_code_sha": now["test_code_sha"],
                    "instance_identity": now["instance_identity"],
                    "receipt": {"path": "work/sensitivity-receipts/test_a-live-1.json"},
                    "mutated_file": {"path": "tests/helper.py", "sha256": digest(helper),
                                     "code_sha": PL.code_sha(helper.read_bytes(), "helper.py")}}
            body.update(over)
            write(PL.probe_record_path(fix.task, "test_a"), body)
        record()
        got = PL.already_probed(entry, {}, fix.task, now=now, project=fix.root)
        check_eq("a record whose mutated helper is as it was: answered", (got["probed"], got["by"], got["holds"]),
                 (True, "probe_record", "instance"))
        write(helper, "VALUE = 2\n")
        check_eq("the oracle helper's CODE changed since: not answered (t-061 fix 2)",
                 PL.already_probed(entry, {}, fix.task, now=now, project=fix.root)["probed"], False)
        write(helper, "# a comment\nVALUE = 1\n")
        check_eq("...a comment there keeps it: the code is the same",
                 PL.already_probed(entry, {}, fix.task, now=now, project=fix.root)["probed"], True)
        write(helper, "VALUE = 1\n")
        helper.unlink()
        check_eq("the helper is gone: it cannot be checked, so it does not block",
                 PL.already_probed(entry, {}, fix.task, now=now, project=fix.root)["probed"], False)
        write(helper, "VALUE = 1\n")
        record(mutated_file={"path": "tests/helper.py", "sha256": "", "code_sha": ""})
        check_eq("a record with an EMPTY sha on both sides of the mutated file does not block (t-061 fix 6)",
                 PL.already_probed(entry, {}, fix.task, now=now, project=fix.root)["probed"], False)
        record(mutated_file={"path": "tests/helper.py", "sha256": "", "code_sha": ""},
               mutated_files=[{"path": "tests/helper.py", "sha256": "", "code_sha": ""}])
        check_eq("...in either spelling of the key",
                 PL.already_probed(entry, {}, fix.task, now=now, project=fix.root)["probed"], False)
        # an empty raw sha on both sides of the TEST: nothing to compare, never 'the same'
        empty = {"input_hash": "", "test_code_sha": "", "instance_identity": {}, "why": PL.WHY_NO_REQUEST}
        record(test_file_sha256="", test_code_sha="", instance_identity={})
        check_eq("a record and a test that both have no readable bytes: not answered",
                 PL.already_probed(entry, {}, fix.task, now=empty, project=fix.root)["probed"], False)
        # a receipt: blocks only when the record behind it holds
        receipt = {"instance_id": "test_a", "case_version": "cv_1", "test_content_hash": now["input_hash"],
                   "source_revision": "src", "build_id": "b", "mutation": "invert",
                   "expected_assertion_failure": "x", "actual_failure": "x", "assertion_location": "t.py:1",
                   "restoration_evidence": "r", "failure_kind": "assertion", "proof_level": "live",
                   "probe_tool": "probe_by_code.py", "mutation_kind": "assertion", "immutable": True,
                   "receipt_hash": "h-1", "test_code_sha": now["test_code_sha"],
                   "instance_identity": now["instance_identity"],
                   "probe_record": "work/probes/test_a.json"}
        path = write(fix.task / "work" / "sensitivity-receipts" / "test_a-live-1.json", receipt)
        with_receipt = dict(entry, sensitivity_proof={"receipt_ref": {"path": path.relative_to(fix.task).as_posix(),
                                                                      "sha256": digest(path)}})
        record(verdict="intended_failure")
        got = PL.already_probed(with_receipt, {}, fix.task, now=now, project=fix.root)
        check_eq("a receipt whose record holds: answered by the receipt", (got["probed"], got["by"], got["level"]),
                 (True, "receipt", "live"))
        check_in("...in its own words: the level, the bytes, the door", "already holds a receipt that the check is live "
                 "for these bytes", got["words"])
        write(helper, "VALUE = 3\n")
        check_eq("...and a receipt whose MUTATED HELPER changed after the probe does not block (t-061 fix 2)",
                 PL.already_probed(with_receipt, {}, fix.task, now=now, project=fix.root)["probed"], False)
        write(helper, "VALUE = 1\n")
        PL.probe_record_path(fix.task, "test_a").unlink()
        check_eq("a receipt with no record behind it cannot say what it mutated: it does not block either",
                 PL.already_probed(with_receipt, {}, fix.task, now=now, project=fix.root)["probed"], False)
        # the receipt of a probe whose oracle was the test itself blocks; its record is the same
        record(verdict="intended_failure", mutated_file={"path": "tests/test_a.py", "sha256": now["input_hash"],
                                                         "code_sha": now["test_code_sha"]})
        check_eq("an oracle in the test itself: the test file is same_test's, nothing else to hold",
                 PL.already_probed(with_receipt, {}, fix.task, now=now, project=fix.root)["probed"], True)
        check_eq("the job in the identity is the author's", now["instance_identity"]["job_id"], job["job_id"])
    finally:
        fix.close()


def a_later_record_does_not_speak_for_a_receipt():
    """t-075 probe A: `receipt.probe_record` is `work/probes/<iid>.json`, which every LATER probe overwrites.
    A `not_executed` rerun over a CHANGED oracle must not be refused as `by=receipt`: the receipt carries what
    it mutated (`mutated_file`), and a record counts behind a receipt only when it is that receipt's own probe."""
    fix = Fixture({"tests/test_a.py": "def test_a(dup):\n    assert dup == 1\n", "tests/helper.py": "VALUE = 1\n"},
                  [row("test_a", "TC-1", "tests/test_a.py")], scope=("TC-1",))
    try:
        fix.job(["TC-1"])
        entry = json.loads((fix.task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))["tests"][0]
        now = PL.instance_identity(entry, fix.task, fix.root)
        helper = fix.root / "tests" / "helper.py"
        mutated = {"path": "tests/helper.py", "sha256": digest(helper),
                   "code_sha": PL.code_sha(helper.read_bytes(), "helper.py")}
        rel = "work/sensitivity-receipts/test_a-live-1.json"

        def receipt(carry: bool) -> dict:
            body = {"instance_id": "test_a", "case_version": "cv_1", "test_content_hash": now["input_hash"],
                    "source_revision": "src", "build_id": "b", "mutation": "invert",
                    "expected_assertion_failure": "x", "actual_failure": "x", "assertion_location": "t.py:1",
                    "restoration_evidence": "r", "failure_kind": "assertion", "proof_level": "live",
                    "probe_tool": "probe_by_code.py", "mutation_kind": "assertion", "immutable": True,
                    "receipt_hash": "h-1", "test_code_sha": now["test_code_sha"],
                    "instance_identity": now["instance_identity"], "probe_record": "work/probes/test_a.json"}
            if carry:
                body["mutated_file"] = mutated
            path = write(fix.task / rel, body)
            return dict(entry, sensitivity_proof={"receipt_ref": {"path": rel, "sha256": digest(path)}})

        def record(**over):
            body = {"schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": "test_a",
                    "verdict": "intended_failure", "recorded_at": "2026-09-20T10:00:00+00:00",
                    "test_file_sha256": now["input_hash"], "instance_identity": now["instance_identity"],
                    "receipt": {"path": rel}, "mutated_file": mutated}
            body.update(over)
            write(PL.probe_record_path(fix.task, "test_a"), body)

        def asked(row_):
            return PL.already_probed(row_, {}, fix.task, now=now, project=fix.root)
        for carried in (True, False):
            label = "a receipt that carries mutated_file" if carried else "a receipt from before that key"
            row_ = receipt(carried)
            write(helper, "VALUE = 1\n")
            record()
            first = asked(row_)
            check_eq(f"{label}: nothing changed since its own probe - answered", (first["probed"], first.get("by")),
                     (True, "receipt"))
            write(helper, "VALUE = 2\n")
            record()
            check_eq(f"{label}: the oracle changed - not answered", asked(row_)["probed"], False)
            record(verdict="not_executed", recorded_at="2026-09-21T10:00:00+00:00", receipt=None)
            got = asked(row_)
            check_eq(f"{label}: a `not_executed` rerun over the CHANGED oracle overwrote the record - not refused as "
                     "by=receipt (probe A3)", (got["probed"], got.get("by")), (False, None))
            write(helper, "VALUE = 1\n")
            record(verdict="not_executed", recorded_at="2026-09-21T10:00:00+00:00", receipt=None)
            check_eq(f"{label}: the oracle back and the record is a not_executed one", asked(row_)["probed"], carried)
            record(receipt={"path": "work/sensitivity-receipts/another-receipt.json"})
            check_eq(f"{label}: an intended_failure record that names ANOTHER receipt is not this receipt's probe",
                     asked(row_)["probed"], carried)
    finally:
        fix.close()


def a_job_of_another_file_is_never_this_rows_identity():
    """t-075 probe B (the dangerous direction): a bare alias is shared by rows of several files, a parametrized form
    is covered from any file. The identity is measured only from a job whose node lies in the row's own file."""
    one, two = "def test_x():\n    assert 1 == 1\n", "def test_x():\n    assert 2 == 2\n"
    rows = [row("TC-1::test_x", "TC-1", "tests/test_one.py", selector="test_x"),
            row("TC-2::test_x", "TC-2", "tests/test_two.py", selector="test_x")]
    fix = Fixture({"tests/test_one.py": one, "tests/test_two.py": two}, rows, scope=("TC-1", "TC-2"))
    try:
        fix.job(["TC-1", "TC-2"])
        row2 = json.loads((fix.task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))["tests"][1]
        # a NEWER job that ran only test_one's node under the bare id `test_x`
        request, _n, _r, _v = ER.build_mine_request(fix.root, ["TC-1"], cfg=fix.cfg, task=TASK, dispatch_id=DISPATCH,
                                                   probe=lambda spec: fix.provenance,
                                                   node_ids=["tests/test_one.py::test_x"], again=True)
        store = ER.JobStore(fix.task / "state" / "execution-jobs")
        _a, job = store.begin(request)
        store.update(job, status="completed", execution_status="passed", freshness="fresh")
        PL._reset()
        before = PL.instance_identity(row2, fix.task, fix.root)
        check("row 2's identity is not taken from the job that ran test_one",
              before["instance_identity"] and before["instance_identity"]["job_id"] != job["job_id"])
        write(fix.root / "tests" / "test_two.py", "def test_x():\n    assert 2 == 3\n")
        PL._reset()
        after = PL.instance_identity(row2, fix.task, fix.root)
        bound = {k: before[k] for k in ("input_hash", "test_code_sha", "instance_identity")}
        check_eq("a real code edit of row 2: the proof bound before is stale, not 'instance'", PL.same_test(after, bound), "")
        # a parametrized form covered from another file
        para = json.loads(json.dumps(job))
        para.update(job_id="para", idempotency_key="para-key", created_at="2999-01-01T00:00:00+00:00",
                    updated_at="2999-01-01T00:00:00+00:00")
        para["request"]["selected_instance_ids"] = ["test_x[a]"]
        para["request"]["command"]["selector_args"] = {"test_x[a]": ["tests/test_one.py::test_x[a]"]}
        store.write(para)
        PL._reset()
        check("a parametrized id of ANOTHER file covers no row of this one",
              PL.instance_identity(row2, fix.task, fix.root)["instance_identity"]["job_id"] != "para")
        # a test moved to a new file while the old file stays: the job that ran the old file is not the moved test's
        moved = dict(row2, file="tests/test_moved.py")
        write(fix.root / "tests" / "test_moved.py", two)
        PL._reset()
        got = PL.instance_identity(moved, fix.task, fix.root)
        check_eq("a row moved to a new file has no run of its own yet: no identity, and the cause says so",
                 (got["instance_identity"], got["why"]), ({}, PL.WHY_NO_REQUEST))
    finally:
        fix.close()


def a_node_id_carries_the_profile_of_its_row():
    """EP1-16 (A-K2, A-K8, A-E4, A-E6, A-E7, A-E8, A-E10): `--node-id` replaces the manifest rows with the ids asked
    for, and the profile the row of that file named was lost with them - so a root two profiles share (`unit` and `ui`
    over `tests/`) refused a test whose row had already said which profile runs it. Now each id keeps the profile of
    the rows of its own file (and nothing else of the row); a file no row names, a row that names none, and rows of
    one file that disagree keep today's answer - the refusal, with the door `run_suite --mine` has (`--profile ID`)."""
    files = {f"tests/test_{n}.py": f"def test_{n}():\n    assert 1 == 1\n" for n in ("one", "free", "a", "b", "bare", "ghost", "mixed")}
    rows = [row("test_one", "TC-1", "tests/test_one.py", profile_id="ui"),
            row("test_one_b", "TC-1", "tests/test_one.py", profile_id="ui"),
            row("test_bare", "TC-2", "tests/test_bare.py"),
            row("test_a", "TC-3", "tests/test_a.py", profile_id="ui"),
            row("test_b", "TC-3", "tests/test_b.py", profile_id="unit"),
            row("test_ghost", "TC-4", "tests/test_ghost.py", profile_id="ghost"),
            row("test_mixed", "TC-5", "tests/test_mixed.py", profile_id="ui"),
            row("test_mixed_b", "TC-5", "tests/test_mixed.py")]
    fix = Fixture(files, rows, scope=("TC-1", "TC-2", "TC-3", "TC-4", "TC-5"))
    try:
        ui_stand = write(fix.root.parent / (fix.root.name + "-bin-ui") / "pytest", "import sys\nsys.exit(0)\n")
        unit = fix.cfg["profiles"][0]
        ui = json.loads(json.dumps(unit))
        ui["profile_id"] = "ui"
        ui["commands"]["one_test"]["argv"][1] = str(ui_stand)
        cfg = dict(fix.cfg, profiles=[unit, ui])
        cfg["execution"] = {"runtime_probes": {"unit": fix.cfg["execution"]["runtime_probes"]["unit"],
                                               "ui": fix.cfg["execution"]["runtime_probes"]["unit"]}}

        def build(case, nodes, **kwargs):
            try:
                request, notes, _r, _v = ER.build_mine_request(
                    fix.root, [case], cfg=cfg, task=TASK, dispatch_id=DISPATCH, probe=lambda spec: fix.provenance,
                    node_ids=nodes, again=True, **kwargs)
                return request, "", notes
            except ER.MineRefusal as exc:
                return None, str(exc), []

        request, why, _notes = build("TC-1", ["tests/test_one.py::test_one"])
        check_eq("A-K8: a shared root, the row of the file names `ui`: the request is built under it",
                 (why, (request or {}).get("profile_id")), ("", "ui"))
        check_in("...and runs the command of `ui`, not the first profile's", str(ui_stand),
                 " ".join((request or {}).get("command", {}).get("argv") or []))
        # A-E10: the explicit id narrows, the row's other instance is not pulled in
        check_eq("A-E10: --node-id narrows the selection; the row's other test of the file is not added",
                 (request or {}).get("selected_instance_ids"), ["test_one"])
        request, why, _notes = build("TC-2", ["tests/test_bare.py::test_bare"])
        check_eq("A-K8: the row names no profile: today's refusal", (request, "share the test root" in why), (None, True))
        check_in("...with the door run_suite --mine has", "--profile ID", why)
        check_in("...and the manifest row's", "`profile_id`", why)
        # A-E8: a test no row names is not placed by a neighbour
        request, why, _notes = build("TC-1", ["tests/test_free.py::test_free"])
        check_eq("A-E8: a node id whose file no row of the case names: no profile is taken from the other rows",
                 (request, "share the test root" in why), (None, True))
        # the rows of one file disagree (one names `ui`, one names none): not decided for it
        request, why, _notes = build("TC-5", ["tests/test_mixed.py::test_mixed"])
        check_eq("rows of one file that do not agree carry no profile (refused as today, not run under `ui`)",
                 (request, "share the test root" in why), (None, True))
        # A-E7: two ids of one case from files of different profiles
        request, why, _notes = build("TC-3", ["tests/test_a.py::test_a", "tests/test_b.py::test_b"])
        check_eq("A-E7: ids of files whose rows name different profiles: one --mine per profile",
                 (request, "run under different profiles (ui, unit)" in why), (None, True))
        # A-E4: the row names a profile the config does not hold
        request, why, _notes = build("TC-4", ["tests/test_ghost.py::test_ghost"])
        check_eq("A-E4: a row naming a profile the config does not hold is refused naming it and the ids it holds",
                 (request, "`ghost`" in why, "(profile_id there: unit, ui)" in why), (None, True, True))
        # A-E6: an explicit profile wins over the row's, with a note
        request, why, notes = build("TC-1", ["tests/test_one.py::test_one"], profile_id="unit")
        check_eq("A-E6: --profile `unit` against a row naming `ui`: `unit` runs", (why, (request or {}).get("profile_id")),
                 ("", "unit"))
        check_in("...and the note says the row's name did not decide", "the manifest names `ui`", " ".join(notes))
        # the same call from a caller with no --profile door (the probe) is refused in the row's words only
        request, why, _notes = build("TC-2", ["tests/test_bare.py::test_bare"], profile_door=False)
        check_in("A-K3: profile_door=False: the refusal names the row door", "`profile_id`", why)
        check_not_in("...and NOT --profile", "--profile", why)
    finally:
        fix.close()


def a_review_copies_why_its_identity_is_missing():
    """t-075 probe C: the non-UTF-8 conftest at REVIEW time leaves the review with no identity and a measurement
    cause; a fixture changed later must not be matched to it by raw equality of the unchanged test file."""
    test = "def test_a(db):\n    names = db.names()\n    assert names == [\"alice\"]\n"
    fix = Fixture({"tests/conftest.py": CONFTEST, "tests/test_a.py": test},
                  [row("test_a", "TC-1", "tests/test_a.py")], scope=("TC-1",))
    try:
        fix.job(["TC-1"])
        entry = json.loads((fix.task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))["tests"][0]
        write(fix.root / "tests" / "conftest.py", CONFTEST.encode() + b"# \xff\n")
        PL._reset()
        at_review = PL.instance_identity(entry, fix.task, fix.root)
        check_eq("at review: no identity, a measurement cause", (at_review["instance_identity"],
                                                                 at_review["why"] in PL.MEASUREMENT), ({}, True))
        receipt = {"instances": [{"instance_id": "test_a", "input_hash": at_review["input_hash"],
                                  "test_code_sha": at_review["test_code_sha"], "instance_identity_why": at_review["why"]}]}
        write(fix.task / WR.REVIEW_RECEIPT_DIR / "S5-critic.json", receipt)
        copied = WR._reviewed_identity(fix.task, "S5-critic")["test_a"]
        check_eq("the review copies the cause from its receipt", copied.get("instance_identity_why"), at_review["why"])
        write(fix.root / "tests" / "conftest.py", CONFTEST.replace("alice", "mallory"))
        PL._reset()
        now = PL.instance_identity(entry, fix.task, fix.root)
        check("the fixture was changed after the review and now has an identity", bool(now["instance_identity"]))
        check_eq("a review whose measurement failed is not matched by the unchanged test file's raw sha (1b, symmetric)",
                 PL.same_test(now, PL.proof_identity(copied)), "")
    finally:
        fix.close()


# --- red_sandbox: what stands as the baseline -------------------------------------------------------------

def the_authors_green_stands_for_the_baseline_or_the_probe_runs_its_own():
    """C2(b), t-061 fixes 4 and 5, through `red_sandbox._author_baseline` (no sandbox, no launch): the
    author's green over these bytes covers; a stand that cannot be looked at, or a product file that moved
    since the green, gives today's own baseline - never `not_executed`, which would be a dead end."""
    files = {"tests/test_a.py": "from calc import add\n\n\ndef test_a():\n    assert add(1, 1) == 2\n",
             "calc.py": "def add(a, b):\n    return a + b\n"}
    fix = Fixture(files, [row("test_a", "TC-1", "tests/test_a.py")], scope=("TC-1",), git=True)
    try:
        job = fix.job(["TC-1"])
        target = {"instance_id": "test_a", "path": "calc.py", "before_sha256": digest(fix.root / "calc.py")}
        placed = {"test_a": {}}
        notes: list = []
        mode, held = RS._author_baseline(fix.root, fix.task, ["TC-1"], [target], placed, notes)
        check_eq("the author's green over the same bytes, the product file as it was at its source_sha: covered",
                 (mode, held and held["jobs"], held and [r["source"] for r in held["results"]]),
                 ("covered", [job["job_id"]], ["author"]))
        check_in("the note names the author's job and that no baseline ran", f"the author's green {job['job_id']} "
                 "on the same bytes (no baseline run)", " ".join(notes))
        # fix 5: the product file moved since the green -> its own baseline, with the note
        (fix.root / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        moved = dict(target, before_sha256=digest(fix.root / "calc.py"))
        notes = []
        mode, held = RS._author_baseline(fix.root, fix.task, ["TC-1"], [moved], placed, notes)
        check_eq("the product file changed since the author's green: the probe runs its own baseline",
                 (mode, held), ("own", None))
        check_in("...and says which file", "the product file changed since the author's green (calc.py)",
                 " ".join(notes))
        (fix.root / "calc.py").write_text(files["calc.py"], encoding="utf-8")
        # a source revision git cannot read: nothing to compare with, its own baseline
        job_path = next((fix.task / "state" / "execution-jobs").glob("*.json"))
        body = json.loads(job_path.read_text(encoding="utf-8"))
        body["request"]["fingerprint_components"]["source_sha"] = "not-a-revision"
        job_path.write_text(json.dumps(body), encoding="utf-8")
        PL._reset()
        notes = []
        mode, _held = RS._author_baseline(fix.root, fix.task, ["TC-1"], [target], placed, notes)
        check_eq("a source_sha git cannot read is not 'the product file is the same': its own baseline", mode, "own")
        body["request"]["fingerprint_components"]["source_sha"] = fix.revision
        job_path.write_text(json.dumps(body), encoding="utf-8")
        # fix 4: the stand cannot be looked at now -> own baseline with the stand's words, never not_executed
        fix.probe_script.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
        notes = []
        mode, held = RS._author_baseline(fix.root, fix.task, ["TC-1"], [target], placed, notes)
        check_eq("the stand cannot be observed: the probe runs its OWN baseline, never `not_executed` (t-061 fix 4)",
                 (mode, held), ("own", None))
        check_in("...saying it is the stand, not the test, and where it goes",
                 "the stand's version cannot be observed now", " ".join(notes))
        check_in("...`environment` in the digest", "`environment` in your digest", " ".join(notes))
        # no green at all: the author runs it first
        other = Fixture(files, [row("test_a", "TC-1", "tests/test_a.py")], scope=("TC-1",), git=True)
        try:
            notes = []
            mode, held = RS._author_baseline(other.root, other.task, ["TC-1"], [target], placed, notes)
            check_eq("no green on record: refused with the instance's words", (mode, list(held)), ("refuse", ["test_a"]))
            check_in("...naming the door: the author's run comes first", "no green run of test_a on these bytes is on "
                     "record: the author's run comes first", held["test_a"])
        finally:
            other.close()
    finally:
        fix.close()


# --- the S5 window, end to end ------------------------------------------------------------------------------

PAIR = '''\
import pytest


class Base:
    def setup_method(self, method):
        self.x = 1


def test_a(db):
    """Lists the names."""
    names = db.names()
    assert names == [
        "alice",
    ]


def test_b():
    assert 1 + 1 == 2


class TestOuter:
    class TestInner:
        def test_n(self):
            assert True
'''
LIVE_REF = "work/sensitivity-receipts/test_a-live-0123456789abcdef.json"
PAIR_REL = "tests/test_pair.py"


class Story:
    """The S5 story of test_window_record (a controller, two accepted dispatches, a plan, a gate) with its
    tests replaced by three tests of ONE file - test_a (new, probed), test_b and TestOuter::TestInner::test_n
    (unchanged, reviewed) - a conftest they use, the author's job, the live receipt of test_a as
    `probe_by_code.py` writes it (its identity measured by the producer) and the critic's review receipt."""

    def __init__(self, base_edit=None, legacy_review: bool = False):
        self.project = temp_project("qa-bind-window-")
        use_project(self.project)
        self.task, _controller = WT.a_story_at_s5(self.project)
        write(self.project / "tests" / "conftest.py", CONFTEST)
        text = PAIR if base_edit is None else base_edit(PAIR)
        write(self.project / PAIR_REL, text)
        for stale in (self.project / "tests").glob("test_tc-*.py"):
            stale.unlink()
        self.files = {PAIR_REL: (self.project / PAIR_REL).read_bytes(),
                      "tests/conftest.py": (self.project / "tests" / "conftest.py").read_bytes()}
        hashes = WT.obligation_hashes(self.task)
        raw = digest(self.project / PAIR_REL)
        rows = []
        for iid, case, row_id, disposition, selector in (
                ("test_a", "TC-1", "TS-1", "new_or_changed", "test_a"),
                ("test_b", "TC-2", "TS-2", "unchanged", "test_b"),
                ("test_n", "TC-2", "TS-2", "unchanged", "TestOuter::TestInner::test_n")):
            item = WT.test_row(iid, case, row_id, raw, disposition, hashes)
            item.update(file=PAIR_REL, selector=selector)
            item["trace_binding"]["selector"] = f"{PAIR_REL}::{selector}"
            rows.append(item)
        write(self.task / "work" / "automation-manifest.json", {
            "schema_version": 2, "tests": rows,
            "obligation_bindings": [
                {"obligation_id": "OB-TS-1", "obligation_hash": hashes["TS-1"]["OB-TS-1"], "instance_ids": ["test_a"],
                 "sensitivity": "proven", "probe_receipt_ref": LIVE_REF, "design_assessment": "sufficient",
                 "code_validity": "valid", "change_disposition": "new_or_changed", "change_basis_ref": "manifest:TC-1"},
                {"obligation_id": "OB-TS-2", "obligation_hash": hashes["TS-2"]["OB-TS-2"],
                 "instance_ids": ["test_b", "test_n"], "sensitivity": "not_required",
                 "design_assessment": "sufficient", "code_validity": "valid", "change_disposition": "unchanged",
                 "change_basis_ref": "manifest:TC-2"}]})
        for block in (self.task / "work" / "run-blocks").glob("*.json"):
            block.unlink()
        for number, iid in enumerate(("test_a", "test_b", "test_n")):
            WT.run_block(self.task, f"2026092409{number}000000000Z-b{number}.json", iid, f"fp-{iid}", f"fingerprint-{iid}")
        # config: a pytest stand-in and the stand's probe, so `build_mine_request` can build the author's request
        stand = write(self.project.parent / (self.project.name + "-bin") / "pytest", "import sys\nsys.exit(0)\n")
        cfg = json.loads((self.project / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        cfg["profiles"] = [{"profile_id": "unit", "selected": True, "roots": {"test": "tests"},
                            "commands": {"one_test": {"argv": [PY, str(stand), "--junitxml", "{report_path}"], "cwd": "."}},
                            "reporter": {"kind": "junit-xml"}, "selectors": {"verified": True}}]
        cfg["execution"] = {"runtime_probes": {"unit": {"argv": [PY, "-c", "print(1)"], "cwd": ".", "timeout_s": 20}}}
        write(self.project / "qa-factory" / "config.json", cfg)
        self.cfg = cfg
        request, _n, _r, _v = ER.build_mine_request(
            self.project, ["TC-1", "TC-2"], cfg=cfg, task=WT.TICKET, dispatch_id=WT.CRITIC,
            probe=lambda spec: dict(PROVENANCE, expected_source_revision="src-1",
                                    provenance=dict(PROVENANCE["provenance"], deployed_source_revision="src-1")))
        store = ER.JobStore(self.task / "state" / "execution-jobs")
        _action, job = store.begin(request)
        store.update(job, status="completed", execution_status="passed", freshness="fresh")
        PL._reset()
        # the live receipt, as probe_by_code writes it: the identity is the producer's, not typed
        self.receipt("test_a")
        self.window, self.notes = WR.build(self.task, WT.CRITIC)
        self.baseline_gaps = validate_window(self.window, self.task)
        stripped = json.loads(json.dumps(self.window))
        if legacy_review:  # a review receipt written before per-test binding: raw bytes only
            for item in stripped["instances"]:
                for key in ("test_code_sha", "instance_identity", "instance_identity_why"):
                    item.pop(key, None)
                for nested in ("review", "probe"):
                    for key in ("test_code_sha", "instance_identity"):
                        (item.get(nested) or {}).pop(key, None)
        self.receipt_ref = WR.write_review_receipt(self.task, stripped, WT.CRITIC)

    def entry(self, iid: str) -> dict:
        manifest = json.loads((self.task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        return next(t for t in manifest["tests"] if t["instance_id"] == iid)

    def receipt(self, iid: str) -> None:
        now = PL.instance_identity(self.entry(iid), self.task, self.project)
        body = WT.live_body(instance_id=iid, test_content_hash=now["input_hash"], test_code_sha=now["test_code_sha"],
                            instance_identity=now["instance_identity"])
        write(self.task / LIVE_REF, body)
        path = self.task / "work" / "automation-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for test in manifest["tests"]:
            if test["instance_id"] == iid:
                test["sensitivity_proof"] = {"receipt_ref": {"path": LIVE_REF, "sha256": digest(self.task / LIVE_REF)}}
        write(path, manifest)

    def edit(self, rel: str, fn) -> None:
        path = self.project / rel
        write(path, fn(self.files[rel]))
        PL._reset()

    def reset(self) -> None:
        """The reviewed bytes, again: every file back to what the review receipt was written over. This story
        is the project the readers (`hooklib.project_root`) look at from now on: several stories live at once."""
        use_project(self.project)
        for rel, data in self.files.items():
            write(self.project / rel, data)
        PL._reset()

    def judge(self) -> tuple:
        """(gaps of validate_window, the printed problem lines, the notes that are not problems)"""
        use_project(self.project)
        PL._reset()
        window, notes = WR.build(self.task, WT.CRITIC)
        info: list = []
        problems = WR.verdict(self.task, window, notes, info)
        return validate_window(window, self.task), problems, info

    def close(self) -> None:
        cleanup(self.project)
        for extra in self.project.parent.glob(self.project.name + "-*"):
            cleanup(extra) if extra.is_dir() else extra.unlink(missing_ok=True)


def text_edit(old: str, new: str, rel: str = PAIR_REL):
    return rel, lambda data: data.replace(old.encode("utf-8"), new.encode("utf-8"))


def gaps_of(gaps: list, iid: str, kinds=("stale_review", "mechanical_green", "sensitivity")) -> list:
    return [g for g in gaps if g.split(":", 1)[0] in kinds and g.split(":", 1)[1] == iid]


def a_story_is_acceptable_before_any_edit():
    story = Story()
    try:
        check_eq("control: the window built at the reviewed bytes has no gap", story.baseline_gaps, [])
        check("validate_window returns a list of gap tokens (a sorted list[str])",
              isinstance(story.baseline_gaps, list) and all(isinstance(g, str) for g in story.baseline_gaps))
        before_receipt = next(i for i in story.window["instances"] if i["instance_id"] == "test_a")
        check_eq("edge 11: a review with NO receipt keeps the claimed raw bytes and no code or identity field",
                 before_receipt["review"], {"verdict": "approved", "input_hash": before_receipt["input_hash"]})
        window, _notes = WR.build(story.task, WT.CRITIC)
        first = next(i for i in window["instances"] if i["instance_id"] == "test_a")
        check_eq("the item carries the raw sha, the code sha and the per-test identity of ONE read",
                 (first["input_hash"], first["test_code_sha"], sorted(first["instance_identity"])),
                 (digest(story.project / PAIR_REL), PL.code_sha((story.project / PAIR_REL).read_bytes(), "test_pair.py"),
                  ["instance_code_sha", "instance_content_sha", "job_id"]))
        check_eq("the review's identity is COPIED from the review receipt, and equals the item's at that time",
                 (first["review"]["input_hash"], first["review"]["test_code_sha"], first["review"]["instance_identity"]),
                 (first["input_hash"], first["test_code_sha"], first["instance_identity"]))
        check_eq("the probe carries the receipt's identity", (first["probe"]["test_code_sha"],
                                                              first["probe"]["instance_identity"]),
                 (first["test_code_sha"], first["instance_identity"]))
        check("nothing about why an identity is missing on an item that has one", "instance_identity_why" not in first)
    finally:
        story.close()


def per_test_binding_through_the_window():
    """AC5: a review receipt at X, then edits, judged through `window_record` + `validate_window`. For test_a:
    a cosmetic edit keeps the review and the probe (with the note), another test's edit keeps them with no
    note, and every edit of its code - or of what its identity reads - gives today's gaps."""
    # ONE story for the edits of the default file (its review receipt, its live receipt and its job are made once
    # and never written again by a judgement); a story of its own only where the reviewed bytes themselves differ
    shared = Story()
    stories = [shared]

    def scenario(name, edit, *, held: bool, note: bool, iid: str = "test_a", story=None):
        story = story or shared
        story.reset()
        try:
            rel, fn = edit
            story.edit(rel, fn)
            check(f"{name}: the file really changed", (story.project / rel).read_bytes() != story.files[rel])
            gaps, problems, info = story.judge()
            mine = gaps_of(gaps, iid)
            if held:
                check_eq(f"{name}: no stale_review / mechanical_green / sensitivity gap", mine, [])
            else:
                check(f"{name}: today's gaps", f"stale_review:{iid}" in mine, str(gaps))
                if iid == "test_a":
                    check_in(f"{name}: and the probe is due again", f"sensitivity:{iid}", mine)
                check("...and no note claims the proof holds", not [n for n in info if n.startswith(iid)], str(info))
            comment = [n for n in info if n.startswith(iid + ":")]
            check_eq(f"{name}: the comment-only note", bool(comment), note)
            if note:
                check_in(f"{name}: it names what holds (the review and the probe)",
                         f"{iid}: the review holds; {PL.code_unchanged_words()}", comment)
            check_eq(f"{name}: the note is not a problem line", [p for p in problems if "comment-only" in p], [])
            return story, gaps, problems
        finally:
            story.reset()

    try:
        _per_test_scenarios(shared, stories, scenario)
    finally:
        for story in stories:
            story.close()


def _per_test_scenarios(shared, stories, scenario):
    check_eq("control: no gap at the reviewed bytes", shared.baseline_gaps, [])
    # gaps: the test's own code, whatever is done around it
    _, gaps, problems = scenario("a list element in an assert", text_edit('"alice",', "*db.names(),"),
                                 held=False, note=False)
    line = next((p for p in problems if p.startswith("sensitivity:test_a")), "")
    check_in("the sensitivity gap is printed with the artifact and the command that produces it",
             "probe_by_code.py --task <T> --dispatch <critic id>", line)
    check_not_in("...and no text says the window binds raw bytes until a later change", "until t-043 C", line)
    scenario("a marker-shaped docstring only (cosmetic: the control of the next line)",
             text_edit('"""Lists the names."""', '"""Lists the names. @pytest.mark.qa(case="TC-1")"""'),
             held=True, note=True)
    scenario("a marker-shaped docstring plus a code edit",
             (PAIR_REL, lambda data: data.replace(b'"""Lists the names."""', b'"""Lists the names. @pytest.mark.qa(case="TC-1")"""')
              .replace(b"names = db.names()", b"names = db.names()[:1]")), held=False, note=False)
    scenario("@pytest.mark.skip added", text_edit("def test_a(db):", "@pytest.mark.skip\ndef test_a(db):"),
             held=False, note=False)
    scenario("a module-wide pytestmark = skip", text_edit("import pytest\n", "import pytest\n\npytestmark = pytest.mark.skip\n"),
             held=False, note=False)
    scenario("a module import added (the skeleton)", text_edit("import pytest\n", "import os\nimport pytest\n"),
             held=False, note=False)
    scenario("a conftest fixture the test uses changed, and a comment in the test",
             ("tests/conftest.py", lambda data: data.replace(b"return Db()", b"return Db()  # was\n    return None")),
             held=False, note=False)
    # the conftest edit above is code (a second return); the comment-in-the-test half is next: BOTH at once
    shared.reset()
    shared.edit("tests/conftest.py", lambda data: data.replace(b'return ["alice"]', b'return ["bob"]'))
    write(shared.project / PAIR_REL, (shared.project / PAIR_REL).read_bytes().replace(
        b"names = db.names()", b"# what the fixture gives\n    names = db.names()"))
    gaps, _problems, info = shared.judge()
    check("MC10: a fixture inside the identity changed AND a comment in the test: a gap - the file's code sha, "
          "equal here, is not consulted when both sides carry an identity", "stale_review:test_a" in gaps
          and "sensitivity:test_a" in gaps, str(gaps))
    check_eq("...and no note says it holds", [n for n in info if n.startswith("test_a:")], [])
    shared.reset()
    scenario("the code of a conftest the test uses (a fixture's return)",
             ("tests/conftest.py", lambda data: data.replace(b'return ["alice"]', b'return ["bob"]')),
             held=False, note=False)
    scenario("the outer class of a nested chain gains @pytest.mark.skip",
             text_edit("class TestOuter:", "@pytest.mark.skip\nclass TestOuter:"), held=False, note=False, iid="test_n")
    scenario("the holder class gets a keyword (metaclass=)", text_edit("    class TestInner:", "    class TestInner(metaclass=type):"),
             held=False, note=False, iid="test_n")
    with_base = Story(lambda text: text.replace("    class TestInner:", "    class TestInner(Base):"))
    stories.append(with_base)
    scenario("a base class body edited (same file, a Base the holder inherits)",
             text_edit("self.x = 1", "self.x = 2"), held=False, note=False, iid="test_n", story=with_base)
    scenario("(control) another test of the file edited, the holder inherits a Base: the holder's review holds",
             text_edit("assert 1 + 1 == 2", "assert 2 + 2 == 4"), held=True, note=False, iid="test_n", story=with_base)
    # held: cosmetic edits, and another test's
    scenario("a comment in the test", text_edit("    names = db.names()", "    # the fixture gives the names\n    names = db.names()"),
             held=True, note=True)
    scenario("a docstring edit", text_edit('"""Lists the names."""', '"""Lists every name the db holds."""'),
             held=True, note=True)
    scenario("a factory marker added", text_edit("def test_a(db):", '@pytest.mark.qa(case="TC-1")\ndef test_a(db):'),
             held=True, note=True)
    scenario("a multi-line factory marker added",
             text_edit("def test_a(db):", '@pytest.mark.qa(\n    case="TC-1",\n)\ndef test_a(db):'), held=True, note=True)
    scenario("ANOTHER test of the file edited", text_edit("assert 1 + 1 == 2", "assert 2 + 2 == 4"),
             held=True, note=False)
    # CRLF: the raw file sha differs and the code is equal (edge 8), and the per-test identity - read by
    # `function_sha` as TEXT, with universal newlines - is the very same: the proof holds by the SAME TEST, so
    # there is no comment-only note to make (the note is for a proof kept by code alone, and here the identity's
    # own content sha is equal). A carrier without an identity keeps it by `file_code`, with the note:
    # test_proof_level.comment_only_changes_keep_the_receipt.
    scenario("CRLF line endings", (PAIR_REL, lambda data: data.replace(b"\n", b"\r\n")), held=True, note=False)
    # undecodable: the code sha is ''; two different byte strings that decode alike are never 'the same'
    shared.reset()
    shared.edit(PAIR_REL, lambda data: data + b"# \xff\xfe one\n")
    undecodable_one = (shared.project / PAIR_REL).read_bytes()
    gaps, _p, _i = shared.judge()
    check("an undecodable variant of the reviewed file: a gap (no code sha, and raw differs)",
          "stale_review:test_a" in gaps and "sensitivity:test_a" in gaps, str(gaps))
    write(shared.project / PAIR_REL, undecodable_one.replace(b"\xff\xfe one", b"\xfe\xff two"))
    gaps, _p, _i = shared.judge()
    check("a second, different undecodable variant: still a gap, never 'the same' by replacement characters",
          "stale_review:test_a" in gaps and "sensitivity:test_a" in gaps, str(gaps))
    # rule 1b: the bound side has an identity, the current side has none because the MEASUREMENT failed
    shared.reset()
    shared.edit("tests/conftest.py", lambda data: data + b"# \xff\n")
    gaps, _problems, info = shared.judge()
    check("rule 1b: a conftest gains a non-UTF-8 byte, the test file is unchanged (raw equal): a gap, not 'raw'",
          "stale_review:test_a" in gaps and "sensitivity:test_a" in gaps, str(gaps))
    window, _notes = WR.build(shared.task, WT.CRITIC)
    item = next(i for i in window["instances"] if i["instance_id"] == "test_a")
    check_eq("...the item says why it has no identity (the closed cause), and keeps the raw sha it read",
             (item.get("instance_identity_why"), "instance_identity" in item, item["input_hash"]),
             (PL.WHY_NO_CODE, False, digest(shared.project / PAIR_REL)))
    shared.reset()
    # a legacy review receipt (no identity, no code sha): raw only - unchanged holds, a comment does not
    legacy = Story(legacy_review=True)
    stories.append(legacy)
    gaps, _p, info = legacy.judge()
    check_eq("a legacy review receipt, the file unchanged: no gap", gaps_of(gaps, "test_a"), [])
    legacy.edit(PAIR_REL, lambda data: data.replace(b"    names = db.names()", b"    # x\n    names = db.names()"))
    gaps, _p, info = legacy.judge()
    check("a legacy review, a comment added: stale_review (a review is never kept by a code sha it never "
          "recorded)", "stale_review:test_a" in gaps, str(gaps))
    check_eq("...the probe, which has its identity, holds", "sensitivity:test_a" in gaps, False)
    legacy.reset()


def a_review_receipt_from_before_is_not_a_collision():
    story = Story(legacy_review=True)
    try:
        path = story.task / story.receipt_ref["path"]
        before = path.read_bytes()
        check_eq("the receipt on disk predates the fields (control)", "instance_identity" in before.decode("utf-8"), False)
        window, _notes = WR.build(story.task, WT.CRITIC)
        again = WR.write_review_receipt(story.task, window, WT.CRITIC)
        check_eq("re-receipted after per-test binding: no collision, the same file", again["path"], story.receipt_ref["path"])
        check_eq("...untouched, byte for byte (an immutable receipt is never rewritten)", path.read_bytes(), before)
        check_eq("...and the note says what it binds", again.get("note"),
                 "the review receipt predates per-test binding: it binds raw bytes")
        window["instances"][0]["obligation_hash"] = "changed-window"
        try:
            WR.write_review_receipt(story.task, window, WT.CRITIC)
            raised = ""
        except ValueError as exc:
            raised = str(exc)
        check_in("a REAL change of the window is still a collision", "immutable review receipt collision", raised)
        check_eq("...and the file is still untouched", path.read_bytes(), before)
    finally:
        story.close()


def a_receipt_of_this_window_written_with_the_fields_is_the_same_receipt():
    story = Story()
    try:
        window, _notes = WR.build(story.task, WT.CRITIC)
        again = WR.write_review_receipt(story.task, window, WT.CRITIC)
        check_eq("the same window again: the same receipt, no note", (again["path"], again.get("note")),
                 (story.receipt_ref["path"], None))
    finally:
        story.close()


def the_note_is_printed_by_run():
    """`run()` prints the notes that are not problems as `note:` lines, whether or not the window is acceptable."""
    story = Story()
    try:
        story.edit(PAIR_REL, lambda data: data.replace(b"    names = db.names()", b"    # x\n    names = db.names()"))
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = WR.run(WT.TICKET, WT.CRITIC)
        check_eq("a window that holds over a comment is acceptable", code, 0)
        check_in("and prints the note (the vocabulary's own words)",
                 f"note: test_a: the review holds; {PL.code_unchanged_words()}", out.getvalue())
        check_in("...for the probe too", f"note: test_a: the probe holds; {PL.code_unchanged_words()}", out.getvalue())
        story.edit(PAIR_REL, lambda data: data.replace(b"    names = db.names()", b"    # x\n    names = db.names()")
                   .replace(b"assert 1 + 1 == 2", b"assert 1 + 1 == 3"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = WR.run(WT.TICKET, WT.CRITIC)
        check_eq("a window that does NOT hold prints its problems", code, 1)
        check_in("...and still the notes of the proofs that do hold", "note: test_a:", out.getvalue())
    finally:
        story.close()


def the_refusal_of_a_case_id_uses_the_projects_form():
    root = temp_project("qa-bind-caseform-")
    try:
        write(root / "qa-factory" / "config.json", {"case_id_form": "{ticket}_TC_{nnn}"})
        try:
            ER.build_mine_request(root, [], cfg={"case_id_form": "{ticket}_TC_{nnn}"}, task="TP1-13797")
            said = ""
        except ER.MineRefusal as exc:
            said = str(exc)
        check_in("the refusal spells the case id in the project's own form", "TP1-13797_TC_001", said)
        check_not_in("...and not in a form nothing accepts here", "TC-001", said)
        try:
            ER.build_mine_request(root, [], cfg={}, task="")
            said = ""
        except ER.MineRefusal as exc:
            said = str(exc)
        check_in("the default form stays TC-001", "--mine TC-001[,TC-002]", said)
    finally:
        cleanup(root)


def main():
    instance_shas_reproduces_the_contracts()
    an_inherited_helper_that_is_also_a_test_file_is_stale_not_equal()
    the_identity_is_measured_from_the_authors_job()
    a_newer_request_with_more_helpers_changes_the_identity()
    a_helper_edited_under_a_cached_identity_is_seen()
    a_probe_record_of_one_id_never_answers_for_another()
    a_probe_answers_only_while_what_it_mutated_holds()
    a_later_record_does_not_speak_for_a_receipt()
    a_job_of_another_file_is_never_this_rows_identity()
    a_node_id_carries_the_profile_of_its_row()
    a_review_copies_why_its_identity_is_missing()
    the_authors_green_stands_for_the_baseline_or_the_probe_runs_its_own()
    the_refusal_of_a_case_id_uses_the_projects_form()
    a_story_is_acceptable_before_any_edit()
    per_test_binding_through_the_window()
    a_review_receipt_from_before_is_not_a_collision()
    a_receipt_of_this_window_written_with_the_fields_is_the_same_receipt()
    the_note_is_printed_by_run()
    finish("test_probe_binding")


if __name__ == "__main__":
    main()
