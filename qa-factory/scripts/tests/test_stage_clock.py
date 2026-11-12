#!/usr/bin/env python3
"""A stage that finished before it started is named, and never silently timed as zero.

TP2-2553's "Run Timeline" carried S0 started at 13:20:00Z and finished at 11:42:43Z.
`retro_numbers.span_seconds` clamped the negative span with `max(0, ...)`, so the retro
printed the stage as taking no time, and nothing in `stage_done`, `validate_artifacts` or the
story listing said a word. A clock is a fact, not a decision: this file holds the stamp on the
record, the factory finding beside the write, the retro's line in place of the zero, and the
rule that none of it is ever a block or a question to the person.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import stage_done as SD  # noqa: E402
import retro_numbers as RN  # noqa: E402
from validate_artifacts import collect_errors, collect_findings  # noqa: E402

# The two stamps, exactly as 2553 left them.
REVERSED = {"status": "done", "role": "qa-scout",
            "started": "2026-09-23T13:20:00Z", "finished": "2026-09-23T11:42:43Z"}
FORWARD = {"status": "done", "role": "qa-scout",
           "started": "2026-09-23T11:42:43Z", "finished": "2026-09-23T13:20:00Z"}


def the_reversal_is_read_off_either_spelling_of_the_pair():
    check_eq("a stage that ran forwards is not an anomaly", SD.clock_anomaly(FORWARD), None)
    check_eq("the reversed pair is reported with both stamps as written",
             SD.clock_anomaly(REVERSED),
             {"started_at": "2026-09-23T13:20:00Z", "finished_at": "2026-09-23T11:42:43Z"})
    epoch = {"stage_started": 1789932444.7, "stage_finished": 1789932000.0}
    found = SD.clock_anomaly(epoch)
    check_in("the controller's epoch pair is read too", "2026-09-2", str(found))
    check("and rendered as a time a person can read", found["started_at"].endswith("+00:00"))
    check_eq("a half-stamped stage is not an anomaly, it is an unfinished stage",
             SD.clock_anomaly({"started": "2026-09-23T13:20:00Z"}), None)
    check_eq("and neither is a stamp nothing can parse",
             SD.clock_anomaly({"started": "yesterday", "finished": "today"}), None)
    check_eq("the whole pipeline lists them in stage order",
             [sid for sid, _ in SD.clock_anomalies({"stages": {"S2": dict(REVERSED),
                                                               "S0": dict(REVERSED),
                                                               "S1": dict(FORWARD)}})],
             ["S0", "S2"])
    check_eq("a pipeline with no stages block is not an error", SD.clock_anomalies({}), [])


def stage_done_still_writes_the_record_and_stamps_the_reversal():
    entry = SD.apply_stage({}, "S0", "done", "qa-scout", "digest",
                           at="2026-09-23T11:42:43+00:00")["stages"]["S0"]
    check_eq("a stage closed by this script runs forwards", entry.get("clock_anomaly"), None)

    pipeline = {"stages": {"S0": {"status": "running", "started": "2026-09-23T13:20:00Z"}}}
    entry = SD.apply_stage(pipeline, "S0", "done", "qa-scout", "digest",
                           at="2026-09-23T11:42:43Z")["stages"]["S0"]
    check_eq("a clock is a fact, not a refusal: the record is still written",
             entry["status"], "done")
    check_eq("and the reversal travels on it",
             entry.get("clock_anomaly"),
             {"started_at": "2026-09-23T13:20:00Z", "finished_at": "2026-09-23T11:42:43Z"})
    entry = SD.apply_stage(pipeline, "S0", "done", "qa-scout", "digest",
                           at="2026-09-23T14:00:00Z")["stages"]["S0"]
    check_not_in("a stamp the next write repairs leaves no stale anomaly behind",
                 "clock_anomaly", json.dumps(entry))


def the_write_hook_names_it_as_the_factory_s_and_blocks_nothing():
    root = temp_dir("qa-stage-clock-")
    try:
        path = root / "pipeline.json"
        path.write_text(json.dumps({"ticket": "TP2-2553", "gates": {},
                                    "stages": {"S0": dict(REVERSED)}}), encoding="utf-8")
        findings = collect_findings(path)
        check_eq("one finding, for the one stage", len(findings), 1)
        check_in("naming the stage", "S0 finished before it started", findings[0])
        check_in("and both stamps", "2026-09-23T13:20:00Z -> 2026-09-23T11:42:43Z", findings[0])
        check_in("whose defect it is", "owner: factory", findings[0])
        check_in("and what happens to the record", "The stage record stands", findings[0])
        check_eq("the write itself is not refused: no error mentions the clock",
                 [e for e in collect_errors(path) if "before it started" in e], [])
        path.write_text(json.dumps({"ticket": "T", "gates": {},
                                    "stages": {"S0": dict(FORWARD)}}), encoding="utf-8")
        check_eq("a story whose clocks run forwards produces no finding",
                 collect_findings(path), [])
    finally:
        cleanup(root)


def the_retro_prints_the_finding_in_place_of_the_clamped_zero():
    pipeline = {"stages": {"S0": dict(REVERSED), "S1": dict(FORWARD)}}
    times = RN.stage_times(pipeline)
    check_eq("a stage nobody can time has no duration at all",
             times["S0"]["seconds"], None)
    check_eq("instead of the zero `max(0, ...)` used to hand it",
             bool(times["S0"].get("clock_anomaly")), True)
    check_eq("the stage beside it keeps its real duration",
             times["S1"]["seconds"], 5837)

    data = {"task": "TP2-2553", "story": {"usd": 100.37, "tokens": 1},
            "by_stage": {"S0": {"dispatches": 1, "requests": 2, "tokens": 3, "cost": 1.0}},
            "stage_times": times, "orchestrator": {}, "by_role": {},
            "clock_anomalies": [dict(stamps, stage=sid)
                                for sid, stamps in SD.clock_anomalies(pipeline)]}
    text = RN.render(data)
    check_in("the stage row says what is wrong with it", "| clock anomaly |", text)
    check_not_in("and never that the stage took no time", "| 0m 0s |", text)
    check_in("the retro states the stage and both stamps",
             "**Clock anomaly (S0):** started 2026-09-23T13:20:00Z, "
             "finished 2026-09-23T11:42:43Z", text)
    check_in("and whose it is", "owner: factory", text)
    said = " ".join(RN.observations(data))
    check_in("the observations carry it too", "Stage S0 finished before it started", said)
    check_not_in("it is never handed to the person as work", "you", said.lower().split(".")[0])


def main():
    the_reversal_is_read_off_either_spelling_of_the_pair()
    stage_done_still_writes_the_record_and_stamps_the_reversal()
    the_write_hook_names_it_as_the_factory_s_and_blocks_nothing()
    the_retro_prints_the_finding_in_place_of_the_clamped_zero()
    finish("test_stage_clock")


if __name__ == "__main__":
    main()
