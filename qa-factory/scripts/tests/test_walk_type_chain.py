#!/usr/bin/env python3
"""TR4-9: the typing chain (TR1-1) must not leak between actors, and two spellings of one field continue it only when the BACKEND says
they are one field (`same_field`; the page decides, code holds no list of spellings - FR-13).

Fakes: a browser that records, per `type`, whether the call was a continuation (`continued`). Real: `_run_steps` / `_continues_field` /
`Walk.op_step` (the actor reset) and `PlaywrightBackend.same_field` over a stub page.
Mutation -> killing test: `same_field` ignored -> test_two_spellings_one_field_continue; a doubt answered as a continuation ->
test_backend_answers_false / _lacks_same_field / _raises; no reset on an actor change -> test_other_actor_same_selector_is_a_new_field.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
import test_manual_capture as T  # noqa: E402
import test_walk_session as W  # noqa: E402
from harness import check_eq, finish  # noqa: E402

MC = S.MC


class _Recording(W.WB):
    def type_chars(self, selector, text, delay_ms, settle_ms=0, continued=False):
        self.typed_calls = getattr(self, "typed_calls", []) + [(selector, continued)]
        return super().type_chars(selector, text, delay_ms, settle_ms, continued)


class _Says(_Recording):
    """A backend that answers `same_field`: `answer` is True / False / None, or an exception class to raise."""
    answer = True

    def same_field(self, a, b):
        self.asked = getattr(self, "asked", []) + [(a, b)]
        if isinstance(self.answer, type):
            raise self.answer("no page")
        return self.answer


def _walk(browser, lines):
    t = S.make_task()
    try:
        attempt = MC.Attempt(t.task, T.UI_CASE, "a1", t.cfg)
        steps = MC.parse_steps(f"goto {T.UI}\n" + "\n".join(lines) + "\n", MC.spec())[1:]
        steps = [dict(s, n=i) for i, s in enumerate(steps, 1)]
        rows, failed = MC._run_steps(browser, attempt, steps, 100, t.cfg, {}, 30, MC.SessionAccount())
        return [r["outcome"] for r in rows], failed
    finally:
        S.cleanup(t)


def _flags(browser):
    return [c for _, c in browser.typed_calls]


def test_two_spellings_one_field_continue():
    b = _Says()
    outcomes, failed = _walk(b, ["type #qty 1", "type input#qty 2"])
    check_eq("`#qty` then `input#qty`, the backend says one field: the second continues", (_flags(b), outcomes), ([False, True], ["ok", "ok"]))
    check_eq("... and the backend was asked with both spellings", b.asked, [("#qty", "input#qty")])


def test_backend_answers_false():
    b = _Says()
    b.answer = False
    outcomes, failed = _walk(b, ["type #qty 1", "type input#qty 2"])
    check_eq("the backend says two fields: two first calls", (_flags(b), outcomes), ([False, False], ["ok", "ok"]))


def test_backend_answers_unknown():
    b = _Says()
    b.answer = None
    _walk(b, ["type #qty 1", "type input#qty 2"])
    check_eq("an unknown answer (None) is a doubt: a new field", _flags(b), [False, False])


def test_backend_lacks_same_field():
    b = _Recording()
    outcomes, failed = _walk(b, ["type #qty 1", "type input#qty 2", "type input#qty 3"])
    check_eq("a backend with no `same_field`: other spelling is a new field, the same spelling continues as before",
             (_flags(b), outcomes), ([False, False, True], ["ok", "ok", "ok"]))


def test_backend_raises_in_same_field():
    b = _Says()
    b.answer = RuntimeError
    outcomes, failed = _walk(b, ["type #qty 1", "type input#qty 2"])
    check_eq("an error in `same_field`: a new field, no crash", (_flags(b), outcomes, failed), ([False, False], ["ok", "ok"], None))


def test_same_selector_does_not_ask():
    b = _Says()
    _walk(b, ["type #qty 1", "type #qty 2"])
    check_eq("the same spelling continues (TR1-1) and the backend is not asked", (_flags(b), getattr(b, "asked", [])), ([False, True], []))


def test_other_actor_same_selector_is_a_new_field():
    rig = W.Rig(actors=("user", "admin"))
    rig.factory = lambda: (rig.made.append(_Recording()), rig.made[-1])[1]
    W.MC.BACKEND_FACTORY = rig.factory
    rig.start()
    try:
        rig.step(W.GO + "type #qty 1\n", actor="user")
        rig.step("type #qty 2\n", actor="admin")
        # one backend per actor, made in the order of the actors: made[0] is actor A (user), made[1] is actor B (admin); every read below
        # names the backend of the actor whose step it judges (never a list flattened over both)
        a_backend, b_backend = rig.made[0], rig.made[1]
        check_eq("actor B's first `type` on actor A's selector is a first call (A's one call and B's one call, each a first)",
                 (a_backend.typed_calls, b_backend.typed_calls), ([("#qty", False)], [("#qty", False)]))
        rig.step("type #qty 3\n", actor="admin")
        check_eq("actor B's second `type` continues B's own chain", b_backend.typed_calls[-1], ("#qty", True))
        rig.step("type #qty 4\n", actor="user")
        check_eq("and going back to actor A breaks it again (A's own backend: its last call, not B's)", a_backend.typed_calls[-1], ("#qty", False))
    finally:
        rig.done()


class _Handle:
    def __init__(self, name):
        self.name = name


class _Loc:
    def __init__(self, page, selector):
        self.page, self.selector, self.first = page, selector, self

    def element_handle(self, timeout=None):
        return _Handle(self.page.resolve[self.selector]) if self.selector in self.page.resolve else None

    def evaluate(self, script, other=None, timeout=None):
        return self.page.resolve.get(self.selector) == other.name


class _Page:
    def __init__(self, resolve):
        self.resolve = resolve

    def locator(self, selector):
        return _Loc(self, selector)


def test_playwright_same_field_reads_the_page():
    real = MC.PlaywrightBackend.__new__(MC.PlaywrightBackend)
    real._page = _Page({"#qty": "e1", "input#qty": "e1", "#other": "e2"})
    check_eq("two spellings of one element: True", real.same_field("#qty", "input#qty"), True)
    check_eq("two elements: False", real.same_field("#qty", "#other"), False)
    check_eq("a selector matching nothing: False", real.same_field("#qty", "#nope"), False)
    real._page = None
    check_eq("a page that cannot answer: False, no crash", real.same_field("#qty", "input#qty"), False)


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    finish("test_walk_type_chain")


if __name__ == "__main__":
    main()
