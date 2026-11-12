#!/usr/bin/env python3
"""F14 (t-1699 N4-1, E16): a role whose agent file lists no Bash is never told to run `handoff_check.py`.

The two texts that told every role to run it are `Driver.exit_ask` (the `seen` text over the lines code filled in the form) and
`Driver.handoff_ladder` (the `exact` text of the mechanical third turn). `qa-test-strategist`, `qa-case-designer` and
`qa-case-critic` have no Bash (`agents/*.md` line 4); a role with no agent file is read as no Bash (`host_adapter.role_tools`).

HONEST NOTE (FR-33): this file proves the TEXT; whether such a role then fixes its form with its Edit tool is proven only by a live
run in which one of those roles meets an exit refusal.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_in, check_not_in, finish  # noqa: E402
from test_story_run_refusals import RES_DISPATCH, RES_PLAIN, res_driver, res_errors, res_fixture  # noqa: E402
from story_run_common import stub_calls  # noqa: E402

import story_run  # noqa: E402

NO_BASH = ("qa-test-strategist", "qa-case-critic", "qa-case-designer", "qa-no-such-role")      # the last has no agent file (K-N4-1c)

# Golden strings: today's texts (before F14), copied from the code of origin/main 95b07b82, for a role WITH Bash (K-N4-1b).
GOLDEN_SEEN = ("Read them: if one is wrong for your work, set it yourself with "
               "`handoff_check.py --file <form> --set <path>=<value>`.\n")
GOLDEN_EXACT = ("Two things and nothing else. 1) Your handoff form: fix exactly these 9 line(s), one field at a time, with "
                f"`handoff_check.py --file work/handoffs/{RES_DISPATCH}.yaml --set <path>=<value>` (never rewrite the file):\n")


def seen_of(role: str) -> str:
    """exit_ask's text for `role` when code filled one line of the form."""
    root, task_root, env = res_fixture("QA-9", RES_PLAIN)
    try:
        driver, _p = res_driver(root, env, "QA-9", [])
        driver.state.setdefault("form_filled", {})[RES_DISPATCH] = ["work.item[1].field = value 1"]
        return driver.exit_ask(role, RES_DISPATCH, ["s5_precheck.py: one finding"])
    finally:
        harness.cleanup(root)


def exact_of(role: str) -> str:
    """The mechanical third turn's prompt for `role` (the second prompt the stub claude was given)."""
    marked = res_errors(*[f"TC-{n}" for n in range(1, 10)])
    root, task_root, env = res_fixture("QA-9", RES_PLAIN)
    try:
        driver, _p = res_driver(root, env, "QA-9", marked)
        result = json.loads((task_root / "state/driver-runs" / f"{RES_DISPATCH}.json").read_text(encoding="utf-8"))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                driver.handoff(role, "S5", RES_DISPATCH, result)
        except story_run.Refusal:
            pass
        calls = stub_calls(root)
        return calls[1]["prompt"].replace("\r\n", "\n") if len(calls) > 1 else ""
    finally:
        harness.cleanup(root)


def k_n4_1() -> None:
    for role in NO_BASH:
        seen, exact = seen_of(role), exact_of(role)
        check("K-N4-1a premise (%s): the texts are really built (the form-filled line is shown; the third turn exists)" % role,
              "work.item[1].field = value 1" in seen and "Two things and nothing else" in exact)
        check_not_in(f"K-N4-1a ({role}): exit_ask names no handoff_check.py", "handoff_check.py", seen)
        check_not_in(f"K-N4-1a ({role}): the third turn names no handoff_check.py", "handoff_check.py", exact)
        check_in(f"K-N4-1a ({role}): exit_ask names the Edit tool and the form's path", f"work/handoffs/{RES_DISPATCH}.yaml with your Edit tool", seen)
        check_in(f"K-N4-1a ({role}): the third turn names the Edit tool, the form's path and the count",
                 f"1) Your handoff form work/handoffs/{RES_DISPATCH}.yaml: fix exactly these 9 line(s) with your Edit tool, one field at a time "
                 "(never rewrite the file):\n", exact)
        check_in(f"K-N4-1a ({role}): the refusal still comes back in the session (the exit check runs by itself)",
                 "the exit check runs by itself when you hand off; its refusal comes back in this session", seen)
    seen, exact = seen_of("qa-automator"), exact_of("qa-automator")
    check_in("K-N4-1b (qa-automator, Bash): exit_ask is today's text, byte for byte", GOLDEN_SEEN, seen)
    check_in("K-N4-1b (qa-automator, Bash): the third turn is today's text, byte for byte", GOLDEN_EXACT, exact)
    check_not_in("K-N4-1b: ...and has no Edit-tool wording", "with your Edit tool", seen + exact)


def main() -> None:
    k_n4_1()
    finish("exit_ask tools")


if __name__ == "__main__":
    main()
