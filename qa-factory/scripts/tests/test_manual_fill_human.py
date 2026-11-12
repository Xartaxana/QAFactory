#!/usr/bin/env python3
"""t-1765 X8-1: `fill` keys the text as a person does and the field ENDS holding the given text, whatever it held.

F1 an empty text only clears (rows `cleared`, `settled`)   F2 a prefilled field ("1" then `fill 12`) ends "12": clear, "1", "2"
F3 the time budget: len x type_delay_ms against the step limit - AT it the fill runs, one character beyond it is refused BEFORE any key
F4 a secret-looking text is keyed, no per-character log, no value in the step line, a limitation   F5 `--whole`, a password/date field, a select:
Playwright `fill`, the line says `input: whole (<why>)`
R1 the REAL backend's `clear_field` + `type_chars` over a stub page that models selection and typing: the end value is the given one
Mutations -> killing key: no clear -> F2/R1; the budget after the first key -> F3; a log of a secret -> F4; a password typed per character -> F5.
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
SEL = "#qty"


class FieldBrowser(S.FakeBrowser):
    """A fake that models one field: its value, its type and tag, what the page does when it is cleared and when a key arrives."""

    def __init__(self, value="", kind=None, tag="input", clears=True, **kw):
        super().__init__(**kw)
        self.value, self.kind, self.tag, self.clears, self.keys = value, kind, tag, clears, []

    def field_traits(self, selector):
        self.keys.append(("traits", selector))
        return {"type": self.kind, "tag": self.tag}, 0.05

    def clear_field(self, selector):
        self.keys.append(("clear", selector))
        if self.clears:
            self.value = ""
        return {"n": "cleared", "value": self.value, "focus": True}, 0.05, 0.01

    def type_chars(self, selector, text, delay_ms, settle_ms=0):
        self.keys.append(("type", text, delay_ms, settle_ms))
        rows = []
        for n, char in enumerate(text, 1):
            self.value += char
            rows.append({"n": n, "value": self.value, "focus": True})
        rows.append({"n": "settled", "value": self.value, "focus": True})
        return rows, 0.05, 0.01

    def fill(self, selector, text):
        self.keys.append(("fill", selector, text))
        self.value = text
        return 0.05

    def settle(self, settle_ms, idle_max_ms, remaining_s):
        return True


def run(t, line, browser):
    code, out, err, browser = T.ui_run(t, f"goto {T.UI}\n{line}\n", browser)
    summary = json.loads(out) if out.strip().startswith("{") else {}
    rows = T.jsonl(t.attempt_dir(CASE) / "steps.jsonl")
    return code, summary, rows[-1] if rows else {}


def log_of(t):
    files = sorted(t.attempt_dir(CASE).glob("*-fill-*.txt"))
    return files[0].read_text(encoding="utf-8").splitlines() if files else None


def f1_f2_end_value():
    t = S.make_task()
    try:
        b = FieldBrowser(value="2")
        code, summary, entry = run(t, f'fill {SEL} ""', b)
        check_eq("F1 an empty text: the field ends empty", b.value, "")
        check_eq("F1 ... only the clearing was done, no keys", [k[0] for k in b.keys if k[0] in ("clear", "type")], ["clear", "type"])
        check_eq("F1 ... the type call got nothing to type", [k[1] for k in b.keys if k[0] == "type"], [""])
        check_eq("F1 the log: `cleared` and `settled` only", [x.split("\t")[0] for x in log_of(t)], ["cleared", "settled"])
        check_eq("F1 the step is ok", entry["outcome"], "ok")
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        b = FieldBrowser(value="1")
        code, summary, entry = run(t, f"fill {SEL} 12", b)
        check_eq("F2 a prefilled '1' and `fill 12`: the field ends '12', not '112'", b.value, "12")
        check_eq("F2 the order: clear, then the characters", [k[0] for k in b.keys if k[0] in ("clear", "type")], ["clear", "type"])
        check_eq("F2 the log: cleared, 1, 2, settled", [x.split("\t")[0] for x in log_of(t)], ["cleared", "1", "2", "settled"])
        check_eq("F2 the keys got the data's pace (50 ms) and settle (300 ms)", [k[2:] for k in b.keys if k[0] == "type"], [(50, 300)])
        check_in("F2 the line says what was typed and what the field holds", 'typed 2 of 2; value "12" after 300 ms', entry["detail"])
        check_in("F2 ... and that it was cleared", "cleared", entry["detail"])
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        b = FieldBrowser(value="1", clears=False)          # a field that hands the old value back: the end is NOT the given text
        code, summary, entry = run(t, f"fill {SEL} 12", b)
        check_eq("F2 a field that cannot be cleared: the step is still ok (the role judges)", entry["outcome"], "ok")
        check_in("F2 ... the line shows what it still held", 'it still held "1"', entry["detail"])
        check_in("F2 ... and the value it ends with", 'value "112"', entry["detail"])
    finally:
        S.cleanup(t)
    # the project's pace is read (AR-3): type_delay_ms 120; a value that is no number is the default
    for value, want in ((120, 120), (0, 0), ("x", 50), (-5, 50)):
        t = S.make_task(cfg=S.config(manual_capture={"type_delay_ms": value}))
        try:
            b = FieldBrowser()
            run(t, f"fill {SEL} ab", b)
            check_eq(f"F2 manual_capture.type_delay_ms = {value!r}", [k[2] for k in b.keys if k[0] == "type"], [want])
        finally:
            S.cleanup(t)


def f3_budget():
    t = S.make_task()
    try:
        attempt = MC.Attempt(t.task, CASE, "a9", t.cfg)
        for count, delay, limit, ok in ((20, 50, 1, True), (21, 50, 1, False), (10, 100, 1, True), (11, 100, 1, False),
                                        (1, 50, 0.04, False)):
            cfg = dict(t.cfg, manual_capture={"type_delay_ms": delay})
            b = FieldBrowser(value="keep")
            step = {"n": 1, "word": "fill", "args": [SEL, "a" * count], "line": f"fill {SEL} <{count}>"}
            entry = MC._run_step(b, attempt, step, limit, cfg, {}, 30)["entry"]
            label = f"F3 {count} chars x {delay} ms against {limit} s"
            check_eq(f"{label}: {'runs' if ok else 'refused'}", entry["outcome"], "ok" if ok else "refused")
            if ok:
                check_eq(f"{label}: the field holds the text", b.value, "a" * count)
            else:
                check_eq(f"{label}: BEFORE any key - the backend was not touched", b.keys, [])
                check_eq(f"{label}: ... the field is as it was", b.value, "keep")
                check_in(f"{label}: the door is `fill --whole`", "Use `fill --whole #qty <text>`", entry["detail"])
                check_in(f"{label}: ... and the arithmetic", f"{count} characters at {delay} ms", entry["detail"])
        b = FieldBrowser(value="keep")
        step = {"n": 1, "word": "fill", "args": ["--whole", SEL, "a" * 500], "line": "fill --whole"}
        entry = MC._run_step(b, attempt, step, 1, t.cfg, {}, 30)["entry"]
        check_eq("F3 the door itself: `--whole` over the budget runs", (entry["outcome"], b.value), ("ok", "a" * 500))
    finally:
        S.cleanup(t)


def f4_secret():
    secret = "password = 'abcdefghijklmnop1234'"
    t = S.make_task()
    try:
        b = FieldBrowser()
        attempt = MC.Attempt(t.task, CASE, "a9", t.cfg)
        step = {"n": 1, "word": "fill", "args": [SEL, secret], "line": f"fill {SEL} <secret>"}
        entry = MC._run_step(b, attempt, step, 180, t.cfg, {}, 30)["entry"]
        check_eq("F4 a secret-looking text: the step is ok (the fill before X8 never refused)", entry["outcome"], "ok")
        check_eq("F4 ... and it was typed", b.value, secret)
        check_eq("F4 ... no log file", list(attempt.dir.glob("*fill*")), [])
        files = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in attempt.dir.rglob("*") if p.is_file())
        check_not_in("F4 ... the value is in no file of the attempt", "abcdefghijklmnop1234", files)
        check_not_in("F4 ... nor in the step line", "abcdefghijklmnop1234", json.dumps(entry))
        check_in("F4 ... the line tells the length, not the value", f"typed {len(secret)} of {len(secret)} characters; value not shown", entry["detail"])
        check("F4 ... a limitation names the pattern's index", any("secret_content_patterns[1]" in x for x in attempt.limitations),
              str(attempt.limitations))
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        cfg = dict(t.cfg, secret_content_patterns=["(unclosed"])
        attempt = MC.Attempt(t.task, CASE, "a9", cfg)
        b = FieldBrowser()
        entry = MC._run_step(b, attempt, {"n": 1, "word": "fill", "args": [SEL, "ab"], "line": "fill"}, 180, cfg, {}, 30)["entry"]
        check_eq("F4 a pattern that cannot be scanned: the field is filled, no log, said", (entry["outcome"], b.value, list(attempt.dir.glob("*fill*"))),
                 ("ok", "ab", []))
        check("F4 ... and a limitation says it could not be scanned", any("could not be scanned" in x for x in attempt.limitations), str(attempt.limitations))
    finally:
        S.cleanup(t)


def f5_whole():
    cases = (("--whole", "input: whole (--whole)", {}), ("password", "input: whole (type=password)", {"kind": "password"}),
             ("date", "input: whole (type=date)", {"kind": "date"}), ("select", "input: whole (<select>)", {"tag": "select"}),
             ("text control", None, {"kind": "text"}))
    for label, said, kw in cases:
        t = S.make_task()
        try:
            b = FieldBrowser(**kw)
            line = f"fill --whole {SEL} 2026-11-04" if label == "--whole" else f"fill {SEL} 2026-11-04"
            code, summary, entry = run(t, line, b)
            check_eq(f"F5 {label}: ok", entry["outcome"], "ok")
            if said:
                check_eq(f"F5 {label}: Playwright `fill`, no keys, no clearing", [k[0] for k in b.keys if k[0] in ("fill", "type", "clear")], ["fill"])
                check_in(f"F5 {label}: the line says so", said, entry["detail"])
                check_eq(f"F5 {label}: no per-character log", log_of(t), None)
            else:
                check_eq(f"F5 {label}: a text field is typed", [k[0] for k in b.keys if k[0] in ("fill", "type", "clear")], ["clear", "type"])
        finally:
            S.cleanup(t)
    t = S.make_task()
    try:
        code, summary, entry = run(t, f"fill {SEL} x", S.FakeBrowser())        # an older fake / a backend with no clear_field: the plain fill
        check_eq("F5 a backend that cannot clear keeps the plain `fill`", entry["outcome"], "ok")
    finally:
        S.cleanup(t)


class KeyPage:
    """A stub of Playwright's page with one field: `keyboard.press("ControlOrMeta+A")` selects, `Delete` removes the selection, `type`
    appends (replacing a selection)."""

    def __init__(self, value="", no_meta=False):
        self.value, self.selected, self.focused, self.no_meta, self.log = value, False, False, no_meta, []
        self.keyboard = self

    def locator(self, selector):
        return Loc(self)

    def wait_for_timeout(self, ms):
        return None

    def press(self, key):
        self.log.append(key)
        if key == "ControlOrMeta+A" and self.no_meta:
            raise _Error("Unknown key: ControlOrMeta")
        if key in ("ControlOrMeta+A", "Control+A"):
            self.selected = True
        elif key == "Delete" and self.selected:
            self.value, self.selected = "", False

    def type(self, char):
        self.value = char if self.selected else self.value + char
        self.selected = False


class _Error(Exception):
    pass


class _Timeout(Exception):
    pass


class Loc:
    def __init__(self, page):
        self.page, self.first = page, self

    def focus(self, timeout=None):
        self.page.focused = True

    def input_value(self, timeout=None):
        return self.page.value

    def evaluate(self, script, arg=None, timeout=None):
        return self.page.focused


def r1_real_backend():
    def backend(page):
        b = MC.PlaywrightBackend.__new__(MC.PlaywrightBackend)
        b._page, b._Error, b._Timeout, b._element_ms, b._limit_ms = page, _Error, _Timeout, 30000, 180000
        return b
    for held, text in (("1", "12"), ("", "12"), ("2", ""), ("long old value", "x")):
        page = KeyPage(held)
        b = backend(page)
        row, took, focus_s = b.clear_field(SEL)
        rows, took, focus_s = b.type_chars(SEL, text, 50, 300)
        check_eq(f"R1 the field held {held!r}, `fill {text!r}`: it ends with the given text", page.value, text)
        check_eq("R1 ... the first row is the clearing, empty", (row["n"], row["value"], row["focus"]), ("cleared", "", True))
        check_eq("R1 ... the last row is `settled` with the end value", (rows[-1]["n"], rows[-1]["value"]), ("settled", text))
    page = KeyPage("1", no_meta=True)
    backend(page).clear_field(SEL)
    check_eq("R1 a Playwright with no ControlOrMeta: Control+A is the fallback, the field is empty", (page.value, page.log), ("", ["ControlOrMeta+A", "Control+A", "Delete"]))


def main():
    for case in (f1_f2_end_value, f3_budget, f4_secret, f5_whole, r1_real_backend):
        case()
    finish("test_manual_fill_human")


if __name__ == "__main__":
    main()
