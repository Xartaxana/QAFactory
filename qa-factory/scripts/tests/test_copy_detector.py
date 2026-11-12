#!/usr/bin/env python3
"""TQ1-19 (D2): `copy_detector.py`, the name-blind copy of a function or a fragment.

  * the normal form: local names, literals and the function's own name do not count; a different call into the project does (K1);
  * the table of inputs the check must meet: renamed variables, parametrized twins (a literal differs), fixtures with one body and
    two names, three `try/except` in one function (a window inside a function), a test that copies a helper (K1-K6);
  * the inverse, which must NOT be a copy: a function with itself, a call to another function, a body under the size limit, copy
    only between two unchanged functions, an edited function against its own old self (K7, D2-10);
  * the limits are a row of `detectors.json`: defaults and a note when the row, a key or the file cannot be read (D2-2); the
    file limit AT and BEYOND (D2-1); a file that does not parse is a note, never a crash (D2-4);
  * the novelty is handed in: `unchanged` is dropped, `unknown` is kept and marked, a failing measurer is `unknown` and says so (D2-3);
  * an import outside the project is not read (D2-6); the CLI prints a summary (N0).

Each key names the mutation it kills (spec M-D2-1: names not blinded -> K1; the others are named on the keys).
"""
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

import copy_detector as CD  # noqa: E402

LIM = {"min_function_statements": 2, "fragment_window": 3, "max_files": 40}


def put(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path.resolve()


def new(_tops):
    return ["new"] * len(_tops)


def found(root, rels, lim=LIM, novelty=new):
    return CD.find_copies([root / r for r in rels], root, lim, novelty)


def pairs(result):
    return sorted((c["unit"].qname, c["old"].qname, c["how"]) for c in result["copies"])


HELPER_A = ("def make_user(client, name):\n    data = {'name': name, 'role': 'user'}\n    reply = client.post('/users', data)\n"
            "    return reply.json()['id']\n")
HELPER_B_SAME = ("def create_account(api, title):\n    payload = {'name': title, 'role': 'admin'}\n    answer = api.post('/users', payload)\n"
                 "    return answer.json()['id']\n")


def normal_form_is_name_blind() -> None:
    import ast
    one = ast.parse("def a(x, y):\n    z = x + 1\n    return f(z, 'p')\n").body[0]
    two = ast.parse("def b(p, q):\n    r = p + 2\n    return f(r, 'zzz')\n").body[0]
    other = ast.parse("def c(x, y):\n    z = x + 1\n    return g(z, 'p')\n").body[0]
    check_eq("K1 / M-D2-1: other names, other literals of the same type: one normal form", CD.normal_form(one), CD.normal_form(two))
    check("K7: a different call into the project is not the same function", CD.normal_form(one) != CD.normal_form(other))
    swapped = ast.parse("def d(y, x):\n    z = x + 1\n    return f(z, 'p')\n").body[0]
    check("the ORDER of the arguments is part of the form (the same names in another order are another function)",
          CD.normal_form(one) != CD.normal_form(swapped))


def the_table_of_inputs() -> None:
    root = temp_dir("qa-cd-table-")
    try:
        put(root, "pages.py", HELPER_A)
        put(root, "other.py", HELPER_B_SAME)
        got = found(root, ["pages.py", "other.py"])
        check_eq("K1: two helpers with other names, other literals and one call: ONE copy, reported once (a pair is not twice)",
                 pairs(got), [("create_account", "make_user", "function")])
        put(root, "other.py", HELPER_B_SAME.replace("api.post", "api.put"))
        check_eq("K7: `.put` against `.post` is another function: no copy", found(root, ["pages.py", "other.py"])["copies"], [])

        put(root, "c1/conftest.py", "import pytest\n\n\n@pytest.fixture\ndef project_a_name(client):\n    name = client.make('a')\n"
                                    "    client.register(name)\n    yield name\n    client.drop(name)\n")
        put(root, "c2/conftest.py", "import pytest\n\n\n@pytest.fixture\ndef story_project_a(client):\n    n = client.make('b')\n"
                                    "    client.register(n)\n    yield n\n    client.drop(n)\n")
        got = found(root, ["c1/conftest.py", "c2/conftest.py"])
        check_eq("K2: fixtures with one body and two names are a copy", [c["unit"].kind for c in got["copies"]], ["fixture"])

        put(root, "t/test_a.py", "def test_one(api):\n    r = api.get('/a')\n    assert r.status_code == 200\n    assert r.json()['k'] == 1\n")
        put(root, "t/test_b.py", "def test_two(api):\n    s = api.get('/b')\n    assert s.status_code == 404\n    assert s.json()['k'] == 2\n")
        got = found(root, ["t/test_a.py", "t/test_b.py"])
        check_eq("K3: parametrized twins (only the literals differ) are a copy of kind `test` (the gate makes it a hint)",
                 [(c["unit"].kind, c["how"]) for c in got["copies"]], [("test", "function")])

        tries = "".join(f"    try:\n        api.put('/{n}', {{}})\n    except HTTPError as e:\n        {v} = e.code\n"
                        for n, v in (("x", "g1"), ("y", "g2"), ("z", "g3")))
        put(root, "t/test_c.py", "def test_c(api):\n" + tries)
        put(root, "t/test_d.py", "def helper_d(api):\n" + tries.replace("g1", "c1").replace("g2", "c2").replace("g3", "c3")
            + "    return c1\n")
        got = found(root, ["t/test_c.py", "t/test_d.py"])
        check_eq("K4: three `try/except` in a row inside one function, repeated in a helper that does more: a FRAGMENT copy, "
                 "the helper (not a test) first", [(c["unit"].name, c["how"]) for c in got["copies"]], [("helper_d", "fragment")])

        put(root, "t/test_e.py", "def test_e(api, user):\n    api.login(user)\n    r = api.get('/a')\n    assert r.status_code == 200\n")
        put(root, "t/test_f.py", "def test_f(api, user):\n    api.login(user)\n    r = api.get('/a')\n    assert r.status_code == 200\n"
                                 "    assert r.json()['k'] == 3\n")
        got = found(root, ["t/test_e.py", "t/test_f.py"])
        check("K5: the same statements in the same order under other variable names: a fragment copy of a test",
              any(c["unit"].kind == "test" for c in got["copies"]), str(pairs(got)))
    finally:
        cleanup(root)


def what_is_not_a_copy() -> None:
    root = temp_dir("qa-cd-inverse-")
    try:
        put(root, "one.py", HELPER_A)
        check_eq("K7: one function with itself is no copy", found(root, ["one.py"])["copies"], [])
        put(root, "tiny.py", "def f(x):\n    return g(x)\n")
        put(root, "tiny2.py", "def h(y):\n    return g(y)\n")
        check_eq("K7: `def f(): return g()` is under the size limit: no copy", found(root, ["tiny.py", "tiny2.py"])["copies"], [])
        # N=2 (the survivor's old `dup-helper` refused a 2-statement exact twin; N=3 would let it pass): AT the limit a copy, one below none
        put(root, "two1.py", "def two_a(x):\n    y = g(x)\n    return h(y)\n")
        put(root, "two2.py", "def two_b(z):\n    w = g(z)\n    return h(w)\n")
        got = found(root, ["two1.py", "two2.py"])
        check_eq("N=2: a 2-statement exact twin IS a copy at the shipped limit", [(c["how"], c["unit"].size) for c in got["copies"]], [("function", 2)])
        check_eq("N=2 boundary BELOW: a 1-statement twin is not (the tiny pair above)", found(root, ["tiny.py", "tiny2.py"])["copies"], [])
        put(root, "a.py", HELPER_A)
        put(root, "b.py", HELPER_B_SAME)
        check_eq("K7: a copy between two UNCHANGED functions is nobody's (novelty `unchanged` drops it)",
                 found(root, ["a.py", "b.py"], novelty=lambda t: ["unchanged"] * len(t))["copies"], [])
        mixed = found(root, ["a.py", "b.py"], novelty=lambda t: ["unchanged" if str(p).endswith("a.py") else "new" for p, _c, _n in t])
        check_eq("... one new, one unchanged: reported on the NEW one", [c["unit"].name for c in mixed["copies"]], ["create_account"])
        # D2-10: a function edited against its own old self - the pool is the CURRENT files, so the old body is not there
        put(root, "edited.py", HELPER_A.replace("'user'", "'admin'"))
        check_eq("D2-10: an edited function is not compared with its old self", found(root, ["edited.py"])["copies"], [])
        # a function with itself in two files given twice: one file once
        check_eq("the same file named twice is read once", found(root, ["a.py", "a.py"])["copies"], [])
        # three statements nested: the window does not cross a def
        put(root, "nest.py", "def outer(x):\n    a = 1\n    def inner(y):\n        return y\n    b = 2\n    return a + b + x\n")
        check_eq("a window never spans a nested def", found(root, ["nest.py"])["copies"], [])
    finally:
        cleanup(root)


def the_limits_are_a_row_with_defaults() -> None:
    root = temp_dir("qa-cd-limits-")
    try:
        shipped, notes = CD.limits()
        check_eq("the shipped row is read: 2 / 3 / 40, no note", (shipped, notes), (dict(LIM), []))
        table = root / "detectors.json"
        table.write_text(json.dumps({"copy_detector": {"min_function_statements": 5, "fragment_window": 4, "max_files": 7}}), encoding="utf-8")
        check_eq("a valid row is the limits", CD.limits(table)[0], {"min_function_statements": 5, "fragment_window": 4, "max_files": 7})
        got, notes = CD.limits(root / "missing.json")
        check_eq("D2-2: a file that is not there: the defaults and a note", (got, len(notes)), (dict(LIM), 1))
        check_in("... naming what happened", "cannot be read", notes[0])
        table.write_text("{not json", encoding="utf-8")
        got, notes = CD.limits(table)
        check_eq("D2-2: a broken file: the defaults and a note", (got, len(notes)), (dict(LIM), 1))
        table.write_text(json.dumps({"other": 1}), encoding="utf-8")
        got, notes = CD.limits(table)
        check_eq("D2-2: a file with no row: the defaults and a note", (got, len(notes)), (dict(LIM), 1))
        check_in("... naming the row", "`copy_detector` row", notes[0])
        for bad in (0, -1, "3", 2.5, True, None):
            table.write_text(json.dumps({"copy_detector": {"min_function_statements": bad, "fragment_window": 4}}), encoding="utf-8")
            got, notes = CD.limits(table)
            check_eq(f"D2-2: min_function_statements={bad!r} is the default, the other keys are read", (got["min_function_statements"], got["fragment_window"]), (2, 4))
            check(f"... and {bad!r} / the absent max_files are named", len(notes) == 2 and "min_function_statements" in notes[0], str(notes))
        table.write_text(json.dumps([1, 2]), encoding="utf-8")
        check_eq("a document that is not an object: defaults and a note", (CD.limits(table)[0], len(CD.limits(table)[1])), (dict(LIM), 1))
    finally:
        cleanup(root)


def the_file_limit_is_named_at_and_beyond() -> None:
    root = temp_dir("qa-cd-files-")
    try:
        names = [f"m{n}.py" for n in range(4)]
        for n, name in enumerate(names):
            put(root, name, HELPER_A.replace("make_user", f"make_{n}"))
        lim = dict(LIM, max_files=4)
        at = found(root, names, lim)
        check_eq("D2-1 AT the limit: all four read, nothing dropped, the copies are there", (at["dropped"], len(at["copies"]) >= 3), ([], True))
        put(root, "extra.py", HELPER_A)
        beyond = found(root, names + ["extra.py"], lim)
        check_eq("D2-1 BEYOND the limit (+1): the one beyond is named", [p.name for p in beyond["dropped"]], ["extra.py"])
        less = found(root, names, dict(LIM, max_files=3))
        check_eq("... the limit moves with the row: three read, one named", (len(less["dropped"]), less["dropped"][0].name), (1, "m3.py"))
    finally:
        cleanup(root)


def an_unreadable_file_is_a_note_not_a_crash() -> None:
    root = temp_dir("qa-cd-parse-")
    try:
        put(root, "ok.py", HELPER_A)
        put(root, "broken.py", "def broken(:\n    pass\n")
        got = found(root, ["ok.py", "broken.py"])
        check_eq("D2-4: a file that does not parse gives a note and no copy", (len(got["notes"]), got["copies"]), (1, []))
        check_in("... the note names the file and says it is unchecked", "broken.py: not parsed", got["notes"][0])
        check_in("... and 'unchecked'", "unchecked", got["notes"][0])
        check_eq("D2-5: no files, no copies, no notes", CD.find_copies([], root, LIM, new), {"copies": [], "notes": [], "dropped": []})
        put(root, "empty.py", "")
        check_eq("an empty file: no units, no note", (found(root, ["empty.py"])["copies"], found(root, ["empty.py"])["notes"]), ([], []))
    finally:
        cleanup(root)


def the_novelty_is_handed_in_and_never_guessed() -> None:
    root = temp_dir("qa-cd-novelty-")
    try:
        put(root, "a.py", HELPER_A)
        put(root, "b.py", HELPER_B_SAME)
        got = found(root, ["a.py", "b.py"], novelty=lambda t: ["maybe"] * len(t))
        check_eq("D2-3: an answer that is none of the three is `unknown`, kept (not dropped, not new)",
                 [c["novelty"] for c in got["copies"]], ["unknown"])
        got = found(root, ["a.py", "b.py"], novelty=None)
        check_eq("D2-3: no measurer given: every copy is `unknown`", [c["novelty"] for c in got["copies"]], ["unknown"])
        got = found(root, ["a.py", "b.py"], novelty=lambda t: ["new"])
        check("a measurer that answers for fewer units: the rest is `unknown`, no IndexError",
              {c["novelty"] for c in got["copies"]} <= {"new", "unknown"} and len(got["copies"]) == 1)

        def broken(_tops):
            raise RuntimeError("no base")
        got = found(root, ["a.py", "b.py"], novelty=broken)
        check_eq("D2-3: a measurer that raises: `unknown` and a note", ([c["novelty"] for c in got["copies"]], len(got["notes"])), (["unknown"], 1))
        check_in("... the note names it", "novelty could not be measured", got["notes"][0])
        asked: list = []
        found(root, ["a.py", "b.py"], novelty=lambda t: asked.append(list(t)) or ["new"] * len(t))
        check_eq("ONE call to the measurer for the run (FR-55), and only for units that have a copy", len(asked), 1)
        put(root, "lonely.py", "def lonely(x):\n    return x.alone().only().once()\n")
        asked.clear()
        found(root, ["lonely.py"], novelty=lambda t: asked.append(t) or [])
        check_eq("no copy, no call to the measurer", asked, [])
    finally:
        cleanup(root)


def an_import_outside_the_project_is_not_read() -> None:
    root = temp_dir("qa-cd-pool-")
    try:
        project = root / "proj"
        put(root, "ext_helpers.py", HELPER_A)        # beside the project, not in it: `root.parent` of the project
        put(project, "tests/test_x.py", "from ext_helpers import make_user\nfrom tests.local_helpers import make_local\n\n\n"
                                       + HELPER_B_SAME.replace("create_account", "test_x_body"))
        put(project, "tests/__init__.py", "")
        put(project, "tests/local_helpers.py", HELPER_A.replace("make_user", "make_local"))
        files = CD.imported_files(project, project / "tests" / "test_x.py")
        check_eq("D2-6: the import of a module that is inside the project is followed, the one outside is not",
                 [p.name for p in files], ["local_helpers.py"])
        got = CD.find_copies([project / "tests" / "test_x.py"], project, LIM, new)
        check_eq("the pool holds the imported project module: the copy is found there",
                 [(c["unit"].name, c["old"].name) for c in got["copies"]], [("test_x_body", "make_local")])
        no_root = CD.find_copies([project / "tests" / "test_x.py"], None, LIM, new)
        check_eq("D2-6: no project root: the pool is the files of the history alone (no import walk), no crash", no_root["copies"], [])
    finally:
        cleanup(root)


def the_cli_prints_a_summary() -> None:
    root = temp_dir("qa-cd-cli-")
    try:
        put(root, "tests/helpers.py", HELPER_A)
        put(root, "tests/test_y.py", "from helpers import make_user\n\n\n" + HELPER_B_SAME.replace("create_account", "test_y"))
        out = io.StringIO()
        with redirect_stdout(out):
            code = CD.main(["--root", str(root), "--min", "3", "--window", "3", "--json"])
        data = json.loads(out.getvalue())
        check_eq("N0 CLI: exit 0 and the summary counts the file with findings", (code, data["summary"]["files_with_findings"]), (0, 1))
        check_eq("N0 CLI: a root that is not a directory is exit 2", CD.main(["--root", str(root / "nope")]), 2)
        check_eq("N0 CLI: --window 0 is exit 2", CD.main(["--root", str(root), "--window", "0"]), 2)
    finally:
        cleanup(root)


def main() -> None:
    normal_form_is_name_blind()
    the_table_of_inputs()
    what_is_not_a_copy()
    the_limits_are_a_row_with_defaults()
    the_file_limit_is_named_at_and_beyond()
    an_unreadable_file_is_a_note_not_a_crash()
    the_novelty_is_handed_in_and_never_guessed()
    an_import_outside_the_project_is_not_read()
    the_cli_prints_a_summary()
    finish("test_copy_detector")


if __name__ == "__main__":
    main()
