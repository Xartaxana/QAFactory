"""The detector rows that stay after X7-2 cut `check_test_code` (retry, broad status and skip markers are the code critic's to
judge now; their tests went with the body).

What is left is the sibling family the plan check reads (`plan_antipatterns`) through the one reader
(`assertion_detectors.shape_patterns`): a key that cannot be read means the built-in floor and one ORACLE_NOTES line naming
the key - never "no check" (FR-4, FR-41, FR-59).
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import check, check_eq, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

ROOT = temp_project("qa-factory-broad-status-")
use_project(ROOT)

import validate_artifacts as V  # noqa: E402  (imported AFTER the project root is set)

AD = V.AD
WORK = temp_dir("qa-broad-status-")
COUNTER = [0]

# --- K-floor: the built-in row is the shipped data -----------------------------------------------------------------------------
for key in V.DETECTOR_FLOORS:
    check_eq(f"K-floor: DETECTOR_FLOORS[{key!r}] is the shipped `{key}` row", list(V.DETECTOR_FLOORS[key]), AD.shape_patterns(key))
check_eq("K-floor: one key has a floor", sorted(V.DETECTOR_FLOORS), ["plan_antipatterns"])

# --- K-malformed: a key that cannot be read is the floor plus one note naming the key, never "no check" ----------------------------
shipped = json.loads(AD.DETECTORS_FILE.read_text(encoding="utf-8"))


def in_world(doc: dict, work):
    """Run `work()` with ASSERTION_DETECTORS_FILE pointing at a copy of the document; the variable is restored."""
    COUNTER[0] += 1
    where = WORK / f"detectors_{COUNTER[0]}.json"
    where.write_text(json.dumps(doc), encoding="utf-8")
    old = os.environ.get(AD.ENV_FILE)
    del V.ORACLE_NOTES[:]
    try:
        os.environ[AD.ENV_FILE] = str(where)
        return work()
    finally:
        if old is None:
            os.environ.pop(AD.ENV_FILE, None)
        else:
            os.environ[AD.ENV_FILE] = old


def without(key: str) -> dict:
    return {k: v for k, v in shipped.items() if k != key}


for label, doc in (("absent", without("plan_antipatterns")), ("empty", dict(shipped, plan_antipatterns=[])),
                   ("bad pattern", dict(shipped, plan_antipatterns=["(("])),
                   ("not a list", dict(shipped, plan_antipatterns="x"))):
    got = in_world(doc, lambda: ([bool(rx.search("the element is visible on the page")) for rx in
                                  V.detector_rows(Path("test-plan.md"), "plan_antipatterns")], list(V.ORACLE_NOTES)))
    check(f"K-malformed [plan_antipatterns {label}]: the floor still holds `is visible`", any(got[0]))
    check(f"K-malformed [plan_antipatterns {label}]: a note names `plan_antipatterns`",
          any("for `plan_antipatterns`" in n for n in got[1]), str(got[1]))
del V.ORACLE_NOTES[:]
got = in_world(shipped, lambda: ([bool(rx.search("the element is visible on the page")) for rx in
                                  V.detector_rows(Path("test-plan.md"), "plan_antipatterns")], list(V.ORACLE_NOTES)))
check_eq("K-malformed: the shipped document gives a hit and no note", (any(got[0]), got[1]), (True, []))

cleanup(WORK)
cleanup(ROOT)
finish("test_broad_status")
