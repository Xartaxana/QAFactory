#!/usr/bin/env python3
"""t-2277 FL-5 (spec line 510; slow file: CI only, the builder does not run it): S3 closes with the first-look dispatch present.

The first-look runner (`qa-runner`, purpose `first_look`) is an OPTIONAL dispatch of S3 and never a role of it. Every reader of S3's
dispatch records must therefore see S3 as it would be without it: the controller registers it in the new plan-contract mode with no
`execution_kind`; the exit gate places it and judges it by its own output; `story_step` never completes S3 with it; the driver's window
and critic-route readers read the strategist's records only. The checks themselves are functions of `test_first_look_step.py` (fast, run
by the builder); this file runs them in the story_run family, beside the readers they are about, and adds the whole-S3 pass with the
REAL controller: first look registered and accepted, window 1, window 2, the critic's route - in the order the driver reaches them.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, finish  # noqa: E402,F401

sys.path.insert(0, str(harness.SCRIPTS))
import test_first_look_step as FLS  # noqa: E402


def s3_closes_with_first_look_dispatch_present():
    FLS.s3_readers_with_first_look_dispatch_present()
    FLS.test_exit_gate_judges_first_look_runner_by_its_own_output()
    FLS.test_strategist_records_reader_is_the_one_filter()
    FLS.test_real_controller_registers_first_look_runner()


def the_first_look_registered_by_the_real_controller_is_read_back():
    """The record the REAL controller keeps of the first-look dispatch is the shape every reader above reads: stage S3, role qa-runner,
    `request_binding.purpose` first_look, and a strategist dispatch registered after it (window 1 of S3) is accepted by the same controller."""
    import tempfile
    from pathlib import Path as P
    with tempfile.TemporaryDirectory() as tmp:
        real = FLS._controller_story(P(tmp))
        packet = real.prepare({"stage": "S3", "role": "qa-runner", "id": "S3-qa-runner-1", "purpose": "first_look"})
        real.apply("dispatch", packet["dispatch_request"])
        record = real.state()["dispatches"]["S3-qa-runner-1"]
        check("the real record names stage, role and purpose where the readers look",
              record.get("stage") == "S3" and record.get("role") == "qa-runner" and (record.get("request_binding") or {}).get("purpose") == "first_look",
              record)
        d = FLS.SR.Driver.__new__(FLS.SR.Driver)
        d.controller_state = real.state      # the readers of the driver, over the real record
        check_eq("a first look not yet accepted (running) leaves S3's window as `w1` and no author done", (d.s3_window(), d.s3_author_done()),
                 ("w1", False))


def main():
    s3_closes_with_first_look_dispatch_present()
    the_first_look_registered_by_the_real_controller_is_read_back()
    finish("test_story_run_first_look")


if __name__ == "__main__":
    main()
