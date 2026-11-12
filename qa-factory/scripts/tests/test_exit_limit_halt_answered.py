"""B-19 (t-1955 N4): the halt a person already saw at `exit_limit` and answered `go on` to is not asked again.

Fast, in-process; the driver is stubbed (no `claude`, no command run). The lead of an `exit_limit` question that said the role halted
keeps a `halt` key (a hash of that digest); `go on` then hands the person's words to the role once (`pending_words`) and the old halt is
not asked again; a NEW halt after that resume is asked; every other road is as before.
"""
import contextlib
import io
import json
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import PLUGIN_ROOT  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import no_move as NM  # noqa: E402
import story_run  # noqa: E402

TASK, D = "QA-9", "S4-qa-case-designer-1"
LINES = ["case_gate: TC-1 has no oracle"]
HALTING = "qa-case-designer S4 window · halt\nI cannot go on: the oracle of TC-1 is unknown."
OTHER_HALT = "qa-case-designer S4 window · halt\nI cannot go on: a different thing is unknown."
OK = "qa-case-designer S4 window · ok"


class Rig:
    def __init__(self, sid="sess-1"):
        from story_run_common import driver_for, seed
        self.root, self.task_root, env = seed(TASK)
        self.driver = d = driver_for(self.root, env, TASK, max_boundaries=1)
        self.calls, self.prompts = [], []
        d.boundary = f"S4:{D}"
        d.state["sessions"][D] = sid
        d.controller_state = lambda: {"dispatches": {D: {"id": D, "stage": "S4", "role": "qa-case-designer", "status": "running",
                                                         "released_by_person": ""}}, "stages": {"S4": {"status": "running"}}}
        d.no_move_facts = lambda state: {"dispatch_status": "running", "closed": False, "gate": ""}
        d.dispatch_role = lambda dispatch: "qa-case-designer"
        d.form_errors = lambda dispatch: []
        d.progress_line = lambda: None
        d.record_running = lambda *a, **k: None
        d.py = lambda script, *a, **k: self.calls.append((script, [str(x) for x in a])) or (0, "")
        d.run_claude = self.claude
        self.next_result = OK

    def claude(self, kind, prompt, **kw):
        self.prompts.append(prompt)
        return {"session_id": "sess-1", "result": self.next_result, "is_error": False, "stderr": "", "total_cost_usd": 0.0, "num_turns": 1}

    def save_result(self, text):
        (self.driver.state_dir / "driver-runs").mkdir(parents=True, exist_ok=True)
        (self.driver.state_dir / "driver-runs" / f"{D}.json").write_text(json.dumps({"result": text}), encoding="utf-8")

    def facts(self, digest=HALTING, sid="sess-1", why="handoff"):
        return self.driver.exit_limit_facts("S4", "qa-case-designer", D, LINES, sid=sid, why=why, digest=digest, error="")

    def ask(self, **kw):
        """The state an open exit_limit question leaves (what the seam writes before it raises)."""
        rec = self.driver.exit_record(D)
        rec.update(lines=LINES, key="k1", stage="S4", role="qa-case-designer")
        rec["ask"] = self.facts(**kw)
        self.driver.save_state()
        return rec["ask"]

    def go_on(self, said="go on", words="go on"):
        """`said`: the person's whole words kept in the words file; `words`: the answer the token is read from."""
        (self.task_root / "state" / "words").mkdir(parents=True, exist_ok=True)
        (self.task_root / "state" / "words" / "a.txt").write_text(said, encoding="utf-8")
        self.driver._answer = {"text": words, "rel": "state/words/a.txt"}
        with contextlib.redirect_stdout(io.StringIO()):
            return self.driver._answer_exit_limit(words, "q", "S4", D, words_file="state/words/a.txt")

    def done(self):
        harness.cleanup(self.root)


def with_rig(fn):
    def run():
        rig = Rig()
        try:
            fn(rig)
        finally:
            rig.done()
    run.__name__ = fn.__name__
    return run


@with_rig
def test_facts_keep_halt_key_for_halting_digest(rig):
    assert rig.facts()["halt"] == rig.driver.halt_key(HALTING) != ""
    assert rig.driver.halt_key("a  b\n c") == rig.driver.halt_key("a b c")      # whitespace-normalised
    assert rig.driver.halt_key("") == "" and rig.driver.halt_key(None) == ""
    assert rig.driver.halt_key(HALTING) != rig.driver.halt_key(OTHER_HALT)


@with_rig
def test_facts_no_halt_key_without_halt(rig):
    assert rig.facts(digest=OK)["halt"] == ""
    assert rig.facts(digest="")["halt"] == ""


@with_rig
def test_facts_no_halt_key_without_session(rig):
    assert rig.facts(sid="")["halt"] == ""
    assert rig.facts(why="session_gone")["halt"] == ""


@with_rig
def test_go_on_option_says_role_reads_words_when_halting(rig):
    def go_on(facts):
        return [o for o in facts["options"] if o["token"] == "go on"][0]
    halted, plain = go_on(rig.facts()), go_on(rig.facts(digest=OK))
    assert "reads your words once in its own session and hands its work over again, because it also said it cannot go on" in halted["says"]
    assert halted["says"].startswith(plain["says"]) and halted["slots"] == {"role": "the case designer"}
    assert plain["slots"] == {}


@with_rig
def test_person_uses_halted_question_id(rig):
    seen = []
    real = rig.driver.closed_question
    rig.driver.closed_question = lambda qid, lead, options: seen.append(qid) or real(qid, lead, options)
    rig.driver.exit_limit_person(rig.facts())
    rig.driver.exit_limit_person(rig.facts(digest=OK))
    assert seen == ["exit.resume_limit_halted", "exit.resume_limit"]


@with_rig
def test_go_on_after_shown_halt_sets_pending_words_whole(rig):
    rig.save_result(HALTING)
    rig.ask()
    said = "go on, the oracle is X\nand also Y"
    assert rig.go_on(said)
    assert rig.driver.state["pending_words"][D] == said
    disk = json.loads((rig.task_root / "state" / "driver-state.json").read_text(encoding="utf-8"))
    assert disk["pending_words"][D] == said
    rig2 = Rig()
    try:                                          # no readable words file -> the answer's own words
        rig2.save_result(HALTING)
        rig2.ask()
        rig2.driver._exit_go_on(rig2.driver.state["exit_limit"][D], "S4", D, "state/words/missing.txt", "go on")
        assert rig2.driver.state["pending_words"][D] == "go on"
    finally:
        rig2.done()
    assert (rig.driver.state["exit_limit"][D]["passes"])        # the waivers were written first


@with_rig
def test_go_on_without_halt_sets_no_words(rig):
    rig.save_result(HALTING)
    rig.ask(digest=OK)
    assert rig.go_on()
    assert D not in rig.driver.state["pending_words"]


@with_rig
def test_go_on_saved_result_changed_sets_no_words(rig):
    rig.save_result(HALTING)
    rig.ask()
    rig.save_result(OTHER_HALT)                  # the role's result changed between the ask and the answer
    assert rig.go_on()
    assert D not in rig.driver.state["pending_words"]


@with_rig
def test_refused_waiver_sets_no_words(rig):
    rig.save_result(HALTING)
    rig.ask()

    def refuse(*a, **k):
        raise story_run.Person("held", "refused", "S4", D)
    rig.driver.pass_block = refuse
    try:
        rig.go_on()
        raise AssertionError("the refused waiver must come out")
    except story_run.Person:
        pass
    assert D not in rig.driver.state["pending_words"]


@with_rig
def test_old_ask_without_halt_key_is_today(rig):
    rig.save_result(HALTING)
    ask = rig.ask()
    del ask["halt"]                              # a story on disk from before N4
    rig.driver.save_state()
    assert rig.go_on()
    assert D not in rig.driver.state["pending_words"]
    person = rig.driver.exit_limit_person(ask)
    assert "exit.resume_limit_halted" not in person.text


@with_rig
def test_wait_existing_job_resumes_instead_of_asking_halt(rig):
    rig.save_result(HALTING)
    rig.driver.state["pending_words"][D] = "the person's words"
    called = []
    rig.driver.resume_role = lambda stage, role, dispatch, words, complete=None: called.append(("resume", stage, dispatch, words))
    rig.driver._finish_saved_result = lambda *a, **k: called.append(("finish",))
    rig.driver._act_wait_existing_job({"dispatch_id": D})
    assert called == [("resume", "S4", D, "the person's words")]


@with_rig
def test_new_halt_after_resume_is_asked_again(rig):
    rig.save_result(HALTING)
    rig.next_result = OTHER_HALT                 # the role answers the words and halts on something else
    rig.driver.handoff = lambda role, stage, dispatch, result: result["result"]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rig.driver.resume_role("S4", "qa-case-designer", D, "the person's words")
        raise AssertionError("a new halt must be asked")
    except story_run.Person as person:
        assert person.kind == "halt"
    assert "the person's words" in rig.prompts[0]
    assert D not in rig.driver.state["pending_words"]


def test_prices_row_exists_and_go_on_is_role_round():
    prices = NM.load_question_prices()
    base = {r["answer"]: r for r in prices["exit.resume_limit"]}
    halted = {r["answer"]: r for r in prices["exit.resume_limit_halted"]}
    assert list(halted) == list(base)
    assert halted["go on"]["factory"] == "role_round" and base["go on"]["factory"] == "command"
    assert {k: v for k, v in halted["go on"].items() if k != "factory"} == {k: v for k, v in base["go on"].items() if k != "factory"}
    for token in ("round", "fresh", "stop"):
        assert halted[token] == base[token]


if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
