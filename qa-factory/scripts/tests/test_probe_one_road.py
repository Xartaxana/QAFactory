"""t-2045 N1: ONE road to the check the probe inverts, for every language (task t-2058, node TR2-14).

The reader order is one function, `probe_by_code._target_of`: `--at` (a line, or `<file>:<line>`), then `--oracle`, then the manifest row's
`assertion_id`, then the first check. A line is looked up in the WHOLE file (`check_on_line`), so a check in a local helper or a
page-object method needs no declaration. Nothing in these tests asks what language the file is in except the fixture: every case is
parametrised over python, typescript, csharp and java, and a red names the language and the branch (P16: the id of the parameter is the
case). No probe is run: pure functions and temp files, so the file is fast.

    python -B scripts/tests/test_probe_one_road.py
"""
import hashlib
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import assertion_detectors as AD  # noqa: E402
import probe_by_code as PBC  # noqa: E402
import probe_debt as PD  # noqa: E402
import proof_level as PL  # noqa: E402

LANGS = ("python", "typescript", "csharp", "java")

# Each fixture marks the lines the tests aim at with `@NAME` in a comment on the line: FIRST (a setup check, the first of the test),
# THEN (the second check - the owner's case), MID (the middle line of a statement that spans three lines), CALL (a call of the
# helper, no check on it), COMMENT (a comment-only line; the next line is blank), HELPER (a check in a helper of the same file),
# OTHER (the only check of another test of the same file).
PY = '''\
import helpers


def test_adds():
    total = add(1, 1)
    assert total > 0, "step"  # @FIRST
    # a comment @COMMENT

    assert total == 2, "then"  # @THEN
    assert (
        total  # @MID
        == 2
    ), "multi"
    check_cart(total)  # @CALL


def check_cart(n):
    assert n == 1, "helper"  # @HELPER


def test_other():
    assert 1 == 1  # @OTHER
'''
CS = '''\
using Xunit;
public class CalcTests
{
    [Fact]
    public void Adds()
    {
        var total = Add(1, 1);
        Assert.True(total > 0);  // @FIRST
        // a comment @COMMENT

        Assert.Equal(2, total);  // @THEN
        Assert.Equal(
            2,  // @MID
            total);
        CheckCart(total);  // @CALL
    }

    private void CheckCart(int n)
    {
        Assert.Equal(1, n);  // @HELPER
    }

    [Fact]
    public void Other()
    {
        Assert.Equal(1, 1);  // @OTHER
    }
}
'''
JAVA = '''\
class CalcTest {
    @Test
    void adds() {
        int total = add(1, 1);
        assertTrue(total > 0);  // @FIRST
        // a comment @COMMENT

        assertEquals(2, total);  // @THEN
        assertEquals(
            2,  // @MID
            total);
        checkCart(total);  // @CALL
    }

    private void checkCart(int n) {
        assertEquals(1, n);  // @HELPER
    }

    @Test
    void other() {
        assertEquals(1, 1);  // @OTHER
    }
}
'''
TS = '''\
import { test, expect } from '@playwright/test';
test('adds', async () => {
  const total = add(1, 1);
  expect(total).toBeTruthy();  // @FIRST
  // a comment @COMMENT

  expect(total).toBe(2);  // @THEN
  expect(
    total,  // @MID
  ).toBe(2);
  checkCart(total);  // @CALL
});
function checkCart(n: number) {
  expect(n).toBe(1);  // @HELPER
}
test('other', async () => {
  expect(1).toBe(1);  // @OTHER
});
'''
HELPER_NAME = {"python": "check_cart", "typescript": "checkCart", "csharp": "CheckCart", "java": "checkCart"}
# the helper FILE of each language (a page-object method / helper function in another file of the test tree), one check on @HELPER2
HELPER_FILE = {
    "python": 'def expect_cart(n):\n    assert n == 1, "h"  # @HELPER2\n',
    "typescript": "export function expectCart(n: number) {\n  expect(n).toBe(1);  // @HELPER2\n}\n",
    "csharp": "public class Pages\n{\n    public void ExpectCart(int n)\n    {\n        Assert.Equal(1, n);  // @HELPER2\n    }\n}\n",
    "java": "class Pages {\n    void expectCart(int n) {\n        assertEquals(1, n);  // @HELPER2\n    }\n}\n",
}
FIXTURE = {
    "python": {"text": PY, "ext": ".py", "file": "test_calc.py", "test": "test_adds", "other": "test_other"},
    "typescript": {"text": TS, "ext": ".ts", "file": "calc.spec.ts", "test": "adds", "other": "other"},
    "csharp": {"text": CS, "ext": ".cs", "file": "CalcTests.cs", "test": "CalcTests.Adds", "other": "CalcTests.Other"},
    "java": {"text": JAVA, "ext": ".java", "file": "CalcTest.java", "test": "CalcTest.adds", "other": "CalcTest.other"},
}


def line_of(text: str, name: str) -> int:
    for number, line in enumerate(text.splitlines(), 1):
        if name in line:
            return number
    raise AssertionError(f"{name} is not in the fixture")


class World:
    """A project in a temp folder: tests/<test file>, tests/Pages<ext> (a helper file), src/app<ext> (a file of the product, with a
    check on it), and a context shaped like `ProbeCtx` for the readers under test."""

    def __init__(self, tmp_path: Path, language: str, assertion_id=None, text=None):
        fx = FIXTURE[language]
        self.language, self.fx, self.root = language, fx, tmp_path
        self.text = fx["text"] if text is None else text
        (tmp_path / "tests").mkdir()
        (tmp_path / "src").mkdir()
        self.path = tmp_path / "tests" / fx["file"]
        self.path.write_bytes(self.text.encode("utf-8"))
        self.helper = tmp_path / "tests" / ("helpers" + fx["ext"] if language == "python" else "Pages" + fx["ext"])
        self.helper.write_bytes(HELPER_FILE[language].encode("utf-8"))
        self.app = tmp_path / "src" / ("app" + fx["ext"])
        self.app.write_bytes(HELPER_FILE[language].encode("utf-8"))
        entry = {"instance_id": "i1", "case": "TC-1", "covers": ["TC-1"]}
        if assertion_id is not None:
            entry["assertion_id"] = assertion_id
        self.rel = f"tests/{fx['file']}"
        self.spec = PBC.parse_node(f"{self.rel}::{fx['test']}", tmp_path)
        self.ctx = SimpleNamespace(root=tmp_path, cfg={"tests_root": "tests"}, spec=self.spec, entry=entry, path=self.path,
                                   detector=self.spec["reader"] == "table", mutation="invert", instance_id="IID")

    def line(self, name: str) -> int:
        return line_of(self.text, name)

    def helper_line(self) -> int:
        return line_of(HELPER_FILE[self.language], "@HELPER2")

    def target(self, at=None, oracle: str = "") -> dict:
        return PBC._target_of(self.ctx, at, oracle, self.path.read_bytes())

    def plan(self, target: dict) -> tuple:
        """(mutated text, detail) of the plan this target gives - what `_plan` runs, without the run-shape checks."""
        mutated, detail, _context = PBC._reader_plan(self.ctx, target, target["file"].read_bytes(), target["file"], "", "", "")
        return mutated.decode("utf-8"), detail

    def changed_lines(self, mutated: str, target: dict) -> list:
        before = target["file"].read_text(encoding="utf-8").splitlines()
        after = mutated.splitlines()
        assert len(before) == len(after), "the line count is kept"
        return [n for n, (a, b) in enumerate(zip(before, after), 1) if a != b]


@pytest.fixture(params=LANGS)
def world(request, tmp_path):
    return lambda assertion_id=None, text=None: World(tmp_path, request.param, assertion_id, text)


def refusal(fn) -> str:
    with pytest.raises(PBC.Refusal) as caught:
        fn()
    assert not isinstance(caught.value, PBC.ToolRefusal), "a target problem is the call's (or the author's), never a tool gap"
    return str(caught.value)


def test_default_target_is_assertion_id(world):
    w = world()
    ident = f"{w.rel}:{w.line('@THEN')}"
    w.ctx.entry["assertion_id"] = ident
    target = w.target()
    assert (target["source"], target["line"], target["file"].resolve()) == ("assertion_id", w.line("@THEN"), w.path.resolve()), target
    assert target["outside_body"] is False and target["given"] is None and target["note"] == ""
    mutated, detail = w.plan(target)
    assert detail["line"] == w.line("@THEN") and detail["target_source"] == "assertion_id" and detail["at"] is None, detail
    assert detail["target_outside_body"] is False
    fact = PBC.target_fact(detail, w.spec, ident)
    assert fact["is_assertion_id"] is True and fact["source"] == "assertion_id", fact


def test_second_check_is_the_then(world):
    """The owner's case: the Then is the SECOND check; the probe must not break the first one."""
    w = world()
    w.ctx.entry["assertion_id"] = f"{w.rel}:{w.line('@THEN')}"
    mutated, detail = w.plan(w.target())
    assert w.changed_lines(mutated, w.target()) == [w.line("@THEN")], "only the Then's own line changes"
    first_line = mutated.splitlines()[w.line("@FIRST") - 1]
    assert first_line == w.text.splitlines()[w.line("@FIRST") - 1], first_line
    assert detail["line"] == w.line("@THEN")


def test_at_wins_over_id(world):
    w = world()
    ident = f"{w.rel}:{w.line('@THEN')}"
    w.ctx.entry["assertion_id"] = ident
    target = w.target(at=w.line("@FIRST"))
    assert (target["source"], target["line"], target["given"]) == ("at", w.line("@FIRST"), w.line("@FIRST")), target
    mutated, detail = w.plan(target)
    assert detail["line"] == w.line("@FIRST") and detail["at"] == w.line("@FIRST") and detail["target_source"] == "at", detail
    assert PBC.target_fact(detail, w.spec, ident)["is_assertion_id"] is False       # the receipt of another line never counts


def test_at_on_python():
    """`--at` is no longer refused on a Python test: the flag check, the parser and the plan read it."""
    spec = PBC.parse_node("tests/test_calc.py::test_adds")
    PBC._refuse_flags(spec, "invert")                                                # no `at` in it any more
    assert PBC._build_parser().parse_args(["--at", "7"]).at == 7
    assert PBC._build_parser().parse_args(["--at", "tests/h.py:7"]).at == "tests/h.py:7"
    for bad in ("x", "7x", "tests/h.py:", ":7", "-3"):
        with pytest.raises(SystemExit):
            PBC._build_parser().parse_args(["--at", bad])
    mutated, detail = PBC.plan_mutation(PY.encode(), spec, "invert", "IID", at=line_of(PY, "@THEN"))
    assert detail["line"] == line_of(PY, "@THEN") and b"assert not (" in mutated, detail


def test_at_file_line_reaches_helper(world):
    w = world()
    spelled = f"tests/{w.helper.name}:{w.helper_line()}"
    target = w.target(at=spelled)
    assert target["file"].resolve() == w.helper.resolve() and target["source"] == "at" and target["given"] == spelled, target
    assert target["line"] == w.helper_line() and target["outside_body"] is True and target["same_file"] is False
    mutated, detail = w.plan(target)
    assert detail["line"] == w.helper_line() and detail["at"] == spelled and detail["target_outside_body"] is True, detail
    assert w.changed_lines(mutated, target) == [w.helper_line()]
    if w.language != "python":
        assert detail["declaration_line"] is None and detail["candidates"] == [], detail     # no declaration of the test is read


def test_at_inside_multiline_statement(world):
    w = world()
    mid = w.line("@MID")
    target = w.target(at=mid)
    mutated, detail = w.plan(target)
    start = w.line("@MID") - 1
    facts = PBC.check_on_line(w.text.encode(), w.rel, PBC._reader_entry(w.spec), mid)
    assert detail["line"] == start and detail["end_line"] >= start + 2, detail         # the statement starts one line above the middle
    assert facts["found"]["line"] == start and facts["found"]["end_line"] == detail["end_line"], facts   # the door and the plan agree


def test_line_with_no_check_refused_names_nearest(world):
    w = world()
    blank = w.line("@COMMENT") + 1
    for what, line in (("blank", blank), ("comment", w.line("@COMMENT")), ("past the end", len(w.text.splitlines()) + 5)):
        before = w.path.read_bytes()
        target = w.target(at=line)
        text = refusal(lambda: w.plan(target))
        assert "holds no check of a form the factory reads" in text, (what, text)
        assert "manifest_put.py" in text and "--fragment" in text and "unverified" in text, (what, text)
        assert w.path.read_bytes() == before, "nothing was written"
        if what != "past the end":
            assert f"`--at {w.line('@THEN')}`" in text, (what, text)                       # the nearest check below is named, never chosen
        else:
            assert "No check of a form the factory reads follows it" in text, text
    call = w.target(at=w.line("@CALL"))
    text = refusal(lambda: w.plan(call))
    assert f"calls `{HELPER_NAME[w.language]}(`" in text, text


def test_no_id_takes_first_with_note(world):
    w = world()
    target = w.target()
    assert (target["source"], target["line"], target["outside_body"]) == ("first", None, False), target
    assert "no assertion_id" in target["note"], target
    mutated, detail = w.plan(target)
    assert detail["line"] == w.line("@FIRST") and detail["target_source"] == "first", detail


def test_name_like_id_is_null(world):
    w = world("add_returns_sum")
    target = w.target()
    assert (target["source"], target["line"]) == ("first", None), target
    assert "add_returns_sum" in target["note"] and "<file>:<line>" in target["note"], target
    _mutated, detail = w.plan(target)
    assert PBC.target_fact(detail, w.spec, "add_returns_sum")["is_assertion_id"] is None
    for odd in ("tests/x:0", "x:", ":4", 7):                                          # not a line either: the same road
        w.ctx.entry["assertion_id"] = odd
        assert w.target()["source"] == "first", odd


def test_id_outside_test_tree_refused(world):
    w = world()
    for ident in (f"src/{w.app.name}:2", f"../{w.app.name}:2", f"tests/missing{w.fx['ext']}:2"):
        w.ctx.entry["assertion_id"] = ident
        before = w.path.read_bytes()
        text = refusal(w.target)
        assert ("no such file" in text) or ("not under a test root" in text), (ident, text)
        assert w.path.read_bytes() == before
    w.ctx.entry["assertion_id"] = f"tests/{w.helper.name}:{w.helper_line()}"            # a helper under the tree is fine
    assert w.target()["file"].resolve() == w.helper.resolve()


def test_python_oracle_absent_file_refused(world):
    """#18: an oracle file that is not there is a refusal, never a fall back to the test - for every language now."""
    w = world()
    text = refusal(lambda: w.target(oracle=f"tests/gone{w.fx['ext']}::helper"))
    assert "--oracle names the file" in text and "no such file" in text, text


def test_python_oracle_outside_tree_refused(world):
    w = world()
    text = refusal(lambda: w.target(oracle=f"src/{w.app.name}::helper"))
    assert "not under a test root" in text and "red_sandbox.py --probe" in text, text
    (w.root / "tests" / "notes.txt").write_text("x", encoding="utf-8")
    wrong = refusal(lambda: w.target(oracle="tests/notes.txt::helper"))
    assert "is not a" in wrong and "file" in wrong, wrong


def test_oracle_wins_the_file_over_id_and_at_wins_the_line(world):
    w = world()
    w.ctx.entry["assertion_id"] = f"{w.rel}:{w.line('@THEN')}"
    target = w.target(oracle=f"tests/{w.helper.name}::helper")
    assert target["source"] == "oracle" and target["line"] is None and target["file"].resolve() == w.helper.resolve(), target
    assert target["outside_body"] is True
    both = w.target(at=w.helper_line(), oracle=f"tests/{w.helper.name}::helper")
    assert both["source"] == "at" and both["line"] == w.helper_line() and both["file"].resolve() == w.helper.resolve(), both
    resolved = PBC._resolve_oracle(w.root, w.root, {}, w.spec, f"tests/{w.helper.name}::helper", w.path, b"", target)
    assert resolved[0].resolve() == w.helper.resolve() and resolved[1] == "helper", resolved
    by_line = PBC._resolve_oracle(w.root, w.root, {}, w.spec, "", w.path, b"", both)
    assert by_line[1] == "" and by_line[0].resolve() == w.helper.resolve(), by_line     # a line names no function


def test_outside_body_stale_id_and_page_object(world):
    """E-O: an id on ANOTHER test's check, and a check in a method helper, are outside the body; the plan says so, and the keys that
    only a declaration gives stay empty (AR-2: the tool reports, the role decides which check is the Then's)."""
    w = world()
    for name in ("@OTHER", "@HELPER"):
        w.ctx.entry["assertion_id"] = f"{w.rel}:{w.line(name)}"
        target = w.target()
        assert target["source"] == "assertion_id" and target["outside_body"] is True and target["same_file"] is True, (name, target)
        mutated, detail = w.plan(target)
        assert detail["line"] == w.line(name) and detail["target_outside_body"] is True, (name, detail)
        if w.language != "python":
            assert detail["declaration_line"] is None and detail["candidates"] == [], (name, detail)
    w.ctx.entry["assertion_id"] = f"{w.rel}:{w.line('@MID') - 1}"
    inside = w.target()
    assert inside["outside_body"] is False, inside


def test_body_not_located_is_null(world):
    w = world()
    ghost = SimpleNamespace(**dict(vars(w.ctx), spec=dict(w.spec, function="no_such_test", chain=[])))
    ghost.entry = dict(w.ctx.entry, assertion_id=f"{w.rel}:{w.line('@THEN')}")
    target = PBC._target_of(ghost, None, "", w.path.read_bytes())
    assert target["line"] == w.line("@THEN") and target["outside_body"] is None, target     # read as outside, never as inside
    assert PBC.test_body_span(w.path.read_bytes(), ghost.spec, PBC._reader_entry(ghost.spec)) is None
    span = PBC.test_body_span(w.path.read_bytes(), w.spec, PBC._reader_entry(w.spec))
    assert span and span[0] <= w.line("@FIRST") <= w.line("@CALL") <= span[1] and not span[0] <= w.line("@HELPER") <= span[1], span


def test_calls_helper_generic_rule(world):
    """S13: the last name before `(` on the line (Python: the outermost call that starts there); None when there is none."""
    w = world()
    facts = PBC.check_on_line(w.text.encode(), w.rel, PBC._reader_entry(w.spec), w.line("@CALL"))
    assert facts["found"] is None and facts["calls_helper"] == HELPER_NAME[w.language], facts
    assert facts["nearest_below"] is not None
    on_check = PBC.check_on_line(w.text.encode(), w.rel, PBC._reader_entry(w.spec), w.line("@THEN"))
    assert on_check["found"]["line"] == w.line("@THEN"), on_check
    comment = PBC.check_on_line(w.text.encode(), w.rel, PBC._reader_entry(w.spec), w.line("@COMMENT"))
    assert comment["found"] is None and comment["calls_helper"] is None, comment            # a comment is blanked, no call
    assert PBC.check_on_line(w.text.encode(), w.rel, PBC._reader_entry(w.spec), 0)["found"] is None


def test_two_checks_on_one_line_the_first_with_a_note(tmp_path):
    two = "def test_adds():\n    total = 2\n    assert total > 0; assert total == 2\n"
    spec = PBC.parse_node("tests/test_calc.py::test_adds")
    mutated, detail = PBC.plan_mutation(two.encode(), spec, "invert", "IID", at=3)
    assert detail["line"] == 3 and "assert not (total > 0)" in mutated.decode() and "two checks start on line 3" in detail["target_note"]
    ts = "test('adds', async () => {\n  expect(1).toBe(1); expect(2).toBe(2);\n});\n"
    tspec = PBC.parse_node("tests/a.spec.ts::adds")
    mutated, detail, _ctx = PBC.plan_detector_mutation(ts.encode(), tspec, "IID", 2, "", "", "tests/a.spec.ts")
    assert detail["line"] == 2 and "two checks start on line 2" in detail["target_note"] and "expect(1).not.toBe(1)" in mutated.decode(), \
        (detail, mutated)


def test_debt_replays_file_line_at():
    """`probe_debt._replay_plan` hands `--at` back as it was spelled: an int (not a bool) or `<file>:<line>`, so a replay aims at
    the same line of the same file; a record the id aimed (`at` null) is re-aimed by the probe itself."""
    def plan(at, **detail):
        record = {"test_node": "tests/CalcTests.cs::CalcTests.Adds", "mutation": "invert",
                  "mutation_detail": dict({"line": 2, "mutation": "invert", "style": "detector", "at": at}, **detail)}
        return PD._replay_plan(record, Path("."))
    for at, wanted in ((15, "15"), (0, "0"), (None, ""), ("", ""), (True, ""), ("15", ""), ("tests/Pages.cs:7", "tests/Pages.cs:7"),
                       (" tests/Pages.cs:7 ", "tests/Pages.cs:7"), ("tests/Pages.cs:x", ""), (7.5, "")):
        assert plan(at)[3] == wanted, (at, plan(at))
    # a record that mutated another file and names no oracle function replays when `at` carries that file; without it, the critic names it
    moved = plan("tests/Pages.cs:7", file="tests/Pages.cs")
    assert moved[3] == "tests/Pages.cs:7" and moved[4] == "", moved
    assert plan(None, file="tests/Pages.cs")[4] != ""


def test_off_target_note_has_one_door():
    fact = {"line": 40, "end_line": 40, "assertion_id": "e2e/cart.spec.ts:43", "is_assertion_id": False}
    note = PBC._off_target_note(fact)
    assert "--at 43" in note and "not read" not in note, note


# --- N1b: a repeat is answered by the bytes AND the target (B10) ------------------------------------------------------

SHA = "a" * 64
TEST_REL = "tests/test_calc.py"


class Repeat:
    """A task folder with probe records and the entry/identity `already_probed` asks about; no probe is run."""

    def __init__(self, tmp_path):
        self.task = tmp_path / "task"
        self.task.mkdir()
        self.entry = {"instance_id": "i1", "file": TEST_REL}
        self.now = {"input_hash": SHA, "test_code_sha": "c" * 64, "instance_identity": {}}

    def write(self, verdict="no_failure", target="absent", path=None, **over):
        body = {"schema_version": 1, "probe_tool": "probe_by_code.py", "instance_id": "i1", "verdict": verdict,
                "recorded_at": "2026-11-05T10:00:00+00:00", "test_file_sha256": SHA, "test_code_sha": "c" * 64,
                "mutated_file": {"path": TEST_REL, "sha256": "d" * 64, "code_sha": "e" * 64}}
        if target != "absent":
            body["target"] = target
        body.update(over)
        path = path or PL.probe_record_path(self.task, "i1")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body), encoding="utf-8")
        return path

    def asked(self, line, source="at", file=TEST_REL, **kwargs):
        return PL.already_probed(self.entry, {}, self.task, now=self.now, project=self.task.parent,
                                 target={"file": file, "line": line, "source": source}, **kwargs)


def fact(line, end_line=None, source="assertion_id", is_id=True):
    return {"line": line, "end_line": end_line or line, "assertion_id": f"{TEST_REL}:{line}", "is_assertion_id": is_id,
            "source": source}


def test_same_bytes_other_target_runs(tmp_path):
    r = Repeat(tmp_path)
    r.write(target=fact(47))
    got = r.asked(46)                                                    # the printed door: the line before the one that failed to fail
    assert got["probed"] is False, got
    assert any("line 47" in n and "line 46" in n for n in got["notes"]), got["notes"]      # the note names the earlier probe's line
    assert r.asked(48)["probed"] is False                                # one past the statement is another check
    other = r.asked(47, file="tests/Pages.cs")                           # the same line of another file is another check
    assert other["probed"] is False, other
    # a multi-line statement holds its inner lines, and the receipt of other bytes never counts (INV)
    r.write(target=fact(10, 13))
    assert [r.asked(n)["probed"] for n in (9, 10, 12, 13, 14)] == [False, True, True, True, False]
    r.now = dict(r.now, input_hash="b" * 64, test_code_sha="f" * 64)
    assert r.asked(10)["probed"] is False


def test_same_bytes_same_target_refused(tmp_path):
    """The negative control of the other tests: the same bytes, the same target, `no_failure` - refused as today."""
    r = Repeat(tmp_path)
    r.write(target=fact(47))
    got = r.asked(47)
    assert got["probed"] is True and got["by"] == "probe_record" and got["prior_verdict"] == "no_failure", got
    assert r.asked(47, source="assertion_id")["probed"] is True          # the source of the request does not matter for a line
    r.write(verdict="wrong_location", target=fact(47))
    assert r.asked(47)["probed"] is True
    # the person's word still passes a repeat of the same target (INV): the door is not touched by this node
    assert PL.already_probed(r.entry, {}, r.task, now=r.now, project=r.task.parent, target=None)["probed"] is True


def test_first_after_first_refused(tmp_path):
    r = Repeat(tmp_path)
    for stored in (fact(5, source="first"), {k: v for k, v in fact(5).items() if k != "source"}):    # no `source`: written before N1
        r.write(target=stored)
        assert r.asked(None, source="first")["probed"] is True, stored
    r.write(target=fact(5, source="at"))                                  # an earlier probe aimed by hand is another target
    assert r.asked(None, source="first")["probed"] is False
    r.write(target=fact(5, source="assertion_id"))
    assert r.asked(None, source="first")["probed"] is False


def test_old_record_no_target_line_runs(tmp_path):
    r = Repeat(tmp_path)
    r.write()                                                            # a record from before `target`
    assert r.asked(46)["probed"] is False                                # asked by line: it runs (toward running)
    assert r.asked(None, source="first")["probed"] is True               # asked by the first check: today's answer
    assert PL.already_probed(r.entry, {}, r.task, now=r.now, project=r.task.parent)["probed"] is True      # `target=None`: byte for byte
    r.write(target={"line": "x", "end_line": None})                      # a target nobody can read is no match either
    assert r.asked(46)["probed"] is False
    r.write(target=fact(46), mutated_file=None)                          # no file known: different, never the same
    assert r.asked(46)["probed"] is False
    r.write(target=fact(46), mutated_file=None, mutation_detail={"file": TEST_REL})      # `mutation_detail.file` names it
    assert r.asked(46)["probed"] is True


def oracle_fact(function, source="oracle"):
    return {"line": 12, "end_line": 12, "assertion_id": None, "is_assertion_id": False, "source": source}


def oracle_asked(r, function, file="tests/h.ts"):
    return PL.already_probed(r.entry, {}, r.task, now=r.now, project=r.task.parent,
                             target={"file": file, "line": None, "source": "oracle", "oracle_function": function})


def oracle_record(r):
    """A stored `--oracle h.ts::g` record whose helper file still holds the bytes it mutated (so `_mutated_files_hold` is true)."""
    helper = r.task.parent / "tests" / "h.ts"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_bytes(b"export function g() {}\n")
    r.write(target=oracle_fact("g"), mutated_file={"path": "tests/h.ts", "sha256": hashlib.sha256(helper.read_bytes()).hexdigest()},
            mutation_detail={"oracle_function": "g", "file": "tests/h.ts"})


def test_oracle_repeat_same_function_refused(tmp_path):
    r = Repeat(tmp_path)
    oracle_record(r)
    got = oracle_asked(r, "g")
    assert got["probed"] is True and got["by"] == "probe_record", got


def test_oracle_other_function_runs(tmp_path):
    r = Repeat(tmp_path)
    oracle_record(r)
    assert oracle_asked(r, "other")["probed"] is False                    # another function of the same file
    assert oracle_asked(r, "g", file="tests/z.ts")["probed"] is False     # the same function name in another file
    assert oracle_asked(r, "")["probed"] is False                         # no function named: never "the same"


def test_oracle_after_first_runs(tmp_path):
    r = Repeat(tmp_path)
    r.write(target=fact(5, source="first"))                              # a record of the first check of the test file
    assert oracle_asked(r, "g", file=TEST_REL)["probed"] is False
    r.write()                                                            # a record from before `target`: not an oracle probe either
    assert oracle_asked(r, "g", file=TEST_REL)["probed"] is False
    assert r.asked(None, source="first")["probed"] is True               # the control: first vs a record from before target is the same


def test_replay_reads_legacy_expected_like_debt(tmp_path):
    """F2: one stored `expected` record, two readers (`proof_level._replay`, `probe_debt._replay_plan`), one answer."""
    r = Repeat(tmp_path)
    node = "tests/test_calc.py::test_adds"
    r.write(verdict="intended_failure", target=fact(5), test_node=node, mutation="expected",
            mutation_detail={"mutation": "expected", "line": 5})
    replay = PL._replay(r.entry, r.task)
    plan = PD._replay_plan(json.loads(PL.probe_record_path(r.task, "i1").read_text(encoding="utf-8")), Path("."))
    assert replay is not None and replay["mutation"] == "invert" == plan[1] and plan[4] == "", (replay, plan)
    assert PL.replay_mutation("expected") == "invert" and PL.replay_mutation("invert") == "invert"
    for odd in (None, 7, ["expected"], "other"):
        assert PL.replay_mutation(odd) == odd


def test_beside_record_blocks_its_own_line(tmp_path):
    r = Repeat(tmp_path)
    assert PL.probe_record_path(r.task, "i1", target_line=46).name == "i1--L46.json"
    assert PL.probe_record_path(r.task, "i1", target_line=46).parent == PL.probe_record_path(r.task, "i1").parent / "checks"   # t-2064 P4a
    for odd in (None, True, "46"):
        assert PL.probe_record_path(r.task, "i1", target_line=odd) == PL.probe_record_path(r.task, "i1"), odd
    long_id = "x" * 300
    assert PL.probe_record_path(r.task, long_id, target_line=7).name.endswith("--L7.json")
    r.write(verdict="intended_failure", target=fact(47))                 # the standing, proved record
    r.write(target=fact(46, is_id=False), path=PL.probe_record_path(r.task, "i1", target_line=46))
    got = r.asked(46)
    assert got["probed"] is True and got["record"] == "work/probes/checks/i1--L46.json", got
    assert r.asked(45)["probed"] is False and r.asked(None, source="first")["probed"] is False
    assert PL.already_probed(r.entry, {}, r.task, now=r.now, project=r.task.parent)["probed"] is False     # no target: only the standing one is read


def finished(w, tmp_path, target, verdict, assertion_id, **extra):
    """A probe record of `target` through `_new_record` and `_finish_record`: what the tool writes, without a run."""
    w.ctx.entry["assertion_id"] = assertion_id
    data = w.path.read_bytes()
    _mutated, detail = w.plan(target)
    detail.setdefault("marker", "m")
    ctx = SimpleNamespace(**dict(vars(w.ctx), task="T-1", dispatch="d1", instance_id="i1", case="TC-1", mutation="invert",
                                 detector=PBC._is_table(w.spec), task_root=tmp_path / "task", manifest_path=tmp_path / "none.json",
                                 stage="S5"))
    record = PBC._new_record(ctx, detail, {}, data, data, w.path)
    record.update(verdict=verdict, restore={"verified": True, "sha256": "s"}, **extra)
    PBC._finish_record(record, ctx.entry, ctx.task_root, "i1")
    return ctx, record, data


def test_new_record_never_overwrites_proved(world, tmp_path, monkeypatch):
    w = world()
    then, first = w.line("@THEN"), w.line("@FIRST")
    ident = f"{w.rel}:{then}"
    w.ctx.entry["assertion_id"] = ident
    (tmp_path / "task").mkdir()
    calls = []
    monkeypatch.setattr(PBC, "attach_receipt", lambda record, entry, task_root: calls.append(record["target"]["line"]))
    ctx, proved, _ = finished(w, tmp_path, w.target(), "intended_failure", ident)             # the id's check, proved
    standing = PL.probe_record_path(ctx.task_root, "i1")
    assert calls == [then] and json.loads(standing.read_text(encoding="utf-8"))["verdict"] == "intended_failure"
    # the retarget (another line) ends `no_failure`: it goes beside; the proved record is byte for byte as it was
    before = standing.read_bytes()
    _ctx, beside, _ = finished(w, tmp_path, w.target(at=first), "no_failure", ident)
    assert standing.read_bytes() == before, "the proved record is not overwritten"
    kept = PL.probe_record_path(ctx.task_root, "i1", target_line=first, file=(beside.get("mutation_detail") or {}).get("file"))
    assert json.loads(kept.read_text(encoding="utf-8"))["verdict"] == "no_failure" and beside["record"] == f"work/probes/checks/{kept.name}", beside
    assert any(f"line {then} stands in work/probes/i1.json" in n for n in beside["notes"]), beside["notes"]
    assert calls == [then], "no receipt is published from a beside record (even an intended_failure of the other line)"
    finished(w, tmp_path, w.target(at=first), "intended_failure", ident)
    assert calls == [then] and standing.read_bytes() == before
    # the controls: another judged verdict of the SAME target replaces as before; a run that judged nothing is the keeper's
    finished(w, tmp_path, w.target(), "no_failure", ident)
    assert json.loads(standing.read_text(encoding="utf-8"))["verdict"] == "no_failure"
    finished(w, tmp_path, w.target(), "intended_failure", ident)
    standing_before = standing.read_bytes()
    finished(w, tmp_path, w.target(at=first), "not_executed", ident)
    stored = json.loads(standing.read_text(encoding="utf-8"))
    assert stored["verdict"] == "intended_failure" and stored["last_attempt"]["verdict"] == "not_executed" and standing_before != standing.read_bytes()
    # an unproved standing record (no_failure) is overwritten by a retarget, as before
    finished(w, tmp_path, w.target(), "no_failure", ident)
    finished(w, tmp_path, w.target(at=first), "no_failure", ident)
    assert json.loads(standing.read_text(encoding="utf-8"))["target"]["line"] == first


def test_incomplete_judgment_kept_beside_proved(world, tmp_path, monkeypatch):
    """F3: an `incomplete` record `cause: judgment` of another target is kept BESIDE the proved one (the critic must be able to judge
    it); an `incomplete` without that cause is the keeper's (the proved record stays, `last_attempt` added)."""
    w = world()
    then, first = w.line("@THEN"), w.line("@FIRST")
    ident = f"{w.rel}:{then}"
    (tmp_path / "task").mkdir()
    w.ctx.entry["assertion_id"] = ident                                  # BEFORE the target is read: the id's line is the check
    monkeypatch.setattr(PBC, "attach_receipt", lambda record, entry, task_root: None)
    ctx, _proved, _ = finished(w, tmp_path, w.target(), "intended_failure", ident)
    standing = PL.probe_record_path(ctx.task_root, "i1")
    before = standing.read_bytes()
    _ctx, retarget, _ = finished(w, tmp_path, w.target(at=first), "incomplete", ident, cause="judgment")
    kept = PL.probe_record_path(ctx.task_root, "i1", target_line=first, file=(retarget.get("mutation_detail") or {}).get("file"))
    assert standing.read_bytes() == before, "the proved record is not overwritten"
    assert kept.is_file() and json.loads(kept.read_text(encoding="utf-8"))["verdict"] == "incomplete"
    kept.unlink()
    finished(w, tmp_path, w.target(at=first), "incomplete", ident, cause="tooling")      # the control: no judgment owed
    assert not kept.exists() and json.loads(standing.read_text(encoding="utf-8"))["last_attempt"]["verdict"] == "incomplete"


def test_printed_door_runs_second_call(world, tmp_path):
    """FR-2, end to end: a `no_failure` on a line other than the Then's prints `--at <the Then>`; the second call with that line is
    not `already_probed` (t-2031's trace: `no_failure` at L47, the printed `--at 46`, then the dead door)."""
    w = world()
    then, first = w.line("@THEN"), w.line("@FIRST")
    (tmp_path / "task").mkdir()
    ctx, record, data = finished(w, tmp_path, w.target(at=first), "no_failure", f"{w.rel}:{then}")
    note = PBC._off_target_note(record["target"], w.rel)
    printed = int(re.search(r"--at (\d+)", note).group(1))
    assert printed == then, note
    now = {"input_hash": hashlib.sha256(data).hexdigest(), "test_code_sha": record["test_code_sha"], "instance_identity": {}}
    sha = now["input_hash"]
    again, notes = PBC._repeat_check(ctx, now, sha, [], w.target(at=first))                     # the negative control: the same line is refused
    assert again and again["verdict"] == "already_probed", again
    second, notes = PBC._repeat_check(ctx, now, sha, [], w.target(at=printed))
    assert second is None, second
    assert any(f"line {first}" in n for n in notes), notes
    default, _ = PBC._repeat_check(ctx, now, sha, [], w.target())                                 # no --at: the id's line, the printed one
    assert default is None, default


# --- N7: `--mutation expected` is removed -------------------------------------------------------------------------------

def test_expected_refused_with_door(world):
    """Through the parser: argparse still lists `expected` (so it does not answer first with a list that omits it), and
    `_refuse_flags` refuses it, for every language, with one sentence and the door: an `invert` ENTRY of the call's model file (t-2064 P4b,
    FR-2: the flag `--mutation invert` selects nothing and is no bypass of a model, so the text no longer names it as the door)."""
    assert PBC.MUTATIONS == ("invert",)
    args = PBC._build_parser().parse_args(["--task", "T", "--test", "t.py::t", "--instance", "i", "--mutation", "expected"])
    assert args.mutation == "expected"                                          # not a SystemExit: the refusal is ours
    assert PBC._build_parser().parse_args(["--task", "T", "--test", "t.py::t", "--instance", "i"]).mutation == "invert"
    w = world()
    text = refusal(lambda: PBC._refuse_flags(w.spec, args.mutation))
    assert "--mutation expected was removed" in text and "Nothing was changed" in text, text
    assert "an `invert` entry for the check in the model file" in text and "work/probe-models/<dispatch id>.json" in text, text
    assert "use --mutation invert" not in text, text                            # the flag is no door any more (no bypass of a model)
    assert "never chooses another expected value" in text and "inverted, never" not in text, text
    PBC._refuse_flags(w.spec, "invert")                                         # the control: the one that remains passes
    with pytest.raises(PBC.Refusal):                                            # the plan refuses it too, naming what remains
        PBC.plan_mutation(PY.encode(), PBC.parse_node("tests/test_calc.py::test_adds"), "expected", "IID")
    assert not hasattr(PBC, "_literal_node") and not hasattr(PBC, "_replacement_literal")      # the literal replacement is gone, not parked


def test_old_expected_record_reads(tmp_path):
    """A stored record with `mutation: expected` still reads: a repeat of its bytes is answered, and its window block is whole."""
    r = Repeat(tmp_path)
    r.write(target=fact(47), mutation="expected", mutation_detail={"mutation": "expected", "literal_before": "4", "literal_after": "5"})
    assert r.asked(47)["probed"] is True
    stored = json.loads(PL.probe_record_path(r.task, "i1").read_text(encoding="utf-8"))
    assert PBC.window_probe(stored)["verdict"] == "no_failure" and stored["mutation"] == "expected"


def test_debt_replays_old_expected_as_invert():
    def plan(mutation):
        record = {"test_node": "tests/test_calc.py::test_adds", "mutation": mutation, "mutation_detail": {"line": 2, "at": 9}}
        return PD._replay_plan(record, Path("."))
    old = plan("expected")
    assert (old[1], old[3], old[4]) == ("invert", "9", ""), old                  # replayable, as the one inversion, aimed as before
    assert plan("invert")[1] == "invert" and plan("invert")[4] == ""
    for other in ("other", "", None, ["expected"], {"a": 1}, 7):                # any other unknown kind is refused as before, never a crash
        got = plan(other)
        assert got[1] == "invert" and "is not one this tool replays" in got[4], (other, got)
    assert PD.LEGACY_MUTATIONS == {"expected": "invert"} and set(PD.LEGACY_MUTATIONS.values()) <= set(PBC.MUTATIONS)


# --- N2: one plan contract - the reader key ------------------------------------------------------------------------------

def test_python_spec_reader_ast_no_language():
    """B1: `parse_node` writes `reader: "ast"`; N3b: a Python spec also carries `language`, `entry` (the `assertion_probes_ast` row)
    and `tail`, as a table spec does; a table spec says `reader: "table"`; a spec built by hand with no key is a named KeyError,
    not a guess (AR-23). `_reader_entry` is the source reader's entry: None for the AST reader."""
    py = PBC.parse_node("tests/test_calc.py::TestX::test_adds[p1]")
    assert py["reader"] == "ast" and py["language"] == "python" and py["entry"] == AD.ast_entry(".py")[1], py
    assert py["tail"] == "TestX::test_adds" and py["param"] == "p1", py
    assert PBC._reader_entry(py) is None and PBC._reader_entry(PBC.parse_node("tests/a.spec.ts::adds"))["lexer"], py
    for node in ("tests/a.spec.ts::adds", "t/T.cs::T.Adds", "t/CalcTest.java::CalcTest.adds"):
        assert PBC.parse_node(node)["reader"] == "table", node
    assert PBC._is_table(py) is False and PBC._is_table(PBC.parse_node("tests/a.spec.ts::adds")) is True
    assert PBC._is_table({"reader": "ast", "language": "x"}) is False
    try:
        PBC._is_table({"file": "t.py"})
    except KeyError as exc:
        assert exc.args == ("reader",), exc.args
    else:
        raise AssertionError("a spec with no `reader` must raise KeyError")


def test_python_build_request_keeps_node_id(tmp_path, monkeypatch):
    """B1: `build_request` for a Python test selects by the NODE ID (`node_ids=[spec["node"]]`) and checks `selected == [instance]`;
    a table test is built for the whole case (`node_ids=None`) - the same rows as before the key existed."""
    import execution_request as ER
    seen = {}

    def fake(root, cases, **kw):
        seen["node_ids"] = kw.get("node_ids")
        return {"selected_instance_ids": ["i1"], "input_fingerprint": "f" * 40}, [], True, True
    monkeypatch.setattr(ER, "build_mine_request", fake)
    monkeypatch.setattr(PBC, "artifacts_dir", lambda task: tmp_path / "art")
    for node, expected in (("tests/test_calc.py::test_adds", ["tests/test_calc.py::test_adds"]), ("tests/a.spec.ts::adds", None)):
        seen.clear()
        request, _notes = PBC.build_request(tmp_path, {}, "T", "D1", "TC-1", PBC.parse_node(node), "i1", "invert", "why")
        assert seen["node_ids"] == expected and request["built_by"]["instance_id"] == "i1", (node, seen)


def test_python_plan_through_reader_plan_stamps_the_target(world):
    """`_reader_plan` is the one call shape: a Python plan comes back with the table's keys, `at` from the target and the target's
    source stamped over the plan's own defaults (`None` when a direct caller gave no target)."""
    w = world()
    target = w.target(at=w.line("@THEN"))
    _mutated, detail = w.plan(target)
    assert detail["at"] == w.line("@THEN") and detail["target_source"] == "at" and detail["message_marker"] == "", detail
    assert {"line", "end_line", "mutation", "style", "language", "head", "form", "pair", "pair_id", "at", "candidates",
            "statement_before", "statement_after", "statement_inverted", "message_marker", "message_form", "message_note",
            "fires_as", "marker", "matcher_at", "declaration_line", "file", "target_source", "target_outside_body"} <= set(detail)
    assert (detail["language"] == "python") == (w.language == "python"), detail["language"]


# --- N2b: Python's check vocabulary is data (assertion_probes_ast.python.forms) ---------------------------------------------

SAMPLES = Path(__file__).resolve().parent / "fixtures" / "probe-languages"
UT = (SAMPLES / "sample_unittest.py").read_bytes()
PW = (SAMPLES / "sample_pw_expect.py").read_bytes()
TOKEN = "ab12cd34ef56"
MARK = "qa-probe-" + TOKEN
EXPR = "'-'.join(['qa-probe', '" + TOKEN + "'])"


def plan(data: bytes, node: str, **kw):
    """(mutated bytes, detail) of `plan_mutation` for a node of a sample, with the factory's marker token."""
    return PBC.plan_mutation(data, PBC.parse_node(f"tests/sample.py::{node}"), "invert", "IID", marker_token=TOKEN, **kw)


def line_of_text(data: bytes, needle: str) -> int:
    return next(n for n, text in enumerate(data.decode().splitlines(), 1) if needle in text)


def planted(monkeypatch, tmp_path, change):
    """Plant a changed copy of the shipped `forms` as the Python entry: written to a file and read back through `ast_entry`, so a
    planted row passes the one validator, and `probe_by_code` reads it where it reads the shipped one."""
    doc = json.loads(AD.detectors_path().read_text(encoding="utf-8"))
    change(doc[AD.AST_KEY]["python"]["forms"])
    path = tmp_path / "detectors.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    entry = AD.ast_entry(".py", path)
    monkeypatch.setattr(PBC, "_python_entry", lambda: entry)
    return entry[1]["forms"]


def test_unittest_assert_equal_inverted_with_marker():
    """PY-unittest, rename: `assertEqual` becomes `assertNotEqual`, every argument kept, the marker in `msg=` joined at run time,
    the line count and the parse kept; the row id is what the detail names."""
    mutated, detail = plan(UT, "CalcTests::test_multiline")
    assert detail["statement_after"].startswith("self.assertNotIn(1, [1, 2]") and f"msg={EXPR}" in detail["statement_after"], detail
    assert detail["form"] == "PY-unittest" and detail["message_form"] == "PY-unittest" and detail["message_marker"] == MARK
    assert detail["style"] == "assertIn" and detail["head"] == "assertIn" and detail["matcher_at"] == "head"
    assert detail["statement_before"].count("\n") == detail["statement_after"].count("\n") == 3 and mutated.count(b"\n") == UT.count(b"\n")
    assert MARK not in mutated.decode() and EXPR not in detail["statement_inverted"]
    mutated, detail = plan(UT, "CalcTests::test_eq_with_author_msg")
    assert detail["statement_after"] == f"self.assertNotEqual(1 + 1, 2, msg={EXPR})", detail
    assert detail["statement_inverted"] == "self.assertNotEqual(1 + 1, 2)", detail
    assert detail["marker"] == "probe-IID invert: self.assertEqual(1 + 1, 2, \"author words\")", detail


def test_unittest_author_msg_replaced():
    """An author's message is replaced - the third positional of `assertEqual`, and the `msg=` keyword of `assertTrue` - never left
    beside the marker (a second `msg` would be a TypeError with no marker)."""
    for node, before in (("test_eq_with_author_msg", "author words"), ("test_true_keyword_msg", "author kw")):
        _mutated, detail = plan(UT, f"CalcTests::{node}")
        assert before in detail["statement_before"] and before not in detail["statement_after"], detail
        assert detail["statement_after"].count("msg=") == 1 and EXPR in detail["statement_after"], detail
    _mutated, detail = plan(UT, "CalcTests::test_true_keyword_msg")
    assert detail["statement_after"] == f"self.assertFalse(1 == 1, msg={EXPR})", detail


def test_unittest_assert_raises_refused_not_skipped():
    """E7: `self.assertRaises` is a check of a row with `invert: null` and it is the FIRST check: the plan refuses and names the row, the
    two doors and the red sandbox - it never skips to the `assertEqual` after it. `--at` on the later line is the door that works."""
    with pytest.raises(PBC.Refusal) as caught:
        plan(UT, "CalcTests::test_raises_comes_first")
    text = str(caught.value)
    later = line_of_text(UT, "self.assertEqual(1, 1)")
    assert "PY-unittest-none" in text and "`assertRaises`" in text and f"`--at {later}`" in text and "--oracle" in text, text
    assert "first check of" in text and "asked for" not in text, text                 # no --at: the plan took the first
    assert PBC.RED_SANDBOX_DOOR in text and "Nothing was changed" in text, text
    at = line_of_text(UT, "self.assertEqual(1, 1)")
    _mutated, detail = plan(UT, "CalcTests::test_raises_comes_first", at=at)
    assert detail["line"] == at and detail["form"] == "PY-unittest" and detail["target_source"] is None


def test_unittest_rows_exist():
    """t-1968 rule: every method the unittest rows name is a real attribute of `unittest.TestCase` (an inversion to a method that
    does not exist throws at the statement with no marker), the rename map is closed under inversion, and one run of a canned
    sample proves the marker lands in the JUnit message (N0 p5)."""
    forms = {f["id"]: f for f in AD.ast_entry(".py")[1]["forms"]}
    names = forms["PY-unittest"]["invert"]["names"]
    for old, spec in names.items():
        assert hasattr(unittest.TestCase, old) and hasattr(unittest.TestCase, spec["to"]), (old, spec)
        if spec["to"] != "assertNotEqual" or old == "assertEqual":                   # the six equality kinds all invert to assertNotEqual
            assert names[spec["to"]]["to"] == old and names[spec["to"]]["args"] == spec["args"], (old, spec)
    assert all(hasattr(unittest.TestCase, n) for n in forms["PY-unittest-none"]["names"])
    assert not set(names) & set(forms["PY-unittest-none"]["names"])                  # a name belongs to one row
    assert hasattr(unittest.TestCase, "subTest")
    # completeness (t-2122 F3): every `assert*` method of this Python's TestCase is in a row, or in the named list of what is no
    # check; a name a future Python adds is red here, never silently skipped by the plan
    not_a_check = set()
    in_rows = set(names) | set(forms["PY-unittest-none"]["names"]) | set(forms["PY-with-unittest"]["names"])
    every = {n for n in dir(unittest.TestCase) if n.startswith("assert") and callable(getattr(unittest.TestCase, n))}
    assert every - in_rows - not_a_check == set(), sorted(every - in_rows - not_a_check)
    for old in ("assertDictEqual", "assertListEqual", "assertSetEqual", "assertTupleEqual", "assertSequenceEqual", "assertMultiLineEqual"):
        assert names[old] == {"to": "assertNotEqual", "args": 2}, old
    assert all(hasattr(unittest.TestCase, n) for n in forms["PY-with-unittest"]["names"])
    import pytest as _pytest
    assert all(hasattr(_pytest, n) for n in forms["PY-with-pytest"]["names"])


def test_unittest_marker_lands_in_the_junit_message(tmp_path):
    """N0 p5 as a test: the mutated sample is run by pytest and the failure message of the JUnit file holds the joined marker."""
    mutated, _detail = plan(UT, "CalcTests::test_eq_with_author_msg")
    (tmp_path / "test_sample.py").write_bytes(mutated)
    junit = tmp_path / "junit.xml"
    subprocess.run([sys.executable, "-m", "pytest", str(tmp_path / "test_sample.py"), "-q", "-p", "no:cacheprovider",
                    f"--junitxml={junit}", "-k", "test_eq_with_author_msg", f"--rootdir={tmp_path}"],
                   cwd=tmp_path, capture_output=True, timeout=120)
    xml = junit.read_text(encoding="utf-8")
    assert "<failure" in xml and f'message="AssertionError: 2 == 2 : {MARK}"' in xml, xml[:400]


def test_pw_expect_to_inverted_with_marker():
    """PY-pw-expect, chain: `to_be_visible` becomes `not_to_be_visible`, the marker is the `message=` keyword of the head call."""
    _mutated, detail = plan(PW, "test_visible")
    assert detail["statement_after"] == f"expect(page.locator(\"#x\"), message={EXPR}).not_to_be_visible()", detail
    assert detail["statement_inverted"] == "expect(page.locator(\"#x\")).not_to_be_visible()", detail
    assert detail["form"] == "PY-pw-expect" and detail["message_marker"] == MARK and detail["style"] == "expect"
    assert detail["matcher_at"] == "after_args"


def test_pw_expect_not_to_restored():
    """`not_to_be_visible` becomes `to_be_visible` (the first pattern that matches), and the author's `message=` is replaced."""
    mutated, detail = plan(PW, "test_not_restored")
    assert detail["statement_after"] == f"expect(page.locator(\"#x\"), message={EXPR}).to_be_visible()", detail
    assert "author words" not in detail["statement_after"] and "author words" in detail["statement_before"]
    assert mutated.count(b"\n") == PW.count(b"\n")


def test_pw_expect_await_kept():
    """An `await` stays in the mutated text, the second positional of the head (Playwright's message) is replaced, the line
    count is kept; and a multi-line chain keeps its shape between the head and the method."""
    mutated, detail = plan(PW, "test_await_kept")
    assert detail["statement_after"] == f"await expect(page.locator(\"#x\"), message={EXPR}).not_to_have_text(\"hi\")", detail
    assert "second positional" not in detail["statement_after"]
    _mutated, multi = plan(PW, "test_chain_multiline")
    assert multi["statement_after"].count("\n") == multi["statement_before"].count("\n") == 4, multi
    assert ").not_to_have_text(" in multi["statement_after"] and f"message={EXPR}" in multi["statement_after"], multi
    assert mutated.count(b"\n") == PW.count(b"\n")


def test_pw_expect_other_library_not_a_check():
    """`source` must match the file: an `expect` of another library is not a check (no row reads it), and the refusal is the
    no-check one that names the rows; the same text with the Playwright import is a check (the negative control)."""
    other = b"from other import expect\n\n\ndef test_visible(page):\n    expect(page.locator(\"#x\")).to_be_visible()\n"
    assert PBC.check_on_line(other, "tests/sample.py", None, 5)["found"] is None
    assert PBC.check_on_line(PW, "tests/sample.py", None, line_of_text(PW, 'expect(page.locator("#x")).to_be_visible()'))["found"]
    same_shape = other.replace(b"from other import", b"from playwright.sync_api import")
    assert PBC.check_on_line(same_shape, "tests/sample.py", None, 5)["found"]["form"] == "PY-pw-expect"
    with pytest.raises(PBC.Refusal) as caught:
        plan(other, "test_visible")
    assert "PY-pw-expect" in str(caught.value) and "no other check of a form the factory reads" in str(caught.value)


def test_at_on_unittest_line_opens():
    """`--at` on `self.assertEqual`: the door (`check_on_line`) finds the check by its row id and the plan inverts exactly that
    statement - one reader (TR2-1's write check reads the same function); `tc.assertEqual` (a receiver no row lists) is not a check."""
    line = line_of_text(UT, "self.assertEqual(1 + 1, 2")
    facts = PBC.check_on_line(UT, "tests/sample.py", None, line)
    assert facts["found"]["form"] == "PY-unittest" and facts["found"]["line"] == line, facts
    _mutated, detail = plan(UT, "CalcTests::test_eq_with_author_msg", at=line)
    assert detail["line"] == line and detail["form"] == "PY-unittest"
    other = line_of_text(UT, "tc.assertEqual(1, 1)")
    assert PBC.check_on_line(UT, "tests/sample.py", None, other)["found"] is None
    assert PBC.check_on_line(UT, "tests/sample.py", None, other)["nearest_below"]["form"] == "PY-assert"
    with pytest.raises(PBC.Refusal) as caught:
        plan(UT, "CalcTests::test_other_receiver", at=other)
    assert "holds no check of a form the factory reads" in str(caught.value)
    sub = line_of_text(UT, "self.assertLess(n, 3)")                    # a subTest block is walked: the first check inside
    assert plan(UT, "CalcTests::test_inside_subtest")[1]["line"] == sub


def test_unknown_form_refusal_names_the_row_and_red_sandbox(monkeypatch, tmp_path):
    """FR-2: a row that reads a check it cannot invert (a method of its `names` outside its rename map) refuses naming the row, `--at`,
    `--oracle` and the red sandbox - never a guess and never a skip. A body with no check of any row says which rows it tried."""
    def drop_one_rename(forms):
        row = next(f for f in forms if f["id"] == "PY-unittest")
        row["names"] = list(row["invert"]["names"]) + ["assertCustom"]
    planted(monkeypatch, tmp_path, drop_one_rename)
    src = b"import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertCustom(1)\n        assert True\n"
    with pytest.raises(PBC.Refusal) as caught:
        PBC.plan_mutation(src, PBC.parse_node("tests/t.py::T::test_a"), "invert", "IID")
    text = str(caught.value)
    assert "PY-unittest" in text and "`assertCustom`" in text and "`--at 7`" in text and PBC.RED_SANDBOX_DOOR in text, text   # 7: the next check
    with pytest.raises(PBC.Refusal) as caught:
        PBC.plan_mutation(b"def test_n():\n    x = 1\n", PBC.parse_node("tests/t.py::test_n"), "invert", "IID")
    assert "the function body has no assert and no other check" in str(caught.value) and "PY-unittest-none" in str(caught.value)


def test_assert_that_wrap_comes_from_data(monkeypatch, tmp_path):
    """A planted row changes the output: the wrap text of PY-assert_that is data (AR-1). The shipped row gives the `hamcrest` text, the
    planted one gives its own, with the same argument."""
    src = b"def test_h():\n    assert_that(1, equal_to(1), 'why')\n"
    node = PBC.parse_node("tests/t.py::test_h")
    _m, shipped = PBC.plan_mutation(src, node, "invert", "IID")
    assert shipped["statement_after"] == 'assert_that(1, __import__("hamcrest").is_not(equal_to(1)), "probe-IID invert: equal_to(1)")'
    planted(monkeypatch, tmp_path, lambda forms: forms[1]["invert"].update(wrap="negated({arg})"))
    _m, changed = PBC.plan_mutation(src, node, "invert", "IID")
    assert changed["statement_after"] == 'assert_that(1, negated(equal_to(1)), "probe-IID invert: equal_to(1)")', changed
    planted(monkeypatch, tmp_path, lambda forms: forms[1].update(names=["check_that"]))      # the name is data too
    with pytest.raises(PBC.Refusal):
        PBC.plan_mutation(src, node, "invert", "IID")                                            # no row reads `assert_that` now


# --- N2b finishing round (t-2119): the `with` shape, the note of `first`, `places` kept ---------------------------------------

def test_with_raises_is_a_check_and_the_plan_names_it():
    """`with self.assertRaises(E):` is a check of row PY-with-unittest (invert null): read by the door, and the plan - which takes it
    as the FIRST check, never skipping to the `assertEqual` inside or after it - names it as not invertible by code with the doors."""
    header = line_of_text(UT, "with self.assertRaises(ValueError):")
    facts = PBC.check_on_line(UT, "tests/sample.py", None, header)
    assert facts["found"]["form"] == "PY-with-unittest" and facts["found"]["line"] == header == facts["found"]["end_line"], facts
    with pytest.raises(PBC.Refusal) as caught:
        plan(UT, "CalcTests::test_with_raises_comes_first")
    text = str(caught.value)
    assert "PY-with-unittest" in text and "`assertRaises`" in text and f"at line {header}" in text, text
    assert "not invertible by code" in text and "critic" in text and f"`--at {header + 2}`" in text and PBC.RED_SANDBOX_DOOR in text, text
    inner = header + 2                                                                         # a line INSIDE the block is its own check
    assert PBC.check_on_line(UT, "tests/sample.py", None, inner)["found"]["form"] == "PY-unittest"
    _m, detail = plan(UT, "CalcTests::test_with_raises_comes_first", at=inner)
    assert detail["line"] == inner and detail["form"] == "PY-unittest" and detail["statement_after"].startswith("self.assertNotEqual(1, 1")
    with pytest.raises(PBC.Refusal) as at_header:                                              # `--at` on the header names it too
        plan(UT, "CalcTests::test_with_raises_comes_first", at=header)
    assert "PY-with-unittest" in str(at_header.value)
    asked = str(at_header.value)                                                               # t-2122 F1: the asked check is not "first"
    assert f"(the line {header} asked for)" in asked and "first check" not in asked and f"`--at {header + 2}`" in asked, asked


def test_with_nested_and_pytest_raises():
    """A `with` nested in a `subTest` block is walked into (the first check is the inner one) and spans its multi-line HEADER only;
    a `with pytest.raises(E):` is a check of PY-with-pytest, and `with open(...)` is none (negative control)."""
    nested = next(n for n, t in enumerate(UT.decode().splitlines(), 1) if t.strip() == "with self.assertRaises(")
    facts = PBC.check_on_line(UT, "tests/sample.py", None, nested)
    assert facts["found"]["form"] == "PY-with-unittest" and facts["found"]["end_line"] == nested + 2, facts       # the header, 3 lines
    assert PBC.check_on_line(UT, "tests/sample.py", None, nested + 3)["found"] is None                             # the body is not the with's
    with pytest.raises(PBC.Refusal) as caught:
        plan(UT, "CalcTests::test_nested_with")
    assert "PY-with-unittest" in str(caught.value) and f"at line {nested}" in str(caught.value), str(caught.value)
    src = b"import pytest\n\n\ndef test_r():\n    with open('f') as fh:\n        pass\n    with pytest.raises(ValueError):\n        int('x')\n"
    assert PBC.check_on_line(src, "t.py", None, 5)["found"] is None
    assert PBC.check_on_line(src, "t.py", None, 7)["found"]["form"] == "PY-with-pytest"
    with pytest.raises(PBC.Refusal) as pyt:
        PBC.plan_mutation(src, PBC.parse_node("tests/t.py::test_r"), "invert", "IID")
    assert "PY-with-pytest" in str(pyt.value) and "`raises`" in str(pyt.value)


def test_first_writes_a_note_for_calls_no_row_reads():
    """The INV of N2b: a call statement no row reads, standing before the first check a row reads, is NAMED (line and row set) in
    `target_note` - the check taken is still the first row-read one, and `--at` is the door. No such call, no note (control)."""
    _m, detail = plan(UT, "CalcTests::test_unread_call_before_check")
    line = line_of_text(UT, "helper_that_checks(1)")
    note = detail["target_note"]
    assert f"1 call statement(s) before line {line + 1}" in note and f"line {line};" in note and "PY-assert" in note, note
    assert "`assertEqual` at line" in note and "--at <line>" in note and detail["line"] == line + 1, (note, detail)
    _m, plain = plan(UT, "CalcTests::test_eq_with_author_msg")
    assert "target_note" not in plain


def test_almost_equal_places_survives():
    """`assertAlmostEqual(a, b, 3)`: `places` is the third positional and is kept (the row's args is 3), the marker goes in `msg=`;
    the keyword form keeps `places=3`, and a fourth positional (the author's `msg`) is replaced."""
    _m, detail = plan(UT, "CalcTests::test_almost_equal_positional_places")
    assert detail["statement_after"] == f"self.assertNotAlmostEqual(1.0, 1.0, 3, msg={EXPR})", detail
    four = b"import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertAlmostEqual(1.0, 1.0, 3, 'author')\n"
    _m, replaced = PBC.plan_mutation(four, PBC.parse_node("tests/t.py::T::test_a"), "invert", "IID", marker_token=TOKEN)
    assert replaced["statement_after"] == f"self.assertNotAlmostEqual(1.0, 1.0, 3, msg={EXPR})", replaced


# --- N2b third round (t-2122): one not-invertible refusal, with-headers in the note, the equality kinds -----------------------

def test_not_invertible_refusal_is_one_text_on_both_readers():
    """F1: the python rows and the table refuse a check they read but do not invert in ONE text: `--at` says "asked for" and never
    "first"; the door prints the next check's real line; with no next check it says so; the same doors on both readers."""
    py = b"import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertRaises(E, f)\n"
    with pytest.raises(PBC.Refusal) as no_next:
        PBC.plan_mutation(py, PBC.parse_node("tests/t.py::T::test_a"), "invert", "IID", at=6)
    text = str(no_next.value)
    assert "(the line 6 asked for)" in text and "no other check of a form the factory reads follows it" in text, text
    cs = "class T {\n  void Adds() {\n    Assert.Throws<E>(() => Foo());\n    Assert.Equal(4, x);\n  }\n}\n".encode()
    spec = PBC.parse_node("t/T.cs::T.Adds")
    seen = {}
    for label, at in (("first", None), ("asked", 3)):
        with pytest.raises(PBC.Refusal) as caught:
            PBC.plan_detector_mutation(cs, spec, "IID", at, "", "", "t/T.cs")
        seen[label] = str(caught.value)
    assert "the first assertion of 'Adds', `Assert.Throws` at line 3" in seen["first"] and "asked for" not in seen["first"], seen
    assert "(the line 3 asked for)" in seen["asked"] and "first assertion" not in seen["asked"], seen
    for text in seen.values():
        assert "`--at 4`" in text and "never skips to a later assertion" in text and PBC.RED_SANDBOX_DOOR in text, text
        assert "not invertible by code" in text and "--oracle" in text, text


def test_skipped_calls_see_with_headers():
    """F2: `from pytest import raises` + `with raises(E):` is a with-header of a call no row reads (the row needs the receiver
    `pytest`): the note names ITS line, not the body's; a with whose header is no call is not listed (control)."""
    src = (b"from pytest import raises\n\n\ndef test_r():\n    x = 1\n    with raises(ValueError):\n        int('x')\n    assert 1 == 1\n")
    _m, detail = PBC.plan_mutation(src, PBC.parse_node("tests/t.py::test_r"), "invert", "IID")
    assert detail["line"] == 8 and "line 6, 7;" in detail["target_note"], detail["target_note"]     # the with (6) AND its body's call (7)
    plain = b"def test_r():\n    with lock:\n        pass\n    assert 1 == 1\n"
    assert "target_note" not in PBC.plan_mutation(plain, PBC.parse_node("tests/t.py::test_r"), "invert", "IID")[1]


def test_equality_kinds_invert_to_assert_not_equal():
    """F3: the six equality kinds are read and inverted to `assertNotEqual` with their two arguments (a keyword such as `seq_type` is
    kept); a callable `assertWarnsRegex` is the first check, refused, not skipped."""
    for name in ("assertDictEqual", "assertListEqual", "assertSetEqual", "assertTupleEqual", "assertSequenceEqual", "assertMultiLineEqual"):
        src = f"import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.{name}(a, b)\n".encode()
        _m, detail = PBC.plan_mutation(src, PBC.parse_node("tests/t.py::T::test_a"), "invert", "IID", marker_token=TOKEN)
        assert detail["statement_after"] == f"self.assertNotEqual(a, b, msg={EXPR})" and detail["form"] == "PY-unittest", (name, detail)
    src = b"import unittest\n\n\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.assertWarnsRegex(W, 'x', f)\n        self.assertEqual(1, 1)\n"
    with pytest.raises(PBC.Refusal) as caught:
        PBC.plan_mutation(src, PBC.parse_node("tests/t.py::T::test_a"), "invert", "IID")
    assert "PY-unittest-none" in str(caught.value) and "`assertWarnsRegex`" in str(caught.value) and "`--at 7`" in str(caught.value)


# --- N3a (t-2127): one binding keyed by the contract's shape, one site gate, `_row_status` -----------------------------------

N3_MARK = "qa-probe-n3a"
N3_ARGV = ["python", "-m", "pytest", "tests"]


def road(monkeypatch, rows, *, contract=None, node="tests/t.py::test_x", reporter="junit-xml", argv=N3_ARGV, keys=("adds",),
         report_read=True, real=False, marker=N3_MARK):
    """`_judge_rows` for the test `node` over raw `rows`: (record, the `among` values the judge saw, the (reporter, pytest_command) the
    frame reader was asked with). Unless `real`, the row judge is replaced by the row's own `v` (its table is tested elsewhere)."""
    spec = dict(PBC.parse_node("src/sum.test.ts::adds"), node=node)
    detail = {"language": "typescript", "candidates": [3], "at": None, "line": 3, "end_line": 5, "message_marker": marker, "fires_as": None,
              "pair": "p"}
    record = {"task": "T", "notes": [], "expected_location": "tests/t.py:3", "expected_reason": "m", "verdict": "not_executed"}
    request = {"instance_contracts": {"adds": contract} if contract is not None else {}}
    if argv is not None:
        request["command"] = {"argv": list(argv)}
    judged, asked = [], []

    def stub(row, site, entry, detail_, *, among, argv):
        judged.append(row["test_id"])
        return {"verdict": row["v"], "actual_location": None, "actual_reason": None, "mismatches": [], "note": "",
                "observed": {"status": row["status"]}}

    def site(row, reporter_, root, test_file, **kw):
        asked.append((reporter_, kw["pytest_command"]))
        return {}
    if not real:
        monkeypatch.setattr(PBC, "judge_probe_row", stub)
    monkeypatch.setattr(PBC.reporters, "assertion_site", site)
    PBC._judge_rows(Path("."), record, rows, reporter, spec, detail, request, Path("x"), list(keys), report_read)
    return record, judged, asked


def n3_row(name, status, v, **extra):
    return dict({"test_id": f"tests.t::{name}", "status": status, "v": v, "problems": []}, **extra)


def test_no_file_contract_binds_param_rows(monkeypatch):
    """B2: a pytest contract carries no `file`: the row of a plugin-parametrised test (`test_x[chromium]`) is the node's, through the
    one matcher. Adversarial: `[chromium]` is the plugin row of a node with no parameter; a node WITH `[webkit]` never takes `[firefox]`."""
    contract = {"report_test_id": "tests/t.py::test_x"}
    record, judged, _ = road(monkeypatch, [n3_row("test_x[chromium]", "failed", "intended_failure"), n3_row("test_y", "failed", "no_failure")],
                             contract=contract)
    assert judged == ["tests.t::test_x[chromium]"] and record["verdict"] == "intended_failure", (record, judged)
    assert "cause" not in record
    assert record["matched_report_id"] == "tests.t::test_x[chromium]", record      # K2: the one row matched by another tail
    record, judged, _ = road(monkeypatch, [n3_row("test_x", "failed", "intended_failure"), n3_row("test_x[chromium]", "failed", "no_failure")],
                             contract=contract)
    assert judged == ["tests.t::test_x"] and record["verdict"] == "intended_failure", (record, judged)    # the exact id wins
    assert "matched_report_id" not in record, record      # control: the row of the node's own tail writes none
    record, judged, _ = road(monkeypatch, [n3_row("test_x[firefox]", "failed", "intended_failure")], contract=contract, node="tests/t.py::test_x[webkit]")
    assert judged == [] and record["cause"] == "tooling", (record, judged)    # `func[webkit]` never matches `func[firefox]`


def test_no_file_contract_two_classes_one_tail_is_tooling_gap(monkeypatch):
    """F1: the tail `test_save` in two classes: which test ran cannot be told, so it is a tooling gap, never a verdict (not the
    judged `no_failure` of the other class's row). Control: two plugin rows of ONE class are still both judged."""
    marker_row = {"test_id": "tests.test_a.TestA::test_save", "status": "failed", "v": "intended_failure", "problems": []}
    other = {"test_id": "tests.test_b.TestB::test_save", "status": "passed", "v": "no_failure", "problems": []}
    record, judged, _ = road(monkeypatch, [marker_row, other], contract={"report_test_id": "tests.test_a.TestA::test_save"},
                             node="tests/test_a.py::TestA::test_save")
    assert judged == [] and record["cause"] == "tooling" and record["verdict"] == "not_executed", (record, judged)
    assert "cannot be told" in " ".join(record["notes"]), record["notes"]
    record, judged, _ = road(monkeypatch, [n3_row("test_save[a]", "failed", "intended_failure"), n3_row("test_save[b]", "failed", "intended_failure")],
                             node="tests/t.py::test_save")
    assert len(judged) == 2 and "cause" not in record, (record, judged)


def test_no_file_contract_two_rows_all_judged(monkeypatch):
    """E-D: two plugin rows `[a]`, `[b]` are BOTH judged; the survivor speaks and is named (a row is never picked silently). No contract
    at all binds the same way (the no-contract world)."""
    rows = [n3_row("test_x[a]", "failed", "intended_failure"), n3_row("test_x[b]", "passed", "no_failure")]
    for contract in ({"report_test_id": "tests/t.py::test_x"}, None):
        record, judged, _ = road(monkeypatch, rows, contract=contract)
        assert judged == ["tests.t::test_x[a]", "tests.t::test_x[b]"], judged
        assert record["verdict"] == "no_failure" and [r["verdict"] for r in record["param_rows"]] == ["intended_failure", "no_failure"], record
        assert "test_x[b]" in " ".join(record["notes"]), record["notes"]


def test_table_reporter_with_file_less_contract(monkeypatch):
    """The adversarial pin of the spec: a contract with no file on a table reporter (`junit-xml`, a non-pytest launcher) is bound by the
    one matcher as well; a contract WITH a file still goes through `selection_rows` (control: its row, not the node's)."""
    record, judged, asked = road(monkeypatch, [n3_row("test_x[chromium]", "failed", "intended_failure")],
                                 contract={"report_test_id": "tests.t::test_x"}, argv=["npx", "playwright", "test"])
    assert judged == ["tests.t::test_x[chromium]"] and asked == [("junit-xml", False)], (judged, asked)
    own = {"file": "tests/t.py", "report_test_id": "tests.t::test_other"}
    _r, judged, _a = road(monkeypatch, [n3_row("test_x[chromium]", "failed", "intended_failure"), n3_row("test_other", "failed", "no_failure")],
                          contract=own)
    assert judged == ["tests.t::test_other"], judged


def test_no_match_is_tooling_gap_with_held_ids(monkeypatch):
    """A report that held rows, none of them the node: `cause: tooling`, the note names what the report held. A report with no rows
    says so and writes no cause (the stand did not run the suite: nothing is said about the tool)."""
    record, judged, _ = road(monkeypatch, [n3_row("test_a", "passed", "no_failure"), n3_row("test_b", "passed", "no_failure")],
                             contract={"report_test_id": "tests/t.py::test_x"})
    assert judged == [] and record["cause"] == "tooling" and record["language"] == "typescript", record
    note = " ".join(record["notes"])
    assert "tests.t::test_a" in note and "tests.t::test_b" in note and "test_x" in note, note
    record, _j, _a = road(monkeypatch, [], contract={"report_test_id": "tests/t.py::test_x"})
    assert "cause" not in record and "no rows" in " ".join(record["notes"]), record
    record, _j, _a = road(monkeypatch, [n3_row("test_a", "passed", "no_failure")], report_read=False)
    assert "cause" not in record, record      # a report that was not read is no fact about the tool


def test_reporter_pytest_reaches_site_reader(monkeypatch):
    """B3: `reporter: pytest` (the default of a pytest profile) is a reader: the frame reader is asked, with the pytest command read
    from the argv once. Control: an argv with no command asks it with False."""
    _r, _j, asked = road(monkeypatch, [n3_row("test_x", "failed", "intended_failure")], reporter="pytest")
    assert asked == [("pytest", True)], asked
    _r, _j, asked = road(monkeypatch, [n3_row("test_x", "failed", "intended_failure")], reporter="trx", argv=["dotnet", "test"])
    assert asked == [("trx", False)], asked


def test_reporter_unknown_site_unread(monkeypatch):
    """B3 (N4): a reporter no reader knows stays `site_unread`, and the frame reader is NOT asked. A row WITH text is the critic's (the place
    is a fact he reads himself, never a verdict - FR-59); a row with NO text is `incomplete`, a tooling gap."""
    failed = n3_row("test_x", "failed", "-", problems=[{"kind": "failure", "message": "boom", "text": "boom"}])
    record, _j, asked = road(monkeypatch, [failed], reporter="mystery", real=True)
    assert asked == [] and record["verdict"] == "incomplete" and record["cause"] == "judgment", (record, asked)
    assert record["observed"]["site_unread"] == "mystery/typescript", record["observed"]
    assert record["judgment_facts"]["failure_text"] == "boom" and record["judgment_facts"]["location"] is None
    quiet = n3_row("test_x", "failed", "-", problems=[{"kind": "failure", "message": "", "text": ""}])
    record, _j, asked = road(monkeypatch, [quiet], reporter="mystery", real=True)
    assert asked == [] and record["verdict"] == "incomplete" and record["cause"] == "tooling" and "judgment_facts" not in record, record


def test_pytest_command_from_argv():
    """E-D: `is_pytest_command(None)` is false and never raises; empty and non-pytest launches are false; a pytest launch is true. The
    road reads it from `request.command.argv`; a request with no command is the same world as no argv."""
    import execution_request as ER
    assert ER.is_pytest_command(None) is False and ER.is_pytest_command([]) is False
    assert ER.is_pytest_command(["npx", "playwright", "test"]) is False and ER.is_pytest_command(["python", "-m", "pytest"]) is True


def test_argv_absent_does_not_raise(monkeypatch):
    _r, _j, asked = road(monkeypatch, [n3_row("test_x", "failed", "intended_failure")], argv=None)
    assert asked == [("junit-xml", False)], asked


def test_empty_keys_tolerated(monkeypatch):
    """`keys` empty: no `keys[0]` on an empty list; a no-file world binds by the node."""
    record, judged, _ = road(monkeypatch, [n3_row("test_x[chromium]", "failed", "intended_failure")], keys=())
    assert judged == ["tests.t::test_x[chromium]"] and record["verdict"] == "intended_failure", record
    record, judged, _ = road(monkeypatch, [n3_row("test_z", "failed", "intended_failure")], keys=())
    assert judged == [] and record["cause"] == "tooling", record


def test_failure_beside_skip_is_failed(monkeypatch):
    """E-P: a raw row whose `status` is `skipped` (a `<skipped>` child outranks the failure in the shared reader) but which holds a
    failure with the probe's marker is judged `failed`: `intended_failure`, proved by the marker. A skip alone stays `not_executed`
    (control), an error beside a skip is `error` (incomplete), and `_row_status` answers the row's own status when no problem speaks."""
    failure = {"kind": "failure", "message": f"Error: {N3_MARK} step", "text": f"Error: {N3_MARK} step"}
    beside = n3_row("test_x", "skipped", "-", problems=[{"kind": "skipped", "message": "", "text": ""}, failure])
    record, _j, _a = road(monkeypatch, [beside], real=True)
    assert record["verdict"] == "intended_failure" and record["proved_by"] == "marker", record
    alone = n3_row("test_x", "skipped", "-", problems=[{"kind": "skipped", "message": "", "text": ""}])
    record, _j, _a = road(monkeypatch, [alone], real=True)
    assert record["verdict"] == "not_executed", record
    assert PBC._row_status(n3_row("test_x", "skipped", "-", problems=[{"kind": "skipped"}, {"kind": "error", "message": "e"}])) == "error"
    assert PBC._row_status(alone) == "skipped" and PBC._row_status({"status": "passed"}) == "passed"
    assert PBC._row_status(beside) == "failed"


# --- N3b (t-2132): ONE row judge - the marker, or passed, or the role - for every language -----------------------------------
# "Only our text proves without a role" (the owner's word): `intended_failure` by code exists only on a read token. Rows are canned
# in the shape each runner prints (a thrown error, a matcher's failure, a rejected promise, a `toPass` callback, a foreign
# `AssertionError`); none of them holds the token, so none proves, wherever it fell and whatever its wording says.

TOK = "qa-probe-n3b000000001"
ARGV = {"python": ["python", "-m", "pytest", "tests"], "typescript": ["npx", "playwright", "test"],
        "csharp": ["dotnet", "test"], "java": ["mvn", "test"]}
N0_ROWS = json.loads((Path(__file__).resolve().parent / "fixtures" / "probe-languages" / "pytest-n0-rows.json").read_text(encoding="utf-8"))


def n0(name: str) -> dict:
    """A row of the N0 report's pytest run (t-2045), as the reader gives it: `{status, problems}`; real output, not hand-shaped."""
    row = N0_ROWS["rows"][name]
    return {"status": row["status"], "problems": [dict(p) for p in row["problems"]]}


# Which rows stay hand-shaped, and why: the Python ones below are N0's real pytest output (p2, p3). N0 holds no C# or Java run, and for
# Playwright only the first lines of e1 (used for the `resolves` row); the other TypeScript rows, and every C# / Java row, are shaped
# by hand after the runner's printed form until a run of that runner is recorded under fixtures/probe-languages.
THROWS = {      # (what, message, text above the first frame) as the language's runner prints it; no token in any
    "python": [("a throw at the statement (N0 p3)", n0("p3")["problems"][0]["message"], n0("p3")["problems"][0]["text"]),
               ("a foreign AssertionError from a helper (N0 p2)", n0("p2")["problems"][0]["message"], n0("p2")["problems"][0]["text"])],
    "typescript": [("a throw in the first argument", "Error: boom", "Error: boom\n  at tests/calc.spec.ts:7:9"),
                   ("a throw in the matcher's argument", "Error: bad", "Error: bad\n  at tests/calc.spec.ts:7:9"),
                   ("a rejected promise that resolves (N0 e1, its first lines)", "Error: expect(received).resolves.toBe()",
                    "Error: expect(received).resolves.toBe()\n    Received promise rejected instead of resolved"),
                   ("a toPass callback", "Error: expect(received).toBe(expected)", "Error: expect(received).toBe(expected)\n  Timeout 5000ms exceeded while waiting on toPass")],
    "csharp": [("a throw at the statement", "System.InvalidOperationException : boom", "System.InvalidOperationException : boom"),
               ("a matcher's own failure wording", "Assert.NotEqual() Failure: Values are equal", "Assert.NotEqual() Failure: Values are equal")],
    "java": [("a throw at the statement", "java.lang.IllegalStateException: boom", "java.lang.IllegalStateException: boom"),
             ("a matcher's own failure wording", "expected: not <2> but was: <2>", "org.opentest4j.AssertionFailedError: expected: not <2> but was: <2>")],
}


def failed(message="", text="", status="failed", kind="failure"):
    return {"status": status, "problems": [{"kind": kind, "message": message, "text": text}] if status != "passed" else []}


class Judged:
    """`judge_probe_row` for one language over the REAL plan of the fixture: the detail carries a token, the site is inside the statement."""

    def __init__(self, w):
        self.w = w
        target = w.target(at=w.line("@THEN"))
        _text, plan_detail = w.plan(target)
        self.detail = dict(plan_detail, message_marker=TOK)
        self.entry = w.spec["entry"]
        self.inside = {"location": f"{w.rel}:{self.detail['line']}", "failure_kind": "assertion", "frame": "at x"}
        self.away = {"location": f"{w.rel}:1", "failure_kind": "exception", "frame": "at y"}

    def __call__(self, row, site=None, detail=None, among=False):
        return PBC.judge_probe_row(row, self.inside if site is None else site, self.entry, detail or self.detail, among=among,
                                   argv=ARGV[self.w.language])


@pytest.fixture
def judged(world):
    return Judged(world())


def test_marker_outranks_place(judged):
    got = judged(failed(f"{TOK} x", "boom"), judged.away)
    assert (got["verdict"], got["proved_by"]) == ("intended_failure", "marker"), got
    control = judged(failed("x", "boom"), judged.inside)
    assert (control["verdict"], control["cause"]) == ("incomplete", "judgment") and "proved_by" not in control, control


def test_passed_row_never_proved(judged):
    for row in (failed(status="passed"), dict(failed(status="passed"), system_out=TOK, problems=[])):
        got = judged(row)
        assert got["verdict"] in ("no_failure", "incomplete") and "proved_by" not in got, got
    held = judged({"test_id": "x", "status": "passed", "problems": [{"kind": "failure", "message": TOK, "text": TOK}]})   # E-P: it holds a failure, so it is `failed`: the control
    assert held["verdict"] == "intended_failure", held


def test_only_marker_proves(judged):
    """A token written into the plan and not read in the text, a `fires_as` that WOULD match the text, and a message-less row."""
    fires_as = judged.detail["fires_as"]
    texts = ["boom"] + ([fires_as.lstrip("^")] if fires_as else [])
    for message, text in (("", t) for t in texts):      # message-less rows
        got = judged(failed(message, text), detail=dict(judged.detail, fires_as=fires_as))
        assert (got["verdict"], got["cause"]) == ("incomplete", "judgment") and "proved_by" not in got, (message, text, got)
    got = judged(failed("x", "y"), detail=dict(judged.detail, fires_as=None))     # a null `fires_as`: no crash
    assert got["verdict"] == "incomplete", got
    got = judged(failed(f"{TOK} x", ""), detail=dict(judged.detail, fires_as=None))
    assert (got["verdict"], got["proved_by"], got["note"]) == ("intended_failure", "marker", ""), got


def test_wrong_place_with_text_is_judgment(judged):
    got = judged(failed("x", "some text"), judged.away)
    assert (got["verdict"], got["cause"]) == ("incomplete", "judgment") and got["actual_location"] is None, got
    facts = PBC.judgment_facts({}, failed("x", "some text"), judged.away, judged.detail, judged.entry)
    assert facts["location_hit"] is False and judged.w.rel in facts["location"]


def test_failed_no_text_is_tooling_cause(judged):
    got = judged(failed("", ""))
    assert got["verdict"] == "incomplete" and "cause" not in got, got      # the caller writes `cause: tooling`


def test_error_row_goes_to_the_critic(judged):
    """par.12 (b), F12 = A (t-2143 N4): an `error` row with text is `incomplete`, `cause: judgment` on every language - the critic judges
    it, one judgment each; a token on an error row proves nothing; an error row with no text stays the tool's gap."""
    got = judged(failed("boom", "boom", status="error", kind="error"))
    assert (got["verdict"], got["cause"]) == ("incomplete", "judgment") and "proved_by" not in got, got
    got = judged(failed(f"{TOK}", f"{TOK}", status="error", kind="error"))      # a token on an error row is not decided here (F12=A)
    assert (got["verdict"], got["cause"]) == ("incomplete", "judgment") and "proved_by" not in got, got
    got = judged(failed("", "", status="error", kind="error"))
    assert got["verdict"] == "incomplete" and "cause" not in got, got


def test_unknown_status_not_executed(judged):
    for status in ("skipped", "not_run", "weird"):
        got = judged({"test_id": "x", "status": status, "problems": []})
        assert got["verdict"] == "not_executed", (status, got)


def test_no_rows_not_executed(monkeypatch):
    record, judged_ids, _asked = road(monkeypatch, [], contract={"report_test_id": "tests/t.py::test_x"}, real=True)
    assert record["verdict"] == "not_executed" and judged_ids == [] and "cause" not in record, record


def test_throws_never_proved_by_code(judged):
    """A throw in the first argument, in the matcher's argument, a rejected promise, a `toPass` callback, a foreign `AssertionError`:
    at the statement's own line, none proves; the critic judges (the same on each language)."""
    for what, message, text in THROWS[judged.w.language]:
        got = judged(failed(message, text), judged.inside)
        assert got["verdict"] == "incomplete" and got["cause"] == "judgment" and "proved_by" not in got, (what, got)


def test_throw_at_statement_same_on_each_language(judged):
    """The fixture is parametrised over the four languages: the same throw at the mutated statement gets the same answer on each."""
    what, message, text = next(row for row in THROWS[judged.w.language] if "throw" in row[0])
    got = judged(failed(message, text), judged.inside)
    assert (got["verdict"], got["cause"], "proved_by" in got) == ("incomplete", "judgment", False), (judged.w.language, what, got)


def test_all_rows_or_not_proved(monkeypatch):
    marked = failed(f"{TOK} x", "boom")
    plain = failed("x", "boom")
    for rows, verdict, proved in (([marked, marked], "intended_failure", "marker"), ([marked, plain], "incomplete", None),
                                  ([plain, marked], "incomplete", None)):
        probe_rows = [{"test_id": f"tests.t::test_x[{i}]", **row} for i, row in enumerate(rows)]
        record = real_road(monkeypatch, probe_rows)
        assert record["verdict"] == verdict and record.get("proved_by") == proved, (verdict, record)
    # the aggregator alone: intended only when every row is, and then `marker`
    probe: dict = {"notes": []}
    PBC._worst_of_rows([({"test_id": "a[1]"}, {"verdict": "intended_failure", "proved_by": "marker"}),
                        ({"test_id": "a[2]"}, {"verdict": "incomplete", "cause": "judgment"})], {"node": "t.py::a"}, probe)
    assert probe["verdict"] == "incomplete" and "proved_by" not in probe, probe


def real_road(monkeypatch, rows, *, detail=None, spec_node="tests/t.py::test_x", reporter="junit-xml"):
    """`_judge_rows` with the REAL row judge over python `rows` (a pytest launch, a site inside the statement); returns the record."""
    spec = PBC.parse_node(spec_node)
    det = dict({"language": "python", "candidates": [], "line": 3, "end_line": 5, "message_marker": TOK, "fires_as": None, "pair": None,
                "target_source": None, "target_outside_body": False, "file": "tests/t.py"}, **(detail or {}))
    record = {"task": "T", "notes": [], "expected_location": "tests/t.py:3", "expected_reason": "m", "verdict": "not_executed"}
    monkeypatch.setattr(PBC.reporters, "assertion_site", lambda row, *a, **k: {"location": "tests/t.py:4", "failure_kind": "assertion", "frame": "t.py:4"})
    PBC._judge_rows(Path("."), record, rows, reporter, spec, det, {"command": {"argv": ARGV["python"]}, "instance_contracts": {}}, Path("x"), ["x"], True)
    return record


def test_python_param_rows_all_judged(monkeypatch):
    rows = [{"test_id": "tests.t::test_x[a]", **failed(f"{TOK}")}, {"test_id": "tests.t::test_x[b]", **failed("other")}]
    record = real_road(monkeypatch, rows)
    assert [r["verdict"] for r in record["param_rows"]] == ["intended_failure", "incomplete"], record
    assert record["verdict"] == "incomplete" and record["cause"] == "judgment" and record["language"] == "python", record


def test_stale_id_pass_is_incomplete_not_no_failure(monkeypatch):
    """E-O: a pass of a check chosen by `--at` / the manifest's id that lies outside the located body (a stale id), or whose body is
    not located (`None` reads as outside), is `incomplete`, `cause: tooling` - never `no_failure`."""
    passed = [{"test_id": "tests.t::test_x", **failed(status="passed")}]
    for source in ("assertion_id", "at"):
        for outside in (True, None):
            record = real_road(monkeypatch, passed, detail={"target_source": source, "target_outside_body": outside})
            assert (record["verdict"], record["cause"]) == ("incomplete", "tooling"), (source, outside, record)
    assert "does not say which body ran" in " ".join(record["notes"]) and "tests.t::test_x" in " ".join(record["notes"])


def test_helper_never_called_pass_is_incomplete(monkeypatch):
    passed = [{"test_id": "tests.t::test_x", **failed(status="passed")}]
    record = real_road(monkeypatch, passed, detail={"target_source": "at", "target_outside_body": True, "candidates": []})
    assert record["verdict"] == "incomplete", record
    record = real_road(monkeypatch, passed, detail={"target_source": "at", "target_outside_body": False, "candidates": [2, 9]})
    assert record["verdict"] == "incomplete", record       # several declarations of the name: which body ran is not told


def test_oracle_pass_still_no_failure(monkeypatch):
    passed = [{"test_id": "tests.t::test_x", **failed(status="passed")}]
    for source in ("oracle", "first"):
        record = real_road(monkeypatch, passed, detail={"target_source": source, "target_outside_body": True})
        assert record["verdict"] == "no_failure" and "cause" not in record, (source, record)
    record = real_road(monkeypatch, passed, detail={"target_source": "at", "target_outside_body": False})
    assert record["verdict"] == "no_failure", record      # control: the check is in the located body, one declaration


def test_old_record_fires_as_reads():
    """An old record's `proved_by: fires_as` reads as it did: `_receipt_core` carries it unread, and no third value is written."""
    record = {"mutation": "invert", "expected_reason": "m", "actual_reason": "m", "expected_location": "t.py:3", "failure_kind": "assertion",
              "record": "work/probes/i.json", "verdict": "intended_failure", "proved_by": "fires_as"}
    facts = {k: "x" for k in PBC.FACT_KEYS}
    assert PBC._receipt_core(record, "i", facts, "restored")["proved_by"] == "fires_as"


def test_critic_proved_by_keeps_quote():
    record = {"mutation": "invert", "expected_reason": "m", "actual_reason": "m", "expected_location": "t.py:3", "failure_kind": "assertion",
              "record": "work/probes/i.json", "verdict": "intended_failure", "proved_by": "critic", "judgment": {"quote": "the line"}}
    core = PBC._receipt_core(record, "i", {k: "x" for k in PBC.FACT_KEYS}, "restored")
    assert (core["proved_by"], core["judgment_quote"]) == ("critic", "the line")
    assert "judgment_quote" not in PBC._receipt_core(dict(record, proved_by="marker"), "i", {k: "x" for k in PBC.FACT_KEYS}, "restored")


# --- B1 of t-2138: WHERE the token may be read is the runner's data (`marker_read`) ------------------------------------------

N0_TOKEN = N0_ROWS["token"]


def n0_judge(name: str, entry=None, site=None) -> dict:
    """`judge_probe_row` over an N0 pytest row with the REAL python entry: the plan's token is N0's `qa-probe-tok`."""
    entry = entry or AD.ast_entry(".py")[1]
    detail = {"language": "python", "line": 3, "end_line": 5, "message_marker": N0_TOKEN, "fires_as": None, "pair": None}
    site = site if site is not None else N0_ROWS["sites"].get(name, {})
    return PBC.judge_probe_row(n0(name), site, entry, detail, among=False, argv=ARGV["python"])


def test_pytest_argument_echo_is_not_a_firing():
    """N0 p6 (a ValueError thrown in the callee, after the message was built): pytest prints the argument values of the frame, so the
    token sits in the TEXT as `message = 'qa-probe-tok'` and not in the message - judgment, never `intended_failure`."""
    row = n0("p6")
    assert N0_TOKEN in row["problems"][0]["text"] and N0_TOKEN not in row["problems"][0]["message"]      # the premise, from the real row
    got = n0_judge("p6")
    assert (got["verdict"], got["cause"]) == ("incomplete", "judgment") and "proved_by" not in got, got
    # the control: a real firing (N0 p1 a plain assert, p5 a unittest msg=) holds the token in the message and is proved
    for name in ("p1", "p5"):
        got = n0_judge(name)
        assert (got["verdict"], got["proved_by"]) == ("intended_failure", "marker"), (name, got)
    # the other N0 rows hold no token at all: judgment (a failed row) and never a proof
    for name in ("p2", "p3"):
        got = n0_judge(name, site=N0_ROWS["sites"]["p1"])
        assert (got["verdict"], got["cause"]) == ("incomplete", "judgment") and "proved_by" not in got, (name, got)


def test_marker_read_is_the_entrys_data(judged):
    """A token only in the failure TEXT proves where the entry says `text` and does not where it says `message` only: the same code,
    the data decides (no language branch). The shipped data pins: pytest reads the message; the table languages read both."""
    expected = {"python": ["message"], "typescript": ["message", "text"], "csharp": ["message", "text"], "java": ["message", "text"]}
    assert AD.marker_read(judged.entry) == expected[judged.w.language]
    got = judged(failed("x", f"first line\n{TOK}"), judged.inside, detail=dict(judged.detail, fires_as=None))
    proved = "text" in expected[judged.w.language]
    assert (got["verdict"] == "intended_failure") is proved, (judged.w.language, got)
    narrowed = dict(judged.entry, marker_read=["message"])
    widened = dict(judged.entry, marker_read=["message", "text"])
    row = failed("x", f"first line\n{TOK}")
    detail = dict(judged.detail, fires_as=None)
    call = lambda entry: PBC.judge_probe_row(row, judged.inside, entry, detail, among=False, argv=ARGV[judged.w.language])["verdict"]
    assert (call(narrowed), call(widened)) == ("incomplete", "intended_failure")


def test_marker_read_default_and_validation(tmp_path):
    """Absent, empty or unreadable reads as the narrow default; the loader refuses a word that is not a report-row field."""
    for entry in ({}, {"marker_read": []}, {"marker_read": ["stdout"]}, {"marker_read": "message"}, None):
        assert AD.marker_read(entry) == ["message"], entry
    assert AD.marker_read({"marker_read": ["message", "text"]}) == ["message", "text"]
    import copy
    doc = json.loads(AD.detectors_path().read_text(encoding="utf-8"))
    for bad in (["stdout"], [], ["text", "text"], "text"):
        broken = copy.deepcopy(doc)
        broken["assertion_probes_ast"]["python"]["marker_read"] = bad
        scratch = tmp_path / "detectors.json"       # a copy: the loader reads any path it is given
        scratch.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(AD.DetectorEntryMalformed):
            AD.ast_entry(".py", scratch)


def test_frames_fact_reads_the_site_readers_walk():
    """F4: `frames` of the facts is `reporters.frame_lines`, the walk the site reader takes its frame from: a project frame is kept,
    a `skip_frames` line is dropped, and a line that names no path is no frame. Real Playwright text (the LOCAL-1 report)."""
    import xml.etree.ElementTree as ET
    junit = SAMPLES / "playwright-red-probe.junit.xml"
    text = next(ET.parse(junit).getroot().iter("failure")).text
    entry = AD.assertion_detectors()["typescript"]
    own = [line.strip() for line in text.splitlines() if "add-to-cart.spec.ts:109:84" in line]
    assert own, "the premise: the real text holds the project frame (twice: the first run and `Retry #1`)"
    framed = PBC._frames_of(text, entry)
    assert framed == own, framed
    library = "      at Object.toBe (/x/node_modules/expect/build/index.js:1:1)"
    assert library.strip() not in PBC._frames_of(text + "\n" + library, entry)
    assert PBC._frames_of("no frame here", entry) == [] and PBC._frames_of(text, None) == []
    import reporters
    assert reporters.frame_lines(text, *AD.grammar_of(entry)[:2]) == framed


# --- the static guard: the road after the plan asks no language question ---------------------------------------------------

ROAD = ("_target_of", "_plan", "judge_probe_row", "_row_by_marker", "_row_passed", "_row_unsettled", "_row_answer", "_judge_rows",
        "_judge_run", "_probe", "_resolve_oracle", "plan_detector_mutation", "build_request", "_off_target_note", "_refuse_flags",
        "_new_record", "_finish_record", "find_oracle", "pick_hop", "checks_of", "run_plan",
        # t-2064 P3: the model on every reader; they ask no language question (`plan_model` and `_model_region` hand the reader's own
        # answer on, as `checks_of` does)
        "plan_model", "_model_region", "_edit_shape", "_assert_with_marker", "_assert_that_with_marker", "_models_refusal", "load_models",
        # t-2064 P4a part 2: the joint judge reads rows, tokens and the entry's data; it asks no language question
        "_problem_texts", "_cut_by_runner", "_judge_joint_rows",
        "_earlier_check_at",
        # t-2064 P4a part 3: the walk reads the plan, the entries and the report rows; the flags and the cut words are the entry's data
        "_entry_sha", "_check_proved", "_walk_plan", "_walk_attempt", "_walk_run_once", "_walk_target", "_walk_record", "_walk_stamp",
        "_walk_clock")
# Named exceptions: (function, what, why). `_reader_plan`, `parse_node`, `_reader_entry`, `_is_table`, `put_back` and the F8 functions
# (`_probe_alternative` and what it calls) are OFF the list, each for its own reason: they ARE the reader's selection, the parse of the
# node, or the alternative probe's own road (P5 merges it); so are P3's `_located`, `_region_of`, `_body_of`, `_model_edit` and
# `_marked_statement`, which read the located check's `reader` once to place an edit or a marker (the reader's selection, like
# `_reader_plan`). P2-P4b extend ROAD by their functions.
ROAD_EXCEPTIONS = {
    ("build_request", "reader", "the runner's selection by node id (t-2045 §3 #10): a table test is built for the whole case"),
    ("_probe", "reader", "builds `ProbeCtx.detector`, the reader selection the plan's run-shape checks read (once, at the one place)"),
    ("_plan", "detector", "the table's whole-case run-shape checks (R6) run only for a table test: a runner's selection like `build_request`'s, until P5 (F8)"),
    ("find_oracle", "language", "reader dispatch: the spec's language is only the hop's label; the AST road returns to `plan_mutation`'s refusal, the table refuses here (until P5)"),
    ("_judge_rows", "is_pytest_command", "a runner's report grammar (is it pytest's), not a language"),
    ("_walk_run_once", "is_pytest_command", "a runner's report grammar (is it pytest's), not a language: the same read as `_judge_rows`"),
    ("_judge_run", "judge_row", "not a language: the alternative probe injects its row judge (until P5)"),
}


def road_findings(source: str, names=ROAD) -> set:
    """{(function, what)}: every language question the AST of these functions asks."""
    import ast
    tree = ast.parse(source)
    found = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in names:
            continue
        doc = node.body[0].value if node.body and isinstance(node.body[0], ast.Expr) else None
        for sub in ast.walk(node):
            if isinstance(sub, ast.Compare) and any(isinstance(c, ast.Constant) and c.value == "python" for c in [sub.left, *sub.comparators]):
                found.add((node.name, 'a comparison with "python"'))
            elif isinstance(sub, ast.Call):
                name = sub.func.attr if isinstance(sub.func, ast.Attribute) else sub.func.id if isinstance(sub.func, ast.Name) else ""
                first = sub.args[0].value if sub.args and isinstance(sub.args[0], ast.Constant) else None
                if name == "endswith" and first == ".py":
                    found.add((node.name, ".endswith('.py')"))
                elif name == "get" and first == "language":
                    found.add((node.name, "language"))
                elif (name == "get" and first == "reader") or name == "_is_table":
                    found.add((node.name, "reader"))
                elif name == "is_pytest_command":
                    found.add((node.name, "is_pytest_command"))
            elif isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Constant) and sub.slice.value == "reader":
                found.add((node.name, "reader"))
            elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load) and sub.id in ("detector", "judge_row"):
                found.add((node.name, "detector" if sub.id == "detector" else "judge_row"))
            elif isinstance(sub, ast.Attribute) and isinstance(sub.ctx, ast.Load) and sub.attr == "detector":
                found.add((node.name, "detector"))      # `ctx.detector`: the same question held in the ProbeCtx (F1 of t-2138)
            elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and "not Python" in sub.value and sub is not doc:
                found.add((node.name, "not Python"))
    return found


def test_no_language_question_on_the_road():
    source = Path(PBC.__file__).read_text(encoding="utf-8")
    found = road_findings(source)
    allowed = {(f, what) for f, what, _why in ROAD_EXCEPTIONS}
    assert all(why for _f, _w, why in ROAD_EXCEPTIONS)
    assert found == allowed, {"a question nobody named": sorted(found - allowed), "an exception that no longer holds": sorted(allowed - found)}
    import ast
    missing = set(ROAD) - {n.name for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    assert not missing, f"the road names functions that do not exist: {sorted(missing)}"


def test_no_language_question_negative_control():
    """The guard sees what it is for: a planted `if not detector:` and `spec.get("language")` are both found; a clean function is not."""
    planted = ("def judge_probe_row(row, spec, detector):\n    if not detector:\n        return spec.get('language')\n"
               "    if spec['file'].endswith('.py') or spec.get('reader') == 'x' or spec['reader']:\n        raise ValueError('is not Python')\n"
               "    return row['lang'] == 'python'\n")
    assert road_findings(planted) == {("judge_probe_row", "detector"), ("judge_probe_row", "language"), ("judge_probe_row", ".endswith('.py')"),
                                      ("judge_probe_row", "reader"), ("judge_probe_row", "not Python"), ("judge_probe_row", 'a comparison with "python"')}
    assert road_findings("def judge_probe_row(row):\n    return row['status']\n") == set()
    # F1: the attribute form (`ctx.detector`) is a question too, alone and on its own
    assert road_findings("def judge_probe_row(row, ctx):\n    if ctx.detector:\n        return 1\n    return row['status']\n") == {("judge_probe_row", "detector")}


# --- N4 (t-2143): a tool refusal of EVERY reader leaves a record, with its language and `cause: tooling` -----------------------------

def refusal_world(tmp_path, monkeypatch, file: str, data: bytes, report_id: str = ""):
    """(task root, args) of a project holding `file` and a manifest row `x` for it; `_tool_refusal_record` reads these and no run."""
    from types import SimpleNamespace
    root, task = tmp_path / "proj", tmp_path / "task"
    (root / file).parent.mkdir(parents=True)
    (root / file).write_bytes(data)
    (task / "work").mkdir(parents=True)
    row = {"instance_id": "x", "file": file, "case": "TC-1", **({"report_test_id": report_id} if report_id else {})}
    (task / "work" / "automation-manifest.json").write_text(json.dumps({"tests": [row]}), encoding="utf-8")
    monkeypatch.setattr(PBC, "project_root", lambda *a, **k: root)
    monkeypatch.setattr(PBC, "load_config", lambda *a, **k: {})
    monkeypatch.setattr(PBC, "_test_path", lambda project, cfg, spec, entry=None: (project / spec["file"], project))
    return task, SimpleNamespace(test=f"{file}::test_x", instance="x", task="T-1"), root / file


def test_python_tool_refusal_has_language_and_cause(tmp_path, monkeypatch):
    """Item 7 (S4): the record of a refused Python probe names `language: python` (the AST reader's entry, after the table's) and
    `cause: tooling`, so `tooling_gap_key` reads it and the owner's class word covers it; a `.py` file is still no entry of the table."""
    assert AD.entry_for_suffix(AD.assertion_detectors(), ".py") == (None, None)        # the table has none: the AST reader is asked second
    task, args, path = refusal_world(tmp_path, monkeypatch, "tests/test_x.py", b"def test_x():\n    pass\n")
    record = PBC._tool_refusal_record(args, task, PBC.ToolRefusal("no check"))
    assert (record["refused"], record["language"], record["cause"], record["verdict"]) == ("tool", "python", "tooling", "not_executed"), record
    assert record["test_file_sha256"] == PBC.sha256(path.read_bytes())
    PBC.atomic_json(PBC.record_path(task, "x"), record)
    assert PL.tooling_gap_key(task, "x", record["test_file_sha256"]) == "tooling:python"
    assert PL.tooling_gap_key(task, "x", "0" * 64) == ""                                 # and for no other bytes
    # a language neither reader claims: a record with no language (as before), never a crash
    task, args, _ = refusal_world(tmp_path / "rb", monkeypatch, "tests/test_x.rb", b"x")
    assert "language" not in PBC._tool_refusal_record(args, task, PBC.ToolRefusal("no check"))


def test_python_name_unproved_needs_a_tail_and_an_entry(tmp_path, monkeypatch):
    """`exc.name_unproved`: the record exists only for a TABLE spec that names a tail and an entry and whose row's `report_test_id` ends
    with that tail; a spec with neither, and a Python spec (the AST reader never raises `name_unproved`: its name is `locate`'s, and its
    entry has no `tail_join` to read the id by), is no proof of the name: None, no record, no crash."""
    unproved = PBC.ToolRefusal("no declaration", name_unproved=True)
    cs = b"class T {\n  void Adds() {\n    var a = 1;\n  }\n}\n"
    task, args, _ = refusal_world(tmp_path / "cs", monkeypatch, "t/T.cs", cs, report_id="t/T.cs::T.Adds")
    args.test = "t/T.cs::T.Adds"
    assert PBC._tool_refusal_record(args, task, unproved)["language"] == "csharp"        # the positive control: a table spec, the row's id ends with the tail
    for spec in ({}, {"reader": "table", "tail": "T.Adds"}, {"reader": "table", "entry": {"x": 1}}):
        monkeypatch.setattr(PBC, "parse_node", lambda text, root=None, _s=spec: _s)
        assert PBC._tool_refusal_record(args, task, unproved) is None, spec
    monkeypatch.undo()
    task, args, _ = refusal_world(tmp_path / "py", monkeypatch, "tests/test_x.py", b"def test_x():\n    pass\n", report_id="tests/test_x.py::test_x")
    assert PBC._tool_refusal_record(args, task, unproved) is None                        # a Python spec: no `name_unproved` record, no KeyError
    assert PBC._tool_refusal_record(args, task, PBC.ToolRefusal("no check"))["language"] == "python"     # while a plain tool refusal leaves its record


def test_python_no_target_leaves_a_record(tmp_path, monkeypatch):
    """Item 7: a Python body with no check of a known form is a `ToolRefusal` (the factory's gap), and `_record_tool_refusal` writes the
    record at the probe's own path; the refusal's text is the one of before."""
    data = b"def test_x():\n    helper(1)\n"
    with pytest.raises(PBC.ToolRefusal, match="the function body has no assert"):
        PBC.plan_mutation(data, PBC.parse_node("tests/test_x.py::test_x"), "invert", "IID")
    with pytest.raises(PBC.Refusal) as plain:                                            # control: a function that is not there is the CALL's fault
        PBC.plan_mutation(data, PBC.parse_node("tests/test_x.py::test_nope"), "invert", "IID")
    assert not isinstance(plain.value, PBC.ToolRefusal)
    task, args, _ = refusal_world(tmp_path, monkeypatch, "tests/test_x.py", data)
    try:
        PBC.plan_mutation(data, PBC.parse_node(args.test), "invert", "IID")
    except PBC.ToolRefusal as exc:
        PBC._record_tool_refusal(args, task, exc)
    written = json.loads(PBC.record_path(task, "x").read_text(encoding="utf-8"))
    assert (written["refused"], written["language"], written["cause"]) == ("tool", "python", "tooling"), written
    assert "the function body has no assert" in written["notes"][0]


def test_table_invert_null_leaves_a_record(tmp_path, monkeypatch):
    """Item 7 / E-F: a check whose row has `invert: null` (a table reader's `Assert.Throws`, a Python `with pytest.raises`) is a
    `ToolRefusal`, not a plain `Refusal`: its text is unchanged and it leaves the record with the language; `--at` on the line
    that holds it is the same (the check exists and the table cannot invert it)."""
    cs = "class T {\n  void Adds() {\n    Assert.Throws<E>(() => Foo());\n    Assert.Equal(4, x);\n  }\n}\n".encode()
    spec = PBC.parse_node("t/T.cs::T.Adds")
    for at in (None, 3):
        with pytest.raises(PBC.ToolRefusal, match="not invertible by code"):
            PBC.plan_detector_mutation(cs, spec, "IID", at, "", "", "t/T.cs")
    py = b"import pytest\n\n\ndef test_r():\n    with pytest.raises(ValueError):\n        int('x')\n"
    with pytest.raises(PBC.ToolRefusal, match="not invertible by code"):
        PBC.plan_mutation(py, PBC.parse_node("tests/t.py::test_r"), "invert", "IID")
    task, args, _ = refusal_world(tmp_path, monkeypatch, "t/T.cs", cs)
    args.test = "t/T.cs::T.Adds"
    try:
        PBC.plan_detector_mutation(cs, spec, "IID", None, "", "", "t/T.cs")
    except PBC.ToolRefusal as exc:
        PBC._record_tool_refusal(args, task, exc)
    written = json.loads(PBC.record_path(task, "x").read_text(encoding="utf-8"))
    assert (written["refused"], written["language"], written["cause"]) == ("tool", "csharp", "tooling"), written
    assert PL.tooling_gap_key(task, "x", written["test_file_sha256"]) == "tooling:csharp"


def test_detectors_read_once_per_process(monkeypatch):
    """par.12 (c): two `parse_node` calls, ONE read of `detectors.json`; a copy at any other path (a test's scratch, the env override)
    is never cached - read on every call, as before - and a rewrite of the shipped file is read again (the key holds mtime and size)."""
    reads = []
    real = Path.read_text

    def spy(self, *a, **k):
        reads.append(Path(self))
        return real(self, *a, **k)
    AD._SHIPPED_TEXT.clear()
    monkeypatch.setattr(Path, "read_text", spy)
    first, second = PBC.parse_node("tests/t.py::test_a"), PBC.parse_node("tests/t.py::test_b")
    assert reads.count(Path(AD.DETECTORS_FILE)) == 1 and first["entry"] == second["entry"], reads
    assert first["entry"] is not second["entry"]                                         # each caller parses its own document: no shared mutable state
    scratch = Path(AD.DETECTORS_FILE)
    AD._document(scratch.with_name("detectors.json"))                                    # the shipped path again: still one read
    assert reads.count(scratch) == 1
    other = scratch.parent / "no-such-detectors.json"
    for _ in range(2):
        with pytest.raises(AD.DetectorsUnreadable):
            AD._document(other)
    assert [p for p in reads if p == other] == [other, other]                            # not the shipped path: read (tried) every time
    key = next(iter(AD._SHIPPED_TEXT))
    AD._SHIPPED_TEXT[(key[0], key[1] + 1, key[2])] = AD._SHIPPED_TEXT.pop(key)           # a stale key (the file "changed"): read again
    AD._document(scratch)
    assert reads.count(scratch) == 2

# --- N5: one hop out of a test body that holds no check, for every language, through data (t-2144) ----------------------------

N5 = Path(__file__).resolve().parent / "fixtures" / "n5-hop"


class Proj:
    """A project in a temp folder (`files`: relative path -> text; the test root is `tests`) and the readers N5 changed, called as `_probe` calls them."""

    def __init__(self, tmp_path: Path, files: dict, node: str, tests_root: str = "tests"):
        for rel, text in files.items():
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        self.root, self.cfg, self.files = tmp_path, {"tests_root": tests_root}, files
        self.spec = PBC.parse_node(node, tmp_path)
        self.path = tmp_path / self.spec["file"]

    def find(self):
        return PBC.find_oracle(self.path.read_text(encoding="utf-8"), self.spec, self.path, self.root, [], PBC._reader_entry(self.spec), self.cfg)

    def resolve(self) -> tuple:
        """(file, function, note) exactly as `_probe` gets them (the conftest chain included)."""
        return PBC._resolve_oracle(self.root, self.root, self.cfg, self.spec, "", self.path, self.path.read_bytes(),
                                   {"file": self.path, "line": None})

    def planned(self, file: Path, name: str, note: str) -> tuple:
        data = file.read_bytes()
        if self.spec["reader"] == "table":
            mutated, detail, _ctx = PBC.plan_detector_mutation(data, self.spec, "IID", None, name, note, PBC._rel_project(file, self.root))
        else:
            mutated, detail = PBC.plan_mutation(data, self.spec, "invert", "IID", name, note)
        return mutated.decode("utf-8"), detail


def refused_text(call, kind=PBC.ToolRefusal) -> str:
    with pytest.raises(kind) as caught:
        call()
    return str(caught.value)


N5_ONE_HOP = {
    "python": ({"tests/test_cart.py": "from helpers import expect_cart\n\n\ndef test_adds():\n    total = 1\n    expect_cart(total)\n",
                "tests/helpers.py": "def expect_cart(n):\n    assert n == 1, 'h'\n"},
               "tests/test_cart.py::test_adds", "tests/helpers.py", "expect_cart"),
    "typescript": ({"tests/calc.spec.ts": "import { test } from '@playwright/test';\nimport { expectCart } from './pages';\n"
                                          "test('adds', async () => {\n  expectCart(1);\n});\n",
                    "tests/pages.ts": "export function expectCart(n: number) {\n  expect(n).toBe(1);\n}\n"},
                   "tests/calc.spec.ts::adds", "tests/pages.ts", "expectCart"),
    "java": ({"src/test/java/com/acme/CalcTest.java": "package com.acme;\n\nimport static com.acme.support.Checks.verifySum;\nimport org.junit.jupiter.api.Test;\n\n"
                                                      "class CalcTest {\n    @Test\n    void adds() {\n        verifySum(2, 2, 4);\n    }\n}\n",
              "src/test/java/com/acme/support/Checks.java": "package com.acme.support;\n\npublic class Checks {\n    public static void verifySum(int a, int b, int s) {\n"
                                                            "        assertEquals(s, a + b);\n    }\n}\n"},
             "src/test/java/com/acme/CalcTest.java::CalcTest.adds", "src/test/java/com/acme/support/Checks.java", "verifySum"),
    "csharp": ({"tests/CalcTests.cs": "namespace Acme.Tests\n{\n    public class CalcTests\n    {\n        public void Adds()\n        {\n            CheckSum(2, 2);\n        }\n\n"
                                      "        private void CheckSum(int a, int b)\n        {\n            Assert.Equal(4, a + b);\n        }\n    }\n}\n"},
               "tests/CalcTests.cs::CalcTests.Adds", "tests/CalcTests.cs", "CheckSum"),
}


@pytest.mark.parametrize("language", sorted(N5_ONE_HOP))
def test_one_hop_each_language(language, tmp_path):
    """N5: a test whose body asserts nothing is followed ONE hop into the helper it calls, in every language - by the AST for Python, by the
    entry's `helper_declaration` and `import_forms` for the others (Java: a static import of a member resolves to its class file; C#: no import form,
    so the same file only, and the note says so). The mutation lands in the helper, on the check's line and nowhere else."""
    files, node, helper_rel, name = N5_ONE_HOP[language]
    proj = Proj(tmp_path, files, node, tests_root="src/test" if language == "java" else "tests")
    file, function, note = proj.resolve()
    assert (file.resolve(), function) == ((tmp_path / helper_rel).resolve(), name), (file, function, note)
    assert "which other tests share" in note and f"`{name}`" in note, note
    assert ("no `import_forms` row" in note) == (language == "csharp"), note
    original = file.read_text(encoding="utf-8")
    mutated, detail = proj.planned(file, name, note)
    changed = [n for n, (a, b) in enumerate(zip(original.splitlines(), mutated.splitlines()), 1) if a != b]
    wanted = [n for n, line in enumerate(original.splitlines(), 1) if re.search(r"\bassert|expect\(|Assert\.", line)]
    assert changed == wanted == [detail["line"]], (changed, wanted, detail["line"])
    assert detail["oracle_function"] == name


def test_csharp_other_file_is_not_followed_and_says_so(tmp_path):
    """C# has no `import_forms`: a helper in another file is not found, the refusal is the tool's, names the door `--at <file>:<line>` and says only
    this file was searched."""
    files = {"tests/CalcTests.cs": N5_ONE_HOP["csharp"][0]["tests/CalcTests.cs"].replace("private void CheckSum", "private void Other"),
             "tests/Helpers.cs": "class Helpers { public static void CheckSum(int a, int b)\n{\n Assert.Equal(4, a + b);\n}\n}\n"}
    proj = Proj(tmp_path, files, "tests/CalcTests.cs::CalcTests.Adds")
    text = refused_text(proj.find)
    assert "no recognised assertion" in text and "--at <file>:<line>" in text and "--oracle" in text and "only this file was searched" in text, text


def test_page_object_method_found(tmp_path):
    """N5, AR-2: a fixture shaped unlike the default - a class method of a page object, on the REAL `BasePage.ts` / `CartPage.ts` of the MyBooks stand
    (`async expectUrl(pathPart: string) { ... }`, no return type) - is found by `helper_declaration` through the test's import, and a call
    of the same name (`cart.expectUrl('/cart');`) is not read as a declaration. Without the import that names the file (the method is inherited,
    no type is resolved), nothing is found and the refusal names the door."""
    files = {"tests/pages/BasePage.ts": (N5 / "pages" / "BasePage.ts").read_bytes(), "tests/pages/CartPage.ts": (N5 / "pages" / "CartPage.ts").read_bytes(),
             "tests/page-object-method.spec.ts": (N5 / "page-object-method.spec.ts").read_bytes()}
    proj = Proj(tmp_path, files, "tests/page-object-method.spec.ts::cart page is open")
    file, function, note = proj.resolve()
    base = (N5 / "pages" / "BasePage.ts").read_text(encoding="utf-8")
    assert (file.name, function) == ("BasePage.ts", "expectUrl") and f"(line {line_of(base, 'toHaveURL')})" in note, (file, function, note)
    mutated, detail = proj.planned(file, function, note)
    assert ".not.toHaveURL" in mutated and detail["line"] == line_of(base, "toHaveURL"), detail
    own = (N5 / "page-object-method.spec.ts").read_text(encoding="utf-8").replace("import { BasePage } from './pages/BasePage';\n", "")
    (tmp_path / "tests" / "page-object-method.spec.ts").write_text(own, encoding="utf-8")
    text = refused_text(proj.find)
    assert "--at <file>:<line>" in text and "`openCart`" in text, text


def test_arrow_const_found(tmp_path):
    """N5: an arrow const with a block body and a check - the REAL `addOne` of cart-stale-tab.spec.ts - is a helper by `helper_declaration`; the
    spec's own body asserts nothing and calls it twice."""
    source = (N5 / "arrow-const.spec.ts").read_bytes()
    proj = Proj(tmp_path, {"tests/arrow-const.spec.ts": source, "tests/pages/CartPage.ts": (N5 / "pages" / "CartPage.ts").read_bytes()},
                "tests/arrow-const.spec.ts::TC-012 stale tab adds two books")
    file, function, note = proj.resolve()
    text = source.decode("utf-8")
    assert (file, function) == (proj.path, "addOne") and f"(line {line_of(text, 'toBeVisible')})" in note, (file, function, note)
    mutated, detail = proj.planned(file, function, note)
    assert ".not.toBeVisible" in mutated and detail["line"] == line_of(text, "toBeVisible"), detail
    assert PBC.enclosing_declaration(source, proj_entry("typescript"), line_of(text, "toBeVisible"))["name"] == "addOne"


def proj_entry(language: str) -> dict:
    return AD.assertion_detectors()[language]


def test_hop_never_into_product(tmp_path):
    """N5, INV of N1: an import that names a file outside the test tree (the product) is not hopped into: the helper there holds a check and is
    NOT found, nothing is read as the oracle, and the refusal counts the import. Java, TypeScript and Python (B1 of t-2167): every language with an import form."""
    ts = Proj(tmp_path / "ts", {"tests/calc.spec.ts": "import { expectCart } from '../src/cart';\ntest('adds', async () => {\n  expectCart(1);\n});\n",
                                "src/cart.ts": "export function expectCart(n: number) {\n  expect(n).toBe(1);\n}\n"}, "tests/calc.spec.ts::adds")
    text = refused_text(ts.find)
    assert "outside the test tree" in text and "../src/cart" in text and "no recognised assertion" in text, text
    java = Proj(tmp_path / "java", {"src/test/java/CalcTest.java": "import com.acme.app.Shared;\nclass CalcTest {\n    void adds() {\n        Shared.verify(1);\n    }\n}\n",
                                    "com/acme/app/Shared.java": "class Shared {\n    static void verify(int n) {\n        assertEquals(1, n);\n    }\n}\n"},
                node="src/test/java/CalcTest.java::CalcTest.adds", tests_root="src/test")
    text = refused_text(java.find)
    assert "outside the test tree" in text and "com.acme.app.Shared" in text, text
    # the same import with the file under the test root IS followed: the guard is the only difference
    inside = Proj(tmp_path / "in", {"src/test/java/CalcTest.java": java.files["src/test/java/CalcTest.java"],
                                    "src/test/java/com/acme/app/Shared.java": java.files["com/acme/app/Shared.java"]},
                  node="src/test/java/CalcTest.java::CalcTest.adds", tests_root="src/test")
    assert inside.find()[0][1] == "verify"
    # no config to judge by: no import is followed (the error direction is toward a refusal)
    unguarded = refused_text(lambda: PBC.find_oracle(inside.path.read_text(encoding="utf-8"), inside.spec, inside.path, inside.root, [],
                                                     PBC._reader_entry(inside.spec), None))
    assert "outside the test tree" in unguarded, unguarded
    # Python (B1 of t-2167): the AST reader's import is guarded by the same predicate - a product module whose helper holds an assert is
    # never the oracle, the note says why, and the refusal of the plan carries it with the door for a check that lives in product code
    py_files = {"tests/test_cart.py": "from app.cart import check_total\n\n\ndef test_total():\n    check_total(1)\n",
                "app/cart.py": "def check_total(n):\n    assert n >= 0, 'contract'\n"}
    py = Proj(tmp_path / "py", py_files, "tests/test_cart.py::test_total")
    found, note = py.find()
    assert found is None and "outside the test tree" in note and "app.cart" in note, (found, note)
    file, function, resolved_note = py.resolve()
    assert (file, function) == (py.path, "") and "outside the test tree" in resolved_note, (file, function, resolved_note)
    text = refused_text(lambda: py.planned(file, function, resolved_note))
    assert "outside the test tree" in text and "red_sandbox.py --probe" in text, text
    assert (tmp_path / "py" / "app" / "cart.py").read_text(encoding="utf-8") == py_files["app/cart.py"]
    # the positive control: the same helper under the test root IS found
    inside_py = Proj(tmp_path / "pyin", {"tests/test_cart.py": "from helpers import check_total\n\n\ndef test_total():\n    check_total(1)\n",
                                         "tests/helpers.py": py_files["app/cart.py"]}, "tests/test_cart.py::test_total")
    assert inside_py.find()[0][1] == "check_total"
    # no config to judge by: no Python import is followed either
    bare = PBC.find_oracle(inside_py.path.read_text(encoding="utf-8"), inside_py.spec, inside_py.path, inside_py.root, [], None, None)
    assert bare[0] is None and "outside the test tree" in bare[1], bare


def test_same_method_in_two_page_objects_is_refused(tmp_path):
    """B2 of t-2167: a bare method name that holds a check in TWO hop files is not told by the name (no type is resolved): the refusal is the
    tool's, names every file:line and the door `--at`; a name with ONE declaration across the files still resolves (control)."""
    page = "export class {cls} {{\n  async verify(n: number) {{\n    expect(n).toBe(1);\n  }}\n}}\n"
    spec = ("import { test } from '@playwright/test';\nimport { HeaderPage } from './pages/HeaderPage';\nimport { CartPage } from './pages/CartPage';\n"
            "test('adds', async () => {\n  const cart = new CartPage();\n  await cart.verify(1);\n});\n")
    files = {"tests/adds.spec.ts": spec, "tests/pages/HeaderPage.ts": page.format(cls="HeaderPage"), "tests/pages/CartPage.ts": page.format(cls="CartPage")}
    proj = Proj(tmp_path / "two", files, "tests/adds.spec.ts::adds")
    text = refused_text(proj.find)
    assert "HeaderPage.ts:2" in text and "CartPage.ts:2" in text and "--at <file>:<line>" in text and "no body is mutated" in text, text
    files["tests/pages/HeaderPage.ts"] = "export class HeaderPage {\n  async open() {\n    await go();\n  }\n}\n"
    one = Proj(tmp_path / "one", files, "tests/adds.spec.ts::adds")
    assert one.find()[0][0].name == "CartPage.ts"


def test_matcher_position_gaps_are_tool_refusals():
    """F4 of t-2167: the gaps of the table's data in `_matcher_position` (no argument list, no second argument) are the factory's: `ToolRefusal`,
    text unchanged, the caller that catches `Refusal` still catches them."""
    entry = AD.assertion_detectors()["typescript"]
    text = "expect;\n"
    src = PBC.Source(text, entry["lexer"], "t/x.spec.ts")
    head = re.match("expect", text)
    for kind in ("second_arg", "after_args"):
        with pytest.raises(PBC.ToolRefusal) as caught:
            PBC._matcher_position(src, kind, head, len(text) - 1, "t/x.spec.ts")
        assert "Nothing was changed" in str(caught.value) or "factory data gap" in str(caught.value), str(caught.value)


def test_python_conftest_and_fixture_param_kept(tmp_path):
    """N5, S10: the Python hop keeps what it had - a fixture named in the test's parameters is found in the conftest chain, and a helper the test
    calls is found in the module it imports - and now takes the calls in SOURCE order."""
    proj = Proj(tmp_path, {"tests/conftest.py": "import pytest\n\n\n@pytest.fixture\ndef cart():\n    assert True, 'fixture'\n",
                           "tests/test_cart.py": "def test_x(cart):\n    pass\n"}, "tests/test_cart.py::test_x")
    file, function, note = proj.resolve()
    assert (file.name, function) == ("conftest.py", "cart") and "(line 6)" in note, (file, function, note)
    ordered = Proj(tmp_path / "o", {"tests/test_o.py": "def test_o():\n    with open('f') as handle:\n        late(handle)\n    first()\n",
                                    "tests/helpers.py": "def first():\n    pass\n"}, "tests/test_o.py::test_o")
    import ast
    function_node = PBC.locate(ast.parse(ordered.path.read_text(encoding="utf-8")), [], "test_o")
    assert PBC._called_names(function_node) == ["open", "late", "first"], PBC._called_names(function_node)


def test_ts_fixture_not_followed_door(tmp_path):
    """N5: a fixture handed in by `test.extend` is not followed: the test asks for `shop`, the fixture file holds a check inside `shop`, and the refusal
    is the tool's, names what was looked at and the door `--at <file>:<line>` (the check's own line)."""
    files = {"tests/fixtures.ts": "export const test = base.extend({\n  shop: async ({}, use) => {\n    expect(1).toBe(1);\n    await use(1);\n  },\n});\n",
             "tests/cart.spec.ts": "import { test } from './fixtures';\ntest('adds', async ({ shop }) => {\n  await shop.book(1);\n});\n"}
    proj = Proj(tmp_path, files, "tests/cart.spec.ts::adds")
    text = refused_text(proj.find)
    assert "--at <file>:<line>" in text and "`test.extend`" in text and "no recognised assertion" in text, text


@pytest.mark.parametrize("language", ["python", "typescript", "java"])
def test_two_hops_refused_with_door(language, tmp_path):
    """N5: a check two hops away (the test calls `outer`, `outer` calls `inner`, `inner` holds the check) is a ToolRefusal whose door is the
    check's own line - never walked into, never a guess."""
    sources = {
        "python": {"tests/test_h.py": "def test_h():\n    outer()\n\n\ndef outer():\n    inner()\n\n\ndef inner():\n    assert 1 == 1\n"},
        "typescript": {"tests/h.spec.ts": "test('h', async () => {\n  outer();\n});\nfunction outer() {\n  inner();\n}\nfunction inner() {\n  expect(1).toBe(1);\n}\n"},
        "java": {"tests/HTest.java": "class HTest {\n    void h() {\n        outer();\n    }\n    void outer() {\n        inner();\n    }\n    void inner() {\n"
                                     "        assertEquals(1, 1);\n    }\n}\n"}}[language]
    rel = next(iter(sources))
    node = {"python": f"{rel}::test_h", "typescript": f"{rel}::h", "java": f"{rel}::HTest.h"}[language]
    proj = Proj(tmp_path, sources, node)
    text = refused_text(proj.find)
    line = {"python": 10, "typescript": 8, "java": 9}[language]
    assert f"--at {rel}:{line}" in text and "one hop" in text and "`inner`" in text and "`outer`" in text, text


def test_name_declared_twice_is_refused_with_lines(tmp_path):
    """N5, INV: a name declared twice in one file, with a check in one of them, is a refusal that names the lines; no body is chosen."""
    src = ("test('adds', async () => {\n  check(1);\n});\nfunction check(n: number) {\n  expect(n).toBe(1);\n}\nfunction check(n: string) {\n}\n")
    proj = Proj(tmp_path, {"tests/d.spec.ts": src}, "tests/d.spec.ts::adds")
    text = refused_text(proj.find, PBC.Refusal)
    assert not isinstance(PBC.Refusal(text), PBC.ToolRefusal) and "declared 2 times" in text and "4, 7" in text and "--at tests/d.spec.ts:<line>" in text, text
    # a name declared twice where NEITHER holds a check is no ambiguity about a check: the hop just finds nothing
    plain = src.replace("expect(n).toBe(1);", "log(n);")
    (tmp_path / "tests" / "d.spec.ts").write_text(plain, encoding="utf-8")
    assert "no recognised assertion" in refused_text(proj.find)


def test_call_name_in_comment_or_string_is_no_call(tmp_path):
    """N5: a helper's name inside a comment or a string of the test body is not a call (the skeleton hides it)."""
    src = ("test('adds', async () => {\n  // checkCart(1);\n  const s = 'checkCart(2)';\n  /* checkCart(3) */\n});\n"
           "function checkCart(n: number) {\n  expect(n).toBe(1);\n}\n")
    proj = Proj(tmp_path, {"tests/c.spec.ts": src}, "tests/c.spec.ts::adds")
    assert "it calls no helper" in refused_text(proj.find)
    (tmp_path / "tests" / "c.spec.ts").write_text(src.replace("// checkCart(1);", "checkCart(1);"), encoding="utf-8")
    assert proj.find()[0][1] == "checkCart"


def test_import_forms_verified_on_real_samples(tmp_path):
    """N5: the shipped rows run on real imports. TypeScript: the imports of the real `add-to-cart.spec.ts` (relative paths only; a package is not one).
    Java: the real import block of a JDK 21 file - plain, nested class, static member and wildcard; the static member and the nested class resolve to the
    class file by dropping trailing segments, a wildcard is no import the row reads, a library names no file (skipped, counted)."""
    ts = AD.assertion_detectors()["typescript"]
    spec_text = (Path(__file__).resolve().parent / "fixtures" / "local1-playwright" / "add-to-cart.spec.ts").read_text(encoding="utf-8")
    row = AD.import_forms(ts)[0]
    got = [m.group("path") for m in row["pattern"].finditer(PBC.Source(spec_text, ts["lexer"], "x").code)]
    assert got == ["../../../core/fixtures/cart.fixture", "../../../core/contracts/validators/errorShape"], got
    java = AD.assertion_detectors()["java"]
    block = (N5 / "jdk-imports.txt").read_text(encoding="utf-8")
    jrow = AD.import_forms(java)[0]
    assert jrow["suffixes"] == [".java"]
    paths = [m.group("path") for m in jrow["pattern"].finditer(block)]
    assert paths == ["java.io.IOException", "java.lang.invoke.MethodHandles.Lookup", "java.nio.ByteOrder", "java.nio.charset.StandardCharsets",
                     "java.text.DecimalFormatSymbols", "java.util.Formatter.FormatSpecifier", "jdk.internal.access.JavaLangAccess",
                     "jdk.internal.access.SharedSecrets", "jdk.internal.util.FormatConcatItem", "java.lang.invoke.MethodType.methodType"], paths
    (tmp_path / "src" / "java" / "util").mkdir(parents=True)
    (tmp_path / "src" / "java" / "util" / "Formatter.java").write_text("class Formatter {}\n", encoding="utf-8")
    (tmp_path / "src" / "java" / "lang" / "invoke").mkdir(parents=True)
    (tmp_path / "src" / "java" / "lang" / "invoke" / "MethodType.java").write_text("class MethodType {}\n", encoding="utf-8")
    here = tmp_path / "src" / "A.java"
    here.write_text(block, encoding="utf-8")
    cfg = {"tests_root": "src"}
    hop = PBC._Hop(here, block, java, "src/A.java", "java")
    files, notes = PBC._imported_modules(hop, tmp_path, cfg)
    assert sorted(f.name for f in files) == ["Formatter.java", "MethodType.java"], files
    assert len(notes) == 1 and "8 import(s) named no file of the project" in notes[0], notes


def test_unresolved_import_is_skipped_with_a_note(tmp_path):
    """N5: an import that names no file is skipped, the hop goes on to the next, and the note says how many were skipped."""
    files, node, _helper, _name = N5_ONE_HOP["java"]
    files = dict(files)
    key = "src/test/java/com/acme/CalcTest.java"
    files[key] = files[key].replace("import org.junit.jupiter.api.Test;", "import org.junit.jupiter.api.Test;\nimport org.assertj.core.api.Assertions;")
    proj = Proj(tmp_path, files, node, tests_root="src/test")
    note = proj.resolve()[2]
    assert "2 import(s) named no file of the project and were skipped" in note, note


def test_enclosing_declaration_each_reader(tmp_path):
    """N5 (for N5b): the innermost declaration holding a line, by each reader, pure. AST: the innermost FunctionDef. Table: `helper_declaration`
    with the name open - a function, an arrow const, a class method, a Java method - and None when none fits; a block keyword (`if (x) {`) is not
    a declaration and a call is not one."""
    py = b"def outer():\n    def inner():\n        x = 1\n    y = 2\n\n\nclass K:\n    def method(self):\n        pass\n\n\nz = 3\n"
    assert PBC.enclosing_declaration(py, None, 3) == {"name": "inner", "first": 2, "last": 3}
    assert PBC.enclosing_declaration(py, None, 4) == {"name": "outer", "first": 1, "last": 4}
    assert PBC.enclosing_declaration(py, None, 9)["name"] == "method" and PBC.enclosing_declaration(py, None, 12) is None
    assert PBC.enclosing_declaration(b"def broken(:\n", None, 1) is None
    ts = AD.assertion_detectors()["typescript"]
    text = ("class Page {\n  async open(): Promise<void> {\n    if (this.ok) {\n      await expect(this.page).toBeVisible();\n    }\n  }\n}\n"
            "const addOne = async (id: number) => {\n  await use(id);\n};\nfunction plain(n: number) {\n  return n;\n}\ntest('t', async () => {\n  addOne(1);\n});\n")
    data = text.encode("utf-8")
    for needle, name in (("toBeVisible", "open"), ("use(id)", "addOne"), ("return n", "plain")):
        found = PBC.enclosing_declaration(data, ts, line_of(text, needle))
        assert found is not None and found["name"] == name, (needle, found)
    assert found["first"] == line_of(text, "function plain") and found["last"] == line_of(text, "return n") + 1
    assert PBC.enclosing_declaration(data, ts, line_of(text, "addOne(1)")) is None      # a line of the test callback: no helper holds it
    assert PBC.enclosing_declaration(data, ts, 99) is None
    java = AD.assertion_detectors()["java"]
    jtext = "class A {\n    void helper(int n) {\n        assertEquals(1, n);\n    }\n}\n"
    assert PBC.enclosing_declaration(jtext.encode("utf-8"), java, 3) == {"name": "helper", "first": 2, "last": 4}


def test_helper_declaration_row_ignores_calls_and_keywords():
    """N5: the shipped TypeScript `helper_declaration` finds declarations by name and nothing else: a call (also at the start of a line), a keyword
    block, an anonymous arrow and a `test(` call are no declaration; the old `function name(` form still is one."""
    ts = AD.assertion_detectors()["typescript"]
    src = PBC.Source("function plain(cb: () => void) {\n}\nconst arrow = async (a: number): Promise<void> => {\n};\nclass C {\n  async method(x: number) {\n  }\n"
                     "  get prop() {\n    return 1;\n  }\n}\nplain(1);\narrow(2);\nif (arrow) {\n}\ntest('t', async ({ page }) => {\n  method(3);\n});\n", ts["lexer"], "t")
    found = sorted(m.group("name") for m in _any(ts, src))
    assert found == ["arrow", "method", "plain", "prop"], found
    for name in ("plain", "arrow", "method"):
        assert len(PBC.declaration_candidates(src, ts, name, True, "t")) == 1, name


def _any(entry, src):
    return [m for m in PBC._any_declaration(entry).finditer(src.code) if src.skeleton[m.start()] == src.code[m.start()]]


def test_declared_once_each_language_and_no_entry(tmp_path):
    """N5 (S9): `declared_once(data, suffix, function)` is "" for a function declared once and a reason otherwise, for every language; a suffix
    with no entry is a reason that names the data gap, never a pass."""
    base = (N5 / "pages" / "BasePage.ts").read_bytes()
    assert PBC.declared_once(base, ".ts", "expectUrl") == ""
    assert PBC.declared_once((N5 / "arrow-const.spec.ts").read_bytes(), ".ts", "addOne") == ""
    assert "no declaration of nothing" in PBC.declared_once(base, ".ts", "nothing")
    assert "declared 2 times" in PBC.declared_once(base + base, ".ts", "expectUrl")
    assert PBC.declared_once(b"class A {\n    void helper(int n) {\n    }\n}\n", ".java", "helper") == ""
    assert PBC.declared_once(b"def helper():\n    pass\n", ".py", "helper") == ""
    assert "more than once" in PBC.declared_once(b"def helper():\n    pass\n\n\ndef helper():\n    pass\n", ".py", "helper")
    assert "does not parse" in PBC.declared_once(b"def broken(:\n", ".py", "broken")
    gap = PBC.declared_once(b"fun helper() {}\n", ".kt", "helper")
    assert "no entry" in gap and "factory data gap" in gap, gap
    assert PBC.declared_once(b"\xff\xfe", ".ts", "x").startswith("the file is not UTF-8")


def test_debt_replays_ts_helper(tmp_path):
    """N5 (S9): `probe_debt._oracle_gone` answers by `declared_once`, so a replay of a probe that mutated a helper in ANY language needs no
    hand-named helper: a TypeScript page-object method and an arrow const replay with `--oracle <file>::<name>`; the reasons of the others stay
    reasons (gone, twice, no entry)."""
    (tmp_path / "tests" / "pages").mkdir(parents=True)
    (tmp_path / "tests" / "pages" / "BasePage.ts").write_bytes((N5 / "pages" / "BasePage.ts").read_bytes())
    (tmp_path / "tests" / "arrow-const.spec.ts").write_bytes((N5 / "arrow-const.spec.ts").read_bytes())
    assert PD._oracle_gone(tmp_path, "tests/pages/BasePage.ts", "expectUrl") == ""
    assert PD._oracle_gone(tmp_path, "tests/arrow-const.spec.ts", "addOne") == ""
    assert "no declaration of vanished" in PD._oracle_gone(tmp_path, "tests/pages/BasePage.ts", "vanished")
    assert "is gone" in PD._oracle_gone(tmp_path, "tests/nowhere.ts", "x") and "cannot be found" in PD._oracle_gone(None, "x.ts", "x")
    (tmp_path / "tests" / "notes.kt").write_text("fun helper() {}\n", encoding="utf-8")
    assert "factory data gap" in PD._oracle_gone(tmp_path, "tests/notes.kt", "helper")
    record = {"test_node": "tests/arrow-const.spec.ts::TC-012 stale tab adds two books", "mutation": "invert",
              "mutated_file": {"path": "tests/pages/BasePage.ts"},
              "mutation_detail": {"line": 5, "mutation": "invert", "style": "detector", "oracle_function": "expectUrl", "file": "tests/pages/BasePage.ts"}}
    plan = PD._replay_plan(record, tmp_path)
    assert plan[2] == "tests/pages/BasePage.ts::expectUrl" and plan[4] == "", plan
    record["mutation_detail"]["oracle_function"] = "vanished"
    assert PD._replay_plan(record, tmp_path)[2] == "" and "cannot be replayed" in PD._replay_plan(record, tmp_path)[4]


# --- N4 leftovers (t-2162): every guard of `_inverted` leaves a record; `passed_residual` is data of the entry ------------------------

INVERT_TEXT = "expect(a).toBe(b);\n"
INVERT_GUARDS = {
    "no pair matches": ({"find": "^nothing", "replace": "x", "fires_as": "zzz"}, "no inversion pair"),
    "replace cannot be expanded": ({"find": "^expect", "replace": "\\1", "fires_as": "zzz"}, "cannot be expanded"),
    "fires_as echoes the statement": ({"find": "^expect", "replace": "expect", "fires_as": "toBe"}, "would also match"),
    "line break moves": ({"find": "^expect", "replace": "expect\n", "fires_as": "zzz"}, "line breaks"),
    "bracket balance changes": ({"find": "^expect", "replace": "expect(", "fires_as": "zzz"}, "bracket balance"),
}


@pytest.mark.parametrize("guard", sorted(INVERT_GUARDS))
def test_inverted_guard_is_a_tool_refusal_that_leaves_a_record(guard, tmp_path, monkeypatch):
    """E-F (t-2045 N4): each of the five guards of `_inverted` is the data's gap, not the call's: a `ToolRefusal`, so the record
    `refused: tool` exists with `language` and `cause: tooling`."""
    pair, words = INVERT_GUARDS[guard]
    entry = AD.assertion_detectors()["typescript"]
    form = {"matcher_at": "head", "invert": [pair]}
    src = PBC.Source(INVERT_TEXT, entry["lexer"], "t/x.spec.ts")
    head = re.match("expect", INVERT_TEXT)
    with pytest.raises(PBC.ToolRefusal) as caught:
        PBC._inverted(src, INVERT_TEXT, entry, "typescript", form, head, 0, len(INVERT_TEXT.rstrip("\n")), "t/x.spec.ts")
    assert words in str(caught.value), str(caught.value)
    task, args, _ = refusal_world(tmp_path, monkeypatch, "tests/x.spec.ts", INVERT_TEXT.encode())
    record = PBC._tool_refusal_record(args, task, caught.value)
    assert record["refused"] == "tool" and record["language"] == "typescript" and record["cause"] == "tooling", record


def passed_row(language: str, entry: dict) -> dict:
    observed = {}
    answer = PBC._row_passed({"status": "passed", "test_id": "t"}, entry, {"language": language, "file": "f", "line": 1}, observed,
                             among=False, argv=["npx", "playwright"])
    return {"answer": answer, "observed": observed}


def test_passed_residual_is_the_entrys_data_not_a_language_branch():
    """t-2064 par.12 (d): the TypeScript entry prints the compiled-output wrapper residual, the Python entry and an entry without the
    key print none; the reader branches on no language."""
    ts = passed_row("typescript", AD.assertion_detectors()["typescript"])
    assert ts["answer"]["verdict"] == "no_failure" and "wrapper of its own" in ts["observed"]["residual"], ts
    py_entry = AD.ast_entry(".py")[1]
    py = passed_row("python", py_entry)
    assert py["answer"]["verdict"] == "no_failure" and "residual" not in py["observed"], py
    bare = {k: v for k, v in AD.assertion_detectors()["typescript"].items() if k != "passed_residual"}
    assert "residual" not in passed_row("typescript", bare)["observed"]
    assert "passed_residual" not in py_entry


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
