#!/usr/bin/env python3
"""The stand (t-017 D2), last third, by the driver in this process with `claude` replaced by the stub: the words the
conductor cannot record, the answer battery, and S1 with the reason the probe gives.

Every scenario builds a Driver in this process, so they run one after another (`run_scenarios([], [...])`). The
helpers, the stub and the runner live in `story_run_common.py`. Continues test_story_run_stand_b.py (t-104).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_in  # noqa: E402
from story_run_common import (  # noqa: E402
    run_scenarios,
    BOM, CUT, OTHER_SCRIPT, d2_answer, d2_conductor_calls, d2_driver, d2_enter, d2_pipeline, d2_seed,
    driver_for, eq, human_broken, s0_pipeline, s0_question, s0_state, seam_control, set_control,
)


def d2_words_the_conductor_cannot_record() -> None:
    """A word that does not pass the block: the conductor asks, the flag is cleared, and the next entry
    asks the stand question again (nothing was passed)."""
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=True)
    try:
        driver, started, steps, probes = d2_driver(root, env, task)
        eq("D2 words: setup - S5 asks", d2_enter(driver, "S5"), 3)
        set_control(root, {"conductor": seam_control("Which stand did you mean by that? Say `retry` once it is settled, or `stop`.", did="nothing")})
        driver, started, steps, probes = d2_driver(root, env, task, answer=d2_answer(root, "hmm, maybe the other one"))
        eq("D2 words: a conductor that cannot record them asks the person", d2_enter(driver, "S5"), 3)
        check_in("D2 words: the conductor's own question", "Which stand did you mean by that?", s0_question(task_root))
        eq("D2 words: the stand question flag is cleared - this is another question", "stand_question" in s0_state(task_root), False)
        eq("D2 words: nothing was passed", s0_pipeline(task_root).get("stage_overrides"), None)
        eq("D2 words: no role started", started, [])
    finally:
        harness.cleanup(root)


def d2_answer_battery() -> None:
    """The stand question takes a person's typing: magnitude, encoding, an empty file. Nothing crashes, a
    10 000-character answer reaches the conductor WHOLE (FR-8), a name survives a BOM, quotes, backticks
    and a full stop, and an empty file changes nothing. In-process."""
    import story_run
    task = "QA-9"
    root, task_root, env = d2_seed(task, environment="Local", pending=True)
    try:
        set_control(root, {"conductor": {"action": "continue", "did": "read it", "text": "Read."}})
        for label, words in (("10 000 characters", "y" * 10000), ("another script", OTHER_SCRIPT)):
            driver = d2_driver(root, env, task)[0]
            eq(f"D2 battery: setup - S5 asks ({label})", d2_enter(driver, "S5"), 3)
            before = len(d2_conductor_calls(root))
            driver = d2_driver(root, env, task, answer=d2_answer(root, words))[0]
            eq(f"D2 battery: {label} - the loop asks again, no crash", d2_enter(driver, "S5"), 3)
            calls = d2_conductor_calls(root)
            eq(f"D2 battery: {label} - one conductor call", len(calls) - before, 1)
            prompt = calls[-1]["prompt"]
            if len(words) <= story_run.NO_MOVE_WORDS_IN_PROMPT:
                check_in(f"D2 battery: {label} - carried whole in its prompt", words, prompt)
            else:
                # C1-1: the prompt carries the first NO_MOVE_WORDS_IN_PROMPT characters and the path of the file that holds the
                # answer WHOLE (FR-8: the carrier of the words is the file, never the prompt)
                check_in(f"D2 battery: {label} - the prompt carries the limit's worth", words[:story_run.NO_MOVE_WORDS_IN_PROMPT], prompt)
                pointer = re.search(r"\(cut; the whole answer is in (.+?)\)", prompt)
                check(f"D2 battery: {label} - and names the file that holds all of it",
                      bool(pointer) and Path(pointer.group(1)).read_text(encoding="utf-8") == words, str(pointer))
        driver = d2_driver(root, env, task)[0]
        eq("D2 battery: setup - S5 asks (empty file)", d2_enter(driver, "S5"), 3)
        for empty in ("", "  \n\t "):
            driver = d2_driver(root, env, task, answer=d2_answer(root, empty))[0]
            eq("D2 battery: an empty answer file is today's Stop", d2_enter(driver, "S5"), story_run.EXIT_ERROR)
            eq("D2 battery: and the question stays open", s0_state(task_root).get("stand_question"), "S5")
        for label, words, name in (("BOM and backticks", BOM + "`staging`", "Staging"),
                                   ("quotes and a full stop", '"Local".', "Local")):
            d2_pipeline(task_root, environment="Other")     # so that the name it becomes can only come from the answer
            before = len(d2_conductor_calls(root))
            driver = d2_driver(root, env, task, answer=d2_answer(root, words))[0]
            d2_enter(driver, "S5")           # the stand behind the name is down: the question is open again afterwards
            eq(f"D2 battery: {label} - read as the stand's name", s0_pipeline(task_root)["environment"], name)
            eq(f"D2 battery: {label} - with no conductor", len(d2_conductor_calls(root)) - before, 0)
    finally:
        harness.cleanup(root)


def d2_s1_and_probe_reason() -> None:
    """(g) the four cases of the stand line in the S1 review, and the probe's first blocking line."""
    import story_run
    task = "QA-9"
    root, task_root, env = d2_seed(task)
    try:
        driver = driver_for(root, env, task)
        cases = [
            ("named and unconfirmed", {"environment": "Local", "environment_pending": True}, ["Local", "Staging"],
             "The stand `Local` did not answer when I checked it; planning goes on, I check it again before the tests run; name another stand here if you want one."),
            ("no name, stands recorded", {"environment": None, "environment_pending": True}, ["Local", "Staging"],
             "Which stand do I test on: Local, Staging?"),
            ("no name, none recorded", {"environment": None, "environment_pending": True}, [],
             "This project records no stand, so nothing is run on one yet; before the tests run I will ask again (the onboarding step named below adds one)."),
            ("named and confirmed", {"environment": "Local", "environment_pending": False}, ["Local", "Staging"],
             "The stand is `Local`."),
        ]
        for label, facts, names, line in cases:
            d2_pipeline(task_root, **facts)
            driver.config["environments"] = [{"name": n} for n in names]
            text = driver.s1_review_text("digest of the scout")
            check_in(f"D2(g) `{label}`: the line", line, text)
            stand_lines = [ln for ln in text.splitlines() if ln.startswith(("The stand", "Which stand", "This project records no stand"))]
            eq(f"D2(g) `{label}`: and only that one stand line", len(stand_lines), 1)
            eq(f"D2(g) `{label}`: the whole review question obeys human-questions.md", human_broken(text), [])
            # t-363 B3 (third site): the plugin's command is an instruction, so it stands in the answer block only - and
            # only in the case that names it
            # (t-373 F7: ONE shape - the command is the Person's `answer_note`, never an inline heading in the text)
            import human_text
            note = human_text.onboarding_note(facts["environment"], names)
            eq(f"D2(g) `{label}`: the text carries no plugin command and no answer heading of its own; the answer note names it "
               "only for `none recorded`",
               ("/qa-factory:" in text, "How to answer" in text, "`/qa-factory:qa-onboarding`" in note),
               (False, False, label == "no name, none recorded"))
        # a story the old S0 wrote (no name, pending false) is read as no name
        d2_pipeline(task_root, environment=None, environment_pending=False)
        driver.config["environments"] = [{"name": "Local"}]
        check_in("D2(g) legacy null/false: read as no name, with the stands offered", "Which stand do I test on: Local?", driver.s1_review_text("d"))
        # t-373 F7: the real road of a refusal to the person's question hands the command over as `answer_note`
        review = ("exit gate for S1-qa-scout-1 (qa-scout, S1): source-inventory.json: required sources remain pending: SRC-1; "
                  "source-inventory.json: no person has reviewed the source decisions yet; digest: your final message is not "
                  "the handoff form")
        for label, facts, names, expected in (("no stand named, none recorded", {"environment": None, "environment_pending": True}, [],
                                               human_text.ONBOARDING_NOTE),
                                              ("stands recorded", {"environment": None, "environment_pending": True}, ["Local"], "")):
            d2_pipeline(task_root, **facts)
            driver.config["environments"] = [{"name": n} for n in names]
            driver.boundary = "S1:S1-qa-scout-1"
            try:
                driver.handle_refusal(story_run.Refusal(review))
                got = ("no question", "")
            except story_run.Person as person:
                got = (person.kind, person.answer_note)
            eq(f"D2(g) F7 the refusal's road to the s1_review question ({label}): the command is the Person's answer note", got,
               ("s1_review", expected))
    finally:
        harness.cleanup(root)
    # the probe's first blocking line, from the shapes env_probe.py prints
    reason = story_run.Driver.probe_reason
    eq("D2 reason: the first line under the Layer-1 heading",
       reason("  base_url (QA_BASE_URL): x\nliveness: dead - x\n\nTHE ENVIRONMENT CANNOT BE USED:\n- the stand does not answer: http://x/health -> NO ANSWER (URLError)\n- the login this project records was refused: y\nLayer 1 is these three lines only"),
       "the stand does not answer: http://x/health -> NO ANSWER (URLError)")
    check_in("D2 reason: the not-configured line", "ENVIRONMENT: not configured", reason("ENVIRONMENT: not configured - the environment block is empty (onboarding fills it in)"))
    eq("D2 reason: nothing printed is said as nothing printed (FR-41)", reason(""), "the probe printed nothing")
    eq("D2 reason: a limit AT 200 characters is not cut", len(reason("THE ENVIRONMENT CANNOT BE USED:\n- " + "x" * 200)), 200)
    cut = reason("THE ENVIRONMENT CANNOT BE USED:\n- " + "x" * 201)
    check("D2 reason: 201 is cut, visibly", cut == "x" * 200 + CUT, cut[-5:])


def main() -> None:
    run_scenarios([], [
        d2_words_the_conductor_cannot_record,
        d2_answer_battery,
        d2_s1_and_probe_reason,
    ])
    harness.finish("test_story_run_stand_c")


if __name__ == "__main__":
    main()
