"""arch_check.check_files: the mechanical architecture check qa-code-critic must run —
sleep-based waits, UI locators outside the page-object layer, and import direction
between declared layers. Exercises check_files() directly on a small realistic tree
instead of going through the CLI/--selftest, per house style.
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import arch_check as A  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, finish  # noqa: E402

root = Path(tempfile.mkdtemp(prefix="qa-arch-check-"))
try:
    pages = root / "tests" / "pages"
    pages.mkdir(parents=True)
    (root / "tests" / "core").mkdir(parents=True)

    (pages / "login_page.py").write_text(
        "class LoginPage:\n    def user(self, page):\n        return page.locator('#user')\n",
        encoding="utf-8")
    (root / "tests" / "test_bad.py").write_text(
        "import time\nfrom tests.pages.login_page import LoginPage\n\n"
        "def test_x(page):\n    time.sleep(2)\n    page.locator('#a').click()\n",
        encoding="utf-8")
    (root / "tests" / "test_good.py").write_text(
        "from tests.pages.login_page import LoginPage\n\n"
        "def test_y(page):\n    assert LoginPage().user(page)\n",
        encoding="utf-8")
    (root / "tests" / "core" / "helpers.py").write_text(
        "def wait_a_bit():\n    return 1\n", encoding="utf-8")
    (root / "tests" / "test_layered.py").write_text(
        "from tests.core.helpers import wait_a_bit\n\ndef test_z():\n    wait_a_bit()\n",
        encoding="utf-8")

    files = A._collect(root / "tests")

    findings, status = A.check_files(files, root, {})
    bad = [f for f in findings if f["file"].endswith("test_bad.py")]
    check_eq("no layers configured -> import check reports not_configured", status["imports"], "not_configured")
    check("a sleep(...) call is a finding", any(f["rule"] == "sleep" for f in bad))
    check("a locator directly in a test body is a finding", any(f["rule"] == "locator-outside-page-object" for f in bad))
    check_eq("exactly the two findings on the bad file, nothing extra", len(bad), 2)
    good = [f for f in findings if f["file"].endswith("test_good.py")]
    check_eq("a test that only calls the page object has no findings", good, [])
    page_object = [f for f in findings if f["file"].endswith("login_page.py")]
    check_eq("a locator INSIDE the page-object layer is not a finding", page_object, [])

    cfg = {"layers": [{"name": "tests", "globs": ["tests/test_*.py"]},
                       {"name": "core", "globs": ["tests/core/*.py"]}],
           "allowed_imports": {"tests": [], "core": []}}
    findings2, status2 = A.check_files([root / "tests" / "test_layered.py",
                                        root / "tests" / "core" / "helpers.py"], root, cfg)
    check_eq("layers configured -> import check runs", status2["imports"], "checked")
    check("importing a layer not listed in allowed_imports is a finding",
          any(f["rule"] == "import-direction" for f in findings2))

    cfg_ok = dict(cfg, allowed_imports={"tests": ["core"], "core": []})
    findings3, _ = A.check_files([root / "tests" / "test_layered.py",
                                  root / "tests" / "core" / "helpers.py"], root, cfg_ok)
    check("the same import is clean once the layer is allowed",
          not any(f["rule"] == "import-direction" for f in findings3))

    # a commented-out sleep is prose, not a finding
    (root / "tests" / "test_commented.py").write_text(
        "def test_c():\n    # time.sleep(2)  -- left here on purpose\n    assert True\n",
        encoding="utf-8")
    findings4, _ = A.check_files([root / "tests" / "test_commented.py"], root, {})
    check_eq("a commented-out sleep is not flagged", findings4, [])

    check("_is_page_object recognizes the pages/ directory", A._is_page_object(pages / "login_page.py", {}))
    check("_is_page_object recognizes a *_page.py suffix outside pages/",
          A._is_page_object(root / "tests" / "checkout_page.py", {}))
    check("_is_page_object is false for an ordinary test file",
          not A._is_page_object(root / "tests" / "test_bad.py", {}))

    # --- B-407 C: the shapes are data, "is this a test body" is the one recognizer -------------------------------
    import json
    import os
    java = root / "jtests"
    (java / "pages").mkdir(parents=True)
    (java / "helpers").mkdir(parents=True)
    (java / "pages" / "LoginPage.java").write_text(
        "class LoginPage {\n  void user() { driver.findElement(By.id(\"user\")); }\n}\n", encoding="utf-8")
    (java / "LoginTest.java").write_text(
        "class LoginTest {\n  void t() throws Exception {\n    Thread.sleep(1000);\n"
        "    driver.findElement(By.id(\"user\"));\n  }\n}\n", encoding="utf-8")
    (java / "helpers" / "Driver.java").write_text(
        "class Driver {\n  void open() { driver.findElement(By.id(\"user\")); }\n}\n", encoding="utf-8")
    (java / "helpers" / "latest.py").write_text("def user(page):\n    return page.locator('#user')\n", encoding="utf-8")
    (java / "helpers" / "waits.py").write_text("import asyncio\n\nasync def pause():\n    await asyncio.sleep(1)\n", encoding="utf-8")
    (java / "test_async.py").write_text("import asyncio\n\nasync def test_a():\n    await asyncio.sleep(1)\n", encoding="utf-8")
    (java / "data.json").write_text('{"x": "Thread.sleep(5)"}\n', encoding="utf-8")
    (java / "notes.md").write_text("Thread.sleep(5) is bad\n", encoding="utf-8")
    (java / "node_modules").mkdir()
    (java / "node_modules" / "dep.js").write_text("setTimeout(); time.sleep(3)\n", encoding="utf-8")

    def findings_by_file(project_cfg=None, files=None):
        found, _status = A.check_files(files or A._collect(java), root, {}, project_cfg)
        grouped = {}
        for f in found:
            grouped.setdefault(f["file"], []).append((f["line"], f["rule"]))
        return grouped

    got = findings_by_file()
    check_eq("K-C6: a locator in a page object (tests/pages/LoginPage.java) is no finding", got.get("jtests/pages/LoginPage.java"), None)
    check_eq("K-C6: a Java test (LoginTest.java) gets the Thread.sleep AND the By.id findings",
             got.get("jtests/LoginTest.java"), [(3, "sleep"), (4, "locator-outside-page-object")])
    check_eq("E-C9: a helper in a test folder with a non-test name (helpers/Driver.java) gets no locator finding",
             got.get("jtests/helpers/Driver.java"), None)
    check_eq("E-C9: ... nor a Python helper (helpers/latest.py: 'test' inside 'latest' is no test)",
             got.get("jtests/helpers/latest.py"), None)
    check_eq("K-C6: asyncio.sleep(1) is a finding in a helper too (a sleep is a sleep wherever it sits)",
             got.get("jtests/helpers/waits.py"), [(4, "sleep")])
    check_eq("K-C6: ... and in a test", got.get("jtests/test_async.py"), [(4, "sleep")])
    check_eq("_collect: a .json and a .md are not code, and node_modules is never walked",
             sorted(p.name for p in A._collect(java)),
             ["Driver.java", "LoginPage.java", "LoginTest.java", "latest.py", "test_async.py", "waits.py"])
    (java / "x_test.go").write_text("package x\n", encoding="utf-8")
    check_in("_collect: an extension the old private tuple lacked is code now (.go)", "x_test.go",
             [p.name for p in A._collect(java)])
    (java / "x_test.go").unlink()

    # E-C9 where it matters: the helper sits INSIDE a real test folder (`tests/`, which `tests_root` also names)
    (root / "tests" / "support").mkdir()
    (root / "tests" / "support" / "ui_helper.py").write_text(
        "def click(page):\n    page.locator('#go').click()\n", encoding="utf-8")
    for label, project in (("no project config", None), ("tests_root: tests (a folder, recognition only)", {"tests_root": "tests"})):
        helper = [f for f in A.check_files([root / "tests" / "support" / "ui_helper.py", root / "tests" / "test_bad.py"],
                                           root, {}, project)[0] if f["rule"] == "locator-outside-page-object"]
        check_eq(f"E-C9 [{label}]: tests/support/ui_helper.py is no test body, tests/test_bad.py still is",
                 [(f["file"], f["line"]) for f in helper], [("tests/test_bad.py", 6)])

    # the project's own word names a test body whatever its name (a `test_locations` file entry)
    flows = java / "flows"
    flows.mkdir()
    (flows / "checkout.py").write_text("def run(page):\n    page.locator('#pay').click()\n", encoding="utf-8")
    (flows / "other.py").write_text("def run(page):\n    page.locator('#pay').click()\n", encoding="utf-8")
    named = findings_by_file({"test_locations": ["jtests/flows/check*.py"]})
    check_eq("a file the project's test_locations names is a test body", named.get("jtests/flows/checkout.py"),
             [(2, "locator-outside-page-object")])
    check_eq("... and its neighbour that nobody named is not", named.get("jtests/flows/other.py"), None)

    # E-C10: the same shapes through the data, and the floor when the data is missing (an older copy of the references)
    shipped = json.loads((Path(A.__file__).resolve().parents[1] / "references" / "detectors.json").read_text(encoding="utf-8"))
    scratch = Path(tempfile.mkdtemp(prefix="qa-arch-shapes-"))

    def in_world(text):
        path = scratch / "detectors.json"
        path.write_text(text, encoding="utf-8")
        os.environ["ASSERTION_DETECTORS_FILE"] = str(path)
        try:
            return findings_by_file()
        finally:
            os.environ.pop("ASSERTION_DETECTORS_FILE", None)

    try:
        no_keys = in_world(json.dumps({k: v for k, v in shipped.items() if k not in ("sleep", "locator")}))
        check_eq("E-C10 [no `sleep`/`locator` keys]: today's regexes are the floor - Thread.sleep and By.id still found",
                 no_keys.get("jtests/LoginTest.java"), [(3, "sleep"), (4, "locator-outside-page-object")])
        check_eq("E-C10 [no keys]: ... and asyncio.sleep(1) is what it was before (not a finding): the floor, not the data",
                 (no_keys.get("jtests/test_async.py"), no_keys.get("jtests/helpers/waits.py")), (None, None))
        broken = in_world("{ not json")
        check_eq("E-C10 [file not JSON]: the floor again - never no check", broken.get("jtests/LoginTest.java"),
                 [(3, "sleep"), (4, "locator-outside-page-object")])
        malformed = in_world(json.dumps(dict(shipped, sleep=["[open"], locator="By\\.")))
        check_eq("E-C10 [malformed keys]: both fall to the floor", malformed.get("jtests/LoginTest.java"),
                 [(3, "sleep"), (4, "locator-outside-page-object")])
        (java / "test_custom.py").write_text("def test_c(app):\n    pause_for(2)\n    tap_on('x')\n    time.sleep(1)\n", encoding="utf-8")
        custom = in_world(json.dumps(dict(shipped, sleep=["pause_for\\("], locator=["tap_on\\("])))
        check_eq("K-C6: the shapes ARE the data - a project's own wait and tap are found, the shipped ones are not",
                 custom.get("jtests/test_custom.py"), [(2, "sleep"), (3, "locator-outside-page-object")])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    # critic t-562 F2 (FR-59): the usual test names cannot be read -> the extension floor collects, never 0 files
    import contextlib
    import io
    import test_locations as TL
    (root / "tests" / "test_a.py").write_text("import time\n\ndef test_a():\n    time.sleep(1)\n", encoding="utf-8")
    (root / "tests" / "notes.md").write_text("time.sleep(1)\n", encoding="utf-8")
    real_markers, err = TL.markers, io.StringIO()
    TL.markers = lambda: ({}, "missing, unreadable or empty")
    try:
        with contextlib.redirect_stderr(err):
            floor_files = A._collect(root / "tests")
            floor_found, floor_status = A.check_files(floor_files, root, {})
    finally:
        TL.markers = real_markers
    check_in("F2: markers unreadable, tests/test_a.py is still collected", "test_a.py", [p.name for p in floor_files])
    check("F2: ... a .md is not (outside the floor)", "notes.md" not in [p.name for p in floor_files])
    check("F2: ... and time.sleep(1) in it is still a sleep finding",
          ("tests/test_a.py", 4, "sleep") in [(f["file"], f["line"], f["rule"]) for f in floor_found])
    notes = [ln for ln in err.getvalue().splitlines() if ln.startswith("arch_check: references/test-path-markers.json could not be read")]
    check_eq("F2: ... and ONE line says the markers were unreadable and the floor was used", len(notes), 1)
    check_in("F2: ... naming the floor's extensions", ".py, .js", notes[0])
    quiet = io.StringIO()
    with contextlib.redirect_stderr(quiet):
        A._collect(root / "tests")
    check_eq("F2 control: with the markers readable there is no such line", "could not be read" in quiet.getvalue(), False)
finally:
    shutil.rmtree(root, ignore_errors=True)

finish("test_arch_check")
