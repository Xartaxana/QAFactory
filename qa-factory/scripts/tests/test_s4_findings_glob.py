#!/usr/bin/env python3
"""t-2089 TR3-5 fix round (AR-13, AR-22): the S4 readers of `critic-findings` never read an S5 file.

The S5 critic writes `work/test-code/critic-findings-<dispatch>.md`; the S4 repair round, gate-A repair and gate-A text read the case
critic's file under `work/test-cases/` only, through `Driver.s4_findings`.
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import story_run  # noqa: E402


def reader(root: Path):
    fake = SimpleNamespace(task_root=root)
    fake.newest = lambda pattern: story_run.Driver.newest(fake, pattern)
    return lambda: story_run.Driver.s4_findings(fake)


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    s4 = reader(root)
    check("no file at all: None, no refusal", s4() is None)
    s5 = root / "work/test-code/critic-findings-S5-qa-code-critic-1.md"
    s5.parent.mkdir(parents=True)
    s5.write_text("S5", encoding="utf-8")
    check("an S5 file alone is not read by S4", s4() is None)
    a = root / "work/test-cases/area/critic-findings.md"
    a.parent.mkdir(parents=True)
    a.write_text("S4", encoding="utf-8")
    newer = a.stat().st_mtime + 100                      # the S5 file is genuinely the newer one (t-2098 F3)
    os.utime(s5, (newer, newer))
    check("the S5 file is newer than the S4 file", s5.stat().st_mtime > a.stat().st_mtime)
    check_eq("an S4 file in an area folder is read, though the S5 file is newer", s4(), a)
    b = root / "work/test-cases/critic-findings.md"
    b.write_text("S4 top", encoding="utf-8")
    check("an S4 file at the top of test-cases is read", s4() in (a, b))
finish("test_s4_findings_glob")
