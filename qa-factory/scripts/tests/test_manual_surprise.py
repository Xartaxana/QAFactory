#!/usr/bin/env python3
"""t-1765 X8-2: the detector of `surprise:` lines - code reports a fact, the role judges it (P27, AR-29); it refuses nothing.

S1 a request during typing -> `request` (+ `field` when the value is not the typed prefix)   S1b an event born by a click is delivered on the
NEXT blocking call (the fake's rule) and still lands on the click: the pump runs inside the step   S1c an event after the last step lands on the last step
S2 a 5xx -> `status`, the console's 'Failed to load resource' folded into it   S2b our `fail_request` is not the product's failure
S3 a redirecting `goto` -> `url`; a click that changes the URL -> the step line only   S4 `watch` changed on a `wait` -> `text`, on a click -> none
S4b a double POST on a click -> `request`   S4c `requestfailed` -> `failed`   S5 the sign-in window keeps facts, hides the account
S6 a failed step keeps its events   S7 an avalanche is grouped `xN`, nothing disappears   S8 a config that still carries the retired `surprise.ignore` hides nothing
S9 the summary says what the detector cannot see   S10 a dead listener is `partial`, never `on`   S11 no file / no detector line is `absent`, never `on`
S12 two calls of an attempt: `k` runs on, ids carry attempt and surface   S13 step 41+: detector and pump still run
L  the line form: `surprise: <id> step <n> (<word>) <kind>: <fact>`; a detector line follows every step; `surprises.jsonl` is not pre-created
Mutations -> killing key: no pump in a step -> S1b; no `ours` mark -> S2b; the fake delivering at once cannot catch that: S1b is the test of the pump.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402
import test_manual_capture as T  # noqa: E402

MC = S.MC
CASE = T.UI_CASE
API = "http://localhost:5173/api"
PAGE = "http://localhost:5173/cart"


def ev(kind, method="GET", path="/x", status=None, text="", failure="", char=None, ours=False, rid=None, location=""):
    return {"kind": kind, "method": method, "url": f"{API}{path}" if path.startswith("/") else path, "status": status, "text": text,
            "failure": failure, "char": char, "ours": ours, "rid": rid, "location": location}


class EventBrowser(S.FakeBrowser):
    """The fake with the real backend's event log, and its one nasty property: an event a step BORN is handed over only on the next
    blocking call (a pump, a wait, a screenshot, the page's words) - the sync API of Playwright does the same."""

    def __init__(self, born=None, **kw):
        super().__init__(**kw)
        self.born, self.log, self.pending, self.dead, self.texts, self.nav, self.url = dict(born or {}), [], [], [], {}, {}, PAGE

    def _call(self, *entry):
        super()._call(*entry)
        self.pending.extend(dict(e) for e in self.born.get(entry[:2], ()))
        if entry[0] in ("goto", "click") and entry[:2] in self.nav:
            self.url = self.nav[entry[:2]]

    def _deliver(self):
        self.log.extend(self.pending)
        self.pending = []

    def settle(self, settle_ms, idle_max_ms, remaining_s):
        self._deliver()
        return True

    def wait_ms(self, ms):
        self._deliver()
        return super().wait_ms(ms)

    def screenshot(self, path):
        self._deliver()
        return super().screenshot(path)

    def page_words(self, mode=None):
        self._deliver()
        return "page"

    def event_mark(self):
        return len(self.log)

    def events_since(self, mark):
        return [dict(e) for e in self.log[mark:]]

    def dead_listeners(self):
        return list(self.dead)

    def watch_text(self, selector):
        return self.texts.get(selector, MC.GONE)

    def current_url(self):
        base = super().current_url()                     # the landing loop's poll counter keeps moving
        return self.url if self.in_steps else base

    @property
    def in_steps(self):
        return any(c[0] == "goto" for c in self.calls)


def run(t, steps, browser, goto=True):
    code, out, err, browser = T.ui_run(t, (f"goto {PAGE}\n" if goto else "") + steps, browser)
    summary = json.loads(out) if out.strip().startswith("{") else {}
    return code, summary, err


def lines(t, attempt="a1"):
    path = t.attempt_dir(CASE, attempt) / "surprises.jsonl"
    return T.jsonl(path) if path.is_file() else None


def only(rows, line):
    return [r for r in (rows or []) if r["line"] == line]


def s1_typing():
    t = S.make_task()
    try:
        b = EventBrowser()
        b.typed = {"#qty": [{"n": 1, "value": "1", "focus": True}, {"n": 2, "value": "1", "focus": True}, {"n": "settled", "value": "1", "focus": True}]}
        b.born = {("type", "#qty"): [ev("request", "PUT", "/cart/items/7", char=(1, 2)), ev("response", "PUT", "/cart/items/7", 200, rid=1)]}
        for e in b.born[("type", "#qty")]:
            e["rid"] = 1
        code, summary, err = run(t, "type #qty 12 10\n", b)
        facts = {r["kind"]: r["fact"] for r in only(lines(t), "surprise")}
        check_eq("S1 a request while typing is a `request` line, with the character", facts.get("request"),
                 f"PUT {API}/cart/items/7 -> 200 after character 1 of 2".replace(API, "/api"))
        check_in("S1 the field that shows '1' for '12' is a `field` line", 'after character 2 the field shows "1" (typed "12")', facts.get("field", ""))
        row = [r for r in summary["steps"] if r["step"].startswith("type")][0]
        check_eq("S1 the step row of the summary carries both", sorted(x.split(" ")[5].rstrip(":") for x in row["surprise"]), ["field", "request"])
    finally:
        S.cleanup(t)


def s1b_pump():
    t = S.make_task()
    try:
        add = ev("request", "POST", "/cart/items")
        b = EventBrowser(born={("click", "#add"): [add]})
        code, summary, err = run(t, 'click "#add"\nwait 100\n', b)
        rows = T.jsonl(t.attempt_dir(CASE) / "steps.jsonl")
        click = [r for r in rows if r["step"].startswith("click")][0]
        check_in("S1b the click's request is in the CLICK's line (the pump delivered it inside the step)", "POST /api/cart/items", click["detail"])
        check_eq("S1b ... and no `request` surprise lands on the `wait` (or anywhere: a click's request is the action's)",
                 [r for r in only(lines(t), "surprise") if r["kind"] == "request"], [])
        wait = [r for r in rows if r["step"].startswith("wait")][0]
        check_not_in("S1b ... the wait's line is plain", "cart", wait["detail"])
    finally:
        S.cleanup(t)

    class NoPump(EventBrowser):
        settle = None                                     # a backend with no pump: the event arrives on the NEXT blocking call

        def screenshot(self, path):                       # (the observation's own calls hand nothing over in this control)
            return S.FakeBrowser.screenshot(self, path)

        def page_words(self, mode=None):
            return "page"
    t = S.make_task()
    try:
        run(t, 'click "#add"\nwait 100\n', NoPump(born={("click", "#add"): [add]}))
        late = [r for r in only(lines(t), "surprise") if r["kind"] == "request"]
        check_eq("S1b negative control: with no pump the click's request lands on the `wait` (the bug the pump removes)",
                 [r["word"] for r in late], ["wait"])
    finally:
        S.cleanup(t)


def s1c_after_last():
    t = S.make_task()
    try:
        b = EventBrowser()
        b.late = [ev("console", text="TypeError: x is undefined")]
        real = b.settle
        calls = []

        def settle(*a):
            calls.append(1)
            if len(calls) == 3:                       # goto, wait-less end: the final pump after the last step
                b.pending.extend(b.late)
            return real(*a)
        b.settle = settle
        code, summary, err = run(t, 'click "#a"\n', b)
        got = [r for r in only(lines(t), "surprise") if r["kind"] == "console"]
        check_eq("S1c an event after the last step is kept", len(got), 1)
        check_in("S1c ... on the last step, and says so", "(after the last step)", got[0]["fact"] if got else "")
    finally:
        S.cleanup(t)


def s2_status_and_ours():
    t = S.make_task()
    try:
        b = EventBrowser(born={("click", "#a"): [ev("response", "GET", "/books/3", 500, rid=2),
                                                 ev("console", text="Failed to load resource: the server responded with a status of 500", location=f"{API}/books/3"),
                                                 ev("pageerror", text="TypeError: cannot read 'price'")]})
        code, summary, err = run(t, 'click "#a"\n', b)
        got = only(lines(t), "surprise")
        check_eq("S2 a 500 is a `status`; the console line of the same resource is folded into it; the page error stays",
                 [(r["kind"], r["fact"]) for r in got],
                 [("status", "GET /api/books/3 -> 500"), ("console", "pageerror: TypeError: cannot read 'price'")])
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        b = EventBrowser(born={("click", "#a"): [ev("response", "GET", "/books/3", 500, rid=3, ours=True),
                                                 ev("failed", "GET", "/books/4", failure="net::ERR_FAILED", rid=4, ours=True),
                                                 ev("response", "GET", "/books/5", 500, rid=5)]})
        run(t, 'click "#a"\n', b)
        check_eq("S2b our `fail_request` (marked) is not the product's: only the unmarked 500 of the same kind is reported",
                 [r["fact"] for r in only(lines(t), "surprise")], ["GET /api/books/5 -> 500"])
    finally:
        S.cleanup(t)
    # the REAL backend marks the request its own `fail_request` handler answers, before it answers
    b = MC.PlaywrightBackend.__new__(MC.PlaywrightBackend)

    class Req:
        method, url = "GET", f"{API}/books/3"

    REQ = Req()

    class Route:
        request = REQ
        answered = []

        def fulfill(self, **kw):
            Route.answered.append(("fulfill", REQ in b._ours))

        def fallback(self):
            pass

    class Page:
        handlers = {}

        def route(self, glob, handler):
            Page.handlers[glob] = handler

        def unroute(self, glob, handler):
            pass
    b._page, b._allowed, b._failing, b._ours = Page(), {MC.host_key(Req.url)}, {}, {}
    b._Timeout = b._Error = Exception
    b._events = []
    b.fail_request("**/api/books/*", 500)
    Page.handlers["**/api/books/*"](Route())
    check_eq("S2b the handler marked the request object BEFORE it fulfilled it", Route.answered, [("fulfill", True)])
    b._on_response(type("R", (), {"request": REQ, "url": Req.url, "status": 500})())
    other = Req()
    b._on_response(type("R", (), {"request": other, "url": Req.url, "status": 500})())
    check_eq("S2b ... the response of the marked request is `ours`, one of an unmarked request (same URL) is not",
             [e["ours"] for e in b._events if e["kind"] == "response"], [True, False])


def s3_url():
    t = S.make_task()
    try:
        b = EventBrowser()
        b.nav = {("goto", f"{PAGE}"): "http://localhost:5173/auth/sign-in"}
        run(t, "", b)
        got = only(lines(t), "surprise")
        check_eq("S3 a `goto` that landed elsewhere is a `url` line", [(r["kind"], r["fact"]) for r in got], [("url", "goto /cart landed on /auth/sign-in")])
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        b = EventBrowser()
        b.nav = {("click", "#go"): "http://localhost:5173/next"}
        run(t, 'click "#go"\n', b)
        rows = T.jsonl(t.attempt_dir(CASE) / "steps.jsonl")
        click = [r for r in rows if r["step"].startswith("click")][0]
        check_in("S3 a click that changes the URL: the step line says it", "url: /cart -> /next", click["detail"])
        check_eq("S3 ... and it is no surprise", [r for r in only(lines(t), "surprise") if r["kind"] == "url"], [])
    finally:
        S.cleanup(t)


def s4_watch():
    t = S.make_task()
    try:
        b = EventBrowser()
        b.texts = {"#badge": "2"}
        orig = b.wait_ms

        def wait(ms):
            b.texts["#badge"] = "0"
            return orig(ms)
        b.wait_ms = wait
        run(t, 'watch "#badge" cart\nwait 100\n', b)
        got = [r for r in only(lines(t), "surprise") if r["kind"] == "text"]
        check_eq("S4 a watched text that changed on a `wait` is a `text` line", [r["fact"] for r in got], ['watch cart: "2" -> "0"'])
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        b = EventBrowser()
        b.texts = {"#badge": "2"}
        b.born = {}
        orig = b.click

        def click(sel):
            b.texts["#badge"] = "3"
            return orig(sel)
        b.click = click
        run(t, 'watch "#badge" cart\nclick "#add"\n', b)
        check_eq("S4 the same change on a click is the action's own: no `text` line", [r for r in only(lines(t), "surprise") if r["kind"] == "text"], [])
    finally:
        S.cleanup(t)


def s4b_double_and_failed():
    t = S.make_task()
    try:
        b = EventBrowser(born={("click", "#send"): [ev("request", "POST", "/orders"), ev("request", "POST", "/orders"), ev("request", "GET", "/me"), ev("request", "GET", "/me")]})
        run(t, 'click "#send"\n', b)
        check_eq("S4b a POST sent twice by a click is a `request` line; a repeated GET is not", [r["fact"] for r in only(lines(t), "surprise")],
                 ["POST /api/orders sent 2 times"])
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        b = EventBrowser(born={("click", "#a"): [ev("failed", "POST", "/cart/merge", failure="net::ERR_CONNECTION_REFUSED", rid=9)]})
        run(t, 'click "#a"\n', b)
        check_eq("S4c a failed request is a `failed` line", [(r["kind"], r["fact"]) for r in only(lines(t), "surprise")],
                 [("failed", "POST /api/cart/merge failed: net::ERR_CONNECTION_REFUSED")])
    finally:
        S.cleanup(t)


def s5_window_and_s6_failed_step():
    class InWindow(EventBrowser):
        def current_url(self):
            return S.SIGN_IN_URL
    t = S.make_task()
    try:
        user = "qa-user@example.test"
        b = InWindow(born={("fill", "#u"): [ev("response", "POST", "/login", 500, rid=1, text=user)],
                           ("fill", "#p"): [ev("console", text=f"bad user {user}")]})
        run(t, 'fill-account "#u" default user\nfill "#p" x\n', b)
        got = only(lines(t), "surprise")
        check("S5 inside the sign-in window the facts are kept", len(got) >= 1, str(got))
        check_not_in("S5 ... with the account hidden", user, json.dumps(got))
        check_eq("S5 ... and no screenshot was taken (the window's rule is unchanged)", list(t.attempt_dir(CASE).glob("observe/*-fill*.png")), [])
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        b = EventBrowser(missing={"#gone"}, born={("click", "#gone"): [ev("pageerror", text="boom")]})
        code, summary, err = run(t, 'click "#gone"\n', b)
        check_eq("S6 the step failed", code, 1)
        check_eq("S6 ... and its event is its surprise", [r["fact"] for r in only(lines(t), "surprise")], ["pageerror: boom"])
    finally:
        S.cleanup(t)


def s7_avalanche_s8_ignore():
    t = S.make_task()
    try:
        born = [ev("response", "GET", f"/p/{i}", 500, rid=i) for i in range(12)] + [ev("response", "GET", "/p/0", 500, rid=99)] * 3
        run(t, 'click "#a"\n', EventBrowser(born={("click", "#a"): born}))
        rows = only(lines(t), "surprise")
        check_eq("S7 twelve different failures are twelve lines (nothing disappears)", len(rows), 12)
        check_in("S7 a repeated one is grouped `x4`", "GET /api/p/0 -> 500 x4", rows[0]["fact"])
        check_eq("S7 ids run on", [r["id"] for r in rows][:3], ["a1-ui-S1", "a1-ui-S2", "a1-ui-S3"])
    finally:
        S.cleanup(t)
    # X9: `manual_capture.surprise.ignore` is retired; a project config that still carries it (valid rules, broken ones, any value) hides nothing
    ignore = [{"kind": "status", "match": "GET /api/p/*", "step": ["click"]}, {"kind": "nonsense", "match": "*"}, "junk", {"kind": "status"}]
    t = S.make_task(cfg=S.config(manual_capture={"surprise": {"ignore": ignore}}))
    try:
        born = [ev("response", "GET", "/p/1", 500, rid=1), ev("response", "GET", "/q/1", 500, rid=2)]
        code, summary, err = run(t, 'click "#a"\n', EventBrowser(born={("click", "#a"): born}))
        rows = only(lines(t), "surprise")
        check_eq("S8 a config that still carries `surprise.ignore` hides nothing: both lines are written",
                 [r["fact"] for r in rows], ["GET /api/p/1 -> 500", "GET /api/q/1 -> 500"])
        check("S8 ... and no line carries `ignored`", all("ignored" not in r for r in rows), str(rows))
        check_eq("S8 the summary lists both and has no `surprises_ignored`",
                 ([s["fact"] for s in summary["surprises"]], "surprises_ignored" in summary),
                 (["GET /api/p/1 -> 500", "GET /api/q/1 -> 500"], False))
        check("S8 nothing is said about the dead key", not any("surprise.ignore" in x for x in summary["limitations"]), str(summary["limitations"]))
        saved = "".join(p.read_text(encoding="utf-8") for p in t.attempt_dir(CASE, "a1").rglob("*surprises*.txt"))
        check("S8 the saved surprises capture lists the lines (premise)", "GET /api/p/1 -> 500" in saved, saved)
        check("S8 ... and has no `ignored by rule`", "ignored by rule" not in saved, saved)
    finally:
        S.cleanup(t)


def s9_s10_s11_s12_s13_form():
    t = S.make_task()
    try:
        code, summary, err = run(t, 'click "#a"\n', EventBrowser())
        check("S9 the summary says what the detector cannot see", any("websocket" in x for x in summary["limitations"]), str(summary["limitations"]))
        det = only(lines(t), "detector")
        check_eq("L a detector line follows every step (the goto and the click)", [d["step"] for d in det], [2, 3])
        check_eq("L ... and says all listeners are alive", {d["listeners"] for d in det}, {"ok"})
        check_eq("L no surprise, but the file exists once a detector line is written; the call says it was on", summary["surprise_detection"], "on")
        check_eq("L the summary lists no surprise", summary["surprises"], [])
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        b = EventBrowser()
        b.dead = ["console"]
        code, summary, err = run(t, 'click "#a"\n', b)
        check_eq("S10 a dead listener: `partial`, never `on`", summary["surprise_detection"], "partial: console dead at steps 2-3")
        check_eq("S10 ... the call goes on", code, 0)
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        code, summary, err = run(t, 'click "#a"\n', S.FakeBrowser())
        check_eq("S11 a backend with no detector: no file is created", lines(t), None)
        check("S11 ... and the call says `absent`, never `on`", summary["surprise_detection"].startswith("absent:"), summary.get("surprise_detection"))
        check_eq("S11 ... with no surprises", summary["surprises"], [])
        (t.attempt_dir(CASE) / "surprises.jsonl").write_text("", encoding="utf-8")
        check_eq("S11 an empty file reads as absent too", MC._detection_of(t.attempt_dir(CASE)).split(":")[0], "absent")
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        run(t, 'click "#a"\n', EventBrowser(born={("click", "#a"): [ev("pageerror", text="one")]}))
        code, out, err, _ = T.ui_run(t, f"goto {PAGE}\nclick \"#b\"\n", EventBrowser(born={("click", "#b"): [ev("pageerror", text="two")]}), ("--attempt", "a1"))
        rows = only(lines(t), "surprise")
        check_eq("S12 a second call of the same attempt: k runs on and ids carry attempt and surface", [r["id"] for r in rows], ["a1-ui-S1", "a1-ui-S2"])
        steps_no = [d["step"] for d in only(lines(t), "detector")]
        check_eq("S12 steps are the attempt's own line numbers, not restarted", steps_no, sorted(set(steps_no)))
        check_eq("S12 the line form", f"surprise: {rows[0]['id']} step {rows[0]['step']} ({rows[0]['word']}) {rows[0]['kind']}: {rows[0]['fact']}",
                 MC._surprise_line(rows[0]))
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        steps = "".join('wait 1\n' for _ in range(44)) + 'click "#late"\n'
        b = EventBrowser(born={("click", "#late"): [ev("pageerror", text="late")]})
        code, summary, err = run(t, steps, b)
        det = only(lines(t), "detector")
        check_eq("S13 step 47 is past the observation limit (40) and still has its detector line", det[-1]["step"], 47)
        check_eq("S13 ... and its surprise", [r["fact"] for r in only(lines(t), "surprise")], ["pageerror: late"])
    finally:
        S.cleanup(t)


JWT = "eyJabcdefghijklmn.eyJabcdefghijklmn.sig"


class HumanBrowser(EventBrowser):
    """The fake with the human `fill` path (`clear_field` + `field_traits` + the character-by-character `type_chars`)."""

    def field_traits(self, selector):
        return {"type": None, "tag": "input"}, 0.01

    def clear_field(self, selector):
        return {"n": "cleared", "value": "", "focus": True}, 0.01, 0.01


def everything(t, summary=None) -> str:
    """Every byte the attempt keeps, and the summary the role is shown."""
    files = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in t.attempt_dir(CASE).rglob("*") if p.is_file())
    return files + json.dumps(summary or {})


def s1_fill():
    t = S.make_task()
    try:
        b = HumanBrowser()
        b.typed = {"#qty": [{"n": 1, "value": "1", "focus": True}, {"n": 2, "value": "1", "focus": True}, {"n": "settled", "value": "1", "focus": True}]}
        b.born = {("type", "#qty"): [ev("request", "PUT", "/cart/items/7", char=(1, 2)), ev("response", "PUT", "/cart/items/7", 200, rid=1)]}
        for e in b.born[("type", "#qty")]:
            e["rid"] = 1
        code, summary, err = run(t, "fill #qty 12\n", b)
        facts = {r["kind"]: r["fact"] for r in only(lines(t), "surprise")}
        check_eq("S1 fill: exit 0", code, 0)
        check_eq("S1 fill: a request while typing is a `request` line, with the character", facts.get("request"),
                 "PUT /api/cart/items/7 -> 200 after character 1 of 2")
        check_eq("S1 fill: the field that shows '1' for the typed '12' is a `field` line (the fill cleared it first: equality)",
                 facts.get("field"), 'after character 2 the field shows "1" (typed "12")')
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        b = HumanBrowser()
        b.typed = {"#qty": [{"n": 1, "value": "a", "focus": True}, {"n": 2, "value": f"password = 'abcdefghijklmnop1234' {JWT}", "focus": True},
                            {"n": "settled", "value": "x", "focus": True}]}
        code, summary, err = run(t, "fill #qty abc\n", b)
        field = [r["fact"] for r in only(lines(t), "surprise") if r["kind"] == "field"]
        check_eq("S1 fill BEYOND: a read-back that looks like a secret: the line says values are not shown",
                 field, ["after character 2 the field does not hold what was typed (values not shown)"])
        check_not_in("S1 fill BEYOND: ... and the value is in no file of the attempt", "abcdefghijklmnop1234", everything(t, summary))
    finally:
        S.cleanup(t)


def s1d_type_secret_flag():
    t = S.make_task()
    try:
        b = EventBrowser()
        b.typed = {"#qty": [{"n": 1, "value": "a", "focus": True}, {"n": 2, "value": "password = 'abcdefghijklmnop1234'", "focus": True},
                            {"n": "settled", "value": "x", "focus": True}]}
        run(t, "type #qty ab 10\n", b)
        check_not_in("m-1 type: a read-back secret reaches no file and no `field` fact", "abcdefghijklmnop1234", everything(t))
    finally:
        S.cleanup(t)


class GapBrowser(EventBrowser):
    """A backend with no pump whose `watch_text` hands the pending events over (a blocking Playwright read does): the events a step
    born arrive INSIDE the detector's own reads, after the step's window was read."""
    settle = None

    def screenshot(self, path):
        return S.FakeBrowser.screenshot(self, path)

    def page_words(self, mode=None):
        return "page"

    def watch_text(self, selector):
        self._deliver()
        return super().watch_text(selector)


def s14_event_during_watch_read():
    for watches in (1, 5):
        t = S.make_task()
        try:
            b = GapBrowser(born={("click", "#a"): [ev("pageerror", text="boom")]})
            b.texts = {f"#w{i}": "1" for i in range(watches)}
            steps = "".join(f'watch "#w{i}" w{i}\n' for i in range(watches)) + 'click "#a"\nwait 100\n'
            code, summary, err = run(t, steps, b)
            got = [(r["word"], r["fact"]) for r in only(lines(t), "surprise")]
            check_eq(f"S14 an event delivered during a watch read ({watches} watch(es)) lands on a step: one event, one line", got,
                     [("wait", "pageerror: boom")])
        finally:
            S.cleanup(t)
    t = S.make_task()                                    # negative control: the window re-marked after the reads (the old code) loses it
    real = MC._surprises_after
    try:
        def remarking(backend, *a, **k):
            found, _ = real(backend, *a, **k)
            return found, backend.event_mark()
        MC._surprises_after = remarking
        b = GapBrowser(born={("click", "#a"): [ev("pageerror", text="boom")]})
        b.texts = {"#w": "1"}
        run(t, 'watch "#w" w\nclick "#a"\nwait 100\n', b)
        check_eq("S14 negative control: re-marking the window after the reads loses the event (the bug)",
                 [r["fact"] for r in only(lines(t), "surprise")], [])
    finally:
        MC._surprises_after = real
        S.cleanup(t)


def s15_secrets_in_step_lines():
    t = S.make_task()
    try:
        b = EventBrowser(born={("click", "#reset"): [ev("request", "GET", f"/reset/{JWT}"), ev("request", "POST", "/cart/items")]})
        code, summary, err = run(t, 'click "#reset"\n', b)
        click = [r for r in T.jsonl(t.attempt_dir(CASE) / "steps.jsonl") if r["step"].startswith("click")][0]
        check_eq("S15 a request path with a JWT: exit 0", code, 0)
        check_not_in("S15 ... the JWT is in no file of the attempt and not in the summary", JWT, everything(t, summary))
        check_in("S15 ... the step line says which pattern kept it out", "not kept: matches secret_content_patterns[3]", click["detail"])
        check_in("S15 ... and the other request of the same click stays readable", "POST /api/cart/items", click["detail"])
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        b = EventBrowser()
        b.texts = {"#badge": f"token {JWT}"}
        code, summary, err = run(t, 'watch "#badge" cart\n', b)
        watch = [r for r in T.jsonl(t.attempt_dir(CASE) / "steps.jsonl") if r["step"].startswith("watch")][0]
        check_not_in("S15 a watched text with a JWT: the JWT is in no file of the attempt", JWT, everything(t, summary))
        check_in("S15 ... the baseline line says which pattern kept it out", "not kept: matches secret_content_patterns[3]", watch["detail"])
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        b = EventBrowser(born={("click", "#a"): [ev("pageerror", text=f"bad token {JWT}")]})
        code, summary, err = run(t, 'click "#a"\n', b)
        check_eq("S15 (E17) a surprise fact with a secret keeps only the pattern's index",
                 [r["fact"] for r in only(lines(t), "surprise")], ["not kept: matches secret_content_patterns[3]"])
        check_not_in("S15 (E17) ... the JWT is in no file", JWT, everything(t, summary))
    finally:
        S.cleanup(t)


def s16_per_step_cap():
    for count, shown, tail in ((5, 5, None), (6, 5, "... and 1 more")):
        t = S.make_task()
        try:
            b = EventBrowser(born={("click", "#a"): [ev("pageerror", text=f"boom {i}") for i in range(count)]})
            code, summary, err = run(t, 'click "#a"\n', b)
            row = [r for r in summary["steps"] if r["step"].startswith("click")][0]["surprise"]
            check_eq(f"S16 {count} errors on one step: {shown} lines in the summary" + (f", then `{tail}`" if tail else ""),
                     (len(row) - (1 if tail else 0), row[-1] if tail else None), (shown, tail))
            check_eq(f"S16 ... and the file holds all {count}", len(only(lines(t), "surprise")), count)
        finally:
            S.cleanup(t)


def s17_torn_line():
    t = S.make_task()
    try:
        run(t, 'click "#a"\n', EventBrowser(born={("click", "#a"): [ev("pageerror", text="one")]}))
        path = t.attempt_dir(CASE) / "surprises.jsonl"
        with path.open("a", encoding="utf-8") as out:
            out.write('{"line": "surprise", "id": "a1-ui-S9", "st')                  # a call killed mid-append
        code2, out2, err2, _ = T.ui_run(t, f"goto {PAGE}\nclick \"#b\"\n", EventBrowser(born={("click", "#b"): [ev("pageerror", text="two")]}),
                                        ("--attempt", "a1"))
        summary2 = json.loads(out2) if out2.strip().startswith("{") else {}
        check_eq("S17 a torn line of surprises.jsonl: a later `ui` call of the attempt is not refused", code2, 0)
        check("S17 ... and its detection is partial, naming the unreadable line",
              summary2.get("surprise_detection", "").startswith("partial:") and "1 unreadable line(s)" in summary2.get("surprise_detection", ""),
              str(summary2.get("surprise_detection")))
    finally:
        S.cleanup(t)


def main():
    for case in (s1_typing, s1_fill, s1d_type_secret_flag, s1b_pump, s1c_after_last, s14_event_during_watch_read, s15_secrets_in_step_lines,
                 s16_per_step_cap, s17_torn_line, s2_status_and_ours, s3_url, s4_watch, s4b_double_and_failed,
                 s5_window_and_s6_failed_step, s7_avalanche_s8_ignore, s9_s10_s11_s12_s13_form):
        case()
    finish("test_manual_surprise")


if __name__ == "__main__":
    main()
