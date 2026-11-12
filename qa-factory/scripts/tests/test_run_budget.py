"""The run budget (D-0017 / D-0018 / D-0019): a result of a test is reused while its bytes, the
stand and the deployed version are unchanged, and only a person's word repeats one.

TP1-13797 is the measurement behind every case: the same seven instances ran green twice on
identical bytes (the `again-2` job of the S5 repair run has the same input fingerprint and the
same seven instance shas as its first job), the S6 runner ran them a third time on bytes that
had changed since, and every red probe ran the mutated test three times through the project's
own `--reruns 2`. Part 1 replays the real job shapes through the ONE predicate, `covered`;
part 2 drives `run_suite.py --mine` / `--request` end to end in a temp project (a fake `pytest`,
no real test tool, no claude); part 3 is the data switches an owner's answer would flip.

The fixtures under fixtures/run-budget-13797/ are sanitized copies of four real job files (the
originals are read-only): every absolute path became `<root>/...`, `<plugin>/...` or `<python>`
and the user name is gone; keys, purposes, statuses, selected ids, fingerprint components and
instance contracts are verbatim.
"""
import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness import PLUGIN_ROOT, check, check_eq, check_in, check_not_in, finish

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import hooklib  # noqa: E402
import run_suite  # noqa: E402
import execution_request as er  # noqa: E402
from diff_scope import executable_sha  # noqa: E402
from event_store import content_hash  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "run-budget-13797"
BLOCK = "already run on these bytes"
ROOT = Path(tempfile.mkdtemp(prefix="qa-run-budget-")).resolve()
TASK = "BUD-1"
TASK_ROOT = ROOT / "qa-factory" / "artifacts" / TASK
PY = sys.executable


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def runtime_sha_of(provenance: dict) -> str:
    """`execution_fingerprint.build`'s runtime_sha, restated: the five fields it hashes."""
    stable = {key: provenance.get(key) for key in
              ("profile_id", "environment_id", "expected_source_revision", "observed_runtime_identity")}
    stable["deployed_source_revision"] = (provenance.get("provenance") or {}).get("deployed_source_revision")
    return content_hash(stable)


def redeployed(request: dict, identity: str) -> dict:
    """The same request on a stand that now runs another build: the observed identity moved, so
    `runtime_sha` and with it the whole input fingerprint are recomputed the way `build` does."""
    moved = copy.deepcopy(request)
    moved["runtime_provenance"]["observed_runtime_identity"] = identity
    moved["fingerprint_components"]["runtime_sha"] = runtime_sha_of(moved["runtime_provenance"])
    moved["input_fingerprint"] = content_hash(moved["fingerprint_components"])
    return moved


def block_of_rows(**outcomes):
    """A `block_of` that answers with a run block whose rows carry the given outcomes."""
    rows = [{"instance_id": name, "status": status, "report_matched": True}
            for name, status in outcomes.items()]
    return lambda job: {"results": rows}


def part_one() -> None:
    policy, note = er.load_run_budget()
    check("the shipped run-budget.json loads", policy is not None and note == "")
    first = fixture("s5-repair-verify-0af95.json")
    again2 = fixture("s5-repair-verify-again-2-17cb93.json")
    s6 = fixture("s6-runner-37369aa9.json")
    probe_job = fixture("red-probe-eb6030db.json")
    ids = first["request"]["selected_instance_ids"]
    check_eq("the fixture is the 13797 shape: seven instances", len(ids), 7)
    check_eq("its `again-2` job is the same key with the same input fingerprint",
             (again2["request"]["idempotency_key"] == first["request"]["idempotency_key"] + ":again-2",
              again2["request"]["input_fingerprint"] == first["request"]["input_fingerprint"]), (True, True))

    # --- T1 (replay, real data): the again-2 run was already answered by the first ------------------
    # A result is per instance, from the run block row (B2). Where no run block is on record the
    # job's own `passed` stands (small choice 2), and the again-2 request is covered: the shape
    # the measurement was about.
    verdicts = [er.covered(first, again2["request"], i, policy=policy) for i in ids]
    check_eq("T1: with no run block on record the again-2 request is covered by the first job, all 7",
             [v[0] for v in verdicts], [True] * 7)
    check_eq("T1: through `covering`, from the whole story's jobs, by the FIRST job",
             [er.covering([first], again2["request"], i, policy=policy)["outcome"] for i in ids],
             ["passed"] * 7)
    # ... but the REAL 0af95 run block says every one of the 7 rows was `not_run` ("report row
    # missing": the reporter ids did not join; a later reparse block, not linked from the job,
    # repaired them). Its job says `passed`, its rows say no instance was seen to pass: with the
    # block read, none of the 7 is a result, so the again-2 run is a rerun (queued separately:
    # the relink of the reparse block).
    real_block = fixture("s5-run-block-0af95.json")
    check_eq("T1 control: the real block has 7 rows, every one not_run",
             (len(real_block["results"]), {r["status"] for r in real_block["results"]}), (7, {"not_run"}))
    with_block = [er.covered(first, again2["request"], i, policy=policy, block_of=lambda job: real_block)
                  for i in ids]
    check_eq("T1: with the real block read, NONE of the 7 is covered (each row says not_run)",
             [v[0] for v in with_block], [False] * 7)
    check("T1: and `why` says what the run's own record said",
          all("not_run" in v[1] and "report row missing" in v[1] for v in with_block))

    # --- T2 (real negative): the S6 run was over other bytes ---------------------------------------
    shared = ("source_sha", "config_sha", "dependency_sha", "runtime_sha", "policy_revision")
    check("T2: the S6 job differs from the S5 one in the test bytes ALONE (a measured fact)",
          all(s6["request"]["fingerprint_components"][k] == first["request"]["fingerprint_components"][k]
              for k in shared)
          and s6["request"]["fingerprint_components"]["test_content_sha"]
          != first["request"]["fingerprint_components"]["test_content_sha"])
    s6_ids = s6["request"]["selected_instance_ids"]
    negative = [er.covered(first, s6["request"], i, policy=policy) for i in s6_ids]
    check_eq("T2: the S6 request is NOT covered by the first job, for any instance",
             [v[0] for v in negative], [False] * len(s6_ids))
    check("T2: and `why` names the instance bytes", all("instance bytes" in v[1] for v in negative))

    # --- T3 (redeploy, on the 13797 shape) ---------------------------------------------------------
    check_eq("T3 control: runtime_sha recomputed from the fixture's provenance is the recorded one",
             runtime_sha_of(again2["request"]["runtime_provenance"]),
             again2["request"]["fingerprint_components"]["runtime_sha"])
    moved = redeployed(again2["request"], "verified_content:ffffffffffff|0|0|0")
    result = [er.covered(first, moved, i, policy=policy) for i in ids]
    check_eq("T3: a redeploy is NOT covered", [v[0] for v in result], [False] * 7)
    check("T3: and `why` names runtime_sha", all("runtime_sha" in v[1] for v in result))

    # --- the order of `why`: not a result, selector, a shared component, bytes, the stand ------------
    request = again2["request"]
    broken_job = copy.deepcopy(first)
    broken_job["execution_status"] = "not_executed"
    both = copy.deepcopy(request)
    both["command"]["selector_args"][ids[0]] = ["elsewhere::test"]
    why = er.covered(broken_job, both, ids[0], policy=policy)
    check("why names 'not a result' before a selector that also differs",
          not why[0] and "not_executed" in why[1])
    why = er.covered(first, both, ids[0], policy=policy)
    check("then the selector", not why[0] and "selector" in why[1])
    cfg = copy.deepcopy(request)
    cfg["fingerprint_components"]["config_sha"] = "0" * 64
    cfg["input_fingerprint"] = content_hash(cfg["fingerprint_components"])
    cfg["instance_contracts"][ids[0]]["instance_content_sha"] = "1" * 64
    why = er.covered(first, cfg, ids[0], policy=policy)
    check("then a shared component by name, before the bytes that also differ",
          not why[0] and "config_sha changed" in why[1])
    unseen = copy.deepcopy(request)
    unseen["runtime_observed"] = False
    check_eq("the stand not observed is never reported as unchanged (FR-41)",
             er.covered(first, unseen, ids[0], policy=policy), (False, "the stand's version was not observed"))
    check("the same request, observed, is covered", er.covered(first, request, ids[0], policy=policy)[0])

    # --- what is and is not a result ---------------------------------------------------------------
    check("a red_probe job is never a result of the unmutated test",
          not er.covered(probe_job, request, probe_job["request"]["selected_instance_ids"][0], policy=policy)[0])
    flaky = copy.deepcopy(first)
    flaky["request"]["purpose"] = "flaky_diagnostic"
    check("a flaky_diagnostic job is counted by the FLAKY cap, not as a result",
          not er.covered(flaky, request, ids[0], policy=policy)[0])
    stale = copy.deepcopy(first)
    stale["freshness"] = "stale"
    check("a job whose evidence is not fresh is not a result", not er.covered(stale, request, ids[0], policy=policy)[0])
    check("an instance the earlier run never selected has no result there",
          "no earlier run selected" in er.covered(first, request, "test_never_selected", policy=policy)[1]
          or not er.covered(first, request, "test_never_selected", policy=policy)[0])

    # --- a hand-written request without the code sha uses the raw sha only; non-pytest rows too ----
    bare = copy.deepcopy(request)
    for contract in bare["instance_contracts"].values():
        contract.pop("instance_content_sha", None)
    bare["input_fingerprint"] = "sha256:another-whole-fingerprint"
    check("a request without instance shas is not covered unless the whole fingerprint is equal",
          not er.covered(first, bare, ids[0], policy=policy)[0])
    bare["input_fingerprint"] = first["request"]["input_fingerprint"]
    check("and the whole fingerprint equal covers (today's rule for a non-pytest profile)",
          er.covered(first, bare, ids[0], policy=policy)[0])
    code_only = copy.deepcopy(request)
    code_only["input_fingerprint"] = "sha256:edited-bytes"
    code_only["instance_contracts"][ids[0]]["instance_content_sha"] = "9" * 64
    code_only["instance_contracts"][ids[0]]["instance_code_sha"] = "c" * 64
    old_code = copy.deepcopy(first)
    check("raw bytes differ and only one side has a code sha: not the same test",
          not er.covered(old_code, code_only, ids[0], policy=policy)[0])
    old_code["request"]["instance_contracts"][ids[0]]["instance_code_sha"] = "c" * 64
    check("raw bytes differ but both code shas equal: the same test (T5's rule)",
          er.covered(old_code, code_only, ids[0], policy=policy)[0])

    # --- a red result (F4 c: one repeat, then answered) and the stand reset (F10 a) ----------------
    red = copy.deepcopy(first)
    red["execution_status"] = "failed"
    red["created_at"] = "2026-09-27T03:50:08+00:00"
    outcomes = {i: "passed" for i in ids}
    outcomes[ids[0]] = "failed"
    reader = block_of_rows(**outcomes)
    check_eq("a red result covers nothing by itself under 'one repeat is allowed'",
             er.covered(red, request, ids[0], policy=policy, block_of=reader)[0], False)
    check("the instances that passed INSIDE a red job keep their result (B-148)",
          er.covered(red, request, ids[1], policy=policy, block_of=reader)[0])
    check("an unreadable run block means 'not a result' (the safe direction)",
          not er.covered(red, request, ids[1], policy=policy, block_of=lambda job: None)[0])
    second_red = copy.deepcopy(red)
    second_red["job_id"] = "second-red"
    check_eq("`covering` counts the reds: one is a repeat away",
             er.covering([red], request, ids[0], policy=policy, block_of=reader)["covered"], False)
    both_red = er.covering([red, second_red], request, ids[0], policy=policy, block_of=reader)
    check_eq("two failed results over identical inputs make the red final",
             (both_red["covered"], both_red["outcome"]), (True, "failed"))
    final_once = dict(policy, failed_result_policy={"covers_after_failures": 1})
    check("one failed result is final when the policy says 1",
          er.covering([red], request, ids[0], policy=final_once, block_of=reader)["covered"])
    never = dict(policy, failed_result_policy={"covers_after_failures": 0})
    check("and never final when it says 0",
          not er.covering([red, second_red], request, ids[0], policy=never, block_of=reader)["covered"])
    # --- B1: the NEWEST result over the same inputs decides ----------------------------------------
    green = copy.deepcopy(first)
    green["job_id"] = "green-job"
    by_status = lambda job: reader(job) if job.get("execution_status") == "failed" else None  # noqa: E731
    got = er.covering([red, green], request, ids[0], policy=policy, block_of=by_status)
    check_eq("B1: a red followed by a green ends green (the repeat turned it)",
             (got["covered"], got["outcome"], [j["job_id"] for j in got["jobs"]]), (True, "passed", ["green-job"]))
    got = er.covering([green, red], request, ids[0], policy=policy, block_of=by_status)
    check("B1: a green FOLLOWED BY a red on the same bytes is not answered `passed`",
          not got["covered"] and got["outcome"] == "" and "one repeat is allowed" in got["why"])
    got = er.covering([green, red, second_red], request, ids[0], policy=policy, block_of=by_status)
    check_eq("B1: ... and once the red has had its one repeat, the newest results decide: red is final",
             (got["covered"], got["outcome"]), (True, "failed"))
    got = er.covering([red, second_red, green], request, ids[0], policy=policy, block_of=by_status)
    check_eq("B1: reds before the newest green never count against it", (got["covered"], got["outcome"]),
             (True, "passed"))
    check("B1: with a red final at once (policy 1) the older green no longer answers",
          er.covering([green, red], request, ids[0], policy=final_once, block_of=by_status)["outcome"] == "failed")
    check("B1: a red older than the green does not count even when the policy never covers a red",
          er.covering([red, green], request, ids[0], policy=never, block_of=by_status)["covered"])
    check("B1: and a newer red over an older green is run again when the policy never covers a red",
          not er.covering([green, red], request, ids[0], policy=never, block_of=by_status)["covered"])

    # --- B2: a result is per instance, from the run block row, for a green job too ------------------
    rows_of = lambda **rows: (lambda job: {"results": [  # noqa: E731
        {"instance_id": i, "status": s, "report_matched": s != "not_run"} for i, s in rows.items()]})
    skipped = rows_of(**{i: ("skipped" if i == ids[0] else "passed") for i in ids})
    check("B2: a skipped row is NOT a result of that instance, though the job says passed",
          not er.covered(first, request, ids[0], policy=policy, block_of=skipped)[0])
    check_in("B2: and `why` says what the row said", "was skipped",
             er.covered(first, request, ids[0], policy=policy, block_of=skipped)[1])
    check("B2: the instances beside it that passed still are results",
          er.covered(first, request, ids[1], policy=policy, block_of=skipped)[0])
    check("B2: a not_run row is not a result either",
          not er.covered(first, request, ids[0], policy=policy,
                         block_of=rows_of(**{i: "not_run" for i in ids}))[0])
    check("B2: a readable block with no row for the instance is no result",
          not er.covered(first, request, ids[0], policy=policy, block_of=rows_of(**{ids[1]: "passed"}))[0])
    check("B2: a block that is on record and unreadable is no result (the safe direction)",
          not er.covered(first, request, ids[0], policy=policy, block_of=lambda job: False)[0])
    check("B2: no block on record at all: the job's own `passed` stands (small choice 2)",
          er.covered(first, request, ids[0], policy=policy, block_of=lambda job: None)[0])
    check("B2: a green job whose row says failed holds a red result of that instance",
          er.covering([first], request, ids[0], policy=final_once,
                      block_of=rows_of(**{i: ("failed" if i == ids[0] else "passed") for i in ids}))["outcome"]
          == "failed")
    check("F10: a red recorded BEFORE the stand was reset is not a result",
          not er.covering([red, second_red], request, ids[0], policy=policy, block_of=reader,
                          reset_at="2026-09-28T00:00:00+00:00")["covered"])
    check("F10: a red recorded AFTER the reset still is",
          er.covering([red, second_red], request, ids[0], policy=policy, block_of=reader,
                      reset_at="2026-09-01T00:00:00+00:00")["covered"])
    check("F10: a green stays a result across the reset",
          er.covered(first, request, ids[0], policy=policy, reset_at="2026-09-28T00:00:00+00:00")[0])
    check("F10: a green inside a red job stays one too",
          er.covered(red, request, ids[1], policy=policy, block_of=reader,
                     reset_at="2026-09-28T00:00:00+00:00")[0])

    # --- F5: the reading of "one run by the author" is data ---------------------------------------
    per_story = dict(policy, author_run_reading="per_story")
    check("per_code_version: the S6 bytes are not covered", not er.covered(first, s6["request"], s6_ids[0], policy=policy)[0])
    check("per_story: any result of the instance covers, whatever its bytes",
          er.covered(first, s6["request"], s6_ids[0], policy=per_story)[0])
    check("per_story does not lift the stand: a redeploy is still not covered",
          not er.covered(first, moved, ids[0], policy=per_story)[0])

    # --- the wrapper the pre-budget callers keep is the same predicate (FR-17) ---------------------
    fingerprint = {"input_fingerprint": again2["request"]["input_fingerprint"],
                   "fingerprint_components": again2["request"]["fingerprint_components"]}
    check("green_over_same_bytes is a thin wrapper over `covered`",
          er.green_over_same_bytes(first, fingerprint, again2["request"]["command"]["selector_args"],
                                   again2["request"]["instance_contracts"], ids))
    check("and a red job is not 'green'",
          not er.green_over_same_bytes(red, fingerprint, again2["request"]["command"]["selector_args"],
                                       again2["request"]["instance_contracts"], ids))

    # --- the data file: a missing or unreadable one enforces nothing, and says so -------------------
    bad = ROOT / "bad-budget.json"
    check("a missing file is one sentence, not a traceback",
          er.load_run_budget(ROOT / "nope.json")[0] is None
          and "not enforced for this run" in er.load_run_budget(ROOT / "nope.json")[1])
    bad.write_text("{", encoding="utf-8")
    check_in("a broken file says why it is unreadable", "run-budget.json unreadable", er.load_run_budget(bad)[1])
    shipped = json.loads((PLUGIN_ROOT / "references" / "run-budget.json").read_text(encoding="utf-8"))
    shipped["words"].pop("green")
    bad.write_text(json.dumps(shipped), encoding="utf-8")
    check_in("a file missing a sentence names it", "words.green", er.load_run_budget(bad)[1])

    # --- A7: the rerun flags, as spelled -----------------------------------------------------------
    flags, regex_flags = set(policy["rerun_flags"]), set(policy["rerun_flags_regex"])
    strip = lambda argv: er.strip_rerun_flags(argv, flags, regex_flags)  # noqa: E731
    check_eq("the regex-valued flag is data: --only-rerun", regex_flags, {"--only-rerun"})
    argv, removed = strip(["poetry", "run", "pytest", "--reruns", "2", "--ui-headless", "t.py::test_a"])
    check_eq("`--reruns 2` goes, the rest stays", (argv, removed),
             (["poetry", "run", "pytest", "--ui-headless", "t.py::test_a"], ["--reruns 2"]))
    argv, removed = strip(["pytest", "--reruns=3", "--reruns-delay", "1", "--only-rerun", "AssertionError",
                           "-x", "a.py::t"])
    check_eq("`--reruns=N`, `--reruns-delay N` and `--only-rerun X` go too", (argv, removed),
             (["pytest", "-x", "a.py::t"], ["--reruns=3", "--reruns-delay 1", "--only-rerun AssertionError"]))
    argv, _ = strip(["pytest", "--reruns", "a.py::t"])
    check_eq("a bare `--reruns` never eats the test that follows it", argv, ["pytest", "a.py::t"])
    argv, _ = strip(["pytest", "--reruns", "tests/test_x.py", "-q"])
    check_eq("nor a test FILE (a value is eaten only when it is a number)", argv, ["pytest", "tests/test_x.py", "-q"])
    argv, _ = strip(["pytest", "--reruns-delay", "tests/test_x.py"])
    check_eq("`--reruns-delay` neither", argv, ["pytest", "tests/test_x.py"])
    argv, removed = strip(["pytest", "--reruns-delay", "0.5", "-q"])
    check_eq("a fractional delay is a number", (argv, removed), (["pytest", "-q"], ["--reruns-delay 0.5"]))
    argv, removed = strip(["pytest", "--only-rerun", ".*\\.py", "tests/test_x.py::t"])
    check_eq("`--only-rerun` always eats its value, a regex that ends in .py included", (argv, removed),
             (["pytest", "tests/test_x.py::t"], ["--only-rerun .*\\.py"]))
    argv, removed = strip(["pytest", "--only-rerun", "-x-regex", "a.py::t"])
    check_eq("... and one that starts with a dash", (argv, removed), (["pytest", "a.py::t"], ["--only-rerun -x-regex"]))
    argv, removed = strip(["pytest", "a.py::t", "--only-rerun"])
    check_eq("`--only-rerun` at the very end has no value to eat", (argv, removed),
             (["pytest", "a.py::t"], ["--only-rerun"]))
    check_eq("nothing to remove is nothing removed", strip(["pytest", "a.py::t"])[1], [])


# --- part 2: end to end ------------------------------------------------------------------------

FAKE_PYTEST = r'''
import sys
from pathlib import Path
args = sys.argv[1:]
report = next((a.split("=", 1)[1] for a in args if a.startswith("--junitxml=")), "")
nodes = [a for a in args if "::" in a]
Path("launches.txt").open("a", encoding="utf-8").write(" ".join(nodes) + "\n")
Path("argv.txt").open("a", encoding="utf-8").write(" ".join(a for a in args if not a.startswith("--junitxml")) + "\n")
if any("ghost" in n for n in nodes):
    print("ERROR: not found: " + nodes[0])
    sys.exit(4)
rows, failed = [], 0
for node in nodes:
    parts = node.replace("\\", "/").split("::")
    classname = ".".join([parts[0][:-3].replace("/", ".")] + parts[1:-1])
    if "red" in parts[-1] or ("flip" in parts[-1] and Path("fail-flip.txt").exists()):
        failed += 1
        rows.append(f'<testcase classname="{classname}" name="{parts[-1]}"><failure message="AssertionError: boom">trace</failure></testcase>')
    elif "skipme" in parts[-1]:
        rows.append(f'<testcase classname="{classname}" name="{parts[-1]}"><skipped message="not today"/></testcase>')
    else:
        rows.append(f'<testcase classname="{classname}" name="{parts[-1]}"/>')
if report:
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text(f'<testsuite tests="{len(rows)}" failures="{failed}" errors="0" skipped="0">' + "".join(rows) + "</testsuite>", encoding="utf-8")
sys.exit(1 if failed else 0)
'''

PROBE = r'''
import json
import sys
from pathlib import Path
here = Path(__file__).parent
if (here / "probe-fail.txt").exists():
    sys.exit(1)
identity = (here / "identity.txt").read_text(encoding="utf-8").strip() if (here / "identity.txt").exists() else "build-1"
print(json.dumps({"profile_id": "api", "timestamp": "2026-09-22T10:00:00Z", "environment_id": "localhost",
                  "expected_source_revision": "source-1", "observed_runtime_identity": identity,
                  "evidence_refs": ["probe"], "result": "matched",
                  "provenance": {"technical_verification": True, "source_linkage": "exact",
                                 "deployed_source_revision": "source-1"}}))
'''

# one small test file per scenario: a scenario never disturbs another's bytes
FILES = {
    "test_a.py": "def test_green():\n    assert 1 == 1\n",
    "test_b.py": "def test_alpha():\n    assert 1 == 1\n\n\ndef test_beta():\n    assert 2 == 2\n",
    "test_c.py": "def test_red():\n    assert False\n",
    "test_d.py": "def test_flake():\n    assert True\n",
    "test_e.py": "def test_deploy():\n    assert True\n",
    "test_f.py": ("import pytest\n\n\ndef test_cosmetic():\n    \"\"\"Checks it.\"\"\"\n    value = compute()\n"
                  "    assert value == 1\n\n\ndef compute():\n    return 1\n"),
    "test_g.py": "def test_legacy():\n    assert True\n",
    "test_h.py": "def test_fresh():\n    assert True\n",
    "test_i.py": "def test_argv():\n    assert True\n",
    "test_j.py": "def test_j_red():\n    assert False\n",
    "test_k.py": "def test_k_red():\n    assert False\n",
    "test_l.py": "def test_l_red():\n    assert False\n",
    "test_m.py": "def test_story():\n    assert 1 == 1\n",
    "test_n.py": "def test_stripped_everywhere():\n    assert True\n",
    "test_o.py": "def test_probed():\n    assert True\n",
    "test_p.py": "def test_nx():\n    assert True\n",
    "test_q.py": "def test_left_alone():\n    assert True\n",
    "test_r.py": "def test_flip():\n    assert True\n",
    "test_s.py": "def test_flip_two():\n    assert True\n",
    "test_t.py": "def test_skipme():\n    assert True\n",
    "test_u.py": "def test_tpl():\n    assert True\n",
    "test_v.py": "def test_unobs():\n    assert True\n",
    "test_w.py": "def test_w_red():\n    assert False\n",
    "test_x.py": "MARK = \"UNTOKENIZABLE\"\n\n\ndef test_frag():\n    assert MARK\n",
}
MANIFEST = {"TC-001": ("test_a.py", "test_green"), "TC-002": ("test_b.py", "test_alpha | test_beta"),
            "TC-003": ("test_c.py", "test_red"), "TC-004": ("test_d.py", "test_flake"),
            "TC-005": ("test_e.py", "test_deploy"), "TC-006": ("test_f.py", "test_cosmetic"),
            "TC-007": ("test_g.py", "test_legacy"), "TC-008": ("test_h.py", "test_fresh"),
            "TC-009": ("test_i.py", "test_argv"), "TC-010": ("test_j.py", "test_j_red"),
            "TC-011": ("test_k.py", "test_k_red"), "TC-012": ("test_l.py", "test_l_red"),
            "TC-013": ("test_m.py", "test_story"), "TC-014": ("test_n.py", "test_stripped_everywhere"),
            "TC-015": ("test_o.py", "test_probed"), "TC-016": ("test_p.py", "test_nx"),
            "TC-017": ("test_q.py", "test_left_alone"), "TC-018": ("test_r.py", "test_flip"),
            "TC-019": ("test_s.py", "test_flip_two"), "TC-020": ("test_t.py", "test_skipme"),
            "TC-021": ("test_u.py", "test_tpl"), "TC-022": ("test_v.py", "test_unobs"),
            "TC-023": ("test_w.py", "test_w_red"), "TC-024": ("test_x.py", "test_frag")}


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1), encoding="utf-8")


def config() -> dict:
    # `--reruns 2 --reruns-delay 1` in the project's own command, as on 13797. The config is
    # part of every fingerprint: it is written once and never touched again.
    return {"profiles": [{"profile_id": "api", "selected": True, "roots": {"test": "tests"},
                          "commands": {"one_test": {"argv": [PY, str(ROOT / "fake" / "pytest"), "--reruns", "2",
                                                             "--reruns-delay", "1", "<test-file>"], "cwd": "."}},
                          "reporter": {"kind": "pytest"}, "selectors": {"verified": True}}],
            "execution": {"runtime_probes": {"api": {"argv": [PY, str(ROOT / "probe.py")], "cwd": ".",
                                                     "timeout_s": 20}}}}


def setup_project() -> None:
    (ROOT / "fake").mkdir(parents=True)
    (ROOT / "fake" / "pytest").write_text(FAKE_PYTEST, encoding="utf-8")
    (ROOT / "probe.py").write_text(PROBE, encoding="utf-8")
    (ROOT / "tests").mkdir()
    (ROOT / "tests" / "conftest.py").write_text("# fixtures\n", encoding="utf-8")
    for name, text in FILES.items():
        (ROOT / "tests" / name).write_text(text, encoding="utf-8")
    write_json(ROOT / "qa-factory" / "config.json", config())
    (ROOT / "qa-factory" / "state").mkdir(parents=True, exist_ok=True)
    set_pipeline()
    set_dispatch("running")
    write_json(TASK_ROOT / "work" / "automation-manifest.json", {"tests": [
        {"case": case, "file": f"tests/{file}", "selector": selector} for case, (file, selector) in MANIFEST.items()]})


def set_dispatch(status: str) -> None:
    write_json(TASK_ROOT / "state" / "controller.json", {
        "schema_version": "2", "revision": "41", "source_revision": "source-1",
        "dispatches": {"S5-qa-automator-1": {"id": "S5-qa-automator-1", "stage": "S5", "role": "qa-automator",
                                             "status": status, "scope": list(MANIFEST),
                                             "budget": {"requests": 150}}}})


def set_pipeline(running: str = "S5", overrides=()) -> None:
    write_json(TASK_ROOT / "pipeline.json", {"stages": {running: {"status": "running"}},
                                             "stage_overrides": list(overrides)})


def word(stage: str = "S5", decision: str = "the person looked and said run it again", at=None) -> dict:
    return {"stage": stage, "match": BLOCK, "decision": decision,
            "at": at or datetime.now(timezone.utc).isoformat(timespec="seconds")}


def call(*argv) -> tuple:
    """run_suite.main() in this process: (exit code, stdout, stderr)."""
    hooklib._PROJECT_ROOT_CACHE = None
    out, err = io.StringIO(), io.StringIO()
    old_argv, old_cwd = sys.argv, os.getcwd()
    sys.argv = ["run_suite.py", *[str(a) for a in argv]]
    os.chdir(ROOT)
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                run_suite.main()
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 2)
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)
    return code, out.getvalue(), err.getvalue()


def last_json(text: str) -> dict:
    lines = [line for line in text.strip().splitlines() if line.startswith("{")]
    return json.loads(lines[-1]) if lines else {}


def launches() -> list:
    path = ROOT / "launches.txt"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def argvs() -> list:
    path = ROOT / "argv.txt"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def store() -> er.JobStore:
    return er.JobStore(TASK_ROOT / "state" / "execution-jobs")


def backdate(instance: str, when: str) -> None:
    """Move every recorded job of one instance back to `when` (whole-second timestamps make
    'newer than' a matter of the clock otherwise; ties keep the order the files were written)."""
    for job in store().jobs():
        if instance in job["request"]["selected_instance_ids"]:
            job["created_at"] = job["updated_at"] = when
            store().write(job)


def count_jobs() -> int:
    return len(list((TASK_ROOT / "state" / "execution-jobs").glob("*.json")))


def count_requests() -> int:
    return len(list((TASK_ROOT / "work" / "requests").glob("*.json")))


def request_files(case: str) -> list:
    return sorted((TASK_ROOT / "work" / "requests").glob(f"mine-*{case}*.json"), key=lambda p: p.stat().st_mtime)


def last_request(case: str) -> dict:
    return json.loads(request_files(case)[-1].read_text(encoding="utf-8"))


def request_files_keys(case: str) -> list:
    """The idempotency keys of the requests `--mine` wrote for a case, oldest first."""
    return [json.loads(p.read_text(encoding="utf-8"))["idempotency_key"] for p in request_files(case)]


def edit(name: str, old: str, new: str) -> None:
    path = ROOT / "tests" / name
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"{name}: the fixture text changed; this edit no longer applies: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


@contextlib.contextmanager
def budget_data(**changes):
    """The shipped run-budget.json with `changes`, as the file the package reads: a data edit is
    all an owner's other answer needs (nothing but `hooklib.ref` is redirected, and only for
    that one file). `changes={"__absent__": True}` is a plugin copy without the file."""
    tmp = Path(tempfile.mkdtemp(prefix="t-budget-data-"))
    data = json.loads((PLUGIN_ROOT / "references" / "run-budget.json").read_text(encoding="utf-8"))
    absent = changes.pop("__absent__", False)
    data.update(changes)
    if not absent:
        (tmp / "run-budget.json").write_text(json.dumps(data), encoding="utf-8")
    real = hooklib.ref
    hooklib.ref = lambda rel: (tmp / rel) if rel == "run-budget.json" else real(rel)
    try:
        yield
    finally:
        hooklib.ref = real
        shutil.rmtree(tmp, ignore_errors=True)


def absent_modules() -> None:
    for name in ("node_ids", "stand_lease", "stand_health"):
        sys.modules[name] = None  # `import name` now raises ImportError


def part_two() -> None:
    # --- T4: the end-to-end answer, `--again`, and the person's word ------------------------------
    code, out, err = call("--mine", "TC-001")
    check_eq("T4: run 1 launches", (code, len(launches())), (0, 1))
    before, jobs_before, requests_before = len(launches()), count_jobs(), count_requests()
    code, out, err = call("--mine", "TC-001")
    answer = last_json(out)
    check_eq("T4: run 2 is answered `reused`, exit 0", (code, answer.get("status")), (0, "reused"))
    check_eq("T4: the launch count is unchanged", len(launches()), before)
    check_eq("T4: and nothing is written: no job, no request file", (count_jobs(), count_requests()),
             (jobs_before, requests_before))
    check("T4: the answer carries the covering job, its summary and the words",
          answer.get("job_id") and answer.get("summary") and answer.get("jobs") == [answer.get("job_id")]
          and "Already run: 1 test(s) passed on" in answer.get("words", ""))
    check_in("T4: the words say the result stands for every later stage", "stands for every later stage",
             answer.get("words", ""))
    code, out, err = call("--mine", "TC-001", "--again")
    answer = last_json(out)
    check_eq("T4: `--again` is still an answer, not a launch", (code, answer.get("status"), len(launches())),
             (0, "reused", before))
    check_in("T4: and the answer names `--again` and the block", "`--again` no longer repeats a result",
             answer.get("words", ""))
    check_in("T4: with the block a person's word passes", BLOCK, answer.get("words", ""))
    check_in("T4 (F2): with the budget on, the hint names a person's word", "A person's word passes a repeat",
             answer.get("hint", ""))
    check_not_in("T4 (F2): and not `--again`", "--again runs", answer.get("hint", ""))
    # The word passes ONE repeat (F1): it must be later than the newest result it repeats. The
    # jobs are dated well before the words, so the order does not depend on the clock's second.
    backdate("test_green", "2026-09-01T00:00:00+00:00")
    set_pipeline(overrides=[word(decision="the fixture behind it changed", at="2026-09-02T00:00:00+00:00")])
    code, out, err = call("--mine", "TC-001")
    check_eq("T4: a person's recorded word launches the repeat", (code, len(launches())), (0, before + 1))
    check_in("T4: and the note records the word", "the fixture behind it changed", err)
    check_eq("T4: the repeat is repair_verify under a key of its own",
             (last_request("TC-001")["purpose"],
              last_request("TC-001")["idempotency_key"] != request_files_keys("TC-001")[0]),
             ("repair_verify", True))
    code, out, err = call("--mine", "TC-001")
    check_eq("T4 (F1): the SAME word does not pass a second repeat: it is answered again",
             (last_json(out).get("status"), len(launches())), ("reused", before + 1))
    set_pipeline(overrides=[word(decision="and once more, I checked",
                                 at=(datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(timespec="seconds"))])
    code, out, err = call("--mine", "TC-001")
    check_eq("T4 (F1): a NEW word, said after that result, passes the next one, under the next key (`:again-2`)",
             (code, len(launches()), last_request("TC-001")["idempotency_key"].endswith(":again-2")),
             (0, before + 2, True))
    set_pipeline()
    code, out, err = call("--mine", "TC-001")
    check_eq("T4: with the word gone the repeat is answered again", (last_json(out).get("status"), len(launches())),
             ("reused", before + 2))

    # --- T5: cosmetic edits are not edits -----------------------------------------------------------
    call("--mine", "TC-006")
    base = len(launches())
    edit("test_f.py", "    value = compute()", "    # why one\n    value = compute()")
    code, out, err = call("--mine", "TC-006")
    check_eq("T5: a comment inside the test body is reused", (last_json(out).get("status"), len(launches())),
             ("reused", base))
    edit("test_f.py", '"""Checks it."""', '"""Checks it, and why it matters."""')
    code, out, err = call("--mine", "TC-006")
    check_eq("T5: a docstring edit is reused", (last_json(out).get("status"), len(launches())), ("reused", base))
    edit("test_f.py", "\n\n\ndef compute", "\n\n\n\n\ndef compute")
    code, out, err = call("--mine", "TC-006")
    check_eq("T5: blank lines are reused", (last_json(out).get("status"), len(launches())), ("reused", base))
    edit("test_f.py", "    return 1", "    # a comment in the helper the test calls\n    return 1")
    code, out, err = call("--mine", "TC-006")
    check_eq("T5: a comment in a helper it calls is reused", (last_json(out).get("status"), len(launches())),
             ("reused", base))
    edit("test_f.py", "assert value == 1", "assert value >= 1")
    code, out, err = call("--mine", "TC-006")
    check_eq("T5: an assert changed launches", (code, len(launches())), (0, base + 1))
    check("T5: and the new job carries both shas",
          all(c.get("instance_content_sha") and c.get("instance_code_sha")
              for c in last_request("TC-006")["instance_contracts"].values()))
    edit("test_f.py", "def test_cosmetic", "@pytest.mark.skip\ndef test_cosmetic")
    code, out, err = call("--mine", "TC-006")
    check_eq("T5: `@pytest.mark.skip` added launches", (code, len(launches())), (0, base + 2))
    edit("test_f.py", "    return 1", "    return 2")
    code, out, err = call("--mine", "TC-006")
    check_eq("T5: the helper's code changed: launches", (code, len(launches())), (0, base + 3))
    marker = "@pytest.mark.qa(\n    case=\"TC-006\",\n)\n"
    code_now = executable_sha("def test_x():\n    pass\n")
    if executable_sha(marker + "def test_x():\n    pass\n") == code_now:
        edit("test_f.py", "def test_cosmetic", marker + "def test_cosmetic")
        code, out, err = call("--mine", "TC-006")
        check_eq("T5b: the factory's marker decorator (a multi-line call) added is reused",
                 (last_json(out).get("status"), len(launches())), ("reused", base + 3))
        edit("test_f.py", 'case="TC-006"', 'case="TC-006", version="cv_2"')
        code, out, err = call("--mine", "TC-006")
        check_eq("T5b: the marker edited is reused", (last_json(out).get("status"), len(launches())),
                 ("reused", base + 3))
    else:
        print("SKIP T5b: diff_scope.executable_sha does not yet treat the factory's marker decorator as "
              "prose (the marker data arrives with t-023); the check switches on by itself when it does")

    # --- T6 (B-148): one instance edited, only it runs ----------------------------------------------
    call("--mine", "TC-002")
    check_eq("T6: the first run carries both instances", launches()[-1].split(),
             ["tests/test_b.py::test_alpha", "tests/test_b.py::test_beta"])
    base = len(launches())
    edit("test_b.py", "def test_alpha():\n    assert 1 == 1", "def test_alpha():\n    assert 1 >= 1")
    code, out, err = call("--mine", "TC-002")
    check_eq("T6: `--mine CASE` launches exactly the edited instance", launches()[-1].split(),
             ["tests/test_b.py::test_alpha"])
    check_eq("T6: one launch", len(launches()), base + 1)
    check_eq("T6: the request selects exactly [test_alpha]", last_request("TC-002")["selected_instance_ids"],
             ["test_alpha"])
    check_in("T6: the note names the instance that was not run again", "test_beta", err)
    check_in("T6: and says why", "have a result on", err)
    check_eq("T6: the request records what was not run again, and by which job",
             sorted(last_request("TC-002").get("not_run_again") or {}), ["test_beta"])
    code, out, err = call("--mine", "TC-002")
    check_eq("T6: and then the whole case is answered", (last_json(out).get("status"), len(launches())),
             ("reused", base + 1))

    # --- D0: what the story already holds, asked with NO dispatch open (S6 reads it) -----------------
    set_dispatch("accepted")
    d0_launches, d0_jobs, d0_requests = len(launches()), count_jobs(), count_requests()
    found = er.fresh_evidence(ROOT, TASK, ["TC-002", "TC-008"], cfg=config(), probe=run_suite.probe_runtime)
    states = {i: v["state"] for i, v in found["instances"].items()}
    check_eq("D0: two instances hold a result, the one never run is missing (no dispatch open)",
             (found["observed"], states), (True, {"test_alpha": "result", "test_beta": "result", "test_fresh": "missing"}))
    check("D0: a result names its outcome and the job", found["instances"]["test_alpha"]["outcome"] == "passed"
          and found["instances"]["test_alpha"]["job_id"])
    edit("test_b.py", "def test_beta():\n    assert 2 == 2", "def test_beta():\n    assert 2 >= 2")
    found = er.fresh_evidence(ROOT, TASK, ["TC-002"], cfg=config(), probe=run_suite.probe_runtime)
    check_eq("D0: an edited test is stale, and the first difference is named",
             ({i: v["state"] for i, v in found["instances"].items()}, "instance bytes" in found["instances"]["test_beta"]["why"]),
             ({"test_alpha": "result", "test_beta": "stale"}, True))
    found = er.fresh_evidence(ROOT, TASK, ["TC-002"], cfg=config(), probe=None)
    check_eq("D0: with no probe nothing is decided: unknown, observed False (FR-41)",
             (found["observed"], sorted({v["state"] for v in found["instances"].values()})), (False, ["unknown"]))
    (ROOT / "probe-fail.txt").write_text("down", encoding="utf-8")
    found = er.fresh_evidence(ROOT, TASK, ["TC-002"], cfg=config(), probe=run_suite.probe_runtime)
    check_eq("D0: a stand that cannot be looked at is unknown too, and does not raise",
             (found["observed"], sorted({v["state"] for v in found["instances"].values()})), (False, ["unknown"]))
    (ROOT / "probe-fail.txt").unlink()
    check_eq("D0: nothing was launched, begun or written", (len(launches()), count_jobs(), count_requests()),
             (d0_launches, d0_jobs, d0_requests))
    set_dispatch("running")

    # --- T7 (red, F4 c): one repeat of a red on identical inputs, then answered ---------------------
    code, out, err = call("--mine", "TC-003")
    check_eq("T7: a red run exits 1", (code, len(launches())), (1, base + 2))
    code, out, err = call("--mine", "TC-003")
    check_eq("T7: the 1st repeat launches (AT the boundary)", (code, len(launches())), (1, base + 3))
    code, out, err = call("--mine", "TC-003")
    answer = last_json(out)
    check_eq("T7: the 2nd is answered `already_run`, exit 0 (BEYOND)", (code, answer.get("status"), len(launches())),
             (0, "already_run", base + 3))
    check_in("T7: the words say what failed and how to read it", "test_red failed on", answer.get("words", ""))
    check_in("T7: naming the detail command", "run_suite.py --mine TC-003 --detail test_red", answer.get("words", ""))
    check_in("T7: and the person's word that passes it", BLOCK, answer.get("words", ""))
    code, out, err = call("--mine", "TC-003", "--again")
    check_eq("T7: `--again` does not repeat a red either", (last_json(out).get("status"), len(launches())),
             ("already_run", base + 3))

    # --- T8 (A3): the stand is looked at now --------------------------------------------------------
    call("--mine", "TC-005")
    base = len(launches())
    code, out, err = call("--mine", "TC-005")
    check_eq("T8: on the same stand the second call is answered", (last_json(out).get("status"), len(launches())),
             ("reused", base))
    (ROOT / "identity.txt").write_text("build-2", encoding="utf-8")
    code, out, err = call("--mine", "TC-005")
    check_eq("T8: after a redeploy the second call LAUNCHES (not invalid_request)", (code, len(launches())),
             (0, base + 1))
    check_in("T8: with the redeploy note", "the stand now runs build-2 (source source-1); the earlier results "
             "were recorded on build-1: they are not reused, this run is due.", err)
    code, out, err = call("--mine", "TC-005")
    check_eq("T8: and the new version's result then stands", (last_json(out).get("status"), len(launches())),
             ("reused", base + 1))
    (ROOT / "probe-fail.txt").write_text("down", encoding="utf-8")
    jobs_before, requests_before, base = count_jobs(), count_requests(), len(launches())
    code, out, err = call("--mine", "TC-005")
    refusal = last_json(out)
    check_eq("T8: a stand that cannot be looked at refuses, exit 2", (code, refusal.get("status")),
             (2, "mine_refused"))
    check_in("T8: in the stand's words", "cannot be observed right now", refusal.get("error", ""))
    check_in("T8: as the environment's, with the door", "`environment`; `stand_health.py --probe --env localhost`",
             refusal.get("error", ""))
    check_eq("T8: nothing launched, no job, no request file, no key",
             (len(launches()), count_jobs(), count_requests()), (base, jobs_before, requests_before))
    (ROOT / "probe-fail.txt").unlink()
    view, _notes, reusable, _v = er.build_mine_request(ROOT, ["TC-005"], cfg=config(), collect=None)
    check_eq("T8: with NO probe injected the request says the stand was not observed",
             view.get("runtime_observed"), False)
    check_eq("T8: and nothing is answered from results", reusable, None)
    job = next(j for j in store().jobs() if "test_deploy" in j["request"]["selected_instance_ids"]
               and j["request"]["runtime_provenance"]["observed_runtime_identity"] == "build-2")
    check_eq("T8: `covered` says so, in those words", er.covered(job, view, "test_deploy", policy=er.load_run_budget()[0]),
             (False, "the stand's version was not observed"))
    (ROOT / "identity.txt").write_text("build-1", encoding="utf-8")

    # --- T9: a job recorded before the code sha, and a comment ---------------------------------------
    call("--mine", "TC-007")
    legacy = next(j for j in store().jobs() if "test_legacy" in j["request"]["selected_instance_ids"])
    for contract in legacy["request"]["instance_contracts"].values():
        contract.pop("instance_code_sha", None)
    store().write(legacy)
    base = len(launches())
    code, out, err = call("--mine", "TC-007")
    check_eq("T9: a legacy job over unchanged bytes still answers (the raw rule)",
             (last_json(out).get("status"), len(launches())), ("reused", base))
    edit("test_g.py", "def test_legacy():\n", "def test_legacy():\n    # a comment\n")
    code, out, err = call("--mine", "TC-007")
    check_eq("T9: a comment edit reruns ONCE (no code sha on the old job)", (code, len(launches())), (0, base + 1))
    check("T9: and the new job carries both shas",
          all(c.get("instance_code_sha") for c in last_request("TC-007")["instance_contracts"].values()))
    edit("test_g.py", "    # a comment\n", "    # another comment\n")
    code, out, err = call("--mine", "TC-007")
    check_eq("T9: after that, a comment is reused", (last_json(out).get("status"), len(launches())),
             ("reused", base + 1))

    # --- T10 (A6): the FLAKY cap --------------------------------------------------------------------
    call("--mine", "TC-004")
    template = last_request("TC-004")
    node = template["command"]["selector_args"]["test_flake"][0]

    def flaky_request(key: str, case_template=None, instance="test_flake") -> Path:
        req = copy.deepcopy(case_template or template)
        req["purpose"] = "flaky_diagnostic"
        req["idempotency_key"] = key
        req["reason"] = "FLAKY confirmation, isolated rerun"
        req["execution"]["selection"] = {"reason": "diagnostic", "evidence_refs": [node]}
        req["remaining_budget"] = 10
        path = ROOT / f"{key}.json"
        write_json(path, req)
        return path

    def flaky_jobs(instance="test_flake") -> list:
        return [j for j in store().jobs() if j["request"].get("purpose") == "flaky_diagnostic"
                and instance in j["request"]["selected_instance_ids"]]

    set_pipeline("S5")
    jobs_before, base = count_jobs(), len(launches())
    code, out, err = call("--request", flaky_request("flaky-s5"))
    refusal = last_json(out)
    check_eq("T10: in stage S5 a flaky rerun is refused", (code, refusal.get("status")), (2, "run_refused"))
    check_in("T10: it says the reruns belong to S7", "flaky_diagnostic reruns belong to S7 triage (the story is in S5)",
             refusal.get("error", ""))
    check_eq("T10: nothing launched and no job begun", (len(launches()), count_jobs()), (base, jobs_before))
    set_pipeline("S7")
    two = copy.deepcopy(template)
    two["selected_instance_ids"] = ["test_flake", "test_extra"]
    two["current_scope_instance_ids"] = ["test_flake", "test_extra"]
    two["command"]["selector_args"]["test_extra"] = [node]
    two["instance_contracts"]["test_extra"] = dict(two["instance_contracts"]["test_flake"],
                                                   report_test_id="tests.test_d::test_extra")
    code, out, err = call("--request", flaky_request("flaky-two", two))
    check_eq("T10: two instances are refused", (code, last_json(out).get("status")), (2, "run_refused"))
    check_in("T10: 'a FLAKY rerun selects ONE failed test; this request selects 2'",
             "a FLAKY rerun selects ONE failed test; this request selects 2", last_json(out).get("error", ""))
    from contract import FLAKY_MIN_RERUNS as CAP
    for n in range(1, CAP + 1):
        code, out, err = call("--request", flaky_request(f"flaky-{n}"))
        check_eq(f"T10: rerun {n} of {CAP} launches", (code, len(flaky_jobs())), (0, n))
    check_not_in("T10: a flaky rerun loses the project's own --reruns (A7)", "--reruns", argvs()[-1])
    base = len(launches())
    code, out, err = call("--request", flaky_request("flaky-beyond"))
    refusal = last_json(out)
    check_eq(f"T10: rerun {CAP + 1} is refused (BEYOND the cap)", (code, refusal.get("status"), len(launches())),
             (2, "run_refused", base))
    check_in("T10: the series is complete - decide from it", f"{CAP} isolated reruns of test_flake are recorded",
             refusal.get("error", ""))
    check_in("T10: and names the jobs", flaky_jobs()[0]["job_id"], refusal.get("error", ""))
    # a person's word passes one request, not the series: an old word does not
    set_pipeline("S7", [word("S7", "said long ago", at="2000-01-01T00:00:00+00:00")])
    code, out, err = call("--request", flaky_request("flaky-oldword"))
    check_eq("T10: a word older than the last rerun does not pass the series", (code, len(launches())), (2, base))
    fresh_at = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(timespec="seconds")
    set_pipeline("S7", [word("S7", "one more, I am watching", at=fresh_at)])
    code, out, err = call("--request", flaky_request("flaky-word"))
    check_eq("T10: a person's word said after the last rerun passes the 4th", (code, len(launches())), (0, base + 1))
    check_in("T10: and the note records it", "passed on a person's word: one more, I am watching", err)
    set_pipeline("S7")
    # jobs with no result do not count
    call("--mine", "TC-016")
    nx_template = last_request("TC-016")
    stale_job = next(j for j in store().jobs() if "test_nx" in j["request"]["selected_instance_ids"])
    for n in range(CAP + 1):
        job = copy.deepcopy(stale_job)
        job["request"] = copy.deepcopy(nx_template)
        job["request"]["purpose"] = "flaky_diagnostic"
        job["request"]["idempotency_key"] = f"flaky-nx-{n}"
        job["idempotency_key"] = f"flaky-nx-{n}"
        job["job_id"] = f"nx{n}"
        job["execution_status"] = "not_executed"
        store().write(job)
    nx_node = nx_template["command"]["selector_args"]["test_nx"][0]
    template_nx = copy.deepcopy(nx_template)
    template_nx["execution"]["selection"] = {"reason": "diagnostic", "evidence_refs": [nx_node]}
    base = len(launches())
    path = ROOT / "flaky-nx.json"
    req = copy.deepcopy(template_nx)
    req.update(purpose="flaky_diagnostic", idempotency_key="flaky-nx-real", remaining_budget=10)
    write_json(path, req)
    code, out, err = call("--request", path)
    check_eq(f"T10: {CAP + 1} not_executed flaky jobs do not count: the rerun launches", (code, len(launches())),
             (0, base + 1))
    set_pipeline()

    # --- T11 (A5): the `--request` path -------------------------------------------------------------
    green_request = last_request("TC-001")
    green_request["idempotency_key"] = "hand-written-1"
    green_request["remaining_budget"] = 5
    path = ROOT / "hand-1.json"
    write_json(path, green_request)
    jobs_before, base = count_jobs(), len(launches())
    code, out, err = call("--request", path)
    answer = last_json(out)
    check_eq("T11: a fully covered `--request` is answered, exit 0",
             (code, answer.get("status"), len(launches())), (0, "reused", base))
    check_eq("T11: the JobStore directory count is unchanged", count_jobs(), jobs_before)
    fresh_view, _n, _r, _v = er.build_mine_request(ROOT, ["TC-008"], cfg=config(), probe=run_suite.probe_runtime,
                                                   collect=None)
    partial = copy.deepcopy(green_request)
    partial["idempotency_key"] = "hand-written-2"
    partial["selected_instance_ids"] = ["test_green", "test_fresh"]
    partial["current_scope_instance_ids"] = ["test_green", "test_fresh"]
    partial["command"]["selector_args"]["test_fresh"] = fresh_view["command"]["selector_args"]["test_fresh"]
    partial["instance_contracts"]["test_fresh"] = fresh_view["instance_contracts"]["test_fresh"]
    path = ROOT / "hand-2.json"
    write_json(path, partial)
    code, out, err = call("--request", path)
    refusal = last_json(out)
    check_eq("T11: a partly covered `--request` is refused, exit 2", (code, refusal.get("status")), (2, "run_refused"))
    check_in("T11: the message lists the covered ids", "test_green: a result over these same bytes already exists",
             refusal.get("error", ""))
    check_in("T11: takes them out of the request and names the person's door",
             f"take them out of selected_instance_ids and run the rest; a person's word passes it (waiver.py, "
             f"stage S5, block \"{BLOCK}\")", refusal.get("error", ""))
    check_eq("T11: nothing launched, no job, no key", (len(launches()), count_jobs()), (base, jobs_before))
    set_pipeline(overrides=[word(decision="both, I checked")])
    code, out, err = call("--request", path)
    check_eq("T11: a person's word passes it", (code, len(launches())), (0, base + 1))
    set_pipeline()

    # --- T12 (A10): the scheduler's label -----------------------------------------------------------
    from execution_scheduler import execute_schedule
    red_first = json.loads(request_files("TC-003")[0].read_text(encoding="utf-8"))
    green_first = json.loads(request_files("TC-001")[0].read_text(encoding="utf-8"))
    receipt = execute_schedule({"requests": [red_first, green_first], "source_revision": "r1"}, ROOT,
                               Path(run_suite.__file__).resolve())
    labels = {row["selected_ids"][0]: row["status"] for row in receipt["groups"]}
    check_eq("T12: an existing completed FAILED key is `already_run`, not `reused`; a passed one is `reused`",
             labels, {"test_red": "already_run", "test_green": "reused"})

    # --- T13 (A9): no run-budget.json ----------------------------------------------------------------
    with budget_data(__absent__=True):
        before, jobs_before = len(launches()), count_jobs()
        code, out, err = call("--mine", "TC-017")
        check_eq("T13: the run proceeds without the data file", (code, len(launches())), (0, before + 1))
        check_eq("T13: with ONE note saying the budget is not enforced",
                 err.count("run-budget.json unreadable"), 1)
        check_in("T13: in those words", "the run budget is not enforced for this run", err)
        code, out, err = call("--mine", "TC-017", "--again")
        check_eq("T13: as before the budget, `--again` repeats a green", (code, len(launches())), (0, before + 2))
        code, out, err = call("--mine", "TC-017")
        check_eq("T13: and the pre-budget whole-run reuse still answers", (last_json(out).get("status"), len(launches())),
                 ("reused", before + 2))
        check_in("T13 (F2): and in that mode its hint names `--again`, which works there",
                 "`--again` runs it once more", last_json(out).get("hint", ""))
        req_path = ROOT / "hand-3.json"
        request = last_request("TC-017")
        request.update(idempotency_key="hand-written-3", remaining_budget=5)
        write_json(req_path, request)
        code, out, err = call("--request", req_path)
        check_eq("T13: a `--request` is not answered either: it runs, with the note",
                 (code, len(launches()), err.count("run-budget.json unreadable")), (0, before + 3, 1))
        # the stand re-observation is a budget feature too
        check("T13: no `runtime_observed` flag when the budget is not enforced",
              "runtime_observed" not in last_request("TC-017"))

    # --- T14 (A7): the rerun flags of a probe --------------------------------------------------------
    call("--mine", "TC-009")
    check_in("T14: an `initial` run keeps the project's `--reruns 2`", "--reruns 2 --reruns-delay 1", argvs()[-1])
    code, out, err = call("--mine", "TC-009", "--purpose", "red_probe", "--cwd", ROOT)
    check_eq("T14: a red_probe launches", code, 0)
    check_not_in("T14: a red_probe run has no `--reruns` in its launched argv", "--reruns", argvs()[-1])
    check_in("T14: and says what it removed", "removed `--reruns 2, --reruns-delay 1` from this red_probe run", err)
    check_in("T14: and why", "a probe must fail once", err)

    part_three()
    part_b()


# --- part 3: the switches an owner's answer would flip, as data only ---------------------------------

def part_three() -> None:
    # F4: how many failed results make a red final (1 = at once, 0 = never)
    with budget_data(failed_result_policy={"covers_after_failures": 1}):
        base = len(launches())
        call("--mine", "TC-011")
        code, out, err = call("--mine", "TC-011")
        check_eq("F4 (data 1): a red is final after one: the 2nd call is answered",
                 (last_json(out).get("status"), len(launches())), ("already_run", base + 1))
    with budget_data(failed_result_policy={"covers_after_failures": 0}):
        base = len(launches())
        for _ in range(3):
            call("--mine", "TC-012")
        check_eq("F4 (data 0): a red is never final: all three calls launch", len(launches()), base + 3)

    # F5: one run per code version (default) or per story
    call("--mine", "TC-013")
    base = len(launches())
    edit("test_m.py", "assert 1 == 1", "assert 1 >= 1")
    with budget_data(author_run_reading="per_story"):
        code, out, err = call("--mine", "TC-013")
        check_eq("F5 (data per_story): an edited test is still answered by its earlier result",
                 (last_json(out).get("status"), len(launches())), ("reused", base))
    code, out, err = call("--mine", "TC-013")
    check_eq("F5 (shipped per_code_version): the edited bytes are the first run of those bytes",
             (code, len(launches())), (0, base + 1))

    # F8: which purposes lose the rerun flags
    with budget_data(strip_reruns_purposes=["initial", "repair_verify", "red_probe", "flaky_diagnostic",
                                            "diagnostic"]):
        call("--mine", "TC-014")
        check_not_in("F8 (data: every behavioral purpose): an `initial` run loses `--reruns` too",
                     "--reruns", argvs()[-1])
    with budget_data(strip_reruns_purposes=[]):
        call("--mine", "TC-015")
        code, out, err = call("--mine", "TC-015", "--purpose", "red_probe", "--cwd", ROOT)
        check_in("F8 (data: empty list): the project's own command is left alone", "--reruns 2", argvs()[-1])
        check_not_in("F8 (data: empty list): and there is no note", "removed `--reruns", err)

    # F10: a person repaired the stand
    del sys.modules["stand_health"]  # `absent_modules()` had put None there
    try:
        import stand_health  # the real one, for this scenario alone
        call("--mine", "TC-010")
        call("--mine", "TC-010")
        base = len(launches())
        code, out, err = call("--mine", "TC-010")
        check_eq("F10 control: two reds on identical bytes are answered", (last_json(out).get("status"), len(launches())),
                 ("already_run", base))
        for job in store().jobs():
            if "test_j_red" in job["request"]["selected_instance_ids"]:
                job["created_at"] = "2026-01-01T00:00:00+00:00"
                store().write(job)
        stand_health.reset(ROOT, "the person restarted the stand")
        code, out, err = call("--mine", "TC-010")
        check_eq("F10 (a): after `stand_health.py --reset` the reds are not results: the test runs",
                 (code, len(launches())), (1, base + 1))
    finally:
        sys.modules["stand_health"] = None


PROVENANCE = {"profile_id": "api", "timestamp": "2026-09-22T10:00:00Z", "environment_id": "localhost",
              "expected_source_revision": "source-1", "observed_runtime_identity": "build-1",
              "evidence_refs": ["probe"], "result": "matched",
              "provenance": {"technical_verification": True, "source_linkage": "exact",
                             "deployed_source_revision": "source-1"}}


def template_flaky(key: str, n: int) -> Path:
    """A flaky request filled in from the `--template request` skeleton by hand: no instance shas
    anywhere, and a whole input fingerprint of its own every time - the request that used to
    slip past a cap counted by bytes."""
    from execution_fingerprint import file_hash
    request = run_suite.template("request")[0]
    test_file, config_file = ROOT / "tests" / "test_u.py", ROOT / "qa-factory" / "config.json"
    node = "tests/test_u.py::test_tpl"
    request.pop("target_kind", None)
    request["command"].pop("repo_id", None)
    request["command"].pop("report_path", None)
    request.update({
        "task": TASK, "revision": "41", "dispatch_id": "S5-qa-automator-1", "profile_id": "api",
        "purpose": "flaky_diagnostic", "reason": "isolated rerun", "idempotency_key": key,
        "input_fingerprint": f"template-fingerprint-{n}",
        "fingerprint_components": {"source_sha": "source-1", "test_content_sha": "t" * 8, "config_sha": "c" * 8},
        "fingerprint_files": [{"path": str(test_file), "sha256": file_hash(test_file), "kind": "test_files"},
                              {"path": str(config_file), "sha256": file_hash(config_file), "kind": "config_files"}],
        "remaining_budget": 5, "selected_instance_ids": ["test_tpl"], "current_scope_instance_ids": ["test_tpl"],
        "runtime_provenance": dict(PROVENANCE),
        "runtime_probe": {"argv": [PY, str(ROOT / "probe.py")], "cwd": ".", "timeout_s": 20},
        "command": {"argv": [PY, str(ROOT / "fake" / "pytest"), "--reruns", "2"], "cwd": ".",
                    "reporter": "pytest", "scope": "selected", "selector_contract_verified": True,
                    "selector_args": {"test_tpl": [node]}},
        "instance_contracts": {"test_tpl": {"report_test_id": "tests.test_u::test_tpl", "parameters": {}}},
        "execution": {"schema_version": 1, "reporter": {"format": "pytest", "path_template": "{report_path}"},
                      "selection": {"reason": "diagnostic", "evidence_refs": [node]}}})
    path = ROOT / f"{key}.json"
    write_json(path, request)
    return path


def as_flaky(template: dict, key: str) -> Path:
    request = copy.deepcopy(template)
    request.update(purpose="flaky_diagnostic", idempotency_key=key, reason="isolated rerun", remaining_budget=10)
    request["execution"]["selection"] = {"reason": "diagnostic", "evidence_refs": ["x"]}
    path = ROOT / f"{key}.json"
    write_json(path, request)
    return path


def part_b() -> None:
    from contract import FLAKY_MIN_RERUNS as CAP
    fail_flag = ROOT / "fail-flip.txt"

    # --- B1: the newest result over the same inputs decides ------------------------------------------
    code, out, err = call("--mine", "TC-018")
    check_eq("B1: a green run", code, 0)
    base = len(launches())
    fail_flag.write_text("the stand is flaky now", encoding="utf-8")
    backdate("test_flip", "2026-09-01T00:00:00+00:00")
    set_pipeline(overrides=[word(decision="I saw it fail, run it again", at="2026-09-02T00:00:00+00:00")])
    code, out, err = call("--mine", "TC-018")
    check_eq("B1: a person's word repeats it and it goes RED on the same bytes", (code, len(launches())),
             (1, base + 1))
    set_pipeline()
    code, out, err = call("--mine", "TC-018")
    check_eq("B1: the older green no longer answers: a newer red over the same bytes is run again (not `passed`)",
             (code, last_json(out).get("status"), len(launches())), (1, None, base + 2))
    code, out, err = call("--mine", "TC-018")
    check_eq("B1: and once the red has had its one repeat it is answered as what it is: `already_run`",
             (code, last_json(out).get("status"), len(launches())), (0, "already_run", base + 2))
    code, out, err = call("--mine", "TC-019")
    check_eq("B1: red first (a flake on the stand)", (code, len(launches())), (1, base + 3))
    fail_flag.unlink()
    code, out, err = call("--mine", "TC-019")
    check_eq("B1: its one repeat is allowed and goes green", (code, len(launches())), (0, base + 4))
    code, out, err = call("--mine", "TC-019")
    check_eq("B1: red then green ends GREEN: the newest result is the answer", (last_json(out).get("status"),
             len(launches())), ("reused", base + 4))

    # --- a part the classifier cannot tell: NO code sha for the instance, the raw rule only ----------
    # `diff_scope.executable_sha` answers "" for a fragment that does not tokenize. A fragment of
    # this test file is made to (the stand-in below), and the instance must then have no code sha at
    # all - not a stable hash of "" that two different edits would share - so a comment edit, which
    # a code sha would have forgiven, is an edit again and the test runs.
    import execution_fingerprint as ef
    real_sha = ef.executable_sha
    ef.executable_sha = lambda text, name="": "" if "UNTOKENIZABLE" in text else real_sha(text, name)
    try:
        call("--mine", "TC-024")
        base = len(launches())
        check_eq("an instance with an untokenizable part has NO code sha",
                 [c.get("instance_code_sha") for c in last_request("TC-024")["instance_contracts"].values()], [""])
        edit("test_x.py", "def test_frag():\n", "def test_frag():\n    # only a comment\n")
        code, out, err = call("--mine", "TC-024")
        check_eq("and a comment edit then LAUNCHES (the raw rule): it is not answered `reused`",
                 (code, last_json(out).get("status"), len(launches())), (0, None, base + 1))
        code, out, err = call("--mine", "TC-024")
        check_eq("while the very same bytes are still answered (the raw rule holds)",
                 (last_json(out).get("status"), len(launches())), ("reused", base + 1))
    finally:
        ef.executable_sha = real_sha

    # --- B2: a skipped instance is not a result ------------------------------------------------------
    code, out, err = call("--mine", "TC-020")
    base = len(launches())
    job = next(j for j in store().jobs() if "test_skipme" in j["request"]["selected_instance_ids"])
    block = json.loads((ROOT / str(job["run_block"]).replace("\\", "/")).read_text(encoding="utf-8"))
    check_eq("B2: the run passed as a JOB while its own row for the test says skipped",
             (job["execution_status"], [r["status"] for r in block["results"]]), ("passed", ["skipped"]))
    code, out, err = call("--mine", "TC-020")
    check_eq("B2: so the next call is NOT answered `reused`: the skipped test is run", (code, len(launches())),
             (0, base + 1))
    check("B2: nor is what it printed an answer", last_json(out).get("status") not in {"reused", "already_run"})

    # --- B3: the FLAKY cap holds for a request written from the template (no shas) --------------------
    set_pipeline("S7")
    for n in range(1, CAP + 1):
        code, out, err = call("--request", template_flaky(f"tpl-flaky-{n}", n))
        check_eq(f"B3: template-shaped rerun {n} of {CAP} launches", (code, last_json(out).get("status")),
                 (0, None))
    base = len(launches())
    code, out, err = call("--request", template_flaky("tpl-flaky-beyond", 99))
    check_eq(f"B3: the {CAP + 1}th is refused, though its bytes cannot be told and its fingerprint is new",
             (code, last_json(out).get("status"), len(launches())), (2, "run_refused", base))
    check_in("B3: counted by the instance id", f"{CAP} isolated reruns of test_tpl are recorded", last_json(out).get("error", ""))
    set_pipeline()

    # --- F3: an unobserved stand is never answered `reused` -------------------------------------------
    unseen, _n, _r, _v = er.build_mine_request(ROOT, ["TC-022"], cfg=config(), probe=None)
    seen, _n, _r, _v = er.build_mine_request(ROOT, ["TC-022"], cfg=config(), probe=run_suite.probe_runtime)
    check_eq("F3: with no probe the request says the stand was not observed", unseen.get("runtime_observed"), False)
    check("F3: and takes a key of its own, not the key of the observed request",
          unseen["idempotency_key"] != seen["idempotency_key"])
    call("--mine", "TC-022")
    blind = last_request("TC-022")
    blind.update(idempotency_key="blind-1", runtime_observed=False, remaining_budget=5)
    path = ROOT / "blind-1.json"
    write_json(path, blind)
    base = len(launches())
    code, out, err = call("--request", path)
    check_eq("F3: an unobserved `--request` is not answered from an observed result: it runs",
             (code, len(launches())), (0, base + 1))
    code, out, err = call("--request", path)
    check_eq("F3: the same key again is NOT answered `reused` through the existing-key branch",
             (code, last_json(out).get("status"), len(launches())), (2, "run_refused", base + 1))
    check_in("F3: it says the stand was not observed and where to look", "was not observed for this request",
             last_json(out).get("error", ""))
    check_in("F3: with the door", "stand_health.py --probe --env localhost", last_json(out).get("error", ""))

    # --- F4: the FLAKY counter honours a stand reset --------------------------------------------------
    call("--mine", "TC-023")
    red_template = last_request("TC-023")
    set_pipeline("S7")
    for n in range(1, CAP + 1):
        code, out, err = call("--request", as_flaky(red_template, f"red-flaky-{n}"))
    base = len(launches())
    code, out, err = call("--request", as_flaky(red_template, "red-flaky-beyond"))
    check_eq("F4 control: three failed isolated reruns are the series: the next is refused",
             (code, last_json(out).get("status"), len(launches())), (2, "run_refused", base))
    del sys.modules["stand_health"]
    try:
        import stand_health
        for job in store().jobs():
            if "test_w_red" in job["request"]["selected_instance_ids"]:
                job["created_at"] = job["updated_at"] = "2026-01-01T00:00:00+00:00"
                store().write(job)
        stand_health.reset(ROOT, "the person repaired the stand")
        code, out, err = call("--request", as_flaky(red_template, "red-flaky-after-reset"))
        check_eq("F4: after `stand_health.py --reset` the earlier reds are not counted: the rerun launches",
                 (code, len(launches())), (1, base + 1))
    finally:
        sys.modules["stand_health"] = None
    set_pipeline()


# --- part 4 (t-055): the adversarial battery, end to end ------------------------------------------------
# t-049: a per-LINE reading of "cosmetic" called `"alice",` in an assert's list, a URL argument on its
# own line, a `// 2` continuation and a literal's last line prose, so an edit of them was reused.
# Every scenario is one file with one case: run once, edit, ask again. A code change must LAUNCH
# (a result over other code is never reused); a cosmetic one must be answered `reused`.

def part_battery() -> None:
    files = {
        "test_ba.py": ("def test_bat_list():\n    names = ['alice', 'bob']\n    assert names == [\n"
                       "        \"alice\",\n        \"bob\",\n    ]\n"),
        "test_bb.py": ("def test_bat_url():\n    response = fetch(\n        \"https://example.test/api/v1/items\",\n"
                       "        {\"limit\": 10},\n    )\n    assert response\n\n\ndef fetch(*args):\n    return args\n"),
        "test_bc.py": ("def test_bat_backslash():\n    base = 8\n    value = base \\\n        // 2\n"
                       "    total = 1 + \\\n        2\n    assert value and total\n"),
        "test_bd.py": ("def test_bat_triple():\n    text = 'a'\n    assert text in \"\"\"\nalpha\n\"\"\"\n"),
        "test_be.py": "import pytest\n\n\ndef test_bat_mark():\n    assert True\n",
        "test_bf.py": "LIMIT = 10\nOTHER = 1\n\n\ndef test_bat_const():\n    assert LIMIT > 1\n",
        "test_bg.py": "def test_bat_fixture(bat_value):\n    assert bat_value == 1\n",
        "test_bh.py": ("import pytest\n\n\ndef test_bat_cosmetic():\n    value = 1\n"
                       "    assert value == pytest.approx(1)\n"),
        "test_bi.py": ("import pytest\n\n\nclass TestBatMethod:\n    def test_bat_method(self):\n"
                       "        value = 1\n        assert value == 1\n"),
        "test_bj.py": ("import pytest\n\n\n@pytest.mark.usefixtures(\"bat_value\")\nclass TestBatHolder:\n"
                       "    def test_bat_holder(self):\n        value = 1\n        assert value == 1\n"),
        "test_bk.py": ("class TestBatOuter:\n    class TestBatInner:\n        def test_bat_nested(self):\n"
                       "            value = 1\n            assert value == 1\n"),
        "test_bl.py": ("import pytest\n\nCONST = 1\n\n\ndef test_d5a():\n    assert CONST == 1\n\n\n"
                       "def test_d5b():\n    assert CONST == 2\n"),
    }
    cases = {"TC-101": ("test_ba.py", "test_bat_list"), "TC-102": ("test_bb.py", "test_bat_url"),
             "TC-103": ("test_bc.py", "test_bat_backslash"), "TC-104": ("test_bd.py", "test_bat_triple"),
             "TC-105": ("test_be.py", "test_bat_mark"), "TC-106": ("test_bf.py", "test_bat_const"),
             "TC-107": ("test_bg.py", "test_bat_fixture"), "TC-108": ("test_bh.py", "test_bat_cosmetic"),
             "TC-109": ("test_bi.py", "TestBatMethod::test_bat_method"),
             "TC-110": ("test_bj.py", "TestBatHolder::test_bat_holder"),
             "TC-111": ("test_bk.py", "TestBatOuter::TestBatInner::test_bat_nested"),
             "TC-112": ("test_bl.py", "test_d5a | test_d5b")}
    for name, text in files.items():
        (ROOT / "tests" / name).write_text(text, encoding="utf-8")
    with (ROOT / "tests" / "conftest.py").open("a", encoding="utf-8") as handle:
        handle.write("\nimport pytest\n\n\n@pytest.fixture\ndef bat_value():\n    return 1\n")
    MANIFEST.update(cases)
    write_json(TASK_ROOT / "work" / "automation-manifest.json", {"tests": [
        {"case": case, "file": f"tests/{file}", "selector": selector} for case, (file, selector) in MANIFEST.items()]})
    set_dispatch("running")
    set_pipeline()

    def launched(case: str, label: str) -> None:
        """The case is run once, so its bytes have a result to be compared with."""
        before = len(launches())
        code, out, err = call("--mine", case)
        check_eq(f"battery {label}: the first run launches", (code, len(launches())), (0, before + 1))

    def edit_then(case: str, label: str, name: str, old: str, new: str, expect: str) -> None:
        """Edit, ask again: `launch` runs the test once more, `reused` answers from the result."""
        before = len(launches())
        edit(name, old, new)
        code, out, err = call("--mine", case)
        if expect == "launch":
            check_eq(f"battery {label}: a code change LAUNCHES (never reused)", (code, len(launches())),
                     (0, before + 1))
        else:
            check_eq(f"battery {label}: a cosmetic change is `reused`",
                     (last_json(out).get("status"), len(launches())), ("reused", before))

    # --- code edits the line reading forgave: every one launches --------------------------------------
    launched("TC-101", "list")
    edit_then("TC-101", "a list element on an assert's continuation line", "test_ba.py",
              '        "bob",\n', '        "carol",\n', "launch")
    launched("TC-102", "url")
    edit_then("TC-102", "a URL argument line inside a multi-line call", "test_bb.py",
              "/api/v1/items", "/api/v2/items", "launch")
    edit_then("TC-102", "a dict argument line inside the same call", "test_bb.py",
              '{"limit": 10}', '{"limit": 11}', "launch")
    launched("TC-103", "backslash")
    edit_then("TC-103", "a `// 2` continuation line", "test_bc.py", "        // 2\n", "        // 3\n", "launch")
    edit_then("TC-103", "a backslash continuation's operand", "test_bc.py",
              "1 + \\\n        2", "1 + \\\n        5", "launch")
    launched("TC-104", "triple")
    edit_then("TC-104", "an assert ending in an edited triple-quoted literal", "test_bd.py",
              "\nalpha\n", "\nbeta\n", "launch")
    launched("TC-105", "pytestmark")
    edit_then("TC-105", "module-level `pytestmark = pytest.mark.skip` added", "test_be.py",
              "import pytest\n", "import pytest\n\npytestmark = pytest.mark.skip\n", "launch")
    edit_then("TC-105", "the same `pytestmark` edited", "test_be.py",
              "pytest.mark.skip", "pytest.mark.xfail", "launch")
    edit_then("TC-105", "a module-level comment beside it", "test_be.py",
              "\npytestmark", "\n# why the whole module is off\npytestmark", "reused")
    launched("TC-106", "constant")
    edit_then("TC-106", "a module-level constant the test uses", "test_bf.py", "LIMIT = 10", "LIMIT = 11", "launch")
    edit_then("TC-106", "a module-level constant it does not use (the skeleton rule)", "test_bf.py",
              "OTHER = 1", "OTHER = 2", "launch")
    call("--mine", "TC-107")
    check_eq("battery fixture: the first run launched", len(launches()) > 0 and launches()[-1].split(),
             ["tests/test_bg.py::test_bat_fixture"])
    before = len(launches())
    edit("conftest.py", "def bat_value():\n    return 1", "def bat_value():\n    return 2")
    code, out, err = call("--mine", "TC-107")
    check_eq("battery: a conftest fixture's return value changed LAUNCHES", (code, len(launches())), (0, before + 1))

    # --- the cosmetic side: reused ----------------------------------------------------------------------
    launched("TC-108", "cosmetic")
    edit_then("TC-108", "a comment inside the test body", "test_bh.py",
              "    value = 1\n", "    # why one\n    value = 1\n", "reused")
    edit_then("TC-108", "a module-level comment", "test_bh.py",
              "import pytest\n", "# a note for the whole module\nimport pytest\n", "reused")
    edit_then("TC-108", "the factory marker added", "test_bh.py", "def test_bat_cosmetic",
              "@pytest.mark.qa(\n    case=\"TC-108\",\n)\ndef test_bat_cosmetic", "reused")
    edit_then("TC-108", "the factory marker edited", "test_bh.py",
              'case="TC-108"', 'case="TC-108", version="cv_2"', "reused")
    edit_then("TC-108", "and then a real assert", "test_bh.py", "pytest.approx(1)", "pytest.approx(2)", "launch")

    # --- class shapes ------------------------------------------------------------------------------------
    from execution_fingerprint import function_sha
    for case, label, name, chain, function in (
            ("TC-109", "a method in a class", "test_bi.py", ("TestBatMethod",), "test_bat_method"),
            ("TC-110", "a method of a decorated holder class", "test_bj.py", ("TestBatHolder",), "test_bat_holder"),
            ("TC-111", "a nested class", "test_bk.py", ("TestBatOuter", "TestBatInner"), "test_bat_nested")):
        try:
            found = function_sha(ROOT / "tests" / name, function, chain, [str(ROOT / "tests" / "conftest.py")])
            check(f"battery {label}: function_sha does not raise and has a function scope, both shas",
                  found["scope"] == "function" and found["sha"] and found["code_sha"])
        except Exception as exc:  # noqa: BLE001 - the point is that nothing escapes
            check(f"battery {label}: function_sha raised {exc!r}", False)
        launched(case, label)
        pad = " " * (4 * (len(chain) + 1))
        edit_then(case, label, name, pad + "value = 1\n", pad + "# why one\n" + pad + "value = 1\n", "reused")
        edit_then(case, label, name, "assert value == 1", "assert value >= 1", "launch")
    edit_then("TC-110", "a decorated holder class: its decorator edited", "test_bj.py",
              '"bat_value"', '"bat_value", "bat_value"', "launch")

    # --- D5: editing test_b of a file with test_a and test_b runs test_b and only test_b -------------------
    call("--mine", "TC-112")
    check_eq("battery D5: the first run carries both", launches()[-1].split(),
             ["tests/test_bl.py::test_d5a", "tests/test_bl.py::test_d5b"])
    before = len(launches())
    edit("test_bl.py", "    assert CONST == 2", "    assert CONST >= 2")
    code, out, err = call("--mine", "TC-112")
    check_eq("battery D5: `--mine` of the case launches exactly test_d5b", (launches()[-1].split(), len(launches())),
             (["tests/test_bl.py::test_d5b"], before + 1))
    check_eq("battery D5: the request selects only test_d5b, and records test_d5a as not run again",
             (last_request("TC-112")["selected_instance_ids"], sorted(last_request("TC-112").get("not_run_again") or {})),
             (["test_d5b"], ["test_d5a"]))
    edit("test_bl.py", "import pytest\n", "import pytest\n\npytestmark = pytest.mark.skip\n")
    code, out, err = call("--mine", "TC-112")
    check_eq("battery D5: a module-wide skip added launches BOTH again",
             (launches()[-1].split(), len(launches())),
             (["tests/test_bl.py::test_d5a", "tests/test_bl.py::test_d5b"], before + 2))

    # --- an unread file is no identity: a file of the run that cannot be read is never covered ---------
    # The whole-input fingerprint cannot be built over a file that is not there, so `--mine` refuses
    # before it; what is left is a helper that vanishes between the listing and the measuring. It is
    # made to vanish here: the measurer is handed one more helper path that is not on disk.
    import execution_fingerprint as ef
    (ROOT / "tests" / "test_bm.py").write_text("def test_bat_unread():\n    value = 1\n    assert value == 1\n",
                                               encoding="utf-8")
    MANIFEST["TC-113"] = ("test_bm.py", "test_bat_unread")
    write_json(TASK_ROOT / "work" / "automation-manifest.json", {"tests": [
        {"case": case, "file": f"tests/{file}", "selector": selector} for case, (file, selector) in MANIFEST.items()]})
    set_dispatch("running")  # its scope is the manifest's cases at the time it is written
    launched("TC-113", "unread helper")
    edit_then("TC-113", "control: a comment while every file is readable", "test_bm.py",
              "    value = 1\n", "    # one\n    value = 1\n", "reused")
    real_function_sha = ef.function_sha
    ef.function_sha = lambda path, function, chain=(), helpers=(), cache=None: real_function_sha(
        path, function, chain, list(helpers) + [str(ROOT / "tests" / "vanished_helper.py")], cache)
    try:
        edit_then("TC-113", "the same kind of edit with one helper unreadable: no identity, the run is due",
                  "test_bm.py", "    value = 1\n", "    # two\n    value = 1\n", "launch")
        check_eq("battery: and the instance carries no sha at all, not the sha of nothing",
                 [(c.get("instance_content_sha"), c.get("instance_code_sha"))
                  for c in last_request("TC-113")["instance_contracts"].values()], [("", "")])
    finally:
        ef.function_sha = real_function_sha
    edit_then("TC-113", "readable again: the earlier readable result answers a comment", "test_bm.py",
              "    value = 1\n", "    # three\n    value = 1\n", "reused")

    # --- round 2 (critic t-066): what the identity must still see, and what it must forgive -------------
    round_two = {
        # a form feed line above the test: `str.splitlines` broke there and the test's last line fell off
        "test_bn.py": ("\x0c\n\ndef test_bat_ff():\n    value = 1\n    assert value == 1\n", "TC-114", "test_bat_ff"),
        # a test that never mentions pytest: the factory's marker must not add `import pytest` to it
        "test_bo.py": ("import pytest\n\n\ndef test_bat_marker():\n    assert 1 == 1\n", "TC-115", "test_bat_marker"),
        # Python runs the LAST definition
        "test_bp.py": ("def test_bat_dup():\n    assert 1 == 1\n\n\ndef test_bat_dup():\n    assert 2 == 2\n",
                       "TC-116", "test_bat_dup"),
    }
    for name, (text, case, selector) in round_two.items():
        (ROOT / "tests" / name).write_text(text, encoding="utf-8")
        MANIFEST[case] = (name, selector)
    write_json(TASK_ROOT / "work" / "automation-manifest.json", {"tests": [
        {"case": case, "file": f"tests/{file}", "selector": selector} for case, (file, selector) in MANIFEST.items()]})
    set_dispatch("running")
    launched("TC-114", "form feed")
    edit_then("TC-114", "a comment in the conftest of the directory is cosmetic", "conftest.py",
              "# fixtures\n", "# fixtures, and a note\n", "reused")
    edit_then("TC-114", "a code edit under a form feed line above the test", "test_bn.py",
              "assert value == 1", "assert value == 2", "launch")
    launched("TC-115", "marker")
    edit_then("TC-115", "the factory marker added to a test that never mentions pytest", "test_bo.py",
              "def test_bat_marker", '@pytest.mark.qa(case="TC-115")\ndef test_bat_marker', "reused")
    edit_then("TC-115", "the factory marker removed", "test_bo.py",
              '@pytest.mark.qa(case="TC-115")\n', "", "reused")
    edit_then("TC-115", "@pytest.mark.skip added to it", "test_bo.py",
              "def test_bat_marker", "@pytest.mark.skip\ndef test_bat_marker", "launch")
    launched("TC-116", "duplicate")
    edit_then("TC-116", "the second, effective, definition edited", "test_bp.py", "assert 2 == 2", "assert 2 == 3",
              "launch")
    edit_then("TC-116", "a code edit in the conftest of the directory runs every test under it", "conftest.py",
              "@pytest.fixture\ndef bat_value():\n    return 2", "@pytest.fixture\ndef bat_value():\n    return 3",
              "launch")


def part_not_found() -> None:
    """B-E5 / M-B11 (HF2-10): an `--node-id` of an existing file whose function is not there is no longer collected; pytest
    says `not found` (exit 4) and the run answers `node_id_mismatch`, `not_executed`. That run spent its key and is NOT a
    result of the test: it is neither a green that covers a repeat nor a red that counts towards `already_run`."""
    (ROOT / "tests" / "test_hf.py").write_text("def test_hf_green():\n    assert True\n", encoding="utf-8")
    MANIFEST["TC-201"] = ("test_hf.py", "test_hf_green")
    write_json(TASK_ROOT / "work" / "automation-manifest.json", {"tests": [
        {"case": case, "file": f"tests/{file}", "selector": selector} for case, (file, selector) in MANIFEST.items()]})
    set_dispatch("running")
    set_pipeline()
    ghost = "tests/test_hf.py::test_hf_ghost"
    before, jobs_before = len(launches()), count_jobs()
    code, out, err = call("--mine", "TC-201", "--node-id", ghost, "--again")
    answer = last_json(out)
    check_eq("M-B11: --node-id of a function that is not there: pytest's exit 4, answered node_id_mismatch, not executed",
             (code, answer.get("blocked"), answer.get("execution_status")), (4, "node_id_mismatch", "not_executed"))
    check_eq("B-E5: the key was spent: the run was launched and a job recorded", (len(launches()), count_jobs()),
             (before + 1, jobs_before + 1))
    job = store().jobs()[-1]
    instance = job["request"]["selected_instance_ids"][0]
    policy = er.load_run_budget()[0]
    outcome, why = er._job_outcome(job, instance, set(policy["result_purposes"]), "", None)
    check_eq("M-B11: that job holds NO result of the test (not a pass, not a failure)", outcome, "")
    check_in("M-B11: ... and the reason says what it ended", "ended not_executed", why)
    code, out, err = call("--mine", "TC-201", "--node-id", ghost, "--again")
    check_eq("B-E5: asking again runs again: not `reused`, not `already_run`, not `duplicate`",
             (code, last_json(out).get("status"), len(launches())), (4, None, before + 2))
    first_key = job["idempotency_key"]
    code, out, err = call("--mine", "TC-201", "--node-id", "tests/test_hf.py::test_hf_green", "--again")
    check_eq("B-E5: the corrected id has another selector and another key, not `duplicate`, and passes",
             (code, last_json(out).get("execution_status"), store().jobs()[-1]["idempotency_key"] != first_key),
             (0, "passed", True))


def main() -> None:
    os.environ["CLAUDE_PROJECT_DIR"] = str(ROOT)
    os.environ["QA_FACTORY_SKIP_DASHBOARD_REFRESH"] = "1"
    try:
        part_one()
        setup_project()
        absent_modules()
        part_two()
        part_battery()
        part_not_found()
    finally:
        for name in ("node_ids", "stand_lease", "stand_health"):
            sys.modules.pop(name, None)
        shutil.rmtree(ROOT, ignore_errors=True)
    finish("test_run_budget")


if __name__ == "__main__":
    main()
