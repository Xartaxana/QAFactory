#!/usr/bin/env python3
"""TR3-10 D fix round N2 (t-2340): what the `added` option of the `walk_account` question promises the person. The road back for the
tied cases is not proven on every path (a question set aside is asked at gate B, after S6 closed; `added` is no `person_does` move, so
nothing sends S6 again), so the option promises only what is true: the NEXT RUN of the story checks the cases. Pins that sentence and
that the old one ("rejoin the plan") is gone."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import human_text  # noqa: E402
from test_walk_supply import Rig, text_of  # noqa: E402

LINES = ["- Title of TC-1 (TC-1)"]


def added_option_promises_the_next_run():
    rig = Rig()
    try:
        person = rig.driver.walk_account_person("DD-1", "admin", ["TC-1"], LINES)
        check_in("the option says the next run checks the cases", "the next run of the story checks these cases", person.text)
        check_not_in("the old promise is gone", "rejoin", person.text)
        check_not_in("and no claim that they return to the plan at once", "the plan", person.text.split("What should happen")[-1])
        check_eq("the text still obeys human-questions.md", human_text.problems(text_of(person), offered=list(person.priced)), [])
        check_eq("the three tokens are unchanged", list(person.priced), ["added", "by hand", "go on"])
        check("no key path or file of ours in the body", not any(n in person.text for n in ("stand-account", ".json", "project_decisions")))
    finally:
        rig.done()


def main():
    added_option_promises_the_next_run()
    finish("test_walk_account_rejoin")


if __name__ == "__main__":
    main()
