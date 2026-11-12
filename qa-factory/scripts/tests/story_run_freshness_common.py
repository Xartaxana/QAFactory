#!/usr/bin/env python3
"""B-364 (= B-259, D-0027): the driver re-reads the ticket for freshness, on the skill's one command and its one trigger.

`ticket_adapter.py freshness` is the one command and the 6 hour window the one trigger (phases/s0.md section 2b); what
this file holds is the driver's side of it, in process, over a real `file` ticket adapter, a real controller and
spies on `py_stdout` (the adapter's answers where a real one cannot be made to give them), `log_append` (the real
journal is read) and the role runs (`run_role` is replaced by a stub that accepts or leaves running):

  K1  the window at and beyond (T+6h / T+6h+1s), the call's argv and timeout
  K2-K4  `none`, `context`, `requirements` (the question: human words, details, baseline bytes, `.next`, one event)
  K5  `old text`: the declined mark, the whole words kept as a remark, a words file, not asked again
  K6-K7  `new text`: S2 then S3 with cause `ticket_changed` (S3 only after S2 was accepted), gate A reopened with its
         top line (and `prepare_stage S4` before `await_gate A`), S5-S8 work of the scope invalidated; the same with no
         gate A decided (no reopen); the rework's own edges (running, superseded, a second change, no accepted work)
  K8-K9  `stop`, then a no-answer run (asked again from the files, no tracker read); an answer that is not a token
  K10-K14  the exits: throttle at/beyond 6 h and a stamp from the future, timeout, exit 5 (auth, `intermediary`),
         exit 4 / 2 / a non-object, exit 1 by owner
  K15-K20  the positions: not in the process that ran S0, not while another question is open, after the answer is
         recorded, not in the answer run; pasted argv; `launch.ticket_not_needed` written before the pop; no
         controller; a closed story; gate B's check before the rehearsal
  K21-K26  the options constant is in s0.md; no baseline; `.next` after a crash; an answer after `.next` is gone;
         the driver's word is the safe side for the reviewers (judge and route)
"""
# Shared helpers of test_story_run_freshness.py, split by tools/test_split.py (TD-11c).
import contextlib
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq  # noqa: E402
from story_run_common import FIXTURE_TICKET, driver_for, s0_journal, seed


KEY = "QA-1"


UTC = timezone.utc


# --- the scaffolding ---------------------------------------------------------------------------------------------
def iso(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


def now_whole() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def adapter(root: Path, env: dict, task_root: Path, *args):
    """The real `ticket_adapter.py freshness` of the project, the way the driver runs it."""
    out = harness.run_script("ticket_adapter.py", "freshness", KEY, "--task-root", str(task_root), "--json", *args,
                             cwd=root, env=env)
    return out, (json.loads(out.stdout) if out.stdout.strip().startswith("{") else {})


def freshness_project(ticket: str = FIXTURE_TICKET):
    """(root, task_root, env, the ticket file): a seeded story, a `file` adapter over tickets/QA-1.md, and the baseline
    the story was built on - written by the adapter's own first look, so its stamp is now (the story has been checked)."""
    root, task_root, env = seed(KEY)
    tickets = root / "tickets"
    tickets.mkdir()
    ticket_file = tickets / f"{KEY}.md"
    ticket_file.write_text(ticket, encoding="utf-8")
    config = root / "qa-factory" / "config.json"
    cfg = json.loads(config.read_text(encoding="utf-8"))
    cfg["adapters"] = {"ticket": {"kind": "file", "path": str(tickets)}}
    config.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    (task_root / "work" / "ticket-freshness.json").unlink()          # seed stamped it; the first look must write the baseline
    out, got = adapter(root, env, task_root)
    check_eq("setup: the adapter's first look writes the baseline", (out.returncode, got.get("result")), (0, "baseline_written"))
    return root, task_root, env, ticket_file


def record(task_root: Path) -> dict:
    return json.loads((task_root / "work" / "ticket-freshness.json").read_text(encoding="utf-8"))


def set_checked(task_root: Path, when: datetime, **extra) -> None:
    path = task_root / "work" / "ticket-freshness.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data.update(checked_at=iso(when), **extra)
    path.write_text(json.dumps(data), encoding="utf-8")


def make_due(task_root: Path) -> None:
    set_checked(task_root, datetime.now(UTC) - timedelta(hours=7))


def edit_requirements(ticket_file: Path) -> None:
    ticket_file.write_text(ticket_file.read_text(encoding="utf-8").replace(
        "at most 5 tags; a sixth tag", "at most 7 tags; an eighth tag"), encoding="utf-8")


def events(root: Path, name: str) -> list:
    return [row for row in s0_journal(root) if row.get("event") == name]


def spy_stdout(driver, answer=None):
    """Record every `py_stdout` call as (script, args, kwargs); `answer(args, kwargs)` -> (code, out, err) stands in for the
    adapter, or None passes the call on to the real thing."""
    calls = []
    real = driver.py_stdout

    def spy(script, *args, **kwargs):
        calls.append((script, args, kwargs))
        if answer is not None and script == "ticket_adapter.py":
            return answer(args, kwargs)
        return real(script, *args, **kwargs)
    driver.py_stdout = spy
    return calls


def adapter_calls(calls: list) -> list:
    return [c for c in calls if c[0] == "ticket_adapter.py"]


def looked(driver, *args, **kwargs):
    """(what `ticket_freshness` returned or raised, what it printed)."""
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            got = driver.ticket_freshness(*args, **kwargs)
    except Exception as exc:
        got = exc
    return got, printed.getvalue()


def entered(driver):
    """(what `ticket_freshness_entry` returned or raised, what it printed): a mutant that lets a look through is a FAIL
    line here, never a crash."""
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            got = driver.ticket_freshness_entry()
    except Exception as exc:
        got = exc
    return got, printed.getvalue()


def person_of(got):
    import story_run
    return got if isinstance(got, story_run.Person) else None


def question_of(driver, person) -> str:
    """The question as `ask()` writes it, the file the person reads."""
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        driver.ask(person)
    return driver.question_path().read_text(encoding="utf-8")


def answer_file(root: Path, words: str) -> str:
    path = root / "answer.md"
    path.write_bytes(words.encode("utf-8"))
    return str(path)


def asked_driver(root: Path, env: dict, task_root: Path, ticket_file: Path, **overrides):
    """A driver that has asked the changed-ticket question: the requirements moved, the check was due, the question is open."""
    edit_requirements(ticket_file)
    make_due(task_root)
    driver = driver_for(root, env, KEY, **overrides)
    got, _ = looked(driver)
    person = person_of(got)
    check("setup: the requirements moved, so the question is asked", person is not None and person.kind == "ticket_changed", repr(got))
    question_of(driver, person)
    return driver, person


# --- K10-K14 the exits ----------------------------------------------------------------------------------------------
def fixed_adapter(code: int, out: str = "", err: str = ""):
    return lambda args, kwargs: (code, out, err)
