#!/usr/bin/env python3
"""controller.py --brief: a short answer for the conductor, the whole result in a file (speed-cost SC1-8 part A1, release 0.10.3).

TP1-12586: 33 controller calls put 157 311 characters into the conductor's context, `--operation rework` alone 109 675. Without the flag
the answer is byte for byte what it always was (the driver parses it, FR-14). With it, an answer over 1500 bytes is a summary: the keys the
conductor ACTS on whole, the rest as counts, the last line naming `state/output/controller-<operation>.json`, which holds the whole result.

Each check names the ONE mutation it kills:
  default byte-equal      the output without `--brief` changes (any byte), or `--brief` is read as on by default
  brief AT / BEYOND       the 1500-byte limit moves (`>=` for `>`), or is counted in characters instead of bytes
  always whole            `--brief` drops or shortens `next_action` / `next` / `window` / `error` / `problems` / `recorded` / ...
  summary shapes          a list / object / long string is printed whole, or the counts are wrong, or the 200 / 8 limits move
  file holds all          the file lacks a field the summary hides, or is not JSON
  pointer line            the last line names a path other than the one written, or an absolute path inside the project
  save failure            a file that cannot be written hides the result instead of printing it whole + the stderr line
  refusals unchanged      `--brief` changes a stderr refusal or its exit code
  briefed operations      `--brief` summarises an operation other than rework / checkpoint (prepare, next, gate-decision, ...): it hides keys the
                          conductor acts on (missing_facts, dispatch_request, options, decision), or the help promises more than it does
  ready commands          a rework / checkpoint command the code prints (a refusal door, a hint) ends without `--brief`; one site per anchor;
                          the same scan over the references / the phase files / SKILL.md
  one atomic writer       the file is written by a saver of its own instead of event_store.atomic_json
  last write wins         a second `--brief` of the same operation leaves the first result in the file
"""
import argparse
import contextlib
import io
import json
import os
import re
import sys
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_dir, temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import controller  # noqa: E402
from controller import Controller  # noqa: E402

E_ACUTE = "é"   # no Cyrillic in the package (FR-30): a non-ASCII value is an escape


def printed(result, brief: bool, root: Path, operation: str = "rework"):
    """`(stdout, stderr)` of `_print_result` for a result."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        controller._print_result(result, argparse.Namespace(brief=brief, operation=operation), root)
    return out.getvalue(), err.getvalue()


def whole_of(result) -> str:
    return json.dumps(result, ensure_ascii=False) + "\n"


def padded(size: int) -> dict:
    """A result whose one-line JSON is exactly `size` UTF-8 bytes."""
    base = len(json.dumps({"k": ""}, ensure_ascii=False).encode("utf-8"))
    return {"k": "a" * (size - base)}


project = temp_project("qa-brief-")
use_project(project)
story = project / "qa-factory" / "artifacts" / "TP3-1"
story.mkdir(parents=True)
Controller(story).apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                       "known_paths": {"root": str(story)}, "idempotency_key": "init"})
env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
out_file = story / "state" / "output" / "controller-rework.json"
try:
    # --- the default is untouched ------------------------------------------------------------------------------
    big = {"dispatched": True, "request": {"id": "S3-x-1", "text": "w" * 3000, "name": E_ACUTE}, "receipt": {"revision": 4},
           "next": "story_step.py materialize --task TP3-1 --dispatch-id S3-x-1"}
    out, err = printed(big, False, story)
    check_eq("default byte-equal: a result over the limit is the same single JSON line, no summary, no file",
             (out, err, out_file.exists()), (whole_of(big), "", False))
    out, _ = printed({"a": 1}, False, story)
    check_eq("default byte-equal: a small result too", out, '{"a": 1}\n')
    parsed = json.loads(printed(big, False, story)[0])
    check_eq("default byte-equal: non-ASCII stays UTF-8 (ensure_ascii=False)", parsed["request"]["name"], E_ACUTE)
    ap_help = run_script("controller.py", "--help", cwd=project, env=env).stdout
    check_in("--brief is documented in --help", "--brief", ap_help)
    check_in("--brief help names the file and the unchanged default", "state/output/controller-<operation>.json", ap_help)

    # --- AT / BEYOND 1500 bytes --------------------------------------------------------------------------------
    at = padded(controller.BRIEF_MAX_BYTES)
    out, err = printed(at, True, story)
    check_eq("brief AT 1500 bytes: the whole line, no file", (out, out_file.exists()), (whole_of(at), False))
    beyond = padded(controller.BRIEF_MAX_BYTES + 1)
    out, err = printed(beyond, True, story)
    check_eq("brief BEYOND (1501): a summary, not the whole line", (out == whole_of(beyond), out_file.is_file()), (False, True))
    wide = {"k": E_ACUTE * 800}   # 800 characters, 1600 bytes + the key: over the limit by BYTES
    out, _ = printed(wide, True, story)
    check_eq("brief counts bytes, not characters", out == whole_of(wide), False)
    out_file.unlink()

    # --- only the operations where the weight is are briefed (the verdict's A1-F1, the Lead's decision) ---------------------
    for op in controller.BRIEF_OPERATIONS:
        out, _ = printed(big, True, story, operation=op)
        check_eq(f"briefed: {op} over the limit is a summary", out == whole_of(big), False)
        (story / "state" / "output" / f"controller-{op}.json").unlink()
    # The shapes the verdict probed: prepare (missing_facts / resolved_paths), relaunch (dispatch_request), resolve_return (options,
    # digest), the gate-decision receipt (decision, read whole by s4.md and s8.md). Each key a summary would hide.
    hidden = {"missing_facts": ["a", "b"], "resolved_paths": {f"p{i}": "x" * 40 for i in range(9)},
              "dispatch_request": {"id": "S3-x-1", "prompt": "q" * 3000}, "options": ["one", "two", "three"], "digest": "d" * 1600,
              "decision": {"gate": "A", "words": "w" * 500}, "role": "qa-x", "reason": "r" * 400}
    for op in (o for o in controller.OPERATIONS if o not in controller.BRIEF_OPERATIONS):
        out, err = printed(hidden, True, story, operation=op)
        check_eq(f"other operations whole: {op} --brief is byte-equal to no flag, no file, nothing on stderr",
                 (out, err, (story / "state" / "output" / f"controller-{op}.json").exists()), (whole_of(hidden), "", False))
    check_in("--help says --brief is for rework and checkpoint only and the rest prints whole", "rework and checkpoint only", " ".join(ap_help.split()))
    check_in("--help: any other operation prints the whole result as without the flag", "Any other operation prints the whole result", " ".join(ap_help.split()))

    # --- the ready rework / checkpoint commands the code prints end with --brief (P3: code names the command) --------------
    door = controller.apply_door("checkpoint", story, "S4-x-1", {"S4-x-1": {"status": "running"}})
    check_in("ready commands: apply_door's checkpoint door, as printed", '--reason "<what it waits on>" --brief`', door)

    # The same scan over the texts and doors OUTSIDE controller.py that print a rework / checkpoint command with operands (SC1-8 tail, t-1335).
    # Bare mentions (no --stage / --dispatch / --reason after the name) are not commands to run and are not sites.
    # (the scripts that print such commands are not scanned for their text: a script's doors are read as behaviour)
    package = SCRIPTS.parent
    scanned = ("references/conductor-actions.json", "references/conductor.md", "references/controller-api.md",
               "skills/qa-story/phases/s0.md", "skills/qa-story/phases/s1.md", "skills/qa-story/phases/s4.md",
               "skills/qa-story/phases/s5.md", "skills/qa-story/phases/s7.md", "skills/qa-story/SKILL.md")

    def json_strings(value):
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [s for item in value.values() for s in json_strings(item)]
        if isinstance(value, list):
            return [s for item in value for s in json_strings(item)]
        return []

    def outside_sites(rel):
        raw = (package / rel).read_text(encoding="utf-8")
        if rel.endswith(".json"):
            texts = json_strings(json.loads(raw))
        else:
            texts = [" ".join(raw.split())]     # a wrapped command is one command
        return [(rel, *site) for text in texts for site in command_sites(text)]

    def command_sites(text):
        """`(command, carries --brief)` for each rework / checkpoint command with operands in a text; `--operation rework` or a
        backticked `rework --stage ...` (controller-api.md) opens one, the next backtick closes it. A flag NAMED without a value
        (SKILL.md: "via `--operation rework --reason`") is a mention, not a command: it has no operand."""
        return [(m.group(0), "--brief" in m.group(1)) for m in re.finditer(r"(?<!never )(?:--operation |`)(?:rework|checkpoint)\b([^`]*)", text)
                if re.search(r"--(?:stage|dispatch|reason)\s+[^\s`]", m.group(1))]

    found_outside = {rel: outside_sites(rel) for rel in scanned}
    check_eq("ready commands outside controller.py: no printed rework / checkpoint command lacks --brief",
             [site[:2] for sites_of in found_outside.values() for site in sites_of if not site[2]], [])

    # --- the keys the conductor acts on are whole ---------------------------------------------------------------
    action = {"action": "prepare_stage", "stage": "S4", "revision": 12, "dispatch_id": "S4-qa-case-designer-2"}
    result = {"next_action": action, "recorded": True, "window": {"open": ["TC-1"], "note": "n" * 400},
              "next": "story_step.py materialize --task TP3-1 --dispatch-id S4-x-2 " + "z" * 300,
              "error": "e" * 500, "problems": ["p" * 300, "q" * 300], "action": "relaunch", "stage": "S4",
              "dispatch_id": "S4-x-2", "dispatched": False, "filler": "f" * 3000}
    out, _ = printed(result, True, story)
    lines = out.splitlines()
    for key in controller.ALWAYS_WHOLE:
        check_in(f"always whole: {key} is the full JSON of its value", f"{key}: {json.dumps(result[key], ensure_ascii=False)}", lines)
    check_not_in("always whole: the filler is not in the summary", "ffffffffff", out)

    # --- the shapes of the rest ---------------------------------------------------------------------------------
    result = {"scalar_short": "x" * 200, "scalar_long": "y" * 201, "number": 7, "flag": False, "nothing": None,
              "items": list(range(30)), "few_keys": {"a": 1, "b": 2}, "many_keys": {f"k{i}": i for i in range(9)},
              "eight_keys": {f"k{i}": i for i in range(8)}, "request": {"id": "r", "pad": "p" * 3000}}
    lines = printed(result, True, story)[0].splitlines()
    check_in("shape: a scalar of 200 characters is shown", "scalar_short: " + json.dumps("x" * 200), lines)
    check_in("shape: a scalar of 201 characters is its length", "scalar_long: 201 chars", lines)
    check_in("shape: a number / a boolean / null by value", "number: 7", lines)
    check_in("shape: false", "flag: false", lines)
    check_in("shape: null", "nothing: null", lines)
    check_in("shape: a list is its count", "items: [30 items]", lines)
    check_in("shape: an object is its keys and their count", "few_keys: {a, b (2 keys)}", lines)
    check_in("shape: 8 keys are all shown", "eight_keys: {k0, k1, k2, k3, k4, k5, k6, k7 (8 keys)}", lines)
    check_in("shape: 9 keys show the first 8 and say there are more", "many_keys: {k0, k1, k2, k3, k4, k5, k6, k7, ... (9 keys)}", lines)
    check_in("shape: the request is its keys (a --build-only --brief summary)", "request: {id, pad (2 keys)}", lines)
    check_eq("shape: a list result is a count; a scalar result is itself",
             (controller._brief_result([1, 2, 3]), controller._brief_result("x")), (["result: [3 items]"], ['result: "x"']))

    # --- the file holds everything; the pointer names it -------------------------------------------------------------
    result = {"dispatched": True, "request": {"id": "S3-x-1", "text": "w" * 3000, "name": E_ACUTE}, "receipt": {"revision": 4}}
    out, err = printed(result, True, story)
    lines = out.splitlines()
    saved = out_file.read_text(encoding="utf-8") if out_file.is_file() else ""
    check_eq("file holds all: the saved JSON is the whole result", json.loads(saved or "null"), result)
    check_eq("pointer line: the last line, project-relative, with the file's byte count (the bytes on disk, whatever the platform's newline)",
             lines[-1], f"full result: qa-factory/artifacts/TP3-1/state/output/controller-rework.json ({out_file.stat().st_size} bytes)")
    check_eq("pointer line: nothing on stderr, no temp file left", (err, list(out_file.parent.glob("*.tmp"))), ("", []))
    spied = []
    with mock.patch.object(controller, "atomic_json", lambda path, value: spied.append((Path(path), value))):
        printed(result, True, story)
    check_eq("one atomic writer: the file is written by event_store.atomic_json (a unique temp name, the Windows retry), not a saver of its own",
             spied, [(out_file, result)])
    check_in("summary: the key the conductor acts on is above the pointer", "dispatched: true", lines[:-1])
    second = dict(result, receipt={"revision": 5}, request={"id": "S3-x-2", "text": "v" * 3000})
    printed(second, True, story)
    check_eq("last write wins: a second --brief replaces the file", json.loads(out_file.read_text(encoding="utf-8")), second)

    # a story folder outside the project: the path printed is the absolute one that exists (FR-37)
    outside = temp_dir("qa-brief-outside-")
    out, _ = printed(result, True, outside)
    check_eq("pointer line: outside the project, the absolute path", out.splitlines()[-1].split(" (")[0],
             f"full result: {outside / 'state' / 'output' / 'controller-rework.json'}")
    cleanup(outside)

    # --- a file that cannot be written ------------------------------------------------------------------------------
    out_file.unlink()
    (story / "state" / "output").rmdir()
    (story / "state" / "output").write_text("in the way", encoding="utf-8")
    out, err = printed(result, True, story)
    check_eq("save failure: the whole line is printed, as without the flag", out, whole_of(result))
    check_in("save failure: the stderr line says why and that it was printed whole",
             "controller: --brief could not save the full result (", err)
    check_in("save failure: ... printed whole", "); printed whole", err)
    (story / "state" / "output").unlink()

    # --- end to end through the real command line ----------------------------------------------------------------------
    real_next_action = Controller.next_action
    sys_argv = sys.argv
    big_action = {"action": "prepare_stage", "stage": "S2", "revision": 3, "filler": "f" * 4000}

    big_request = {"id": "S4-x-1", "role": "qa-case-designer", "filler": "f" * 4000}

    def main_with(operation, *flags):
        out, err = io.StringIO(), io.StringIO()
        sys.argv = ["controller.py", "--task-root", str(story), "--operation", operation, *flags]
        try:
            with mock.patch.object(Controller, "next_action", return_value=big_action), \
                    mock.patch.object(Controller, "build_checkpoint_request", return_value=big_request), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                controller.main()
        finally:
            sys.argv = sys_argv
        return out.getvalue(), err.getvalue()

    out, _ = main_with("next")
    check_eq("main next, no flag: the whole JSON line", out, whole_of(big_action))
    out_brief, _ = main_with("next", "--brief")
    check_eq("main next --brief: NOT a briefed operation - the same bytes as without the flag, no file",
             (out_brief, (story / "state" / "output" / "controller-next.json").exists()), (out, False))
    out, _ = main_with("checkpoint", "--build-only")
    check_eq("main checkpoint, no flag: the whole JSON line", out, whole_of({"recorded": False, "request": big_request}))
    out, _ = main_with("checkpoint", "--build-only", "--brief")
    check_in("main checkpoint --brief: recorded is whole", "recorded: false", out.splitlines())
    check_in("main checkpoint --brief: the request is its keys", "request: {id, role, filler (3 keys)}", out.splitlines())
    check_in("main checkpoint --brief: the pointer names the operation's file", "state/output/controller-checkpoint.json (", out.splitlines()[-1])
    check_not_in("main checkpoint --brief: the filler is not printed", "ffffffffff", out)
    check_eq("main checkpoint --brief: the file holds the filler too",
             json.loads((story / "state" / "output" / "controller-checkpoint.json").read_text(encoding="utf-8")),
             {"recorded": False, "request": big_request})

    # --- refusals are untouched -------------------------------------------------------------------------------------------
    plain = run_script("controller.py", "--task-root", story, "--operation", "no_such_operation", cwd=project, env=env)
    flagged = run_script("controller.py", "--task-root", story, "--operation", "no_such_operation", "--brief", cwd=project, env=env)
    check_eq("refusals unchanged: same exit code, same stderr, nothing on stdout with --brief",
             (flagged.returncode, flagged.stderr, flagged.stdout), (plain.returncode, plain.stderr, ""))
    check("refusals unchanged: the refusal is a refusal (exit 2)", plain.returncode == 2, str(plain.returncode))

    # a small real answer: --brief and no flag are byte-equal on the real command line, and --brief leaves no state/output
    a = run_script("controller.py", "--task-root", story, "--operation", "next", cwd=project, env=env)
    b = run_script("controller.py", "--task-root", story, "--operation", "next", "--brief", cwd=project, env=env)
    check_eq("small real answer: --brief prints it whole, byte for byte", (b.stdout, b.returncode), (a.stdout, 0))
    check("small real answer: the answer was under the limit (so this row proves the whole-line road)",
          len(a.stdout.strip().encode("utf-8")) <= controller.BRIEF_MAX_BYTES, str(len(a.stdout)))
finally:
    cleanup(project)

finish("test_controller_brief")
