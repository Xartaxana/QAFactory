#!/usr/bin/env python3
"""S5's rubric questions: one small state per test function, and the downgrade seam in
s5_precheck that a judge may use to turn a finding into a hint.

No test here reaches the network: `judge._post` is replaced by a transport that answers from
a table, exactly as scripts/tests/test_judge.py does. What is checked is the factory's side —
which questions are asked of which function, that a function is judged against the Then
clauses the manifest binds to IT, that `judge.provider: none` leaves s5_precheck's output
identical, and that a downgrade happens only in `mode: on` and stays visible as a hint, a
note and a `judge.passes()` row.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import judge  # noqa: E402
import judge_code as J  # noqa: E402
import s5_precheck as P  # noqa: E402

CASE_MD = """---
id: TC-700
status: Approved
---
## Given
A workflow the test creates.

## When
1. Open the workflows page.

## Then
1. The banner `sync_state` is visible.
2. The call returns status `400`.
3. The body's `help` is null.
"""

TEST_PY = '''"""Tests for TC-700."""
import time


def test_banner_appears(page, admin_account):
    """@case TC-700 - the banner."""
    page.goto("/workflows")
    time.sleep(2)
    assert_that(page.locator(".sync_state").is_visible(), equal_to(True))


def test_rejects_bad_payload(client):
    """@case TC-700 - the rejection."""
    response = client.post("/validate", json={"bad": 1})
    assert_that(response.status_code, equal_to(400), response.text)
    assert_that(response.json()["help"], not_none(), "help")
'''

MANIFEST = {
    "tests": [
        {"case": "TC-700", "file": "tests/test_banner.py", "marker": "TC-700",
         "instance_id": "test_banner_appears", "test_function": "test_banner_appears",
         "status": "green"},
        {"case": "TC-700", "file": "tests/test_banner.py", "marker": "TC-700",
         "instance_id": "test_rejects_bad_payload", "test_function": "test_rejects_bad_payload",
         "status": "green"},
    ],
    "then_bindings": [
        {"case": "TC-700", "then": 1, "instance_id": "test_banner_appears",
         "assertion_ref": "tests/test_banner.py:9", "status": "covered"},
        {"case": "TC-700", "then": 2, "instance_id": "test_rejects_bad_payload",
         "assertion_ref": "tests/test_banner.py:15", "status": "covered"},
        {"case": "TC-700", "then": 3, "instance_id": "test_rejects_bad_payload",
         "assertion_ref": "tests/test_banner.py:16", "status": "covered"},
    ],
}


def fake_transport(table):
    """The transport of scripts/tests/test_judge.py, copied so this file imports no other
    test: a question answered from a table, and every payload kept for inspection."""
    calls = []

    def post(payload, key, timeout, attempts=4):
        calls.append(payload)
        answers = {}
        for name, question in payload["questions"].items():
            value = table(payload["state"], name, question)
            if question["type"] == "noul":
                answers[name] = {"type": "noul", "noul": value}
            else:
                answers[name] = {"type": "choice", "choice": value[0], "confidence": value[1],
                                 "probabilities": {value[0]: value[1]}}
        return {"model": "judge-test", "answers": answers, "usage": {"input_tokens": 100}}
    post.calls = calls
    return post


def set_judge(root: Path, block: dict | None) -> None:
    path = root / "qa-factory/config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.pop("judge", None)
    if block is not None:
        cfg["judge"] = block
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def seed(root: Path) -> Path:
    task = root / "qa-factory/artifacts/TICKET-700"
    (task / "work/test-cases").mkdir(parents=True)
    (task / "work/run-blocks").mkdir(parents=True)
    (task / "work/automation-manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    (task / "work/test-cases/TC-700.md").write_text(CASE_MD, encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests/test_banner.py").write_text(TEST_PY, encoding="utf-8")
    return task


# A judge that likes everything: every positive dimension true, every negative one false.
def all_good(state, name, question):
    if question["type"] == "choice":
        return ("tooling", 0.95)
    positive = {"assert_matches_then", "sleep_justified", "owns_its_data", "narrow_negative", "q"}
    return 0.97 if name in positive else 0.02


CFG = {"provider": "typesafe", "mode": "shadow", "disabled": []}
KEYS = {"sleep_justified": "sleep", "locator_fragile": "locator", "narrow_negative": "negative_code"}


def asked_for(code: str, negative: bool = False) -> set:
    state = {"test": {"file": "t.py", "function": "f", "fixtures": [], "code": code},
             "case": {"ids": ["TC-1"], "then": "", "negative": negative}}
    return set(J.questions_for(state, CFG))


def with_detectors(text: str | None):
    """Point the shape reader at a scratch detectors file (None: the shipped one), the way a test of the probe does."""
    if text is None:
        os.environ.pop("ASSERTION_DETECTORS_FILE", None)
        return None
    scratch = harness.temp_dir("qa-judge-shapes-")
    path = scratch / "detectors.json"
    path.write_text(text, encoding="utf-8")
    os.environ["ASSERTION_DETECTORS_FILE"] = str(path)
    return scratch


def shape_tables() -> None:
    """K-C3 and E-C5: which shapes make a question worth asking, and what a missing table means (ask more)."""
    fires = {
        "sleep_justified": ["time.sleep(2)", "Thread.sleep(500);", "await asyncio.sleep(1)", "sleep( 3)",
                            "page.wait_for_timeout(1000)", "await page.waitForTimeout(500);", "await Task.Delay(1000);",
                            "Thread.Sleep(10);", "time.Sleep(time.Second)", "cy.wait(2000)"],
        "locator_fragile": ["page.locator('#a')", "driver.find_element(By.ID, 'a')", "By.id(\"x\")",
                            "page.getByRole('button')", "cy.get('.x')", "$('#a')", "$$(\"li\")", "page.get_by_text('x')",
                            "xpath = '//a'", "from selenium import webdriver", "import playwright", "page.goto(u)",
                            "el = q.query_selector('a')", "css_selector = 'a'"],
        "narrow_negative": ["with pytest.raises(ValueError):", "assert r.status_code == 404", "assert 'error' in body",
                            "expect(fn).toThrow()", "Assert.Throws<ArgumentException>(() => x());",
                            "assertThrows(IllegalStateException.class, () -> f());", "r = Forbidden()",
                            "assert code == 503", "body = INVALID"],
    }
    quiet = {
        "sleep_justified": ["cy.wait('@login')", "await asyncio.wait_for(x, 5)", "sleep(delay)", "sleeping = True",
                            "Task.Run(x)"],
        "locator_fragile": ["client.get('/x')", "response.json()", "cart.total == 2", "Bypass(x)", "getByte(x)",
                            "policy.get(x)", "homepage.get(x)", "x = 1"],
        "narrow_negative": ["assert r.status_code == 200", "assert total == 20", "x = 1", "terror = 1",
                            "Assert.Equal(1, 2)", "assertEquals(1, 2)"],
    }
    for dimension, samples in fires.items():
        for code in samples:
            check(f"K-C3: `{code}` asks {dimension}", dimension in asked_for(code))
    for dimension, samples in quiet.items():
        for code in samples:
            check(f"K-C3: `{code}` does NOT ask {dimension} (a sample outside the table)", dimension not in asked_for(code))
    check("K-C3: a case the FIELD calls negative asks narrow_negative whatever the code says",
          "narrow_negative" in asked_for("x = 1", negative=True))
    check_eq("K-C3: no shape in the code, no field - none of the three is asked",
             {d for d in KEYS if d in asked_for("x = 1")}, set())
    shipped = json.loads(Path(harness.SCRIPTS).parent.joinpath("references/detectors.json").read_text(encoding="utf-8"))

    def doc_without(*dropped, **replaced) -> str:
        return json.dumps({**{k: v for k, v in shipped.items() if k not in dropped}, **replaced})

    # E-C5 / E-C10: a table that is missing, unreadable or malformed means ASK - never `clean` through a missed shape.
    worlds = {
        "sleep key dropped (an older copy of the references)": (doc_without("sleep"), {"sleep_justified"}),
        "locator key dropped": (doc_without("locator"), {"locator_fragile"}),
        "locator_words key dropped": (doc_without("locator_words"), {"locator_fragile"}),
        "negative_code key dropped": (doc_without("negative_code"), {"narrow_negative"}),
        "sleep key malformed (does not compile)": (doc_without(sleep=["time\\.sleep\\(", "[open"]), {"sleep_justified"}),
        "locator key empty": (doc_without(locator=[]), {"locator_fragile"}),
        "negative_code key not a list": (doc_without(negative_code="error"), {"narrow_negative"}),
        "the file is not JSON": ("{ not json", set(KEYS)),
        "every new key dropped at once": (doc_without("sleep", "locator", "locator_words", "negative_code"), set(KEYS)),
    }
    try:
        for label, (text, expected) in worlds.items():
            scratch = with_detectors(text)
            try:
                check_eq(f"E-C5 [{label}]: a test with no shape in it is asked exactly the dimensions that table feeds",
                         {d for d in KEYS if d in asked_for("x = 1")}, expected)
                if "sleep_justified" not in expected:
                    check(f"E-C5 [{label}]: a dimension whose table IS readable still reads it (`time.sleep(1)` asks sleep)",
                          "sleep_justified" in asked_for("time.sleep(1)"))
                    check_eq(f"E-C5 [{label}]: ... and a line with no sleep in it does not ask sleep",
                             "sleep_justified" in asked_for("page.locator('a')"), False)
            finally:
                if scratch:
                    harness.cleanup(scratch)
        # a readable table whose other keys are missing never asks MORE than the key it lacks
        scratch = with_detectors(doc_without("negative_code"))
        try:
            check("E-C5: a locator-only line is asked locator_fragile and not sleep_justified when only `negative_code` is gone",
                  {"locator_fragile"} <= asked_for("page.locator('a')") and "sleep_justified" not in asked_for("page.locator('a')"))
        finally:
            harness.cleanup(scratch)
    finally:
        with_detectors(None)
    # the shipped table: every sample dimension above is read from detectors.json (one reader), and nothing but the
    # data decides - a new shape in the file is asked at once
    scratch = with_detectors(doc_without(sleep=["totally_custom_wait\\("]))
    try:
        check("K-C3: the question follows the DATA (a project's own wait shape, no code change)",
              "sleep_justified" in asked_for("totally_custom_wait(3)") and "sleep_justified" not in asked_for("time.sleep(1)"))
    finally:
        harness.cleanup(scratch)
        with_detectors(None)
    # the rendering of "skipped" is pinned in main (it needs a story with a non-Python test file)


def main() -> None:
    shape_tables()
    registry = judge.load_registry()
    mine = [i for i in registry.values() if i.get("registry_file") == "code.json"]
    check("every judgment of this package is registered", len(mine) >= 10)
    check("and every id is prefixed with its subject",
          all(i["id"].startswith("code_") for i in mine))
    check("every dimension judge_code asks for exists in the registry",
          all(jid in registry for jid, _p, _d in J.DIMENSIONS.values()))
    check("a rejected dimension records why",
          all(i.get("calibration") for i in mine if i.get("enabled") is False))

    root = harness.temp_project("qa-judge-code-")
    os.environ["QA_JUDGE_TEST_KEY"] = "not-a-real-key"
    real_post = judge._post
    try:
        harness.use_project(root)
        task = seed(root)

        # --- provider none: the default, and nothing changes anywhere -------------------
        judge._post = fake_transport(all_good)
        check_eq("judge_code is a no-op without a provider", J.run(task)["status"], "off")
        check("and writes no file", not (task / "work/judge-code.json").exists())
        check_eq("--cause falls back to the contract's own default",
                 (J.cause("a sleep must become a wait", None, root)["status"],
                  J.cause("a sleep must become a wait", None, root)["repair_cause"]),
                 ("off", "test_defect"))
        bare = P.run(task)
        set_judge(root, {"provider": "none", "mode": "on"})
        check_eq("`provider: none` leaves s5_precheck byte for byte as it was",
                 json.dumps(P.run(task), sort_keys=True), json.dumps(bare, sort_keys=True))
        check_eq("provider none sends nothing at all", len(judge._post.calls), 0)

        # --- the states: one function each, scoped to the clauses bound to it ------------
        set_judge(root, {"provider": "typesafe", "mode": "shadow",
                         "api_key_env": "QA_JUDGE_TEST_KEY"})
        judge._post = fake_transport(all_good)
        report = J.run(task)
        check_eq("every test function of the scope is judged, none skipped",
                 sorted(k.split("::")[1] for k in report["tests"]),
                 ["test_banner_appears", "test_rejects_bad_payload"])
        check_eq("all dimensions passing makes a test clean", report["needs_critic"], [])
        check("the file the critic reads first is written",
              (task / "work/judge-code.json").is_file())
        check_eq("one function is one request", len(judge._post.calls), 2)
        check("and each state is small", all(len(json.dumps(c["state"])) < 6000
                                             for c in judge._post.calls))
        states = {c["state"]["test"]["function"]: c["state"] for c in judge._post.calls}
        asked = {c["state"]["test"]["function"]: set(c["questions"]) for c in judge._post.calls}
        check_in("a function is judged against the Then the manifest binds to IT",
                 "Then 2", states["test_rejects_bad_payload"]["case"]["then"])
        check_not_in("and not against a clause another function proves",
                     "Then 1", states["test_rejects_bad_payload"]["case"]["then"])
        check("the sleep question is asked only where there is a sleep",
              "sleep_justified" in asked["test_banner_appears"]
              and "sleep_justified" not in asked["test_rejects_bad_payload"])
        check("and the locator question only of the test that touches the page",
              "locator_fragile" in asked["test_banner_appears"]
              and "locator_fragile" not in asked["test_rejects_bad_payload"])
        check_eq("the record says which clauses the state carried",
                 report["tests"]["test_banner.py::test_banner_appears"]["then_scope"], "bindings")

        # a dimension the judge decides against sends that one test to the critic
        judge._post = fake_transport(
            lambda s, n, q: 0.99 if n == "hardcoded_credential" else all_good(s, n, q))
        flagged = J.run(task)
        check_eq("a failed dimension is named, not just counted",
                 sorted(flagged["decided_fails"]),
                 ["test_banner.py::test_banner_appears",
                  "test_banner.py::test_rejects_bad_payload"])
        check_eq("and it is the dimension the judge decided against",
                 flagged["tests"]["test_banner.py::test_banner_appears"]["fails"],
                 ["hardcoded_credential"])
        check_not_in("no credential value is ever written to the file",
                     "not-a-real-key",
                     (task / "work/judge-code.json").read_text(encoding="utf-8"))

        # --- K-C3: a test file the judge cannot read is said, not "none skipped" -------------------------
        (root / "tests/BannerTests.cs").write_text("// TC-700\n", encoding="utf-8")
        with_cs = json.loads(json.dumps(MANIFEST))
        with_cs["tests"].append({"case": "TC-700", "file": "tests/BannerTests.cs", "marker": "TC-700",
                                 "instance_id": "TC-700::Banner", "status": "green"})
        manifest_path = task / "work/automation-manifest.json"
        manifest_path.write_text(json.dumps(with_cs), encoding="utf-8")
        judge._post = fake_transport(all_good)
        mixed = J.run(task)
        manifest_path.write_text(json.dumps(MANIFEST), encoding="utf-8")
        check_eq("K-C3: the report names the non-Python file it skipped, once", mixed["skipped_files"], ["BannerTests.cs"])
        check_in("K-C3: render says how many were skipped and who reads them",
                 "1 non-Python file(s) skipped (the critic reviews them in full)", J.render(mixed))
        check_not_in("K-C3: ... and no longer claims none were", "none skipped", J.render(mixed))
        check_in("K-C3: a run that skipped nothing still says so", "none skipped", J.render(J.run(task)))
        check_in("K-C3: a report written before the field existed reads as none skipped", "none skipped",
                 J.render({"status": "ok", "mode": "shadow", "tests": {}, "clean": [], "needs_critic": [],
                           "decided_fails": []}))

        # --- the repair cause ------------------------------------------------------------
        judge._post = fake_transport(lambda s, n, q: ("environment", 0.93))
        answer = J.cause("the stand has no non-owner account", "tests/test_banner.py", root)
        check_eq("a decided cause is the one the judge chose",
                 (answer["repair_cause"], answer["decided"]), ("environment", True))
        judge._post = fake_transport(lambda s, n, q: ("environment", 0.4))
        unsure = J.cause("the stand has no non-owner account", None, root)
        check_eq("an undecided cause leaves the contract's default in place",
                 (unsure["repair_cause"], unsure["decided"], unsure["leaning"]),
                 ("test_defect", False, "environment"))

        # --- the downgrade seam ------------------------------------------------------------
        base = bare  # the findings as they stand with no judge at all
        smells = [f for f in base["advice"] if f["check"] == "smell"]       # X7-2: a smell is ADVICE, not a judged finding
        contradictions = [f for f in base["findings"]
                          if f["check"] == "bindings" and "contradicted-" in f["id"]]
        check("the story is built so that the smell is advice and the judged family (a Then contradiction) really fires",
              len(smells) == 1 and len(contradictions) == 1 and not [f for f in base["findings"] if f["check"] == "smell"])

        set_judge(root, {"provider": "typesafe", "mode": "shadow",
                         "api_key_env": "QA_JUDGE_TEST_KEY"})
        judge._post = fake_transport(lambda s, n, q: 0.99)  # every judged refusal would pass
        shadow = P.run(task)
        check_eq("shadow downgrades nothing", len(shadow["findings"]), len(base["findings"]))
        check_in("but it records what it would have passed",
                 "would pass", "\n".join(shadow["notes"]))

        set_judge(root, {"provider": "typesafe", "mode": "on",
                         "api_key_env": "QA_JUDGE_TEST_KEY"})
        passed = P.run(task)
        left = {f["id"] for f in passed["findings"]}
        check("a smell is advice for the critic and stays so in mode on (no judge question downgrades it any more)",
              smells[0]["id"] in {a["id"] for a in passed["advice"]})
        check("a Then contradiction the judge reads as consistent is downgraded",
              contradictions[0]["id"] not in left)
        check_eq("a downgraded finding becomes a hint the author still reads",
                 sorted(h["id"] for h in passed["hints"] if h.get("judge")),
                 sorted([contradictions[0]["id"]]))
        check_in("and a note says the judge did it", "downgraded to a hint by the judge",
                 "\n".join(passed["notes"]))
        rows = judge.passes(root, "TICKET-700")
        check_eq("every block the judge let through is listed for the gate brief",
                 sorted({r["refusal"] for r in rows}), ["s5_then_contradiction"])
        check("a finding of a family nobody registered is never put to the judge",
              all(r["refusal"] in ("s5_then_contradiction",) for r in rows))

        # a judge that says no leaves every finding where it was
        judge._post = fake_transport(lambda s, n, q: 0.01)
        held = P.run(task)
        check_eq("a judge that disagrees changes nothing",
                 {f["id"] for f in held["findings"]}, {f["id"] for f in base["findings"]})

        # --- an unreachable judge is never a halt -------------------------------------------
        def broken(*_a, **_k):
            raise RuntimeError("HTTP 529: overloaded")
        judge._post = broken
        check_eq("judge_code reports it and exits for the fallback",
                 J.run(task)["status"], "unavailable")
        down = P.run(task)
        check_eq("and s5_precheck keeps every finding it found",
                 {f["id"] for f in down["findings"]}, {f["id"] for f in base["findings"]})
        check_eq("--cause too", J.cause("anything", None, root)["repair_cause"], "test_defect")
    finally:
        judge._post = real_post
        harness.cleanup(root)
    harness.finish("test_judge_code")


if __name__ == "__main__":
    main()
