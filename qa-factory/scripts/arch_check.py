#!/usr/bin/env python3
"""Mechanical architecture check for generated test code (mandatory step of qa-code-critic).

    python arch_check.py [--tests-root DIR] [--files f1 f2 ...] [--json] [--selftest]

Three checks, all configurable through `qa-factory/config.json` → `arch_check`:
  1. `sleep` calls in tests (`time.sleep(`, `sleep(<number>`, `Thread.sleep`, `page.wait_for_timeout(` etc.: the
     `sleep` key of `references/detectors.json`).
  2. UI locators outside the page-object layer (`page.locator(`, `By.`, `find_element`, `get_by_role(` etc.: the
     `locator` key) in test bodies (a file named as a test, or named by the project's `test_locations`; a helper in
     a test folder is not one) that are not under a page-object directory (`pages/`, `page_objects/`,
     `pageobjects/`, `*_page.py`).
  3. Import direction between declared layers: `arch_check.layers` = [{"name": "tests", "globs": ["tests/**"]},
     {"name": "pages", "globs": ["tests/pages/**"]}, ...] and `arch_check.allowed_imports` = {"tests": ["pages", "api"],
     "pages": ["core"], ...}. A module in layer X importing a module of layer Y not listed for X is a finding.
     Without a `layers` list, check 3 is skipped and reported as `not_configured`.

Exit codes: 0 no findings, 1 findings, 2 bad usage. Findings are printed one per line: `file:line rule message`.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assertion_detectors as AD  # noqa: E402
import test_files as TF  # noqa: E402
from hooklib import sorted_paths  # noqa: E402
try:
    import hooklib  # type: ignore
except Exception:  # pragma: no cover - selftest without the package context
    hooklib = None

# The shapes are data: `references/detectors.json` keys `sleep` and `locator`, read through
# `assertion_detectors.shape_patterns` (B-407 C, one reader with judge_code). These two are the FLOOR - what the
# check was before - used when a key cannot be read, so a missing table never means "no check".
SLEEP_RE = re.compile(r"(?:\btime\.sleep\(|(?<![\w.])sleep\(\s*\d|Thread\.sleep\(|wait_for_timeout\()")
LOCATOR_RE = re.compile(r"(?:\.locator\(|\bBy\.|find_element(?:s)?\(|get_by_(?:role|text|label|placeholder|test_id)\(|\$\$?\(\s*['\"])")
PAGE_OBJECT_DIRS = ("pages", "page_objects", "pageobjects", "screens")
IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)


def _load_project_cfg() -> dict:
    """The whole `qa-factory/config.json` ({} when there is none): the project's own word on where its tests are
    (`test_locations`, `run.levels`, `tests_root`) is what `is_test_for` reads."""
    if hooklib is None:
        return {}
    try:
        cfg_path = hooklib.state_dir() / "config.json"
        if cfg_path.exists():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _shape_rxs(key: str, floor: re.Pattern) -> list:
    """The compiled regexes of one `detectors.json` key, or `[floor]` (what the check was before) when the key
    cannot be read: an unknown table is never "no check"."""
    try:
        return [re.compile(p) for p in AD.shape_patterns(key)]
    except Exception:
        return [floor]


def _is_page_object(path: Path, cfg: dict) -> bool:
    parts = {p.lower() for p in path.parts}
    dirs = tuple(cfg.get("page_object_dirs", PAGE_OBJECT_DIRS))
    if any(d in parts for d in dirs):
        return True
    return path.name.lower().endswith(("_page.py", ".page.ts", ".page.js"))


def _layer_of(rel: str, layers: list[dict]) -> str | None:
    rel = rel.replace(os.sep, "/")
    best = None
    for layer in layers:
        for g in layer.get("globs", []):
            if fnmatch.fnmatch(rel, g):
                if best is None or len(g) > len(best[1]):
                    best = (layer["name"], g)
    return best[0] if best else None


def _module_to_rel(mod: str, root: Path) -> str | None:
    cand = root / (mod.replace(".", "/"))
    for suffix in (".py", "/__init__.py"):
        p = Path(str(cand) + suffix)
        if p.exists():
            return str(p.relative_to(root)).replace(os.sep, "/")
    return None


def check_files(files: list[Path], root: Path, cfg: dict, project_cfg: dict | None = None) -> tuple[list[dict], dict]:
    """`cfg` is the `arch_check` block; `project_cfg` the whole config (the project's word on where its tests
    are), {} when there is none - then only the usual test names decide what a test body is."""
    findings: list[dict] = []
    layers = cfg.get("layers") or []
    allowed = cfg.get("allowed_imports") or {}
    status = {"sleep": "checked", "locators": "checked", "imports": "checked" if layers else "not_configured"}
    sleeps, locators = _shape_rxs("sleep", SLEEP_RE), _shape_rxs("locator", LOCATOR_RE)
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(f.relative_to(root)).replace(os.sep, "/") if f.is_relative_to(root) else str(f)
        test_body = None    # asked once, and only when a locator shows up
        for n, line in enumerate(text.splitlines(), 1):
            if any(rx.search(line) for rx in sleeps) and not line.lstrip().startswith("#"):
                findings.append({"file": rel, "line": n, "rule": "sleep", "message": "sleep-based waiting; wait for a condition instead"})
            if any(rx.search(line) for rx in locators) and not _is_page_object(f, cfg):
                if test_body is None:
                    # A test BODY, not a helper that sits in a test folder (E-C9): by its own name, or named by
                    # the project. Unknown (the usual names cannot be read) is "not a test body"; test_files
                    # says why on stderr.
                    test_body = TF.is_test_for("test_body", rel, project_cfg or {}, base=root, root=root) is True
                if test_body:
                    findings.append({"file": rel, "line": n, "rule": "locator-outside-page-object", "message": "UI locator in a test body; move it to the page-object layer"})
        if layers:
            src_layer = _layer_of(rel, layers)
            if src_layer:
                for m in IMPORT_RE.finditer(text):
                    mod = m.group(1) or m.group(2)
                    target_rel = _module_to_rel(mod, root)
                    if not target_rel:
                        continue
                    dst_layer = _layer_of(target_rel, layers)
                    if dst_layer and dst_layer != src_layer and dst_layer not in allowed.get(src_layer, []):
                        line_no = text.count("\n", 0, m.start()) + 1
                        findings.append({"file": rel, "line": line_no, "rule": "import-direction",
                                         "message": f"layer '{src_layer}' may not import layer '{dst_layer}' ({mod})"})
    return findings, status


def _collect(tests_root: Path) -> list[Path]:
    """The code files under the tests root: `test_files.is_code_file` says which extensions are code. None (the list
    cannot be read) is never "no files": the FR-59 floor `test_files.CODE_EXTENSION_FLOOR` is used and ONE line on
    stderr says so (the same sentence validate_artifacts prints)."""
    out, floor = [], False
    for p in sorted_paths(tests_root.rglob("*")):
        if not p.is_file() or "node_modules" in p.parts:
            continue
        known = TF.is_code_file(p.name)
        if known is None:
            floor = True
            known = p.suffix.lower() in TF.CODE_EXTENSION_FLOOR
        if known:
            out.append(p)
    if floor:
        print("arch_check: references/test-path-markers.json could not be read (the usual test names or code extensions), so "
              f"files with the extensions {', '.join(TF.CODE_EXTENSION_FLOOR)} were treated as code", file=sys.stderr)
    return out


def selftest() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "tests" / "pages").mkdir(parents=True)
        (root / "tests" / "pages" / "login_page.py").write_text("class LoginPage:\n    def user(self, page):\n        return page.locator('#user')\n", encoding="utf-8")
        (root / "tests" / "test_bad.py").write_text("import time\nfrom tests.pages.login_page import LoginPage\n\ndef test_x(page):\n    time.sleep(2)\n    page.locator('#a').click()\n", encoding="utf-8")
        (root / "tests" / "test_good.py").write_text("from tests.pages.login_page import LoginPage\n\ndef test_y(page):\n    assert LoginPage().user(page)\n", encoding="utf-8")
        (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (root / "tests" / "pages" / "__init__.py").write_text("", encoding="utf-8")
        cfg = {"layers": [{"name": "tests", "globs": ["tests/test_*.py"]}, {"name": "pages", "globs": ["tests/pages/*.py"]}],
               "allowed_imports": {"tests": ["pages"], "pages": []}}
        findings, status = check_files(_collect(root / "tests"), root, cfg)
        rules = sorted({f["rule"] for f in findings})
        bad = [f for f in findings if f["file"].endswith("test_bad.py")]
        good = [f for f in findings if f["file"].endswith("test_good.py") or f["file"].endswith("login_page.py")]
        ok = rules == ["locator-outside-page-object", "sleep"] and len(bad) == 2 and not good and status["imports"] == "checked"
        print(f"arch_check selftest: {'ok' if ok else 'FAIL'} findings={findings}")
        return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tests-root", help="directory to scan (default: config.tests_root or ./tests)")
    ap.add_argument("--files", nargs="*", help="explicit files to check")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ns = ap.parse_args()
    if ns.selftest:
        return selftest()
    project = _load_project_cfg()
    cfg = project.get("arch_check", {}) or {}
    root = hooklib.project_root() if hooklib else Path.cwd()
    if ns.files:
        files = [Path(f).resolve() for f in ns.files]
    else:
        tests_root = Path(ns.tests_root) if ns.tests_root else None
        if tests_root is None and hooklib is not None:
            tests_root = root / str(project.get("tests_root") or "tests")
        if not tests_root or not tests_root.exists():
            print(f"arch_check: tests root not found ({tests_root})", file=sys.stderr)
            return 2
        files = _collect(tests_root)
    findings, status = check_files(files, root, cfg, project)
    if ns.json:
        print(json.dumps({"findings": findings, "status": status, "files_checked": len(files)}, indent=2))
    else:
        for f in findings:
            print(f"{f['file']}:{f['line']} {f['rule']} {f['message']}")
        print(f"arch_check: {len(findings)} finding(s) in {len(files)} file(s); imports: {status['imports']}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
