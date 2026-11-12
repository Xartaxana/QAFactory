#!/usr/bin/env python3
"""Refusals of FORM: a misspelled word is mapped, never waved through.

Nothing here reaches the network - `judge._post` answers from a table, exactly as
test_judge.py does it. The words are the real ones: the verdicts and row states of the
sixteen S5 dispatches of TP1-15045, the `unresolved[]` reasons its manifest carries, and
the node id whose browser prefix burned a red probe.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in  # noqa: E402
from test_judge import fake_transport, set_judge  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import judge  # noqa: E402
import judge_form  # noqa: E402
import node_ids  # noqa: E402
import role_digest as RD  # noqa: E402

# One real digest of 2026-09-21, with its verdict in the critic's own word and a row state
# nobody added to the vocabulary. Everything else about it is in the form.
SPELLING = "\n".join([
    "qa-code-critic S5 window 2b (TC-007, TC-011) · rejected",
    "TC-007 · approved-with-fixes · one completeness gap in the Given",
    "TC-011 · not-executed · the red probe could not be launched",
    "work/reviews/S5-qa-code-critic-7-window2b.json",
])
SCOPE = ["TC-007", "TC-011"]
# The invented word test_role_digest already refuses: the judge must decline it, not guess.
INVENTED = "\n".join(["qa-runner S6 TC-005 · ok", "TC-005 · mostly-fine · it ran",
                      "work/run-report.json"])

MAP = {"rejected": ("concerns", 0.99), "approved-with-fixes": ("approved_with_fixes", 1.0),
       "not-executed": ("skipped", 0.53), "mostly-fine": ("other", 0.63),
       "env blocker": ("blocked_by_env", 1.0)}


def split(text: str, scope: list) -> tuple:
    """`(refused, advice)` the exit gate makes of a digest: a word outside the list is advice, what is absent is refused (X2-3)."""
    import exit_gate as gate
    return gate._digest_word_split(text, scope, RD.check(text, scope))


def table(state, name, question):
    word = state.get("word") if isinstance(state, dict) else ""
    if name in ("verdict", "state"):
        return MAP.get(word, ("other", 0.5))
    if name == "q" and question["type"] == "choice" and "collected" in state:
        return (state["collected"][0], 0.97)
    return 0.9


def the_registry_is_what_the_package_promised() -> None:
    registry = judge.load_registry()
    mine = {jid: item for jid, item in registry.items()
            if item.get("registry_file") == "form.json"}
    check_eq("the package registers exactly its four questions", sorted(mine),
             ["form_digest_verdict", "form_node_id", "form_row_state", "form_unresolved_reason"])
    check("every one of them passes a block, so every one keeps 0.9",
          all(item["thresholds"]["confidence"] >= 0.9 for item in mine.values()))
    check("and every one records what it was calibrated against",
          all(item.get("calibration") for item in mine.values()))
    check("`other` is always offered, so the judge can decline instead of guessing",
          all("other" in item["criteria"] for jid, item in mine.items() if jid != "form_node_id"))
    check("the digest-word helpers left the module with the gate's judge (X2-3)",
          not any(hasattr(judge_form, name) for name in ("digest", "digest_errors", "_row_options", "MAX_DIGEST_ASKS")))
    check("the reason mapping left the module with the role's choice of the route word (X7-2)",
          not any(hasattr(judge_form, name) for name in ("unresolved_reason", "normalise_unresolved", "UNRESOLVED_OPTIONS")))


def nothing_moves_without_a_provider(root: Path) -> None:
    judge._post = fake_transport(table)
    set_judge(root, None)
    refused, advice = split(SPELLING, SCOPE)
    check_eq("provider none: a digest word outside the list is advice, not a refusal", (refused, bool(advice)), ([], True))
    check("control: a digest with no artifact path is still refused", bool(split("\n".join(SPELLING.splitlines()[:-1]), SCOPE)[0]))
    check_eq("and asks nothing", len(judge._post.calls), 0)
    collected = ["a/test_x.py::test_one[chromium-alpha]", "a/test_x.py::test_one[firefox-alpha]"]
    got = node_ids.match(["a/test_x.py::test_one[beta]"], collected, project_root=root)
    check_eq("and a node id with no spelling is missing, as it always was",
             [m["asked"] for m in got["missing"]], ["a/test_x.py::test_one[beta]"])
    check_eq("still nothing asked", len(judge._post.calls), 0)


def shadow_and_on_ask_nothing_about_a_digest(root: Path) -> None:
    """The gate asks no judge about a digest word, in any mode (X2-3); the words stay advice and the journal stays empty."""
    for mode in ("shadow", "on"):
        set_judge(root, {"provider": "typesafe", "mode": mode, "api_key_env": "QA_JUDGE_TEST_KEY"})
        judge._post = fake_transport(table)
        refused, advice = split(SPELLING, SCOPE)
        check_eq(f"{mode}: the words are advice and nothing is refused", (refused, len(advice) >= 2), ([], True))
        check_in(f"{mode}: the advice names the verdict word the role wrote", "rejected", "; ".join(advice))
        check_in(f"{mode}: and the row state word", "not-executed", "; ".join(advice))
        check_eq(f"{mode}: the judge was asked nothing", len(judge._post.calls), 0)
        check_eq(f"{mode}: nothing is recorded as passed", judge.passes(root, "QA-1"), [])
        missing = "\n".join(line for line in SPELLING.splitlines() if not line.startswith("TC-011"))
        refused, _ = split(missing, SCOPE)
        check(f"{mode}: control - a row missing for an id of the scope is refused", any("TC-011" in e for e in refused))
    set_judge(root, {"provider": "typesafe", "mode": "shadow", "api_key_env": "QA_JUDGE_TEST_KEY"})
    judge._post = fake_transport(table)
    collected = ["a/test_x.py::test_one[chromium-alpha]", "a/test_x.py::test_one[firefox-alpha]"]
    node_ids.match(["a/test_x.py::test_one[beta]"], collected, ticket="QA-1", project_root=root)
    check("control: the judge is still asked about a node id, so a zero above is about the digest", len(judge._post.calls) > 0)


def the_word_asked_about_is_the_verdict(root: Path) -> None:
    """Which word the judge is shown, before anything is asked of it. The 0.7.x header carries
    its verdict inside the first field and a sentence of fact at the end; asking about the
    sentence would be a question nobody could answer."""
    legacy = "qa-automator S5 rejected · work/automation-manifest.json · 11 instances green"
    spot = RD.askable(legacy)["verdict"]
    check_eq("the legacy header is asked about its verdict, not its closing fact",
             (spot["word"], spot["where"]), ("rejected", "word"))
    check_eq("and the mapped word goes back where it stood",
             RD.apply(legacy, {"verdict": "concerns"}).split(" · ")[0],
             "qa-automator S5 concerns")
    check_eq("which makes the header parse",
             RD.parse(RD.apply(legacy, {"verdict": "concerns"}))["header"]["verdict"], "concerns")
    current = "qa-code-critic S5 window 2b (TC-007, TC-011) · rejected"
    check_eq("the current header is asked about its last field",
             RD.askable(current)["verdict"]["where"], "field")
    check_eq("a header already in the form raises no question at all",
             RD.askable("qa-runner S6 TC-005 · ok\nTC-005 · passed · ok\nwork/run-report.json"),
             {"verdict": {}, "rows": []})
    check_eq("and neither does prose that carries no id at all",
             RD.askable("I looked at four files and found nothing.\nwork/x.json")["rows"], [])


def an_invented_word_is_advice_not_a_refusal(root: Path) -> None:
    judge._post = fake_transport(table)
    refused, advice = split(INVENTED, ["TC-005"])
    check_eq("a word that means nothing is not guessed at and not refused: it is advice", (refused, bool(advice)), ([], True))
    check_in("the advice names the word", "mostly-fine", "; ".join(advice))
    check_eq("nothing was sent to a judge", len(judge._post.calls), 0)
    check("control: the same digest without its path is refused", bool(split(INVENTED.rsplit("\n", 1)[0], ["TC-005"])[0]))


def the_gate_refusal_keeps_its_prefix(root: Path) -> None:
    """A24 matches refusal texts by prefix: the judge changes what is listed, never the head."""
    import exit_gate as gate
    harness.use_project(root)
    task = root / "qa-factory" / "artifacts" / "QA-1"
    (task / "state").mkdir(parents=True, exist_ok=True)
    (task / "state" / "controller.json").write_text(json.dumps({"dispatches": {
        "S5-qa-code-critic-1": {"id": "S5-qa-code-critic-1", "stage": "S5",
                                "role": "qa-code-critic", "status": "running",
                                "scope": SCOPE}}}), encoding="utf-8")
    saved = gate.artifact_root
    gate.artifact_root = lambda: root / "qa-factory" / "artifacts"
    try:
        judge._post = fake_transport(table)
        check_eq("a digest with only words outside the list is not refused", gate.digest_errors("qa-code-critic", "QA-1", SPELLING), [])
        check("its words are advice in the file", bool(gate._STASH.get(("qa-code-critic", "QA-1", "digest"))))
        errors = gate.digest_errors("qa-code-critic", "QA-1", "qa-code-critic S5 window 2b · rejected")
        check_eq("a digest with no path still prints exactly one refusal", len(errors), 1)
        check("and it still starts with the words A24 matches",
              errors[0].startswith("digest: your final message is not the handoff form."))
        clean = "\n".join(["qa-code-critic S5 window 2b · concerns",
                           "TC-007 · approved · nothing to change",
                           "TC-011 · reviewed · read and judged",
                           "work/reviews/x.json"])
        before = len(judge._post.calls)
        check_eq("a digest already in the form is not sent anywhere",
                 (gate.digest_errors("qa-code-critic", "QA-1", clean), len(judge._post.calls)),
                 ([], before))
        # cmp2 stop 6 (F-cmp2-9): the whole form, then a paragraph and a file list after the path.
        wordy = clean + "\n\nTwo concerns remain on TC-011.\n- work/reviews/x.json\n- tests/api/test_y.py"
        check_eq("the form followed by prose is the form: no refusal, nothing sent to the judge",
                 (gate.digest_errors("qa-code-critic", "QA-1", wordy), len(judge._post.calls)),
                 ([], before))
    finally:
        gate.artifact_root = saved


def an_unreachable_judge_never_passes_a_block(root: Path) -> None:
    calls = []

    def broken(*_a, **_k):
        calls.append(1)
        raise RuntimeError("HTTP 529: overloaded")
    judge._post = broken
    collected = ["a/test_x.py::test_one[chromium-alpha]", "a/test_x.py::test_one[firefox-alpha]"]
    got = node_ids.match(["a/test_x.py::test_one[beta]"], collected, ticket="QA-1", project_root=root)
    check("control: the broken judge was really asked", len(calls) > 0)
    check_eq("a judge that cannot answer leaves the id missing", [m["asked"] for m in got["missing"]],
             ["a/test_x.py::test_one[beta]"])


def a_node_id_is_pinned_only_when_the_judge_is_sure(root: Path) -> None:
    # The real file of TP1-15045's harness: the parameter carries the action AND the
    # fixture that performs it, so no deterministic rule maps `[Reload]` onto it.
    file = "tests/ui/workflows/test_unsaved_changes.py"
    collected = [f"{file}::test_unsaved_changes_after_adding_node[chromium-Reload-reload_page]",
                 f"{file}::test_unsaved_changes_after_adding_workflow_name[chromium-Reload-reload_page]"]
    asked = f"{file}::test_unsaved_changes_after_adding_node[Reload]"
    judge._post = fake_transport(table)
    set_judge(root, {"provider": "typesafe", "mode": "shadow", "api_key_env": "QA_JUDGE_TEST_KEY"})
    watched = node_ids.match([asked], collected, ticket="QA-1", project_root=root)
    check_eq("shadow leaves the id missing", [m["asked"] for m in watched["missing"]], [asked])
    check_in("and says only what it would have done", "shadow", "\n".join(watched["notes"]))
    set_judge(root, {"provider": "typesafe", "mode": "on", "api_key_env": "QA_JUDGE_TEST_KEY"})
    got = node_ids.match([asked], collected, ticket="QA-1", project_root=root)
    check_eq("`on` pins the spelling the judge named", got["resolved"], {asked: collected[0]})
    check_eq("and nothing is left blocking the launch", got["missing"], [])
    check_in("the note names the judge, so the person can see who decided", "form_node_id",
             "\n".join(got["notes"]))
    plain = f"{file}::test_unsaved_changes_after_adding_node[Back]"
    before = len(judge._post.calls)
    one = node_ids.match([plain], [f"{file}::test_unsaved_changes_after_adding_node[chromium-Back]"],
                         ticket="QA-1", project_root=root)
    check_eq("a browser prefix is the deterministic path's business, not the judge's",
             (one["missing"], len(judge._post.calls)), ([], before))
    lonely = node_ids.match(["a/test_x.py::test_gone[p]"], ["a/test_y.py::test_other"],
                            ticket="QA-1", project_root=root)
    check_eq("and a single unrelated candidate is never put to a choice of one",
             [m["asked"] for m in lonely["missing"]], ["a/test_x.py::test_gone[p]"])


def main() -> None:
    the_registry_is_what_the_package_promised()
    the_word_asked_about_is_the_verdict(None)
    root = harness.temp_project("qa-judge-form-")
    os.environ["QA_JUDGE_TEST_KEY"] = "not-a-real-key"
    real_post = judge._post
    try:
        harness.use_project(root)
        (root / "qa-factory" / "artifacts" / "QA-1" / "work").mkdir(parents=True)
        nothing_moves_without_a_provider(root)
        shadow_and_on_ask_nothing_about_a_digest(root)
        an_invented_word_is_advice_not_a_refusal(root)
        the_gate_refusal_keeps_its_prefix(root)
        an_unreachable_judge_never_passes_a_block(root)
        set_judge(root, {"provider": "typesafe", "mode": "on", "api_key_env": "QA_JUDGE_TEST_KEY"})
        a_node_id_is_pinned_only_when_the_judge_is_sure(root)
    finally:
        judge._post = real_post
        harness.cleanup(root)
    harness.finish("test_judge_form")


if __name__ == "__main__":
    main()
