#!/usr/bin/env python3
"""A handover form is filled in one call: `handoff_check.py --values`, array paths, ONE applier (SC1-2 part A1) and ONE
refusal with one ready command (part A2).

The failure behind every key: a scout filled its form with 89 separate `--set` processes (35-50 s each), a strategist
with 73 `Edit` calls, and `--set scope[1].id` could not create the second row at all; the refusal that taught them
printed a `--set` command under every problem. Each test says the one behaviour it pins and what it protects; the keys
are the names K-A* of the spec (t-1243, section 3 parts A1 and A2).
"""
# Shared helpers of test_handoff_values.py, split by tools/test_split.py (TD-11c).
import hashlib
import json
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import FIXTURES, PLUGIN_ROOT, SCRIPTS, run_script
sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import handoff  # noqa: E402


CONTRACT = "s2-tester-to-strategist"


DISPATCH = "S2-qa-requirements-tester-1"


FIXTURE = FIXTURES / "s2-handoff-13877" / "work" / "handoffs" / f"{DISPATCH}.yaml"


# ------------------------------------------------------------------------------------------------ scaffolding
def _story(root: Path) -> Path:
    art = root / "artifacts" / "QA-9"
    (art / "work").mkdir(parents=True)
    return art


def _form(art: Path, dispatch: str = DISPATCH) -> Path:
    """A fresh S2 form, started the way the factory starts it (`handoff_init.py`)."""
    run_script("handoff_init.py", "--task", "QA-9", "--stage", "S2", "--role", "qa-requirements-tester",
               "--to", "qa-test-strategist", "--dispatch", dispatch, "--task-root", str(art))
    return art / "work" / "handoffs" / f"{dispatch}.yaml"


def _form5(art: Path, dispatch: str) -> Path:
    """A fresh S5 code-critic form: untouched at birth, which the S2 form is not."""
    run_script("handoff_init.py", "--task", "QA-9", "--stage", "S5", "--role", "qa-code-critic",
               "--to", "qa-automator", "--dispatch", dispatch, "--task-root", str(art))
    return art / "work" / "handoffs" / f"{dispatch}.yaml"


def _doc(form: Path):
    return handoff.parse(form.read_text(encoding="utf-8"))


def _hc(art: Path, form: Path, *flags: str):
    done = run_script("handoff_check.py", "--file", str(form), "--task-root", str(art), "--no-judge", *flags)
    out = done.stdout
    return done.returncode, (json.loads(out) if "--json" in flags and out.lstrip().startswith("{") else out)


def _hc_stdin(art: Path, form: Path, text: str, *flags: str):
    done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "handoff_check.py"), "--file", str(form),
                           "--task-root", str(art), "--no-judge", *flags],
                          input=text, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    return done.returncode, done.stdout


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _paths(problems) -> list:
    return [p["path"] if isinstance(p, dict) else p.path for p in problems]


def _green_copy(art: Path, edits: dict | None = None, dispatch: str = DISPATCH) -> Path:
    """The real 13877 S2 form in a story of its own, with `edits` ({path: value}, written as typed) applied."""
    form = art / "work" / "handoffs" / f"{dispatch}.yaml"
    form.parent.mkdir(parents=True, exist_ok=True)
    text = FIXTURE.read_text(encoding="utf-8")
    if "tried_note:" not in text and "\ntried:" not in text:
        # spec t-1765 X1 B-B: the S2 form carries `tried` now; the recorded 13877 fixture predates it, so the green copy states
        # why the table is empty (the contract's own door) - without it the "green" form is not green
        text += "\ntried_note: nothing was tried, the recorded fixture form predates the table\n"
    form.write_text(text, encoding="utf-8")
    doc = _doc(form)
    for path, value in (edits or {}).items():
        assert handoff.set_value(doc, path, value), path
    form.write_text(doc.text(), encoding="utf-8")
    return form
