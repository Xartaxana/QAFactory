#!/usr/bin/env python3
"""TR3-10 A: the step `account <handle> confirmed|unconfirmed <why>`, the doubts store and the report's unconfirmed-accounts line.

The browser is a FAKE (test_manual_observe.ObsBrowser); everything the factory owns is real: `parse_steps`, the step loop, the secret scan,
`CreatedAccounts` (two files, one lock), `AccountDoubts` (one file, `event_store.hold_file_lock`) and `resolve_actor`.

Mutation -> the ONE test that kills it: `confirmed` that does not make an identity -> confirmed_created_becomes_identity; a name this story
never created accepted -> confirmed_unknown_name_refused; `unconfirmed` that leaves the user usable -> unconfirmed_created_marked; a doubt
written nowhere -> unconfirmed_given_goes_to_doubts; no lock around the doubts file -> doubts_two_writers_keep_both; a malformed word
recorded -> bad_shape_refused_each; a why with a credential kept -> why_secret_refused_nothing_written; the word counted as an action ->
word_not_acting_legal_after_final; a missing file read as a problem or an unreadable one as none ->
doubts_missing_is_empty_unreadable_is_problem; a busy lock waited for forever or a silent drop -> doubts_lock_busy_names_holder_nothing_written;
the report line without the cut at 5 -> unconfirmed_line_at_5_and_6_names.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
import event_store as ES  # noqa: E402
import report_facts as RF  # noqa: E402
import test_manual_capture as TMC  # noqa: E402
import test_manual_observe as O  # noqa: E402
import walk_session as WS  # noqa: E402

MC = S.MC
CASE = S.CASES["ui"]
SIGN_IN = S.SIGN_IN_URL
NAME, PW = "qa-factory-word-0001", "WORD-PW-SENTINEL-51c2"
SAFE = "a test stand, rebuilt nightly"
TOKEN_SHAPED = "password: '" + "a1" * 12 + "'"       # built, so this file itself matches no secret pattern as written


def make():
    cfg = S.config()
    cfg["environments"][0]["safe_to_break"] = SAFE
    return S.make_task(cfg=cfg)


def run(t, body, browser=None):
    return O.run(t, f"goto {SIGN_IN}\n{body}", browser or O.ObsBrowser())


def steps_of(t):
    root = MC.case_root(t.task, CASE)
    return TMC.jsonl(root / MC.attempts_of(root)[-1] / "steps.jsonl")


def account_rows(t):
    return [r for r in steps_of(t) if r["step"].startswith("account ")]


def seed_unconfirmed(t, name=NAME):
    store = MC.created_account_store(t.task)
    store.add(name, PW, CASE, "/auth/sign-in", status=MC.UNCONFIRMED, reason="the sign-up has not been seen to land")
    return store


def test_confirmed_created_becomes_identity():
    t = make()
    try:
        store = seed_unconfirmed(t)
        assert store.password_of(NAME) is None
        code, s, out, err, b = run(t, f'account created:{NAME} confirmed "a success message on the same page"\n')
        assert code == 0, (out, err)
        assert store.password_of(NAME) == PW
        names = MC.CreatedAccounts._rows(store.names_path)
        assert [(r["name"], r.get("status"), r.get("confirmed_by"), r.get("why")) for r in names] == \
            [(NAME, None, "role", "a success message on the same page")]
        assert "status" not in MC.CreatedAccounts._rows(store.secret_path)[0]
        row = account_rows(t)[0]
        assert row["outcome"] == "ok" and f"account created:{NAME} confirmed" in row["detail"] and "page: /auth/sign-in" in row["detail"]
        assert PW not in S.tree_text(t.task) + out + err
        # on a name already confirmed (by code or by the role): no change, and the step says so
        before = store.names_path.read_text(encoding="utf-8")
        code, s, out, err, b = run(t, f'account created:{NAME} confirmed "again"\n')
        assert code == 0 and "already confirmed; nothing changed" in account_rows(t)[-1]["detail"]
        assert store.names_path.read_text(encoding="utf-8") == before
    finally:
        S.cleanup(t)


def test_confirmed_unknown_name_refused():
    t = make()
    try:
        for handle in ("created:never-made", "created:"):
            code, s, out, err, b = run(t, f'account {handle} confirmed "I saw it"\n')
            assert code == 1 and account_rows(t)[-1]["outcome"] == "refused", (handle, out, err)
            assert "not a user this story created" in account_rows(t)[-1]["detail"]
        store = MC.created_account_store(t.task)
        assert not store.names_path.exists() and not store.secret_path.exists()
        assert MC.account_doubts(t.task) == (set(), "")
    finally:
        S.cleanup(t)


def test_unconfirmed_created_marked():
    t = make()
    try:
        store = MC.created_account_store(t.task)
        store.add(NAME, PW, CASE, "/x")                     # an identity (the `http` route)
        assert store.password_of(NAME) == PW
        code, s, out, err, b = run(t, f'account created:{NAME} unconfirmed "the sign-in page came back"\n')
        assert code == 0, (out, err)
        assert store.is_unconfirmed(NAME) and store.password_of(NAME) is None
        row = MC.CreatedAccounts._rows(store.names_path)[0]
        assert (row["status"], row["reason"]) == ("unconfirmed", "the sign-in page came back")
    finally:
        S.cleanup(t)


def test_unconfirmed_given_goes_to_doubts():
    t = make()
    try:
        code, s, out, err, b = run(t, 'account default unconfirmed "the sign-in page refused it"\n'
                                      'account default unconfirmed "refused twice"\n')
        assert code == 0, (out, err)
        assert MC.account_doubts(t.task) == ({"default"}, "")
        rows = MC.AccountDoubts(t.task).rows()
        assert [(r["handle"], r["why"], r["case"]) for r in rows] == [("default", "refused twice", CASE)]       # one row per handle, the last why
        code, s, out, err, b = run(t, 'account default confirmed "it worked after all"\n')
        assert code == 0 and "needs no confirmation" in account_rows(t)[-1]["detail"]
        assert MC.account_doubts(t.task)[0] == {"default"}                      # `confirmed` on a given handle writes nothing
        code, s, out, err, b = run(t, 'account nobody-role unconfirmed "x"\n')
        assert code == 1 and account_rows(t)[-1]["outcome"] == "refused"        # a handle of no form is refused, nothing written
        assert MC.account_doubts(t.task)[0] == {"default"}
        # F5: two spellings of one stand role are ONE doubt, stored under the stand's real role key (the pool reads that key)
        attempt = MC.Attempt(t.task, CASE, "a-role", S.config())
        account = MC.SessionAccount(stand={"credentials_by_role": {"user": "AUTH_USERNAME / AUTH_PASSWORD in .env"}},
                                    project_root=t.project, task_root=t.task)
        for spelling in ("User", "USER"):
            step = {"n": 1, "line": f'account {spelling} unconfirmed "refused as {spelling}"', "word": "account",
                    "args": [spelling, "unconfirmed", f"refused as {spelling}"]}
            got = MC._run_account_word(O.ObsBrowser(), attempt, step, S.config(), account)
            assert got["entry"]["outcome"] == "ok", got
        by_handle = {r["handle"]: r["why"] for r in MC.AccountDoubts(t.task).rows()}
        assert by_handle == {"default": "refused twice", "user": "refused as USER"}, by_handle
    finally:
        S.cleanup(t)


def _worker(task_root, tag, count, go):
    deadline = time.monotonic() + 30
    while not Path(go).exists() and time.monotonic() < deadline:
        time.sleep(0.005)
    doubts = MC.AccountDoubts(task_root)
    for number in range(count):
        doubts.add(f"env:{tag}_{number}/{tag}_PW", "why", "CASE")


def test_doubts_two_writers_keep_both():
    t = make()
    try:
        go, count = t.task / "go.flag", 20
        procs = [subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(t.task), tag, str(count), str(go)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for tag in ("A", "B")]
        go.write_text("go", encoding="utf-8")
        results = [p.communicate(timeout=120) + (p.returncode,) for p in procs]
        assert [r[2] for r in results] == [0, 0], results
        want = sorted(f"env:{tag}_{n}/{tag}_PW" for tag in ("A", "B") for n in range(count))
        assert sorted(r["handle"] for r in MC.AccountDoubts(t.task).rows()) == want
    finally:
        S.cleanup(t)


def test_bad_shape_refused_each():
    spec = MC.spec()
    shape = spec["steps"]["account"]["args"]

    def refused(line):
        try:
            MC.parse_steps(f"goto {SIGN_IN}\n{line}\n", spec)
        except ValueError as exc:
            return str(exc)
        return ""
    for label, line, needle in (
            ("one word", "account default", shape),
            ("two words", "account default confirmed", shape),
            ("four words", 'account default confirmed "a" "b"', shape),
            ("verdict", 'account default maybe "x"', "confirmed, unconfirmed"),
            ("empty why", 'account default confirmed ""', "why not empty"),
            ("blank why", 'account default confirmed "   "', "why not empty"),
            ("empty handle", 'account "" confirmed "x"', "handle not empty")):
        text = refused(line)
        assert needle in text and "line 2" in text, (label, text)
    assert refused('account default confirmed "' + "w" * 300 + '"') == ""
    over = refused('account default confirmed "' + "w" * 301 + '"')
    assert "at most 300 characters" in over and "301" in over, over
    # nothing is recorded from a malformed word
    t = make()
    try:
        code, s, out, err, b = run(t, "account default unconfirmed\n")
        assert code == 2 and MC.account_doubts(t.task) == (set(), "")
        code, s, out, err, b = run(t, 'account default unconfirmed "' + "w" * 301 + '"\n')
        assert code == 2 and not MC.account_doubts_path(t.task).exists()
    finally:
        S.cleanup(t)


def test_why_secret_refused_nothing_written():
    t = make()
    try:
        code, s, out, err, b = run(t, f'account default unconfirmed "{TOKEN_SHAPED}"\n')
        assert code != 0 and "secret_content_patterns" in err, (code, err)
        assert not MC.account_doubts_path(t.task).exists()
        # the same test inside the word itself (a road that did not scan the text), in a task of its own: the first half's
        # steps.txt is the test's own input file and holds the token by construction
        S.cleanup(t)
        t = make()
        attempt = MC.Attempt(t.task, CASE, "a-secret", S.config())
        account = MC.SessionAccount(stand=None, project_root=t.project, task_root=t.task)
        step = {"n": 1, "line": f'account default unconfirmed "{TOKEN_SHAPED}"', "word": "account", "args": ["default", "unconfirmed", TOKEN_SHAPED]}
        got = MC._run_account_word(O.ObsBrowser(), attempt, step, S.config(), account)
        assert got["entry"]["outcome"] == "refused" and "nothing was written" in got["entry"]["detail"]
        assert TOKEN_SHAPED not in got["entry"]["detail"]
        assert not MC.account_doubts_path(t.task).exists()
        # F6: the refused step must not record the walker's raw line (it holds the why): the token is in no file of the task tree
        assert TOKEN_SHAPED not in got["entry"]["step"] and "secret_content_patterns" in got["entry"]["step"]
        assert TOKEN_SHAPED not in S.tree_text(t.task)
        # and the same when the patterns cannot be scanned
        broken = S.config()
        broken["secret_content_patterns"] = ["(unclosed"]
        step2 = dict(step, line=f'account default confirmed "{TOKEN_SHAPED}"', args=["default", "confirmed", TOKEN_SHAPED])
        got2 = MC._run_account_word(O.ObsBrowser(), attempt, step2, broken, account)
        assert got2["entry"]["outcome"] == "refused" and "could not be scanned" in got2["entry"]["detail"], got2
        assert TOKEN_SHAPED not in S.tree_text(t.task)
    finally:
        S.cleanup(t)


def test_word_not_acting_legal_after_final():
    d = WS.data()
    assert "account" not in WS.acting_words(d) and "account" not in d["final_also_actions"]
    assert "account" not in (MC.spec()["surprise"]["action_steps"] + MC.spec()["surprise"]["input_steps"])
    rows = [{"step": "fill-account #u default user"}, {"step": "click submit"}, {"step": "account default unconfirmed x"}, {"step": "click go"}]
    assert WS.first_action_row(rows, d) == 3                    # the word is neither the submit nor the item's first action
    assert WS.first_action_row(rows[:3], d) == -1
    t = make()
    try:
        code, s, out, err, b = run(t, 'capture post_action completion\naccount default unconfirmed "after the final"\n')
        assert code == 0, (out, err)
        assert [r["outcome"] for r in account_rows(t)] == ["ok"]
    finally:
        S.cleanup(t)


def test_doubts_missing_is_empty_unreadable_is_problem():
    t = make()
    try:
        assert MC.account_doubts(t.task) == (set(), "")
        path = MC.account_doubts_path(t.task)
        path.write_text("{broken", encoding="utf-8")
        handles, problem = MC.account_doubts(t.task)
        assert handles == set() and problem
        path.write_text(json.dumps({"accounts": "no"}), encoding="utf-8")
        assert MC.account_doubts(t.task)[1]
        # a doubt is never written over an unreadable list (the other walkers' doubts would be lost)
        try:
            MC.AccountDoubts(t.task).add("default", "why", "C")
            raise AssertionError("an unreadable list was written over")
        except ValueError as exc:
            assert "Nothing was written" in str(exc)
        assert path.read_text(encoding="utf-8") == json.dumps({"accounts": "no"})
        path.write_text(json.dumps({"accounts": [{"handle": "default", "why": "w"}, "junk", {"why": "no handle"}]}), encoding="utf-8")
        assert MC.account_doubts(t.task) == ({"default"}, "")
    finally:
        S.cleanup(t)


def test_doubts_lock_busy_names_holder_nothing_written():
    t = make()
    try:
        doubts = MC.AccountDoubts(t.task)
        lock_path = MC.account_doubts_path(t.task).with_suffix(".lock")
        held = ES.take_file_lock(lock_path, 0, purpose="test holds it", record_holder=True)
        try:
            try:
                doubts.add("default", "why", "C", wait_s=0.2)
                raise AssertionError("a held lock was passed")
            except TimeoutError as exc:
                text = str(exc)
        finally:
            held.release()
        assert "held by another walker for over 0.2 s: nothing was written. Repeat the step; " in text
        assert "held by process" in text, text                  # the holder clause of TR4-2a, named
        assert not MC.account_doubts_path(t.task).exists()
        doubts.add("default", "why", "C")                         # released: the same call now writes
        assert MC.account_doubts(t.task)[0] == {"default"}
    finally:
        S.cleanup(t)


def test_unconfirmed_line_at_5_and_6_names():
    t = make()
    try:
        assert RF.unconfirmed_accounts_line(t.task) == ""
        for count in (5, 6):
            rows = [{"name": f"qa-factory-u{i}", "case": "C", "at": "t", "endpoint": "/x", "status": "unconfirmed", "reason": f"refused {i}"}
                    for i in range(count)]
            (t.task / "state" / "created-accounts.json").write_text(json.dumps({"accounts": rows}), encoding="utf-8")
            line = RF.unconfirmed_accounts_line(t.task)
            assert line.count("qa-factory-u") == 5 and ("+1 more" in line) == (count == 6), line
        (t.task / "state" / "created-accounts.json").unlink()
        MC.AccountDoubts(t.task).add("env:A/B", "the page said wrong password", "C")
        line = RF.unconfirmed_accounts_line(t.task)
        assert "the stand's account env:A/B (given: the page said wrong password)" in line and line.startswith("Accounts the checks could not")
    finally:
        S.cleanup(t)


def test_created_line_marks_role_confirmed():
    """K10 (F4): a name confirmed on the walker's word is marked with it in the report line; one confirmed by code is not."""
    t = make()
    try:
        store = seed_unconfirmed(t)
        store.add("qa-factory-by-code", PW, CASE, "/x")
        code, s, out, err, b = run(t, f'account created:{NAME} confirmed "a success message on the same page"\n')
        assert code == 0, (out, err)
        line = RF.created_accounts_line(t.task)
        assert f"{NAME} (on the walker's word: a success message on the same page)" in line, line
        assert "qa-factory-by-code," in line or "qa-factory-by-code;" in line, line      # by code: no marker
        assert "qa-factory-by-code (" not in line, line
    finally:
        S.cleanup(t)


def _signup_with(t, word):
    """One call: the sign-up form typed, `word` (a line or ""), then the submit that leaves the form (the code's own confirmation)."""
    original = MC.generated_account
    MC.generated_account = lambda task_root, case: (NAME, PW)
    try:
        body = ('fill-new-account "#email" user\nfill-new-account "#pw" secret\n' + word + "click submit\n")
        return run(t, body, O.ObsBrowser(flow=True))
    finally:
        MC.generated_account = original


def test_role_doubt_beats_code_confirmation_in_the_same_call():
    t = make()
    try:
        code, s, out, err, b = _signup_with(t, f'account created:{NAME} unconfirmed "the page showed no success message"\n')
        assert code == 0, (out, err)
        store = MC.created_account_store(t.task)
        assert store.is_unconfirmed(NAME) and store.password_of(NAME) is None       # the submit left the form, the doubt still stands
        row = MC.CreatedAccounts._rows(store.names_path)[0]
        assert row["status"] == "unconfirmed" and row["reason"] == "the page showed no success message"
    finally:
        S.cleanup(t)


def test_name_without_doubt_is_still_confirmed_by_code():
    t = make()
    try:
        # a doubt about ANOTHER handle changes nothing for the created name
        code, s, out, err, b = _signup_with(t, 'account default unconfirmed "refused"\n')
        assert code == 0, (out, err)
        store = MC.created_account_store(t.task)
        assert not store.is_unconfirmed(NAME) and store.password_of(NAME) == PW
        row = MC.CreatedAccounts._rows(store.names_path)[0]
        assert "status" not in row and "confirmed_by" not in row                    # confirmed by code, as before
    finally:
        S.cleanup(t)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        _worker(sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5])
        sys.exit(0)
    import pytest; sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
