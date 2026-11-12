#!/usr/bin/env python3
"""t-404 N5 (SC2-38 item 4, option c of F-S3C-6): the runner writes a case's seed once, as `seed-steps.md`.

There is no code behind the seed; what is pinned is the three facts the text relies on:
K5-1 the REAL `guard_pre_tool.py` (a subprocess, the event on stdin) lets `qa-runner` write the seed path (exit 0);
     control of the same shape: `work/test-plan.md` written by `qa-runner` is refused (exit 2).
K5-2 the text names the path through the case folder that holds `request.json` (`area/TC` is the folder `area__TC`,
     `manual_capture.case_dir_name`), and that is the folder the code uses.
K5-4 the file beside the attempts changes nothing: `attempts_of`, the next `http` capture's attempt, `build`.
Mutation "another path in the text" (e.g. `seed-steps.md` moved to `work/seed/`): killed by K5-2 here.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_manual_capture as T  # noqa: E402  (its fixtures; main() runs only under __main__)
from harness import SCRIPTS, check, check_eq, check_in, finish  # noqa: E402

S, MC, M = T.S, T.MC, T.M
PACKAGE = Path(__file__).resolve().parents[2]
TEXTS = {"qa-runner.md": PACKAGE / "agents" / "qa-runner.md", "manual-evidence.md": PACKAGE / "references" / "manual-evidence.md"}
SEED_NAME = "seed-steps.md"
TEXT_PATH = re.compile(r"`(work/evidence/manual/<case>/" + re.escape(SEED_NAME) + r")`")
UNSEEDED_CASE = "area/TP1-1_TC_001"


def guard(project: Path, event: dict):
    """(exit code, stderr) of guard_pre_tool.py fed one PreToolUse event on stdin, as the host calls it."""
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), PYTHONDONTWRITEBYTECODE="1")
    payload = dict({"hook_event_name": "PreToolUse", "session_id": "t404-seed-0000-4000-000000000001",
                    "cwd": str(project)}, **event)
    proc = subprocess.run([sys.executable, "-B", str(SCRIPTS / "guard_pre_tool.py")], input=json.dumps(payload),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(project),
                          env=env, timeout=120)
    return proc.returncode, proc.stderr


def write_event(path: Path, role: str = "qa-factory:qa-runner") -> dict:
    return {"tool_name": "Write", "agent_type": role, "tool_input": {"file_path": str(path), "content": "x"}}


def k5_1_guard():
    t = S.make_task(manual=("api",))
    try:
        project = t.task.parents[2]
        case_dir = MC.case_root(t.task, UNSEEDED_CASE)
        seed = case_dir / SEED_NAME
        # the runner's own dispatch is open, as it is while the runner works; the plan is another role's artifact
        (t.task / "state").mkdir(exist_ok=True)
        (t.task / "state" / "controller.json").write_text(json.dumps(
            {"dispatches": {"S6-qa-runner-1": {"role": "qa-runner", "status": "running"}}, "stages": {}}), encoding="utf-8")
        code, err = guard(project, write_event(seed))
        check_eq("K5-1 the real guard lets qa-runner write the seed path (exit 0)", code, 0)
        code, err = guard(project, write_event(seed, role="qa-factory:qa-orchestrator"))
        check_eq("K5-1 the conductor (a role that is not qa-runner) is not refused either", code, 0)
        code, err = guard(project, write_event(t.task / "work" / "test-plan.md"))
        check_eq("K5-1 control of the same shape: work/test-plan.md written by qa-runner is refused (exit 2)", code, 2)
        check_in("K5-1 control: the refusal names the owner of the plan", "belongs to", err)
    finally:
        S.cleanup(t)


def k5_2_text_path():
    t = S.make_task(manual=("api",))
    try:
        case = T.API_CASE
        with t.patched():
            M.prepare_to_file(t.task, case, T.OBLIGATIONS[case])
        root = MC.case_root(t.task, case)
        request = root / "request.json"
        check("K5-2 the case folder holds request.json (prepare wrote it)", request.is_file())
        real = (root / SEED_NAME).relative_to(t.task).as_posix().replace(root.name, "<case>")
        for name, path in TEXTS.items():
            found = TEXT_PATH.findall(path.read_text(encoding="utf-8"))
            check_eq(f"K5-2 {name} names the seed path, once: the code's case folder + {SEED_NAME}", found, [real])
        text = " ".join(TEXTS["manual-evidence.md"].read_text(encoding="utf-8").split())   # line breaks folded
        check_in("K5-2 manual-evidence.md says the file sits beside request.json", "beside `request.json`", text)
        check_in("K5-2 manual-evidence.md says what `area/TC` is as a folder", "`area/TC` is `area__TC`", text)
        check_eq("K5-2 and that is what the code does", MC.case_dir_name("area/TC"), "area__TC")
    finally:
        S.cleanup(t)


def k5_4_beside_attempts():
    t = S.make_task(manual=("api",))
    try:
        case = T.API_CASE
        get, post = f"{T.LOCAL}/v1/workflows/w1", f"{T.LOCAL}/v1/workflows/w1/validate"
        http = S.FakeHttp({("POST", f"{T.LOCAL}/v1/local-auth/login"): S.ok_json({"access_token": S.TOKEN}),
                           ("GET", get): S.ok_json({"id": "w1"}), ("POST", post): S.ok_json({"valid": True})})
        T.seed_runtime_records(t)
        with t.patched():
            M.prepare_to_file(t.task, case, T.OBLIGATIONS[case])
        root = MC.case_root(t.task, case)
        (root / SEED_NAME).write_text("1. POST /v1/users --as default (create the user)\n2. a database step: named in words\n",
                                      encoding="utf-8")
        check_eq("K5-4 attempts_of lists no attempt for the seed file (no attempt yet)", MC.attempts_of(root), [])
        code, out, err = T.http_run(t, http, "--method", "GET", "--url", get, "--phase", "pre_action", "--as", "default")
        check_eq("K5-4 the next http capture runs (exit 0)", (code, err[:300]), (0, ""))
        check_eq("K5-4 ... and opens a1 beside the seed file", json.loads(out)["attempt"], "a1")
        code, out, err = T.http_run(t, http, "--method", "POST", "--url", post, "--proves", "completion",
                                    "--state-url", get, "--attempt", "a1", "--as", "default")
        check_eq("K5-4 a second call joins a1", code, 0)
        check_eq("K5-4 attempts_of still lists only a1", MC.attempts_of(root), ["a1"])
        code, out, err = T.build(t, case, "--result", "pass", "--actual", "seen", "--masked")
        check_eq("K5-4 build writes the record with the seed file beside the attempt (exit 0)", (code, err[:400]), (0, ""))
        check("K5-4 record.json is in a1 and the seed file is untouched", (root / "a1" / "record.json").is_file()
              and (root / SEED_NAME).read_text(encoding="utf-8").startswith("1. POST"))
    finally:
        S.cleanup(t)


def main():
    k5_1_guard()
    k5_2_text_path()
    k5_4_beside_attempts()
    finish("test_manual_seed_path")


if __name__ == "__main__":
    main()
