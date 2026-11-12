#!/usr/bin/env python3
"""The driver: one story S0-S9, headless, with no orchestrator model between the boundaries.

On TP1-13797 the orchestrator spent $37.67 and 509 model turns, most of them re-reading
its own context between two deterministic commands. Every boundary of the pipeline is already
one command (`story_step.py start|bind|finish|where`, `gate_brief.py`, `controller.py
--operation gate-decision|rework|release`, `stage_done.py --set/--warn`, `waiver.py`), so the
loop that calls them needs no model at all:

    story_run.py --task T [--answer FILE] [--until gate_A|gate_B|end] [--dry-run]
                 [--model sonnet] [--plugin-dir DIR] [--project DIR] [--host claude|codex]
                 [--mr X | --branch X | --commit X] [--ungrounded] [--ticket-file P] [--env NAME]
                 [--branch-suffix S] [--skip-sources FILE] [--max-boundaries N]

The loop is `story_step.py where` -> the next action. A stage is `start` -> the role, run
as `claude -p --agent qa-factory:<role>` in the project root -> `bind` -> the handoff form is
checked the way the exit gate checks it (one `--resume` asking for the form) -> `finish`.

`--host codex` (or `driver.host` in config.json) runs the same loop over the Codex CLI: a role is
`codex exec --json -C <project> -` with the prompt on stdin, a continuation of the same dispatch is
`codex exec resume <thread id> --json -`, and the thread id is the dispatch's agent id. Nothing else of
the loop changes: the conductor, `bind`, the handoff check, `finish`, the in-flight record and the
journals are the same code. The driver WAITS on the child process, so no model turn is spent on
`wait_agent` polling (TP2-2406 under the desktop host: 930 polling requests, 129.9M input
tokens, 46% of the orchestrator's input). `--model` absent, the model is `default_model.codex` of
`references/driver-infra.json`. See `design/driver.md`, "The Codex host".
A gate, a halt, the S1 source review and the S9 retro question are written to
`qa-factory/artifacts/<T>/state/driver-question.md`, printed, and the driver exits 3; the
person's words come back as `--answer FILE` and are recorded by the conductor with the
factory's own commands, after which the loop goes on.

A refusal (a non-zero exit of any factory script, an exit-gate error the role did not repair)
first meets the known-refusal table below; what the table does not know goes to the
conductor — `claude -p` with a fresh context, `references/conductor.md` as its system prompt,
the refusal, `where`, and the files the refusal names. Its last line is one JSON object
`{"action": "continue|retry|ask_person|stop", "did": ..., "question": ...}`. At most three
conductor calls per boundary, then the person.

Exit codes: 0 the story finished (or `--until` was reached); 3 a person is needed (the
question is in `state/driver-question.md` and printed); 4 stopped after the conductor gave up
(`state/driver-question.md` carries the reason); 5 the infrastructure under `claude -p` failed
(a login, a usage limit, a broken answer that outlived its retries): nothing is asked, the message
and the command to go on are printed, `state/driver-state.json` `interrupted` keeps the cut-off
call, and the same command run again continues it; 1 an error of the driver's own.

Journals: `state/driver-runs.jsonl` (two lines per `claude -p`: a `launched` row before the process starts, the
call's own row when it ends - a `launched` row with no end row is a call that was running when the driver died) and `state/conductor.jsonl`
(one line per refusal handled) — `design/driver.md` documents both shapes.

Nothing here decides a test, a verdict or a bug: roles do, scripts do. The driver only calls
them in the order the phase files fix, and the conductor only records and repairs.
"""

import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from driver_chains import DriverChains  # noqa: E402
import module_facade  # noqa: E402
import driver_chains  # noqa: E402,F401
import driver_core  # noqa: E402,F401
import driver_timing  # noqa: E402,F401
import driver_runner  # noqa: E402,F401
import driver_dialog  # noqa: E402,F401
import driver_conductor  # noqa: E402,F401
import driver_dispatch  # noqa: E402,F401
import driver_s0  # noqa: E402,F401
import driver_sources  # noqa: E402,F401
import driver_stage_plan  # noqa: E402,F401
import driver_stage_build  # noqa: E402,F401
import driver_stage_s5  # noqa: E402,F401
import driver_stage_s6  # noqa: E402,F401
import driver_stage_s7  # noqa: E402,F401
import driver_stage_s8s9  # noqa: E402,F401
import driver_gates  # noqa: E402,F401
import driver_machine  # noqa: E402,F401
from driver_core import DriverCore, EXIT_ERROR, HOSTS, Stop  # noqa: E402
from driver_runner import DriverRunner  # noqa: E402
from driver_dialog import DriverDialog  # noqa: E402
from driver_conductor import DriverConductor  # noqa: E402
from driver_dispatch import DriverDispatch  # noqa: E402
from driver_s0 import DriverS0  # noqa: E402
from driver_sources import DriverSources  # noqa: E402
from driver_stage_plan import DriverStagePlan  # noqa: E402
from driver_stage_build import DriverStageBuild  # noqa: E402
from driver_stage_s5 import DriverStageS5  # noqa: E402
from driver_stage_s6 import DriverStageS6  # noqa: E402
from driver_stage_s7 import DriverStageS7  # noqa: E402
from driver_stage_s8s9 import DriverStageS8s9  # noqa: E402
from driver_gates import DriverGates  # noqa: E402
from driver_machine import DriverMachine  # noqa: E402


class Driver(DriverMachine, DriverGates, DriverStagePlan, DriverStageBuild, DriverStageS5, DriverStageS6, DriverStageS7, DriverStageS8s9, DriverS0, DriverSources, DriverDispatch, DriverConductor, DriverDialog, DriverRunner, DriverCore, DriverChains):

    pass


def main() -> int:
    # FR-43 (t-363 B2, B-253 g): the driver's log is read WHILE it runs, and stdout to a file is block-buffered, so on
    # 02.10 the log of a driver that died silently was empty. Line-buffered from the first line; a stream with no
    # `reconfigure` (a StringIO in a test, a pipe under an old Python) is skipped without a word (the `except`).
    try:
        import console_io
        console_io.utf8_stdio(line_buffering=True)
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--task", required=True)
    ap.add_argument("--answer", help="a file with the person's words for the open question")
    ap.add_argument("--until", choices=["gate_A", "gate_B", "end"], default="end")
    ap.add_argument("--dry-run", action="store_true", help="print the actions for the current state, run nothing")
    ap.add_argument("--model", default=None,
                    help="the model the roles run under: claude - default sonnet; codex - default "
                         "`default_model.codex` of references/driver-infra.json")
    ap.add_argument("--host", choices=list(HOSTS), default=None,
                    help="the CLI the roles run under: claude (`claude -p`, the default) or codex (`codex exec`); "
                         "absent, `driver.host` of config.json, else claude")
    ap.add_argument("--plugin-dir", help="plugin root (default: this script's own)")
    ap.add_argument("--project", help="project root (default: the nearest qa-factory/config.json above cwd)")
    ap.add_argument("--mr")
    ap.add_argument("--branch")
    ap.add_argument("--commit")
    ap.add_argument("--ungrounded", action="store_true")

    def pair(value: str, what: str, door: str) -> tuple:
        """`<name>=<word>` as a pair, or an argparse refusal that names the form (FR-1, FR-2: the door is the corrected flag)."""
        name, sep, word = str(value).partition("=")
        name, word = name.strip(), word.strip()
        if not (sep and name and word) or "." in name:
            raise argparse.ArgumentTypeError(f"`{value}` is not {what}. {door}")
        return name, word

    def side_flag(value: str) -> tuple:
        name, word = pair(value, "a side and its reality", "Give --side <name>=<reality>, the name without a dot.")
        import stage_done      # the ONE reader of the reality words (`references/side-realities.json`) is the writer's own check
        try:
            stage_done.coerce_value(f"sides.{name}.reality", word)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"--side {value}: {exc}. Start again with --side {name}=<one of those words>.")
        return name, word

    def reference_flag(value: str) -> tuple:
        return pair(value, "a side and the stand that runs its old version", "Give --reference <side>=<stand>, the side without a dot.")

    ap.add_argument("--side", action="append", type=side_flag, metavar="NAME=REALITY",
                    help="a side of the product that is not real on this stand, e.g. backend=substituted (repeatable); "
                         "the words are those of references/side-realities.json")
    ap.add_argument("--reference", action="append", type=reference_flag, metavar="SIDE=STAND",
                    help="the stand that still runs the OLD version of a side, to be walked as the reference (repeatable)")
    ap.add_argument("--ticket-file")
    ap.add_argument("--env")
    ap.add_argument("--branch-suffix", default="")
    ap.add_argument("--no-trace", action="store_true", dest="no_trace",
                    help="experiment: nothing leaves the project (P8)")
    ap.add_argument("--skip-sources", dest="skip_sources", metavar="FILE",
                    help="a text file, one source per line and why it is left out: read when a story STARTS, "
                         "before anything is fetched (B-231)")
    ap.add_argument("--max-boundaries", default=80)
    ns = ap.parse_args()
    if ns.skip_sources:
        # The driver changes into the project root (`Driver.__init__`), so a path the person typed
        # relative to THEIR folder would point somewhere else from then on.
        ns.skip_sources = str(Path(ns.skip_sources).resolve())
    try:
        driver = Driver(ns)
    except SystemExit as exc:  # hooklib.require_project refused
        return int(exc.code or EXIT_ERROR)
    except Stop as stop:       # the host cannot start (`Driver.host_refusal`): the reason, the code, no traceback
        print(f"story_run: stopped — {stop.reason}", flush=True)
        return stop.code
    if ns.dry_run:
        return driver.describe()
    return driver.run()


module_facade.install(__name__, [driver_chains, driver_core, driver_timing, driver_runner, driver_dialog, driver_conductor, driver_dispatch, driver_s0, driver_sources, driver_stage_plan, driver_stage_build, driver_stage_s5, driver_stage_s6, driver_stage_s7, driver_stage_s8s9, driver_gates, driver_machine])


if __name__ == "__main__":
    sys.exit(main())
