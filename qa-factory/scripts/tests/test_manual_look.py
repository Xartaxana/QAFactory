#!/usr/bin/env python3
"""t-1765 X8-1: `look` (the page seen as a person sees it), `watch` registration, and the pump that ends a step that acts.

L1 a look stores the tree as a state file, first line `form:`, the step line carries the count and the first 20 lines
L2 a tree over the limit is cut at a line, the cut is named (AT the limit: whole; one byte beyond: cut)
L3 an empty page: the empty-content line, the step stays ok   L4 nothing read: ok, `nothing read`, a limitation, no file
L5 refused: sign-in window, a secret, a pattern that cannot be scanned (never a file)   L6 `look <selector>` narrows; text form says why
L8 `watch`: a gone element reads `<gone>`, the sixth label is refused with the number   L9 a device: `look` is `source`, a selector is refused with its door
L10 the pump (`settle`) is held to the step's remaining limit and to `settle_idle_max_ms`; `idle: not reached` reaches the step line
P1 the parse: `look` takes 0-1 words, `watch` 1-2, `fill --whole` forms
Mutations -> killing key: no cut -> L2; empty page stored as empty -> L3; a file written when nothing was read -> L4; the window not refused -> L5;
no ceiling on watches -> L8; a pump with no remaining-limit -> L10.
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
GOTO = f"goto {T.UI}\n"


class LookBrowser(S.FakeBrowser):
    """The fake with what X8-1 added to the real backend: `look`, `watch_text`, `settle`."""

    def __init__(self, tree="- heading \"Cart\" [level=1]\n- button \"Add\"", form="aria", why="", texts=None, **kw):
        super().__init__(**kw)
        self.tree, self.form, self.why, self.texts, self.looked, self.settled = tree, form, why, dict(texts or {}), [], []
        self.idle = True

    def look(self, selector=None):
        self.looked.append(selector)
        return self.tree, self.form, self.why, 0.1

    def watch_text(self, selector):
        return self.texts.get(selector, MC.GONE)

    def settle(self, settle_ms, idle_max_ms, remaining_s):
        self.settled.append((settle_ms, idle_max_ms, round(remaining_s, 1)))
        return self.idle


def run(t, steps, browser):
    code, out, err, browser = T.ui_run(t, GOTO + steps, browser)
    summary = json.loads(out) if out.strip().startswith("{") else {}
    return code, summary, err


def steps_of(t):
    return T.jsonl(t.attempt_dir(CASE) / "steps.jsonl")


def look_files(t):
    return sorted(t.attempt_dir(CASE).glob("*-look-*"))


def l1_stores():
    t = S.make_task()
    try:
        tree = "\n".join(f"- row {i}" for i in range(30))
        code, summary, err = run(t, "look\n", LookBrowser(tree=tree))
        check_eq("L1 the call ends ok", code, 0)
        files = look_files(t)
        check_eq("L1 one file `NNN-look-<label>.txt`", [f.suffix for f in files], [".txt"])
        text = files[0].read_text(encoding="utf-8").splitlines()
        check_eq("L1 the first line says the form", text[0], "form: aria")
        check_eq("L1 the tree follows whole", text[1:], tree.splitlines())
        captures = T.jsonl(t.attempt_dir(CASE) / "captures.jsonl")
        mine = [c for c in captures if "look" in c["path"]]
        check_eq("L1 registered as supporting evidence of kind state", [(c["kind"], c["phase"]) for c in mine], [("state", "supporting")])
        detail = steps_of(t)[-1]["detail"].split("\n")
        check_eq("L1 the step line: counts, the path, then the first 20 lines (the form line is the first)", len(detail), 21)
        check("L1 ... counts and path", detail[0].startswith("look: 31 lines, ") and mine[0]["path"] in detail[0], detail[0])
        check("L1 ... at most 1500 characters", len("\n".join(detail)) <= 1500 + 3, str(len("\n".join(detail))))
    finally:
        S.cleanup(t)


def l2_cut():
    t = S.make_task()
    try:
        limit = MC.spec()["steps"]["look"]["max_bytes"]
        head = "form: aria\n"
        line = "x" * 99 + "\n"
        n_at = (limit - len(head)) // len(line)
        body_at = line * n_at
        pad = limit - len(head) - len(body_at)          # the last line is lengthened so the file is EXACTLY `limit` bytes
        body_at = body_at[:-1] + "p" * pad + "\n"
        check_eq("L2 setup: the file is exactly at the limit", len((head + body_at).encode()), limit)
        code, summary, err = run(t, "look\n", LookBrowser(tree=body_at.rstrip("\n")))
        text = look_files(t)[0].read_text(encoding="utf-8")
        check_not_in("L2 AT the limit: whole, no cut line", "[cut:", text)
        check_eq("L2 AT the limit: no limitation", summary["limitations"], [])
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        tree = "\n".join("y" * 99 for _ in range(300))           # 30 000 bytes: over the 24 000 limit
        code, summary, err = run(t, "look\n", LookBrowser(tree=tree))
        files = look_files(t)
        text = files[0].read_text(encoding="utf-8")
        lines = text.splitlines()
        check("L2 BEYOND: the file ends with the named cut", lines[-1].startswith("[cut: ") and lines[-1].endswith("look <selector> narrows it]"), lines[-1])
        kept = len(lines) - 2                                      # the form line and the cut line are not tree lines
        check_in("L2 BEYOND: the number of lines left out is right", f"[cut: {300 - kept} more lines not stored", lines[-1])
        check("L2 BEYOND: no line is cut in the middle", all(x == "y" * 99 for x in lines[1:-1]))
        check("L2 BEYOND: the file is under the role's whole-read limit (30 000)", len(text.encode()) < 30000, str(len(text.encode())))
        check("L2 BEYOND: the attempt says it was cut", any("look cut:" in x for x in summary["limitations"]), str(summary["limitations"]))
    finally:
        S.cleanup(t)
    # the limit follows the role's own read limit: read.max_bytes 20 000 -> 20 000 - 1024
    t = S.make_task(cfg=S.config(read={"max_bytes": 20000}))
    try:
        code, summary, err = run(t, "look\n", LookBrowser(tree="\n".join("y" * 99 for _ in range(300))))
        size = len(look_files(t)[0].read_bytes())
        check("L2 the limit is min(24000, read.max_bytes - 1024): the file is under 20 000", size < 20000, str(size))
    finally:
        S.cleanup(t)


def l3_l4_empty_and_nothing():
    t = S.make_task()
    try:
        code, summary, err = run(t, "look\n", LookBrowser(tree=""))
        check_eq("L3 an empty page: the step is ok", code, 0)
        check_eq("L3 ... the file says it has no content", look_files(t)[0].read_text(encoding="utf-8"),
                 "form: aria\nthe page has no accessible content\n")
    finally:
        S.cleanup(t)

    class Blind(LookBrowser):
        def look(self, selector=None):
            return None, "", "Error: Target page, context or browser has been closed\nCall log: ...", 0.1
    t = S.make_task()
    try:
        code, summary, err = run(t, "look\n", Blind())
        check_eq("L4 nothing read: the step stays ok (an observation never stops the run)", code, 0)
        check_eq("L4 ... says why, first line only", steps_of(t)[-1]["detail"], "nothing read: Error: Target page, context or browser has been closed")
        check_eq("L4 ... no file", look_files(t), [])
        check("L4 ... a limitation", any("read nothing" in x for x in summary["limitations"]), str(summary["limitations"]))
    finally:
        S.cleanup(t)


def l5_refusals():
    t = S.make_task()
    try:
        class InWindow(LookBrowser):
            def current_url(self):
                return S.SIGN_IN_URL                        # the page never leaves the sign-in address: the window stays open
        browser = InWindow()
        steps = ('fill-account "#u" default user\n' "look\n")
        code, summary, err = run(t, steps, browser)
        entry = steps_of(t)[-1]
        check_eq("L5 inside the sign-in window: refused", entry["outcome"], "refused")
        check_in("L5 ... with the window's door", "capture after the page has left the sign-in address", entry["detail"])
        check_eq("L5 ... and the page was never read", browser.looked, [])
        check_eq("L5 ... no file", look_files(t), [])
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        secret = "password = 'abcdefghijklmnop1234'"
        run(t, "look\n", LookBrowser(tree=f'- text "{secret}"'))
        entry = steps_of(t)[-1]
        check_eq("L5 a secret on the page: refused", entry["outcome"], "refused")
        check_in("L5 ... naming the pattern's index only", "secret_content_patterns[1]", entry["detail"])
        check_not_in("L5 ... the match is nowhere", "abcdefghijklmnop1234", json.dumps(entry))
        check_eq("L5 ... no file", look_files(t), [])
    finally:
        S.cleanup(t)
    # a pattern that cannot be scanned: direct step (the steps file itself would be refused by its own scan before any step)
    t = S.make_task()
    try:
        cfg = dict(t.cfg, secret_content_patterns=["(unclosed"])
        attempt = MC.Attempt(t.task, CASE, "a9", cfg)
        step = {"n": 1, "word": "look", "args": [], "line": "look"}
        outcome = MC._run_step(LookBrowser(), attempt, step, 180, cfg, {}, 30)
        check_eq("L5 a broken pattern: refused, not a crash", outcome["entry"]["outcome"], "refused")
        check_in("L5 ... and says it could not scan", "could not be scanned", outcome["entry"]["detail"])
        check_eq("L5 ... no file", [p for p in attempt.dir.glob("*look*")], [])
    finally:
        S.cleanup(t)


def l6_selector_and_text_form():
    t = S.make_task()
    try:
        browser = LookBrowser(tree="Cart is empty", form="text", why="Locator.aria_snapshot: Timeout 30000ms exceeded.\nCall log:")
        run(t, 'look "#cart"\n', browser)
        check_eq("L6 the selector reaches the backend", browser.looked, ["#cart"])
        text = [f for f in look_files(t)][0]
        check_eq("L6 the text form names why (first line)", text.read_text(encoding="utf-8").splitlines()[0],
                 "form: text (Locator.aria_snapshot: Timeout 30000ms exceeded.)")
        check_in("L6 the file is named by the selector", "cart", text.name)
    finally:
        S.cleanup(t)


def l8_watch():
    t = S.make_task()
    try:
        steps = "".join(f'watch "#e{i}" w{i}\n' for i in range(1, 6)) + 'watch "#e6" w6\n'
        browser = LookBrowser(texts={"#e1": "2 items"})
        code, summary, err = run(t, steps, browser)
        rows = steps_of(t)
        details = [r["detail"] for r in rows if r["step"].startswith("watch")]
        check_eq("L8 a text is the baseline", details[0], 'watching w1: "2 items"')
        check_eq("L8 a vanished element reads <gone>", details[1], 'watching w2: "<gone>"')
        check_eq("L8 five labels are accepted, the sixth is refused", [r["outcome"] for r in rows if r["step"].startswith("watch")],
                 ["ok"] * 5 + ["refused"])
        check_in("L8 the refusal names the number and the watched labels", "5 can be", details[5])
        check_in("L8 ... and the labels", "w1, w2, w3, w4, w5", details[5])
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        steps = "".join(f'watch "#e{i}" w{i}\n' for i in range(1, 6)) + 'watch "#e9" w5\n'
        code, summary, err = run(t, steps, LookBrowser())
        check_eq("L8 a repeated label replaces its element and is not counted again (the 6th line is ok)", steps_of(t)[-1]["outcome"], "ok")
    finally:
        S.cleanup(t)


def l9_device():
    class Device:
        def source(self):
            return '<?xml version="1.0"?>\n<hierarchy><node text="Cart"/></hierarchy>', 0.1

    t = S.make_task()
    try:
        attempt = MC.Attempt(t.task, CASE, "a9", t.cfg)
        attempt.command = "app"
        bad = MC._run_step(Device(), attempt, {"n": 1, "word": "look", "args": ["id=cart"], "line": "look id=cart"}, 180, t.cfg, {}, 30)["entry"]
        check_eq("L9 a selector on a device: refused", bad["outcome"], "refused")
        check_in("L9 ... the door is `look` with no argument", "repeat the step as `look` with no argument", bad["detail"])
        good = MC._run_step(Device(), attempt, {"n": 2, "word": "look", "args": [], "line": "look"}, 180, t.cfg, {}, 30)["entry"]
        check_eq("L9 `look` alone is the screen's tree", good["outcome"], "ok")
        files = list(attempt.dir.glob("*-look-*.xml"))
        check_eq("L9 ... stored as xml, no form line in front of the XML declaration", files[0].read_text(encoding="utf-8").startswith("<?xml"), True)
        check_eq("L9 the surface's steps file accepts `look` and `look <x>` (arity 0-1)",
                 [len(MC.parse_steps(l, MC.spec(), MC.APP_WORDS, ["id"])) for l in ("look\n", "look id=a\n")], [1, 1])
    finally:
        S.cleanup(t)


class PageStub:
    """Records what the real backend's `settle` asked the page for."""

    def __init__(self, idle=True, closed=False):
        self.waits, self.idles, self.idle, self.closed = [], [], idle, closed

    def wait_for_timeout(self, ms):
        if self.closed:
            raise OSError("Target page, context or browser has been closed")
        self.waits.append(ms)

    def wait_for_load_state(self, state, timeout=None):
        self.idles.append((state, timeout))
        if not self.idle:
            raise PwTimeout("networkidle")
        return None


class PwTimeout(Exception):
    """Stands for playwright's TimeoutError."""


def l10_pump():
    def backend(page):
        b = MC.PlaywrightBackend.__new__(MC.PlaywrightBackend)
        b._page, b._Timeout = page, PwTimeout
        return b
    cases = (("plenty of time: 300 then idle held to 2000", 10.0, 300, 2000, [300], [("networkidle", 2000)]),
             ("1.0 s left: idle gets what is left of it", 1.0, 300, 2000, [300], [("networkidle", 700)]),
             ("0.2 s left: only part of the wait, no idle at all", 0.2, 300, 2000, [200], []),
             ("nothing left: no wait, no idle (a 0 timeout would mean no limit)", 0.0, 300, 2000, [], []),
             ("a negative remainder is nothing", -3.0, 300, 2000, [], []),
             ("AT the cap: idle_max 100 of 10 s", 10.0, 300, 100, [300], [("networkidle", 100)]))
    for label, remaining, settle, idle_max, waits, idles in cases:
        page = PageStub()
        got = backend(page).settle(settle, idle_max, remaining)
        check_eq(f"L10 {label}: the waits", page.waits, waits)
        check_eq(f"L10 {label}: the idle waits", page.idles, idles)
        check_eq(f"L10 {label}: idle reached is told", got, bool(idles))
    check_eq("L10 a network that never quiets: False (`not idle`), no exception", backend(PageStub(idle=False)).settle(300, 2000, 10), False)
    check_eq("L10 a closed page claims nothing: None, no exception", backend(PageStub(closed=True)).settle(300, 2000, 10), None)
    # through the step loop: what the step line says and what the pump is given
    t = S.make_task()
    try:
        browser = LookBrowser()
        browser.idle = False
        code, summary, err = run(t, 'click "#add"\nwait 10\n', browser)
        rows = {r["step"]: r["detail"] for r in steps_of(t)}
        check_eq("L10 a click's pump: settle_ms 300 from the template default, idle cap from data", browser.settled[0][:2], (300, 2000))
        check("L10 ... the pump is given the step's remaining limit (<= the limit)", browser.settled[0][2] <= 100, str(browser.settled))
        check_eq("L10 `idle: not reached` is in the click's step line", rows['click "#add"'], "idle: not reached")
        check_eq("L10 a `wait` is not pumped (it neither acts nor types)", len(browser.settled), 2)     # goto + click only
        check_eq("L10 ... and its line is plain", rows["wait 10"], "")
        browser.idle = True
        t2 = S.make_task()
        code, summary, err = run(t2, 'click "#add"\n', browser)
        check_eq("L10 an idle network adds nothing to the line", {r["step"]: r["detail"] for r in steps_of(t2)}['click "#add"'], "")
        S.cleanup(t2)
    finally:
        S.cleanup(t)
    # the project's key is read: manual_capture.settle_ms 50 (and a value that is no number is the default)
    for value, want in ((50, 50), ("slow", 300), (-1, 300), (True, 300)):
        t = S.make_task(cfg=S.config(manual_capture={"settle_ms": value}))
        try:
            browser = LookBrowser()
            run(t, 'click "#add"\n', browser)
            check_eq(f"L10 manual_capture.settle_ms = {value!r}", browser.settled[0][0], want)
        finally:
            S.cleanup(t)


def p1_parse():
    ok = lambda text: MC.parse_steps(GOTO + text, MC.spec())
    check_eq("P1 `look` and `look <selector>`", [len(ok(x)) for x in ("look\n", "look main\n")], [2, 2])
    check_eq("P1 `watch <selector> [label]`", [len(ok(x)) for x in ("watch .a\n", "watch .a badge\n")], [2, 2])
    for bad, needle in (("look a b\n", "`look` takes [<selector>]"), ("watch\n", "`watch` takes <selector> [<label>]"),
                        ("watch a b c\n", "`watch` takes"), ("fill a b c\n", "the flag `--whole` comes first"),
                        ("fill --whole a\n", "the flag `--whole` comes first")):
        try:
            ok(bad)
            raised = ""
        except ValueError as exc:
            raised = str(exc)
        check_in(f"P1 {bad.strip()!r} is refused", needle, raised)
    check_eq("P1 `fill --whole <sel> <text>` and `fill <sel> <text>`", [ok(x)[-1]["args"] for x in ("fill --whole a b\n", "fill a b\n")],
             [["--whole", "a", "b"], ["a", "b"]])


def main():
    for case in (l1_stores, l2_cut, l3_l4_empty_and_nothing, l5_refusals, l6_selector_and_text_form, l8_watch, l9_device, l10_pump, p1_parse):
        case()
    finish("test_manual_look")


if __name__ == "__main__":
    main()
