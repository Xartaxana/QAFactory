"""Typed RunRequest scope, deduplication, reports, and launcher receipts."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, finish

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
from execution_request import (JobStore, RequestError, request_digest, selector_join_problem,  # noqa: E402
                               validate_request)
from execution_fingerprint import file_hash  # noqa: E402
from run_suite import template  # noqa: E402
from profile_contract import ACCEPTS as ACCEPTS_OF_THE_PACKAGE  # noqa: E402


# Outside the package: a local-directory marketplace copies whatever lies in it.
ROOT = Path(tempfile.mkdtemp(prefix="qa-execution-request-"))


def base_request(key: str = "initial-1") -> dict:
    ids = [f"case-{i}" for i in range(10)]
    return {
        "task": "REQ-1", "revision": "plan-1", "dispatch_id": "dispatch-1",
        "profile_id": "api", "purpose": "initial", "selected_instance_ids": ids,
        "current_scope_instance_ids": ids, "input_fingerprint": "sha256:inputs-1",
        "fingerprint_files": [{"path": str(ROOT / "dummy_runner.py"),
                               "sha256": file_hash(ROOT / "dummy_runner.py"), "kind": "test_files"},
                              {"path": str(ROOT / "qa-factory" / "config.json"),
                               "sha256": file_hash(ROOT / "qa-factory" / "config.json"), "kind": "config_files"}],
        "fingerprint_components": {"source_sha": "a" * 40, "test_content_sha": "b" * 64,
                                   "config_sha": "c" * 64},
        "runtime_provenance": {"profile_id": "api", "timestamp": "2026-09-17T12:00:00Z",
                               "environment_id": "qa", "expected_source_revision": "source-1",
                               "observed_runtime_identity": "build-1", "evidence_refs": ["deploy/1"],
                               "provenance": {"technical_verification": True,
                                              "source_linkage": "exact",
                                              "deployed_source_revision": "source-1"},
                               "result": "matched"},
        "runtime_required": True,
        "runtime_probe": {"argv": [sys.executable, str(ROOT / "runtime_probe.py")],
                          "cwd": ".", "timeout_s": 5},
        "instance_contracts": {instance: {"report_test_id": f"x::{instance}",
                                           "parameters": {"index": i}}
                               for i, instance in enumerate(ids)},
        "reason": "author completed the approved set", "remaining_budget": 100,
        "idempotency_key": key, "freshness": "fresh",
        "command": {"argv": [sys.executable, str(ROOT / "dummy_runner.py"), "{report_path}"], "cwd": ".",
                    "scope": "selected", "reporter": "junit-xml", "report_path": "{report_path}",
                    "selector_contract_verified": True,
                    "selector_args": {instance: [instance] for instance in ids}},
    }


def invoke(request: dict) -> subprocess.CompletedProcess:
    path = ROOT / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(ROOT)
    env["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = "1"
    return subprocess.run([sys.executable, str(PLUGIN_ROOT / "scripts" / "run_suite.py"),
                          "--request", str(path)], cwd=ROOT, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=90)


JOIN = {"option": "--filter", "separator": "|"}
TRX_LOGGER = "trx;LogFileName={report_path}"


def filter_request(key: str, ids: list, join=None, reporter: str = "junit-xml",
                   embedded: bool = False) -> dict:
    """A request whose runner takes ONE selection option: `--filter FullyQualifiedName=<id>`.

    `embedded` puts the report placeholder INSIDE a token (`trx;LogFileName={report_path}`),
    the way the .NET logger option spells it; otherwise the argv has the exact token."""
    request = base_request(key)
    # Its own input fingerprint: a request over bytes that already hold a result is ANSWERED from
    # it and launches nothing (the run budget), so a launch check needs bytes no earlier one ran.
    request["input_fingerprint"] = "sha256:" + key
    request["selected_instance_ids"] = list(ids)
    request["command"]["argv"] = ([sys.executable, str(ROOT / "filter_runner.py"),
                                   "--logger", TRX_LOGGER] if embedded else
                                  [sys.executable, str(ROOT / "filter_runner.py"), "{report_path}"])
    request["command"]["reporter"] = reporter
    request["command"]["selector_args"] = {
        instance: ["--filter", f"FullyQualifiedName={instance}"]
        for instance in request["current_scope_instance_ids"]}
    if reporter == "trx":
        request["instance_contracts"] = {
            instance: {**contract, "report_id_source": "catalog"}
            for instance, contract in request["instance_contracts"].items()}
    if join is not None:
        request["command"]["selector_join"] = join
    return request


def refusal(request: dict) -> str:
    """The validator's refusal text, or "" when the request passes."""
    try:
        validate_request(request, ROOT)
    except RequestError as exc:
        return str(exc)
    return ""


def resolve(request: dict) -> dict:
    """The validated request; a refusal is a failed check here, not a crashed file."""
    try:
        return validate_request(request, ROOT)
    except RequestError as exc:
        return {"resolved_argv": [f"REFUSED: {exc}"], "selected_instance_ids": []}


def tail(request: dict) -> list:
    """What the selection appended after the command's own argv."""
    return resolve(request)["resolved_argv"][len(request["command"]["argv"]):]


def selector_join_checks() -> None:
    """M18: one option that takes the whole selection is a rule of the runner profile, not of
    the code; the placeholder may sit whole or embedded in exactly one token (upstream's rule)."""
    ids = [f"case-{i}" for i in range(10)]
    value = {i: f"FullyQualifiedName={i}" for i in ids}

    # absent: today's behaviour, byte for byte
    golden = validate_request(base_request("golden-argv"), ROOT)["resolved_argv"]
    check_eq("no selector_join: resolved_argv is the repeat rule, byte for byte", golden,
             [sys.executable, str(ROOT / "dummy_runner.py"), "{report_path}"] + ids)
    repeated = tail(filter_request("repeat-filters", ids))
    check_eq("no selector_join: ten instances still repeat the option ten times",
             repeated, [t for i in ids for t in ("--filter", value[i])])

    # join
    check_eq("selector_join: ten instances become ONE option and one joined value",
             tail(filter_request("join-ten", ids, JOIN)),
             ["--filter", "|".join(value[i] for i in ids)])
    check_eq("selector_join: exactly one instance is appended unchanged",
             tail(filter_request("join-one", ["case-3"], JOIN)), ["--filter", value["case-3"]])
    check_eq("selector_join: one instance is never wrapped by `group`",
             tail(filter_request("join-one-group", ["case-3"], {**JOIN, "group": ["(", ")"]})),
             ["--filter", value["case-3"]])
    check_eq("selector_join: two instances, in the order they were selected",
             tail(filter_request("join-two", ["case-5", "case-1"], JOIN)),
             ["--filter", value["case-5"] + "|" + value["case-1"]])
    check_eq("selector_join: `group` wraps each value when there are two or more",
             tail(filter_request("join-group", ["case-1", "case-2"],
                                 {"option": "--filter", "separator": " OR ", "group": ["(", ")"]})),
             ["--filter", f"({value['case-1']}) OR ({value['case-2']})"])
    dup = filter_request("join-dup", ["case-1", "case-2", "case-3"], JOIN)
    dup["command"]["selector_args"]["case-3"] = list(dup["command"]["selector_args"]["case-1"])
    check_eq("selector_join: an exact duplicate value is emitted once, first appearance wins",
             tail(dup), ["--filter", value["case-1"] + "|" + value["case-2"]])
    check("selector_join: every selected instance is still in the request",
          resolve(dup)["selected_instance_ids"] == ["case-1", "case-2", "case-3"])

    # a selector that cannot be joined is refused, never silently dropped
    three = filter_request("join-three", ["case-1", "case-2"], JOIN)
    three["command"]["selector_args"]["case-2"] = ["--filter", value["case-2"], "--no-build"]
    why = refusal(three)
    check_in("a three-token selector is refused, naming the instance", "case-2", why)
    check_in("and the shape it expected", "[--filter, <value>]", why)
    check_in("and the door that corrects it", "manifest_put.py", why)
    check_eq("the same three-token selector alone is appended unchanged",
             tail({**three, "selected_instance_ids": ["case-2"]}),
             ["--filter", value["case-2"], "--no-build"])
    other = filter_request("join-other-option", ["case-1", "case-2"], JOIN)
    other["command"]["selector_args"]["case-1"] = ["--other", "x"]
    check_in("another option than the profile's is refused too", "case-1", refusal(other))

    # a malformed rule in a hand-written request
    for label, bad in (("a string", "|"), ("null", None), ("a list", []),
                       ("no option", {"separator": "|"}), ("no separator", {"option": "--filter"}),
                       ("an empty option", {"option": "", "separator": "|"}),
                       ("an empty separator", {"option": "--filter", "separator": ""}),
                       ("a non-string option", {"option": 5, "separator": "|"}),
                       ("a string group", {**JOIN, "group": "()"}),
                       ("a one-item group", {**JOIN, "group": ["("]}),
                       ("a numeric group", {**JOIN, "group": [1, 2]}),
                       ("a three-item group", {**JOIN, "group": ["(", ")", "x"]})):
        malformed = filter_request("join-bad", ["case-1"], JOIN)
        malformed["command"]["selector_join"] = bad
        check_in(f"a malformed selector_join ({label}) is refused", "command.selector_join",
                 refusal(malformed))
    # F4: a key the rule does not know is a typo, and a typo launched the values unwrapped - the
    # refusal names the keys the rule has (the door is the key spelled right)
    for label, bad in (("groups", {**JOIN, "groups": ["(", ")"]}), ("seperator", {"option": "--filter",
                       "seperator": "|"}), ("a key with a valid group", {**JOIN, "group": ["(", ")"], "unwrapped": 1})):
        typo = filter_request("join-typo", ["case-1", "case-2"], JOIN)
        typo["command"]["selector_join"] = bad
        why = refusal(typo)
        check_in(f"an unknown selector_join key ({label}) is refused", "command.selector_join", why)
        check_in(f"{label}: the refusal names the allowed keys", "option, separator, group", why)
        check_in(f"{label}: and the key it did not know",
                 [k for k in bad if k not in ("option", "separator", "group")][0], why)
    check_eq("selector_join_problem: a rule with every allowed key is fine",
             selector_join_problem({**JOIN, "group": ["(", ")"]}), "")
    check_in("selector_join_problem: an unknown key names the allowed ones", "option, separator, group",
             selector_join_problem({**JOIN, "groups": []}))
    # F4: a pytest profile never takes a join - its selectors are built by the factory - and the door
    # is the PROFILE, not manifest_put.py (a role cannot correct a profile through the manifest)
    py_join = filter_request("join-pytest", ids, JOIN)
    py_join["command"]["argv"] = ["pytest", "--junitxml", "{report_path}"]
    py_join["command"]["selector_args"] = {i: [f"tests/test_x.py::{i}"] for i in ids}
    why = refusal(py_join)
    check_in("a pytest command with a selector_join is refused with the profile as the door",
             "remove selectors.join from profile api: pytest selectors are built by the factory", why)
    check_not_in("and the door is not manifest_put.py", "manifest_put.py", why)
    py_one = {**py_join, "selected_instance_ids": ["case-1"]}
    check_eq("one pytest instance never reached the join, so it still passes", refusal(py_one), "")
    ambiguous = filter_request("join-ambiguous", ["case-1", "case-2"], JOIN)
    ambiguous["instance_contracts"]["case-2"]["report_test_id"] = "x::case-1"
    check_in("the ambiguous report_test_id refusal is unchanged by a join", "maps ambiguously",
             refusal(ambiguous))

    # placeholder: one rule for the exact token and for a token that contains it
    embedded = filter_request("embedded", ["case-1"], embedded=True)
    check_eq("a token that CONTAINS the placeholder satisfies the validator", refusal(embedded), "")
    check_eq("an embedded placeholder stays inside its token in the resolved argv (the launch replaces it "
             "inside that token) and the selection follows it",
             resolve(embedded)["resolved_argv"][-4:],
             ["--logger", TRX_LOGGER, "--filter", value["case-1"]])
    two_holders = filter_request("two-placeholders", ["case-1"], embedded=True)
    two_holders["command"]["argv"] = two_holders["command"]["argv"] + ["--also={report_path}"]
    check_in("two tokens carrying the placeholder are refused: exactly one token", "exactly one token",
             refusal(two_holders))
    none_at_all = filter_request("no-placeholder", ["case-1"])
    none_at_all["command"]["argv"] = [sys.executable, "runner.py"]
    check_in("an argv with no placeholder is still refused", "explicit {report_path} token",
             refusal(none_at_all))
    in_selector = filter_request("selector-placeholder", ["case-1"])
    in_selector["command"]["selector_args"]["case-1"] = ["--filter", "x={report_path}"]
    why = refusal(in_selector)
    check_in("a placeholder inside a selector is refused", "case-1", why)
    check_in("and says a selector is identity, not report plumbing", "selector", why)

    # the template names the join, with one example
    skeleton, legend = template("request")
    check_in("--template request names command.selector_join", "command.selector_join",
             "\n".join(legend))
    check_in("with one example line", '"option": "--filter"', "\n".join(legend))


def launch_checks() -> None:
    """The same rules end to end through run_suite.py --request: the runner prints its usage
    text and writes nothing when the option is repeated, as `dotnet test` does."""
    ids = [f"case-{i}" for i in range(10)]
    seen = ROOT / "argv-seen.txt"
    blocks = ROOT / "qa-factory" / "artifacts" / "REQ-1" / "work" / "run-blocks"
    for embedded in (False, True):
        how = "an embedded placeholder" if embedded else "an exact placeholder token"
        seen.unlink(missing_ok=True)
        joined = invoke(filter_request(f"launch-join-{embedded}", ids, JOIN, embedded=embedded))
        check_eq(f"ten instances through one --filter run ({how})", joined.returncode, 0)
        lines = seen.read_text(encoding="utf-8").splitlines() if seen.exists() else []
        check_eq(f"the runner was launched once ({how})", len(lines), 1)
        check_eq(f"with exactly one --filter ({how})",
                 lines[0].split().count("--filter") if lines else -1, 1)
        check(f"and no brace of the placeholder reaches the launched argv ({how})",
              bool(lines) and "{report_path}" not in lines[0])
        newest = max(blocks.glob("*.json"), key=lambda p: p.stat().st_mtime)
        rows = json.loads(newest.read_text(encoding="utf-8")).get("results", [])
        check_eq(f"every selected instance joined its reporter row ({how})",
                 [(r.get("instance_id"), r.get("report_matched")) for r in rows],
                 [(i, True) for i in ids])
    seen.unlink(missing_ok=True)
    single = invoke(filter_request("launch-embedded", ["case-4"], embedded=True))
    check_eq("an embedded placeholder is launched bound, not literally", single.returncode, 0)
    check("the launched argv carries the absolute report path",
          seen.exists() and "{report_path}" not in seen.read_text(encoding="utf-8"))


def t238_w5_the_reader_fills_in_this_machine_and_leaves_what_a_person_wrote() -> None:
    """The config stores `{python}` and `{plugin_root}`; `registered_probe` (the S5 run path's reader of
    `execution.runtime_probes`) fills in THIS machine's interpreter and plugin location. An argv written
    before that holds absolute paths, and runs as written."""
    import hooklib
    from execution_request import registered_probe
    head = ["{python}", "{plugin_root}/scripts/runtime_probe.py"]
    tail = ["--profile", "api", "--container", "c", "--checkout", "../../testproject1", "--app-root", "/app"]

    def cfg_of(entry, key="api"):
        return {"execution": {"runtime_probes": {key: entry}}}
    spec = registered_probe(cfg_of({"argv": head + tail, "cwd": ".", "timeout_s": 120}), "api")
    check_eq("{python} becomes this machine's interpreter", spec["argv"][0], sys.executable)
    check_eq("{plugin_root} becomes hooklib's plugin root", spec["argv"][1],
             str(hooklib.PLUGIN_ROOT) + "/scripts/runtime_probe.py")
    check("and the script it names exists", Path(spec["argv"][1]).is_file())
    check_eq("nothing else in the argv moves", spec["argv"][2:], tail)
    check_eq("cwd and timeout are carried", (spec["cwd"], spec["timeout_s"]), (".", 120))
    absent = registered_probe(cfg_of({"argv": head + tail}), "api")
    check_eq("`cwd` absent is the project root, as it always was; the timeout defaults to 30",
             (absent["cwd"], absent["timeout_s"]), (".", 30))
    legacy = [sys.executable, str(PLUGIN_ROOT / "scripts" / "runtime_probe.py")] + tail
    check_eq("an entry written BEFORE the change (absolute argv) is executed as written",
             registered_probe(cfg_of({"argv": legacy, "cwd": ".", "timeout_s": 5}), "api")["argv"], legacy)
    project = ["python", "/opt/project/probe.py", "--profile", "api"]
    check_eq("an absolute path to a project script stays as the person wrote it",
             registered_probe(cfg_of({"argv": project}), "api")["argv"], project)
    check_eq("`*` serves a profile with no entry of its own",
             registered_probe(cfg_of({"argv": head}, "*"), "e2e-ui")["argv"][0], sys.executable)
    check_eq("an entry of the profile wins over `*`", registered_probe(
        {"execution": {"runtime_probes": {"api": {"argv": ["x"]}, "*": {"argv": ["y"]}}}}, "api")["argv"], ["x"])
    for label, config in (("no execution", {}), ("no runtime_probes", {"execution": {}}),
                          ("runtime_probes of another shape", {"execution": {"runtime_probes": ["x"]}}),
                          ("an entry with no argv", cfg_of({"cwd": "."})), ("an empty argv", cfg_of({"argv": []})),
                          ("a profile that has none", cfg_of({"argv": head}, "ui"))):
        check_eq(f"{label}: no probe is registered (the caller's own refusal speaks)",
                 registered_probe(config, "api"), None)
    accepted = {**base_request("registered-probe"), "runtime_probe": {k: spec[k] for k in ("argv", "cwd", "timeout_s")}}
    check_eq("the substituted entry is what validate_request accepts as the request's `runtime_probe`",
             validate_request(accepted, ROOT)["runtime_probe"]["argv"][0], sys.executable)


def ep1_24_b1_the_s5_refusal_names_the_probe_command() -> None:
    """EP1-24 B1 (AK1, AK2, AK3, AK8; B-1..B-4, B-10): the refusal of a first typed run with no probe ends with ONE ready
    command, the container named when exactly one runs; the refusal's class and opening words never change."""
    import runtime_probe
    from execution_request import MineRefusal, _observe_stand
    real = runtime_probe.containers
    calls = []
    answer: list = []

    def fake(timeout: int = 20):
        calls.append(1)
        if isinstance(answer, Exception):
            raise answer
        return answer

    repos = {"implementation_repos": [{"repo_id": "app", "local_path": "app", "execution_profile_id": "api"}]}

    def refused(cfg: dict, profile: str = "api", probe=lambda spec: {}, **kw) -> str:
        """The refusal text; the project records a checkout for `api` unless `bare` (F1)."""
        full = cfg if kw.get("bare") else {**repos, **cfg}
        try:
            _observe_stand(full, profile, None, "run", probe, {}, ROOT, None, kw.get("evidence_only", False), [],
                           task_root=kw.get("task_root"))
        except MineRefusal as exc:
            return str(exc)
        raise AssertionError("the stand was observed; a refusal was expected")
    opening = "this is the story's first typed run on profile api, and the factory does not know how to identify"
    try:
        runtime_probe.containers = fake
        answer = [("app-1", "img")]
        one = refused({})
        check_in("AK1: one container: the command names it, profile filled in",
                 'runtime_probe.py" --suggest --write --profile api --container app-1', one)
        check_in("AK1: the second door (--template request) is kept", "--template request", one)
        check_in("the refusal opens as before", opening, one)
        answer = [("a", ""), ("b", "")]
        two = refused({})
        check_in("AK2: two containers: both names", "(a, b)", two)
        check_in("AK2: and the command asks the role to choose", "--profile api --container <name>", two)
        answer = [(f"c{i}", "") for i in range(5)]
        check_not_in("B-2: five names: no tail", "more)", refused({}))
        answer = [(f"c{i}", "") for i in range(6)]
        six = refused({})
        check_in("B-2: six names: five and `(+1 more)`", "c0, c1, c2, c3, c4 (+1 more)", six)
        check_not_in("B-2: the sixth is not named", "c5", six)
        answer = []
        none = refused({})
        check_not_in("AK3: no container: the command carries no --container", "--container", none.split("`")[1])
        check_in("AK3: and says to bring the stand up", "bring the stand up", none)
        for label, boom in (("OSError", OSError("docker")), ("a surprise", RuntimeError("x"))):
            answer = boom
            text = refused({})
            check_in(f"B-1: containers() raising {label}: a MineRefusal still, with the door and no container",
                     "--suggest --write --profile api", text)
            check_in(f"B-1: {label}: the same opening words", opening, text)
        answer = [("app-1", "")]
        calls.clear()
        # B-10: an entry exists for ANOTHER profile: the text says which profile has none, and offers that profile's command
        other = {"execution": {"runtime_probes": {"ui": {"argv": ["x"]}}}}
        text = refused(other)
        check_in("B-10: names the profile that has no entry", "no `execution.runtime_probes` entry in qa-factory/config.json for profile api", text)
        check_in("B-10: and the command is for that profile", "--profile api --container app-1", text)
        check_not_in("B-10: --force is never advised", "--force", text)
        # B-3: `*` is an entry: the profile is not refused for lack of one (the probe is used)
        star = {"execution": {"runtime_probes": {"*": {"argv": [sys.executable, "-c", "pass"], "cwd": "."}}}}
        got = _observe_stand(star, "api", None, "run", lambda spec: {"result": "matched"}, {}, ROOT, None, False, [])
        check_eq("B-3: a `*` entry is a probe", got["runtime_required"], True)
        # AK8 / M-B2: a registered probe never asks docker
        calls.clear()
        own = {"execution": {"runtime_probes": {"api": {"argv": [sys.executable, "-c", "pass"], "cwd": "."}}}}
        _observe_stand(own, "api", None, "run", lambda spec: {"result": "matched"}, {}, ROOT, None, False, [])
        check_eq("AK8: with a probe registered `containers()` is not called", calls, [])
        # an entry for this profile and no way to look at the stand: no door that would rewrite the entry (B-10)
        try:
            _observe_stand(own, "api", None, "run", None, {}, ROOT, None, False, [])
            same = ""
        except MineRefusal as exc:
            same = str(exc)
        check("B-10: an existing entry is refused without the write door", same != "" and "--suggest" not in same and "--force" not in same)
        check_eq("and without asking docker", calls, [])
        # B-4: a freshness read prints no write door and asks no docker
        fresh = refused({}, evidence_only=True)
        check_not_in("B-4: evidence_only: no write door", "--suggest", fresh)
        check_eq("B-4: and docker is not asked", calls, [])
        # F1: no recorded checkout for the profile: no door (gate A refuses to derive here too), the reason in words, the
        # template door stays, docker is not asked. Both shapes: no repository at all; the profile's own repository with no path
        # (the other repository's checkout is not a stand-in).
        answer = [("app-1", "")]
        for label, cfg_f1 in (("no repository", {}),
                              ("the profile's repository has no local_path",
                               {"implementation_repos": [{"repo_id": "web", "local_path": "web", "execution_profile_id": "ui"},
                                                         {"repo_id": "app", "execution_profile_id": "api"}]})):
            calls.clear()
            nothing = refused(cfg_f1, bare=True)
            check_not_in(f"F1: {label}: no write door", "--suggest", nothing)
            check_in(f"F1: {label}: the reason is in words", "records no checkout for it", nothing)
            check_in(f"F1: {label}: the template door stays", "--template request", nothing)
            check_in(f"F1: {label}: the refusal opens as before", opening, nothing)
            check_eq(f"F1: {label}: docker is not asked", calls, [])
        # F5: a key PRESENT with no usable `argv` is named as such, never "no entry", and no door: `--suggest --write` would
        # refuse it and advise `--force`, which B-10 forbids
        for label, entry in (("a note and no argv", {"note": "x", "cwd": "."}), ("a string", "runtime_probe.py")):
            calls.clear()
            text = refused({"execution": {"runtime_probes": {"api": entry, "ui": {"argv": ["x"]}}}})
            check_in(f"F5: {label}: the entry is named as unusable", "entry for profile api in qa-factory/config.json has no `argv`", text)
            check_not_in(f"F5: {label}: not told there is no entry", "no `execution.runtime_probes` entry", text)
            check_not_in(f"F5: {label}: no write door and no --force", "--suggest", text)
            check_not_in(f"F5: {label}: no --force", "--force", text)
            check_in(f"F5: {label}: the template door stays", "--template request", text)
            check_eq(f"F5: {label}: docker is not asked", calls, [])
        # AK1a: with the story known the containers are narrowed by its files (the gate-A reader), ONE name left is the command's
        work = ROOT / "ak1a"
        (work / "app" / "src").mkdir(parents=True, exist_ok=True)
        (work / "app" / "src" / "x.py").write_text("x = 1\n", encoding="utf-8")
        story = work / "story"
        (story / "work").mkdir(parents=True, exist_ok=True)
        (story / "work" / "impl-diff.txt").write_text("--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-x = 0\n+x = 1\n", encoding="utf-8")
        asked = []
        held_candidates = runtime_probe.content_candidates

        def only(names):
            def fake_candidates(files, checkout, app_root, running, timeout=20, cfg=None):
                asked.append((list(files), Path(checkout).name, [n for n, _i in running]))
                if isinstance(names, Exception):
                    raise names
                return names
            return fake_candidates

        def narrowed(names, **kw):
            runtime_probe.content_candidates = only(names)
            try:
                return _observe_stand_text(work, story if kw.get("known", True) else None)
            finally:
                runtime_probe.content_candidates = held_candidates

        def _observe_stand_text(project: Path, task_root) -> str:
            try:
                _observe_stand(repos, "api", None, "run", lambda spec: {}, {}, project, None, False, [], task_root=task_root)
            except MineRefusal as exc:
                return str(exc)
            raise AssertionError("a refusal was expected")
        answer = [("a", ""), ("b", "")]
        one = narrowed(["b"])
        check_in("AK1a: root known, files in one container: the command names it", "--profile api --container b`", one)
        check_eq("AK1a: the filter was asked with the story's files, the profile's checkout and both containers",
                 asked[-1], (["src/x.py"], "app", ["a", "b"]))
        check_not_in("AK1a: and the other is not named", "(a, b)", one)
        asked.clear()
        both = narrowed(["a", "b"])
        check_in("AK1a: both hold the files: both names", "(a, b)", both)
        check_in("AK1a: none holds them (a built bundle): all names, the role chooses", "(a, b)", narrowed([]))
        check_in("AK1a: the filter failing: all names, a MineRefusal still", "(a, b)", narrowed(RuntimeError("docker")))
        asked.clear()
        check_in("AK1a: root unknown: both names", "(a, b)", narrowed(["b"], known=False))
        check_eq("AK1a: and the filter is not asked", asked, [])
    finally:
        runtime_probe.containers = real


def t238_w4_not_applicable_is_in_the_accepted_set(request: dict) -> None:
    """A probe that does not apply to a profile (runtime_probe.py: the story changes no file of its
    checkout) answers `not_applicable`. `validate_request` accepted that word before this change and
    still does - for a verified local_source profile (`runtime_required: false`). For a profile that
    runs against a docker stand (`runtime_required: true`) it refuses it with the sentence below:
    OPEN QUESTION for the integrator (t-238 report): the probe's answer cannot reach a typed run
    there until that gate says when `not_applicable` is enough."""
    record = {**request["runtime_provenance"], "result": "not_applicable", "observed_runtime_identity": "",
              "evidence_refs": [], "provenance": {}}
    local = {**request, "idempotency_key": "na-local", "runtime_required": False, "target_kind": "local_source",
             "runtime_provenance": record}
    check_eq("not_applicable on a verified local_source profile is accepted, as before",
             validate_request(local, ROOT)["runtime_provenance"]["result"], "not_applicable")
    docker = {**request, "idempotency_key": "na-docker", "runtime_provenance": record}
    try:
        validate_request(docker, ROOT)
        refused = ""
    except RequestError as exc:
        refused = str(exc)
    check_in("on a docker-stand profile it is refused as it was, by the local_source rule (a gap, not a pass)",
             "runtime not_applicable requires a verified local_source profile contract", refused)
    mismatched = {**request, "idempotency_key": "na-mismatch", "runtime_provenance": {
        **request["runtime_provenance"], "result": "mismatched"}}
    try:
        validate_request(mismatched, ROOT)
        said = ""
    except RequestError as exc:
        said = str(exc)
    check_in("control: `mismatched` is refused by the accepted set", "must be valid matched, person_confirmed", said)
    check_in("and the refusal says what the probe said, what was expected and the door (t-300 N2)",
             "runtime probe returned mismatched", said)


def t279_k_na_a_probe_with_no_changed_file_is_enough_on_any_stand(request: dict) -> None:
    """K-NA: the cmp2-shaped config (api + e2e-ui, two checkouts) with a UI-only diff. The probe of the api
    profile compares nothing and says `not_applicable` with `reason_code: no_changed_file`; the api profile's
    request is then valid on the DOCKER stand (`runtime_required: true`, no local_source). The reason is a
    FIELD (FR-12): the same answer with no reason_code, or with another one, is refused as it was."""
    import contextlib
    import io
    import runtime_probe
    work = Path(tempfile.mkdtemp(prefix="qa-k-na-"))
    try:
        (work / "backend" / "src").mkdir(parents=True)
        (work / "backend" / "src" / "a.py").write_text("a", encoding="utf-8")
        (work / "ui" / "src").mkdir(parents=True)
        (work / "ui" / "src" / "Page.vue").write_text("v", encoding="utf-8")
        task = work / "story"
        (task / "work").mkdir(parents=True)
        (task / "work" / "impl-diff.txt").write_text("+++ b/src/Page.vue\n", encoding="utf-8")
        out, old = io.StringIO(), sys.argv
        sys.argv = ["runtime_probe.py", "--profile", "api", "--environment", "qa", "--container", "api-c",
                    "--checkout", str(work / "backend"), "--expected", "source-1", "--task-root", str(task)]
        try:
            with contextlib.redirect_stdout(out):
                runtime_probe.main()
        finally:
            sys.argv = old
        record = json.loads(out.getvalue())
        check_eq("K-NA: the api profile's probe, on a UI-only diff, is not_applicable with its reason as a field",
                 (record["result"], record["reason_code"]), ("not_applicable", "no_changed_file"))

        def verdict(rec, key):
            docker = {**request, "idempotency_key": key, "runtime_provenance": rec}   # runtime_required stays True
            try:
                return validate_request(docker, ROOT)["runtime_provenance"]["result"]
            except RequestError as exc:
                return str(exc)
        check_eq("K-NA: that record makes the api profile's request valid on the docker stand", verdict(record, "kna-1"),
                 "not_applicable")
        no_code = {k: v for k, v in record.items() if k != "reason_code"}
        check_in("K-NA control: the same answer with NO reason_code (an older probe file) is refused as before",
                 "runtime not_applicable requires a verified local_source profile contract", verdict(no_code, "kna-2"))
        check_in("K-NA control: with ANOTHER reason code it is refused too",
                 "runtime not_applicable requires a verified local_source profile contract",
                 verdict({**record, "reason_code": "stand_down"}, "kna-3"))
        check_in("K-NA control: the sentence alone is not read - a different sentence with the code still passes",
                 "not_applicable", verdict({**record, "reason": "whatever"}, "kna-4"))
        check_in("K-NA control: and the code on a `mismatched` record opens nothing",
                 "must be valid matched, person_confirmed", verdict({**record, "result": "mismatched"}, "kna-5"))
        check_in("K-NA control: nor on a `unknown` record carrying the image identity (automation needs matched)",
                 "must be valid matched, person_confirmed",
                 verdict({**record, "result": "unknown", "observed_runtime_identity": "image:sha256:" + "b" * 64}, "kna-6"))
    finally:
        shutil.rmtree(work, ignore_errors=True)


IMAGE = "image:sha256:" + "b" * 64
DEPLOYED = "d" * 40
UNKNOWN_ERROR = "which build the stand runs could not be read: the image carries no label org.opencontainers.image.revision"
UNKNOWN_REMEDY = "label the image with the commit it was built from, or tell me how to read it; the way is recorded for this stand in qa-factory/records/stand-identity.json"
VOIDED_WHAT = "the stand runs another image"


def provenance_shapes(base: dict, task: str = "REQ-1") -> dict:
    """The seven columns of the draft's per-site table (t-300 N2 section 2), each shaped as the real probe writes it:
    M matched, MM a sha-rung mismatch (no error, no remedy), CM a content mismatch, PC a valid bound person's word,
    U an unknown with its error, remedy and voided word, NA1 / NA2 `not_applicable` with / without its reason code."""
    pc = {**base, "result": "person_confirmed", "observed_runtime_identity": IMAGE, "evidence_refs": ["evidence/pc.json"],
          "provenance": {"technical_verification": False, "identity_kind": "person_confirmed"},
          "person_confirmation": {"words": "yes, it is deployed", "at": "2026-10-02T11:00:00+00:00", "task": task,
                                  "kind": "deployed", "revision": base["expected_source_revision"]}}
    na = {**base, "result": "not_applicable", "observed_runtime_identity": "", "evidence_refs": [], "provenance": {},
          "reason_code": "no_changed_file"}
    return {
        "M": base,
        "MM": {**base, "result": "mismatched", "observed_runtime_identity": IMAGE,
               "provenance": {**base["provenance"], "deployed_source_revision": DEPLOYED}},
        "CM": {**base, "result": "mismatched", "observed_runtime_identity": "verified_content:abc",
               "provenance": {**base["provenance"], "source_linkage": "verified_content",
                              "deployed_source_revision": "content_mismatch"},
               "differing_files": ["src/a.vue", "src/b.vue", "src/c.vue", "src/d.vue", "src/e.vue"]},
        "PC": pc,
        "U": {**base, "result": "unknown", "observed_runtime_identity": IMAGE, "evidence_refs": [],
              "provenance": {"technical_verification": False}, "error": UNKNOWN_ERROR, "remedy": UNKNOWN_REMEDY,
              "asks_person": "how", "voided": {"what": VOIDED_WHAT, "earlier_at": "2026-10-01T10:00:00+00:00"}},
        "NA1": na, "NA2": {k: v for k, v in na.items() if k != "reason_code"}}


def n2_k1_probe_runtime_is_the_one_predicate(request: dict) -> None:
    """K-N2.1 (t-300 N2, S1): `run_suite.probe_runtime` - the run path, the post-run probe, `--mine`, the red probe and the
    manual capture - reads a probe's answer through `profile_contract.acceptable_provenance(record, ACCEPTS)`: M, PC and NA1
    are returned; MM, CM, U and NA2 raise a `ProvenanceRefused` that carries the record and says what the probe said, what
    was expected and the door - with the probe's own `error`, `remedy` and `voided.what` verbatim."""
    import inspect
    import run_suite
    from execution_request import ProvenanceRefused
    import profile_contract
    shapes = provenance_shapes(request["runtime_provenance"])
    check("K-N2.1: the strict reader has no `allow_image_identity` (Q18-B: nothing is taken on an unknown)",
          "allow_image_identity" not in inspect.signature(run_suite.probe_runtime).parameters)

    def probe(shape):
        script = ROOT / f"probe-{shape}.py"
        script.write_text("import json; print(json.dumps(" + repr(shapes[shape]) + "))", encoding="utf-8")
        spec = {"argv": [sys.executable, str(script)], "cwd": str(ROOT), "timeout_s": 30}
        try:
            return "returned", run_suite.probe_runtime(spec)
        except ProvenanceRefused as exc:
            return "refused", exc
    for shape in ("M", "PC", "NA1"):
        kind, got = probe(shape)
        check_eq(f"K-N2.1: {shape} is returned", (kind, got["result"] if kind == "returned" else str(got)),
                 ("returned", shapes[shape]["result"]))
    for shape in ("MM", "CM", "U", "NA2"):
        kind, got = probe(shape)
        check_eq(f"K-N2.1: {shape} raises ProvenanceRefused, a RequestError that carries the record",
                 (kind, isinstance(got, RequestError), getattr(got, "record", None) == shapes[shape]), ("refused", True, True))
    said = {shape: str(probe(shape)[1]) for shape in ("MM", "CM", "U", "NA2")}
    check_in("K-N2.1 MM: names the build the stand runs", DEPLOYED[:12], said["MM"])
    check_in("K-N2.1 MM: and this story's commit", "source-1", said["MM"])
    check_in("K-N2.1 MM: and the person's door (a commit can be tested: `test deployed`)", "`test deployed`", said["MM"])
    check_in("K-N2.1 CM: names the files the stand serves otherwise (three, then the count)", "src/a.vue, src/b.vue, src/c.vue and 2 more",
             said["CM"])
    check_not_in("K-N2.1 CM: offers no `test deployed` (a content mismatch has no commit to name)", "test deployed", said["CM"])
    check_not_in("K-N2.1 CM: and names no fourth file", "src/d.vue", said["CM"])
    for needle, label in ((UNKNOWN_ERROR, "error"), (UNKNOWN_REMEDY, "remedy"), (VOIDED_WHAT, "voided.what")):
        check_in(f"K-N2.1 U: the record's `{label}` is in the message verbatim", needle, said["U"])
    check_in("K-N2.1 U: the word that no longer holds says since when", "2026-10-01", said["U"])
    check_in("K-N2.1 NA2: today's local_source sentence", "runtime not_applicable requires a verified local_source", said["NA2"])
    # controls
    bare = {k: v for k, v in shapes["U"].items() if k not in ("remedy", "voided", "asks_person")}
    check_eq("K-N2.1 control: an `unknown` with an error and no remedy says the error and nothing more",
             str(ProvenanceRefused(bare)), "runtime probe returned unknown: " + UNKNOWN_ERROR)
    nothing = {k: v for k, v in shapes["U"].items() if k not in ("error", "remedy", "voided", "asks_person")}
    check_in("K-N2.1 control: no error and no remedy: the result word plus `the probe gave no reason`",
             "runtime probe returned unknown: the probe gave no reason", str(ProvenanceRefused(nothing)))
    noresult = {k: v for k, v in shapes["M"].items() if k != "result"}
    check_in("K-N2.1 control: a record with no `result` is refused with `the probe gave no reason`, never the bare "
             "`unverified provenance`", "the probe gave no reason", str(ProvenanceRefused(noresult)))
    check_not_in("K-N2.1 control: and `unverified provenance` is not the whole of it", "unverified provenance",
                 str(ProvenanceRefused(noresult)))
    check_in("K-N2.1 control: a record that does not validate says what is wrong with it", "unverified provenance: ",
             str(ProvenanceRefused({**shapes["M"], "evidence_refs": []})))
    # a moved test_deployed word comes back `mismatched` + `voided` (F1): the sentence carries both
    moved = {**shapes["MM"], "voided": {"what": "the checkout moved to commit " + "c" * 12, "earlier_at": "2026-10-02T09:00:00+00:00"}}
    check_in("K-N2.1 F1: a `mismatched` that carries a voided word appends it, the way `unknown` does",
             "The person's word of 2026-10-02 no longer holds: the checkout moved to commit " + "c" * 12, str(ProvenanceRefused(moved)))
    # F4: a probe that exits non-zero says its own reason (the real probe's exit 2: "no story is running ... Pass --task")
    script = ROOT / "probe-fail.py"
    script.write_text("import sys; sys.stderr.write('no story is running; Pass --task\\nsecond line\\n'); sys.exit(2)",
                      encoding="utf-8")
    try:
        run_suite.probe_runtime({"argv": [sys.executable, str(script)], "cwd": str(ROOT), "timeout_s": 30})
        failed = ""
    except RequestError as exc:
        failed = str(exc)
    check_eq("K-N2.1 F4: a non-zero exit quotes the first line of the probe's stderr, not the bare `runtime probe failed`",
             failed, "runtime probe failed: no story is running; Pass --task")
    script.write_text("import sys; sys.exit(3)", encoding="utf-8")
    try:
        run_suite.probe_runtime({"argv": [sys.executable, str(script)], "cwd": str(ROOT), "timeout_s": 30})
        failed = ""
    except RequestError as exc:
        failed = str(exc)
    check_in("K-N2.1 F4 control: a probe that says nothing is named as that, with its exit code",
             "exited with code 3 and printed no reason on stderr", failed)
    script.write_text("print('not json at all')", encoding="utf-8")
    try:
        run_suite.probe_runtime({"argv": [sys.executable, str(script)], "cwd": str(ROOT), "timeout_s": 30})
        failed = ""
    except RequestError as exc:
        failed = str(exc)
    check_in("K-N2.1 F4: output that is not JSON says what it printed", "did not return JSON: it printed: not json at all", failed)
    # the spellings outside the five, and an unknown token (E11)
    check_eq("K-N2.1 E11: `MATCHED` is not `matched`, `Person_Confirmed` is not `person_confirmed`",
             (profile_contract.acceptable_provenance({**shapes["M"], "result": "MATCHED"}, profile_contract.ACCEPTS),
              profile_contract.acceptable_provenance({**shapes["PC"], "result": "Person_Confirmed"}, profile_contract.ACCEPTS)),
             (False, False))
    try:
        profile_contract.acceptable_provenance(shapes["M"], ("matched", "unknown"))
        raised = False
    except ValueError:
        raised = True
    check("K-N2.1 E11: an unknown token is a programming error (ValueError), never a silent refusal", raised)


def n2_k2_validate_request_takes_a_word_bound_to_the_story(request: dict) -> None:
    """K-N2.2 (S4): a request that stands on the PERSON'S WORD for this story is valid; every way the word fails to say what
    it was given for is refused (E2, E11), and so is a word on a request that skips the probe (X7) or one given for another
    story (X5). The local_source `not_applicable` rule stays (X3; tested in t238_w4 and K-NA above)."""
    shapes = provenance_shapes(request["runtime_provenance"])
    pc = shapes["PC"]

    def verdict(record, key, **over):
        try:
            return validate_request({**request, "idempotency_key": key, "runtime_provenance": record, **over},
                                    ROOT)["runtime_provenance"]["result"]
        except RequestError as exc:
            return str(exc)

    def edited(**fields):
        confirmation = {**pc["person_confirmation"], **{k: v for k, v in fields.items() if k in pc["person_confirmation"]}}
        out = {**pc, "person_confirmation": confirmation}
        for key, value in fields.items():
            if key not in pc["person_confirmation"]:
                out[key] = value
        return out
    check_eq("K-N2.2: a person's word, bound to this story and to what it says, is accepted", verdict(pc, "n2k2-1"),
             "person_confirmed")
    check_in("K-N2.2 X7: the same word on a request with `runtime_required: false` is refused: nothing re-reads the stand",
             "stands only on a run whose stand the probe re-reads at launch", verdict(pc, "n2k2-2", runtime_required=False))
    other = verdict(edited(task="OTHER-9"), "n2k2-3")
    check_in("K-N2.2 X5: a word given for ANOTHER story is refused, naming both", "was given for story OTHER-9, and this is story REQ-1", other)
    refused = "must be valid matched, person_confirmed"
    for label, record in (
            ("empty words", edited(words="")),
            ("technical_verification true", {**pc, "provenance": {**pc["provenance"], "technical_verification": True}}),
            ("no revision", {**edited(), "person_confirmation": {k: v for k, v in pc["person_confirmation"].items() if k != "revision"}}),
            ("no kind", {**edited(), "person_confirmation": {k: v for k, v in pc["person_confirmation"].items() if k != "kind"}}),
            ("no task", {**edited(), "person_confirmation": {k: v for k, v in pc["person_confirmation"].items() if k != "task"}}),
            ("a `deployed` word for another commit", edited(revision="elsewhere-1")),
            ("a kind outside the two", edited(kind="withdrawn")),
            ("an empty identity", {**pc, "observed_runtime_identity": ""}),
            ("tested_build that is not the revision", {**pc, "tested_build": "x" * 40}),
            ("`MATCHED`", {**shapes["M"], "result": "MATCHED"}),
            ("`Person_Confirmed`", {**pc, "result": "Person_Confirmed"}),
            ("matched wearing identity_kind person_confirmed",
             {**shapes["M"], "provenance": {**shapes["M"]["provenance"], "identity_kind": "person_confirmed"}})):
        check_in(f"K-N2.2 E11: {label} is refused", refused, verdict(record, "n2k2-x-" + label[:8]))
    test_deployed = {**pc, "tested_build": DEPLOYED, "provenance": {**pc["provenance"], "deployed_source_revision": DEPLOYED},
                     "person_confirmation": {**pc["person_confirmation"], "kind": "test_deployed", "revision": DEPLOYED,
                                             "story_revision": pc["expected_source_revision"]}}
    check_eq("K-N2.2: a `test_deployed` word (revision D, story_revision this story, tested_build D) is accepted",
             verdict(test_deployed, "n2k2-td"), "person_confirmed")
    same = {**test_deployed, "tested_build": pc["expected_source_revision"],
            "provenance": {**pc["provenance"], "deployed_source_revision": pc["expected_source_revision"]},
            "person_confirmation": {**test_deployed["person_confirmation"], "revision": pc["expected_source_revision"]}}
    check_in("K-N2.2 F5 (t-395): a `test_deployed` word whose build under test IS this story's commit is refused: it says `another "
             "build` and names the same one", "names the build under test and this story's commit as the SAME build",
             verdict(same, "n2k2-same"))
    # F6: the X7 sentence is read from the refusals block (a changed block value changes the sentence)
    import profile_contract as P
    import tempfile
    block = Path(tempfile.mkdtemp(prefix="qa-f6-x7-")) / "methods.json"
    block.write_text(json.dumps({"refusals": {"person_runtime_off": "BLOCK[person_runtime_off]"}}), encoding="utf-8")
    held, P.REFUSAL_DATA = P.REFUSAL_DATA, block
    try:
        changed = verdict(pc, "n2k2-x7", runtime_required=False)
    finally:
        P.REFUSAL_DATA = held
        shutil.rmtree(block.parent, ignore_errors=True)
    check_in("K-N2.2 F6: the X7 sentence is read from the refusals block", "BLOCK[person_runtime_off]", changed)
    check_in("K-N2.2 control: the same word with no tested_build is refused (the build under test must be said)", refused,
             verdict({k: v for k, v in test_deployed.items() if k != "tested_build"}, "n2k2-td2"))
    check_in("K-N2.2 control: and with another story_revision", refused,
             verdict({**test_deployed, "person_confirmation": {**test_deployed["person_confirmation"], "story_revision": "elsewhere-1"}}, "n2k2-td3"))
    check_eq("K-N2.2 control: a `matched` record is accepted as it always was", verdict(shapes["M"], "n2k2-m"), "matched")
    check_in("K-N2.2 control: an `unknown` is refused, whatever it names", refused, verdict(shapes["U"], "n2k2-u"))


def n2_k3_the_fingerprint_of_a_word_is_not_the_fingerprint_of_a_reading(request: dict) -> None:
    """K-N2.3 (S7): `execution_fingerprint.build` fingerprints a run that stands on the word, and an `unknown`/`mismatched`
    one still raises. A `matched` and a person's word over the SAME image give different `runtime_sha`: a green under the
    word is never reused as a `matched` result (FR-18). Bare `not_applicable` stays fingerprinted (X3)."""
    from execution_fingerprint import build
    shapes = provenance_shapes(request["runtime_provenance"])

    def fingerprint(record):
        return build({"source_revision": "s1", "test_files": [str(ROOT / "dummy_runner.py")],
                      "config_files": [str(ROOT / "qa-factory" / "config.json")], "dependency_files": [],
                      "runtime_provenance": record, "profile_id": "api",
                      "project_config": str(ROOT / "qa-factory" / "config.json")})
    reading = {**shapes["M"], "observed_runtime_identity": IMAGE}
    try:
        word, why = fingerprint(shapes["PC"]), ""
    except ValueError as exc:      # a mutant that refuses the word must be a FAIL line, not a crash
        word, why = None, str(exc)
    check("K-N2.3: a person's word is fingerprinted", word is not None and bool(word["input_fingerprint"]), why)
    if word is None:
        return
    check("K-N2.3: and its runtime_sha differs from a `matched` over the same image digest",
          word["fingerprint_components"]["runtime_sha"] != fingerprint(reading)["fingerprint_components"]["runtime_sha"])
    check_eq("K-N2.3 control: two `matched` readings of that image fingerprint alike (so the difference is the word's)",
             fingerprint(reading)["fingerprint_components"]["runtime_sha"],
             fingerprint({**reading, "timestamp": "2026-10-03T09:00:00Z"})["fingerprint_components"]["runtime_sha"])
    for shape in ("U", "MM", "CM"):
        try:
            fingerprint(shapes[shape])
            raised = ""
        except ValueError as exc:
            raised = str(exc)
        check_in(f"K-N2.3: {shape} raises, and says why", "runtime provenance is unverified/mismatched: runtime probe returned", raised)
    # F5 (t-395): the collision the critic measured - a `matched` with no deployed revision (a project's own probe) and a person's
    # `deployed` word on ONE image used to share runtime_sha; the word now carries a key of its own
    bare_reading = {**shapes["M"], "observed_runtime_identity": IMAGE,
                    "provenance": {"technical_verification": True, "source_linkage": "exact"}}
    check("K-N2.3 F5: a `matched` reading with no deployed revision and the person's word on the SAME image: different runtime_sha",
          fingerprint(bare_reading)["fingerprint_components"]["runtime_sha"] != word["fingerprint_components"]["runtime_sha"])
    # F5: NO matched fingerprint changes: the exact bytes of the pre-t-395 reading, independent of the code under test, and a pin
    pinned = fingerprint(reading)["fingerprint_components"]["runtime_sha"]
    from event_store import content_hash
    check_eq("K-N2.3 F5: a `matched` runtime_sha is the hash of the four fields + deployed revision, as before (computed apart)",
             pinned, content_hash({"profile_id": "api", "environment_id": "qa", "expected_source_revision": "source-1",
                                   "observed_runtime_identity": IMAGE, "deployed_source_revision": "source-1"}))
    check_eq("K-N2.3 F5: ... and it is the literal the code produced before the key existed (a pin)", pinned,
             "ef2306f773e2f5b2b682c00a3d373c4c74c02b8bdf03921cb740a04d9fda9b2c")
    check("K-N2.3 F5: the word's own fingerprint is not that one", word["fingerprint_components"]["runtime_sha"] != pinned)
    check("K-N2.3: bare `not_applicable` (no reason code) is still fingerprinted (the local_source request)",
          bool(fingerprint(shapes["NA2"])["input_fingerprint"]))
    check("K-N2.3: and the coded one", bool(fingerprint(shapes["NA1"])["input_fingerprint"]))
    # FB-8: a word that accepted these exact bytes is another run when the bytes it accepted are other (kind content_accepted only)
    accepted = {"a": "a" * 64, "b": "b" * 64}

    def content_word(content):
        said = {**shapes["PC"]["person_confirmation"], "kind": "content_accepted", "content": content}
        return {**shapes["PC"], "person_confirmation": said, "content_identity": content, "accepted_files": ["Makefile"]}
    shas = {key: fingerprint(content_word(value))["fingerprint_components"]["runtime_sha"] for key, value in accepted.items()}
    check("FB8 (R15): two content words over other accepted bytes: different runtime_sha (fb8_runtime_sha_differs_per_accepted_content)",
          shas["a"] != shas["b"] and shas["a"] != word["fingerprint_components"]["runtime_sha"])
    check_eq("FB8 (R15): the same accepted bytes fingerprint alike",
             fingerprint(content_word(accepted["a"]))["fingerprint_components"]["runtime_sha"], shas["a"])
    check_eq("FB8 (R15): a `matched` runtime_sha is unchanged by the key (fb8_matched_runtime_sha_unchanged)",
             fingerprint(reading)["fingerprint_components"]["runtime_sha"], pinned)


def n2_k11_a_word_is_never_equivalence_verified(request: dict) -> None:
    """K-N2.11 (S3, E10): the run block marks `equivalence_verified` only for runtime AND data seed `matched` with evidence. A
    run that stands on the person's word is accepted at launch and is NEVER reported as the verified equivalent (FR-58)."""
    import run_suite
    shapes = provenance_shapes(request["runtime_provenance"])
    seed = {"result": "matched", "evidence_refs": ["seed/1"]}

    def block(record):
        found = run_suite.build_run_block(
            {"purpose": "initial", "selected_instance_ids": ["case-0"], "profile_id": "api", "dispatch_id": "d1",
             "instance_contracts": {"case-0": {"report_test_id": "x::case-0"}}, "runtime_provenance": record,
             "execution": {"data_seed_contract": seed}},
            {"execution_status": "passed", "results": [{"test_id": "x::case-0", "status": "passed"}]}, "attempt-1")
        return found["equivalence_verified"], found["results"][0]["equivalence_verified"]
    check_eq("K-N2.11: runtime `matched` + seed matched: verified (the control)", block(shapes["M"]), (True, True))
    check_eq("K-N2.11: runtime `person_confirmed` + seed matched: NOT verified", block(shapes["PC"]), (False, False))


def n2_f1_b220_the_report_placeholder_may_sit_inside_one_token(request: dict) -> None:
    """F1-b220 (the B-220 node, critic t-380 F1): S5 accepts `{report_path}` EMBEDDED in one argv token, the way the gate's
    reporter probe does, and launches with the path substituted inside it. Exactly one token carries it; two are refused
    naming both; none is refused as before; a whole-token `{report_path}` (every other test here) still works."""
    runner = ROOT / "embedded_runner.py"
    runner.write_text(
        "import sys\nfrom pathlib import Path\n"
        "argv = sys.argv[1:]\n"
        "Path('argv-seen-' + argv[0].split('=')[0].replace(';', '_') + '.txt').write_text(chr(10).join(argv))\n"
        "report = Path(argv[0].split('=', 1)[1])\nreport.parent.mkdir(parents=True, exist_ok=True)\n"
        "cases = ''.join(f'<testcase classname=\"x\" name=\"{x}\"/>' for x in argv[1:])\n"
        "report.write_text(f'<testsuite tests=\"{len(argv) - 1}\" failures=\"0\" errors=\"0\" skipped=\"0\">{cases}</testsuite>')\n",
        encoding="utf-8")

    def shaped(key, token, reporter="junit-xml", extra=()):
        r = base_request(key)
        r["input_fingerprint"] = "sha256:" + key
        r["selected_instance_ids"] = ["case-0", "case-1"]
        r["command"] = {**r["command"], "argv": [sys.executable, str(runner), token, *extra], "reporter": reporter,
                        "selector_args": {i: [i] for i in ("case-0", "case-1")}}
        if reporter == "trx":
            for contract in r["instance_contracts"].values():
                contract["report_id_source"] = "catalog"
        return r

    def refusal(r):
        try:
            validate_request(r, ROOT)
            return ""
        except RequestError as exc:
            return str(exc)
    check_eq("F1-b220: a `trx;LogFileName={report_path}` token is a valid command (trx reporter)",
             refusal(shaped("b220-trx", "trx;LogFileName={report_path}", "trx")), "")
    check_eq("F1-b220: so is `--report={report_path}` (junit-xml)", refusal(shaped("b220-j", "--report={report_path}")), "")
    check_eq("F1-b220 control: the whole-token form is still valid", refusal(shaped("b220-w", "{report_path}")), "")
    two = refusal(shaped("b220-2", "--report={report_path}", extra=("--also={report_path}",)))
    check_in("F1-b220: two tokens carrying the placeholder are refused", "exactly one token", two)
    check_in("F1-b220: naming both", "'--report={report_path}', '--also={report_path}'", two)
    check_in("F1-b220 control: a placeholder nowhere (junit-xml) is refused as before",
             "external reporter command.argv must contain an explicit {report_path} token", refusal(shaped("b220-0", "--report=x.xml")))
    # launched: the runner receives the path INSIDE its token, never the placeholder, and its report is read
    done = invoke(shaped("b220-run", "--report={report_path}"))
    check_eq("F1-b220: an embedded junit-xml token launches and the run passes", (done.returncode, '"execution_status": "passed"' in done.stdout),
             (0, True))
    seen = (ROOT / "argv-seen---report.txt").read_text(encoding="utf-8").splitlines()
    check("F1-b220: the runner got the path substituted INSIDE the token, under this job's own evidence folder",
          seen[0].startswith("--report=") and "{report_path}" not in seen[0] and seen[0].endswith("report.junit.xml")
          and "evidence" in seen[0].replace("\\", "/") and "/runs/" in seen[0].replace("\\", "/"), seen[0])
    check_eq("F1-b220: and the selected instances follow, untouched", seen[1:], ["case-0", "case-1"])
    done = invoke(shaped("b220-trx-run", "trx;LogFileName={report_path}", "trx"))
    seen = (ROOT / "argv-seen-trx_LogFileName.txt").read_text(encoding="utf-8").splitlines()
    check("F1-b220: the trx token is launched the same way (`trx;LogFileName=<path>.trx`)",
          seen[0].startswith("trx;LogFileName=") and "{report_path}" not in seen[0] and seen[0].endswith("report.trx"), seen[0])


REHEARSAL_PROBE = r'''
import json
import sys
from pathlib import Path
here = Path(__file__).parent
argv = sys.argv[1:]
with (here / "argv.log").open("a", encoding="utf-8") as log:
    log.write(json.dumps(argv) + "\n")
if (here / "fail.txt").exists():
    sys.stderr.write((here / "fail.txt").read_text(encoding="utf-8"))
    sys.exit(1)
mode = (here / "mode.txt").read_text(encoding="utf-8").strip() if (here / "mode.txt").exists() else "matched"
rehearsal = "--no-evidence" in argv
record = {"profile_id": "api", "timestamp": "2026-10-02T12:00:00+00:00", "environment_id": "localhost",
          "expected_source_revision": "source-1", "observed_runtime_identity": "build-1",
          "evidence_refs": [] if rehearsal else ["probe"], "result": "matched",
          "provenance": {"technical_verification": True, "source_linkage": "exact",
                         "deployed_source_revision": "source-1"}}
if mode == "person_confirmed":
    # the facts the word must carry to count (t-300 N2 X6): the kind, the story, the revision - equal to the expected one
    record.update(result="person_confirmed", evidence_refs=[],
                  provenance={"technical_verification": False, "identity_kind": "person_confirmed"},
                  person_confirmation={"words": "yes", "at": "2026-10-02T11:00:00+00:00", "task": "K33-1",
                                       "kind": "deployed", "revision": "source-1"})
if mode == "unknown":
    record.update(result="unknown", evidence_refs=[], provenance={"technical_verification": False},
                  error="which build the stand runs could not be read", remedy="tell me how to read it", asks_person="how")
if mode == "na1":
    record.update(result="not_applicable", evidence_refs=[], observed_runtime_identity="", provenance={},
                  reason_code="no_changed_file")
if rehearsal and mode != "unmarked":
    record["observed_without_evidence"] = True
print(json.dumps(record))
'''


def hf3_6a_the_s6_close_context() -> None:
    """HF3-6 part 6a, A-K1..A-K7: `s6_close_dispatch` allows the S6 close context exactly where the controller would take
    the S6 code-only receipt (one predicate, `controller.code_close_conflicts`), refuses before anything is read or
    written otherwise, and `build_mine_request(s6_close=True)` builds only a red probe, from a fresh reading of the state."""
    import execution_request as er
    from harness import use_project
    work = Path(tempfile.mkdtemp(prefix="qa-hf36a-")).resolve()
    saved = os.environ.get("CLAUDE_PROJECT_DIR")
    try:
        (work / "fake").mkdir()
        (work / "fake" / "pytest").write_text("# the runner is never started here\n", encoding="utf-8")
        (work / "tests").mkdir()
        (work / "tests" / "test_b.py").write_text("def test_alpha():\n    assert 1 == 1\n", encoding="utf-8")
        provenance = {"profile_id": "api", "timestamp": "2026-10-02T12:00:00+00:00", "environment_id": "localhost",
                      "expected_source_revision": "source-1", "observed_runtime_identity": "build-1",
                      "evidence_refs": ["probe"], "result": "matched",
                      "provenance": {"technical_verification": True, "source_linkage": "exact",
                                     "deployed_source_revision": "source-1"}}
        cfg = {"profiles": [{"profile_id": "api", "selected": True, "roots": {"test": "tests"},
                             "commands": {"one_test": {"argv": [sys.executable, str(work / "fake" / "pytest"),
                                                                "<test-file>"], "cwd": "."}},
                             "reporter": {"kind": "pytest"}, "selectors": {"verified": True}}],
               "execution": {"runtime_probes": {"api": {"argv": [sys.executable, "-c", "pass"], "cwd": ".",
                                                        "timeout_s": 30}}}}
        (work / "qa-factory" / "state").mkdir(parents=True)
        (work / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        task = work / "qa-factory" / "artifacts" / "HF36-1"
        done = {f"S{i}": {"status": "completed"} for i in range(6)}

        def put(name: str, value) -> None:
            (task / name).parent.mkdir(parents=True, exist_ok=True)
            (task / name).write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")

        def state(**over) -> dict:
            base = {"schema_version": "2", "revision": 7, "source_revision": "source-1", "scope": ["TC-002", "TC-003"],
                    "dispatches": {"S5-qa-code-critic-1": {"id": "S5-qa-code-critic-1", "stage": "S5",
                                                           "role": "qa-code-critic", "status": "accepted",
                                                           "scope": ["TC-002"], "budget": {"requests": 50}}},
                    "stages": dict(done)}
            base.update(over)
            return base

        put("work/automation-manifest.json",
            {"tests": [{"case": "TC-002", "file": "tests/test_b.py", "selector": "test_alpha"}]})
        put("pipeline.json", {"stages": {"S5": {"status": "done"}}})
        use_project(work)

        def tree() -> dict:
            return {p.relative_to(work).as_posix(): file_hash(p) for p in sorted(work.rglob("*")) if p.is_file()}

        def refusal(cases=("TC-002",)) -> str:
            before = tree()
            try:
                er.s6_close_dispatch(task, list(cases))
            except er.MineRefusal as exc:
                check_eq("A-K5/A-K8 a refused context changed no byte of the project", tree(), before)
                return str(exc)
            return ""

        # A-K1: the context exists where the controller would take the S6 receipt
        put("state/controller.json", state())
        check_eq("A-K1 S0..S5 completed, S6 pending, nothing running: the stand-in dispatch, revision 7",
                 er.s6_close_dispatch(task, ["TC-002"]),
                 {"id": "S6-close-r7", "stage": "S6", "scope": ["TC-002", "TC-003"], "budget": {}})
        put("state/controller.json", state(stages={**done, "S6": {"status": "pending"}}))
        check_eq("A-K1 ...and a pending S6 entry is still the context", er.s6_close_dispatch(task, ["TC-003"])["id"],
                 "S6-close-r7")
        put("state/controller.json", state(revision="7/../x"))
        check_eq("A-K1 the id keeps to [A-Za-z0-9-] whatever the revision holds",
                 er.s6_close_dispatch(task, ["TC-002"])["id"], "S6-close-r7----x")
        # A-K2: a running dispatch of ANY stage refuses, and the refusal names every id and the door
        runner = {"id": "S6-qa-runner-1", "stage": "S6", "role": "qa-runner", "status": "running", "scope": ["TC-002"]}
        critic = {"id": "S5-qa-code-critic-2", "stage": "S5", "role": "qa-code-critic", "status": "running"}
        retry = {"id": "S5-qa-code-critic-3", "stage": "S5", "role": "qa-code-critic", "status": "running",
                 "parent_retry": "S5-qa-code-critic-2"}
        for label, rows in (("an S6 runner", [runner]), ("an S5 critic", [critic]), ("a retry with a parent", [retry]),
                            ("two", [runner, critic])):
            put("state/controller.json", state(dispatches={r["id"]: r for r in rows}))
            text = refusal()
            check(f"A-K2 {label} running: the refusal names every id and `--dispatch`",   # every holder's door (t-2183 F2): none by position
                  all(r["id"] in text and f"`--dispatch {r['id']}`" in text for r in rows), text)
        # A-K3: S6 closed, by code (the receipt) or by its runner
        put("state/controller.json", state(stages={**done, "S6": {"status": "completed", "code_only": True,
                                                                  "receipt_id": "S6-code-only-1"}}))
        text = refusal()
        check("A-K3 S6 closed by code: names the receipt and the `rework` door",
              "S6-code-only-1" in text and "--operation rework --stage S6" in text, text)
        put("state/controller.json", state(stages={**done, "S6": {"status": "completed"}}))
        check_in("A-K3 S6 closed by its runner: says so", "by its runner", refusal())
        # a sentence of the predicate this reader does not know is still a refusal, in the controller's own words
        import controller as controller_module
        known = controller_module.code_close_conflicts
        controller_module.code_close_conflicts = lambda s, st, v=None: [(ValueError, "a new kind of conflict")]   # TR4-7 passes `verdicts`
        try:
            put("state/controller.json", state())
            check_in("edge: an unknown conflict is refused with its own sentence", "(a new kind of conflict)", refusal())
        finally:
            controller_module.code_close_conflicts = known
        # A-K4: S6 has not started
        for label, stages in (("S5 running", {**done, "S5": {"status": "running"}}),
                              ("S5 pending", {**done, "S5": {"status": "pending"}}),
                              ("S5 not recorded", {k: v for k, v in done.items() if k != "S5"})):
            put("state/controller.json", state(stages=stages))
            check_in(f"A-K4 {label}: S6 has not started, and which stage is behind", "S6 has not started: S5 is ", refusal())
        no_stages = state()
        del no_stages["stages"]
        put("state/controller.json", no_stages)
        check_in("A-K4 no `stages` at all is not read as closed", "S6 has not started: S0 is not recorded", refusal())
        # a story closed by gate B (not reopened) is not a context; reopened by a person's word it is again
        put("state/controller.json", state())
        put("pipeline.json", {"stages": {"S5": {"status": "done"}}, "closed_at": "2026-10-27T10:00:00"})
        check_in("edge: a closed story is refused, in the closed words", "S6 is already closed (the story is closed)",
                 refusal())
        put("pipeline.json", {"stages": {"S5": {"status": "done"}}, "closed_at": "2026-10-27T10:00:00",
                              "reopened_at": "2026-10-27T11:00:00"})
        check_eq("edge: a story reopened by a person's word is a context again",
                 er.s6_close_dispatch(task, ["TC-002"])["id"], "S6-close-r7")
        put("pipeline.json", {"stages": {"S5": {"status": "done"}}})
        # A-K5: a state that cannot be read; the project is byte for byte the same after each
        for label, content in (("not JSON", "{ not json"), ("a list", "[1, 2]")):
            put("state/controller.json", content)
            text = refusal()
            check(f"A-K5 state/controller.json is {label}: refused, with the `recover` door",
                  "cannot be read" in text and "controller.py --task HF36-1 --operation recover" in text, text)
        (task / "state" / "controller.json").unlink()
        check_in("A-K5 no state/controller.json: refused, with the `recover` door", "--operation recover", refusal())
        # A-K6: a case outside the scope, an empty scope, no `scope` key
        put("state/controller.json", state())
        check_in("A-K6 a case outside the story's scope", "TC-009 is not in the story's approved scope",
                 refusal(("TC-002", "TC-009")))
        for label, scope in (("an empty scope", []), ("a scope that is not a list", "TC-002")):
            put("state/controller.json", state(scope=scope))
            check_in(f"A-K6 {label} is not read as 'everything'", "is not in the story's approved scope", refusal())
        # F-5: the refusals of the scope and of the prior stage name a door their receiver can use
        put("state/controller.json", state())
        check_in("F-5 scope: the case is probed under the dispatch that holds it", "`--dispatch <id>`",
                 refusal(("TC-009",)))
        put("state/controller.json", state(stages={**done, "S5": {"status": "running"}}))
        text = refusal()
        check("F-5 prior: close the stage behind first, or a probe under a dispatch",
              "Close S5 first" in text and "`--dispatch <id>`" in text, text)
        # F-1: the DETAILS of a refusal come from the predicate's facts, not from a second scan of the state
        import controller as controller_module
        known_facts = controller_module.code_close_facts
        try:
            put("state/controller.json", state())
            controller_module.code_close_facts = lambda s, st, v=None: {"running": ["zz-9"], "behind": None, "completed": False}   # t-2113: the caller passes `verdicts` since TR1-9
            text = refusal()
            check("F-1 a running dispatch the facts name (and the state does not) is named, with its door",
                  "(zz-9)" in text and "`--dispatch zz-9`" in text, text)
            controller_module.code_close_facts = lambda s, st, v=None: {"running": [], "behind": ("S3", "blocked"), "completed": False}
            check_in("F-1 the stage behind and its status come from the facts", "S6 has not started: S3 is blocked", refusal())
            controller_module.code_close_facts = lambda s, st, v=None: {"running": [], "behind": ("S3", None), "completed": False}
            check_in("F-1 ...and a status the facts do not know is `not recorded`", "S3 is not recorded", refusal())
            controller_module.code_close_facts = lambda s, st, v=None: {"running": [], "behind": None, "completed": True}
            check_in("F-1 completed from the facts", "S6 is already closed (by its runner)", refusal())
        finally:
            controller_module.code_close_facts = known_facts
        # F-3: rows of the wrong shape refuse, with the same words, never a traceback
        put("state/controller.json", state(dispatches={"d1": "accepted"}))
        text = refusal()
        check("F-3 a dispatch row that is not a dict is read as running, named by its key",
              "(d1)" in text and "`--dispatch d1`" in text, text)
        put("state/controller.json", state(dispatches={"d2": {"id": "d2-x", "stage": "S5"}}))
        check_in("F-3 a dispatch row with no status is read as running", "`--dispatch d2-x`", refusal())
        put("state/controller.json", state(stages={**done, "S3": "completed"}))
        check_in("F-3 a stage entry that is not a dict is an incomplete stage", "S6 has not started: S3 is not recorded",
                 refusal())
        put("state/controller.json", state(stages={**done, "S6": "completed"}))
        check_in("F-3 the stage's own entry that is not a dict is not read as 'not closed'", "S6 is already closed",
                 refusal())
        put("state/controller.json", state())
        for label, content in (("not JSON", "{ nope"), ("a list", "[]")):
            put("pipeline.json", content)
            text = refusal()
            check(f"F-3 pipeline.json is {label}: whether the story is closed is unknown - refused, with the `recover` door",
                  "pipeline.json" in text and "controller.py --task HF36-1 --operation recover" in text, text)
        (task / "pipeline.json").unlink()
        check_in("F-3 no pipeline.json: refused too", "pipeline.json", refusal())
        put("pipeline.json", {"stages": {"S5": {"status": "done"}}})
        check_eq("control: pipeline.json readable again, the context is back", er.s6_close_dispatch(task, ["TC-002"])["id"],
                 "S6-close-r7")
        # A-K7: build_mine_request(s6_close=True)
        put("state/controller.json", state())
        args = dict(cfg=cfg, task="HF36-1", node_ids=["tests/test_b.py::test_alpha"], again=True, reason="probe",
                    probe=lambda spec: provenance, cwd=str(work))

        def refused(**over) -> str:
            before = tree()
            try:
                er.build_mine_request(work, ["TC-002"], **{**args, **over})
            except er.MineRefusal as exc:
                check_eq("A-K7 a refused call changed no byte of the project", tree(), before)
                return str(exc)
            return ""

        check_in("A-K7 purpose initial is refused: the close context builds only a red probe",
                 "builds only a red probe", refused(purpose="initial", s6_close=True))
        check_in("A-K7 no purpose is refused too", "builds only a red probe", refused(s6_close=True))
        text = refused(purpose="red_probe", s6_close=True, dispatch_id="S5-qa-code-critic-1")
        check("A-K7 a dispatch id with the close context is the caller's mistake, naming both",
              "dispatch_id" in text and "evidence_only" in text, text)
        check_in("A-K7 so is evidence_only with it", "excludes", refused(purpose="red_probe", s6_close=True,
                                                                          evidence_only=True))
        check_in("A-K7 a task is required", "name its task id", refused(purpose="red_probe", s6_close=True, task=""))
        request, _notes, _reusable, _verified = er.build_mine_request(work, ["TC-002"], purpose="red_probe",
                                                                       s6_close=True, **args)
        check_eq("A-K7 red_probe: the request carries the context's id, the revision of the file, one request left",
                 (request["dispatch_id"], request["revision"], request["remaining_budget"], request["purpose"]),
                 ("S6-close-r7", "7", 1, "red_probe"))
        put("state/controller.json", state(revision=9))
        request, _notes, _reusable, _verified = er.build_mine_request(work, ["TC-002"], purpose="red_probe",
                                                                       s6_close=True, **args)
        check_eq("A-K7 the id is read afresh at each call (never taken from the caller)",
                 (request["dispatch_id"], request["revision"]), ("S6-close-r9", "9"))
        # F-2: the context's id and the request's revision come from ONE reading of state/controller.json
        reads, real_read = [], er._read_json
        er._read_json = lambda p, *a, **k: (reads.append(Path(p).name), real_read(p, *a, **k))[1]
        try:
            er.build_mine_request(work, ["TC-002"], purpose="red_probe", s6_close=True, **args)
        finally:
            er._read_json = real_read
        check_eq("F-2 the build reads state/controller.json once", reads.count("controller.json"), 1)
        put("state/controller.json", state(dispatches={runner["id"]: runner}))
        check_in("A-K7 a running dispatch refuses the build as it refuses the gate", "a dispatch is open",
                 refused(purpose="red_probe", s6_close=True))
        # control: the ordinary call (a running dispatch, no close context) is as before
        put("state/controller.json", state(dispatches={runner["id"]: runner}))
        request, _notes, _reusable, _verified = er.build_mine_request(work, ["TC-002"], purpose="red_probe", **args)
        check_eq("A-K7 control: without s6_close the running dispatch is the one used",
                 request["dispatch_id"], "S6-qa-runner-1")
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved
        shutil.rmtree(work, ignore_errors=True)


def t300_k33_a_freshness_read_is_a_rehearsal_end_to_end() -> None:
    """K33 (t-300 §0b B1), END TO END through the production callable: `fresh_evidence(..., probe=run_suite.probe_runtime)`
    is what the driver's `s6_freshness` calls. The probe script's basename is `runtime_probe.py`, so it is OURS: it is
    run with `--no-evidence` (and this story's `--task-root`), prints a `matched` that names no evidence file and says so,
    and the read must still decide (`observed: True`) - the strict reader would raise on that record and S6 would lose
    t-043 D1 for ever. The strict reader itself is NOT loosened (the two pins)."""
    import hooklib
    import run_suite
    import execution_request as er
    from profile_contract import validate_runtime_provenance
    from harness import use_project
    work = Path(tempfile.mkdtemp(prefix="qa-k33-")).resolve()
    saved = os.environ.get("CLAUDE_PROJECT_DIR")
    try:
        (work / "fake").mkdir()
        (work / "fake" / "pytest").write_text("# the runner is never started here\n", encoding="utf-8")
        probe_dir = work / "probe"
        probe_dir.mkdir()
        (probe_dir / "runtime_probe.py").write_text(REHEARSAL_PROBE, encoding="utf-8")
        (work / "tests").mkdir()
        (work / "tests" / "conftest.py").write_text("# fixtures\n", encoding="utf-8")
        (work / "tests" / "test_b.py").write_text("def test_alpha():\n    assert 1 == 1\n", encoding="utf-8")
        spec = {"argv": [sys.executable, str(probe_dir / "runtime_probe.py"), "--profile", "api"], "cwd": ".", "timeout_s": 30}
        cfg = {"profiles": [{"profile_id": "api", "selected": True, "roots": {"test": "tests"},
                             "commands": {"one_test": {"argv": [sys.executable, str(work / "fake" / "pytest"), "<test-file>"], "cwd": "."}},
                             "reporter": {"kind": "pytest"}, "selectors": {"verified": True}}],
               "execution": {"runtime_probes": {"api": spec}}}
        (work / "qa-factory" / "state").mkdir(parents=True)
        (work / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        task = work / "qa-factory" / "artifacts" / "K33-1"
        for name, value in (("work/automation-manifest.json",
                             {"tests": [{"case": "TC-002", "file": "tests/test_b.py", "selector": "test_alpha"}]}),
                            ("state/controller.json",
                             {"schema_version": "2", "revision": "1", "source_revision": "source-1",
                              "dispatches": {"S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator",
                                                                   "status": "running", "scope": ["TC-002"], "budget": {"requests": 150}}}}),
                            ("pipeline.json", {"stages": {"S5": {"status": "running"}}})):
            (task / name).parent.mkdir(parents=True, exist_ok=True)
            (task / name).write_text(json.dumps(value), encoding="utf-8")
        use_project(work)

        def calls() -> list:
            path = probe_dir / "argv.log"
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

        found = er.fresh_evidence(work, "K33-1", ["TC-002"], cfg=cfg, probe=run_suite.probe_runtime)
        check_eq("K33: the read DECIDES: observed True, the one test is `missing` (nothing ran it)",
                 (found["observed"], sorted({v["state"] for v in found["instances"].values()})), (True, ["missing"]))
        argv = calls()[-1]
        check_eq("K33: the probe was run with --no-evidence LAST (nothing written on a read)", argv[-1], "--no-evidence")
        check_eq("K33: and with this story's folder", argv[argv.index("--task-root") + 1], str(task))
        check_eq("K33: no evidence file was written by the read", (task / "evidence").exists(), False)
        # PIN 1: the strict reader is unchanged - a `matched` printed without evidence raises there
        before = len(calls())
        try:
            run_suite.probe_runtime({**spec, "cwd": str(work), "argv": spec["argv"] + ["--no-evidence"]})
            raised = ""
        except RequestError as exc:
            raised = str(exc)
        check_in("K33 PIN 1: `run_suite.probe_runtime` still raises on a matched + marker + empty evidence", "unverified provenance", raised)
        # PIN 2: and so does the validator
        printed = json.loads(__import__("subprocess").run(spec["argv"] + ["--no-evidence"], capture_output=True, text=True).stdout)
        checked = validate_runtime_provenance(printed)
        check_eq("K33 PIN 2: `validate_runtime_provenance` says that same record is INVALID, marker and all (strict)",
                 (printed["observed_without_evidence"], printed["evidence_refs"], checked["valid"], checked["result"]),
                 (True, [], False, "unknown"))
        # CONTROL: a real run (not evidence_only) passes no flag, and the request does not store a rehearsal argv
        request, _notes, _reusable, _verified = er.build_mine_request(work, ["TC-002"], cfg=cfg, task="K33-1",
                                                                       probe=run_suite.probe_runtime)
        real = calls()[-1]
        check_eq("K33 CONTROL: `build_mine_request(evidence_only=False)` runs the probe with NO rehearsal flag", "--no-evidence" in real, False)
        check_eq("K33: and the request it builds stores the project's own argv as its runtime_probe, never a rehearsal one",
                 ("--no-evidence" in request["runtime_probe"]["argv"], "--task-root" in request["runtime_probe"]["argv"],
                  request["runtime_probe"]["argv"][:3]), (False, False, spec["argv"][:3]))
        check_eq("K33: the record a real run reads names its evidence and carries no marker",
                 (request["runtime_provenance"]["evidence_refs"], "observed_without_evidence" in request["runtime_provenance"]),
                 (["probe"], False))
        # EP1-24 AK1a at the site: `build_mine_request` hands the story's folder to the stand's refusal, so the door narrows by it
        import runtime_probe as rp_door
        (work / "app" / "src").mkdir(parents=True)
        (work / "app" / "src" / "x.py").write_text("x = 1\n", encoding="utf-8")
        (task / "work" / "impl-diff.txt").write_text("--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-x = 0\n+x = 1\n", encoding="utf-8")
        held_rp = (rp_door.containers, rp_door.content_candidates)
        rp_door.containers = lambda timeout=20: [("a", ""), ("b", "")]
        rp_door.content_candidates = lambda files, checkout, app_root, running, timeout=20, cfg=None: ["b"]
        try:
            door_cfg = {**cfg, "implementation_repos": [{"repo_id": "app", "local_path": "app", "execution_profile_id": "api"}],
                        "execution": {}}
            try:
                er.build_mine_request(work, ["TC-002"], cfg=door_cfg, task="K33-1", probe=run_suite.probe_runtime)
                door_text = ""
            except er.MineRefusal as exc:
                door_text = str(exc)
        finally:
            rp_door.containers, rp_door.content_candidates = held_rp
        check_in("EP1-24 AK1a at the site: the refusal of `build_mine_request` names the ONE container the story's files are in",
                 "--profile api --container b`", door_text)
        # B-407 B-deps, the fingerprint site: the dependency files of the run's cwd are the data's (a Java manifest counts,
        # the project's own `run.dependency_files` counts), and an unreadable table is a note in the request's notes
        def watched(config: dict, notes_wanted: bool = False):
            built, built_notes, _r, _v = er.build_mine_request(work, ["TC-002"], cfg=config, task="K33-1", probe=run_suite.probe_runtime)
            names = [Path(r["path"]).name for r in built["fingerprint_files"] if r["kind"] == "dependency_files"]
            return (names, [n for n in built_notes if "table of dependency files" in n]) if notes_wanted else names
        (work / "pyproject.toml").write_text("[tool.poetry]\n", encoding="utf-8")
        check_eq("B-407 B-deps K-D-1 at the site: a Python project's fingerprint watches the same one file as before", watched(cfg), ["pyproject.toml"])
        (work / "pom.xml").write_text("<project/>\n", encoding="utf-8")
        (work / "shared.lock").write_text("x\n", encoding="utf-8")
        cfg["run"] = {"dependency_files": ["shared.lock"]}
        check_eq("B-407 B-deps K-D-2 at the site: pom.xml and the project's own `run.dependency_files` are watched",
                 sorted(watched(cfg)), ["pom.xml", "pyproject.toml", "shared.lock"])
        saved_loader = hooklib.load_ref_json
        hooklib.load_ref_json = lambda name: {}
        try:
            check_eq("B-407 B-deps E-D-4 at the site: an unreadable table is the floor (pyproject.toml, not pom.xml) and ONE note in the request's notes",
                     (lambda r: (r[0], len(r[1])))(watched(cfg, True)), (["pyproject.toml", "shared.lock"], 1))
        finally:
            hooklib.load_ref_json = saved_loader
        cfg.pop("run")
        (work / "pom.xml").unlink()
        (work / "shared.lock").unlink()
        (work / "pyproject.toml").unlink()
        # a custom callable a caller injects is honoured as given (the rehearsal reader replaces ONLY the strict one)
        seen = []
        custom = lambda s: seen.append(s) or {"profile_id": "api", "timestamp": "2026-10-02T12:00:00+00:00", "environment_id": "localhost",
                                              "expected_source_revision": "source-1", "observed_runtime_identity": "custom-1",
                                              "evidence_refs": ["x"], "result": "matched",
                                              "provenance": {"technical_verification": True, "source_linkage": "exact",
                                                             "deployed_source_revision": "source-1"}}
        before = len(calls())
        found = er.fresh_evidence(work, "K33-1", ["TC-002"], cfg=cfg, probe=custom)
        check_eq("K33: an injected custom probe is the one used (the script is not run) and the story is named to it",
                 (found["observed"], len(calls()) - before, seen[0].get("task_root")), (True, 0, str(task)))
        # the refused directions: the SAME RequestError the strict reader raises (the first read of a story has no earlier
        # request to fall back on, so the caller - `s6_freshness` - meets the raise and answers `decided: False`, FR-41)
        def refusal(**_none) -> str:
            try:
                er.fresh_evidence(work, "K33-1", ["TC-002"], cfg=cfg, probe=run_suite.probe_runtime)
                return ""
            except RequestError as exc:
                return str(exc)
        (probe_dir / "fail.txt").write_text("no story is running; Pass --task\nsecond line", encoding="utf-8")
        check_eq("K33 F4: a probe that exits non-zero is refused as the strict reader refuses it (a RequestError) and says ITS "
                 "reason: the first line of its stderr, not the bare `runtime probe failed`",
                 refusal(), "runtime probe failed: no story is running; Pass --task")
        (probe_dir / "fail.txt").write_text("", encoding="utf-8")
        check_in("K33 F4 control: a probe that exits non-zero and says nothing is named as that", "exited with code 1 and printed no reason",
                 refusal())
        (probe_dir / "fail.txt").unlink()
        (probe_dir / "mode.txt").write_text("unmarked", encoding="utf-8")
        unmarked = refusal()
        check_in("K33 CONTROL: a rehearsal `matched` with NO marker (nothing says it was one) is refused: the excuse needs its marker",
                 "runtime probe returned unverified provenance: ", unmarked)
        check_in("K33 CONTROL: and the refusal says what is missing", "evidence_refs must be a non-empty array", unmarked)
        # K-N2.5 (S5, t-300 N2): the rehearsal reader takes what the run path takes - ONE set (X4)
        check("K-N2.5: `rehearsal_probe`'s default accepts IS `profile_contract.ACCEPTS` (one set, not a copy)",
              er.rehearsal_probe.__defaults__[0] is ACCEPTS_OF_THE_PACKAGE)
        (probe_dir / "mode.txt").write_text("person_confirmed", encoding="utf-8")
        check_eq("K-N2.5 (flips K33): a person_confirmed answer - the word, with the kind, the story and the revision it was "
                 "given for - is TAKEN by a freshness read: what the stage entry accepts, the run accepts", refusal(), "")
        found = er.fresh_evidence(work, "K33-1", ["TC-002"], cfg=cfg, probe=run_suite.probe_runtime)
        check_eq("K-N2.5: and the read DECIDES (observed True) on it", found["observed"], True)
        (probe_dir / "mode.txt").write_text("unknown", encoding="utf-8")
        said = refusal()
        check_in("K-N2.5: an `unknown` is refused with the probe's own words (the error and the remedy)",
                 "runtime probe returned unknown: which build the stand runs could not be read. tell me how to read it", said)
        try:
            er.fresh_evidence(work, "K33-1", ["TC-002"], cfg=cfg, probe=run_suite.probe_runtime)
            raised = ""
        except RequestError as exc:
            raised = type(exc).__name__
        check_eq("K-N2.5 E9: the rehearsal reader raises the SAME exception class as the strict one (one problem, one refusal shape)",
                 raised, "ProvenanceRefused")
        (probe_dir / "mode.txt").write_text("na1", encoding="utf-8")
        found = er.fresh_evidence(work, "K33-1", ["TC-002"], cfg=cfg, probe=run_suite.probe_runtime)
        check_eq("K-N2.5 control: a probe that compared nothing (`no_changed_file`) still decides", found["observed"], True)
        (probe_dir / "mode.txt").unlink()
        check_eq("K33 CONTROL: with the probe healthy again the very same read is accepted", refusal(), "")
        # AE16: a foreign probe script is never handed the flag
        foreign = probe_dir / "my_runtime_probe.py"
        foreign.write_text(REHEARSAL_PROBE.replace('"--no-evidence" in argv', 'False'), encoding="utf-8")
        cfg["execution"]["runtime_probes"]["api"] = {"argv": [sys.executable, str(foreign), "--profile", "api"], "cwd": ".", "timeout_s": 30}
        before = len(calls())
        found = er.fresh_evidence(work, "K33-1", ["TC-002"], cfg=cfg, probe=run_suite.probe_runtime)
        check_eq("K33 AE16: a project's own probe script (another basename) is run exactly as registered: no flag, no --task-root",
                 (found["observed"], calls()[before:] and "--no-evidence" in calls()[-1], "--task-root" in calls()[-1]), (True, False, False))
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved
        hooklib._PROJECT_ROOT_CACHE = None
        shutil.rmtree(work, ignore_errors=True)


def dependency_files_checks() -> None:
    """B-407 B-deps (F-7): the files a run's fingerprint and the D-0023 rehearsal key watch are data
    (`references/dependency-files.json`), widened by the project's own `run.dependency_files`."""
    import hooklib
    import execution_request as er
    shipped = json.loads((PLUGIN_ROOT / "references" / "dependency-files.json").read_text(encoding="utf-8"))
    floor = ("pyproject.toml", "poetry.lock", "requirements.txt", "setup.cfg", "package.json", "package-lock.json")
    report_floor = ("pytest.ini", "tox.ini", "setup.cfg", "conftest.py")
    check_eq("E-D-4 pin: the shipped data holds every name watched before it existed (never fewer files)",
             [n for n in floor if n not in shipped["names"]] + [n for n in report_floor if n not in shipped["report_config"]], [])
    check_eq("E-D-4 control: the same comparison against a data file that dropped `poetry.lock` finds it",
             [n for n in floor if n not in [m for m in shipped["names"] if m != "poetry.lock"]], ["poetry.lock"])
    check_eq("the code's floors are today's six and four names", (er._DEPENDENCY_FLOOR, er._REPORT_CONFIG_FLOOR), (floor, report_floor))
    check_eq("`_DEPENDENCY_FILES` stays exported, and is the data's names", er._DEPENDENCY_FILES, tuple(shipped["names"]))

    def folder(*names: str) -> Path:
        path = Path(tempfile.mkdtemp(prefix="qa-depfiles-", dir=ROOT))
        for name in names:
            (path / name).parent.mkdir(parents=True, exist_ok=True)
            (path / name).write_text("x\n", encoding="utf-8")
        return path

    def listed(path: Path, cfg=None) -> tuple:
        paths, note = er.dependency_files(path, cfg or {})
        return [Path(p).relative_to(path).as_posix() for p in paths], note

    python = folder("pyproject.toml", "poetry.lock", "Makefile", "pytest.ini")
    check_eq("K-D-1: the Python fixture's dependency list is today's (pyproject.toml, poetry.lock) and says nothing",
             listed(python), (["pyproject.toml", "poetry.lock"], ""))
    check_eq("K-D-1: the paths are `str(run_cwd / name)`, as the fingerprint always took them",
             er.dependency_files(python, {})[0], [str(python / "pyproject.toml"), str(python / "poetry.lock")])
    for names, expect in ((("pom.xml",), ["pom.xml"]), (("App.csproj",), ["App.csproj"]), (("go.mod", "go.sum"), ["go.mod", "go.sum"]),
                          (("jest.config.js",), [])):
        check_eq(f"K-D-2: {names} {'is' if expect else 'is NOT (it is a report config: the key only)'} on the dependency list",
                 listed(folder(*names))[0], expect)
    check_eq("K-D-2: a pattern reads the top level only (E-D-3): `src/App.csproj` and `module/pom.xml` are not found",
             listed(folder("src/App.csproj", "module/pom.xml"))[0], [])
    check_eq("E-D-3: the door for anything deeper is `run.dependency_files` (relative to the cwd)",
             listed(folder("src/App.csproj", "module/pom.xml", "pom.xml"), {"run": {"dependency_files": ["src/App.csproj", "module/pom.xml", "pom.xml", "gone.lock"]}}),
             (["pom.xml", "src/App.csproj", "module/pom.xml"], ""))
    check_eq("a name the project lists that the table lacks counts, once",
             listed(folder("custom.lock"), {"run": {"dependency_files": ["custom.lock", "custom.lock"]}}), (["custom.lock"], ""))
    bad_config = listed(folder("pom.xml"), {"run": {"dependency_files": "pom.xml"}})
    check_eq("`run.dependency_files` that is not a list is ignored and said once; the table still works", (bad_config[0], bool(bad_config[1])),
             (["pom.xml"], True))
    check_eq("an absent `run`, a `run` that is no object and a None config are the same as no door",
             [listed(python, cfg)[0] for cfg in ({}, {"run": []}, {"run": {"dependency_files": None}}, None)], [["pyproject.toml", "poetry.lock"]] * 4)

    # E-D-4: the table cannot be read, or is malformed: today's six, one note, never fewer
    java = folder("pom.xml", "requirements.txt", "App.csproj", "package.json")
    original = hooklib.load_ref_json
    try:
        broken = {"missing or unreadable (load_ref_json gives {})": {},
                  "`names` is not a list": {"names": "pom.xml", "patterns": [], "report_config": ["pytest.ini"]},
                  "`names` holds a non-string": {"names": ["pom.xml", 5], "patterns": [], "report_config": ["pytest.ini"]},
                  "`names` is empty": {"names": [], "patterns": [], "report_config": ["pytest.ini"]}}
        for why, data in broken.items():
            hooklib.load_ref_json = lambda name, data=data: data
            got = listed(java)
            check_eq(f"E-D-4: a table that is {why}: the floor's files only (requirements.txt, package.json)", got[0], ["requirements.txt", "package.json"])
            check_eq("E-D-4: ... and ONE note (the table's, said once)", got[1].count("table of dependency files"), 1)
        hooklib.load_ref_json = lambda name: {"names": ["pom.xml"], "patterns": ["src/*.csproj"], "report_config": ["pytest.ini"]}
        got = listed(java)
        check_eq("E-D-4: a pattern with a path separator is malformed (top level only): no patterns, the table's other keys stand, one note",
                 (got[0], "`patterns`" in got[1]), (["pom.xml"], True))
        hooklib.load_ref_json = lambda name: {"names": ["pom.xml"], "patterns": ["*.csproj"], "report_config": ["pytest.ini"]}
        check_eq("control: the same hook with a whole table reads it (the swap is what the cases above vary)", listed(java), (["pom.xml", "App.csproj"], ""))
        hooklib.load_ref_json = lambda name: (_ for _ in ()).throw(RuntimeError("no plugin root"))
        check_eq("E-D-4: a reader that raises is the floor too, never an exception", listed(java)[0], ["requirements.txt", "package.json"])
        hooklib.load_ref_json = lambda name: {}
        check_eq("E-D-4: the report-config floor is today's four names when the table is broken",
                 er.dependency_table()["report_config"], list(report_floor))
    finally:
        hooklib.load_ref_json = original
    check_eq("control: the real table is read again after the swaps", listed(java), (["requirements.txt", "package.json", "pom.xml", "App.csproj"], ""))


def rh1_5_one_reading_of_the_selected_profiles() -> None:
    """RH1-5 leftover (AR-13): the request builder reads the selected profiles through `profile_contract.selected_profiles`
    (a profile with no `selected` key is selected, `selected: false` sits out, none selected = all), never its own copy.
    Killing: a private copy back in execution_request (identity key), or a copy that reads a missing key as not selected."""
    import execution_request as ER
    import profile_contract as PC
    check("selected profiles: execution_request holds no private copy", not hasattr(ER, "_selected_profiles"))
    check("selected profiles: the reading is profile_contract's own", ER.selected_profiles is PC.selected_profiles)
    cfg = {"profiles": [{"profile_id": "api", "roots": {"test": "tests/api"}},
                        {"profile_id": "ui", "selected": False, "roots": {"test": "tests/ui"}}]}
    check_eq("selected profiles: no key = selected, false sits out", [p["profile_id"] for p in PC.selected_profiles(cfg)],
             ["api"])
    check_eq("selected profiles through profiles_owning: the unselected root owns nothing",
             ER.profiles_owning(cfg, "tests/ui/a.py"), [])
    none = {"profiles": [{"profile_id": "a", "selected": False}, {"profile_id": "b", "selected": False}]}
    check_eq("selected profiles: none selected = all", [p["profile_id"] for p in PC.selected_profiles(none)], ["a", "b"])


def hf2_10_spell_as_collected_proves_only_what_it_found() -> None:
    """B.3 (HF2-10): `verified` of `_spell_as_collected` decides whether anybody checks the ids again, so it may err
    ONLY towards False. The eight inputs of the spec, each with a key, and a positive control."""
    import importlib.util
    import execution_request as er
    spec = importlib.util.spec_from_file_location("node_ids_real_for_spell", PLUGIN_ROOT / "scripts" / "node_ids.py")
    real = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real)
    project = Path("/proj")

    def row(node: str, path: str) -> dict:
        return {"instance_id": node.split("::", 1)[-1], "case": "TC-1", "node": node, "path": Path(path),
                "entry": {}, "report_test_id": ""}

    def spelled(rows: list, collected):
        notes: list = []

        def collect(argv, cwd, files):
            if isinstance(collected, BaseException):
                raise collected
            return list(collected)
        out, verified = er._spell_as_collected(rows, {"argv": ["pytest"]}, project, collect, notes)
        return out, verified, notes

    a = row("tests/test_a.py::test_x", "/proj/tests/test_a.py")
    out, verified, _n = spelled([a], ["tests/test_a.py::test_x"])
    check_eq("B.3 control: a row found once in a parsed list is verified and carries the collected report id",
             (verified, out[0].get("collected"), out[0]["report_test_id"]), (True, True, "tests.test_a::test_x"))
    # (1) any exception of the collect
    for label, error in (("CollectError unread", real.CollectError("pytest collected 3 test(s) but none could be parsed", "head")),
                         ("a timeout", real.CollectError("collect timed out after 180s")),
                         ("ImportError", ImportError("no node_ids")), ("RuntimeError", RuntimeError("boom"))):
        out, verified, _n = spelled([a], error)
        check_eq(f"B.3 (1) {label}: not verified, the row as it was", (verified, out), (False, [a]))
    # (2) an empty list
    out, verified, _n = spelled([a], [])
    check_eq("B.3 (2) an empty successful collect: not verified (and the row untouched)", (verified, out), (False, [a]))
    # (3) a row missing from the list; the found one is still respelled, the other is not "verified"
    b = row("tests/test_a.py::test_y", "/proj/tests/test_a.py")
    out, verified, _n = spelled([a, b], ["tests/test_a.py::test_x"])
    check_eq("B.3 (3) one row missing from the list: not verified as a whole", verified, False)
    check_eq("B.3 (3) ... and the missing row is not marked as collected", [r.get("collected") for r in out], [True, None])
    # (4) a parametrized row with no candidate or with several
    p = row("tests/test_a.py::test_x[a]", "/proj/tests/test_a.py")
    out, verified, _n = spelled([p], ["tests/test_a.py::test_x[b]"])
    check_eq("B.3 (4) a parametrized row with 0 candidates: not verified", (verified, out), (False, [p]))
    out, verified, _n = spelled([p], ["tests/test_a.py::test_x[chromium-a]", "tests/test_a.py::test_x[firefox-a]"])
    check_eq("B.3 (4) ... with 2 candidates: not verified, never the first", (verified, out), (False, [p]))
    out, verified, _n = spelled([p], ["tests/test_a.py::test_x[chromium-a]"])
    check_eq("B.3 (4) control: exactly one candidate is the real id", (verified, out[0]["node"]),
             (True, "tests/test_a.py::test_x[chromium-a]"))
    # (5) a banner glued to the first id
    out, verified, _n = spelled([a], ["\U0001F50D Fetching providers...tests/test_a.py::test_x"])
    check_eq("B.3 (5) an id with a banner glued before it is not the row's id: not verified", (verified, out), (False, [a]))
    # (6) a space or a unicode letter in a parameter: only the exact spelling matches
    for text in ("a b", "é"):
        q = row(f"tests/test_a.py::test_x[{text}]", "/proj/tests/test_a.py")
        out, verified, _n = spelled([q], [f"tests/test_a.py::test_x[{text}]"])
        check_eq(f"B.3 (6) [{text}] collected as written is verified", verified, True)
    q = row("tests/test_a.py::test_x[a-b]", "/proj/tests/test_a.py")
    check_eq("B.3 (6) [a-b] is not [a b]", spelled([q], ["tests/test_a.py::test_x[a b]"])[1], False)
    q = row("tests/test_a.py::test_x[é]", "/proj/tests/test_a.py")
    check_eq("B.3 (6) [é] is not [e]", spelled([q], ["tests/test_a.py::test_x[e]"])[1], False)
    # (7) two files that differ only in case: only on a file system that tells them apart
    if os.name == "nt":
        print("SKIP B.3 (7): case-only file names cannot exist on this file system (Windows); the key runs on POSIX "
              "(the comparison is folded only on os.name == 'nt', like _path_key)")
    else:
        upper = row("tests/A.py::test_x", "/proj/tests/A.py")
        out, verified, notes = spelled([upper], ["tests/a.py::test_x"])
        check_eq("B.3 (7) tests/A.py is not tests/a.py: not verified", (verified, out), (False, [upper]))
        out, verified, notes = spelled([upper], ["tests/A.py::test_x", "tests/a.py::test_x"])
        check_eq("B.3 (7) ... and a list holding both gives the row ITS file, not 'two parametrizations'",
                 (verified, len(out), notes), (True, 1, []))
    # (8) the same function name in another file
    other = row("tests/a/test_a.py::test_x", "/proj/tests/a/test_a.py")
    out, verified, _n = spelled([other], ["tests/b/test_a.py::test_x"])
    check_eq("B.3 (8) another file's test with the same function name is not this row's: not verified",
             (verified, out), (False, [other]))
    out, verified, _n = spelled([other], ["tests/b/test_a.py::test_x", "tests/a/test_a.py::test_x"])
    check_eq("B.3 (8) control: both listed, the row takes its own", (verified, len(out)), (True, 1))


def rh1_9_same_instance_bytes_asks_the_one_comparator() -> None:
    """RH1-9 N2 (AR-13, AR-28): `same_instance_bytes` decides through `proof_level.compare_identity`; the budget side of the
    flaky counter is kept by its own caller."""
    import execution_request as ER
    import proof_level as PL
    same = ER.same_instance_bytes
    check_eq("K-E1: equal content sha, no code sha on either side (a legacy request) -> True",
             same({"instance_content_sha": "c"}, {"instance_content_sha": "c"}), True)
    check_eq("K-E1: equal code sha, other content -> True (a comment-only edit)",
             same({"instance_content_sha": "c1", "instance_code_sha": "k"},
                  {"instance_content_sha": "c2", "instance_code_sha": "k"}), True)
    check_eq("K-E2: equal content sha, DIFFERENT code sha -> False (it was True before RH1-9)",
             same({"instance_content_sha": "c", "instance_code_sha": "k1"},
                  {"instance_content_sha": "c", "instance_code_sha": "k2"}), False)
    check_eq("K-E3: nothing against nothing -> False", same({}, {}), False)
    check_eq("K-E3: None against None -> False", same(None, None), False)
    check_eq("K-E3: a sha against nothing -> False", same({"instance_content_sha": "c"}, {}), False)
    real = PL.compare_identity
    PL.compare_identity = lambda a, b: ("different", "code")
    try:
        check_eq("K-E4: the answer is the comparator's (swapped to `different`, equal shas -> False)",
                 same({"instance_content_sha": "c", "instance_code_sha": "k"},
                      {"instance_content_sha": "c", "instance_code_sha": "k"}), False)
    finally:
        PL.compare_identity = real
    check_eq("K-E4 control: restored, the same shas -> True",
             same({"instance_content_sha": "c", "instance_code_sha": "k"},
                  {"instance_content_sha": "c", "instance_code_sha": "k"}), True)
    check_eq("K-E5: the flaky counter on a request with no sha counts by id -> True (the budget side)",
             ER._same_identity_for_count({"instance_contracts": {"t": {}}}, {"instance_contracts": {"t": {"instance_content_sha": "c"}}},
                                         "t"), True)
    check_eq("K-E5 control: a request WITH a sha against another sha is not the same",
             ER._same_identity_for_count({"instance_contracts": {"t": {"instance_content_sha": "c1"}}},
                                         {"instance_contracts": {"t": {"instance_content_sha": "c2"}}}, "t"), False)


def hf8_18_c_k11_a_row_of_another_spelling_is_admitted_outside_the_scope() -> None:
    """C-K11 (HF8-18 N1 widens the door `_admitted_outside` asks): the critic's red probe of a case OUTSIDE its dispatch is admitted
    when the row holds a receipt of another spelling of the same test on other bytes (the row had no probe of its own); the row
    with no receipt at all keeps today's refusal; so does a receipt of another function."""
    import test_proof_level as TPL
    from execution_request import _admitted_outside
    s, edit, put_receipt, row = TPL.other_spelling_world()
    try:
        bare = put_receipt("test_a", "test_a")
        s.put("tests/test_a.py", edit)
        critic = {"role": "qa-code-critic"}

        def asked(entry):
            return _admitted_outside(["TC-1"], ["TC-9"], [], {"tests": [entry]}, s.task, critic, "red_probe", False)
        check_eq("C-K11: a receipt of another spelling of the same test on other bytes - admitted",
                 asked(row("test_a[p]", bare)), (True, ["test_a[p]"]))
        check_eq("C-K11: the row with no receipt - not admitted, as before", asked(row("test_a[p]")), (False, []))
        check_eq("C-K11: a receipt of another function - not admitted",
                 asked(row("test_a[p]", put_receipt("test_y", "test_y"))), (False, []))
    finally:
        s.close()


def ep1_1_b371_instance_file_is_looked_for_in_the_run_directory_first() -> None:
    """B-371 pin: `instance_shas` looks for the instance's file in `run_cwd/file`, then in `root/file`, the order
    `build_mine_request` uses. A file at both places is the run directory's; the root's serves only when the run
    directory has none."""
    from execution_request import instance_shas
    from execution_fingerprint import function_sha
    root = Path(tempfile.mkdtemp(prefix="ep11-b371-"))
    try:
        (root / "sub").mkdir()
        (root / "sub" / "test_a.py").write_text("def test_a():\n    assert 1 == 1\n", encoding="utf-8")
        (root / "test_a.py").write_text("def test_a():\n    assert 2 == 2\n", encoding="utf-8")
        request = {"command": {"argv": ["pytest"], "cwd": "sub", "selector_args": {"i": ["test_a.py::test_a"]}},
                   "fingerprint_files": []}
        near = function_sha((root / "sub" / "test_a.py").resolve(), "test_a", (), [])["sha"]
        far = function_sha((root / "test_a.py").resolve(), "test_a", (), [])["sha"]
        check("B-371 the two files differ (the pin can tell them apart)", near != far and near and far)
        check_eq("B-371 both present: the run directory's file is measured",
                 instance_shas(root, request, "i")["instance_content_sha"], near)
        (root / "sub" / "test_a.py").unlink()
        check_eq("B-371 none in the run directory: the root's file is measured",
                 instance_shas(root, request, "i")["instance_content_sha"], far)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def ep1_28_stand_probe_spec() -> None:
    """EP1-28 (H-2): `stand_probe_spec` is the project's entry, else the default probe in memory; `why` says why there is none."""
    from execution_request import stand_probe_spec
    app = {"repo_id": "app", "local_path": "app", "role": "application", "execution_profile_id": "web"}
    tests = {"repo_id": "tests", "local_path": "tests", "role": "tests", "execution_profile_id": "web"}
    base = {"environments": [{"name": "localhost"}], "implementation_repos": [app, tests], "execution": {"runtime_probes": {}}}
    spec, why = stand_probe_spec(base, "web")
    argv = spec["argv"]
    check_eq("derived: a spec and no reason", (bool(spec), why), (True, ""))
    check_eq("derived: the application's checkout, the only stand, no container, cwd and timeout",
             (argv[argv.index("--checkout") + 1], argv[argv.index("--environment") + 1], "--container" in argv, spec["cwd"], spec["timeout_s"],
              spec.get("derived")), ("app", "localhost", False, ".", 30, True))
    check_eq("derived: no story named, no --task", "--task" in argv, False)
    check_eq("derived: with a story the probe is told it", stand_probe_spec(base, "web", "localhost", "QA-1")[0]["argv"][-2:], ["--task", "QA-1"])
    check("derived: the tokens are resolved for this machine", not any("{" in a for a in argv), str(argv))
    entry = {"argv": ["probe-x"], "cwd": "sub", "timeout_s": 7}
    got, why = stand_probe_spec(dict(base, execution={"runtime_probes": {"web": entry}}), "web")
    check_eq("derived: the project's entry wins and is not marked derived", (got, why), ({"argv": ["probe-x"], "cwd": "sub", "timeout_s": 7}, ""))
    star, _ = stand_probe_spec(dict(base, execution={"runtime_probes": {"*": entry}}), "web")
    check_eq("derived: the `*` entry wins too", star["argv"], ["probe-x"])
    # the three causes of None, and the others
    for label, cfg, needle in (
            ("no repository", dict(base, implementation_repos=[]), "no checkout of the application is recorded for profile web"),
            ("a repository without a path", dict(base, implementation_repos=[dict(app, local_path=""), dict(tests, local_path="")]),
             "no checkout of the application is recorded"),
            ("two repositories, no role", dict(base, implementation_repos=[dict(app, role=""), dict(tests, role="")]),
             "2 implementation repositories for profile web (app, tests)"),
            ("the application without a path", dict(base, implementation_repos=[dict(app, local_path=""), tests]),
             "the application repository app of profile web records no local_path"),
            ("two stands", dict(base, environments=[{"name": "localhost"}, {"name": "qa"}]), "this project names 2 stands (localhost, qa)")):
        got, why = stand_probe_spec(cfg, "web")
        check_eq(f"derived, {label}: no spec", got, None)
        check_in(f"derived, {label}: the reason in words", needle, why)
    got, why = stand_probe_spec(dict(base, environments=[{"name": "localhost"}, {"name": "qa"}]), "web", "qa")
    check_eq("derived: two stands and one named: that one", got["argv"][got["argv"].index("--environment") + 1], "qa")
    check_eq("derived: an empty config is a reason, not a raise", stand_probe_spec({}, "web")[0], None)
    # the S5 door of a stand docker names nothing for: a flag that exists, not a dead end (FR-2)
    import execution_request
    import runtime_probe
    saved = runtime_probe.containers
    runtime_probe.containers = lambda *a, **k: []
    try:
        door = execution_request._probe_door(base, "web")
    finally:
        runtime_probe.containers = saved
    check_in("door: no container named by docker: the door is --no-container", "--no-container", door)
    check_not_in("door: ... and no longer the dead advice to add --container for a stand that is not a docker one", "not a docker one", door)


SPEC_TS = """const PRICE = 10;
test.describe('g', () => {
  test('@api CART-1_TC_004 adds one', async () => { expect(PRICE).toBe(10); });
});
for (const p of rows) {
  test(`CART-1_TC_007 loop [${p.id}]`, async () => { expect(p).toBeTruthy(); });
}
"""


def ep1_37_selection_from_the_file() -> None:
    """EP1-37 p. 2, 4 (B-2, B-3): `code_selection` is the ONE builder of a file-and-line selector and its report identity, from the
    bytes read NOW; it builds nothing for a runner whose data states no `selection` (a project's own script, `gradlew`), and the
    selector of a file whose name is a regex is escaped. `selector_file` reads the contract's file, else the node id's;
    `instance_shas` measures a TS test by the same producer the request used (B-3)."""
    import re
    import tempfile
    import test_source
    import execution_request as ER
    root = Path(tempfile.mkdtemp(prefix="qa-er-ep137-"))
    try:
        (root / "tests").mkdir()
        spec = root / "tests" / "cart.spec.ts"
        spec.write_text(SPEC_TS, encoding="utf-8")
        argv = ["npx", "playwright", "test"]
        entry = {"file": "tests/cart.spec.ts", "instance_id": "CART-1_TC_004 adds one"}
        join = " › "
        got = ER.code_selection(entry, argv, root, root)
        check_eq("selector_args: the escaped file and the line of the `test` token", got["selector_args"], ["/tests/cart\\.spec\\.ts:3"])
        check_eq("report_test_id: the plain file, the raw title path with the runner's join", got["report_test_id"],
                 "tests/cart.spec.ts::g" + join + "@api CART-1_TC_004 adds one")
        check_eq("classname_match comes from the data", got["classname_match"], "file_suffix")
        check_not_in("a plain test has no report_match", "report_match", got)
        token = re.compile(got["selector_args"][0].split(":")[0])
        check("M-16: `a.spec.ts` does not select `data.spec.ts`", token.search("/x/data.spec.ts") is None
              and ER.code_selection({"file": "tests/cart.spec.ts", "instance_id": "CART-1_TC_004 adds one"}, argv, root, root) is not None)
        check("the escape selects the file itself", token.search("/work/tests/cart.spec.ts") is not None)
        loop = ER.code_selection({"file": "tests/cart.spec.ts", "instance_id": "CART-1_TC_007 loop"}, argv, root, root)
        check_eq("a loop test: ONE selector of the line of the loop's test call", loop["selector_args"], ["/tests/cart\\.spec\\.ts:6"])
        check("and a pattern of the whole report name", test_source.pattern_matches(loop["report_match"]["pattern"], "g".replace("g", "") + "CART-1_TC_007 loop [a]"))
        # the line is read from the bytes of NOW (no memory of the row)
        spec.write_text("// one more line\n// and another\n" + SPEC_TS, encoding="utf-8")
        check_eq("an edit above the test moves the line", ER.code_selection(entry, argv, root, root)["selector_args"], ["/tests/cart\\.spec\\.ts:5"])
        # nothing built, nothing guessed
        check_eq("a runner with no `selection` in the data: None", ER.code_selection(entry, ["gradlew", "test"], root, root), None)
        check_eq("the project's own script: None", ER.code_selection(entry, ["./run-tests.sh"], root, root), None)
        check_eq("an id the file does not hold: None", ER.code_selection({**entry, "instance_id": "CART-1_TC_099 x"}, argv, root, root), None)
        check_eq("a file that is not there: None", ER.code_selection({**entry, "file": "tests/none.spec.ts"}, argv, root, root), None)
        (root / "tests" / "A.kt").write_text("class A\n", encoding="utf-8")
        check_eq("a file with no row in the table: None", ER.code_selection({**entry, "file": "tests/A.kt"}, argv, root, root), None)
        # selector_file (B-2)
        check_eq("selector_file: the contract's file wins over a `file:line` token",
                 ER.selector_file({"instance_contracts": {"x": {"file": "tests/a.spec.ts"}}, "command": {"selector_args": {"x": ["/tests/a\\.spec\\.ts:12"]}}}, "x"),
                 "tests/a.spec.ts")
        check_eq("selector_file: a pytest node id as before", ER.selector_file({"command": {"selector_args": {"x": ["tests/a.py::test_x[1]"]}}}, "x"), "tests/a.py")
        check_eq("selector_file: nothing named", ER.selector_file({}, "x"), None)
        # instance_shas: the producer and the re-measurer are one (B-3)
        spec.write_text(SPEC_TS, encoding="utf-8")
        contract = {"file": "tests/cart.spec.ts", "report_test_id": got["report_test_id"], "classname_match": "file_suffix"}
        request = {"command": {"argv": argv, "cwd": ".", "selector_args": {"x": got["selector_args"]}}, "instance_contracts": {"x": contract}}
        measured = ER.instance_shas(root, request, "x")
        made = test_source.instance_shas_of(spec, contract["report_test_id"], None, join)
        check_eq("instance_shas = the producer's identity", {k: measured[k] for k in ("instance_content_sha", "instance_code_sha")},
                 {k: made[k] for k in ("instance_content_sha", "instance_code_sha")})
        check_eq("scope is file_skeleton", measured["scope"], "file_skeleton")
        spec.write_text(SPEC_TS.replace("PRICE = 10", "PRICE = 20"), encoding="utf-8")
        check("a constant above the test: another identity", ER.instance_shas(root, request, "x")["instance_code_sha"] != measured["instance_code_sha"])
        check_eq("a request with no `file` in the contract: {} as it always was",
                 ER.instance_shas(root, {**request, "instance_contracts": {"x": {"report_test_id": "r"}}}, "x"), {})
        spec.unlink()
        check_eq("the file is gone: {} (a longer run, not a false `same`)", ER.instance_shas(root, request, "x"), {})
    finally:
        shutil.rmtree(root, ignore_errors=True)


def ep1_37_build_mine_request_role_wins() -> None:
    """EP1-37 p. 3: the role's selector and report id win over the code's; with none the code builds them, and the identity is measured."""
    import re
    import run_suite
    import execution_request as er
    from harness import use_project
    work = Path(tempfile.mkdtemp(prefix="qa-ep137-")).resolve()
    saved = os.environ.get("CLAUDE_PROJECT_DIR")
    try:
        (work / "probe").mkdir()
        (work / "probe" / "runtime_probe.py").write_text(REHEARSAL_PROBE, encoding="utf-8")
        (work / "tests").mkdir()
        (work / "tests" / "a.spec.ts").write_text("test('TC-002 adds one', async () => { expect(1).toBe(1); });\n", encoding="utf-8")
        spec = {"argv": [sys.executable, str(work / "probe" / "runtime_probe.py"), "--profile", "web"], "cwd": ".", "timeout_s": 30}
        cfg = {"profiles": [{"profile_id": "web", "selected": True, "roots": {"test": "tests"},
                             "commands": {"one_test": {"argv": ["npx", "playwright", "test", "<test-file>"], "cwd": "."}},
                             "reporter": {"kind": "junit-xml"}, "selectors": {"verified": True}}],
               "execution": {"runtime_probes": {"web": spec}}}
        (work / "qa-factory" / "state").mkdir(parents=True)
        (work / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        task = work / "qa-factory" / "artifacts" / "K-1"
        use_project(work)
        row = {"case": "TC-002", "file": "tests/a.spec.ts", "selector": "tests/a.spec.ts::TC-002 adds one",
               "instance_id": "TC-002 adds one", "test": "TC-002 adds one"}

        def build(entry: dict) -> tuple:
            for name, value in (("work/automation-manifest.json", {"tests": [entry]}),
                                ("state/controller.json", {"schema_version": "2", "revision": "1", "source_revision": "s", "dispatches": {
                                    "S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator", "status": "running",
                                                          "scope": ["TC-002"], "budget": {"requests": 150}}}}),
                                ("pipeline.json", {"stages": {"S5": {"status": "running"}}})):
                (task / name).parent.mkdir(parents=True, exist_ok=True)
                (task / name).write_text(json.dumps(value), encoding="utf-8")
            request = er.build_mine_request(work, ["TC-002"], cfg=cfg, task="K-1", probe=run_suite.probe_runtime)[0]
            iid = request["selected_instance_ids"][0]
            return request["command"]["selector_args"][iid], request["instance_contracts"][iid]

        args, contract = build(row)
        check_eq("no role value: the code builds the selector", args, ["/" + re.escape("tests/a.spec.ts") + ":1"])
        check_eq("no role value: the code builds the report id", contract["report_test_id"], "tests/a.spec.ts::TC-002 adds one")
        check_eq("no role value: file and join", (contract["file"], contract["classname_match"]), ("tests/a.spec.ts", "file_suffix"))
        check_eq("the identity is measured by the one producer", contract["instance_content_scope"], "file_skeleton")
        args, contract = build({**row, "selector_args": ["--grep", "mine"], "report_test_id": "mine::adds"})
        check_eq("the role's selector wins", args, ["--grep", "mine"])
        check_eq("the role's report id wins", contract["report_test_id"], "mine::adds")
        check_eq("no code-built matching data beside it", ("classname_match" in contract, "report_match" in contract), (False, False))
        check_eq("the file is still there, so the same table judges it", contract["file"], "tests/a.spec.ts")
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved
        shutil.rmtree(work, ignore_errors=True)


def pc9b_c8_a_reference_stand_run_is_a_sample() -> None:
    """C8 (t-2181 PC-9b, rewritten t-2277 W1, owner 11.11.2026): a request whose probe names a stand that runs the OLD version of a side of
    the story is NOT refused: `validate_request` passes it and `run_suite.py --request` launches it; the run block is written as a sample
    (`reference_run` mark, in `work/reference-runs`, never in `work/run-blocks`, so no evidence reader sees it). NEGATIVE CONTROLS: the
    same request on the story's own stand is a plain run (no mark, `work/run-blocks`); a story with no reference is a plain run; the
    record that names the story's own stand ALSO as the reference is still refused (a data contradiction, not C8)."""
    story_dir = ROOT / "qa-factory" / "artifacts" / "REQ-1"
    story = story_dir / "pipeline.json"
    sides = {"ui": {"reality": "real", "deliverable": True, "reference": "qa", "source": "person"}}

    def run(key: str, stand: str = "qa") -> tuple:
        request = base_request(key)
        request["input_fingerprint"] = "sha256:" + key           # bytes no earlier run holds: a repeat is answered, never launched
        request["runtime_provenance"]["environment_id"] = stand
        before = {p.name for p in (story_dir / "work").rglob("*.json")} if (story_dir / "work").exists() else set()
        out = invoke(request)
        samples = sorted((story_dir / "work" / "reference-runs").glob("*.json")) if (story_dir / "work" / "reference-runs").exists() else []
        plain = sorted((story_dir / "work" / "run-blocks").glob("*.json")) if (story_dir / "work" / "run-blocks").exists() else []
        return request, out, [p for p in samples if p.name not in before], [p for p in plain if p.name not in before]
    try:
        story.write_text(json.dumps({"ticket": "REQ-1", "environment": "dev", "sides": sides}), encoding="utf-8")
        request = base_request("c8-reference")                       # its probe says environment_id `qa`: the reference stand
        check_eq("C8: validate_request no longer refuses a run aimed at the reference stand", refusal(request), "")
        counter = ROOT / "launch-count.txt"
        launched = counter.read_text() if counter.exists() else "0"
        _, out, samples, plain = run("c8-reference-run")
        check("C8: run_suite --request on the reference stand goes (exit 0, not run_refused, the runner launched)",
              out.returncode == 0 and "run_refused" not in out.stdout and counter.exists() and counter.read_text() != launched,
              f"{out.returncode} {out.stdout[-300:]} {out.stderr[-300:]}")
        check_eq("C8: its run block is a sample - one block in work/reference-runs, none in work/run-blocks", (len(samples), len(plain)), (1, 0))
        block = json.loads(samples[0].read_text(encoding="utf-8")) if samples else {}
        check_eq("C8: the block carries the mark (stand, side, not the story's code)",
                 {k: (block.get("reference_run") or {}).get(k) for k in ("stand", "side", "story_code")},
                 {"stand": "qa", "side": "ui", "story_code": False})
        check_in("C8: and the mark's words say it is a sample, not the story's result", "a sample, not the story's result",
                 str((block.get("reference_run") or {}).get("words")))
        import finalize_task as FT
        reduced = FT.reduce(story_dir)[0]
        check_eq("C8: the reducer (the one reader of the story's evidence) holds no row of the sample (earlier runs of the story stay)",
                 [r for r in reduced.get("results") or [] if r.get("attempt_id") == block.get("attempt_id")], [])
        _, out, samples, plain = run("c8-own-run", "dev")
        check_eq("C8 negative control: the same request on the story's own stand is a plain run (no sample, a run block)",
                 (out.returncode, len(samples), len(plain)), (0, 0, 1))
        check_eq("C8 negative control: and its block has no mark", "reference_run" in json.loads(plain[0].read_text(encoding="utf-8")) if plain else None, False)
        story.write_text(json.dumps({"ticket": "REQ-1", "environment": "dev"}), encoding="utf-8")
        _, out, samples, plain = run("c8-none-run")
        check_eq("C8: a story with no reference never reads the rule (a plain run, as before)", (out.returncode, len(samples), len(plain)), (0, 0, 1))
        story.write_text(json.dumps({"ticket": "REQ-1", "environment": "qa", "sides": sides}), encoding="utf-8")
        why = refusal(base_request("c8-contradiction"))
        check("C8: the record that names the story's own stand also as the reference is still refused (a contradiction)",
              "both as its own stand" in why and "sides.ui.reference" in why, why)
    finally:
        story.write_text(json.dumps({"ticket": "REQ-1"}), encoding="utf-8")


def main() -> None:
    ep1_1_b371_instance_file_is_looked_for_in_the_run_directory_first()
    ep1_28_stand_probe_spec()
    rh1_9_same_instance_bytes_asks_the_one_comparator()
    hf8_18_c_k11_a_row_of_another_spelling_is_admitted_outside_the_scope()
    if ROOT.exists():
        shutil.rmtree(ROOT)
    (ROOT / "qa-factory" / "state").mkdir(parents=True)
    (ROOT / "qa-factory" / "artifacts" / "REQ-1").mkdir(parents=True)   # the story: S0 makes it, run_suite never does (CX1-18)
    (ROOT / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    (ROOT / "dummy_runner.py").write_text(
        "from pathlib import Path\n"
        "p=Path('launch-count.txt'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')\n"
        "report=Path(__import__('sys').argv[1]); report.parent.mkdir(parents=True, exist_ok=True)\n"
        "ids=__import__('sys').argv[2:]\n"
        "cases=''.join(f'<testcase classname=\"x\" name=\"{x}\"/>' for x in ids)\n"
        "report.write_text(f'<testsuite tests=\"{len(ids)}\" failures=\"0\" errors=\"0\" skipped=\"0\">{cases}</testsuite>')\n",
        encoding="utf-8")
    (ROOT / "runtime_probe.py").write_text(
        "import json\nprint(json.dumps({\"profile_id\":\"api\",\"timestamp\":\"2026-09-17T12:00:00Z\","
        "\"environment_id\":\"qa\",\"expected_source_revision\":\"source-1\","
        "\"observed_runtime_identity\":\"build-1\",\"evidence_refs\":[\"probe\"],"
        "\"provenance\":{\"technical_verification\":True,\"source_linkage\":\"exact\","
        "\"deployed_source_revision\":\"source-1\"},\"result\":\"matched\"}))\n",
        encoding="utf-8")
    # A runner that behaves like `dotnet test`: one selection option or it prints its usage text
    # and writes nothing. The report path rides inside `--logger trx;LogFileName=<path>`.
    (ROOT / "filter_runner.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "Path('argv-seen.txt').open('a', encoding='utf-8').write(' '.join(args) + '\\n')\n"
        "if args.count('--filter') != 1:\n"
        "    print('Usage: dotnet test [options] -- one --filter expression is expected')\n"
        "    sys.exit(1)\n"
        "logger = next((a for a in args if a.startswith('trx;LogFileName=')), '')\n"
        "report = Path(logger.split('=', 1)[1] if logger else args[0])\n"
        "ids = [v.replace('FullyQualifiedName=', '') for v in args[args.index('--filter') + 1].split('|')]\n"
        "report.parent.mkdir(parents=True, exist_ok=True)\n"
        "cases = ''.join(f'<testcase classname=\"x\" name=\"{x}\"/>' for x in ids)\n"
        "report.write_text(f'<testsuite tests=\"{len(ids)}\" failures=\"0\" errors=\"0\" skipped=\"0\">{cases}</testsuite>')\n",
        encoding="utf-8")
    try:
        request = base_request()
        check_eq("valid request resolves ten explicit selector instances",
                 len(validate_request(request, ROOT)["selected_instance_ids"]), 10)
        selector_join_checks()
        dependency_files_checks()

        bad = {**request, "purpose": "impact_regression", "idempotency_key": "bad-regression"}
        try:
            validate_request(bad, ROOT)
            regression_denied = False
        except RequestError as exc:
            regression_denied = "recommendation-only" in str(exc)
        check("impact regression is denied before launch", regression_denied)

        outside = {**request, "selected_instance_ids": ["case-outside"],
                   "idempotency_key": "bad-scope"}
        try:
            validate_request(outside, ROOT)
            outside_denied = False
        except RequestError as exc:
            outside_denied = "outside approved current scope" in str(exc)
        check("selected instance outside current scope is denied", outside_denied)

        broad = json.loads(json.dumps(request))
        broad["command"]["scope"] = "full_suite"
        try:
            validate_request(broad, ROOT)
            broad_denied = False
        except RequestError as exc:
            broad_denied = "full_suite" in str(exc)
        check("behavioral full-suite command is unsupported", broad_denied)

        unknown_selector = json.loads(json.dumps(request))
        unknown_selector["command"]["selector_args"].pop("case-0")
        try:
            validate_request(unknown_selector, ROOT)
            selector_denied = False
        except RequestError as exc:
            selector_denied = "unsupported selector" in str(exc)
        check("unknown framework selector is denied instead of appended blindly", selector_denied)
        empty_selection = json.loads(json.dumps(request))
        empty_selection["selected_instance_ids"] = []
        try:
            validate_request(empty_selection, ROOT)
            empty_denied = False
        except RequestError as exc:
            empty_denied = "at least one" in str(exc)
        check("empty behavioral selection cannot degrade to whole suite", empty_denied)
        hidden = {**request, "purpose": "quality", "idempotency_key": "hidden-wrapper"}
        hidden["command"] = {"argv": [sys.executable, "wrapper.py"], "cwd": ".",
                             "scope": "selected", "reporter": "none", "runs_tests": True}
        try:
            validate_request(hidden, ROOT)
            hidden_denied = False
        except RequestError as exc:
            hidden_denied = "hidden behavioral wrapper" in str(exc)
        check("quality wrapper that launches tests is rejected", hidden_denied)
        exhausted = {**request, "idempotency_key": "budget-zero", "remaining_budget": 0}
        try:
            validate_request(exhausted, ROOT)
            exhausted_denied = False
        except RequestError as exc:
            exhausted_denied = "greater than zero" in str(exc)
        check("new behavioral request with exhausted budget is rejected", exhausted_denied)

        first = invoke(request)
        check_eq("initial ten-instance batch launches successfully", first.returncode, 0)
        check_eq("initial batch launches one subprocess", (ROOT / "launch-count.txt").read_text(), "1")
        duplicate = invoke(request)
        check_eq("duplicate successful request returns without subprocess", duplicate.returncode, 0)
        check_in("duplicate successful request reports reused", '"status": "reused"', duplicate.stdout)
        check_eq("duplicate does not create a double green", (ROOT / "launch-count.txt").read_text(), "1")
        # The run budget: the same inputs under a key of its own are the same run. Every
        # instance already holds a result, so the request is answered and nothing is begun.
        jobs_dir = ROOT / "qa-factory" / "artifacts" / "REQ-1" / "state" / "execution-jobs"
        jobs_before = len(list(jobs_dir.glob("*.json")))
        answered = invoke(base_request("initial-second-key"))
        check_eq("a new key over inputs that already hold a result is answered, exit 0", answered.returncode, 0)
        check_in("with `reused` and the words", '"words": "Already run: 10 test(s) passed on', answered.stdout)
        check_eq("nothing was launched", (ROOT / "launch-count.txt").read_text(), "1")
        check_eq("and no job or key was begun", len(list(jobs_dir.glob("*.json"))), jobs_before)

        repair = base_request("repair-1")
        repair["purpose"] = "repair_verify"
        repair["selected_instance_ids"] = ["case-2", "case-7"]
        repair["input_fingerprint"] = "sha256:inputs-2"
        repaired = invoke(repair)
        check_eq("targeted two-instance repair launches successfully", repaired.returncode, 0)
        check_eq("ten initial plus two targeted means two subprocess batches", (ROOT / "launch-count.txt").read_text(), "2")
        run_blocks = sorted((ROOT / "qa-factory" / "artifacts" / "REQ-1" / "work" / "run-blocks").glob("*.json"))
        check_eq("typed executions produced immutable reducer inputs", len(run_blocks), 2)
        blocks = [json.loads(path.read_text(encoding="utf-8")) for path in run_blocks]
        check_eq("initial block records ten selected instances",
                 len(next(b for b in blocks if b["purpose"] == "initial")["results"]), 10)
        check_eq("repair block records only two selected instances",
                 len(next(b for b in blocks if b["purpose"] == "repair_verify")["results"]), 2)

        # The run budget answers a request whose every instance already holds a result over the
        # same inputs, so the requests below that must LAUNCH carry inputs of their own (their
        # own input_fingerprint, with no instance bytes to match): each is a different run.
        stale = base_request("stale-report")
        stale["input_fingerprint"] = "sha256:inputs-stale"
        stale["command"]["argv"] = [sys.executable, "-c", "print('no new report')", "{report_path}"]
        stale["command"]["selector_args"] = {x: [] for x in stale["selected_instance_ids"]}
        # Empty selector argv is intentionally unsupported, so use diagnostic with one explicit selector.
        stale["selected_instance_ids"] = ["case-0"]
        stale["command"]["selector_args"] = {"case-0": ["case-0"]}
        resolved_stale = validate_request(stale, ROOT)
        stale_job = request_digest(resolved_stale)[:20]
        stale_report = ROOT / "qa-factory" / "artifacts" / "REQ-1" / "evidence" / "runs" / stale_job / "report.junit.xml"
        stale_report.parent.mkdir(parents=True, exist_ok=True)
        stale_report.write_text('<testsuite tests="1" failures="0"/>', encoding="utf-8")
        os.utime(stale_report, (1, 1))
        stale_run = invoke(stale)
        stale_payload = json.loads(stale_run.stdout)
        check_in("stale externally declared report is rejected", "stale report rejected",
                 stale_payload.get("report_error", ""))

        launch_fail = base_request("launch-fail")
        launch_fail["input_fingerprint"] = "sha256:inputs-launch-fail"
        launch_fail["command"]["argv"] = ["qa-executable-that-does-not-exist", "{report_path}"]
        failed = invoke(launch_fail)
        # A launcher the agent cannot start is not a broken run: nothing is launched, no job
        # is begun, and the runner asks the three-answer question the gate rehearsal asks
        # (install it here, name an environment, or the person runs these cases).
        check_eq("a missing launcher is a question, not a test exit", failed.returncode, 3)
        check_in("the runner names the gap", "executor_unavailable", failed.stdout)
        check_in("the three options travel with it", "options", failed.stdout)
        job_files = list((ROOT / "qa-factory" / "artifacts" / "REQ-1" / "state" /
                          "execution-jobs").glob("*.json"))
        check("jobs were persisted before every real subprocess launch", len(job_files) >= 3)
        check("nothing was launched, so no job records the missing launcher",
              not any(j.get("status") == "failed_to_launch"
                      for j in (json.loads(p.read_text()) for p in job_files)))

        store = JobStore(ROOT / "direct-jobs")
        unknown = validate_request({**request, "idempotency_key": "unknown-freshness",
                                    "freshness": "fresh"}, ROOT)
        action, job = store.begin(unknown)
        store.update(job, status="completed", execution_status="passed", freshness="unknown")
        check_eq("fresh request starts a persisted job", action, "launch")
        # A request carrying unknown freshness is rejected rather than matching that evidence.
        try:
            validate_request({**request, "idempotency_key": "new", "freshness": "unknown"}, ROOT)
            unknown_denied = False
        except RequestError:
            unknown_denied = True
        check("unknown freshness cannot match", unknown_denied)
        corrupt_store = JobStore(ROOT / "corrupt-jobs")
        corrupt_store.directory.mkdir()              # a store names its folder and creates nothing until it writes (CX1-18)
        corrupt_store._path("corrupt").write_text("{", encoding="utf-8")
        try:
            corrupt_store.read("corrupt")
            corrupt_denied = False
        except RequestError:
            corrupt_denied = True
        check("corrupt persisted claim blocks duplicate launch", corrupt_denied)
        # What `begin` says of a key that already holds a job: a green result is `reused`, a
        # finished run that did not pass is `already_run` (not a `duplicate`, which reads as "still
        # in flight"), and only a job not finished is a `duplicate`.
        label_store = JobStore(ROOT / "label-jobs")
        for name, state, outcome, label in (("red", "completed", "failed", "already_run"),
                                            ("green", "completed", "passed", "reused"),
                                            ("broken", "completed", "broken_run", "already_run"),
                                            ("live", "running", None, "duplicate")):
            labelled = validate_request(base_request(f"label-{name}"), ROOT)
            _first, held = label_store.begin(labelled)
            label_store.update(held, status=state, execution_status=outcome, freshness="fresh")
            check_eq(f"begin labels a {name} key `{label}`", label_store.begin(labelled)[0], label)
        mismatch = base_request("profile-mismatch")
        mismatch["runtime_provenance"]["profile_id"] = "web"
        try:
            validate_request(mismatch, ROOT)
            mismatch_denied = False
        except RequestError:
            mismatch_denied = True
        check("runtime evidence from another profile cannot authorize execution", mismatch_denied)
        guarded = base_request("byte-change")
        config_path = ROOT / "qa-factory" / "config.json"
        original_config = config_path.read_bytes()
        config_path.write_text('{"changed":true}', encoding="utf-8")
        try:
            validate_request(guarded, ROOT)
            changed_denied = False
        except RequestError:
            changed_denied = True
        finally:
            config_path.write_bytes(original_config)
        check("changed fingerprint input bytes block launch and reuse", changed_denied)
        changing_probe = ROOT / "changing_probe.py"
        changing_probe.write_text(
            "import json\nfrom pathlib import Path\n"
            "p=Path('probe-count.txt'); n=int(p.read_text())+1 if p.exists() else 1; p.write_text(str(n))\n"
            "print(json.dumps({\"profile_id\":\"api\",\"timestamp\":\"2026-09-17T12:00:00Z\","
            "\"environment_id\":\"qa\",\"expected_source_revision\":\"source-1\","
            "\"observed_runtime_identity\":('build-1' if n==1 else 'build-2'),\"evidence_refs\":[\"probe\"],"
            "\"provenance\":{\"technical_verification\":True,\"source_linkage\":\"exact\","
            "\"deployed_source_revision\":\"source-1\"},\"result\":\"matched\"}))\n",
            encoding="utf-8")
        changing = base_request("runtime-changed")
        changing["input_fingerprint"] = "sha256:inputs-runtime-changed"
        changing["runtime_probe"]["argv"] = [sys.executable, str(changing_probe)]
        changed_run = invoke(changing)
        check_in("runtime identity changing during a batch is inconclusive", '"execution_status": "inconclusive"',
                 changed_run.stdout)
        stable_store = JobStore(ROOT / "stable-digest-jobs")
        stable = validate_request(base_request("stable-refresh"), ROOT)
        _, stable_job = stable_store.begin(stable)
        stable_store.update(stable_job, status="completed", execution_status="passed", freshness="fresh")
        refreshed_raw = base_request("stable-refresh")
        refreshed_raw["remaining_budget"] = 0
        refreshed_raw["runtime_provenance"]["timestamp"] = "2026-09-17T12:05:00Z"
        refreshed_raw["runtime_provenance"]["evidence_refs"] = ["deploy/refreshed"]
        refreshed = validate_request(refreshed_raw, ROOT, allow_exhausted_reuse=True)
        check_eq("same semantic request reuses after budget exhaustion and provenance refresh",
                 stable_store.begin(refreshed)[0], "reused")
        changed_runtime = {**refreshed, "runtime_provenance": {
            **refreshed["runtime_provenance"], "observed_runtime_identity": "build-2"}}
        try:
            stable_store.begin(changed_runtime)
            runtime_conflict = False
        except RequestError:
            runtime_conflict = True
        check("same key rejects a changed runtime identity", runtime_conflict)
        launch_checks()
        t238_w5_the_reader_fills_in_this_machine_and_leaves_what_a_person_wrote()
        ep1_24_b1_the_s5_refusal_names_the_probe_command()
        t238_w4_not_applicable_is_in_the_accepted_set(request)
        t279_k_na_a_probe_with_no_changed_file_is_enough_on_any_stand(request)
        n2_k1_probe_runtime_is_the_one_predicate(request)
        n2_k2_validate_request_takes_a_word_bound_to_the_story(request)
        n2_k3_the_fingerprint_of_a_word_is_not_the_fingerprint_of_a_reading(request)
        n2_k11_a_word_is_never_equivalence_verified(request)
        n2_f1_b220_the_report_placeholder_may_sit_inside_one_token(request)
        t300_k33_a_freshness_read_is_a_rehearsal_end_to_end()
        hf3_6a_the_s6_close_context()
        pc9b_c8_a_reference_stand_run_is_a_sample()
        hf2_10_spell_as_collected_proves_only_what_it_found()
        rh1_5_one_reading_of_the_selected_profiles()
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
    ep1_37_selection_from_the_file()
    ep1_37_build_mine_request_role_wins()
    finish("test_execution_request")


if __name__ == "__main__":
    main()
