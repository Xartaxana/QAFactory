#!/usr/bin/env python3
"""Every block in the controller has a named route through it (FR-4, FR-5; PLAN P21.4).

`design/controller-blocks.md` is the walk: one row per `raise StateConflict` in
`controller.py`, each with the route a person takes through it — their recorded word, a
factory command, or "no word passes this, because ...". This file is what keeps the walk
true: a block with no row fails, a row with no block fails, and a route outside the three
fails.

Why a file and not a comment: the rule was kept per-check, so it held at one gate and failed
at the next. S5's completion demanded a window acceptance record that no word could pass, and
it cost three answers and a halt in TP1-13797 run 5 before it read `stage_overrides[]`
like the rest. The walk that followed found two more of the same shape (S1 sources, S3 plan
rows) and 81 blocks whose way through is a command the message already names.

The key is the function plus the message, never a line number: lines move with every edit
above them.
"""
import ast
import collections
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq  # noqa: E402

PLUGIN = harness.PLUGIN_ROOT
WALK = PLUGIN / "design" / "controller-blocks.md"
ROUTES = {"person", "command", "caller", "unpassable"}

sys.path.insert(0, str(harness.SCRIPTS))
import event_store  # noqa: E402


def refusal_classes() -> frozenset:
    """Every class a refusal of the controller can be raised as: `ValueError`, `StateConflict`
    and what the event store derives from them (`DerivedViewStale`, ...). Derived from the module
    that defines them, so a new subclass is walked the day it is raised and not the day somebody
    remembers this list. The walk once matched two names, and a block raised as a subclass
    (`DerivedViewStale`, the refusal that says "the event is committed, do not repeat it") had no
    row and no door (FR-2)."""
    found = {"ValueError"}
    for value in vars(event_store).values():
        if isinstance(value, type) and issubclass(value, ValueError) and value.__module__ == event_store.__name__:
            found.add(value.__name__)
    return frozenset(found)


def blocks_in_source(src=None) -> collections.Counter:
    """(function, class, first literal of the message) for every `raise` of a refusal class and
    every collected `(Class, message)` pair - the form `_decision_problems` and the S5 completion
    gather their problems in. `src` is the controller's text unless a test passes its own."""
    classes = refusal_classes()
    src = src if src is not None else (harness.SCRIPTS / "controller.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = collections.Counter()

    class Walk(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def visit_FunctionDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def block(self, node, cls_name):
            segment = " ".join((ast.get_source_segment(src, node) or "").split())
            literal = re.search(r'"((?:[^"\\]|\\.)+)"', segment)
            text = (literal.group(1) if literal else "").strip()
            # A literal that is only a joiner says nothing about the block: the walk shows
            # the call for those, and the key has to be the same on both sides.
            if len(text.strip(" .;,-")) < 4:
                text = segment[:70]
            found[(self.stack[-1] if self.stack else "?", cls_name, text[:110])] += 1

        def visit_Raise(self, node):
            exc = node.exc
            if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name) and exc.func.id in classes:
                self.block(node, exc.func.id)
            self.generic_visit(node)

        def visit_ExceptHandler(self, node):
            # `except (StateConflict, ValueError):` names two classes and refuses nothing: only
            # the body is walked, never the handler's type.
            for child in node.body:
                self.visit(child)

        def visit_Tuple(self, node):
            # A COLLECTED block (K1): `(StateConflict, "<message>")` is a refusal that is raised
            # later, with its siblings, by `_raise_all`. Keyed exactly like a `raise` (function +
            # head literal, or the segment when there is none). A tuple of two classes
            # (`isinstance(x, (A, B))`) is no message.
            first, second = (node.elts + [None, None])[:2]
            if (len(node.elts) == 2 and isinstance(first, ast.Name) and first.id in classes
                    and not (isinstance(second, ast.Name) and second.id in classes)):
                self.block(node, first.id)
            self.generic_visit(node)

    Walk().visit(tree)
    return found


def rows_in_walk() -> tuple:
    rows, routes = collections.Counter(), []
    for line in WALK.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        # Five columns: the summary table at the top of the file has three, and skipping it
        # this way means the walk can grow a preamble without the test noticing anything.
        if len(cells) != 5 or cells[3].strip("`") not in ROUTES:
            continue
        rows[(cells[0].strip("`"), cells[1].strip("`"), cells[2].replace("\\|", "|"))] += 1
        routes.append((cells[0].strip("`"), cells[2], cells[3].strip("`"), cells[4]))
    return rows, routes


def main() -> None:
    check(f"the walk exists: design/{WALK.name}", WALK.is_file())
    source, (walked, routes) = blocks_in_source(), rows_in_walk()

    missing = sorted(key for key in source if source[key] > walked.get(key, 0))
    check("every block in controller.py has a row in the walk", not missing,
          "not walked: " + "; ".join(f"{fn} {cls}: {msg[:60]}" for fn, cls, msg in missing[:6]))
    stale = sorted(key for key in walked if walked[key] > source.get(key, 0))
    check("and every row in the walk still has a block", not stale,
          "gone from the source: " + "; ".join(f"{fn} {cls}: {msg[:60]}" for fn, cls, msg in stale[:6]))
    check_eq("the counts agree", sum(source.values()), sum(walked.values()))

    for where, message, route, way in routes:
        check(f"{where}: `{message[:44]}` names its way through", bool(way.strip()),
              f"route `{route}` with an empty column is a row nobody can act on (FR-1)")
        if route == "unpassable":
            check(f"{where}: `{message[:44]}` says why no word passes it",
                  len(way.strip()) > 40, "an `unpassable` row is only honest with its reason")

    # The three routes are a closed set: a fourth would be a way through that nothing holds.
    seen = {route for _, _, route, _ in routes}
    check_eq("the walk uses the three routes and no others", seen, ROUTES)

    # The blocks measured in run 5 take the person's route, because their own refusal says so.
    person = {message for _, message, route, _ in routes if route == "person"}
    # (t-721 F-7: the S1 source collection branch is gone - `source_inputs` is the one reader of the inventory
    # and a source gap is passed by `accept-gap`; the block `S1 source collection pending/invalid` no longer exists.)
    for message in ("S3 structured test plan invalid",):
        check(f"a person's word passes `{message[:42]}`",
              any(m.startswith(message) for m in person), str(sorted(person))[:400])
    # S5's window gate raises the message a variable holds, so the walk shows the call and not
    # the sentence. What matters is that it is raised from a filtered list at all.
    check("and the S5 window gate reads the person's word too",
          any("blocking[0]" in m for m in person), str(sorted(person))[:400])

    harness.finish("test_controller_blocks")


if __name__ == "__main__":
    main()
