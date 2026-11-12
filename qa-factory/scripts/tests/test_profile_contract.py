"""Profile contract: scoped capabilities, multi-repo identity, and runtime provenance."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, finish  # noqa: E402
from profile_contract import (implementation_repo_readiness, profile_readiness, validate_config,
                              validate_runtime_provenance)  # noqa: E402


def profile(profile_id: str, capability: str, dependency: str) -> dict:
    return {
        "profile_id": profile_id, "revision": "1", "roots": {"repo": ".", "test": "tests"},
        "adapter_id": "native", "adapter_version": "1", "capabilities": [capability],
        "dependency_ids": [dependency],
        "commands": {"run": {"kind": "run", "argv": [sys.executable, "{selector}"],
                              "cwd": ".", "scope": "selected"}},
        "selectors": {"test_id": "{selector}"}, "reporter": {"kind": "junit"},
        "quality_gates": {"collect": {"required": True, "command": "run",
                                       "quality_kind": "collect", "runs_tests": False}},
        "execution_prerequisites": {"runtime": "python 3.12", "package_manager": "uv 0.8.1",
                                    "dependency_state": "locked", "hook_executables": []},
        "conventions_refs": [], "environment_refs": [], "data_refs": [], "ownership_refs": [],
        "extensions": {"schema_version": "native/1"},
    }


def dependency(dep_id: str, capability: str, status: str) -> dict:
    return {"dependency_id": dep_id, "upstream_source": "project lockfile",
            "exact_version_or_revision": "1.2.3", "integrity": "", "location": ".tools",
            "capability": capability, "consumer": "runner", "owner": "project", "status": status,
            "executable": sys.executable, "probe_evidence": ["version:1.2.3"]}


def main() -> None:
    cfg = {
        "supported_capabilities": ["api", "native"],
        "adapter_capabilities": {"native": ["api", "native"]},
        "profiles": [profile("api", "api", "api-runner"),
                     profile("android", "native", "mobile-runner")],
        "managed_dependencies": [dependency("api-runner", "api", "ready"),
                                 dependency("mobile-runner", "native", "unavailable")],
        "implementation_repos": [
            {"repo_id": "service", "role": "application", "local_path": "../service",
             "remote_identity": "origin/service", "source_ref": "refs/merge-requests/42/head",
             "source_sha": "a" * 40, "execution_profile_id": "api", "write_target": False,
             "readiness_evidence": ["git:exact-ref"]},
            {"repo_id": "tests", "role": "tests", "local_path": ".",
             "remote_identity": "origin/tests", "source_ref": "refs/heads/qa-42",
             "source_sha": "b" * 40, "execution_profile_id": "api", "write_target": True,
             "working_branch": "qa-42", "base_sha": "b" * 40,
             "readiness_evidence": ["runtime:python", "command:api-runner"]},
        ],
    }
    check_eq("complete multi-repo profile config is valid", validate_config(cfg), [])
    check_eq("API-only selection is ready without a browser dependency",
             profile_readiness(cfg, ["api"])["api"]["status"], "ready")
    check("unselected unavailable native contour is absent",
          "android" not in profile_readiness(cfg, ["api"]))
    check_eq("selected native contour reports its own unavailable dependency",
             profile_readiness(cfg, ["android"])["android"]["status"], "unavailable")
    unverified_adapter = {**cfg, "adapter_capabilities": {}}
    check_eq("adapter name without a verified matrix stays unknown",
             profile_readiness(unverified_adapter, ["api"])["api"]["status"], "unknown")
    missing_tool = {**cfg, "managed_dependencies": [
        {**dependency("api-runner", "api", "ready"), "executable": "qa-no-such-tool"},
        dependency("mobile-runner", "native", "ready")]}
    check_eq("declared ready dependency is probed instead of trusted",
             profile_readiness(missing_tool, ["api"])["api"]["status"], "unavailable")

    native_only = {**cfg, "profiles": [profile("android", "native", "mobile-runner")],
                   "managed_dependencies": [dependency("mobile-runner", "native", "ready")]}
    native_only["implementation_repos"] = []
    check_eq("native profile has no browser requirement", validate_config(native_only), [])
    check("native profile does not invent screenshots",
          "screenshot" not in str(native_only["profiles"][0]).lower())

    bad_repo = {**cfg, "implementation_repos": [{"repo_id": "service", "role": "application",
                "local_path": "../service", "remote_identity": "origin/service",
                "source_sha": "a" * 40, "execution_profile_id": "api",
                "write_target": False, "readiness_evidence": []}]}
    errors = validate_config(bad_repo)
    check_in("source ref is required independently and before branch selection",
             "source_ref", errors)
    check("read-only source repo does not require a working branch",
          not any("working_branch" in error for error in errors))
    repo_records = implementation_repo_readiness(cfg, profile_readiness(cfg, ["api"]), Path.cwd())
    check_eq("missing repository path blocks only that repository", repo_records[0]["status"], "unavailable")
    check_eq("existing test repository retains scoped readiness", repo_records[1]["status"], "ready")

    unknown = validate_runtime_provenance({
        "profile_id": "api", "timestamp": "2026-09-17T12:00:00Z", "environment_id": "qa",
        "expected_source_revision": "abc", "observed_runtime_identity": "build-17",
        "evidence_refs": ["ci/job/17"], "provenance": {"technical_verification": False,
        "source_linkage": "unknown"}, "result": "unknown"})
    check_eq("unknown deployment is not promoted to matched", unknown["result"], "unknown")
    check_eq("unknown deployment record remains valid evidence", unknown["valid"], True)

    mismatch = validate_runtime_provenance({
        "profile_id": "api", "timestamp": "2026-09-17T12:00:00Z", "environment_id": "qa",
        "expected_source_revision": "mr-head-new", "mr_source_revision": "mr-head-new",
        "observed_runtime_identity": "build-old", "evidence_refs": ["deploy/manifest"],
        "provenance": {"technical_verification": True, "source_linkage": "exact",
                       "deployed_source_revision": "mr-head-old"}, "result": "matched"})
    check_eq("MR source versus deployed build mismatch overrides claimed match",
             mismatch["result"], "mismatched")

    squash = validate_runtime_provenance({
        "profile_id": "api", "timestamp": "2026-09-17T12:00:00Z", "environment_id": "qa",
        "expected_source_revision": "feature-head", "mr_source_revision": "feature-head",
        "observed_runtime_identity": "merge-build", "evidence_refs": ["ci/content-attestation"],
        "provenance": {"technical_verification": True, "source_linkage": "verified_content",
                       "deployed_source_revision": "squash-result",
                       "verified_source_revisions": ["feature-head"]}, "result": "matched"})
    check_eq("technical content binding permits a squash build SHA", squash["result"], "matched")
    check_eq("squash content provenance remains structurally valid", squash["valid"], True)
    unbound_squash = validate_runtime_provenance({
        "profile_id": "api", "timestamp": "2026-09-17T12:00:00Z", "environment_id": "qa",
        "expected_source_revision": "feature-head", "mr_source_revision": "feature-head",
        "observed_runtime_identity": "merge-build", "evidence_refs": ["ci/build"],
        "provenance": {"technical_verification": True, "source_linkage": "verified_content",
                       "deployed_source_revision": "squash-result"}, "result": "matched"})
    check_eq("different build SHA without explicit content binding stays mismatched",
             unbound_squash["result"], "mismatched")

    weak_match = validate_runtime_provenance({
        "profile_id": "api", "timestamp": "2026-09-17T12:00:00Z", "environment_id": "qa",
        "expected_source_revision": "abc", "observed_runtime_identity": "green-job",
        "evidence_refs": ["owner statement"], "provenance": {"technical_verification": False,
        "source_linkage": "owner_statement"}, "result": "matched"})
    check_eq("owner statement cannot establish a match", weak_match["result"], "unknown")
    check_eq("a falsely matched record is invalid", weak_match["valid"], False)

    legacy = {"tests_root": "tests", "test_command_templates": {}}
    check_eq("legacy config remains valid under the additive contract", validate_config(legacy), [])

    no_version = {**cfg, "managed_dependencies": [{**dependency("api-runner", "api", "ready"),
                                                     "exact_version_or_revision": ""}]}
    check_in("managed dependency requires exact version", "exact_version_or_revision",
             validate_config(no_version))
    t300_k27_person_confirmed_and_acceptable_provenance()
    fb8_content_word_problems()
    h_noraise()
    ep1_36_selectors_verified()
    finish("test_profile_contract")


def ep1_36_selectors_verified() -> None:
    """EP1-36 item 8 (F-8 a): `selectors_verified(profile, root)`. The hand wins in both directions; with no literal the command
    must be one the run forms select a test with AND the durable rehearsal record must name THIS command. Every other state is
    False (the gate refuses and names its door), and nothing raises."""
    import json
    import shutil
    import tempfile
    import onboarding_probe as OP
    from profile_contract import selectors_verified
    pw = ["npx", "playwright", "test", "--reporter=junit"]

    def prof(argv, verified=None, pid="pw") -> dict:
        selectors = {} if verified is None else {"verified": verified}
        return {"profile_id": pid, "selectors": selectors, "commands": {"one_test": {"argv": list(argv), "cwd": "."}}}

    def project(*rows) -> Path:
        root = Path(tempfile.mkdtemp(prefix="qa-selectors-verified-"))
        path = root / "qa-factory" / "state" / OP.G.REPORTER_REHEARSALS_FILE
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema_version": 1, "rehearsals": {f"k{n}": r for n, r in enumerate(rows)}}), encoding="utf-8")
        return root

    def rehearsed(argv, pid="pw") -> dict:
        return {"profile_id": pid, "argv_digest": OP.argv_digest(argv), "at": "2026-10-01T00:00:00"}
    root = project(rehearsed(pw))
    empty = Path(tempfile.mkdtemp(prefix="qa-selectors-verified-"))
    try:
        check_eq("SV: the rehearsed command of a form that selects is verified", selectors_verified(prof(pw), root), True)
        check_eq("SV (hand): a literal False wins over the record", selectors_verified(prof(pw, False), root), False)
        check_eq("SV (hand): a literal True needs no record", selectors_verified(prof(pw, True), empty), True)
        check_eq("SV (hand): ...nor a root", selectors_verified(prof(pw, True), None), True)
        check_eq("SV: another argv than the record's is `command_changed`, not verified",
                 selectors_verified(prof(["npx", "playwright", "test", "--reporter=line"]), root), False)
        check_eq("SV: another profile's rehearsal proves nothing", selectors_verified(prof(pw, pid="other"), root), False)
        check_eq("SV: no record at all", selectors_verified(prof(pw), empty), False)
        check_eq("SV: no root", selectors_verified(prof(pw), None), False)
        wrapper = ["node", "run-e2e.mjs"]
        check_eq("SV: a wrapper script has no `selection`: False even when its digest is on record",
                 selectors_verified(prof(wrapper), project(rehearsed(wrapper))), False)
        check_eq("SV: a form with no `selection` in the data (jest) is not verified by a record",
                 selectors_verified(prof(["npx", "jest"]), project(rehearsed(["npx", "jest"]))), False)
        check_eq("SV: a profile with no command", selectors_verified({"profile_id": "pw"}, root), False)
        (empty / "qa-factory" / "state").mkdir(parents=True)
        (empty / "qa-factory" / "state" / OP.G.REPORTER_REHEARSALS_FILE).write_text("{not json", encoding="utf-8")
        check_eq("SV: an unreadable record proves nothing", selectors_verified(prof(pw), empty), False)
        for label, bad in (("a profile that is no object", "pw"), ("None", None), ("a list", [pw])):
            check_eq(f"SV (never raises): {label}", selectors_verified(bad, root), False)
        check_eq("SV (never raises): a root that is no path", selectors_verified(prof(pw), object()), False)
        check_eq("SV (never raises): `selectors` that is no object", selectors_verified({"profile_id": "pw", "selectors": "yes"}, root), False)
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(empty, ignore_errors=True)


def h_noraise() -> None:
    """H-noraise (OH3-26): the validator is a gate now, and a gate that raises on a hostile shape says nothing. Every awkward
    input of the spec's list returns at least one line that names its path - never an exception, never an empty list."""
    import copy
    import json
    sample = json.loads((Path(__file__).resolve().parents[2] / "references" / "profile-shape.json").read_text(encoding="utf-8"))
    check_eq("H-noraise control: the shipped sample is valid, so every line below comes from the hostile value",
             validate_config({"profiles": [sample["profile"]], "implementation_repos": [sample["implementation_repo"]],
                              "managed_dependencies": [sample["managed_dependency"]]}), [])

    def cfg(change=None, *, repo=None, dep=None, top=None) -> dict:
        profile = copy.deepcopy(sample["profile"])
        if change:
            change(profile)
        out = {"profiles": [profile], "implementation_repos": [copy.deepcopy(sample["implementation_repo"])],
               "managed_dependencies": [copy.deepcopy(sample["managed_dependency"])]}
        if repo:
            repo(out["implementation_repos"][0])
        if dep:
            dep(out["managed_dependencies"][0])
        out.update(top or {})
        return out

    def execution(profile, **parts) -> None:
        concurrency = {"native_supported": True, "isolation": "shared"}
        profile["extensions"]["execution"] = {"schema_version": 1, "concurrency": concurrency, **parts}
        for command in profile["commands"].values():
            command.update({"repo_id": "r", "framework_adapter": "a", "reporter": {"format": "none"}, "selectors": {}})

    def one(profile, **fields) -> None:
        profile["commands"]["one_test"].update(fields)

    hostile = {
        "commands a list, execution schema 1": lambda p: (execution(p), p.update(commands=[{"kind": "test"}])),
        "commands a string": lambda p: p.update(commands="npx"),
        "commands a number": lambda p: p.update(commands=5),
        "a command that is not an object, execution schema 1": lambda p: (execution(p), p["commands"].update(extra="npx")),
        "kind a list": lambda p: one(p, kind=["test"]),
        "kind a list, execution schema 1": lambda p: (execution(p), one(p, kind=["test"])),
        "scope an object": lambda p: one(p, scope={"a": 1}),
        "reporter.format a list": lambda p: one(p, reporter={"format": []}),
        "quality_kind a list": lambda p: p.update(quality_gates={"g": {"command": "one_test", "quality_kind": [], "runs_tests": True}}),
        "isolation a list": lambda p: execution(p, concurrency={"native_supported": True, "isolation": []}),
        "level a list": lambda p: execution(p, level_rules=[{"repo_id": "r", "patterns": ["*"], "level": []}]),
        "profile_id a list": lambda p: p.update(profile_id=["a"]),
        "quality_gates a list": lambda p: p.update(quality_gates=["a"]),
        "quality_gates a string": lambda p: p.update(quality_gates="x"),
        "quality_gates a number": lambda p: p.update(quality_gates=5),
        "commands a number with a gate command": lambda p: p.update(
            commands=5, quality_gates={"g": {"command": "a", "quality_kind": "lint", "runs_tests": False}}),
        "resources a number": lambda p: execution(p, resources=5),
        "level_rules a number": lambda p: execution(p, level_rules=5),
        "argv a string": lambda p: one(p, argv="npx playwright test"),
        "gate command a list, commands an object": lambda p: p.update(
            quality_gates={"g": {"command": ["one_test"], "quality_kind": "lint", "runs_tests": False}}),
        "nested 50 deep": lambda p: one(p, argv=json.loads("[" * 50 + "]" * 50), kind=json.loads('{"a":' * 50 + "1" + "}" * 50)),
    }
    for label, change in hostile.items():
        try:
            lines = validate_config(cfg(change))
        except Exception as exc:  # noqa: BLE001 - the point of the key
            check(f"H-noraise: {label}: raised {type(exc).__name__}: {exc}", False)
            continue
        check(f"H-noraise: {label}: at least one line, and it names its path", bool(lines) and all(isinstance(x, str) and ":" in x for x in lines),
              str(lines))
    others = {
        "execution_profile_id a list": cfg(repo=lambda r: r.update(execution_profile_id=["web-tests"])),
        "status a list": cfg(dep=lambda d: d.update(status=[])),
        "implementation_repos a number": cfg(top={"implementation_repos": 5}),
        "managed_dependencies a number": cfg(top={"managed_dependencies": 5}),
    }
    for label, config in others.items():
        try:
            lines = validate_config(config)
        except Exception as exc:  # noqa: BLE001
            check(f"H-noraise: {label}: raised {type(exc).__name__}: {exc}", False)
            continue
        check(f"H-noraise: {label}: at least one line, and it names its path", bool(lines) and all(":" in x for x in lines), str(lines))
    check_eq("H-noraise: a config that is not an object is one line, not an exception", validate_config([]), ["config: must be an object"])


def fb8_content_word_problems() -> None:
    import profile_contract as P
    ident = "a" * 64
    good = confirmed_record(content_identity=ident, accepted_files=["Makefile"],
                            person_confirmation={"words": "test as is", "at": "2026-10-02T11:00:00+00:00", "task": "QA-1",
                                                 "kind": "content_accepted", "revision": HEAD, "content": ident})
    check_eq("FB8 (R12): a good content word has no problems, and is person_confirmed with and without rehearsal=True",
             (P.person_confirmed_problems(good), P.acceptable_provenance(good, P.ACCEPTS, task="QA-1"),
              P.acceptable_provenance(good, P.ACCEPTS, rehearsal=True, task="QA-1")), ([], True, True))

    def bad(**more):
        record = dict(good, **more)
        return P.person_confirmed_problems(record), P.acceptable_provenance(record, P.ACCEPTS, task="QA-1")
    other_word = dict(good["person_confirmation"], revision=OTHER)
    check_eq("FB8 (R12): a revision that is not this story's commit is refused",
             (len(bad(person_confirmation=other_word)[0]), bad(person_confirmation=other_word)[1]), (1, False))
    other_content = dict(good["person_confirmation"], content="b" * 64)
    check_eq("FB8 (R12): a content that is not the record's content_identity is refused",
             (len(bad(person_confirmation=other_content)[0]), bad(person_confirmation=other_content)[1]), (1, False))
    check_eq("FB8 (R12): no content_identity in the record is refused", bad(content_identity="")[1], False)
    check_eq("FB8 (R12): an empty accepted_files is refused", bad(accepted_files=[])[1], False)
    check_eq("FB8 (R12): a tested_build is refused", bad(tested_build=HEAD)[1], False)
    check_in("FB8 (R14): the refusal of a content mismatch names the second door",
             "`test as is`", P.say_refusal("content_mismatch", files="Makefile"))
    check_in("FB8 (R14): and so does the capture remedy", "`test as is`", P.say_refusal("remedy_other_content"))
    check_eq("FB8 (R16): shown_files caps AT and BEYOND FILES_SHOWN",
             (P.shown_files(["a", "b", "c"]), P.shown_files(["a", "b", "c", "d"]), P.shown_files([])),
             ("a, b, c", "a, b, c and 1 more", ""))


HEAD = "0cc6c4f1" + "a" * 32
OTHER = "d" * 40


def matched_record(**more) -> dict:
    """What `runtime_probe.py` prints for a build it read (the shape of a real run: one evidence file named)."""
    record = {"profile_id": "e2e-ui", "timestamp": "2026-10-02T12:00:00+00:00", "environment_id": "localhost",
              "expected_source_revision": HEAD, "observed_runtime_identity": "image:sha256:" + "b" * 64,
              "evidence_refs": ["evidence/runtime-provenance-e2e-ui.json"], "result": "matched",
              "provenance": {"technical_verification": True, "source_linkage": "exact", "identity_kind": "oci_label",
                             "deployed_source_revision": HEAD, "verified_source_revisions": [HEAD]}}
    record.update(more)
    return record


def confirmed_record(**more) -> dict:
    record = {"profile_id": "e2e-ui", "timestamp": "2026-10-02T12:00:00+00:00", "environment_id": "localhost",
              "expected_source_revision": HEAD, "observed_runtime_identity": "person-confirmed:2026-10-02T11:00:00+00:00",
              "evidence_refs": [], "result": "person_confirmed",
              "provenance": {"technical_verification": False, "identity_kind": "person_confirmed"},
              "person_confirmation": {"words": "yes, deployed", "at": "2026-10-02T11:00:00+00:00", "task": "QA-1",
                                      "kind": "deployed", "revision": HEAD}}
    record.update(more)
    return record


def t300_k27_person_confirmed_and_acceptable_provenance() -> None:
    """K27 (t-300): the fifth word and the ONE reading of "may I take this record" (F11)."""
    import profile_contract as P
    check_eq("K27: PROVENANCE_RESULTS has five words, the fifth is person_confirmed",
             (len(P.PROVENANCE_RESULTS), "person_confirmed" in P.PROVENANCE_RESULTS), (5, True))
    good = confirmed_record()
    check_eq("K27: a valid person_confirmed record validates, and is person_confirmed (never matched)",
             (P.validate_runtime_provenance(good)["valid"], P.validate_runtime_provenance(good)["result"], P.person_confirmed(good)),
             (True, "person_confirmed", True))
    invalid = {
        "empty words": confirmed_record(person_confirmation={"words": "  ", "at": "2026-10-02T11:00:00+00:00", "revision": HEAD}),
        "no confirmation block": {k: v for k, v in confirmed_record().items() if k != "person_confirmation"},
        "no time": confirmed_record(person_confirmation={"words": "yes", "revision": HEAD}),
        "technical_verification true": confirmed_record(provenance={"technical_verification": True,
                                                                    "identity_kind": "person_confirmed"}),
        "an identity_kind that is not person_confirmed": confirmed_record(provenance={"technical_verification": False,
                                                                                    "identity_kind": "oci_label"}),
        "an empty identity": confirmed_record(observed_runtime_identity=""),
        "a tested_build that is not the confirmed revision": confirmed_record(tested_build=OTHER),
    }
    for label, record in invalid.items():
        checked = P.validate_runtime_provenance(record)
        check_eq(f"K27: {label}: invalid, and `unknown` (a word that does not hold together answers nothing)",
                 (checked["valid"], checked["result"], P.person_confirmed(record)), (False, "unknown", False))
    dressed = matched_record(provenance={"technical_verification": True, "source_linkage": "exact",
                                         "identity_kind": "person_confirmed", "deployed_source_revision": HEAD,
                                         "verified_source_revisions": [HEAD]})
    check_eq("K27: `matched` + identity_kind person_confirmed (the word dressed as a reading) is invalid and unknown",
             (P.validate_runtime_provenance(dressed)["valid"], P.validate_runtime_provenance(dressed)["result"]),
             (False, "unknown"))
    tested = confirmed_record(tested_build=OTHER, provenance={"technical_verification": False, "identity_kind": "person_confirmed",
                                                              "deployed_source_revision": OTHER},
                              person_confirmation={"words": "test what is deployed", "at": "2026-10-02T11:00:00+00:00",
                                                   "task": "QA-1", "kind": "test_deployed", "revision": OTHER,
                                                   "story_revision": HEAD})
    check_eq("K27: person_confirmed with deployed_source_revision != expected stays person_confirmed (test deployed: never downgraded)",
             (P.validate_runtime_provenance(tested)["valid"], P.validate_runtime_provenance(tested)["result"], P.person_confirmed(tested)),
             (True, "person_confirmed", True))
    check_eq("K27 control: the same disagreement on a MATCHED record is still mismatched",
             P.validate_runtime_provenance(matched_record(provenance={"technical_verification": True, "source_linkage": "exact",
                                                                      "deployed_source_revision": OTHER}))["result"], "mismatched")
    check_eq("K27: person_confirmed(...) of a non-record or of another word is False",
             (P.person_confirmed(None), P.person_confirmed({}), P.person_confirmed(matched_record())), (False, False, False))

    # acceptable_provenance: the matrix. Existing matched / mismatched cases are unchanged.
    accept = P.acceptable_provenance
    check_eq("K27: a valid matched record is accepted by a caller that accepts `matched`, refused by one that does not",
             (accept(matched_record(), ("matched",)), accept(matched_record(), ("person_confirmed",))), (True, False))
    check_eq("K27: person_confirmed is accepted only by name",
             (accept(good, ("person_confirmed",)), accept(good, ("matched",)), accept(good, ("matched", "not_applicable:no_changed_file"))),
             (True, False, False))
    check_eq("K27: an invalid person_confirmed is refused even by name", accept(invalid["empty words"], ("person_confirmed",)), False)
    check_eq("K27: `MATCHED` (a spelling) is refused", accept(matched_record(result="MATCHED"), ("matched",)), False)
    check_eq("K27: a word outside the five is refused", accept(matched_record(result="verified"), ("matched",)), False)
    check_eq("K27: a mismatched record is refused whatever the list says",
             accept(matched_record(provenance={"technical_verification": True, "source_linkage": "exact",
                                               "deployed_source_revision": OTHER}), ("matched",)), False)
    check_eq("K27: `unknown` is never accepted", accept(matched_record(result="unknown"), ("matched", "person_confirmed")), False)
    na = {"profile_id": "api", "timestamp": "2026-10-02T12:00:00+00:00", "environment_id": "localhost",
          "expected_source_revision": HEAD, "observed_runtime_identity": "", "evidence_refs": [], "result": "not_applicable",
          "reason_code": "no_changed_file", "provenance": {"technical_verification": False}}
    token = ("not_applicable:no_changed_file",)
    check_eq("K27: not_applicable WITH reason_code no_changed_file is accepted by its token, and refused without the token",
             (accept(na, token), accept(na, ("matched",))), (True, False))
    check_eq("K27: not_applicable WITHOUT reason_code is refused against the token",
             accept({k: v for k, v in na.items() if k != "reason_code"}, token), False)
    for bad in (("matched", "nonsense"), ("MATCHED",), ("not_applicable",)):
        try:
            accept(matched_record(), bad)
            raised = False
        except ValueError:
            raised = True
        check_eq(f"K27: an unknown accepts token {bad!r} is a ValueError, never a silent refusal", raised, True)
    check_eq("K27: a record that is not a dict is refused", (accept(None, ("matched",)), accept("matched", ("matched",))), (False, False))

    # rehearsal=True: ONE excuse, and only with the marker
    printed = matched_record(evidence_refs=[], observed_without_evidence=True)
    check_eq("K27: STRICT: a matched record with no evidence file is invalid for validate_runtime_provenance, marker or not (pin 1)",
             (P.validate_runtime_provenance(printed)["valid"], P.validate_runtime_provenance(printed)["result"]), (False, "unknown"))
    check_eq("K27: rehearsal=True admits that matched record (no evidence refs, the marker)", accept(printed, ("matched",), rehearsal=True), True)
    check_eq("K27 NEGATIVE CONTROL: the same record with rehearsal=False is refused", accept(printed, ("matched",), rehearsal=False), False)
    check_eq("K27 NEGATIVE CONTROL: rehearsal=True WITHOUT the marker is refused",
             accept(matched_record(evidence_refs=[]), ("matched",), rehearsal=True), False)
    check_eq("K27: the marker alone (no rehearsal=True) does not make a matched record without evidence acceptable",
             accept(matched_record(evidence_refs=[], observed_without_evidence=True), ("matched",)), False)
    check_eq("K27: the marker must be exactly true (a string 'true' is not the marker)",
             accept(matched_record(evidence_refs=[], observed_without_evidence="true"), ("matched",), rehearsal=True), False)
    check_eq("K27: evidence_refs that is not an empty list (None) is refused even with the marker",
             accept(matched_record(evidence_refs=None, observed_without_evidence=True), ("matched",), rehearsal=True), False)
    check_eq("K27: rehearsal=True still refuses everything else that makes a matched record invalid (no technical verification)",
             accept(matched_record(evidence_refs=[], observed_without_evidence=True,
                                   provenance={"technical_verification": False}), ("matched",), rehearsal=True), False)
    check_eq("K27: rehearsal=True with the marker never turns a mismatched record into a pass",
             accept(matched_record(evidence_refs=[], observed_without_evidence=True,
                                   provenance={"technical_verification": True, "source_linkage": "exact",
                                               "deployed_source_revision": OTHER}), ("matched",), rehearsal=True), False)
    check_eq("K27: the rehearsal view changes ONE thing: a matched + marker record gets a stand-in evidence ref; nothing else is touched",
             (P.rehearsal_view(printed)["evidence_refs"], P.rehearsal_view(matched_record()) == matched_record(),
              P.rehearsal_view(good) is good), ([P.REHEARSAL_EVIDENCE], True, True))
    t300_n2_the_word_says_what_it_was_given_for()
    t300_n2_the_refusal_says_what_the_probe_said()


def t300_n2_the_word_says_what_it_was_given_for() -> None:
    """t-300 N2 X5/X6/E2: a person's word counts only when it SAYS what it was given for - the kind, the story, the revision -
    and the revisions agree with the record it sits in. `task=` binds it to one story (E5)."""
    import profile_contract as P
    good = confirmed_record()
    check_eq("N2 X6: the word the probe writes (kind, task, revision all there) has no problem", P.person_confirmed_problems(good), [])
    for label, record, fragment in (
            ("no kind", confirmed_record(person_confirmation={k: v for k, v in good["person_confirmation"].items() if k != "kind"}),
             "person_confirmation.kind must be one of deployed, test_deployed"),
            ("a kind outside the two", confirmed_record(person_confirmation={**good["person_confirmation"], "kind": "withdrawn"}),
             "person_confirmation.kind must be one of"),
            ("no task", confirmed_record(person_confirmation={k: v for k, v in good["person_confirmation"].items() if k != "task"}),
             "person_confirmation.task is required"),
            ("no revision", confirmed_record(person_confirmation={k: v for k, v in good["person_confirmation"].items() if k != "revision"}),
             "person_confirmation.revision is required"),
            ("a deployed word for another commit", confirmed_record(person_confirmation={**good["person_confirmation"], "revision": OTHER}),
             "a `deployed` word must name this story's commit"),
            ("a test_deployed word with no tested_build",
             confirmed_record(person_confirmation={**good["person_confirmation"], "kind": "test_deployed", "revision": OTHER,
                                                   "story_revision": HEAD}),
             "tested_build must equal person_confirmation.revision"),
            ("a test_deployed word for another story commit",
             confirmed_record(tested_build=OTHER, provenance={"technical_verification": False, "identity_kind": "person_confirmed"},
                              person_confirmation={**good["person_confirmation"], "kind": "test_deployed", "revision": OTHER,
                                                   "story_revision": "e" * 40}),
             "story_revision must equal expected_source_revision")):
        problems = P.person_confirmed_problems(record)
        check_eq(f"N2 X6 E2: {label}: refused, and the problem says which fact is missing",
                 (any(fragment in p for p in problems), P.person_confirmed(record), P.acceptable_provenance(record, P.ACCEPTS)),
                 (True, False, False))
    same = confirmed_record(tested_build=HEAD, provenance={"technical_verification": False, "identity_kind": "person_confirmed",
                                                          "deployed_source_revision": HEAD},
                            person_confirmation={**good["person_confirmation"], "kind": "test_deployed", "revision": HEAD,
                                                 "story_revision": HEAD})
    check_eq("N2 F5 (t-395): a `test_deployed` word whose revision IS its story_revision is refused (it names ONE build as two), "
             "with the block's sentence",
             (P.person_confirmed(same), P.acceptable_provenance(same, P.ACCEPTS),
              P.say_refusal("confirmation_same_build") in P.person_confirmed_problems(same)), (False, False, True))
    other_build = confirmed_record(tested_build=OTHER, provenance={"technical_verification": False, "identity_kind": "person_confirmed",
                                                                   "deployed_source_revision": OTHER},
                                   person_confirmation={**good["person_confirmation"], "kind": "test_deployed", "revision": OTHER,
                                                        "story_revision": HEAD})
    check_eq("N2 F5 twin: the same word naming ANOTHER build is accepted (K27's own `tested` shape)", P.person_confirmed(other_build), True)
    import json
    import tempfile
    import shutil
    folder = Path(tempfile.mkdtemp(prefix="qa-f5-block-"))
    held = P.REFUSAL_DATA
    try:
        (folder / "m.json").write_text(json.dumps({"refusals": {"confirmation_same_build": "BLOCK[same build]"}}), encoding="utf-8")
        P.REFUSAL_DATA = folder / "m.json"
        check_eq("N2 F5/F6: the sentence is read from the refusals block (a changed block value changes it)",
                 "BLOCK[same build]" in P.person_confirmed_problems(same), True)
    finally:
        P.REFUSAL_DATA = held
        shutil.rmtree(folder, ignore_errors=True)
    check_eq("N2 X5: with `task=`, the word given for ANOTHER story is refused by the predicate, naming both stories",
             (P.acceptable_provenance(good, P.ACCEPTS, task="QA-1"), P.acceptable_provenance(good, P.ACCEPTS, task="QA-2"),
              P.person_confirmed_problems(good, "QA-2")),
             (True, False, ["the person's word was given for story QA-1, and this is story QA-2"]))
    check_eq("N2 X5 control: with no `task` the predicate does not ask (the caller that cannot name the story is not refused)",
             P.acceptable_provenance(good, P.ACCEPTS), True)
    check_eq("N2 X5: the story binding never touches a `matched` record", P.acceptable_provenance(matched_record(), P.ACCEPTS, task="QA-2"), True)
    check_eq("N2: person_confirmed_problems of a non-record says so", P.person_confirmed_problems(None), ["the record is not an object"])


def t300_n2_the_refusal_says_what_the_probe_said() -> None:
    """t-300 N2 X10/F1: the words of a refusal are DATA (`refusals` in references/build-identity-methods.json) with ONE default
    in `profile_contract` for a package that has no block yet; the data wins key by key once the block exists; and the sentence
    is built from fields of the record."""
    import json
    import profile_contract as P
    import tempfile
    mismatched = matched_record(result="mismatched", provenance={"technical_verification": True, "source_linkage": "exact",
                                                                  "deployed_source_revision": OTHER})
    data = json.loads((Path(P.__file__).resolve().parent.parent / "references" / "build-identity-methods.json").read_text(encoding="utf-8"))
    block = data.get("refusals") or {}
    check_eq("N2 X10 (the move that creates the block): the shipped data file HAS a `refusals` block holding every default key",
             sorted(set(P.REFUSAL_DEFAULTS) - set(block)), [])
    check_eq("N2 X10: and the shipped words equal the defaults (one text, kept in two places only until the block is the one)",
             {k: block[k] for k in P.REFUSAL_DEFAULTS}, dict(P.REFUSAL_DEFAULTS))
    shown = P.refusal_text(mismatched)
    check_in("N2: a proven mismatch names the build the stand runs", OTHER[:12], shown)
    check_in("N2: and this story's commit", HEAD[:12], shown)
    check_in("N2: and the person's door", "`test deployed`", shown)
    voided = dict(mismatched, voided={"what": "the stand now shows the build " + OTHER[:12], "earlier_at": "2026-10-02T09:30:00+00:00"})
    check_in("N2 F1: a moved word comes back `mismatched` + `voided`: the sentence appends the voided clause the way `unknown` does",
             "The person's word of 2026-10-02 no longer holds: the stand now shows the build " + OTHER[:12], P.refusal_text(voided))
    check_eq("N2 F1 control: an unconfirmed word (plain `mismatched`, no voided) appends nothing",
             P.refusal_text(mismatched).count("no longer holds"), 0)
    check_eq("N2: the build question is the person's only while a commit is named: stand_runs_other_build reads the effective result",
             (P.stand_runs_other_build(mismatched), P.stand_runs_other_build(matched_record()), P.stand_runs_other_build(None),
              P.stand_runs_other_build(matched_record(result="unknown"))), (True, False, False, False))
    # TEMPORAL: no block / no file -> the default; the block -> its text wins, key by key
    folder = Path(tempfile.mkdtemp(prefix="qa-refusal-words-"))
    try:
        absent = P.refusal_words(folder / "nope.json")
        check_eq("N2 TEMPORAL: a data file that is absent leaves the defaults, so every refusal still produces a sentence",
                 absent, P.REFUSAL_DEFAULTS)
        (folder / "old.json").write_text(json.dumps({"schema_version": 1, "ladder": []}), encoding="utf-8")
        check_eq("N2 TEMPORAL: a file with no `refusals` block (the data file before this revision) leaves the defaults",
                 P.refusal_words(folder / "old.json"), P.REFUSAL_DEFAULTS)
        (folder / "broken.json").write_text("{", encoding="utf-8")
        check_eq("N2 TEMPORAL: an unreadable file leaves the defaults too", P.refusal_words(folder / "broken.json"), P.REFUSAL_DEFAULTS)
        (folder / "new.json").write_text(json.dumps({"refusals": {"note": "x", "no_reason": "NO WORD FROM THE PROBE", "bogus": 3}}),
                                         encoding="utf-8")
        words = P.refusal_words(folder / "new.json")
        check_eq("N2 TEMPORAL: once the block exists its text WINS for the key it holds, the default stands for the rest",
                 (words["no_reason"], words["mismatched"] == P.REFUSAL_DEFAULTS["mismatched"], "note" in words, "bogus" in words),
                 ("NO WORD FROM THE PROBE", True, False, False))
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
    check_eq("N2: a template naming a slot nobody gave comes back as written (a refusal never raises)",
             P.say_refusal("mismatched", {"mismatched": "stand {nobody}"}), "stand {nobody}")
    check_in("N2 F4: a non-zero exit quotes the first non-blank line of stderr", "no story is running",
             P.probe_failed_text(2, "\n  no story is running; Pass --task\nmore"))
    check_in("N2 F4: and one that said nothing is named as that, with its code", "exited with code 7 and printed no reason on stderr",
             P.probe_failed_text(7, ""))


if __name__ == "__main__":
    main()
