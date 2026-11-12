"""E01/E04/E08/E09/E35 seams across request scope, reuse, provenance and red proof."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from harness import PLUGIN_ROOT, check, check_eq, check_in, finish

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
from execution_request import (JobStore, MineRefusal, RequestError, attempt_identity,  # noqa: E402
                               ordinary_precedent, sandbox_run_directory, validate_request)
from execution_fingerprint import file_hash  # noqa: E402
from red_sandbox import verify  # noqa: E402
from run_suite import execution_status  # noqa: E402

# Outside the package: a local-directory marketplace copies whatever lies in it.
ROOT = Path(tempfile.mkdtemp(prefix="qa-execution-pipeline-"))


def request(key: str, purpose: str, selected: list[str], scope: list[str], fingerprint: str) -> dict:
    return {"task": "PIPE-1", "revision": "plan-1", "dispatch_id": "d-1",
            "profile_id": "native", "purpose": purpose, "selected_instance_ids": selected,
            "current_scope_instance_ids": scope, "input_fingerprint": fingerprint,
            "fingerprint_files": [{"path": str(ROOT / "runner.py"), "sha256": file_hash(ROOT / "runner.py"),
                                   "kind": "test_files"}],
            "fingerprint_components": {"source_sha": "a" * 40,
                                       "test_content_sha": fingerprint.ljust(64, "0")[:64],
                                       "config_sha": "c" * 64},
            "runtime_provenance": {"profile_id": "native", "timestamp": "2026-09-17T12:00:00Z",
                "environment_id": "device-1", "expected_source_revision": "src-1",
                "observed_runtime_identity": "app-build-1", "evidence_refs": ["device/build-id"],
                "provenance": {"technical_verification": True, "source_linkage": "exact",
                "deployed_source_revision": "src-1"}, "result": "matched"},
            "runtime_required": True,
            "runtime_probe": {"argv": [sys.executable, "runner.py"], "cwd": ".", "timeout_s": 5},
            "reason": purpose, "remaining_budget": 100, "idempotency_key": key,
            "freshness": "fresh", "command": {"argv": [sys.executable, "runner.py"],
            "cwd": ".", "scope": "selected", "reporter": "pytest",
            "selector_contract_verified": True,
            "selector_args": {item: [item] for item in selected}},
            "instance_contracts": {item: {"report_test_id": item, "parameters": {}}
                                   for item in selected}}


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ROOT.mkdir()
    (ROOT / "runner.py").write_text("# fixture\n", encoding="utf-8")
    try:
        scope = [f"i-{n}" for n in range(10)]
        store = JobStore(ROOT / "jobs")
        initial = validate_request(request("initial", "initial", scope, scope, "initial"), ROOT)
        action, job = store.begin(initial)
        check_eq("E01 initial ten creates one job", action, "launch")
        store.update(job, status="completed", execution_status="failed", freshness="fresh")

        repair_ids = ["i-2", "i-7"]
        repair = validate_request(request("repair", "repair_verify", repair_ids, scope, "repair"), ROOT)
        action, repaired = store.begin(repair)
        check_eq("E04 repair selects only two failed instances", len(repair["selected_instance_ids"]), 2)
        check_eq("E04 repair is one new targeted job", action, "launch")
        store.update(repaired, status="completed", execution_status="passed", freshness="fresh")

        red = validate_request(request("red", "red_probe", scope, scope, "red"), ROOT)
        action, red_job = store.begin(red)
        check_eq("E08 critic adds red only, no critic green", action, "launch")
        store.update(red_job, status="completed", execution_status="passed", freshness="fresh")
        action, same = store.begin(red)
        check_eq("E09 S6 reuses fresh red receipt", action, "reused")
        check_eq("E09 reuse points to same job", same["job_id"], red_job["job_id"])

        helper_subset = request("helper", "repair_verify", ["i-1", "i-4"], scope, "helper")
        check_eq("helper change expands only within current approved subset",
                 validate_request(helper_subset, ROOT)["selected_instance_ids"], ["i-1", "i-4"])

        for result in ("unknown", "mismatched"):
            invalid = request("native-" + result, "initial", ["i-1"], scope, result)
            invalid["runtime_provenance"]["result"] = result
            if result == "mismatched":
                invalid["runtime_provenance"]["provenance"]["deployed_source_revision"] = "old"
            try:
                validate_request(invalid, ROOT)
                denied = False
            except RequestError:
                denied = True
            check(f"native runtime provenance {result} cannot run or reuse", denied)

        author = ROOT / "author.py"
        author.write_text("assert value == 1\n", encoding="utf-8")
        before = hashlib.sha256(author.read_bytes()).hexdigest()
        receipt = {"repo": str(ROOT), "original_hashes": {"author.py": before},
                   "targets": [{"instance_id": "i-1", "expected_location": "author.py:1",
                                "expected_reason": "expected 1"}]}
        wrong_import = [{"instance_id": "i-1", "status": "failed", "failure_kind": "import",
                         "location": "author.py:1", "reason": "expected 1",
                         "semantic_verdict": "intended_failure"}]
        check_eq("wrong import failure is not red proof", verify(receipt, wrong_import)["status"], "incomplete")
        timeout = [{"instance_id": "i-1", "status": "timeout", "failure_kind": "timeout",
                    "location": "", "reason": "", "semantic_verdict": "incomplete"}]
        # Lead decision (t-070 Q3): a mutated run that ends in `timeout` is never `survived` and never a kill:
        # it is the probe's defect, with words that say what to do
        timed = verify(receipt, timeout)
        check_eq("timeout is not red proof: probe_defect", timed["status"], "probe_defect")
        check_eq("...with the words that name the way on", timed["probe_defects"][0]["reason"],
                 "the mutated run timed out (the time budget of the run): rerun the probe with a longer budget, "
                 "or judge the test by hand")
        check_eq("runner classifies timeout separately", execution_status({"exit_code": 124}), "timeout")
        check_eq("main author bytes remain unchanged", hashlib.sha256(author.read_bytes()).hexdigest(), before)
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
    artifact_volatility()
    red_probe_directory()
    one_path_one_mutation()
    finish("test_execution_pipeline")


def junction_or_symlink(link: Path, target: Path) -> bool:
    """A directory link at `link` pointing to `target`; False where this OS user cannot make one
    (a symlink needs a privilege on Windows; a junction does not)."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                              capture_output=True, text=True, timeout=30)
        return done.returncode == 0 and link.exists()
    return False


def red_probe_directory() -> None:
    """M19: where a red probe runs is decided by the profile and the clone, never by the last
    probe. Before this, the precedent of a probe was the latest earlier PROBE, so a probe
    without a directory inherited the absolute path of a clone that no longer existed; a probe
    run in a clone lost the profile's subdirectory; and two clones could share one attempt
    identity."""
    base = Path(tempfile.mkdtemp(prefix="qa-red-probe-directory-")).resolve()
    try:
        project = base / "project"
        (project / "backend").mkdir(parents=True)
        clone = base / "clone"
        (clone / "backend").mkdir(parents=True)
        profile = {"profile_id": "backend-xunit",
                   "commands": {"one_test": {"argv": ["dotnet"], "cwd": "backend"}}}

        check_eq("a profile-relative run directory is kept inside the clone",
                 sandbox_run_directory(project, clone, profile, None), (clone / "backend").resolve())
        absolute = {"commands": {"one_test": {"argv": ["dotnet"], "cwd": str(project / "backend")}}}
        check_eq("an absolute configured directory is mapped under the clone",
                 sandbox_run_directory(project, clone, absolute, None), (clone / "backend").resolve())
        check_eq("no profile directory and no precedent: the clone itself",
                 sandbox_run_directory(project, clone, {}, None), clone.resolve())

        # the precedent: the latest ORDINARY behavioural job of the profile, never a probe
        ordinary = {"request": {"purpose": "repair_verify", "profile_id": "backend-xunit",
                                "command": {"cwd": str(project / "backend")}}}
        stale = {"request": {"purpose": "red_probe", "profile_id": "backend-xunit",
                             "command": {"cwd": "C:/discarded-red-probe"}}}
        check_eq("a new red probe cannot inherit a discarded probe request",
                 ordinary_precedent([ordinary, stale], "backend-xunit"), ordinary["request"])
        check_eq("with only probes on record there is no precedent",
                 ordinary_precedent([stale], "backend-xunit"), None)
        other = {"request": {"purpose": "initial", "profile_id": "other", "command": {"cwd": "x"}}}
        check_eq("an ordinary job of another profile is not this profile's precedent",
                 ordinary_precedent([other], "backend-xunit"), None)
        check_eq("a build job is not behavioural, so it is no precedent",
                 ordinary_precedent([{"request": {"purpose": "build", "profile_id": "backend-xunit"}}],
                                    "backend-xunit"), None)
        check_eq("an ordinary precedent's absolute directory inside the project is mapped under the clone",
                 sandbox_run_directory(project, clone, {}, ordinary["request"]),
                 (clone / "backend").resolve())
        check_eq("a stale precedent directory outside the project is ignored",
                 sandbox_run_directory(project, clone, {}, stale["request"]), clone.resolve())

        # refusals, each naming the offending path
        def refused(profile_doc, root=clone) -> str:
            try:
                sandbox_run_directory(project, root, profile_doc, None)
            except MineRefusal as exc:
                return str(exc)
            return ""

        outside = str(base / "elsewhere")
        why = refused({"commands": {"one_test": {"argv": ["x"], "cwd": outside}}})
        check_in("an absolute directory outside the project is refused, naming it", outside, why)
        check_in("and says where to correct it", "commands.one_test.cwd", why)
        why = refused({"commands": {"one_test": {"argv": ["x"], "cwd": "../../escape"}}})
        check_in("a `..` that escapes the project is refused, naming it", "../../escape", why)
        why = refused({"commands": {"one_test": {"argv": ["x"], "cwd": "backend/../backend"}}})
        check_eq("a `..` that stays inside the project is not an escape", why, "")
        why = refused({"commands": {"one_test": {"argv": ["x"], "cwd": "missing-dir"}}})
        check_in("a directory missing inside the sandbox is refused, naming it", "missing-dir", why)
        check_in("and names the sandbox", str(clone), why)
        why = refused({}, root=base / "no-such-clone")
        check_in("a sandbox root that is not a directory is refused, naming it", "no-such-clone", why)

        elsewhere = base / "author-tree"
        (elsewhere / "inner").mkdir(parents=True)
        if junction_or_symlink(clone / "link", elsewhere):
            why = refused({"commands": {"one_test": {"argv": ["x"], "cwd": "link/inner"}}})
            check_in("a directory link out of the sandbox is refused, naming the directory",
                     "link", why)
            check_in("and says it is not inside the sandbox", "not inside the sandbox", why)
        else:
            print("SKIPPED: a directory link out of the sandbox is refused "
                  "(this OS user can create neither a symlink nor a junction)")

        # identity of the attempt
        material = {"i": ["selector"]}
        # The identity is a key of records already on a project's disk: a new package version must compute the same key
        # for the same attempt, or it stops finding its own earlier runs. This literal is that contract, not a measurement.
        check_eq("an ordinary run's identity is the key older versions wrote",
                 attempt_identity(material, "same", "initial", "a"), "9649e7917b12")
        check_eq("an observed initial run is the same key",
                 attempt_identity(material, "same", "initial", "a", unobserved=False), "9649e7917b12")
        check_eq("an ordinary run's identity ignores an incidental directory",
                 attempt_identity(material, "same", "initial", "a"),
                 attempt_identity(material, "same", "initial", "b"))
        check_eq("so does a repair run's", attempt_identity(material, "same", "repair_verify", "a"),
                 attempt_identity(material, "same", "repair_verify", "b"))
        check("separate clones give a red probe distinct identities",
              attempt_identity(material, "same", "red_probe", "clone-a")
              != attempt_identity(material, "same", "red_probe", "clone-b"))
        check_eq("the same clone keeps the same identity",
                 attempt_identity(material, "same", "red_probe", "clone-a"),
                 attempt_identity(material, "same", "red_probe", "clone-a"))
        # E-7: the observation state of the stand (upstream's F3) and the clone (ours) are both part
        # of what ran.
        check("an unobserved run never lands on the observed run's key",
              attempt_identity(material, "same", "initial", "a", unobserved=True)
              != attempt_identity(material, "same", "initial", "a", unobserved=False))
        check_eq("an unobserved run's own key is stable",
                 attempt_identity(material, "same", "initial", "a", unobserved=True),
                 attempt_identity(material, "same", "initial", "b", unobserved=True))
        check("a red probe in clone A is not the same attempt as in clone B (observed or not)",
              attempt_identity(material, "same", "red_probe", "clone-a", unobserved=True)
              != attempt_identity(material, "same", "red_probe", "clone-b", unobserved=True)
              and attempt_identity(material, "same", "red_probe", "clone-a")
              != attempt_identity(material, "same", "red_probe", "clone-b"))
        check("an unobserved red probe is not the observed red probe in the same clone",
              attempt_identity(material, "same", "red_probe", "clone-a", unobserved=True)
              != attempt_identity(material, "same", "red_probe", "clone-a", unobserved=False))
    finally:
        shutil.rmtree(base, ignore_errors=True)


def artifact_volatility() -> None:
    """M20: live story artifacts are mutable factory state, so the probe names them in its
    receipt but neither copies them into the sandbox nor compares them. The location is the project's own (`artifact_root` in
    qa-factory/config.json), so the volatile prefix is computed from it, not hard-coded."""
    import red_sandbox as RS
    # The default prefixes: every existing caller passes nothing and keeps working.
    check("default: live story artifacts are volatile",
          RS.is_generated("qa-factory/artifacts/QA-1/state/events.lock"))
    check("default: the state directory stays volatile", RS.is_generated("qa-factory/state/x.json"))
    # L7: upstream moved the tracked journal (and the ledger, decisions, approvals) from state/ to
    # records/; a journal append during a probe must not read as "main-tree bytes changed".
    check("default: the records directory (the tracked journal) is volatile too",
          RS.is_generated("qa-factory/records/journal.jsonl"))
    check("product and test sources stay inputs", not RS.is_generated("backend/Tests/FeedbackTests.cs"))
    check("the prefix matches from the repository root only",
          not RS.is_generated("src/qa-factory/artifacts/x.py"))
    check("a Windows spelling of a volatile path is volatile too",
          RS.is_generated("qa-factory\\artifacts\\QA-1\\x.json"))

    base = Path(tempfile.mkdtemp(prefix="qa-artifact-volatility-"))
    try:
        def repo_with(name: str, config) -> Path:
            repo = base / name
            (repo / "qa-factory").mkdir(parents=True)
            if config is not None:
                text = config if isinstance(config, str) else json.dumps(config)
                (repo / "qa-factory" / "config.json").write_text(text, encoding="utf-8")
            return repo

        outside = base / "elsewhere" / "artifacts"
        cases = {
            "no config.json readable -> the default prefix": (None, ("qa-factory/artifacts/",)),
            "config without artifact_root -> the default prefix": ({"adapters": {}}, ("qa-factory/artifacts/",)),
            "a config that is not JSON -> the default prefix": ("{broken", ("qa-factory/artifacts/",)),
            "an unusable artifact_root value -> the default prefix": ({"artifact_root": ""}, ("qa-factory/artifacts/",)),
            "another relative directory inside the repo": ({"artifact_root": "qa/work-items"}, ("qa/work-items/",)),
            "a trailing slash does not change the prefix": ({"artifact_root": "qa/work-items/"}, ("qa/work-items/",)),
            "absolute and outside the repo -> no extra prefix": ({"artifact_root": str(outside)}, ()),
            "relative but escaping the repo -> no extra prefix": ({"artifact_root": "../escaped"}, ()),
            "the repo root itself is not a prefix": ({"artifact_root": "."}, ()),
        }
        for label, (config, expected) in cases.items():
            repo = repo_with("r" + str(abs(hash(label))), config)
            check_eq(label, RS.artifact_prefixes(repo), expected)
        repo = repo_with("absinside", None)
        (repo / "qa-factory" / "config.json").write_text(
            json.dumps({"artifact_root": str(repo / "deep" / "work")}), encoding="utf-8")
        check_eq("absolute but inside the repo -> its repo-relative prefix",
                 RS.artifact_prefixes(repo), ("deep/work/",))

        moved = ("qa/work-items/",)
        check("moved: that prefix is volatile", RS.is_generated("qa/work-items/QA-1/x.json", moved))
        check("moved: the old default location is no longer special",
              not RS.is_generated("qa-factory/artifacts/QA-1/x.json", moved))
        check("moved: the state directory stays volatile", RS.is_generated("qa-factory/state/x.json", moved))
        check("moved: the records directory stays volatile", RS.is_generated("qa-factory/records/x.json", moved))
        check("moved: the match is from the repository root only",
              not RS.is_generated("src/qa/work-items/x.py", moved))
        check("outside: nothing extra is volatile, nothing fails",
              not RS.is_generated("qa-factory/artifacts/QA-1/x.json", ())
              and RS.is_generated("qa-factory/state/x.json", ()))

        # The whole path through prepare(): a project that moved its artifacts.
        repo = repo_with("moved-repo", {"artifact_root": "qa/work-items"})
        (repo / "qa" / "work-items" / "T-1").mkdir(parents=True)
        live = repo / "qa" / "work-items" / "T-1" / "events.lock"
        live.write_text("lock 1\n", encoding="utf-8")
        old_home = repo / "qa-factory" / "artifacts" / "T-1"
        old_home.mkdir(parents=True)
        (old_home / "note.md").write_text("an ordinary file here\n", encoding="utf-8")
        (repo / "tests").mkdir()
        author = repo / "tests" / "test_x.py"
        author.write_text("def test_x():\n    assert 1\n", encoding="utf-8")
        import subprocess
        subprocess.run(["git", "init", "-q"], cwd=str(repo), capture_output=True, timeout=60)
        destination = Path(str(repo) + "-sandbox")
        receipt = RS.prepare(repo, destination, {"mutations": [
            {"path": "tests/test_x.py", "before_sha256": RS.digest(author),
             "replacement_utf8": "def test_x():\n    assert 2\n",
             "instance_id": "TC-1::test_x", "expected_location": "tests/test_x.py:2",
             "expected_reason": "assert 2"}]})
        check("prepare: the configured artifacts location is not in the integrity set",
              "qa/work-items/T-1/events.lock" in receipt["volatile"]
              and "qa/work-items/T-1/events.lock" not in receipt["original_hashes"])
        check("prepare: the old default location is an ordinary input once moved",
              "qa-factory/artifacts/T-1/note.md" in receipt["original_hashes"])
        live.write_text("lock 2\n", encoding="utf-8")
        verdict = RS.verify(receipt, [{"instance_id": "TC-1::test_x", "status": "failed",
                                       "failure_kind": "assertion", "location": "tests/test_x.py:2",
                                       "reason": "assert 2", "semantic_verdict": "intended_failure"}])
        check_eq("prepare: a live artifact rewritten under the probe does not fail it",
                 verdict["status"], "accepted")
        shutil.rmtree(destination, ignore_errors=True)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def one_path_one_mutation() -> None:
    """B-314: `prepare()` wrote each mutation in turn, so a second mutation of one path silently
    overwrote the first while both targets stayed in the receipt - a probe of two obligations
    that proved one. Differing replacements of one path are refused before anything is created;
    identical ones lose nothing and pass."""
    import red_sandbox as RS
    from harness import check_not_in, run_script
    base = Path(tempfile.mkdtemp(prefix="qa-b141-"))
    try:
        repo = base / "repo"
        (repo / "a").mkdir(parents=True)
        (repo / "a" / "b.py").write_text("X = 1\n", encoding="utf-8")
        (repo / "a" / "c.py").write_text("Y = 1\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=str(repo), capture_output=True, timeout=60)

        def mutation(path: str, real: str, text: str, instance: str) -> dict:
            return {"path": path, "before_sha256": RS.digest(repo / real), "replacement_utf8": text,
                    "instance_id": instance, "expected_location": "tests/t.py:3",
                    "expected_reason": "boom"}

        def attempt(name: str, mutations: list) -> tuple:
            destination = base / name
            try:
                RS.prepare(repo, destination, {"mutations": mutations})
            except ValueError as exc:
                return str(exc), destination
            return "", destination

        destination = base / "distinct"
        receipt = RS.prepare(repo, destination, {"mutations": [
            mutation("a/b.py", "a/b.py", "X = 2\n", "I-1"), mutation("a/c.py", "a/c.py", "Y = 2\n", "I-2")]})
        check_eq("B-314: distinct paths are both written",
                 ((destination / "a" / "b.py").read_text(encoding="utf-8"),
                  (destination / "a" / "c.py").read_text(encoding="utf-8")), ("X = 2\n", "Y = 2\n"))
        check_eq("and both stay in the receipt", len(receipt["targets"]), 2)

        message, destination = attempt("same", [mutation("a/b.py", "a/b.py", "X = 2\n", "I-1"),
                                                mutation("a/b.py", "a/b.py", "X = 3\n", "I-2")])
        check("B-314: two differing replacements of one path are refused", bool(message))
        check_in("naming the first mutation", "I-1", message)
        check_in("naming the second mutation", "I-2", message)
        check_in("and the path", "a/b.py", message)
        check_in("with the door: one probe per mutation", "one probe per mutation", message)
        check_in("or one combined replacement", "combined replacement", message)
        check_in("and saying that a person's word does not pass it", "No person's word", message)
        check("the destination was not created", not destination.exists())
        check("the author's bytes are untouched", (repo / "a" / "b.py").read_text(encoding="utf-8") == "X = 1\n")

        spellings = ["./a/b.py", str(repo / "a" / "b.py")]
        if os.name == "nt":  # a case-insensitive filesystem with two separators
            spellings += ["a\\b.py", "A/B.PY", ".\\A\\b.py"]
        for number, spelled in enumerate(spellings):
            message, destination = attempt(f"spelled-{number}", [
                mutation("a/b.py", "a/b.py", "X = 2\n", "I-1"),
                mutation(spelled, "a/b.py", "X = 3\n", "I-2")])
            check_in(f"the same path spelled {spelled!r} is the same path", "I-2", message)
            check_in(f"and the first mutation is named beside it ({spelled!r})", "I-1", message)
            check(f"nothing is created for {spelled!r}", not destination.exists())

        message, destination = attempt("three", [mutation("a/b.py", "a/b.py", "X = 2\n", "I-1"),
                                                 mutation("a/c.py", "a/c.py", "Y = 2\n", "I-2"),
                                                 mutation("a/b.py", "a/b.py", "X = 3\n", "I-3")])
        check("three mutations, two of them one path: refused", bool(message))
        check_in("naming the first of the pair", "I-1", message)
        check_in("and the third", "I-3", message)
        check_not_in("without blaming the one that is alone", "I-2", message)
        check("nothing is created", not destination.exists())

        destination = base / "identical"
        receipt = RS.prepare(repo, destination, {"mutations": [
            mutation("a/b.py", "a/b.py", "X = 2\n", "I-1"), mutation("a/b.py", "a/b.py", "X = 2\n", "I-2")]})
        check_eq("B-314: identical replacements of one path lose nothing and are allowed",
                 ((destination / "a" / "b.py").read_text(encoding="utf-8"), len(receipt["targets"])),
                 ("X = 2\n", 2))

        request_file = base / "request.json"
        request_file.write_text(json.dumps({"mutations": [
            mutation("a/b.py", "a/b.py", "X = 2\n", "I-1"),
            mutation("a/b.py", "a/b.py", "X = 3\n", "I-2")]}), encoding="utf-8")
        destination = base / "cli"
        cli = run_script("red_sandbox.py", "--repo", repo, "--destination", destination,
                         "--request", request_file)
        check_eq("the CLI refuses with exit 2, not a traceback", cli.returncode, 2)
        printed = json.loads(cli.stdout.strip().splitlines()[-1]) if cli.stdout.strip() else {}
        check_eq("and answers one JSON line with the refusal's own shape",
                 (printed.get("status"), "I-2" in printed.get("message", "")), ("refused", True))
        check("the CLI created nothing", not destination.exists())
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()
