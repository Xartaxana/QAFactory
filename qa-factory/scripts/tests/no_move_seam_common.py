#!/usr/bin/env python3
"""The one seam "no move" (conductor/1, C1-1): `Driver.no_move` and the pure half in `no_move.py`.

In-process, with `conductor` stubbed on the driver (no `claude`, no network): the cases are N1 one `why` at a time, N2 the moves
filter (one positive and one negative per row, every adversarial input on the safe side), N3 `options` authoritative, N4 the
cap AT and BEYOND, N5 the gate kinds, N9 the edges, and the pins that tie the carriers (MOVE_FACTS keys == moves[].id; the labels
of `price_lines` == item 6 of human-questions.md)."""
# Shared helpers of test_no_move_seam.py, split by tools/test_split.py (TD-11c).
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from story_run_common import driver_for, seam_option, seed  # noqa: E402
import no_move as NM  # noqa: E402
import story_run  # noqa: E402


TWO = (("retry", "person_does"), ("stop", "stop_here"))


QUESTION = "What should happen? `retry` once you have dealt with it, or `stop`."


def verdict(tokens=TWO, question=QUESTION, action="ask_person", **extra):
    # RN1-9: a conductor question names a class and what it read; the DEFAULT keeps every key of this file on the road of a usable answer,
    # and a case that wants the refusal overrides it (`why_person=None`, `checked=""`)
    return dict({"action": action, "did": "looked", "question": question, "why_person": "access", "checked": "the refusal",
                 "options": [seam_option(token, move) for token, move in tokens]}, **extra)


def rig(task="QA-9", answers=None):
    """A driver whose conductor is a stub: `answers` is the list of verdicts it gives; `calls` collects the prompts."""
    root, task_root, env = seed(task)
    driver = driver_for(root, env, task)
    driver.calls, driver.defects = [], []
    queue = list(answers or [])

    def conductor(text, *, words="", files=None, words_file=None):
        count = driver.conductor_calls.get(driver.boundary, 0)
        if count >= story_run.CONDUCTOR_CALLS_PER_BOUNDARY:
            raise story_run.ConductorSpent(count, text)
        driver.calls.append({"text": text, "words": words, "words_file": words_file})
        driver.conductor_calls[driver.boundary] = count + 1
        return queue.pop(0) if queue else verdict()
    driver.conductor = conductor
    real_py = driver.py
    driver.py = lambda script, *a, **k: (driver.defects.append(a), (0, ""))[1] if script == "log_append.py" and "defect_found" in a else real_py(script, *a, **k)
    return root, task_root, driver


def raised(driver, state, moves=None):
    try:
        return driver.no_move(state, moves), None
    except story_run.Person as person:
        return None, person


FACTS = {"dispatch_status": "blocked", "session": True, "running": False, "closed": False, "attempts": 0,
         "rework_stages": [], "stand_authorized": False, "live_exclusions": False}


def seam_asked(driver, options=TWO, *, stage="S5", dispatch="S5-qa-x-1", block="", kind="conductor", words_file="", why="unread_answer"):
    """Open a question the way the seam raises one (a Person carrying `offered`), through `ask()` as the run does."""
    person = story_run.Person(kind, "What now? `retry` or `stop`?\n\n(a) `retry` - looks again", stage, dispatch)
    person.offered = tuple(token for token, _ in options)
    person.options = [{"token": token, "move": move} for token, move in options]
    person.words_file, person.why, person.block = words_file, why, block
    driver.ask(person)


def answer(task_root, name, data: bytes):
    path = task_root / name
    path.write_bytes(data)
    return path


def take(driver, path):
    """`take_answer`: None when it came back, else the Person the seam raised from inside it."""
    try:
        driver.take_answer(path)
        return None
    except story_run.Person as person:
        return person


def logged_rig(answers=None):
    """`rig` with every `log_append` call collected in `driver.logged` (and the judge of the reply switched off)."""
    root, task_root, driver = rig(answers=answers)
    driver.logged, inner = [], driver.py
    driver.py = lambda script, *a, **k: (driver.logged.append(a), inner(script, *a, **k))[1] if script == "log_append.py" else inner(script, *a, **k)
    driver.judged_reply = lambda *a, **k: ""
    driver.no_move_facts = lambda state: dict(FACTS)
    return root, task_root, driver


SITE_Q = "Which of these should happen? `read` or `stop`?"


def _site_ok(doors, spec, normalize) -> bool:
    try:
        NM.site_check(doors, spec, normalize)
        return True
    except NM.DataUnreadable:
        return False
