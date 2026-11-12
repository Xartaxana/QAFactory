"""GW1-3 (B-271): the retro is always the full one - no road writes `retro_mode` numbers or skip.

Keys K1-K7 of docs/tasks/specs/t-700-gw1-3-gate-b-words.md: the stage_done refusal and its door, the SETTABLE lexicon, the CLI
on a seeded story (bytes unchanged after a refusal), and the conductor prompt (the text of conductor.md / s8.md / s9.md / the
retro analyst is rows of design/role-rules.json). Never launches a real `claude -p`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))


def k1_k2_k3() -> None:
    import stage_done
    for v in ("numbers", "skip", " NUMBERS ", "Skip"):
        try:
            stage_done.coerce_value("retro_mode", v)
            check(f"K1 {v!r} refused", False, "no ValueError")
        except ValueError as err:
            msg = str(err)
            check(f"K1 {v!r} refused with the door", "always the full one" in msg and "--remark --stage S9" in msg, msg)
            check(f"K1 {v!r} says where the words go, not the report",
                  "the gate B packet and the MR's open items carry them" in msg and "the report carries" not in msg, msg)
    import person_words
    # K3 (fix round): the door is the renderer's, byte-equal to the text it replaced
    by_hand = "waiver.py --task <T> --remark --stage S9 --words-file <file>"
    check("K3 person_words.door == the hand-written door",
          person_words.door("waiver.py --task <T> --remark --stage S9") == by_hand)
    try:
        stage_done.coerce_value("retro_mode", "skip")
    except ValueError as err:
        check("K3 the refusal carries the door whole", f"`{by_hand}`" in str(err), str(err))
    check("K2 full is accepted", stage_done.coerce_value("retro_mode", "full") == "full")
    check("K2 empty is None", stage_done.coerce_value("retro_mode", "") is None)
    check("K3 SETTABLE", stage_done.SETTABLE["retro_mode"] == ("full",), str(stage_done.SETTABLE["retro_mode"]))


def k4_cli() -> None:
    from story_run_common import seed
    task = "QA-9"
    root, task_root, env = seed(task)
    try:
        pipe = task_root / "pipeline.json"
        before = pipe.read_bytes()
        done = harness.run_script("stage_done.py", "--task", task, "--set", "retro_mode=skip", cwd=root, env=env)
        out = done.stdout + done.stderr
        check("K4 skip refused (exit non-zero)", done.returncode != 0, out)
        check("K4 pipeline.json bytes identical", pipe.read_bytes() == before)
        check("K4 the output names --remark", "--remark" in out, out)
        done = harness.run_script("stage_done.py", "--task", task, "--set", "retro_mode=full", cwd=root, env=env)
        check("K4 control: full exits 0", done.returncode == 0, done.stdout + done.stderr)
        import json
        check("K4 control: retro_mode == full", json.loads(pipe.read_text(encoding="utf-8")).get("retro_mode") == "full")
    finally:
        harness.cleanup(root)


def k5_prompt() -> None:
    import story_run
    text = story_run.Driver.generic_prompt("waiver", "S9", "q")
    check("K5 no retro_mode in the conductor prompt", "retro_mode" not in text)
    check("K5 control: the waiver road is named", "waiver.py --block/--remark" in text)


def main() -> None:
    k1_k2_k3()
    k4_cli()
    k5_prompt()
    harness.finish("test_retro_always_full")


if __name__ == "__main__":
    main()
