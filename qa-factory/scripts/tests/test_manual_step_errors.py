#!/usr/bin/env python3
"""t-1511 HF5-1: a step with an element says what is wrong, not "no element matched" for every timeout.

The page is a STUB (no browser), but the code under test is the REAL `PlaywrightBackend`: `_timed`,
`why_not_actionable`, `click`/`fill`/`wait_selector`/`read` and `screenshot` run as shipped; only `open`, the sign-in
and the landing probes (the half this node does not touch) are replaced. Run through `manual_capture ui`, so the step
line, the screenshot, `steps.jsonl` and the record `manual_evidence.py build` makes are the real consumers (K1).

The "was" of K1 is the step of attempt a4 of case TC-010 of the 12586 run, kept in fixtures/run-12586-tc010/:
`click "#project-selector"` -> "no element matched within 30 s" while a Guided Tour mask covered the page.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402
import test_manual_capture as TMC  # noqa: E402

MC = S.MC
FIXTURE = HERE / "fixtures" / "run-12586-tc010"
UI_CASE = S.CASES["ui"]
COVER_TEXT = "Guided Tour Available Take a quick tour of the new project screen"
PW_LINE = "Locator.click: Timeout 30000ms exceeded."
PW_MESSAGE = PW_LINE + "\nCall log:\n  - waiting for locator('#project-selector').first"


class _Timeout(Exception):
    """Stands for playwright's TimeoutError."""


class _Error(Exception):
    """Stands for playwright's Error."""


class Locator:
    def __init__(self, page):
        self.page, self.first = page, self

    def count(self):
        return self.page.probe("count", self.page.count)

    def is_visible(self):
        return self.page.probe("visible", self.page.visible)

    def is_enabled(self):
        return self.page.probe("enabled", self.page.enabled)

    def bounding_box(self, **kw):
        return self.page.probe("box", self.page.box)

    def evaluate(self, script, arg):
        self.page.evaluated.append((script, arg))
        return self.page.probe("top", self.page.top)

    def _times_out(self, *a, **k):
        raise _Timeout(self.page.said)
    click = fill = inner_text = get_attribute = _times_out


class Page:
    """What the stub page knows: the element is there, visible, enabled, and `top` is what sits at its center."""

    def __init__(self, **over):
        self.count, self.visible, self.enabled = 1, True, True
        self.box = {"x": 10, "y": 20, "width": 100, "height": 40}
        self.top = {"covered": True, "tag": "div", "classes": ["p-dialog-mask", "p-component-overlay"], "text": COVER_TEXT}
        self.said, self.shot_error, self.evaluated, self.last_selector = PW_MESSAGE, False, [], None
        self.__dict__.update(over)

    def probe(self, name, value):
        if isinstance(value, Exception):
            raise value
        return value

    def locator(self, selector):
        self.last_selector = selector
        return Locator(self)

    def wait_for_selector(self, selector, timeout=None):
        raise _Timeout(self.said)

    def wait_for_timeout(self, ms):
        return None

    def screenshot(self, path=None, full_page=False):
        if self.shot_error:
            raise _Error("screenshot failed")
        Path(path).write_bytes(b"\x89PNG-stub")


class RealStepsBackend(MC.PlaywrightBackend):
    """The REAL backend class, built with `__new__` (no Playwright import); the sign-in and landing half is the
    scaffold fake's (not under test here). Every step method is the shipped one."""

    @classmethod
    def make(cls, page, element_ms=30000):
        backend = cls.__new__(cls)
        backend._page, backend._Timeout, backend._Error = page, _Timeout, _Error
        backend._element_ms, backend._limit_ms = element_ms, 180000
        backend.now, backend.fake = 0.0, S.FakeBrowser()
        return backend

    def open(self, timeout_s, allowed_hosts, local_storage=None, element_wait_s=None):
        return None

    def login(self, recipe, credentials, frontend_url):
        return 0.1

    def goto(self, url):
        return 0.2

    def monotonic(self):
        return self.now

    def pause(self, seconds):
        self.now += max(seconds, 1e-6)

    def current_url(self):
        return S.HOME_URL

    def cookie_names(self):
        return {S.SESSION_COOKIE}

    def field_visible(self, row):
        return False

    def page_words(self):
        return "Welcome"

    def close(self):
        return None


def run_steps(t, page, steps, element_ms=30000):
    backend = RealStepsBackend.make(page, element_ms)
    steps_file = t.task / "steps.txt"
    steps_file.write_text(steps, encoding="utf-8")
    TMC.patch_backends(backend)
    code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps_file)])
    summary = json.loads(out) if out.strip() else {}
    return code, summary, err


def failed_detail(t, page, steps, element_ms=30000):
    code, summary, err = run_steps(t, page, steps, element_ms)
    failed = summary.get("failed")
    check(f"a failed step is reported ({steps.strip().splitlines()[-1]})", bool(failed), f"{code} {summary} {err}")
    return failed["detail"] if failed else ""


def direct_step(t, page, line, cfg=None, timeout_s=180, element_s=30, element_ms=30000, attempt_name="a9", limit_ms=None):
    """One `_run_step` on the real backend: the detail of its entry. `limit_ms`: the backend's page limit (what `open` sets)."""
    backend = RealStepsBackend.make(page, element_ms)
    if limit_ms:
        backend._limit_ms = limit_ms
    attempt = MC.Attempt(t.task, UI_CASE, attempt_name, cfg or t.cfg)
    return MC._run_step(backend, attempt, _parse(line), timeout_s, cfg or t.cfg, {}, element_s)["entry"], attempt


def _parse(line):
    word, _, rest = line.partition(" ")
    import shlex
    return {"word": word, "args": shlex.split(rest), "line": line}


UI = TMC.UI
CLICK = f'goto {UI}\nclick "#project-selector"\n'


def k1_the_tc010_step():
    was = [json.loads(x) for x in (FIXTURE / "steps.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    was_step = next(s for s in was if s["step"] == 'click "#project-selector"')
    check_eq("K1 was: the step of the stand's run said only 'no element matched'", was_step["detail"],
             "no element matched within 30 s")
    t = S.make_task()
    try:
        TMC.seed_runtime_records(t)
        page = Page()
        code, summary, err = run_steps(t, page, CLICK)
        check_eq("K1: the covered click fails the case step (exit 1)", code, 1)
        detail = (summary.get("failed") or {}).get("detail", "")
        check_in("K1: the step names the cover", 'covered by div.p-dialog-mask.p-component-overlay ("Guided Tour Available', detail)
        check_in("K1: and the screenshot", "; screenshot: work/evidence/manual/TP1-15045_TC_007/", detail)
        check_in("K1: and the browser's own first line, last", "; Playwright said: " + PW_LINE, detail)
        check_not_in("K1: and not the old claim", "no element matched", detail)
        check("K1: the screenshot is before the browser's words", detail.index("screenshot:") < detail.index("Playwright said"), detail)
        check_not_in("K1: the browser's call log is not carried", "Call log", detail)
        check_eq("K1: the probe asked the page where the element is", bool(page.evaluated), True)
        shot = detail.split("; screenshot: ")[1].split(";")[0]
        check("K1: the screenshot file exists", (t.task / shot).is_file(), shot)
        code, out, err = TMC.build(t, UI_CASE, "--result", "inconclusive", "--actual", "the click did not land",
                                   "--masked", "--limitation", "x")
        check_eq("K1: build on this attempt passes", code, 0)
        record = json.loads((t.attempt_dir(UI_CASE) / "record.json").read_text(encoding="utf-8"))
        check("K1 (stand): the record's steps_actual carries 'covered by'",
              any("covered by div.p-dialog-mask" in s for s in record["steps_actual"]), str(record["steps_actual"]))
        check("K1: and the failed step's screenshot is an evidence ref",
              any(r["path"] == shot for r in record["evidence_refs"]), shot)
    finally:
        S.cleanup(t)


def k2_k3_k7_classes():
    t = S.make_task()
    try:
        d = failed_detail(t, Page(count=0), CLICK)
        check_in("K2: count 0 -> 'no element matched'", "no element matched #project-selector within 30 s", d)
        d = failed_detail(t, Page(visible=False), CLICK)
        check_in("K3: not visible", "#project-selector was found but is not visible", d)
        check_not_in("K3: not visible is not 'no element matched'", "no element matched", d)
        d = failed_detail(t, Page(enabled=False), CLICK)
        check_in("K3: not enabled", "#project-selector was found but is not enabled", d)
        for label, over in (("count raises", {"count": _Error("x")}), ("visible raises", {"visible": _Error("x")}),
                            ("enabled raises", {"enabled": _Error("x")}), ("box raises", {"box": _Error("x")}),
                            ("evaluate raises", {"top": _Error("x")}), ("no box", {"box": None}),
                            ("elementFromPoint null", {"top": None}),
                            ("garbage answer", {"top": "div"}),
                            ("descendant on top", {"top": {"covered": False}})):
            d = failed_detail(t, Page(**over), CLICK)
            check_in(f"K3/K7 {label}: could not be established", "could not be established", d)
            check_not_in(f"K3/K7 {label}: neither 'covered by'", "covered by", d)
            check_not_in(f"K3/K7 {label}: nor 'no element matched'", "no element matched #project-selector within", d)
        d = failed_detail(t, Page(count=_Error("x")), CLICK)
        check_in("K3: a count that raises is named as such", "count failed", d)
        d = failed_detail(t, Page(top={"covered": True, "tag": "div", "classes": [], "text": ""}), CLICK)
        check_in("K7: a cover with no text and no class is still named", "is covered by div", d)
        check_not_in("K7: and has no empty quotes", '("")', d)
    finally:
        S.cleanup(t)


def k4_no_pointer_no_cover():
    t = S.make_task()
    try:
        for label, line in (("wait", 'wait "#project-selector"'), ("fill", 'fill "#project-selector" hello'),
                            ("read", 'read "#project-selector"')):
            entry, _ = direct_step(t, Page(), line)
            check_eq(f"K4 {label}: the step fails", entry["outcome"], "failed")
            check_not_in(f"K4 {label}: under a cover it is not 'covered by'", "covered by", entry["detail"])
            check_in(f"K4 {label}: it says what it could not establish", "could not be established", entry["detail"])
        page = Page()
        direct_step(t, page, 'fill "#project-selector" hello')
        check_eq("K4: a fill asks no element-at-point question", page.evaluated, [])
    finally:
        S.cleanup(t)


def k5_the_300_cap():
    t = S.make_task()
    try:
        def detail_with(n):
            page = Page(count=0, said="Locator.click: " + "y" * n)
            entry, _ = direct_step(t, page, 'click "#a"')
            return entry["detail"]
        base = len(detail_with(1))
        n_at = 1 + (300 - base)
        check("K5 setup: the length can be set within the browser line's own 200 cap", 1 <= n_at <= 200, str(n_at))
        at = detail_with(n_at)
        check_eq("K5 AT: 300 characters are kept whole", (len(at), at.endswith("...")), (300, False))
        beyond = detail_with(n_at + 1)
        check_eq("K5 BEYOND: 301 -> 300 + '...'", (len(beyond), beyond.endswith("...")), (303, True))
        check_in("K5: what is cut is the browser's tail, the classification and the screenshot come first",
                 "no element matched #a within 30 s; screenshot: ", beyond)
        long_line = detail_with(500)
        check("K5: the browser's first line is capped at 200 before the detail cap",
              long_line.count("y") <= 200, str(long_line.count("y")))
    finally:
        S.cleanup(t)


def k6_lookup():
    t = S.make_task()
    try:
        class Slow(RealStepsBackend):
            def click(self, selector):
                return 41.0
        backend = Slow.make(Page())
        attempt = MC.Attempt(t.task, UI_CASE, "a8", t.cfg)
        entry = MC._run_step(backend, attempt, _parse('click "#a"'), 180, t.cfg, {}, 30)["entry"]
        check_eq("K6: a step that finished after the limit is a failed step", entry["outcome"], "failed")
        check_in("K6: and says it completed late, with both numbers",
                 "the step completed after the element limit (took 41.00 s, limit 30 s)", entry["detail"])
        check_not_in("K6: not 'no element matched'", "no element matched", entry["detail"])
        # a non-element timeout is unchanged: a goto that runs past the limit is a StepTimeout
        class SlowGoto(RealStepsBackend):
            def goto(self, url):
                return 300.0
        entry = MC._run_step(SlowGoto.make(Page()), attempt, _parse(f"goto {UI}"), 180, t.cfg, {}, 30)["entry"]
        check_eq("K6: a page load past the limit is still a timeout", entry["outcome"], "timeout")
        # and the real _timed: a non-element Timeout raises StepTimeout
        backend = RealStepsBackend.make(Page())
        try:
            backend._timed(lambda: (_ for _ in ()).throw(_Timeout("t")))
            check("K6: non-element timeout raises StepTimeout", False)
        except MC.StepTimeout:
            check("K6: non-element timeout raises StepTimeout", True)
    finally:
        S.cleanup(t)


def k8_secret_cover_text():
    t = S.make_task()
    try:
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkw."
        for label, text in (("at the start", "Session " + jwt + "sig"), ("beyond the 60 shown", "Banner " + "w " * 40 + jwt + "sig")):
            page = Page(top={"covered": True, "tag": "div", "classes": ["toast"], "text": text})
            entry, attempt = direct_step(t, page, 'click "#a"')
            check_in(f"K8 {label}: the cover is named without its text", "covered by div.toast (text not kept: matches secret_content_patterns[3])",
                     entry["detail"])
            check_not_in(f"K8 {label}: no JWT bytes in the step", "eyJ", entry["detail"])
            everything = S.tree_text(attempt.dir)
            check_not_in(f"K8 {label}: and none in any file of the attempt", "eyJhbGci", everything)
        entry, _ = direct_step(t, Page(), 'click "#a"', cfg={**t.cfg, "secret_content_patterns": ["("]})
        check_in("K8: a pattern that cannot be scanned keeps no text and says so",
                 "text not kept: secret_content_patterns could not be scanned", entry["detail"])
        entry, _ = direct_step(t, Page(), 'click "#a"')
        check_in("K8 control: an ordinary cover text is kept", COVER_TEXT[:40], entry["detail"])
        # the shown text is cut at 60
        page = Page(top={"covered": True, "tag": "div", "classes": [], "text": "a" * 61})
        entry, _ = direct_step(t, page, 'click "#a"')
        check_in("K8: the shown cover text is at most 60 characters", '("' + "a" * 60 + '")', entry["detail"])
    finally:
        S.cleanup(t)


def screenshot_missing():
    t = S.make_task()
    try:
        entry, _ = direct_step(t, Page(shot_error=True), 'click "#a"')
        check_eq("a step whose screenshot failed is still failed", entry["outcome"], "failed")
        check_not_in("and its detail has no 'screenshot:'", "screenshot:", entry["detail"])
        check_in("and still says what covers", "covered by div.p-dialog-mask", entry["detail"])
    finally:
        S.cleanup(t)


def h1_shadow_dom_guard():
    js = MC.PlaywrightBackend._TOP_AT_POINT
    guard = "el.getRootNode() !== document"
    check_in("H1: the page script leaves a target inside a shadow root unestablished", guard, js)
    check("H1: and asks before it reads the element at the point", guard in js and js.index(guard) < js.index("elementFromPoint"))
    # the guard's answer (null) reaches the step as "could not be established", never "covered by <host>"
    t = S.make_task()
    try:
        entry, _ = direct_step(t, Page(top=None), 'click "#a"')
        check_in("H1: a null answer is 'could not be established'", "could not be established", entry["detail"])
        check_not_in("H1: and not 'covered by'", "covered by", entry["detail"])
    finally:
        S.cleanup(t)


def h2_first_line_helper():
    class E(Exception):
        pass
    check_eq("H2: the first line", MC._first_line(E(" one\ntwo ")), "one")
    check_eq("H2 AT: 200 characters kept", len(MC._first_line(E("x" * 200))), 200)
    check_eq("H2 BEYOND: 201 -> 200", len(MC._first_line(E("x" * 201))), 200)
    check_eq("H2: empty -> the class name", MC._first_line(E("  ")), "E")
    check_eq("H2: empty -> the given fallback", MC._first_line(E(""), ""), "")


class TypingLocator:
    """The field of a TypingPage: reads what the page model holds (EP1-29)."""

    def __init__(self, page):
        self.page, self.first = page, self

    def _read(self, what):
        if self.page.gone:
            raise _Error("element is not attached")
        return what

    def focus(self, timeout=None):
        if self.page.gone:
            raise _Timeout(self.page.said)
        self.page.focus_calls.append(timeout)
        self.page.focused = True

    def input_value(self, timeout=None):
        return self._read(self.page.value)

    def inner_text(self, timeout=None):
        return self._read(self.page.value)

    def evaluate(self, script, arg=None, timeout=None):
        self.page.evaluate_calls += 1
        if self.page.evaluate_calls in self.page.evaluate_fails:
            raise _Error("Execution context was destroyed")
        return self._read(self.page.focused)


class Keyboard:
    def __init__(self, page):
        self.page = page

    def type(self, ch):
        page = self.page
        page.calls.append(("type", ch))
        page.chars += 1
        if page.chars == page.lose_focus_on_char:        # the redraw: the field is replaced, the character is swallowed
            page.focused = False
        if page.focused and not page.gone:
            page.value += ch
        if page.chars == page.gone_after_chars:
            page.gone = True

    def press(self, key):
        self.page.calls.append(("press", key))
        if key == "Control+A":
            self.page.selected = True
        elif key == "Backspace":
            self.page.value, self.page.selected = ("" if self.page.selected else self.page.value[:-1]), False

    def insert_text(self, text):
        self.page.calls.append(("insert", text))
        self.page.value += text


class TypingPage(Page):
    """A page with ONE field: its value and its focus are a model. `lose_focus_on_char=2`: the second keystroke finds the field
    redrawn (focus lost, the character swallowed); `drop_on_settle`: the page empties the field when a wait of `settle` ms
    is over (the server answered); `gone_after_chars`: the element disappears; `evaluate_fails`: which focus reads raise."""

    def __init__(self, **over):
        super().__init__()
        self.value, self.focused, self.selected, self.gone, self.chars = "", False, False, False, 0
        self.lose_focus_on_char = self.gone_after_chars = self.drop_on_settle = None
        self.focus_calls, self.calls, self.waits, self.evaluate_calls, self.evaluate_fails = [], [], [], 0, set()
        self.clock = [0.0]
        self.keyboard = Keyboard(self)
        self.__dict__.update(over)

    def locator(self, selector):
        return TypingLocator(self)

    def wait_for_timeout(self, ms):
        self.waits.append(ms)
        self.clock[0] += ms / 1000
        if self.drop_on_settle and ms >= self.drop_on_settle:
            self.value = ""


def ep1_29_keyboard():
    t = S.make_task()
    counter = []

    def direct_step(t, page, line, **kw):       # a folder of its own per step: one test's log never leaks into the next
        counter.append(1)
        return globals()["direct_step"](t, page, line, attempt_name=f"a{len(counter) + 10}", **kw)
    try:
        # (1) the focus is set ONCE, before the first character; the page loses it on the second keystroke and the record says so
        page = TypingPage(lose_focus_on_char=2)
        entry, attempt = direct_step(t, page, "type input 12")
        check_eq("EP1-29 type: ONE focus for the whole text (a focus per character would hide the lost one)", len(page.focus_calls), 1)
        check_eq("EP1-29 type: the focus waits the element limit", page.focus_calls, [30000])
        check_eq("EP1-29 type: the characters, the pauses (default 200 ms) and the settle (1500 ms)", (page.calls, page.waits),
                 ([("type", "1"), ("type", "2")], [200, 200, 1500]))
        check_eq("EP1-29 type: ok, and the detail names the value and the character after which the focus went",
                 (entry["outcome"], entry["detail"]), ("ok", 'typed 2 of 2; value "1" after 1500 ms; focus lost after character 1'))
        log = next(attempt.dir.glob("*type-input*")).read_text(encoding="utf-8").splitlines()
        check_eq("EP1-29 type: two character lines (the second focus=no) and the settled one", log,
                 ["1\t1\tfocus=yes", "2\t1\tfocus=no", "settled\t1\tfocus=no"])
        # (2) the value is lost only AFTER the page's answer: the last character looks fine, `settled` shows the loss
        page = TypingPage(drop_on_settle=1500)
        entry, attempt = direct_step(t, page, "type input 12")
        check_eq("EP1-29 settle: the wait after the LAST character happened and the field was read again", page.waits[-1], 1500)
        check_in("EP1-29 settle: the record shows the loss the last character hid", 'value "" after 1500 ms (it was "12" at the last character)',
                 entry["detail"])
        check_eq("EP1-29 settle: the settled line", next(attempt.dir.glob("*type-input*")).read_text(encoding="utf-8").splitlines()[-1],
                 "settled\t\tfocus=yes")
        # (3) press Control+A, Backspace: the field is empty; focused_before is read BEFORE the focus is set
        page = TypingPage(value="12")
        entry, attempt = direct_step(t, page, "press input Control+A")
        check_in("EP1-29 press: the field had no focus before the step (read before `focus`)", "focused before=no", entry["detail"])
        check_eq("EP1-29 press: the log line", next(attempt.dir.glob("*press-input*")).read_text(encoding="utf-8"),
                 "Control+A\t12\tfocus=yes\tfocused_before=no")
        entry, attempt = direct_step(t, page, "press input Backspace")
        check_in("EP1-29 press: now it had", "focused before=yes", entry["detail"])
        check_in("EP1-29 press: Control+A then Backspace leaves the field empty", 'value ""', entry["detail"])
        # (4) the focus read before the step fails: `no`; the read after it is its own
        page = TypingPage(value="x", evaluate_fails={1})
        entry, _ = direct_step(t, page, "press input Tab")
        check_in("EP1-29 press: a focus that cannot be read before is `no`, the step goes on", "focused before=no", entry["detail"])
        check_in("EP1-29 press: and the focus after it, read on its own, is yes", "focus=yes", entry["detail"])
        # (5) paste: one insertion, never a character at a time
        page = TypingPage()
        entry, attempt = direct_step(t, page, "paste input 12")
        check_eq("EP1-29 paste: one insert_text and no typed character", page.calls, [("insert", "12")])
        check_in("EP1-29 paste: the value", 'pasted; value "12"', entry["detail"])
        # (6) the element is gone after the first character: <gone>, the typing goes on, the step is ok
        page = TypingPage(gone_after_chars=1, focused=True)
        entry, attempt = direct_step(t, page, "type input 12")
        check_eq("EP1-29 type: a vanished element does not end the step", entry["outcome"], "ok")
        check_eq("EP1-29 type: the rows after the loss", next(attempt.dir.glob("*type-input*")).read_text(encoding="utf-8").splitlines()[1:],
                 ["2\t<gone>\tfocus=no", "settled\t<gone>\tfocus=no"])
        # (7) no element before the first character: a failed step, like fill
        entry, _ = direct_step(t, TypingPage(gone=True), "type input 12")
        check_eq("EP1-29 type: no element is a failed step", entry["outcome"], "failed")
        # (8) 200 characters at the 200 ms default = 40 s + the settle: against timeout_s, never against the element limit
        text = "a" * 200
        real_clock = MC.time.perf_counter
        try:
            for label, timeout_s, expect in (("under the step limit", 100, "ok"), ("beyond the step limit", 30, "timeout")):
                page = TypingPage()
                MC.time.perf_counter = lambda page=page: page.clock[0]
                entry, _ = direct_step(t, page, f"type input {text}", timeout_s=timeout_s, element_s=30)
                check_eq(f"EP1-29 type: 200 characters at 200 ms ({page.clock[0]:g} s) {label}: {expect}", entry["outcome"], expect)
        finally:
            MC.time.perf_counter = real_clock
        # (9) the limit holds INSIDE the loop: the typing stops at the deadline and the rows read so far are kept before the timeout
        try:
            page = TypingPage()
            MC.time.perf_counter = lambda page=page: page.clock[0]
            entry, attempt = direct_step(t, page, f"type input {text}", timeout_s=10, element_s=30, limit_ms=10000)
            kept = next(attempt.dir.glob("*type-input*")).read_text(encoding="utf-8").splitlines()
            check_eq("EP1-29 type: the outcome beyond the limit is a timeout", entry["outcome"], "timeout")
            check("EP1-29 type: stopped near the deadline, not after 200 characters", 40 <= len(page.calls) < 60, f"{len(page.calls)}")
            check_eq("EP1-29 type: the rows before the stop are in the file, the last one is `stopped`",
                     (len(kept), kept[-1].split("\t")[0]), (len(page.calls) + 1, "stopped"))
        finally:
            MC.time.perf_counter = real_clock
    finally:
        S.cleanup(t)


class Field:
    """A sign-in field of the stub login page: it becomes visible `page.appears_ms` after the page loaded."""

    def __init__(self, page, name):
        self.page, self.name = page, name

    def wait_for(self, state=None, timeout=None):
        self.page.waits.append((self.name, state, timeout))
        if self.page.appears_ms is None or self.page.appears_ms > timeout:
            raise _Timeout("Locator.wait_for: Timeout exceeded.")

    def fill(self, text, **kw):
        # the real fill waits the element limit (30 s) - the stub says so by raising its Timeout when the field is absent
        if self.page.appears_ms is None:
            raise _Timeout("Locator.fill: Timeout 30000ms exceeded.")
        self.page.filled.append(self.name)

    def click(self, **kw):
        self.page.clicked.append(self.name)


class LoginPage:
    def __init__(self, appears_ms=0):
        self.appears_ms, self.waits, self.filled, self.clicked = appears_ms, [], [], []

    def goto(self, url, timeout=None):
        return None

    def wait_for_load_state(self, state, timeout=None):
        return None

    def get_by_text(self, text):
        return self

    def is_visible(self):
        return False

    def get_by_role(self, role, name=None):
        return Field(self, name)


def ep1_31_default_form_wait():
    """EP1-31 (t-506 5.2 (3)): the factory's default sign-in form is waited for `login.ui_fit_wait_s`, a project's own recipe
    for the full element wait; the first is the factory's to fix, said in its own words."""
    creds = MC.Credentials("u@example.invalid", "not-a-real-value")
    default = MC.spec()["login"]["ui"]
    fit = MC.spec()["login"]["ui_fit_wait_s"]
    check_eq("EP1-31 the data row says 5 seconds", fit, 5)
    page = LoginPage(appears_ms=0)
    MC.PlaywrightBackend.login(RealStepsBackend.make(page), dict(default, fit_wait_s=fit), creds, "http://localhost:5173")
    check_eq("EP1-31 a form that is there: the first field is waited for 5000 ms, then filled and submitted",
             (page.waits, page.filled, page.clicked), ([("Email address", "visible", 5000)], ["Email address", "Password"], ["Sign in to your account"]))
    page = LoginPage(appears_ms=5000)
    MC.PlaywrightBackend.login(RealStepsBackend.make(page), dict(default, fit_wait_s=fit), creds, "http://localhost:5173")
    check_eq("EP1-31 AT the limit (5.000 s): the sign-in goes on", page.filled, ["Email address", "Password"])
    for label, appears in (("BEYOND the limit (5.1 s)", 5100), ("never", None)):
        page = LoginPage(appears_ms=appears)
        try:
            MC.PlaywrightBackend.login(RealStepsBackend.make(page), dict(default, fit_wait_s=fit), creds, "http://localhost:5173")
            raised = None
        except MC.StepFailed as exc:
            raised = str(exc)
        check_eq(f"EP1-31 {label}: StepFailed in the factory's words, nothing typed", (raised, page.filled),
                 ("the factory's default sign-in form is not on this page", []))
    page = LoginPage(appears_ms=None)
    try:
        MC.PlaywrightBackend.login(RealStepsBackend.make(page), dict(default), creds, "http://localhost:5173")
        outcome = "no exception"
    except MC.StepTimeout:
        outcome = "StepTimeout"
    check_eq("EP1-31 a recipe with no fit_wait_s waits the element limit as before (no early StepFailed, no wait_for)",
             (outcome, page.waits), ("StepTimeout", []))

    class Recording(RealStepsBackend):
        recipes: list = []

        def login(self, recipe, credentials, frontend_url):
            Recording.recipes.append(dict(recipe))
            return 0.1

    for label, over, want in (("no login.ui in config (the default)", {}, fit), ("login.ui written by the project", {"manual_capture": {
            "login": {"ui": dict(default)}}}, None)):
        Recording.recipes = []
        t = S.make_task(cfg=S.config(**over))
        try:
            steps_file = t.task / "steps.txt"
            steps_file.write_text(f"goto {UI}\n", encoding="utf-8")
            TMC.patch_backends(Recording.make(Page()))
            S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps_file)])
        finally:
            S.cleanup(t)
        got = Recording.recipes[0].get("fit_wait_s") if Recording.recipes else "login not reached"
        check_eq(f"EP1-31 run_ui, {label}: fit_wait_s", got, want)


def ep1_31_http_capture_sign_in():
    """EP1-31 through `manual_capture http` (the real run_http): a sign-in the factory has no request for ends in an
    env_blocked row with 0 requests; `none` signs in by nothing and says so; a role's own Authorization needs neither."""
    local = TMC.LOCAL
    get = f"{local}/v1/workflows/w1"
    environment = S.config()["environment"]
    for kind in ("harness_command", "bearer_env", "oidc_password"):
        t = S.make_task(manual=("api",), cfg=S.config(environment={**environment, "access": {"kind": kind}}))
        try:
            http = S.FakeHttp({("GET", get): S.ok_json({"id": "w1"})})
            code, out, err = TMC.http_run(t, http, "--method", "GET", "--url", get, "--phase", "pre_action")
            row = (json.loads(out).get("env_blocked") or {}) if out.strip() else {}
            check("EP1-31 run_http %s with no recipe: exit 3, env_blocked, 0 requests" % kind,
                  code == 3 and http.calls == [] and "nothing was sent" in row.get("probe_line", ""), f"{code} {out[:300]} {err[:200]}")
            check_in(f"EP1-31 run_http {kind}: the printed variant is the login-not-tried one (t-1955 N2)", "login by code was not tried", err)
            check_not_in(f"EP1-31 run_http {kind}: no credential anywhere in the record", S.PASSWORD, S.tree_text(t.task))
            code, out, err = TMC.http_run(t, http, "--method", "GET", "--url", get, "--header", "Authorization: Bearer role-own",
                                          "--phase", "pre_action")
            check(f"EP1-31 run_http {kind}: the role's own Authorization needs no login (no refusal, one GET)",
                  (code, [c[0] for c in http.calls]) == (0, ["GET"]), f"{code} {err[:300]}")
        finally:
            S.cleanup(t)
    t = S.make_task(manual=("api",), cfg=S.config(environment={**environment, "access": {"kind": "none"}}))
    try:
        http = S.FakeHttp({("GET", get): S.ok_json({"id": "w1"})})
        code, out, err = TMC.http_run(t, http, "--method", "GET", "--url", get, "--phase", "pre_action")
        check_eq("EP1-31 run_http access none: no sign-in request, the GET goes", (code, [(c[0]) for c in http.calls]), (0, ["GET"]))
        check_in("EP1-31 ... and stderr says why", "environment.access.kind is none: no login by code", err)
        check_not_in("EP1-31 ... no Authorization header was made up", "Authorization", json.dumps(http.calls[0][2]))
        code, out, err = TMC.http_run(t, http, "--method", "GET", "--url", get, "--as", "default")
        check("EP1-31 run_http access none with --as: refused by the existing NO_LOGIN_AS, nothing sent",
              code == 2 and "need no login" in err and len(http.calls) == 1, f"{code} {err[:200]}")
    finally:
        S.cleanup(t)


class Route:
    """What a handler of `page.route` is given: it records the one answer the handler chose."""

    def __init__(self, url, method):
        self.request, self.answer = type("Request", (), {"url": url, "method": method})(), []

    def fulfill(self, **kw):
        self.answer.append(("fulfill", kw))

    def abort(self, reason=None):
        self.answer.append(("abort", reason))

    def fallback(self):
        self.answer.append(("fallback",))

    def continue_(self):
        self.answer.append(("continue",))


class RoutePage(Page):
    """A page whose requests go through the routes laid with `route` (a glob is matched by fnmatch, `**/` as `*`)."""

    def __init__(self, **over):
        super().__init__(**over)
        self.routes, self.unrouted = [], []

    def route(self, glob, handler):
        if getattr(self, "route_error", None):
            raise _Error(self.route_error)
        self.routes.append((glob, handler))

    def unroute(self, glob, handler):
        self.unrouted.append(glob)
        self.routes = [r for r in self.routes if r != (glob, handler)]

    def send(self, url, method="GET"):
        import fnmatch
        route = Route(url, method)
        for glob, handler in self.routes:
            if fnmatch.fnmatch(url, glob.replace("**/", "*")):
                handler(route)
                break
        return route.answer


def failing_backend(page):
    backend = RealStepsBackend.make(page)
    backend._allowed, backend._failing = {("http", "localhost", 5173)}, {}
    return backend


def ep1_30_routes():
    """EP1-30 (t-506 4.2 (3), t-524 5): the REAL `fail_request` / `restore_request` / `drain_failures` on a stub page."""
    stand, api = "http://localhost:5173", "http://localhost:5173/api/x"
    page = RoutePage()
    backend = failing_backend(page)
    backend.fail_request("**/api/x", "500")
    check_eq("EP1-30 a status: the request is answered with it, an empty JSON body", page.send(api),
             [("fulfill", {"status": 500, "content_type": "application/json", "body": "{}"})])
    check_eq("EP1-30 a request that matches nothing is not touched", page.send(stand + "/other"), [])
    backend.fail_request("**/api/t", "timeout")
    check_eq("EP1-30 timeout: dropped as timed out, never held (the step does not hang)", page.send(stand + "/api/t"), [("abort", "timedout")])
    check_eq("EP1-30 the foreign host is handed back to the guard, no answer made up in its name",
             (page.send("http://evil.example/api/x"), page.send("http://evil.example/api/t")), ([("fallback",)], [("fallback",)]))
    state = backend.drain_failures()
    check_eq("EP1-30 the counts: the foreign requests are no hit", (state["**/api/x"]["hits"], state["**/api/t"]["hits"]), (1, 1))
    check_eq("EP1-30 the lines are method and url", state["**/api/x"]["rows"], [{"method": "GET", "url": api}])
    state["**/api/x"]["hits"] = 99
    check_eq("EP1-30 drain gives a copy", backend.drain_failures()["**/api/x"]["hits"], 1)
    # restore: the route goes, the record stays (the session keeps it), and a second restore is a failed step
    seconds = backend.restore_request("**/api/x")
    check_eq("EP1-30 restore: the route is off and the request goes through", (page.unrouted, page.send(api), seconds >= 0), (["**/api/x"], [], True))
    check_eq("EP1-30 restore: the record stays, inactive", (backend.drain_failures()["**/api/x"]["hits"], backend.drain_failures()["**/api/x"]["active"]),
             (1, False))
    for glob in ("**/api/x", "**/none"):
        try:
            backend.restore_request(glob)
            check(f"EP1-30 restore of {glob}: a failed step", False)
        except MC.StepFailed as exc:
            check_in(f"EP1-30 restore of {glob}: a failed step naming the active ones", "Active: **/api/t", exc.head)
    # a repeat of the pattern while it is on: the old route comes off first, the record starts from zero, the last word acts
    backend.fail_request("**/api/t", "503")
    check_eq("EP1-30 repeat: one route for the pattern, answered with the last word", (page.unrouted[-1], len(page.routes), page.send(stand + "/api/t")),
             ("**/api/t", 1, [("fulfill", {"status": 503, "content_type": "application/json", "body": "{}"})]))
    check_eq("EP1-30 repeat: the hits start from zero", backend.drain_failures()["**/api/t"]["hits"], 1)
    # a restored pattern, failed again: the record is new, nothing to take off
    before = list(page.unrouted)
    backend.fail_request("**/api/x", "404")
    check_eq("EP1-30 failed again after a restore: a new record from zero, no second unroute", (backend.drain_failures()["**/api/x"]["hits"], page.unrouted), (0, before))
    # the cap: AT 50 lines, 51 requests count exactly, the lines stop (data: max_logged)
    page = RoutePage()
    backend = failing_backend(page)
    backend.fail_request("**/api/x*", "500")
    for number in range(51):
        page.send(f"{api}?n={number}")
    state = backend.drain_failures()["**/api/x*"]
    check_eq("EP1-30 51 requests: the count is exact and 50 lines are kept", (state["hits"], len(state["rows"])), (51, 50))
    page = RoutePage()
    backend = failing_backend(page)
    backend.fail_request("**/api/x*", "500")
    for number in range(50):
        page.send(f"{api}?n={number}")
    state = backend.drain_failures()["**/api/x*"]
    check_eq("EP1-30 50 requests: the count and the lines are 50", (state["hits"], len(state["rows"])), (50, 50))
    # a route the browser refuses is a failed step, not a crash
    page = RoutePage(route_error="Target page, context or browser has been closed")
    try:
        failing_backend(page).fail_request("**/api/x", "500")
        check("EP1-30 a route the page refuses: a failed step", False)
    except MC.StepFailed as exc:
        check_in("EP1-30 a route the page refuses: a failed step", "closed", exc.head)


class ReadLocator(Locator):
    """EP1-32: an element with attributes (`attrs`: name -> value, a missing name is `None`) and states (`states`: name ->
    bool, or an exception to raise, as playwright does for `is_checked` on a non-checkbox)."""

    def get_attribute(self, name, timeout=None):
        return self.page.attrs.get(name)

    def _state(self, name):
        value = self.page.states[name]
        if isinstance(value, Exception):
            raise value
        return value

    def is_disabled(self, timeout=None):
        return self._state("disabled")

    def is_checked(self, timeout=None):
        return self._state("checked")

    def is_visible(self, timeout=None):
        return self._state("visible")


class ReadPage(Page):
    def __init__(self, attrs=None, states=None, **over):
        super().__init__(**over)
        self.attrs, self.states = attrs or {}, states or {}

    def locator(self, selector):
        self.last_selector = selector
        return ReadLocator(self)


def ep1_32_read_attribute_and_state():
    """EP1-32 (t-506 6.4 tests 1 and 2): the REAL `read`; a missing attribute is not an empty one; `state=` is true/false."""
    t = S.make_task()
    try:
        page = ReadPage(attrs={"disabled": "", "title": "x"}, states={"disabled": True, "checked": _Error("Not a checkbox"),
                                                                       "visible": False})
        marker = MC.spec()["read_absent_marker"]
        for line, want in (('read "#b" attr=disabled', ""), ('read "#b" attr=aria-disabled', marker), ('read "#b" attr=title', "x"),
                           ('read "#b" state=disabled', "true"), ('read "#b" state=visible', "false")):
            backend = RealStepsBackend.make(page)
            value, _ = backend.read("#b", line.split()[-1])
            check_eq(f"EP1-32 read: `{line}` reads {want!r}", value, want)
        check("EP1-32 read: a missing attribute is not the empty string", marker != "", marker)
        entry, attempt = direct_step(t, page, 'read "#b" attr=aria-disabled')
        check_eq("EP1-32 step: the log file holds the marker, not nothing",
                 next(attempt.dir.glob("*read-*")).read_text(encoding="utf-8"), marker)
        entry, _ = direct_step(t, page, 'read "#b" state=checked')
        check_eq("EP1-32 state=checked on a non-checkbox: a failed step, not `false`", entry["outcome"], "failed")
        check_in("EP1-32 and it says what the browser said", "Not a checkbox", entry["detail"])
        entry, _ = direct_step(t, page, 'read "#b" state=foo')
        check_eq("EP1-32 a state outside the list never reaches the page", entry["outcome"], "failed")
    finally:
        S.cleanup(t)


def main():
    ep1_32_read_attribute_and_state()
    ep1_30_routes()
    ep1_29_keyboard()
    ep1_31_http_capture_sign_in()
    ep1_31_default_form_wait()
    h1_shadow_dom_guard()
    h2_first_line_helper()
    k1_the_tc010_step()
    k2_k3_k7_classes()
    k4_no_pointer_no_cover()
    k5_the_300_cap()
    k6_lookup()
    k8_secret_cover_text()
    screenshot_missing()
    finish("test_manual_step_errors")


if __name__ == "__main__":
    main()
