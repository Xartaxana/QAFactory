#!/usr/bin/env python3
"""TQ1-11: the roles that write and judge tests are told, by path and by state, the approach the project recorded at onboarding.

K1/K2 `config_contract.test_data_states` (the one reader of `test_data`), K3-K7 the brief lines of the S3 strategist, the S5
automator and the code critic, K8 the code judge's state, K9 the judge's question text, K10 the role and rubric text.
The keys of K9 and K10 are quoted from the spec (t-636 as amended by the plan critic t-646: B-1, B-2) BEFORE the run.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import brief_pack  # noqa: E402
import config_contract as CC  # noqa: E402
import hooklib  # noqa: E402
import judge  # noqa: E402
import judge_code as J  # noqa: E402

PLUGIN = harness.PLUGIN_ROOT
ROLES = {"qa-test-strategist": "S3", "qa-automator": "S5", "qa-code-critic": "S5"}


def put_config(root: Path, **blocks) -> None:
    path = root / "qa-factory/config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    for key, value in blocks.items():
        if value is None:
            cfg.pop(key, None)
        else:
            cfg[key] = value
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    for attr in [a for a in dir(hooklib) if "CACHE" in a]:
        setattr(hooklib, attr, None)


def seed(root: Path, ticket: str = "QA-9") -> Path:
    task = root / "qa-factory/artifacts" / ticket
    (task / "work").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps(
        {"ticket": ticket, "size": "S", "environment": "local", "implementation_source": "diff",
         "stages": {"S0": {"status": "pending"}}, "gates": {}, "halts": []}), encoding="utf-8")
    return task


def reader_states() -> None:
    """K1, K2: test_data_states."""
    got = lambda cfg: CC.test_data_states(cfg)
    for name, cfg in (("None", None), ("a list", []), ("a string", "x"), ("no block", {"a": 1})):
        check_eq(f"K1 {name} -> absent", got(cfg), {"state": "absent", "keys": [], "values": {}})
    check_eq("K1 a block that is a string -> malformed", got({"test_data": "x"})["state"], "malformed")
    check_eq("K1 a block that is a list -> malformed", got({"test_data": []})["state"], "malformed")
    names = list(CC.canonical_template()["test_data"])
    empty = got({"test_data": {}})
    check_eq("K1 an empty block -> read, every template key not_recorded", empty,
             {"state": "read", "keys": [(k, "not_recorded") for k in names], "values": {}})
    cases = (("", "not_recorded"), ("  ", "not_recorded"), (None, "not_recorded"), ("Unknown ", "unknown"), ("TBD", "unknown"),
             ("tbd", "unknown"), ("?", "unknown"), ([], "none"), (["users"], "recorded"), ("fixtures", "recorded"), (5, "recorded"))
    for value, status in cases:
        row = got({"test_data": {"seeds": value}})
        check_eq(f"K1 seeds={value!r} -> {status}", dict(row["keys"])["seeds"], status)
        check_eq(f"K1 seeds={value!r}: the value is carried only when recorded", "seeds" in row["values"], status == "recorded")
    check_eq("K1 control: a recorded value is carried as given", got({"test_data": {"seeds": ["a", "b"]}})["values"], {"seeds": ["a", "b"]})
    # K2: the template's order, then the project's own key; the template is the source of the closed list
    row = got({"test_data": {"zeta": "z", "seeds": "s"}})
    check_eq("K2 the template keys come first in the template's order, then the project's own", [k for k, _s in row["keys"]], names + ["zeta"])
    real = CC.canonical_template
    try:
        CC.canonical_template = lambda: {"test_data": {"seeds": ""}}
        check_eq("K2 control: a template without `generators` does not invent it", [k for k, _s in got({"test_data": {}})["keys"]], ["seeds"])
        CC.canonical_template = lambda: (_ for _ in ()).throw(OSError("gone"))
        check_eq("K2 a template that cannot be read leaves the project's keys, and does not raise",
                 [k for k, _s in got({"test_data": {"seeds": "s"}})["keys"]], ["seeds"])
    finally:
        CC.canonical_template = real


def brief_lines() -> None:
    """K3-K7: the brief."""
    root = harness.temp_project("qa-approach-")
    real_ceiling = brief_pack.BRIEF_MAX_BYTES
    try:
        harness.use_project(root)
        seed(root)
        strategy = root / "qa-factory" / "strategy"
        strategy.mkdir(parents=True, exist_ok=True)
        stage_of = {"qa-case-designer": "S4", "qa-runner": "S6", **ROLES}

        def brief(role: str, n: str = "1") -> str:
            return brief_pack.build("QA-9", stage_of[role], role, f"{stage_of[role]}-{role}-{n}", write=False)["markdown"]

        def line(text: str, start: str) -> str:
            return next((x for x in text.splitlines() if x.startswith(start)), "")

        put_config(root, test_data={"accounts_by_role": "created per test through the admin API", "seeds": "", "generators": "unknown",
                                    "pii_and_masking": ["x"], "cleanup_owner": "the suite", "shared_records": []}, strategy_documents=[])
        # K3 code rules: absent (the world before onboarding wrote the file), then present
        absent = brief("qa-test-strategist")
        check_in("K3 no framework-rules.md: the line names the path and says not recorded",
                 "- code rules: qa-factory/strategy/framework-rules.md: not recorded - onboarded before", absent)
        check_not_in("K3 control: the line never promises 'not written yet' for it", "framework-rules.md: not written yet", absent)
        (strategy / "framework-rules.md").write_text("r" * 600, encoding="utf-8")
        check_in("K3 present: path and size, the strategist is not injected it",
                 "- code rules: qa-factory/strategy/framework-rules.md (600 B)\n", brief("qa-test-strategist", "2") + "\n")
        for role in ("qa-automator", "qa-code-critic"):
            check_in(f"K3 {role} is injected the file: the line says so", "(600 B), already in your prompt", brief(role))
        # K4: the three roles at their stages, not the others
        for role in ROLES:
            text = brief(role, "3")
            check_in(f"K4 {role} at {stage_of[role]}: the approach block is in the head", "Project approach (recorded at onboarding;", text)
            check_in(f"K4 {role}: the test data line", '- test data: qa-factory/config.json `test_data` (Grep -n "test_data") - recorded: '
                     "accounts_by_role, pii_and_masking, cleanup_owner; unknown: generators; not recorded: seeds; shared_records: none - every test creates its own", text)
            check_not_in(f"K4 {role}: no value is copied into the brief", "admin API", text)
        for role in ("qa-case-designer", "qa-runner"):
            check_not_in(f"K4 control: {role} gets no approach lines", "Project approach", brief(role, "3"))
        # E2 / E2b: absent block, malformed block, unreadable config
        put_config(root, test_data=None)
        check_in("K3 no test_data block: not recorded, onboarding topic 3", "has no test_data block - not recorded (onboarding topic 3)", brief("qa-automator", "4"))
        put_config(root, test_data="x")
        check_in("K3 test_data not an object: not read", "test_data is not an object - not read", brief("qa-automator", "5"))
        good = (root / "qa-factory/config.json").read_text(encoding="utf-8")
        (root / "qa-factory/config.json").write_text("{not json", encoding="utf-8")
        for attr in [a for a in dir(hooklib) if "CACHE" in a]:
            setattr(hooklib, attr, None)
        check_in("K3 an unreadable config: said as unreadable, the brief is still built",
                 "could not be read; no approach to data is on record for this run", brief_pack.project_approach_lines("qa-automator", root, root / "qa-factory/artifacts/QA-9")[2])
        (root / "qa-factory/config.json").write_text(good, encoding="utf-8")
        # K5 a project's own strategy document
        (root / "docs").mkdir(exist_ok=True)
        (root / "docs/framework-rules.md").write_text("o" * 700, encoding="utf-8")
        (strategy / "framework-rules.md").unlink()
        put_config(root, test_data={}, strategy_documents=[{"path": "docs/framework-rules.md", "provenance": "pre_existing", "editable": False}])
        text = brief("qa-test-strategist", "6")
        check_in("K5 strategy_documents[]: the code rules line names the project's own file", "- code rules: docs/framework-rules.md (700 B)", text)
        check_in("K5 ... and the documents line says qa-factory/strategy holds none and names the own one",
                 "- strategy documents: qa-factory/strategy/ holds none; the project's own: docs/framework-rules.md", text)
        # K6 (fix 2, B-1): the ceiling cuts the approach block FIRST - full, one line, a pointer line, nothing - and the
        # person's words section is always there (the words themselves: test_brief_pack.approach_scenario)
        full = brief_pack.build("QA-9", "S5", "qa-automator", "S5-qa-automator-7", write=False)
        for needle in ("Project approach (recorded", "- code rules:", "- test data:", "- strategy documents:"):
            check_in(f"K6 at the normal ceiling the full block holds {needle!r}", needle, full["markdown"])
        check_in("K6 ... and the person's words section (or its pointer) is there", "## The person's words that concern you", full["markdown"])
        forms = brief_pack.approach_forms("qa-automator", root, root / "qa-factory/artifacts/QA-9")
        check_eq("K6 the forms: 4 lines, one line, one pointer line, nothing", {level: len(lines) for level, lines in forms.items()},
                 {2: 4, 1: 1, 0: 1, -1: 0})
        try:
            for ceiling, present, absent, label in (
                    (full["budget_bytes"] - 1,"Project approach (cut for room)", "- test data:", "one byte short: the one-line form"),
                    (1, "## The person's words that concern you", "Project approach", "1 byte: the block is gone, the words section stays")):
                brief_pack.BRIEF_MAX_BYTES = ceiling
                text = brief("qa-automator", "7")
                check_in(f"K6 {label}: {present!r}", present, text)
                check_not_in(f"K6 {label}: not {absent!r}", absent, text)
        finally:
            brief_pack.BRIEF_MAX_BYTES = real_ceiling
        # K7: AT and BEYOND the limits
        for i in range(1, 8):
            (strategy / f"doc{i}.md").write_text("d", encoding="utf-8")
        docs = line(brief("qa-code-critic", "8"), "- strategy documents:")
        check_in("K7 7 documents: 6 names and the rest counted", "doc6.md (+1 more)", docs)
        check_not_in("K7 ... the seventh name is not listed", "doc7.md", docs)
        (strategy / "doc7.md").unlink()
        docs = line(brief("qa-code-critic", "9"), "- strategy documents:")
        check_in("K7 AT 6 documents: all names", "doc6.md", docs)
        check_not_in("K7 ... and no 'more'", "more", docs)
        exact = "p" * (brief_pack.APPROACH_LINE_CHARS - len("- strategy documents: qa-factory/strategy/ holds none; the project's own: "))
        for extra, expect_cut in ((exact, False), (exact + "p", True)):
            put_config(root, strategy_documents=[{"path": extra}])
            for p in (strategy.glob("doc*.md")):
                p.unlink()
            line_ = brief_pack.project_approach_lines("qa-automator", root, root / "qa-factory/artifacts/QA-9")[3]
            check_eq(f"K7 a line of {len(line_)} chars: cut only beyond {brief_pack.APPROACH_LINE_CHARS}", line_.endswith(" ..."), expect_cut)
            check_eq("K7 ... and never longer than the limit", len(line_) <= brief_pack.APPROACH_LINE_CHARS, True)
    finally:
        brief_pack.BRIEF_MAX_BYTES = real_ceiling
        harness.cleanup(root)


CASE_MD = "---\nid: TC-700\nstatus: Approved\n---\n## Given\nA workflow.\n\n## When\n1. Open.\n\n## Then\n1. The banner is visible.\n"
TEST_PY = ('def test_banner_appears(project_a, non_admin_user):\n    """@case TC-700 - the banner."""\n'
           '    assert_that(project_a.page.is_visible(), equal_to(True))\n')
MANIFEST = {"tests": [{"case": "TC-700", "file": "tests/test_banner.py", "marker": "TC-700", "instance_id": "test_banner_appears",
                       "test_function": "test_banner_appears", "status": "green"}],
            "then_bindings": [{"case": "TC-700", "then": 1, "instance_id": "test_banner_appears",
                               "assertion_ref": "tests/test_banner.py:3", "status": "covered"}]}


def fake_transport():
    calls = []

    def post(payload, key, timeout, attempts=4):
        calls.append(payload)
        answers = {name: ({"type": "choice", "choice": "tooling", "confidence": 0.9, "probabilities": {"tooling": 0.9}}
                          if q["type"] == "choice" else {"type": "noul", "noul": 0.5}) for name, q in payload["questions"].items()}
        return {"model": "judge-test", "answers": answers, "usage": {"input_tokens": 100}}
    post.calls = calls
    return post


def judge_state() -> None:
    """K8: the judge's state carries the project's approach, and only the origin-of-data keys."""
    import os
    root = harness.temp_project("qa-approach-judge-")
    os.environ["QA_JUDGE_TEST_KEY"] = "not-a-real-key"
    real_post = judge._post
    try:
        harness.use_project(root)
        task = root / "qa-factory/artifacts/TICKET-700"
        (task / "work/test-cases").mkdir(parents=True)
        (task / "work/run-blocks").mkdir(parents=True)
        (task / "work/automation-manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
        (task / "work/test-cases/TC-700.md").write_text(CASE_MD, encoding="utf-8")
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests/test_banner.py").write_text(TEST_PY, encoding="utf-8")
        put_config(root, judge={"provider": "typesafe", "mode": "shadow", "api_key_env": "QA_JUDGE_TEST_KEY"},
                   test_data={"accounts_by_role": "extra users created per test through the admin API", "seeds": "factories in tests/factories.py",
                              "generators": "", "pii_and_masking": "PII_SENTINEL", "cleanup_owner": "CLEANUP_SENTINEL", "shared_records": ["Organization"]})

        def state() -> dict:
            judge._post = fake_transport()
            report = J.run(task)
            return report, judge._post.calls[0]["state"]
        report, st = state()
        approach = st["project"]["test_data"]
        check_eq("K8 the run is ok", report["status"], "ok")
        check_in("K8 the state carries accounts_by_role", "accounts_by_role: extra users created per test through the admin API", approach)
        check_in("K8 ... seeds and the list-valued shared_records", "shared_records: Organization", approach)
        check_in("K8 ... seeds", "seeds: factories in tests/factories.py", approach)
        check_not_in("K8 not the masking key", "PII_SENTINEL", json.dumps(st))
        check_not_in("K8 not the cleanup key", "CLEANUP_SENTINEL", json.dumps(st))
        check_not_in("K8 an empty key is not listed", "generators", approach)
        # the limit: AT and BEYOND JUDGE_TEST_DATA_CHARS
        for n, cut in ((J.JUDGE_TEST_DATA_CHARS, False), (J.JUDGE_TEST_DATA_CHARS + 1, True)):
            put_config(root, test_data={"seeds": "s" * n})
            value = state()[1]["project"]["test_data"]
            check_eq(f"K8 a value of {n} chars is {'cut' if cut else 'whole'}", "# ... trimmed" in value, cut)
        # the unsafe-to-pass directions: nothing recorded is the word, never an invented approach
        put_config(root, test_data=None)
        check_eq("K8 no block -> 'not recorded'", state()[1]["project"]["test_data"], "not recorded")
        put_config(root, test_data={"seeds": "unknown", "accounts_by_role": "TBD", "pii_and_masking": "x"})
        check_eq("K8 only unknown / TBD / unrelated keys -> 'not recorded'", state()[1]["project"]["test_data"], "not recorded")
        check_eq("K8 an unreadable config -> 'not recorded' (the function, which never raises)", (
            (root / "qa-factory/config.json").write_text("{nope", encoding="utf-8"), J.test_data_for_judge(task))[1], "not recorded")
        check_eq("K8 the state of a row without an approach says 'not recorded'", J.NOT_RECORDED, "not recorded")
    finally:
        judge._post = real_post
        harness.cleanup(root)


def texts() -> None:
    """K9: the judge's thresholds (its words and the roles' texts are rows of design/role-rules.json)."""
    entry = next(j for j in json.loads((PLUGIN / "references/judgments.d/code.json").read_text(encoding="utf-8"))["judgments"]
                 if j["id"] == "code_owns_its_data")
    check_eq("K9 thresholds are untouched", entry["thresholds"], {"true_at": 0.85, "false_at": 0.15})


def main() -> None:
    reader_states()
    texts()
    brief_lines()
    judge_state()
    harness.finish("test_project_approach")


if __name__ == "__main__":
    main()
