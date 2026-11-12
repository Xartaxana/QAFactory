#!/usr/bin/env python3
"""t-1955 N2 (B-17): a login by code the factory does not know is the factory's gap and locks nothing.

Fast: no browser, no network. The rows are written to a temp attempt folder the way `Attempt.env_blocked` writes them
(`env_blocked.json`, `steps.jsonl`); what is real is the code under test - `http_login_source`, `_blocked`,
`choose_attempt`, `_account_steps_gate` and `manual_evidence.build_record`. Pytest collects the `test_*` functions; the
file also runs as a script.
"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import manual_capture as MC  # noqa: E402
import manual_evidence as ME  # noqa: E402

CASE = "TC_014"
UNKNOWN = {"probe_line": "login by code: this project's sign-in is not an HTTP request the factory knows "
                         "(environment.access.kind harness_command); nothing was sent",
           "remedy": "record manual_capture.login.http", "owner": "factory", "do_not_retry": True,
           "cause": MC.LOGIN_UNKNOWN_CAUSE}
OLD_USER_ROW = {"probe_line": "login by code: the account was refused", "remedy": "fix the account", "owner": "user",
                "do_not_retry": True}


class Tmp:
    def __init__(self):
        self.dir = tempfile.TemporaryDirectory(prefix="qa-login-unknown-")
        self.task = Path(self.dir.name).resolve()
        self.root = MC.case_root(self.task, CASE)

    def attempt(self, name="a1", row=None, steps=None, raw_steps=None):
        folder = self.root / name
        folder.mkdir(parents=True, exist_ok=True)
        if row is not None:
            (folder / "env_blocked.json").write_text(json.dumps(row), encoding="utf-8")
        if steps is not None:
            raw_steps = "".join(json.dumps(s) + "\n" for s in steps)
        if raw_steps is not None:
            (folder / "steps.jsonl").write_text(raw_steps, encoding="utf-8")
        return folder


def step(command, outcome, text="a step"):
    return {"at": "2026-11-05T10:00:00", "command": command, "step": text, "outcome": outcome, "detail": ""}


def gate(t, monkey=True):
    """Run `_account_steps_gate` for one `fill-account` step; the actor resolution is a stub (not under test)."""
    real = MC.resolve_actor
    MC.resolve_actor = lambda *a, **k: None
    try:
        MC._account_steps_gate([{"word": "fill-account", "args": ["#u", "user"], "line": "fill-account #u user"}],
                               {}, {}, t.task, CASE)
    finally:
        MC.resolve_actor = real


def refused(fn):
    try:
        fn()
    except ValueError as exc:
        return str(exc)
    return None


def not_known_error(kind="harness_command"):
    cfg = {"environment": {"access": {"kind": kind}}}
    try:
        MC.http_login_source(cfg, MC.spec(), {}, None)
    except MC.EnvBlocked as exc:
        return exc
    raise AssertionError("no EnvBlocked")


def test_not_known_kind_row_is_factory_login_unknown():
    exc = not_known_error()
    assert exc.row["owner"] == "factory"
    assert exc.row["do_not_retry"] is True
    assert exc.row["cause"] == MC.LOGIN_UNKNOWN_CAUSE == "login_unknown"
    assert "fill-account" in exc.row["remedy"] and "nothing was sent" in exc.row["probe_line"]


class StubAttempt:
    name = "a1"

    def env_blocked(self, case, row):
        return dict(row)


def test_blocked_text_says_not_tried_and_no_halt():
    exc = not_known_error()
    err = io.StringIO()
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = MC._blocked(StubAttempt(), CASE, exc)
    text = err.getvalue()
    assert code == MC.EXIT_ENV_BLOCKED
    assert "was not tried" in text and "fill-account" in text and "The block goes on" in text
    assert "halt" not in text.lower() and "did not land" not in text
    assert "owner factory" in text


def test_steps_gate_open_after_login_unknown():
    t = Tmp()
    t.attempt(row=UNKNOWN)
    assert refused(lambda: gate(t)) is None
    # even an owner `user` row carrying the cause never locks (the cause test comes first)
    t.attempt(row=dict(UNKNOWN, owner="user"), steps=[step("ui", "failed")])
    assert refused(lambda: gate(t)) is None


def test_steps_gate_open_for_old_row_without_steps():
    """The F15 shape of TC_014 a1: owner user, do_not_retry, no cause, no steps.jsonl. Never rewritten."""
    t = Tmp()
    folder = t.attempt(row=OLD_USER_ROW)
    before = (folder / "env_blocked.json").read_bytes()
    assert not (folder / "steps.jsonl").exists()
    assert refused(lambda: gate(t)) is None
    assert (folder / "env_blocked.json").read_bytes() == before


def test_steps_gate_locked_for_old_row_last_ui_failed():
    """The negative: a truly refused account (a ui login refused after submit) stays locked."""
    t = Tmp()
    t.attempt(row=OLD_USER_ROW, steps=[step("ui", "ok", "goto"), step("ui", "failed", "login by code")])
    text = refused(lambda: gate(t))
    assert text is not None and "owner user" in text and "fill-account" in text


def test_steps_gate_open_when_failed_see_then_later_row():
    t = Tmp()
    t.attempt(row=OLD_USER_ROW, steps=[step("ui", "failed", "see"), step("http", "ok", "GET /v1/x")])
    assert refused(lambda: gate(t)) is None


def test_steps_gate_locked_for_build_cause():
    t = Tmp()
    t.attempt(row=dict(OLD_USER_ROW, cause="build"))
    assert refused(lambda: gate(t)) is not None


def test_steps_gate_locked_for_device_cause():
    t = Tmp()
    t.attempt(row=dict(OLD_USER_ROW, cause="device"))
    assert refused(lambda: gate(t)) is not None


def test_unreadable_steps_file_no_cause_not_locked():
    t = Tmp()
    t.attempt(row=OLD_USER_ROW, raw_steps="{broken\n\xff not json\n")
    assert refused(lambda: gate(t)) is None
    # non-JSON lines are skipped, the last PARSEABLE row counts; a locking cause locks regardless of the file
    t2 = Tmp()
    t2.attempt(row=OLD_USER_ROW, raw_steps=json.dumps(step("ui", "failed")) + "\n{torn\n")
    assert refused(lambda: gate(t2)) is not None
    t3 = Tmp()
    t3.attempt(row=dict(OLD_USER_ROW, cause="build"), raw_steps="{broken\n")
    assert refused(lambda: gate(t3)) is not None
    t4 = Tmp()
    t4.attempt(row=OLD_USER_ROW, raw_steps="")
    assert refused(lambda: gate(t4)) is None


def test_choose_attempt_login_unknown_says_new_attempt():
    t = Tmp()
    t.attempt(row=UNKNOWN)
    text = refused(lambda: MC.choose_attempt(t.root, "a1"))
    assert text is not None and "not tried" in text and "nothing was sent" in text and "new attempt" in text
    assert "halt" not in text.lower()
    # without --attempt a new row does not reuse the blocked attempt: a new attempt
    assert MC.choose_attempt(t.root, None) == "a2"
    # an old user row (no cause) whose last step is a failed `ui` step (a sign-in was sent and refused) keeps the old refusal, with its halt
    t2 = Tmp()
    t2.attempt(row=OLD_USER_ROW, steps=[step("ui", "failed", "login by code")])
    assert "halt" in refused(lambda: MC.choose_attempt(t2.root, "a1"))


def test_choose_attempt_old_row_without_step_evidence_says_new_attempt():
    """The analog of the steps gate: an old row (owner user, no cause) with no failed `ui` step is opened by the gate, so a named
    `--attempt` on it says what the gate does - capture into a new attempt - and does not print the halt wording. The named attempt
    itself stays refused (a capture never goes into an env_blocked attempt)."""
    for label, kwargs in (("no steps file", {}), ("last step ok", {"steps": [step("ui", "ok", "goto")]}),
                          ("failed `see` then a later row", {"steps": [step("ui", "failed", "see"), step("http", "ok", "GET /v1/x")]})):
        t = Tmp()
        t.attempt(row=OLD_USER_ROW, **kwargs)
        text = refused(lambda: MC.choose_attempt(t.root, "a1"))
        assert text is not None and "new attempt" in text and "fill-account" in text, (label, text)
        assert "halt" not in text.lower(), (label, text)
        assert MC.choose_attempt(t.root, None) == "a2", label
    # a cause that locks (build) keeps the halt wording whatever the steps say
    t3 = Tmp()
    t3.attempt(row=dict(OLD_USER_ROW, cause="build"))
    assert "halt" in refused(lambda: MC.choose_attempt(t3.root, "a1"))


def _build(t):
    (t.root / "request.json").write_text(json.dumps({"case": CASE}), encoding="utf-8")
    return refused(lambda: ME.build_record(t.task, CASE, "inconclusive", "nothing was captured", "generated"))


def test_build_record_login_unknown_says_new_attempt_no_halt():
    t = Tmp()
    t.attempt(row=UNKNOWN)
    text = _build(t)
    assert text is not None and text.startswith(f"attempt a1 of {CASE} has no record: ")
    assert "was not tried and nothing was sent" in text and "new attempt" in text and "fill-account" in text
    assert "halt the block)" not in text and "Put the case in env_blocked" not in text and "did not land" not in text


def test_build_record_build_cause_unchanged():
    t = Tmp()
    t.attempt(row=dict(OLD_USER_ROW, cause="build"))
    text = _build(t)
    assert text is not None and "Put the case in env_blocked[]" in text and "halt the block)" in text
    assert "the stand does not hold this story's build" in text
    t2 = Tmp()
    t2.attempt(row=OLD_USER_ROW)
    assert "the login did not land" in _build(t2)


def test_refusal_texts_are_data_rows():
    table = json.loads((SCRIPTS.parent / "references" / "build-identity-methods.json").read_text(encoding="utf-8"))
    assert "{probe_line}" in table["refusals"]["blocked_login_unknown"]
    words = json.loads((SCRIPTS.parent / "references" / "manual-capture-steps.json").read_text(encoding="utf-8"))
    assert "fill-account" in words["login"]["words"]["not_known_door"]
    src = (SCRIPTS / "manual_capture.py").read_text(encoding="utf-8")
    assert "The block goes on" not in src      # the sentence lives in the data row, not in code


if __name__ == "__main__":
    failed = 0
    total = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            total += 1
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as exc:
                failed += 1
                print(f"FAIL {name}: {exc}")
    print(f"=== test_manual_capture_login_unknown: {total - failed}/{total} ok ===")
    sys.exit(1 if failed else 0)
