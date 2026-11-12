#!/usr/bin/env python3
"""`waiver.py --stage ... --block "wait_existing_job"` has to reach the dispatch.

A stage override passes stage ERRORS, and a dispatch nobody is doing is not one. On
TP1-15045 the person said "it's dead, go on", this factory wrote their words into
`stage_overrides[]`, printed OK — and `next` went on answering `wait_existing_job` for the
rest of the story. The recorded word has to travel to the thing that is actually holding the
story, which is `controller.py --operation release`, and the person has to be told which of
the two happened. Run against the real controller, never against a stub: the whole point of
this file is that the two ends are connected.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import waiver  # noqa: E402
from controller import Controller  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_state as BASE  # noqa: E402

DISPATCH = "S1-qa-scout-1"


def story(root: Path) -> Controller:
    """One story with one dispatch open and nobody doing it."""
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    task = root / "qa-factory" / "artifacts" / root.name
    task.mkdir(parents=True)
    controller = Controller(task)
    controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                    "known_paths": {"root": str(task)},
                                    "idempotency_key": "init"})
    BASE.accept_stage(controller, task, "S0")
    controller.apply("dispatch", {"id": DISPATCH, "stage": "S1", "role": "qa-scout",
                                  "scope": [], "input_hash": "ctx", "budget": {"requests": 30},
                                  "known_paths": {"root": str(task)}, "idempotency_key": "d-1"})
    return controller


def listed(task_id: str, **kw) -> tuple:
    """(exit code, what `waiver.show` printed) - the same function the `--list` command runs."""
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = waiver.show(task_id, **kw)
    return code, out.getvalue()


def critics_fixture(pipeline: Path, state: dict) -> None:
    """t-373 F1-F3: the critic's fixture of t-371, each line as the person must read it. The list lands in a QUESTION packet,
    so the whole rendered list obeys the question rules - not the weaker report rules - and no line shows a block KEY
    (a gap's or a profile's id, a row id, a configuration key, a stage code standing alone)."""
    import human_text
    state["stage_overrides"] = [
        {"stage": "S5", "match": "stand gap: RP-api", "decision": "go on, I test admin by hand", "at": "2026-10-03T08:00:00+00:00"},
        {"stage": "S1", "match": "SG-resume-none", "decision": "fine: go", "at": "2026-10-02T09:00:00+00:00"},
        {"stage": "S3", "match": "SG-command", "decision": "ok", "at": "2026-10-01T09:00:00+00:00"},
        {"stage": "S5", "match": "executor unavailable: api", "decision": "go on", "at": "2026-10-01T09:00:00+00:00",
         "revoked_at": "2026-10-02T09:00:00+00:00"},
        {"stage": "S7", "match": "S7 triage incomplete", "decision": "yes", "at": "2026-10-02T09:00:00+00:00"},
        {"stage": "S2", "match": "OBL-7 not covered", "decision": "skip it", "at": "2026-10-02T09:00:00+00:00"},
        {"stage": "S5", "match": "profiles[api].commands.one_test is empty", "decision": "go", "at": "2026-10-02T09:00:00+00:00"},
        {"stage": "S5", "match": "stand gap: the stand has no login for the admin role", "decision": "go on, I test admin by hand",
         "at": "2026-10-03T08:00:00+00:00"},
    ]
    state["gate_waivers"] = [{"gate": "A", "requirement": "R-9", "decision": "scope is enough", "at": "2026-09-30T12:00:00+00:00"},
                             {"gate": "B", "requirement": "REQ-12", "decision": "ship", "at": "2026-09-30T12:00:00+00:00"}]
    pipeline.write_text(json.dumps(state), encoding="utf-8")
    code, text = listed(pipeline.parent.name)
    shown = [(p["rule"], p["found"]) for p in human_text.shape_problems(text, kind="question")]
    print("RENDERED LIST (t-373 critic fixture):\n" + text + f"question problems: {shown}")
    check_eq("B1 (t-373 F3): the whole rendered list obeys the QUESTION rules (the packet's own check): no problem", shown, [])
    lines = text.splitlines()
    check_eq("B1 (t-373 F1): `stand gap: RP-api` is a phrase, never the gap's key", lines[0].split(" · ")[1], waiver.STAND_GAP_BLOCK)
    check_eq("B1 (t-373 F1): `executor unavailable: api` is a phrase, never the profile's key", lines[3].split(" · ")[1], waiver.HANDED_BLOCK)
    check_eq("B1 (t-373 F1): a gap block with WORDS after the prefix is the factory's phrase already: shown as recorded",
             lines[7].split(" · ")[1], "stand gap: the stand has no login for the admin role")
    check_eq("B1 (t-373 F3): a stage code standing alone is said with the stage's name", lines[4].split(" · ")[1],
             "Triage (S7) triage incomplete")
    check_eq("B1 (t-373 F3): a row id nobody explained and a configuration key are the generic phrase",
             (lines[5].split(" · ")[1], lines[6].split(" · ")[1], lines[8].split(" · ")[1]),
             (waiver.GENERIC_BLOCK, waiver.GENERIC_BLOCK, "R-9"))
    check_eq("B1 (t-373 F3): ...a gate waiver's requirement goes through the same filter (`REQ-12`)", lines[9].split(" · ")[1], waiver.GENERIC_BLOCK)
    import refusal_registry
    check_eq("B1 (t-373 F2): EVERY registry id is the generic phrase - the shape filter alone would let the ids it does not know through",
             sorted({e["id"] for e in refusal_registry.REGISTRY if waiver.block_in_words(e["id"]) != waiver.GENERIC_BLOCK}), [])
    for token in ("RP-api", "OBL-7", "REQ-12", "one_test", "SG-"):
        check_not_in(f"B1 (t-373): no `{token}` in the person's list", token, text)


def person_list(root: Path, task_id: str) -> None:
    """t-363 B1: `--list` is the list a PERSON reads, one line per waiver: the stage, the block in words, their word
    whole, the date - never a script name, a flag, an exit code, a dispatch id or a block key (owner's rule, t-342)."""
    import human_text
    pipeline = root / "qa-factory" / "artifacts" / task_id / "pipeline.json"
    state = json.loads(pipeline.read_text(encoding="utf-8"))
    registry_id = "SG-resume-none"
    import refusal_registry
    next(e for e in refusal_registry.REGISTRY if e["id"] == registry_id)
    quoted = 'he said: "go on, the stand is theirs" and then: stop'
    state["stage_overrides"] = [
        {"stage": "S5", "match": "executor unavailable: pytest", "decision": "go on, I will run them myself",
         "at": "2026-10-03T05:41:12+00:00", "by": "human"},
        {"stage": "S1", "match": registry_id, "decision": quoted, "at": "2026-10-02T09:00:00+00:00"},
        {"stage": "S2", "match": "waiver.py --task QA-1 --stage S2 --block x", "decision": "fine", "at": "2026-10-02"},
        {"stage": "S6", "match": "*", "decision": "ship it", "at": "2026-10-01T00:00:00+00:00"},
        {"stage": "S4", "match": "wait_existing_job on S4-qa-case-designer-1", "decision": "dead, go on",
         "at": "2026-10-01T00:00:00+00:00"},
    ]
    state["gate_waivers"] = [{"gate": "A", "requirement": "R-9", "decision": "scope is enough",
                              "at": "2026-09-30T12:00:00+00:00", "by": "human"}]
    pipeline.write_text(json.dumps(state), encoding="utf-8")
    code, text = listed(task_id)
    lines = text.splitlines()
    check_eq("B1: the list exits clean and has one line per waiver, no cap", (code, len(lines)), (0, 6))
    check_eq("B1: a stage override reads `<stage> · <the block> · your word: \"<words>\" · <date>`", lines[0],
             f'Automation (S5) · {waiver.HANDED_BLOCK} · your word: "go on, I will run them myself" · 2026-10-03')
    check_eq("B1 (t-373 F2): a block that is a registry id is the generic phrase - the registry's `refuses` text is a role's (field "
             "names, state paths) - and the words stay whole (quotes and a colon)",
             lines[1], f'Context and grounding (S1) · {waiver.GENERIC_BLOCK} · your word: "{quoted}" · 2026-10-02')
    check_not_in("B1 (t-373 F2): ...and nothing of the entry's own text reaches the person", "pipeline.json", lines[1])
    for hard in ("SG-command", "PT-human-word"):         # registry entries whose text names a script and a flag
        check_eq(f"B1: a registry id whose own text carries a script name ({hard}) is the generic phrase, not the script",
                 waiver.block_in_words(hard), waiver.GENERIC_BLOCK)
    check_in("B1: free words with quotes and a colon come back whole", quoted, text)
    check("B1: a block string with a script name recorded before this change is replaced by the generic phrase",
          lines[2].startswith("Understanding and size (S2) · a check the factory ran · your word: \"fine\""), lines[2])
    check_eq("B1: `*` is said in words", lines[3].split(" · ")[1], waiver.EVERY_BLOCK)
    check("B1: a dispatch id inside a stored block is replaced too", lines[4].split(" · ")[1] == waiver.GENERIC_BLOCK, lines[4])
    check_eq("B1: a gate waiver is a line of its own", lines[5],
             'gate A · R-9 · your word: "scope is enough" · 2026-09-30')
    for token in ("waiver.py", "--", "exit ", "S4-qa-", "wait_existing_job", registry_id, "T00:"):
        check_not_in(f"B1: no `{token}` in the person's list", token, text)
    check_eq("B1: the list obeys human-questions.md (human_text, report rules)", human_text.problems(text, kind="report"), [])
    critics_fixture(pipeline, state)
    # a record that is not complete never raises: its slot reads `not recorded` (a pipeline.json from an older build)
    state["stage_overrides"] = [{"stage": "S1"}, "not an object", {"match": "source material unavailable", "decision": " "},
                                {"stage": "S9", "match": "x", "decision": "y"}]
    state["gate_waivers"] = [{"requirement": "R-1"}]
    pipeline.write_text(json.dumps(state), encoding="utf-8")
    code, text = listed(task_id)
    check_eq("B1: an incomplete record is a line with `not recorded` slots, never a KeyError", (code, text.splitlines()),
             (0, ["Context and grounding (S1) · not recorded · no words recorded · not recorded",
                  "not recorded · source material unavailable · no words recorded · not recorded",
                  "Closure and retro (S9) · x · your word: \"y\" · not recorded",
                  "not recorded · R-1 · no words recorded · not recorded"]))
    # a pass the person took back stays in their list, marked at the end of its line (FR-8: their own history, never hidden)
    state["stage_overrides"] = [{"stage": "S1", "match": "source material unavailable", "decision": "go on without the video",
                                 "at": "2026-10-01T10:00:00+00:00", "revoked_at": "2026-10-02T10:00:00+00:00",
                                 "revoked_by": "human", "revoked_decision": "the video is attached now"},
                                {"stage": "S5", "match": "executor unavailable: pytest", "decision": "go on", "at": "2026-10-03"}]
    state["gate_waivers"] = []
    pipeline.write_text(json.dumps(state), encoding="utf-8")
    code, text = listed(task_id)
    check_eq("B1: a revoked override is marked `(withdrawn)` at the end of its line and still listed; a live one is not marked",
             (code, text.splitlines()),
             (0, ['Context and grounding (S1) · source material unavailable · your word: "go on without the video" · 2026-10-01 (withdrawn)',
                  f'Automation (S5) · {waiver.HANDED_BLOCK} · your word: "go on" · 2026-10-03']))
    check_eq("B1: ...and the list with a withdrawn line obeys the text rules", human_text.problems(text, kind="report"), [])
    state["stage_overrides"], state["gate_waivers"] = [], []
    pipeline.write_text(json.dumps(state), encoding="utf-8")
    check_eq("B1: no waivers at all prints nothing (so the gate packet has no section)", listed(task_id), (0, ""))
    # the machine form, and the command line the gate packet runs
    state["stage_overrides"] = [{"stage": "S5", "match": "executor unavailable: pytest", "decision": "go on",
                                 "at": "2026-10-03T05:41:12+00:00"}]
    pipeline.write_text(json.dumps(state), encoding="utf-8")
    code, machine = listed(task_id, machine=True)
    check_eq("B1: `--json` is the records as recorded, for code", (code, json.loads(machine)),
             (0, {"stage_overrides": state["stage_overrides"], "gate_waivers": []}))
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    cli = harness.run_script("waiver.py", "--task", task_id, "--list", cwd=root, env=env)
    check_eq("B1: the command line's default is the person form", (cli.returncode, cli.stdout.strip()),
             (0, f'Automation (S5) · {waiver.HANDED_BLOCK} · your word: "go on" · 2026-10-03'))
    cli = harness.run_script("waiver.py", "--task", task_id, "--list", "--json", cwd=root, env=env)
    check_eq("B1: ...and `--json` is the machine form", (cli.returncode, "stage_overrides" in json.loads(cli.stdout)), (0, True))
    bare = harness.run_script("waiver.py", "--task", task_id, "--json", cwd=root, env=env)
    check_eq("B1: `--json` alone is refused (it is the machine form of --list)", bare.returncode, 2)
    gone = harness.run_script("waiver.py", "--task", "NO-SUCH-TASK", "--list", cwd=root, env=env)
    check_eq("B1: a story with no readable pipeline.json is a non-zero exit with the sentence on stderr, nothing on stdout",
             (gone.returncode, gone.stdout, "no readable pipeline.json" in gone.stderr), (waiver.EXIT_NO_PIPELINE, "", True))


STAGES_MODEL = SCRIPTS.parent / "references" / "stages.json"
STANDING_BLOCK_CMP3 = "window_record.py --review-receipt"      # cmp3 18:09: a name the standing refusal does not hold


def stage_run(task_id: str, stage: str, block: str, words: str = "go on, I accept it") -> tuple:
    """(exit code, stdout, stderr) of `waiver.run_stage` - the function the command line runs."""
    import contextlib
    import io
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = waiver.run_stage(task_id, stage, block, words, "human")
    return code, out.getvalue(), err.getvalue()


def standing_pipeline(task_dir: Path, task_id: str, *, done_through: str = "S4", approved: bool = True) -> None:
    """A story whose guard has nothing to say about the stage after `done_through` (gate A approved), or - with `done_through`
    short of the stage - one whose guard refuses; no override is recorded."""
    model = json.loads(STAGES_MODEL.read_text(encoding="utf-8"))
    order = [s["id"] for s in model["stages"]]
    stages = {sid: {"status": "done" if order.index(sid) <= order.index(done_through) else "pending"} for sid in order}
    gates = {"A": {"status": "approved", "decision": "approved"}} if approved else {}
    (task_dir / "pipeline.json").write_text(json.dumps({"ticket": task_id, "stages": stages, "gates": gates}), encoding="utf-8")
    (task_dir / "state" / "standing-refusal.json").unlink(missing_ok=True)       # a case starts with no refusal standing
    if order.index(done_through) >= order.index("S5"):    # what a real S5 leaves; S6-S8 are refused without it (C4-1)
        (task_dir / "work").mkdir(exist_ok=True)
        (task_dir / "work" / "automation-manifest.json").write_text('{"tests": [], "unresolved": []}', encoding="utf-8")


def put_standing(task_dir: Path, stage: str, lines, doors=None, raw: str | None = None) -> Path:
    """What the driver leaves for `block_standing`: `state/standing-refusal.json` (t-722 §3.1; `doors` is the Lead's edge of
    t-768). `raw` writes the file byte for byte (a broken or empty record)."""
    path = task_dir / "state" / "standing-refusal.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"stage": stage, "lines": lines}
    if doors is not None:
        record["doors"] = doors
    path.write_text(raw if raw is not None else json.dumps(record), encoding="utf-8")
    return path


def recorded(task_dir: Path) -> list:
    return json.loads((task_dir / "pipeline.json").read_text(encoding="utf-8")).get("stage_overrides") or []


def standing_refusal(root: Path, task_id: str) -> None:
    """t-722 C2-5 (class K4): a `--block` is recorded only against a refusal that holds it; "block lifted" is printed only for
    what the guard re-run (or the refusal's own door) said. WR numbers are the spec's (§7); D* are the door pins of t-768."""
    from role_cli import REPAIR_MARKER
    task_dir = root / "qa-factory" / "artifacts" / task_id
    controller_problems = ["the qa-code-critic window is not receipted: no review receipt for TC-1",
                           "no window record for TC-2: the probe receipt cannot be read"]
    # the refusal as the controller words it (C:3143-3148): problems joined with "; ", its own prose, the door in backticks
    controller_text = ("; ".join(controller_problems) + ". These are the review's own receipts, not the person's to produce. "
                       f"{REPAIR_MARKER}. If a person accepts the window without them: `"
                       + f'waiver.py --task {task_id} --stage S5 --block "not receipted" --words-file <file>' + "`.")
    lines = waiver.refusal_parts(controller_text)
    check_eq("WR0: the controller's text reads as its problems apart, the door in backticks cut (the record's `lines`)",
             (lines[0], len(lines), "waiver.py --task" in " ".join(lines)), (controller_problems[0], 2, False))

    # WR1 - cmp3 18:09: the block the standing refusal does not hold is refused, nothing is written
    standing_pipeline(task_dir, task_id)
    put_standing(task_dir, "S5", lines)
    before = (task_dir / "pipeline.json").read_text(encoding="utf-8")
    code, out, err = stage_run(task_id, "S5", STANDING_BLOCK_CMP3)
    check_eq("WR1: a block in no line of the standing refusal exits 2", code, waiver.EXIT_BAD_ARGS)
    check_eq("WR1: ...and pipeline.json is as it was", (task_dir / "pipeline.json").read_text(encoding="utf-8"), before)
    check_in("WR1: ...the standing line is the first closed option", f"  1. {lines[0]}", err)
    check_in("WR1: ...and the other door is named: keep the words with --remark", "--remark", err)
    check_in("WR1: ...with the words by file", "--words-file", err)
    check_not_in("WR1: ...and nothing says the block was lifted", "block lifted", out + err)

    # WR2 - a part only one line holds: recorded, said to be unverified, never lifted
    code, out, err = stage_run(task_id, "S5", "not receipted")
    check_eq("WR2: a block that is a part of a standing line is recorded", (code, len(recorded(task_dir))), (0, 1))
    check_in("WR2: ...against the refusal", "recorded against the refusal standing at S5", out)
    check_in("WR2: ...naming the line", f"1. {lines[0]}", out)
    check_in("WR2: ...and says it was not verified", "not verified", out)
    check_not_in("WR2: ...and never `block lifted`", "block lifted", out + err)

    # WR3 - nothing known to stand (the orchestrator road, K4-NP3): recorded, not verified, never lifted
    nothing_standing = ("not verified: no refusal of S5 is known to this command (the driver records the refusal it is "
                        "handling; none is open now)")
    other_record = "not verified: there is no record of S5 this command can read - the block is recorded, not verified"
    for label, prepare, said in (("no record at all", lambda: put_standing(task_dir, "S5", lines).unlink(), nothing_standing),
                                 ("a record of another stage", lambda: put_standing(task_dir, "S3", lines), other_record),
                                 ("a record with neither lines nor doors", lambda: put_standing(task_dir, "S5", [], doors=[]),
                                  nothing_standing),
                                 ("a record of lines that are not strings", lambda: put_standing(task_dir, "S5", [3, None, " "]),
                                  nothing_standing)):
        standing_pipeline(task_dir, task_id)
        prepare()
        code, out, err = stage_run(task_id, "S5", STANDING_BLOCK_CMP3)
        check_eq(f"WR3: {label}: the block is recorded", (code, len(recorded(task_dir))), (0, 1))
        check_in(f"WR3: {label}: not verified, in the words of what is known (t-782 M1)", said, out)
        check_not_in(f"WR3: {label}: never lifted, and no unreadable-record line", "block lifted", out)
        check_not_in(f"WR3: {label}: ...", waiver.STANDING_UNREADABLE, out)
        if said is other_record:
            check_not_in(f"WR3: {label}: `none is open now` is not said over a refusal recorded elsewhere", "none is open now", out)
    for label, raw in (("an empty file", ""), ("broken JSON", "{"), ("a JSON list", "[]")):
        standing_pipeline(task_dir, task_id)
        put_standing(task_dir, "S5", [], raw=raw)
        code, out, err = stage_run(task_id, "S5", STANDING_BLOCK_CMP3)
        check_eq(f"WR3: {label} reads as unknown, recorded", (code, len(recorded(task_dir))), (0, 1))
        check_in(f"WR3: {label}: the unreadable record is said", waiver.STANDING_UNREADABLE, out)
        check_in(f"WR3: {label}: and not verified, as what cannot be read", other_record, out)
        check_not_in(f"WR3: {label}: `none is open now` is not established over an unreadable record", "none is open now", out)
        check_not_in(f"WR3: {label}: never lifted", "block lifted", out)

    # WR4 - the factory's own constants are known by FORM; the record is not read for them (a broken one proves it)
    for block in waiver.OWN_FORM_BLOCKS:
        standing_pipeline(task_dir, task_id)
        put_standing(task_dir, "S5", ["a line that holds none of the constants"], raw="{")
        code, out, err = stage_run(task_id, "S5", block)
        check_eq(f"WR4: `{block}` is recorded", (code, len(recorded(task_dir))), (0, 1))
        check_in(f"WR4: `{block}` prints the constant's own line", "recorded for the step of the factory that asked for this word", out)
        check_not_in(f"WR4: `{block}`: the record was not read, nothing says lifted", "block lifted", out)
        check_not_in(f"WR4: `{block}`: ...nor that the record could not be read", waiver.STANDING_UNREADABLE, out)
    standing_pipeline(task_dir, task_id)
    put_standing(task_dir, "S5", ["one line"])
    code, out, err = stage_run(task_id, "S5", "Stand Not   Confirmed")
    check_eq("WR4b: the constant is matched whole, case and spaces folded", (code, len(recorded(task_dir))), (0, 1))
    code, out, err = stage_run(task_id, "S5", "stand not confirmed or else")
    check_eq("WR4b: ...a longer text that merely contains it is no constant: held against the record, refused", code, waiver.EXIT_BAD_ARGS)

    # WR5 - `*` is legal; with a record it names every line
    standing_pipeline(task_dir, task_id)
    put_standing(task_dir, "S5", ["first problem", "second problem"])
    code, out, err = stage_run(task_id, "S5", "*")
    check_eq("WR5: `*` is recorded against a record of two lines", (code, len(recorded(task_dir))), (0, 1))
    check_in("WR5: ...both lines are named", "1. first problem", out)
    check_in("WR5: ...both", "2. second problem", out)
    standing_pipeline(task_dir, task_id)
    put_standing(task_dir, "S5", ["x"], raw="[]")
    check_eq("WR5: `*` with nothing known is recorded too (never refused)", stage_run(task_id, "S5", "*")[0], 0)

    # WR6 - the listing ceiling, AT and BEYOND
    many = [f"problem number {n:02d} of the refusal" for n in range(1, 22)]
    for count, more in ((20, False), (21, True)):
        standing_pipeline(task_dir, task_id)
        put_standing(task_dir, "S5", many[:count])
        code, out, err = stage_run(task_id, "S5", "no such text anywhere")
        check_eq(f"WR6: {count} standing lines: refused", code, waiver.EXIT_BAD_ARGS)
        check_in(f"WR6: {count} lines: the 20th is listed", "20. problem number 20 of the refusal", err)
        check_eq(f"WR6: {count} lines: the 21st is never listed", "21. " in err, False)
        check_eq(f"WR6: {count} lines: `(+1 more` {'is' if more else 'is not'} printed", "(+1 more" in err, more)
        if more:
            check_in("WR6: ...with the file that holds them", "standing-refusal.json", err)
    standing_pipeline(task_dir, task_id)
    put_standing(task_dir, "S5", many)
    code, out, err = stage_run(task_id, "S5", "*")
    check_eq("WR6: the success list is capped the same way", ("20. problem number 20" in out, "(+1 more" in out), (True, True))

    # WR7 - a text only in the hint of a guard line is no line of the refusal (the negative pin of the finding 9)
    standing_pipeline(task_dir, task_id, done_through="S3")
    import stage_guard
    guard = stage_guard.dispatch_errors(json.loads((task_dir / "pipeline.json").read_text(encoding="utf-8")), "S5", journal=False)
    check("WR7: the fixture's guard refuses and its line carries the hint with the command",
          bool(guard) and "waiver.py --task" in guard[0], str(guard))
    # t-722 §L-7: the guard is an advisor, the driver's record is the carrier - a guard alone refuses nothing
    code, out, err = stage_run(task_id, "S5", "waiver.py --task")
    check_eq("WR7: guard non-empty and NO record: a block found only in the hint is recorded, not refused",
             (code, len(recorded(task_dir))), (0, 1))
    check_in("WR7: ...naming the guard's standing line, whole (t-782 M1)",
             "the guard of S5 holds 1 line(s), and the block passes none of them:\n  1. stage S5 cannot start", out)
    check_in("WR7: ...and saying what is not known", "not verified: the driver's record of S5 is empty - the block is recorded, "
             "not verified", out)
    check_not_in("WR7: ...never `none is open now` over a standing guard", "none is open now", out)
    check_not_in("WR7: ...and never lifted", "block lifted", out + err)
    # t-782 P1 / P1b: a rehearsal door at gate A (the guard always holds a line there) - recorded, the line named
    for label, kw, first in (("P1 required stages not done", {"done_through": "S3"}, "1. stage S5 cannot start"),
                             ("P1b gate A not approved", {"approved": False}, "1. stage S5 is past gate A")):
        standing_pipeline(task_dir, task_id, **kw)
        code, out, err = stage_run(task_id, "S5", "executor unavailable: e2e-ui")
        check_eq(f"M1 {label}: the rehearsal door is recorded", (code, len(recorded(task_dir))), (0, 1))
        check_in(f"M1 {label}: ...the guard's standing line is named", first, out)
        # C4-3: `executor unavailable: <profile>` is a NAME its reader acts on, no longer "unknown" - the record is not read
        # for it, and the line says so (the guard's standing lines above are still named, never a lift)
        check_in(f"M1 {label}: ...recorded as a name its reader acts on, not verified", "read by contract:handed_profiles", out)
        check_in(f"M1 {label}: ...the standing refusal was not held against it", "not verified here", out)
        check_not_in(f"M1 {label}: ...and `none is open now` is not said", "none is open now", out)
        check_not_in(f"M1 {label}: ...nor `block lifted`", "block lifted", out)
    standing_pipeline(task_dir, task_id, done_through="S3", approved=False)
    code, out, err = stage_run(task_id, "S5", "executor unavailable: e2e-ui")
    check_in("M1: a guard of two lines: both are named", "holds 2 line(s)", out)
    check_eq("M1: ...each numbered", ("  1. " in out, "  2. " in out), (True, True))
    many_guard = [f"guard line number {n:02d}" for n in range(1, 22)]
    for count, more in ((20, False), (21, True)):
        said = "\n".join(waiver._guard_holds(task_id, "S5", many_guard[:count]))
        check_eq(f"M1: {count} guard lines: the 20th named, the 21st never, `(+1 more` {'is' if more else 'is not'} printed",
                 ("20. guard line number 20" in said, "21. " in said, "(+1 more" in said), (True, False, more))
        if more:
            check_in("M1: ...with the command that prints the rest", f"(+1 more: stage_guard.py --ticket {task_id} --stage S5)", said)
    check_eq("M1: an empty guard names nothing", waiver._guard_holds(task_id, "S5", []), [])
    standing_pipeline(task_dir, task_id, done_through="S3")
    put_standing(task_dir, "S5", [stage_guard.without_hint(guard[0])], doors=["no accepted controller stage"])
    code, out, err = stage_run(task_id, "S5", "waiver.py --task")
    check_eq("WR7: guard AND a non-empty record: a block found only in the hint is refused", (code, recorded(task_dir)), (waiver.EXIT_BAD_ARGS, []))
    check_in("WR7: ...and the record's line, without its hint, is the option", "1. stage S5 cannot start", err)
    check_in("WR7: ...with the door the refusal printed", "  - no accepted controller stage", err)
    check_not_in("WR7: ...the hint is not offered back", "Your word passes this", err)
    standing_pipeline(task_dir, task_id, done_through="S3")
    put_standing(task_dir, "S5", [], doors=["no accepted controller stage"])
    code, out, err = stage_run(task_id, "S5", "waiver.py --task")
    check_eq("WR7: a record of doors only (guard non-empty) judges by the doors: refused", (code, recorded(task_dir)), (waiver.EXIT_BAD_ARGS, []))
    standing_pipeline(task_dir, task_id, done_through="S3")
    put_standing(task_dir, "S3", [stage_guard.without_hint(guard[0])])
    code, out, err = stage_run(task_id, "S5", "waiver.py --task")
    check_eq("WR7: guard non-empty and a record of ANOTHER stage: recorded, not verified", (code, len(recorded(task_dir))), (0, 1))
    check_in("WR7: ...and the text says whose record it is", "record of the standing refusal is of stage S3, not S5", out)
    standing_pipeline(task_dir, task_id, done_through="S3")
    code, out, err = stage_run(task_id, "S5", "required stages are not done")
    check_eq("WR7: ...while the phrase the guard's line holds is recorded", (code, len(recorded(task_dir))), (0, 1))
    check_in("WR7: ...and then the guard re-run speaks", "block lifted: the guard of S5 no longer refuses on it", out)

    # WR8 - the guard's own texts after a record: lifted / other blocks still stand / NOT lifted
    standing_pipeline(task_dir, task_id, approved=False)
    code, out, err = stage_run(task_id, "S5", "gate A is not approved")
    check_in("WR8: the block the guard refused on and nothing else: lifted, in the new words",
             "block lifted: the guard of S5 no longer refuses on it, and no other dispatch block of S5 stands", out)
    standing_pipeline(task_dir, task_id, done_through="S3", approved=False)
    code, out, err = stage_run(task_id, "S5", "gate A is not approved")
    check_in("WR8: ...another block standing: the old words", "block lifted; 1 other block(s) of S5 still stand: ", out)
    standing_pipeline(task_dir, task_id, approved=False)
    check_in("WR8: ...an override that does not pass the line: NOT lifted, as before",
             "block NOT lifted: stage S5 is past gate A", waiver.recheck_stage_block(task_id, "S5", "gate A is not approved"))

    # WR10 - the one definition of the factory's own blocks (N5): every literal the callers still spell is in the registry
    import re
    sr = (SCRIPTS / "story_run.py").read_text(encoding="utf-8")
    literals = set(re.findall(r'"--block",\s*"([^"]+)"', sr))
    check_eq("WR10: every literal block story_run.py spells for itself is a registry block",
             sorted(b for b in literals if b not in waiver.OWN_FORM_BLOCKS), [])
    login = re.search(r'STAND_LOGIN_BLOCK\s*=\s*(\S+)', sr).group(1).strip()
    check("WR10: STAND_LOGIN_BLOCK is the registry's name or its value",
          login in (f'"{waiver.STAND_LOGIN_MISSING_BLOCK}"', "waiver.STAND_LOGIN_MISSING_BLOCK"), login)
    # C2-5s (t-835): the transitional release is over - the callers take the NAME, no literal is left (N5), and it is the same object
    check_eq("WR10 (C2-5s): the driver spells no `--block` literal any more - the callers take the registry's names", sorted(literals), [])
    check_eq("WR10 (C2-5s): STAND_LOGIN_BLOCK is the registry's name in the source", login, "waiver.STAND_LOGIN_MISSING_BLOCK")
    import story_run
    check("WR10 (C2-5s): story_run.Driver.STAND_LOGIN_BLOCK is the registry's own object", story_run.Driver.STAND_LOGIN_BLOCK is waiver.STAND_LOGIN_MISSING_BLOCK)
    check_eq("WR10 (C2-5s): no name of the registry is spelled as a quoted literal block in the driver's calls or `block=`",
             [n for n in waiver.OWN_FORM_BLOCKS if re.search(r'(?:"--block",|block=)\s*"' + re.escape(n) + '"', sr)], [])
    prose = re.findall(r'--block\s+\\?"([A-Za-z][^"\\<{\n]*)\\?"', sr)     # t-842 item 4: the two prose commands (and the docstring) are inline-door literals
    check_eq("WR10 (t-842 item 4): every prose `--block \"<name>\"` of the driver spells a registry constant, and the two are there (C1-6b: the stand's door is `_words_door`, the name rides a constant)",
             (sorted(set(prose)), [b for b in prose if b not in waiver.OWN_FORM_BLOCKS]),
             (sorted([waiver.MODE_SWITCH_BLOCK, waiver.QUESTION_THRESHOLD_BLOCK]), []))
    import story_step
    check("WR10: story_step.MODE_SWITCH is the registry's own object", story_step.MODE_SWITCH is waiver.MODE_SWITCH_BLOCK)

    # WR11 - a whole line the driver recorded passes itself (N1): the lines the code builds in exit_gate.py, rendered
    fixtures = {
        "exit_gate.py:718/721": ("case identity: a case file's `id` is its file name and one case id in a form this project "
                                 "records (TC-<n>; for this story `TC-1`) - 2 file(s) break that: bad.md -> `TC-2.md` with "
                                 "`id: TC-2`; other.md -> `TC-3.md` with `id: TC-3`. Way on: write each case again under the "
                                 "name shown for it (its own number, in the form in force) with `id:` equal to that name (the orchestrator "
                                 "removes the stray file); or, if this project's own ids look like that, `config.case_id_form` records the "
                                 "form (the person or qa-onboarding writes it). A person's word passes this check"),
        "exit_gate.py:813": "re-entry re-checked, 2 error(s) remain; first: " + "; ".join(["a.json: x missing", "b.json: y empty"]),
        "exit_gate.py:847": "; ".join(f"{p['error']} <- \"{p['decision']}\"" for p in
                                      [{"error": "c.json: z missing", "decision": "go on"}, {"error": "d.json: w empty", "decision": "fine"}]),
        "exit_gate.py:862": "block 1/3; broken artifacts: 2; first: " + "; ".join(["e.json: q missing", "f.json: r empty"]),
    }
    for where, line in fixtures.items():
        standing_pipeline(task_dir, task_id)
        put_standing(task_dir, "S5", waiver.refusal_parts([line]))
        if waiver.PLACEHOLDER_RE.search(line):
            # GW1-1 P4 (ae8dd25c, after this key): a block holding a `<...>` names nothing and is refused whole - the refusal's own
            # text says "give a part of the line without it". The line's `TC-<n>` is the form's placeholder, so a part passes.
            code, out, err = stage_run(task_id, "S5", line)
            check_eq(f"WR11 {where}: a line holding the form's `<n>` is refused whole (P4), nothing recorded",
                     (code, len(recorded(task_dir)), "still holds the placeholder" in err), (waiver.EXIT_BAD_ARGS, 0, True))
            line = next(p for p in waiver.refusal_parts([line]) if not waiver.PLACEHOLDER_RE.search(p))
        code, out, err = stage_run(task_id, "S5", line)
        check_eq(f"WR11 {where}: the whole line (or its part without a placeholder) is recorded against the record built from it",
                 (code, len(recorded(task_dir))), (0, 1))
        check_in(f"WR11 {where}: as a carrier match", "recorded against the refusal standing at", out)
    line = fixtures["exit_gate.py:862"]
    standing_pipeline(task_dir, task_id)
    put_standing(task_dir, "S5", waiver.refusal_parts([line]))
    code, out, err = stage_run(task_id, "S5", line + "; g.json: not in the record")
    check_eq("WR11b: the same line with one part the record does not hold is refused", (code, recorded(task_dir)), (waiver.EXIT_BAD_ARGS, []))
    code, out, err = stage_run(task_id, "S5", "`waiver.py --task X --stage S5`")
    check_eq("WR11b: a block that is only code in backticks has no part, so it passes no line (N1, edge 27)", (code, recorded(task_dir)), (waiver.EXIT_BAD_ARGS, []))
    standing_pipeline(task_dir, task_id)
    put_standing(task_dir, "S5", [], raw="[]")
    check_eq("WR11b: ...and with nothing standing it is recorded as unknown", stage_run(task_id, "S5", "`only code`")[0], 0)

    # WR12 - a revocation takes a pass back; it lifts nothing (N7)
    standing_pipeline(task_dir, task_id, approved=False)
    stage_run(task_id, "S5", "gate A is not approved")
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = waiver.run_revoke(task_id, "S5", "gate A is not approved", "I changed my mind", "human")
    check_eq("WR12: the revocation is recorded", code, 0)
    check_in("WR12: ...and says the pass was taken back, the guard refuses on it again", "pass taken back: the guard of S5 refuses on it again: ", out.getvalue())
    check_not_in("WR12: ...never `block lifted`", "block lifted", out.getvalue())
    standing_pipeline(task_dir, task_id)
    stage_run(task_id, "S5", "something the guard never refused")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        waiver.run_revoke(task_id, "S5", "something the guard never refused", "no longer", "human")
    check_in("WR12: a revoked block the guard does not refuse on: said apart", "pass taken back: the guard of S5 does not refuse on it now", out.getvalue())
    check_not_in("WR12: ...never `block lifted` there either", "block lifted", out.getvalue())

    # D* - the refusal's own door (t-768, the Lead's edge 2): a block taken verbatim from the door the factory printed
    door_text = ("stage_done: S9 is a controller-managed stage and the controller has not accepted it, so `--status done` "
                 "would record a completion no evidence stands behind. A stage a ROLE ran is closed by accepting its dispatch "
                 "first. If a person decided to close it anyway: `"
                 + f'waiver.py --task {task_id} --stage S9 --block "no accepted controller stage" --words-file <file>' + "`.")
    door_lines, door_names = waiver.refusal_parts([door_text]), waiver.door_blocks(door_text)
    check_eq("D0: the door names the block, whole", door_names, ["no accepted controller stage"])
    check("D0: ...and the name is in no prose line (the cut door line was its only home)",
          "no accepted controller stage" not in " ".join(door_lines).lower(), str(door_lines))
    check_eq("D0: a placeholder and `*` are no door names",
             waiver.door_blocks('--block "<part of the line>" --block "*" --block \'gate rehearsal\' --block "gate rehearsal"'),
             ["gate rehearsal"])
    check_eq("D0: the guard's hint door is read the same way (a name with spaces, doubles dropped)",
             waiver.door_blocks(guard[0], guard[0]), ["required stages are not done"])
    standing_pipeline(task_dir, task_id, done_through="S8")
    put_standing(task_dir, "S9", door_lines, doors=door_names)
    code, out, err = stage_run(task_id, "S9", "no accepted controller stage")
    check_eq("D1: the block taken verbatim from the factory's own door is recorded", (code, len(recorded(task_dir))), (0, 1))
    check_in("D1: ...on the refusal's own door, by its name (t-782 M2)", "recorded on the refusal's own door (no accepted controller stage)", out)
    check_in("D1: ...not verified: nothing re-ran the check", "not verified: the record does not re-run the check", out)
    check_eq("D1: ...and never `block lifted`", out.count("block lifted"), 0)
    standing_pipeline(task_dir, task_id, done_through="S8")
    put_standing(task_dir, "S9", door_lines, doors=door_names)
    code, out, err = stage_run(task_id, "S9", "  No   Accepted CONTROLLER stage ")
    check_eq("D1: ...case and spaces folded, the door is the same and printed by the record's name",
             (code, "recorded on the refusal's own door (no accepted controller stage)" in out), (0, True))
    standing_pipeline(task_dir, task_id, done_through="S8")
    put_standing(task_dir, "S9", door_lines)
    code, out, err = stage_run(task_id, "S9", "no accepted controller stage")
    check_eq("D1: the record without `doors` holds the prose only: the same block is refused", (code, recorded(task_dir)), (waiver.EXIT_BAD_ARGS, []))
    # the same block with no standing refusal: unknown
    standing_pipeline(task_dir, task_id, done_through="S8")
    code, out, err = stage_run(task_id, "S9", "no accepted controller stage")
    check_eq("D2: ...and with no standing refusal at all it is recorded as not verified", (code, "not verified" in out, "block lifted" in out), (0, True, False))
    # another refusal's door
    standing_pipeline(task_dir, task_id, done_through="S8")
    put_standing(task_dir, "S9", door_lines, doors=door_names)
    code, out, err = stage_run(task_id, "S9", "gate rehearsal")
    check_eq("D3: a block from a DIFFERENT refusal's door is refused", (code, recorded(task_dir)), (waiver.EXIT_BAD_ARGS, []))
    check_in("D3: ...the standing line is listed", "1. " + door_lines[0][:40], err)
    check_in("D3: ...and so is the door the standing refusal printed", "  - no accepted controller stage", err)
    # a door and a prose line both hold the block: the door's kind wins, one lifted line
    standing_pipeline(task_dir, task_id, done_through="S8")
    put_standing(task_dir, "S9", ["report check: the report holds no left-with-you section"], doors=["report check"])
    code, out, err = stage_run(task_id, "S9", "report check")
    check_eq("D4: a block that is a door AND part of a prose line: recorded, the door's kind, no lifted line",
             (code, out.count("block lifted"), "recorded on the refusal's own door (report check)" in out), (0, 0, True))
    check_in("D4: ...and the prose line it also passes is named", "it also passes 1 line(s) of the refusal standing at S9: report check: ", out)
    # a door of another stage is not read; a record of doors only is a standing refusal
    standing_pipeline(task_dir, task_id)
    put_standing(task_dir, "S9", door_lines, doors=door_names)
    code, out, err = stage_run(task_id, "S5", "no accepted controller stage")
    check_eq("D5: the door of a record of another stage is not read: unknown, recorded",
             (code, "not verified: there is no record of S5 this command can read" in out), (0, True))
    standing_pipeline(task_dir, task_id, done_through="S8")
    put_standing(task_dir, "S9", [], doors=door_names)
    code, out, err = stage_run(task_id, "S9", "something else")
    check_eq("D5: a record of doors only is a standing refusal: another block is refused and the door listed", (code, "  - no accepted controller stage" in err), (waiver.EXIT_BAD_ARGS, True))
    code, out, err = stage_run(task_id, "S9", "*")
    check_eq("D5: ...while `*` is never refused", code, 0)
    # t-782 P2: `*` over a record of doors only names the doors, never "no refusal ... is known"
    check_in("M1 P2: `*` over doors only: the door is named", "only the door(s) its refusal printed:\n  - no accepted controller stage", out)
    check_in("M1 P2: ...and what is not known", "not verified: the record of S9 holds doors only, no line to check the block against", out)
    check_eq("M1 P2: ...never `no refusal of S9 is known` nor `none is open now`",
             ("no refusal of S9 is known" in out, "none is open now" in out), (False, False))
    # t-782 P4: the door kind with a guard that still refuses names the guard's line too
    standing_pipeline(task_dir, task_id, done_through="S3")
    put_standing(task_dir, "S5", [], doors=["no accepted controller stage"])
    code, out, err = stage_run(task_id, "S5", "no accepted controller stage")
    check_eq("M2 P4: the door with a standing guard: recorded, not lifted", (code, len(recorded(task_dir)), "block lifted" in out),
             (0, 1, False))
    check_in("M2 P4: ...the guard's standing line is named", "the guard of S5 holds 1 line(s), and the block passes none of them:\n"
             "  1. stage S5 cannot start", out)
    long_door = "a door name far longer than any cell of a table " * 6
    long_door = long_door.strip()
    standing_pipeline(task_dir, task_id, done_through="S8")
    put_standing(task_dir, "S9", [], doors=[long_door])
    code, out, err = stage_run(task_id, "S9", long_door)
    check_eq("M2: a door name longer than any cell is printed whole", (code, f"recorded on the refusal's own door ({long_door})" in out),
             (0, True))
    # t-782 m3 / P3: a stand-gap card prints its reading and nothing that says the block was lifted
    standing_pipeline(task_dir, task_id)
    code, out, err = stage_run(task_id, "S5", "stand gap: TC-1")
    check_eq("m3 P3: a stand-gap card is recorded and its reading printed", (code, "stand gap TC-1 now reads:" in out), (0, True))
    check_in("m3 P3: ...the card is asked again (the words start with none of the four)", "the card is asked again", out)
    check_not_in("m3 P3: ...and no `block lifted` after it", "block lifted", out)
    # t-782 M3 and M2: the texts that teach the rule say what the code does
    check("M3: the module text states the L-7 rule: the guard alone refuses nothing",
          "the guard alone refuses nothing" in waiver.__doc__, "")
    check("M3: ...and the temporal edge as it is now: the driver writes and erases the record, no record = silent (no `dormant` left)",
          "the driver writes the record when the seam is called for a refusal" in waiver.__doc__
          and "with no record the refusal is silent" in waiver.__doc__ and "dormant" not in waiver.__doc__, "")
    many_doors = [f"door number {n:02d}" for n in range(1, 22)]
    standing_pipeline(task_dir, task_id, done_through="S8")
    put_standing(task_dir, "S9", ["a line"], doors=many_doors)
    code, out, err = stage_run(task_id, "S9", "nothing of it")
    check_eq("D6: 21 doors: 20 listed and `(+1 more`", ("  - door number 20" in err, "door number 21" in err, "(+1 more" in err), (True, False, True))

    # t-842 F2: the tail cut is for a DOOR (a final span holding `--` or `.py`), never for a problem's own code span
    two = ["no test is bound to case `TC-3`", "no test is bound to case `TC-7`"]
    door = "If a person accepts it: `waiver.py --task QA-9 --stage S5 --block \"x\" --words-file <file>`."
    check_eq("F2: two lines that differ only in their final `TC-n` span stay two record lines", waiver.refusal_parts(two), two)
    check_eq("F2: ...while a final span that IS a door is cut, the full stop with it", waiver.refusal_parts(["problem one. " + door]), ["problem one. If a person accepts it:"])
    check_eq("F2 edge (named): a final span with `--` or `.py` is a door by FORM - a problem ending in a file name is cut, not kept",
             waiver.refusal_parts(["no test imports `helper.py`", "no test imports `--flag`"]), ["no test imports"])
    check_eq("F2: the cut is idempotent - a record line normalised again is itself", [waiver.refusal_parts([p]) for p in waiver.refusal_parts(two + [door])],
             [[p] for p in waiver.refusal_parts(two + [door])])
    check_eq("F2: ...also over ``missing `a` `b` `` (the t-842 F3 double-normalisation input)", waiver.refusal_parts(waiver.refusal_parts(["missing `a` `b`"])),
             waiver.refusal_parts(["missing `a` `b`"]))
    standing_pipeline(task_dir, task_id)
    put_standing(task_dir, "S5", waiver.refusal_parts(two))
    code, out, err = stage_run(task_id, "S5", two[0])
    check_eq("F2: a block on ONE of the two lines passes that line only (the reader's own pass, not both)",
             (code, len(recorded(task_dir)), "the word is in 1 of its line(s)" in out), (0, 1, True))
    check_eq("F2: ...and the reader clears exactly the first line of the two", waiver._reads(waiver.refusal_parts(two), "S5", two[0]), [two[0]])


UTF8_VARIABLES = ("PYTHONUTF8", "PYTHONIOENCODING")


def f1_a_release_with_words_outside_the_console_codepage(root: Path, task_id: str, controller: Controller) -> None:
    """t-873 F-1 (major): the controller commits a release and only THEN prints its answer, which carries the person's words
    (`ensure_ascii=False`). On a console code page (cp1252) the print of Cyrillic or an arrow died with UnicodeEncodeError: rc 1 after
    a committed release, and the driver said "nothing was released". Two moves, each pinned: (a) the controller puts its streams on
    UTF-8 itself (`console_io`, axis 15): `run_release` with NO env and NEITHER variable in the parent's environment gets rc 0 and the
    answer; (b) the caller's child environment reaches the process (`env=`). The edge: a controller that fails for ANOTHER reason
    records nothing, and that is how the two are told apart - the controller's RECORD (the dispatch's status), not the print."""
    task_root = root / "qa-factory" / "artifacts" / task_id
    third = "S1-qa-scout-3"
    controller.apply("dispatch", {"id": third, "stage": "S1", "role": "qa-scout", "scope": [], "input_hash": "ctx3", "budget": {"requests": 30},
                                  "known_paths": {"root": str(task_root)}, "idempotency_key": "d-3"})
    cyrillic = "".join(chr(c) for c in (0x43D, 0x438, 0x43A, 0x442, 0x43E, 0x20, 0x43D, 0x435, 0x20, 0x434, 0x435, 0x43B, 0x430, 0x435, 0x442))
    words = f"it is dead {arrow()} {cyrillic}, go on\r\n"
    path = task_root / "state" / "words" / "f1.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(words.encode("utf-8"))
    kept = {name: os.environ.pop(name) for name in UTF8_VARIABLES if name in os.environ}
    try:
        statuses = {k: v.get("status") for k, v in controller.state()["dispatches"].items()}
        code, out = waiver.run_release(task_root, "S1-qa-scout-9", words_file=str(path))
        check_eq("F-1 edge: a controller that fails for another reason (unknown dispatch) records nothing - the record is the proof",
                 (code != 0, {k: v.get("status") for k, v in controller.state()["dispatches"].items()}), (True, statuses))
        code, out = waiver.run_release(task_root, third, words_file=str(path))
        check_eq("F-1 (a): words with Cyrillic and an arrow, neither UTF-8 variable in the environment: rc 0 (the controller sets its own streams)", code, 0)
        check_in("F-1 (a): ...and the answer carries the words, whole", cyrillic, out)
        check_eq("F-1 (a): ...and the record says the dispatch is released", controller.state()["dispatches"][third].get("status"), "released_by_person")
    finally:
        os.environ.update(kept)
    import subprocess
    seen, real = [], subprocess.run
    child = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    subprocess.run = lambda *a, **k: (seen.append(k.get("env")), real(*a, **k))[1]
    try:
        waiver.run_release(task_root, "S1-qa-scout-9", words_file=str(path), env=child)
        waiver.run_release(task_root, "S1-qa-scout-9", words_file=str(path))
    finally:
        subprocess.run = real
    check_eq("F-1 (b): the environment the caller passes is the child's (its UTF-8 pair, no more is printed); none passed means the process's own",
             [e if e is None else (e.get("PYTHONUTF8"), e.get("PYTHONIOENCODING")) for e in seen], [("1", "utf-8"), None])


def pipeline_of(task_dir: Path) -> dict:
    return json.loads((task_dir / "pipeline.json").read_text(encoding="utf-8"))


def refused_load(path: Path) -> str:
    """The message of the loader's refusal for the table at `path`, or "" when it was accepted."""
    try:
        waiver.load_block_names(path)
    except waiver.BlockNamesError as exc:
        return str(exc)
    return ""


def block_names(root: Path, task_id: str) -> None:
    """conductor/4 C4-3: the block NAMES a code reader acts on (`references/block-names.json`, FR-13) are accepted by the
    writer whatever the standing refusal holds - the probe of t-875: `keep it local` was `unmatched` against any other line of
    the S8 record, `unknown` with none; `executor unavailable: <profile>` the same at S5."""
    import contract
    import external_writes
    task_dir = root / "qa-factory" / "artifacts" / task_id
    other = ["the qa-code-critic window is not receipted: no review receipt for TC-1"]

    shipped = waiver.load_block_names()
    c43 = ("keep it local", "executor unavailable: <profile>", "story budget")
    check_eq("BN0: the shipped table holds the three names of C4-3, each reader a function that exists (the four own-form rows follow, C4-8)",
             [(r["block"], r["reader"], r["stages"]) for r in shipped if r["block"] in c43],
             [("keep it local", "external_writes:local_only_decision", ("S8", "S9")),
              ("executor unavailable: <profile>", "contract:handed_profiles", ("S5",)),
              ("story budget", "story_budget:override", ("*",))])

    # BN1/BN2 - `keep it local`: with another line standing, and with no record at all
    for label, prepare in (("a record of S8 holds another line", lambda: put_standing(task_dir, "S8", other)),
                           ("no record at all", lambda: None),
                           ("a record that cannot be read", lambda: put_standing(task_dir, "S8", [], raw="{"))):
        standing_pipeline(task_dir, task_id, done_through="S7")
        prepare()
        check_eq(f"BN1: `keep it local` ({label}) is the factory's own name - neither unmatched nor unknown",
                 waiver.block_standing(task_id, "S8", "keep it local", pipeline_of(task_dir))[:2], ("own_form", []))
        check_eq(f"BN1: ({label}) ...and it carries the table row it matched (F-3: the report does not load the table again)",
                 (waiver.block_standing(task_id, "S8", "keep it local", pipeline_of(task_dir))[2] or {}).get("reader"),
                 "external_writes:local_only_decision")
        code, out, err = stage_run(task_id, "S8", "keep it local", "just leave them in the repo")
        check_eq(f"BN1: ({label}) it is recorded", (code, len(recorded(task_dir))), (0, 1))
        check_in(f"BN1: ({label}) the line names its reader", "read by external_writes:local_only_decision", out)
        check_not_in(f"BN1: ({label}) never `block lifted`, never refused", "block lifted", out + err)
        check("BN1: ...and the reader acts on what was recorded", bool(external_writes.local_only_decision(task_id)))

    # BN3 - `executor unavailable: <profile>` at S5, the same two worlds, and the reader reads the profile
    for label, prepare in (("a record of S5 holds another line", lambda: put_standing(task_dir, "S5", other)),
                           ("no record at all", lambda: None)):
        standing_pipeline(task_dir, task_id)
        prepare()
        check_eq(f"BN3: `executor unavailable: profile-x` ({label}) is a name, neither unmatched nor unknown",
                 waiver.block_standing(task_id, "S5", "executor unavailable: profile-x", pipeline_of(task_dir))[:2],
                 ("own_form", []))
        code, out, err = stage_run(task_id, "S5", "executor unavailable: profile-x", "I run them myself")
        check_eq(f"BN3: ({label}) it is recorded", (code, len(recorded(task_dir))), (0, 1))
        check_eq("BN3: ...and `contract.handed_profiles` reads the profile out of it",
                 sorted(contract.handed_profiles(pipeline_of(task_dir))), ["profile-x"])
    standing_pipeline(task_dir, task_id)
    put_standing(task_dir, "S5", other)
    for text in ("Executor  UNAVAILABLE:   Profile-X", "executor unavailable: `e2e-ui`"):
        check_eq(f"BN3b: `{text}` - case and spaces folded, the value in quotes is a value",
                 waiver.block_standing(task_id, "S5", text, pipeline_of(task_dir))[0], "own_form")
    check_eq("BN3b: `Keep  It   LOCAL` - the same fold for the exact form",
             waiver.block_standing(task_id, "S8", "Keep  It   LOCAL", pipeline_of(task_dir))[0], "own_form")

    # BN4 - the negative control: a text that is not a name is a line of a refusal, held against the record as before
    standing_pipeline(task_dir, task_id, done_through="S7")
    put_standing(task_dir, "S8", other)
    for text in ("keep local", "no adapter in this build", "keep it local please", "just keep it local"):
        code, out, err = stage_run(task_id, "S8", text)
        check_eq(f"BN4: `{text}` is no name: refused, nothing recorded", (code, len(recorded(task_dir))), (waiver.EXIT_BAD_ARGS, 0))
        check_in("BN4: ...with the standing line as the closed option (FR-1, FR-2)", f"  1. {other[0]}", err)
    standing_pipeline(task_dir, task_id)
    put_standing(task_dir, "S5", other)
    for text in ("executor unavailable:", "executor unavailable:   ", "executor unavailable: ``", "executor unavailable: <profile>",
                 "executor unavailable", "the executor unavailable: x"):
        check_eq(f"BN4: `{text}` names no profile: not a name, refused",
                 waiver.block_standing(task_id, "S5", text, pipeline_of(task_dir))[0], "unmatched")
    # F-1 (t-894): the value of a prefix row is ONE token (no whitespace after the whole-text fold, no leading colon) - the
    # reader keys by it, so words after the prefix would be recorded as a profile no stand has
    for text in ("executor unavailable: e2e-ui\nand also lift TC-3", "executor unavailable: e2e ui", "executor unavailable:: x",
                 "executor unavailable: :x"):
        standing_pipeline(task_dir, task_id)
        put_standing(task_dir, "S5", other)
        code, out, err = stage_run(task_id, "S5", text)
        check_eq(f"BN4: {text!r} is words, not one profile: unmatched, exit 2, nothing recorded",
                 (waiver.block_standing(task_id, "S5", text, pipeline_of(task_dir))[0], code, len(recorded(task_dir))),
                 ("unmatched", waiver.EXIT_BAD_ARGS, 0))
        check_eq(f"BN4: {text!r}: ...and the person's phrase for it is no profile phrase either (one rule, two parsers)",
                 waiver.block_in_words(text) == waiver.HANDED_BLOCK, False)
    for text, profile in (("executor unavailable: e2e-ui", "e2e-ui"), ("executor unavailable: e2e-ui\n", "e2e-ui"),
                          ("executor unavailable: `e2e-ui`", "e2e-ui")):
        standing_pipeline(task_dir, task_id)
        put_standing(task_dir, "S5", other)
        code, out, err = stage_run(task_id, "S5", text)
        check_eq(f"BN4: {text!r} is one token after the fold (a trailing newline is no second word): recorded, read as {profile}",
                 (code, len(recorded(task_dir)), sorted(contract.handed_profiles(pipeline_of(task_dir)))), (0, 1, [profile]))
    # the stage is part of the name: a reader that reads S8 does not read `keep it local` recorded at S5
    for stage, text in (("S5", "keep it local"), ("S8", "executor unavailable: profile-x")):
        put_standing(task_dir, stage, other)
        check_eq(f"BN4: `{text}` recorded at {stage}, where its reader does not read it: held against the record, unmatched",
                 waiver.block_standing(task_id, stage, text, pipeline_of(task_dir))[0], "unmatched")
    check_eq("BN4: `story budget` is read at every stage",
             [waiver.block_standing(task_id, s, "story budget", pipeline_of(task_dir))[0] for s in ("S1", "S5", "S9")],
             ["own_form"] * 3)

    # BN7 (C4-9, t-898) - ONE reader of the prefix value: `contract.prefix_value` is what the writer (`block_name_row`), the
    # person's phrase (`block_in_words`) and the reader (`contract.handed_profiles`) all call, so the three see the same
    # value and answer the same way. One assertion per probe per parser: (helper value, writer accepts, phrase is the
    # handed phrase, profiles the reader holds from a record of that block).
    probes = (("executor unavailable: e2e-ui\nand also lift TC-3", None), ("executor unavailable: e2e ui", None),
              ("executor unavailable: : x", None), ("executor unavailable:", None), ("executor unavailable:   ", None),
              ("executor unavailable: ``", None), ("executor unavailable: e2e-ui", "e2e-ui"),
              ("executor unavailable: `e2e-ui`", "e2e-ui"), ('Executor  UNAVAILABLE:  "e2e-ui"\n', "e2e-ui"))
    for text, value in probes:
        record = {"stage_overrides": [{"stage": "S5", "match": text, "decision": "I run them myself", "at": "2026-10-16"}]}
        accepted = value is not None
        check_eq(f"BN7: {text!r}: the helper's value", contract.prefix_value(text, contract.HANDED_MATCH_PREFIX), value)
        check_eq(f"BN7: {text!r}: the writer (block_name_row) {'accepts' if accepted else 'refuses'} it",
                 waiver.block_name_row(text, "S5") is not None, accepted)
        check_eq(f"BN7: {text!r}: the person's phrase (block_in_words) {'is' if accepted else 'is not'} the handed phrase",
                 waiver.block_in_words(text) == waiver.HANDED_BLOCK, accepted)
        check_eq(f"BN7: {text!r}: the reader (handed_profiles) holds {'the value' if accepted else 'no profile'}",
                 sorted(contract.handed_profiles(record)), [value] if accepted else [])
    check_eq("BN7: the helper is the module's only reader (waiver keeps no copy)", hasattr(waiver, "_prefix_value"), False)

    # BN5 - a block that is BOTH a line of the refusal and a name is accepted either way; an empty block is unchanged
    standing_pipeline(task_dir, task_id, done_through="S7")
    put_standing(task_dir, "S8", other + ["the gate B question asks: keep it local"])
    check_eq("BN5: a name that is also a part of a standing line is accepted (the name wins, position (a))",
             waiver.block_standing(task_id, "S8", "keep it local", pipeline_of(task_dir))[0], "own_form")
    check_eq("BN5: an empty --block reads as before (held against the record)",
             waiver.block_standing(task_id, "S8", "", pipeline_of(task_dir))[0], "unmatched")

    # BN6 - a table that cannot be trusted refuses the block and names the file; `*`, an empty block and the forms the table
    # is not consulted for are unaffected
    work = temp_dir("qa-block-names-")
    table = work / "block-names.json"
    good = {"block": "keep it local", "reader": "external_writes:local_only_decision", "stages": ["S8"]}
    cases = (("a JSON list", "[]", ""), ("broken JSON", "{", ""), ("an empty file", "", ""), ("no `names`", "{}", ""),
             ("an empty `names`", '{"names": []}', ""), ("`names` not a list", '{"names": "x"}', ""),
             ("a row that is no object", {"names": [good, 3]}, "row 2"),
             ("a row without a reader", {"names": [good, {"block": "typo name", "stages": ["S8"]}]}, "row 2 (typo name)"),
             ("a reader that is no module of scripts/", {"names": [dict(good, block="typo name", reader="no_such_module:f")]},
              "row 1 (typo name)"),
             ("a reader that is no function of its module", {"names": [dict(good, block="typo name", reader="contract:no_such_fn")]},
              "row 1 (typo name)"),
             ("a reader that is not module:function", {"names": [dict(good, block="typo name", reader="local_only_decision")]},
              "row 1 (typo name)"),
             ("a row without stages", {"names": [{"block": "typo name", "reader": good["reader"]}]}, "row 1 (typo name)"),
             ("stages that are no stage ids", {"names": [dict(good, block="typo name", stages=["eight"])]}, "row 1 (typo name)"),
             ("an empty block", {"names": [dict(good, block=" ")]}, "row 1"),
             ("a placeholder in the middle", {"names": [dict(good, block="a <x> b")]}, "row 1 (a <x> b)"),
             ("two placeholders", {"names": [dict(good, block="a: <x> <y>")]}, "row 1 (a: <x> <y>)"),
             ("a placeholder and no fixed text", {"names": [dict(good, block="<x>")]}, "row 1 (<x>)"))
    real_reference = waiver.reference_file
    try:
        check_in("BN6: an absent file is refused, naming it", "block-names.json", refused_load(table))   # not written yet
        for label, content, row in cases:
            table.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
            message = refused_load(table)
            check(f"BN6: {label}: the loader refuses", message != "", "accepted")
            check_in(f"BN6: {label}: ...naming the file", "block-names.json", message)
            if row:
                check_in(f"BN6: {label}: ...and the row", row, message)
            waiver.reference_file = lambda name, _t=table: _t
            standing_pipeline(task_dir, task_id, done_through="S7")
            put_standing(task_dir, "S8", other)
            code, out, err = stage_run(task_id, "S8", "keep it local")
            check_eq(f"BN6: {label}: the writer refuses the block, nothing is recorded",
                     (code, len(recorded(task_dir))), (waiver.EXIT_BAD_ARGS, 0))
            check_in(f"BN6: {label}: ...names the file", "block-names.json", err)
            check_in(f"BN6: {label}: ...and the other door, the remark", "--remark", err)
            check_not_in(f"BN6: {label}: ...never a lift", "block lifted", out + err)
            check_eq(f"BN6: {label}: a block that is no name is refused too, not passed as unknown",
                     stage_run(task_id, "S8", "a block no line holds")[0], waiver.EXIT_BAD_ARGS)
            check_eq(f"BN6: {label}: `*` and a form the table is not read for are recorded",
                     [stage_run(task_id, "S8", b)[0] for b in ("*", "stand not confirmed")], [0, 0])
            check_eq(f"BN6: {label}: an empty block does not read the table (unchanged)",
                     waiver.block_standing(task_id, "S8", "", pipeline_of(task_dir))[0], "unmatched")
            standing_pipeline(task_dir, task_id, done_through="S7")           # no record at all: the verdict would be `unknown`
            code, out, err = stage_run(task_id, "S8", "a block no line holds")
            check_eq(f"BN6: {label}: with no record the verdict `unknown` needs the table too: refused, naming the file, nothing recorded",
                     (code, len(recorded(task_dir)), "block-names.json" in err), (waiver.EXIT_BAD_ARGS, 0, True))
            # F-3 (t-894): a stand gap is known by form and written without the table; its report must not read the table
            # either - the word is on disk, a traceback after the write would be a lie about what happened. A retry is the
            # same entry (the writer replaces by stage and block), never a second one.
            standing_pipeline(task_dir, task_id)
            tries = []
            for _ in range(2):
                try:
                    tries.append(stage_run(task_id, "S5", "stand gap: PC-1")[:2])
                except Exception as exc:
                    tries.append((type(exc).__name__, ""))
            check_eq(f"BN6: {label}: a stand gap is recorded once, exit 0, no traceback, on the first try and on a retry",
                     ([t[0] for t in tries], len(recorded(task_dir))), ([0, 0], 1))
            check_in(f"BN6: {label}: ...and its stand-gap reading is printed as before", "stand gap PC-1 now reads:", tries[0][1])
            # F-2 (t-894): the table cannot change a block that is a part of a standing line (a carrier), so it must not
            # refuse it; the same for a block that is BOTH such a part and a name - the carrier road takes it
            standing_pipeline(task_dir, task_id, done_through="S7")
            put_standing(task_dir, "S8", other + ["the gate B question asks: keep it local"])
            for text in ("not receipted", "keep it local"):
                code, out, err = stage_run(task_id, "S8", text)
                check_eq(f"BN6: {label}: `{text}` is a part of a standing line: recorded through the carrier, not refused",
                         (code, len(recorded(task_dir))), (0, 1))
                check_in(f"BN6: {label}: `{text}` ...by the carrier road", "recorded against the refusal standing", out)
                # the carrier road neither refuses nor complains about the table; since the decision classes (c10 of test_decision_classes)
                # the stdout says, as an honest note, that the word was recorded WITHOUT a class - the one place the table is named
                check_not_in(f"BN6: {label}: `{text}` ...no word about the table in a refusal", "block-names.json", err)
                check_in(f"BN6: {label}: `{text}` ...only the note that no class could be read", "recorded without a class", out)
                standing_pipeline(task_dir, task_id, done_through="S7")
                put_standing(task_dir, "S8", other + ["the gate B question asks: keep it local"])
            waiver.reference_file = real_reference
        table.write_text(json.dumps({"names": [good]}), encoding="utf-8")
        check_eq("BN6: the same file with one good row is accepted", refused_load(table), "")
    finally:
        waiver.reference_file = real_reference
        cleanup(work)


def own_form_table() -> None:
    """conductor/4 C4-8: the factory's own-form constants are rows of `references/block-names.json` too (who reads them is
    data, FR-13), and the reader pointer may be a method (`<module>:<Class>.<method>`)."""
    rows = {r["block"]: r for r in waiver.load_block_names()}
    for name in waiver.OWN_FORM_BLOCKS:
        row = rows.get(waiver._fold(name))
        check(f"C48: OWN_FORM_BLOCKS member `{name}` has a row in block-names.json (the loader checked its reader)", row is not None,
              "no row")
    check_eq("C48: the constants stay plain string literals (importable with the table unreadable)",
             [type(b) for b in waiver.OWN_FORM_BLOCKS], [str] * 4)
    check_eq("C48: the readers of the four names",
             sorted((rows[waiver._fold(n)]["reader"], rows[waiver._fold(n)]["stages"]) for n in waiver.OWN_FORM_BLOCKS
                    if waiver._fold(n) in rows),
             [("story_run:Driver.question_threshold", ("S2", "S3", "S4")),("story_run:Driver.stand_check", ("S5", "S6")),
              ("story_run:Driver.stand_login_gate", ("S6",)), ("story_step:run_mode_switch", ("*",))])
    work = temp_dir("qa-reader-form-")
    scripts = work / "scripts"
    scripts.mkdir()
    (scripts / "mod.py").write_text(
        "def top(x):\n    return x\n\n\nclass Alpha(Base):\n    def one(self):\n        def inner():\n            pass\n"
        "    def two(self):\n        pass\n\n\nclass Beta:\n    def three(self):\n        pass\n\n\ndef after(x):\n    pass\n",
        encoding="utf-8")
    table = work / "block-names.json"
    try:
        for reader, ok in (("mod:Alpha.one", True), ("mod:Alpha.two", True), ("mod:Beta.three", True), ("mod:top", True),
                           ("mod:Beta.one", False),          # (i) a method of another class
                           ("mod:top.one", False), ("mod:after.one", False),   # (ii) a module-level function written as Class.method
                           ("mod:Gamma.one", False),         # (iii) a class that does not exist
                           ("mod:Alpha.one.two", False),     # (iv) two dots
                           ("mod:Alpha.inner", False),       # a def nested in a method is no method of the class
                           ("mod:Alpha.after", False), ("nomod:Alpha.one", False), ("mod:Alpha.", False), ("mod:.one", False)):
            table.write_text(json.dumps({"names": [{"block": "x name", "reader": reader, "stages": ["S5"]}]}), encoding="utf-8")
            try:
                waiver.load_block_names(table, scripts)
                got, message = True, ""
            except waiver.BlockNamesError as exc:
                got, message = False, str(exc)
            check_eq(f"C48: reader `{reader}` is {'accepted' if ok else 'refused'}", got, ok)
            if not ok:
                check_in(f"C48: reader `{reader}`: the refusal names the row", "row 1 (x name)", message)
    finally:
        cleanup(work)


def arrow() -> str:
    return chr(0x2192)


def main() -> None:
    root = temp_dir("qa-waiver-release-")
    import os
    import hooklib
    cached, hooklib._PROJECT_ROOT_CACHE = hooklib._PROJECT_ROOT_CACHE, None
    old_env = os.environ.get("CLAUDE_PROJECT_DIR")
    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    try:
        controller = story(root)
        task_id = root.name
        check_eq("the dispatch starts out running",
                 (controller.state()["dispatches"][DISPATCH]).get("status"), "running")

        # The words name no dispatch: the controller picks the only open one and says so.
        answer = waiver.route_release(task_id, "next says wait_existing_job",
                                      "it's dead, go on")
        check_in("the person's word reaches the controller", "block lifted", answer)
        check_eq("and the dispatch stops holding the story",
                 (controller.state()["dispatches"][DISPATCH]).get("status"), "released_by_person")
        check_in("the controller's own answer is shown, not a summary of it", DISPATCH, answer)

        # Releasing what is already released is not a second release, and the person is told
        # plainly rather than being handed a traceback.
        again = waiver.route_release(task_id, "wait_existing_job", "still dead")
        check("a dispatch that holds nothing back is said so",
              again.startswith("block NOT lifted"), again)

        # The whole route, as the orchestrator runs it: one command, and the printed answer
        # says whether the block is gone.
        pipeline = root / "qa-factory" / "artifacts" / task_id / "pipeline.json"
        second = "S1-qa-scout-2"
        controller.apply("dispatch", {"id": second, "stage": "S1", "role": "qa-scout",
                                      "scope": [], "input_hash": "ctx2",
                                      "budget": {"requests": 30},
                                      "known_paths": {"root": str(pipeline.parent)},
                                      "idempotency_key": "d-2"})
        pipeline.write_text(json.dumps({"ticket": task_id,
                                        "stages": {"S0": {"status": "done"},
                                                   "S1": {"status": "running"}}}), encoding="utf-8")
        import io
        import contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = waiver.run_stage(task_id, "S1", f"wait_existing_job on {second}",
                                    "nobody is working on it, go on", "human")
        printed = out.getvalue()
        check_eq("waiver.py --stage exits clean", code, 0)
        check_in("the person's words are still recorded as a stage override",
                 "stage_overrides[]", printed)
        check_in("and the block they named is reported lifted", "block lifted", printed)
        check_eq("because the dispatch they named was the one released",
                 (controller.state()["dispatches"][second]).get("status"), "released_by_person")

        # An ordinary stage block is NOT routed here: it goes on being re-checked by the guard.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            waiver.run_stage(task_id, "S1", "source material unavailable",
                             "go on without the video", "human")
        check_in("an ordinary block still goes through the dispatch guard",
                 "block", out.getvalue())
        check("and is not sent to release",
              "released by the person's word" not in out.getvalue(), out.getvalue())
        # WR9 (t-722 C2-6, moved from C2-5): route_release keeps its texts over run_release, which is THE one caller of the controller's release
        code, out = waiver.run_release(root / "qa-factory" / "artifacts" / task_id, "S1-qa-scout-9", words="gone")
        check_eq("WR9: run_release returns the controller's refusal as (exit code, answer), never text for a person", (code != 0, "S1-qa-scout-9" in out), (True, True))
        check_eq("WR9: ...and a controller that cannot start is RUN_FAILED with the reason", waiver.RUN_FAILED, 127)
        check("WR9: route_release over it still says `block NOT lifted` for the same refusal",
              waiver.route_release(task_id, "wait_existing_job on S1-qa-scout-9", "gone").startswith("block NOT lifted"))
        f1_a_release_with_words_outside_the_console_codepage(root, task_id, controller)
        person_list(root, task_id)
        standing_refusal(root, task_id)
        block_names(root, task_id)
        own_form_table()
    finally:
        hooklib._PROJECT_ROOT_CACHE = cached
        if old_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = old_env
        cleanup(root)
    finish("test_waiver_release")


if __name__ == "__main__":
    main()
