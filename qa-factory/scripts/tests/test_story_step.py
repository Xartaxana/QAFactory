#!/usr/bin/env python3
"""The story_step tests were split by command (TQ1-10): `test_story_step_{start,finish,decide,config,gate}.py` hold the checks,
`story_step_common.py` the shared helpers, and this module re-exports those helpers under the old name for the tests that say
`import test_story_step as STEP`. It holds no check of its own: selftest runs each new file as its own process.

`python -B test_story_step.py --all` runs the five files one after the other (the old single command).
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from story_step_common import (  # noqa: E402,F401
    CONFIG_FIELD,
    DECIDE_WORDS,
    FakeController,
    _StopAtAuthor,
    author_picture,
    author_picture_of,
    author_story,
    change_config,
    dispatch_record,
    finish_here,
    finish_s1,
    finish_s4,
    finish_s5,
    manifest_of,
    open_story,
    run_decide,
    s4_story,
    s5_window_story,
    seed,
    set_pipeline_block,
    set_rows,
    sha256_of,
)

# the re-export is the point of this module (`import test_story_step as STEP` in the other tests): naming it in __all__ keeps it
__all__ = [
    "CONFIG_FIELD", "DECIDE_WORDS", "FakeController", "_StopAtAuthor", "author_picture", "author_picture_of", "author_story",
    "change_config", "dispatch_record", "finish_here", "finish_s1", "finish_s4", "finish_s5", "manifest_of", "open_story",
    "run_decide", "s4_story", "s5_window_story", "seed", "set_pipeline_block", "set_rows", "sha256_of",
]

PARTS = ("start", "finish", "decide", "config", "gate")


def main() -> int:
    if "--all" not in sys.argv[1:]:
        print("test_story_step.py: no checks of its own; they are in " + ", ".join(f"test_story_step_{p}.py" for p in PARTS))
        return 0
    here = Path(__file__).resolve().parent
    code = 0
    for part in PARTS:
        code = subprocess.run([sys.executable, "-B", str(here / f"test_story_step_{part}.py")]).returncode or code
    return code


if __name__ == "__main__":
    sys.exit(main())
