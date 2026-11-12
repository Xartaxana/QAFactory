#!/usr/bin/env python3
"""t-1957 N1c: the step `fill-new-account <selector> user|secret [template]` and the lock on `CreatedAccounts.add`.

The browser is a FAKE (test_manual_observe.ObsBrowser over scaffold.FakeBrowser); everything the factory owns is real: `parse_steps`,
the step loop, the sign-in window, the secret scan, the redaction, `CreatedAccounts` (two files, one lock) and `resolve_actor`.
The pair is fixed by replacing `MC.generated_account` where a test needs to know the value it must not find.

Mutation -> the ONE test that kills it: no lock around the read-modify-write of `CreatedAccounts.add` -> test_concurrent_add_keeps_both;
the secret in the names file / the steps line / the answer -> test_records_name_never_value; a typed value that skips `account.hide`
-> test_records_name_never_value; no `safe_to_break` check -> test_not_safe_to_break_refused; `secret` typing a value nobody
recorded -> test_secret_before_user_refused; the window not opened by the new word -> test_opens_signin_window; a refused sign-up left
usable (no `unconfirmed` mark, or `password_of` answering for it) -> test_refused_signup_is_unconfirmed; no placeholder check or no
default template -> test_email_template; a generated value that matches a secret pattern stored -> test_pattern_match_never_stored.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402
import test_manual_capture as TMC  # noqa: E402
import test_manual_observe as O  # noqa: E402

MC = S.MC
UI, CASE = TMC.UI, S.CASES["ui"]
SIGN_IN, HOME = S.SIGN_IN_URL, S.HOME_URL
NAME = "qa-factory-fixed-name-0001"
PW = "NEWPW-SENTINEL-7c3e91"
TOKEN_SHAPED = "eyJ" + "a" * 12 + ".eyJ" + "b" * 12 + ".sig"       # built, so this file itself matches no secret pattern
FORM = f"goto {SIGN_IN}\n" 'fill-new-account "#email" user\n' 'fill-new-account "#pw" secret\n' "click submit\n"
SAFE = "a test stand, rebuilt nightly"


def config(safe=SAFE):
    cfg = S.config()
    if safe is not None:
        cfg["environments"][0]["safe_to_break"] = safe
    return cfg


def make(safe=SAFE):
    return S.make_task(cfg=config(safe))


class Fixed:
    """`MC.generated_account` returns the given pairs in turn (the last one repeats); put back on exit."""

    def __init__(self, *pairs):
        self.pairs, self.seen = list(pairs), 0

    def __enter__(self):
        self.original = MC.generated_account

        def make_pair(task_root, case):
            pair = self.pairs[min(self.seen, len(self.pairs) - 1)]
            self.seen += 1
            return pair
        MC.generated_account = make_pair
        return self

    def __exit__(self, *exc):
        MC.generated_account = self.original


class EchoAfterFill(O.ObsBrowser):
    """A page that shows the new account's words only once something was typed (before that the account does not exist to be shown)."""

    def page_words(self, mode=None):
        text = super().page_words(mode)
        return text if any(c[0] == "fill" for c in self.calls) else "Home"


def store_of(t):
    return MC.created_account_store(t.task)


def rows(path):
    return MC.CreatedAccounts._rows(Path(path))


def last_steps(t):
    """The steps.jsonl rows of the newest attempt: the summary row of an ok step carries no detail, the file does."""
    root = MC.case_root(t.task, CASE)
    return TMC.jsonl(root / MC.attempts_of(root)[-1] / "steps.jsonl")


def fills(browser):
    return [c[1:] for c in browser.calls if c[0] == "fill"]


# --------------------------------------------------------------------------------------------

def test_records_name_never_value():
    t = make()
    try:
        words = f"Welcome {NAME} your key is {PW}"
        with Fixed((NAME, PW)):
            code, s, out, err, b = O.run(t, FORM, EchoAfterFill(flow=True, short=words, long=words, words=words))
        check_eq("the sign-up steps ran (exit 0)", code, 0)
        check_eq("the name and the secret were typed, by code", fills(b), [("#email", NAME), ("#pw", PW)])
        store = store_of(t)
        check_eq("the names file holds the name, the case and the endpoint, no secret",
                 [(r["name"], r["case"], r["endpoint"]) for r in rows(store.names_path)], [(NAME, CASE, "/auth/sign-in")])
        check_not_in("the names file carries no secret", PW, store.names_path.read_text(encoding="utf-8"))
        check_eq("the machine-local file keeps the pair", [(r["name"], r["password"]) for r in rows(store.secret_path)], [(NAME, PW)])
        check("the machine-local file is not under the story's folder", t.task not in store.secret_path.parents, str(store.secret_path))
        check_eq("the steps say the account by name and [generated]",
                 [r["detail"] for r in last_steps(t) if r["step"].startswith("fill-new-account")], [f"created:{NAME} [generated]"] * 2)
        everything = S.tree_text(t.task) + out + err
        check_not_in("the secret is in no file of the story and not in the output", PW, everything)
        check_in("the excerpt of a step after the account exists hides it", "[redacted]", s["steps"][1]["text"])
        check_eq("password_of gives the secret to the code that signs in", store.password_of(NAME), PW)
    finally:
        S.cleanup(t)


def test_secret_before_user_refused():
    t = make()
    try:
        code, s, out, err, b = O.run(t, f"goto {SIGN_IN}\n" 'fill-new-account "#pw" secret\n', O.ObsBrowser())
        last = last_steps(t)[-1]
        check_eq("a secret with no user before it is refused", (code, last["outcome"]), (1, "refused"))
        check_in("... with the door: type the user first", "type the user first", last["detail"])
        check_eq("... and nothing was typed", fills(b), [])
        check("... and nothing was recorded", not store_of(t).secret_path.exists() and not store_of(t).names_path.exists(), "a file exists")
    finally:
        S.cleanup(t)


def _worker(task_root, tag, count, go):
    """One of two processes adding `count` users to the same story."""
    deadline = time.monotonic() + 30
    while not Path(go).exists() and time.monotonic() < deadline:
        time.sleep(0.005)
    store = MC.created_account_store(task_root)
    for number in range(count):
        store.add(f"{tag}-{number}", f"pw-{tag}-{number}", "CASE", "/x")


def test_concurrent_add_keeps_both():
    t = make()
    try:
        go, count = t.task / "go.flag", 25
        procs = [subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(t.task), tag, str(count), str(go)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for tag in ("A", "B")]
        go.write_text("go", encoding="utf-8")
        results = [p.communicate(timeout=120) + (p.returncode,) for p in procs]
        check_eq("both processes ended well", [r[2] for r in results], [0, 0])
        store = store_of(t)
        want = sorted(f"{tag}-{n}" for tag in ("A", "B") for n in range(count))
        check_eq("every name of both processes is in the names file", sorted(r["name"] for r in rows(store.names_path)), want)
        check_eq("every secret of both processes is in the machine-local file (a created password is never lost)",
                 sorted((r["name"], r["password"]) for r in rows(store.secret_path)), sorted((n, "pw-" + n) for n in want))
    finally:
        S.cleanup(t)


def test_email_template():
    t = make()
    try:
        with Fixed((NAME, PW)):
            code, s, out, err, b = O.run(t, FORM.replace('"#email" user', '"#email" user "{generated_username}@example.test"'),
                                         O.ObsBrowser(flow=True))
        check_eq("the template shapes the name that is typed", (code, fills(b)[0]), (0, ("#email", f"{NAME}@example.test")))
        check_eq("... and the name that is recorded", [r["name"] for r in rows(store_of(t).names_path)], [f"{NAME}@example.test"])
        check_eq("... while the secret is the pair's", fills(b)[1], ("#pw", PW))
        check_eq("the data row is the default template", MC.spec()["generated_user_template"], "{generated_username}")
        # a template without the placeholder is refused, before the browser opens, naming it
        t2 = make()
        try:
            browser = O.ObsBrowser()
            code, out, err, _ = TMC.ui_run(t2, f'goto {UI}\nfill-new-account "#e" user "plain@example.test"\n', browser)
            check_eq("a template with no placeholder: exit 2, before the browser", (code, browser.opened), (2, None))
            check_in("... naming the placeholder", "{generated_username}", err)
            code, out, err, _ = TMC.ui_run(t2, f'goto {UI}\nfill-new-account "#e" secret "{{generated_username}}@x"\n', O.ObsBrowser())
            check_eq("a template on a secret is refused (exit 2)", code, 2)
            code, out, err, _ = TMC.ui_run(t2, f'goto {UI}\nfill-new-account "#e" name\n', O.ObsBrowser())
            check_eq("a kind that is neither user nor secret is refused (exit 2)", code, 2)
            code, out, err, _ = TMC.ui_run(t2, f'goto {UI}\nfill-new-account "#e"\n', O.ObsBrowser())
            check_eq("too few words is refused (exit 2)", code, 2)
            check_in("... with the shape", "<selector> user|secret [template]", err)
            # the data row without the placeholder: the same refusal at the step
            original = MC.spec
            broken = dict(original(), generated_user_template="fixed-name")
            MC.spec = lambda: broken
            try:
                code, s, out, err, b = O.run(t2, FORM, O.ObsBrowser())
            finally:
                MC.spec = original
            check_eq("a data row without the placeholder: the step is refused", (code, s["steps"][-1]["outcome"]), (1, "refused"))
            check_in("... naming the placeholder", "{generated_username}", last_steps(t2)[-1]["detail"])
            check_eq("... and nothing was typed", fills(b), [])
        finally:
            S.cleanup(t2)
    finally:
        S.cleanup(t)


def test_typed_by_character():
    class Keys(O.ObsBrowser):
        def clear_field(self, selector):
            self._call("clear", selector)
            return {"n": 0, "value": "", "focus": True}, 0.1, 0.1

    t = make()
    try:
        with Fixed((NAME, PW)):
            code, s, out, err, b = O.run(t, FORM, Keys(flow=True))
        typed = [c[1:3] for c in b.calls if c[0] == "type"]
        check_eq("a backend that keys a field gets the value character by character", (code, typed),
                 (0, [("#email", NAME), ("#pw", PW)]))
        check_eq("... and `fill` was not used", fills(b), [])
        check_not_in("... the key log holding the value is stored nowhere", PW, S.tree_text(t.task) + out + err)
    finally:
        S.cleanup(t)


def test_not_safe_to_break_refused():
    for label, safe in (("absent", None), ("false", False), ("empty", "  ")):
        t = make(safe)
        try:
            code, s, out, err, b = O.run(t, FORM, O.ObsBrowser())
            last = last_steps(t)[-1]
            check_eq(f"{label}: the step is refused", (code, last["outcome"]), (1, "refused"))
            check_in(f"{label}: the words", "this stand may not be changed", last["detail"])
            check_in(f"{label}: a door for the role", "fill-account", last["detail"])
            check_eq(f"{label}: nothing typed, nothing recorded", (fills(b), store_of(t).secret_path.exists()), ([], False))
        finally:
            S.cleanup(t)
    for label, safe in (("a note", SAFE), ("true", True)):
        t = make(safe)
        try:
            code, s, out, err, b = O.run(t, FORM, O.ObsBrowser(flow=True))
            check_eq(f"control, safe_to_break is {label}: the account is made", (code, len(fills(b))), (0, 2))
        finally:
            S.cleanup(t)


def test_opens_signin_window():
    t = make()
    try:
        code, s, out, err, b = O.run(t, f"goto {SIGN_IN}\n" 'fill-new-account "#email" user\ncapture post_action completion\n', O.ObsBrowser())
        check_eq("a capture right after the new account's field is refused", (code, s["steps"][-1]["outcome"]), (1, "refused"))
        check_in("... by the sign-in window", "no screenshot: the sign-in form may show the account", s["failed"]["detail"])
        check_eq("... and no screen of the form was saved", O.attempt_pngs(t), ["observe/001-goto.png"])
        code, s, out, err, b = O.run(t, FORM + "capture post_action completion\n", O.ObsBrowser(flow=True))
        check_eq("control: after the page left the sign-in address the window is shut and the capture runs", code, 0)
    finally:
        S.cleanup(t)


def test_refused_signup_is_unconfirmed():
    t = make()
    try:
        words = "That email is already taken"
        with Fixed((NAME, PW)):
            code, s, out, err, b = O.run(t, FORM + 'read "#welcome"\n', O.ObsBrowser(flow=False, short=words, long=words, missing={"#welcome"}))
        check_eq("the step after the refused sign-up fails", (code, s["steps"][-1]["outcome"]), (1, "failed"))
        store = store_of(t)
        names, secret = rows(store.names_path)[0], rows(store.secret_path)[0]
        check_eq("both rows say unconfirmed", (names["status"], secret["status"]), ("unconfirmed", "unconfirmed"))
        check_in("the names row carries the page's words", "already taken", names["reason"])
        check_not_in("... and no secret", PW, json.dumps(names))
        check_eq("password_of does not hand the refused account's secret over", store.password_of(NAME), None)
        stand = t.cfg["environments"][0]
        try:
            MC.resolve_actor(t.cfg, stand, f"created:{NAME}", t.task)
            said = ""
        except ValueError as exc:
            said = str(exc)
        check_in("--as created:<name> of it is refused, saying unconfirmed", "unconfirmed", said)
        check_not_in("... without the secret", PW, said)
        # control: a sign-up that landed stays usable
        t2 = make()
        try:
            with Fixed((NAME, PW)):
                code, s, out, err, b = O.run(t2, FORM + 'read "#welcome"\n', O.ObsBrowser(flow=True, missing={"#welcome"}))
            check_eq("control: the step fails after a sign-up that LEFT the form", (code, s["steps"][-1]["outcome"]), (1, "failed"))
            check_eq("control: ... and the account is not marked", [r.get("status") for r in rows(store_of(t2).names_path)], [None])
            values = MC.resolve_actor(t2.cfg, t2.cfg["environments"][0], f"created:{NAME}", t2.task)[2]
            check_eq("control: ... and `created:<name>` gives its pair to the code", values, {"username": NAME, "password": PW})
        finally:
            S.cleanup(t2)
    finally:
        S.cleanup(t)


def _signup(form_url, tail, browser, safe=SAFE):
    """One sign-up run: `FORM` on `form_url` plus `tail`; (code, summary, task, store). The caller cleans the task up."""
    t = make(safe)
    with Fixed((NAME, PW)):
        code, s, out, err, b = O.run(t, FORM.replace(SIGN_IN, form_url) + tail, browser)
    return code, s, t, store_of(t)


def _status(store):
    return [r.get("status") for r in rows(store.names_path)], [r.get("status") for r in rows(store.secret_path)]


def test_unconfirmed_until_seen_to_land():
    """F11: the live recipe's `url_not` holds neither /register nor /login, so the sign-up page is outside it and the window closes at
    once; the account is still not an identity until a step shows a page other than the form's."""
    register = HOME + "register"
    words = "That email is already taken"
    refused = dict(flow=False, short=words, long=words, missing={"#welcome"})
    # B: the form is outside url_not, refused, a later step fails
    code, s, t, store = _signup(register, 'read "#welcome"\n', O.ObsBrowser(**refused))
    try:
        check_eq("B: the later step fails", (code, s["steps"][-1]["outcome"]), (1, "failed"))
        check_eq("B: both rows say unconfirmed", _status(store), (["unconfirmed"], ["unconfirmed"]))
        check_eq("B: password_of gives nothing", store.password_of(NAME), None)
        check_in("B: the page's words replace the reason", "already taken", rows(store.names_path)[0]["reason"])
    finally:
        S.cleanup(t)
    # C: the same, no later step at all - an unknown is not a pass
    code, s, t, store = _signup(register, "", O.ObsBrowser(**refused))
    try:
        check_eq("C: no later step: exit 0", code, 0)
        check_eq("C: both rows still say unconfirmed", _status(store), (["unconfirmed"], ["unconfirmed"]))
        check_eq("C: password_of gives nothing", store.password_of(NAME), None)
        check_in("C: the reason says it was not seen to land", "not been seen to land", rows(store.names_path)[0]["reason"])
        try:
            MC.resolve_actor(t.cfg, t.cfg["environments"][0], f"created:{NAME}", t.task)
            said = ""
        except ValueError as exc:
            said = str(exc)
        check_in("C: `created:<name>` is refused, saying unconfirmed", "unconfirmed", said)
        check_in("C: ... in the new words", "refused or was not seen to land", said)
    finally:
        S.cleanup(t)
    # the sign-up page is the sign-in page and stays: refused with no later step
    code, s, t, store = _signup(SIGN_IN, "", O.ObsBrowser(**refused))
    try:
        check_eq("A: on the sign-in address, no later step: unconfirmed", (code, _status(store)), (0, (["unconfirmed"], ["unconfirmed"])))
    finally:
        S.cleanup(t)
    # a goto away is no proof, and a later step on the page it went to is none either
    for label, tail in (("a goto alone", f"goto {HOME}projects\n"), ("a goto and a click", f"goto {HOME}projects\nclick other\n")):
        code, s, t, store = _signup(register, tail, O.ObsBrowser(**refused))
        try:
            check_eq(f"{label} is no proof of the sign-up", (code, _status(store)), (0, (["unconfirmed"], ["unconfirmed"])))
        finally:
            S.cleanup(t)
    # control: the page left the form's path by the submit - confirmed, an identity, on the form outside url_not and on the sign-in page
    for label, form in (("outside url_not", register), ("on the sign-in address", SIGN_IN)):
        code, s, t, store = _signup(form, "", O.ObsBrowser(flow=True))
        try:
            check_eq(f"control, the form {label}, the submit leaves it: confirmed", (code, _status(store)), (0, ([None], [None])))
            check_eq(f"control, {label}: the status and reason are gone", ["reason" in r for r in rows(store.names_path)], [False])
            check_eq(f"control, {label}: password_of gives the pair", store.password_of(NAME), PW)
        finally:
            S.cleanup(t)
    # a later failure elsewhere does not touch an account that landed
    code, s, t, store = _signup(register, 'read "#welcome"\n', O.ObsBrowser(flow=True, missing={"#welcome"}))
    try:
        check_eq("a landed account is not marked by a later failure", (code, _status(store)), (1, ([None], [None])))
    finally:
        S.cleanup(t)


def test_safe_to_break_words():
    """F12: a string that IS a `no` word does not pass (the whole value, stripped, case-folded); a sentence that begins with one does."""
    rows_no = MC.spec()["safe_to_break_no"]
    check_eq("the data row", rows_no, ["no", "false", "none", "unknown", "n/a"])
    for word in [*rows_no, "No", "  FALSE ", "Unknown\n"]:
        t = make(word)
        try:
            code, s, out, err, b = O.run(t, FORM, O.ObsBrowser(flow=True))
            check_eq(f"safe_to_break {word!r}: refused, nothing typed or recorded",
                     (code, s["steps"][-1]["outcome"], fills(b), store_of(t).secret_path.exists()), (1, "refused", [], False))
        finally:
            S.cleanup(t)
    for sentence in (SAFE, "no data here matters, the stand is rebuilt nightly", "not applicable only to production"):
        t = make(sentence)
        try:
            code, s, out, err, b = O.run(t, FORM, O.ObsBrowser(flow=True))
            check_eq(f"control, the sentence {sentence[:24]!r}: the account is made", (code, len(fills(b))), (0, 2))
        finally:
            S.cleanup(t)


def test_held_lock_names_the_wait():
    """F13: `add` waits `wait_s` for the lock, then raises by name with nothing written; the `http` route passes the long wait."""
    t = make()
    try:
        store = store_of(t)
        with store._locked():
            try:
                store.add("held-user", "held-pw", "CASE", "/x", wait_s=0.2)
                said = ""
            except TimeoutError as exc:
                said = str(exc)
        check_in("a held lock: TimeoutError naming the wait", "held by another walker for over 0.2 s", said)
        check("... and nothing was written", not store.secret_path.exists() and not store.names_path.exists(), "a file exists")
        store.add("held-user", "held-pw", "CASE", "/x", wait_s=0.2)
        check_eq("released: the row is written once", [r["name"] for r in rows(store.names_path)], ["held-user"])
        check_eq("the http route waits long (a user already made on the stand)", MC.ACCOUNT_LOCK_WAIT_HTTP_S, 300)
        source = Path(MC.__file__).read_text(encoding="utf-8")
        check_in("... and passes it", "urlsplit(url).path, wait_s=ACCOUNT_LOCK_WAIT_HTTP_S)", source)
    finally:
        S.cleanup(t)


def test_secret_bound_to_the_item():
    """F14: the pair a walk session keeps on its account belongs to the item that typed the user."""
    original = MC.SessionAccount

    def with_pair(case):
        class Kept(original):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.generated = (case, NAME, PW)
        return Kept
    try:
        for label, case, want in (("another item's pair", "SOME-OTHER-CASE", (1, "refused", [])), ("this item's pair", CASE, (0, "ok", [("#pw", PW)]))):
            t = make()
            try:
                MC.SessionAccount = with_pair(case)
                code, s, out, err, b = O.run(t, f"goto {SIGN_IN}\n" 'fill-new-account "#pw" secret\n', O.ObsBrowser(flow=True))
                check_eq(f"a secret with {label}", (code, s["steps"][-1]["outcome"], fills(b)), want)
                if want[1] == "refused":
                    check_in("... with the door: type the user first", "type the user first", last_steps(t)[-1]["detail"])
            finally:
                S.cleanup(t)
    finally:
        MC.SessionAccount = original


def test_pattern_match_never_stored():
    t = make()
    try:
        with Fixed((NAME, TOKEN_SHAPED), (NAME, PW)) as fixed:
            code, s, out, err, b = O.run(t, FORM, O.ObsBrowser(flow=True))
        check_eq("a generated value that matches a secret pattern is replaced by a fresh pair", (code, fixed.seen, fills(b)[1]),
                 (0, 2, ("#pw", PW)))
        check_not_in("... and the matching value is in no file", TOKEN_SHAPED,
                     S.tree_text(t.task) + S.tree_text(store_of(t).secret_path.parent))
        with Fixed((NAME, TOKEN_SHAPED)) as fixed:
            code, s, out, err, b = O.run(t, FORM, O.ObsBrowser(flow=True))
        check_eq("three matches in a row: the step is refused", (code, s["steps"][-1]["outcome"], fixed.seen), (1, "refused", MC.NEW_ACCOUNT_TRIES))
        check_in("... naming the pattern's index only", "secret_content_patterns[3]", last_steps(t)[-1]["detail"])
        check_not_in("... never the value", TOKEN_SHAPED,
                     S.tree_text(t.task) + S.tree_text(store_of(t).secret_path.parent) + out + err)
    finally:
        S.cleanup(t)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        _worker(sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5])
        return
    test_records_name_never_value()
    test_secret_before_user_refused()
    test_concurrent_add_keeps_both()
    test_email_template()
    test_typed_by_character()
    test_not_safe_to_break_refused()
    test_opens_signin_window()
    test_refused_signup_is_unconfirmed()
    test_unconfirmed_until_seen_to_land()
    test_safe_to_break_words()
    test_held_lock_names_the_wait()
    test_secret_bound_to_the_item()
    test_pattern_match_never_stored()
    finish("test_fill_new_account")


if __name__ == "__main__":
    main()
