#!/usr/bin/env python3
"""t-1539 HF5-4: the agent sees the screen - observation after every step, `fill-account`, the sign-in window.

The browser is a FAKE (scaffold.FakeBrowser) or, for K1 and the `page_words` pins, the REAL `PlaywrightBackend` built
with `__new__` over a stub page (the HF5-1 form: no Playwright import). Everything the factory owns is real: the step
loop (`_run_steps`), the excerpt, the sign-in window, `resolve_actor`/`read_login`, the secret scan, captures.jsonl,
`manual_evidence.py build`.

Mutation -> the ONE test that kills it: a PNG taken inside the sign-in window -> K3; an excerpt that skips `_hide` -> K4;
an observation PNG registered in captures.jsonl -> K1 (and K6); OBSERVE_MAX_STEPS not applied -> K2.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402
import test_manual_capture as TMC  # noqa: E402
import test_manual_step_errors as TSE  # noqa: E402

MC = S.MC
UI, CASE = TMC.UI, S.CASES["ui"]
PKG = HERE.parent.parent
SIGN_IN, HOME = S.SIGN_IN_URL, S.HOME_URL
SIGN_IN_FILE = (f"goto {SIGN_IN}\n" 'fill-account "#email" default user\n' 'fill-account "#pw" default secret\n'
                "click submit\n" f"goto {HOME}projects\n")


class ObsBrowser(S.FakeBrowser):
    """The scaffold's browser with what observation reads: `page_words(mode)`, the URL of the step phase (it follows
    `goto`, and the click of `submit` leaves the sign-in page), and screenshots of the observation dir that can fail."""

    def __init__(self, short="Home", long="Home page body", flow=False, shot_fails=False, words_raise=False, **kw):
        super().__init__(**kw)
        self.short, self.long, self.flow, self.shot_fails, self.words_raise = short, long, flow, shot_fails, words_raise
        self.cur_url, self.in_steps, self.modes = SIGN_IN, False, []

    def page_words(self, mode=None):
        self.modes.append(mode)
        if self.words_raise:
            raise RuntimeError("the page is gone")
        return self.long if mode == "long" else self.short if mode == "short" else self.words

    def goto(self, url):
        self.in_steps, self.cur_url = True, url
        return super().goto(url)

    def click(self, selector):
        if self.flow and selector == "submit":
            self.cur_url = HOME
        return super().click(selector)

    def current_url(self):
        return self.cur_url if self.in_steps else super().current_url()

    def screenshot(self, path):
        if self.shot_fails and "observe" in Path(path).parts:
            raise MC.StepFailed("the screenshot failed")
        return super().screenshot(path)


def run(t, steps, browser=None, extra=()):
    code, out, err, browser = TMC.ui_run(t, steps, browser or ObsBrowser(), extra)
    return code, without_login(json.loads(out) if out.strip().startswith("{") else {}), out, err, browser


def without_login(summary):
    """The summary with the sign-in by code's row taken out of `steps`: the rows the tests index are the steps file's."""
    if "steps" in summary:
        summary["steps"] = [r for r in summary["steps"] if not r["step"].startswith("login by code")]
    return summary


def attempt_pngs(t, attempt="a1"):
    return sorted(p.relative_to(t.attempt_dir(CASE, attempt)).as_posix() for p in t.attempt_dir(CASE, attempt).rglob("*.png"))


def captures_paths(t, attempt="a1"):
    path = t.attempt_dir(CASE, attempt) / "captures.jsonl"
    return [r["path"] for r in TMC.jsonl(path)] if path.is_file() else []


# --------------------------------------------------------------------------------------------
# the real page_words over a stub page
# --------------------------------------------------------------------------------------------

class Text:
    def __init__(self, text, visible=True, fails=False):
        self.text, self.visible, self.fails = text, visible, fails

    def is_visible(self):
        return self.visible

    def inner_text(self, timeout=None):
        if self.fails:
            raise TSE._Timeout("no body")
        return self.text


class Group(Text):
    def __init__(self, items=(), body=None, fails=False):
        super().__init__(body or "", fails=fails)
        self.items = list(items)

    def all(self):
        return self.items


class WordsPage:
    def __init__(self, heading="", dialogs=(), body="", body_fails=False, dialogs_fail=False):
        self.heading, self.dialogs, self.body = heading, list(dialogs), body
        self.body_fails, self.dialogs_fail = body_fails, dialogs_fail

    def locator(self, selector):
        if selector == "h1, h2, [role=heading]":
            return Group([Text(self.heading)] if self.heading else [])
        if selector == "[role=dialog], [role=alert]":
            if self.dialogs_fail:
                raise TSE._Error("dialogs")
            return Group([Text(d) for d in self.dialogs])
        if selector == "body":
            return Group(body=self.body, fails=self.body_fails)
        raise AssertionError(selector)


def words_backend(page):
    backend = MC.PlaywrightBackend.__new__(MC.PlaywrightBackend)
    backend._page, backend._Timeout, backend._Error = page, TSE._Timeout, TSE._Error
    return backend


def page_words_pins():
    page = WordsPage("Projects", ["Guided Tour Available Take a quick tour"], "Projects body text")
    b = words_backend(page)
    check_eq("page_words(None): the failed login's words are still the first heading", b.page_words(), "Projects")
    check_eq("page_words(short): the heading and the dialog", b.page_words("short"),
             "Projects | Guided Tour Available Take a quick tour")
    check_eq("page_words(long): the heading and the body", b.page_words("long"), "Projects | Projects body text")
    check_eq("page_words(short) with no dialog: the body in its place", words_backend(WordsPage("", [], "only body")).page_words("short"),
             "only body")
    check_eq("page_words(long) with no body: the heading alone", words_backend(WordsPage("H", [], "x", body_fails=True)).page_words("long"), "H")
    check_eq("page_words: nothing readable gives the empty text", words_backend(WordsPage("", [], "x", True, True)).page_words("short"), "")
    check_eq("page_words: U+2028 and newlines are one line", words_backend(WordsPage("", [], "a b\nc")).page_words("long"), "a b c")
    huge = words_backend(WordsPage("", [], "x" * (MC.PAGE_TEXT_CHARS * 3))).page_words("long")
    check("page_words: a huge DOM is read up to the cap", len(huge) == MC.PAGE_TEXT_CHARS, str(len(huge)))


# --------------------------------------------------------------------------------------------
# K1: the stand's modal, seen and passed by the role (the HF5-1 K1 state)
# --------------------------------------------------------------------------------------------

class ModalLoc:
    def __init__(self, page, selector):
        self.page, self.selector, self.first = page, selector, self

    def count(self):
        return 1

    def is_visible(self):
        return True

    def is_enabled(self):
        return True

    def bounding_box(self, **kw):
        return {"x": 10, "y": 20, "width": 100, "height": 40}

    def evaluate(self, script, arg):
        return ({"covered": True, "tag": "div", "classes": ["p-dialog-mask"], "text": TSE.COVER_TEXT}
                if self.page.modal else {"covered": False})

    def click(self, timeout=None):
        if self.selector == "text=Maybe Later":
            self.page.modal = False
        elif self.page.modal:
            raise TSE._Timeout(TSE.PW_MESSAGE)


class ModalPage(TSE.Page):
    def __init__(self):
        super().__init__()
        self.modal = True

    def locator(self, selector):
        if selector == "h1, h2, [role=heading]":
            return Group([Text("Projects")])
        if selector == "[role=dialog], [role=alert]":
            return Group([Text(TSE.COVER_TEXT)] if self.modal else [])
        if selector == "body":
            return Group(body="Projects " + (TSE.COVER_TEXT if self.modal else "Select a project"))
        return ModalLoc(self, selector)


class WordsBackend(TSE.RealStepsBackend):
    page_words = MC.PlaywrightBackend.page_words        # the real one: the stub page is what is faked


def modal_run(t, page, steps):
    backend = WordsBackend.make(page)
    (t.task / "steps.txt").write_text(steps, encoding="utf-8")
    TMC.patch_backends(backend)
    code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", CASE, "--steps-file", str(t.task / "steps.txt")])
    return code, without_login(json.loads(out) if out.strip() else {}), err


def k1_the_modal_is_seen_and_passed():
    t = S.make_task()
    try:
        TMC.seed_runtime_records(t)
        page = ModalPage()
        code, summary, err = modal_run(t, page, f'goto {UI}\nclick "#project-selector"\n')
        check_eq("K1: the covered click fails the step (exit 1)", code, 1)
        rows = summary["steps"]
        check_eq("K1: the failed step is the second", [r["outcome"] for r in rows], ["ok", "failed"])
        failed = rows[1]
        check_in("K1: the failed step's text shows the modal", "Guided Tour Available", failed["text"])
        check("K1: the failed step's screenshot is the one in captures.jsonl", failed["screenshot"] in captures_paths(t, "a1"),
              f"{failed['screenshot']} {captures_paths(t, 'a1')}")
        check_in("K1: the passed step's screen is in observe/", "/a1/observe/001-goto.png", rows[0]["screenshot"])
        check("K1: an observation PNG is never in captures.jsonl", not any("/observe/" in p for p in captures_paths(t, "a1")),
              str(captures_paths(t, "a1")))
        check_in("K1: the summary says where the screens of passed steps are", "/a1/observe and are not part of the record",
                 summary["observation"])
        # the role reads the modal, closes it and captures again
        steps = (f"goto {UI}\ncapture pre_action initial\nclick \"text=Maybe Later\"\nclick \"#project-selector\"\n"
                 "capture post_action completion\n")
        code, summary2, err = modal_run(t, page, steps)
        check_eq("K1: the next attempt passes the modal and ends (exit 0)", (code, summary2["attempt"]), (0, "a2"))
        code, out, err = TMC.build(t, CASE, "--result", "pass", "--actual", "the project selector opened", "--masked")
        check_eq("K1: `build --result pass` passes on the attempt that has observe/", code, 0)
        record = json.loads((t.attempt_dir(CASE, "a2") / "record.json").read_text(encoding="utf-8"))
        check("K1: the observation PNGs exist on disk", len(attempt_pngs(t, "a2")) >= 3, str(attempt_pngs(t, "a2")))
        check("K1: no evidence ref is an observation PNG", not any("observe/" in r["path"] for r in record["evidence_refs"]),
              str([r["path"] for r in record["evidence_refs"]]))
    finally:
        S.cleanup(t)


# --------------------------------------------------------------------------------------------
# K2: the limits, AT and BEYOND
# --------------------------------------------------------------------------------------------

def k2_limits():
    t = S.make_task()
    try:
        forty = f"goto {UI}\n" + "wait 1\n" * 39
        code, s, out, err, b = run(t, forty)
        check_eq("K2 40 steps: all observed", sum(1 for r in s["steps"] if "screenshot" in r), 40)
        check_eq("K2 40 steps: 40 observation screens", len(attempt_pngs(t, "a1")), 40)
        check_not_in("K2 40 steps: no limitation", "observation stopped", json.dumps(s["limitations"]))
        forty_one = f"goto {UI}\n" + "wait 1\n" * 40
        code, s, out, err, b = run(t, forty_one)
        check_eq("K2 41 steps: the 41st is not observed", ["screenshot" in r for r in s["steps"]][-2:], [True, False])
        check_eq("K2 41 steps: still 40 observation screens", len(attempt_pngs(t, "a2")), 40)
        check_eq("K2 41 steps: the 41st row keeps step and outcome", sorted(s["steps"][-1]), ["outcome", "step"])
        check_in("K2 41 steps: one limitation says so", "observation stopped after 40 steps", json.dumps(s["limitations"]))
        check_eq("K2 41 steps: the run is not cut short", (code, s["steps"][-1]["outcome"]), (0, "ok"))
        for n, want in ((160, "b" * 160), (161, "b" * 160 + "..."), (1, "b")):
            code, s, out, err, b = run(t, f"goto {UI}\n", ObsBrowser(short="b" * n))
            check_eq(f"K2 a passed step's excerpt at {n}", s["steps"][0]["text"], want)
        for n, want in ((600, "c" * 600), (601, "c" * 600 + "...")):
            code, s, out, err, b = run(t, f"goto {UI}\nclick \"#x\"\n", ObsBrowser(long="c" * n, missing={"#x"}))
            check_eq(f"K2 a failed step's excerpt at {n}", s["steps"][1]["text"], want)
            check_eq(f"K2 a failed step reads the long form at {n}", b.modes[-1], "long")
        # the sum of the excerpts: a run cannot reach it (40 x 160 + 600), so the function is pinned directly
        t2 = S.make_task()
        try:
            att = MC.Attempt(t2.task, CASE, "a1", t2.cfg)

            def rows(last, failed_text=None):
                out_rows = [{"step": f"s{i}", "outcome": "ok", "screenshot": None, "text": "x" * 160} for i in range(49)]
                out_rows.append({"step": "s49", "outcome": "ok", "screenshot": None, "text": "y" * last})
                if failed_text:
                    out_rows.append({"step": "f", "outcome": "failed", "screenshot": None, "text": failed_text})
                return out_rows
            at = MC._summary(att, CASE, rows(160), 0, None, {}, observed=True)
            check_eq("K2 8000: nothing is trimmed", ("observation_trimmed" in at, at["steps"][0]["text"] == "x" * 160), (False, True))
            beyond = MC._summary(att, CASE, rows(161), 0, None, {}, observed=True)
            check_eq("K2 8001: the oldest passed excerpt is emptied and counted", (beyond["steps"][0]["text"], beyond["observation_trimmed"]),
                     ("", 1))
            check_eq("K2 8001: the next one is kept", beyond["steps"][1]["text"], "x" * 160)
            withfail = MC._summary(att, CASE, rows(160, "z" * 600), 0, {"step": "f"}, {}, observed=True)
            check_eq("K2: a failed step's excerpt is never trimmed", withfail["steps"][-1]["text"], "z" * 600)
            check("K2: the passed ones are trimmed from the start instead",
                  withfail["steps"][0]["text"] == "" and withfail["observation_trimmed"] >= 1, str(withfail["observation_trimmed"]))
            plain = MC._summary(att, CASE, [{"step": "a", "outcome": "ok"}], 0, None, {})
            check_eq("K2: an `http` summary has no observation keys", ("observation" in plain, plain["steps"]), (False, [{"step": "a", "outcome": "ok"}]))
        finally:
            S.cleanup(t2)
    finally:
        S.cleanup(t)


# --------------------------------------------------------------------------------------------
# K3: the sign-in window
# --------------------------------------------------------------------------------------------

def k3_the_window():
    t = S.make_task()
    try:
        code, s, out, err, b = run(t, SIGN_IN_FILE, ObsBrowser(flow=True, short=f"Signed in as {S.USER}"))
        check_eq("K3: the sign-in by steps runs (exit 0)", code, 0)
        check_eq("K3: the screens saved are the step before the window and the step after it",
                 attempt_pngs(t), ["observe/001-goto.png", "observe/005-goto.png"])
        check_eq("K3: the steps inside the window carry no screenshot", [r["screenshot"] for r in s["steps"][-4:-1]], [None, None, None])
        check("K3: ... and still carry their text (hidden)", all(r["text"] for r in s["steps"][-4:-1]), str(s["steps"]))
        check_eq("K3: the typed values are the account's", [c[2] for c in b.calls if c[0] == "fill"], [S.USER, S.PASSWORD])
        # a capture inside the window is refused
        code, s, out, err, b = run(t, f"goto {SIGN_IN}\nfill-account \"#email\" default user\ncapture post_action completion\n",
                                   ObsBrowser())
        check_eq("K3: a capture in the window is refused, the run stops", (code, s["steps"][-1]["outcome"]), (1, "refused"))
        check_in("K3: ... with the reason", "no screenshot: the sign-in form may show the account", s["failed"]["detail"])
        check_eq("K3: ... and no screen of the form is saved", [p for p in attempt_pngs(t, "a2") if "001" not in p], [])
        # a failed step in the window has no screenshot; the same failure outside it has one
        code, s, out, err, b = run(t, f"goto {SIGN_IN}\nfill-account \"#email\" default user\nclick \"#nope\"\n",
                                   ObsBrowser(missing={"#nope"}))
        failed = s["steps"][-1]
        check_eq("K3: a failed step in the window: no screenshot", (failed["outcome"], failed["screenshot"]), ("failed", None))
        check_in("K3: ... and the detail says why", "no screenshot: the sign-in form may show the account", s["failed"]["detail"])
        check_not_in("K3: ... and no failed-step PNG was registered", "failed-step", json.dumps(captures_paths(t, "a3")))
        code, s, out, err, b = run(t, f"goto {SIGN_IN}\nclick \"#nope\"\n", ObsBrowser(missing={"#nope"}))
        check("K3 control: outside the window the failed step has its screenshot", s["steps"][-1]["screenshot"] in captures_paths(t, "a4"),
              str(s["steps"]))
        # the window never closes while the URL is still on the sign-in address
        code, s, out, err, b = run(t, SIGN_IN_FILE, ObsBrowser(flow=False))
        check_eq("K3: a sign-in that never leaves the form keeps the window open to the end", attempt_pngs(t, "a5"), ["observe/001-goto.png"])
    finally:
        S.cleanup(t)


# --------------------------------------------------------------------------------------------
# K4: no value anywhere; the actor and the key
# --------------------------------------------------------------------------------------------

def k4_names_not_values():
    t = S.make_task()
    try:
        words = f"Welcome {S.USER} your key is {S.PASSWORD}"
        code, s, out, err, b = run(t, SIGN_IN_FILE, ObsBrowser(flow=True, short=words, long=words, words=words))
        everything = S.tree_text(t.task) + out + err
        check_eq("K4: ran", code, 0)
        check_not_in("K4: the password is in no file of the attempt and not in stdout", S.PASSWORD, everything)
        check_not_in("K4: the account's name neither", S.USER, everything)
        check_in("K4: an excerpt shows [redacted] in their place", "[redacted]", s["steps"][0]["text"])
        lines = [json.loads(x)["step"] for x in (t.attempt_dir(CASE) / "steps.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        check_in("K4: steps.jsonl holds the names", 'fill-account "#email" default user', lines)
        check_in("K4: ... for the secret too", 'fill-account "#pw" default secret', lines)
        # a read of the field's value (attr=value) is hidden too
        code, s, out, err, b = run(t, f"goto {UI}\nread \"#email\" attr=value\n", ObsBrowser(reads={"#email": S.USER}))
        check_not_in("K4: a read value that is the account is not stored", S.USER, S.tree_text(t.task) + out)
        # a secret-looking excerpt keeps only the pattern's index
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig"
        code, s, out, err, b = run(t, f"goto {UI}\n", ObsBrowser(short=f"token {jwt}"))
        check_eq("K4: a JWT in the text is not kept", s["steps"][0]["text"], "(text not kept: matches secret_content_patterns[3])")
        check_not_in("K4: ... nowhere", jwt, S.tree_text(t.task) + out)
        # an unknown actor is refused before the browser opens
        t2 = S.make_task()
        try:
            browser = ObsBrowser()
            code, out, err, _ = TMC.ui_run(t2, f"goto {UI}\nfill-account \"#e\" nobody user\n", browser)
            check_eq("K4: an unknown actor: exit 2", code, 2)
            check_in("K4: ... names the line", 'fill-account "#e" nobody user', err)
            check_in("K4: ... and the door of `--as`", "--as env:USER_KEY/SECRET_KEY", err)
            check_eq("K4: ... before the browser: no attempt, nothing opened", (browser.opened, t2.attempt_dir(CASE).exists()), (None, False))
            code, out, err, _ = TMC.ui_run(t2, f"goto {UI}\nfill-account \"#e\" default name\n", ObsBrowser())
            check_eq("K4: the last word must be user or secret (exit 2)", code, 2)
            code, out, err, _ = TMC.ui_run(t2, f"goto {UI}\nfill-account \"#e\" env:NO_SUCH_USER/NO_SUCH_PW user\n", ObsBrowser())
            check_eq("K4: a key the env file lacks: the step is refused", code, 1)
            row = json.loads(out)["steps"][-1]
            check_eq("K4: ... outcome refused", row["outcome"], "refused")
            check_in("K4: ... naming the key", "NO_SUCH_USER", json.loads(out)["failed"]["detail"])
        finally:
            S.cleanup(t2)
    finally:
        S.cleanup(t)


# --------------------------------------------------------------------------------------------
# K5: do_not_retry and the owner
# --------------------------------------------------------------------------------------------

def k5_owner_of_the_block():
    for owner, want in (("user", 2), ("factory", 0)):
        t = S.make_task()
        try:
            blocked = t.attempt_dir(CASE)
            blocked.mkdir(parents=True)
            (blocked / "env_blocked.json").write_text(json.dumps(
                {"id": CASE, "probe_line": "login by code: did not land", "remedy": "r", "owner": owner, "do_not_retry": True}),
                encoding="utf-8")
            # the real producer (`_login_blocked`) ends the attempt with a failed `ui` step: that is the evidence a login was SENT
            (blocked / "steps.jsonl").write_text(json.dumps({"command": "ui", "outcome": "failed"}) + "\n", encoding="utf-8")
            browser = ObsBrowser(flow=True)
            code, out, err, _ = TMC.ui_run(t, SIGN_IN_FILE, browser)
            check_eq(f"K5 owner {owner}: fill-account after a do_not_retry block", code, want)
            if want == 2:
                check_in("K5: the door is the runner's env_blocked[] line", "env_blocked[] with the printed line", err)
                check_in("K5: ... naming the attempt's line", "login by code: did not land", err)
                check_eq("K5: nothing opened", browser.opened, None)
                code, out, err, _ = TMC.ui_run(t, f"goto {UI}\n", ObsBrowser())
                check_eq("K5 control: the same block without fill-account is not refused by this gate", code, 0)
            else:
                check_eq("K5: the attempt ran as a new one", json.loads(out)["attempt"], "a2")
        finally:
            S.cleanup(t)


# --------------------------------------------------------------------------------------------
# K8 (fix round t-1550): the owner-factory door can be walked; the capture refusal names a real door
# --------------------------------------------------------------------------------------------

def k8_fill_account_makes_no_code_login():
    t = S.make_task()
    try:
        blocked = t.attempt_dir(CASE)
        blocked.mkdir(parents=True)
        (blocked / "env_blocked.json").write_text(json.dumps(
            {"id": CASE, "probe_line": "login by code: the sign-in field was not found", "remedy": "r", "owner": "factory",
             "do_not_retry": True}), encoding="utf-8")
        # F1: the recipe did not fit the page (the code login would fail again), the steps sign in through the form
        browser = ObsBrowser(flow=True, login_error=MC.StepFailed("the sign-in field was not found"))
        code, out, err, _ = TMC.ui_run(t, SIGN_IN_FILE, browser)
        check_eq("K8 F1: last attempt env_blocked owner factory + fill-account: the steps run (exit 0)", code, 0)
        check_eq("K8 F1: ... the backend got NO login call", (browser.credentials_seen, [c for c in browser.calls if c[0] == "login"]),
                 (None, []))
        check_not_in("K8 F1: ... and the summary holds no `login by code` row", "login by code", out)
        check_eq("K8 F1: ... typed the account through the form", [c[2] for c in browser.calls if c[0] == "fill"], [S.USER, S.PASSWORD])
        # `--as` together with fill-account is refused, not silently ignored
        browser = ObsBrowser(flow=True)
        code, out, err, _ = TMC.ui_run(t, SIGN_IN_FILE, browser, ("--as", "default"))
        check_eq("K8 F1: `--as` with a `fill-account` steps file: exit 2, nothing opened", (code, browser.opened), (2, None))
        check_in("K8 F1: ... saying why and what to do", "`--as` signs in by code; a steps file with `fill-account` signs in "
                 "through the form: leave `--as` out", err)
        # control: a steps file without fill-account still signs in by code (the login call is made)
        browser = ObsBrowser()
        code, out, err, _ = TMC.ui_run(t, f"goto {UI}\n", browser)
        check_eq("K8 F1 control: no fill-account: the code login is made", (code, browser.credentials_seen is not None), (0, True))
        # `login.ui: null` + fill-account: allowed, the form is typed
        nulled = S.make_task(cfg=S.config(manual_capture={"login": {"ui": None}}))
        try:
            browser = ObsBrowser(flow=True)
            code, out, err, _ = TMC.ui_run(nulled, SIGN_IN_FILE, browser)
            check_eq("K8 F1: `login.ui: null` + fill-account runs", (code, browser.credentials_seen), (0, None))
        finally:
            S.cleanup(nulled)
        # F12: a capture in the window is refused naming the door that exists
        shaped = json.loads(json.dumps(MC.spec()["login"]["ui"]))
        shaped["landed"] = {"session_cookie": "c"}
        bare = S.make_task(cfg=S.config(manual_capture={"login": {"ui": shaped}}))
        try:
            code, s, out, err, b = run(bare, f"goto {SIGN_IN}\nfill-account \"#email\" default user\ncapture post_action completion\n",
                                       ObsBrowser())
            check_eq("K8 F12: no url_not: the capture in the window is refused", (code, s["steps"][-1]["outcome"]), (1, "refused"))
            check_in("K8 F12: ... naming the config key that closes the window", "manual_capture.login.ui.landed.url_not",
                     s["failed"]["detail"])
            check_not_in("K8 F12: ... and not the door that cannot happen", "left the sign-in address", s["failed"]["detail"])
        finally:
            S.cleanup(bare)
        code, s, out, err, b = run(t, f"goto {SIGN_IN}\nfill-account \"#email\" default user\ncapture post_action completion\n",
                                   ObsBrowser())
        check_in("K8 F12 control: with a url_not the door is the leaving of the sign-in address",
                 "capture after the page has left the sign-in address", s["failed"]["detail"])
        # F11: the steps-file secret refusal names the door of an account
        code, out, err, _ = TMC.ui_run(t, f"goto {UI}\nfill \"#pw\" password=\"aaaaaaaaaaaaaaaaaaaa\"\n", ObsBrowser())
        check_eq("K8 F11: a credential typed into a step: exit 2", code, 2)
        check_in("K8 F11: ... the door is `fill-account <selector> <actor> user|secret`", "fill-account <selector> <actor> user|secret", err)
    finally:
        S.cleanup(t)


# --------------------------------------------------------------------------------------------
# K6: a plain run keeps every old key and adds the observation
# --------------------------------------------------------------------------------------------

def k6_plain_run_and_never_fails_a_step():
    t = S.make_task()
    try:
        code, s, out, err, b = run(t, TMC.UI_STEPS)
        check_eq("K6: ran", code, 0)
        check("K6: every old key of the summary is there",
              all(k in s for k in ("ok", "case", "attempt", "dir", "captures", "steps", "failed", "limitations", "probe")), str(sorted(s)))
        check_eq("K6: every row has step, outcome and the observation", {tuple(sorted(r)) for r in s["steps"]},
                 {("outcome", "screenshot", "step", "text")})
        names = {Path(r["path"]).name for r in s["captures"]}
        check_eq("K6: captures are the capture steps and the read, as before", len(s["captures"]), 3)
        check_eq("K6: captures.jsonl is exactly what the summary lists",
                 [r["path"] for r in s["captures"]], captures_paths(t))
        check("K6: the observation screens are in observe/ only", all(p.startswith("observe/") or Path(p).name in names for p in attempt_pngs(t)),
              str(attempt_pngs(t)))
        # observing never changes an outcome: no screenshot, a page that cannot be read
        for label, browser in (("a screenshot that fails", ObsBrowser(shot_fails=True)), ("a page that raises", ObsBrowser(words_raise=True))):
            code, s, out, err, b = run(t, f"goto {UI}\nclick \"#a\"\n", browser)
            check_eq(f"K6: {label}: the run still passes", (code, [r["outcome"] for r in s["steps"]]), (0, ["ok", "ok"]))
        code, s, out, err, b = run(t, f"goto {UI}\n", ObsBrowser(shot_fails=True))
        check_eq("K6: ... null, the text kept", (s["steps"][0]["screenshot"], s["steps"][0]["text"]), (None, "Home"))
        code, s, out, err, b = run(t, f"goto {UI}\n", ObsBrowser(words_raise=True))
        check_eq("K6: a page that cannot be read gives an empty text, the screenshot kept",
                 (bool(s["steps"][0]["screenshot"]), s["steps"][0]["text"]), (True, ""))
    finally:
        S.cleanup(t)


# --------------------------------------------------------------------------------------------
# K7: the three texts (DOC-WITNESS; the keys are quoted from the DoD, with a negative control)
# --------------------------------------------------------------------------------------------

def k7_texts():
    # The role-text keys of K7 (runner charter, manual-evidence.md, role-commands.json) live in design/role-rules.json (TD-5.3.3).
    # X7-3: the 9500 B ceiling is dropped (R-drop): the runner is a charter, `charter.charter_errors` holds its size (150 lines)
    check("K7: qa-runner.md is a charter of the form (its size is held by charter_errors)",
          __import__("charter").charter_errors((PKG / "agents/qa-runner.md").read_text(encoding="utf-8")) == [])
    check("K7: manual-evidence.md is under its 12000 B ceiling", len((PKG / "references/manual-evidence.md").read_bytes()) <= 12000)


def main():
    page_words_pins()
    k1_the_modal_is_seen_and_passed()
    k2_limits()
    k3_the_window()
    k4_names_not_values()
    k5_owner_of_the_block()
    k8_fill_account_makes_no_code_login()
    k6_plain_run_and_never_fails_a_step()
    k7_texts()
    finish("test_manual_observe")


if __name__ == "__main__":
    main()
